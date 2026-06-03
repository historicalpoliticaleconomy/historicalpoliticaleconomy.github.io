/** @type {Array<Object>} */
let allData = [];

// Geo data built from geo.json at init time
/** @type {Map<string, string[]>} subregion → country names */
let SUBREGION_COUNTRIES = new Map();
/** @type {Map<string, string>} subregion → continent */
let SUBREGION_CONTINENT = new Map();
/** @type {string[]} ordered continent names */
let CONTINENTS = [];
/** @type {Map<string, string[]>} continent → subregion names */
let CONTINENT_SUBREGIONS = new Map();

// Continent display order (M.49 major areas)
const CONTINENT_ORDER = ['Africa', 'Americas', 'Asia', 'Europe', 'Oceania'];

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

// Heatmap drill-down state: 0=continents, 1=subregions, 2=countries
let heatmapLevel    = 0;
let focusContinent  = null;
let focusSubregion  = null;

// Article filter state (mutually exclusive)
let selectedCell    = null; // { rowKey: string, bi: number }  (continent or subregion level)
let selectedCountry = null; // { country: string, bi: number }

function buildGeo(geoData) {
  const bySubregion = new Map();
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

  // Build continent → sorted subregions
  const contSubMap = new Map();
  for (const [sub, cont] of subToContinent) {
    if (!contSubMap.has(cont)) contSubMap.set(cont, []);
    contSubMap.get(cont).push(sub);
  }
  for (const subs of contSubMap.values()) subs.sort();
  CONTINENT_SUBREGIONS = contSubMap;

  CONTINENTS = [...CONTINENT_ORDER.filter(c => contSubMap.has(c)), 'Global/Comparative'];
}

// ── Color scale ──────────────────────────────────────────────────────────────

function cellColor(count, max) {
  if (count === 0) return '#eef0f5';
  const t = Math.pow(count / max, 0.55);
  return `rgb(${Math.round(208 - 179 * t)},${Math.round(218 - 166 * t)},${Math.round(240 - 143 * t)})`;
}

// ── Count helpers ─────────────────────────────────────────────────────────────

function entryOverlapsBucket(entry, bucket) {
  const ps = entry.period_start ?? entry.period_end;
  const pe = entry.period_end   ?? entry.period_start;
  if (ps == null) return false;
  return ps <= bucket.end && pe >= bucket.start;
}

function countsByRows(rows, keyFn) {
  // rows: array of row-key strings; returns counts[rowIndex][bucketIndex]
  const counts = rows.map(() => BUCKETS.map(() => 0));
  for (const entry of allData) {
    BUCKETS.forEach((b, bi) => {
      if (!entryOverlapsBucket(entry, b)) return;
      rows.forEach((key, ri) => {
        if (entryMatchesKey(entry, key)) counts[ri][bi]++;
      });
    });
  }
  return counts;
}

function entryMatchesKey(entry, key) {
  if (key === 'Global/Comparative') return entry.regions.includes('Global/Comparative');
  // Is it a continent?
  if (CONTINENT_SUBREGIONS.has(key)) {
    const subs = CONTINENT_SUBREGIONS.get(key) || [];
    return subs.some(s => entry.regions.includes(s));
  }
  // Is it a subregion?
  if (SUBREGION_COUNTRIES.has(key)) return entry.regions.includes(key);
  // Otherwise treat as a country name
  return entry.countries.includes(key);
}

// ── Heatmap rendering ─────────────────────────────────────────────────────────

function buildHeatmap() {
  const container = document.getElementById('heatmap');
  container.innerHTML = '';
  container.style.gridTemplateColumns = `max-content repeat(${BUCKETS.length}, minmax(0, 52px))`;

  if (heatmapLevel === 0) renderContinentView(container);
  else if (heatmapLevel === 1) renderSubregionView(container);
  else renderCountryView(container);
}

function renderBreadcrumb(container, parts) {
  if (!parts.length) return;
  const bc = document.createElement('div');
  bc.className   = 'hm-breadcrumb';
  bc.style.gridColumn = `1 / -1`;
  bc.innerHTML = parts.map((p, i) =>
    i < parts.length - 1
      ? `<span class="hm-bc-link" data-level="${i}">${escapeHtml(p)}</span>`
      : `<span>${escapeHtml(p)}</span>`
  ).join(' › ');
  bc.querySelectorAll('.hm-bc-link').forEach(el => {
    el.addEventListener('click', () => {
      const level = parseInt(el.dataset.level || '0');
      if (level === 0) { heatmapLevel = 0; focusContinent = null; focusSubregion = null; }
      clearSelection();
      buildHeatmap();
    });
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

function renderRows(container, rows, maxCount, counts, onLabelClick, labelClass = 'hm-row-label') {
  rows.forEach((key, ri) => {
    if (counts[ri].every(c => c === 0)) return;

    const rowLabel = document.createElement('div');
    rowLabel.className   = labelClass;
    rowLabel.id          = `hm-row-${CSS.escape(key)}`;
    rowLabel.textContent = key;
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
      if (selectedCountry?.bi === bi && key === selectedCountry?.country) cell.classList.add('active');
      container.appendChild(cell);
    });
  });
}

function renderContinentView(container) {
  renderColumnHeaders(container);
  const counts   = countsByRows(CONTINENTS, k => k);
  const maxCount = Math.max(1, ...counts.flat());
  renderRows(container, CONTINENTS, maxCount, counts, key => {
    if (key === 'Global/Comparative') { toggleCell(key, selectedCell?.bi ?? -1); return; }
    focusContinent = key;
    heatmapLevel   = 1;
    clearSelection();
    buildHeatmap();
  });
}

function renderSubregionView(container) {
  renderBreadcrumb(container, [focusContinent]);
  renderColumnHeaders(container);
  const subs   = CONTINENT_SUBREGIONS.get(focusContinent) || [];
  const counts = countsByRows(subs, k => k);
  const max    = Math.max(1, ...counts.flat());
  renderRows(container, subs, max, counts, key => {
    focusSubregion = key;
    heatmapLevel   = 2;
    clearSelection();
    buildHeatmap();
  });
}

function renderCountryView(container) {
  renderBreadcrumb(container, [focusContinent, focusSubregion]);
  renderColumnHeaders(container);
  const allCountries = SUBREGION_COUNTRIES.get(focusSubregion) || [];
  // Only show countries that have at least one article
  const activeCountries = allCountries.filter(c =>
    allData.some(e => e.countries.includes(c))
  );
  if (!activeCountries.length) {
    const msg = document.createElement('div');
    msg.style.gridColumn = `1 / -1`;
    msg.style.padding = '.5rem';
    msg.style.color = 'var(--muted)';
    msg.style.fontSize = '.8rem';
    msg.textContent = 'No datasets with country data in this sub-region yet.';
    container.appendChild(msg);
    return;
  }
  const counts = countsByRows(activeCountries, c => c);
  const max    = Math.max(1, ...counts.flat());
  renderRows(container, activeCountries, max, counts,
    () => {}, // no drill-down from country level
    'hm-row-label hm-country-label'
  );
}

// ── Selection ─────────────────────────────────────────────────────────────────

function clearSelection() {
  selectedCell    = null;
  selectedCountry = null;
}

function toggleCell(rowKey, bi) {
  if (selectedCell?.rowKey === rowKey && selectedCell?.bi === bi) {
    selectedCell = null;
  } else {
    selectedCell    = { rowKey, bi };
    selectedCountry = null;
  }
  buildHeatmap();
  applyFilters();
}

function toggleCountryCell(country, bi) {
  if (selectedCountry?.country === country && selectedCountry?.bi === bi) {
    selectedCountry = null;
  } else {
    selectedCountry = { country, bi };
    selectedCell    = null;
  }
  applyFilters();
}

// ── Filtering ─────────────────────────────────────────────────────────────────

function applyFilters() {
  const filtered = allData.filter(entry => {
    if (selectedCell !== null) {
      const { rowKey, bi } = selectedCell;
      if (!entryMatchesKey(entry, rowKey)) return false;
      if (!entryOverlapsBucket(entry, BUCKETS[bi])) return false;
    }
    if (selectedCountry !== null) {
      const { country, bi } = selectedCountry;
      if (!entry.countries.includes(country)) return false;
      if (!entryOverlapsBucket(entry, BUCKETS[bi])) return false;
    }
    return true;
  });

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
  const regionTags  = entry.regions.map(r => `<span class="tag">${escapeHtml(r)}</span>`).join('');
  const countryTags = (entry.countries || []).map(c => `<span class="country-tag">${escapeHtml(c)}</span>`).join('');

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

  buildHeatmap();
  applyFilters();
}

init().catch(err => {
  document.getElementById('results-count').textContent = 'Failed to load data.';
  console.error(err);
});
