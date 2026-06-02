# hpedb

```bash
# Install
poetry install

# Fetch article metadata (JOP, APSR, AJPS)
poetry run hpedb --from-year 2020 --mailto you@example.com

# Supplement missing abstracts from Semantic Scholar
poetry run hpedb-supplement

# Tests
poetry run pytest -m "not e2e"   # unit only
poetry run pytest                 # all (hits real APIs)

# Type check
poetry run mypy src/ tests/
```
