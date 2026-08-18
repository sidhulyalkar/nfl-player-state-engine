import { GoogleGenAI } from '@google/genai';
import { tools } from './tools.js';

const base = process.env.PSE_API_BASE_URL ?? 'http://localhost:8000';
const pseTimeoutMs = Number(process.env.PSE_API_TIMEOUT_MS ?? 15_000);

async function executeTool(name: string, args: Record<string, unknown>) {
  const leagueId = encodeURIComponent(String(args.league_id ?? ''));
  const rosterId = encodeURIComponent(String(args.roster_id ?? ''));
  let route = '';
  let init: RequestInit = { signal: AbortSignal.timeout(pseTimeoutMs) };

  if (name === 'get_league_context') {
    route = `/v1/copilot/context/${leagueId}${rosterId ? `?roster_id=${rosterId}` : ''}`;
  } else if (name === 'get_player_board') {
    route = `/v1/leagues/${leagueId}/players?decision=${encodeURIComponent(String(args.decision ?? 'trade'))}`;
  } else if (name === 'get_live_draft_board') {
    const params = new URLSearchParams({ roster_id: String(args.roster_id ?? ''), refresh: 'true' });
    if (args.draft_slot !== undefined) params.set('draft_slot', String(args.draft_slot));
    if (args.limit !== undefined) params.set('limit', String(args.limit));
    route = `/v1/leagues/${leagueId}/draft/board?${params.toString()}`;
  } else if (name === 'compare_draft_candidates') {
    route = `/v1/leagues/${leagueId}/draft/compare`;
    init = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        roster_id: args.roster_id,
        player_ids: args.player_ids,
        draft_slot: args.draft_slot,
        simulations: Number(args.simulations ?? 600),
        refresh: true,
      }),
      signal: AbortSignal.timeout(pseTimeoutMs),
    };
  } else if (name === 'get_trade_suggestions') {
    route = `/v1/leagues/${leagueId}/trades/suggestions?roster_id=${rosterId}&limit=${Number(args.limit ?? 8)}`;
  } else if (name === 'get_waiver_board') {
    route = `/v1/leagues/${leagueId}/waivers?roster_id=${rosterId}`;
  } else if (name === 'get_optimized_lineup') {
    route = `/v1/leagues/${leagueId}/lineup?roster_id=${rosterId}`;
  } else {
    throw new Error(`Unknown tool: ${name}`);
  }

  const response = await fetch(`${base}${route}`, init);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function selectFallbackTool(message: string) {
  const normalized = message.toLowerCase();
  if (/\b(draft|pick|on the clock|available|adp|qb2|superflex)\b/.test(normalized)) return 'get_live_draft_board';
  if (/\b(waiver|free agent|faab|add|drop)\b/.test(normalized)) return 'get_waiver_board';
  if (/\b(lineup|start|sit|bench)\b/.test(normalized)) return 'get_optimized_lineup';
  if (/\b(trade|deal|counteroffer)\b/.test(normalized)) return 'get_trade_suggestions';
  return 'get_player_board';
}

function summarizeFallback(name: string, result: unknown) {
  if (name === 'get_live_draft_board' && result && typeof result === 'object') {
    const board = (result as { board?: Array<Record<string, unknown>> }).board ?? [];
    if (!board.length) return 'The live draft tool returned no available players.';
    return board.slice(0, 8).map((item, index) =>
      `${index + 1}. ${String(item.player_name ?? item.player_id)} · ${String(item.position ?? '')} · ${Number(item.live_draft_score ?? 0).toFixed(1)} · ${String(item.draft_action ?? '')}`
    ).join('\n');
  }
  const rows = Array.isArray(result) ? result : [];
  if (!rows.length) return 'The deterministic tool returned no eligible results.';
  if (name === 'get_trade_suggestions') {
    return rows.slice(0, 3).map((row, index) =>
      `${index + 1}. ${String((row as Record<string, unknown>).explanation ?? 'Trade proposal')}`
    ).join('\n');
  }
  return rows.slice(0, 8).map((row, index) => {
    const item = row as Record<string, unknown>;
    const player = String(item.player_name ?? item.name ?? item.player_id ?? 'Unknown player');
    const slot = item.assigned_slot ? ` · ${String(item.assigned_slot)}` : '';
    const score = Number(item.decision_specific_score ?? item.lineup_score ?? item.waiver_upgrade);
    return `${index + 1}. ${player}${slot}${Number.isFinite(score) ? ` · ${score.toFixed(1)}` : ''}`;
  }).join('\n');
}

async function runStructuredFallback(message: string, leagueId?: string, rosterId?: string) {
  if (!leagueId || leagueId === 'demo-league') {
    return 'Gemini is not configured. Import a live league to use deterministic draft, lineup, waiver, trade, and ranking tools.';
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
  if (!process.env.GEMINI_API_KEY) return runStructuredFallback(message, leagueId, rosterId);
  const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });
  const context = `Current league_id=${leagueId ?? 'unknown'} and roster_id=${rosterId ?? 'unknown'}.`;
  const contents: any[] = [{ role: 'user', parts: [{ text: `${context}\n\n${message}` }] }];
  const config = {
    systemInstruction: `You are Fourth Down Copilot, an evidence-grounded fantasy football analyst. Use deterministic tools before factual claims. For draft questions distinguish raw projection, league-specific VORP and scarcity, roster counterfactual fit, and probability of surviving to the next pick. Never invent projections, ADP, ownership, or draft state. Treat 2QB and superflex rules as first-class. Mention material uncertainty and whether market survival is empirical or fallback. Be concise but analytically useful.`,
    tools: [{ functionDeclarations: tools }],
  };
  for (let iteration = 0; iteration < 5; iteration += 1) {
    const response = await ai.models.generateContent({
      model: process.env.GEMINI_MODEL ?? 'gemini-3.6-flash', contents, config,
    });
    if (!response.functionCalls?.length) return response.text || 'No answer generated.';
    contents.push(response.candidates?.[0]?.content);
    for (const call of response.functionCalls) {
      if (!call.name) throw new Error('Gemini returned a function call without a name.');
      const result = await executeTool(call.name, (call.args ?? {}) as Record<string, unknown>);
      contents.push({ role: 'user', parts: [{ functionResponse: {
        name: call.name, id: call.id, response: { result },
      } }] });
    }
  }
  return 'The request required too many tool steps. Narrow the question to one draft comparison, lineup, trade, or waiver decision.';
}
