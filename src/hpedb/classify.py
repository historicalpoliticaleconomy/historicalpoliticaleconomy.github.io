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
    "HPE = empirical research whose primary contribution is explaining why a specific "
    "historical outcome occurred, how a historical institution worked, or how a specific "
    "historical phenomenon persists into the present — where the finding is tied to the "
    "historical case itself. A paper that uses historical cases comparatively to establish "
    "a general behavioral regularity is NOT HPE, even if all cases are drawn from history.\n\n"
    "Sharpest test: remove the history and ask whether the finding survives. If yes, "
    "the history is illustrative and the paper is NOT HPE. If the finding disappears "
    "without the historical documentation, the paper IS HPE.\n\n"
    "YES HPE — direct historical study:\n"
    "  North & Weingast (1989) explain the Glorious Revolution specifically — remove "
    "the history and the finding disappears. Van Zanden et al. (2012) document European "
    "parliamentary development specifically. Aidt & Franck (2019) on the Great Reform "
    "Act of 1832; Chaney (2013) on economic shocks and Islamic political power in "
    "medieval Egypt; Wang (2022) on kinship networks and state-building in imperial China.\n\n"
    "YES HPE — persistence papers:\n"
    "  Nunn & Wantchekon (2011): the slave trade specifically caused mistrust in "
    "specific African regions — remove the historical documentation and there is no paper. "
    "Alesina, Giuliano & Nunn (2013) on plough use and gender roles; "
    "Valencia (2019) on Jesuit missions and human capital in South America; "
    "Becker & Woessmann (2009) on Protestant Reformation and literacy; "
    "Michalopoulos & Papaioannou (2013) on pre-colonial institutions and African development. "
    "Persistence papers satisfy the test because the claim is always 'X historical "
    "event/institution in Y places caused Z today' — the historical specificity is load-bearing.\n\n"
    "NOT HPE:\n"
    "  - Historical variable used only as an IV or control, with no substantive "
    "analysis of the historical variation itself.\n"
    "  - Large-N comparative surveys of historical cases used to establish a general "
    "behavioral or institutional regularity — e.g., that democratization typically "
    "results from elite miscalculation, or that civil wars generally follow resource "
    "shocks: the contribution is the generalization, not the historical documentation.\n"
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
    '                   Use [] only for Global/Comparative papers.\n\n'
    'Always return valid JSON. If no abstract is available, classify from the title alone. '
    'Never refuse or explain — return JSON regardless.'
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


# Common LLM aliases that pycountry.lookup() cannot resolve (renamed or missing common_name)
_COUNTRY_ALIASES: dict[str, str] = {
    "Turkey":                "Türkiye",
    "Russia":                "Russian Federation",
    "South Korea":           "Korea, Republic of",
    "North Korea":           "Korea, Democratic People's Republic of",
    "Iran":                  "Iran, Islamic Republic of",
    "Syria":                 "Syrian Arab Republic",
    "Vietnam":               "Viet Nam",
    "Ivory Coast":           "Côte d'Ivoire",
    "Cape Verde":            "Cabo Verde",
    "Swaziland":             "Eswatini",
    "Macedonia":             "North Macedonia",
    "Democratic Republic of the Congo": "Congo, The Democratic Republic of the",
    "DR Congo":              "Congo, The Democratic Republic of the",
    "DRC":                   "Congo, The Democratic Republic of the",
    "São Tomé and Príncipe": "Sao Tome and Principe",
    "The Gambia":            "Gambia",
    # Sub-national UK entities
    "England":               "United Kingdom",
    "Scotland":              "United Kingdom",
    "Wales":                 "United Kingdom",
    "Northern Ireland":      "United Kingdom",
    # Ecclesiastical / disputed / renamed
    "Vatican City":          "Holy See (Vatican City State)",
    "Palestine":             "Palestine, State of",
    # Note: 'United States of America' resolves via pycountry.lookup() (official_name match)
}

# M.49 region aliases for common model mis-namings
_REGION_ALIASES: dict[str, str] = {
    "Southern America": "South America",
    "North America":    "Northern America",
}


def _normalize_region(name: str) -> str:
    if name in VALID_REGIONS:
        return name
    return _REGION_ALIASES.get(name, name)


def _normalize_country(name: str) -> str:
    """Return the canonical pycountry short name, falling back to the original."""
    if _is_known_country(name):
        return name
    if name in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[name]
    try:
        return pycountry.countries.lookup(name).name
    except LookupError:
        return name


def _user_message(title: str, abstract: str | None) -> str:
    body = abstract if abstract is not None else "[No abstract; classify from title only]"
    return f"Title: {title}\nAbstract: {body}"



def _extract_json(raw: str) -> str:
    # Strip markdown code fences the model occasionally adds despite instructions
    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        stripped = "\n".join(inner)
    start, end = stripped.find("{"), stripped.rfind("}")
    return stripped[start : end + 1] if start != -1 and end != -1 else stripped


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
    normalized_regions = [_normalize_region(r) for r in raw_regions if isinstance(r, str)]
    regions = [r for r in normalized_regions if r in VALID_REGIONS]
    invalid_regions = [r for r in normalized_regions if r not in VALID_REGIONS]
    if invalid_regions:
        print(f"  [{doi}] Unrecognised regions (filtered): {invalid_regions}")

    raw_countries: Any = data.get("countries") or []
    if not isinstance(raw_countries, list):
        raw_countries = []
    countries = [_normalize_country(c) for c in raw_countries if isinstance(c, str) and c]
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
                "max_tokens": 512,
                "system": _SYSTEM_PROMPT,
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
                "max_tokens": 512,
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


def validate_prompt(
    conn: sqlite3.Connection,
    backend: Backend,
    model: str,
    api_key: str | None = None,
) -> None:
    from hpedb.validate import CASES

    dois = [c["doi"] for c in CASES]
    rows = conn.execute(
        f"SELECT doi, title, abstract FROM articles WHERE doi IN ({','.join('?'*len(dois))})",
        dois,
    ).fetchall()

    found: dict[str, tuple[str | None, str | None]] = {
        str(r[0]): (str(r[1]) if r[1] else None, str(r[2]) if r[2] else None)
        for r in rows
    }
    missing = [c for c in CASES if c["doi"] not in found]
    if missing:
        print(f"Warning: {len(missing)} case(s) not in DB (skipped):")
        for m in missing:
            print(f"  {m['doi']}  {m['label']}")

    articles: list[Article] = [
        (c["doi"], found[c["doi"]][0], found[c["doi"]][1])
        for c in CASES if c["doi"] in found
    ]

    run = _run_claude_batch if backend == "claude" else _run_openai_batch
    results = {r["doi"]: r for r in run(articles, model, api_key)}

    passed = failed = skipped = 0
    col = 46
    print(f"\n{'Case':<{col}} {'Expected':<10} {'Got':<10} Result")
    print("─" * (col + 32))
    for case in CASES:
        doi, label, exp = case["doi"], case["label"], case["expected_hpe"]
        if doi not in results:
            skipped += 1
            print(f"{label:<{col}} {'?':<10} {'(skip)':<10} SKIP")
            continue
        got = results[doi]["is_hpe"]
        ok  = got == exp
        passed += ok
        failed += not ok
        exp_s = "HPE" if exp else "not HPE"
        got_s = "HPE" if got else "not HPE"
        mark  = "PASS" if ok else "FAIL ✗"
        print(f"{label:<{col}} {exp_s:<10} {got_s:<10} {mark}")

    print(f"\n{passed} passed  {failed} failed  {skipped} skipped  (of {len(CASES)} cases)")


def fix_many_countries(conn: sqlite3.Connection, threshold: int = 25) -> int:
    """
    For classifications with more than `threshold` countries, clear countries
    and set region to Global/Comparative — these are comparative studies, not
    country-specific papers.
    """
    rows = conn.execute(
        "SELECT doi FROM classifications WHERE json_array_length(countries) > ?",
        (threshold,),
    ).fetchall()
    for (doi,) in rows:
        conn.execute(
            "UPDATE classifications SET countries = '[]', regions = ? WHERE doi = ?",
            (json.dumps(["Global/Comparative"]), str(doi)),
        )
    conn.commit()
    return len(rows)


def normalize_stored_countries(conn: sqlite3.Connection) -> int:
    """Re-normalize country names in all existing classifications in-place."""
    rows = conn.execute("SELECT doi, countries FROM classifications").fetchall()
    updated = 0
    for doi, countries_json in rows:
        original: list[str] = json.loads(countries_json or "[]")
        normalized = [_normalize_country(c) for c in original if isinstance(c, str)]
        if normalized != original:
            conn.execute(
                "UPDATE classifications SET countries = ? WHERE doi = ?",
                (json.dumps(normalized), str(doi)),
            )
            updated += 1
    conn.commit()
    return updated


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
    parser.add_argument("--backend", choices=["openai", "claude"],
                        help="Classification backend (required unless running a no-API migration command)")
    parser.add_argument("--model",   help="Override default model for the chosen backend")
    parser.add_argument("--db",      default="articles.db", metavar="PATH")
    parser.add_argument("--api-key", dest="api_key",
                        help="API key (falls back to OPENAI_API_KEY / ANTHROPIC_API_KEY env vars)")
    parser.add_argument("--fresh", action="store_true",
                        help="Reclassify already-classified articles")
    parser.add_argument("--normalize-countries", action="store_true",
                        help="Re-normalize country names in existing classifications (no API calls)")
    parser.add_argument("--fix-many-countries", action="store_true",
                        help="Set countries=[] and region=Global/Comparative for papers exceeding threshold (no API calls)")
    parser.add_argument("--country-threshold", type=int, default=25, metavar="N",
                        help="Country count threshold for --fix-many-countries (default: 25)")
    parser.add_argument("--validate", action="store_true",
                        help="Classify only the validation test cases and report pass/fail")
    args = parser.parse_args()

    conn = init_db(args.db)
    init_classifications(conn)

    if args.validate:
        if args.backend is None:
            parser.error("--backend is required with --validate")
        validate_prompt(conn, args.backend, args.model or _DEFAULT_MODELS[args.backend], api_key=args.api_key)
        conn.close()
        return

    if args.normalize_countries:
        n = normalize_stored_countries(conn)
        conn.close()
        print(f"Updated country names in {n} classifications.")
        return

    if args.fix_many_countries:
        n = fix_many_countries(conn, threshold=args.country_threshold)
        conn.close()
        print(f"Fixed {n} classifications with >{args.country_threshold} countries → Global/Comparative.")
        return

    if args.backend is None:
        parser.error("--backend is required unless running a no-API migration command")

    backend: Backend = args.backend
    model: str = args.model or _DEFAULT_MODELS[backend]
    n = classify_articles(conn, backend, model, api_key=args.api_key, fresh=args.fresh)
    conn.close()
    print(f"\nClassified {n} articles.")
