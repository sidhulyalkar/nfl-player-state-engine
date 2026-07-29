import express from 'express';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runCopilot } from './gemini.js';

try {
  process.loadEnvFile();
} catch (error) {
  if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
}

const app = express();
const port = Number(process.env.PORT ?? 3000);
const host = process.env.HOST ?? '0.0.0.0';
const pseBase = process.env.PSE_API_BASE_URL ?? 'http://localhost:8000';
const pseTimeoutMs = Number(process.env.PSE_API_TIMEOUT_MS ?? 15_000);
const sourceDirectory = path.dirname(fileURLToPath(import.meta.url));
const isProduction = process.env.NODE_ENV === 'production' || process.argv.includes('--production');
const clientRoot = path.resolve(sourceDirectory, isProduction ? '../..' : '..');
const clientDist = path.join(clientRoot, 'dist');

app.use(express.json({ limit: '2mb' }));

app.all('/api/pse/*path', async (request, response) => {
  try {
    const targetPath = request.originalUrl.replace(/^\/api\/pse/, '');
    const upstream = await fetch(`${pseBase}${targetPath}`, {
      method: request.method,
      headers: { 'Content-Type': 'application/json' },
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : JSON.stringify(request.body),
      signal: AbortSignal.timeout(pseTimeoutMs),
    });
    response.status(upstream.status);
    response.setHeader('Content-Type', upstream.headers.get('content-type') ?? 'application/json');
    response.send(await upstream.text());
  } catch (error) {
    response.status(502).json({
      error: 'Player State Engine unavailable',
      detail: error instanceof Error ? error.message : 'Upstream request failed',
    });
  }
});

app.post('/api/copilot', async (request, response) => {
  try {
    const { message, leagueId, rosterId } = request.body as { message?: string; leagueId?: string; rosterId?: string };
    if (!message?.trim()) return response.status(422).json({ error: 'message is required' });
    return response.json({ text: await runCopilot(message, leagueId, rosterId) });
  } catch (error) {
    return response.status(500).json({ error: error instanceof Error ? error.message : 'Copilot failed' });
  }
});

app.get('/api/health', (_request, response) => response.json({
  status: 'ok',
  runtime: 'node',
  mode: isProduction ? 'production' : 'development',
}));

async function start() {
  if (isProduction) {
    app.use(express.static(clientDist));
    app.use((request, response, next) => {
      if (request.method === 'GET' && request.accepts('html')) {
        return response.sendFile(path.join(clientDist, 'index.html'));
      }
      return next();
    });
  } else {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      root: clientRoot,
      appType: 'spa',
      server: { middlewareMode: true },
    });
    app.use(vite.middlewares);
  }

  app.listen(port, host, () => {
    console.log(`Gemini fantasy console listening on http://${host}:${port}`);
  });
}

start().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
