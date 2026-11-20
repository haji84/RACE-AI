(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory(require('./staking.js'));
  else root.KeirinRollover=factory(root.KeirinStaking);
})(typeof window==='object'?window:globalThis,function(staking){
  'use strict';
  const budgets=[2000,2500,3000];
  const maxReceipt=100000000;

  function checkBudget(value){
    if(!budgets.includes(value))throw new RangeError('初回予算は2000・2500・3000円から選んでください。');
  }
  function checkReceipt(value){
    if(value!==null&&(!Number.isSafeInteger(value)||value<0||value>maxReceipt)){
      throw new RangeError('受取額は0〜100000000円の整数、未入力はnullにしてください。');
    }
  }
  function positiveInteger(value){
    if(!Number.isSafeInteger(value)||value<=0)throw new RangeError('正の整数の金額が必要です。');
  }

  // Receipts include refunds. Only profit may fund the second and final stage.
  function plan({initialBudget,firstReturn=null,secondReturn=null}={}){
    checkBudget(initialBudget);
    checkReceipt(firstReturn);
    checkReceipt(secondReturn);
    const base={firstStake:initialBudget,nextStake:0,reserve:0,finalReturn:null,net:null};
    if(firstReturn===null){
      return {...base,status:'awaiting_first',reason:'1戦目の受取額（払戻と返還の合計）を入力してください。'};
    }

    const profit=firstReturn-initialBudget;
    if(profit<2000){
      const reason=firstReturn===0
        ?'1戦目の受取が0円で終了。初回予算が損失になります。'
        :profit<0
          ?'1戦目は購入額を回収できず終了。返還を含む受取額で計算しています。'
          :profit===0
            ?'1戦目の受取が初回予算と同額のため、差額0円で終了します。'
            :'利益が次の最低額2,000円に届かないため終了。受取は取り分けます。';
      return {...base,status:'stopped',reserve:firstReturn,finalReturn:firstReturn,net:profit,reason};
    }

    const nextStake=profit>=3000?3000:profit>=2500?2500:2000;
    const reserve=firstReturn-nextStake;
    if(secondReturn===null){
      return {
        ...base,status:'awaiting_second',nextStake,reserve,
        reason:'元金と余剰分を取り分け、利益の範囲で2戦目へ。2戦目の受取額を入力してください。',
      };
    }
    const finalReturn=reserve+secondReturn;
    return {
      ...base,status:'completed',nextStake,reserve,finalReturn,net:finalReturn-initialBudget,
      reason:'2戦目の受取を取り分け分に加えて終了。3戦目へは進みません。',
    };
  }

  // Bounds assume one winning ticket and no refund, in 0.1-odds increments.
  function positiveBounds(total,amount){
    positiveInteger(total);
    positiveInteger(amount);
    const scaled=total*10;
    if(!Number.isSafeInteger(scaled))throw new RangeError('金額が計算可能な範囲を超えています。');
    return {breakEvenOdds:Math.ceil(scaled/amount)/10,profitOdds:(Math.floor(scaled/amount)+1)/10};
  }
  function continuationOdds(initialBudget,amount,minNext=2000){
    checkBudget(initialBudget);
    positiveInteger(minNext);
    return positiveBounds(initialBudget+minNext,amount).breakEvenOdds;
  }
  return {plan,positiveBounds,continuationOdds,allocate:staking.allocate};
});
