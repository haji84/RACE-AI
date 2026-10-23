"use strict";
(() => {
  const Model=globalThis.RaceFullOdds;
  const $=id=>document.getElementById(id);
  const state={feed:null,manual:false,first:"all",order:"ticket",query:"",visible:80};
  const raceId=new URLSearchParams(location.search).get("race_id");
  const validRaceId=typeof raceId==="string"&&/^[A-Za-z0-9:_-]{5,160}$/.test(raceId);
  const fmt=t=>{
    if(!t||!Number.isFinite(Date.parse(t)))return "未取得";
    return new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",year:"numeric",
      month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",
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
    $("first-number").value=feed.participants.some(n=>String(n)===current)?current:"all";
    state.first=$("first-number").value;
  }
  function summary(){
    const f=state.feed;
    if(!f)return;
    $("race-name").textContent=(sportNames[f.sport]||f.sport)+" ・ "+f.venue+" "+f.race_no+"R";
    $("race-cutoff").textContent=fmt(f.cutoff_at);
    $("source-time").textContent="オッズ提供時刻（申告）："+fmt(f.source_published_at);
    $("receive-time").textContent="配信側受信時刻（申告）："+fmt(f.ingested_at);
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
    $("feed-status").textContent=(state.manual?"手元の読込データ｜":"配信されたJSON｜")+
      fresh.label+"｜"+(f.source_status==="SYNTHETIC_ONLY"?"合成データ":"未検証の提供元申告値")+
      "。1分ごとに公式オッズが変化する保証はありません。";
    $("feed-status").classList.toggle("stale",fresh.stale);
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
    state.feed=feed;state.manual=manual;state.visible=80;
    $("file-error").hidden=true;
    options(feed);render();
  }
  async function load(){
    if(!validRaceId){
      $("feed-status").textContent="レースを選択してから全オッズを開いてください。";
      empty("表示対象レースがありません。");
      return;
    }
    const path="./data/odds/"+encodeURIComponent(raceId)+".json";
    const res=await fetch(path,{cache:"no-store",credentials:"same-origin"});
    if(!res.ok)throw new Error("全オッズ配信元が未接続か、まだ配信されていません（HTTP "+res.status+"）。");
    const payload=await res.json();
    accept(payload,false);
  }
  async function refresh(){
    try{await load();}
    catch(err){
      $("file-error").textContent="更新できません："+err.message;
      $("file-error").hidden=false;
      if(state.feed){
        $("feed-status").textContent="配信の更新に失敗。以前の受信オッズです。最新ではありません。";
        $("feed-status").classList.add("stale");
      }else {
        $("feed-status").textContent="実オッズ配信は未接続。架空のオッズは表示しません。";
        empty("データを確認できません。");
      }
    }
  }
  $("first-number").addEventListener("change",e=>{state.first=e.target.value;state.visible=80;render();});
  $("order").addEventListener("change",e=>{state.order=e.target.value;state.visible=80;render();});
  $("ticket-search").addEventListener("input",e=>{state.query=e.target.value;state.visible=80;render();});
  $("show-more").addEventListener("click",()=>{state.visible+=80;render();});
  $("refresh").addEventListener("click",refresh);
  $("odds-file").addEventListener("change",async e=>{
    const file=e.target.files[0];if(!file)return;
    try{
      if(file.size>2*1024*1024)throw new Error("入力ファイルは2MB以内にしてください。");
      accept(JSON.parse(await file.text()),true);
    }catch(err){$("file-error").textContent="読込を拒否しました："+err.message;$("file-error").hidden=false;}
  });
  setInterval(()=>{if(state.feed)summary();},15000);
  setInterval(()=>{if(!document.hidden&&!state.manual&&validRaceId)refresh();},60000);
  refresh();
})();
