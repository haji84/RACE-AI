"use strict";
(() => {
  const M=globalThis.RaceAuditModel;
  const $=id=>document.getElementById(id);
  const el=(tag,cls,txt)=>{
    const n=document.createElement(tag);if(cls)n.className=cls;
    if(txt!==undefined&&txt!==null)n.textContent=String(txt);
    return n;
  };
  const append=(parent,...nodes)=>{nodes.forEach(n=>parent.append(n));return parent;};
  const timestamp=t=>t&&Number.isFinite(Date.parse(t))?
    new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(t)):"未取得";
  const yen=v=>Number.isSafeInteger(v)?v.toLocaleString("ja-JP")+"円":"未取得";
  const link=url=>{try{const a=new URL(url);return a.protocol==="https:"?a.href:null;}catch{return null;}};
  const tone={HIT:["的中（申告値）","hit"],MISS:["不的中","miss"],NO_FORECAST:["未予想","unverified"],
    PENDING:["結果待ち","pending"],PREDICTION_UNVERIFIED:["保存証拠不足","unverified"],
    NOT_OFFERED:["3連単非発売","neutral"],VOID:["不成立・照合不可","neutral"]};
  const state={sport:"all",period:"today",day:M.jstToday(),outcome:"all",sort:"latest",query:"",visible:80,automatic:true};
  let data=null, lastLoaded=null;
  function stateTabs(){
    for(const b of document.querySelectorAll("[data-sport]")){
      const selected=b.dataset.sport===state.sport;
      b.classList.toggle("active",selected);b.setAttribute("aria-selected",String(selected));
    }
    for(const b of document.querySelectorAll("[data-period]")){
      const selected=b.dataset.period===state.period;
      b.classList.toggle("active",selected);b.setAttribute("aria-pressed",String(selected));
    }
    for(const b of document.querySelectorAll("[data-state]")){
      const selected=b.dataset.state===state.outcome;
      b.classList.toggle("active",selected);b.setAttribute("aria-pressed",String(selected));
    }
    $("selected-date").value=state.day;
    $("sort-order").value=state.sort;
  }
  function statusBadge(r){
    const [name,css]=tone[M.outcome(r)]||["未確認","neutral"];
    return el("span","pill "+css,name);
  }
  function noteText(r){
    if(!r.prediction)return r.no_forecast_reason||"予想の保存記録なし。";
    if(!M.eligibleFreeze(r))return "締切前保存・外部受領証拠・オッズ分離の検査を通過できません。正式的中に加算しません。";
    if(!r.result||r.result.status==="pending")return "予想記録あり。公式確定結果を確認できていません。";
    if(r.offering_status!=="TRIFECTA_OFFERED")return "3連単の発売または成立条件が確認できません。";
    return "";
  }
  function proofLink(url,label){
    const target=link(url);
    if(!target)return null;
    const a=el("a","proof-link",label+" ↗");
    a.href=target;a.target="_blank";a.rel="noopener noreferrer";
    return a;
  }
  function chips(combo,winning=false){
    return el("span","ticket"+(winning?" won":""),M.ticketKey(combo));
  }
  function card(r){
    const card=el("article","race"),header=el("div","race-summary");
    const left=el("div"),right=el("div","cutoff");
    append(left,el("span","venue",M.displaySport[r.sport]+" ・ "+(M.raceDay(r)||"開催日未確認")),
      el("h3","",r.venue+" "+r.race_no+"R"),statusBadge(r));
    append(right,el("span","","投票締切（記録値）"),el("b","",timestamp(r.cutoff_at)));
    append(header,left,right);card.append(header);
    const oddsLink=el("a","full-odds-link","全3連単オッズを見る（AI予想8点以外も） →");
    oddsLink.href="./full-odds.html?race_id="+encodeURIComponent(r.race_id);
    oddsLink.title="同じサイト内の全組合せオッズ画面。実データが未配信なら未取得と表示します。";
    card.append(oddsLink);
    const split=el("div","race-main"),forecast=el("section","side forecast"),result=el("section","side result");
    forecast.append(el("h4","","AI予想 ・ 最大8点"));
    if(!r.prediction)forecast.append(el("p","empty-label","未予想（NO_FORECAST）"));
    else{
      const tickets=el("div","ticket-list");
      const winning=r.result?.status==="final"?r.result.winning_combinations.map(M.ticketKey):[];
      r.prediction.ordered_top8.forEach((t,i)=>{
        const item=el("span","ticket-wrap");
        append(item,el("small","rank",String(i+1)),chips(t,winning.includes(M.ticketKey(t))));
        tickets.append(item);
      });
      forecast.append(tickets);
    }
    result.append(el("h4","","公式3連単の結果"));
    if(r.result?.status==="final"){
      const winner=r.result.winning_combinations.map(M.ticketKey).join(" / ");
      result.append(el("div","winner",winner),el("span","subnote","確定結果（読込データ）"));
      if(r.result.payout_yen_per_100!=null)
        result.append(el("p","payout","公式100円当たり "+yen(r.result.payout_yen_per_100)));
    }else result.append(el("p","empty-label",
      r.result?.status==="void"?"不成立（読込データ）":r.result?.status==="pending"?"確定待ち":r.result?.status==="unsupported"?"照合不可":"公式結果 未取得"));
    split.append(forecast,result);card.append(split);

    if(Array.isArray(r.comparison_predictions)&&r.comparison_predictions.length){
      const panel=el("section","side comparison-panel");
      panel.append(el("h4","","別モデルの予想（正式予想と区別）"));
      for(const p of r.comparison_predictions){
        const row=el("div","comparison-row"),name=el("strong","",p.model_id+" / "+p.model_version);
        const verified=M.eligiblePrediction(r,p),hit=M.scorePrediction(r,p);
        const stateLabel=hit===null?"結果待ち":!verified?"締切前証拠不足":hit?"的中（読込値）":"不的中（読込値）";
        row.append(name,el("div","subnote",stateLabel));
        const tickets=el("div","ticket-list");
        const wins=r.result?.status==="final"?r.result.winning_combinations.map(M.ticketKey):[];
        for(let i=0;i<p.ordered_top8.length;i++){
          const t=p.ordered_top8[i],chip=el("span","ticket-wrap");
          chip.append(el("small","rank",String(i+1)));
          chip.append(chips(t,verified&&wins.includes(M.ticketKey(t))));
          tickets.append(chip);
        }
        row.append(tickets);
        panel.append(row);
      }
      card.append(panel);
    }

    if(r.actual_purchase?.confirmed===true){
      const a=r.actual_purchase,net=a.payout_yen+a.refund_yen-a.stake_yen;
      card.append(el("div","purchase-line",
        "実購入の申告 "+yen(a.stake_yen)+" ・ 払戻 "+yen(a.payout_yen)+" ・ 返還 "+yen(a.refund_yen)+" ・ 差引 "+(net>=0?"+":"")+yen(net)));
    }else card.append(el("div","purchase-line muted","実購入：記録なし（予想＝購入ではありません）"));
    const reason=noteText(r);
    if(reason)card.append(el("p","reason",reason));
    const detail=el("details","race-evidence");
    detail.append(el("summary","","予想根拠・締切前保存の証拠・結果履歴を見る"));
    const info=el("dl","details");
    const fields=[
      ["レースの状態",r.race_status||"未確認"],["3連単発売",r.offering_status],
      ["予想モデル",r.prediction?.model_id||r.prediction?.model_version||"未取得"],
      ["モデル版",r.prediction?.model_version||"未取得"],
      ["予想生成日時",timestamp(r.prediction?.generated_at)],
      ["実保存完了日時（申告）",timestamp(r.prediction?.persisted_at)],
      ["外部保存レシート",r.prediction?.external_receipt_verified===true?"検証済みと申告（独立検査未完了）":"未検証"],
      ["入力SHA-256",r.prediction?.input_sha256||"未取得"],
      ["予想SHA-256",r.prediction?.prediction_sha256||"未取得"],
      ["予想時点の根拠",r.prediction?.rationale||"未取得"],
      ["公式結果確認日時",timestamp(r.result?.confirmed_at)]
    ];
    for(const [k,v] of fields)info.append(append(el("div"),el("dt","",k),el("dd","",v)));
    detail.append(info);
    const evidence=proofLink(r.prediction?.evidence_url||r.evidence_url,"出典・予想証拠");
    if(evidence)detail.append(evidence);
    const history=el("section","revision-history");
    history.append(el("h4","","結果の改訂履歴"));
    if(Array.isArray(r.result_revisions)&&r.result_revisions.length){
      for(const rev of r.result_revisions){
        const terms=rev.status==="final"?rev.winning_combinations.map(M.ticketKey).join(" / "):rev.status;
        history.append(el("p","revision",
          "第"+rev.revision_no+"版："+terms+" ・ "+timestamp(rev.confirmed_at)+
          (rev.payout_yen_per_100!=null?" ・ 公式払戻 "+yen(rev.payout_yen_per_100):"")+
          (M.eligibleFreeze(r)&&r.offering_status==="TRIFECTA_OFFERED"&&rev.status==="final"?
            (M.score({...r,result:rev})?" ・ この版では的中":" ・ この版では不的中"):"")));
      }
    }else history.append(el("p","muted small","改訂履歴は未取得（改訂なしとの断定ではありません）"));
    detail.append(history);card.append(detail);
    return card;
  }
  function render(){
    stateTabs();
    const all=data?.records||[];
    const scope=all.filter(r=>(state.sport==="all"||r.sport===state.sport)&&M.inPeriod(r,state.period,state.day));
    const sum=M.summary(scope),a=sum.overall;
    $("total-races").textContent=data?a.ledger.toLocaleString("ja-JP")+"件":"未取得";
    $("frozen-count").textContent=data?a.frozenReported.toLocaleString("ja-JP")+"件":"未取得";
    $("settled-count").textContent=data?a.evaluable.toLocaleString("ja-JP")+"件":"未取得";
    $("hit-rate").textContent=a.hit8===null?"未検証":(a.hit8*100).toFixed(2)+"%";
    $("hit-count").textContent=a.hit8===null?"公式結果の母数なし":a.hits+"的中 / "+a.evaluable+"評価可能";
    $("actual-money").textContent=a.actualPurchases?
      "実購入の申告 "+a.actualPurchases+"件 ・ 支出 "+yen(a.actualStake)+" ・ 払戻 "+yen(a.actualPayout)+" ・ 差引 "+(a.actualNet>=0?"+":"")+yen(a.actualNet):
      "実購入・払戻：記録なし（仮想購入は実収支に含めない）";
    const kind=data?.dataset_status||"NOT_LOADED";
    $("data-kind").textContent=({AUDIT_ONLY:"暫定監査台帳",REAL_REPORTED:"実データ申告",SYNTHETIC_ONLY:"合成テスト専用",NOT_LOADED:"未取得"})[kind];
    $("data-notice").textContent=kind==="SYNTHETIC_ONLY"?
      "【合成デモ】表示と集計の試験用データです。的中数・払戻・98％達成の実績ではありません。":
      kind==="REAL_REPORTED"?"予想・結果はデータ提供側の申告値。保存時刻・公式出典の真正性は独立監査が必要です。":
      kind==="AUDIT_ONLY"?"暫定レース台帳です。実予想・公式結果は未取得。収録件数は全レース確認済み件数ではありません。":
      "閲覧データがありません。JSONを確認してください。";
    $("data-meta").textContent=data?"取込 "+all.length+"枠 / "+(state.automatic?"同一サイトの監査スナップショット":"読込ファイル")+" / 元データの真正性は未検証":
      "データ未取得。";
    $("coverage-note").textContent="全レース捕捉：未検証";
    const bySport=$("sport-breakdown");bySport.replaceChildren();
    for(const [sport,g] of Object.entries(sum.bySport)){
      const tr=el("tr");
      for(const v of [M.displaySport[sport],g.ledger,g.frozenReported,g.evaluable,g.hits,
        g.evaluable?(100*g.hits/g.evaluable).toFixed(2)+"%":"未検証"])tr.append(el("td","",v));
      bySport.append(tr);
    }
    const models=$("model-breakdown");models.replaceChildren();
    const groups=M.modelComparison(scope);
    if(groups.length){
      for(const g of groups.sort((a,b)=>(b.hit8??-1)-(a.hit8??-1)||a.key.localeCompare(b.key))){
        const tr=el("tr");
        for(const v of [g.model_id+" / "+M.displaySport[g.sport]+" ("+g.model_version+")",
          g.ledger,g.evaluable,g.hits,g.hit8===null?"未検証":(100*g.hit8).toFixed(2)+"%"+(g.ci95?" (95%区間 "+(100*g.ci95[0]).toFixed(1)+"–"+(100*g.ci95[1]).toFixed(1)+"%)":""),g.comparison])
          tr.append(el("td","",v));
        models.append(tr);
      }
    }else {
      const td=el("td","","比較できる実モデルの予想がまだありません。");
      td.colSpan=6;models.append(append(el("tr"),td));
    }
    const queried=M.filtered(scope,{state:state.outcome,query:state.query});
    const ordered=M.sortRaces(queried,state.sort,scope);
    $("shown-count").textContent=ordered.length+"件 / "+scope.length+"件（全台帳 "+all.length+"枠）";
    const list=$("race-list");list.replaceChildren();
    if(!scope.length){list.append(el("div","empty","選択した競技・期間のレースは未取得です。累計も確認できます。"));return;}
    if(!ordered.length){list.append(el("div","empty","条件に一致するレースはありません。状態フィルタを変更してください。"));return;}
    ordered.slice(0,state.visible).forEach(r=>list.append(card(r)));
    if(ordered.length>state.visible){
      const btn=el("button","more","さらに80件表示（残り"+(ordered.length-state.visible)+"件）");
      btn.type="button";btn.addEventListener("click",()=>{state.visible+=80;render();});
      list.append(btn);
    }
  }
  function setSport(sport){state.sport=sport;state.visible=80;render();}
  function setPeriod(period){state.period=period;state.visible=80;render();}
  function setOutcome(outcome){state.outcome=outcome;state.visible=80;render();}
  function stampLoaded(){lastLoaded=new Date();$("last-refreshed").textContent="画面のデータ確認："+timestamp(lastLoaded.toISOString())+" JST（公式の確定時刻ではありません）";}
  async function loadSeed(){
    const response=await fetch("./data/2026-10-22-forecast-audit.json",{cache:"no-store",credentials:"same-origin"});
    if(!response.ok)throw new Error("監査台帳の取得に失敗しました。");
    const parsed=M.merge([await response.json()]);
    data=parsed;state.automatic=true;stampLoaded();render();
  }
  async function importFiles(files){
    try{
      const objects=[];
      for(const file of files){if(file.size>5*1024*1024)throw new Error("5MB超のファイルは読み込めません。");objects.push(JSON.parse(await file.text()));}
      const parsed=M.merge(objects);
      data=parsed;state.automatic=false;state.visible=80;
      // Example historical files must remain navigable without pretending to be today's result.
      state.period="all";
      $("import-error").hidden=true;stampLoaded();render();
    }catch(e){$("import-error").textContent="読込失敗："+e.message;$("import-error").hidden=false;}
  }
  async function loadDemo(){
    try{
      const response=await fetch("./data/example-synthetic-forecast-audit.json",{cache:"no-store"});
      if(!response.ok)throw new Error("合成デモは未配信です。");
      data=M.merge([await response.json()]);
      state.period="all";state.sport="all";state.outcome="all";state.automatic=false;state.visible=80;
      $("import-error").hidden=true;stampLoaded();render();
    }catch(e){$("import-error").textContent="デモ読込失敗："+e.message;$("import-error").hidden=false;}
  }
  for(const b of document.querySelectorAll("[data-sport]"))b.addEventListener("click",()=>setSport(b.dataset.sport));
  for(const b of document.querySelectorAll("[data-period]"))b.addEventListener("click",()=>setPeriod(b.dataset.period));
  for(const b of document.querySelectorAll("[data-state]"))b.addEventListener("click",()=>setOutcome(b.dataset.state));
  $("selected-date").addEventListener("change",e=>{if(e.target.value){state.day=e.target.value;state.period="today";state.visible=80;render();}});
  $("sort-order").addEventListener("change",e=>{state.sort=e.target.value;state.visible=80;render();});
  $("search").addEventListener("input",e=>{state.query=e.target.value;state.visible=80;render();});
  $("load-synthetic").addEventListener("click",loadDemo);
  $("import-files").addEventListener("change",e=>{if(e.target.files.length)importFiles([...e.target.files]);});
  $("reload-feed").addEventListener("click",async()=>{try{await loadSeed();$("import-error").hidden=true;}
    catch(e){$("import-error").textContent=e.message;$("import-error").hidden=false;}});
  setInterval(()=>{if(state.automatic&&!document.hidden)loadSeed().catch(()=>{$("last-refreshed").textContent="更新失敗：前回確認 "+timestamp(lastLoaded?.toISOString())+" JST";});},90000);
  stateTabs();
  loadSeed().catch(e=>{$("import-error").textContent=e.message;$("import-error").hidden=false;render();});
})();
