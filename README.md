# hpedb

Pipeline for building a browsable database of Historical Political Economy replication datasets from peer-reviewed journal articles.

## Pipeline

```bash
poetry install
```

### 1. Fetch article metadata

Downloads article metadata from Crossref 

```bash
poetry run hpedb --from-year 2000 --mailto your@email.address
```

### 2. Classify HPE articles

```bash
poetry run hpedb-classify --backend claude
```

### 3. Enrich with replication URLs

```bash
poetry run hpedb-enrich
poetry run hpedb-enrich --verbose   # show per-article API results
poetry run hpedb-enrich --dry-run   # print URLs without writing to DB
poetry run hpedb-enrich --fresh     # re-lookup already-enriched articles
```

### 4. Export to JSON

Exports enriched HPE articles (those with replication URLs) to `docs/data.json` for the website.

```bash
poetry run hpedb-export
```

## Website

```bash
cd docs && python -m http.server
```

Open `http://localhost:8000`.

## Development

```bash
poetry run pytest -m "not e2e"   # unit tests only
poetry run pytest                 # all tests (hits real APIs)
poetry run mypy src/ tests/
```
