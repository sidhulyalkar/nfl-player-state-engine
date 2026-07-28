import type { PlayerRow, PowerRanking, TradeSuggestion } from '../../shared/types';

const names = [
  ['Lamar Jackson', 'QB', 'BAL'], ['Jahmyr Gibbs', 'RB', 'DET'], ['Bijan Robinson', 'RB', 'ATL'],
  ['Justin Jefferson', 'WR', 'MIN'], ['CeeDee Lamb', 'WR', 'DAL'], ['Amon-Ra St. Brown', 'WR', 'DET'],
  ['Brock Bowers', 'TE', 'LV'], ['Trey McBride', 'TE', 'ARI'], ['Drake London', 'WR', 'ATL'],
  ['Bucky Irving', 'RB', 'TB'], ['Jayden Daniels', 'QB', 'WAS'], ['Garrett Wilson', 'WR', 'NYJ'],
];

export const demoPlayers: PlayerRow[] = names.map(([player_name, position, recent_team], index) => ({
  player_id: `demo-${index}`,
  player_name,
  position,
  recent_team,
  owner_team_name: index < 8 ? ['Neural Blitz', 'Shasta Snowdogs', 'Fourth & Chaos', 'Bayesian Ballers'][index % 4] : null,
  owner_roster_id: index < 8 ? String((index % 4) + 1) : null,
  is_free_agent: index >= 8,
  decision_specific_score: 92 - index * 3.7,
  fantasy_points_ppr_q10: 8 + (index % 4),
  fantasy_points_ppr_q50: 17 - index * 0.35,
  fantasy_points_ppr_q90: 29 - index * 0.25,
  season_points_q10: 145 - index * 4,
  season_points_q50: 245 - index * 6,
  season_points_q90: 340 - index * 5,
  availability_probability: index === 7 ? 0.78 : 0.95,
  opportunity_confidence: 0.64 + (index % 5) * 0.06,
  breakout_probability: index >= 8 ? 0.45 + (index % 3) * 0.12 : 0.18,
  decision_reasons: index >= 8 ? 'role expanding, favorable team fit' : 'stable opportunity, projection-led value',
}));

export const demoPower: PowerRanking[] = [
  ['1', 'Neural Blitz', '6-2-0', 91, 364, 280, 438, 44],
  ['2', 'Shasta Snowdogs', '5-3-0', 84, 341, 267, 421, 51],
  ['3', 'Fourth & Chaos', '4-4-0', 76, 326, 251, 415, 63],
  ['4', 'Bayesian Ballers', '3-5-0', 69, 308, 249, 380, 39],
].map(([roster_id, team_name, record, power_score, roster_value, floor_value, ceiling_value, risk_score]) => ({
  roster_id: String(roster_id), team_name: String(team_name), record: String(record),
  power_score: Number(power_score), roster_value: Number(roster_value), floor_value: Number(floor_value),
  ceiling_value: Number(ceiling_value), risk_score: Number(risk_score),
}));

export const demoTrades: TradeSuggestion[] = [
  {
    explanation: 'Neural Blitz converts surplus WR depth into an RB starter while Shasta Snowdogs gains weekly ceiling and roster flexibility.',
    analysis: {
      fairness_score: 88, mutual_benefit_score: 79, confidence: 0.76, verdict: 'accept',
      side_a: { roster_id: '1', value_delta: 3.4, starter_delta: 2.8, reasons: ['starting lineup improves', 'positional balance improves'] },
      side_b: { roster_id: '2', value_delta: 2.1, starter_delta: 1.0, reasons: ['bench depth improves', 'adds ceiling more than floor'] },
    },
    trade: {},
  },
];

export const demoNFL = {
  season: 2026,
  week: 8,
  teams: ['DET','SF','BAL','MIN','DAL','ATL','TB','ARI'].map((team, index) => ({
    team, wins: 7 - Math.floor(index / 2), losses: 1 + Math.floor(index / 2), ties: 0,
    points_for: 240 - index * 9, points_against: 160 + index * 7,
    point_differential: 80 - index * 16, win_percentage: (7 - Math.floor(index / 2)) / 8,
    streak: index % 2 ? 'W2' : 'W4',
  })),
};
