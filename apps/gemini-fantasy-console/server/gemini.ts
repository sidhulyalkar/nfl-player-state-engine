import { GoogleGenAI } from '@google/genai';
import { tools } from './tools.js';

const base = process.env.PSE_API_BASE_URL ?? 'http://localhost:8000';
const pseTimeoutMs = Number(process.env.PSE_API_TIMEOUT_MS ?? 15_000);

async function executeTool(name: string, args: Record<string, unknown>) {
  const leagueId = encodeURIComponent(String(args.league_id ?? ''));
  const rosterId = encodeURIComponent(String(args.roster_id ?? ''));
  const routes: Record<string, string> = {
    get_league_context: `/v1/copilot/context/${leagueId}${rosterId ? `?roster_id=${rosterId}` : ''}`,
    get_player_board: `/v1/leagues/${leagueId}/players?decision=${encodeURIComponent(String(args.decision ?? 'trade'))}`,
    get_trade_suggestions: `/v1/leagues/${leagueId}/trades/suggestions?roster_id=${rosterId}&limit=${Number(args.limit ?? 8)}`,
    get_waiver_board: `/v1/leagues/${leagueId}/waivers?roster_id=${rosterId}`,
    get_optimized_lineup: `/v1/leagues/${leagueId}/lineup?roster_id=${rosterId}`,
  };
  const route = routes[name];
  if (!route) throw new Error(`Unknown tool: ${name}`);
  const response = await fetch(`${base}${route}`, {
    signal: AbortSignal.timeout(pseTimeoutMs),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function selectFallbackTool(message: string) {
  const normalized = message.toLowerCase();
  if (/\b(waiver|free agent|faab|add|drop)\b/.test(normalized)) return 'get_waiver_board';
  if (/\b(lineup|start|sit|bench)\b/.test(normalized)) return 'get_optimized_lineup';
  if (/\b(trade|deal|counteroffer)\b/.test(normalized)) return 'get_trade_suggestions';
  return 'get_player_board';
}

function summarizeFallback(name: string, result: unknown) {
  const rows = Array.isArray(result) ? result : [];
  if (!rows.length) return 'The deterministic tool returned no eligible results.';
  if (name === 'get_trade_suggestions') {
    return rows.slice(0, 3).map((row, index) => {
      const item = row as Record<string, unknown>;
      return `${index + 1}. ${String(item.explanation ?? 'Trade proposal returned without an explanation.')}`;
    }).join('\n');
  }
  return rows.slice(0, 8).map((row, index) => {
    const item = row as Record<string, unknown>;
    const nameValue = String(item.player_name ?? item.name ?? item.player_id ?? 'Unknown player');
    const slot = item.assigned_slot ? ` · ${String(item.assigned_slot)}` : '';
    const score = Number(item.decision_specific_score ?? item.lineup_score ?? item.waiver_upgrade);
    return `${index + 1}. ${nameValue}${slot}${Number.isFinite(score) ? ` · ${score.toFixed(1)}` : ''}`;
  }).join('\n');
}

async function runStructuredFallback(message: string, leagueId?: string, rosterId?: string) {
  if (!leagueId || leagueId === 'demo-league') {
    return 'Gemini is not configured. Import a live league to use deterministic offline lineup, waiver, trade, and ranking tools.';
  }
  const name = selectFallbackTool(message);
  const result = await executeTool(name, {
    league_id: leagueId,
    roster_id: rosterId,
    decision: /\bdynasty\b/i.test(message) ? 'dynasty' : /\bdraft\b/i.test(message) ? 'draft' : 'trade',
    limit: 8,
  });
  return `Structured fallback · Gemini unavailable\n\n${summarizeFallback(name, result)}\n\nValues above come directly from the Player State Engine; no language model generated them.`;
}

export async function runCopilot(message: string, leagueId?: string, rosterId?: string): Promise<string> {
  if (!process.env.GEMINI_API_KEY) {
    return runStructuredFallback(message, leagueId, rosterId);
  }
  const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });
  const context = `Current league_id=${leagueId ?? 'unknown'} and roster_id=${rosterId ?? 'unknown'}.`;
  const contents: any[] = [{ role: 'user', parts: [{ text: `${context}\n\n${message}` }] }];
  const config = {
    systemInstruction: `You are Fourth Down Copilot, an evidence-grounded fantasy football analyst. Use tools before making claims about players, ownership, trades, waivers, or lineups. Never invent projections. Distinguish model output from interpretation, mention material uncertainty, and explain decisions in league-specific terms. Be concise but analytically useful.`,
    tools: [{ functionDeclarations: tools }],
  };
  for (let iteration = 0; iteration < 4; iteration += 1) {
    const response = await ai.models.generateContent({
      model: process.env.GEMINI_MODEL ?? 'gemini-3.6-flash',
      contents,
      config,
    });
    if (!response.functionCalls?.length) return response.text || 'No answer generated.';
    contents.push(response.candidates?.[0]?.content);
    for (const call of response.functionCalls) {
      if (!call.name) throw new Error('Gemini returned a function call without a name.');
      const result = await executeTool(
        call.name,
        (call.args ?? {}) as Record<string, unknown>,
      );
      contents.push({
        role: 'user',
        parts: [
          {
            functionResponse: {
              name: call.name,
              id: call.id,
              response: { result },
            },
          },
        ],
      });
    }
  }
  return 'The request required too many tool steps. Narrow the question to one lineup, trade, player group, or waiver decision.';
}
