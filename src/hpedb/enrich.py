import argparse
import re
import sqlite3
import time
from typing import Any

import requests
from tqdm import tqdm

from hpedb.db import init_classifications, init_db, update_replication_url

_DATAVERSE_BASE = "https://dataverse.harvard.edu/api/search"
_ZENODO_BASE    = "https://zenodo.org/api/records"
_CROSSREF_BASE  = "https://api.crossref.org/works"

# Harvard Dataverse collection aliases per journal (None = global search)
_DATAVERSE_SUBTREE: dict[str, str | None] = {
    "APSR": "the_review",
    "AJPS": "ajps",
    "QJE":  "qje",
    "JOP":  None,
    "JPE":  None,
}

# Zenodo community slug per journal (None = no community filter)
_ZENODO_COMMUNITY: dict[str, str | None] = {
    "Econometrica": "es-replication-repository",
}

# Journals whose article pages on the publisher site may host replication data
# directly (used as fallback when Zenodo finds nothing)
_ES_FALLBACK: set[str] = {"Econometrica"}

# Matches any href pointing to a zip file — the ES site's standard supplement format
_ES_DATA_PATTERN = re.compile(r'href=["\'][^"\']*\.zip["\']', re.IGNORECASE)

# Matches DOIs from known replication repositories found in Crossref reference lists
_REPO_DOI_RE = re.compile(
    r'10\.7910/DVN/[A-Z0-9]+'  # Harvard Dataverse
    r'|10\.3886/[EI]\S+'        # openICPSR (E = AEA collection, I = ICPSR)
    r'|10\.5281/zenodo\.\d+',   # Zenodo
    re.IGNORECASE,
)

_RATE_LIMIT_PAUSE = 1.0

_ALL_SOURCES = set(_DATAVERSE_SUBTREE) | set(_ZENODO_COMMUNITY) | {"AER"}


def _dataverse_get(
    params: dict[str, Any], session: requests.Session,
) -> list[dict[str, Any]] | None:
    """Return items list, or None on network/HTTP error."""
    try:
        resp = session.get(_DATAVERSE_BASE, params=params, timeout=15)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    return list(resp.json().get("data", {}).get("items", []))


def _lookup_dataverse(
    doi: str, subtree: str | None, session: requests.Session,
    title: str | None = None, verbose: bool = False,
) -> str | None:
    # Step 1: field-specific query (works for APSR, AJPS — journals that populate publicationIDNumber)
    params: dict[str, Any] = {"q": f'publicationIDNumber:"{doi}"', "type": "dataset", "per_page": "5"}
    if subtree is not None:
        params["subtree"] = subtree
    items = _dataverse_get(params, session)
    if items is None:
        if verbose:
            tqdm.write(f"  [{doi}] request error on field query")
        return None
    if verbose:
        tqdm.write(f"  [{doi}] field query: {len(items)} result(s): {[it.get('name','?') for it in items]}")

    # Step 2: full-text DOI search within journal subtree (fallback for QJE and others that
    # store the DOI in citation text rather than the publicationIDNumber metadata field)
    if not items and subtree is not None:
        ft_params: dict[str, Any] = {"q": f'"{doi}"', "type": "dataset", "per_page": "5", "subtree": subtree}
        items = _dataverse_get(ft_params, session) or []
        if verbose and items:
            tqdm.write(f"  [{doi}] full-text fallback: {len(items)} result(s): {[it.get('name','?') for it in items]}")

    if len(items) == 1 and "url" in items[0]:
        return str(items[0]["url"])

    # Step 3: title search — universal last resort for any journal whose datasets
    # don't carry a machine-readable DOI field (notably JOP, JPE)
    if not items and title is not None:
        title_params: dict[str, Any] = {"q": f'"{title}"', "type": "dataset", "per_page": "5"}
        if subtree is not None:
            title_params["subtree"] = subtree
        items = _dataverse_get(title_params, session) or []
        if verbose:
            tqdm.write(f"  [{doi}] title fallback: {len(items)} result(s): {[it.get('name','?') for it in items]}")
        if len(items) == 1 and "url" in items[0]:
            return str(items[0]["url"])

    return None


def _lookup_crossref(
    doi: str, title: str | None, session: requests.Session, verbose: bool = False,
) -> str | None:
    try:
        resp = session.get(f"{_CROSSREF_BASE}/{doi}", timeout=15)
    except requests.RequestException:
        if verbose:
            tqdm.write(f"  [{doi}] Crossref: request error")
        return None
    if resp.status_code != 200:
        if verbose:
            tqdm.write(f"  [{doi}] Crossref: HTTP {resp.status_code}")
        return None

    refs = resp.json().get("message", {}).get("reference", [])
    candidates: list[tuple[str, str]] = []
    for r in refs:
        u = r.get("unstructured", "")
        m = _REPO_DOI_RE.search(u.replace(" ", ""))
        if m:
            candidates.append((m.group().rstrip(".,;"), u))

    if verbose:
        tqdm.write(f"  [{doi}] Crossref: {len(candidates)} repository reference(s)")

    if not candidates:
        return None
    if len(candidates) == 1:
        return f"https://doi.org/{candidates[0][0]}"

    # Multiple candidates: disambiguate by matching title tokens (≥6 chars)
    if title is not None:
        tokens = [w for w in re.split(r'\W+', title) if len(w) >= 6]
        for repo_doi, u in candidates:
            if any(tok.lower() in u.lower() for tok in tokens):
                if verbose:
                    tqdm.write(f"  [{doi}] Crossref: disambiguated via title token")
                return f"https://doi.org/{repo_doi}"

    if verbose:
        tqdm.write(f"  [{doi}] Crossref: {len(candidates)} ambiguous candidates, skipping")
    return None


def _lookup_zenodo(
    doi: str, community: str | None, session: requests.Session, verbose: bool = False,
) -> str | None:
    # Step 1: structured related-identifier search
    params: dict[str, Any] = {"q": f'related.identifier:"{doi}"', "size": 5}
    if community is not None:
        params["communities"] = community
    try:
        resp = session.get(_ZENODO_BASE, params=params, timeout=15)
    except requests.RequestException:
        if verbose:
            tqdm.write(f"  [{doi}] Zenodo request error on field query")
        return None
    if resp.status_code != 200:
        if verbose:
            tqdm.write(f"  [{doi}] Zenodo HTTP {resp.status_code}")
        return None
    hits: list[dict[str, Any]] = resp.json().get("hits", {}).get("hits", [])
    if verbose:
        titles = [h.get("metadata", {}).get("title", "?") for h in hits]
        tqdm.write(f"  [{doi}] Zenodo field query: {len(hits)} result(s): {titles}")

    # Step 2: full-text fallback
    if not hits:
        ft_params: dict[str, Any] = {"q": f'"{doi}"', "size": 5}
        if community is not None:
            ft_params["communities"] = community
        try:
            ft_resp = session.get(_ZENODO_BASE, params=ft_params, timeout=15)
        except requests.RequestException:
            return None
        if ft_resp.status_code == 200:
            hits = ft_resp.json().get("hits", {}).get("hits", [])
            if verbose and hits:
                titles = [h.get("metadata", {}).get("title", "?") for h in hits]
                tqdm.write(f"  [{doi}] Zenodo full-text fallback: {len(hits)} result(s): {titles}")

    if len(hits) == 1:
        return str(hits[0]["links"]["html"])
    return None


def _lookup_es_page(
    doi: str, session: requests.Session, verbose: bool = False,
) -> str | None:
    try:
        resp = session.get(f"https://doi.org/{doi}", allow_redirects=True, timeout=15)
    except requests.RequestException:
        if verbose:
            tqdm.write(f"  [{doi}] ES page: request error")
        return None
    if resp.status_code != 200:
        if verbose:
            tqdm.write(f"  [{doi}] ES page: HTTP {resp.status_code}")
        return None
    if "econometricsociety.org" not in resp.url:
        if verbose:
            tqdm.write(f"  [{doi}] ES page: resolved to non-ES URL {resp.url}")
        return None
    if _ES_DATA_PATTERN.search(resp.text):
        if verbose:
            tqdm.write(f"  [{doi}] ES page: found data link at {resp.url}")
        return str(resp.url)
    if verbose:
        tqdm.write(f"  [{doi}] ES page: no data link at {resp.url}")
    return None


def _lookup(
    doi: str, journal: str, session: requests.Session,
    title: str | None = None, verbose: bool = False,
) -> str | None:
    url: str | None = None
    if journal in _DATAVERSE_SUBTREE:
        url = _lookup_dataverse(doi, _DATAVERSE_SUBTREE[journal], session, title=title, verbose=verbose)
    if url is None and journal in _ZENODO_COMMUNITY:
        url = _lookup_zenodo(doi, _ZENODO_COMMUNITY[journal], session, verbose=verbose)
    if url is None and journal in _ES_FALLBACK:
        url = _lookup_es_page(doi, session, verbose=verbose)
    if url is None:
        url = _lookup_crossref(doi, title, session, verbose=verbose)
    return url


def enrich_replication_urls(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    fresh: bool = False,
    verbose: bool = False,
) -> tuple[int, int]:
    where = (
        "c.is_hpe = 1"
        if fresh
        else "c.is_hpe = 1 AND c.replication_url IS NULL"
    )
    rows: list[tuple[str, str, str | None]] = [
        (str(r[0]), str(r[1]), str(r[2]) if r[2] else None)
        for r in conn.execute(
            f"SELECT a.doi, a.journal, a.title FROM articles a JOIN classifications c ON c.doi = a.doi WHERE {where}"
        ).fetchall()
    ]

    found = 0
    with requests.Session() as session:
        for doi, journal, title in tqdm(rows, unit="article"):
            if journal not in _ALL_SOURCES:
                if verbose:
                    tqdm.write(f"  [{doi}] journal={journal}: no source configured; skipping")
                time.sleep(_RATE_LIMIT_PAUSE)
                continue
            url = _lookup(doi, journal, session, title=title, verbose=verbose)
            if url is not None:
                found += 1
                tqdm.write(f"  [{doi}] found: {url}")
                if not dry_run:
                    update_replication_url(conn, doi, url)
            time.sleep(_RATE_LIMIT_PAUSE)

    return found, len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich HPE classifications with replication dataset URLs."
    )
    parser.add_argument("--db",      default="articles.db", metavar="PATH")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print found URLs without writing to DB")
    parser.add_argument("--fresh",   action="store_true",
                        help="Re-lookup all HPE articles, not just those missing a URL")
    parser.add_argument("--verbose", action="store_true",
                        help="Print each API result (hits, misses, errors)")
    args = parser.parse_args()

    conn = init_db(args.db)
    init_classifications(conn)
    print("Enriching replication URLs from Harvard Dataverse, openICPSR, Zenodo, and publisher pages...")
    found, total = enrich_replication_urls(
        conn, dry_run=args.dry_run, fresh=args.fresh, verbose=args.verbose,
    )
    conn.close()
    print(f"\nDone. Found replication URLs for {found}/{total} HPE articles.")
