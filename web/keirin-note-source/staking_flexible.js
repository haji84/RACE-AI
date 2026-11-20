(function(root){
  'use strict';
  const base=typeof module==='object'&&module.exports?require('./staking.js'):root.KeirinStaking;
  function allocate(tickets,budget){
    if(![2000,2500,3000].includes(budget))throw new RangeError('Unsupported budget');
    if(!Array.isArray(tickets)||tickets.length<1||tickets.length>504)throw new RangeError('Invalid ticket count');
    if(tickets.length*100>budget)throw new RangeError('Budget is below 100 yen per selected ticket');
    const seen={};
    const weights=tickets.map(t=>{if(!['本線','押さえ','波乱'].includes(t.role))throw new TypeError('Invalid ticket role');const i=seen[t.role]||0;seen[t.role]=i+1;return ({'本線':8,'押さえ':2,'波乱':0.75}[t.role])/(1+i*0.35);});
    const remaining=budget/100-tickets.length,total=weights.reduce((a,b)=>a+b,0);
    const raw=weights.map(w=>remaining*w/total),units=raw.map(x=>1+Math.floor(x));
    const left=budget/100-units.reduce((a,b)=>a+b,0),order=raw.map((v,i)=>({i,rem:v-Math.floor(v)})).sort((a,b)=>b.rem-a.rem||a.i-b.i);
    for(let j=0;j<left;j++)units[order[j].i]++;
    return units.map(x=>x*100);
  }
  const api={...base,allocate,canAllocate:(tickets,budget)=>tickets.length>0&&tickets.length*100<=budget};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.KeirinStaking=api;
})(typeof window==='object'?window:globalThis);
