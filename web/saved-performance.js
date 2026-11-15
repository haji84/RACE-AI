/* Read-only observed Top8 comparison and hypothetical daily cash accounting. */
(function(root,factory){
  const api=factory(typeof module==='object'&&module.exports?require('./product-data.js'):root.RaceProductData);if(typeof module==='object'&&module.exports)module.exports=api;else root.RaceSavedPerformance=api;
})(typeof globalThis!=='undefined'?globalThis:this,(Data)=>{
  'use strict';
  const key=t=>Array.isArray(t)?t.join('-'):'';
  const ticket=t=>Array.isArray(t)&&t.length===3&&t.every(n=>Number.isInteger(n)&&n>=1&&n<=99)&&new Set(t).size===3;
  const money=n=>Number.isSafeInteger(n)&&n>=0;
  const add=(a,b)=>{const v=a+b;if(!Number.isSafeInteger(v))throw new RangeError('SIMULATION_AMOUNT_OVERFLOW');return v;};
  const multiply=(a,b)=>{const v=a*b;if(!Number.isSafeInteger(v))throw new RangeError('SIMULATION_AMOUNT_OVERFLOW');return v;};
  const predictions=r=>[r.prediction,...(r.comparison_predictions||[])].filter(Boolean);
  const codeIdentity=p=>Data?.codeIdentity ? Data.codeIdentity(p) : null;
  const facts=(row,p)=>Data?.effectivePredictionFacts ? Data.effectivePredictionFacts(row,p) : p;
  function pick(row,group){
    if(row.scope!==group.scope||row.sport!==group.sport)return null;
    const found=predictions(row).filter(p=>p.model_id===group.model_id&&p.model_version===group.model_version&&p.stage===group.stage&&(p.variant??null)===(group.variant??null)&&codeIdentity(p)===(group.code_identity??null));
    return found.length===1?found[0]:null;
  }
  function validPlan(p,row){
    const top=p?.ordered_top8;
    if(!p||p.native_top8_available===false||!Array.isArray(top)||!top.every(ticket)||new Set(top.map(key)).size!==top.length)return false;
    if(top.length===8)return true;
    if(top.length!==6||row?.sport!=='boat'||!Array.isArray(row.participants)||row.participants.length!==3)return false;
    const people=row.participants,lanes=people.map(p=>p.number),registrations=people.map(p=>p.registration_no);
    if(lanes.some(n=>!Number.isInteger(n)||n<1||n>6)||new Set(lanes).size!==3||registrations.some(r=>typeof r!=='string'||!/^\d{4}$/.test(r))||new Set(registrations).size!==3||top.some(t=>t.some(n=>!lanes.includes(n))))return false;
    const rankings=[p.ordered_candidates,p.candidates].filter(value=>value!=null);
    if(rankings.some(rows=>!Array.isArray(rows)||rows.length!==6||rows.some((item,i)=>key(Array.isArray(item)?item:item?.combination)!==key(top[i]))))return false;
    return rankings.length>0||row.roster_status==='OFFICIAL_ACTIVE'||people.every(person=>person.active===true&&person.withdrawn!==true);
  }
  function refundRule(r){
    const boats=r.refund_boats||[],combinations=r.refund_combinations||[],details=r.refunds||[];
    if(!Array.isArray(boats)||boats.some(n=>!Number.isInteger(n)||n<1||n>99)||new Set(boats).size!==boats.length||
       !Array.isArray(combinations)||!combinations.every(ticket)||new Set(combinations.map(key)).size!==combinations.length||!Array.isArray(details))return null;
    for(const d of details){
      if(!d||typeof d!=='object'||!ticket(d.combination)||d.refund_yen_per_100!==100||
         Object.keys(d).some(k=>!['combination','refund_yen_per_100','bet_type'].includes(k))||
         (d.bet_type!==undefined&&d.bet_type!=='trifecta'))return null;
    }
    const detailed=details.map(d=>key(d.combination));if(new Set(detailed).size!==detailed.length)return null;
    if(r.refund_combinations!==undefined&&r.refunds!==undefined&&JSON.stringify(combinations.map(key).sort())!==JSON.stringify([...detailed].sort()))return null;
    if(r.refund_yen>0&&!boats.length&&!combinations.length&&!details.length)return null;
    const returned=new Set([...combinations.map(key),...detailed]);
    return t=>t.some(n=>boats.includes(n))||returned.has(key(t));
  }
  function compare(row,prediction){
    const r=row.result;
    if(r?.status==='void')return {status:'VOID',matches:[]};
    if(!prediction)return {status:'NO_FORECAST',matches:[]};
    if(!validPlan(prediction,row))return {status:'REVIEW',matches:[]};
    if(!r||r.status==='pending')return {status:'PENDING',matches:[]};
    if(r.status!=='final'||!Array.isArray(r.winning_combinations)||!r.winning_combinations.length||!r.winning_combinations.every(ticket)||new Set(r.winning_combinations.map(key)).size!==r.winning_combinations.length)return {status:'REVIEW',matches:[]};
    const refunded=refundRule(r);
    if(!refunded||r.winning_combinations.some(refunded))return {status:'REVIEW',matches:[]};
    if(prediction.ordered_top8.every(refunded))return {status:'VOID',matches:[]};
    const saved=new Set(prediction.ordered_top8.map(key));
    const matches=r.winning_combinations.filter(t=>saved.has(key(t)));
    return {status:matches.length?'HIT':'MISS',matches};
  }
  function settlement(row,prediction,allocation){
    const comparison=compare(row,prediction),r=row.result;
    const hold=()=>({comparison:comparison.status,payout:null,refund:null,settled:false});
    if(comparison.status==='VOID')return {comparison:'VOID',payout:0,refund:allocation.stake,settled:true};
    if(!['HIT','MISS'].includes(comparison.status))return hold();
    const refunded=refundRule(r);if(!refunded)return hold();
    let refund=0,payout=0;
    for(const {combination:t,amount:stake} of allocation.tickets){
      if(refunded(t)){refund=add(refund,stake);continue;}
      if(!comparison.matches.some(w=>key(w)===key(t)))continue;
      let amount;
      if(r.payouts!==undefined){
        if(!Array.isArray(r.payouts))return hold();
        const found=r.payouts.filter(p=>p?.bet_type==='trifecta'&&ticket(p.combination)&&key(p.combination)===key(t));
        if(found.length!==1)return hold();amount=found[0].payout_per_100_yen;
        if(r.winning_combinations.length===1&&r.payout_yen_per_100!=null&&r.payout_yen_per_100!==amount)return hold();
      }else if(r.winning_combinations.length===1)amount=r.payout_yen_per_100;
      else return hold();
      if(!money(amount))return hold();payout=add(payout,multiply(amount,stake/100));
    }
    return {comparison:refund===allocation.stake?'VOID':comparison.status,payout,refund,settled:true};
  }
  function planReason(row,p){
    if(!p)return 'NO_UNAMBIGUOUS_SAVED_MODEL';
    const f=facts(row,p);
    if(typeof p.model_id!=='string'||!p.model_id.trim()||(!(typeof f.model_version==='string'&&f.model_version.trim())&&!codeIdentity(p)&&!f.native_evidence)||!['P0','P1','A_PRE_TRIAL','B_POST_TRIAL'].includes(p.stage))return 'MODEL_IDENTITY_UNKNOWN';
    if(!validPlan(p,row))return 'COMPLETE_TOP8_NOT_SAVED';
    if(row.offering_status==='NOT_OFFERED')return 'TRIFECTA_NOT_OFFERED';
    const cutoff=Date.parse(p.cutoff_at||row.cutoff_at),generated=Date.parse(f.generated_at),saved=Date.parse(p.persisted_at),asof=Date.parse(p.as_of);
    if(![cutoff,saved,asof].every(Number.isFinite)||!Number.isFinite(generated)&&!f.native_evidence)return 'SAVE_CLOCK_UNKNOWN';
    // An authenticated native as-of plus its physical pre-cutoff original can
    // substantiate a hypothetical plan without manufacturing generated_at.
    const allowance=f.save_clock_tolerance_ms||0;
    if(asof>saved+allowance||Number.isFinite(generated)&&(asof>generated||generated>saved+allowance)||saved>=cutoff)return 'NOT_SAVED_BEFORE_CUTOFF';
    return null;
  }
  function allocate(row,p,raceBudget=800){
    if(![800,1000].includes(raceBudget))throw new RangeError('RACE_BUDGET_INVALID');
    if(planReason(row,p))throw new Error('SAVED_PLAN_INELIGIBLE');
    const tickets=p.ordered_top8.map(t=>({combination:t.slice(),amount:100,families:0,stableFamilies:0}));
    const baseStake=tickets.length*100;
    const base={raceBudget,baseStake,stake:baseStake,held:raceBudget-baseStake,tickets,evidenceStatus:'FLAT_TOP8',decisionAt:p.persisted_at,tieRule:'NUMERIC_COMBINATION_ORDER'};
    if(raceBudget===800)return base;
    const cutoff=Date.parse(p.cutoff_at||row.cutoff_at),asof=Date.parse(p.as_of),decision=Date.parse(p.persisted_at);
    const identity=q=>JSON.stringify([q.model_id,facts(row,q).model_version,codeIdentity(q),q.stage,q.variant??null]);
    const peers=predictions(row).filter(q=>!planReason(row,q)&&q.stage===p.stage&&Date.parse(q.cutoff_at||row.cutoff_at)===cutoff&&Date.parse(q.as_of)===asof&&Date.parse(q.persisted_at)<=decision);
    const multiplicity=new Map();for(const q of peers)multiplicity.set(identity(q),(multiplicity.get(identity(q))||0)+1);
    const usable=peers.filter(q=>multiplicity.get(identity(q))===1);
    for(const item of tickets){
      const families=new Set(),versions=new Map();
      for(const q of usable)if(q.ordered_top8.some(t=>key(t)===key(item.combination))){
        families.add(q.model_id);const id=JSON.stringify([q.model_id,facts(row,q).model_version,codeIdentity(q)]);
        if(!versions.has(id))versions.set(id,{model:q.model_id,variants:new Set()});versions.get(id).variants.add(q.variant);
      }
      item.families=families.size;
      item.stableFamilies=new Set([...versions.values()].filter(v=>v.variants.has('HISTORY_BASELINE')&&v.variants.has('HISTORY_ADDED')).map(v=>v.model)).size;
    }
    const numericOrder=(a,b)=>{for(let i=0;i<3;i++)if(a.combination[i]!==b.combination[i])return a.combination[i]-b.combination[i];return 0;};
    const supported=tickets.filter(t=>t.families>=2).sort((a,b)=>b.families-a.families||b.stableFamilies-a.stableFamilies||numericOrder(a,b));
    if(!supported.length)return {...base,evidenceStatus:'ADDITIONAL_EVIDENCE_MISSING'};
    for(let i=0;i<(raceBudget-baseStake)/100;i++)supported[i%supported.length].amount+=100;
    return {...base,stake:raceBudget,held:0,evidenceStatus:'CROSS_MODEL_SUPPORT_REFERENCE'};
  }
  function summarize(records,group){
    const rows=group?records.filter(r=>r.scope===group.scope&&r.sport===group.sport):records;
    const stats={races:rows.length,available:0,hits:0,misses:0,pending:0,void:0,noForecast:0,review:0};
    const counts={HIT:'hits',MISS:'misses',PENDING:'pending',VOID:'void',NO_FORECAST:'noForecast',REVIEW:'review'};
    for(const r of rows){
      if(['final','void'].includes(r.result?.status))stats.available++;
      stats[counts[compare(r,group?pick(r,group):null).status]]++;
    }
    return stats;
  }
  function simulate(records,group,budget,{raceBudget=800}={}){
    if(!Number.isSafeInteger(budget)||budget<100||budget>10000000||budget%100)throw new RangeError('DAILY_BUDGET_INVALID');
    if(![800,1000].includes(raceBudget))throw new RangeError('RACE_BUDGET_INVALID');
    const selected=records.filter(r=>r.scope===group.scope&&r.sport===group.sport);
    if(new Set(selected.map(r=>r.race_id)).size!==selected.length)throw new Error('DUPLICATE_SAVED_RACE');
    const dates=[...new Set(selected.map(r=>r.event_date_jst))].sort(),days=[],rows=[];
    const comparison={hits:0,misses:0,pending:0,void:0,noForecast:0,review:0};
    const boughtComparison={hits:0,misses:0,pending:0,void:0,noForecast:0,review:0};
    const counts={HIT:'hits',MISS:'misses',PENDING:'pending',VOID:'void',NO_FORECAST:'noForecast',REVIEW:'review'};
    for(const day of dates){
      let remaining=budget;const d={day,budget,spent:0,reserved:0,held:0,payout:0,refund:0,settledStake:0,settledCount:0,pendingStake:0,bought:0,skippedBudget:0};
      const dated=selected.filter(r=>r.event_date_jst===day).map(r=>({row:r,p:pick(r,group)}));
      const cutoff=x=>{const n=Date.parse(x.p?.cutoff_at||x.row.cutoff_at);return Number.isFinite(n)?n:Infinity;};
      dated.sort((a,b)=>cutoff(a)-cutoff(b)||(a.row.race_id<b.row.race_id?-1:a.row.race_id>b.row.race_id?1:0));
      for(const {row:r,p} of dated){
        const observed=compare(r,p);comparison[counts[observed.status]]++;
        const reason=planReason(r,p),entry={race_id:r.race_id,day,prediction:p,comparison:observed.status,stake:0,allocation:null,payout:null,refund:null,net:null,reason};
        if(!reason&&remaining<raceBudget){entry.reason='DAILY_BUDGET_LIMIT';d.skippedBudget++;}
        else if(!reason){
          const allocation=allocate(r,p,raceBudget);entry.allocation=allocation;entry.stake=allocation.stake;
          remaining-=raceBudget;d.reserved+=raceBudget;d.held+=allocation.held;d.spent+=entry.stake;d.bought++;
          boughtComparison[counts[observed.status]]++;
          const s=settlement(r,p,allocation);
          // Settle a complete race plan together; unknown winning payouts keep
          // that whole allocated plan pending, rather than inventing a zero loss.
          if(s.settled){
            entry.payout=s.payout;entry.refund=s.refund;entry.net=add(add(s.payout,s.refund),-entry.stake);
            d.payout=add(d.payout,s.payout);d.refund=add(d.refund,s.refund);d.settledStake+=entry.stake;d.settledCount++;
          }else d.pendingStake+=entry.stake;
        }
        rows.push(entry);
      }
      d.unspent=remaining+d.held;d.settledNet=d.settledStake?add(add(d.payout,d.refund),-d.settledStake):null;
      d.net=d.pendingStake?null:add(add(d.payout,d.refund),-d.spent);d.balance=add(d.unspent,add(d.payout,d.refund));days.push(d);
    }
    const total={budgetPerDay:budget,raceBudget,budgetTotal:0,spent:0,reserved:0,held:0,unspent:0,payout:0,refund:0,settledStake:0,settledCount:0,pendingStake:0,bought:0,skippedBudget:0,balance:0};
    for(const d of days)for(const [name,source] of Object.entries({budgetTotal:'budget',spent:'spent',reserved:'reserved',held:'held',unspent:'unspent',payout:'payout',refund:'refund',settledStake:'settledStake',settledCount:'settledCount',pendingStake:'pendingStake',bought:'bought',skippedBudget:'skippedBudget',balance:'balance'}))total[name]=add(total[name],d[source]);
    total.settledNet=total.settledStake?add(add(total.payout,total.refund),-total.settledStake):null;
    total.net=total.pendingStake?null:add(add(total.payout,total.refund),-total.spent);
    total.roi=total.settledStake?(total.payout+total.refund)/total.settledStake*100:null;
    return {...total,comparison,boughtComparison,days,rows,hypothetical:true,reinvested:false};
  }
  return Object.freeze({compare,pick,simulate,summarize,allocate,planReason});
});
