'use strict';
const {createHash}=require('node:crypto');
const {frozenRow}=require('./keirin_note_frozen_fixture.cjs');
const DAY='2030-01-15',RACE='203001159801';
function nationwideDoc({conditioned=false,revision='1',observed_at=DAY+'T04:00:00Z'}={}){
  const original=frozenRow();
  if(!conditioned)for(const name of ['conditioned','conditioned_cipher_sha256','conditioned_sealed_at'])original[name]=null;
  return {schema:'RACE_AI_KEIRIN_NATIONWIDE_FORECAST_VIEW_V1',day_jst:DAY,revision:revision.repeat(64),observed_at,
    registry_available:true,inventory_complete:true,missing_venues:[],disappeared_race_ids:[],races:[
      {race_id:RACE,venue_code:98,race_no:1,cutoff_at:original.baseline.published_cutoff_at,state:'A_B_AUTHENTICATED_PRE_CUTOFF',condition_state:conditioned?'CONDITIONED_AUTHENTICATED_PRE_CUTOFF':'HISTORY_SOURCE_UNAVAILABLE',original_identity:{baseline:'a'.repeat(64),conditioned:conditioned?'b'.repeat(64):null},original},
      {race_id:'203001159802',venue_code:98,race_no:2,cutoff_at:null,state:'UNSUPPORTED_CLASS_OR_ROUND',condition_state:'NO_CONDITIONED_ORIGINAL',original_identity:null,original:null},
      {race_id:'203001159803',venue_code:98,race_no:3,cutoff_at:null,state:'WAITING_SOURCE_CAPTURE',condition_state:'HISTORY_NOT_COLLECTED',original_identity:null,original:null}
    ]};
}
function nationwidePacket(doc=nationwideDoc()){
  const text=JSON.stringify(doc),raw=Buffer.from(text);
  return {schema:'RACE_AI_KEIRIN_NOTE_VIEW_V1',formal_model_admission:false,production_weight_switch:false,
    dates:[DAY],source_commit:'a'.repeat(40),imported_at:doc.observed_at,
    files:{['data/'+DAY+'/nationwide_forecasts.json']:{text,bytes:raw.length,sha256:createHash('sha256').update(raw).digest('hex')}}};
}
module.exports={DAY,RACE,nationwideDoc,nationwidePacket};
