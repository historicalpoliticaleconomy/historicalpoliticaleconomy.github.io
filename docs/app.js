/** @type {Array<Object>} */
let allData = [];

/** @type {Map<string, string[]>} */
let SUBREGION_COUNTRIES = new Map();
/** @type {Map<string, string>} */
let SUBREGION_CONTINENT = new Map();
/** @type {string[]} */
let CONTINENTS = [];
/** @type {Map<string, string[]>} */
let CONTINENT_SUBREGIONS = new Map();
/** @type {Map<string, string>} geo.json country name → its canonical subregion */
let COUNTRY_CANONICAL_SUBREGION = new Map();

const CONTINENT_ORDER = ['Africa', 'Americas', 'Asia', 'Europe', 'Oceania'];

const COUNTRY_DISPLAY_NAMES = new Map([
  ['Congo, The Democratic Republic of the', 'DR Congo'],
  ['Korea, Republic of',                    'South Korea'],
  ['Korea, Democratic People\'s Republic of', 'North Korea'],
  ['Russian Federation',                    'Russia'],
  ['Iran, Islamic Republic of',             'Iran'],
  ['Syrian Arab Republic',                  'Syria'],
  ['Viet Nam',                              'Vietnam'],
  ['Taiwan, Province of China',             'Taiwan'],
  ['Palestine, State of',                   'Palestine'],
  ['Lao People\'s Democratic Republic',     'Laos'],
  ['Bolivia, Plurinational State of',       'Bolivia'],
  ['Venezuela, Bolivarian Republic of',     'Venezuela'],
  ['Tanzania, United Republic of',          'Tanzania'],
  ['Moldova, Republic of',                  'Moldova'],
  ['Holy See (Vatican City State)',          'Vatican City'],
]);

const displayCountry = name => COUNTRY_DISPLAY_NAMES.get(name) ?? name;

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

// Heatmap drill-down state
let heatmapLevel   = 0;
let focusContinent = null;
let focusSubregion = null;

// Two-level filter state
let searchQuery  = '';   // top-level: text
let selectedCell = null; // lower-level: { rowKey, bi }


function buildGeo(geoData) {
  const bySubregion    = new Map();
  const subToContinent = new Map();

  for (const entry of geoData.countries) {
    const { name, continent, subregion } = entry;
    if (!subregion || !continent) continue;
    if (!bySubregion.has(subregion)) bySubregion.set(subregion, []);
    bySubregion.get(subregion).push(name);
    subToContinent.set(subregion, continent);
  }

  SUBREGION_COUNTRIES = bySubregion;
  SUBREGION_CONTINENT = subToContinent;

  const contSubMap = new Map();
  for (const [sub, cont] of subToContinent) {
    if (!contSubMap.has(cont)) contSubMap.set(cont, []);
    contSubMap.get(cont).push(sub);
  }
  for (const subs of contSubMap.values()) subs.sort();
  CONTINENT_SUBREGIONS = contSubMap;

  CONTINENTS = [...CONTINENT_ORDER.filter(c => contSubMap.has(c)), 'Global/Comparative'];

  const canonMap = new Map();
  for (const [sub, countries] of bySubregion) {
    for (const c of countries) canonMap.set(c, sub);
  }
  COUNTRY_CANONICAL_SUBREGION = canonMap;
}

// ── Color scale ───────────────────────────────────────────────────────────────

function cellColor(count, max) {
  if (count === 0) return '#eef0f5';
  const t = Math.pow(count / max, 0.55);
  return `rgb(${Math.round(208 - 179 * t)},${Math.round(218 - 166 * t)},${Math.round(240 - 143 * t)})`;
}

// ── Pure filter helpers (also tested in tests/test_app_logic.mjs) ─────────────

function entryOverlapsBucket(entry, bucket) {
  const ps = entry.period_start ?? entry.period_end;
  const pe = entry.period_end   ?? entry.period_start;
  if (ps == null) return false;
  return ps <= bucket.end && pe >= bucket.start;
}


function entryMatchesKey(entry, key) {
  if (key === 'Global/Comparative') return entry.regions.includes('Global/Comparative');
  if (CONTINENT_SUBREGIONS.has(key)) {
    const subs = CONTINENT_SUBREGIONS.get(key) || [];
    return subs.some(s => entry.regions.includes(s));
  }
  if (SUBREGION_COUNTRIES.has(key)) return entry.regions.includes(key);
  return (entry.countries || []).includes(key);
}

// Returns allData filtered by the top-level text + date inputs.
// The heatmap and cell filter operate on this subset.
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

function getSearchCandidates() {
  return searchQuery ? allData.filter(e => entryMatchesText(e, searchQuery)) : allData;
}

function countsByRows(rows, data) {
  const counts = rows.map(() => BUCKETS.map(() => 0));
  for (const entry of data) {
    BUCKETS.forEach((b, bi) => {
      if (!entryOverlapsBucket(entry, b)) return;
      rows.forEach((key, ri) => {
        if (entryMatchesKey(entry, key)) counts[ri][bi]++;
      });
    });
  }
  return counts;
}

// Countries visible in a subregion drill-down.
// Canonical (geo.json) countries appear only under their canonical subregion.
// Non-canonical countries (historical polities, territories) are "anchored" to
// whichever of an entry's subregions has the most canonical countries — preventing
// them from bleeding into unrelated subregions on multi-region comparative papers.
function countriesForSubregion(sub, data) {
  return [...new Set(
    data
      .filter(e => e.regions.includes(sub))
      .flatMap(e => {
        const regions   = e.regions   || [];
        const countries = e.countries || [];

        // Compute anchor regions for non-canonical countries: the region(s) in
        // this entry with the highest count of geo.json-canonical countries.
        let anchorRegions;
        if (regions.length <= 1) {
          anchorRegions = new Set(regions);
        } else {
          const counts = regions.map(r => ({
            r, n: countries.filter(c => COUNTRY_CANONICAL_SUBREGION.get(c) === r).length,
          }));
          const max = Math.max(...counts.map(x => x.n));
          // No canonical countries at all → can't determine anchor, allow all regions.
          anchorRegions = new Set(
            max === 0 ? regions : counts.filter(x => x.n === max).map(x => x.r)
          );
        }

        return countries.filter(c => {
          if (!c) return false;
          const canonical = COUNTRY_CANONICAL_SUBREGION.get(c);
          return canonical ? canonical === sub : anchorRegions.has(sub);
        });
      })
  )];
}

// ── Heatmap rendering ─────────────────────────────────────────────────────────

function buildHeatmap() {
  const container = document.getElementById('heatmap');
  container.innerHTML = '';
  container.style.gridTemplateColumns = `max-content repeat(${BUCKETS.length}, minmax(0, 52px))`;

  if (heatmapLevel === 0) renderContinentView(container);
  else if (heatmapLevel === 1) renderSubregionView(container);
  else renderCountryView(container);

  container.classList.remove('hm-fade-in');
  void container.offsetHeight;
  container.classList.add('hm-fade-in');
}

function renderBreadcrumb(container) {
  const bc = document.createElement('div');
  bc.className = 'hm-breadcrumb';
  bc.style.gridColumn = '1 / -1';

  const items = [
    {
      label:  'All continents',
      action: () => {
        heatmapLevel = 0; focusContinent = null; focusSubregion = null;
        selectedCell = null; buildHeatmap(); applyFilters();
      },
    },
  ];
  if (focusContinent && heatmapLevel === 2) {
    items.push({
      label:  focusContinent,
      action: () => { heatmapLevel = 1; focusSubregion = null; selectedCell = null; buildHeatmap(); applyFilters(); },
    });
  }
  items.push({ label: heatmapLevel === 1 ? focusContinent : focusSubregion, action: null });

  bc.innerHTML = items.map((item, i) =>
    item.action
      ? `<span class="hm-bc-link" data-idx="${i}">${escapeHtml(item.label)}</span>`
      : `<span class="hm-bc-current">${escapeHtml(item.label)}</span>`
  ).join(' › ');

  bc.querySelectorAll('.hm-bc-link').forEach(el => {
    const idx = parseInt(el.dataset.idx);
    el.addEventListener('click', items[idx].action);
  });

  container.appendChild(bc);
}

function renderColumnHeaders(container) {
  container.appendChild(document.createElement('div')); // corner
  BUCKETS.forEach((b, bi) => {
    const el = document.createElement('div');
    el.className   = 'hm-col-label';
    el.id          = `hm-col-${bi}`;
    el.textContent = b.label;
    container.appendChild(el);
  });
}

function renderRows(container, rows, maxCount, counts, onLabelClick, labelClassFn = 'hm-row-label') {
  const getClass = typeof labelClassFn === 'function' ? labelClassFn : () => labelClassFn;
  rows.forEach((key, ri) => {
    if (counts[ri].every(c => c === 0)) return;

    const rowLabel = document.createElement('div');
    rowLabel.className   = getClass(key);
    rowLabel.id          = `hm-row-${CSS.escape(key)}`;
    rowLabel.textContent = displayCountry(key);
    rowLabel.addEventListener('click', () => onLabelClick(key));
    container.appendChild(rowLabel);

    BUCKETS.forEach((bucket, bi) => {
      const count = counts[ri][bi];
      const cell  = document.createElement('div');
      cell.className        = 'hm-cell';
      cell.id               = `hm-cell-${CSS.escape(key)}-${bi}`;
      cell.style.background = cellColor(count, maxCount);
      cell.title = `${key} · ${bucket.label}: ${count} dataset${count !== 1 ? 's' : ''}`;
      if (count > 0) {
        cell.textContent = String(count);
        cell.addEventListener('click', () => toggleCell(key, bi));
      }
      if (selectedCell?.rowKey === key && selectedCell?.bi === bi) cell.classList.add('active');
      container.appendChild(cell);
    });
  });
}

// Returns the flat row list for a continent after subregion auto-expansion.
// Greedily expands the smallest subregions first while total rows stays ≤ 10.
function effectiveSubregionRows(continent, data) {
  const rows         = [];
  const autoExpanded = new Set();

  const subregionData = [];
  for (const sub of (CONTINENT_SUBREGIONS.get(continent) || [])) {
    if (!data.some(e => entryMatchesKey(e, sub))) continue;
    const activeCountries = countriesForSubregion(sub, data);
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

function renderContinentView(container) {
  renderColumnHeaders(container);
  const data = getSearchCandidates();

  // Compute effective rows per active continent
  const continentData = [];
  for (const continent of CONTINENTS) {
    if (continent === 'Global/Comparative') {
      if (data.some(e => (e.regions || []).includes('Global/Comparative'))) {
        continentData.push({ continent, effRows: ['Global/Comparative'], isGlobal: true });
      }
      continue;
    }
    const { rows: effRows } = effectiveSubregionRows(continent, data);
    if (effRows.length === 0) continue;
    continentData.push({ continent, effRows, isGlobal: false });
  }

  // Greedily expand continents (smallest first) while total rows ≤ 10
  let totalRows = continentData.length;
  const expandedContinents = new Set();
  const bySize = [...continentData]
    .filter(d => !d.isGlobal)
    .sort((a, b) => a.effRows.length - b.effRows.length);

  for (const { continent, effRows } of bySize) {
    if (totalRows + (effRows.length - 1) <= 10) {
      expandedContinents.add(continent);
      totalRows += effRows.length - 1;
    }
  }

  // Build flat row list in CONTINENTS order
  const rows         = [];
  const autoExpanded = new Set();
  for (const { continent, effRows, isGlobal } of continentData) {
    if (isGlobal || !expandedContinents.has(continent)) {
      rows.push(continent);
    } else {
      for (const r of effRows) {
        rows.push(r);
        if (!SUBREGION_COUNTRIES.has(r)) autoExpanded.add(r);
      }
    }
  }

  const counts   = countsByRows(rows, data);
  const maxCount = Math.max(1, ...counts.flat());
  renderRows(container, rows, maxCount, counts, key => {
    if (autoExpanded.has(key)) return;
    if (key === 'Global/Comparative') { toggleCell(key, -1); return; }
    if (SUBREGION_COUNTRIES.has(key)) {
      focusContinent = SUBREGION_CONTINENT.get(key) ?? null;
      focusSubregion = key;
      heatmapLevel   = 2; selectedCell = null;
      buildHeatmap(); applyFilters(); return;
    }
    focusContinent = key;
    heatmapLevel   = 1; selectedCell = null;
    buildHeatmap(); applyFilters();
  }, key => autoExpanded.has(key) ? 'hm-row-label hm-country-label' : 'hm-row-label');
}

function renderSubregionView(container) {
  renderBreadcrumb(container);
  renderColumnHeaders(container);

  const data                     = getSearchCandidates();
  const { rows, autoExpanded }   = effectiveSubregionRows(focusContinent, data);
  const counts                   = countsByRows(rows, data);
  const max                      = Math.max(1, ...counts.flat());

  renderRows(container, rows, max, counts, key => {
    if (autoExpanded.has(key)) return;
    focusSubregion = key;
    heatmapLevel   = 2;
    selectedCell   = null;
    buildHeatmap();
    applyFilters();
  }, key => autoExpanded.has(key) ? 'hm-row-label hm-country-label' : 'hm-row-label');
}

function renderCountryView(container) {
  renderBreadcrumb(container);
  renderColumnHeaders(container);

  const data            = getSearchCandidates();
  const activeCountries = countriesForSubregion(focusSubregion, data);

  if (!activeCountries.length) {
    const msg = document.createElement('div');
    msg.style.gridColumn = '1 / -1';
    msg.style.padding    = '.5rem';
    msg.style.color      = 'var(--muted)';
    msg.style.fontSize   = '.8rem';
    msg.textContent = 'No datasets with country data in this sub-region yet.';
    container.appendChild(msg);
    return;
  }

  const counts = countsByRows(activeCountries, data);
  const max    = Math.max(1, ...counts.flat());
  renderRows(container, activeCountries, max, counts, () => {}, 'hm-row-label hm-country-label');
}

// ── Selection ─────────────────────────────────────────────────────────────────

function toggleCell(rowKey, bi) {
  selectedCell = (selectedCell?.rowKey === rowKey && selectedCell?.bi === bi)
    ? null
    : { rowKey, bi };
  buildHeatmap();
  applyFilters();
}

// ── Filtering ─────────────────────────────────────────────────────────────────

function applyFilters() {
  const candidates = getSearchCandidates();
  const filtered   = selectedCell === null
    ? candidates
    : candidates.filter(entry =>
        entryMatchesKey(entry, selectedCell.rowKey) &&
        (selectedCell.bi < 0 || entryOverlapsBucket(entry, BUCKETS[selectedCell.bi]))
      );

  document.getElementById('results-count').textContent =
    `${filtered.length} dataset${filtered.length !== 1 ? 's' : ''}`;
  document.getElementById('results').innerHTML = filtered.map(renderCard).join('');
}

// ── Cards ─────────────────────────────────────────────────────────────────────

function formatPeriod(start, end) {
  if (start == null && end == null) return null;
  const fmt = n => n < 0 ? `${Math.abs(n)} BCE` : String(n);
  const s = start != null ? fmt(start) : '?';
  const e = end   != null ? fmt(end)   : '?';
  return s === e ? s : `${s}–${e}`;
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function errorHref(doi) {
  const body = `DOI: ${doi}\n\nDescribe the error:\n`;
  return `mailto:hmm2198@columbia.edu`
    + `?subject=${encodeURIComponent('HPE Error Report')}`
    + `&body=${encodeURIComponent(body)}`;
}

function renderCard(entry) {
  const period      = formatPeriod(entry.period_start, entry.period_end);
  const regionTags  = entry.regions.map(r =>
    `<span class="tag" data-region="${escapeHtml(r)}">${escapeHtml(r)}</span>`).join('');
  const countryTags = (entry.countries || []).map(c =>
    `<span class="country-tag" data-country="${escapeHtml(c)}">${escapeHtml(displayCountry(c))}</span>`).join('');

  return `
    <li class="card">
      <div class="card-top">
        ${period     ? `<span class="period">${escapeHtml(period)}</span>` : ''}
        ${regionTags}
      </div>
      ${countryTags ? `<div class="country-tags">${countryTags}</div>` : ''}
      <div class="card-title">${escapeHtml(entry.title || '(no title)')}</div>
      <div class="card-footer">
        <span class="card-authors">${escapeHtml(entry.authors || '')}</span>
        <div class="card-links">
          <a class="btn-error" href="${errorHref(entry.doi)}">Report error</a>
          <a class="btn-article" href="https://doi.org/${entry.doi}" target="_blank" rel="noopener">Article ↗</a>
          <a class="btn-data" href="${escapeHtml(entry.replication_url)}" target="_blank" rel="noopener">Get Data</a>
        </div>
      </div>
    </li>`;
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  const [dataResp, geoResp] = await Promise.all([
    fetch('data.json'),
    fetch('geo.json'),
  ]);
  allData = await dataResp.json();
  buildGeo(await geoResp.json());

  for (const entry of allData) {
    entry._continents = (entry.regions || [])
      .map(r => SUBREGION_CONTINENT.get(r)).filter(Boolean);
  }

  document.getElementById('search-input').addEventListener('input', e => {
    searchQuery  = e.target.value.trim();
    selectedCell = null;
    buildHeatmap();
    applyFilters();
  });

  document.getElementById('results').addEventListener('click', e => {
    const regionEl  = e.target.closest('[data-region]');
    const countryEl = e.target.closest('[data-country]');
    if (!regionEl && !countryEl) return;
    e.stopPropagation();

    if (regionEl) {
      const r = regionEl.dataset.region;
      if (r === 'Global/Comparative') return;
      focusSubregion = r;
      focusContinent = SUBREGION_CONTINENT.get(r) ?? null;
      heatmapLevel   = 2;
      selectedCell   = { rowKey: r, bi: -1 };
    } else {
      const c   = countryEl.dataset.country;
      const sub = COUNTRY_CANONICAL_SUBREGION.get(c)
        ?? [...SUBREGION_COUNTRIES.keys()].find(s => countriesForSubregion(s, allData).includes(c));
      if (!sub) return;
      focusSubregion = sub;
      focusContinent = SUBREGION_CONTINENT.get(sub) ?? null;
      heatmapLevel   = 2;
      selectedCell   = { rowKey: c, bi: -1 };
    }

    buildHeatmap();
    applyFilters();
  });

  buildHeatmap();
  applyFilters();
}

init().catch(err => {
  document.getElementById('results-count').textContent = 'Failed to load data.';
  console.error(err);
});

// ── Debug helpers (call from browser console) ─────────────────────────────────
// debugSubregion("party", "Caribbean") — shows which countries appear and why
window.debugSubregion = function(query, sub) {
  const data = query
    ? allData.filter(e => entryMatchesText(e, query))
    : allData;
  const entries = data.filter(e => e.regions.includes(sub));
  console.group(`countriesForSubregion("${sub}") with query="${query}" — ${entries.length} entries`);
  for (const e of entries) {
    const regions   = e.regions   || [];
    const countries = e.countries || [];
    const counts = regions.map(r => ({
      r, n: countries.filter(c => COUNTRY_CANONICAL_SUBREGION.get(c) === r).length,
    }));
    const max = Math.max(...counts.map(x => x.n));
    const anchors = max === 0 ? regions : counts.filter(x => x.n === max).map(x => x.r);
    const shown = countries.filter(c => {
      const canon = COUNTRY_CANONICAL_SUBREGION.get(c);
      return canon ? canon === sub : anchors.includes(sub);
    });
    console.log(e.doi, '|', e.title?.slice(0, 60));
    console.log('  regions:', regions.join(', '));
    console.log('  countries:', countries.join(', '));
    console.log('  canonical counts:', counts.map(x => `${x.r}:${x.n}`).join(', '));
    console.log('  anchors:', anchors.join(', '), '| shown here:', shown.join(', '));
  }
  console.groupEnd();
};

// debugContinent("party") — shows what the continent view would render
window.debugContinent = function(query) {
  const data = query ? allData.filter(e => entryMatchesText(e, query)) : allData;
  console.group(`continent view for query="${query}"`);
  for (const continent of CONTINENTS) {
    if (continent === 'Global/Comparative') continue;
    const { rows: effRows } = effectiveSubregionRows(continent, data);
    if (effRows.length === 0) continue;
    console.log(continent, '→', effRows.join(', '), `(${effRows.length} rows)`);
  }
  console.groupEnd();
};
