/** Stable, safe operator diagnostics for the local Python PSE upstream. */
export interface ProxyFailure {
  error: string;
  detail: string;
  code: 'PSE_UPSTREAM_OFFLINE'|'PSE_UPSTREAM_TIMEOUT'|'PSE_UPSTREAM_UNAVAILABLE';
  stage: 'api_transport';
  hint: string;
  retryable: true;
}
export function proxyFailure(error:unknown):ProxyFailure {
  const message=error instanceof Error?error.message:String(error);
  const code= /timeout|abort/i.test(message)
    ? 'PSE_UPSTREAM_TIMEOUT'
    : /ECONNREFUSED|fetch failed|ENOTFOUND|EHOSTUNREACH|ECONNRESET/i.test(message)
      ? 'PSE_UPSTREAM_OFFLINE' : 'PSE_UPSTREAM_UNAVAILABLE';
  const hints={
    PSE_UPSTREAM_OFFLINE:'The Python Player State Engine API is not reachable. Start it with `python -m player_state_engine.api` from your repository .venv, or run scripts/dev-local.sh to launch both services.',
    PSE_UPSTREAM_TIMEOUT:'The Python API did not respond within the configured timeout. Verify API health and inspect server logs before retrying.',
    PSE_UPSTREAM_UNAVAILABLE:'The Python API connection failed. Check the Python API process and PSE_API_BASE_URL on the Node server.',
  };
  return {error:'Player State Engine unavailable',detail:hints[code],
    code,stage:'api_transport',hint:hints[code],retryable:true};
}
