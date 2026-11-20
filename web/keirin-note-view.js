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
  let loadVersion=0,activeLoadAbort=null;
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
  function beginLoad(){loadVersion++;activeLoadAbort?.abort();activeLoadAbort=null;return loadVersion;}
  function build(){
    shell.innerHTML=`<header class="kn-head"><div><p class="kn-eyebrow">RACE AI · KEIRIN NOTE</p><h1>競輪の読みどころ</h1><p>保存された分析・参考モデル・買い目を確認する</p></div><button type="button" id="kn-close" class="kn-close">閉じる</button></header>
      <div class="kn-scroll"><section class="kn-import"><div><label class="kn-file">保存データを開く<input id="kn-file" type="file" accept=".json,application/json"></label><button id="kn-clear" type="button" class="kn-secondary">読込データを消す</button></div><p id="kn-status" role="status">本人用リンク、または保存データJSONから開けます。</p></section>
      <nav id="kn-days" class="kn-day-tabs" aria-label="予想の日付"></nav><section id="kn-metrics" class="kn-metrics"></section>
      <section class="kn-tools"><div id="kn-venues" class="kn-venues" aria-label="会場"></div><div class="kn-controls"><label>券種<select id="kn-market"><option value="3t">3連単</option><option value="2t">2車単</option></select></label><label>表示する予想<select id="kn-variant"><option value="flexible">改訂された分析</option><option value="original">原分析</option><option value="rollover">絞り込み分析</option><option value="A">参考A</option><option value="B">参考B・6局面</option><option value="C">参考Cの状況</option></select></label><label class="kn-search-label">検索<input id="kn-search" type="search" placeholder="会場・選手・レース名"></label></div><div class="kn-small-controls"><label><input id="kn-future" type="checkbox">これからのレース</label><label><input id="kn-selected" type="checkbox">検討リストのみ</label><span id="kn-count"></span></div></section>
      <div id="kn-races" class="kn-grid"></div>
      <details class="kn-rollover"><summary>2段階の資金配分を試算する</summary><p>受取額は払戻と返還の合計を手入力します。実購入の記録とは別の試算です。</p><div class="kn-controls"><label>初回の予算<select id="kn-roll-budget"><option>2000</option><option selected>2500</option><option>3000</option></select></label><label>1戦目の受取額<input id="kn-return-one" type="number" min="0" max="100000000" step="100" placeholder="未入力"></label><label>2戦目の受取額<input id="kn-return-two" type="number" min="0" max="100000000" step="100" placeholder="未入力"></label></div><div id="kn-roll-result"></div></details>
      <footer class="kn-footer"><p>個別分析・改訂・参考A/Bはそれぞれの保存原本を保持します。参考Cの未生成も表示します。参考モデルの重みは校正済み確率ではありません。</p><p>画面での選択と配分は購入候補です。投票・決済は行いません。データと本人用リンクの鍵は外部へ送信しません。</p><p id="kn-provenance"></p></footer></div>
      <div class="kn-selection"><div><strong id="kn-selection-count">検討リスト 0件</strong><small>候補・配分の試算</small></div><button id="kn-copy-selection" type="button">検討リストをコピー</button></div>`;
    $('kn-close').addEventListener('click',()=>dialog.close());
    $('kn-file').addEventListener('change',async event=>{const file=event.target.files?.[0];if(!file)return;const version=beginLoad();try{if(file.size>64*1024*1024)throw Error();note('保存データを確認しています。');await accept(await M.openPacket(JSON.parse(await file.text())),version);}catch{if(version===loadVersion)note('保存データを開けませんでした。形式と原本の整合を確認してください。',true);}if(version===loadVersion)event.target.value='';});
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
  async function accept(value,version){if(version!==loadVersion)return;data=value;currentDay=data.dates.at(-1);venue='';query='';$('kn-search').value='';preferences.clear();selected.clear();expanded.clear();const authored=all().some(row=>row.original?.tickets?.length||row.two?.tickets?.length||row.flexible?.markets?.['3t']?.tickets?.length||row.flexible?.markets?.['2t']?.tickets?.length);variant=authored?'flexible':'A';if(!authored){market='3t';$('kn-market').value=market;}$('kn-variant').value=variant;render();note(data.feed?.providerDenied?'保存データを開きました。入力元の取得拒否により、自動取得は停止しています。':'保存データを端末内で開きました。',Boolean(data.feed?.providerDenied));}
  function render(){
    const days=data?.dates||[];$('kn-days').innerHTML=days.map(d=>'<button type="button" data-day="'+esc(d)+'" aria-pressed="'+(d===currentDay)+'">'+esc(d.slice(5).replace('-','月')+'日')+'</button>').join('');
    const list=all(),riders=list.reduce((n,r)=>n+r.riders.length,0),original=list.reduce((n,r)=>n+M.forecast(r,'3t','original').tickets.length,0),priced=list.filter(r=>r.quote.fetched_at).length;
    $('kn-metrics').innerHTML=[['対象レース',list.length+'件'],['出走メンバー',riders+'名'],['原分析の買い目',original+'点'],['保存オッズ',priced+'レース']].map(([k,v])=>'<div><span>'+esc(k)+'</span><strong>'+esc(v)+'</strong></div>').join('');
    const venues=[...new Set(list.map(r=>r.venue))];$('kn-venues').innerHTML=[['','全会場'],...venues.map(v=>[v,v])].map(([v,label])=>'<button type="button" data-venue="'+esc(v)+'" aria-pressed="'+(v===venue)+'">'+esc(label)+'</button>').join('');
    $('kn-provenance').textContent=data?'読込日時 '+stamp(data.importedAt)+' · 出典と予想時点は各レースで確認できます。'+(data.refreshHolds?.length?' · 入力変更 '+data.refreshHolds.length+'件は原分析との照合待ちです。':''):'';
    renderCards();
  }
  function renderCards(){
    const list=all(),now=Date.now();const shown=list.filter(r=>(!venue||r.venue===venue)&&(!query||(r.venue+' '+r.title+' '+r.riders.map(p=>p.name).join(' ')+' '+r.original.headline).toLocaleLowerCase('ja').includes(query))&&(!futureOnly||r.cutoff&&Date.parse(r.cutoff)>now)&&(!selectedOnly||selected.has(r.id)));
    $('kn-count').textContent='表示 '+shown.length+' / 全'+list.length+'レース';
    $('kn-races').innerHTML=shown.length?shown.map(renderRace).join(''):'<div class="kn-empty">'+(data?'条件に合うレースはありません。':'本人用リンク、または保存データを開くと予想を表示します。')+'</div>';
    selectionSummary();
  }
  function lineHtml(row){
    const line=n=>Number.isInteger(n)?car(n):n&&Array.isArray(n.contest)?'<span class="kn-contest">'+n.contest.map(car).join('')+'<small>競り</small></span>':'';
    return row.lines.map(group=>'<span class="kn-line">'+(Array.isArray(group)?group:[]).map(line).join('<span>−</span>')+'</span>').join('<span class="kn-line-gap">/</span>');
  }
  function renderRace(row){
    const prediction=M.forecast(row,market,variant),p=pref(row),allocation=M.allocate(prediction,p.budget,p.excluded),key=row.id+':'+market+':'+variant,open=expanded.has(key);
    const late=row.cutoff&&Date.parse(row.cutoff)<Date.now();
    const items=prediction.tickets.map((ticket,i)=>{
      const quote=row.quote[market==='2t'?'odds_2t':'odds_3t']?.[ticket.combo],status=row.quote[market==='2t'?'quote_status_2t':'quote_status_3t']?.[ticket.combo];
      const odds=typeof quote==='number'&&quote>0&&quote<9999.9?quote+'倍':status==='capped'?'上限表示':'未確認';
      return '<div class="kn-ticket '+(!open&&i>=3?'kn-ticket-folded':'')+'"><label>'+ (prediction.allocatable?'<input type="checkbox" data-ticket="'+esc(ticket.combo)+'" data-race="'+row.id+'" '+(!p.excluded.has(ticket.combo)?'checked':'')+' aria-label="'+esc(ticket.combo)+'を配分対象にする">':'')+'<span class="kn-combo">'+ticket.combo.split('-').map(Number).map(car).join('<span>−</span>')+'</span><span class="kn-role">'+esc(ticket.role)+'</span></label><div><b>'+ (prediction.allocatable?money(allocation.amounts[i]):'比較用')+'</b><small>'+esc(odds)+'</small></div></div>';
    }).join('');
    const outcome=row.settlement;
    const result=outcome?'<section class="kn-result"><b>提供サイトの保存分析の照合</b><p>'+esc(outcome.winning_combo||'結果未確認')+' · '+(outcome.sources_agree===false?'出典間の相違で保留':outcome.hit?'的中':outcome.status==='MISS'?'不的中':esc(outcome.status||'照合未確認'))+'</p><p>各100円の想定：'+money(outcome.net_yen)+'（実購入ではありません）</p></section>':'';
    const budget=prediction.allocatable?'<div class="kn-budget"><label>候補予算<select data-budget="'+row.id+'">'+[2000,2500,3000].map(n=>'<option value="'+n+'" '+(n===p.budget?'selected':'')+'>'+money(n)+'</option>').join('')+'</select></label><span>配分 '+allocation.chosen.length+'点 / 合計 '+money(allocation.total)+'</span></div>':'';
    return '<article class="kn-race" data-note-race="'+row.id+'"><div class="kn-race-top"><div><h2>'+esc(row.venue)+' '+row.number+'R</h2><p>'+esc(row.title)+'</p></div><div class="kn-time"><small>掲載締切</small><b>'+time(row.cutoff)+'</b><small>発走 '+time(row.start)+'</small></div></div><div class="kn-badges"><span>'+esc(prediction.label)+'</span>'+(late?'<span class="kn-past">掲載締切後</span>':'')+(prediction.confidence?'<span>分析区分 '+esc(prediction.confidence)+'</span>':'')+'</div><h3>'+esc(prediction.headline)+'</h3><p class="kn-reason">'+esc(prediction.reason)+'</p><div class="kn-lines">'+lineHtml(row)+'</div><p class="kn-small">媒体の並び予想・位置取りの参考です。</p>'+budget+
      '<div class="kn-point-heading"><b>予想 '+prediction.tickets.length+'点'+(prediction.allocatable?' · 配分 '+allocation.chosen.length+'点':'')+'</b></div><div class="kn-tickets">'+(items||'<p class="kn-empty">'+esc(prediction.reason||'この券種の保存予想はありません。')+'</p>')+'</div>'+(prediction.tickets.length>3?'<button type="button" class="kn-more" data-expand="'+row.id+'">'+(open?'上位3点に戻す':'全'+prediction.tickets.length+'点を表示')+'</button>':'')+
      (prediction.allocatable&&!allocation.available?'<p class="kn-warning">配分対象がないか、全点への100円単位の配分に予算が足りません。点数を選び直してください。</p>':'')+
      '<div class="kn-race-actions"><button type="button" data-select="'+row.id+'" aria-pressed="'+selected.has(row.id)+'">'+(selected.has(row.id)?'検討リストから外す':'検討リストに追加')+'</button><button type="button" data-copy="'+row.id+'" '+(prediction.allocatable&&!allocation.available?'disabled':'')+'>買い目をコピー</button></div>'+result+
      scenarios(prediction.scenarios)+roster(row)+
      '<details class="kn-details"><summary>出典・予想時点・注意点</summary><p>'+esc(prediction.risk||'保存された条件付きの分析です。')+'</p><p>予想の記載時点 '+stamp(prediction.createdAt)+'</p><p>オッズの保存時点 '+stamp(row.quote.source_updated_at||row.quote.fetched_at)+'</p><p>'+esc(row.quote.scope_label||'保存時点の値。現在値は掲載元で確認してください。')+'</p>'+sourceLink(row.sourceUrl,'出走表・掲載オッズ')+referenceProvenance(row)+'<p class="kn-small">参考A/Bは既存計算、Cは独立した連係履歴が不足しているため未生成です。正式な全モデル実測の認証とは別に表示しています。</p></details></article>';
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
    const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),feed?120000:20000);
    activeLoadAbort=abort;
    try{let value;if(feed){if(typeof window.RaceKeirinNoteFeed?.open!=='function')throw Error();value=await window.RaceKeirinNoteFeed.open(feed[1],{signal:abort.signal,onStatus:()=>{if(version===loadVersion)note('保存された最新データを確認しています。');}});}else{const response=await fetch(new URL('./views/'+match[1]+'.json',document.baseURI),{cache:'no-store',credentials:'omit',referrerPolicy:'no-referrer',signal:abort.signal});if(!response.ok)throw Error();value=await M.openCipher(await bounded(response),{cipherSha:match[1],key:match[2]});}await accept(value,version);}
    catch{if(version===loadVersion)note('本人用リンクのデータを開けませんでした。保存データまたはリンクを確認してください。',true);}finally{clearTimeout(timer);if(activeLoadAbort===abort)activeLoadAbort=null;}
  }
  build();launcher.addEventListener('click',()=>dialog.showModal());fromFragment();
})();
