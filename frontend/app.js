let currentUploadSessionId = null;
let entries = [];
let hasGenerated = false;

const $ = (id) => document.getElementById(id);

function setMessage(text, type='ok') {
  $('message').innerHTML = `<span class="${type}">${text}</span>`;
}

async function api(url, options={}) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok && res.status !== 207) throw new Error(data.error || data.detail || JSON.stringify(data));
  return data;
}

async function loadMetadata() {
  const data = await api('/api/metadata/');
  $('stats').innerHTML = `
    <div class="stat"><strong>${data.rooms}</strong><span>Rooms</span></div>
    <div class="stat"><strong>${data.time_slots}</strong><span>Mon-Fri Slots</span></div>
    <div class="stat"><strong>${data.departments.length}</strong><span>Faculties</span></div>
    <div class="stat"><strong>${data.programs.length}</strong><span>Programs</span></div>`;
  $('facultyFilter').innerHTML = '<option value="all">All faculties</option>' + data.departments.map(d => `<option value="${d.code}">${d.code} - ${d.full_name}</option>`).join('');
  $('programFilter').innerHTML = '<option value="all">All programs</option>' + data.programs.map(p => `<option value="${p.code}">${p.code} - ${p.full_name}</option>`).join('');
}

function renderTable() {
  const q = $('searchBox').value.trim().toLowerCase();
  const filtered = entries.filter(e => !q || Object.values(e).join(' ').toLowerCase().includes(q));
  if (!filtered.length) {
    $('timetableBody').innerHTML = `<tr><td class="empty" colspan="8">No timetable entries yet.</td></tr>`;
    return;
  }
  $('timetableBody').innerHTML = filtered.map(e => `
    <tr>
      <td>${e.day}</td>
      <td>${e.startTime} - ${e.endTime}</td>
      <td>${e.courseCode}</td>
      <td>${e.courseTitle}</td>
      <td>${e.instructor}</td>
      <td>${e.section}</td>
      <td>${e.room}</td>
      <td>${e.faculty}</td>
    </tr>`).join('');
}

/**
 * Update the hard constraint status panel after generation.
 * @param {object} hc - hard_constraints object from backend
 * @param {number} placed - number of placed tasks
 * @param {number} total - total number of tasks
 */
function updateConstraintPanel(hc, placed, total) {
  const panel = $('constraintPanel');
  panel.classList.remove('hidden');

  const v = hc.violations || {};
  const checks = [
    { key: 'HC1_teacher', cardId: 'hc1Card', iconId: 'hc1Icon', detailId: 'hc1Detail',
      passMsg: 'No teacher conflicts detected', failMsg: (n) => `${n} teacher conflict(s) found` },
    { key: 'HC2_room', cardId: 'hc2Card', iconId: 'hc2Icon', detailId: 'hc2Detail',
      passMsg: 'No room conflicts detected', failMsg: (n) => `${n} room conflict(s) found` },
    { key: 'HC3_section', cardId: 'hc3Card', iconId: 'hc3Icon', detailId: 'hc3Detail',
      passMsg: 'No section overlaps detected', failMsg: (n) => `${n} section overlap(s) found` },
    { key: 'HC4_sessions', cardId: 'hc4Card', iconId: 'hc4Icon', detailId: 'hc4Detail',
      passMsg: 'All sessions scheduled correctly', failMsg: (n) => `${n} offering(s) with wrong session count` },
  ];

  let allPass = true;
  for (const c of checks) {
    const arr = v[c.key] || [];
    const card = $(c.cardId);
    const icon = $(c.iconId);
    const detail = $(c.detailId);
    if (arr.length === 0) {
      card.className = 'constraint-card pass';
      icon.textContent = '✅';
      detail.textContent = c.passMsg;
    } else {
      card.className = 'constraint-card fail';
      icon.textContent = '❌';
      detail.textContent = c.failMsg(arr.length);
      allPass = false;
    }
  }

  const summary = $('constraintSummary');
  if (allPass) {
    summary.className = 'constraint-summary all-pass';
    summary.textContent = `All 4 hard constraints satisfied · ${placed}/${total} sessions placed`;
  } else {
    summary.className = 'constraint-summary has-fail';
    summary.textContent = `${hc.total_violations} violation(s) detected · ${placed}/${total} sessions placed`;
  }
}

async function loadTimetable() {
  const params = new URLSearchParams();
  for (const [id, key] of [['facultyFilter','faculty'], ['programFilter','program'], ['yearFilter','year']]) {
    const value = $(id).value;
    if (value && value !== 'all') params.set(key, value);
  }
  const data = await api('/api/timetable/?' + params.toString());
  
  const dayOrder = { 'MON': 1, 'TUE': 2, 'WED': 3, 'THU': 4, 'FRI': 5 };
  
  entries = (data.entries || []).sort((a, b) => {
    const dayA = dayOrder[a.dayCode] || 99;
    const dayB = dayOrder[b.dayCode] || 99;
    if (dayA !== dayB) return dayA - dayB;
    if (a.period !== b.period) return a.period - b.period;
    return a.room.localeCompare(b.room);
  });
  
  renderTable();
}

$('loadStaticBtn').onclick = async () => {
  try {
    setMessage('Loading static data...');
    const data = await api('/api/load-static-data/', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
    setMessage(data.message || 'Static data loaded.');
    await loadMetadata();
  } catch (e) { setMessage(e.message, 'bad'); }
};

$('uploadBtn').onclick = async () => {
  const file = $('courseFile').files[0];
  if (!file) return $('uploadResult').innerHTML = '<span class="bad">Select an Excel file first.</span>';
  const form = new FormData();
  form.append('file', file);
  try {
    $('uploadResult').innerHTML = 'Uploading and parsing...';
    // Clear old timetable before uploading new file
    await fetch('/api/timetable/clear/', {method:'DELETE'});
    entries = [];
    hasGenerated = false;
    renderTable();
    setMessage('');
    $('constraintPanel').classList.add('hidden');
    $('progressContainer').classList.add('hidden');
    const data = await api('/api/upload/', {method:'POST', body:form});
    currentUploadSessionId = data.upload_session_id;
    $('uploadResult').innerHTML = `<span class="ok">Parsed ${data.preview.length} offerings from ${data.total_rows} rows. Ready to generate.</span>`;
  } catch (e) { $('uploadResult').innerHTML = `<span class="bad">${e.message}</span>`; }
};

// ---------------------------------------------------------------------------
// Progress bar controller
// ---------------------------------------------------------------------------
const PHASES = [
  { at: 0,  label: 'Initializing solver...' },
  { at: 8,  label: 'Building constraint domains...' },
  { at: 18, label: 'Pass 1 — Greedy placement...' },
  { at: 40, label: 'Pass 2 — Retry unplaced tasks...' },
  { at: 58, label: 'Pass 3 — Swap repair...' },
  { at: 72, label: 'Running additional restarts...' },
  { at: 85, label: 'Validating hard constraints...' },
  { at: 92, label: 'Saving to database...' },
];

let progressTimer = null;
let progressStart = 0;
let elapsedTimer = null;

function startProgress() {
  const container = $('progressContainer');
  container.classList.remove('hidden', 'done');
  const fill = $('progressFill');
  const glow = $('progressGlow');
  fill.style.width = '0%';
  glow.style.width = '0%';
  $('progressPercent').textContent = '0%';
  $('progressPhase').textContent = PHASES[0].label;
  $('progressElapsed').textContent = '0s elapsed';
  $('progressLabel').textContent = 'Generating timetable...';

  progressStart = Date.now();
  let pct = 0;

  // Elapsed time counter
  elapsedTimer = setInterval(() => {
    const s = Math.floor((Date.now() - progressStart) / 1000);
    $('progressElapsed').textContent = `${s}s elapsed`;
  }, 500);

  // Simulated progress — ramps quickly at first, then slows down (never exceeds 95%)
  progressTimer = setInterval(() => {
    const elapsed = (Date.now() - progressStart) / 1000;
    // Asymptotic curve: approaches 95% over ~90s
    const target = 95 * (1 - Math.exp(-elapsed / 25));
    pct = Math.min(pct + (target - pct) * 0.15, 95);
    const rounded = Math.round(pct);

    fill.style.width = rounded + '%';
    glow.style.width = rounded + '%';
    $('progressPercent').textContent = rounded + '%';

    // Update phase label
    let phase = PHASES[0].label;
    for (const p of PHASES) {
      if (rounded >= p.at) phase = p.label;
    }
    $('progressPhase').textContent = phase;
  }, 300);
}

function finishProgress(success, actualTimeMs = null) {
  clearInterval(progressTimer);
  clearInterval(elapsedTimer);
  progressTimer = null;
  elapsedTimer = null;

  const container = $('progressContainer');
  const fill = $('progressFill');
  const glow = $('progressGlow');
  
  let elapsedStr = '';
  if (actualTimeMs !== null) {
    elapsedStr = (actualTimeMs / 1000).toFixed(1) + 's';
  } else {
    const elapsed = Math.floor((Date.now() - progressStart) / 1000);
    elapsedStr = elapsed + 's';
  }

  fill.style.width = '100%';
  glow.style.width = '100%';
  $('progressPercent').textContent = '100%';
  $('progressElapsed').textContent = `${elapsedStr} elapsed`;

  if (success) {
    container.classList.add('done');
    $('progressLabel').textContent = 'Generation complete!';
    $('progressPhase').textContent = 'All phases finished successfully.';
  } else {
    $('progressLabel').textContent = 'Generation failed';
    $('progressPhase').textContent = 'An error occurred during generation.';
  }
}

// ---------------------------------------------------------------------------

$('generateBtn').onclick = async () => {
  const btn = $('generateBtn');
  btn.disabled = true;
  btn.textContent = 'Generating...';
  startProgress();
  try {
    setMessage('');
    const payload = {
      upload_session_id: currentUploadSessionId,
      faculty: $('facultyFilter').value,
      program: $('programFilter').value,
      year: $('yearFilter').value,
    };
    const data = await api('/api/generate/', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    finishProgress(true, data.generation_time_ms);

    const hc = data.hard_constraints || {};
    const placed = data.placed_tasks || 0;
    const total = data.total_tasks || 0;

    let msg = `Generated ${data.entries_generated} entries (${placed}/${total} sessions). Time: ${data.generation_time_ms} ms.`;
    if (hc.satisfied) {
      msg += '<br><strong style="color:#047857">✅ All 4 hard constraints satisfied!</strong>';
      setMessage(msg, 'ok');
    } else {
      msg += `<br><strong style="color:#dc2626">⚠️ ${hc.total_violations} constraint violation(s) detected.</strong>`;
      setMessage(msg, 'warn');
    }

    updateConstraintPanel(hc, placed, total);
    hasGenerated = true;
    await loadTimetable();
  } catch (e) {
    finishProgress(false);
    setMessage(e.message, 'bad');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Generate Timetable';
  }
};

$('clearBtn').onclick = async () => {
  try {
    const res = await fetch('/api/timetable/clear/', {method:'DELETE'});
    const data = await res.json();
    setMessage(data.message || 'Cleared timetable.');
    entries = [];
    renderTable();
    $('constraintPanel').classList.add('hidden');
    $('progressContainer').classList.add('hidden');
  } catch (e) { setMessage(e.message, 'bad'); }
};

['facultyFilter', 'programFilter', 'yearFilter'].forEach(id => $(id).addEventListener('change', () => { if (hasGenerated) loadTimetable(); }));
$('searchBox').addEventListener('input', renderTable);

// On startup: load metadata only, clear any old timetable, show empty table
loadMetadata().then(async () => {
  await fetch('/api/timetable/clear/', {method:'DELETE'});
  entries = [];
  renderTable();
}).catch(e => setMessage(e.message, 'bad'));
