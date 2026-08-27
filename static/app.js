const state = {
  role: localStorage.getItem('nightingale-role') || 'clinician',
  data: null,
  filter: 'all',
  modal: null,
  focus: null,
  loading: true,
};

const ROLE_COPY = {
  clinician: { eyebrow: 'Clinical review workspace', title: 'A clearer story, before the visit', subtitle: 'The care team’s shared memory, distilled into the next safe action.' },
  staff: { eyebrow: 'Care coordination workspace', title: 'Handoffs without the scavenger hunt', subtitle: 'See what changed, what is waiting, and where to close the loop.' },
  patient: { eyebrow: 'Your care companion', title: 'Your care, in one calm place', subtitle: 'A plain-language snapshot of what your care team has shared with you.' },
  admin: { eyebrow: 'Clinic oversight workspace', title: 'A trustworthy view across the clinic', subtitle: 'Review access, decisions, and care-team activity without reading every note.' },
};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
}

function formatDate(value, withTime = true) {
  if (!value) return '';
  const date = new Date(value);
  return new Intl.DateTimeFormat('en-SG', withTime ? { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' } : { day: '2-digit', month: 'short', year: 'numeric' }).format(date);
}

function roleLabel(role) {
  return ({ system: 'AI scribe', staff: 'Staff', clinician: 'Clinician', patient: 'Patient' }[role] || role);
}

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', 'X-Demo-Role': state.role, ...(options.headers || {}) };
  const response = await fetch(path, { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body.error || `Request failed (${response.status})`);
    error.payload = body;
    error.status = response.status;
    throw error;
  }
  return body;
}

async function loadCareNote() {
  state.loading = true;
  render();
  try {
    state.data = await api('/api/care-note');
  } catch (error) {
    showToast(error.message, true);
  } finally {
    state.loading = false;
    render();
  }
}

function showToast(message, error = false) {
  const region = document.getElementById('toast-region');
  if (!region) return;
  const toast = document.createElement('div');
  toast.className = `toast${error ? ' error' : ''}`;
  toast.textContent = message;
  region.appendChild(toast);
  setTimeout(() => toast.remove(), 3800);
}

function patientHeader() {
  const patient = state.data.patient;
  return `<section class="patient-header">
    <span class="avatar avatar-teal">${escapeHtml(patient.initials)}</span>
    <div>
      <div class="patient-name"><h2>${escapeHtml(patient.name)}</h2><span class="verified-chip">✓ identity matched</span></div>
      <div class="patient-meta">${patient.age} years · ${escapeHtml(patient.pronouns)} <span>•</span> ${escapeHtml(patient.mrn_masked)} <span>•</span> ${patient.conditions.map(escapeHtml).join(' · ')}</div>
    </div>
    <div class="header-stats">
      <div class="header-stat"><strong>${state.data.highlights.length || '—'}</strong><small>attention signals</small></div>
      <div class="header-stat"><strong>${state.data.tasks.filter((task) => task.status === 'open').length}</strong><small>open loops</small></div>
      <div class="header-stat"><strong>${escapeHtml(patient.next_appointment.split(' · ')[0])}</strong><small>next review</small></div>
    </div>
  </section>`;
}

function intro() {
  const copy = ROLE_COPY[state.role];
  const p = state.data.permissions;
  return `<div class="page-intro">
    <div><div class="eyebrow-main">${copy.eyebrow}</div><h1>${copy.title}</h1><p>${copy.subtitle}</p></div>
    <div class="intro-actions">
      ${p.can_capture_voice ? '<button class="secondary-button" data-action="voice"><span>◉</span> Capture consult</button>' : ''}
      ${p.can_add_staff_note || p.can_add_clinician_note || p.can_add_patient_insight ? '<button class="primary-button" data-action="compose"><span>＋</span> Add to care note</button>' : ''}
      ${p.can_view_audit ? '<button class="secondary-button" data-action="audit"><span>≡</span> Audit trail</button>' : ''}
    </div>
  </div>`;
}

function renderClinicalGlance() {
  const highlights = state.data.highlights;
  const top = highlights[0];
  const openTasks = state.data.tasks.filter((task) => task.status === 'open');
  return `<section class="glance-grid">
    <article class="card glance-card">
      <div class="card-head"><div class="card-title"><span class="spark">✦</span> What matters now</div><span class="card-subtle">10-second view</span></div>
      ${top ? `<div class="glance-primary">
        <div class="priority-row"><span class="priority-label"><i></i> Priority signal · ${escapeHtml(top.risk_level)} risk</span><span class="score-pill">${top.importance_score} / 100</span></div>
        <h3>${escapeHtml(top.title)} needs human review</h3>
        <p>${escapeHtml(top.risk_reason)} This is linked to a source span, not a free-floating AI claim.</p>
        <div class="primary-footer"><span></span>${escapeHtml(top.source_label)} <button class="text-button" data-jump-entry="${escapeHtml(top.entry_id)}" data-jump-quote="${escapeHtml(top.provenance_pointer.quote)}">Open source ↗</button></div>
      </div><div class="delta-strip"><div><small>Since last review</small><strong>BP still above target</strong></div><div><small>New context</small><strong>2 doses missed</strong></div><div><small>Waiting on</small><strong>ECG confirmation</strong></div></div>` : '<div class="empty-state">No attention signal is available for this role view.</div>'}
      <div class="highlight-list">${highlights.slice(0, 3).map((highlight, index) => renderHighlight(highlight, index + 1)).join('')}</div>
    </article>
    <article class="card task-card"><div class="card-head"><div class="card-title"><span class="spark">⌁</span> Open loops</div><span class="card-subtle">${openTasks.length} to close</span></div>
      <div class="task-list">${state.data.tasks.map(renderTask).join('') || '<div class="empty-state">Nothing waiting here.</div>'}<div class="task-summary"><span>Care-team momentum</span><strong>${state.data.tasks.length - openTasks.length}/${state.data.tasks.length || 0}</strong></div></div>
    </article>
    <article class="card trust-card"><div class="card-head"><div class="card-title"><span class="spark">⌘</span> Trust ledger</div><span class="card-subtle">Why this surfaced</span></div>
      <div class="trust-body"><div class="trust-callout"><strong>Human judgment stays in the loop</strong><p>${escapeHtml(state.data.learning.message)}</p></div>
        <div class="trust-rule"><span class="rule-check">✓</span><div><strong>Safety floors</strong><small>Chest symptoms, allergies and unresolved actions cannot be learned away.</small></div></div>
        <div class="trust-rule"><span class="rule-check">✓</span><div><strong>Evidence-linked</strong><small>Every suggestion carries a source entry, exact span and short reason.</small></div></div>
        <div class="trust-rule"><span class="rule-check">✓</span><div><strong>Learning signal</strong><small>${state.data.learning.accepted_count} accepted pattern${state.data.learning.accepted_count === 1 ? '' : 's'}; no silent auto-publishing.</small></div></div>
      </div>
    </article>
  </section>`;
}

function renderPatientGlance() {
  const patient = state.data.patient;
  const instructions = patient.patient_instructions || [];
  return `<section class="patient-glance">
    <article class="patient-welcome"><div class="eyebrow-main" style="color:#a7e4d9">SHARED WITH YOU</div><h2>Hi ${escapeHtml(patient.name.split(' ')[0])}, here is what to bring forward.</h2><p>${escapeHtml(patient.patient_summary)}</p><span class="gentle-note">◌ This page shows care-team approved updates only</span></article>
    <article class="card patient-next"><h3>Your next step</h3><div class="next-date"><span class="calendar-mark">07</span><div><strong>${escapeHtml(patient.next_appointment)}</strong><small>Harbour Clinic · bring your BP log</small></div></div><div class="patient-booklet" style="margin-top:14px"><h4>Visit prep booklet</h4><ul>${instructions.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div></article>
  </section>`;
}

function renderHighlight(highlight, index) {
  const status = highlight.status;
  return `<div class="highlight-row" data-highlight-id="${escapeHtml(highlight.id)}">
    <span class="highlight-number">0${index}</span><div><h4>${escapeHtml(highlight.title)} <span class="role-badge ${highlight.source_type.includes('ai_') ? 'ai' : 'clinician'}">${highlight.source_type.includes('ai_') ? 'AI' : 'note'}</span></h4><p>${escapeHtml(highlight.risk_reason)}</p><div class="highlight-meta"><span class="score-track"><i style="width:${highlight.importance_score}%"></i></span><span>${highlight.importance_score}</span><span>·</span><button class="source-link" data-jump-entry="${escapeHtml(highlight.entry_id)}" data-jump-quote="${escapeHtml(highlight.provenance_pointer.quote)}">${escapeHtml(highlight.source_label)}</button></div></div>
    <div>${status === 'suggested' && state.role !== 'admin' ? `<div class="decision-buttons"><button class="mini-decision" data-decision="accepted" data-highlight="${escapeHtml(highlight.id)}">Keep</button><button class="mini-decision" data-decision="rejected" data-highlight="${escapeHtml(highlight.id)}">Dismiss</button></div>` : `<span class="approval-badge ${status === 'accepted' ? 'approved' : ''}">${status === 'accepted' ? '✓ kept' : 'dismissed'}</span>`}</div>
  </div>`;
}

function renderTask(task) {
  return `<div class="task-item ${task.status === 'done' ? 'done' : ''}"><button class="task-checkbox" data-task="${escapeHtml(task.id)}" aria-label="Mark task ${task.status === 'done' ? 'open' : 'done'}">${task.status === 'done' ? '✓' : ''}</button><div><strong>${escapeHtml(task.title)}</strong><small>${escapeHtml(task.due)} · ${escapeHtml(task.owner_name)}</small></div><span class="owner-tag ${escapeHtml(task.owner_role)}">${escapeHtml(task.owner_role)}</span></div>`;
}

function renderContent(entry) {
  const text = entry.content || '';
  if (!state.focus || state.focus.entryId !== entry.id || !state.focus.quote) return escapeHtml(text);
  const index = text.toLowerCase().indexOf(state.focus.quote.toLowerCase());
  if (index < 0) return escapeHtml(text);
  return `${escapeHtml(text.slice(0, index))}<mark>${escapeHtml(text.slice(index, index + state.focus.quote.length))}</mark>${escapeHtml(text.slice(index + state.focus.quote.length))}`;
}

function filteredTimeline() {
  const items = state.data.timeline || [];
  if (state.filter === 'all') return items;
  if (state.filter === 'ai') return items.filter((entry) => entry.author_role === 'system' && entry.type.includes('ai_'));
  if (state.filter === 'notes') return items.filter((entry) => ['staff', 'clinician', 'patient'].includes(entry.author_role));
  return items.filter((entry) => entry.author_role === 'system' && !entry.type.includes('ai_'));
}

function renderEntry(entry) {
  const roleClass = entry.author_role === 'system' ? (entry.type.includes('ai_') ? 'ai' : 'system') : entry.author_role;
  const ai = entry.author_role === 'system' && entry.type.includes('ai_');
  const comments = state.role !== 'patient' && entry.can_comment ? `<button class="entry-action" data-comments="${escapeHtml(entry.id)}">▱ Comment</button>` : '';
  const history = entry.can_view_history ? `<button class="entry-action" data-history="${escapeHtml(entry.id)}">↺ History</button>` : '';
  const edit = entry.can_edit ? `<button class="entry-action" data-edit="${escapeHtml(entry.id)}">✎ Edit</button>` : '';
  const aiBadge = ai ? `<span class="approval-badge">AI-generated · verify</span>` : (entry.patient_visible ? (entry.patient_approved ? '<span class="approval-badge approved">✓ patient-safe copy</span>' : '<span class="approval-badge">Needs human sign-off</span>') : '');
  const snippets = Object.entries(entry.sections || {}).slice(0, 2).map(([label, value]) => `<div class="snippet"><small>${escapeHtml(label.replaceAll('_', ' '))}</small><span>${escapeHtml(value)}</span></div>`).join('');
  return `<article id="entry-${escapeHtml(entry.id)}" class="entry ${roleClass}" data-entry="${escapeHtml(entry.id)}">
    <div class="entry-top"><div><div class="entry-title"><h3>${escapeHtml(entry.title)}</h3><span class="role-badge ${roleClass}">${escapeHtml(entry.author_label || roleLabel(entry.author_role))}</span><span class="type-badge">${escapeHtml(entry.type_label || entry.type)}</span>${aiBadge}</div><div class="entry-byline"><span>${escapeHtml(entry.source_label)}</span><span class="dot"></span><span>${escapeHtml(entry.confidence_label || '')}</span></div></div><span class="entry-time">${formatDate(entry.created_at)}</span></div>
    <p class="entry-content">${renderContent(entry)}</p>
    ${snippets ? `<div class="section-snippets">${snippets}</div>` : ''}
    ${ai ? `<div class="ai-disclaimer">Generated from ${escapeHtml(entry.provenance_kind || 'source')} · original source: ${escapeHtml(entry.source_id)} · no diagnosis is asserted</div>` : ''}
    <div class="entry-tags">${(entry.tags || []).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}</div>
    <div class="entry-bottom"><button class="entry-action source" data-jump-entry="${escapeHtml(entry.id)}">⌁ Source of truth</button>${comments}${history}${edit}${entry.can_approve_patient_copy ? `<button class="entry-action" data-approve-entry="${escapeHtml(entry.id)}">✓ Approve patient copy</button>` : ''}<span class="entry-source"><span class="provenance-icon">↗</span>${entry.version ? `v${entry.version}` : ''}</span></div>
  </article>`;
}

function renderTimeline() {
  const entries = filteredTimeline();
  return `<section class="card timeline-card" id="timeline">
    <div class="timeline-head"><div><h2>Longitudinal timeline</h2><p>One continuous story · ${state.data.timeline.length} entries · provenance stays attached</p></div><button class="secondary-button" data-action="info">What is shown?</button></div>
    <div class="timeline-tabs">${[['all', 'All context'], ['ai', 'AI-scribed'], ['notes', 'Human notes'], ['activity', 'System activity']].map(([key, label]) => `<button class="timeline-tab ${state.filter === key ? 'active' : ''}" data-filter="${key}">${label}</button>`).join('')}</div>
    <div class="entry-list">${entries.length ? entries.map(renderEntry).join('') : '<div class="empty-state">No entries in this view.</div>'}</div>
  </section>`;
}

function renderSideRail() {
  const patient = state.data.patient;
  return `<aside class="side-stack">
    <article class="card side-card"><h3>Care team</h3><p>Small handoffs are visible; internal comments stay role-scoped.</p>
      <div class="team-row"><span class="avatar avatar-navy">AP</span><div><strong>Dr. Arjun Patel</strong><small>Clinician · owner of plan</small></div><span class="team-status">online</span></div>
      <div class="team-row"><span class="avatar avatar-teal">LO</span><div><strong>Lena Ortiz, RN</strong><small>Staff · follow-up owner</small></div><span class="team-status">today</span></div>
      <div class="team-row"><span class="avatar avatar-yellow">MC</span><div><strong>${escapeHtml(patient.name)}</strong><small>Patient · shared insights</small></div><span class="team-status">portal</span></div>
    </article>
    <article class="card side-card"><h3>Signal hygiene</h3><p>Numbers explain attention, never replace clinical judgment.</p><div class="metric-band"><div class="metric-box"><strong>${state.data.warm_path_ms}ms</strong><small>warm glance path</small></div><div class="metric-box"><strong>100%</strong><small>source-linked signals</small></div></div><div class="structured-snapshot"><div><span>Blood pressure</span><strong>149 / 92</strong><em>above target</em></div><div><span>Allergy</span><strong>Penicillin</strong><em class="verified-text">verified</em></div></div><div class="safety-list"><div class="safety-item"><b>↳</b><span>High-risk phrases get a deterministic floor.</span></div><div class="safety-item"><b>↳</b><span>Medium confidence means “review,” not “safe.”</span></div><div class="safety-item"><b>↳</b><span>Patient copy requires an approved human surface.</span></div></div></article>
    <article class="card side-card"><h3>Patient-ready prep</h3><p>Make the next visit shorter before it starts.</p><div class="patient-booklet"><h4>Bring this booklet</h4><ul>${(patient.patient_instructions || []).map((instruction) => `<li>${escapeHtml(instruction)}</li>`).join('')}</ul></div></article>
  </aside>`;
}

function render() {
  const workspace = document.getElementById('workspace');
  const roleSelect = document.getElementById('role-select');
  if (roleSelect) roleSelect.value = state.role;
  const actor = {
    clinician: ['AP', 'Arjun Patel', 'Clinician · Harbour'],
    staff: ['LO', 'Lena Ortiz', 'Staff / nurse · Harbour'],
    patient: ['MC', 'Maya Chen', 'Patient · Harbour'],
    admin: ['HA', 'Harbour admin', 'Admin · Harbour'],
  }[state.role];
  if (actor) {
    const avatar = document.getElementById('actor-avatar');
    const name = document.getElementById('actor-name');
    const actorRole = document.getElementById('actor-role');
    if (avatar) avatar.textContent = actor[0];
    if (name) name.textContent = actor[1];
    if (actorRole) actorRole.textContent = actor[2];
  }
  if (!workspace) return;
  if (state.loading || !state.data) {
    workspace.innerHTML = '<div class="card empty-state" style="margin-top:40px">Opening the shared care note…</div>';
    return;
  }
  workspace.innerHTML = `${intro()}${patientHeader()}${state.role === 'patient' ? renderPatientGlance() : renderClinicalGlance()}<div class="content-grid">${renderTimeline()}${renderSideRail()}</div>`;
}

function openModal(content, wide = false) {
  state.modal = true;
  document.getElementById('modal-root').innerHTML = `<div class="modal-backdrop" data-close-modal><div class="modal ${wide ? 'wide' : ''}" role="dialog" aria-modal="true">${content}</div></div>`;
}

function closeModal() {
  state.modal = null;
  document.getElementById('modal-root').innerHTML = '';
}

function composerModal() {
  const canStaff = state.data.permissions.can_add_staff_note;
  const canClinician = state.data.permissions.can_add_clinician_note;
  const canPatient = state.data.permissions.can_add_patient_insight;
  const options = [canStaff ? '<option value="staff_note">Staff note · internal handoff</option>' : '', canClinician ? '<option value="clinician_note">Clinician note · internal clinical context</option>' : '', canPatient ? '<option value="patient_insight">Patient insight · shared with care team</option>' : ''].join('');
  openModal(`<div class="modal-head"><div><h2>Add to the shared care note</h2><p>Write once; let the role policy decide who can see it.</p></div><button class="modal-close" data-close-modal>×</button></div><form class="modal-body form-grid" id="composer-form"><label class="form-label">Entry type<select name="type">${options}</select></label><label class="form-label">Title<input name="title" placeholder="e.g. Follow-up coordination" maxlength="90" /></label><label class="form-label">Note content<textarea name="content" required placeholder="Keep the source and next action clear. Use @mentions for handoffs."></textarea></label><div class="form-hint">This creates an immutable source entry with an audit event. Internal notes never appear in patient view.</div><div class="modal-actions"><button type="button" class="secondary-button" data-close-modal>Cancel</button><button class="primary-button">Add entry</button></div></form>`);
}

function editModal(entryId) {
  const entry = state.data.timeline.find((item) => item.id === entryId);
  if (!entry) return;
  const sections = Object.keys(entry.sections || {});
  const initialSection = sections[0] || '';
  const value = initialSection ? entry.sections[initialSection] : entry.content;
  openModal(`<div class="modal-head"><div><h2>Edit a role-owned section</h2><p>${escapeHtml(entry.title)} · current version ${entry.version}</p></div><button class="modal-close" data-close-modal>×</button></div><form class="modal-body form-grid" id="edit-form" data-entry="${escapeHtml(entryId)}"><label class="form-label">Section<select name="section">${sections.map((section) => `<option value="${escapeHtml(section)}">${escapeHtml(section.replaceAll('_', ' '))}</option>`).join('')}</select></label><label class="form-label">Updated text<textarea name="content" required>${escapeHtml(value)}</textarea></label><div class="form-hint">If another person changes this same section first, Nightingale keeps the latest server version and asks you to compare. Different sections merge safely.</div><div class="modal-actions"><button type="button" class="secondary-button" data-close-modal>Cancel</button><button class="primary-button">Save v${entry.version + 1}</button></div></form>`);
  const select = document.querySelector('#edit-form select');
  select.addEventListener('change', () => {
    const current = state.data.timeline.find((item) => item.id === entryId);
    document.querySelector('#edit-form textarea').value = current.sections[select.value] || current.content;
  });
}

async function commentsModal(entryId) {
  try {
    const result = await api(`/api/entries/${encodeURIComponent(entryId)}/comments`);
    const entry = state.data.timeline.find((item) => item.id === entryId);
    const comments = result.items || [];
    openModal(`<div class="modal-head"><div><h2>Threaded handoff</h2><p>${escapeHtml(entry?.title || 'Timeline entry')} · mentions notify the next owner</p></div><button class="modal-close" data-close-modal>×</button></div><div class="modal-body"><div>${comments.length ? comments.map((comment) => `<div class="comment-item"><div class="comment-meta"><strong>${escapeHtml(roleLabel(comment.author_role))}</strong><span>·</span><span>${formatDate(comment.created_at)}</span><span class="approval-badge ${comment.status === 'open' ? '' : 'approved'}">${comment.status}</span><button class="text-button" style="margin-left:auto" data-toggle-comment="${escapeHtml(comment.id)}" data-comment-entry="${escapeHtml(entryId)}">${comment.status === 'open' ? 'Resolve' : 'Unresolve'}</button></div><p>${escapeHtml(comment.body).replace(/(@[A-Za-z][A-Za-z0-9_.-]*)/g, '<span class="mention">$1</span>')}</p></div>`).join('') : '<div class="no-comments">No comments yet. Add the smallest useful handoff.</div>'}</div><form class="form-grid" id="comment-form" data-entry="${escapeHtml(entryId)}"><label class="form-label">New comment<textarea name="body" required placeholder="e.g. @clinician I confirmed the slot…"></textarea></label><label class="form-label">Assign to<select name="assigned_to"><option value="">No assignment</option><option value="cl-dr-patel">Dr. Arjun Patel</option><option value="st-lena">Lena Ortiz, RN</option></select></label><div class="modal-actions"><button type="button" class="secondary-button" data-close-modal>Close</button><button class="primary-button">Post comment</button></div></form></div>`);
  } catch (error) { showToast(error.message, true); }
}

async function historyModal(entryId) {
  try {
    const result = await api(`/api/entries/${encodeURIComponent(entryId)}/versions`);
    const entry = state.data.timeline.find((item) => item.id === entryId);
    const versions = [...(result.versions || [])].reverse();
    openModal(`<div class="modal-head"><div><h2>Revision history</h2><p>${escapeHtml(entry?.title || '')} · full snapshots, metadata-only audit log</p></div><button class="modal-close" data-close-modal>×</button></div><div class="modal-body">${versions.map((version) => `<div class="version-row"><div class="version-top"><strong>Version ${version.version}${version.version === result.current_version ? ' · current' : ''}</strong><small>${escapeHtml(roleLabel(version.actor_role))} · ${formatDate(version.created_at)}</small></div><pre class="version-diff">${escapeHtml((version.diff || []).join('\n') || 'Initial snapshot · no prior diff')}</pre>${version.version !== result.current_version ? `<div style="margin-top:7px"><button class="secondary-button" data-revert-entry="${escapeHtml(entryId)}" data-revert-version="${version.version}">Revert to v${version.version}</button></div>` : ''}</div>`).join('')}</div>`, true);
  } catch (error) { showToast(error.message, true); }
}

function auditModal() {
  api('/api/audit').then((result) => {
    const items = result.items || [];
    openModal(`<div class="modal-head"><div><h2>Audit trail</h2><p>Who changed what · metadata only · no note content copied into the log</p></div><button class="modal-close" data-close-modal>×</button></div><div class="modal-body">${items.length ? items.slice().reverse().map((item) => `<div class="audit-item"><small>${formatDate(item.timestamp)}</small><div><strong>${escapeHtml(item.action.replaceAll('_', ' '))}</strong><span>${escapeHtml(item.actor_role)} · ${escapeHtml(item.actor_id)} · ${escapeHtml(item.entity_type)} ${escapeHtml(item.entity_id)}</span></div></div>`).join('') : '<div class="empty-state">No audit events yet.</div>'}</div>`, true);
  }).catch((error) => showToast(error.message, true));
}

function voiceModal() {
  openModal(`<div class="modal-head"><div><h2>Ambient consult capture</h2><p>Consent gate · redact first · then derive a source-linked summary</p></div><button class="modal-close" data-close-modal>×</button></div><div class="modal-body"><div class="voice-step"><span class="step-num">1</span><div><strong>Ask for consent</strong><small>Capture is visible to everyone in this demo; no raw audio is uploaded.</small></div></div><div class="voice-step"><span class="step-num">2</span><div><strong>Redact before model processing</strong><small>Names, ID numbers and phones are blocked at the server boundary.</small></div></div><div class="voice-step"><span class="step-num">3</span><div><strong>Keep the transcript as provenance</strong><small>A generated summary points back to this redacted source session.</small></div></div><form class="form-grid" id="voice-form" style="margin-top:14px"><label class="form-label">Interaction type<select name="interaction"><option>Clinical consult</option><option>Nurse consult</option><option>Patient session</option></select></label><label class="form-label">Redacted transcript preview<textarea name="redacted_transcript" required>Speaker 1: Maya reports that chest pressure returned once while climbing stairs. Speaker 2: Care team will review the ECG plan; no diagnosis is made in this session.</textarea></label><div class="form-hint">Synthetic demo policy: raw audio is discarded. The server accepts only this redacted transcript field and records <strong>raw_audio_stored = false</strong>.</div><div class="modal-actions"><button type="button" class="secondary-button" data-close-modal>Cancel</button><button class="primary-button"><span class="recording-dot"></span> Create redacted summary</button></div></form></div>`);
}

function infoModal() {
  openModal(`<div class="modal-head"><div><h2>What is shown here?</h2><p>A compact design contract for the shared record</p></div><button class="modal-close" data-close-modal>×</button></div><div class="modal-body"><div class="trust-rule"><span class="rule-check">01</span><div><strong>Source before summary</strong><small>AI-scribed entries remain distinct. A highlight is only useful when it can jump to the original entry and exact text span.</small></div></div><div class="trust-rule"><span class="rule-check">02</span><div><strong>Risk has a floor</strong><small>Explicit safety phrases and unresolved actions set minimum attention. Learning only changes ranking above that floor.</small></div></div><div class="trust-rule"><span class="rule-check">03</span><div><strong>Patient view is a different surface</strong><small>Patients see approved plain-language updates and prep instructions—not internal comments or raw AI-scribed notes.</small></div></div><div class="trust-rule"><span class="rule-check">04</span><div><strong>Fewer clicks, safer clicks</strong><small>The top card is designed for a glance; deeper evidence is one click away, so speed never requires hiding uncertainty.</small></div></div></div>`);
}

async function submitComposer(form) {
  const payload = Object.fromEntries(new FormData(form).entries());
  try { await api('/api/entries', { method: 'POST', body: JSON.stringify(payload) }); closeModal(); await loadCareNote(); showToast('Entry added to the shared care note.'); }
  catch (error) { showToast(error.message, true); }
}

async function submitEdit(form) {
  const entryId = form.dataset.entry;
  const entry = state.data.timeline.find((item) => item.id === entryId);
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.base_version = entry.version;
  try { await api(`/api/entries/${encodeURIComponent(entryId)}`, { method: 'PATCH', body: JSON.stringify(payload) }); closeModal(); await loadCareNote(); showToast('Saved as a new version; other sections were preserved.'); }
  catch (error) { showToast(error.message + (error.status === 409 ? ' Refresh the source before retrying.' : ''), true); }
}

async function submitComment(form) {
  try { await api(`/api/entries/${encodeURIComponent(form.dataset.entry)}/comments`, { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form).entries())) }); closeModal(); showToast('Comment added; the handoff is now visible to the care team.'); }
  catch (error) { showToast(error.message, true); }
}

async function submitVoice(form) {
  const payload = Object.fromEntries(new FormData(form).entries());
  try { await api('/api/voice-sessions', { method: 'POST', body: JSON.stringify(payload) }); closeModal(); await loadCareNote(); showToast('Redacted AI-scribed entry added with provenance.'); }
  catch (error) { showToast(error.message, true); }
}

async function jumpTo(entryId, quote = '') {
  state.filter = 'all';
  state.focus = { entryId, quote };
  render();
  requestAnimationFrame(() => {
    const element = document.getElementById(`entry-${entryId}`);
    if (element) { element.scrollIntoView({ behavior: 'smooth', block: 'center' }); element.classList.add('source-flash'); setTimeout(() => element.classList.remove('source-flash'), 1800); }
  });
}

document.addEventListener('click', async (event) => {
  const target = event.target.closest('button, [data-close-modal]');
  if (!target) return;
  if (target.hasAttribute('data-close-modal')) { closeModal(); return; }
  if (target.dataset.filter) { state.filter = target.dataset.filter; render(); return; }
  if (target.dataset.jumpEntry) { jumpTo(target.dataset.jumpEntry, target.dataset.jumpQuote || ''); return; }
  if (target.dataset.decision) {
    try { await api(`/api/highlights/${encodeURIComponent(target.dataset.highlight)}/decision`, { method: 'POST', body: JSON.stringify({ decision: target.dataset.decision }) }); await loadCareNote(); showToast(target.dataset.decision === 'accepted' ? 'Signal kept; the importance model learned from this confirmation.' : 'Signal dismissed for this note.'); }
    catch (error) { showToast(error.message, true); }
    return;
  }
  if (target.dataset.task) {
    try { await api(`/api/tasks/${encodeURIComponent(target.dataset.task)}/toggle`, { method: 'POST', body: '{}' }); await loadCareNote(); showToast('Open loop updated.'); }
    catch (error) { showToast(error.message, true); }
    return;
  }
  if (target.dataset.comments) { commentsModal(target.dataset.comments); return; }
  if (target.dataset.toggleComment) {
    try { await api(`/api/comments/${encodeURIComponent(target.dataset.toggleComment)}/toggle`, { method: 'POST', body: '{}' }); await commentsModal(target.dataset.commentEntry); showToast('Comment state updated.'); }
    catch (error) { showToast(error.message, true); }
    return;
  }
  if (target.dataset.history) { historyModal(target.dataset.history); return; }
  if (target.dataset.edit) { editModal(target.dataset.edit); return; }
  if (target.dataset.revertEntry) {
    if (!confirm(`Revert this note to version ${target.dataset.revertVersion}? This creates a new auditable version.`)) return;
    try { await api(`/api/entries/${encodeURIComponent(target.dataset.revertEntry)}/revert`, { method: 'POST', body: JSON.stringify({ target_version: Number(target.dataset.revertVersion) }) }); closeModal(); await loadCareNote(); showToast('Reverted as a new version; the audit trail is intact.'); }
    catch (error) { showToast(error.message, true); }
    return;
  }
  if (target.dataset.approveEntry) {
    try { await api(`/api/entries/${encodeURIComponent(target.dataset.approveEntry)}/approve-patient`, { method: 'POST', body: '{}' }); await loadCareNote(); showToast('Patient-facing copy approved; it is now visible on the patient surface.'); }
    catch (error) { showToast(error.message, true); }
    return;
  }
  if (target.dataset.action === 'compose') { composerModal(); return; }
  if (target.dataset.action === 'voice') { voiceModal(); return; }
  if (target.dataset.action === 'audit') { auditModal(); return; }
  if (target.dataset.action === 'info') { infoModal(); return; }
  if (target.dataset.nav && target.dataset.nav !== 'glance') { showToast(`${target.textContent.trim()} is outside this focused demo.`); return; }
  if (target.id === 'open-command') { openModal(`<div class="modal-head"><div><h2>Quick actions</h2><p>Keep the next useful action one click away.</p></div><button class="modal-close" data-close-modal>×</button></div><div class="modal-body form-grid"><button class="secondary-button" data-action="compose">＋ Add a note</button><button class="secondary-button" data-action="voice">◉ Capture a redacted consult</button><button class="secondary-button" data-action="info">⌘ Read the trust contract</button></div>`); return; }
});

document.addEventListener('submit', (event) => {
  event.preventDefault();
  if (event.target.id === 'composer-form') submitComposer(event.target);
  if (event.target.id === 'edit-form') submitEdit(event.target);
  if (event.target.id === 'comment-form') submitComment(event.target);
  if (event.target.id === 'voice-form') submitVoice(event.target);
});

document.getElementById('role-select').addEventListener('change', (event) => {
  state.role = event.target.value;
  localStorage.setItem('nightingale-role', state.role);
  state.filter = 'all'; state.focus = null;
  loadCareNote();
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && state.modal) closeModal();
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); document.getElementById('open-command')?.click(); }
});

loadCareNote();
// Lightweight live-note refresh for the offline prototype. A production
// clinic would replace this with authenticated SSE/WebSocket invalidations.
setInterval(() => {
  if (!state.modal && !document.hidden) loadCareNote();
}, 30000);
