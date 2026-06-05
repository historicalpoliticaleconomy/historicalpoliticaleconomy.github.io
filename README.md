# hpedb

Pipeline for building a browsable database of Historical Political Economy replication datasets from peer-reviewed journal articles.

## Pipeline

```bash
poetry install
```

1. **Fetch** — downloads article metadata from Crossref:
   ```bash
   poetry run hpedb --from-year 2000 --mailto your@email.address
   ```

2. **Classify** — tags articles as HPE using an LLM:
   ```bash
   poetry run hpedb-classify --backend claude
   ```

3. **Supplement** — fetches abstracts from Semantic Scholar:
   ```bash
   poetry run hpedb-supplement
   ```

4. **Enrich** — finds replication URLs:
   ```bash
   poetry run hpedb-enrich
   ```

5. **Override** — applies human corrections and additions from `overrides.json`:
   ```bash
   poetry run hpedb-overrides overrides.json
   ```

6. **Export** — writes `docs/data.json` for the website:
   ```bash
   poetry run hpedb-export
   ```

## Corrections and submissions

Use the GitHub issue forms to [report a data error](https://github.com/historicalpoliticaleconomy/historicalpoliticaleconomy.github.io/issues/new?template=data-correction.yml) or [add a dataset](https://github.com/historicalpoliticaleconomy/historicalpoliticaleconomy.github.io/issues/new?template=new-dataset.yml).

**Approving an issue (maintainers):** add the `approved` label. The workflow in `.github/workflows/apply-override.yml` parses the issue body, appends to `overrides.json`, reruns override + export, commits, and closes the issue.

To apply manually without the workflow:
```bash
echo "$ISSUE_BODY" | python scripts/parse_issue.py --type correction > /tmp/parsed.json
python scripts/apply_parsed.py /tmp/parsed.json correction
poetry run hpedb-overrides overrides.json && poetry run hpedb-export
```

## Website

```bash
cd docs && python -m http.server   # open http://localhost:8000
```

## Development

```bash
poetry run pytest -m "not e2e"   # unit tests (no API calls)
poetry run mypy src/ tests/
```
