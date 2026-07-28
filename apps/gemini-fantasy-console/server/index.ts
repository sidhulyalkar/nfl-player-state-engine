import cors from 'cors';
import express from 'express';
import path from 'node:path';
import { runCopilot } from './gemini.js';

const app = express();
const port = Number(process.env.PORT ?? 8787);
const pseBase = process.env.PSE_API_BASE_URL ?? 'http://localhost:8000';
const clientDist = path.resolve(process.cwd(), 'dist');
app.use(cors());
app.use(express.json({ limit: '2mb' }));

app.all('/api/pse/*path', async (request, response) => {
  const targetPath = request.originalUrl.replace(/^\/api\/pse/, '');
  const upstream = await fetch(`${pseBase}${targetPath}`, {
    method: request.method,
    headers: { 'Content-Type': 'application/json' },
    body: ['GET', 'HEAD'].includes(request.method) ? undefined : JSON.stringify(request.body),
  });
  response.status(upstream.status);
  response.setHeader('Content-Type', upstream.headers.get('content-type') ?? 'application/json');
  response.send(await upstream.text());
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

app.get('/api/health', (_request, response) => response.json({ status: 'ok', pseBase }));
app.use(express.static(clientDist));
app.use((request, response, next) => {
  if (request.method === 'GET' && request.accepts('html')) {
    return response.sendFile(path.join(clientDist, 'index.html'));
  }
  return next();
});
app.listen(port, () => console.log(`Gemini fantasy console server listening on ${port}`));
