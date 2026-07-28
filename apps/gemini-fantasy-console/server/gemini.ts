import { GoogleGenAI } from '@google/genai';
import { tools } from './tools.js';

const base = process.env.PSE_API_BASE_URL ?? 'http://localhost:8000';

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
  const response = await fetch(`${base}${route}`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function runCopilot(message: string, leagueId?: string, rosterId?: string): Promise<string> {
  if (!process.env.GEMINI_API_KEY) {
    return 'Gemini is not configured yet. Set the server-side GEMINI_API_KEY secret. The deterministic dashboard remains usable without it.';
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
