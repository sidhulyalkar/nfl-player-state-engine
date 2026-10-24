import test from 'node:test';
import assert from 'node:assert/strict';
import {proxyFailure} from './proxyDiagnostics.ts';
test('offline Python API shows launch hint, not a fake Sleeper failure',()=>{
  const v=proxyFailure(new TypeError('fetch failed'));
  assert.equal(v.code,'PSE_UPSTREAM_OFFLINE');
  assert.equal(v.stage,'api_transport');
  assert.match(v.detail,/python -m player_state_engine.api/);
  assert.equal(v.retryable,true);
});
test('aborted requests receive timeout guidance',()=>{
  const v=proxyFailure(new Error('The operation timed out'));
  assert.equal(v.code,'PSE_UPSTREAM_TIMEOUT');
});
test('unknown proxy errors do not expose credentials in response body',()=>{
  const v=proxyFailure(new Error('HTTP header Authorization: SECRET-TOKEN'));
  assert.equal(v.code,'PSE_UPSTREAM_UNAVAILABLE');
  assert.ok(!JSON.stringify(v).includes('SECRET-TOKEN'));
});
