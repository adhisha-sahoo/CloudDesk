import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {webcrypto} from 'node:crypto';
import {DemoClient} from '../site/demo.js';
globalThis.crypto ??= webcrypto;
const runbooks = JSON.parse(await readFile(new URL('../site/runbooks.json', import.meta.url)));
const make = () => new DemoClient(runbooks, {getItem: () => null, setItem: () => {}});
test('browser demonstration protects approvals and duplicate keys', async () => {
  const client = make();
  try {
    const spec = {slug:'browser-test',ttl_minutes:1,reason:'Browser test request'};
    const record = await client.create(spec,'same-key');
    await client.ready(record.id);
    assert.equal((await client.create(spec,'same-key')).id,record.id);
    await assert.rejects(client.create({...spec,ttl_minutes:30},'same-key'));
    client.role = 'requester';
    await assert.rejects(client.approve(record.id,record.plan_digest),error => error.status === 403);
    client.role = 'approver';
    await assert.rejects(client.approve(record.id,'0'.repeat(64)));
    await client.approve(record.id,record.plan_digest);
    assert.equal(record.status,'ACTIVE');
    record.expires_at = 0; client.expire();
    assert.equal(record.status,'DESTROYED');
  } finally {client.close();}
});
test('browser assistant abstains without evidence and never claims LLM inference', async () => {
  const client = make();
  try {
    assert.equal((await client.ask('What is the weather tomorrow?')).mode,'abstained');
    const answer = await client.ask('My S3 access is denied');
    assert.equal(answer.mode,'browser_extractive');
    assert.ok(answer.steps.every(step => runbooks.some(doc => doc.steps.some(item => item.id === step.id && item.text === step.text))));
    assert.equal((await client.replay('expiry')).passed,null);
  } finally {client.close();}
});
