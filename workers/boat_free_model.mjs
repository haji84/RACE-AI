/** Cloudflare port of the fixed, untrained PR71 A/B model. No odds/results in inputs. */
const HEX=/^[a-f0-9]{64}$/,RID=/^(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])$/;
export const MODEL_IDS=['boat-display-rating-PL-reference-v1-UNVALIDATED','boat-course-motor-shadow-v0.1-UNTRAINED'];
const BONUS=[.20,.10,.04,-.04,-.12,-.18];
const ensure=(x,m)=>{if(!x)throw Error(m);};
const exact=(x,keys)=>!!x&&typeof x==='object'&&!Array.isArray(x)&&Object.keys(x).sort().join('|')===[...keys].sort().join('|');
const finite=(n,lo,hi)=>typeof n==='number'&&Number.isFinite(n)&&n>=lo&&n<=hi;
const time=x=>{ensure(typeof x==='string'&&/T\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(x),'AWARE_CLOCK_REQUIRED');const n=Date.parse(x);ensure(Number.isFinite(n),'INVALID_CLOCK');return n;};
export const jstDay=d=>new Date(d.getTime()+32400000).toISOString().slice(0,10).replaceAll('-','');
function sum(xs){let s=0,c=0;for(const x of xs){const y=x-c,t=s+y;c=(t-s)-y;s=t;}return s;}
function ranking(strength){const total=sum(strength),rows=[];for(let a=1;a<=6;a++)for(let b=1;b<=6;b++)for(let c=1;c<=6;c++){if(a===b||a===c||b===c)continue;const x=strength[a-1],y=strength[b-1],z=strength[c-1];rows.push({ticket:`${a}-${b}-${c}`,score:x/total*y/(total-x)*z/(total-x-y)});}ensure(Math.abs(sum(rows.map(x=>x.score))-1)<1e-9,'MODEL_MASS_INVALID');return rows.sort((a,b)=>b.score-a.score||a.ticket.localeCompare(b.ticket));}
export function buildPair(source,generatedAt){
 ensure(exact(source,['race_id','cutoff_at','captured_at','program_source_sha256','beforeinfo_source_sha256','boats']),'EXACT_OBSERVATION_REQUIRED');
 const id=RID.exec(source.race_id),cutoff=time(source.cutoff_at),capture=time(source.captured_at),generated=time(generatedAt);
 ensure(id&&source.cutoff_at.endsWith('+09:00')&&jstDay(new Date(cutoff))===id[1],'RACE_CUTOFF_DATE_CONFLICT');
 ensure(capture<=generated&&generated+120000<cutoff,'NOT_SAFE_PRE_CUTOFF');
 ensure(HEX.test(source.program_source_sha256)&&HEX.test(source.beforeinfo_source_sha256),'SOURCE_SHA_REQUIRED');
 ensure(Array.isArray(source.boats)&&source.boats.length===6,'SIX_BOATS_REQUIRED');
 const boats=[...source.boats].sort((a,b)=>a.lane-b.lane),ids=new Set();
 for(let i=0;i<6;i++){const b=boats[i];ensure(exact(b,['lane','racer_id','national_win_rate','exhibition_time_seconds','motor_two_place_rate_percent']),'EXACT_BOAT_REQUIRED');ensure(b.lane===i+1&&/^\d{4}$/.test(b.racer_id)&&!ids.has(b.racer_id),'BOAT_IDENTITIES_INVALID');ids.add(b.racer_id);ensure((b.national_win_rate===null||finite(b.national_win_rate,0,10))&&finite(b.exhibition_time_seconds,4,12)&&finite(b.motor_two_place_rate_percent,0,100),'OBSERVED_FEATURE_REQUIRED');}
 const mean=sum(boats.map(b=>b.exhibition_time_seconds))/6,motorMean=sum(boats.map(b=>b.motor_two_place_rate_percent))/6;
 const raw=boats.map(b=>Math.log(Math.max(b.national_win_rate??1,.01))+mean-b.exhibition_time_seconds);
 return {schema:'BOAT_FREE_RUNTIME_PAIR_V1',race_id:source.race_id,cutoff_at:source.cutoff_at,captured_at:source.captured_at,generated_at:generatedAt,program_source_sha256:source.program_source_sha256,beforeinfo_source_sha256:source.beforeinfo_source_sha256,models:MODEL_IDS.map((model_id,k)=>{const full_120=ranking(raw.map((r,i)=>Math.exp(Math.max(-20,Math.min(20,r+(k?BONUS[i]+.003*(boats[i].motor_two_place_rate_percent-motorMean):0))))));return {model_id,calibrated:false,trained:false,odds_independent:true,full_120,top8:full_120.slice(0,8).map(x=>({...x}))};}),prediction_implementation:'CLOUDFLARE_JS_PORT_NUMERIC_PARITY_REQUIRED',source_snapshot:source};
}
export function scorePair(pair,result){
 ensure(result&&Array.isArray(result.top3)&&result.top3.length===3&&new Set(result.top3).size===3&&result.top3.every(n=>Number.isInteger(n)&&n>=1&&n<=6),'OFFICIAL_TOP3_REQUIRED');
 const refunds=result.refund_boats??[];ensure(Array.isArray(refunds)&&new Set(refunds).size===refunds.length&&refunds.every(n=>Number.isInteger(n)&&n>=1&&n<=6&&!result.top3.includes(n)),'REFUND_CONFLICT');
 ensure(Number.isSafeInteger(result.payout_per_100_yen)&&result.payout_per_100_yen>=100,'OFFICIAL_PAYOUT_REQUIRED');
 const winner=result.top3.join('-'),normal=refunds.length===0;
 if(pair!==null){ensure(pair.schema==='BOAT_FREE_RUNTIME_PAIR_V1'&&Array.isArray(pair.models)&&pair.models.length===2,'FROZEN_PAIR_REQUIRED');for(let k=0;k<2;k++){const m=pair.models[k];ensure(m.model_id===MODEL_IDS[k]&&m.calibrated===false&&m.trained===false&&m.full_120?.length===120&&m.top8?.length===8,'MODEL_IDENTITY_INVALID');ensure(new Set(m.full_120.map(x=>x.ticket)).size===120&&m.full_120.every(x=>/^([1-6])-([1-6])-([1-6])$/.test(x.ticket)&&new Set(x.ticket.split('-')).size===3&&finite(x.score,0,1)),'FROZEN_DISTRIBUTION_INVALID');ensure(Math.abs(sum(m.full_120.map(x=>x.score))-1)<1e-9&&JSON.stringify(m.top8)===JSON.stringify(m.full_120.slice(0,8)),'FROZEN_RANK_INVALID');}}
 return {schema:'BOAT_FREE_RUNTIME_SCORE_V1',result_class:normal?'SETTLED':'SETTLED_WITH_REFUND',top3:result.top3,refund_boats:[...refunds].sort(),payout_per_100_yen:result.payout_per_100_yen,forecast_present:pair!==null,models:MODEL_IDS.map((model_id,k)=>{const m=pair?.models[k],picks=m?.top8??[],r=picks.filter(x=>x.ticket.split('-').some(n=>refunds.includes(Number(n)))).length,hit=picks.some(x=>x.ticket===winner),score=m?.full_120.find(x=>x.ticket===winner)?.score;return {model_id,normal_hit1:normal?Number(picks[0]?.ticket===winner):null,normal_hit8:normal?Number(hit):null,stake_yen:picks.length*100,refund_yen:r*100,net_stake_yen:(picks.length-r)*100,winnings_yen:hit?result.payout_per_100_yen:0,total_return_yen:r*100+(hit?result.payout_per_100_yen:0),winner_rank:m?m.full_120.findIndex(x=>x.ticket===winner)+1:null,brier:normal&&m?sum(m.full_120.map(x=>(x.score-Number(x.ticket===winner))**2)):null,log_loss:normal&&score?-Math.log(score):null};})};
}
const txt=s=>s.replace(/<[^>]+>/g,' ').replace(/&nbsp;|&#160;/g,' ').replace(/&amp;/g,'&').replace(/\s+/g,' ').trim().normalize('NFKC');
export function parseProgram(html,roster){
 const tables=[...html.matchAll(/<table\b[^>]*>([\s\S]*?)<\/table>/gi)].map(x=>x[1]).filter(t=>['ボートレーサー','全国','当地','モーター'].every(x=>txt(t).includes(x)));
 ensure(tables.length===1,'PROGRAM_MOTOR_TABLE');const groups=[...tables[0].matchAll(/<tbody\b[^>]*>([\s\S]*?)<\/tbody>/gi)];ensure(groups.length===6,'PROGRAM_MOTOR_SIX_GROUPS');const rates=new Map();
 for(const g of groups){const row=/<tr\b[^>]*>([\s\S]*?)<\/tr>/i.exec(g[1]);ensure(row,'PROGRAM_MOTOR_ROW');const cols=[...row[1].matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/gi)].map(x=>txt(x[1]));ensure(cols.length>=8,'PROGRAM_MOTOR_COLUMNS');const lane=Number(cols[0]),reg=/^(\d{4})\s*\//.exec(cols[2]),m=/^(\d+)\s+(\d+\.\d{2})\s+(\d+\.\d{2})$/.exec(cols[6]);ensure(reg&&m&&finite(Number(m[2]),0,100)&&finite(Number(m[3]),0,100),'PROGRAM_MOTOR_RATE');ensure(roster.some(r=>r.lane===lane&&r.registration_no===reg[1])&&!rates.has(lane),'PROGRAM_MOTOR_IDENTITY');rates.set(lane,Number(m[2]));}
 return roster.map(r=>({...r,motor_two_place_rate_percent:rates.get(r.lane)}));
}
export function parseDay(html,day){
 ensure(/^\d{8}$/.test(day),'INDEX_DAY_INVALID');const title=[...html.matchAll(/<(?:h[1-6]|div|span)[^>]*class=["'][^"']*title2_mainLabel[^"']*["'][^>]*>([\s\S]*?)<\/(?:h[1-6]|div|span)>/gi)];ensure(title.length===1&&txt(title[0][1])===`${Number(day.slice(4,6))}月${Number(day.slice(6,8))}日のレース情報`,'INDEX_TITLE_DATE');
 ensure(html.includes('btnGroup3_refreshBtn')&&html.includes(`index?hd=${day}`)&&txt(html).includes('締切予定時刻は締切5分前より赤く表示されます。'),'INDEX_COMPLETENESS');
 const tables=[...html.matchAll(/<table\b[^>]*>([\s\S]*?)<\/table>/gi)].map(x=>x[1]).filter(t=>['レース場','進行状況','開催期間/日次','レース別情報'].every(x=>txt(t).includes(x)));ensure(tables.length===1,'INDEX_TABLE_INVALID');const rows=[...tables[0].matchAll(/<tbody\b[^>]*>([\s\S]*?)<\/tbody>/gi)];ensure(rows.length>0&&rows.length<=24,'INDEX_VENUES_INVALID');const venues=[];
 for(const x of rows){const row=/<tr\b[^>]*>([\s\S]*?)<\/tr>/i.exec(x[1]);ensure(row,'INDEX_VENUE_ROW');const images=[...row[1].matchAll(/src=["']\/static_extra\/pc\/images\/text_place1_(\d{2})\.png["']/g)];ensure(images.length===1,'INDEX_VENUE_IMAGE');const venue=images[0][1];ensure(/^(0[1-9]|1\d|2[0-4])$/.test(venue)&&!venues.includes(venue),'INDEX_DUPLICATE_VENUE');const hrefs=[...row[1].matchAll(/<a\b[^>]*href=["']([^"']+)["']/gi)].map(m=>new URL(m[1].replaceAll('&amp;','&'),'https://www.boatrace.jp'));const meet=hrefs.filter(u=>u.pathname==='/owpc/pc/race/raceindex'),entry=hrefs.filter(u=>u.pathname==='/owpc/pc/race/racelist');ensure(meet.length===1&&entry.length===1,'INDEX_LINKS_MISSING');for(const u of [meet[0],entry[0]])ensure(u.origin==='https://www.boatrace.jp'&&u.searchParams.get('jcd')===venue&&u.searchParams.get('hd')===day&&!u.hash,'INDEX_LINK_IDENTITY');ensure(meet[0].searchParams.size===2&&entry[0].searchParams.size===3&&Number(entry[0].searchParams.get('rno'))>=1&&Number(entry[0].searchParams.get('rno'))<=12,'INDEX_LINK_EXTRA');venues.push(venue);}
 return venues.sort();
}
