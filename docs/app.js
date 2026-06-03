/** @type {Array<Object>} */
let allData = [];

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
          <a class="btn-article" href="https://doi.org/${entry.doi}" target="_blank" rel="noopener">Article ↗</a>
          <a class="btn-data" href="${escapeHtml(entry.replication_url)}" target="_blank" rel="noopener">Get Data</a>
        </div>
      </div>
    </li>`;
}

function applyFilters() {
  const periodFrom     = parseInt(document.getElementById('period-from').value) || null;
  const periodTo       = parseInt(document.getElementById('period-to').value)   || null;
  const checkedRegions = [...document.querySelectorAll('#region-filters input:checked')]
    .map(el => el.value);

  const filtered = allData.filter(entry => {
    if (periodFrom != null && entry.period_end   != null && entry.period_end   < periodFrom) return false;
    if (periodTo   != null && entry.period_start != null && entry.period_start > periodTo)   return false;
    if (checkedRegions.length > 0 && !checkedRegions.some(r => entry.regions.includes(r))) return false;
    return true;
  });

  document.getElementById('results-count').textContent =
    `${filtered.length} dataset${filtered.length !== 1 ? 's' : ''}`;
  document.getElementById('results').innerHTML = filtered.map(renderCard).join('');
}

async function init() {
  const resp = await fetch('data.json');
  allData = await resp.json();

  const regions   = [...new Set(allData.flatMap(e => e.regions))].sort();
  const regionDiv = document.getElementById('region-filters');
  regions.forEach(r => {
    const label = document.createElement('label');
    const cb    = document.createElement('input');
    cb.type  = 'checkbox';
    cb.value = r;
    cb.addEventListener('change', applyFilters);
    label.appendChild(cb);
    label.append(` ${r}`);
    regionDiv.appendChild(label);
  });

  ['period-from', 'period-to'].forEach(id => {
    document.getElementById(id).addEventListener('input', applyFilters);
  });

  document.getElementById('clear-filters').addEventListener('click', () => {
    document.querySelectorAll('aside input[type=number]').forEach(el => { el.value = ''; });
    document.querySelectorAll('aside input[type=checkbox]').forEach(el => { el.checked = false; });
    applyFilters();
  });

  applyFilters();
}

init().catch(err => {
  document.getElementById('results-count').textContent = 'Failed to load data.';
  console.error(err);
});
