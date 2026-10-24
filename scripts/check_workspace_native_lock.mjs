// Prevent platform-specific npm lockfile omissions in the npm workspace.
// The app lockfile intentionally retains Rollup and esbuild binaries for all OS/CPU targets.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const workspace = 'apps/gemini-fantasy-console/';
const rootLock = JSON.parse(readFileSync(resolve(root, 'package-lock.json'), 'utf8'));
const appLock = JSON.parse(readFileSync(resolve(root, workspace, 'package-lock.json'), 'utf8'));

const isNative = name =>
  /^node_modules\/(?:@esbuild\/|@rollup\/|fsevents$)/.test(name) ||
  /^node_modules\/vite\/node_modules\/@esbuild\//.test(name);

const missing = [];
let checked = 0;
for (const [name, expected] of Object.entries(appLock.packages)) {
  if (!isNative(name) || expected.optional !== true) continue;
  checked += 1;
  const rootName = workspace + name;
  const actual = rootLock.packages[rootName];
  if (!actual || actual.version !== expected.version ||
      actual.integrity !== expected.integrity ||
      actual.optional !== true) {
    missing.push(rootName);
  }
}
assert.ok(checked > 50, 'Expected all optional Rollup and esbuild platform packages');
assert.deepEqual(missing, [],
  'Root workspace lockfile omits native optional packages. Restore from the frontend lockfile.');
console.log(`PASS: root npm lock preserves ${checked} optional platform binaries from frontend lock.`);
