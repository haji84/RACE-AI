"use strict";
(function (root, factory) {
  const audit = typeof module === "object" && module.exports ? require("./forecast-audit-model.js") : root.RaceAuditModel;
  const api = factory(audit);
  if (typeof module === "object" && module.exports) module.exports = api;
  root.RaceProductData = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (Audit) {
  const sports = ["boat", "keirin", "autorace", "horse"];
  const scopes = ["official", "research", "synthetic"];
  const stages = ["P0", "P1", "UNKNOWN"];
  const nativeAutoraceStages = ["A_PRE_TRIAL", "B_POST_TRIAL"];
  const summaryStages = [...stages.slice(0,2), ...nativeAutoraceStages, "UNKNOWN"];
  const privateCycleSchema = "RACE_AI_PRIVATE_CYCLE_VIEW_V1";
  const sha = value => typeof value === "string" && /^[a-f0-9]{64}$/i.test(value);
  const stamp = value => typeof value === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value) && validDay(value.slice(0,10)) && Number.isFinite(Date.parse(value));
  const text = value => typeof value === "string" && value.trim().length > 0;
  function fail(message) { throw new Error(message); }
  function freeze(value) {
    if (value && typeof value === "object") {
      for (const child of Object.values(value)) freeze(child);
      Object.freeze(value);
    }
    return value;
  }
  function clone(raw) {
    let encoded;
    try {
      encoded = typeof raw === "string" ? raw : JSON.stringify(raw, (_key, value) => {
        if (typeof value === "number" && !Number.isFinite(value) || ["function", "symbol", "bigint"].includes(typeof value)) fail("有限のJSONデータが必要です。");
        return value;
      });
      if (typeof encoded !== "string" || encoded.length > 64 * 1024 * 1024) fail("JSONデータが大きすぎます。");
      return JSON.parse(encoded);
    } catch (error) {
      if (/JSON/.test(error.message)) throw error;
      fail("JSONデータの形式が不正です。");
    }
  }
  function canonical(value) {
    if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
    if (value && typeof value === "object") return "{" + Object.keys(value).sort().map(k => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
    return JSON.stringify(value);
  }
  const savedEvidence = new WeakMap(),evidenceRows = new WeakSet();
  const evidenceSchema = "RACE_AI_SAVED_PREDICTION_EVIDENCE_V1";
  function valueBinding(value) {
    const scalarOrder=(a,b)=>{const x=Array.from(a),y=Array.from(b);for(let i=0;i<Math.min(x.length,y.length);i++){const n=x[i].codePointAt(0)-y[i].codePointAt(0);if(n)return n;}return x.length-y.length;};
    const typed=v=>{
      if(v===null)return ["null"];
      if(typeof v==="boolean")return ["boolean",v];
      if(typeof v==="number"){
        if(!Number.isFinite(v))fail("保存原本の数値が不正です。");
        const bytes=new Uint8Array(8);new DataView(bytes.buffer).setFloat64(0,v,false);
        return ["number",Array.from(bytes,n=>n.toString(16).padStart(2,"0")).join("")];
      }
      if(typeof v==="string")return ["string",v];
      if(Array.isArray(v))return ["array",v.map(typed)];
      if(v&&typeof v==="object")return ["object",Object.keys(v).sort(scalarOrder).map(k=>[k,typed(v[k])])];
      fail("保存原本の形式が不正です。");
    };
    return sha256(JSON.stringify(typed(value)));
  }
  // Synchronous SHA-256 permits the existing synchronous parser to bind sidecar
  // evidence before it adds browser-only research flags to a cloned original.
  function sha256(source) {
    const constants=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    const initial=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    const input=new TextEncoder().encode(source),bytes=new Uint8Array(Math.ceil((input.length+9)/64)*64),view=new DataView(bytes.buffer);
    bytes.set(input);bytes[input.length]=128;view.setUint32(bytes.length-8,Math.floor(input.length/0x20000000),false);view.setUint32(bytes.length-4,input.length*8>>>0,false);
    const rotate=(v,n)=>v>>>n|v<<32-n,words=new Int32Array(64),state=initial.slice();
    for(let offset=0;offset<bytes.length;offset+=64){
      for(let i=0;i<16;i++)words[i]=view.getInt32(offset+4*i,false);
      for(let i=16;i<64;i++){const a=words[i-15],b=words[i-2];words[i]=(words[i-16]+(rotate(a,7)^rotate(a,18)^a>>>3)+words[i-7]+(rotate(b,17)^rotate(b,19)^b>>>10))|0;}
      let [a,b,c,d,e,f,g,h]=state;
      for(let i=0;i<64;i++){const t=(h+(rotate(e,6)^rotate(e,11)^rotate(e,25))+(e&f^~e&g)+constants[i]+words[i])|0,u=((rotate(a,2)^rotate(a,13)^rotate(a,22))+(a&b^a&c^b&c))|0;h=g;g=f;f=e;e=d+t|0;d=c;c=b;b=a;a=t+u|0;}
      for(const [i,v] of [a,b,c,d,e,f,g,h].entries())state[i]=state[i]+v|0;
    }
    return state.map(v=>(v>>>0).toString(16).padStart(8,"0")).join("");
  }
  function bindPredictionEvidence(row) {
    const entries=row.saved_prediction_evidence;
    if(entries==null)return;
    if(!entries||typeof entries!=="object"||Array.isArray(entries)||Object.keys(entries).length>128)fail("保存原本の追加証拠が不正です。");
    const remaining=new Set(Object.keys(entries));
    for(const p of candidates(row)){
      const identity=savedPredictionIdentity(p),id=sha256(canonical([row.race_id,identity])),e=entries[id];
      if(e==null)continue;
      const a=e.artifact,n=e.native,at=n?.generated_at,completed=n?.generation_completed_no_later_than;
      const allowance=Date.parse(a?.created_at)%1000===0?999:0;
      const valid=e.schema===evidenceSchema&&e.verification_scope==="AUTHENTICATED_NATIVE_ARTIFACT_IMPORT"&&e.saved_prediction_identity===identity&&
        sha(e.prediction_original_sha256)&&e.prediction_binding_sha256===valueBinding(p)&&
        a&&a.repository_id===1416489937&&Number.isSafeInteger(a.id)&&a.id===p.artifact_id&&Number.isSafeInteger(a.run_id)&&a.run_id>0&&
        typeof a.head_sha==="string"&&/^[a-f0-9]{40}$/.test(a.head_sha)&&(!p.source_code_commit||p.source_code_commit===a.head_sha)&&
        typeof a.digest==="string"&&/^sha256:[a-f0-9]{64}$/.test(a.digest)&&a.member===(p.stage==="P0"?"forecasts.json":"national.json")&&a.member_sha256===p.original_json_sha256&&
        stamp(a.created_at)&&Date.parse(a.created_at)===Date.parse(p.persisted_at)&&n&&n.model_id===p.model_id&&n.stage===p.stage&&
        n.prediction_sha256===(p.prediction_sha256??p.model_sha256)&&stamp(n.as_of)&&stamp(n.cutoff_at)&&
        Date.parse(n.as_of)===Date.parse(p.as_of)&&Date.parse(n.cutoff_at)===Date.parse(p.cutoff_at??row.cutoff_at)&&
        Date.parse(n.as_of)<=Date.parse(a.created_at)+allowance&&Date.parse(a.created_at)<Date.parse(n.cutoff_at)&&
        (at==null||stamp(at)&&Date.parse(n.as_of)<=Date.parse(at)&&Date.parse(at)<=Date.parse(a.created_at)+allowance)&&
        (completed==null||stamp(completed)&&Date.parse(n.as_of)<=Date.parse(completed)&&Date.parse(completed)<=Date.parse(a.created_at)+allowance&&(at==null||Date.parse(at)<=Date.parse(completed)))&&
        e.clock_kind===(at!=null?"EXACT_NATIVE_GENERATED_AT":completed!=null?"NATIVE_ASOF_AND_COMPLETION_UPPER_BOUND":"NATIVE_ASOF_AND_PRE_CUTOFF_ORIGINAL");
      if(!valid)fail("保存原本と追加証拠が一致しません。");
      for(const field of ["model_version","input_sha256","source_sha256","generated_at"]){
        const value=n[field];if(value!=null&&(field.endsWith("sha256")?!sha(value):field==="model_version"?!text(value):!stamp(value)))fail("追加証拠の保存値が不正です。");
        if(p[field]!=null&&value!=null&&p[field]!==value)fail("保存原本と追加証拠の値が矛盾しています。");
      }
      savedEvidence.set(p,{row,evidence:e});remaining.delete(id);
    }
    if(remaining.size)fail("保存原本のない追加証拠があります。");
    evidenceRows.add(row);
  }
  function predictionEvidence(row,p) {
    if(!p)return null;
    const cached=savedEvidence.get(p);
    if(Object.isFrozen(row)&&Object.isFrozen(p)&&evidenceRows.has(row))return cached?.row===row?cached.evidence:null;
    savedEvidence.delete(p);bindPredictionEvidence(row);return savedEvidence.get(p)?.evidence||null;
  }
  function effectivePredictionFacts(row,p) {
    if(!p)return null;
    const evidence=predictionEvidence(row,p),n=evidence?.native;
    return {model_version:p.model_version??n?.model_version??null,input_sha256:p.input_sha256??n?.input_sha256??null,
      source_sha256:p.source_sha256??n?.source_sha256??null,generated_at:p.generated_at??n?.generated_at??null,
      native_as_of:n?.as_of??null,generation_completed_no_later_than:n?.generation_completed_no_later_than??null,
      clock_kind:evidence?.clock_kind??(p.generated_at?"SAVED_GENERATED_AT":"UNVERIFIED"),native_evidence:!!evidence,
      save_clock_tolerance_ms:evidence&&Date.parse(evidence.artifact.created_at)%1000===0?999:0};
  }
  function validDay(day) {
    return typeof day === "string" && /^\d{4}-\d\d-\d\d$/.test(day) && Number.isFinite(Date.parse(day + "T00:00:00Z")) && new Date(day + "T00:00:00Z").toISOString().slice(0, 10) === day;
  }
  function ticket(value) {
    return Array.isArray(value) && value.length === 3 && value.every(x => Number.isInteger(x) && x > 0 && x <= 99) && new Set(value).size === 3;
  }
  function validateStamps(value, fields) {
    if (!value) return;
    for (const field of fields) if (value[field] != null && !stamp(value[field])) fail("保存時刻の形式が不正です: " + field);
  }
  function marketIsolation(value) {
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      if (key !== "odds_independent" && /odds|popularity|market|payout|確定配当|人気/i.test(key)) fail("予想に市場由来の値を混ぜないでください。");
      marketIsolation(child);
    }
  }
  function candidateOrder(p) {
    for (const field of ["candidates", "ordered_candidates"]) {
      const rows = p[field];
      if (rows == null) continue;
      if (!Array.isArray(rows) || !rows.length || rows.length > 941094) fail("保存候補の形式が不正です。");
      const combinations = rows.map(row => Array.isArray(row) ? row : row?.combination);
      if (combinations.some(t => !ticket(t)) || new Set(combinations.map(t => t.join("-"))).size !== combinations.length) fail("保存候補に重複・不正な組合せがあります。");
      if (rows.some(row => !Array.isArray(row) && row.score != null && (typeof row.score !== "number" || !Number.isFinite(row.score) || row.score < 0))) fail("保存候補スコアが不正です。");
      if (canonical(combinations.slice(0, p.ordered_top8.length)) !== canonical(p.ordered_top8)) fail("保存候補順位とTop8が一致しません。");
    }
    if (p.candidates != null && p.ordered_candidates != null) {
      const combos = rows => rows.map(r => Array.isArray(r) ? r : r.combination);
      if (canonical(combos(p.candidates)) !== canonical(combos(p.ordered_candidates))) fail("保存候補順位が一致しません。");
    }
  }
  function refunds(result) {
    if (!result) return;
    if (result.refund_boats != null && (!Array.isArray(result.refund_boats) || result.refund_boats.some(x => !Number.isInteger(x) || x < 1 || x > 99) || new Set(result.refund_boats).size !== result.refund_boats.length)) fail("返還対象の形式が不正です。");
    if (result.refunds != null && (!Array.isArray(result.refunds) || result.refunds.length > 10000)) fail("返還記録の形式が不正です。");
    if (result.refund_combinations != null) {
      const combinations = result.refund_combinations;
      if (!Array.isArray(combinations) || combinations.length > 10000 || combinations.some(t => !ticket(t)) ||
          new Set(combinations.map(t => t.join("-"))).size !== combinations.length) fail("返還組合せの形式が不正です。");
      if (result.refunds != null) {
        const detailed = result.refunds.map(r => r?.combination);
        if (detailed.some(t => !ticket(t)) || canonical(detailed.map(t => t.join("-")).sort()) !==
            canonical(combinations.map(t => t.join("-")).sort())) fail("返還組合せの別名と明細が一致しません。");
      }
    }
    const visit = value => {
      if (!value || typeof value !== "object") return;
      for (const [key, child] of Object.entries(value)) {
        if (/refund.*yen|yen.*refund/i.test(key) && (!Number.isSafeInteger(child) || child < 0)) fail("返還金額が不正です。");
        visit(child);
      }
    };
    visit(result);
  }
  function sourcePinned(row) {
    return row.scope === "official" && sha(row.source_sha256) && text(row.source_provenance);
  }
  // These gates check importer assertions and matching saved pins. The browser
  // cannot authenticate the importer's authority, signature or source rights.
  function eligiblePrediction(row, p) {
    const receipt = p?.external_receipt;
    return !!(!row.private_cycle_view && sourcePinned(row) && p && text(p.model_id) && stages.slice(0, 2).includes(p.stage) && Audit.eligiblePrediction(row, p) &&
      receipt && text(receipt.authority) && receipt.content_sha256 === p.prediction_sha256 &&
      receipt.source_sha256 === row.source_sha256 && stamp(receipt.server_received_at) &&
      Date.parse(receipt.server_received_at) === Date.parse(p.persisted_at));
  }
  function hasRefund(result) {
    return !!(result?.refund_boats?.length || result?.refunds?.length || result?.refund_combinations?.length || result?.refund_yen > 0 || result?.status === "void");
  }
  function eligibleResult(row) {
    const r = row.result, evidence = r?.evidence;
    return !!(!row.private_cycle_view && sourcePinned(row) && row.offering_status === "TRIFECTA_OFFERED" &&
      r?.status === "final" && r.official === true && sha(r.source_sha256) && stamp(r.confirmed_at) &&
      stamp(row.cutoff_at) && Date.parse(r.confirmed_at) >= Date.parse(row.cutoff_at) && !hasRefund(r) &&
      evidence && text(evidence.authority) && evidence.content_sha256 === r.source_sha256 &&
      stamp(evidence.observed_at) && Date.parse(evidence.observed_at) === Date.parse(r.confirmed_at));
  }
  function candidates(row) { return [row.prediction, ...(row.comparison_predictions || [])].filter(Boolean); }
  function identity(p) { return canonical([p.stage || "UNKNOWN", p.model_id || null, p.model_version]); }
  function codeIdentity(p) {
    return p && p.model_version==null && typeof p.source_code_commit==="string" && /^[a-f0-9]{40}$/.test(p.source_code_commit) &&
      Number.isSafeInteger(p.artifact_id) && p.artifact_id>0 && sha(p.original_json_sha256) && stamp(p.persisted_at) ? p.source_code_commit : null;
  }
  function savedPredictionIdentity(p) {
    const fields=["stage","native_stage","model_id","model_version","variant","source_code_commit","as_of","cutoff_at",
      "input_sha256","source_sha256","source_captured_at","source_provenance","artifact_id","original_json_sha256",
      "physical_receipt_sha256","pair_sha256","persisted_at","server_saved_at","training_sha256","training_artifact_id","training_receipt_digest"];
    const ref=p.native_source_reference;
    const reference=ref && typeof ref==="object" && !Array.isArray(ref) ? Object.fromEntries(Object.entries(ref).filter(([key])=>!["prediction_sha256","output_sha256","model_sha256"].includes(key))) : ref ?? null;
    return canonical([...fields.map(field=>p[field] ?? null),reference]);
  }
  function selectPrediction(row, options = {}) {
    const fields = {stage:"stage",modelId:"model_id",version:"model_version",variant:"variant",predictionSha:"prediction_sha256",outputSha:"output_sha256",asOf:"as_of",cutoffAt:"cutoff_at",sourceSha:"source_sha256",artifactId:"artifact_id",receiptSha:"physical_receipt_sha256",sourceCodeCommit:"source_code_commit"};
    const supplied = Object.keys(fields).filter(key => Object.hasOwn(options,key));
    if(Object.hasOwn(options,"saveIdentity"))supplied.push("saveIdentity");
    if (!supplied.length) return row.prediction || null;
    const found=candidates(row).filter(p => supplied.every(key => key==="saveIdentity" ? savedPredictionIdentity(p)===options[key] : p[fields[key]] === options[key]));
    return found.length===1 ? found[0] : null;
  }
  function optionalSha(value, label) { if (value != null && !sha(value)) fail(label + "のSHAが不正です。"); }
  function optionalLabel(value, label, max = 250) { if (value != null && (!text(value) || value.length > max)) fail(label + "が不正です。"); }
  function missingReasons(value) {
    if (value == null) return [];
    if (!Array.isArray(value) || value.length > 1000 || value.some(reason => !text(reason) || reason.length > 2000)) fail("欠測理由が不正です。");
    return value;
  }
  function partialResult(result) {
    if (!result || typeof result !== "object" || Array.isArray(result) || !["final","pending","void","unsupported"].includes(result.status) ||
        !Array.isArray(result.winning_combinations) || result.winning_combinations.some(t => !ticket(t)) ||
        new Set(result.winning_combinations.map(t => t.join("-"))).size !== result.winning_combinations.length ||
        (result.status === "final" ? result.winning_combinations.length === 0 : result.winning_combinations.length !== 0)) fail("観測結果の形式が不正です。");
    if (result.payout_yen_per_100 != null && (!Number.isSafeInteger(result.payout_yen_per_100) || result.payout_yen_per_100 < 0)) fail("観測払戻が不正です。");
    validateStamps(result,["confirmed_at","observed_at"]);optionalSha(result.source_sha256,"観測結果");refunds(result);
    result.official = false;
  }
  function resultRosterMatches(row,results) {
    function identities(people,missing=false) {
      if(!Array.isArray(people)||people.length>6)throw new Error();const out=new Map();
      for(const p of people){
        if(!p||typeof p!=="object"||Object.hasOwn(p,"race_id")&&p.race_id!==row.race_id)throw new Error();
        const lanes=["lane","number"].filter(k=>Object.hasOwn(p,k)).map(k=>p[k]),ids=["registration_no","racer_registration_id","registration_number","participant_id","racer_id"].filter(k=>Object.hasOwn(p,k)).map(k=>p[k]);
        if(!lanes.length||lanes.some(n=>!Number.isInteger(n)||n<1||n>6||n!==lanes[0])||out.has(lanes[0])||!ids.length||ids.some(id=>id!==ids[0])||
          !(missing&&ids[0]===null||typeof ids[0]==="string"&&/^[0-9]{4}$/.test(ids[0]))||ids[0]!=null&&[...out.values()].includes(ids[0]))throw new Error();
        out.set(lanes[0],ids[0]);
      }return out;
    }
    try {
      const active=identities(row.participants),known=new Map(active),withdrawn=new Set(row.withdrawn_lanes||[]);
      if(active.size<3||!Array.isArray(row.withdrawn_lanes||[])||withdrawn.size!==(row.withdrawn_lanes||[]).length||[...withdrawn].some(n=>!Number.isInteger(n)||n<1||n>6))return false;
      const bind=proof=>{for(const [lane,id] of proof){if(id===null)continue;if(known.has(lane)&&known.get(lane)!==id||[...known.values()].includes(id)&&known.get(lane)!==id)throw new Error();known.set(lane,id);}};
      const absent=identities(row.withdrawn_participants||[],true);for(const lane of absent.keys())withdrawn.add(lane);bind(absent);
      const snapshots=row.saved_participant_rosters||[];if(!Array.isArray(snapshots)||snapshots.length>1000)return false;
      for(const snapshot of snapshots){
        if(!snapshot||typeof snapshot!=="object"||Object.hasOwn(snapshot,"race_id")&&snapshot.race_id!==row.race_id)return false;
        const proof=identities(snapshot.participants,true);if(proof.size<3)return false;bind(proof);
        for(const p of snapshot.participants)if(p.active===false||p.withdrawn===true||p.entry_status==="withdrawn")withdrawn.add(p.number??p.lane);
      }
      if(known.size>6||[...withdrawn].some(n=>active.has(n)))return false;
      const observed=identities(results);if(observed.size<3||[...active].some(([lane,id])=>observed.get(lane)!==id))return false;
      for(const p of results){const lane=p.lane??p.number;if(Object.hasOwn(p,"verified_official")&&p.verified_official!==true)return false;
        if(!active.has(lane)&&(known.get(lane)!==observed.get(lane)||!["ABSENT","WITHDRAWN","RETURNED","欠"].includes(p.finish_status)||p.finish!=null))return false;
      }return true;
    }catch{return false;}
  }
  function cutoffReconciliation(row,result) {
    const proof=result?.cutoff_reconciliation;if(proof==null)return false;
    const perModel=proof?.basis==="RAW_OFFICIAL_SP_RESULT_PER_SAVED_MODEL_CUTOFF";
    const reject=()=>fail("締切差の参考照合の出典・出走者・保存時刻が一致しません。");
    if(!proof || typeof proof!=="object" || Array.isArray(proof) || row.sport!=="boat" || !row.private_cycle_view || result.status!=="final" ||
      (!perModel&&proof.basis!=="RAW_OFFICIAL_RESULT_PER_ORIGINAL_CUTOFF") || proof.formal_eligible!==false || proof.roster_identity_verified!==true || proof.all_originals_saved_before_both!==true ||
      !sha(proof.source_sha256) || proof.source_sha256!==result.source_sha256 || typeof proof.maximum_offset_seconds!=="number" || !Number.isFinite(proof.maximum_offset_seconds) || proof.maximum_offset_seconds<0 || proof.maximum_offset_seconds>(perModel?86400:60))reject();
    const originals=proof.original_cutoffs,saved=row.saved_cutoff_variants||[];
    if(!Array.isArray(originals)||originals.some(c=>!stamp(c))||new Set(originals).size!==originals.length||canonical([...originals].sort())!==canonical([...saved].sort())||new Set(saved.map(Date.parse)).size<2)reject();
    const clocks=originals.map(Date.parse),scheduled=(row.saved_schedule_cutoff_variants||[]).map(Date.parse);
    const scheduleCount=new Set(scheduled).size,scheduleBound=scheduleCount<=1&&!row.missing_reasons?.includes("SAVED_SCHEDULE_CUTOFF_CONFLICT")||perModel&&scheduleCount>1;
    if(!scheduleBound || scheduled.some(c=>!clocks.includes(c)) || row.saved_observation_cutoff_variants?.length)reject();
    const people=row.participants,roster=new Map();
    if(!Array.isArray(people)||people.length<3||people.length>6)reject();
    for(const person of people){if(!Number.isInteger(person.number)||person.number<1||person.number>6||typeof person.registration_no!=="string"||!/^\d{4}$/.test(person.registration_no)||roster.has(person.number))reject();roster.set(person.number,person.registration_no);}
    if(new Set(roster.values()).size!==roster.size)reject();
    const observed=Date.parse(result.observed_at),observations=row.result_observations||[];
    if(!observations.length||observed!==Math.max(...observations.map(o=>Date.parse(o.captured_at))))reject();
    const matching=observations.filter(o=>Date.parse(o.captured_at)===observed&&o.source_sha256===proof.source_sha256);
    if(matching.length!==1)reject();
    const observation=matching[0],data=observation.data;
    if(observation.body_identity_verified!==true||observation.status!=="AVAILABLE"||!data||data.status!=="settled"||data.confirmed!==true||data.finish_confirmed!==true||!resultRosterMatches(row,data.results))reject();
    const payouts=Array.isArray(data.payouts)?data.payouts.filter(p=>p?.bet_type==="trifecta"):[],winners=result.winning_combinations;
    if(payouts.length!==winners.length||payouts.some(p=>!ticket(p.combination)||p.combination.some(n=>!roster.has(n))||!Number.isSafeInteger(p.payout_per_100_yen)||p.payout_per_100_yen<0)||
      canonical(payouts.map(p=>p.combination.join("-")).sort())!==canonical(winners.map(t=>t.join("-")).sort())||!winners.some(t=>canonical(t)===canonical(data.top3)))reject();
    if(payouts.length===1 ? result.payout_yen_per_100!==payouts[0].payout_per_100_yen : canonical(result.payouts)!==canonical(payouts))reject();
    if(result.payouts!=null && canonical(result.payouts)!==canonical(payouts))reject();
    for(const field of ["refund_boats","refunds","refund_combinations","dead_heat"])if(canonical(result[field]??null)!==canonical(data[field]??null))reject();
    if(!stamp(observation.closed_at))reject();
    if(perModel){
      if((Object.hasOwn(proof,"source_schedule_binding")?proof.source_schedule_binding:observation.schedule_binding)!=="SP_EXPLICIT_RACE_HEADER"||![undefined,null,"SP_EXPLICIT_RACE_HEADER"].includes(observation.schedule_binding)||!stamp(proof.source_cutoff_at)||Date.parse(proof.source_cutoff_at)!==Date.parse(observation.closed_at))reject();
      try{const source=observation.source_url;if(typeof source!=="string"||!source.startsWith("https://www.boatrace.jp/owsp/sp/spdata?"))reject();const url=new URL(source),q=url.searchParams,number=q.get("rno"),day=q.get("hd"),venue=q.get("jcd");if(url.pathname!=="/owsp/sp/spdata"||url.hash||[...q].length!==4||new Set(q.keys()).size!==4||q.get("type")!=="raceresult"||!/^(?:[1-9]|1[0-2])$/.test(number)||!/^(0[1-9]|1[0-9]|2[0-4])$/.test(venue)||!/^\d{8}$/.test(day)||!validDay(day.slice(0,4)+"-"+day.slice(4,6)+"-"+day.slice(6,8))||day+"-"+venue+"-"+number.padStart(2,"0")!==row.race_id)reject();}catch{reject();}
    }
    clocks.push(Date.parse(observation.closed_at));
    if(clocks.some(c=>new Date(c+9*60*60*1000).toISOString().slice(0,10)!==row.event_date_jst)||(Math.max(...clocks)-Math.min(...clocks))/1000>proof.maximum_offset_seconds||observed<Math.max(...clocks))reject();
    const predictions=candidates(row);if(!predictions.length)reject();
    for(const p of predictions){if(perModel&&(!stamp(p.cutoff_at)||!clocks.slice(0,-1).includes(Date.parse(p.cutoff_at))))reject();const limit=perModel?Math.min(Date.parse(p.cutoff_at),Date.parse(observation.closed_at)):Math.min(...clocks),saved=p.persisted_at??p.server_saved_at;if(!stamp(saved)||Date.parse(saved)>=limit)reject();for(const field of ["as_of","generated_at","source_captured_at","server_saved_at"])if(p[field]!=null&&(!stamp(p[field])||Date.parse(p[field])>=limit))reject();}
    return true;
  }
  function boundSameRaceResultName(source, raceId) {
    // This is a display-only name from an already authenticated official
    // result; do not treat its text as a prediction or a fresh source GET.
    if (source?.kind !== "SAME_RACE_RESULT" || source.race_id !== raceId ||
        !sha(source.source_sha256) || !stamp(source.captured_at)) return false;
    const match = /^([0-9]{8})-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])$/.exec(raceId);
    if (!match) return false;
    try {
      const url = new URL(source.source_url);
      if (url.protocol !== "https:" || url.host !== "www.boatrace.jp" ||
          url.username || url.password || url.hash || url.pathname !== "/owsp/sp/spdata") return false;
      const query = url.searchParams;
      return [...query].length === 4 && new Set(query.keys()).size === 4 &&
        query.get("type") === "raceresult" && query.get("hd") === match[1] &&
        query.get("jcd") === match[2] && query.get("rno") === String(Number(match[3])) &&
        Date.parse(source.captured_at) >= Date.parse(
          match[1].slice(0,4) + "-" + match[1].slice(4,6) + "-" + match[1].slice(6,8) + "T00:00:00+09:00");
    } catch { return false; }
  }

  function parsePrivateCycle(value) {
    if (!["REAL_REPORTED","SYNTHETIC_ONLY"].includes(value.dataset_status) || !Array.isArray(value.records) || value.records.length > 10000) fail("私有循環データの種別・レース配列が不正です。");
    if (value.event_date_jst != null && !validDay(value.event_date_jst)) fail("JST開催日が不正です。");
    optionalSha(value.source_state_sha256,"循環状態");
    const seen = new Set();
    for (const row of value.records) {
      const dispatchRow = row?.native_dispatch_view === true || row?.source_observation_view === true;
      if (!row || typeof row !== "object" || Array.isArray(row) || !text(row.race_id) || row.race_id.length > 250 ||
          !sports.includes(row.sport) || !(dispatchRow && row.venue == null || text(row.venue) && row.venue.length <= 100) ||
          !(dispatchRow && row.race_no == null || Number.isInteger(row.race_no) && row.race_no >= 1 && row.race_no <= 99) ||
          !validDay(row.event_date_jst) || !["TRIFECTA_OFFERED","NOT_OFFERED","UNKNOWN"].includes(row.offering_status)) fail("私有循環レースの識別情報が不正です。");
      if (seen.has(row.race_id)) fail("同じレースIDの重複があります。");seen.add(row.race_id);
      bindPredictionEvidence(row);
      validateStamps(row,["cutoff_at","observed_at","as_of","updated_at"]);
      if (row.cutoff_at && new Date(Date.parse(row.cutoff_at) + 9 * 60 * 60 * 1000).toISOString().slice(0,10) !== row.event_date_jst) fail("JST開催日と締切時刻が一致しません。");
      let savedCutoffs=null,scheduleCutoffs=null,observationCutoffs=null;
      for (const field of ["saved_cutoff_variants","saved_schedule_cutoff_variants","saved_observation_cutoff_variants"]) if (row[field] != null) {
        const observationVariants=field==="saved_observation_cutoff_variants";
        if (!Array.isArray(row[field]) || row[field].length > 64 || row[field].some(value=>!stamp(value) || !observationVariants && new Date(Date.parse(value)+9*60*60*1000).toISOString().slice(0,10)!==row.event_date_jst)) fail("保存された締切一覧が不正です。");
        const instants=new Set(row[field].map(Date.parse));if(new Set(row[field]).size!==row[field].length) fail("保存された締切が重複しています。");
        if(field==="saved_cutoff_variants")savedCutoffs=instants.size?instants:null;
        else if(observationVariants)observationCutoffs=instants.size?instants:null;
        else scheduleCutoffs=instants;
      }
      if (savedCutoffs && (savedCutoffs.size>1 ? row.cutoff_at!==null : row.cutoff_at==null || !savedCutoffs.has(Date.parse(row.cutoff_at)))) fail("原本間の締切不一致を単一時刻に変更できません。");
      if (!savedCutoffs && scheduleCutoffs?.size>1 && row.cutoff_at!==null) fail("台帳間の締切不一致を単一時刻に変更できません。");
      if (observationCutoffs && (observationCutoffs.size<2 || row.cutoff_at!==null && savedCutoffs?.size!==1)) fail("取得観測間の締切不一致を単一時刻に変更できません。");
      optionalSha(row.source_sha256,"情報源");optionalSha(row.source_sha,"情報源");
      if (row.source_sha != null && row.source_sha256 != null && row.source_sha !== row.source_sha256) fail("元データSHAが一致しません。");
      if (row.participants != null) {
        if (!Array.isArray(row.participants) || row.participants.length > 99) fail("出走表の形式が不正です。");
        const numbers = new Set();
        for (const person of row.participants) {
          if (!person || typeof person !== "object" || !Number.isInteger(person.number) || person.number < 1 || person.number > 99 || numbers.has(person.number)) fail("出走番号が不正です。");
          numbers.add(person.number);optionalLabel(person.name,"出走者名",500);optionalLabel(person.registration_no,"登録番号",100);
          if(person.name_source!=null){
            const source=person.name_source;
            if(!source || typeof source!=="object" || Array.isArray(source) || !["SAME_RACE_PROGRAM","SAME_RACE_RESULT","VERIFIED_RACER_REGISTRY"].includes(source.kind) ||
              source.registration_no!==person.registration_no || !text(person.name) ||
              source.kind==="SAME_RACE_PROGRAM" && source.race_id!==row.race_id ||
              source.kind==="SAME_RACE_RESULT" && !boundSameRaceResultName(source,row.race_id) ||
              source.kind==="VERIFIED_RACER_REGISTRY" && (source.verified!==true || !sha(source.source_sha256)))fail("選手名と登録・出典の対応が不正です。");
            optionalSha(source.source_sha256,"選手名の出典");validateStamps(source,["captured_at"]);optionalLabel(source.source_url,"選手名の出典URL",2000);
          }
        }
      }
      const reasons = missingReasons(row.missing_reasons);
      row.scope = value.dataset_status === "SYNTHETIC_ONLY" ? "synthetic" : "research";
      row.private_cycle_view = true;row.source_schema = privateCycleSchema;row.evidence_imported_only = true;
      if (row.source_observation_view === true) {
        const observation=row.source_observation;
        if (row.prediction!=null || row.comparison_predictions?.length || row.result!=null || row.result_observations?.length || row.cutoff_at!=null ||
            savedCutoffs?.size || scheduleCutoffs?.size || observationCutoffs?.size || row.offering_status!=="UNKNOWN" ||
            !observation || typeof observation!=="object" || observation.kind!=="CAPTURED_PUBLIC_PAGE_FACTS" || !stamp(observation.observed_at) ||
            !sha(observation.source_sha256) || !sha(observation.original_json_sha256) || !Number.isSafeInteger(observation.artifact_id) || observation.artifact_id<1 ||
            observation.source_uri!==row.race_id || observation.source_url!==observation.source_uri || observation.final_url!==observation.source_uri) fail("取得ページ観測と予想・結果を混在させられません。");
        let url;try{url=new URL(observation.source_url);}catch{fail("取得ページURLが不正です。");}
        if(url.protocol!=="https:" || url.username || url.password || url.hash || observation.source_url.length>512)fail("取得ページURLが不正です。");
        observation.independent_source_verified=false;observation.pre_cutoff_receipt_verified=false;
      }
      if (row.scheduled_stages != null && (!Array.isArray(row.scheduled_stages) || !row.scheduled_stages.length || row.scheduled_stages.length > 4 ||
          new Set(row.scheduled_stages).size !== row.scheduled_stages.length || row.scheduled_stages.some(stage=>!stages.slice(0,2).includes(stage) && !(row.sport === "autorace" && nativeAutoraceStages.includes(stage))))) fail("対象台帳の予想時点が不正です。");
      if (row.dispatch_slots != null) {
        if (!dispatchRow || !Array.isArray(row.dispatch_slots) || row.dispatch_slots.length > 4096) fail("モデル別状態の形式が不正です。");
        const statuses=["NOT_APPLICABLE","INPUT_MISSING","TRAINED_ARTIFACT_MISSING","DEADLINE_PASSED","RULE_FILTERED","UNCONNECTED_NATIVE_RUNTIME","SOURCE_NOT_AUTHORIZED","INPUT_REJECTED","EXECUTION_FAILED","GENERATED_UNATTESTED","ORIGINAL_REUSED"];
        const slots = new Set();
        for (const slot of row.dispatch_slots) {
          if (!slot || typeof slot !== "object" || Array.isArray(slot) || !text(slot.model_id) || slot.model_id.length > 128 ||
              !(stages.slice(0,2).includes(slot.stage) || row.sport === "autorace" && nativeAutoraceStages.includes(slot.stage)) ||
              !statuses.includes(slot.status) || typeof slot.applicable !== "boolean") fail("モデル別状態の識別情報が不正です。");
          optionalLabel(slot.model_version,"モデル版",100);optionalLabel(slot.reason,"状態理由",2000);
          if (row.scheduled_stages && !row.scheduled_stages.includes(slot.stage)) fail("モデル別状態の時点が対象台帳にありません。");
          optionalLabel(slot.projection_status,"表示状態",100);optionalLabel(slot.projection_reason,"表示理由",2000);
          optionalSha(slot.output_sha256,"保存出力本文");optionalSha(slot.prediction_sha256,"モデル別原本");
          const key=canonical([slot.stage,slot.model_id,slot.model_version ?? null]);
          if (slots.has(key)) fail("同じモデル別状態が重複しています。");slots.add(key);
        }
      }
      if (row.prediction != null && (!row.prediction || typeof row.prediction !== "object" || Array.isArray(row.prediction))) fail("保存予想の形式が不正です。");
      if (row.comparison_predictions != null && (!Array.isArray(row.comparison_predictions) || row.comparison_predictions.length > 4095)) fail("比較モデル予想の件数が不正です。");
      if (row.comparison_predictions?.some(p => !p || typeof p !== "object" || Array.isArray(p))) fail("比較保存予想の形式が不正です。");
      if (row.actual_purchase != null && (row.actual_purchase.confirmed !== true || ["stake_yen","payout_yen","refund_yen"].some(key => !Number.isSafeInteger(row.actual_purchase[key]) || row.actual_purchase[key] < 0))) fail("購入申告の形式が不正です。");
      const identities = new Set();
      for (const p of candidates(row)) {
        if (!p || typeof p !== "object" || Array.isArray(p) || !Array.isArray(p.ordered_top8) || !p.ordered_top8.length || p.ordered_top8.length > 8 ||
            p.ordered_top8.some(t => !ticket(t)) || new Set(p.ordered_top8.map(t => t.join("-"))).size !== p.ordered_top8.length) fail("私有循環の保存Top8が不正です。");
        if (!stages.includes(p.stage) && !(row.sport === "autorace" && nativeAutoraceStages.includes(p.stage))) fail("競技に対応する保存時点が必要です。");
        if (row.scheduled_stages && !row.scheduled_stages.includes(p.stage)) fail("保存予想の時点が対象台帳にありません。");
        optionalLabel(p.model_id,"モデルID",128);optionalLabel(p.model_version,"モデル版",100);optionalLabel(p.variant,"保存モデル区分",250);
        if(p.source_code_commit!=null && (typeof p.source_code_commit!=="string" || !/^[a-f0-9]{40}$/.test(p.source_code_commit)))fail("保存コードのコミットが不正です。");
        validateStamps(p,["generated_at","as_of","persisted_at","server_saved_at","cutoff_at","observed_at"]);
        if (p.cutoff_at && row.cutoff_at && Date.parse(p.cutoff_at) !== Date.parse(row.cutoff_at)) fail("保存予想とレースの締切が一致しません。");
        if (savedCutoffs && !savedCutoffs.has(Date.parse(p.cutoff_at))) fail("保存予想の締切が原本の一覧にありません。");
        if (p.persisted_at && p.server_saved_at && Date.parse(p.persisted_at) !== Date.parse(p.server_saved_at)) fail("保存予想の保存時刻が一致しません。");
        const nativeDispatch = p.native_dispatch_prediction === true;
        if (nativeDispatch && !sha(p.output_sha256)) fail("保存出力本文のSHAが必要です。");
        if (p.prediction_sha256 == null ? !(nativeDispatch && p.hash_basis === "NATIVE_OUTPUT_CONTENT") : !sha(p.prediction_sha256)) fail("保存予想のSHAが不正です。");
        for (const field of ["input_sha256","source_sha256","model_sha256","original_json_sha256","training_sha256","output_sha256"]) optionalSha(p[field],field);
        if (!nativeDispatch && p.model_sha256 != null && p.model_sha256 !== p.prediction_sha256) fail("保存モデルのSHAが一致しません。");
        if (p.artifact_id != null && (!Number.isSafeInteger(p.artifact_id) || p.artifact_id < 1)) fail("原本artifact IDが不正です。");
        if (p.odds_independent != null && typeof p.odds_independent !== "boolean") fail("オッズ分離の保存値が不正です。");
        marketIsolation(p);candidateOrder(p);
        const key = savedPredictionIdentity(p);
        if (identities.has(key)) fail("同じ保存予想原本の重複があります。");identities.add(key);
        p.external_receipt_verified = false;p.private_cycle_view = true;
        const absent = missingReasons(p.missing_reasons);
        for (const [field,reason] of [["model_id","MODEL_ID_NOT_SAVED"],["model_version","MODEL_VERSION_NOT_SAVED"],["generated_at","GENERATED_AT_NOT_SAVED"],["input_sha256","INPUT_SHA_NOT_SAVED"],["source_sha256","SOURCE_SHA_NOT_SAVED"],["odds_independent","ODDS_INDEPENDENCE_NOT_SAVED"]]) if (p[field] == null) absent.push(reason);
        absent.push("INDEPENDENT_RECEIPT_NOT_VERIFIED");p.missing_reasons = [...new Set(absent)];
        if (p.prediction_sha256 == null) p.missing_reasons.push("NATIVE_PREDICTION_SHA_NOT_SAVED");
      }
      if (row.result != null) partialResult(row.result);
      if (row.result_revisions != null && (!Array.isArray(row.result_revisions) || row.result_revisions.length)) fail("私有循環の取得観測を公式改訂番号へ変換できません。");
      row.result_revisions = row.result_revisions || [];
      if (row.result_observations != null && (!Array.isArray(row.result_observations) || row.result_observations.length > 10000)) fail("取得観測履歴が不正です。");
      const captures = new Map();
      for (const observation of row.result_observations || []) {
        if (!observation || typeof observation !== "object" || Array.isArray(observation) || observation.race_id !== row.race_id || !stamp(observation.captured_at)) fail("取得観測の識別情報・時刻が不正です。");
        optionalSha(observation.source_sha256,"取得観測");validateStamps(observation,["closed_at"]);
        const previous = captures.get(observation.captured_at);
        if (previous && canonical(previous) !== canonical(observation)) fail("同じ取得時刻の観測内容が矛盾しています。");
        captures.set(observation.captured_at,observation);
      }
      const reconciled=cutoffReconciliation(row,row.result);
      if (row.result_observation_rejections != null) {
        if (!Array.isArray(row.result_observation_rejections) || row.result_observation_rejections.length>10000) fail("結果観測の照合不可記録が不正です。");
        const seenRejections=new Set();
        for (const rejected of row.result_observation_rejections) {
          if (!rejected || typeof rejected!=="object" || !stamp(rejected.captured_at) || typeof rejected.reason!=="string" || !/^[A-Z][A-Z0-9_]{0,199}$/.test(rejected.reason)) fail("結果観測の照合不可理由が不正です。");
          optionalSha(rejected.source_sha256,"照合不可観測");
          const key=canonical([Date.parse(rejected.captured_at),rejected.source_sha256??null]);
          if(seenRejections.has(key) || !(row.result_observations||[]).some(o=>Date.parse(o.captured_at)===Date.parse(rejected.captured_at) && (o.source_sha256??null)===(rejected.source_sha256??null))) fail("照合不可記録が元の結果観測と一致しません。");
          seenRejections.add(key);
          if(row.result?.status==="final" && Date.parse(row.result.observed_at)===Date.parse(rejected.captured_at) && !(reconciled && rejected.reason==="RESULT_AMBIGUOUS_FORECAST_CUTOFF" && rejected.source_sha256===row.result.source_sha256)) fail("照合不可の結果観測を確定結果にできません。");
        }
      }
      if (savedCutoffs?.size>1 && row.result?.status==="final" && !reconciled) fail("原本間の締切が未確定の結果は照合できません。");
      if (!savedCutoffs && scheduleCutoffs?.size>1 && row.result?.status==="final") fail("台帳間の締切が未確定の結果は照合できません。");
      if (observationCutoffs && row.result?.status==="final") fail("取得観測間の締切が未確定の結果は照合できません。");
      reasons.push("PRIVATE_CYCLE_RESEARCH_VIEW_ONLY","INDEPENDENT_RECEIPT_NOT_VERIFIED");
      if (!candidates(row).length) reasons.push("NO_SAVED_PREDICTION");
      row.missing_reasons = [...new Set(reasons)];
    }
    value.evidence_imported_only = true;
    value.verification_limitations = "保存された私有循環状態の研究閲覧です。未保存のモデル版・生成時刻・入力SHAを補完せず、観測履歴を公式改訂や独立保存証拠として扱いません。";
    return freeze(value);
  }
  function parse(raw) {
    if (!Audit) fail("監査データ検証モジュールが必要です。");
    const value = clone(raw);
    if (value?.schema === privateCycleSchema) return parsePrivateCycle(value);
    if (!value || value.schema !== "RACE_AI_FORECAST_AUDIT_V1") fail("未対応のデータ形式です。");
    if (!["AUDIT_ONLY", "REAL_REPORTED", "SYNTHETIC_ONLY"].includes(value.dataset_status) || !Array.isArray(value.records) || value.records.length > 10000) fail("データ種別・レース配列が不正です。");
    if (value.event_date_jst != null && !validDay(value.event_date_jst)) fail("JST開催日が不正です。");
    const seen = new Set();
    value.records = value.records.map(row => {
      if (!row || typeof row !== "object") fail("レースの形式が不正です。");
      if (row.source_sha != null) {
        if (row.source_sha256 != null && row.source_sha256 !== row.source_sha) fail("元データSHAが一致しません。");
        row.source_sha256 = row.source_sha;
      }
      if (row.sport === "horse_local" || row.sport === "horse_jra") {
        row.source_sport = row.sport;
        row.sport = "horse";
      }
      if (seen.has(row.race_id)) fail("同じレースIDの重複があります。");
      seen.add(row.race_id);
      if (row.scope != null && !scopes.includes(row.scope)) fail("データの範囲が不正です。");
      const day = row.event_date_jst || Audit.raceDay(row) || value.event_date_jst || null;
      if (day != null && !validDay(day)) fail("JST開催日が不正です。");
      if (row.event_date_jst != null && !validDay(row.event_date_jst)) fail("JST開催日が不正です。");
      validateStamps(row, ["cutoff_at", "observed_at", "as_of", "updated_at"]);
      if (day && row.cutoff_at && new Date(Date.parse(row.cutoff_at) + 9 * 60 * 60 * 1000).toISOString().slice(0, 10) !== day) fail("JST開催日と締切時刻が一致しません。");
      row.event_date_jst = day;
      const reasons = row.missing_reasons == null ? [] : row.missing_reasons;
      if (!Array.isArray(reasons) || reasons.some(r => !text(r))) fail("欠測理由が不正です。");
      row.missing_reasons = reasons;
      if (value.dataset_status === "SYNTHETIC_ONLY") row.scope = "synthetic";
      else if (value.dataset_status !== "REAL_REPORTED" || row.scope !== "official" || !sha(row.source_sha256) || !text(row.source_provenance)) {
        if (row.scope === "synthetic") fail("合成と実データを混在させないでください。");
        if (row.scope !== "research") reasons.push("OFFICIAL_SCOPE_OR_SOURCE_EVIDENCE_MISSING");
        row.scope = "research";
      }
      if (row.comparison_predictions != null && (!Array.isArray(row.comparison_predictions) || row.comparison_predictions.length > 64)) fail("比較モデル予想の件数が不正です。");
      const variants = candidates(row), identities = new Set();
      for (const p of variants) {
        if (!p || typeof p !== "object" || Array.isArray(p)) fail("予想の形式が不正です。");
        p.stage = p.stage || row.stage || "UNKNOWN";
        if (!stages.includes(p.stage)) fail("予想時点はP0/P1/UNKNOWNが必要です。");
        if (p.model_id != null && (!text(p.model_id) || p.model_id.length > 128)) fail("モデル識別子が不正です。");
        validateStamps(p, ["generated_at", "persisted_at", "cutoff_at", "as_of", "observed_at"]);
        marketIsolation(p);
        candidateOrder(p);
        if (identities.has(identity(p))) fail("同じ時点・モデル・版の重複があります。");
        identities.add(identity(p));
        // Reuse the existing strict odds-free audit admission for each saved
        // variant. Its older model key does not distinguish P0 from P1.
        const check = {...row, prediction:p}; delete check.comparison_predictions;
        Audit.parse({...value, records:[check]});
        if (p.stage === "UNKNOWN") reasons.push("PREDICTION_STAGE_NOT_SAVED");
        if (!p.model_id) reasons.push("MODEL_ID_NOT_SAVED");
        if (!eligiblePrediction(row, p)) reasons.push("EXTERNAL_RECEIPT_PIN_MISSING_OR_MISMATCHED");
      }
      if (!variants.length) {
        const check = {...row}; delete check.comparison_predictions;
        Audit.parse({...value, records:[check]});
        reasons.push(row.no_forecast_reason || "NO_SAVED_PREDICTION");
      }
      if (row.result_revisions != null) {
        row.result_revisions.forEach((r, index) => {
          if (r.revision_no !== index + 1) fail("結果改訂の版は連続している必要があります。");
          validateStamps(r, ["confirmed_at", "observed_at"]);
          refunds(r);
        });
        if (row.result_revisions.length && !row.result) fail("最新の公式結果と改訂履歴が一致しません。");
        if (row.result_revisions.length) {
          const withoutRevision = result => Object.fromEntries(Object.entries(result).filter(([key]) => key !== "revision_no"));
          if (canonical(withoutRevision(row.result_revisions.at(-1))) !== canonical(withoutRevision(row.result))) fail("最新結果の払戻・返還・出典と改訂履歴が一致しません。");
        }
      }
      refunds(row.result);
      validateStamps(row.result, ["confirmed_at", "observed_at"]);
      if (row.result && !eligibleResult(row)) reasons.push(hasRefund(row.result) ? "REFUND_REVIEW_REQUIRED" : "OFFICIAL_RESULT_PIN_MISSING_OR_MISMATCHED");
      row.missing_reasons = [...new Set(reasons)];
      row.evidence_imported_only = true;
      return row;
    });
    value.evidence_imported_only = true;
    value.verification_limitations = "保存された取込元の申告・SHA・時刻の整合性を表示します。ブラウザは署名・権限・独立時刻を認証しません。";
    return freeze(value);
  }
  function newStats() {
    return {ledger:0, officialLedger:0, researchLedger:0, syntheticLedger:0, frozenReported:0, noForecast:0,
      evaluable:0, hits:null, hit8:null, excluded:0, actualPurchases:0, actualStake:0, actualPayout:0,
      actualRefund:0, actualNet:null, evidence_imported_only:true, stage_mixed:false,
      identity_mixed:false, prediction_identities:[]};
  }
  function scored(row, p) {
    return eligiblePrediction(row, p) && row.result.winning_combinations.some(w => p.ordered_top8.some(t => Audit.ticketKey(t) === Audit.ticketKey(w)));
  }
  function accumulate(stats, row, p = row.prediction) {
    stats.ledger++;
    stats[row.scope + "Ledger"]++;
    if (eligiblePrediction(row, p)) stats.frozenReported++; else stats.noForecast++;
    if (eligibleResult(row)) {
      stats.evaluable++;
      stats.hits = (stats.hits || 0) + (scored(row, p) ? 1 : 0);
    } else stats.excluded++;
    const a = row.actual_purchase;
    if (row.scope === "official" && a?.confirmed === true) {
      stats.actualPurchases++; stats.actualStake += a.stake_yen;
      stats.actualPayout += a.payout_yen; stats.actualRefund += a.refund_yen;
    }
  }
  function finish(stats, identities) {
    stats.prediction_identities = [...identities].sort().map(key => {
      const [stage, model_id, model_version] = JSON.parse(key);
      return {stage, model_id, model_version};
    });
    stats.stage_mixed = new Set(stats.prediction_identities.map(p => p.stage)).size > 1;
    stats.identity_mixed = identities.size > 1;
    stats.hit8 = stats.evaluable && identities.size === 1 ? stats.hits / stats.evaluable : null;
    stats.actualNet = stats.actualPurchases ? stats.actualPayout + stats.actualRefund - stats.actualStake : null;
    return stats;
  }
  function summary(records) {
    const overall = newStats(), bySport = Object.fromEntries(sports.map(s => [s, newStats()]));
    const byScope = Object.fromEntries(scopes.map(s => [s, newStats()]));
    const byStage = Object.fromEntries(summaryStages.map(s => [s, newStats()]));
    const identitySets = new Map([overall, ...Object.values(bySport), ...Object.values(byScope), ...Object.values(byStage)].map(s => [s, new Set()]));
    for (const row of records) {
      const stage = row.prediction?.stage || "UNKNOWN";
      for (const target of [overall, bySport[row.sport], byScope[row.scope]]) {
        accumulate(target, row);
        if (row.scope === "official" && row.prediction) identitySets.get(target).add(identity(row.prediction));
      }
      for (const phase of summaryStages) {
        if (nativeAutoraceStages.includes(phase) && (row.sport !== "autorace" || !row.private_cycle_view)) continue;
        const variants = candidates(row).filter(p => p.stage === phase);
        // Each named stage keeps the full official schedule denominator,
        // including races with no saved forecast at that stage. UNKNOWN remains
        // the explicit unknown/missing-primary view rather than another cohort.
        const declared=(row.scheduled_stages||[]).includes(phase) || (row.dispatch_slots||[]).some(slot=>slot.stage===phase);
        if (phase === "UNKNOWN" ? stage !== "UNKNOWN" : row.scope !== "official" && !variants.length && !declared) continue;
        accumulate(byStage[phase], row, variants[0] || null);
        if (row.scope === "official") for (const p of variants) identitySets.get(byStage[phase]).add(identity(p));
      }
    }
    for (const [stats, identities] of identitySets) finish(stats, identities);
    return {overall, bySport, byScope, byStage};
  }
  function modelGroups(records) {
    const groups = new Map();
    for (const row of records) for (const p of candidates(row)) {
      const variant = p.private_cycle_view ? p.variant ?? null : null;
      const code_identity = p.private_cycle_view ? codeIdentity(p) : null;
      const key = canonical([row.scope, row.sport, p.stage, p.model_id || null, p.model_version, variant,...(code_identity?[code_identity]:[])]);
      if (!groups.has(key)) groups.set(key, {key, scope:row.scope, sport:row.sport, stage:p.stage,
        model_id:p.model_id || null, model_version:p.model_version, variant, code_identity, private_cycle_view:!!p.private_cycle_view, issued:0, ambiguous_originals:0, ...newStats(),
        comparison:"保存原本の参考比較（同一未来レース・入力・時刻の並走は別途検証）"});
    }
    for (const group of groups.values()) {
      const cohort = records.filter(r => {
        if (r.scope !== group.scope || r.sport !== group.sport) return false;
        const declared=[...(r.scheduled_stages||[]),...(r.dispatch_slots||[]).map(slot=>slot.stage)];
        return !r.private_cycle_view || !declared.length || declared.includes(group.stage) || candidates(r).some(p=>p.stage===group.stage);
      });
      for (const row of cohort) {
        const found = candidates(row).filter(p => p.stage === group.stage && (p.model_id || null) === group.model_id && p.model_version === group.model_version &&
          (!group.private_cycle_view || (p.variant ?? null) === group.variant && codeIdentity(p) === group.code_identity));
        const p = found.length===1 ? found[0] : null;
        if (found.length) group.issued++;
        if (found.length>1) group.ambiguous_originals++;
        accumulate(group, row, p);
      }
      if(group.ambiguous_originals)group.comparison+=" · 同じ条件に複数の保存原本がある"+group.ambiguous_originals+"レースは、個別原本をレース詳細で確認してください。";
      finish(group, new Set(group.scope === "official" ? [canonical([group.stage, group.model_id, group.model_version])] : []));
    }
    return [...groups.values()];
  }
  return Object.freeze({parse, summary, selectPrediction, modelGroups, eligiblePrediction, eligibleResult, candidates, savedPredictionIdentity, codeIdentity, predictionEvidence, effectivePredictionFacts});
});
