/** Source-aware published score changes. Not live NFL play-by-play. */
export interface PublishedGame {
  game_id:string;away_team:string;home_team:string;
  away_score:number|null;home_score:number|null;
}
export interface PublishedBoard {
  season:number;week:number;
  source:{fetched_at_utc:string|null;integrity_verified:boolean;stale:boolean};
  games:readonly PublishedGame[];
}
export interface PublishedSignal {
  key:string;game_id:string;team:string;text:string;at:string;
  kind:'PUBLISHED_SCORE_REVISION'|'FIRST_PUBLISHED_SCORE';
}
function validScore(value:number|null):value is number {
  return typeof value==='number'&&Number.isInteger(value)&&value>=0&&value<200;
}
export function publishedScoreSignals(before:PublishedBoard|null,after:PublishedBoard):PublishedSignal[]{
  const at=after.source.fetched_at_utc;
  // Never replay stale caches, same-source snapshots or a different football week as "new" news.
  if(!before||before.season!==after.season||before.week!==after.week
      ||!after.source.integrity_verified||after.source.stale||!at
      ||!before.source.fetched_at_utc)return [];
  const nextTime=Date.parse(at),previousTime=Date.parse(before.source.fetched_at_utc);
  if(!Number.isFinite(nextTime)||!Number.isFinite(previousTime)||nextTime<=previousTime)return [];
  const old=new Map(before.games.map(g=>[g.game_id,g]));
  const output:PublishedSignal[]=[];
  for(const game of after.games){
    const prior=old.get(game.game_id);
    if(!prior||prior.home_team!==game.home_team||prior.away_team!==game.away_team
        ||!validScore(game.away_score)||!validScore(game.home_score))continue;
    const known=validScore(prior.away_score)&&validScore(prior.home_score);
    if(known&&prior.away_score===game.away_score&&prior.home_score===game.home_score)continue;
    const beforeText=known?`previously ${prior.away_team} ${prior.away_score} · ${prior.home_team} ${prior.home_score}`
      :'scores previously unavailable';
    output.push({
      key:[game.game_id,at,game.away_score,game.home_score].join(':'),
      game_id:game.game_id,team:game.away_team+' at '+game.home_team,
      kind:known?'PUBLISHED_SCORE_REVISION':'FIRST_PUBLISHED_SCORE',
      text:`Published score ${game.away_team} ${game.away_score} · ${game.home_team} ${game.home_score} (${beforeText}). This is a source revision, not a confirmed scoring play; play type and timing are unknown.`,
      at,
    });
  }
  return output;
}
