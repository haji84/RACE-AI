/** RACE-AI one-race metadata-only 3-cycle receipt audit.
 * Pure local validation. Never fetch upstream, modify D1 or claim licensing.
 * Input is caller-provided metadata and NOT independently authenticated.
 * A technical PASS means structural completeness, not formal E2E admission.
 */
const HASH=/^[a-f0-9]{64}$/;
function stamp(value){
  if(typeof value!=="string"||!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value))
    return null;
  const t=Date.parse(value);
  return Number.isFinite(t)?t:null;
}
function auditThreeCycles(raw){
 const blockers=[],observed={source_cycles:0,saved_cycles:0,browser_linked_cycles:0};
 const fail=s=>{if(!blockers.includes(s))blockers.push(s);};
 if(!raw||raw.schema!=="RACE_AI_ODDS_THREE_CYCLE_AUDIT_V1")
   return {status:"HOLD",blockers:["SCHEMA_UNSUPPORTED"],observed};
 const race=raw.race_id;
 const cutoff=stamp(raw.cutoff_at);
 if(typeof race!=="string"||!/^20\d{6}-\d\d-\d\d$/.test(race)||cutoff===null)
   fail("UNVERIFIED_RACE_OR_CUTOFF");
 if(raw.rights_confirmed!==true||typeof raw.rights_evidence_ref!=="string"||
    raw.rights_evidence_ref.length<8)fail("UPSTREAM_RIGHTS_UNVERIFIED");
 if(raw.shared_free_quota_verified!==true)fail("ACCOUNT_FREE_USAGE_UNVERIFIED");
 if(raw.official_cutoff_verified!==true)fail("OFFICIAL_CUTOFF_UNVERIFIED");
 const source=Array.isArray(raw.source_attempts)?raw.source_attempts:[];
 const browser=Array.isArray(raw.safari_receipts)?raw.safari_receipts:[];
 if(source.length<3)fail("FEWER_THAN_THREE_SOURCE_CYCLES");
 if(browser.length<3)fail("FEWER_THAN_THREE_SAFARI_READS");
 const valid=[];
 for(const entry of source){
   const begin=stamp(entry?.attempt_at),end=stamp(entry?.finished_at);
   const received=stamp(entry?.server_received_at),published=stamp(entry?.source_published_at);
   if(entry?.race_id!==race||begin===null||end===null||
       received===null||published===null||
       !(begin<=published || published<=received) || // checked by ordering below
       begin>end||received>end||published>received||
       (cutoff!==null&&(begin>=cutoff||received>=cutoff))||
       !HASH.test(entry?.snapshot_sha256||"")||
       entry?.quoted_count!==120||entry?.ticket_count!==120||
       !["D1_SAVED_SHA_VERIFIED","SOURCE_UNCHANGED"].includes(entry?.status))
      {fail("INVALID_SOURCE_RECEIPT");continue;}
   if(entry.status==="D1_SAVED_SHA_VERIFIED"&&
      entry.snapshot_sha256!==entry.d1_readback_sha256)
      {fail("D1_READBACK_SHA_MISMATCH");continue;}
   if(entry.status==="SOURCE_UNCHANGED"&&
      entry.snapshot_sha256!==entry.d1_readback_sha256)
      {fail("UNCHANGED_SNAPSHOT_READBACK_MISSING");continue;}
   valid.push({...entry,_begin:begin,_end:end,_received:received});
 }
 valid.sort((a,b)=>a._begin-b._begin);
 const good=[];
 for(const row of valid){
   if(good.length&&row._begin-good[good.length-1]._begin<55_000)
     {fail("SOURCE_CADENCE_BELOW_55_SECONDS");continue;}
   if(good.length&&row._begin-good[good.length-1]._begin>90_000)
     fail("SOURCE_CADENCE_ABOVE_90_SECONDS");
   good.push(row);
 }
 observed.source_cycles=good.length;
 observed.saved_cycles=good.filter(r=>r.status==="D1_SAVED_SHA_VERIFIED").length;
 if(observed.saved_cycles<3)fail("THREE_D1_SNAPSHOT_WRITES_NOT_PROVEN");
 const usedReads=new Set;
 for(const row of good){
   if(row.status!=="D1_SAVED_SHA_VERIFIED")continue;
   const i=browser.findIndex((ev,index)=>{
     if(usedReads.has(index)||ev?.ok!==true||ev?.trigger!=="timer"||
        ev?.race_id!==race||ev?.ingested_at!==row.server_received_at)return false;
     const browserTime=stamp(ev.browser_at);
     return browserTime!==null&&browserTime>=row._received&&browserTime-row._received<=120_000;
   });
   if(i>=0){usedReads.add(i);observed.browser_linked_cycles++;}
 }
 if(observed.browser_linked_cycles<3)fail("THREE_SAFARI_D1_LINKED_RECEIPTS_NOT_PROVEN");
 const seen=browser.filter(x=>x?.ok===true&&x?.trigger==="timer")
  .map(x=>stamp(x.browser_at)).filter(x=>x!==null).sort((a,b)=>a-b);
 if(seen.length>=3&&seen.some((at,i)=>i>0&&(at-seen[i-1]<55_000||at-seen[i-1]>90_000)))
   fail("SAFARI_CADENCE_OUTSIDE_55_TO_90_SECONDS");
 return {status:blockers.length?"HOLD":"METADATA_CONTRACT_PASS_NEEDS_INDEPENDENT_ATTESTATION",blockers,observed,
   warning:"Caller-provided metadata is not proof of actual rights, official source, Cloudflare D1 or iPhone delivery."};
}
export {auditThreeCycles};
