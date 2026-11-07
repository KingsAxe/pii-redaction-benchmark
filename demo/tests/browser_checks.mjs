// Run by unittest with the installed Node runtime; no packages or network.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const source = readFileSync(new URL("../static/review.js", import.meta.url), "utf8");
const {codePointOffset, selectionInterval, showCoverage} = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const text = "A😀e\u0301\nB";
assert.equal(codePointOffset(text, 0), 0);
assert.equal(codePointOffset(text, 1), 1);
assert.equal(codePointOffset(text, 3), 2);
assert.equal(codePointOffset(text, 5), 4);
assert.equal(codePointOffset(text, 7), 6);
assert.deepEqual(selectionInterval(text, 1, 5), [1, 4]);
for (const offset of [-1, 2, 8, 1.5]) assert.throws(() => codePointOffset(text, offset));
assert.throws(() => selectionInterval(text, 3, 3));
assert.throws(() => selectionInterval(text, 5, 1));

// Minimal DOM double only accepts text nodes and mark elements, never HTML.
const children = [];
globalThis.document = {
    createTextNode: (value) => ({type: "text", textContent: value}),
    createElement: (type) => { assert.equal(type, "mark"); return {type, textContent: ""}; }
};
const container = {replaceChildren: () => {children.length = 0;}, append: (child) => children.push(child)};
const malicious = '<img onerror="throw 1">😀\n#';
showCoverage(container, malicious, [[0, 5], [22, 25]]);
assert.equal(children.map((child) => child.textContent).join(""), malicious);
assert.ok(children.some((child) => child.type === "mark"));
console.log("Browser offset and safe-text rendering checks passed");
