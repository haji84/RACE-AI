(function(root){
  'use strict';
  // Rank/role weights express an allocation example, not fitted probabilities.
  function allocate(tickets,budget){
    if(![2000,2500,3000].includes(budget))throw new RangeError('Unsupported budget');
    if(!Array.isArray(tickets)||tickets.length<1||tickets.length>12)throw new RangeError('Invalid ticket count');
    const seen={};
    const weights=tickets.map(t=>{
      if(!['本線','押さえ','波乱'].includes(t.role))throw new TypeError('Invalid ticket role');
      const i=seen[t.role]||0;seen[t.role]=i+1;
      return ({'本線':8,'押さえ':2,'波乱':0.75}[t.role])/(1+i*0.35);
    });
    const remaining=budget/100-tickets.length;
    const total=weights.reduce((a,b)=>a+b,0);
    const raw=weights.map(w=>remaining*w/total);
    const units=raw.map(x=>1+Math.floor(x));
    let left=budget/100-units.reduce((a,b)=>a+b,0);
    const order=raw.map((v,i)=>({i,rem:v-Math.floor(v)})).sort((a,b)=>b.rem-a.rem||a.i-b.i);
    for(let j=0;j<left;j++)units[order[j].i]++;
    return units.map(x=>x*100);
  }
  function profitOdds(budget,amount){
    if(!Number.isFinite(budget)||!Number.isFinite(amount)||budget<=0||amount<=0)throw new RangeError('Positive amounts required');
    return (Math.floor(budget*10/amount)+1)/10;
  }
  function estimate(budget,amount,odds){
    if(typeof odds!=='number'||!Number.isFinite(odds)||odds<1||odds>=9999.9)return null;
    const payout=Math.round(amount*odds);
    return {payout,net:payout-budget};
  }
  const api={allocate,profitOdds,estimate};
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.KeirinStaking=api;
})(typeof window==='object'?window:globalThis);
