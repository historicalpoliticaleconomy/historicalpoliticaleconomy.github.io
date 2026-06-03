/** @type {Array<Object>} */
let allData = [];

function formatPeriod(start, end) {
  if (start == null && end == null) return null;
  const s = start != null ? String(start < 0 ? `${Math.abs(start)} BCE` : start) : '?';
  const e = end   != null ? String(end   < 0 ? `${Math.abs(end)} BCE`   : end)   : '?';
  return s === e ? s : `${s}–${e}`;
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderCard(entry) {
  const period    = formatPeriod(entry.period_start, entry.period_end);
  const regionTags = entry.regions.map(r => `<span class="tag">${escapeHtml(r)}</span>`).join('');
  const dataHref  = entry.replication_url || `https://doi.org/${entry.doi}`;
  const dataLabel = entry.replication_url ? 'Get Data' : 'Get Data (via article)';
  const articleLink = entry.replication_url
    ? `<a class="btn-article" href="https://doi.org/${entry.doi}" target="_blank" rel="noopener">Article ↗</a>`
    : '';

  return `
    <li class="card">
      <div class="card-meta">
        <span class="journal-badge">${escapeHtml(entry.journal)}</span>
        ${entry.year   ? `<span class="pub-year">${entry.year}</span>` : ''}
        ${period       ? `<span class="hist-period">${escapeHtml(period)}</span>` : ''}
      </div>
      <h3 class="card-title">${escapeHtml(entry.title || '(no title)')}</h3>
      ${entry.authors ? `<p class="card-authors">${escapeHtml(entry.authors)}</p>` : ''}
      ${regionTags    ? `<div class="tags">${regionTags}</div>` : ''}
      <div class="card-actions">
        <a class="btn-data" href="${escapeHtml(dataHref)}" target="_blank" rel="noopener">${dataLabel}</a>
        ${articleLink}
      </div>
    </li>`;
}

function applyFilters() {
  const periodFrom  = parseInt(document.getElementById('period-from').value) || null;
  const periodTo    = parseInt(document.getElementById('period-to').value)   || null;
  const pubFrom     = parseInt(document.getElementById('pub-from').value)    || null;
  const pubTo       = parseInt(document.getElementById('pub-to').value)      || null;
  const journal     = document.getElementById('journal-filter').value;
  const dataOnly    = document.getElementById('data-available').checked;
  const checkedRegions = [...document.querySelectorAll('#region-filters input:checked')]
    .map(el => el.value);

  const filtered = allData.filter(entry => {
    if (periodFrom != null && entry.period_end   != null && entry.period_end   < periodFrom) return false;
    if (periodTo   != null && entry.period_start != null && entry.period_start > periodTo)   return false;
    if (pubFrom    != null && entry.year         != null && entry.year         < pubFrom)     return false;
    if (pubTo      != null && entry.year         != null && entry.year         > pubTo)       return false;
    if (journal && entry.journal !== journal) return false;
    if (checkedRegions.length > 0 && !checkedRegions.some(r => entry.regions.includes(r))) return false;
    if (dataOnly && !entry.replication_url) return false;
    return true;
  });

  const count = document.getElementById('results-count');
  count.textContent = `${filtered.length} dataset${filtered.length !== 1 ? 's' : ''}`;

  document.getElementById('results').innerHTML = filtered.map(renderCard).join('');
}

async function init() {
  const resp = await fetch('data.json');
  allData = await resp.json();

  // Populate journal dropdown
  const journals = [...new Set(allData.map(e => e.journal))].sort();
  const sel = document.getElementById('journal-filter');
  journals.forEach(j => {
    const opt = document.createElement('option');
    opt.value = j;
    opt.textContent = j;
    sel.appendChild(opt);
  });

  // Populate region checkboxes
  const regions = [...new Set(allData.flatMap(e => e.regions))].sort();
  const regionDiv = document.getElementById('region-filters');
  regions.forEach(r => {
    const label = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = r;
    cb.addEventListener('change', applyFilters);
    label.appendChild(cb);
    label.append(` ${r}`);
    regionDiv.appendChild(label);
  });

  // Wire up remaining inputs
  ['period-from', 'period-to', 'pub-from', 'pub-to'].forEach(id => {
    document.getElementById(id).addEventListener('input', applyFilters);
  });
  document.getElementById('journal-filter').addEventListener('change', applyFilters);
  document.getElementById('data-available').addEventListener('change', applyFilters);

  document.getElementById('clear-filters').addEventListener('click', () => {
    document.querySelectorAll('aside input[type=number]').forEach(el => { el.value = ''; });
    document.querySelectorAll('aside input[type=checkbox]').forEach(el => { el.checked = false; });
    document.getElementById('journal-filter').value = '';
    applyFilters();
  });

  applyFilters();
}

init().catch(err => {
  document.getElementById('results-count').textContent = 'Failed to load data.';
  console.error(err);
});
