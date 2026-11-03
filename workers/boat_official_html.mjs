/** Strict public HTML -> normalized private research facts. Source bytes are not retained. */
const HOST='https://www.boatrace.jp';
const view=raw=>raw.replace(/<script\b[\s\S]*?<\/script>/gi,'').replace(/<style\b[\s\S]*?<\/style>/gi,'').replace(/<[^>]*>/g,' ').replace(/&nbsp;|&#160;/gi,' ').replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/\s+/g,' ').trim().normalize('NFKC');
const cells=raw=>Array.from(raw.matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi),x=>({html:x[1],text:view(x[1])}));
function tables(html){
 const result=[];
 for(const m of html.matchAll(/<table\b[^>]*>([\s\S]*?)<\/table>/gi)){
  const raw=m[1],head=/<thead\b[^>]*>([\s\S]*?)<\/thead>/i.exec(raw);
  result.push({header:head?view(head[1]):'',fullText:view(raw),heads:head?cells(head[1]):[],
   bodies:Array.from(raw.matchAll(/<tbody\b[^>]*>([\s\S]*?)<\/tbody>/gi),x=>Array.from(x[1].matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi),r=>cells(r[1]))),
   rows:Array.from(raw.matchAll(/<tbody\b[^>]*>([\s\S]*?)<\/tbody>/gi)).flatMap(x=>Array.from(x[1].matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi),r=>cells(r[1])))});
 }
 return result;
}
function only(tables,labels){
 const matches=tables.filter(t=>labels.every(label=>t.fullText.includes(label)));
 if(matches.length!==1)throw Error('OFFICIAL_HTML_UNEXPECTED_TABLE');
 return matches[0];
}
function pageIdentity(html,day,venue,race,kind){
 const hrefs=[...html.matchAll(/<a\b[^>]*href=["']([^"']+)["']/gi)].map(x=>x[1].replace(/&amp;/g,'&'));
 const links=[];
 for(const h of hrefs){
  let u;try{u=new URL(h,HOST);}catch{continue;}
  if(u.pathname==='/owpc/pc/race/'+kind){
   // Other-date navigation links may coexist on the official page. Only
  // admit exact same-date, same-venue race links to the selected 12R index.
  if(u.origin!==HOST||u.searchParams.get('hd')!==day||u.searchParams.get('jcd')!==venue)continue;
  if(u.searchParams.size!==3)throw Error('OFFICIAL_HTML_LINK_IDENTITY_CONFLICT');
   const n=Number(u.searchParams.get('rno'));
   if(!Number.isInteger(n)||n<1||n>12)throw Error('OFFICIAL_HTML_LINK_RACE_INVALID');
   links.push(n);
  }
 }
 if(!links.includes(race)||new Set(links).size!==12)throw Error('OFFICIAL_HTML_RACE_SCHEDULE_LINKS_MISSING');
}
function parseSchedule(html,day,venue){
 pageIdentity(html,day,venue,1,'racelist');
 const table=only(tables(html),['締切予定時刻']);
 const row=table.rows.find(x=>x.some(y=>y.text==='締切予定時刻'));
 if(!row||row.length!==13||row[0].text!=='締切予定時刻')throw Error('OFFICIAL_SCHEDULE_INCOMPLETE');
 const times=row.slice(1).map(x=>x.text);
 if(times.some(x=>!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(x)))throw Error('OFFICIAL_SCHEDULE_TIME_INVALID');
 return times.map((time,i)=>({race_id:day+'-'+venue+'-'+String(i+1).padStart(2,'0'),
  venue,race_no:i+1,cutoff_at:day.slice(0,4)+'-'+day.slice(4,6)+'-'+day.slice(6,8)+'T'+time+':00+09:00'}));
}
function parseRacelist(html,day,venue,race){
 pageIdentity(html,day,venue,race,'racelist');
 const t=only(tables(html),['枠','ボートレーサー','全国','当地','モーター','ボート']);
 const mainRows=t.bodies.length===6?t.bodies.map(group=>group[0]):t.rows;
 if(mainRows.length!==6||mainRows.some(row=>!row))throw Error('OFFICIAL_RACELIST_BODY_GROUPS_UNVERIFIED');
 const racers=mainRows.map(row=>{
  if(row.length<8)throw Error('OFFICIAL_RACELIST_COLUMNS_'+row.length);
  if(!/^[1-6]$/.test(row[0].text))throw Error('OFFICIAL_RACELIST_LANE_CHARS_'+row[0].text.length+'_'+Array.from(row[0].text.slice(0,5),c=>c.codePointAt(0)).join('_'));
  const reg=/\b([0-9]{4})\s*\//.exec(row[2].text);
  if(!reg||!row[2].html.includes('toban='+reg[1]))throw Error('OFFICIAL_RACELIST_REGISTRATION_MISMATCH');
  const rate=/^(\d+\.\d{2})/.exec(row[4].text);
  if(!rate||Number(rate[1])>10)throw Error('OFFICIAL_RACELIST_NATIONAL_RATE_INVALID');
  return {lane:Number(row[0].text),registration_no:reg[1],national_win_rate:Number(rate[1])};
 });
 if(new Set(racers.map(x=>x.lane)).size!==6||new Set(racers.map(x=>x.registration_no)).size!==6)throw Error('OFFICIAL_RACELIST_DUPLICATE');
 return racers.sort((a,b)=>a.lane-b.lane);
}
function parseExhibition(html,day,venue,race,roster){
 pageIdentity(html,day,venue,race,'beforeinfo');
 const t=only(tables(html),['ボートレーサー','展示','チルト']);
 const mainRows=t.bodies.length===6?t.bodies.map(group=>group[0]):t.rows;
 if(mainRows.length!==6||mainRows.some(row=>!row))throw Error('OFFICIAL_EXHIBITION_SIX_MISSING');
 const rows=mainRows.map(row=>{
  if(row.length<6||!/^[1-6]$/.test(row[0].text))throw Error('OFFICIAL_EXHIBITION_LANE_INVALID');
  const reg=/toban=([0-9]{4})/.exec(row[2].html);
  if(!reg)throw Error('OFFICIAL_EXHIBITION_REGISTRATION_MISSING');
  const time=row[4].text;
  if(!/^\d+\.\d{2}$/.test(time)||Number(time)<4||Number(time)>12)throw Error('OFFICIAL_EXHIBITION_NOT_PUBLISHED');
  return {lane:Number(row[0].text),registration_no:reg[1],exhibition_time_seconds:Number(time)};
 });
 const byLane=new Map(rows.map(r=>[r.lane,r]));
 if(byLane.size!==6||roster.length!==6)throw Error('OFFICIAL_EXHIBITION_DUPLICATE');
 return roster.map(r=>{const x=byLane.get(r.lane);if(!x||x.registration_no!==r.registration_no)throw Error('OFFICIAL_EXHIBITION_ROSTER_CHANGED');return {...r,exhibition_time_seconds:x.exhibition_time_seconds};});
}
function parseResult(html,day,venue,race,expectedRoster=null){
 pageIdentity(html,day,venue,race,'raceresult');
 const ts=tables(html),finish=only(ts,['着','枠','ボートレーサー','レースタイム']);
 if(finish.rows.length!==6)throw Error('OFFICIAL_RESULT_SIX_FINISHES_MISSING');
 const positions=new Map(),lanes=new Set(),racers=new Set(),observedRoster=[];
 for(const row of finish.rows){
  if(row.length!==4)throw Error('OFFICIAL_RESULT_FINISH_COLUMNS_INVALID');
  const pos=row[0].text,lane=row[1].text,id=/^\s*([0-9]{4})\b/.exec(row[2].text);
  const numeric=/^[1-6]$/.test(pos);
  const disposition=/^(?:欠|転|落|沈|失|妨|不|F|L|エ)$/.test(pos);
  // A verified top-three can coexist with a lower-place retirement.
  // Never manufacture 4th-6th place, and never score refunded outcomes.
  if(!(numeric||disposition)||!/^[1-6]$/.test(lane)||!id
     ||(numeric&&positions.has(Number(pos)))||lanes.has(Number(lane))||racers.has(id[1]))
    throw Error('OFFICIAL_RESULT_NONSTANDARD_FINISH');
  if(numeric)positions.set(Number(pos),{lane:Number(lane),registration_no:id[1]});
  lanes.add(Number(lane));racers.add(id[1]);observedRoster.push({lane:Number(lane),registration_no:id[1]});
 }
 if(![1,2,3].every(n=>positions.has(n))||lanes.size!==6||racers.size!==6)
  throw Error('OFFICIAL_RESULT_TOP3_OR_ROSTER_INCOMPLETE');
 if(expectedRoster){
  if(expectedRoster.length!==6||expectedRoster.some(r=>!observedRoster.some(x=>x.lane===r.lane&&x.registration_no===r.registration_no)))
   throw Error('OFFICIAL_RESULT_ROSTER_MISMATCH');
 }
 const top3=[1,2,3].map(n=>positions.get(n).lane),payout=only(ts,['勝式','組番','払戻金']);
 const rows=payout.rows.filter(row=>row.some(cell=>cell.text.replace(/\s+/g,'')==='3連単'));
 if(rows.length!==1)throw Error('OFFICIAL_RESULT_TRIFECTA_MISSING');
 const text=rows[0].map(x=>x.text).join(' ');
 if(/特払い|不成立|同着|中止/.test(text))throw Error('OFFICIAL_RESULT_SPECIAL_OUTCOME');
 const combos=[...text.matchAll(/([1-6])\s*[-－―]\s*([1-6])\s*[-－―]\s*([1-6])/g)];
 if(combos.length!==1)throw Error('OFFICIAL_RESULT_PAYOUT_IDENTITY_MISSING');
 const paid=combos[0].slice(1,4).map(Number);
 if(paid.join('-')!==top3.join('-'))throw Error('OFFICIAL_RESULT_PAYOUT_CONFLICT');
 const returns=only(ts,['返還']);
 const refundText=returns.rows.map(r=>r.map(c=>c.text).join(' ')).join(' ').trim();
 if(refundText&&!/^(?:なし|--|―|－|-)$/.test(refundText))throw Error('OFFICIAL_RESULT_REFUND_UNVERIFIED');
 return top3;
}
/** Strict 100-yen trifecta payout when published. Unreadable price is null,
 * never zero, and never an input to the forecast model. */
function parseResultDetails(html,day,venue,race,roster=null){
 const top3=parseResult(html,day,venue,race,roster);
 const payout=only(tables(html),['勝式','組番','払戻金']);
 const index=payout.heads.findIndex(c=>c.text.replace(/\s+/g,'')==='払戻金');
 const rows=payout.rows.filter(row=>row.some(c=>c.text.replace(/\s+/g,'')==='3連単'));
 const raw=index>=0?rows[0]?.[index]?.text?.trim():'';
 const match=/^[￥¥]?\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)\s*円?$/.exec(raw||'');
 const yen=match?Number(match[1].replace(/,/g,'')):null;
 return {top3,payout_per_100_yen:Number.isSafeInteger(yen)&&yen>=100?yen:null};
}
export {parseSchedule,parseRacelist,parseExhibition,parseResult,parseResultDetails};
