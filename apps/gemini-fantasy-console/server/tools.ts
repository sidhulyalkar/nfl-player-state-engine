import { type FunctionDeclaration, Type } from '@google/genai';

export const tools: FunctionDeclaration[] = [
  {
    name: 'get_league_context',
    description: 'Retrieve the complete fantasy league snapshot, power rankings, free agents, and optionally one roster.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        league_id: { type: Type.STRING },
        roster_id: { type: Type.STRING },
      },
      required: ['league_id'],
    },
  },
  {
    name: 'get_player_board',
    description: 'Retrieve league-aware player values and ownership for a decision such as trade, waiver, draft, dynasty, or start_sit.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        league_id: { type: Type.STRING },
        decision: {
          type: Type.STRING,
          enum: ['trade', 'waiver', 'draft', 'dynasty', 'stash', 'start_sit'],
        },
      },
      required: ['league_id', 'decision'],
    },
  },
  {
    name: 'get_trade_suggestions',
    description: 'Find mutually beneficial trades for one roster based on both teams before and after the trade.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        league_id: { type: Type.STRING },
        roster_id: { type: Type.STRING },
        limit: { type: Type.INTEGER },
      },
      required: ['league_id', 'roster_id'],
    },
  },
  {
    name: 'get_waiver_board',
    description: 'Rank free agents by roster-relative upgrade, opportunity, breakout probability, and FAAB planning value.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        league_id: { type: Type.STRING },
        roster_id: { type: Type.STRING },
      },
      required: ['league_id', 'roster_id'],
    },
  },
  {
    name: 'get_optimized_lineup',
    description: 'Return the legal optimized lineup for a roster under the league settings and current risk preference.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        league_id: { type: Type.STRING },
        roster_id: { type: Type.STRING },
      },
      required: ['league_id', 'roster_id'],
    },
  },
];
