'use strict';
(() => {
  const UI=globalThis.RaceUI,Money=globalThis.RaceMoney,Settlement=globalThis.RaceSettlement,Exhibition=globalThis.RaceExhibition,Original=globalThis.RaceOriginalExhibition,NameBound=globalThis.RaceNameBoundExhibition,NameBoundEvaluation=globalThis.RaceNameBoundEvaluation,$=id=>document.getElementById(id);
  const names={home:['おかえりなさい','今日も、データを味方に。','レースを知る。根拠を確かめる。あなたの判断を、ここから。'],races:['全国24場の開催情報','全レース一覧','開催場とレースを選んで、出走データを確認しましょう。'],detail:['出走表と直前情報','レース詳細','取得した情報と、その時点を確かめる。'],picks:['自分の判断を記録','買い目配分','予算の範囲で、買い目と購入記録を整理します。'],results:['確定結果から振り返る','成績分析','購入・返還・払戻を区別し、実際の記録から検証します。'],research:['判断の根拠と検証','研究','取得できたデータと、予想の検証状況を確認します。'],settings:['自分に合った使い方','設定','資金と表示の設定は、このブラウザに保存されます。']};
  const defaults={dayBudget:0,raceBudget:0,lossLimit:0,maxBets:8,mode:'balanced',longshot:false,autoRefresh:true};
  let report=null,selectedId='',page='home',tab='overview',feedState='loading',feedMessage='',requestSerial=0,controller=null,toastTimer,storageAvailable=true;
  let settings={...defaults},ledger=[],drafts=new Map(),savingPurchase=false,localStateHealthy=true;
  let raceUpdates=null,raceUpdatesState='idle',raceUpdatesMessage='',raceUpdatesId='',raceRequestSerial=0,raceController=null,knownRaceStops=new Map();
  let predictionReceipt=null,predictionState='idle',predictionMessage='',predictionRaceId='',predictionModelId='',predictionSerial=0,predictionController=null;
  let postReceipt=null,postBaselineReceipt=null,postState='idle',postMessage='',postRaceId='',postSerial=0,postController=null,phaseInventory=new Map();
  let originalReceipt=null,originalBaseline=null,originalState='idle',originalMessage='',originalRaceId='',originalSerial=0,originalController=null;
  let nbEnvelope=null,nbState='idle',nbMessage='',nbRaceId='',nbSerial=0,nbController=null;
  let nbEvaluation=null,nbEvaluationState='idle',nbEvaluationMessage='',nbEvaluationSerial=0,nbEvaluationController=null;
  let evaluation=null,evaluationState='idle',evaluationMessage='',evaluationRaceId='',evaluationSerial=0,evaluationController=null;
  let settlementReports=new Map(),settlementErrors=new Map(),settlementAudit=[],settlementSerial=0,settlementControllers=new Set(),settlementState='idle';
  const SETTINGS_KEY='raceai.settings.v1',LEDGER_KEY='raceai.ledger.v1',STATE_LOCK='raceai.local-state.v1';
  const AUDIT_KEY='raceai.result-audit.v1';
  const yen=n=>Number(n).toLocaleString('ja-JP')+'円';
  const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;};
  const button=(label,cls,action)=>{const b=node('button',cls,label);b.type='button';b.addEventListener('click',action);return b;};
  const option=(label,value)=>{const n=node('option','',label);n.value=value;return n;};
  const today=()=>UI.dayJst();
  const all=()=>UI.allRaces(report);
  const current=()=>all().find(r=>r.race_id===selectedId);
  const raceName=r=>r?r.venueName+' '+Number(r.race_id.slice(-2))+'R':'レース未選択';
  const draft=()=>drafts.get(selectedId)||[];
  const todayLedger=()=>ledger.filter(r=>r.purchase_day===today());
  const limits=()=>({budget_yen:settings.raceBudget,day_budget_yen:settings.dayBudget,loss_limit_yen:settings.lossLimit,max_bets:settings.maxBets});
  const summary=records=>Money.summarize_ledger(records);
  function setMessage(id,message,error=false){$(id).textContent=message;$(id).classList.toggle('error',error);}
  function toast(message,error=false){clearTimeout(toastTimer);$('toast').textContent=message;$('toast').classList.toggle('error',error);$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,4500);}
  function persist(key,value){try{localStorage.setItem(key,JSON.stringify(value));return true;}catch{storageAvailable=false;toast('端末への保存ができません。ブラウザの保存設定を確認してください。',true);return false;}}
  function readLocalState(){
    const raw=JSON.parse(localStorage.getItem(SETTINGS_KEY)||'null'),next={...defaults};
    if(raw!==null){
      if(typeof raw!=='object'||Array.isArray(raw))throw new Error('保存済みの設定を確認できません。');
      for(const key of ['dayBudget','raceBudget','lossLimit']){if(!Number.isSafeInteger(raw[key])||raw[key]<0||raw[key]>10000000||raw[key]%100)throw new Error('保存済みの予算設定が不正です。');next[key]=raw[key];}
      if(![8,16,24,32].includes(raw.maxBets)||!['hit','balanced','return'].includes(raw.mode))throw new Error('保存済みの表示設定が不正です。');
      next.maxBets=raw.maxBets;next.mode=raw.mode;
      for(const key of ['longshot','autoRefresh']){if(typeof raw[key]!=='boolean')throw new Error('保存済みの表示設定が不正です。');next[key]=raw[key];}
    }
    const saved=JSON.parse(localStorage.getItem(LEDGER_KEY)||'[]');
    if(!Array.isArray(saved))throw new Error('保存済みの購入記録を確認できません。');
    // Restored financial claims are never authority; fresh same-origin reports project settlement separately.
    const records=saved.map(({id,race_id,purchased_at,bets})=>({id,race_id,purchased_at,bets}));summary(records);
    return {settings:next,ledger:records.map(r=>({...r,purchase_day:UI.dayJst(new Date(r.purchased_at)),source:'manual'}))};
  }
  function applyLocalState(state){settings=state.settings;ledger=state.ledger;localStateHealthy=true;}
  function restore(){
    try{applyLocalState(readLocalState());}catch{storageAvailable=false;localStateHealthy=false;}
  }
  async function editLocalState(action,requiresLock=false){
    const execute=()=>{let state;try{state=readLocalState();}catch{localStateHealthy=false;throw new Error('保存済みデータを確認できないため、上書きを停止しました。');}applyLocalState(state);return action(state);};
    if(navigator.locks?.request)return navigator.locks.request(STATE_LOCK,{mode:'exclusive'},execute);
    if(requiresLock)throw new Error('このブラウザでは購入記録を安全に保存できません。対応する新しいブラウザで開いてください。');
    return execute();
  }
  function refreshLocalViews(){syncSettings();renderMoney();renderDraft();}
  function clearSettlements(){settlementSerial++;for(const c of settlementControllers)c.abort();settlementControllers.clear();settlementReports.clear();settlementErrors.clear();settlementState='idle';}
  function ledgerIdentity(){return JSON.stringify(ledger);}
  async function saveSettlementAudit(checked,valid){
    await editLocalState(()=>{
      if(!valid())return;
      const saved=JSON.parse(localStorage.getItem(AUDIT_KEY)||'[]'),next=Settlement.appendAudit(saved,checked,new Date().toISOString());
      if(!valid())return;
      if(next.length!==saved.length&&!persist(AUDIT_KEY,next))throw new Error('公式照合の証拠履歴を保存できませんでした。');
      settlementAudit=next;
    },true);
  }
  async function loadSettlements(){
    clearSettlements();
    if(!Settlement){settlementState='error';renderMoney();return;}
    if(!localStateHealthy||!report||feedState==='manual'||report.date_jst!==today()||report.redistribution_authorized!==true){renderMoney();return;}
    const day=today(),feed=report,serial=settlementSerial,localIdentity=ledgerIdentity(),ids=[...new Set(todayLedger().map(r=>r.race_id))].filter(id=>all().some(r=>r.race_id===id));
    if(!ids.length){renderMoney();return;}
    const valid=()=>serial===settlementSerial&&report===feed&&report?.date_jst===day&&today()===day&&$('race-date').value===day&&ledgerIdentity()===localIdentity&&localStateHealthy;
    settlementState='loading';renderMoney();let cursor=0;
    async function worker(){
      while(cursor<ids.length&&valid()){
        const id=ids[cursor++],race=all().find(r=>r.race_id===id),request=new AbortController();settlementControllers.add(request);
        const timeout=setTimeout(()=>request.abort(),15000);
        try{
          const response=await fetch('./api/settlement?race_id='+encodeURIComponent(id),{cache:'no-store',credentials:'same-origin',signal:request.signal}),body=await readRaceBody(response);
          if(!valid())return;if(!response.ok)throw new Error('公式結果の照合APIへの接続に失敗しました。');
          const programSha256=await Settlement.programDigest(race);
          const checked=Settlement.validateReport(JSON.parse(body),{race,dateJst:day,programSha256});
          if(!valid())return;await saveSettlementAudit(checked,valid);if(!valid())return;settlementReports.set(id,checked);
        }catch(error){if(!valid())return;settlementReports.delete(id);settlementErrors.set(id,error.name==='AbortError'?'公式結果の照合がタイムアウトしました。':error.message);}
        finally{clearTimeout(timeout);settlementControllers.delete(request);if(valid())renderMoney();}
      }
    }
    await Promise.all(Array.from({length:Math.min(3,ids.length)},worker));
    if(valid()){settlementState=settlementErrors.size?'error':'ready';renderMoney();}
    else if(serial===settlementSerial){
      // The lock may discover a purchase saved before its storage event is delivered.
      // Start again from that freshly read ledger rather than leaving loading stuck.
      return loadSettlements();
    }
  }
  function financialProjection(records){
    if(Settlement)return Settlement.projectLedger(records,settlementReports,{dateJst:today(),races:feedState==='manual'?[]:all()});
    return {records,summary:summary(records),details:new Map(),hit_count:0,effective_count:0};
  }
  async function updatePreferences(patch){
    try{await editLocalState(()=>{const next={...settings,...patch};if(!persist(SETTINGS_KEY,next))throw new Error('表示設定を保存できませんでした。');settings=next;});refreshLocalViews();}
    catch(error){toast(error.message,true);}
  }
  function showPage(next,updateHash=true){
    page=UI.pages.includes(next)?next:'home';pickSport('boat');
    document.querySelectorAll('[data-view]').forEach(n=>n.hidden=n.dataset.view!==page);
    document.querySelectorAll('[data-page]').forEach(b=>{const active=b.dataset.page===page||(page==='detail'&&b.dataset.page==='races');b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    [ $('page-kicker').textContent,$('page-title').textContent,$('page-description').textContent ]=names[page];
    document.title=names[page][1]+' | RACE AI';
    if(updateHash){const hash='#/'+page+(page==='detail'&&selectedId?'/'+selectedId:'');if(location.hash!==hash)location.hash=hash;}
    if(page==='detail'){renderDetail();loadRaceUpdates();if(tab==='prediction')loadPrediction();}if(page==='picks')renderDraft();
  }
  function pickSport(sport){const boat=sport==='boat';$('boat-view').hidden=!boat;$('coming').hidden=boat;document.querySelectorAll('[data-sport]').forEach(b=>{const active=b.dataset.sport===sport;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});if(!boat)$('coming-title').textContent=({cycle:'競輪',auto:'オートレース',horse:'競馬'})[sport]+'は準備中です';}
  function laneBadge(lane){return node('span','lane-badge lane-'+lane,lane);}
  function combination(value){const n=node('span','combination');const lanes=typeof value==='string'?value.split('-'):value;lanes.forEach((lane,i)=>{if(i)n.append(node('span','','−'));n.append(laneBadge(lane));});return n;}
  function racerCard(boat,lane,expanded=false){
    const card=node('article','racer-mini'),portrait=node('div','racer-portrait');portrait.setAttribute('aria-hidden','true');portrait.append(laneBadge(lane),node('span','silhouette'));card.append(portrait,node('strong','',UI.text(boat?.name)),node('small','',boat?'登録 '+boat.racer_registration_id:'出走情報 未取得'));
    if(expanded){const stats=node('div','racer-stats');for(const [label,key]of [['モーター','motor_no'],['平均ST','average_st'],['展示タイム','display_time']])stats.append(node('span','',label),node('b','',UI.text(boat?.[key])));card.append(stats);}
    else card.append(node('span','racer-fact',boat?.motor_no?'モーター '+boat.motor_no:'データ未取得'));
    return card;
  }
  function racerStrip(race,expanded=false){const n=node('div','racers-strip');for(let lane=1;lane<=6;lane++)n.append(racerCard(race?.boats.find(b=>b.lane===lane),lane,expanded));return n;}
  function empty(title,description,action){const n=node('div','empty-state');n.append(node('span','','≋'),node('h3','',title),node('p','',description));if(action)n.append(button(action.label,'secondary',action.run));return n;}
  function status(state,message){feedState=state;feedMessage=message;$('feed-banner').dataset.state=state;
    const titles={loading:'本日のデータを確認中',ready:'当日の出走データを読み込みました',unobtained:'データ未取得',error:'データの取得に失敗しました','no-event':'開催なしを確認しました',historical:'この日付のデータは未取得です',manual:'検証用JSONを表示しています'};
    $('feed-status-title').textContent=titles[state]||titles.unobtained;$('feed-status-description').textContent=message;$('feed-updated').textContent=state==='loading'?'確認中':'確認 '+new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit'}).format(new Date());
    $('refresh-feed').classList.toggle('loading',state==='loading');$('refresh-feed').disabled=state==='loading';
  }
  function renderHome(){
    const rows=all().sort((a,b)=>(UI.cutoff(a,report.date_jst)??Infinity)-(UI.cutoff(b,report.date_jst)??Infinity));
    const feature=rows.find(r=>UI.purchaseAvailability(r,report.date_jst).allowed)||rows[0];
    $('featured-race').textContent=feature?raceName(feature):'今日の一戦を、データから。';$('featured-detail').textContent=feature?'締切 '+UI.timeLabel(feature,report.date_jst)+' · 出走 '+feature.boats.length+'艇 · 出走表を確認できます。':'当日の出走表が届き次第、レースを表示します。';$('hero-date').textContent=report?report.date_jst+' · JST':'日本時間 '+today();
    $('home-racers').replaceChildren(...racerStrip(feature).children);$('home-venues').textContent=report?report.venues.filter(v=>v.races.length).length+'場':'未取得';$('home-races').textContent=report?report.races:'―';$('home-complete').textContent=report?report.complete_six_boat_races:'―';$('featured-open').disabled=!feature;
    $('featured-open').onclick=()=>{if(feature){selectRace(feature.race_id);showPage('detail');}};
  }
  function renderVenues(){
    const selected=$('venue-select').value;$('venue-buttons').replaceChildren(...UI.venueNames.map((name,i)=>{const code=String(i+1).padStart(2,'0'),state=UI.venueState(report,code);const b=button('','venue-button '+state+(selected===code?' selected':''),()=>{$('venue-select').value=selected===code?'':code;renderRaces();});b.append(node('span','',name),node('small','',({ready:'取得済み','no-event':'開催なし',unobtained:'未取得',error:'取得失敗'})[state]));b.setAttribute('aria-pressed',String(selected===code));return b;}));
    $('venue-browser-state').textContent=report?'取得 '+report.venues.filter(v=>v.races.length).length+'場':'取得待ち';
  }
  function renderRaces(){
    renderVenues();const code=$('venue-select').value,query=$('global-search').value;const rows=UI.filterRaces(report,{venue:code,query,number:$('race-number-filter').value,sort:$('race-sort').value});
    $('race-list-title').textContent=code?UI.venueNames[Number(code)-1]+'のレース':'レース一覧';$('race-count').textContent=report?rows.length+'レース / 収録 '+report.races+'レース':'未取得';
    if(rows.length){$('race-cards').replaceChildren(...rows.map(r=>{
      const n=node('article','race-card'),header=node('div','race-card-header'),time=node('div','race-card-time');time.append(node('span','','締切時刻'),node('strong','',UI.timeLabel(r,report.date_jst)));header.append(node('span','sport-badge','ボートレース'),node('h3','',raceName(r)),time);
      const bottom=node('div','race-card-bottom'),phase=node('p','race-phase-status',Original?.phaseStatus(phaseInventory.get(r.race_id))||Exhibition?.phaseStatus(phaseInventory.get(r.race_id))||'展示前 未確認 · 展示後 未確認 · オリジナル反映 未確認');bottom.append(node('p','muted',r.preview_available?'展示情報あり · AI評価は未検証':'展示情報 未取得 · AI評価は未検証'),button('出走表・詳細を見る →','outline-button',()=>{selectRace(r.race_id);showPage('detail');}));n.append(header,racerStrip(r),phase,bottom);return n;
    }));return;}
    if(feedState==='loading'){const n=node('div','skeleton-card');n.setAttribute('aria-label','レースデータを読み込み中');for(let i=0;i<3;i++)n.append(node('span'));$('race-cards').replaceChildren(n);return;}
    const state=code?UI.venueState(report,code):report?.status==='NO_EVENT'?'no-event':feedState;
    let title='本日の出走データは未取得です',description='取得でき次第ここに表示します。未取得のため、開催の有無はまだ確認できません。';
    if(state==='no-event'){title='この日の開催はありません';description='取得済みの開催情報で、開催なしを確認しました。';}
    else if(feedState==='error'||state==='error'){title='出走データを取得できませんでした';description=feedState==='error'?feedMessage:'この会場の取得処理に失敗しています。開催なしとは区別しています。更新して再確認できます。';}
    else if(feedState==='historical'){title='選択日の履歴は未取得です';description='当日データの配信に対応しています。今日に戻ると、最新の出走表を確認します。';}
    else if(report&&(!code||UI.venueState(report,code)==='ready')){title='条件に合うレースがありません';description='選手名・開催場・レース番号の検索条件を変更してください。';}
    else if(code)title=UI.venueNames[Number(code)-1]+'のデータは未取得です';
    $('race-cards').replaceChildren(empty(title,description,{label:feedState==='historical'?'今日に戻る':'もう一度確認',run:()=>{$('race-date').value=today();loadAuthorizedDayFeed();}}));
  }
  function clearRaceUpdates(){clearNameBound();raceRequestSerial++;raceController?.abort();raceController=null;raceUpdates=null;raceUpdatesState='idle';raceUpdatesMessage='';raceUpdatesId='';clearPrediction();}
  function selectRace(id){if(!all().some(r=>r.race_id===id))return;if(selectedId!==id)clearRaceUpdates();selectedId=id;refreshRaceSelect();renderDetail();renderDraft();}
  function updateFor(kind){return raceUpdates?.records.find(wrapper=>wrapper.record.kind===kind);}
  function programIdentity(race){return JSON.stringify([race.race_id,race.closed_at,race.boats.slice().sort((a,b)=>a.lane-b.lane).map(b=>[b.lane,b.racer_registration_id,b.name])]);}
  function researchIdentity(race){return JSON.stringify([programIdentity(race),race.boats.slice().sort((a,b)=>a.lane-b.lane).map(b=>[b.lane,b.national_win_rate??null])]);}
  function clearEvaluation(){evaluationSerial++;evaluationController?.abort();evaluationController=null;evaluation=null;evaluationState='idle';evaluationMessage='';evaluationRaceId='';}
  function clearExhibition(){if(postRaceId&&postState==='loading')phaseInventory.set(postRaceId,{...phaseInventory.get(postRaceId),post:'idle'});postSerial++;postController?.abort();postController=null;postReceipt=null;postBaselineReceipt=null;postState='idle';postMessage='';postRaceId='';}
  function clearOriginal(){if(originalRaceId&&originalState==='loading')phaseInventory.set(originalRaceId,{...phaseInventory.get(originalRaceId),original:'idle'});originalSerial++;originalController?.abort();originalController=null;originalReceipt=null;originalBaseline=null;originalState='idle';originalMessage='';originalRaceId='';}
  function updatePhase(id,patch){phaseInventory.set(id,{...phaseInventory.get(id),...patch});renderRaces();}
  function clearPrediction(){clearNameBound();if(predictionRaceId&&predictionState==='loading')phaseInventory.set(predictionRaceId,{...phaseInventory.get(predictionRaceId),baseline:'idle'});predictionSerial++;predictionController?.abort();predictionController=null;predictionReceipt=null;predictionState='idle';predictionMessage='';predictionRaceId='';predictionModelId='';clearExhibition();clearOriginal();clearEvaluation();}
  async function loadPrediction(force=false){
    const race=current();if(page!=='detail'||tab!=='prediction'||!race||report.date_jst!==today())return;
    if(!force&&predictionRaceId===race.race_id&&predictionState!=='idle'){if(predictionState!=='loading'){loadEvaluation();loadExhibition();}return;}
    predictionController?.abort();clearExhibition();clearOriginal();clearEvaluation();const request=new AbortController(),serial=++predictionSerial,id=race.race_id,day=report.date_jst,identity=researchIdentity(race);predictionController=request;predictionReceipt=null;predictionRaceId=id;predictionState='loading';predictionMessage='締切前に保存された研究用の計算結果を確認しています。';updatePhase(id,{baseline:'loading',post:'idle'});renderDetailTab();
    const valid=()=>serial===predictionSerial&&selectedId===id&&report?.date_jst===day&&today()===day&&current()&&researchIdentity(current())===identity;
    const timeout=setTimeout(()=>request.abort(),15000);
    try{
      const response=await fetch('./api/prediction?race_id='+encodeURIComponent(id),{cache:'no-store',credentials:'same-origin',signal:request.signal}),body=await readRaceBody(response);if(!valid())return;
      if(response.status===404){predictionState='unobtained';predictionMessage='このレースの研究予測はまだ保存されていません。';return;}
      if(!response.ok)throw new Error('保存済みの研究予測を取得できませんでした。');
      let raw;try{raw=JSON.parse(body);}catch{throw new Error('研究予測データの形式を確認できません。');}
      const checked=UI.validatePredictionReceipt(raw,{race:current(),dateJst:day});if(!valid())return;predictionReceipt=checked;predictionState='ready';predictionMessage='締切前に生成・保存された研究用の確率です。精度と確率校正は未検証です。';predictionModelId=checked.snapshot.models.some(m=>m.model_id===predictionModelId)?predictionModelId:checked.snapshot.models.find(m=>m.model_id==='official-program-rating-pl')?.model_id||checked.snapshot.models[0].model_id;
    }catch(error){if(!valid())return;predictionReceipt=null;predictionState='error';predictionMessage=error.name==='AbortError'?'研究予測の取得がタイムアウトしました。再確認してください。':error.message;}
    finally{clearTimeout(timeout);if(valid()){updatePhase(id,{baseline:predictionState});if(tab==='prediction'){renderDetailTab();loadEvaluation();loadExhibition();}}}
  }
  async function loadExhibition(){
    const race=current();if(page!=='detail'||tab!=='prediction'||!race||report.date_jst!==today()||predictionState==='loading')return;
    if(postRaceId===race.race_id&&postState!=='idle')return;
    clearExhibition();const request=new AbortController(),serial=postSerial,id=race.race_id,day=report.date_jst,identity=programIdentity(race),baseline=predictionReceipt;postController=request;postRaceId=id;postState='loading';postMessage='展示後に保存された別の研究予測を確認しています。';updatePhase(id,{post:'loading'});renderDetailTab();
    const valid=()=>serial===postSerial&&selectedId===id&&report?.date_jst===day&&today()===day&&current()&&programIdentity(current())===identity&&predictionReceipt===baseline;
    const timeout=setTimeout(()=>request.abort(),15000);
    try{
      const response=await fetch('./api/exhibition-prediction?race_id='+encodeURIComponent(id),{cache:'no-store',credentials:'same-origin',signal:request.signal}),body=await readRaceBody(response);if(!valid())return;
      if(response.status===404){postState='unobtained';postMessage='展示後予想はまだ保存されていません。展示前予想を更新済みとして代用しません。';return;}
      if(!response.ok)throw new Error('展示後予想の取得に失敗しました。');
      const raw=JSON.parse(body),link=raw?.snapshot?.baseline_link;let pinned=baseline;
      if(!pinned||pinned.request_id!==link?.request_id){
        if(typeof link?.request_id!=='string'||!/^([1-9][0-9]{0,19})-([1-9][0-9]{0,3})$/.test(link.request_id))throw new Error('展示後予想の比較元を確認できません。');
        const response=await fetch('./api/prediction?race_id='+encodeURIComponent(id)+'&request_id='+encodeURIComponent(link.request_id),{cache:'no-store',credentials:'same-origin',signal:request.signal});const body=await readRaceBody(response);if(!valid())return;if(!response.ok)throw new Error('展示後予想の固定された比較元を取得できません。');pinned=UI.validatePredictionReceipt(JSON.parse(body),{race:current(),dateJst:day});
      }
      if(!Exhibition?.validateReceipt)throw new Error('展示後予想の検証機能を読み込めませんでした。');
      const programIdentitySha256=await Settlement.programDigest(race),checked=Exhibition.validateReceipt(raw,{race:current(),dateJst:day,baselineReceipt:pinned,programIdentitySha256});if(!valid())return;
      postReceipt=checked;postBaselineReceipt=pinned;postState='ready';postMessage='展示タイムだけを使った、別保存の研究予測です。精度は未検証です。';
    }catch(error){if(!valid())return;postReceipt=null;postBaselineReceipt=null;postState='error';postMessage=error.name==='AbortError'?'展示後予想の取得がタイムアウトしました。':error.message;}
    finally{clearTimeout(timeout);if(valid()){updatePhase(id,{post:postState});if(tab==='prediction')renderDetailTab();}}
  }
  function clearNameBound(){clearNameBoundEvaluation();nbSerial++;nbController?.abort();nbController=null;nbEnvelope=null;nbState='idle';nbMessage='';nbRaceId='';}
  async function loadNameBound(){
    const race=current();if(page!=='detail'||tab!=='prediction'||!race||report.date_jst!==today())return;
    clearNameBound();const request=new AbortController(),serial=nbSerial,id=race.race_id,day=report.date_jst,identity=programIdentity(race);nbController=request;nbRaceId=id;nbState='loading';nbMessage='選択したレースの保存済み比較を確認しています。';renderDetailTab();
    const valid=()=>serial===nbSerial&&selectedId===id&&report?.date_jst===day&&today()===day&&current()&&programIdentity(current())===identity;
    const timeout=setTimeout(()=>request.abort(),15000);
    try{
      const response=await fetch('./api/name-bound-exhibition?race_id='+encodeURIComponent(id),{cache:'no-store',credentials:'same-origin',signal:request.signal}),body=await readRaceBody(response);if(!valid())return;
      if(response.status===404){nbState='unobtained';nbMessage='この比較は未保存です。';return;}if(!response.ok)throw new Error('保存済み比較を取得できませんでした。');
      const raw=JSON.parse(body),checked=NameBound.validateNameBoundComparison(raw,race),originalDigest=await Settlement.programDigest(race);if(!valid())return;
      if(originalDigest!==checked.inputs.program_identity_sha256)throw new Error('比較元の出走表が一致しません。');
      const fullNames=new Map(checked.name_binding.receipt.snapshot.bindings.map(b=>[b.lane,b.verified_full_name])),projected={...race,boats:race.boats.map(b=>({...b,name:fullNames.get(b.lane)}))};
      const projectedDigest=await Settlement.programDigest(projected);if(!valid())return;
      if(projectedDigest!==checked.inputs.validation_program_identity_sha256)throw new Error('出典に照合した6氏名が一致しません。');
      nbEnvelope=checked;nbState='ready';nbMessage='B情報のみ比較元と、別保存の2モデルを表示しています。';
    }catch(error){if(!valid())return;nbEnvelope=null;nbState='error';nbMessage=error.name==='AbortError'?'保存済み比較の確認がタイムアウトしました。':error.message;}
    finally{clearTimeout(timeout);if(valid()&&tab==='prediction')renderDetailTab();}
  }
  function renderNameBound(){
    const panel=node('section','name-bound-comparison');panel.dataset.state=nbState;panel.dataset.raceId=nbRaceId;
    const head=node('div','section-head'),action=button(nbState==='loading'?'確認中…':'保存済み展示比較を確認','outline-button',loadNameBound);action.id='load-name-bound-exhibition';action.disabled=nbState==='loading';head.append(node('h3','prediction-section-title','保存済みの展示比較'),action);panel.append(head,node('p','photo-note','B情報のみ比較元・通常展示反映・オリジナル展示反映を、同じ固定比較元で確認します。選択レースのみを読み込みます。'));
    const status=node('p','message',nbMessage||'保存済み比較は未取得です。');status.setAttribute('role','status');panel.append(status);
    if(nbEnvelope){try{const content=node('div','nb-content');const parsed=new DOMParser().parseFromString(NameBound.renderNameBoundComparison(nbEnvelope,current()),'text/html');content.append(...parsed.body.childNodes);panel.append(content);}catch{clearNameBound();panel.dataset.state='error';status.textContent='比較の対象日・固定入力を確認できません。';}}
    if(nbEnvelope)panel.append(renderNameBoundEvaluationPanel());
    return panel;
  }
  function clearNameBoundEvaluation(){nbEvaluationSerial++;nbEvaluationController?.abort();nbEvaluationController=null;nbEvaluation=null;nbEvaluationState='idle';nbEvaluationMessage='';}
  async function loadNameBoundEvaluation(){
    const race=current();if(page!=='detail'||tab!=='prediction'||!race||report.date_jst!==today()||!nbEnvelope||nbState!=='ready')return;
    clearNameBoundEvaluation();const request=new AbortController(),serial=nbEvaluationSerial,id=race.race_id,day=report.date_jst,identity=programIdentity(race),nbEnvelopeRef=nbEnvelope,nonce=nbEnvelopeRef.receipt.request_id,forecastSerial=nbSerial;
    nbEvaluationController=request;nbEvaluationState='loading';nbEvaluationMessage='この保存番号の予想と、取得済みの公式結果を照合しています。';renderDetailTab();
    const valid=()=>serial===nbEvaluationSerial&&forecastSerial===nbSerial&&selectedId===id&&report?.date_jst===day&&today()===day&&current()&&programIdentity(current())===identity&&nbEnvelope===nbEnvelopeRef&&nbEnvelopeRef.receipt.request_id===nonce;
    const timeout=setTimeout(()=>request.abort(),15000);
    try{
      const response=await fetch('./api/name-bound-evaluation?race_id='+encodeURIComponent(id)+'&forecast_request_id='+encodeURIComponent(nonce),{cache:'no-store',credentials:'same-origin',signal:request.signal}),body=await readRaceBody(response);if(!valid())return;
      if(response.status===404){nbEvaluationState='unobtained';nbEvaluationMessage='指定した保存番号の予想を取得できませんでした。';return;}
      if(!response.ok)throw new Error('保存済み予想と公式結果の照合を取得できませんでした。');
      const checked=NameBoundEvaluation.validateNameBoundEvaluation(JSON.parse(body),nbEnvelopeRef,race,Date.now());if(!valid())return;
      nbEvaluation=checked;nbEvaluationState='ready';nbEvaluationMessage=checked.status==='EVALUATED'?'保存済みの3段階の予想を、1レースの公式着順と照合しました。':'公式結果の取得・確定状況を表示しています。';
    }catch(error){if(!valid())return;nbEvaluation=null;nbEvaluationState='error';nbEvaluationMessage=error.name==='AbortError'?'結果との照合がタイムアウトしました。':error.message;}
    finally{clearTimeout(timeout);if(valid()&&tab==='prediction')renderDetailTab();}
  }
  function renderNameBoundEvaluationPanel(){
    const panel=node('section','nb-evaluation');panel.dataset.state=nbEvaluationState;
    const head=node('div','section-head'),action=button(nbEvaluationState==='loading'?'照合中…':'保存済み予想を結果と照合','outline-button',loadNameBoundEvaluation);action.id='load-name-bound-evaluation';action.disabled=nbEvaluationState==='loading';head.append(node('h3','prediction-section-title','公式結果との照合'),action);panel.append(head,node('p','photo-note','表示中の保存番号に固定して、取得済みの公式結果と比較します。'));
    const status=node('p','message',nbEvaluationMessage||'結果との照合は未実行です。');status.setAttribute('role','status');panel.append(status);
    if(nbEvaluation){try{const content=node('div','nb-evaluation-content');const parsed=new DOMParser().parseFromString(NameBoundEvaluation.renderNameBoundEvaluation(nbEvaluation,nbEnvelope,current()),'text/html');content.append(...parsed.body.childNodes);panel.append(content);}catch{clearNameBoundEvaluation();panel.dataset.state='error';status.textContent='結果照合の対象・固定リンク・スコアを確認できません。';}}
    return panel;
  }
  async function loadOriginal(){
    const race=current();if(page!=='detail'||tab!=='prediction'||!race||report.date_jst!==today())return;
    clearOriginal();const request=new AbortController(),serial=originalSerial,id=race.race_id,day=report.date_jst,identity=programIdentity(race),baseline=predictionReceipt;originalController=request;originalRaceId=id;originalState='loading';originalMessage='オリジナル展示を反映した、別保存の研究予測を確認しています。';updatePhase(id,{original:'loading'});renderDetailTab();
    const valid=()=>serial===originalSerial&&selectedId===id&&report?.date_jst===day&&today()===day&&current()&&programIdentity(current())===identity&&predictionReceipt===baseline;
    const timeout=setTimeout(()=>request.abort(),15000);
    try{
      const response=await fetch('./api/exhibition-prediction?race_id='+encodeURIComponent(id)+'&variant=original-v1',{cache:'no-store',credentials:'same-origin',signal:request.signal}),body=await readRaceBody(response);if(!valid())return;
      if(response.status===404){originalState='unobtained';originalMessage='オリジナル反映予想は未保存です。既存の展示後予想で代用しません。';return;}if(!response.ok)throw new Error('オリジナル反映予想の取得に失敗しました。');
      const raw=JSON.parse(body),link=raw?.snapshot?.baseline_link;let pinned=baseline;
      if(!pinned||pinned.request_id!==link?.request_id){if(typeof link?.request_id!=='string'||!/^([1-9][0-9]{0,19})-([1-9][0-9]{0,3})$/.test(link.request_id))throw new Error('オリジナル反映予想の比較元を確認できません。');const response=await fetch('./api/prediction?race_id='+encodeURIComponent(id)+'&request_id='+encodeURIComponent(link.request_id),{cache:'no-store',credentials:'same-origin',signal:request.signal}),body=await readRaceBody(response);if(!valid())return;if(!response.ok)throw new Error('オリジナル反映予想の固定された比較元を取得できません。');pinned=UI.validatePredictionReceipt(JSON.parse(body),{race:current(),dateJst:day});}
      if(!Original?.validateReceipt)throw new Error('オリジナル反映予想の検証機能を読み込めませんでした。');
      const programIdentitySha256=await Settlement.programDigest(race),checked=Original.validateReceipt(raw,{race:current(),dateJst:day,baselineReceipt:pinned,programIdentitySha256});if(!valid())return;originalReceipt=checked;originalBaseline=pinned;originalState='ready';originalMessage='展示・周回・回り足・直線の実測値を使った未学習の別モデルです。映像特徴量は未使用です。';
    }catch(error){if(!valid())return;originalReceipt=null;originalBaseline=null;originalState='error';originalMessage=error.name==='AbortError'?'オリジナル反映予想の取得がタイムアウトしました。':error.message;}
    finally{clearTimeout(timeout);if(valid()){updatePhase(id,{original:originalState});if(tab==='prediction')renderDetailTab();}}
  }
  async function loadEvaluation(){
    const race=current();if(page!=='detail'||tab!=='prediction'||!race||report.date_jst!==today()||predictionState==='loading')return;
    if(evaluationRaceId===race.race_id&&evaluationState!=='idle')return;
    evaluationController?.abort();const request=new AbortController(),serial=++evaluationSerial,id=race.race_id,day=report.date_jst,identity=researchIdentity(race),saved=predictionReceipt;evaluationController=request;evaluation=null;evaluationRaceId=id;evaluationState='loading';evaluationMessage='保存済みの予測と公式結果を、同じレース・情報時点で照合しています。';renderDetailTab();
    const valid=()=>serial===evaluationSerial&&selectedId===id&&report?.date_jst===day&&today()===day&&current()&&researchIdentity(current())===identity&&predictionReceipt===saved;
    const timeout=setTimeout(()=>request.abort(),15000);
    try{
      const response=await fetch('./api/evaluation?race_id='+encodeURIComponent(id),{cache:'no-store',credentials:'same-origin',signal:request.signal}),body=await readRaceBody(response);if(!valid())return;
      if(response.status===404){evaluationState='unobtained';evaluationMessage='このレースの研究評価はまだ取得できません。';return;}
      if(!response.ok)throw new Error('研究評価を取得できませんでした。');
      let raw;try{raw=JSON.parse(body);}catch{throw new Error('研究評価データの形式を確認できません。');}
      const checked=UI.validateEvaluation(raw,{race:current(),dateJst:day,predictionReceipt:saved});if(!valid())return;evaluation=checked;evaluationState='ready';evaluationMessage='取得済みの公式結果との照合状況です。';
    }catch(error){if(!valid())return;evaluation=null;evaluationState='error';evaluationMessage=error.name==='AbortError'?'研究評価の取得がタイムアウトしました。再確認してください。':error.message;}
    finally{clearTimeout(timeout);if(valid()&&tab==='prediction')renderDetailTab();}
  }
  async function readRaceBody(response){
    const max=256000;if(Number(response.headers.get('content-length')||0)>max)throw new Error('更新データが大きすぎます。');
    if(!response.body){const value=await response.text();if(new TextEncoder().encode(value).length>max)throw new Error('更新データが大きすぎます。');return value;}
    const reader=response.body.getReader(),decoder=new TextDecoder('utf-8',{fatal:true});let size=0,value='';
    try{while(true){const chunk=await reader.read();if(chunk.done)break;size+=chunk.value.byteLength;if(size>max){await reader.cancel();throw new Error('更新データが大きすぎます。');}value+=decoder.decode(chunk.value,{stream:true});}return value+decoder.decode();}finally{reader.releaseLock();}
  }
  async function loadRaceUpdates(force=false){
    const race=current();if(page!=='detail'||!race||report.date_jst!==today())return;
    if(!force&&raceUpdatesId===race.race_id&&raceUpdatesState!=='idle')return;
    raceController?.abort();const request=new AbortController();raceController=request;const serial=++raceRequestSerial,id=race.race_id,day=report.date_jst,identity=programIdentity(race);raceUpdates=null;raceUpdatesId=id;raceUpdatesState='loading';raceUpdatesMessage='公式の直前情報・オッズ・結果を確認しています。';renderDetail();
    const valid=()=>serial===raceRequestSerial&&selectedId===id&&report?.date_jst===day&&today()===day&&current()&&programIdentity(current())===identity;
    const timeout=setTimeout(()=>request.abort(),10000);
    try{
      const response=await fetch('./api/race?race_id='+encodeURIComponent(id),{cache:'no-store',credentials:'same-origin',signal:request.signal});
      const text=await readRaceBody(response);if(!valid())return;
      if(response.status===404){raceUpdatesState='unobtained';raceUpdatesMessage='このレースの直前情報・オッズ・結果は未取得です。';return;}
      if(!response.ok)throw new Error('レース更新データを取得できませんでした。');
      let raw;try{raw=JSON.parse(text);}catch{throw new Error('更新データの形式を確認できません。');}
      const checked=UI.validateRaceBundle(raw,{race:current(),dateJst:day});if(!valid())return;
      const result=checked.records.find(w=>w.record.kind==='raceresult')?.record;
      if(result?.body_identity_verified===true&&result.data){if(['cancelled','no_contest','postponed'].includes(result.data.status))knownRaceStops.set(id,{identity,status:result.data.status});else if(result.data.finish_confirmed===true||result.data.confirmed===true)knownRaceStops.delete(id);}
      raceUpdates=checked;raceUpdatesState='ready';raceUpdatesMessage=checked.records.length?'取得時刻と保存時刻を確認できます。':'このレースの更新情報は未取得です。';
    }catch(error){if(!valid())return;raceUpdates=null;raceUpdatesState='error';raceUpdatesMessage=error.name==='AbortError'?'更新データの取得がタイムアウトしました。もう一度更新してください。':error.message;}
    finally{clearTimeout(timeout);if(valid()){renderDetail();renderDraft();}}
  }
  function refreshRaceSelect(){const rows=all().filter(r=>!current()||r.venue===current().venue);$('race-select').replaceChildren(...rows.map(r=>option(raceName(r),r.race_id)));$('race-select').disabled=!rows.length;if(rows.length)$('race-select').value=selectedId;else $('race-select').append(option('データ未取得',''));}
  function renderDetail(){
    const race=current(),preview=updateFor('beforeinfo')?.record.data;$('detail-title').textContent=raceName(race);$('detail-breadcrumb').textContent=raceName(race);$('detail-cutoff').textContent=race?UI.timeLabel(race,report.date_jst):'未取得';$('detail-cutoff-status').textContent=race?UI.purchaseAvailability(race,report.date_jst).reason:'時刻未確認';$('race-meta').textContent=race?report.date_jst+' · '+race.boats.length+'艇 · 展示 '+(preview?.boats?.some(b=>b.display_time!=null||b.preview_st!=null)?'取得済み':'未取得'):'取得済みのレースから出走表を確認できます。';$('detail-to-picks').disabled=!race;
    $('detail-racers').replaceChildren(...racerStrip(race,true).children);$('weather-chips').replaceChildren();
    const weather=preview?.weather||{};for(const [label,key,unit]of [['風速','wind_speed_mps','m/s'],['風向番号','wind_direction_source_code',''],['波高','wave_height_cm','cm']])$('weather-chips').append(node('span','',label+' '+(weather[key]!=null?UI.text(weather[key])+unit:'未取得')));
    if(race){$('racers-body').replaceChildren(...race.boats.slice().sort((a,b)=>a.lane-b.lane).map(b=>{const row=node('tr'),lane=node('td'),name=node('td');lane.append(laneBadge(b.lane));name.append(node('span','table-name',UI.text(b.name)),node('small','table-registration','登録 '+b.racer_registration_id));row.append(lane,name,...['motor_no','average_st','display_time','preview_course'].map(key=>node('td','',UI.text(b[key]))));return row;}));}
    else{const row=node('tr'),cell=node('td','empty','レース未選択');cell.colSpan=6;row.append(cell);$('racers-body').replaceChildren(row);}
    renderDetailTab();
  }
  function table(headers,rows){const scroll=node('div','table-scroll'),table=node('table'),head=node('thead'),body=node('tbody'),tr=node('tr');headers.forEach(v=>tr.append(node('th','',v)));head.append(tr);rows.forEach(fields=>{const row=node('tr');fields.forEach(v=>row.append(node('td','',UI.text(v))));body.append(row);});table.append(head,body);scroll.append(table);return scroll;}
  function stampLabel(value){return new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(value))+' JST';}
  function updateProof(wrapper){
    const proof=node('div','update-proof'),record=wrapper.record,phase=UI.raceUpdatePhase(wrapper,current().closed_at),link=node('a','',({beforeinfo:'公式直前情報',odds3t:'公式3連単オッズ',raceresult:'公式レース結果'})[record.kind]);link.href=record.source_url;link.target='_blank';link.rel='noopener noreferrer';
    proof.append(node('span','state-pill '+(phase.preRace?'ready':'warning'),phase.label),link,node('small','','取得 '+stampLabel(record.captured_at)),node('small','','保存 '+stampLabel(wrapper.cloud_saved_at)));return proof;
  }
  function updateStatus(){const n=node('div','race-update-status');n.dataset.state=raceUpdatesState;n.append(node('span','',raceUpdatesState==='loading'?'確認中':raceUpdatesState==='error'?'取得失敗':raceUpdatesState==='ready'?'更新情報':'未取得'),node('p','',raceUpdatesMessage||'直前情報・オッズ・結果は未取得です。'));return n;}
  function renderPreview(){
    const panel=node('section','official-update-panel'),wrapper=updateFor('beforeinfo');panel.append(node('h3','','展示・直前情報'));
    if(!wrapper){panel.append(node('p','muted','展示・スタート展示・水面気象は未取得です。'));return panel;}
    panel.append(updateProof(wrapper));const record=wrapper.record,data=record.data;
    if(!data){panel.append(node('p','muted','公式ページの情報は未取得です。数値を補完せずに表示しています。'));return panel;}
    panel.append(table(['艇','展示タイム','展示ST','展示進入','チルト'],data.boats.map(b=>[b.lane,b.display_time,b.preview_st_status==='OK'?b.preview_st:b.preview_raw_st||null,b.preview_course,b.tilt])));
    const weather=node('div','official-weather'),w=data.weather||{};for(const [label,key,unit]of [['天候','weather_label',''],['風速','wind_speed_mps','m/s'],['波高','wave_height_cm','cm'],['気温','air_temperature_c','℃'],['水温','water_temperature_c','℃']])weather.append(node('span','',label+' '+(w[key]!=null?UI.text(w[key])+unit:'未取得')));panel.append(weather,node('p','photo-note','展示進入は確認できた値だけを表示します。スタート展示の表示順を実進入コースへ読み替えません。'));
    if(w.source_reported_local_time)panel.append(node('p','photo-note','気象の表示時刻 '+UI.text(w.source_reported_local_time)+'（日付は原本で未確認）'));
    if(record.status==='PENDING')panel.append(node('p','muted','展示タイム・展示STは未取得です。'));
    return panel;
  }
  function renderOdds(){
    const panel=node('section','official-update-panel'),wrapper=updateFor('odds3t');panel.append(node('h3','','3連単オッズ'));
    if(!wrapper){panel.append(node('p','muted','オッズは未取得です。'));return panel;}
    panel.append(updateProof(wrapper));const record=wrapper.record;
    if(!record.data){panel.append(node('p','muted','公式ページのオッズは未取得です。'));return panel;}
    const rows=UI.sortedOdds(record),known=rows.filter(r=>r.odds!==null).length;panel.append(node('p','muted',(record.data.odds_phase==='final'?'締切時オッズ':'取得時点のオッズ')+' · '+known+' / 120通り取得 · 低い倍率から表示'));
    const grid=node('div','odds-grid');grid.setAttribute('aria-label','3連単120通りのオッズ');for(const row of rows){const item=node('div','odds-item');item.append(combination(row.combination),node('strong','',row.odds===null?'未取得':row.odds+'倍'));grid.append(item);}panel.append(grid,node('p','photo-note','取得後にオッズが変わる場合があります。未取得のオッズは0倍として扱いません。AIの推奨買い目・期待値は未接続です。'));return panel;
  }
  function renderOfficialResult(){
    const panel=node('section','official-update-panel'),wrapper=updateFor('raceresult');panel.append(node('h3','','このレースの結果'));
    if(!wrapper){panel.append(node('p','muted','結果は未取得・未確定です。'));return panel;}
    panel.append(updateProof(wrapper));const record=wrapper.record,view=UI.confirmedResultView(record),data=record.data;
    if(!data||record.status==='PENDING'){panel.append(node('p','muted',data?.status==='postponed'?'延期の情報あり・返還処理は未確定です。':'結果は未確定です。着順や払戻を0として表示しません。'));return panel;}
    panel.append(node('p','result-disposition',({settled:'着順の確認済み情報',dead_heat:'同着を含む結果・払戻の網羅は確認中',special:'特払いを含む結果',cancelled:'レース中止',no_contest:'不成立',postponed:'レース延期'})[view.status]));
    if(view.results.length)panel.append(table(['艇','登録番号','着順・状態','本番ST','実進入'],view.results.slice().sort((a,b)=>(a.finish??99)-(b.finish??99)||a.lane-b.lane).map(r=>[r.lane,r.racer_registration_id,r.finish??r.finish_status,r.actual_st_status==='OK'?r.actual_st:r.actual_raw_st||null,r.actual_course])));
    else panel.append(node('p','muted','着順は未確定です。'));
    const labels={trifecta:'3連単',trio:'3連複',exacta:'2連単',quinella:'2連複',quinella_place:'拡連複',win:'単勝',place:'複勝'};
    if(view.payouts.length||view.specialPayouts.length){panel.append(node('h4','','確認済みの払戻（100円あたり）'),table(['券種','組番','払戻'],[...view.payouts.map(p=>[labels[p.bet_type],p.combination.join('−'),yen(p.payout_per_100_yen)]),...view.specialPayouts.map(p=>[labels[p.bet_type],'特払い',yen(p.payout_per_100_yen)])]));}
    else panel.append(node('p','muted','券種ごとの確定払戻は確認中です。'));
    panel.append(node('p','result-refund',view.refundLabel));if(data.refund_boats?.length)panel.append(node('p','photo-note','原本に記載された返還対象艇：'+data.refund_boats.join('・')+'号艇。買い目ごとの返還額は未確定です。'));
    panel.append(node('p','photo-note','購入記録への自動精算は行っていません。未確認の券種や返還を、不的中として集計しません。'));return panel;
  }
  function renderPrediction(){
    const panel=node('section','research-prediction');panel.dataset.state=predictionState;
    panel.append(node('h3','prediction-section-title','展示前予想（展示情報未反映）'),node('p','photo-note','入力の種類を表す名称です。実際の展示実施時刻・公開時刻の前に保存したことを意味しません。'));
    const notice=node('div','prediction-notice');notice.append(node('strong','','研究用・未検証'),node('span','','購入見送り'),node('p','','固定の単純なモデルによる比較です。学習・精度検証・確率校正は未実施です。推奨買い目や推奨金額は表示しません。'));panel.append(notice);
    const state=node('div','race-update-status');state.dataset.state=predictionState;state.append(node('span','',({loading:'確認中',ready:'保存済み',unobtained:'未保存',error:'取得失敗',idle:'未取得'})[predictionState]),node('p','',predictionMessage||'このレースの保存済み研究予測を確認します。'));panel.append(state);
    if(!predictionReceipt){panel.append(renderEvaluation());return panel;}
    const snapshot=predictionReceipt.snapshot,proof=node('div','prediction-proof'),link=node('a','','公式番組表');link.href=snapshot.program_source.source_url;link.target='_blank';link.rel='noopener noreferrer';
    proof.append(link,node('span','','番組表取得 '+stampLabel(snapshot.program_source.captured_at)),node('span','','情報の時点 '+stampLabel(snapshot.as_of)),node('span','','予測生成 '+stampLabel(snapshot.generated_at)),node('span','','クラウド保存 '+stampLabel(predictionReceipt.cloud_saved_at)),node('span','state-pill ready','締切前に生成・保存'));panel.append(proof);
    const uniform=id=>id==='official-program-uniform-pl',label=id=>uniform(id)?'全艇同じ強さの比較基準':'全国勝率（得点）の単純比較';
    const choice=node('label','prediction-model-choice','比較モデル'),select=node('select');select.id='prediction-model';select.setAttribute('aria-label','研究用の比較モデル');for(const m of snapshot.models)select.append(option(label(m.model_id),m.model_id));select.value=predictionModelId;select.addEventListener('change',()=>{predictionModelId=select.value;renderDetailTab();});choice.append(select);panel.append(choice);
    const model=snapshot.models.find(m=>m.model_id===predictionModelId)||snapshot.models[0],isUniform=uniform(model.model_id),description=node('div','prediction-method');description.append(node('h3','',label(model.model_id)),node('p','',isUniform?'6艇を同じ強さと置く、比較用の均等な基準です。すべての3連単を同じ確率で扱います。':'番組表の全国勝率を、相対的な強さとして使う単純な計算です。全国勝率の得点を、そのまま1着確率として扱いません。0の得点には計算上0.01の下限を置きます。全国勝率は予測保存時の番組表の値です。'),node('small','','モデル '+model.model_id+' / バージョン '+model.model_version));panel.append(description);
    if(snapshot.models.length===1)panel.append(node('p','photo-note','全国勝率が一部未取得のため、均等な比較基準のみを表示しています。'));
    const percent=p=>p*100<0.01?'<0.01%':(p*100).toFixed(2)+'%',marginals=model.marginals.slice().sort((a,b)=>a.lane-b.lane),positions=['first','second','third','fourth','fifth','sixth'];
    panel.append(node('h3','prediction-section-title','6艇の着順確率'),table(['艇','選手・登録番号','全国勝率（得点）','1着','2着','3着','4着','5着','6着','3着以内'],marginals.map(m=>{const b=snapshot.program_boats.find(b=>b.lane===m.lane);return [m.lane,UI.text(b.name)+' / '+b.racer_registration_id,b.national_win_rate,...positions.map(p=>percent(m[p+'_probability'])),percent(m.top3_probability)];})));
    const ordered=UI.sortedPredictionTriples(model);panel.append(node('h3','prediction-section-title',isUniform?'均等な確率の表示例（艇番順）':'計算上の確率が高い組み合わせ（上位10通り）'),table(['順','3連単','研究用の確率'],ordered.slice(0,10).map((row,index)=>[index+1,row.combination.join('−'),percent(row.probability)])));
    const more=node('details','prediction-all'),heading=node('summary','','120通りの研究用確率をすべて見る'),grid=node('div','prediction-probability-grid');for(const row of ordered){const item=node('div','prediction-probability');item.append(combination(row.combination),node('strong','',percent(row.probability)));grid.append(item);}more.append(heading,grid);panel.append(more,node('p','photo-note','確率は表示時に四捨五入するため、表示値の合計には丸め差があります。これらの確率が実際の的中率と一致するかは未検証です。'));
    panel.append(renderEvaluation());return panel;
  }
  function renderExhibition(){
    const panel=node('section','exhibition-comparison');panel.dataset.state=postState;panel.dataset.raceId=postRaceId;panel.append(node('h3','prediction-section-title','展示後予想'),node('p','photo-note','公式展示タイムを取り込んだ別保存の研究予測です。映像・オリジナル展示の解析完了を意味しません。'));
    const state=node('div','race-update-status');state.dataset.state=postState;state.append(node('span','',({loading:'確認中',ready:'保存済み',unobtained:'未保存',error:'取得失敗',idle:'未確認'})[postState]),node('p','',postMessage||'選択レースの保存済み展示後予想を確認します。'));panel.append(state);
    if(!postReceipt){panel.append(node('p','muted','展示後の確率・変化量は未取得です。展示ST・風・オリジナル展示タイム・映像特徴量を使った予測は表示していません。'));return panel;}
    const s=postReceipt.snapshot,base=s.baseline_link,source=s.beforeinfo_link,percent=p=>(p*100).toFixed(2)+'%',delta=p=>(Math.abs(p)<1e-10?'0.00':(p>0?'+':'')+(p*100).toFixed(2))+'pt';
    const baselineLabel=base.model_id==='official-program-rating-pl'?'全国勝率（得点）の単純比較':'全艇同じ強さの比較基準';
    panel.append(node('p','post-comparison-baseline','比較元の展示前予想：'+baselineLabel+' ／ 保存リクエスト '+base.request_id+(predictionReceipt?.request_id!==base.request_id?'。左側の最新予想とは別の、固定された保存版に対する差です。':'。左側のモデル切替にかかわらず、この比較元に固定しています。')));
    const proof=node('div','exhibition-proof'),link=node('a','','使用した公式展示情報');link.href=source.source_url;link.target='_blank';link.rel='noopener noreferrer';proof.append(node('span','','比較元クラウド保存 '+stampLabel(base.cloud_saved_at)),link,node('span','','展示取得 '+stampLabel(source.captured_at)),node('span','','展示クラウド保存 '+stampLabel(source.cloud_saved_at)),node('span','','情報の時点 '+stampLabel(s.as_of)),node('span','','予測生成 '+stampLabel(s.generated_at)),node('span','','展示後クラウド保存 '+stampLabel(postReceipt.cloud_saved_at)));panel.append(proof);
    const method=node('div','post-model-method');method.append(node('h3','prediction-section-title','展示タイムだけを反映する研究モデル'),node('p','','展示平均との差を強さに加える固定係数1.0 / 秒の未学習モデルです。平均より速い展示タイムほど計算上の強さが増えます。対数の強さは−20〜20、得点の下限は0.01です。係数・精度・確率校正は未検証です。'),node('small','','モデル '+s.model.model_id+' / v'+s.model.model_version+' · 研究用・未検証／購入見送り'));panel.append(method);
    const features=node('div','post-features'),featureLabels={display_time:'展示タイム',preview_st:'展示ST',weather:'風・波・天候',original_exhibition:'オリジナル展示タイム（周回・直線・回り足）',exhibition_video:'映像特徴量（行き足・伸び足・ターン）'},featureText={AVAILABLE:'6艇分を使用',OBSERVED_UNUSED:'取得済み・未使用',PARTIAL_UNUSED:'一部取得・未使用',MISSING:'未取得・未使用',SOURCE_TIME_UNVERIFIED_UNUSED:'元情報の日付・時刻未確認・未使用'};
    for(const [key,label]of Object.entries(featureLabels)){const f=s.feature_status[key];features.append(node('p','',label+'：'+featureText[f.status]));}panel.append(features);
    panel.append(node('h3','prediction-section-title','使用した展示タイムと1着確率の変化'));
    const boats=table(['艇','選手・登録番号','展示（秒）','平均との差（秒）','元の強さ → 展示後','展示前1着','展示後1着','差'],s.boats.slice().sort((a,b)=>a.lane-b.lane).map(b=>{const person=postBaselineReceipt.snapshot.program_boats.find(p=>p.lane===b.lane),d=s.deltas.marginals.find(p=>p.lane===b.lane).first;return [b.lane,person.name+' / '+b.racer_registration_id,b.display_time_seconds.toFixed(2),b.display_delta_seconds.toFixed(3),b.base_strength.toFixed(3)+' → '+b.adjusted_strength.toFixed(3),percent(d.baseline_probability),percent(d.post_probability),delta(d.delta_probability)];}));boats.classList.add('post-boat-deltas');panel.append(boats);
    const ranks=node('details','post-ranks');ranks.append(node('summary','','6艇の全着順確率の変化を見る'),table(['艇',...['1着','2着','3着','4着','5着','6着','3着以内']],s.deltas.marginals.map(row=>[row.lane,...['first','second','third','fourth','fifth','sixth','top3'].map(p=>percent(row[p].baseline_probability)+' → '+percent(row[p].post_probability)+'（'+delta(row[p].delta_probability)+'）')])));panel.append(ranks);
    const ordered=s.deltas.triples.slice().sort((a,b)=>b.post_probability-a.post_probability||a.combination.join('').localeCompare(b.combination.join('')));
    const candidates=table(['研究用の組み合わせ','比較元の確率','展示後の確率','差'],ordered.slice(0,10).map(row=>[row.combination.join('−'),percent(row.baseline_probability),percent(row.post_probability),delta(row.delta_probability)]));candidates.classList.add('post-candidates');panel.append(node('h3','prediction-section-title','計算上の確率が高い研究用の組み合わせ（上位10通り）'),candidates,node('p','photo-note','研究用の候補です。推奨買い目・推奨金額ではありません。確率の変化は的中率や精度の改善を示しません。'));
    const more=node('details','post-all'),grid=node('div','post-probability-grid');more.append(node('summary','','120通りの展示前後の確率・変化量をすべて見る'));for(const row of ordered){const item=node('div','post-probability');item.append(combination(row.combination),node('span','','展示前 '+percent(row.baseline_probability)),node('strong','','展示後 '+percent(row.post_probability)),node('span','post-delta',delta(row.delta_probability)));grid.append(item);}more.append(grid);panel.append(more,node('p','photo-note','保存版 '+s.snapshot_id+'。表示は丸めているため、合計には丸め差があります。オリジナル展示・映像・ST・気象はこの版の確率に反映されていません。'));
    return panel;
  }
  function renderOriginal(){
    const panel=node('section','original-comparison');panel.dataset.state=originalState;panel.dataset.raceId=originalRaceId;const head=node('div','section-head'),action=button(originalState==='loading'?'確認中…':'オリジナル反映予想を確認','outline-button',loadOriginal);action.id='load-original-exhibition';action.disabled=originalState==='loading'||predictionState==='loading';head.append(node('h3','prediction-section-title','オリジナル展示を反映した別予想'),action);panel.append(head,node('p','photo-note','選択したレースだけを確認します。通常の展示タイムだけを使うv1モデルとは別の、未学習・未検証モデルです。'));
    const state=node('div','race-update-status');state.dataset.state=originalState;state.append(node('span','',({loading:'確認中',ready:'保存済み',unobtained:'未保存',error:'取得失敗',idle:'未確認'})[originalState]),node('p','',originalMessage||'元データと保存済みの別予想を取得するには、確認ボタンを押してください。'));panel.append(state);
    if(!originalReceipt){panel.append(node('p','muted','オリジナル展示の実測値・確率は未取得です。映像特徴量を使った予測は表示していません。'));return panel;}
    const s=originalReceipt.snapshot,base=s.baseline_link,source=s.original_link,percent=p=>(p*100).toFixed(2)+'%',delta=p=>(Math.abs(p)<1e-10?'0.00':(p>0?'+':'')+(p*100).toFixed(2))+'pt';
    const baselineLabel=base.model_id==='official-program-rating-pl'?'全国勝率（得点）の単純比較':'全艇同じ強さの比較基準';panel.append(node('p','original-pinned-baseline','固定された比較元：'+baselineLabel+' ／ 保存リクエスト '+base.request_id+'。左側のモデル切替や最新の予想で、この比較元を置き換えません。'));
    const proof=node('div','original-proof');proof.append(node('span','','比較元クラウド保存 '+stampLabel(base.cloud_saved_at)));
    for(const item of source.sources){const link=node('a','',item.component==='original'?'公式オリジナル展示の取得元':'公式の標準展示・6艇照合元');link.href=item.source_url;link.target='_blank';link.rel='noopener noreferrer';proof.append(link,node('span','','原本取得 '+stampLabel(item.captured_at)),node('small','','取得内容SHA256 '+item.source_sha256));}
    const before=node('a','','使用した公式直前情報');before.href=s.beforeinfo_link.source_url;before.target='_blank';before.rel='noopener noreferrer';proof.append(node('span','','正規化データの端末保存 '+stampLabel(source.runner_saved_at)),node('span','','正規化データのクラウド保存 '+stampLabel(source.cloud_saved_at)),before,node('span','','直前情報取得 '+stampLabel(s.beforeinfo_link.captured_at)+' ／ クラウド保存 '+stampLabel(s.beforeinfo_link.cloud_saved_at)),node('span','','情報の時点 '+stampLabel(s.as_of)),node('span','','予測生成 '+stampLabel(s.generated_at)),node('span','','別予想クラウド保存 '+stampLabel(originalReceipt.cloud_saved_at)));panel.append(proof);
    panel.append(node('p','original-limits','元の表に日付・登録番号・締切の本文証拠はありません。取得URLと、独立した出走表の6艇の氏名を完全一致で照合した資料です。測定の定義や会場間の精度・確率校正は未検証です。同じレース内の実測値の差だけを計算に使います。'));
    const method=node('div','original-method');method.append(node('h3','prediction-section-title','4種類の実測値を使う固定の研究モデル'),node('p','','各艇の「6艇平均 − 実測秒数」に、展示1.0、一周0.05、回り足0.20、直線0.20 / 秒の固定係数を掛けます。4つの寄与の合計を元の対数の強さに加え、−20〜20に制限して指数に戻す未学習モデルです。得点の下限は0.01。これらの係数は精度検証で学習した値ではありません。'),node('small','','モデル '+s.model.model_id+' / v'+s.model.model_version+' · 研究用・未検証／購入見送り'));panel.append(method);
    const st=({OBSERVED_UNUSED:'取得済み',PARTIAL_UNUSED:'一部取得',MISSING:'未取得'})[s.feature_status.preview_st.status];panel.append(node('p','original-unused','映像の検証済み特徴量：未取得・予測未使用。展示ST：'+st+'・未使用。風・波・天候：元情報の日付未確認・未使用。映像処理の完了や、艇の速さ・ターン技量の検証を示すモデルではありません。'));
    const values=table(['艇','選手・登録番号','展示（秒）','一周（秒）','回り足（秒）','直線（秒）','展示前1着','オリジナル反映1着','差'],s.boats.slice().sort((a,b)=>a.lane-b.lane).map(b=>{const person=originalBaseline.snapshot.program_boats.find(p=>p.lane===b.lane),d=s.deltas.marginals.find(p=>p.lane===b.lane).first;return [b.lane,person.name+' / '+b.racer_registration_id,b.display_time_seconds.toFixed(2),b.original_times.lap_s.toFixed(2),b.original_times.turn_s.toFixed(2),b.original_times.straight_s.toFixed(2),percent(d.baseline_probability),percent(d.post_probability),delta(d.delta_probability)];}));values.classList.add('original-boat-values');panel.append(node('h3','prediction-section-title','6艇・24個の使用した実測値と1着確率'),values);
    const contribution=table(['艇','展示の寄与','一周の寄与','回り足の寄与','直線の寄与','対数強さの増分合計','元の強さ → 反映後'],s.boats.map(b=>[b.lane,...['display_time_s','lap_s','turn_s','straight_s'].map(key=>{const c=b.contributions[key];return c.delta_seconds.toFixed(3)+'秒 × '+c.coefficient_per_second+' = '+c.log_strength_contribution.toFixed(6);}),b.total_log_strength_delta.toFixed(6),b.base_strength.toFixed(3)+' → '+b.adjusted_strength.toFixed(3)]));contribution.classList.add('original-contributions');panel.append(node('h3','prediction-section-title','計算に使った4つの寄与（対数の強さ）'),contribution);
    const ranks=node('details','original-ranks');ranks.append(node('summary','','6艇の全着順確率の変化を見る'),table(['艇','1着','2着','3着','4着','5着','6着','3着以内'],s.deltas.marginals.map(row=>[row.lane,...['first','second','third','fourth','fifth','sixth','top3'].map(rank=>percent(row[rank].baseline_probability)+' → '+percent(row[rank].post_probability)+'（'+delta(row[rank].delta_probability)+'）')])));panel.append(ranks);
    const ordered=s.deltas.triples.slice().sort((a,b)=>b.post_probability-a.post_probability||a.combination.join('').localeCompare(b.combination.join(''))),top=table(['研究用の組み合わせ','固定比較元','オリジナル反映','差'],ordered.slice(0,10).map(row=>[row.combination.join('−'),percent(row.baseline_probability),percent(row.post_probability),delta(row.delta_probability)]));panel.append(node('h3','prediction-section-title','計算上の確率が高い研究用の組み合わせ'),top,node('p','photo-note','推奨買い目・推奨金額ではありません。確率の変化は精度や回収率の改善を示しません。'));
    const more=node('details','original-all'),grid=node('div','original-probability-grid');more.append(node('summary','','120通りの固定比較元・オリジナル反映確率と差を見る'));for(const row of ordered){const item=node('div','original-probability');item.append(combination(row.combination),node('span','','比較元 '+percent(row.baseline_probability)),node('strong','','オリジナル反映 '+percent(row.post_probability)),node('span','',delta(row.delta_probability)));grid.append(item);}more.append(grid);panel.append(more,node('p','photo-note','保存版 '+s.snapshot_id+' ／ 正規化入力の保存版 '+source.snapshot_id+'。表示の丸めによる合計差があります。'));
    return panel;
  }
  function renderEvaluation(){
    const panel=node('section','research-evaluation');panel.dataset.state=evaluationState;panel.dataset.raceId=evaluationRaceId;panel.append(node('h3','prediction-section-title','公式結果との研究用の照合'));
    if(!evaluation){const state=node('div','race-update-status');state.dataset.state=evaluationState;state.append(node('span','',({loading:'確認中',error:'取得失敗',unobtained:'未取得',idle:'未取得'})[evaluationState]),node('p','',evaluationMessage||'保存済みの予測を確認したあと、公式結果と照合します。'));panel.append(state);return panel;}
    const status=evaluation.status,labels={PREDICTION_NOT_SAVED:'締切前の予測が未保存',RESULT_NOT_OBTAINED:'公式結果が未取得',RESULT_PENDING:'公式着順が未確定',RESULT_UNSUPPORTED:'今回の評価対象外',EVALUATED:'公式着順と照合済み'},descriptions={PREDICTION_NOT_SAVED:'締切前にクラウドへ保存された予測がないため、比較指標は計算しません。',RESULT_NOT_OBTAINED:'公式結果を取得できていないため、比較指標は未取得です。',RESULT_PENDING:'着順が確定するまで、比較指標は未確定です。',RESULT_UNSUPPORTED:({OFFICIAL_RESULT_STATUS_UNSUPPORTED:'中止・延期・同着・特払いなど、通常の一意の着順を比較できない結果です。',OFFICIAL_REFUND_OUTCOME_UNSUPPORTED:'返還を伴う結果のため、この比較から除外しています。',OFFICIAL_TOP3_NOT_UNIQUE:'上位3艇の一意の着順を確認できないため、この比較から除外しています。'})[evaluation.exclusion_reason],EVALUATED:'同じレース・同じ情報時点の保存済み予測を、公式の上位3艇と比較しています。'};
    const state=node('div','evaluation-status');state.append(node('span','state-pill '+(status==='EVALUATED'?'ready':'unobtained'),labels[status]),node('p','muted',descriptions[status]));panel.append(state);
    if(status==='EVALUATED'){
      panel.append(node('p','evaluation-sample','共通1レース（N=1）・各モデル120通りの3連単'),node('p','evaluation-caution','標本数が小さいため、モデルの優劣・精度・確率校正は未検証です。この1レースから採用モデルや購入判断を決めません。'));
      const scores=table(['比較モデル','Brierスコア','対数損失','確定した3連単への予測確率'],evaluation.models.map(m=>[(m.model_id==='official-program-uniform-pl'?'全艇同じ強さの比較基準':'全国勝率（得点）の単純比較')+' / v'+m.model_version,m.multiclass_brier.toFixed(6),m.log_loss.toFixed(6),(m.winner_probability*100<0.01?'<0.01':(m.winner_probability*100).toFixed(2))+'%']));scores.classList.add('evaluation-scores');panel.append(scores,node('p','photo-note','Brierスコアは120通りの確率と実際の着順との差の二乗和、対数損失は確定した3連単に付けた確率から求めます。どちらも小さいほど、この結果に対する確率のずれが小さい指標です。的中率や品質の等級ではありません。'));
    }
    const result=evaluation.result_proof;
    if(result){
      const outcome=node('div','evaluation-outcome');if(result.finish_confirmed&&result.top3){outcome.append(node('strong','','公式の上位3艇'),combination(result.top3));}const disposition=({cancelled:'レース中止',no_contest:'競走不成立',postponed:'レース延期'})[result.status];outcome.append(node('span','',disposition||(result.finish_confirmed?'着順確定':'着順は未確定')),node('span','',result.financial_confirmed?'払戻・返還も確認済み':'払戻・返還は確認中'));panel.append(outcome);
      const proof=node('div','prediction-proof evaluation-result-proof'),link=node('a','','公式結果');link.href=result.source_url;link.target='_blank';link.rel='noopener noreferrer';proof.append(link,node('span','','結果取得 '+stampLabel(result.captured_at)),node('span','','クラウド保存 '+stampLabel(result.cloud_saved_at)));panel.append(proof);
    }
    const prediction=evaluation.prediction_proof;if(prediction)panel.append(node('p','photo-note evaluation-prediction-proof','評価対象の予測：情報の時点 '+stampLabel(prediction.as_of)+' ／ 生成 '+stampLabel(prediction.generated_at)+' ／ クラウド保存 '+stampLabel(prediction.cloud_saved_at)));
    panel.append(node('p','photo-note','評価確認 '+stampLabel(evaluation.as_of)+'。研究用・未検証／購入見送り。'));return panel;
  }
  function renderDetailTab(){
    const race=current(),target=$('detail-tab-content'),heading=node('div','detail-tab-heading'),body=node('div','detail-tab-body');const labels={overview:'レースのポイント',entries:'出走表の確認',preview:'直前情報',analysis:'取得データの分析',history:'過去レース',prediction:'AI予想',bets:'このレースの買い目',video:'映像・展示解析'};
    const predictionTab=tab==='prediction',loading=predictionTab?predictionState==='loading'||evaluationState==='loading'||postState==='loading':raceUpdatesState==='loading';
    document.querySelectorAll('[data-tab]').forEach(b=>{b.classList.toggle('active',b.dataset.tab===tab);b.setAttribute('aria-pressed',String(b.dataset.tab===tab));});heading.append(node('h2','',labels[tab]),button(loading?'確認中…':predictionTab?'研究予測を再確認':'直前情報を更新','text-button',()=>predictionTab?loadPrediction(true):loadRaceUpdates(true)));heading.lastElementChild.disabled=loading||!race;target.replaceChildren(heading,body);
    if(!race){body.append(node('p','','全レースからレースを選ぶと、取得済みの情報を確認できます。'));return;}
    if(['overview','preview','analysis','history'].includes(tab))body.append(updateStatus());
    if(tab==='overview'){body.append(node('p','',raceName(race)+'の出走表は'+race.boats.length+'艇分を取得しています。直前情報は取得・保存時刻付きで別に確認できます。'),node('p','','選手の登録番号、モーター番号、平均STを出走表で確認してください。AIによる展開評価は精度検証待ちです。'));}
    if(tab==='entries')body.append(node('p','','この下に6艇の出走メンバーと、取得済みの登録番号・モーター・ST・展示を表示しています。未取得の項目は補完しません。'));
    if(tab==='preview')body.append(renderPreview());
    if(tab==='analysis')body.append(renderOdds(),renderOfficialResult(),table(['艇','モーター番号','モーター2連対率','ボート番号'],race.boats.map(b=>[b.lane,b.motor_no,b.motor_top2_rate,b.boat_no])),node('p','','機力の格付けは未検証です。'));
    if(tab==='history')body.append(renderOfficialResult(),node('p','','選手別の過去レース履歴は未接続です。上の結果は、現在選択しているレースの取得済み情報です。'));
    if(tab==='prediction'){const phases=node('div','exhibition-phases');phases.append(renderPrediction(),renderExhibition());body.append(phases,renderOriginal(),renderNameBound());}
    if(tab==='bets'){const records=ledger.filter(r=>r.race_id===selectedId);body.append(node('p','',records.length?'このレースの手動購入記録 '+records.length+'件があります。':'このレースの購入記録はまだありません。'));body.append(button('自分の買い目を記録 →','primary',()=>showPage('picks')));}
    if(tab==='video')body.append(node('p','','解析を許可された展示映像は未取得です。行き足・伸び足・回り足・ターン特性の映像評価は、実測の特徴量と検証証拠がそろい次第表示します。'));
  }
  function syncSettings(){
    document.querySelectorAll('[data-mode]').forEach(b=>{const active=b.dataset.mode===settings.mode;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});$('longshot-home').checked=settings.longshot;
    for(const [id,key]of [['setting-day-budget','dayBudget'],['setting-race-budget','raceBudget'],['setting-loss-limit','lossLimit']])$(id).value=settings[key]||'';
    $('setting-max-bets').value=settings.maxBets;$('setting-mode').value=settings.mode;$('setting-longshot').checked=settings.longshot;$('setting-auto-refresh').checked=settings.autoRefresh;
    $('pick-race-budget').textContent=settings.raceBudget?yen(settings.raceBudget):'未設定';$('pick-day-budget').textContent=settings.dayBudget?yen(settings.dayBudget):'未設定';$('pick-mode').textContent=({hit:'的中重視',balanced:'バランス重視',return:'回収重視'})[settings.mode];$('pick-max').textContent=settings.maxBets+'点';
  }
  function renderMoney(){
    const projection=financialProjection(todayLedger()),s=projection.summary,history=financialProjection(ledger),h=history.summary,remaining=Math.max(0,settings.dayBudget-s.total_stake_yen);
    $('metric-budget').textContent=settings.dayBudget?yen(settings.dayBudget):'未設定';$('metric-spent').textContent=yen(s.total_stake_yen);$('metric-remaining').textContent=settings.dayBudget?yen(remaining):'未設定';$('metric-purchases').textContent='記録 '+s.purchase_count+'件';$('metric-roi').textContent=s.actual_roi_percent===null?'―':s.actual_roi_percent+'%';$('metric-hits').textContent=projection.effective_count?projection.hit_count+' / '+projection.effective_count:'― / 0';
    $('sidebar-budget').textContent=settings.dayBudget?yen(remaining):'未設定';$('sidebar-spent').textContent=yen(s.total_stake_yen);$('sidebar-remaining').textContent=settings.dayBudget?yen(remaining):'未設定';$('nav-pick-count').textContent=String(ledger.length);
    const budgetUsed=settings.dayBudget?Math.min(100,s.total_stake_yen/settings.dayBudget*100):0;$('budget-meter').setAttribute('stroke-dasharray',budgetUsed.toFixed(2)+' 100');
    for(const [id,key]of [['result-total-stake','total_stake_yen'],['result-effective','settled_effective_stake_yen'],['result-payout','payout_yen'],['result-net','net_profit_yen'],['result-pending','pending_stake_yen'],['result-refund','refund_yen']])$(id).textContent=yen(h[key]);
    $('result-roi').textContent=h.actual_roi_percent===null?'―':h.actual_roi_percent+'%';$('result-hit-count').textContent=history.hit_count+' / '+history.effective_count+'件（返還・特払だけの的中を除外）';
    $('settlement-status').dataset.state=settlementState;$('settlement-status').textContent=!Settlement?'公式照合の機能を読み込めませんでした。再読み込みしてください。':settlementState==='loading'?'記録済みレースの公式結果を確認中です。':settlementState==='error'?'公式結果の照合に失敗しました。該当レースの確定表示を解除しました。再確認してください。':settlementState==='ready'?'当日の公式証拠を確認しました。証拠が不足する購入記録は保留です。':'当日の出走表と公式証拠がそろうまで、購入記録は保留です。';
    $('refresh-settlement').disabled=settlementState==='loading';$('result-record-count').textContent=ledger.length+'件';renderHistory('purchase-history',todayLedger(),projection);renderHistory('results-history',ledger,history);
  }
  function renderHistory(id,records,projection){
    const container=$(id);if(!records.length){container.replaceChildren(empty('購入記録はまだありません','レースを選び、自分の買い目を記録すると、ここに表示します。'));return;}
    container.replaceChildren(...records.slice().reverse().map(record=>{
      const n=node('article','ledger-record'),header=node('div','ledger-record-header'),list=node('div','ledger-record-list'),code=record.race_id.slice(9,11),detail=projection.details.get(record.id),settled=detail?.settlement;
      header.append(node('strong','',UI.venueNames[Number(code)-1]+' '+Number(record.race_id.slice(-2))+'R'),node('small','',record.purchase_day+' · 手動記録'));for(const bet of record.bets){const item=node('span');item.append(combination(bet.combination),node('b','',yen(bet.stake_yen)));list.append(item);}
      n.dataset.settlement=settled?'settled':'pending';n.append(header,list,node('p','settlement-record-status',settled?detail.reason+' · 払戻 '+yen(settled.payout_yen)+' · 返還 '+yen(settled.refund_yen)+' · 収支 '+yen(settled.net_profit_yen):(settlementErrors.get(record.race_id)||detail?.reason||'公式結果の照合待ち')+' · 成績集計は保留です。'));
      if(detail?.report?.result_proof){const proof=detail.report.result_proof,a=node('a','','公式結果の証拠');a.href=proof.source_url;a.target='_blank';a.rel='noopener noreferrer';n.append(a,node('small','settlement-proof','取得 '+proof.captured_at+' / 保存 '+proof.cloud_saved_at+' / ID '+proof.snapshot_id));}
      const audit=settlementAudit.filter(e=>e.race_id===record.race_id);if(audit.length)n.append(node('small','settlement-proof','端末の証拠履歴 '+audit.length+'版（履歴だけでは確定しません）'));
      return n;
    }));
  }
  function purchaseGate(raceId=selectedId){
    const race=all().find(r=>r.race_id===raceId);if(!race)return {allowed:false,reason:'全レースから記録するレースを選んでください。'};
    if(!navigator.locks?.request)return {allowed:false,reason:'このブラウザでは購入記録を安全に保存できません。対応する新しいブラウザで開いてください。'};
    if(!localStateHealthy)return {allowed:false,reason:'保存済みデータを確認できないため、新しい購入記録の保存を停止しています。'};
    const stop=knownRaceStops.get(raceId);if(stop?.identity===programIdentity(race))return {allowed:false,reason:({cancelled:'公式情報でレース中止を確認したため、新規記録を停止しています。',no_contest:'公式情報で不成立を確認したため、新規記録を停止しています。',postponed:'公式情報で延期を確認したため、新規記録を停止しています。'})[stop.status]};
    if(report.date_jst!==today())return {allowed:false,reason:'当日のレース以外は、新規記録を停止しています。'};
    if(report.redistribution_authorized!==true)return {allowed:false,reason:'配信許可を確認できない検証データでは、購入記録を保存できません。'};
    if(!settings.dayBudget||!settings.raceBudget||!settings.lossLimit)return {allowed:false,reason:'設定で1日・1レース予算と損失上限を保存してください。'};
    return UI.purchaseAvailability(race,report.date_jst);
  }
  function renderDraft(){
    const rows=draft(),gate=purchaseGate();$('pick-race-title').textContent=raceName(current());$('purchase-availability').textContent=gate.reason;$('add-bet').disabled=!gate.allowed;
    let checked;try{checked=Money.validate_purchase(rows,limits());const recorded=ledger.filter(r=>r.race_id===selectedId).flatMap(r=>r.bets);const cumulative=Money.validate_purchase([...recorded,...rows],limits());checked={...checked,remaining_budget_yen:cumulative.remaining_budget_yen};}catch(error){checked={total_stake_yen:rows.reduce((s,r)=>s+r.stake_yen,0),remaining_budget_yen:0,allocation_percent:[]};if(rows.length)setMessage('bet-message','設定上限を超えています。買い目を減らすか予算を確認してください。',true);}
    $('draft-bets').replaceChildren(...rows.map((bet,index)=>{const n=node('article','draft-bet');n.append(combination(bet.combination),node('strong','',yen(bet.stake_yen)),node('small','',checked.allocation_percent[index]?checked.allocation_percent[index]+'%':'―'),button('×','remove-bet',()=>{drafts.set(selectedId,rows.filter((_,i)=>i!==index));setMessage('bet-message','買い目を削除しました。');renderDraft();}));n.lastElementChild.setAttribute('aria-label',bet.combination.join('-')+'を削除');return n;}));
    $('draft-total').textContent=yen(checked.total_stake_yen);$('draft-remaining').textContent=settings.raceBudget?yen(checked.remaining_budget_yen):'未設定';$('save-purchase').disabled=savingPurchase||!gate.allowed||!rows.length||checked.total_stake_yen>settings.raceBudget;
  }
  function moneyError(error){
    const m=String(error.message);if(/duplicate/.test(m))return '同じ買い目が候補または購入記録にあります。重複は記録できません。';if(/distinct|combination/.test(m))return '1〜6の異なる艇番を選択してください。';if(/maximum number|cumulative race/.test(m))return '1レースの買い目点数または予算の上限を超えています。';if(/budget|limit/.test(m))return 'レース予算・1日予算・損失上限を超えるため記録できません。';if(/100-yen|stake/.test(m))return '金額は100円以上、100円単位の整数で入力してください。';return '入力内容を確認してください：'+m;
  }
  function addBet(event){event.preventDefault();const gate=purchaseGate();if(!gate.allowed){setMessage('bet-message',gate.reason,true);return;}const row={race_id:selectedId,bet_type:'trifecta',combination:['bet-first','bet-second','bet-third'].map(id=>Number($(id).value)),stake_yen:Number($('bet-amount').value)};
    try{const checked=Money.validate_purchase([...draft(),row],limits());const testRecord={id:'check',race_id:selectedId,purchased_at:new Date().toISOString(),bets:checked.bets};Money.append_purchase(ledger,testRecord,limits());drafts.set(selectedId,checked.bets);setMessage('bet-message','未購入の買い目に追加しました。');renderDraft();}catch(error){setMessage('bet-message',moneyError(error),true);}
  }
  async function savePurchase(){if(savingPurchase)return;const gate=purchaseGate();if(!gate.allowed){setMessage('bet-message',gate.reason,true);renderDraft();return;}if(!draft().length)return;
    const raceId=selectedId,bets=structuredClone(draft()),identity=programIdentity(current());savingPurchase=true;renderDraft();
    try{await editLocalState(()=>{
      if(selectedId!==raceId||!current()||programIdentity(current())!==identity)throw new Error('選択レースまたは出走表が変わりました。内容を再確認してください。');
      const latestGate=purchaseGate(raceId);if(!latestGate.allowed)throw new Error(latestGate.reason);
      const next=Money.append_purchase(ledger,{id:crypto.randomUUID(),race_id:raceId,purchased_at:new Date().toISOString(),bets},limits());
      if(!persist(LEDGER_KEY,next))throw new Error('保存に失敗しました。購入記録は追加していません。');ledger=next;
    },true);drafts.delete(raceId);setMessage('bet-message','手動の購入記録を保存しました。投票は行っていません。');toast('購入記録をこの端末に保存しました。');}
    catch(error){setMessage('bet-message',error instanceof Money.MoneyError?moneyError(error):error.message,true);}
    finally{savingPurchase=false;refreshLocalViews();loadSettlements();}
  }
  function exportLedger(){const data=JSON.stringify({schema:'raceai.manual-ledger.v1',exported_at:new Date().toISOString(),records:ledger},null,2);const url=URL.createObjectURL(new Blob([data],{type:'application/json'})),a=node('a');a.href=url;a.download='raceai-purchases-'+today()+'.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function renderResearch(){
    const boats=all().flatMap(r=>r.boats),fields=[['選手・登録番号','racer_registration_id'],['モーター番号','motor_no'],['平均ST','average_st'],['展示タイム','display_time'],['展示ST','preview_st'],['展示進入','preview_course']];
    $('data-quality').replaceChildren(...fields.map(([label,key])=>{const count=boats.filter(b=>b[key]!=null&&b[key]!=='').length,n=node('article','quality-item'),track=node('div','quality-track');n.dataset.level=!count?'empty':count===boats.length?'complete':'partial';n.append(node('span','',label),node('strong','',report?count+' / '+boats.length:'未取得'),node('small','',report?'取得艇数 / 収録艇数':'出走表の到着待ち'));track.append(node('i'));n.append(track);return n;}));
  }
  function renderSource(manual=false){
    $('source-state').textContent=report?(manual?'検証用ファイル':report.test_data?'合成テストデータ':/^(www1\.mbrace\.or\.jp|www\.boatrace\.jp|www\.boatrace-tokuyama\.jp)$/.test(new URL(report.source_url).hostname)?'公式番組表・開催一覧':'出走データを取得済み'):'データ未取得';$('source-date').textContent=report?.date_jst||'未取得';$('source-time').textContent=report?.first_observed_at?new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date(report.first_observed_at))+' JST':'未取得';$('source-origin').replaceChildren();
    if(report){const a=node('a','',new URL(report.source_url).hostname);a.href=report.source_url;a.target='_blank';a.rel='noopener noreferrer';a.title=report.source_url;$('source-origin').append(a);}else $('source-origin').textContent='未取得';
  }
  function renderAll(){renderHome();renderRaces();renderDetail();renderMoney();renderDraft();renderResearch();}
  function clearReport(){clearRaceUpdates();clearSettlements();phaseInventory.clear();report=null;selectedId='';refreshRaceSelect();renderSource();renderAll();}
  function showReport(data,manual=false){
    const previous=current()?programIdentity(current()):null,previousResearch=current()?researchIdentity(current()):null;clearSettlements();report=data;const requested=UI.parseRoute(location.hash).raceId;selectedId=all().some(r=>r.race_id===(requested||selectedId))?(requested||selectedId):all()[0]?.race_id||'';if(!current()||programIdentity(current())!==previous)clearRaceUpdates();else if(researchIdentity(current())!==previousResearch)clearPrediction();refreshRaceSelect();renderSource(manual);renderAll();loadSettlements();if(page==='detail'){loadRaceUpdates(true);if(tab==='prediction')loadPrediction(true);}
  }
  async function loadAuthorizedDayFeed(){
    const date=$('race-date').value;if(date!==today()){requestSerial++;controller?.abort();status('historical','履歴の配信は未接続です。今日の日付を選ぶと当日データを取得します。');clearReport();return;}
    controller?.abort();clearNameBound();clearExhibition();clearOriginal();phaseInventory.clear();clearSettlements();renderMoney();if(tab==='prediction')renderDetailTab();controller=new AbortController();const requestController=controller,serial=++requestSerial;status('loading','許可を確認した当日データを自動で読み込みます。');renderRaces();const timeout=setTimeout(()=>requestController.abort(),10000);
    try{
      const response=await fetch("./api/today", {cache:"no-store", credentials:"same-origin",signal:requestController.signal});
      const body=await response.text();if(serial!==requestSerial)return;if(body.length>6_000_000)throw new Error('データが大きすぎます。');let raw;try{raw=JSON.parse(body);}catch{if(response.ok)throw new Error('配信データの形式を確認できません。');}
      if(response.status===404||response.status===503){const failed=['FEED_STORE_UNAVAILABLE','FEED_TOO_LARGE','FEED_STALE_OR_UNAPPROVED','FEED_INVALID'].includes(raw?.error);status(failed?'error':'unobtained',failed?'配信元の取得・検証に失敗しました。時間をおいて更新してください。':'本日の配信データは準備中です。開催なしとは区別して表示しています。');clearReport();return;}
      if(!response.ok)throw new Error('配信APIから HTTP '+response.status+' が返りました。');
      const checked=UI.validateReport(raw,{automatic:true,today:today()});if(serial!==requestSerial)return;
      status(checked.status==='NO_EVENT'?'no-event':'ready',checked.test_data?'合成テストデータです。実レース情報ではありません。':checked.status==='NO_EVENT'?'許可された開催情報で、本日の開催なしを確認しました。':'出典と取得時刻を確認できます。AI予想の精度検証は進行中です。');showReport(checked);setMessage('file-message','本日のデータを自動読込しました。');
    }catch(error){if(serial!==requestSerial)return;status('error',error.name==='AbortError'?'取得がタイムアウトしました。更新ボタンから再確認できます。':'自動取得を利用できません：'+error.message);clearReport();setMessage('file-message',feedMessage,true);}
    finally{clearTimeout(timeout);if(serial===requestSerial){$('refresh-feed').disabled=false;$('refresh-feed').classList.remove('loading');}}
  }
  async function saveSettings(event){event.preventDefault();try{
    const next={...settings,dayBudget:Number($('setting-day-budget').value),raceBudget:Number($('setting-race-budget').value),lossLimit:Number($('setting-loss-limit').value),maxBets:Number($('setting-max-bets').value),mode:$('setting-mode').value,longshot:$('setting-longshot').checked,autoRefresh:$('setting-auto-refresh').checked};
    for(const key of ['dayBudget','raceBudget','lossLimit'])if(!Number.isSafeInteger(next[key])||next[key]<0||next[key]>10000000||next[key]%100)throw new Error('予算と損失上限は0〜10,000,000円の100円単位で入力してください。');
    if(next.raceBudget>next.dayBudget||next.lossLimit>next.dayBudget)throw new Error('1レース予算と損失上限は、1日予算以下に設定してください。');
    Money.validate_purchase([],{budget_yen:next.raceBudget,day_budget_yen:next.dayBudget,loss_limit_yen:next.lossLimit,max_bets:next.maxBets});
    await editLocalState(()=>{if(summary(todayLedger()).total_stake_yen>next.dayBudget)throw new Error('1日予算は、本日の記録済み購入額以上に設定してください。');if(!persist(SETTINGS_KEY,next))throw new Error('ブラウザに設定を保存できませんでした。');settings=next;});refreshLocalViews();setMessage('settings-message','設定をこのブラウザに保存しました。');toast('設定を保存しました。');
  }catch(error){setMessage('settings-message',error.message,true);}}
  document.querySelectorAll('[data-page],[data-goto]').forEach(b=>b.addEventListener('click',()=>showPage(b.dataset.page||b.dataset.goto)));
  document.querySelectorAll('[data-sport]').forEach(b=>b.addEventListener('click',()=>pickSport(b.dataset.sport)));$('return-boat').addEventListener('click',()=>pickSport('boat'));
  document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>updatePreferences({mode:b.dataset.mode})));$('longshot-home').addEventListener('change',()=>updatePreferences({longshot:$('longshot-home').checked}));
  document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{tab=b.dataset.tab;renderDetailTab();if(tab==='prediction')loadPrediction();}));$('detail-to-picks').addEventListener('click',()=>showPage('picks'));
  $('global-search').addEventListener('input',()=>{showPage('races');renderRaces();});for(const id of ['venue-select','race-number-filter','race-sort'])$(id).addEventListener('change',renderRaces);$('race-select').addEventListener('change',()=>{selectRace($('race-select').value);showPage('detail');});
  $('clear-filters').addEventListener('click',()=>{$('global-search').value='';$('venue-select').value='';$('race-number-filter').value='';$('race-sort').value='venue';renderRaces();});
  $('race-date').value=today();$('race-date').addEventListener('change',loadAuthorizedDayFeed);$('refresh-feed').addEventListener('click',loadAuthorizedDayFeed);
  for(let i=1;i<=12;i++)$('race-number-filter').append(option(i+'R',String(i)));UI.venueNames.forEach((name,i)=>$('venue-select').append(option(name,String(i+1).padStart(2,'0'))));
  ['bet-first','bet-second','bet-third'].forEach((id,i)=>{for(let lane=1;lane<=6;lane++)$(id).append(option(String(lane),String(lane)));$(id).value=String(i+1);});
  $('bet-form').addEventListener('submit',addBet);$('save-purchase').addEventListener('click',savePurchase);$('settings-form').addEventListener('submit',saveSettings);$('export-ledger').addEventListener('click',exportLedger);$('export-ledger-settings').addEventListener('click',exportLedger);
  $('refresh-settlement').addEventListener('click',loadSettlements);
  $('notifications').addEventListener('click',()=>toast($('feed-status-title').textContent+'。'+feedMessage));$('open-debug-import').addEventListener('click',()=>$('debug-import').hidden=false);
  $('race-file').addEventListener('change',async event=>{const file=event.target.files?.[0];if(!file)return;requestSerial++;controller?.abort();try{if(file.size>6_000_000)throw new Error('6MBを超えるファイルは読み取れません。');if(!/\.json$/i.test(file.name))throw new Error('JSONファイルを選択してください。');const content=await file.text();const data=UI.validateReport(JSON.parse(content));if(data.date_jst!==today())throw new Error('対象日が本日ではありません。過去データを当日として表示できません。');$('race-date').value=data.date_jst;status('manual','端末内の検証データです。原本の独立検証・配信許可の証明とは区別します。');showReport(data,true);setMessage('file-message','端末内で読み込みました。サーバーへ送信していません。');}catch(error){status('error','検証用JSONの読み込みを停止しました：'+error.message);clearReport();setMessage('file-message',error.message,true);}finally{$('refresh-feed').disabled=false;$('refresh-feed').classList.remove('loading');}});
  window.addEventListener('hashchange',()=>{const route=UI.parseRoute(location.hash);if(route.raceId)selectRace(route.raceId);showPage(route.page,false);});
  window.addEventListener('storage',event=>{if(event.storageArea!==localStorage||![null,SETTINGS_KEY,LEDGER_KEY,AUDIT_KEY].includes(event.key))return;
    if(event.key===AUDIT_KEY){try{const value=JSON.parse(localStorage.getItem(AUDIT_KEY)||'[]');Settlement?.appendAudit(value,{result_proof:null},'');settlementAudit=value;renderMoney();}catch{toast('別のタブの照合履歴を確認できません。',true);}return;}
    clearSettlements();try{applyLocalState(readLocalState());refreshLocalViews();loadSettlements();}catch{localStateHealthy=false;renderMoney();renderDraft();toast('別のタブの保存データを確認できないため、新規記録を停止しました。',true);}});
  let lastDay=today();function checkDay(){const day=today();if(day!==lastDay){lastDay=day;$('race-date').value=day;drafts.clear();knownRaceStops.clear();clearReport();loadAuthorizedDayFeed();renderMoney();}else if(page==='picks')renderDraft();}
  setInterval(checkDay,30000);setInterval(()=>{if(settings.autoRefresh&&document.visibilityState==='visible'&&$('race-date').value===today())loadAuthorizedDayFeed();},180000);
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'){checkDay();if(settings.autoRefresh&&$('race-date').value===today())loadAuthorizedDayFeed();}});
  restore();syncSettings();renderAll();const route=UI.parseRoute(location.hash);showPage(route.page,false);if(!storageAvailable)setMessage('settings-message','保存済みデータを読み込めませんでした。ブラウザの保存設定を確認してください。',true);loadAuthorizedDayFeed();
})();
