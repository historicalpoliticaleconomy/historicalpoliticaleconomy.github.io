/**
 * Unit tests for pure app.js logic.
 * Run with: node --test tests/test_app_logic.mjs
 *
 * Functions are imported directly from docs/app.js (ES module).
 * buildGeo() is called with the real geo.json so the global Maps are populated.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  entryMatchesText, entryOverlapsBucket, entryMatchesKey,
  countsByRows, effectiveSubregionRows, countriesForSubregion,
  displayCountry, escapeHtml, formatPeriod, errorHref, cellColor,
  buildGeo,
  BUCKETS, COUNTRY_CANONICAL_SUBREGION,
} from '../docs/app.js';

// Populate global geo Maps from the shipped geo.json
const __filename = fileURLToPath(import.meta.url);
const __dirname  = dirname(__filename);
buildGeo(JSON.parse(readFileSync(join(__dirname, '../docs/geo.json'), 'utf8')));

// ── Fixtures (use real subregion/country names from geo.json) ─────────────────

const ENTRIES = [
  { doi: 'a', title: 'A', authors: '', regions: ['Western Europe'], countries: ['Germany'],       period_start: 1800, period_end: 1850 },
  { doi: 'b', title: 'B', authors: '', regions: ['Western Europe'], countries: ['France'],        period_start: 1700, period_end: 1799 },
  { doi: 'c', title: 'C', authors: '', regions: ['Eastern Europe'], countries: ['Poland'],        period_start: 1900, period_end: 1944 },
  { doi: 'd', title: 'D', authors: '', regions: ['South America'],  countries: ['Brazil'],        period_start: 1500, period_end: 1600 },
  { doi: 'e', title: 'E', authors: '', regions: ['Global/Comparative'], countries: [],            period_start: 1800, period_end: 1900 },
  { doi: 'f', title: 'F', authors: '', regions: ['Western Europe'], countries: ['Germany'],       period_start: null, period_end: null },
];

// applyFilters has DOM side effects — replicate the filtering logic for tests.
function filterEntries(data, selectedCell) {
  if (selectedCell === null) return data;
  const { rowKey, bi } = selectedCell;
  return data.filter(e =>
    entryMatchesKey(e, rowKey) &&
    (bi < 0 || entryOverlapsBucket(e, BUCKETS[bi]))
  );
}

// ── entryMatchesText ──────────────────────────────────────────────────────────

describe('entryMatchesText', () => {
  const entry = {
    title:       'The Rise of Prussia and the Junker Class',
    authors:     'HINTZE, O.; WEBER, M.',
    regions:     ['Eastern Europe'],
    countries:   ['Germany'],
    _continents: ['Europe'],
  };

  test('exact title substring matches', () => {
    assert.ok(entryMatchesText(entry, 'prussia'));
  });

  test('partial title word matches', () => {
    assert.ok(entryMatchesText(entry, 'pruss'));
  });

  test('author substring matches', () => {
    assert.ok(entryMatchesText(entry, 'hintze'));
  });

  test('region tag matches', () => {
    assert.ok(entryMatchesText(entry, 'eastern europe'));
  });

  test('country tag matches', () => {
    assert.ok(entryMatchesText(entry, 'germany'));
  });

  test('derived continent matches', () => {
    assert.ok(entryMatchesText(entry, 'europe'));
  });

  test('multi-term AND — all terms must match', () => {
    assert.ok(entryMatchesText(entry, 'prussia germany'));
  });

  test('multi-term AND — fails if one term absent', () => {
    assert.ok(!entryMatchesText(entry, 'prussia france'));
  });

  test('no false positive — unrelated term does not match', () => {
    assert.ok(!entryMatchesText(entry, 'louisiana'));
  });

  test('"prussia" does NOT match "suppressing"', () => {
    const louisiana = {
      title:       'Suppressing Black Votes: Voting Restrictions in Louisiana',
      authors:     'KEELE, L.; CUBBISON, W.',
      regions:     ['Northern America'],
      countries:   ['United States'],
      _continents: ['Americas'],
    };
    assert.ok(!entryMatchesText(louisiana, 'prussia'));
  });

  test('empty query matches everything', () => {
    assert.ok(entryMatchesText(entry, ''));
  });
});

// ── entryOverlapsBucket ───────────────────────────────────────────────────────

describe('entryOverlapsBucket', () => {
  test('fully within bucket', () => {
    assert.ok(entryOverlapsBucket({ period_start: 1810, period_end: 1840 }, BUCKETS[5])); // 1800–1849
  });

  test('straddles bucket boundary', () => {
    assert.ok(entryOverlapsBucket({ period_start: 1780, period_end: 1820 }, BUCKETS[5])); // 1800–1849
  });

  test('no overlap — before bucket', () => {
    assert.ok(!entryOverlapsBucket({ period_start: 1600, period_end: 1699 }, BUCKETS[5])); // 1800–1849
  });

  test('no overlap — after bucket', () => {
    assert.ok(!entryOverlapsBucket({ period_start: 1900, period_end: 1944 }, BUCKETS[5])); // 1800–1849
  });

  test('null period returns false', () => {
    assert.ok(!entryOverlapsBucket({ period_start: null, period_end: null }, BUCKETS[5]));
  });

  test('only period_start set — falls in bucket', () => {
    assert.ok(entryOverlapsBucket({ period_start: 1820, period_end: null }, BUCKETS[5]));
  });

  test('Pre-1000 bucket matches ancient entry', () => {
    assert.ok(entryOverlapsBucket({ period_start: -500, period_end: 500 }, BUCKETS[0]));
  });

  test('1945+ bucket is open-ended', () => {
    assert.ok(entryOverlapsBucket({ period_start: 1990, period_end: 2020 }, BUCKETS[8]));
  });
});

// ── entryMatchesKey ───────────────────────────────────────────────────────────

describe('entryMatchesKey', () => {
  test('Global/Comparative matches correctly', () => {
    assert.ok(entryMatchesKey(ENTRIES[4], 'Global/Comparative'));
    assert.ok(!entryMatchesKey(ENTRIES[0], 'Global/Comparative'));
  });

  test('continent key matches via subregion', () => {
    assert.ok(entryMatchesKey(ENTRIES[0], 'Europe'));   // Western Europe ∈ Europe
    assert.ok(entryMatchesKey(ENTRIES[2], 'Europe'));   // Eastern Europe ∈ Europe
    assert.ok(!entryMatchesKey(ENTRIES[3], 'Europe'));  // South America ∉ Europe
  });

  test('subregion key matches exactly', () => {
    assert.ok(entryMatchesKey(ENTRIES[0], 'Western Europe'));
    assert.ok(!entryMatchesKey(ENTRIES[0], 'Eastern Europe'));
  });

  test('country key matches via countries array', () => {
    assert.ok(entryMatchesKey(ENTRIES[0], 'Germany'));
    assert.ok(!entryMatchesKey(ENTRIES[0], 'France'));
  });
});

// ── filter logic (replaces applyFilters which has DOM side effects) ───────────

describe('applyFilters', () => {
  test('no selectedCell — returns all', () => {
    assert.equal(filterEntries(ENTRIES, null).length, ENTRIES.length);
  });

  test('selectedCell filters by region + bucket', () => {
    // Western Europe, bucket 5 (1800–1849) — should match entry a only
    const result = filterEntries(ENTRIES, { rowKey: 'Western Europe', bi: 5 });
    assert.equal(result.length, 1);
    assert.equal(result[0].doi, 'a');
  });

  test('selectedCell bi=-1 (Global/Comparative label click) — no bucket filter', () => {
    const result = filterEntries(ENTRIES, { rowKey: 'Global/Comparative', bi: -1 });
    assert.equal(result.length, 1);
    assert.equal(result[0].doi, 'e');
  });

  test('null-period entries pass when bi=-1 (no bucket filter)', () => {
    const result = filterEntries(ENTRIES, { rowKey: 'Europe', bi: -1 });
    const dois   = result.map(e => e.doi).sort();
    assert.deepEqual(dois, ['a', 'b', 'c', 'f']);
  });
});

// ── effectiveSubregionRows ────────────────────────────────────────────────────

describe('effectiveSubregionRows', () => {
  test('single active country → auto-expands to country row', () => {
    const data = [ENTRIES[0]]; // only Germany / Western Europe
    const { rows, autoExpanded } = effectiveSubregionRows('Europe', data);
    assert.ok(rows.includes('Germany'));
    assert.ok(autoExpanded.has('Germany'));
    assert.ok(!rows.includes('Western Europe'));
  });

  test('two active countries in same subregion → both inlined', () => {
    const data = [ENTRIES[0], ENTRIES[1]]; // Germany + France, both Western Europe
    const { rows, autoExpanded } = effectiveSubregionRows('Europe', data);
    assert.ok(rows.includes('Germany'));
    assert.ok(rows.includes('France'));
    assert.ok(autoExpanded.has('Germany'));
    assert.ok(autoExpanded.has('France'));
    assert.ok(!rows.includes('Western Europe'));
  });

  test('greedy: smaller subregion expands first; larger blocked when limit reached', () => {
    // Three European subregions; Western Europe (9 canonical countries) stays collapsed
    // because by the time smaller regions expand, totalRows would exceed 10.
    // NE(1) + EE(2) + WE(9): start=3; expand NE→3; expand EE→4; WE: 4+8=12>10 → blocked.
    const data = [
      { doi: 'ne1', title: '', authors: '', regions: ['Northern Europe'], countries: ['Norway'],  period_start: 1800, period_end: 1900 },
      { doi: 'ee1', title: '', authors: '', regions: ['Eastern Europe'],  countries: ['Poland'],  period_start: 1800, period_end: 1900 },
      { doi: 'ee2', title: '', authors: '', regions: ['Eastern Europe'],  countries: ['Hungary'], period_start: 1800, period_end: 1900 },
      ...['Germany', 'France', 'Austria', 'Belgium', 'Switzerland',
          'Netherlands', 'Luxembourg', 'Monaco', 'Liechtenstein'].map((c, i) => ({
        doi: `we${i}`, title: '', authors: '', regions: ['Western Europe'], countries: [c],
        period_start: 1800, period_end: 1900,
      })),
    ];
    const { rows, autoExpanded } = effectiveSubregionRows('Europe', data);
    // Smaller subregions auto-expand
    assert.ok(rows.includes('Norway'));
    assert.ok(autoExpanded.has('Norway'));
    assert.ok(rows.includes('Poland') && rows.includes('Hungary'));
    // Western Europe stays as subregion label (too many countries to expand)
    assert.ok(rows.includes('Western Europe'));
    assert.ok(!rows.includes('Germany'));
  });

  test('non-geo.json country (historical polity) appears in drill-down', () => {
    const data = [
      { doi: 'h', title: '', authors: '', regions: ['Eastern Europe'], countries: ['Prussia'],
        period_start: 1700, period_end: 1800 },
    ];
    const { rows, autoExpanded } = effectiveSubregionRows('Europe', data);
    assert.ok(rows.includes('Prussia'));
    assert.ok(autoExpanded.has('Prussia'));
    assert.ok(!rows.includes('Eastern Europe'));
  });

  test('anchor logic: non-canonical country placed in dominant canonical region only', () => {
    const entry = {
      doi: 'multi', title: '', authors: '',
      regions:   ['Caribbean', 'Eastern Europe'],
      countries: ['Cuba', 'Bulgaria', 'Poland', 'Romania', 'OldEmpire'],
      period_start: 1900, period_end: 1991,
    };
    const caribbean = countriesForSubregion('Caribbean',     [entry]);
    const easternEu = countriesForSubregion('Eastern Europe', [entry]);
    assert.ok(caribbean.includes('Cuba'));
    assert.ok(!caribbean.includes('OldEmpire'));
    assert.ok(easternEu.includes('Bulgaria') && easternEu.includes('Poland'));
    assert.ok(easternEu.includes('OldEmpire'));
    assert.ok(!easternEu.includes('Cuba'));
  });

  test('cross-contamination: country canonical to another subregion is excluded', () => {
    const data = [{
      doi: 'i', title: '', authors: '',
      regions:   ['Western Europe', 'Eastern Europe'],
      countries: ['Germany', 'Poland'],
      period_start: 1800, period_end: 1900,
    }];
    const weCountries = countriesForSubregion('Western Europe', data);
    assert.ok(weCountries.includes('Germany'));
    assert.ok(!weCountries.includes('Poland'));

    const eeCountries = countriesForSubregion('Eastern Europe', data);
    assert.ok(eeCountries.includes('Poland'));
    assert.ok(!eeCountries.includes('Germany'));
  });

  test('empty data → empty rows', () => {
    const { rows } = effectiveSubregionRows('Europe', []);
    assert.deepEqual(rows, []);
  });
});

// ── countsByRows ──────────────────────────────────────────────────────────────

describe('countsByRows', () => {
  test('counts Western Europe entries per bucket', () => {
    const rows   = ['Western Europe'];
    const counts = countsByRows(rows, ENTRIES);
    assert.equal(counts[0][4], 1); // bucket 4 (1700–1799): entry b
    assert.equal(counts[0][5], 1); // bucket 5 (1800–1849): entry a
    assert.equal(counts[0][6], 1); // bucket 6 (1850–1899): entry a straddles
    assert.equal(counts[0].reduce((s, c) => s + c, 0), 3);
  });

  test('counts reflect filtered data', () => {
    const filtered = ENTRIES.filter(e => e.period_start != null && e.period_start >= 1800);
    const counts   = countsByRows(['Western Europe'], filtered);
    assert.equal(counts[0][4], 0); // entry b (1700–1799) excluded
    assert.equal(counts[0][5], 1); // entry a (1800–1850) included
  });

  test('empty data gives all-zero counts', () => {
    const counts = countsByRows(['Western Europe', 'Eastern Europe'], []);
    assert.ok(counts.every(row => row.every(c => c === 0)));
  });
});

// ── displayCountry ────────────────────────────────────────────────────────────

describe('displayCountry', () => {
  test('ugly ISO name gets a display alias', () => {
    assert.equal(displayCountry('Congo, The Democratic Republic of the'), 'DR Congo');
  });

  test('normal name passes through unchanged', () => {
    assert.equal(displayCountry('France'), 'France');
  });

  test('another alias: Korea, Republic of', () => {
    assert.equal(displayCountry('Korea, Republic of'), 'South Korea');
  });
});

// ── escapeHtml ────────────────────────────────────────────────────────────────

describe('escapeHtml', () => {
  test('escapes <', () => assert.equal(escapeHtml('<b>'), '&lt;b&gt;'));
  test('escapes &', () => assert.equal(escapeHtml('a & b'), 'a &amp; b'));
  test('plain text unchanged', () => assert.equal(escapeHtml('hello'), 'hello'));
  test('falsy input returns empty string', () => assert.equal(escapeHtml(''), ''));
});

// ── formatPeriod ──────────────────────────────────────────────────────────────

describe('formatPeriod', () => {
  test('range',              () => assert.equal(formatPeriod(1800, 1900), '1800–1900'));
  test('same start and end', () => assert.equal(formatPeriod(1850, 1850), '1850'));
  test('start only',         () => assert.equal(formatPeriod(1800, null), '1800–?'));
  test('end only',           () => assert.equal(formatPeriod(null, 1900), '?–1900'));
  test('both null',          () => assert.equal(formatPeriod(null, null), null));
  test('BCE displayed as "N BCE"', () => assert.equal(formatPeriod(-500, 500), '500 BCE–500'));
});

// ── errorHref ─────────────────────────────────────────────────────────────────

describe('errorHref', () => {
  test('returns a GitHub issues URL', () => {
    const href = errorHref('10.1086/123');
    assert.ok(href.startsWith('https://github.com/'));
    assert.ok(href.includes('template=data-correction.yml'));
  });

  test('DOI is URL-encoded in query param', () => {
    const href = errorHref('10.1086/123');
    assert.ok(href.includes(`doi=${encodeURIComponent('10.1086/123')}`));
  });
});

// ── cellColor ─────────────────────────────────────────────────────────────────

describe('cellColor', () => {
  test('zero count → background colour (not transparent)', () => {
    const color = cellColor(0, 10);
    assert.equal(color, '#eef0f5');
  });

  test('positive count → rgb color string', () => {
    const color = cellColor(5, 10);
    assert.ok(color.startsWith('rgb('));
  });

  test('color scales monotonically with count', () => {
    // Higher count → lower blue channel value (darker / more saturated)
    const blueChannel = c => parseInt(c.match(/rgb\(\d+,\d+,(\d+)\)/)?.[1] ?? '999');
    const lo = blueChannel(cellColor(1, 10));
    const hi = blueChannel(cellColor(9, 10));
    assert.ok(hi < lo, 'higher count should produce lower blue channel (more saturated)');
  });
});
