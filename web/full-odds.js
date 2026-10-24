"use strict";
(() => {
  const Model=globalThis.RaceFullOdds;
  const $=id=>document.getElementById(id);
  const state={feed:null,manual:false,first:"all",order:"ticket",query:"",visible:80,lastBrowserRead:null,successCount:0,failures:0,events:[],busy:false,lastAttemptAt:0,lastSuccessfulAt:0,lastRefreshFailed:false};
  const raceId=new URLSearchParams(location.search).get("race_id");
  const validRaceId=typeof raceId==="string"&&/^[A-Za-z0-9:_-]{5,160}$/.test(raceId);
  const fmt=t=>{
    if(!t||!Number.isFinite(Date.parse(t)))return "未取得";
    return new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",year:"numeric",
      month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit",
      hour12:false}).format(new Date(t))+" JST";
  };
  const sportNames={boat:"ボート",keirin:"競輪",autorace:"オート",horse:"競馬"};
  const empty=(message)=>{
    $("odds-rows").replaceChildren();
    const tr=document.createElement("tr"),td=document.createElement("td");
    td.colSpan=4;td.textContent=message;tr.append(td);$("odds-rows").append(tr);
    $("visible-count").textContent="0件";$("show-more").hidden=true;
  };
  function options(feed){
    const current=$("first-number").value;
    $("first-number").replaceChildren();
    for(const number of ["all",...feed.participants]){
      const opt=document.createElement("option");
      opt.value=String(number);opt.textContent=number==="all"?"全番号":number+"着ではなく、1着 "+number;
      $("first-number").append(opt);
    }
    $("first-number").value=current==="all"||feed.participants.some(n=>String(n)===current)?current:"all";
    state.first=$("first-number").value;
  }
  function summary(){
    const f=state.feed;
    if(!f)return;
    $("race-name").textContent=(sportNames[f.sport]||f.sport)+" ・ "+f.venue+" "+f.race_no+"R";
    $("race-cutoff").textContent=fmt(f.cutoff_at);
    $("source-time").textContent="オッズ提供時刻（申告）："+fmt(f.source_published_at);
    $("receive-time").textContent="配信側受信時刻（申告）："+fmt(f.ingested_at);
    $("browser-read-time").textContent=(state.manual?"手元ファイルの読込：":"この画面がJSONの受信を確認：")+
      fmt(state.lastBrowserRead)+(state.manual?"":"（成功 "+state.successCount+" 回、公式の更新回数とは別）");
    $("source-kind").textContent=f.source_status==="SYNTHETIC_ONLY"?
      "データ：合成テスト用（実オッズではありません）":
      "データ：提供元の申告値（独立真正性は未検証）";
    const quoted=f.odds.filter(x=>x.status==="QUOTED").length;
    $("quote-count").textContent="全有効組番 "+f.odds.length+"件 / オッズ値取得 "+quoted+"件 / 未取得 "+(f.odds.length-quoted)+"件";
    const where=$("source-link");where.replaceChildren();
    const a=document.createElement("a");
    const safe=new URL(f.source_url);
    if(safe.protocol==="https:"){
      a.href=safe.href;a.target="_blank";a.rel="noopener noreferrer";
      a.textContent="情報提供元の参照ページ ↗";where.append(a);
    }
    const fresh=Model.freshness(f);
    if(state.lastRefreshFailed)return;
    $("feed-status").textContent=(state.manual?"手元の読込データ｜":"配信されたJSON｜")+
      fresh.label+"｜"+(f.source_status==="SYNTHETIC_ONLY"?"合成データ":"未検証の提供元申告値")+
      "。1分ごとに公式オッズが変化する保証はありません。";
    $("feed-status").classList.toggle("stale",fresh.stale);
  }
  const changeLabels={
    FIRST_READ:"初回データ受信",QUOTE_CHANGED:"オッズ値・発売状態が変化",
    SOURCE_TIME_CHANGED:"提供元更新時刻のみ変化",
    D1_RECEIPT_CHANGED:"D1受信時刻のみ変化",UNCHANGED:"同一スナップショット"
  };
  const triggerLabels={initial:"初回",timer:"自動60秒",manual:"手動",recovery:"復帰後再確認"};
  function traceRead(entry){
    state.events.push(entry);
    if(state.events.length>12)state.events.shift();
    const latest=state.events.at(-1);
    const total=state.successCount+state.failures;
    $("refresh-evidence").textContent=
      "ブラウザからの再読込 "+total+"回（成功"+state.successCount+"／失敗"+state.failures+"）"+
      "｜最新 "+(latest.ok?"成功":"失敗")+"｜モード "+(state.manual?"手元ファイル":"保護JSON受信");
    const progress=Model.safariAcceptance(state.events);
    $("refresh-progress").textContent="画面の約60秒自動受信："+Math.min(progress.confirmedIntervals,3)+
      "/3回"+(progress.passed?"（ブラウザ受信の試験PASS。上流公式更新の証明ではありません）":"");
    const history=$("refresh-history");history.replaceChildren();
    for(const ev of [...state.events].reverse().slice(0,4)){
      const li=document.createElement("li");
      li.textContent=fmt(ev.browser_at)+" / "+(triggerLabels[ev.trigger]||"不明")+" / "+(ev.ok?"JSON再読込成功":"更新失敗")+
        (ev.gap_seconds===null?" / 初回":(" / 成功間隔 "+ev.gap_seconds+"秒"))+
        (ev.ok?" / "+changeLabels[ev.change_kind]+"（変更組番 "+ev.changed_quotes+"）":"")+
        (ev.ok?" / D1受信 "+fmt(ev.ingested_at)+" / 提供元更新 "+fmt(ev.source_published_at):"");
      history.append(li);
    }
  }
  function render(){
    summary();
    if(!state.feed){empty("全オッズ配信が未接続です。実在のオッズ値は生成しません。");return;}
    const rows=Model.select(state.feed,{first:state.first,query:state.query,order:state.order});
    $("visible-count").textContent=rows.length+"件中 "+Math.min(rows.length,state.visible)+"件表示";
    const body=$("odds-rows");body.replaceChildren();
    for(const item of rows.slice(0,state.visible)){
      const tr=document.createElement("tr");
      const cols=[
        Model.key(item.ticket),
        item.status==="QUOTED"?item.decimal_odds.toLocaleString("ja-JP",{maximumFractionDigits:2})+"倍":"未取得",
        item.status==="QUOTED"?Math.floor(100*item.decimal_odds).toLocaleString("ja-JP")+"円（参考）":"未取得",
        item.status==="QUOTED"?(100/item.decimal_odds).toFixed(2)+"%（単純計算）":"未取得"
      ];
      for(const val of cols){const td=document.createElement("td");td.textContent=val;tr.append(td);}
      body.append(tr);
    }
    if(!rows.length)empty("一致する組番はありません。");
    $("show-more").hidden=rows.length<=state.visible;
    if(!$("show-more").hidden)$("show-more").textContent="さらに80件表示（残り"+(rows.length-state.visible)+"件）";
  }
  function accept(obj,manual){
    const feed=Model.parse(obj);
    if(validRaceId&&feed.race_id!==raceId)throw new Error("選択中のレースIDとオッズデータが一致しません。");
    const difference=Model.readDifference(state.feed,feed);
    const firstRace=state.feed===null||state.feed.race_id!==feed.race_id;
    state.lastRefreshFailed=false;
    state.feed=feed;state.manual=manual;
    if(firstRace)state.visible=Model.initialRowLimit(feed);
    state.lastBrowserRead=new Date().toISOString();
    if(!manual)state.successCount+=1;
    $("file-error").hidden=true;
    options(feed);render();
    return difference;
  }
  async function load(){
    if(!validRaceId){
      $("feed-status").textContent="レースを選択してから全オッズを開いてください。";
      empty("表示対象レースがありません。");
      throw new Error("表示するレースIDが不正です。");
    }
    const path="./data/odds/"+encodeURIComponent(raceId)+".json";
    const res=await fetch(path,{cache:"no-store",credentials:"same-origin"});
    if(res.redirected&&new URL(res.url).origin!==location.origin)
      throw new Error("所有者認証が切れています。Cloudflare Accessで再ログインしてください。");
    if(!res.ok)throw new Error("全オッズ配信元が未接続か、まだ配信されていません（HTTP "+res.status+"）。");
    if(!(res.headers.get("content-type")||"").toLowerCase().includes("application/json"))
      throw new Error("JSONではない応答です。所有者認証の状態を確認してください。");
    const payload=await res.json();
    return accept(payload,false);
  }
  async function refresh(trigger="manual"){
    if(state.busy)return;
    const started=Date.now();
    state.busy=true;state.lastAttemptAt=started;
    try{
      const difference=await load();
      const completed=Date.now();
      const gap=state.lastSuccessfulAt?(completed-state.lastSuccessfulAt)/1000:null;
      state.lastSuccessfulAt=completed;
      traceRead({ok:true,trigger,manual_file_mode:false,browser_at:new Date(completed).toISOString(),
        gap_seconds:gap===null?null:Number(gap.toFixed(1)),
        change_kind:difference.kind,changed_quotes:difference.changedQuotes,
        ingested_at:state.feed.ingested_at,source_published_at:state.feed.source_published_at});
    }catch(err){
      state.failures++;state.lastRefreshFailed=true;
      traceRead({ok:false,trigger,manual_file_mode:false,browser_at:new Date().toISOString(),gap_seconds:null});
      $("file-error").textContent="更新できません："+err.message;
      $("file-error").hidden=false;
      if(state.feed){
        $("feed-status").textContent="配信の更新に失敗。以前の受信オッズです。最新ではありません。";
        $("feed-status").classList.add("stale");
      }else{
        $("feed-status").textContent="実オッズ配信は未接続。架空のオッズは表示しません。";
        empty("データを確認できません。");
      }
    }finally{state.busy=false;}
  }
  $("first-number").addEventListener("change",e=>{state.first=e.target.value;state.visible=Model.initialRowLimit(state.feed);render();});
  $("order").addEventListener("change",e=>{state.order=e.target.value;state.visible=Model.initialRowLimit(state.feed);render();});
  $("ticket-search").addEventListener("input",e=>{state.query=e.target.value;state.visible=Model.initialRowLimit(state.feed);render();});
  $("show-more").addEventListener("click",()=>{state.visible+=80;render();});
  $("refresh").addEventListener("click",()=>refresh("manual"));
  $("odds-file").addEventListener("change",async e=>{
    const file=e.target.files[0];if(!file)return;
    try{
      if(file.size>2*1024*1024)throw new Error("入力ファイルは2MB以内にしてください。");
      accept(JSON.parse(await file.text()),true);
    }catch(err){$("file-error").textContent="読込を拒否しました："+err.message;$("file-error").hidden=false;}
  });
  function diagnosticText(){
    const info={schema:"RACE_AI_SAFARI_READ_RECEIPTS_V2",
      caveat:"Local browser observations only. Not a source 60s acquisition proof.",
      race_id:validRaceId?raceId:null,manual_file_mode:state.manual,
      read_successes:state.successCount,read_failures:state.failures,
      received_rows:state.feed?.odds.length??null,
      safari_auto_acceptance:Model.safariAcceptance(state.events),
      events:state.events.map(e=>({
        browser_at:e.browser_at,trigger:e.trigger,ok:e.ok,
        gap_seconds:e.gap_seconds??null,
        change_kind:e.change_kind??null,changed_quotes:e.changed_quotes??null,
        ingested_at:e.ingested_at??null,source_published_at:e.source_published_at??null
      }))};
    return JSON.stringify(info,null,2);
  }
  function revealDiagnostic(){
    $("evidence-fallback").hidden=false;
    $("evidence-text").value=diagnosticText();
    $("evidence-text").focus();
    $("evidence-text").select();
    $("evidence-text").setSelectionRange(0,$("evidence-text").value.length);
  }
  $("select-evidence").addEventListener("click",()=>{
    revealDiagnostic();
    $("copy-status").textContent="下の診断テキストを長押しして、すべて選択してコピーしてください。";
  });
  $("copy-evidence").addEventListener("click",async()=>{
    const value=diagnosticText();
    try{
      if(!navigator.clipboard?.writeText)throw new Error("clipboard not available");
      await navigator.clipboard.writeText(value);
      $("copy-status").textContent="診断結果をコピーしました。チャットに貼り付けてください。";
    }catch{
      revealDiagnostic();
      let copied=false;
      try{copied=document.execCommand?.("copy")===true;}catch{}
      $("copy-status").textContent=copied?
        "代替方法でコピーしました。チャットに貼り付けてください。":
        "自動コピーが使えません。下のテキストを長押ししてコピーしてください。";
    }
  });
  function nextRefreshLabel(){
    if(state.manual)return "手元のJSON表示中。自動再読込は停止しています。";
    if(document.hidden)return "Safariが非表示のため、自動更新が中断される場合があります。";
    if(state.busy)return "保存済みJSONを再確認中";
    if(!state.lastAttemptAt)return "初回取得待ち";
    const remaining=Math.max(0,60-Math.floor((Date.now()-state.lastAttemptAt)/1000));
    return "次の自動再読込：約"+remaining+"秒（Safariのタイマー制約により遅れる場合あり）";
  }
  setInterval(()=>{$("refresh-next").textContent=nextRefreshLabel();},1000);
  setInterval(()=>{if(state.feed)summary();},15000);
  setInterval(()=>{if(!document.hidden&&!state.manual&&validRaceId)refresh("timer");},60000);
  function refreshOnReturn(){
    if(!document.hidden&&!state.manual&&validRaceId&&!state.busy&&
      Date.now()-state.lastAttemptAt>=60000)refresh("recovery");
  }
  document.addEventListener("visibilitychange",refreshOnReturn);
  window.addEventListener("pageshow",refreshOnReturn);
  window.addEventListener("online",refreshOnReturn);
  refresh("initial");
})();
