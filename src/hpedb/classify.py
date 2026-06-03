import argparse
import io
import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Literal

import anthropic
import openai
from anthropic.types import TextBlock
from anthropic.types.messages.message_batch_succeeded_result import MessageBatchSucceededResult
from openai.types.chat import ChatCompletion

from hpedb.db import get_unclassified_dois, init_classifications, init_db, upsert_classification
from hpedb.types import ClassificationRecord

Backend = Literal["openai", "claude"]

VALID_REGIONS: frozenset[str] = frozenset({
    "North America", "Latin America", "Western Europe", "Eastern Europe",
    "Middle East & North Africa", "Sub-Saharan Africa", "South Asia",
    "East Asia", "Southeast Asia", "Oceania", "Global/Comparative",
})

_DEFAULT_MODELS: dict[Backend, str] = {
    "openai": "gpt-4o-mini",
    "claude": "claude-haiku-4-5-20251001",
}

_POLL_INTERVAL = 30  # seconds between batch status polls

# HPE definition from: Charnysh, Finkel & Gehlbach (2023),
# "Historical Political Economy: Past, Present, and Future,"
# Annual Review of Political Science 26(1).
# DOI: 10.1146/annurev-polisci-051921-102440
_SYSTEM_PROMPT = (
    "You are a political science researcher. Classify the article below for the "
    "subfield of Historical Political Economy (HPE): research whose PRIMARY "
    "contribution is the extended analysis of a particular historical place and "
    "time — not merely the use of historical facts as instruments or controls for "
    "contemporary outcomes.\n\n"
    "An article IS HPE if the historical period itself is the object of study: "
    "state formation, historical elections and legislatures, colonial institutions "
    "and their direct operation (not just their modern legacy), labor coercion "
    "(slavery/serfdom), pre-industrial political economy, religion and early state "
    "building, land reform, historical conflict. Persistence papers count as HPE "
    "only when the historical period is analyzed in depth as the primary explanatory "
    "mechanism — e.g., documenting how and why a historical institution operated, "
    "not merely instrumenting a contemporary outcome with a historical fact.\n\n"
    "An article is NOT HPE if:\n"
    "  - It is a field experiment, survey experiment, or RCT, even in a "
    "historical-sounding context.\n"
    "  - It is a cross-national or cross-regional panel study whose main "
    "contribution is explaining contemporary political behavior (voting, "
    "legislative activity, public opinion, regime transitions after 1990) "
    "and historical data appear only as baseline controls.\n"
    "  - It studies long-run effects of a historical event but does not analyze "
    "the historical period itself — e.g., using a colonial-era border or "
    "institution as an instrument for a contemporary outcome without examining "
    "how or why that institution operated historically.\n"
    "  - It is primarily a theoretical or methodological contribution, even if "
    "motivated by historical examples.\n\n"
    "Return ONLY valid JSON with exactly these keys:\n"
    '  "is_hpe"       – boolean\n'
    '  "period_start" – integer year or null (historical period the DATA analyzes;\n'
    '                   null if is_hpe is false; negative for BCE)\n'
    '  "period_end"   – integer year or null (same; null if is_hpe is false)\n'
    '  "regions"      – array of strings (what the DATA covers); choose from:\n'
    '                   ["North America", "Latin America", "Western Europe",\n'
    '                    "Eastern Europe", "Middle East & North Africa",\n'
    '                    "Sub-Saharan Africa", "South Asia", "East Asia",\n'
    '                    "Southeast Asia", "Oceania", "Global/Comparative"]'
)

Article = tuple[str, str | None, str | None]  # (doi, title, abstract)


def _user_message(title: str, abstract: str | None) -> str:
    body = abstract if abstract is not None else "[No abstract; classify from title only]"
    return f"Title: {title}\nAbstract: {body}"



def _extract_json(raw: str) -> str:
    start, end = raw.find("{"), raw.rfind("}")
    return raw[start : end + 1] if start != -1 and end != -1 else raw


def parse_classification_response(
    raw: str, doi: str, backend: Backend, model: str,
) -> ClassificationRecord | None:
    try:
        data: Any = json.loads(_extract_json(raw))
    except json.JSONDecodeError as exc:
        print(f"  [{doi}] Invalid JSON ({exc}); raw: {raw[:120]!r}")
        return None

    if not isinstance(data, dict):
        print(f"  [{doi}] Expected JSON object, got {type(data).__name__}")
        return None

    if "is_hpe" not in data:
        print(f"  [{doi}] Missing 'is_hpe'; keys: {list(data.keys())}")

    period_start_raw = data.get("period_start")
    period_end_raw   = data.get("period_end")
    raw_regions: Any = data.get("regions") or []
    if not isinstance(raw_regions, list):
        raw_regions = []
    regions = [r for r in raw_regions if isinstance(r, str) and r in VALID_REGIONS]
    invalid = [r for r in raw_regions if isinstance(r, str) and r not in VALID_REGIONS]
    if invalid:
        print(f"  [{doi}] Filtered unrecognised regions: {invalid}")

    return ClassificationRecord(
        doi=doi,
        is_hpe=bool(data.get("is_hpe", False)),
        period_start=int(period_start_raw) if isinstance(period_start_raw, int) else None,
        period_end=int(period_end_raw) if isinstance(period_end_raw, int) else None,
        regions=json.dumps(regions),
        backend=backend,
        model=model,
        classified_at=datetime.now(timezone.utc).isoformat(),
    )


def _run_claude_batch(
    articles: list[Article], model: str, api_key: str | None,
) -> list[ClassificationRecord]:
    client = anthropic.Anthropic(api_key=api_key)
    doi_index = [doi for doi, _, _ in articles]

    # Anthropic custom_id must match ^[a-zA-Z0-9_-]{1,64}$; DOIs contain '/' and '.'
    requests = [
        {
            "custom_id": str(i),
            "params": {
                "model": model,
                "max_tokens": 256,
                "system": [{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": _user_message(title or "", abstract)}],
            },
        }
        for i, (_, title, abstract) in enumerate(articles)
    ]

    batch = client.messages.batches.create(requests=requests)  # type: ignore[arg-type]  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    print(f"Batch {batch.id} submitted ({len(articles)} articles). Polling every {_POLL_INTERVAL}s...", flush=True)

    while batch.processing_status == "in_progress":
        time.sleep(_POLL_INTERVAL)
        batch = client.messages.batches.retrieve(batch.id)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        c = batch.request_counts
        print(f"  {c.processing} processing / {c.succeeded} succeeded / {c.errored} errored", flush=True)

    if batch.processing_status != "ended":
        raise RuntimeError(f"Batch ended with unexpected status: {batch.processing_status}")

    records: list[ClassificationRecord] = []
    for result in client.messages.batches.results(batch.id):  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        doi = doi_index[int(result.custom_id)]
        if isinstance(result.result, MessageBatchSucceededResult):
            first = result.result.message.content[0] if result.result.message.content else None
            content = first.text if isinstance(first, TextBlock) else "{}"
            rec = parse_classification_response(content, doi, "claude", model)
            if rec is not None:
                records.append(rec)
            else:
                print(f"  [{doi}] Unparseable response; skipping (will retry next run).")
        else:
            print(f"  [{doi}] {result.result.type}; skipping (will retry next run).")
    return records


def _run_openai_batch(
    articles: list[Article], model: str, api_key: str | None,
) -> list[ClassificationRecord]:
    client = openai.OpenAI(api_key=api_key)
    doi_index = [doi for doi, _, _ in articles]

    jsonl = "\n".join(
        json.dumps({
            "custom_id": str(i),
            "method": "POST", "url": "/v1/chat/completions",
            "body": {
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": _user_message(title or "", abstract)},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 256,
            },
        })
        for i, (_, title, abstract) in enumerate(articles)
    ).encode()

    uploaded = client.files.create(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        file=("batch.jsonl", io.BytesIO(jsonl), "application/jsonl"), purpose="batch",
    )
    batch = client.batches.create(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        input_file_id=uploaded.id, endpoint="/v1/chat/completions", completion_window="24h",
    )
    print(f"Batch {batch.id} submitted ({len(articles)} articles). Polling every {_POLL_INTERVAL}s...", flush=True)

    while batch.status in {"validating", "in_progress", "finalizing"}:
        time.sleep(_POLL_INTERVAL)
        batch = client.batches.retrieve(batch.id)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        counts = batch.request_counts
        print(f"  {batch.status}: {counts.completed if counts else '?'}/{len(articles)} completed", flush=True)

    if batch.status != "completed":
        raise RuntimeError(f"Batch ended with unexpected status: {batch.status}")
    if batch.output_file_id is None:
        raise RuntimeError("Batch completed but output_file_id is None")

    raw = client.files.content(batch.output_file_id)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    records: list[ClassificationRecord] = []
    for line in raw.text.splitlines():
        if not line.strip():
            continue
        row: dict[str, Any] = json.loads(line)
        doi = doi_index[int(row["custom_id"])]
        if row.get("error"):
            print(f"  [{doi}] API error: {row['error']}; skipping (will retry next run).")
            continue
        try:
            text: str = row["response"]["body"]["choices"][0]["message"]["content"] or "{}"
        except (KeyError, IndexError, TypeError) as exc:
            print(f"  [{doi}] Malformed response ({exc}); skipping (will retry next run).")
            continue
        rec = parse_classification_response(text, doi, "openai", model)
        if rec is not None:
            records.append(rec)
    return records


def classify_articles(
    conn: sqlite3.Connection,
    backend: Backend,
    model: str,
    api_key: str | None = None,
    fresh: bool = False,
) -> int:
    init_classifications(conn)

    dois = (
        [str(r[0]) for r in conn.execute("SELECT doi FROM articles").fetchall()]
        if fresh
        else get_unclassified_dois(conn)
    )
    if not dois:
        print("Nothing to classify.")
        return 0

    articles: list[Article] = [
        (str(r[0]), str(r[1]) if r[1] is not None else None, str(r[2]) if r[2] is not None else None)
        for r in conn.execute(
            f"SELECT doi, title, abstract FROM articles WHERE doi IN ({','.join('?'*len(dois))})",
            dois,
        ).fetchall()
    ]

    run = _run_claude_batch if backend == "claude" else _run_openai_batch
    for rec in run(articles, model, api_key):
        upsert_classification(conn, rec)
    return len(articles)


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify articles as Historical Political Economy (HPE).")
    parser.add_argument("--backend", required=True, choices=["openai", "claude"])
    parser.add_argument("--model",   help="Override default model for the chosen backend")
    parser.add_argument("--db",      default="articles.db", metavar="PATH")
    parser.add_argument("--api-key", dest="api_key",
                        help="API key (falls back to OPENAI_API_KEY / ANTHROPIC_API_KEY env vars)")
    parser.add_argument("--fresh", action="store_true",
                        help="Reclassify already-classified articles")
    args = parser.parse_args()

    backend: Backend = args.backend
    model: str = args.model or _DEFAULT_MODELS[backend]

    conn = init_db(args.db)
    init_classifications(conn)
    n = classify_articles(conn, backend, model, api_key=args.api_key, fresh=args.fresh)
    conn.close()
    print(f"\nClassified {n} articles.")
