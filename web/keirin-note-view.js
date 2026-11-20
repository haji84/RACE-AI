/* A separate owner view. It never writes the formal model ledger or changes its keys. */
(() => {
  'use strict';
  const M=window.RaceKeirinNote;
  if(!M||document.getElementById('keirin-note-dialog'))return;
  const fragment=window.RaceNoteInitialFragment||location.hash;
  const dialog=document.createElement('dialog');dialog.id='keirin-note-dialog';dialog.className='kn-modal';dialog.setAttribute('aria-label','競輪の予想・分析ガイド');
  const host=document.createElement('div');host.className='kn-host';dialog.append(host);
  const root=host.attachShadow({mode:'open'}),sheet=document.createElement('link');sheet.rel='stylesheet';sheet.href=document.querySelector('link[rel="stylesheet"]')?.href||'./style.css';root.append(sheet);
  const shell=document.createElement('div');shell.className='kn-shell';root.append(shell);document.body.append(dialog);
  const launcher=document.createElement('button');launcher.id='keirin-note-open';launcher.type='button';launcher.className='kn-launcher';launcher.textContent='競輪の予想・分析ガイドを開く';
  const strip=document.createElement('div');strip.className='kn-launch-strip';strip.append(launcher);(document.getElementById('data-banner')||document.querySelector('main'))?.after(strip);
  let data=null,currentDay='',venue='',query='',market='3t',variant='flexible',futureOnly=false,selectedOnly=false;
  let loadVersion=0,activeLoadAbort=null,feedWatcher=null,pendingFeed=null;
  const preferences=new Map(),selected=new Set(),expanded=new Set();
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=v=>Number.isFinite(v)?v.toLocaleString('ja-JP')+'円':'未確認';
  const $=id=>root.getElementById(id),all=()=>data?M.rows(data,currentDay):[];
  const time=v=>v&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleTimeString('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit'}):'未確認';
  const stamp=v=>v&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo',hour12:false}):'未確認';
  const num=(v,suffix='')=>typeof v==='number'&&Number.isFinite(v)?esc(v)+suffix:'未確認';
  const car=n=>Number.isInteger(n)&&n>=1&&n<=9?'<span class="kn-car kn-c'+n+'">'+n+'</span>':'';
  const pref=row=>{const key=row.id+':'+market+':'+variant;if(!preferences.has(key))preferences.set(key,{budget:2500,excluded:new Set()});return preferences.get(key);};
  function sourceLink(url,label){const safe=M.safeUrl(url);return safe?'<a target="_blank" rel="noopener noreferrer" href="'+esc(safe)+'">'+esc(label)+'</a>':'';}
  function note(message,error=false){$('kn-status').textContent=message;$('kn-status').classList.toggle('kn-error',error);}
  function beginLoad(){loadVersion++;activeLoadAbort?.abort();activeLoadAbort=null;feedWatcher?.stop();feedWatcher=null;pendingFeed=null;return loadVersion;}
  function build(){
    shell.innerHTML=`<header class="kn-head"><div><p class="kn-eyebrow">RACE AI · KEIRIN NOTE</p><h1>競輪の読みどころ</h1><p>保存された分析・参考モデル・買い目を確認する</p></div><button type="button" id="kn-close" class="kn-close">閉じる</button></header>
      <div class="kn-scroll"><section class="kn-import"><div><label class="kn-file">保存データを開く<input id="kn-file" type="file" accept=".json,application/json"></label><button id="kn-clear" type="button" class="kn-secondary">読込データを消す</button></div><p id="kn-status" role="status">本人用リンク、または保存データJSONから開けます。</p></section>
      <nav id="kn-days" class="kn-day-tabs" aria-label="予想の日付"></nav><section id="kn-metrics" class="kn-metrics"></section>
      <section class="kn-tools"><div id="kn-venues" class="kn-venues" aria-label="会場"></div><div class="kn-controls"><label>券種<select id="kn-market"><option value="3t">3連単</option><option value="2t">2車単</option></select></label><label>表示する予想<select id="kn-variant"><option value="flexible">改訂された分析</option><option value="original">原分析</option><option value="rollover">絞り込み分析</option><option value="A">参考A</option><option value="B">参考B・6局面</option><option value="C">参考Cの状況</option></select></label><label class="kn-search-label">検索<input id="kn-search" type="search" placeholder="会場・選手・レース名"></label></div><div class="kn-small-controls"><label><input id="kn-future" type="checkbox">これからのレース</label><label><input id="kn-selected" type="checkbox">検討リストのみ</label><span id="kn-count"></span></div></section>
      <section id="kn-nationwide-summary" class="kn-result kn-nationwide-summary" hidden></section><section id="kn-research-summary" class="kn-result" hidden></section><div id="kn-result-only"></div><div id="kn-races" class="kn-grid"></div>
      <details class="kn-rollover"><summary>2段階の資金配分を試算する</summary><p>受取額は払戻と返還の合計を手入力します。実購入の記録とは別の試算です。</p><div class="kn-controls"><label>初回の予算<select id="kn-roll-budget"><option>2000</option><option selected>2500</option><option>3000</option></select></label><label>1戦目の受取額<input id="kn-return-one" type="number" min="0" max="100000000" step="100" placeholder="未入力"></label><label>2戦目の受取額<input id="kn-return-two" type="number" min="0" max="100000000" step="100" placeholder="未入力"></label></div><div id="kn-roll-result"></div></details>
      <footer class="kn-footer"><p>個別分析・改訂・参考A/Bはそれぞれの保存原本を保持します。参考Cの未生成も表示します。参考モデルの重みは校正済み確率ではありません。</p><p>画面での選択と配分は購入候補です。投票・決済は行いません。データと本人用リンクの鍵は外部へ送信しません。</p><p id="kn-provenance"></p></footer></div>
      <div class="kn-selection"><div><strong id="kn-selection-count">検討リスト 0件</strong><small>候補・配分の試算</small></div><button id="kn-copy-selection" type="button">検討リストをコピー</button></div>`;
    $('kn-close').addEventListener('click',()=>dialog.close());
    $('kn-file').addEventListener('change',async event=>{
      // Shadow-tree event targets are cleared after dispatch. Keep the input
      // itself before awaiting file reads so the completed import can reset it.
      const input=event.currentTarget,file=input.files?.[0];if(!file)return;
      const version=beginLoad();
      try{if(file.size>64*1024*1024)throw Error();note('保存データを確認しています。');await accept(await M.openPacket(JSON.parse(await file.text())),version);}
      catch{if(version===loadVersion)note('保存データを開けませんでした。形式と原本の整合を確認してください。',true);}
      if(version===loadVersion)input.value='';
    });
    $('kn-clear').addEventListener('click',()=>{beginLoad();data=null;currentDay='';preferences.clear();selected.clear();expanded.clear();if(/^#(?:note|notefeed)=/.test(location.hash)){history.replaceState(null,'',location.pathname+location.search);window.RaceNoteInitialFragment='';}render();note('読込データを消去しました。');});
    $('kn-market').addEventListener('change',event=>{market=event.target.value;renderCards();});
    $('kn-variant').addEventListener('change',event=>{variant=event.target.value;renderCards();});
    $('kn-search').addEventListener('input',event=>{query=event.target.value.trim().toLocaleLowerCase('ja');renderCards();});
    $('kn-future').addEventListener('change',event=>{futureOnly=event.target.checked;renderCards();});
    $('kn-selected').addEventListener('change',event=>{selectedOnly=event.target.checked;renderCards();});
    root.addEventListener('click',event=>click(event.target.closest('button')));
    root.addEventListener('change',event=>{const e=event.target;if(e.matches('[data-budget]')){const row=all().find(r=>r.id===e.dataset.budget);if(row){pref(row).budget=Number(e.value);renderCards();}}else if(e.matches('[data-ticket]')){const row=all().find(r=>r.id===e.dataset.race);if(row){const p=pref(row);e.checked?p.excluded.delete(e.dataset.ticket):p.excluded.add(e.dataset.ticket);renderCards();}}});
    for(const id of ['kn-roll-budget','kn-return-one','kn-return-two'])$(id).addEventListener('input',renderRollover);
    $('kn-copy-selection').addEventListener('click',()=>copy(all().filter(r=>selected.has(r.id)).map(copyRace).filter(Boolean).join('\n\n')));
    render();renderRollover();
  }
  async function accept(value,version){if(version!==loadVersion)return;data=value;currentDay=data.dates.at(-1);venue='';query='';$('kn-search').value='';preferences.clear();selected.clear();expanded.clear();const authored=all().some(row=>row.original?.tickets?.length||row.two?.tickets?.length||row.flexible?.markets?.['3t']?.tickets?.length||row.flexible?.markets?.['2t']?.tickets?.length);variant=authored?'flexible':'A';if(!authored){market='3t';$('kn-market').value=market;}$('kn-variant').value=variant;render();note(data.feed?.providerDenied?'保存データを端末内で開きました。入力元への取得は停止中です。保存済み結果の更新は確認します。':'保存データを端末内で開きました。',Boolean(data.feed?.providerDenied));}
  function refreshDisplay(value,version){
    if(version!==loadVersion)return;
    if(root.activeElement?.matches('[data-budget],[data-ticket]')){pendingFeed={value,version};return;}
    pendingFeed=null;const same=data?.feed?.revision===value.feed?.revision;
    data=value;if(!data.dates.includes(currentDay))currentDay=data.dates.at(-1)||'';
    if(same){renderProvenance();note(data.feed?.providerDenied?'保存データの更新を確認しました。入力元への取得は停止中です。':'保存データの更新を確認しました。',Boolean(data.feed?.providerDenied));return;}
    const scroll=root.querySelector('.kn-scroll'),position=scroll.scrollTop;render();scroll.scrollTop=position;
    note(data.feed?.providerDenied?'保存された結果を更新しました。入力元への取得は停止中です。':'保存された最新の結果を反映しました。',Boolean(data.feed?.providerDenied));
  }
  function renderProvenance(){
    const observations=data?[...data.resultUpdates.values()].flatMap(rows=>[...rows.values()].map(r=>r.observed_at)):[];
    const latest=observations.sort((a,b)=>Date.parse(a)-Date.parse(b)).at(-1);
    $('kn-provenance').textContent=data?'読込日時 '+stamp(data.importedAt)+' · 出典と予想時点は各レースで確認できます。'+(data.feed?' · 表示確認 '+stamp(data.feed.checkedAt)+'（表示中は30秒ごとに保存データを確認）':'')+(latest?' · 結果確認 '+stamp(latest):'')+(data.refreshHolds?.length?' · 入力変更 '+data.refreshHolds.length+'件は原分析との照合待ちです。':''):'';
  }
  function render(){
    const days=data?.dates||[];$('kn-days').innerHTML=days.map(d=>'<button type="button" data-day="'+esc(d)+'" aria-pressed="'+(d===currentDay)+'">'+esc(d.slice(5).replace('-','月')+'日')+'</button>').join('');
    const list=all(),riders=list.reduce((n,r)=>n+r.riders.length,0),original=list.reduce((n,r)=>n+M.forecast(r,'3t','original').tickets.length,0),priced=list.filter(r=>r.quote.fetched_at).length;
    const nationwide=data?.nationwide?.get(currentDay),saved=nationwide?.races.filter(row=>row.original_identity).length||0,adjusted=nationwide?.races.filter(row=>row.original_identity?.conditioned).length||0;
    const metrics=nationwide?[['確認した対象',nationwide.registry_available?nationwide.races.length+'件':'確認中'],['A保存済み',saved+'件'],['B保存済み',saved+'件'],['補正A/B保存済み',adjusted+'件']]:[['対象レース',list.length+'件'],['出走メンバー',riders+'名'],['原分析の買い目',original+'点'],['保存オッズ',priced+'レース']];
    $('kn-metrics').innerHTML=metrics.map(([k,v])=>'<div><span>'+esc(k)+'</span><strong>'+esc(v)+'</strong></div>').join('');
    const imported=list.some(row=>!row.nationwideOnly);$('kn-market').disabled=Boolean(nationwide)&&!imported;$('kn-variant').disabled=Boolean(nationwide)&&!imported;
    const venues=[...new Set(list.map(r=>r.venue))];$('kn-venues').innerHTML=[['','締切順・全会場'],...venues.map(v=>[v,v])].map(([v,label])=>'<button type="button" data-venue="'+esc(v)+'" aria-pressed="'+(v===venue)+'">'+esc(label)+'</button>').join('');
    renderProvenance();
    renderCards();
  }
  function renderCards(){
    const list=all(),now=Date.now();const shown=list.filter(r=>(!venue||r.venue===venue)&&(!query||(r.venue+' '+r.title+' '+r.riders.map(p=>p.name).join(' ')+' '+r.original.headline).toLocaleLowerCase('ja').includes(query))&&(!futureOnly||r.cutoff&&Date.parse(r.cutoff)>now)&&(!selectedOnly||selected.has(r.id)));
    $('kn-count').textContent='表示 '+shown.length+' / 全'+list.length+'レース';
    $('kn-races').innerHTML=shown.length?shown.map(renderRace).join(''):'<div class="kn-empty">'+(data?'条件に合うレースはありません。':'本人用リンク、または保存データを開くと予想を表示します。')+'</div>';
    renderNationwideSummary();
    renderResearchSummary(list);
    selectionSummary();
  }
  function lineHtml(row){
    const line=n=>Number.isInteger(n)?car(n):n&&Array.isArray(n.contest)?'<span class="kn-contest">'+n.contest.map(car).join('')+'<small>競り</small></span>':'';
    return row.lines.map(group=>'<span class="kn-line">'+(Array.isArray(group)?group:[]).map(line).join('<span>−</span>')+'</span>').join('<span class="kn-line-gap">/</span>');
  }
  function renderRace(row){
    if(row.nationwideOnly)return renderNationwideRace(row);
    const prediction=M.forecast(row,market,variant),p=pref(row),allocation=M.allocate(prediction,p.budget,p.excluded),key=row.id+':'+market+':'+variant,open=expanded.has(key);
    const late=row.cutoff&&Date.parse(row.cutoff)<Date.now();
    const items=prediction.tickets.map((ticket,i)=>{
      const quote=row.quote[market==='2t'?'odds_2t':'odds_3t']?.[ticket.combo],status=row.quote[market==='2t'?'quote_status_2t':'quote_status_3t']?.[ticket.combo];
      const odds=typeof quote==='number'&&quote>0&&quote<9999.9?quote+'倍':status==='capped'?'上限表示':'未確認';
      return '<div class="kn-ticket '+(!open&&i>=3?'kn-ticket-folded':'')+'"><label>'+ (prediction.allocatable?'<input type="checkbox" data-ticket="'+esc(ticket.combo)+'" data-race="'+row.id+'" '+(!p.excluded.has(ticket.combo)?'checked':'')+' aria-label="'+esc(ticket.combo)+'を配分対象にする">':'')+'<span class="kn-combo">'+ticket.combo.split('-').map(Number).map(car).join('<span>−</span>')+'</span><span class="kn-role">'+esc(ticket.role)+'</span></label><div><b>'+ (prediction.allocatable?money(allocation.amounts[i]):'比較用')+'</b><small>'+esc(odds)+'</small></div></div>';
    }).join('');
    const outcome=row.settlement;
    const result=liveResult(row)+(outcome?'<section class="kn-result"><b>提供サイトの保存分析の照合</b><p>'+esc(outcome.winning_combo||'結果未確認')+' · '+(outcome.sources_agree===false?'出典間の相違で保留':outcome.hit?'的中':outcome.status==='MISS'?'不的中':esc(outcome.status||'照合未確認'))+'</p><p>各100円の想定：'+money(outcome.net_yen)+'（実購入ではありません）</p></section>':'');
    const budget=prediction.allocatable?'<div class="kn-budget"><label>候補予算<select data-budget="'+row.id+'">'+[2000,2500,3000].map(n=>'<option value="'+n+'" '+(n===p.budget?'selected':'')+'>'+money(n)+'</option>').join('')+'</select></label><span>配分 '+allocation.chosen.length+'点 / 合計 '+money(allocation.total)+'</span></div>':'';
    return '<article class="kn-race" data-note-race="'+row.id+'"><div class="kn-race-top"><div><h2>'+esc(row.venue)+' '+row.number+'R</h2><p>'+esc(row.title)+'</p></div><div class="kn-time"><small>掲載締切</small><b>'+time(row.cutoff)+'</b><small>発走 '+time(row.start)+'</small></div></div><div class="kn-badges"><span>'+esc(prediction.label)+'</span>'+(late?'<span class="kn-past">掲載締切後</span>':'')+(prediction.confidence?'<span>分析区分 '+esc(prediction.confidence)+'</span>':'')+'</div><h3>'+esc(prediction.headline)+'</h3><p class="kn-reason">'+esc(prediction.reason)+'</p><div class="kn-lines">'+lineHtml(row)+'</div><p class="kn-small">媒体の並び予想・位置取りの参考です。</p>'+budget+
      '<div class="kn-point-heading"><b>予想 '+prediction.tickets.length+'点'+(prediction.allocatable?' · 配分 '+allocation.chosen.length+'点':'')+'</b></div><div class="kn-tickets">'+(items||'<p class="kn-empty">'+esc(prediction.reason||'この券種の保存予想はありません。')+'</p>')+'</div>'+(prediction.tickets.length>3?'<button type="button" class="kn-more" data-expand="'+row.id+'">'+(open?'上位3点に戻す':'全'+prediction.tickets.length+'点を表示')+'</button>':'')+
      (prediction.allocatable&&!allocation.available?'<p class="kn-warning">配分対象がないか、全点への100円単位の配分に予算が足りません。点数を選び直してください。</p>':'')+
      '<div class="kn-race-actions"><button type="button" data-select="'+row.id+'" aria-pressed="'+selected.has(row.id)+'">'+(selected.has(row.id)?'検討リストから外す':'検討リストに追加')+'</button><button type="button" data-copy="'+row.id+'" '+(prediction.allocatable&&!allocation.available?'disabled':'')+'>買い目をコピー</button></div>'+nationalStatus(row)+result+researchResult(row)+
      scenarios(prediction.scenarios)+roster(row)+
      '<details class="kn-details"><summary>出典・予想時点・注意点</summary><p>'+esc(prediction.risk||'保存された条件付きの分析です。')+'</p><p>予想の記載時点 '+stamp(prediction.createdAt)+'</p><p>オッズの保存時点 '+stamp(row.quote.source_updated_at||row.quote.fetched_at)+'</p><p>'+esc(row.quote.scope_label||'保存時点の値。現在値は掲載元で確認してください。')+'</p>'+sourceLink(row.sourceUrl,'出走表・掲載オッズ')+referenceProvenance(row)+'<p class="kn-small">参考A/Bは既存計算、Cは独立した連係履歴が不足しているため未生成です。正式な全モデル実測の認証とは別に表示しています。</p></details></article>';
  }
  function nationalStateLabel(state){
    const labels={WAITING_SOURCE_CAPTURE:'出走表などの取得待ち',UNSUPPORTED_CLASS_OR_ROUND:'この種別・勝ち上がり条件の確認待ち',PUBLISHED_RESULT_NO_PRE_CUTOFF_ORIGINAL:'締切前の保存予想なし',FROZEN_ORIGINAL_PRESERVED:'締切前に保存した予想を保持',SOURCE_CAPTURE_BUDGET_PENDING:'次の情報取得を待っています',CUTOFF_MARGIN_INSUFFICIENT:'締切前の保存に間に合わず未作成',BASELINE_SOURCE_UNVERIFIED:'出走表・並びの照合待ち',PROVIDER_STOPPED:'取得先の制限により情報収集を停止中',SOURCE_UNAVAILABLE:'必要な情報を取得できず保留',A_B_ARCHIVED_AWAITING_INDEPENDENT_READBACK:'A/Bの保存内容を確認中',A_B_AUTHENTICATED_PRE_CUTOFF:'A/Bの締切前保存を確認済み',ORIGIN_PROOF_PENDING:'締切前の保存記録を確認中',FROZEN_ARCHIVE_UNVERIFIED:'保存原本の再確認待ち',RACE_DISAPPEARED_FROM_CURRENT_LIST:'開催一覧から外れたため確認中'};
    return labels[state]||'保存状況を確認中';
  }
  function conditionLabel(state){
    const labels={HISTORY_NOT_COLLECTED:'近況・落車後の資料を収集中',HISTORY_SOURCE_UNAVAILABLE:'近況・落車後の資料を取得できず補正は保留',HISTORY_UNVERIFIED:'近況・落車後の資料を照合中',INSUFFICIENT_CAPTURE_MARGIN:'締切までに補正を保存できず未作成',CONDITIONED_ARCHIVED_AWAITING_READBACK:'補正A/Bの保存内容を確認中',CONDITIONED_AUTHENTICATED_PRE_CUTOFF:'補正A/Bの締切前保存を確認済み',CONDITIONED_ORIGIN_PROOF_PENDING:'補正A/Bの保存記録を確認中',CONDITIONED_ARCHIVE_UNVERIFIED:'補正A/Bの原本を再確認中',NO_CONDITIONED_ORIGINAL:'補正A/Bの保存予想なし'};
    return labels[state]||'補正A/Bの資料待ち';
  }
  function nationalStatus(row){
    const status=row.nationwideStatus;if(!status)return '';
    return '<section class="kn-nationwide-status" data-nationwide-state="'+esc(status.state)+'"><p><b>'+nationalStateLabel(status.state)+'</b></p><p>'+conditionLabel(status.condition_state)+'</p>'+(status.original_identity&&!row.frozenForecast?'<p class="kn-warning">以前に保存した買い目は未読込です。未作成や不的中には数えていません。</p>':'')+'</section>';
  }
  function renderNationwideRace(row){
    return '<article class="kn-race kn-national-race" data-note-race="'+row.id+'"><div class="kn-race-top"><div><h2>'+esc(row.venue)+' '+row.number+'R</h2><p>各予想の買い目・根拠・採点を確認できます。</p></div><div class="kn-time"><small>掲載締切</small><b>'+time(row.cutoff)+'</b></div></div>'+nationalStatus(row)+liveResult(row)+researchResult(row)+'</article>';
  }
  function renderNationwideSummary(){
    const panel=$('kn-nationwide-summary'),doc=data?.nationwide?.get(currentDay);
    if(!doc){panel.hidden=true;panel.textContent='';return;}
    const total=doc.races.length,saved=doc.races.filter(row=>row.original_identity).length,adjusted=doc.races.filter(row=>row.original_identity?.conditioned).length,unread=doc.races.filter(row=>row.original_identity&&!row.original).length,unsupported=doc.races.filter(row=>row.state==='UNSUPPORTED_CLASS_OR_ROUND').length;
    panel.hidden=false;panel.dataset.registeredRaces=total;
    const heading=doc.inventory_complete?'全'+total+'レースの保存状況':'確認できた'+total+'レースの保存状況';
    const coverage=doc.inventory_complete?'この日付の登録済み全レースが分母です。':(doc.registry_available?'全国の対象総数はまだ確認中です。':'この日の開催一覧をまだ確認できていません。')+(doc.missing_venues.length?' 未確認の開催コード：'+doc.missing_venues.map(n=>String(n).padStart(2,'0')).join('・'):'');
    panel.innerHTML='<h2>'+heading+'</h2><p>A/B保存済み '+saved+' / '+total+'件 · 補正A/B保存済み '+adjusted+' / '+total+'件</p><p>保存予想が未確認 '+(total-saved)+'件（うち種別・条件の確認待ち '+unsupported+'件）</p>'+(unread?'<p class="kn-warning">保存記録は確認できましたが、買い目の原本が未読込のレースが '+unread+'件あります。</p>':'')+'<p class="kn-small">'+esc(coverage)+' 未作成は外れに含めません。Cは別に未作成を表示します。</p><p class="kn-small">保存状況の確認 '+stamp(doc.observed_at)+'</p>';
  }
  function frozenBasis(saved){
    const facts=saved.facts,styles={NIGE:'逃げ',MAKURI:'捲り',SASHI:'差し',MARK:'追込',ALLROUND:'自在',UNKNOWN:'未確認'};
    const line=facts.line_groups.map(g=>g.join('−')).join(' / ');
    const factsTable='<p>保存時の'+(facts.competition==='GIRLS'?'位置取りの仮定':'並び予想')+'：'+esc(line)+'</p><div class="kn-table-scroll"><table><thead><tr><th>車</th><th>印順位</th><th>得点</th><th>近況値</th><th>H/B</th><th>脚質</th></tr></thead><tbody>'+facts.riders.map(r=>'<tr><td>'+r.car+'</td><td>'+(r.mark_rank==='UNMARKED'?'無印':r.mark_rank)+'</td><td>'+r.competition_points+'</td><td>'+r.recent_form_score+'</td><td>'+r.h_count+'/'+r.b_count+'</td><td>'+styles[r.style]+'</td></tr>').join('')+'</tbody></table></div>';
    const actions={PREDICTED_LINE_ORDER_ONLY:'掲載の並びを出発点にする想定',LEADER_ATTACKS:'主導権候補が動く想定',CHALLENGER_EARLY_COUNTER:'別の先頭候補が早めに仕掛け返す想定',LEADER_TRIES_TO_HOLD_PACE:'主導権候補がペースを保つ想定',LEADER_MAKURI_OR_KAMASHI:'主導権候補が捲り・かましで前へ出る想定',CHALLENGER_MAKURI:'別の先頭候補が捲る想定',FRONT_LINE_CONTINUITY_UNVERIFIED:'前の隊列が続くかは未確認',FOLLOWER_SASHI_SCENARIO:'番手から差す展開を想定',FOURTH_CORNER_ORDER_CONTINUES:'4コーナーの順序が続く想定',LATE_SPRINT_OVERTAKE:'終盤の加速で前を交わす想定',FRONT_LEADER_PACE_FADE:'前の選手が失速する想定'};
    const actionText=value=>actions[value]||(/^LEADER_CAR_[1-9]$/.test(value)?'主導権候補は'+value.at(-1)+'番':/^CAR_[1-9]$/.test(value)?'対象は'+value.at(-1)+'番':'保存された動きの仮定');
    const phases=['初周','打鐘','最終ホーム','最終バック','4コーナー','ゴール'];
    const scenarios=saved.scenarios.map((s,i)=>'<article class="kn-frozen-scenario"><h5>見立て '+(i+1)+' · '+esc(s.projected_3ren_tan.join('−'))+'</h5><p>候補内の重み '+(s.relative_research_weight*100).toFixed(1)+'%</p><ol>'+s.six_phases.map((p,j)=>'<li><b>'+phases[j]+'</b> '+esc(p.projected_order.join(' → '))+'<br>'+esc(p.hypothesis_actions.map(actionText).join(' / '))+'</li>').join('')+'</ol></article>').join('');
    const trend={IMPROVING:'上向き',DECLINING:'下向き',NO_CLEAR_CHANGE:'目立つ変化なし',INSUFFICIENT_DATA:'比較材料が不足'};
    const change=v=>v===null?'未比較':(v>0?'+':'')+v;
    const adjustments=saved.assessments.length?'<p>直近成績と落車前後の成績差に基づく、保存時点の補正です。落車の記録だけで状態を決めつけていません。</p><div class="kn-table-scroll"><table><thead><tr><th>車</th><th>近況</th><th>直近の差</th><th>落車前後の差</th><th>補正値</th></tr></thead><tbody>'+saved.assessments.map(a=>'<tr><td>'+a.car+'</td><td>'+trend[a.trend]+'</td><td>'+change(a.recent_result_change)+'</td><td>'+change(a.post_fall_change)+'</td><td>'+change(a.score_adjustment)+'</td></tr>').join('')+'</tbody></table></div>'+saved.assessments.map(a=>'<p>'+a.car+'番：'+(a.fall_on_record?'落車の保存記録あり':'落車の保存記録なし')+' · 欠場期間 '+(a.documented_absence_days===null?'未確認':a.documented_absence_days+'日')+' · 復帰後 '+(a.return_after_absence_results===null?'未確認':a.return_after_absence_results+'走')+' · コメント記録 '+(a.comments_count??'未確認')+'件</p>').join('')+'<p class="kn-small">数値は保存された比較用の値です。体調の診断や的中率を表すものではありません。</p>':'';
    const title=saved.adjusted?(saved.role==='B'?'展開の見立て・近況の補正':'近況の補正・根拠'):(saved.role==='B'?'展開の見立て・根拠':'予想の根拠');
    return '<details class="kn-details kn-frozen-basis"><summary>'+title+'</summary><p>'+(saved.role==='A'?'保存時の印順位と選手の数値をもとに候補順を付けています。Aの原本には局面別の見立てはありません。':'保存された6局面の見立てです。各局面の順序は予想上の仮定です。')+'</p>'+factsTable+adjustments+(scenarios?'<p class="kn-small">分岐の重みは候補内の比重です。的中確率ではありません。</p>'+scenarios:'')+'</details>';
  }
  function frozenTickets(saved){
    if(!saved)return '';
    return '<p class="kn-frozen-clock">作成 '+stamp(saved.generatedAt)+'<br>締切前の保存 '+stamp(saved.sealedAt)+'</p><p>全部の買い目</p><ol class="kn-frozen-tickets" data-frozen-arm="'+saved.name+'">'+saved.tickets.map(t=>'<li data-frozen-combo="'+t.combo+'">'+t.combo.split('-').map(Number).map(car).join('<span>−</span>')+'</li>').join('')+'</ol>'+frozenBasis(saved);
  }
  function resultLabel(state){
    if(state==='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL')return '二つの掲載元が一致（公式認証なし）';
    if(state==='HOLD_SECONDARY_RESULT_DISAGREEMENT')return '出典間の相違で保留';
    if(state?.startsWith('PENDING_'))return '結果の掲載・確定待ち';
    const holds={HOLD_NO_PUBLISHED_CUTOFF_HINT:'掲載締切を確認できないため保留',HOLD_PROVIDER_DENIED_OR_RATE_LIMITED_STOP:'入力元の取得拒否で保留',HOLD_RESULT_SOURCE_UNAVAILABLE:'結果の取得を保留',HOLD_RESULT_SOURCE_UNVERIFIED:'結果の根拠を確認できないため保留',HOLD_RESULT_DAY_MISMATCH:'結果の日付照合を保留',HOLD_RESULT_RACE_MISMATCH:'結果のレース照合を保留',HOLD_SPECIAL_REFUND_OR_TIE_REQUIRES_OFFICIAL:'返還・中止・同着の公式確認待ち',HOLD_CONFLICTING_SOURCE_RESULT:'掲載内容の相違で保留'};
    return holds[state]||'結果の照合は未取得';
  }
  function comparisonHtml(row,model,version=null){
    const score=M.compare(row,market,model,version),status=score.status==='RESEARCH_HIT'?'的中':score.status==='RESEARCH_MISS'?'不的中':'未判定';
    const label=['A','B','C'].includes(model)?'参考'+model:M.forecast(row,market,model).label;
    const timing={GENERATED_AT_MISSING:'予想の生成時点は未確認',CUTOFF_UNVERIFIED:'掲載締切は未確認',GENERATED_AFTER_OR_AT_CUTOFF:'掲載締切以後に生成された保存版',RECORDED_PRE_CUTOFF_NOT_FORMAL:'記載時点は掲載締切前（正式な保存時刻の認証なし）'};
    return '<div class="'+(['A','B','C'].includes(model)?'kn-reference-comparison':'kn-selected-comparison')+'" data-model="'+esc(model)+'"><p><b>'+esc(label)+' · '+score.ticketCount+'点 · '+status+'</b></p><p>各100円の想定：投資 '+money(score.stakeYen)+' · 払戻 '+money(score.payoutYen)+' · 差引 '+money(score.netYen)+'</p><p class="kn-small">予想の記載時点 '+stamp(score.generatedAt)+' · '+esc(timing[score.timingStatus])+'</p>'+(score.reason==='RESULT_HISTORY_INCOMPLETE'?'<p class="kn-warning">先行する結果の保存版が未読込のため、比較は保留しています。</p>':'')+'</div>';
  }
  function bindingHtml(value,label){
    return value?'<p class="kn-small">'+esc(label)+'のファイルSHA256 '+esc(value.fileSha256)+'<br>暗号文SHA256 '+esc(value.cipherSha||'暗号文経由の読込ではありません')+'</p>':'';
  }
  function resultRevision(saved,n){
    const o=saved.observation;
    return '<section data-result-revision="'+n+'"><p><b>結果の保存版 '+n+' · '+esc(resultLabel(o.state))+'</b></p><p>取得 '+stamp(o.captured_at)+' · '+esc(o.winning_triple?.join('−')||'結果保留')+' · 各100円の3連単払戻 '+money(o.payout_per_100yen)+'</p>'+o.provider_receipts.map(r=>'<p>'+sourceLink(r.source_url,r.provider+'の結果')+' · 出典取得 '+stamp(r.observed_at)+'</p>').join('')+bindingHtml(saved.binding,'結果原本')+'</section>';
  }
  function researchResult(row){
    if(!row.latestResearchResult&&!Object.keys(row.reference||{}).length)return '';
    const latest=row.latestResearchResult?.observation,history=row.researchResultHistory||[],versions=row.referenceHistory||[];
    return '<section class="kn-result kn-research-result kn-details" data-result-state="'+esc(latest?.state||'UNOBSERVED')+'"><b>参考A/Bと保存結果の照合</b><p>'+esc(resultLabel(latest?.state))+' · '+esc(latest?.winning_triple?.join('−')||'結果未確認')+'</p>'+(!['A','B','C'].includes(variant)?comparisonHtml(row,variant):'')+comparisonHtml(row,'A')+comparisonHtml(row,'B')+'<p class="kn-small">条件付きの研究比較です。点数は各保存版の全買い目を使用し、1点100円で計算します。実購入・正式PR71成績・学習効果の証明ではありません。2車単の払戻は独立した根拠がないため未確認です。</p><details class="kn-details"><summary>結果の改訂履歴・出典</summary>'+(history.length?history.map((saved,n)=>resultRevision(saved,n+1)).join(''):'<p>結果の保存履歴はありません。</p>')+'</details><details class="kn-details"><summary>参考予想の保存版・原本の照合</summary>'+[...versions,{reference:row.reference,envelope:row.referenceEnvelope,binding:row.bindings?.reference}].map((version,n)=>'<section><p><b>参考予想の保存版 '+(n+1)+(n===versions.length?'（現在）':'')+'</b></p>'+comparisonHtml(row,'A',version)+comparisonHtml(row,'B',version)+bindingHtml(version.binding,'参考予想原本')+'</section>').join('')+'</details></section>';
  }
  function renderResearchSummary(list){
    const panel=$('kn-research-summary'),only=$('kn-result-only');
    if(!data){panel.hidden=true;panel.textContent='';only.innerHTML='';return;}
    const results=[...(data.results||new Map())].filter(([id])=>id.startsWith(currentDay.replaceAll('-',''))),known=new Set(list.map(row=>row.id)),unpaired=results.filter(([id])=>!known.has(id));
    if(data.nationwide?.has(currentDay)&&!results.length&&list.every(row=>row.nationwideOnly)){panel.hidden=true;panel.textContent='';only.innerHTML='';return;}
    const summary=M.summarize(list,market),arm=name=>{const v=summary[name];return '参考'+name+'：的中 '+v.hitRaces+' / 判定 '+v.evaluableRaces+'レース · 未判定 '+v.unknownRaces+'件 · 保存点数 '+(v.ticketCounts.length?v.ticketCounts.join('・'):'未確認')+'点';};
    panel.hidden=false;panel.innerHTML='<b>保存結果と参考予想の研究比較</b><p>保存結果 '+results.length+'件 · 予想未読込 '+unpaired.length+'件</p><p>同じレースでA/Bを比較できる数 '+summary.pairedRaceCount+' / '+summary.raceCount+' · その共通レースの的中 A '+summary.paired.A.hitRaces+' / '+summary.pairedRaceCount+'、B '+summary.paired.B.hitRaces+' / '+summary.pairedRaceCount+'</p><p>'+esc(arm('A'))+'</p><p>'+esc(arm('B'))+'</p><p class="kn-small">表示中の日付の全保存レースが分母です。未判定は外れに含めません。A/Bの差から学習による改善は判断できません。</p>';
    only.innerHTML=unpaired.map(([id,history])=>'<details class="kn-details"><summary>'+esc(id)+' · '+esc(resultLabel(history.at(-1)?.observation.state))+'</summary><p>このレースの予想原本は未読込のため、的中比較の分母へ加えません。</p>'+history.map((saved,n)=>resultRevision(saved,n+1)).join('')+'</details>').join('');
  }
  function liveResult(row){
    const result=row.resultUpdate,frozen=row.frozenForecast,national=row.nationwideStatus;if(!result&&!frozen&&!national)return '';
    const official=result?.authority==='official',confirmed=result?.order_status==='confirmed',paid=official&&result?.payout_status==='confirmed';
    const order=result?.order_status==='conflict'?'出典間の相違を確認中':confirmed?result.winning_triples.join(' / '):'着順を確認中';
    const status={hit:'的中',miss:'不的中',pending:'未照合',void:'返還・採点対象外',unverifiable:'原本の確認待ち'};
    const arms=[['A','A'],['B','B'],['adjusted_A','補正A'],['adjusted_B','補正B'],['C','C']].map(([name,label])=>{
      const arm=result?.arms[name],saved=M.frozenArm(row,name),aligned=!saved||arm?.points==null||arm.points===saved.tickets.length;
      const state=aligned?(arm?.state||'pending'):'unverifiable',missing=national&&!saved&&!arm?.points;
      const referencePending=!saved&&national?.original_identity&&(['A','B'].includes(name)||name.startsWith('adjusted_')&&national.original_identity.conditioned);
      const outcome=(frozen||national)&&name==='C'?'未作成':referencePending?'保存原本の読込待ち':missing?(name.startsWith('adjusted_')?'補正の保存待ち':'未作成'):!result?'結果待ち':status[state]||'未照合';
      return '<div class="kn-result-arm" data-result-arm="'+name+'"><h4>'+(frozen||national?label:'締切前保存'+label)+'</h4><p>採点結果：<strong>'+esc(outcome)+'</strong></p><p>'+(saved?'点数 '+saved.tickets.length+'点':arm?.points!=null?arm.points+'点':(frozen||national)&&name==='C'?'Cの予想は未作成です。':'点数未確認')+'</p>'+(missing&&name.startsWith('adjusted_')?'<p class="kn-small">'+conditionLabel(national.condition_state)+'</p>':'')+(paid&&aligned&&arm?.stake_yen!=null&&arm?.return_yen!=null?'<p>各100円の想定：投資 '+money(arm.stake_yen)+' / 払戻 '+money(arm.return_yen)+'</p>':'')+(!aligned?'<p class="kn-warning">保存原本と採点側の点数が一致していないため、採点結果の表示を保留しています。</p>':'')+frozenTickets(saved)+'</div>';
    }).join('');
    const sourceNames={keirin_jp:'KEIRIN.JP',kdreams:'Kドリームス',netkeirin:'netkeirin',official_pdf:'公式PDF',official_json:'公式データ'};
    const comparisonNames={matched:'一致',different:'相違あり',unavailable:'取得待ち',unverified:'未確認'};
    const comparisons=(result?.source_comparison||[]).map(s=>sourceNames[s.source_id]+'：'+comparisonNames[s.state]).join(' / ');
    const payout=paid?Object.entries(result.payouts_100yen).map(([combo,yen])=>esc(combo)+' '+money(yen)).join(' / '):(result?.payout_status==='held'?'配当の確認を保留中':'配当確認中');
    const purposes={OFFICIAL_CALENDAR:'開催日程',CALENDAR_SCRIPT:'開催日程の画面処理',FORM_SCRIPT:'画面の遷移処理',OFFICIAL_RACE_LIST:'レース一覧',RACE_LIST_VIEW_SCRIPT:'レース一覧の表示処理',RACE_LIST_CONTROLLER_SCRIPT:'レース一覧の遷移処理',OFFICIAL_FINAL_RESULT:'公式の着順・配当',OFFICIAL_PAYOUT_UNIT:'配当単位の説明',OFFICIAL_JSON_CALENDAR:'開催日程',OFFICIAL_JSON_DAY_LIST:'開催別のレース一覧',OFFICIAL_JSON_RESULT_SUMMARY:'結果一覧',OFFICIAL_JSON_HEADER:'レース情報',OFFICIAL_JSON_DETAIL:'公式の着順・配当'};
    const stages={REQUEST:'通信',HTTP_RESPONSE:'応答確認',CONTENT_CHECK:'ページ内容の確認',PARSE_RESULT:'結果の読取',VERIFY_UNIT:'配当単位の確認',PERSIST_STOP:'取得停止の保存'};
    const diagnostics=result?.diagnostics.length?'<details class="kn-details"><summary>取得先と確認状況</summary>'+result.diagnostics.map(d=>'<p class="kn-small"><b>'+purposes[d.purpose]+'</b> · '+esc(d.method)+' '+esc(d.source_host+d.source_path)+'<br>HTTP '+(d.http_status===null?'応答なし':d.http_status)+' · '+stages[d.stage]+' · '+esc(d.reason)+'<br>'+stamp(d.observed_at)+'</p>').join('')+'</details>':'';
    return '<section class="kn-result kn-live-result"><h3>'+(frozen?'締切前に保存した予想':official?'公式結果':national&&!result?'予想の保存状況':'参考結果・公式確認待ち')+'</h3>'+(frozen?'<p class="kn-small">入力の保存時点 '+stamp(frozen.baseline.source_as_of)+' · 締切 '+stamp(frozen.baseline.published_cutoff_at)+'</p>':'')+'<p class="kn-result-order">'+(result?(official?'公式結果：':'参考結果・公式確認待ち：'):'')+esc(order)+'</p><p>'+payout+(paid?'（100円あたり）':'')+'</p><div class="kn-result-arms'+(frozen?' kn-has-originals':'')+'">'+arms+'</div><p class="kn-small">'+(frozen?'締切前に保存された各原本の照合です。':'')+(result?'結果確認 '+stamp(result.observed_at):'結果の保存を待っています。')+'</p>'+(comparisons?'<p class="kn-small kn-result-comparison">保存資料との照合：'+esc(comparisons)+'</p>':'')+diagnostics+'</section>';
  }
  function scenarios(values){
    if(!Array.isArray(values)||!values.length)return '';
    const names=['初周','打鐘','最終ホーム','最終バック','4コーナー','ゴール'];
    return '<details class="kn-details"><summary>展開と根拠・6局面を読む</summary>'+values.slice(0,64).map((s,i)=>{
      if(!s||typeof s!=='object')return '';
      const phases=s.six_phases||s.phases||s.phase_orders||[];
      const list=Array.isArray(phases)?phases:Object.entries(phases).map(([phase,order])=>({phase,order}));
      return '<section class="kn-scenario"><h4>'+esc(s.label||s.scenario_id||s.id||'展開 '+(i+1))+'</h4><p>'+esc(s.condition||'条件付きの展開仮説')+'</p><ol>'+list.map((p,n)=>{const order=p?.projected_order||p?.order||p?.ordering;const actions=p?.hypothesis_actions;return '<li><b>'+esc(typeof p==='object'?p?.label||p?.phase||names[n]||'局面':names[n]||'局面')+'</b><span>'+esc(typeof p==='string'?p:p?.description||p?.event||(Array.isArray(order)?order.map(v=>Array.isArray(v)?v.join('−'):v).join(' → '):'')||'記述未取得')+'</span>'+(actions?'<p>'+esc(Array.isArray(actions)?actions.join(' / '):actions)+'</p>':'')+'</li>';}).join('')+'</ol><p class="kn-small">'+esc(Array.isArray(s.evidence)?s.evidence.join(' / '):s.evidence||'')+'</p></section>';
    }).join('')+'</details>';
  }
  function roster(row){
    return '<details class="kn-details"><summary>選手の数字・コメント・近況</summary><div class="kn-table-scroll"><table><thead><tr><th>車</th><th>選手</th><th>得点</th><th>S/H/B</th><th>逃/捲/差/マ</th><th>勝率</th><th>3連対</th></tr></thead><tbody>'+row.riders.map(p=>'<tr><td>'+car(p.number)+'</td><td>'+esc(p.name)+'</td><td>'+num(p.score)+'</td><td>'+[p.S,p.H,p.B].map(v=>num(v)).join('/')+'</td><td>'+[p.nige??p.escape,p.makuri,p.sashi,p.mark].map(v=>num(v)).join('/')+'</td><td>'+num(p.win_rate??p.win,'%')+'</td><td>'+num(p.top3_rate,'%')+'</td></tr>').join('')+'</tbody></table></div>'+row.riders.map(p=>'<p class="kn-rider-note"><b>'+p.number+' '+esc(p.name)+'</b><span>コメント：'+esc(p.comment||'未取得')+'</span><span>近況：'+esc((Array.isArray(p.recent_meets)?p.recent_meets:Array.isArray(p.recent_meetings)?p.recent_meetings:Object.values(p.recent_meetings||{})).filter(Boolean).join(' / ')||'未取得')+'</span></p>'+fieldProvenance(p)).join('')+'<p class="kn-small">主表示の統計は掲載元の値を保持します。参考A/Bのnetkeirin統計と平均しません。H/Bは過去の先頭回数で、今日の隊列ではありません。</p></details>';
  }
  function providerName(url){const host=new URL(url).hostname;return host==='keirin.netkeiba.com'?'netkeirin':host==='keirin.kdreams.jp'?'Kドリームス':host;}
  function referenceProvenance(row){const pages=row.referenceEnvelope?.input?.source_pages;if(!Array.isArray(pages))return '';const seen=new Set(),links=pages.flatMap(page=>{const url=M.safeUrl(page?.url);if(!url||seen.has(url))return [];seen.add(url);return [sourceLink(url,'参考A/Bの入力・'+providerName(url))];});return links.length?'<p class="kn-small kn-reference-provenance">'+links.join(' / ')+'</p>':'';}
  function fieldProvenance(person){const fields=person.field_sources;if(!fields||typeof fields!=='object'||Array.isArray(fields))return '';const labels={statistics:'得点・率・成績',H:'H',B:'B',comment:'コメント',recent_meetings:'近況',venue_5yr:'当場の成績',same_distance_year:'同じ周長の成績'};const links=Object.entries(fields).flatMap(([field,value])=>{const url=M.safeUrl(typeof value==='string'?value:value?.url);return url?[sourceLink(url,(labels[field]||field)+'：'+providerName(url))]:[];});return links.length?'<p class="kn-small kn-field-provenance">'+esc(person.number)+'番の項目別出典：'+links.join(' / ')+'</p>':'';}
  function selectionSummary(){const list=all().filter(r=>selected.has(r.id));const total=list.reduce((n,r)=>{const f=M.forecast(r,market,variant),p=pref(r);return n+M.allocate(f,p.budget,p.excluded).total;},0);$('kn-selection-count').textContent='検討リスト '+list.length+'件 · '+money(total);$('kn-copy-selection').disabled=!list.length;}
  function copyRace(row){const f=M.forecast(row,market,variant),p=pref(row),a=M.allocate(f,p.budget,p.excluded);if(f.allocatable&&!a.available)return '';return row.date+' '+row.venue+' '+row.number+'R / '+f.label+' / 掲載締切 '+time(row.cutoff)+'\n'+f.tickets.filter((t,i)=>!f.allocatable||a.amounts[i]>0).map(t=>{const i=f.tickets.indexOf(t);return t.combo+(f.allocatable?' '+money(a.amounts[i]):'');}).join('\n')+'\n'+(f.allocatable?'候補配分 '+money(a.total)+' · 未購入':'参考計算・比較用');}
  async function copy(value){if(!value)return;try{await navigator.clipboard.writeText(value);note('買い目候補をコピーしました。');}catch{const area=document.createElement('textarea');area.value=value;root.append(area);area.select();const ok=document.execCommand('copy');area.remove();note(ok?'買い目候補をコピーしました。':'このブラウザーではコピーできませんでした。',!ok);}}
  function click(button){
    if(!button)return;
    if(button.dataset.day){currentDay=button.dataset.day;venue='';render();return;}
    if(Object.hasOwn(button.dataset,'venue')){venue=button.dataset.venue;render();return;}
    if(button.dataset.expand){const key=button.dataset.expand+':'+market+':'+variant;expanded.has(key)?expanded.delete(key):expanded.add(key);renderCards();return;}
    if(button.dataset.select){const id=button.dataset.select;selected.has(id)?selected.delete(id):selected.add(id);renderCards();return;}
    if(button.dataset.copy){const row=all().find(r=>r.id===button.dataset.copy);if(row)copy(copyRace(row));}
  }
  function renderRollover(){
    try{const value=id=>$(id).value===''?null:Number($(id).value);const p=window.KeirinRollover.plan({initialBudget:Number($('kn-roll-budget').value),firstReturn:value('kn-return-one'),secondReturn:value('kn-return-two')});$('kn-roll-result').innerHTML='<p>初回 '+money(p.firstStake)+' · 次の候補 '+money(p.nextStake)+' · 留保 '+money(p.reserve)+'</p><p>'+esc(p.reason||'最終の試算：'+money(p.net))+'</p>';}catch{$('kn-roll-result').textContent='受取額は0〜100,000,000円の整数で入力してください。';}
  }
  async function bounded(response){const limit=90*1024*1024,length=response.headers.get('content-length');if(length!==null&&(!/^\d+$/.test(length)||Number(length)>limit))throw Error();const reader=response.body?.getReader();if(!reader)throw Error();const parts=[];let total=0;try{for(;;){const {value,done}=await reader.read();if(done)break;total+=value.byteLength;if(total>limit)throw Error();parts.push(value);}}catch{await reader.cancel().catch(()=>{});throw Error();}const bytes=new Uint8Array(total);let offset=0;for(const p of parts){bytes.set(p,offset);offset+=p.length;}return bytes;}
  async function fromFragment(){
    const match=/^#note=([a-f0-9]{64})\.([A-Za-z0-9_-]{43})$/.exec(fragment);
    const feed=/^#notefeed=([A-Za-z0-9_-]{150,400})$/.exec(fragment);
    if(!match&&!feed)return;
    const version=beginLoad();
    dialog.showModal();note('本人用の保存データを開いています。');
    if(feed&&typeof window.RaceKeirinNoteFeed?.createSession==='function'){
      try{
        const session=await window.RaceKeirinNoteFeed.createSession(feed[1]);
        if(version!==loadVersion){session.close();return;}
        let first=true;
        feedWatcher=window.RaceKeirinNoteFeed.watchSession(session,{
          isActive:()=>dialog.open&&document.visibilityState!=='hidden',
          onUpdate:async value=>{if(version!==loadVersion)return;if(first){first=false;await accept(value,version);}else refreshDisplay(value,version);},
          onError:()=>{if(version===loadVersion)note(data?'更新を確認できませんでした。前回確認できた表示を保持しています。':'本人用リンクのデータを開けませんでした。保存データまたはリンクを確認してください。',true);}
        });
        await feedWatcher.check();
      }catch{if(version===loadVersion)note('本人用リンクのデータを開けませんでした。保存データまたはリンクを確認してください。',true);}
      return;
    }
    const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),feed?120000:20000);
    activeLoadAbort=abort;
    try{let value;if(feed){if(typeof window.RaceKeirinNoteFeed?.open!=='function')throw Error();value=await window.RaceKeirinNoteFeed.open(feed[1],{signal:abort.signal,onStatus:()=>{if(version===loadVersion)note('保存された最新データを確認しています。');}});}else{const response=await fetch(new URL('./views/'+match[1]+'.json',document.baseURI),{cache:'no-store',credentials:'omit',referrerPolicy:'no-referrer',signal:abort.signal});if(!response.ok)throw Error();value=await M.openCipher(await bounded(response),{cipherSha:match[1],key:match[2]});}await accept(value,version);}
    catch{if(version===loadVersion)note('本人用リンクのデータを開けませんでした。保存データまたはリンクを確認してください。',true);}finally{clearTimeout(timer);if(activeLoadAbort===abort)activeLoadAbort=null;}
  }
  build();launcher.addEventListener('click',()=>{dialog.showModal();feedWatcher?.check();});
  document.addEventListener('visibilitychange',()=>feedWatcher?.check());
  window.addEventListener('pageshow',()=>feedWatcher?.check());
  root.addEventListener('focusout',()=>queueMicrotask(()=>{if(pendingFeed)refreshDisplay(pendingFeed.value,pendingFeed.version);}));
  fromFragment();
})();
