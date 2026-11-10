// Exercise the actual page controller with DOM/HTTP doubles. This is not a browser screenshot test.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setImmediate as nextTurn} from 'node:timers/promises';

const html = readFileSync(new URL('../static/index.html', import.meta.url), 'utf8');
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
assert.equal(ids.length, new Set(ids).size, 'DOM IDs must be unique');
const downloads = [], blobs = new Map();
class Element {
    constructor() {
        this.value = ''; this.checked = false; this.disabled = false; this.hidden = false;
        this.open = true; this.dataset = {}; this.textContent = ''; this.listeners = {}; this.children = [];
    }
    addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
    replaceChildren() { this.children = []; }
    append(child) { this.children.push(child); }
    set innerHTML(value) { throw new Error('Submitted text must never be parsed as HTML'); }
    click() { downloads.push({name: this.download, blob: blobs.get(this.href)}); }
}
const elements = Object.fromEntries(ids.map((id) => [id, new Element()]));
globalThis.document = {
    getElementById(id) { assert.ok(elements[id], `Missing controller element: ${id}`); return elements[id]; },
    createTextNode: (textContent) => ({textContent}),
    createElement: () => new Element(),
};
globalThis.window = {location: {search: ''}, history: {replaceState() {}}};
URL.createObjectURL = (blob) => {const id = `blob:test-${blobs.size}`; blobs.set(id, blob); return id;};
URL.revokeObjectURL = () => {};

const text = 'A😀e\u0301\nZ', reviewId = 'a'.repeat(32);
let version = 0, status = 'pending', covered = new Set();
const revision = () => version.toString(16).padStart(64, '0');
const masked = () => Array.from(text, (char, i) => covered.has(i) && char !== '\n' ? '#' : char).join('');
const snapshot = () => ({review_id: reviewId, revision_id: revision(), revision_number: version, status,
    canonical_original: text, masked_text: masked(), masked_proposal: text, detected_mask_intervals: [],
    mask_intervals: [], detection_counts: {}, coverage_counts: {}, expires_in_seconds: 1800});
const response = (body, code = 200) => ({ok: code < 400, status: code,
    json: async () => structuredClone(body), text: async () => body, headers: {get: () => revision()}});
let lastEdit;
globalThis.fetch = async (path, options) => {
    const body = options.body ? JSON.parse(options.body) : null;
    if (path === '/reviews') {
        assert.deepEqual(body, {text, synthetic_input: true});
        version = 1; return response(snapshot(), 201);
    }
    if (path.includes('/output?')) {
        const expected = new URL(path, 'http://example.invalid').searchParams.get('expected_revision');
        return status === 'approved' && expected === revision()
            ? response(masked()) : response({detail: {message: 'Output denied'}}, 409);
    }
    assert.equal(body.expected_revision, revision());
    if (path.endsWith('/mask')) {
        lastEdit = body;
        for (const [start, end] of body.intervals) {
            for (let i = start; i < end; i++) body.operation === 'add' ? covered.add(i) : covered.delete(i);
        }
        status = 'pending';
    } else if (path.endsWith('/approve')) status = 'approved';
    else if (path.endsWith('/reject')) status = 'rejected';
    else assert.fail('Unexpected page request');
    version += 1;
    return response(snapshot());
};
const source = readFileSync(new URL('../static/review.js', import.meta.url), 'utf8');
await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
async function event(id, type) {
    if (type === 'click') assert.equal(elements[id].disabled, false, `${id} must be enabled`);
    for (const callback of elements[id].listeners[type] || []) await callback({preventDefault() {}});
    await nextTurn();
}

elements['input-text'].value = text;
elements.synthetic.checked = true;
await event('submission', 'submit');
assert.equal(elements['input-panel'].open, false);
assert.equal(elements['review-state'].textContent, 'Pending review');
assert.equal(elements.download.disabled, true);
elements.original.selectionStart = 1; elements.original.selectionEnd = 5;
await event('original', 'select');
assert.match(elements.selection.textContent, /\[1, 4\)/);
await event('add', 'click');
assert.deepEqual(lastEdit.intervals, [[1, 4]]);
assert.equal(elements.proposal.value, 'A###\nZ');
assert.equal(elements.original.value, text);
elements.original.selectionStart = 1; elements.original.selectionEnd = 3;
await event('remove', 'click');
assert.equal(elements.proposal.value, 'A😀##\nZ');
await event('add', 'click');
elements['approval-ack'].checked = true;
await event('approval-ack', 'change');
await event('approve', 'click');
assert.equal(elements.review.dataset.status, 'approved');
assert.equal(elements['review-state'].textContent, 'Approved');
const approved = revision();
await event('download', 'click');
assert.equal(downloads[0].name, 'synthetic-reviewed.txt');
assert.deepEqual(Buffer.from(await downloads[0].blob.arrayBuffer()), Buffer.from('A###\nZ', 'utf8'));
assert.equal(elements['approved-output'].textContent, 'A###\nZ');
elements.original.selectionStart = 6; elements.original.selectionEnd = 7;
await event('add', 'click');
assert.notEqual(revision(), approved);
assert.equal(elements.review.dataset.status, 'pending');
assert.equal(elements['review-state'].textContent, 'Pending review');
assert.equal(elements.download.disabled, true);
assert.equal(elements['approval-ack'].checked, false);
assert.equal(elements['approved-output'].textContent, 'No approved output retrieved.');
assert.equal((await fetch(`/reviews/${reviewId}/output?expected_revision=${approved}`, {})).status, 409);
await event('reject', 'click');
assert.equal(elements['review-state'].textContent, 'Rejected');
assert.equal(elements.add.disabled, true);
assert.equal(elements.download.disabled, true);
console.log('Page selection, correction, approval, download, and invalidation checks passed');
