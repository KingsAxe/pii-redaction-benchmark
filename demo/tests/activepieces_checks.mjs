import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const load = async (name) => {
    const source = readFileSync(new URL(`../activepieces/${name}.ts`, import.meta.url), 'utf8');
    return (await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)).code;
};
const create = await load('create_review');
const retrieve = await load('retrieve_output');
const id = 'a'.repeat(32), revision = 'b'.repeat(64);
let calls = [];
globalThis.fetch = async (url, options) => {
    calls.push({url, options});
    return {status: 201, json: async () => ({review_id: id, revision_id: revision, configuration: 'custom_generic'})};
};
const created = await create({text: 'Tiny synthetic fixture'});
assert.equal(calls.length, 1);
assert.deepEqual(JSON.parse(calls[0].options.body), {text: 'Tiny synthetic fixture', synthetic_input: true});
assert.equal(created.review_url, `http://127.0.0.1:8000/?review_id=${id}`);
calls = [];
globalThis.fetch = async (url) => {
    calls.push(url);
    return {status: 200, headers: {get: () => revision}, text: async () => '###\n'};
};
assert.deepEqual(await retrieve({review_id: id, expected_revision: revision}), {review_id: id, revision_id: revision, masked_text: '###\n'});
assert.equal(calls.length, 1);
await assert.rejects(retrieve({review_id: '<script>', expected_revision: revision}));
assert.equal(calls.length, 1); // Invalid IDs never make a request.
for (const reason of ['review_not_approved', 'stale_revision', 'review_rejected']) {
    calls = [];
    globalThis.fetch = async () => {calls.push(1); return {status: 409, json: async () => ({detail: {code: reason, message: 'SYNTHETIC_CANARY'}})};};
    await assert.rejects(retrieve({review_id: id, expected_revision: revision}), new RegExp(reason));
    assert.equal(calls.length, 1); // No action-level retry, even after denial.
}
globalThis.fetch = async () => ({status: 500, json: async () => ({detail: {code: 'SYNTHETIC_CANARY'}})});
await assert.rejects(retrieve({review_id: id, expected_revision: revision}), /request_failed/);
console.log('Activepieces request, identity, output, and no-retry checks passed');
