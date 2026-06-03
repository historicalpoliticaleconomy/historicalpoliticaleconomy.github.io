# hpedb

Pipeline for building a browsable database of Historical Political Economy replication datasets from peer-reviewed journal articles.

## Pipeline

```bash
poetry install
```

### 1. Fetch article metadata

Downloads article metadata from Crossref for JOP, APSR, AJPS, QJE, JPE, AER, and Econometrica.

```bash
poetry run hpedb --from-year 2000 --mailto hmm2198@columbia.edu
```

### 2. Classify HPE articles

Classifies each article as Historical Political Economy or not using an LLM. Adds period, region, and HPE flag to the database.

```bash
poetry run hpedb-classify --backend claude
```

### 3. Enrich with replication URLs

Looks up replication dataset URLs for HPE articles via Harvard Dataverse, Zenodo, Econometric Society article pages, and Crossref reference scanning.

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

Open `http://localhost:8000`. The heatmap shows dataset coverage by historical period and region; click any cell to filter.

## Development

```bash
poetry run pytest -m "not e2e"   # unit tests only
poetry run pytest                 # all tests (hits real APIs)
poetry run mypy src/ tests/
```
