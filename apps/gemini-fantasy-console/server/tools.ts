import { type FunctionDeclaration, Type } from '@google/genai';

export const tools: FunctionDeclaration[] = [
  {
    name: 'get_league_context',
    description: 'Retrieve the complete fantasy league snapshot, power rankings, free agents, and optionally one roster.',
    parameters: { type: Type.OBJECT, properties: { league_id: { type: Type.STRING }, roster_id: { type: Type.STRING } }, required: ['league_id'] },
  },
  {
    name: 'get_player_board',
    description: 'Retrieve league-aware player values and ownership for a decision such as trade, waiver, draft, dynasty, or start_sit.',
    parameters: { type: Type.OBJECT, properties: { league_id: { type: Type.STRING }, decision: { type: Type.STRING, enum: ['trade', 'waiver', 'draft', 'dynasty', 'stash', 'start_sit'] } }, required: ['league_id', 'decision'] },
  },
  {
    name: 'get_live_draft_board',
    description: 'Retrieve the authoritative live Draft War Room board including 2QB scarcity, roster need, tier cliffs, room timing, survival-to-next-pick, dynamic wait-loss diagnostics, and recent picks.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        league_id: { type: Type.STRING }, roster_id: { type: Type.STRING },
        draft_slot: { type: Type.INTEGER }, limit: { type: Type.INTEGER },
      },
      required: ['league_id', 'roster_id'],
    },
  },
  {
    name: 'compare_draft_candidates',
    description: 'Compare 2 to 5 currently available draft candidates using server-side football value, league scarcity, pick timing, and roster counterfactual simulation.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        league_id: { type: Type.STRING }, roster_id: { type: Type.STRING },
        player_ids: { type: Type.ARRAY, items: { type: Type.STRING } },
        draft_slot: { type: Type.INTEGER }, simulations: { type: Type.INTEGER },
      },
      required: ['league_id', 'roster_id', 'player_ids'],
    },
  },
  {
    name: 'get_ranking_calibration',
    description: 'Retrieve scoring-exactness provenance plus model-versus-expert and market disagreement for a league. External rankings are audit signals and never the numerical source of truth.',
    parameters: {
      type: Type.OBJECT,
      properties: { league_id: { type: Type.STRING }, limit: { type: Type.INTEGER } },
      required: ['league_id'],
    },
  },
  {
    name: 'plan_two_turn_draft',
    description: 'Run the explicitly unpromoted research two-turn draft lookahead for 2 to 5 candidates. Use only to explain future-pick opportunity, never as the production recommendation.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        league_id: { type: Type.STRING }, roster_id: { type: Type.STRING },
        player_ids: { type: Type.ARRAY, items: { type: Type.STRING } },
        draft_slot: { type: Type.INTEGER }, simulations: { type: Type.INTEGER },
      },
      required: ['league_id', 'roster_id', 'player_ids'],
    },
  },
  {
    name: 'get_trade_suggestions',
    description: 'Find mutually beneficial trades for one roster based on both teams before and after the trade.',
    parameters: { type: Type.OBJECT, properties: { league_id: { type: Type.STRING }, roster_id: { type: Type.STRING }, limit: { type: Type.INTEGER } }, required: ['league_id', 'roster_id'] },
  },
  {
    name: 'get_waiver_board',
    description: 'Rank free agents by roster-relative upgrade, opportunity, breakout probability, and FAAB planning value.',
    parameters: { type: Type.OBJECT, properties: { league_id: { type: Type.STRING }, roster_id: { type: Type.STRING } }, required: ['league_id', 'roster_id'] },
  },
  {
    name: 'get_optimized_lineup',
    description: 'Return the legal optimized lineup for a roster under the league settings and current risk preference.',
    parameters: { type: Type.OBJECT, properties: { league_id: { type: Type.STRING }, roster_id: { type: Type.STRING } }, required: ['league_id', 'roster_id'] },
  },
];
