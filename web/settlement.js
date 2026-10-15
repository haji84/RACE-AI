/* Fresh same-origin reports establish authority. Persisted audit and purchase result claims never do. */
(function(root,factory){
  'use strict';
  const api=factory(typeof module==='object'&&module.exports?require('./money.js'):root.RaceMoney);
  if(typeof module==='object'&&module.exports)module.exports=api;
  root.RaceSettlement=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Money){
  'use strict';
  const TYPES=['trifecta','trio','exacta','quinella','quinella_place','win','place'];
  const REFUNDS=['cancelled','no_contest','postponed'];
  const REASONS={RESULT_NOT_OBTAINED:['OFFICIAL_RESULT_NOT_OBTAINED'],RESULT_PENDING:['OFFICIAL_RESULT_PENDING'],
    SETTLEMENT_UNSUPPORTED:['OFFICIAL_REFUND_OUTCOME_UNSUPPORTED','OFFICIAL_TIE_COVERAGE_UNSUPPORTED','OFFICIAL_MARKET_COVERAGE_UNVERIFIED'],
    SETTLEMENT_PARTIAL:['OFFICIAL_MARKET_COVERAGE_INCOMPLETE'],SETTLEMENT_READY:[null]};
  const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
  const hash=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
  const day=value=>new Date(value+9*3600000).toISOString().slice(0,10);
  const fail=()=>{throw new Error('公式照合データの対象・時刻・確認証拠を確認できません。');};
  function time(value){
    const m=typeof value==='string'&&/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
    if(!m)fail();const stamp=Date.parse(value),local=new Date(m[1]+'Z');
    if(!Number.isFinite(stamp)||!Number.isFinite(local.getTime())||local.toISOString().slice(0,19)!==m[1]||Number(m[1].slice(0,4))<1)fail();
    if(m[3]!=='Z'&&(Number(m[3].slice(1,3))>23||Number(m[3].slice(4,6))>59))fail();return stamp;
  }
  function closing(race,dateJst){
    if(!race)fail();const value=/^\d{2}:\d{2}$/.test(race.closed_at)?dateJst+'T'+race.closed_at+':00+09:00':race.closed_at;
    const stamp=time(value);if(day(stamp)!==dateJst)fail();return stamp;
  }
  function exact(value,fields){if(!object(value)||Object.keys(value).sort().join()!==fields.slice().sort().join())fail();}
  function validateReport(raw,{race,dateJst,now=Date.now(),programSha256}={}){
    exact(raw,['schema_version','race_id','date_jst','as_of','closed_at','program_sha256','status','markets','excluded_market_types','result_proof','exclusion_reason']);
    if(!race||raw.schema_version!==1||raw.race_id!==race.race_id||!/^\d{8}-(?:0[1-9]|1\d|2[0-4])-(?:0[1-9]|1[0-2])$/.test(raw.race_id)||raw.date_jst!==dateJst||raw.race_id.slice(0,8)!==dateJst?.replaceAll('-','')||day(now)!==dateJst||!hash(raw.program_sha256)||!REASONS[raw.status]?.includes(raw.exclusion_reason))fail();
    if(programSha256!==undefined&&(!hash(programSha256)||raw.program_sha256!==programSha256))fail();
    const cutoff=closing(race,dateJst),asof=time(raw.as_of);
    if(time(raw.closed_at)!==cutoff||day(asof)!==dateJst||asof>now+60000)fail();
    if(!Array.isArray(raw.markets)||raw.markets.length>7||!Array.isArray(raw.excluded_market_types)||raw.excluded_market_types.length>7||new Set(raw.excluded_market_types).size!==raw.excluded_market_types.length||raw.excluded_market_types.some(t=>!TYPES.includes(t)))fail();
    const financial=['SETTLEMENT_READY','SETTLEMENT_PARTIAL'].includes(raw.status),proof=raw.result_proof;
    if(raw.status==='RESULT_NOT_OBTAINED'?proof!==null:!object(proof))fail();
    if(proof){
      exact(proof,['snapshot_id','source_url','source_sha256','captured_at','cloud_saved_at','status','finish_confirmed','financial_confirmed','top3']);
      if(!hash(proof.snapshot_id)||!hash(proof.source_sha256)||!['PENDING','settled','dead_heat','special',...REFUNDS].includes(proof.status)||typeof proof.finish_confirmed!=='boolean'||typeof proof.financial_confirmed!=='boolean')fail();
      let url;try{url=new URL(proof.source_url);}catch{fail();}const [,venue,number]=raw.race_id.split('-');
      if(url.protocol!=='https:'||url.hostname!=='www.boatrace.jp'||url.port||url.username||url.password||url.hash||url.pathname!=='/owpc/pc/race/raceresult'||[...url.searchParams.keys()].sort().join()!=='hd,jcd,rno'||url.searchParams.get('hd')!==dateJst.replaceAll('-','')||url.searchParams.get('jcd')!==venue||!/^\d{1,2}$/.test(url.searchParams.get('rno'))||Number(url.searchParams.get('rno'))!==Number(number))fail();
      const captured=time(proof.captured_at),saved=time(proof.cloud_saved_at);
      if(day(captured)!==dateJst||day(saved)!==dateJst||captured>saved||saved>asof||(['settled','dead_heat','special'].includes(proof.status)&&captured<cutoff))fail();
      if(proof.top3!==null&&(!Array.isArray(proof.top3)||proof.top3.length!==3||new Set(proof.top3).size!==3||proof.top3.some(v=>!Number.isInteger(v)||v<1||v>6)))fail();
      if(financial&&(proof.status==='PENDING'||(['settled','dead_heat'].includes(proof.status)&&(!proof.finish_confirmed||proof.top3===null))||(!REFUNDS.includes(proof.status)&&asof<cutoff)))fail();
      if(financial&&(proof.status==='dead_heat'||(REFUNDS.includes(proof.status)&&(!proof.financial_confirmed||raw.status!=='SETTLEMENT_READY'||proof.finish_confirmed||proof.top3!==null))))fail();
    }
    if(financial?raw.markets.length===0:raw.markets.length!==0)fail();
    const covered=new Set();
    for(const market of raw.markets){
      exact(market,['race_id','status','confirmed','verified_market_types','payouts','refunds','special_payouts']);
      const types=market.verified_market_types;
      const compatible=market.status===proof.status||(proof.status==='special'&&market.status==='settled');
      if(market.race_id!==raw.race_id||market.confirmed!==true||!compatible||!Array.isArray(types)||types.length!==1||!TYPES.includes(types[0])||covered.has(types[0])||raw.excluded_market_types.includes(types[0]))fail();
      const type=types[0];covered.add(type);
      if(!Array.isArray(market.payouts)||market.payouts.length>120||!Array.isArray(market.refunds)||market.refunds.length||!Array.isArray(market.special_payouts)||market.special_payouts.length>1)fail();
      if(['settled','dead_heat'].includes(market.status)&&!market.payouts.length)fail();
      for(const row of market.payouts){exact(row,['bet_type','combination','payout_per_100_yen']);if(row.bet_type!==type)fail();}
      for(const row of market.special_payouts){exact(row,['bet_type','payout_per_100_yen']);if(row.bet_type!==type)fail();}
      Money.settle_bets([],market);
    }
    if(TYPES.some(t=>!covered.has(t)&&!raw.excluded_market_types.includes(t))||(raw.status==='SETTLEMENT_READY'&&raw.excluded_market_types.length)||(raw.status==='SETTLEMENT_PARTIAL'&&!raw.excluded_market_types.length))fail();
    // Copy to prevent a later caller mutation from changing a validated response.
    return JSON.parse(JSON.stringify(raw));
  }
  function projectLedger(input,reports,{dateJst,now=Date.now(),races=[]}={}){
    const records=input.map(({id,race_id,purchased_at,bets})=>({id,race_id,purchased_at,bets:JSON.parse(JSON.stringify(bets))}));
    Money.summarize_ledger(records);
    const details=new Map(),effective=[];let hits=0;
    for(const record of records){
      const purchaseDay=day(time(record.purchased_at)),race=races.find(r=>r.race_id===record.race_id);let verified=null,settled=null,reason='公式結果の照合待ち';
      if(purchaseDay!==dateJst||record.race_id.slice(0,8)!==dateJst.replaceAll('-',''))reason='過去日の照合は未対応です';
      else if(!race)reason='当日の出走表が未取得です';
      else try{
        const raw=reports.get(record.race_id);if(raw){verified=validateReport(raw,{race,dateJst,now});const used=[...new Set(record.bets.map(b=>b.bet_type))],markets=used.map(t=>verified.markets.find(m=>m.verified_market_types[0]===t));
          if(markets.every(Boolean)){
            const result={race_id:record.race_id,status:markets.some(m=>m.status==='special')?'special':markets[0].status,confirmed:true,verified_market_types:used,payouts:markets.flatMap(m=>m.payouts),refunds:markets.flatMap(m=>m.refunds),special_payouts:markets.flatMap(m=>m.special_payouts)};
            settled=Money.settle_bets(record.bets,result);record.official_result=result;reason=REFUNDS.includes(result.status)?'公式証拠で全額返還を確認':'公式証拠で照合済み';
            if(settled.effective_stake_yen>0){effective.push(record);if(markets.filter(m=>m.status!=='special').some(m=>Money.settle_bets(record.bets.filter(b=>b.bet_type===m.verified_market_types[0]),m).payout_yen>0))hits++;}
          }
          else reason='購入した券種の確定証拠が不足しています';
        }
      }catch{reason='公式照合データを再確認してください';verified=null;}
      details.set(record.id,{settlement:settled,report:verified,reason});
    }
    return {records,summary:Money.summarize_ledger(records),details,hit_count:hits,effective_count:effective.length};
  }
  function canonical(value){if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';if(object(value))return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';return JSON.stringify(value);}
  async function programDigest(race){
    if(!object(race)||!Array.isArray(race.boats)||race.boats.length!==6)fail();
    const boats=race.boats.map(b=>({lane:b.lane,racer_registration_id:b.racer_registration_id,name:typeof b.name==='string'?b.name.normalize('NFKC').replace(/\s/g,''):''})).sort((a,b)=>a.lane-b.lane);
    if(boats.some((b,i)=>b.lane!==i+1||!/^\d{4}$/.test(b.racer_registration_id)||!b.name)||new Set(boats.map(b=>b.racer_registration_id)).size!==6)fail();
    const stamp=time(race.closed_at),fraction=/\.(\d{1,6})/.exec(race.closed_at)?.[1]||'',closed=new Date(stamp).toISOString().slice(0,19)+'.'+fraction.padEnd(6,'0')+'+00:00';
    const bytes=new TextEncoder().encode(canonical({race_id:race.race_id,closed_at:closed,boats}));
    const digest=await globalThis.crypto.subtle.digest('SHA-256',bytes);return [...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join('');
  }
  function appendAudit(audit,report,observedAt){
    if(!Array.isArray(audit)||audit.length>10000||audit.some(entry=>!object(entry)||typeof entry.race_id!=='string'||!object(entry.report)||typeof entry.observed_at!=='string'))throw new Error('保存済みの照合履歴を確認できないため、追記を停止しました。');
    if(!report.result_proof)return audit.slice();
    const fingerprint=canonical({...report,as_of:null});
    if(audit.some(entry=>entry.race_id===report.race_id&&canonical({...entry.report,as_of:null})===fingerprint))return audit.slice();
    return [...audit,{race_id:report.race_id,observed_at:observedAt,report:JSON.parse(JSON.stringify(report))}];
  }
  return {validateReport,projectLedger,appendAudit,programDigest};
});
