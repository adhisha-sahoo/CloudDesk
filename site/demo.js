const KEY = 'clouddesk-demo-v1';
const now = () => Date.now() / 1000;
const uuid = () => crypto.randomUUID().replaceAll('-', '');
const hash = async value => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))].map(x => x.toString(16).padStart(2, '0')).join('');
const fail = (message, status = 409) => { const error = new Error(message); error.status = status; throw error; };

export class DemoClient {
  constructor(runbooks, storage = globalThis.localStorage) {
    this.runbooks = runbooks;
    this.storage = storage;
    this.role = 'approver';
    this.mode = 'demo';
    try { this.data = JSON.parse(storage?.getItem(KEY) || 'null'); } catch { this.data = null; }
    if (!this.data || this.data.version !== 1) this.data = {version: 1, requests: [], events: [], keys: {}};
    this.timer = setInterval(() => this.expire(), 1000);
  }
  save() { try { this.storage?.setItem(KEY, JSON.stringify(this.data)); } catch { /* Session still works when storage is unavailable. */ } }
  async init() {
    if (!this.data.requests.length) {
      const active = await this.create({slug: 'analytics-lab', ttl_minutes: 30, reason: 'Sample: validate a data ingestion workflow'}, uuid());
      await this.ready(active.id);
      await this.approve(active.id, active.plan_digest);
      const pending = await this.create({slug: 'onboarding-files', ttl_minutes: 60, reason: 'Sample: test an onboarding file workflow'}, uuid());
      await this.ready(pending.id);
    }
    return this;
  }
  event(record, action) { this.data.events.push({request_id: record.id, event: {request_id: record.id, action, actor: `demo-${this.role}`, time: now()}}); this.save(); }
  get(id) { const record = this.data.requests.find(r => r.id === id); if (!record || (this.role === 'requester' && record.owner !== 'demo-requester')) fail('Request not found', 404); return record; }
  async list() { this.expire(); return this.data.requests.filter(r => this.role === 'approver' || r.owner === 'demo-requester').slice().reverse(); }
  async create(spec, key) {
    if (!/^[a-z][a-z0-9-]{2,29}$/.test(spec.slug) || !Number.isInteger(spec.ttl_minutes) || spec.ttl_minutes < 1 || spec.ttl_minutes > 120 || spec.reason.length < 3 || spec.reason.length > 300) fail('Invalid sandbox name, purpose, or lifetime', 422);
    const fingerprint = JSON.stringify(spec);
    if (this.data.keys[key]) { const saved = this.data.keys[key]; if (saved.fingerprint !== fingerprint) fail('This idempotency key belongs to a different request'); return this.get(saved.id); }
    const record = {id: uuid(), slug: spec.slug, ttl_minutes: spec.ttl_minutes, reason: spec.reason, owner: 'demo-requester', created_at: now(), updated_at: now(), status: 'PLANNING', expires_at: null, plan: null, plan_digest: null, resource: null, error: null};
    this.data.requests.push(record); this.data.keys[key] = {id: record.id, fingerprint}; this.event(record, 'REQUEST_CREATED');
    setTimeout(() => this.ready(record.id), 350);
    return record;
  }
  async ready(id) {
    const record = this.data.requests.find(r => r.id === id);
    if (record.status !== 'PLANNING') return record;
    const bucket = `cd-${record.slug}-${id.slice(0, 12)}`;
    record.plan = {engine: 'Browser simulation', bucket, role: `cd-${id}`, environment: 'browser simulation', controls: ['AES256 encryption', 'all public access blocked', 'bucket-scoped IAM policy'], changes: ['aws_s3_bucket', 'aws_s3_bucket_public_access_block', 'aws_s3_bucket_server_side_encryption_configuration', 'aws_iam_role', 'aws_iam_role_policy'].map(type => ({type, name: type.includes('iam') ? `cd-${id}` : bucket, action: 'simulated create'}))};
    record.plan_digest = await hash(JSON.stringify(record.plan)); record.plan.digest = record.plan_digest;
    record.status = 'AWAITING_APPROVAL'; record.updated_at = now(); this.event(record, 'PLAN_READY'); return record;
  }
  async approve(id, digest) {
    if (this.role !== 'approver') fail('An approver account is required', 403);
    const record = this.get(id); if (record.status !== 'AWAITING_APPROVAL') fail('Only a planned request can be approved');
    if (digest !== record.plan_digest) fail('Plan changed; review the current plan');
    record.status = 'ACTIVE'; record.expires_at = now() + record.ttl_minutes * 60; record.updated_at = now();
    record.resource = {bucket: record.plan.bucket, role: record.plan.role, environment: 'browser simulation'};
    this.event(record, 'PLAN_APPROVED'); this.event(record, 'RESOURCE_ACTIVE'); return record;
  }
  async reject(id) {
    if (this.role !== 'approver') fail('An approver account is required', 403);
    const record = this.get(id); if (record.status !== 'AWAITING_APPROVAL') fail('Only a planned request can be rejected');
    record.status = 'REJECTED'; this.event(record, 'REQUEST_REJECTED'); return record;
  }
  async destroy(id) {
    const record = this.get(id); if (record.status === 'DESTROYED') return record;
    if (!['ACTIVE', 'FAILED', 'CLEANUP_FAILED'].includes(record.status)) fail('Request is not ready for cleanup');
    record.status = 'DESTROYED'; record.updated_at = now(); this.event(record, 'RESOURCE_DESTROYED'); return record;
  }
  async retry(id) {
    const record = this.get(id); if (record.status !== 'FAILED') fail('Only a failed request can be replanned');
    record.status = 'PLANNING'; record.error = null; this.event(record, 'REPLAN_REQUESTED'); setTimeout(() => this.ready(id), 350); return record;
  }
  expire() {
    for (const record of this.data.requests) if (record.status === 'ACTIVE' && record.expires_at <= now()) {
      this.event(record, 'TTL_EXPIRED'); record.status = 'DESTROYED'; this.event(record, 'RESOURCE_DESTROYED');
    }
  }
  async history(id) { this.get(id); return this.data.events.filter(e => e.request_id === id); }
  async metrics() {
    const rows = await this.list(), states = {};
    for (const row of rows) states[row.status] = (states[row.status] || 0) + 1;
    return {total: rows.length, states, p95_provision_seconds: null, measured_provisions: 0, audit_chain_valid: null, environment: 'browser simulation'};
  }
  async ask(question) {
    const stop = new Set('a an the is are was were to of for my i me why how what do does can could please help with it on in and or this that not when'.split(' '));
    const words = new Set((question.toLowerCase().match(/[a-z0-9]+/g) || []).filter(w => !stop.has(w)));
    const ranked = this.runbooks.map(doc => ({doc, score: 0}));
    for (const item of ranked) item.score = [...new Set((item.doc.title + ' ' + item.doc.keywords).toLowerCase().match(/[a-z0-9]+/g))].filter(w => words.has(w)).length;
    const docs = ranked.filter(x => x.score >= 2).sort((a, b) => b.score - a.score).slice(0, 2).map(x => x.doc);
    if (!docs.length) return {mode: 'abstained', answer: 'I do not have enough relevant runbook evidence to answer this question.', steps: [], sources: []};
    return {mode: 'browser_extractive', answer: 'These runbook checks can help investigate; they are not a confirmed diagnosis.', steps: docs.flatMap(doc => doc.steps.map(step => ({...step, runbook_id: doc.id}))), sources: docs.map(doc => ({id: doc.id, title: doc.title, url: doc.source_url}))};
  }
  async replay(scenario) {
    const checks = {
      duplicate: ['Same idempotency key returns the existing request', 'Changed payload is rejected with a conflict'],
      unauthorized: ['Requester approval returns forbidden', 'Request remains awaiting approval'],
      failure: ['Injected apply failure is recorded', 'Retry requires a fresh plan and approval'],
      expiry: ['Sandbox reaches expiry', 'Simulated cleanup removes its resources'],
      'cleanup-retry': ['Injected cleanup failure is recorded', 'The scheduled retry succeeds']
    };
    if (!checks[scenario]) fail('Unknown replay', 404);
    // These cards illustrate the backend tests. They are deliberately not measured test results.
    return {scenario, description: 'Browser illustration of the backend test', passed: null, checks: checks[scenario].map(check => ({check, passed: null})), events: [], duration_ms: null, environment: 'browser simulation'};
  }
  close() { clearInterval(this.timer); }
  async reset() { this.data = {version: 1, requests: [], events: [], keys: {}}; this.save(); await this.init(); }
}

export class ApiClient {
  constructor(credentials, role = 'approver') { this.credentials = credentials; this.role = role; this.mode = 'api'; }
  async call(path, method = 'GET', body, extraHeaders = {}) {
    const response = await fetch(`/api${path}`, {method, headers: {Authorization: `Bearer ${this.credentials[this.role] || ''}`, ...(body !== undefined ? {'Content-Type': 'application/json'} : {}), ...extraHeaders}, ...(body !== undefined ? {body: JSON.stringify(body)} : {})});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) fail(typeof data.detail === 'string' ? data.detail : 'The API rejected this request. Check the input and your credentials.', response.status);
    return data;
  }
  list() { return this.call('/requests'); }
  create(spec, key) { return this.call('/requests', 'POST', spec, {'Idempotency-Key': key}); }
  approve(id, digest) { return this.call(`/requests/${id}/approve`, 'POST', {plan_digest: digest}); }
  reject(id) { return this.call(`/requests/${id}/reject`, 'POST', {}); }
  destroy(id) { return this.call(`/requests/${id}/destroy`, 'POST', {}); }
  retry(id) { return this.call(`/requests/${id}/retry`, 'POST', {}); }
  history(id) { return this.call(`/requests/${id}/audit`); }
  metrics() { return this.call('/metrics'); }
  ask(question) { return this.call('/assistant/ask', 'POST', {question}); }
  replay(scenario) { return this.call(`/replays/${scenario}`, 'POST', {}); }
  close() {}
}
