"use strict";
(() => {
  const el = id => document.getElementById(id);
  const model = globalThis.RaceUI;
  const venueNames = ['桐生','戸田','江戸川','平和島','多摩川','浜名湖','蒲郡','常滑','津','三国','びわこ','住之江','尼崎','鳴門','丸亀','児島','宮島','徳山','下関','若松','芦屋','福岡','唐津','大村'];
  const pageNames = {home:['YOUR RACE DASHBOARD','今日も、データがあなたの味方です。','出走データと資金記録から、今日のレースを確認しましょう。'],races:['TODAY’S RACES','全レース一覧','取得できた出走表から、レースを選びましょう。'],detail:['RACE DETAIL','レース詳細','出走表・展示・モーターを、取得されたデータから確認。'],picks:['BET ALLOCATION','買い目配分','予算に合わせて、手入力の買い目と金額を整理。'],results:['PERFORMANCE','成績分析','実際に記録した購入と、確定した結果を集計。'],research:['DATA RESEARCH','研究','今日の出走データの取得範囲と出典を確認。'],settings:['PREFERENCES','設定','この画面を開いている間の資金・表示設定。']};
  let report=null, selectedId='', activePage='home', activeSport='boat', detailTab='racers', loadNumber=0, pendingAuto=0;
  const state={budget:10000,raceBudget:2000,maxPicks:8,mode:'balanced',longshot:false,candidates:[],purchases:[]};
  const text = value => value === null || value === undefined || value === '' || (typeof value === 'number' && !Number.isFinite(value)) ? '未取得' : typeof value === 'string' ? value.slice(0,200) : typeof value === 'number' ? String(value) : '未取得';
  const money = value => value.toLocaleString('ja-JP')+'円';
  const node = (tag, cls, content) => { const n=document.createElement(tag);if(cls)n.className=cls;if(content!==undefined)n.textContent=content;return n; };
  const button = (content, cls, fn) => {const n=node('button',cls,content);n.type='button';n.addEventListener('click',fn);return n;};
  const empty = (title,desc) => {const n=node('div','empty-state');n.append(node('span','empty-icon','◒'),node('h3','',title),node('p','muted',desc));return n;};
  const allRaces = () => (report?.venues || []).flatMap(v=>v.races.map(r=>({...r,venue:v.venue})));
  const raceName = race => race ? venueNames[Number(race.venue)-1]+' '+Number(race.race_id.slice(-2))+'R' : 'レース未選択';
  const currentRace = () => allRaces().find(r=>r.race_id===selectedId);
  const currentDay = () => new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const todaySummary = () => model.summarize(state.purchases.filter(p=>p.day===currentDay()));
  function invalidatePreviousDay() {
    if(!report||report.date_jst===currentDay())return false;
    report=null;selectedId='';refreshSelects();
    el('source-state').textContent='日付が変わりました / データ未取得';el('source-date').textContent='対象日：未取得';el('source-time').textContent='初回確認時刻：未取得';el('header-date').textContent=currentDay()+' / JST';
    return true;
  }

  const badge = lane => node('span','lane lane-'+lane,String(lane));
  const combo = lanes => {const n=node('div','combo');lanes.forEach((lane,i)=>{if(i)n.append(node('span','combo-dash','−'));n.append(badge(lane));});return n;};
  function metric(label,value,sub,icon='▥') {const n=node('article','metric');n.append(node('span','metric-icon',icon));const info=node('div');info.append(node('span','metric-label',label),node('strong','',value));if(sub)info.append(node('small','muted',sub));n.append(info);return n;}
  function showPage(page) {
    if(invalidatePreviousDay())renderAll();if(!pageNames[page])page='home';activePage=page;pickSport('boat');
    document.querySelectorAll('.page').forEach(n=>n.hidden=n.id!=='page-'+page);
    document.querySelectorAll('[data-page]').forEach(b=>{const active=b.dataset.page===page;b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    const [eyebrow,title,desc]=pageNames[page];el('page-eyebrow').textContent=eyebrow;el('page-title').textContent=title;el('page-description').textContent=desc;
    el('prediction-mode').parentElement.hidden=['detail','results','research','settings'].includes(page);
    if(location.hash!=='#'+page)history.replaceState(null,'','#'+page);
    if(page==='detail')renderDetail();if(page==='picks')renderTickets();if(page==='results')renderResults();
  }
  function pickSport(sport) {activeSport=sport;document.querySelectorAll('[data-sport]').forEach(b=>{b.classList.toggle('active',b.dataset.sport===sport);b.setAttribute('aria-pressed',String(b.dataset.sport===sport));});el('boat-view').hidden=sport!=='boat';el('coming').hidden=sport==='boat';if(sport!=='boat')el('coming-title').textContent=({horse:'競馬',cycle:'競輪',auto:'オートレース'})[sport]+' · Coming soon...';}
  function syncPreferences() {document.querySelectorAll('[data-mode]').forEach(b=>{b.classList.toggle('active',b.dataset.mode===state.mode);b.setAttribute('aria-pressed',String(b.dataset.mode===state.mode));});el('settings-mode').value=state.mode;el('longshot').checked=state.longshot;el('settings-longshot').checked=state.longshot;}
  function dateWithZone(value) {
    if (typeof value !== "string" || !/T.*(Z|[+-][0-9]{2}:[0-9]{2})$/.test(value)) return false;
    return Number.isFinite(Date.parse(value));
  }

  function validate(raw) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("JSONの形式が正しくありません。");
    if (typeof raw.date_jst !== "string" || !/^\d{4}-\d\d-\d\d$/.test(raw.date_jst)
        || !Number.isFinite(Date.parse(raw.date_jst + "T00:00:00Z"))) throw new Error("対象日が不正です。");
    if (!dateWithZone(raw.first_observed_at)) throw new Error("初回確認時刻に時差情報がありません。");
    if (typeof raw.source_url !== "string" || !raw.source_url.startsWith("https://")
        || !/^[a-f0-9]{64}$/.test(raw.source_sha256 || "")) throw new Error("取得元の証拠情報が不足しています。");
    if (!Array.isArray(raw.venues) || raw.venues.length < 1 || raw.venues.length > 24) throw new Error("開催場データが不正です。");
    const venueCodes = new Set();
    let count = 0;
    let complete = 0;
    for (const venue of raw.venues) {
      if (!venue || !/^(0[1-9]|1[0-9]|2[0-4])$/.test(venue.venue || "")
          || venueCodes.has(venue.venue) || !Array.isArray(venue.races)
          || venue.races.length < 1 || venue.races.length > 12) throw new Error("開催場・レース一覧に矛盾があります。");
      venueCodes.add(venue.venue);
      const raceIds = new Set();
      for (const race of venue.races) {
        const match = typeof race.race_id === "string"
          && race.race_id.match(/^(\d{8})-(\d{2})-(0[1-9]|1[0-2])$/);
        if (!match || match[1] !== raw.date_jst.replaceAll("-", "")
          || match[2] !== venue.venue || raceIds.has(race.race_id)
          || !Array.isArray(race.boats) || race.boats.length < 1 || race.boats.length > 6)
          throw new Error("レース識別子または艇数が不正です。");
        raceIds.add(race.race_id);
        const lanes = new Set();
        for (const boat of race.boats) {
          if (!boat || !Number.isInteger(boat.lane) || boat.lane < 1 || boat.lane > 6
            || lanes.has(boat.lane)
            || !/^\d{4}$/.test(boat.racer_registration_id || "")
            || (boat.motor_no !== null && ( !Number.isInteger(boat.motor_no) || boat.motor_no < 1 || boat.motor_no > 999)))
            throw new Error("艇・選手・モーターの記録が不正です。");
          lanes.add(boat.lane);
        }
        count += 1;
        if (race.boats.length === 6) complete += 1;
      }
    }
    if (raw.races !== undefined && raw.races !== count) throw new Error("レース総数に矛盾があります。");
    if (raw.complete_six_boat_races !== undefined && raw.complete_six_boat_races !== complete)
      throw new Error("6艇の集計値に矛盾があります。");
    return { raw, count, complete };
  }

  function validateCurrent(raw) {
    const checked=validate(raw);
    const today=currentDay();
    if(checked.raw.date_jst!==today)throw new Error('対象日が本日ではありません');
    if(checked.raw.redistribution_authorized!==true)throw new Error('再配信許可を確認できません');
    if(Date.parse(checked.raw.first_observed_at)>Date.now()+60000)throw new Error('取得時刻が未来です');
    return {...checked.raw,races:checked.count,complete_six_boat_races:checked.complete};
  }
  function racerCard(boat, expanded=false) {
    const card=node('article','racer-card');const head=node('div','racer-avatar');head.append(badge(boat.lane),node('span','avatar-silhouette','◉'));card.append(head,node('strong','racer-name',text(boat.name)==='未取得'?'登録 '+boat.racer_registration_id:text(boat.name)),node('small','muted','登録番号 '+boat.racer_registration_id));
    if(expanded){const fields=node('dl','racer-fields');for(const [label,value] of [['モーター',boat.motor_no],['平均ST',boat.average_st],['展示タイム',boat.display_time]])fields.append(node('dt','',label),node('dd','',text(value)));card.append(fields);}return card;
  }
  function raceCard(race,featured=false) {
    const card=node('article','race-card'+(featured?' featured':''));const head=node('div','race-card-head');const title=node('div');title.append(node('span','sport-tag','◒ ボートレース'),node('h3','',raceName(race)));const meta=node('div','race-time');meta.append(node('span','',report.date_jst),node('strong','','締切 '+text(race.closed_at)));head.append(title,meta);card.append(head);
    const tags=node('div','race-tags');tags.append(node('span','tag',race.boats.length+'艇の出走表'),node('span','tag '+(race.preview_available===true?'green':''),race.preview_available===true?'展示情報あり':'展示 未取得'),node('span','tag',race.result_available===true?'結果情報あり':'結果 未取得'));card.append(tags);
    const members=node('div','racer-grid');race.boats.slice().sort((a,b)=>a.lane-b.lane).forEach(b=>members.append(racerCard(b)));card.append(members);
    const foot=node('div','race-card-footer');foot.append(node('span','muted','AI評価・推奨買い目：検証中'),button('レース詳細を見る →','outline',()=>openRace(race.race_id)));card.append(foot);return card;
  }
  function openRace(id) {selectedId=id;detailTab='racers';el('ticket-race').value=id;showPage('detail');window.scrollTo({top:0,behavior:'smooth'});}
  function renderHome() {
    const summary=todaySummary();el('home-metrics').replaceChildren(metric('本日の予算',money(state.budget),'ご自身の設定','▣'),metric('使用額',money(summary.spent),'実際の購入記録','▤'),metric('残予算',money(state.budget-summary.spent),'予算 − 購入記録','▣'),metric('記録の回収率',summary.roi===null?'未集計':summary.roi.toFixed(1)+'%','手入力 / 結果確定分のみ','▥'),metric('的中 / 確定買い目',summary.settled?summary.hits+' / '+summary.settled:'未集計','買い目単位 / 購入 '+summary.purchases+'点','◎'));
    const races=allRaces().slice(0,3);el('home-races').replaceChildren(...(races.length?races.map((r,i)=>raceCard(r,i===0)):[empty('本日の出走データを待っています','データを取得すると、ここに開催場とレースを表示します。')]));
    el('home-data').replaceChildren(metric('開催場',report?report.venues.length+'場':'未取得','取得済みの開催場','▦'),metric('収録レース',report?allRaces().length+'レース':'未取得','本日の出走表','◒'));
    el('home-budget').replaceChildren(node('strong','',money(state.budget-summary.spent)),node('p','muted','残予算 / '+money(state.budget)));const progress=node('progress');progress.max=state.budget;progress.value=Math.min(summary.spent,state.budget);progress.setAttribute('aria-label','本日の予算使用額');el('home-budget').append(progress);
  }
  function renderRaces() {
    const query=el('race-search').value.trim().toLowerCase(), venue=el('venue-filter').value;
    let races=allRaces().filter(r=>(!venue||r.venue===venue)&&(!el('complete-filter').checked||r.boats.length===6)&&(!query||(raceName(r)+' '+r.boats.map(b=>text(b.name)+' '+b.racer_registration_id).join(' ')).toLowerCase().includes(query)));
    if(el('race-sort').value==='time')races.sort((a,b)=>(typeof a.closed_at==='string'?a.closed_at:'zzz').localeCompare(typeof b.closed_at==='string'?b.closed_at:'zzz')||a.race_id.localeCompare(b.race_id));
    else races.sort((a,b)=>a.race_id.localeCompare(b.race_id));
    el('race-count').textContent=report?'全'+races.length+'レース / 取得 '+allRaces().length+'レース':'本日のデータ未取得';el('all-races').replaceChildren(...(races.length?races.map(r=>raceCard(r)):[empty(venue&&!report?.venues.some(v=>v.venue===venue)?venueNames[Number(venue)-1]+'のデータは未取得です':report?'条件に合うレースがありません':'本日の出走データは未取得です',venue&&!report?.venues.some(v=>v.venue===venue)?'未取得のため、開催の有無は確認できません。':report?'検索や開催場の条件を変更してください。':'取得状況は「研究」から確認できます。')]));
    el('venue-buttons').replaceChildren(...venueNames.map((name,i)=>{const code=String(i+1).padStart(2,'0');const available=report?.venues.some(v=>v.venue===code);const b=button(name,'venue-button'+(venue===code?' active':''),()=>{el('venue-filter').value=code;renderRaces();});b.title=available?'出走データ取得済み':'データ未取得';b.setAttribute('aria-pressed',String(venue===code));return b;}));
  }
  function dataTable(headers, rows) {const wrap=node('div','table-scroll');const table=node('table');const tr=node('tr');headers.forEach(h=>tr.append(node('th','',h)));const thead=node('thead');thead.append(tr);const body=node('tbody');rows.forEach(fields=>{const row=node('tr');fields.forEach(v=>{const td=node('td');if(v instanceof Node)td.append(v);else td.textContent=text(v);row.append(td);});body.append(row);});table.append(thead,body);wrap.append(table);return wrap;}
  function renderDetail() {
    const target=el('race-detail'),race=currentRace();target.replaceChildren();if(!race){target.append(empty('レースを選択してください','全レースから出走データを選ぶと、詳細を確認できます。'),button('全レースを開く →','primary',()=>showPage('races')));return;}
    const panel=node('section','panel detail-panel');const title=node('div','detail-title');title.append(node('span','sport-tag','◒ ボートレース'),node('h2','',raceName(race)),node('span','tag','締切 '+text(race.closed_at)));panel.append(title);
    const hero=node('div','detail-hero');hero.append(node('p','eyebrow','RACE DATA'),node('h3','','出走表から、レースを知る。'),node('p','','6艇の選手・モーター・展示を確認。取得できない項目は「未取得」と表示します。'),node('span','hero-wave','≋'));panel.append(hero);
    const tabs=node('nav','detail-tabs');tabs.setAttribute('aria-label','レース詳細タブ');for(const [key,label] of [['racers','出走表・選手'],['preview','直前情報'],['motor','モーター'],['weather','水面・気象'],['analysis','AI予想・買い目']]){const b=button(label,detailTab===key?'active':'',()=>{detailTab=key;renderDetail();});b.setAttribute('aria-pressed',String(detailTab===key));tabs.append(b);}panel.append(tabs);
    const boats=race.boats.slice().sort((a,b)=>a.lane-b.lane);
    if(detailTab==='racers'){const grid=node('div','racer-grid expanded');boats.forEach(b=>grid.append(racerCard(b,true)));panel.append(grid,dataTable(['艇','選手','モーター','平均ST','展示タイム','展示進入'],boats.map(b=>[badge(b.lane),text(b.name)+' / '+b.racer_registration_id,b.motor_no,b.average_st,b.display_time,b.preview_course])));}
    if(detailTab==='preview')panel.append(dataTable(['艇','展示タイム','展示ST','展示進入'],boats.map(b=>[badge(b.lane),b.display_time,b.preview_st,b.preview_course])),node('p','muted','展示情報は取得時点の記録です。発走前の取得時点は原本で確認してください。'));
    if(detailTab==='motor')panel.append(dataTable(['艇','モーター番号','2連対率','使用サイクル'],boats.map(b=>[badge(b.lane),b.motor_no,b.motor_top2_rate,'未取得'])));
    if(detailTab==='weather'){const w=race.weather_preview||{};panel.append(dataTable(['風速','風向番号','波高'],[[w.wind_speed,w.wind_direction_number,w.wave_height]]),node('p','muted','単位・風向の対応・水温・潮位は、この配信データから確認できません。'));}
    if(detailTab==='analysis')panel.append(empty('AI評価・予想は検証中です','実レース検証と時点管理が完了するまで、推奨買い目・推定確率・期待値は公開しません。'),button('手入力の買い目を管理 →','primary',()=>{el('ticket-race').value=race.race_id;showPage('picks');}));
    target.append(panel);const foot=node('div','detail-actions');foot.append(node('p','muted','原本未独立検証 / '+report.first_observed_at),button('このレースの買い目を入力 →','primary',()=>{el('ticket-race').value=race.race_id;showPage('picks');}));target.append(foot);
  }
  function refreshSelects() {
    const selected=el('ticket-race').value,venueFilter=el('venue-filter').value;el('venue-filter').replaceChildren(new Option('すべての開催場',''));venueNames.forEach((name,index)=>el('venue-filter').append(new Option(name,String(index+1).padStart(2,'0'))));el('venue-filter').value=venueFilter;
    el('ticket-race').replaceChildren(new Option('レースを選択',''));allRaces().forEach(r=>el('ticket-race').append(new Option(raceName(r),r.race_id)));if(allRaces().some(r=>r.race_id===selected))el('ticket-race').value=selected;
  }
  function renderTickets() {
    const chosen=el('ticket-race').value;const tickets=state.candidates.filter(t=>t.raceId===chosen);const total=tickets.reduce((s,t)=>s+t.amount,0);el('ticket-list').replaceChildren();
    if(!tickets.length)el('ticket-list').append(empty('買い目候補を入力しましょう','レースを選び、3つの異なる艇番と金額を入力してください。'));
    tickets.forEach((t,index)=>{const row=node('article','ticket-row');row.append(node('span','ticket-rank',String(index+1)),combo(t.lanes),node('span','tag','手入力'),node('strong','ticket-stake',money(t.amount)),button('削除','text-button',()=>{state.candidates=state.candidates.filter(x=>x!==t);renderTickets();renderCandidateCount();}));el('ticket-list').append(row);});
    const summary=el('allocation-summary');summary.replaceChildren(metric('合計候補額',money(total),'未購入の候補','▤'),metric('未使用予算',money(state.raceBudget-total),'1レース予算との差額','▣'),node('div','notice subtle','オッズ・推定確率・払戻レンジ・AIリスク評価：未取得'));
    el('record-purchase').disabled=!tickets.length||total>state.raceBudget||tickets.length>state.maxPicks;el('equal-allocate').disabled=!tickets.length;renderCandidateCount();
  }
  function renderCandidateCount(){el('candidate-count').textContent=state.candidates.length?state.candidates.length+'点 / '+money(state.candidates.reduce((s,t)=>s+t.amount,0))+' の未購入候補':'手入力の候補はまだありません。';}
  function renderResults() {
    const s=model.summarize(state.purchases);el('result-metrics').replaceChildren(metric('この画面の購入額',money(s.spent),'日付をまたいだ記録を含む'),metric('払戻額',s.settled?money(s.returned):'未集計','結果確定 '+s.settled+'点'),metric('記録の回収率',s.roi===null?'未集計':s.roi.toFixed(1)+'%','手入力 / 結果確定分のみ'),metric('記録の的中率',s.hitRate===null?'未集計':s.hitRate.toFixed(1)+'%','買い目単位 / 的中 '+s.hits+' / 確定 '+s.settled));
    el('purchase-list').replaceChildren();if(!state.purchases.length)el('purchase-list').append(empty('購入記録はまだありません','実際に購入した買い目を「買い目」で記録してください。'));
    state.purchases.forEach(p=>{const row=node('article','purchase-row');const info=node('div');info.append(node('strong','',p.raceLabel),node('small','muted',p.day+' / ご自身の記録'),combo(p.lanes),node('p','muted','購入 '+money(p.amount)));row.append(info);if(p.payout===null){const form=node('form','settle-form');const label=node('label','','払戻額（円）');const input=node('input');input.type='number';input.min='0';input.max='1000000000';input.step='1';input.required=true;input.setAttribute('aria-label',p.raceLabel+' '+p.lanes.join('-')+' の払戻額');label.append(input);const submit=node('button','outline','結果を確定');submit.type='submit';form.append(label,submit);form.addEventListener('submit',event=>{event.preventDefault();const value=Number(input.value);if(!Number.isSafeInteger(value)||value<0||value>1000000000){el('result-message').textContent='払戻額は0以上の整数で入力してください。';return;}p.payout=value;renderResults();renderHome();});row.append(form);}else row.append(node('span','tag '+(p.payout?'green':''),p.payout?'払戻 '+money(p.payout):'払戻なし（結果確定）'));el('purchase-list').append(row);});
  }
  function renderResearch() {
    const races=allRaces(), boats=races.flatMap(r=>r.boats),complete=races.filter(r=>r.boats.length===6).length;
    el('research-metrics').replaceChildren(metric('開催場',report?report.venues.length+'場':'未取得','本日配信分'),metric('収録レース',report?races.length+'レース':'未取得','本日配信分'),metric('6艇そろったレース',report?complete+'レース':'未取得','出走表の艇数'),metric('展示情報あり',report?races.filter(r=>r.preview_available===true).length+'レース':'未取得','存在フラグによる集計'));
    const content=el('research-content');content.replaceChildren();if(!report){content.append(empty('データは未取得です','再確認または検証用JSONの読み込みで、取得範囲を確認できます。'));return;}
    const fields=[['選手名','name'],['モーター番号','motor_no'],['平均ST','average_st'],['展示タイム','display_time'],['展示ST','preview_st'],['展示進入','preview_course']];content.append(dataTable(['項目','取得された艇数','対象艇数'],fields.map(([name,key])=>[name,boats.filter(b=>text(b[key])!=='未取得').length,boats.length])));
    const source=node('dl','provenance');for(const [k,v] of [['取得元',report.source_url],['対象日',report.date_jst],['初回確認時刻',report.first_observed_at],['SHA-256',report.source_sha256],['原本の独立検証','未確認']])source.append(node('dt','',k),node('dd','',text(v)));content.append(source,node('p','muted','周回・回り足・直線の原本展示値、モーター使用サイクル、AI評価・予想の実測精度は未取得・未検証です。'));
  }
  function renderAll(){invalidatePreviousDay();renderHome();renderRaces();renderTickets();renderResults();renderResearch();if(activePage==='detail')renderDetail();}
  function showReport(data) {report=data;selectedId=allRaces().some(r=>r.race_id===selectedId)?selectedId:allRaces()[0]?.race_id||'';refreshSelects();renderAll();el('source-date').textContent='対象日：'+data.date_jst;el('source-time').textContent='初回確認時刻：'+data.first_observed_at;el('header-date').textContent=data.date_jst+' / JST';}
  async function loadAuthorizedDayFeed() {
    if(pendingAuto)return;const number=++loadNumber;pendingAuto=number;el('source-state').textContent='本日のデータを確認中';el('reload-feed').disabled=true;
    try {
      const response=await fetch("./api/today", {cache:"no-store", credentials:"same-origin"});
      if(response.status===404||response.status===503)throw new Error('本日の配信データは準備中です。');if(!response.ok)throw new Error('HTTP '+response.status);
      const body=await response.text();if(body.length>6_000_000)throw new Error('データが大きすぎます');const data=validateCurrent(JSON.parse(body));
      if(number!==loadNumber)return;showReport(data);el('source-state').textContent='配信許可フラグあり・原本未独立検証';el('file-message').textContent='本日のデータを自動読込しました。';
    } catch(error) {if(number!==loadNumber)return;report=null;selectedId='';refreshSelects();renderAll();el('source-state').textContent='データ未取得';el('source-date').textContent='対象日：未取得';el('source-time').textContent='初回確認時刻：未取得';el('file-message').textContent='自動取得を利用できません：'+error.message;}
    finally{if(pendingAuto===number)pendingAuto=0;if(number===loadNumber)el('reload-feed').disabled=false;}
  }
  document.querySelectorAll('[data-page],[data-goto]').forEach(b=>b.addEventListener('click',()=>showPage(b.dataset.page||b.dataset.goto)));
  document.querySelectorAll('[data-sport]').forEach(b=>b.addEventListener('click',()=>pickSport(b.dataset.sport)));el('return-boat').addEventListener('click',()=>pickSport('boat'));
  document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>{state.mode=b.dataset.mode;syncPreferences();}));el('longshot').addEventListener('change',()=>{state.longshot=el('longshot').checked;syncPreferences();});
  window.addEventListener('hashchange',()=>showPage(location.hash.slice(1)));document.querySelectorAll('.brand').forEach(a=>a.addEventListener('click',()=>showPage('home')));
  for(const id of ['race-search','venue-filter','complete-filter','race-sort'])el(id).addEventListener(id==='race-search'?'input':'change',renderRaces);
  el('global-search').addEventListener('input',()=>{el('race-search').value=el('global-search').value;showPage('races');renderRaces();});el('clear-filters').addEventListener('click',()=>{el('race-search').value='';el('global-search').value='';el('venue-filter').value='';el('complete-filter').checked=false;el('race-sort').value='venue';renderRaces();});
  ['lane-first','lane-second','lane-third'].forEach((id,i)=>{for(let lane=1;lane<=6;lane++)el(id).append(new Option(String(lane),String(lane)));el(id).value=String(i+1);});
  el('ticket-race').addEventListener('change',renderTickets);el('max-picks').addEventListener('change',()=>{state.maxPicks=Number(el('max-picks').value);renderTickets();});
  el('race-budget').addEventListener('change',()=>{const n=Number(el('race-budget').value);if(!Number.isSafeInteger(n)||n<100||n>10000000||n%100){el('ticket-message').textContent='予算は100〜10,000,000円の100円単位で入力してください。';el('race-budget').value=state.raceBudget;return;}state.raceBudget=n;renderTickets();});
  el('ticket-form').addEventListener('submit',e=>{e.preventDefault();const raceId=el('ticket-race').value,lanes=['lane-first','lane-second','lane-third'].map(id=>Number(el(id).value)),amount=Number(el('ticket-amount').value);let error=model.validateTicket(lanes,amount);const tickets=state.candidates.filter(t=>t.raceId===raceId);if(!raceId)error='対象レースを選択してください。';else if(tickets.length>=state.maxPicks)error='最大買い目数に達しています。';else if(tickets.some(t=>t.lanes.join('-')===lanes.join('-')))error='同じ買い目がすでにあります。';else if(tickets.reduce((s,t)=>s+t.amount,0)+amount>state.raceBudget)error='1レース予算を超えています。';el('ticket-message').textContent=error||'未購入の候補に追加しました。';if(error)return;state.candidates.push({raceId,lanes,amount});renderTickets();});
  el('equal-allocate').addEventListener('click',()=>{const tickets=state.candidates.filter(t=>t.raceId===el('ticket-race').value);if(state.raceBudget<tickets.length*100){el('ticket-message').textContent='全候補に100円以上配分できる予算を設定してください。';return;}model.allocate(state.raceBudget,tickets.length).forEach((amount,i)=>tickets[i].amount=amount);el('ticket-message').textContent='1レース予算を均等配分しました。';renderTickets();});
  el('record-purchase').addEventListener('click',()=>{if(invalidatePreviousDay()){renderAll();el('ticket-message').textContent='日付が変わりました。本日のレースを再取得してから記録してください。';loadAuthorizedDayFeed();return;}const raceId=el('ticket-race').value,tickets=state.candidates.filter(t=>t.raceId===raceId),total=tickets.reduce((s,t)=>s+t.amount,0);if(!tickets.length||total>state.raceBudget)return;if(tickets.length>state.maxPicks){el('ticket-message').textContent='最大買い目数を超えています。候補を削除するか点数設定を変更してください。';return;}if(todaySummary().spent+total>state.budget){el('ticket-message').textContent='1日の予算を超えるため記録できません。設定で予算を確認してください。';return;}const race=allRaces().find(r=>r.race_id===raceId);if(!race){el('ticket-message').textContent='対象レースのデータを再取得してください。';return;}tickets.forEach(t=>state.purchases.push({...t,lanes:t.lanes.slice(),raceLabel:raceName(race),day:report.date_jst,payout:null}));state.candidates=state.candidates.filter(t=>t.raceId!==raceId);el('ticket-message').textContent='実際の購入として記録しました。成績で結果を入力できます。';renderAll();});
  el('settings-form').addEventListener('submit',e=>{e.preventDefault();const budget=Number(el('daily-budget').value);if(!Number.isSafeInteger(budget)||budget<100||budget>10000000||budget%100||budget<todaySummary().spent){el('settings-message').textContent='予算は購入済み金額以上、100〜10,000,000円の100円単位で入力してください。';return;}state.budget=budget;state.mode=el('settings-mode').value;state.longshot=el('settings-longshot').checked;syncPreferences();renderHome();el('settings-message').textContent='この画面を開いている間の設定に反映しました。';});
  el('race-file').addEventListener('change',async e=>{
    const file=e.target.files?.[0];if(!file)return;const number=++loadNumber;el('reload-feed').disabled=false;
    try {
      if(file.size>6_000_000)throw new Error('6MBを超えるファイルは読み取れません。');
      if(!/\.json$/i.test(file.name))throw new Error('JSONファイルを選択してください。');
      const content=await file.text();if(number!==loadNumber)return;
      const data=validateCurrent(JSON.parse(content));showReport(data);
      el('source-state').textContent='本日の手動JSON・原本未独立検証';
      el('file-message').textContent='本日の許可フラグありJSONを端末内で読み込みました。サーバーへ送信していません。';
    } catch(error) {
      if(number!==loadNumber)return;
      report=null;selectedId='';refreshSelects();renderAll();el('source-state').textContent='データ未取得';
      el('source-date').textContent='対象日：未取得';el('source-time').textContent='初回確認時刻：未取得';
      el('file-message').textContent='読み込みを停止しました：'+error.message;
    }
  });
  function checkDayAndRefresh() {if(invalidatePreviousDay())renderAll();if(document.visibilityState==='visible')loadAuthorizedDayFeed();}
  function scheduleDayBoundary() {
    const jst=new Date(Date.now()+9*60*60*1000);
    const next=Date.UTC(jst.getUTCFullYear(),jst.getUTCMonth(),jst.getUTCDate()+1)-9*60*60*1000;
    setTimeout(()=>{checkDayAndRefresh();scheduleDayBoundary();},Math.max(50,next-Date.now()+50));
  }
  setInterval(checkDayAndRefresh,60_000);
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')checkDayAndRefresh();});
  scheduleDayBoundary();
  el('reload-feed').addEventListener('click',loadAuthorizedDayFeed);syncPreferences();renderAll();showPage(location.hash.slice(1)||'home');loadAuthorizedDayFeed();
})();
