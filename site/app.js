import {DemoClient, ApiClient} from './demo.js';

const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const short = id => id.slice(0, 8);
const titleCase = value => value.toLowerCase().replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
const status = value => `<span class="status ${esc(value.toLowerCase())}">${esc(titleCase(value))}</span>`;
const age = seconds => { const minutes = Math.max(0, Math.floor((Date.now()/1000 - seconds)/60)); return minutes < 1 ? 'just now' : minutes < 60 ? `${minutes}m ago` : `${Math.floor(minutes/60)}h ago`; };
const lifetime = record => !record.expires_at ? `${record.ttl_minutes}m after apply` : record.status === 'DESTROYED' ? 'Cleaned up' : `${Math.max(0, Math.ceil((record.expires_at - Date.now()/1000)/60))}m remaining`;
const labels = {overview:'Overview', requests:'Sandbox requests', assistant:'Runbook assistant', lab:'Incident lab', audit:'Audit trail', setup:'Integrations & setup'};
let client, runbooks = [], requests = [], metrics = {}, events = [], page = 'overview', filter = 'all', search = '', selectedId = null, lastAnswer = null, lastQuestion = '', createKey = null, createFingerprint = null, backendAvailable = false, repoUrl = '';
const replayResults = {};
let toastTimer;

function toast(message) { $('#toast').textContent = message; $('#toast').classList.add('visible'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 4500); }
function navigate(target) { if (!labels[target]) target = 'overview'; page = target; location.hash = target; document.querySelectorAll('.nav').forEach(n => n.classList.toggle('active', n.dataset.page === target)); $('#page-name').textContent = labels[target]; render(); }
function intro(kicker, title, description, action = '') { return `<div class="page-intro"><div><span class="eyebrow">${kicker}</span><h1>${title}</h1><p class="muted">${description}</p></div>${action || `<span class="date-label">${esc(new Date().toLocaleDateString(undefined, {day:'numeric',month:'long',year:'numeric'}))}</span>`}</div>`; }
function rows(items) {
  return items.length ? items.map(r => `<tr><td><button class="request-name" data-detail="${r.id}">${esc(r.slug)}<small>CD-${short(r.id)}</small></button></td><td>${status(r.status)}</td><td>${esc(lifetime(r))}</td><td><button class="link-button" data-detail="${r.id}">Review ↗</button></td></tr>`).join('') : '<tr><td colspan="4"><div class="empty"><strong>Your next sandbox starts here.</strong>Create a request to review its infrastructure plan.</div></td></tr>';
}
function table(items) { return `<div class="table-wrap"><table><thead><tr><th>SANDBOX</th><th>STATUS</th><th>LIFETIME</th><th>ACTION</th></tr></thead><tbody>${rows(items)}</tbody></table></div>`; }
function overview() {
  const states = metrics.states || {}, pending = states.AWAITING_APPROVAL || 0, active = states.ACTIVE || 0, cleaned = states.DESTROYED || 0;
  const p95 = metrics.p95_provision_seconds;
  return intro('OPERATIONS AT A GLANCE', 'A little less toil. A lot more clarity.', 'Request infrastructure, review the changes, and let the workflow take care of the rest.') +
  `<section class="hero"><div class="hero-copy"><span class="eyebrow">INFRASTRUCTURE, THOUGHTFULLY AUTOMATED</span><h2>Every sandbox has a beginning.<br>And a clean ending.</h2><p>Private storage, explicit approvals, and automatic expiry. A small platform built around the details that matter.</p><button class="hero-link" data-nav="requests">Explore your requests <span>→</span></button></div><div class="hero-graphic" aria-hidden="true"><div class="graphic-card"><span>⇄</span><small>REQUEST</small></div><span class="graphic-dash">···</span><div class="graphic-card middle"><span>✓</span><small>REVIEW</small></div><span class="graphic-dash">···</span><div class="graphic-card"><span>◷</span><small>EXPIRE</small></div></div></section>` +
  `<div class="stats">${[['Awaiting approval',pending,'Ready for a second look','◇'],['Active sandboxes',active,'Scoped access · limited lifetime','▣'],['Cleaned up',cleaned,'Resources with a completed teardown','✓'],['Provisioning p95',p95 === null || p95 === undefined ? '—' : p95,'Measured from approval to active','◷']].map(([label,value,note,icon]) => `<div class="stat"><div class="stat-label">${label}<span>${icon}</span></div><div class="stat-value">${value}${label === 'Provisioning p95' && typeof value === 'number' ? '<small> seconds</small>' : ''}</div><div class="stat-foot">${client.mode === 'demo' && label === 'Provisioning p95' ? 'Run the backend to measure real timings' : note}</div></div>`).join('')}</div>` +
  `<div class="dashboard-grid"><section class="panel"><div class="panel-header"><div><h3>Recent sandbox requests</h3><p>A clear view of what is changing.</p></div><button class="link-button" data-nav="requests">View all →</button></div>${table(requests.slice(0,4))}<div class="workflow">${[['Request','Choose a name and lifetime'],['Plan','Inspect proposed resources'],['Approve','Bind approval to the plan'],['Clean up','Remove expired resources']].map(([name,note],i) => `<div class="workflow-step"><span>${i+1}</span><strong>${name}</strong><p>${note}</p></div>`).join('')}</div><div class="note">✓ Resource changes require approval. Failed applies require a fresh review.</div></section><section class="panel"><div class="panel-header"><div><h3>Workspace activity</h3><p>Small changes, clearly recorded.</p></div><span class="eyebrow">RECENT</span></div><div class="activity">${events.slice(-5).reverse().map(e => `<div class="activity-item"><span class="activity-mark">${e.event.action.includes('ACTIVE') ? '✓' : '↗'}</span><div><strong>${esc(titleCase(e.event.action))}</strong><small>CD-${short(e.request_id)}</small></div><time>${age(e.event.time)}</time></div>`).join('') || '<div class="empty">Your request activity will appear here.</div>'}</div></section></div>` +
  `<div class="quick-grid">${[['assistant','✧','A second pair of eyes','Find checks in your runbooks'],['lab','⚑','Practice the unhappy path','Explore incidents and recovery'],['audit','≡','Follow the evidence','Inspect each request’s history']].map(([nav,icon,title,note]) => `<button class="quick-card" data-nav="${nav}"><span class="quick-icon">${icon}</span><span><strong>${title}</strong><small>${note}</small></span><b>↗</b></button>`).join('')}</div>`;
}
function requestsPage() {
  const filtered = requests.filter(r => (filter === 'all' || r.status === filter) && `${r.slug} ${r.id}`.includes(search.toLowerCase()));
  return intro('SELF-SERVICE INFRASTRUCTURE', 'Your sandboxes, in one place.', 'Review the plan before approving. Every active sandbox has a limited lifetime.') +
  `<section class="panel"><div class="filters"><input id="request-search" aria-label="Search requests" placeholder="Search name or request ID" value="${esc(search)}">${[['all','All requests'],['AWAITING_APPROVAL','Awaiting approval'],['ACTIVE','Active'],['DESTROYED','Cleaned up'],['FAILED','Failed']].map(([value,label]) => `<button class="filter ${filter === value ? 'active' : ''}" data-filter="${value}">${label}</button>`).join('')}</div>${table(filtered)}<div class="note">${filtered.length} requests · ${client.mode === 'demo' ? 'Simulated resources stored in this browser' : 'Authenticated local API results'}</div></section>`;
}
function answerHtml(answer) {
  return `<div class="answer"><span class="config-tag">${esc(answer.mode.replaceAll('_',' '))}</span><p>${esc(answer.answer)}</p>${answer.steps.length ? `<ol>${answer.steps.map(s => `<li>${esc(s.text)} <small>[${esc(s.runbook_id)}]</small></li>`).join('')}</ol><div class="sources">${answer.sources.map(s => `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)} ↗</a>`).join('')}</div>` : ''}</div>`;
}
function assistantPage() {
  return intro('TROUBLESHOOT WITH EVIDENCE', 'A second pair of eyes.', 'Runbook checks with source citations. The assistant cannot approve or execute changes.') +
  `<div class="assistant-layout"><section class="panel assistant-box"><span class="config-tag">${client.mode === 'demo' ? 'BROWSER RUNBOOK SEARCH' : 'LOCAL ASSISTANT API'}</span><form id="assistant-form"><label>What are you investigating?<textarea id="question" required minlength="3" maxlength="1500" placeholder="My S3 sandbox returns AccessDenied. What should I check?">${esc(lastQuestion)}</textarea></label><div class="suggestions">${['S3 access denied','Jenkins pipeline failed','Expired sandbox cleanup failed'].map(q => `<button type="button" class="suggestion" data-question="${q}">${q}</button>`).join('')}</div><button class="button primary" type="submit">Find relevant checks →</button></form><div id="answer-area">${lastAnswer ? answerHtml(lastAnswer) : '<div class="empty"><strong>Start with a symptom.</strong>Answers reference existing runbooks. Missing evidence leads to an explicit abstention.</div>'}</div></section><section class="panel"><div class="panel-header"><div><h3>Runbook library</h3><p>${runbooks.length} focused operational guides</p></div><span>≡</span></div>${runbooks.map(doc => `<a class="runbook-item" href="${esc(doc.source_url)}" target="_blank" rel="noopener noreferrer">${esc(doc.title)}<small>${doc.steps.length} diagnostic checks · primary documentation ↗</small></a>`).join('')}<div class="note">Optional Ollama inference selects existing step IDs. It never invents executable commands.</div></section></div>`;
}
function labPage() {
  const cards = [['duplicate','One request. One sandbox.','Repeat an idempotency key and verify the existing request is reused.'],['unauthorized','The right person, the right role.','Try approving infrastructure with a requester account.'],['failure','A failure is a state, not a dead end.','Inject an apply failure and require another review before retrying.'],['expiry','Clean endings, automatically.','Advance the test clock and verify resource cleanup.'],['cleanup-retry','Recovery deserves a second try.','Inject a transient cleanup failure and exercise the scheduled retry.']];
  return intro('PRACTICE THE UNHAPPY PATH', 'A small lab for useful failures.', client.mode === 'demo' ? 'Browser cards illustrate the tests. Run the backend to execute them against real emulator APIs.' : 'Each replay uses isolated test records and local emulator resources, then cleans them up.') +
  `<div class="lab-grid">${cards.map(([id,title,description],i) => `<section class="panel lab-card"><span class="lab-number">SCENARIO 0${i+1}</span><h3>${title}</h3><p>${description}</p><button class="button secondary small" data-replay="${id}">${client.mode === 'demo' ? 'Explore scenario' : 'Run replay'} →</button><div id="replay-${id}">${replayResults[id] ? replayHtml(replayResults[id]) : ''}</div></section>`).join('')}</div>`;
}
function replayHtml(result) { return `<div class="replay-result"><strong>${result.passed === null ? 'Scenario illustration · not an executed test' : result.passed ? 'All checks passed' : 'A check failed'}</strong><ul>${result.checks.map(c => `<li>${c.passed === null ? '→' : c.passed ? '✓' : '×'} ${esc(c.check)}</li>`).join('')}</ul>${result.duration_ms === null ? '' : `${result.duration_ms} ms · ${esc(result.environment)}`}</div>`; }
function auditPage() {
  return intro('FOLLOW THE EVIDENCE', 'Every change leaves a trail.', client.mode === 'demo' ? 'Simulated activity history. The backend uses a verifiable hash-linked audit chain.' : 'Request events are linked with SHA-256 hashes. This detects edits; it is not an externally anchored, immutable log.') +
  `<section class="panel"><div class="panel-header"><div><h3>Request event history</h3><p>${events.length} visible events</p></div><span class="config-tag">${client.mode === 'demo' ? 'SIMULATED HISTORY' : metrics.audit_chain_valid ? 'HASH CHAIN VERIFIED' : 'CHAIN VERIFICATION FAILED'}</span></div>${events.slice().reverse().map(e => `<div class="audit-row"><div class="avatar">↗</div><div><strong>${esc(titleCase(e.event.action))}</strong><small>CD-${short(e.request_id)} · ${esc(e.event.actor)}</small></div><time>${esc(new Date(e.event.time*1000).toLocaleString())}</time></div>`).join('') || '<div class="empty">Create a request to begin the audit trail.</div>'}</section>`;
}
function setupPage() {
  return intro('RUN IT YOUR WAY', 'Local first. API connected.', 'The default setup needs no cloud account, payment card, or paid model API.') +
  `<div class="setup-grid"><section class="panel setup-card"><span class="config-tag">START HERE</span><h3>Run the complete local backend</h3><p>Python 3.11+ is required. Commands run from the repository root.</p><pre>python -m venv .venv\n# Activate your virtual environment\npython -m pip install -e .\npython scripts/bootstrap.py\npython -m uvicorn clouddesk.app:app --host 127.0.0.1</pre><p>Open <code>http://127.0.0.1:8000</code> and connect with your generated tokens. Moto starts automatically.</p><button class="button secondary small" id="open-connect">Connect local API →</button></section><section class="panel setup-card"><span class="config-tag">SLACK · FREE WORKSPACE</span><h3>Requests where work happens</h3><p>The Socket Mode bridge receives slash commands without exposing a public backend.</p><ol><li>Create an app using the included Slack manifest.</li><li>Add your workspace ID, bot token, app token, and approver IDs to your local .env.</li><li>Run <code>python scripts/slack_socket.py</code>.</li></ol><pre>/clouddesk create analytics-lab duration=30m\n/clouddesk status REQUEST_ID\n/clouddesk approve REQUEST_ID PLAN_DIGEST</pre></section><section class="panel setup-card"><span class="config-tag">JENKINS + TERRAFORM</span><h3>Infrastructure as a reviewed change</h3><p>The optional Jenkins profile runs a real Terraform plan and applies the exact approved saved plan. All endpoints remain local.</p><pre>docker compose --profile jenkins up --build</pre><p>Generate a Jenkins API token, select the Jenkins executor in .env, and restart the app. The repository includes the pipeline and setup guide.</p></section><section class="panel setup-card"><span class="config-tag">OLLAMA · OPTIONAL LOCAL INFERENCE</span><h3>A grounded assistant, on your computer</h3><p>Runbook search works immediately. Enable local inference only after downloading a model your computer can run.</p><pre>ollama pull qwen2.5:1.5b\n# .env\nCLOUDDESK_ASSISTANT_MODE=ollama\nCLOUDDESK_OLLAMA_MODEL=qwen2.5:1.5b</pre><p>The model selects existing diagnostic steps. If unavailable, the response is explicitly labeled as extractive fallback.</p></section><section class="panel setup-card"><span class="config-tag">GITHUB PAGES</span><h3>A recruiter-friendly demonstration</h3><p>The public site demonstrates the workflow entirely in the browser. It does not host Python, Jenkins, or AWS resources.</p><p>The included GitHub Actions workflow tests the backend and publishes the static demonstration to Pages.</p>${repoUrl ? `<a class="button secondary small" href="${esc(repoUrl)}" target="_blank" rel="noopener noreferrer">View source & setup guide ↗</a>` : '<p>See README.md and docs/DEPLOYMENT.md in the project source.</p>'}</section><section class="panel setup-card"><span class="config-tag">SERVICE MANAGEMENT</span><h3>Tickets without a paid dependency</h3><p>The local request API is the working ticket system. An optional ServiceNow adapter syncs records only when you configure your own accessible developer instance.</p><p>The core project does not require or assume a ServiceNow account.</p></section></div>`;
}
function render() { $('#main').innerHTML = ({overview,requests:requestsPage,assistant:assistantPage,lab:labPage,audit:auditPage,setup:setupPage}[page])(); }
function modeUi() {
  const api = client.mode === 'api';
  $('#connection-label').innerHTML = `<span class="online-dot"></span> ${api ? 'Local API connected' : 'Browser demo'}`;
  $('#mode-banner').innerHTML = api ? '<span class="banner-dot"></span><strong>Local backend connected</strong><span>Requests run against your local AWS emulator. No billable cloud endpoints are enabled.</span>' : '<span class="banner-dot"></span><strong>Interactive demonstration</strong><span>Everything here is simulated in your browser. No cloud resources or paid APIs are used.</span>';
  $('#profile-role').textContent = `${api ? 'Local' : 'Demo'} ${client.role}`;
  $('#profile-mode').textContent = api ? 'Authenticated local workspace' : 'Browser demonstration';
  $('#role-button').textContent = `Role: ${client.role}`;
  $('#reset-demo').hidden = api;
}
async function refresh() {
  try {
    requests = await client.list(); metrics = await client.metrics();
    events = (await Promise.all(requests.slice(0,30).map(r => client.history(r.id)))).flat().sort((a,b) => a.event.time - b.event.time);
    $('#pending-count').textContent = metrics.states?.AWAITING_APPROVAL || 0;
    if (['overview','requests','audit'].includes(page) && !$('#request-search')?.matches(':focus')) render();
    if (selectedId && $('#detail-dialog').open) await showDetail(selectedId, false);
  } catch (error) { toast(error.message); }
}
async function showDetail(id, open = true) {
  const record = requests.find(r => r.id === id); if (!record) return;
  selectedId = id; const history = await client.history(id), plan = record.plan;
  $('#detail-content').innerHTML = `<div class="dialog-head"><div><span class="eyebrow">CD-${short(id)}</span><h2>${esc(record.slug)}</h2></div><button type="button" class="icon-button close-dialog" aria-label="Close">×</button></div>${status(record.status)}<div class="detail-meta"><div><small>ENVIRONMENT</small><strong>${client.mode === 'demo' ? 'Browser simulation' : 'Local AWS emulator'}</strong></div><div><small>LIFETIME</small><strong>${esc(lifetime(record))}</strong></div><div><small>OWNER</small><strong>${esc(record.owner)}</strong></div><div><small>PURPOSE</small><strong>${esc(record.reason)}</strong></div></div><h3>Resource plan</h3>${plan ? `<p class="muted">${esc(plan.engine)}</p><ul class="plan-list">${plan.changes.map(c => `<li><span>+</span><code>${esc(c.type)}</code><span>· ${esc(c.action)}</span></li>`).join('')}</ul><div class="callout"><span>✓</span><div><strong>Template controls</strong><p>${esc(plan.controls.join(' · '))}</p></div></div><p class="digest">Approved-plan digest<br>${esc(record.plan_digest)}</p>` : '<p class="muted">Preparing the resource plan…</p>'}${record.resource?.bucket ? `<p class="muted">Bucket: <code>${esc(record.resource.bucket)}</code></p>` : ''}${record.error ? `<p class="error">${esc(record.error)}</p>` : ''}<div class="detail-audit"><h3>Request history</h3>${history.map(e => `<div>${esc(titleCase(e.event.action))} · ${age(e.event.time)}</div>`).join('')}</div><div class="dialog-actions">${record.status === 'AWAITING_APPROVAL' ? `<button class="button secondary" data-action="reject" data-id="${id}" ${client.role !== 'approver' ? 'disabled' : ''}>Reject</button><button class="button primary" data-action="approve" data-id="${id}" data-digest="${esc(record.plan_digest)}" ${client.role !== 'approver' ? 'disabled' : ''}>Approve this plan →</button>` : ''}${['ACTIVE','FAILED','CLEANUP_FAILED'].includes(record.status) ? `<button class="button danger" data-action="destroy" data-id="${id}">Clean up sandbox</button>` : ''}${record.status === 'FAILED' ? `<button class="button primary" data-action="retry" data-id="${id}">Replan for review →</button>` : ''}</div>`;
  if (open && !$('#detail-dialog').open) $('#detail-dialog').showModal();
}

document.addEventListener('click', async event => {
  const button = event.target.closest('button'); if (!button || button.disabled) return;
  if (button.dataset.page || button.dataset.nav) navigate(button.dataset.page || button.dataset.nav);
  if (button.classList.contains('new-request')) { $('#form-error').textContent = ''; $('#request-dialog').showModal(); }
  if (button.classList.contains('close-dialog')) { button.closest('dialog').close(); if (button.closest('dialog').id === 'detail-dialog') selectedId = null; }
  if (button.dataset.detail) { try { await showDetail(button.dataset.detail); } catch (error) { toast(error.message); } }
  if (button.dataset.filter) { filter = button.dataset.filter; render(); }
  if (button.dataset.question) { $('#question').value = button.dataset.question; $('#assistant-form').requestSubmit(); }
  if (button.id === 'connection-button' || button.id === 'open-connect') $('#connection-dialog').showModal();
  if (button.id === 'role-button') {
    const role = client.role === 'approver' ? 'requester' : 'approver';
    if (client.mode === 'api' && !client.credentials[role]) { toast(`Add a ${role} token to switch roles.`); $('#connection-dialog').showModal(); return; }
    client.role = role; modeUi(); await refresh(); render();
  }
  if (button.id === 'reset-demo') { await client.reset(); await refresh(); toast('Demonstration reset.'); }
  if (button.id === 'use-demo') { client.close(); client = await new DemoClient(runbooks).init(); modeUi(); $('#connection-dialog').close(); await refresh(); render(); }
  if (button.dataset.action) {
    button.disabled = true;
    try { await client[button.dataset.action](button.dataset.id, button.dataset.digest); toast('Request updated.'); await refresh(); } catch (error) { toast(error.message); button.disabled = false; }
  }
  if (button.dataset.replay) {
    button.disabled = true; const original = button.textContent; button.textContent = 'Running…';
    try { const result = await client.replay(button.dataset.replay); replayResults[button.dataset.replay] = result; $(`#replay-${button.dataset.replay}`).innerHTML = replayHtml(result); } catch (error) { toast(error.message); }
    finally { button.disabled = false; button.textContent = original; }
  }
});
document.addEventListener('input', event => {
  if (event.target.id === 'request-search') { search = event.target.value; const position = event.target.selectionStart; render(); $('#request-search').focus(); $('#request-search').setSelectionRange(position,position); }
});
document.addEventListener('submit', async event => {
  event.preventDefault(); const form = event.target, button = form.querySelector('[type="submit"]'); if (button) button.disabled = true;
  try {
    if (form.id === 'request-form') {
      const values = new FormData(form), spec = {slug: values.get('slug'), ttl_minutes: Number(values.get('ttl')), reason: values.get('reason')};
      const fingerprint = JSON.stringify(spec); if (fingerprint !== createFingerprint) { createKey = crypto.randomUUID(); createFingerprint = fingerprint; }
      const result = await client.create(spec, createKey); createKey = null; createFingerprint = null; form.reset(); $('#request-dialog').close(); await refresh(); navigate('requests'); toast(`Request CD-${short(result.id)} created.`);
    }
    if (form.id === 'assistant-form') {
      lastQuestion = $('#question').value; $('#answer-area').innerHTML = '<div class="empty">Checking the runbook library…</div>';
      lastAnswer = await client.ask(lastQuestion); $('#answer-area').innerHTML = answerHtml(lastAnswer);
    }
    if (form.id === 'connection-form') {
      if (!backendAvailable) throw new Error('This site is a static demo. Run the backend locally and open http://127.0.0.1:8000 to connect.');
      const values = new FormData(form), credentials = {requester: values.get('requester'), approver: values.get('approver')};
      if (!credentials.requester && !credentials.approver) throw new Error('Enter at least one local API token.');
      for (const role of ['requester','approver']) if (credentials[role]) {
        const probe = new ApiClient(credentials, role); const identity = await probe.call('/me');
        if (identity.role !== role) throw new Error(`The ${role} field contains a token for a different role.`);
      }
      const next = new ApiClient(credentials, credentials.approver ? 'approver' : 'requester'); client.close(); client = next; form.reset(); modeUi(); $('#connection-dialog').close(); await refresh(); render(); toast('Connected to your local API.');
    }
  } catch (error) {
    if (form.id === 'request-form') $('#form-error').textContent = error.message;
    else if (form.id === 'connection-form') $('#connection-error').textContent = error.message;
    else toast(error.message);
  } finally { if (button) button.disabled = false; }
});
window.addEventListener('hashchange', () => { if (page !== location.hash.slice(1)) navigate(location.hash.slice(1)); });
window.addEventListener('beforeunload', () => client?.close());

async function boot() {
  try {
    const response = await fetch('./runbooks.json'); if (!response.ok) throw new Error('Runbook library could not be loaded.'); runbooks = await response.json();
    const config = await fetch('./config.json').then(r => r.ok ? r.json() : {}).catch(() => ({}));
    if (/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(config.repository_url || '')) { repoUrl = config.repository_url; $('#repo-link').href = repoUrl; $('#repo-link').target = '_blank'; $('#repo-link').rel = 'noopener noreferrer'; }
    client = await new DemoClient(runbooks).init(); modeUi(); navigate(location.hash.slice(1) || 'overview'); await refresh();
    if (['127.0.0.1','localhost'].includes(location.hostname)) {
      try { const health = await fetch('/api/health', {signal: AbortSignal.timeout(1800)}); backendAvailable = health.ok && (await health.json()).backend === 'api'; } catch { backendAvailable = false; }
    }
    if (backendAvailable) { toast('Local backend detected. Connect your generated API tokens to use it.'); }
    setInterval(refresh, 3000);
  } catch (error) { $('#main').innerHTML = `<div class="empty"><strong>Could not start CloudDesk</strong>${esc(error.message)}<p>Serve this folder over HTTP; opening index.html directly does not support module loading.</p></div>`; }
}
boot();
