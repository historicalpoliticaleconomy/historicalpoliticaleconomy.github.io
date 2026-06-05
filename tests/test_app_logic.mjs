/**
 * Unit tests for pure app.js logic.
 * Run with: node --test tests/test_app_logic.mjs
 *
 * These tests duplicate the relevant pure functions from app.js so they can
 * run in Node without a DOM. Any logic change in app.js must be mirrored here.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

// ── Replicated pure functions ─────────────────────────────────────────────────

const BUCKETS = [
  { label: 'Pre-1000',  start: -Infinity, end: 999   },
  { label: '1000–1499', start: 1000,      end: 1499  },
  { label: '1500–1599', start: 1500,      end: 1599  },
  { label: '1600–1699', start: 1600,      end: 1699  },
  { label: '1700–1799', start: 1700,      end: 1799  },
  { label: '1800–1849', start: 1800,      end: 1849  },
  { label: '1850–1899', start: 1850,      end: 1899  },
  { label: '1900–1944', start: 1900,      end: 1944  },
  { label: '1945+',     start: 1945,      end: Infinity },
];

function entryOverlapsBucket(entry, bucket) {
  const ps = entry.period_start ?? entry.period_end;
  const pe = entry.period_end   ?? entry.period_start;
  if (ps == null) return false;
  return ps <= bucket.end && pe >= bucket.start;
}


// Minimal geo mock for entryMatchesKey
const MOCK_CONTINENT_SUBREGIONS = new Map([
  ['Europe', ['Western Europe', 'Eastern Europe']],
  ['Americas', ['South America', 'Northern America']],
]);
const MOCK_SUBREGION_COUNTRIES = new Map([
  ['Western Europe', ['Germany', 'France', 'United Kingdom']],
  ['Eastern Europe', ['Poland', 'Hungary']],
  ['South America',  ['Brazil', 'Argentina']],
]);

function entryMatchesKey(entry, key, continentSubregions, subregionCountries) {
  if (key === 'Global/Comparative') return entry.regions.includes('Global/Comparative');
  if (continentSubregions.has(key)) {
    const subs = continentSubregions.get(key) || [];
    return subs.some(s => entry.regions.includes(s));
  }
  if (subregionCountries.has(key)) return entry.regions.includes(key);
  return (entry.countries || []).includes(key);
}

function applyFilters(allData, selectedCell) {
  if (selectedCell === null) return allData;
  const { rowKey, bi } = selectedCell;
  return allData.filter(entry =>
    entryMatchesKey(entry, rowKey, MOCK_CONTINENT_SUBREGIONS, MOCK_SUBREGION_COUNTRIES) &&
    (bi < 0 || entryOverlapsBucket(entry, BUCKETS[bi]))
  );
}

function countsByRows(rows, data, continentSubregions, subregionCountries) {
  const counts = rows.map(() => BUCKETS.map(() => 0));
  for (const entry of data) {
    BUCKETS.forEach((b, bi) => {
      if (!entryOverlapsBucket(entry, b)) return;
      rows.forEach((key, ri) => {
        if (entryMatchesKey(entry, key, continentSubregions, subregionCountries)) counts[ri][bi]++;
      });
    });
  }
  return counts;
}

// ── Fixtures ──────────────────────────────────────────────────────────────────

const ENTRIES = [
  { doi: 'a', regions: ['Western Europe'], countries: ['Germany'],       period_start: 1800, period_end: 1850 },
  { doi: 'b', regions: ['Western Europe'], countries: ['France'],        period_start: 1700, period_end: 1799 },
  { doi: 'c', regions: ['Eastern Europe'], countries: ['Poland'],        period_start: 1900, period_end: 1944 },
  { doi: 'd', regions: ['South America'],  countries: ['Brazil'],        period_start: 1500, period_end: 1600 },
  { doi: 'e', regions: ['Global/Comparative'], countries: [],            period_start: 1800, period_end: 1900 },
  { doi: 'f', regions: ['Western Europe'], countries: ['Germany'],       period_start: null, period_end: null },
];

// ── Replicated entryMatchesText ───────────────────────────────────────────────

function entryMatchesText(entry, query) {
  const terms    = query.toLowerCase().split(/\s+/).filter(Boolean);
  const haystack = [
    entry.title    || '',
    entry.authors  || '',
    ...(entry.regions    || []),
    ...(entry.countries  || []),
    ...(entry._continents || []),
  ].join(' ').toLowerCase();
  return terms.every(t => haystack.includes(t));
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
    // empty query → no terms → every([]) = true
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
  const match = (entry, key) =>
    entryMatchesKey(entry, key, MOCK_CONTINENT_SUBREGIONS, MOCK_SUBREGION_COUNTRIES);

  test('Global/Comparative matches correctly', () => {
    assert.ok(match(ENTRIES[4], 'Global/Comparative'));
    assert.ok(!match(ENTRIES[0], 'Global/Comparative'));
  });

  test('continent key matches via subregion', () => {
    assert.ok(match(ENTRIES[0], 'Europe'));  // Western Europe ∈ Europe
    assert.ok(match(ENTRIES[2], 'Europe'));  // Eastern Europe ∈ Europe
    assert.ok(!match(ENTRIES[3], 'Europe')); // South America ∉ Europe
  });

  test('subregion key matches exactly', () => {
    assert.ok(match(ENTRIES[0], 'Western Europe'));
    assert.ok(!match(ENTRIES[0], 'Eastern Europe'));
  });

  test('country key matches via countries array', () => {
    assert.ok(match(ENTRIES[0], 'Germany'));
    assert.ok(!match(ENTRIES[0], 'France'));
  });
});

// ── applyFilters (without Fuse.js) ────────────────────────────────────────────

describe('applyFilters', () => {
  test('no selectedCell — returns all', () => {
    const result = applyFilters(ENTRIES, null);
    assert.equal(result.length, ENTRIES.length);
  });

  test('selectedCell filters by region + bucket', () => {
    // Western Europe, bucket 5 (1800–1849) — should match entry a only
    const result = applyFilters(ENTRIES, { rowKey: 'Western Europe', bi: 5 });
    assert.equal(result.length, 1);
    assert.equal(result[0].doi, 'a');
  });

  test('selectedCell bi=-1 (Global/Comparative label click) — no bucket filter', () => {
    const result = applyFilters(ENTRIES, { rowKey: 'Global/Comparative', bi: -1 });
    assert.equal(result.length, 1);
    assert.equal(result[0].doi, 'e');
  });

  test('null-period entries pass when bi=-1 (no bucket filter)', () => {
    const result = applyFilters(ENTRIES, { rowKey: 'Europe', bi: -1 });
    const dois = result.map(e => e.doi).sort();
    // a, b, c, f are European; d is South America; e is Global/Comparative
    assert.deepEqual(dois, ['a', 'b', 'c', 'f']);
  });
});

// ── effectiveSubregionRows ────────────────────────────────────────────────────

function countriesForSubregion(sub, data, countryCanonicalSubregion) {
  return [...new Set(
    data
      .filter(e => e.regions.includes(sub))
      .flatMap(e => {
        const regions   = e.regions   || [];
        const countries = e.countries || [];

        let anchorRegions;
        if (regions.length <= 1) {
          anchorRegions = new Set(regions);
        } else {
          const counts = regions.map(r => ({
            r, n: countries.filter(c => countryCanonicalSubregion.get(c) === r).length,
          }));
          const max = Math.max(...counts.map(x => x.n));
          anchorRegions = new Set(
            max === 0 ? regions : counts.filter(x => x.n === max).map(x => x.r)
          );
        }

        return countries.filter(c => {
          if (!c) return false;
          const canonical = countryCanonicalSubregion.get(c);
          return canonical ? canonical === sub : anchorRegions.has(sub);
        });
      })
  )];
}

function effectiveSubregionRows(continent, data, continentSubregions, subregionCountries) {
  // Build canonical map from the provided subregionCountries mock
  const countryCanonicalSubregion = new Map();
  for (const [sub, countries] of subregionCountries) {
    for (const c of countries) countryCanonicalSubregion.set(c, sub);
  }

  const rows         = [];
  const autoExpanded = new Set();

  const subregionData = [];
  for (const sub of (continentSubregions.get(continent) || [])) {
    if (!data.some(e => entryMatchesKey(e, sub, continentSubregions, subregionCountries))) continue;
    const activeCountries = countriesForSubregion(sub, data, countryCanonicalSubregion);
    subregionData.push({ sub, activeCountries });
  }

  let totalRows = subregionData.length;
  const expanded = new Set();
  const bySize = [...subregionData]
    .filter(d => d.activeCountries.length > 0)
    .sort((a, b) => a.activeCountries.length - b.activeCountries.length);

  for (const { sub, activeCountries } of bySize) {
    if (totalRows + (activeCountries.length - 1) <= 10) {
      expanded.add(sub);
      totalRows += activeCountries.length - 1;
    }
  }

  for (const { sub, activeCountries } of subregionData) {
    if (expanded.has(sub)) {
      for (const c of activeCountries) { rows.push(c); autoExpanded.add(c); }
    } else {
      rows.push(sub);
    }
  }

  return { rows, autoExpanded };
}

describe('effectiveSubregionRows', () => {
  test('single active country → auto-expands to country row', () => {
    const data = [ENTRIES[0]]; // only Germany / Western Europe
    const { rows, autoExpanded } = effectiveSubregionRows(
      'Europe', data, MOCK_CONTINENT_SUBREGIONS, MOCK_SUBREGION_COUNTRIES
    );
    assert.deepEqual(rows, ['Germany']);
    assert.ok(autoExpanded.has('Germany'));
  });

  test('two active countries in same subregion → both inlined', () => {
    const data = [ENTRIES[0], ENTRIES[1]]; // Germany + France, both Western Europe
    const { rows, autoExpanded } = effectiveSubregionRows(
      'Europe', data, MOCK_CONTINENT_SUBREGIONS, MOCK_SUBREGION_COUNTRIES
    );
    assert.ok(rows.includes('Germany'));
    assert.ok(rows.includes('France'));
    assert.ok(autoExpanded.has('Germany'));
    assert.ok(autoExpanded.has('France'));
    assert.ok(!rows.includes('Western Europe'));
  });

  test('greedy: smaller subregion expands first; larger blocked when limit reached', () => {
    // SmallSub has 2 countries, BigSub has 10 — start totalRows=2.
    // Expanding SmallSub: delta=1 → 3 ≤ 10 → expand.
    // Expanding BigSub: delta=9 → 12 > 10 → blocked.
    const bigSubCountries = Array.from({ length: 10 }, (_, i) => `Country${i + 1}`);
    const localSubregionCountries  = new Map([['SmallSub', ['A', 'B']], ['BigSub', bigSubCountries]]);
    const localContinentSubregions = new Map([['TestContinent', ['SmallSub', 'BigSub']]]);
    const data = [
      { doi: 'x1', regions: ['SmallSub'], countries: ['A'], period_start: 1800, period_end: 1900 },
      { doi: 'x2', regions: ['SmallSub'], countries: ['B'], period_start: 1800, period_end: 1900 },
      ...bigSubCountries.map((c, i) => ({
        doi: `z${i}`, regions: ['BigSub'], countries: [c], period_start: 1800, period_end: 1900,
      })),
    ];
    const { rows, autoExpanded } = effectiveSubregionRows(
      'TestContinent', data, localContinentSubregions, localSubregionCountries
    );
    assert.ok(rows.includes('A') && rows.includes('B'));
    assert.ok(autoExpanded.has('A') && autoExpanded.has('B'));
    assert.ok(rows.includes('BigSub'));
    assert.ok(!rows.includes('SmallSub'));
    assert.equal(rows.length, 3); // A, B, BigSub
  });

  test('non-geo.json country (e.g. historical polity) appears in drill-down', () => {
    // "Prussia" is not in any geo.json subregion list, so it has no canonical subregion.
    // It should still appear in the Eastern Europe drill-down because it's not
    // canonical to any *other* subregion either.
    const data = [
      { doi: 'h', regions: ['Eastern Europe'], countries: ['Prussia'], period_start: 1700, period_end: 1800 },
    ];
    const { rows, autoExpanded } = effectiveSubregionRows(
      'Europe', data, MOCK_CONTINENT_SUBREGIONS, MOCK_SUBREGION_COUNTRIES
    );
    assert.ok(rows.includes('Prussia'));
    assert.ok(autoExpanded.has('Prussia'));
    assert.ok(!rows.includes('Eastern Europe'));
  });

  test('anchor logic: non-canonical country placed in dominant canonical region only', () => {
    // Paper spans Caribbean + Eastern Europe. Eastern Europe has 3 canonical countries,
    // Caribbean has 1. "OldEmpire" (non-canonical) anchors to Eastern Europe only.
    const localSubregionCountries = new Map([
      ['Caribbean',    ['Cuba']],
      ['Eastern Europe', ['Bulgaria', 'Poland', 'Romania']],
    ]);
    const localContinentSubregions = new Map([
      ['TestContinent', ['Caribbean', 'Eastern Europe']],
    ]);
    const canonMap = new Map();
    for (const [s, cs] of localSubregionCountries) for (const c of cs) canonMap.set(c, s);

    const entry = {
      doi: 'multi',
      regions: ['Caribbean', 'Eastern Europe'],
      countries: ['Cuba', 'Bulgaria', 'Poland', 'Romania', 'OldEmpire'],
      period_start: 1900, period_end: 1991,
    };

    const caribbean  = countriesForSubregion('Caribbean',     [entry], canonMap);
    const easternEu  = countriesForSubregion('Eastern Europe', [entry], canonMap);

    // Cuba in Caribbean; OldEmpire anchors to Eastern Europe (dominant canonical region)
    assert.ok(caribbean.includes('Cuba'));
    assert.ok(!caribbean.includes('OldEmpire'));
    assert.ok(easternEu.includes('Bulgaria') && easternEu.includes('Poland') && easternEu.includes('Romania'));
    assert.ok(easternEu.includes('OldEmpire'));
    assert.ok(!easternEu.includes('Cuba'));
  });

  test('cross-contamination: country canonical to another subregion is excluded', () => {
    // A paper tagged Western Europe + Eastern Europe with Germany (Western) and Poland (Eastern).
    // Each should only appear under its own subregion, not bleed across.
    const data = [
      {
        doi: 'i',
        regions: ['Western Europe', 'Eastern Europe'],
        countries: ['Germany', 'Poland'],
        period_start: 1800, period_end: 1900,
      },
    ];
    // Western Europe drill-down: Germany shown, Poland excluded (canonical Eastern Europe)
    const weCountries = countriesForSubregion(
      'Western Europe', data,
      (() => { const m = new Map(); for (const [s, cs] of MOCK_SUBREGION_COUNTRIES) for (const c of cs) m.set(c, s); return m; })()
    );
    assert.ok(weCountries.includes('Germany'));
    assert.ok(!weCountries.includes('Poland'));

    // Eastern Europe drill-down: Poland shown, Germany excluded (canonical Western Europe)
    const eeCountries = countriesForSubregion(
      'Eastern Europe', data,
      (() => { const m = new Map(); for (const [s, cs] of MOCK_SUBREGION_COUNTRIES) for (const c of cs) m.set(c, s); return m; })()
    );
    assert.ok(eeCountries.includes('Poland'));
    assert.ok(!eeCountries.includes('Germany'));
  });

  test('empty data → empty rows', () => {
    const { rows } = effectiveSubregionRows(
      'Europe', [], MOCK_CONTINENT_SUBREGIONS, MOCK_SUBREGION_COUNTRIES
    );
    assert.deepEqual(rows, []);
  });
});

// ── countsByRows ──────────────────────────────────────────────────────────────

describe('countsByRows', () => {
  test('counts Western Europe entries per bucket', () => {
    const rows   = ['Western Europe'];
    const counts = countsByRows(rows, ENTRIES, MOCK_CONTINENT_SUBREGIONS, MOCK_SUBREGION_COUNTRIES);
    // Entry a: 1800–1850 → spans bucket 5 (1800–1849) AND bucket 6 (1850–1899) (pe=1850 >= 1850)
    // Entry b: 1700–1799 → bucket 4 (1700–1799)
    // Entry f: null → no bucket
    assert.equal(counts[0][4], 1); // bucket 4 (1700–1799): entry b
    assert.equal(counts[0][5], 1); // bucket 5 (1800–1849): entry a
    assert.equal(counts[0][6], 1); // bucket 6 (1850–1899): entry a (straddles boundary)
    assert.equal(counts[0].reduce((s, c) => s + c, 0), 3);
  });

  test('counts reflect filtered data (heatmap as lower-level filter)', () => {
    // Pass only entries with period_start >= 1800; bucket 4 (1700–1799) should be 0
    const filtered = ENTRIES.filter(e => e.period_start != null && e.period_start >= 1800);
    const rows     = ['Western Europe'];
    const counts   = countsByRows(rows, filtered, MOCK_CONTINENT_SUBREGIONS, MOCK_SUBREGION_COUNTRIES);
    assert.equal(counts[0][4], 0); // entry b (1700–1799) excluded
    assert.equal(counts[0][5], 1); // entry a (1800–1850) included
  });

  test('empty data gives all-zero counts', () => {
    const rows   = ['Western Europe', 'Eastern Europe'];
    const counts = countsByRows(rows, [], MOCK_CONTINENT_SUBREGIONS, MOCK_SUBREGION_COUNTRIES);
    assert.ok(counts.every(row => row.every(c => c === 0)));
  });
});
