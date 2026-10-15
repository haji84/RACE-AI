/* Read-only replay. SHA pins are server-validated Python-canonical evidence, not JS float hashes. */
(function(root,factory){'use strict';const api=factory(typeof module==='object'&&module.exports?require('./ui-core.js'):root.RaceUI,typeof module==='object'&&module.exports?require('./name-bound-exhibition.js'):root.RaceNameBoundExhibition);if(typeof module==='object'&&module.exports)module.exports=api;root.RaceNameBoundEvaluation=api;})(typeof globalThis!=='undefined'?globalThis:this,function(UI,NameBound){
'use strict';
const SCOPE='SAME_RACE_DIFFERENT_FEATURE_PHASES_NOT_EQUAL_INFORMATION_CUTOFF';
const phases=['B_ONLY_BASELINE','DISPLAY_V2','ORIGINAL_V2'],labels=['B情報のみ比較元','通常展示反映','オリジナル展示反映'];
const fail=()=>{throw new Error('保存済み予想と公式結果の対象・固定リンク・時刻・スコアを確認できません。');},check=c=>{if(!c)fail();};
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
function exact(v,keys){check(object(v)&&Object.keys(v).sort().join()===keys.split(' ').sort().join());}
const number=(v,lo=-Infinity,hi=Infinity)=>check(typeof v==='number'&&Number.isFinite(v)&&v>=lo&&v<=hi);
const hash=v=>check(typeof v==='string'&&/^[a-f0-9]{64}$/.test(v));
const same=(a,b)=>check(JSON.stringify(a)===JSON.stringify(b));
function sum(values){let total=0,correction=0;for(const value of values){const next=total+value;correction+=Math.abs(total)>=Math.abs(value)?total-next+value:value-next+total;total=next;}return total+correction;}
function validateNameBoundEvaluation(value,forecast,race,now=Date.now()){
 try{
  number(now,0);check(Number.isSafeInteger(Math.floor(now)));NameBound.validateNameBoundComparison(forecast,race,now);
  check(new TextEncoder().encode(JSON.stringify(value)).length<=256000);
  exact(value,'schema_version race_id date_jst as_of closed_at status research_only validation_status purchase_decision purchase_recommendations comparison_scope physical_exhibition_timing_verified common_race_ids models forecast_proof result_proof exclusion_reason');
  const day=UI.dayJst(new Date(now)),clock=BigInt(Math.floor(now))*1000n;
  function time(v){const match=typeof v==='string'&&/^(\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d)(?:\.(\d{1,6}))?(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(v);check(match);const ms=Date.parse(v),local=new Date(match[1]+'Z');check(Number.isFinite(ms)&&Number.isFinite(local.getTime())&&local.toISOString().slice(0,19)===match[1]&&UI.dayJst(new Date(ms))===day);return BigInt(ms)*1000n+BigInt((match[2]||'').padEnd(6,'0').slice(3));}
  const close=time(race.closed_at),asOf=time(value.as_of);
  check(value.schema_version===1&&value.race_id===race.race_id&&value.date_jst===day&&time(value.closed_at)===close&&asOf<=clock);
  check(value.research_only===true&&value.validation_status==='UNVALIDATED'&&value.purchase_decision==='skip'&&value.comparison_scope===SCOPE&&value.physical_exhibition_timing_verified===false);same(value.purchase_recommendations,[]);
  const {receipt:r,finalization:f,baseline:b,inputs:i,name_binding:n}=forecast,s=r.snapshot,p=value.forecast_proof;
  exact(p,'request_id snapshot_id envelope_sha256 baseline_request_id baseline_snapshot_id baseline_receipt_sha256 name_binding_request_id input_snapshot_id generated_at cloud_saved_at receipt_confirmed_at');
  // The full-envelope digest is a server pin; every browser-comparable parent/nonce is exact.
  hash(p.envelope_sha256);
  const pinned={request_id:r.request_id,snapshot_id:s.snapshot_id,baseline_request_id:b.request_id,baseline_snapshot_id:b.snapshot.snapshot_id,baseline_receipt_sha256:s.baseline_link.receipt_sha256,name_binding_request_id:n.receipt.request_id,input_snapshot_id:i.snapshot_id,generated_at:s.generated_at,cloud_saved_at:r.cloud_saved_at,receipt_confirmed_at:f.receipt_confirmed_at};
  for(const key of Object.keys(pinned))check(p[key]===pinned[key]);
  check(time(p.generated_at)<=time(p.cloud_saved_at)&&time(p.cloud_saved_at)<=time(p.receipt_confirmed_at)&&time(p.receipt_confirmed_at)<=asOf);
  let expected='RESULT_NOT_OBTAINED',reason='OFFICIAL_RESULT_NOT_OBTAINED';
  const result=value.result_proof;
  if(result!==null){
   exact(result,'snapshot_id source_url source_sha256 captured_at cloud_saved_at status finish_confirmed financial_confirmed top3 refund_boats program_identity_sha256');
   for(const key of ['snapshot_id','source_sha256','program_identity_sha256'])hash(result[key]);check(result.program_identity_sha256===s.validation_program_identity_sha256);
   const capture=time(result.captured_at),saved=time(result.cloud_saved_at);check(close<=capture&&capture<=saved&&saved<=asOf);
   check(typeof result.finish_confirmed==='boolean'&&typeof result.financial_confirmed==='boolean'&&['PENDING','postponed','cancelled','no_contest','special','dead_heat','settled'].includes(result.status));
   const refunds=result.refund_boats;check(Array.isArray(refunds)&&refunds.every((lane,index)=>Number.isInteger(lane)&&lane>=1&&lane<=6&&(!index||lane>refunds[index-1])));
   const top=result.top3;check(top===null||Array.isArray(top)&&top.length===3&&new Set(top).size===3&&top.every(lane=>Number.isInteger(lane)&&lane>=1&&lane<=6));
   const url=new URL(result.source_url),[date,venue,raceNo]=race.race_id.split('-');
   check(typeof result.source_url==='string'&&url.protocol==='https:'&&url.hostname==='www.boatrace.jp'&&!url.port&&!url.username&&!url.password&&!url.hash&&url.pathname==='/owpc/pc/race/raceresult'&&[...url.searchParams.keys()].sort().join()==='hd,jcd,rno'&&url.searchParams.get('hd')===date&&url.searchParams.get('jcd')===venue&&/^[0-9]{1,2}$/.test(url.searchParams.get('rno'))&&Number(url.searchParams.get('rno'))===Number(raceNo));
   if(result.status==='PENDING'||result.status==='postponed'&&!result.financial_confirmed){expected='RESULT_PENDING';reason='OFFICIAL_RESULT_PENDING';}
   else if(result.status!=='settled'){expected='RESULT_UNSUPPORTED';reason='OFFICIAL_RESULT_STATUS_UNSUPPORTED';}
   else if(!result.finish_confirmed){expected='RESULT_PENDING';reason='OFFICIAL_RESULT_PENDING';}
   else if(refunds.length){expected='RESULT_UNSUPPORTED';reason='OFFICIAL_REFUND_OUTCOME_UNSUPPORTED';}
   else if(top===null){expected='RESULT_UNSUPPORTED';reason='OFFICIAL_TOP3_NOT_UNIQUE';}
   else{expected='EVALUATED';reason=null;}
  }
  check(value.status===expected&&value.exclusion_reason===reason);
  if(expected!=='EVALUATED'){same(value.models,[]);same(value.common_race_ids,[]);return value;}
  same(value.common_race_ids,[race.race_id]);check(Array.isArray(value.models)&&value.models.length===3);
  const selected=b.snapshot.models.find(model=>model.model_id===s.baseline_link.model_id);
  [selected,...s.models].forEach((model,index)=>{
   const row=value.models[index],source=index?r:b;exact(row,'model_id model_version phase race_count ticket_count multiclass_brier log_loss winner_probability forecast_generated_at forecast_cloud_saved_at');
   check(row.model_id===model.model_id&&row.model_version===model.model_version&&row.phase===phases[index]&&row.race_count===1&&row.ticket_count===120&&row.forecast_generated_at===source.snapshot.generated_at&&row.forecast_cloud_saved_at===source.cloud_saved_at);
   const errors=[];let winner=null;check(model.triples.length===120);
   for(const triple of model.triples){number(triple.probability,Number.MIN_VALUE,1);const hit=triple.combination.join('-')===result.top3.join('-');errors.push((triple.probability-(hit?1:0))**2);if(hit){check(winner===null);winner=triple.probability;}}
   check(winner!==null);number(row.multiclass_brier,0,2);number(row.log_loss,0);number(row.winner_probability,Number.MIN_VALUE,1);
   for(const [key,want]of [['multiclass_brier',sum(errors)],['log_loss',-Math.log(winner)],['winner_probability',winner]])check(Math.abs(row[key]-want)<=1e-12);
  });
  return value;
 }catch{fail();}
}
const escape=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function renderNameBoundEvaluation(report,forecast,race,now=Date.now()){
 validateNameBoundEvaluation(report,forecast,race,now);
 const p=report.forecast_proof,result=report.result_proof;
 const messages={RESULT_NOT_OBTAINED:'公式結果は未取得です。',RESULT_PENDING:'公式結果は未確定です。',RESULT_UNSUPPORTED:'この公式結果は照合対象外です。'};
 let html='<p class="nb-evaluation-version">'+escape(race.venueName||race.race_id)+' · 予想の保存番号 '+escape(p.request_id)+' · '+escape(report.status)+'</p>';
 if(result)html+='<p>公式着順: '+escape(result.top3?.join(' → ')||'未確認')+' · 着順確認 '+escape(result.finish_confirmed)+' · 払戻等の金銭確認 '+escape(result.financial_confirmed)+'</p>';
 if(report.status==='EVALUATED'){
  html+='<p>N=1（同一レース・各120通り）。</p><div class="table-scroll" tabindex="0" role="region" aria-label="保存済み予想と公式結果の3モデル照合"><table><thead><tr>'+['入力段階','モデル / 版','N','Brier','log loss','的中順序の確率','予想生成','予想クラウド保存'].map(x=>'<th scope="col">'+escape(x)+'</th>').join('')+'</tr></thead><tbody>';
  report.models.forEach((row,index)=>{html+='<tr class="nb-evaluation-score">'+[labels[index],row.model_id+' / '+row.model_version,row.race_count,row.multiclass_brier.toFixed(12),row.log_loss.toFixed(12),(row.winner_probability*100).toFixed(6)+'%',row.forecast_generated_at,row.forecast_cloud_saved_at].map(x=>'<td>'+escape(x)+'</td>').join('')+'</tr>';});html+='</tbody></table></div>';
 }else html+='<p>'+escape(messages[report.status])+' サンプル数・スコアは表示しません。理由: '+escape(report.exclusion_reason)+'</p>';
 html+='<p>入力段階が異なる比較です。同一の情報締切での比較ではありません。物理的な展示前の時点も証明していません。着順の確認と払戻・返還の金銭確認は別です。1レースから精度向上・収益性・モデル採用を判断できません。</p><p>research_only=true · UNVALIDATED · skip · []（購入推奨なし）</p>';
 html+='<details><summary>固定予想と公式結果の出典・保存時刻</summary><p>照合時刻 '+escape(report.as_of)+' · 締切 '+escape(report.closed_at)+'</p><p>予想生成 '+escape(p.generated_at)+' · クラウド保存 '+escape(p.cloud_saved_at)+' · 保存確認 '+escape(p.receipt_confirmed_at)+'</p><p>予想snapshot '+escape(p.snapshot_id)+' · envelope SHA-256 '+escape(p.envelope_sha256)+' · 比較元 '+escape(p.baseline_request_id)+' / '+escape(p.baseline_snapshot_id)+' · 比較元receipt SHA-256 '+escape(p.baseline_receipt_sha256)+' · 氏名照合 '+escape(p.name_binding_request_id)+' · 入力 '+escape(p.input_snapshot_id)+'</p>';
 if(result)html+='<p>結果出典 <a href="'+escape(result.source_url)+'" target="_blank" rel="noopener noreferrer">'+escape(result.source_url)+'</a></p><p>結果取得 '+escape(result.captured_at)+' · 結果クラウド保存 '+escape(result.cloud_saved_at)+'</p><p>結果snapshot '+escape(result.snapshot_id)+' · source SHA-256 '+escape(result.source_sha256)+' · 氏名照合後の出走表SHA-256 '+escape(result.program_identity_sha256)+' · 返還艇 '+escape(JSON.stringify(result.refund_boats))+'</p>';
 return html+'<p>SHA-256 はサーバーで検証した Python 正規化形式の固定値です。ブラウザは保存済み予想の確率と3スコアを数値で再計算します。公式ページの再取得や Python 浮動小数点のハッシュ再計算は行いません。</p></details>';
}
return {validateNameBoundEvaluation,renderNameBoundEvaluation};
});
