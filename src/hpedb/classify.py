import argparse
import io
import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Literal

import anthropic
import openai
import pycountry
from anthropic.types import TextBlock
from anthropic.types.messages.message_batch_succeeded_result import MessageBatchSucceededResult
from openai.types.chat import ChatCompletion

from hpedb.db import get_unclassified_dois, init_classifications, init_db, upsert_classification
from hpedb.types import ClassificationRecord

Backend = Literal["openai", "claude"]

VALID_REGIONS: frozenset[str] = frozenset({
    # UN M.49 sub-regions (https://unstats.un.org/unsd/methodology/m49/)
    "Northern Africa", "Eastern Africa", "Middle Africa", "Southern Africa", "Western Africa",
    "Northern America", "Caribbean", "Central America", "South America",
    "Central Asia", "Eastern Asia", "South-eastern Asia", "Southern Asia", "Western Asia",
    "Eastern Europe", "Northern Europe", "Southern Europe", "Western Europe",
    "Australia and New Zealand", "Melanesia", "Micronesia", "Polynesia",
    "Global/Comparative",
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
    "You are a political science researcher. Classify the article as Historical "
    "Political Economy (HPE) or not.\n\n"
    "HPE = empirical research that substantively analyzes a historical period, "
    "institution, or phenomenon. Persistence papers (historical variation explaining "
    "contemporary outcomes) count as HPE when the paper seriously documents the "
    "historical phenomenon itself — not merely uses it as an instrument.\n\n"
    "YES HPE — direct historical study:\n"
    "  North & Weingast (1989) on 17th-c. English fiscal institutions; "
    "Van Zanden et al. (2012) on European parliaments 1188–1789; "
    "Aidt & Franck (2019) on the Great Reform Act of 1832; "
    "Chaney (2013) on economic shocks and Islamic political power in medieval Egypt; "
    "Wang (2022) on kinship networks and state-building in imperial China.\n\n"
    "YES HPE — persistence papers:\n"
    "  Alesina, Giuliano & Nunn (2013) on plough use and gender roles; "
    "Nunn & Wantchekon (2011) on the slave trade and mistrust in Africa; "
    "Valencia (2019) on Jesuit missions and human capital in South America; "
    "Becker & Woessmann (2009) on Protestant Reformation and literacy; "
    "Michalopoulos & Papaioannou (2013) on pre-colonial institutions and African development.\n\n"
    "NOT HPE:\n"
    "  - Historical variable used only as an IV or control, with no substantive "
    "analysis of the historical variation itself.\n"
    "  - Experiments (field, lab, or survey), even with historical-sounding topics: "
    "e.g., Tannenwald-style studies of nuclear taboos with experimental evidence; "
    "field experiments on social contact and prejudice in contemporary settings.\n"
    "  - Theoretical or normative philosophy papers, even if drawing on historical "
    "thinkers or examples: e.g., papers reconstructing Dewey's theory of coercion, "
    "or normative debates about democratic citizenship.\n"
    "  - Contemporary electoral, behavioral, or opinion studies, even with long "
    "panel data: e.g., studies of partisan polarization, vote share, electoral fraud "
    "in recent decades, or cross-national partisanship activation — these study "
    "contemporary political behavior, not historical phenomena.\n"
    "  - Studies of contemporary outcomes (voting, public opinion, regime type) "
    "where historical data appear only as baseline controls.\n\n"
    "Return ONLY valid JSON:\n"
    '  "is_hpe"       – boolean\n'
    '  "period_start" – integer year or null (BCE = negative; null if not HPE)\n'
    '  "period_end"   – integer year or null\n'
    '  "regions"      – array of UN M.49 sub-regions the data covers; choose from:\n'
    '                   ["Northern Africa", "Eastern Africa", "Middle Africa",\n'
    '                    "Southern Africa", "Western Africa",\n'
    '                    "Northern America", "Caribbean", "Central America", "South America",\n'
    '                    "Central Asia", "Eastern Asia", "South-eastern Asia",\n'
    '                    "Southern Asia", "Western Asia",\n'
    '                    "Eastern Europe", "Northern Europe", "Southern Europe", "Western Europe",\n'
    '                    "Australia and New Zealand", "Melanesia", "Micronesia", "Polynesia",\n'
    '                    "Global/Comparative"]\n'
    '  "countries"    – array of ISO 3166-1 English short names for the geographic areas\n'
    '                   studied. Use the modern country name regardless of historical polity\n'
    '                   (Weimar/DDR era → "Germany"; British Raj era → "India").\n'
    '                   For dissolved multi-country states, list modern successors\n'
    '                   (Yugoslavia → "Serbia", "Croatia", "Slovenia", etc.).\n'
    '                   Use [] only for Global/Comparative papers.'
)

Article = tuple[str, str | None, str | None]  # (doi, title, abstract)

# Build a set of known country names from pycountry for warn-and-keep validation
_KNOWN_COUNTRIES: frozenset[str] = frozenset(
    name
    for c in pycountry.countries
    for name in ([c.name] + ([c.common_name] if hasattr(c, "common_name") else []))
)


def _is_known_country(name: str) -> bool:
    return name in _KNOWN_COUNTRIES


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
    invalid_regions = [r for r in raw_regions if isinstance(r, str) and r not in VALID_REGIONS]
    if invalid_regions:
        print(f"  [{doi}] Unrecognised regions (filtered): {invalid_regions}")

    raw_countries: Any = data.get("countries") or []
    if not isinstance(raw_countries, list):
        raw_countries = []
    countries = [c for c in raw_countries if isinstance(c, str) and c]
    unknown_countries = [c for c in countries if not _is_known_country(c)]
    if unknown_countries:
        print(f"  [{doi}] Unrecognised countries (kept): {unknown_countries}")

    return ClassificationRecord(
        doi=doi,
        is_hpe=bool(data.get("is_hpe", False)),
        period_start=int(period_start_raw) if isinstance(period_start_raw, int) else None,
        period_end=int(period_end_raw) if isinstance(period_end_raw, int) else None,
        regions=json.dumps(regions),
        countries=json.dumps(countries),
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
