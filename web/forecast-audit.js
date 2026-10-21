"use strict";
(() => {
  const model=globalThis.RaceAuditModel;
  const $=id=>document.getElementById(id);
  const node=(tag,cl,txt)=>{
    const n=document.createElement(tag);if(cl)n.className=cl;
    if(txt!==undefined&&txt!==null)n.textContent=String(txt);return n;
  };
  const child=(parent,...children)=>{children.forEach(c=>parent.append(c));return parent;};
  const dateText=(s)=>{
    if(!s || !Number.isFinite(Date.parse(s)))return "未取得";
    return new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(s));
  };
  const escapeCutoff=r=>r.cutoff_at&&Number.isFinite(Date.parse(r.cutoff_at))?Date.parse(r.cutoff_at):Number.POSITIVE_INFINITY;
  const validLink=value=>{try{const u=new URL(value);return ["https:","http:"].includes(u.protocol)?u.href:null}catch{return null}};
  let data=null;
  let lastError=null;
  const statusLabel={FROZEN_REPORTED:"締切前保存（申告）",PREDICTION_UNVERIFIED:"予想記録・保存証拠不足",NO_FORECAST:"未予想"};
  function statePill(r) {
    const st=model.status(r);
    const hit=model.score(r);
    if(hit===true)return node("span","pill hit","的中（記録上）");
    if(hit===false)return node("span",st==="FROZEN_REPORTED"?"pill miss":"pill unverified",st==="FROZEN_REPORTED"?"不的中":"事前保存証拠不足");
    if(st==="PREDICTION_UNVERIFIED")return node("span","pill unverified","予想の証拠不足");
    if(st==="FROZEN_REPORTED")return node("span","pill pending","予想凍結・結果待ち");
    return node("span","pill unverified","未予想");
  }
  function explanation(r) {
    if(!r.prediction)return r.no_forecast_reason||"予想記録なし。詳細理由は未取得。";
    if(!model.eligibleFreeze(r))return "予想記録はありますが、外部保存証拠・オッズ非依存・締切時刻の検査を通過できません。公式的中数に加算しません。";
    if(!r.result)return "事前保存記録あり。公式確定結果を取得していません。";
    if(r.result.status==="final"&&r.offering_status!=="TRIFECTA_OFFERED")return "結果の着順はありますが、3連単発売の確認がありません。";
    return "";
  }
  function card(r) {
    const wrap=node("article","race");
    const head=node("div","race-summary"),left=node("div"),right=node("div","cutoff");
    child(left,node("span","venue",model.displaySport[r.sport]+"　"+r.race_id),node("h3","",r.venue+" "+r.race_no+"R"),statePill(r));
    child(right,node("span","","締切（記録上）"),node("b","",dateText(r.cutoff_at)));
    child(head,left,right);wrap.append(head);
    const two=node("div","race-main"),p=node("section","side"),result=node("section","side");
    p.append(node("h4","","AI予想　最大8点"));
    if(!r.prediction){p.append(node("p","empty-label","予想未取得 / NO_FORECAST"))}
    else{
      const list=node("div","ticket-list"),winners=r.result?.status==="final"?r.result.winning_combinations.map(model.ticketKey):[];
      for(const t of r.prediction.ordered_top8)list.append(node("span","ticket"+(winners.includes(model.ticketKey(t))?" won":""),model.ticketKey(t)));
      p.append(list);
    }
    result.append(node("h4","","公式結果との照合"));
    if(r.result?.status==="final"&&r.result.winning_combinations.length){
      result.append(node("div","winner",r.result.winning_combinations.map(model.ticketKey).join(" / ")));
      result.append(node("div","empty-label",r.offering_status==="TRIFECTA_OFFERED"?"確定3連単（読込データ）":"3連単発売は未確認"));
    }else result.append(node("p","empty-label",r.result?.status==="void"?"レース不成立（申告）":r.result?.status==="pending"?"公式結果確定待ち":"公式確定結果 未取得"));
    two.append(p,result);wrap.append(two);
    const facts=node("dl","details");
    const fields=[
      ["出走の状況",r.race_status||"未確認"],
      ["発売状況",({TRIFECTA_OFFERED:"3連単発売を記録",NOT_OFFERED:"3連単非発売",UNKNOWN:"3連単発売未確認"})[r.offering_status]],
      ["予想保存完了",r.prediction?dateText(r.prediction.persisted_at):"記録なし"],
      ["予想モデル",r.prediction?.model_version||"未取得"],
      ["モデル根拠",r.prediction?.rationale||"未取得"],
      ["予想SHA256",r.prediction?.prediction_sha256||"未取得"],
      ["入力SHA256",r.prediction?.input_sha256||"未取得"],
      ["結果確定発表",r.result?dateText(r.result.confirmed_at):"未取得"]
    ];
    for(const [key,value] of fields)facts.append(child(node("div"),node("dt","",key),node("dd","",value)));
    wrap.append(facts);
    const why=explanation(r);if(why)wrap.append(node("div","reason",why));
    const link=validLink(r.prediction?.evidence_url||r.evidence_url);
    if(link){const a=node("a","proof-link","出典・証拠へのリンク ↗");a.href=link;a.target="_blank";a.rel="noopener noreferrer";wrap.append(a);}
    return wrap;
  }
  function render() {
    const records=data?.records||[];
    const s=model.summary(records).overall;
    $("total-races").textContent=data?s.ledger.toLocaleString("ja-JP")+"件":"未取得";
    $("frozen-count").textContent=data?s.frozenReported.toLocaleString("ja-JP")+"件":"未取得";
    $("settled-count").textContent=data?s.evaluable.toLocaleString("ja-JP")+"件":"未取得";
    $("hit-rate").textContent=s.hit8===null?"未検証":(s.hit8*100).toFixed(2)+"%";
    $("hit-count").textContent=s.hit8===null?"評価可能レースの確定結果なし":s.hits+"的中 / "+s.evaluable+"レース（読込値）";
    const type=data?.dataset_status||"NOT_LOADED";
    $("data-kind").textContent=({AUDIT_ONLY:"暫定監査台帳",REAL_REPORTED:"実データの申告",SYNTHETIC_ONLY:"合成テスト専用",NOT_LOADED:"未取得"})[type];
    $("data-notice").textContent=type==="SYNTHETIC_ONLY"?"合成データの検証表示。実際の予想実績ではありません。":type==="REAL_REPORTED"?
      "読込データの事前予想と結果を比較中。画面内の証拠フラグとSHAの真正性は別途独立検証してください。98％達成とは判断しません。":
      "収録データは開催・レースの暫定台帳です。実予想・結果照合は未接続。322件は全レース確認済み数ではありません。";
    $("data-meta").textContent=data?records.length+"レース収録 / 出典ファイルからの申告値 / 外部の真正性は未検証":"利用可能な台帳を取得していません。";
    const query=$("search").value.trim().toLowerCase(),sport=$("sport-filter").value,st=$("status-filter").value;
    const filtered=records.filter(r=>(sport==="all"||r.sport===sport)&&
      (st==="all"||(st==="final"?r.result?.status==="final":model.status(r)===st))&&
      (!query||(r.venue+" "+r.race_no+"R "+r.race_id).toLowerCase().includes(query)));
    filtered.sort((a,b)=>escapeCutoff(a)-escapeCutoff(b)||a.sport.localeCompare(b.sport)||a.race_id.localeCompare(b.race_id));
    $("shown-count").textContent=filtered.length+"件を表示 / "+records.length+"件";
    const list=$("race-list");list.replaceChildren();
    if(!records.length){list.append(node("div","empty","データがありません。予想結果のJSONを読み込むと、レースごとに8点と確定着順を照合できます。"));return;}
    if(!filtered.length){list.append(node("div","empty","表示条件に一致するレースがありません。"));return;}
    // Keep DOM bounded on an iPhone; the full denominator still includes all records.
    for(const r of filtered.slice(0,120))list.append(card(r));
    if(filtered.length>120)list.append(node("div","empty","120件まで表示中。競技・状態・会場検索で絞り込んでください。集計には全件を使用しています。"));
  }
  async function loadFiles(files){
    $("import-error").hidden=true;lastError=null;
    try {
      const objects=[];
      for(const f of files){if(f.size>5*1024*1024)throw new Error("5MBを超えるファイルは読み込めません。");objects.push(JSON.parse(await f.text()));}
      data=model.merge(objects);render();
    }catch(e){lastError=e.message;$("import-error").textContent="読込失敗："+lastError;$("import-error").hidden=false;}
  }
  async function initial() {
    try{
      const res=await fetch("./data/2026-10-22-forecast-audit.json",{cache:"no-store",credentials:"same-origin"});
      if(!res.ok)throw new Error("台帳データは未配信");
      data=model.merge([await res.json()]);
    }catch(e){data=null;}
    render();
  }
  for(const id of ["sport-filter","status-filter","search"])$(id).addEventListener(id==="search"?"input":"change",render);
  $("import-files").addEventListener("change",e=>{if(e.target.files?.length)loadFiles([...e.target.files]);});
  initial();
})();
