/* One audited historical artifact. No live feed, source acquisition or writes. */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else {root.RaceAIArchivedCohort=api;api.mount(root.document);}
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const SHA='77c93e07046721de8cead6ef21515f7d190601db63b92abfaee82c43f95e20d6';
  const AUDITED='2026-10-16T02:16:37.318964+00:00';
  const EVIDENCE='https://github.com/haji84/RACE-AI/blob/99eef90bd88b5c377cef1e00ee4be81667c11fe9/docs/evidence/2026-10-16/archived-cohort-three-artifact-audit.md';
  const labels=['B情報のみ比較元','通常展示反映','オリジナル展示反映'];
  const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function verify(bytes,crypto,now=new Date()){
    const raw=bytes instanceof ArrayBuffer?new Uint8Array(bytes):bytes;
    if(!(raw instanceof Uint8Array)||raw.byteLength!==7173||!crypto?.subtle||!(now instanceof Date)||!Number.isFinite(now.getTime())||now.getTime()<Date.parse(AUDITED))throw new Error('履歴集計の証拠を確認できません。');
    const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),b=>b.toString(16).padStart(2,'0')).join('');
    if(digest!==SHA)throw new Error('履歴集計の原文が監査済みの内容と一致しません。');
    return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));
  }
  function render(report){
    // Called only after verify() authenticates the complete report bytes.
    const rows=report.models.map((m,i)=>`<tr data-cohort-model="${esc(m.phase)}"><th scope="row">${labels[i]}</th><td>${m.mean_multiclass_brier.toFixed(6)}</td><td>${m.mean_log_loss.toFixed(6)}</td><td>${(m.mean_winner_probability*100).toFixed(3)}%</td><td>${m.mean_brier_delta_from_baseline.toFixed(6)}</td><td>${m.mean_log_loss_delta_from_baseline.toFixed(6)}</td></tr>`).join('');
    const races=report.observations.map(o=>`<li>${esc(o.race_id)}：元評価時点 <time datetime="${esc(o.original_evaluation_as_of)}">${esc(o.original_evaluation_as_of)}</time></li>`).join('');
    return `<p><strong>${report.race_count}レース / ${report.day_count}日</strong>（${esc(report.evaluated_dates[0])} ～ ${esc(report.evaluated_dates.at(-1))}）の保存済み履歴です。当日全レースの成績ではありません。</p>
      <p class="state-pill warning">研究用・未検証（UNVALIDATED）</p>
      <p>集計時点：<time datetime="${esc(report.as_of)}">${esc(report.as_of)}</time><br>独立監査時点：<time datetime="${AUDITED}">${AUDITED}</time>（UTC）</p>
      <div class="table-scroll" tabindex="0" role="region" aria-label="保存済み三版の平均評価値。横に移動できます"><table><caption>各レース120通りの三連単を評価した平均値</caption><thead><tr><th scope="col">予想の版</th><th scope="col">Brier Score</th><th scope="col">Log Loss</th><th scope="col">実着順への平均予測確率</th><th scope="col">Brier差分</th><th scope="col">Log Loss差分</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="photo-note">Brier Score・Log Lossは低いほど、この対象内での誤差が小さい指標です。差分は同じレースのB情報のみ比較元との差の平均です。小標本の事後比較であり、精度改善や採用判断の根拠にはできません。</p>
      <p>物理的な展示前後の対：0。展示前の実保存を独立時計で確認した比較ではありません。未使用期間の評価・確率校正・映像の寄与・採用判断は未検証です。購入見送り・推奨買い目なしを維持します。</p>
      <details><summary>対象レースと監査証拠</summary><ul>${races}</ul><p>集計の原文と元評価時点を保持しています。表示時に元の予測・結果を再取得したり、再集計したりしません。</p><p><a href="${EVIDENCE}" target="_blank" rel="noopener noreferrer">固定版の独立監査記録を確認</a></p><p class="photo-note">原文 SHA-256：${SHA}<br>集計識別子：${esc(report.snapshot_id)}</p></details>`;
  }
  function controller(elements,{fetch:fetcher=globalThis.fetch,crypto=globalThis.crypto,now=()=>new Date()}={}){
    let busy=false;
    return async function load(){
      if(busy)return;
      busy=true;elements.button.disabled=true;elements.content.innerHTML='';
      elements.status.textContent='保存済み履歴を照合しています。';elements.status.dataset.state='loading';
      const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),10000);
      try{
        const response=await fetcher('/api/archived-cohort',{method:'GET',cache:'no-store',credentials:'same-origin',redirect:'error',signal:abort.signal});
        if(!response.ok)throw new Error('保存済み履歴を取得できません。');
        const bytes=await response.arrayBuffer();
        const report=await verify(bytes,crypto,now());
        elements.content.innerHTML=render(report);
        elements.status.textContent='監査済み原文との一致を確認しました。予測精度は未検証です。';elements.status.dataset.state='success';
      }catch{
        elements.content.innerHTML='';elements.status.textContent='履歴集計の証拠を確認できません。時間をおいて再確認してください。';elements.status.dataset.state='error';
      }finally{clearTimeout(timer);busy=false;elements.button.disabled=false;}
    };
  }
  function mount(document){
    const button=document?.getElementById('archived-cohort-load'),status=document?.getElementById('archived-cohort-status'),content=document?.getElementById('archived-cohort-content');
    if(button&&status&&content)button.addEventListener('click',controller({button,status,content}));
  }
  return {verify,render,controller,mount};
});
