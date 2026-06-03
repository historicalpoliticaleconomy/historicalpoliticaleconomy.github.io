/** @type {Array<Object>} */
let allData = [];

/** @type {{ ri: number, bi: number } | null} */
let selectedCell = null;

const REGIONS = [
  'Western Europe',
  'Eastern Europe',
  'North America',
  'Latin America',
  'Middle East & North Africa',
  'East Asia',
  'South Asia',
  'Sub-Saharan Africa',
  'Oceania',
  'Global/Comparative',
];

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

function cellColor(count, max) {
  if (count === 0) return '#eef0f5';
  const t = Math.pow(count / max, 0.55);
  return `rgb(${Math.round(208 - 179 * t)},${Math.round(218 - 166 * t)},${Math.round(240 - 143 * t)})`;
}

function heatmapCounts() {
  const counts = REGIONS.map(() => BUCKETS.map(() => 0));
  for (const entry of allData) {
    const ps = entry.period_start ?? entry.period_end;
    const pe = entry.period_end   ?? entry.period_start;
    if (ps == null) continue;
    BUCKETS.forEach((b, bi) => {
      if (ps <= b.end && pe >= b.start) {
        entry.regions.forEach(r => {
          const ri = REGIONS.indexOf(r);
          if (ri >= 0) counts[ri][bi]++;
        });
      }
    });
  }
  return counts;
}

function toggleCell(ri, bi) {
  if (selectedCell) {
    document.getElementById(`hm-cell-${selectedCell.ri}-${selectedCell.bi}`)?.classList.remove('active');
    document.getElementById(`hm-row-${selectedCell.ri}`)?.classList.remove('active');
    document.getElementById(`hm-col-${selectedCell.bi}`)?.classList.remove('active');
  }

  selectedCell = (selectedCell?.ri === ri && selectedCell?.bi === bi)
    ? null
    : { ri, bi };

  if (selectedCell) {
    document.getElementById(`hm-cell-${ri}-${bi}`)?.classList.add('active');
    document.getElementById(`hm-row-${ri}`)?.classList.add('active');
    document.getElementById(`hm-col-${bi}`)?.classList.add('active');
  }

  applyFilters();
}

function buildHeatmap() {
  const counts   = heatmapCounts();
  const maxCount = Math.max(1, ...counts.flat());
  const container = document.getElementById('heatmap');
  container.style.gridTemplateColumns = `max-content repeat(${BUCKETS.length}, minmax(0, 35px))`;

  // Header row
  container.appendChild(document.createElement('div')); // corner
  BUCKETS.forEach((b, bi) => {
    const el = document.createElement('div');
    el.className   = 'hm-col-label';
    el.id          = `hm-col-${bi}`;
    el.textContent = b.label;
    container.appendChild(el);
  });

  // Data rows (skip zero rows)
  REGIONS.forEach((region, ri) => {
    if (counts[ri].every(c => c === 0)) return;

    const rowLabel = document.createElement('div');
    rowLabel.className   = 'hm-row-label';
    rowLabel.id          = `hm-row-${ri}`;
    rowLabel.textContent = region;
    container.appendChild(rowLabel);

    BUCKETS.forEach((bucket, bi) => {
      const count = counts[ri][bi];
      const cell  = document.createElement('div');
      cell.className        = 'hm-cell';
      cell.id               = `hm-cell-${ri}-${bi}`;
      cell.style.background = cellColor(count, maxCount);
      cell.title = `${region} · ${bucket.label}: ${count} dataset${count !== 1 ? 's' : ''}`;
      if (count > 0) {
        cell.textContent = String(count);
        cell.addEventListener('click', () => toggleCell(ri, bi));
      }
      container.appendChild(cell);
    });
  });
}

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
  const period     = formatPeriod(entry.period_start, entry.period_end);
  const regionTags = entry.regions.map(r => `<span class="tag">${escapeHtml(r)}</span>`).join('');

  return `
    <li class="card">
      <div class="card-top">
        ${period     ? `<span class="period">${escapeHtml(period)}</span>` : ''}
        ${regionTags}
      </div>
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

function applyFilters() {
  const filtered = selectedCell === null
    ? allData
    : allData.filter(entry => {
        const region = REGIONS[selectedCell.ri];
        const bucket = BUCKETS[selectedCell.bi];
        if (!entry.regions.includes(region)) return false;
        const ps = entry.period_start ?? entry.period_end;
        const pe = entry.period_end   ?? entry.period_start;
        if (ps == null) return false;
        return ps <= bucket.end && pe >= bucket.start;
      });

  document.getElementById('results-count').textContent =
    `${filtered.length} dataset${filtered.length !== 1 ? 's' : ''}`;
  document.getElementById('results').innerHTML = filtered.map(renderCard).join('');
}

async function init() {
  const resp = await fetch('data.json');
  allData = await resp.json();
  buildHeatmap();
  applyFilters();
}

init().catch(err => {
  document.getElementById('results-count').textContent = 'Failed to load data.';
  console.error(err);
});
