/* Descriptive, separately timestamped historical samples for an unchanged race card. */
(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.RaceKeirinRiderHistory = factory();
})(typeof window === 'object' ? window : globalThis, function() {
  'use strict';
  const periods = {all:null, '3_years':36, '1_year':12, '6_months':6, '4_months':4, '3_months':3, '1_month':1};
  const labels = {all:'収録全期間', '3_years':'3年', '1_year':'1年', '6_months':'6か月', '4_months':'4か月', '3_months':'3か月', '1_month':'1か月'};
  const starts = [30, 20, 10, 5];
  const ranks = Array.from({length:9}, (_,i)=>String(i+1));
  const required = ['observed_count','missing_finish_count','finish_counts','finish_rates','first_observed_day','latest_observed_day'];
  const need = ok => { if (!ok) throw Error('KEIRIN_RIDER_HISTORY_INVALID'); };
  const exact = (value, keys) => value && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).length === keys.length && keys.every(key=>Object.hasOwn(value,key));
  const sha = v => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v);
  const registration = v => typeof v === 'string' && /^\d{6}$/.test(v) && v !== '000000';
  const count = v => Number.isSafeInteger(v) && v >= 0;
  const normalized = name => typeof name === 'string' ? name.normalize('NFKC').replace(/\s/g,'') : '';
  const admitted = new WeakSet();

  function monthsBefore(end, months) {
    const day = new Date(end+'T00:00:00Z'), number = day.getUTCDate();
    day.setUTCDate(1);
    day.setUTCMonth(day.getUTCMonth()-months+1, 0);
    day.setUTCDate(Math.min(number,day.getUTCDate()));
    return day.toISOString().slice(0,10);
  }
  function validateSample(sample, end, first, limit, day) {
    need(exact(sample, required.concat(limit ? ['unfilled_slots','tied_boundary_observations'] : ['start_day_inclusive'])));
    const n = sample.observed_count;
    need(count(n) && sample.missing_finish_count === null && exact(sample.finish_counts,ranks));
    need(ranks.every(rank=>count(sample.finish_counts[rank])) && ranks.reduce((a,rank)=>a+sample.finish_counts[rank],0)===n);
    if (n) {
      need(exact(sample.finish_rates,ranks) && ranks.every(rank=>{
        const v=sample.finish_rates[rank];
        return typeof v==='number' && v>=0 && v<=1 && Math.abs(v-sample.finish_counts[rank]/n)<=1e-12;
      }));
      need(day(sample.first_observed_day) && day(sample.latest_observed_day) &&
        sample.first_observed_day<=sample.latest_observed_day && sample.latest_observed_day<end &&
        (first===null || sample.first_observed_day>=first));
    } else {
      need(sample.finish_rates===null && sample.first_observed_day===null && sample.latest_observed_day===null);
    }
    if (limit) need(n<=limit && sample.unfilled_slots===limit-n && count(sample.tied_boundary_observations));
    else need(sample.start_day_inclusive===first);
  }
  function validateHistory(h, person, date, day) {
    need(exact(h,['registration','as_of_exclusive','periods','last_starts']) && h.registration===person.registration &&
      day(h.as_of_exclusive) && h.as_of_exclusive<=date && exact(h.periods,Object.keys(periods)) && exact(h.last_starts,starts));
    const all=h.periods.all;
    for (const [name,months] of Object.entries(periods)) {
      validateSample(h.periods[name],h.as_of_exclusive,months===null?null:monthsBefore(h.as_of_exclusive,months),null,day);
    }
    for(const n of starts) validateSample(h.last_starts[n],h.as_of_exclusive,null,n,day);
    for(const samples of [Object.keys(periods).map(name=>h.periods[name]),
                          [all,...starts.map(n=>h.last_starts[n])]]) {
      for(let i=1;i<samples.length;i++) {
        const large=samples[i-1],small=samples[i];
        need(ranks.every(r=>small.finish_counts[r]<=large.finish_counts[r]));
        if(small.observed_count) need(small.latest_observed_day===large.latest_observed_day && small.first_observed_day>=large.first_observed_day);
      }
    }
  }
  function freeze(value) {
    if(value && typeof value==='object' && !Object.isFrozen(value)) {
      Object.values(value).forEach(freeze);Object.freeze(value);
    }
    return value;
  }
  function attach(doc, rows, date, rosterSha, clock) {
    const meta=['generated_at','knowledge_as_of','source_roster_sha256','registry_sha256','archive_sha256s','predictive_model_changed'];
    need(exact(doc,['schema',...meta,'races']) && doc.schema==='RACE_AI_KEIRIN_RIDER_HISTORY_SUPPLEMENT_V1' &&
      doc.predictive_model_changed===false && clock.utc(doc.generated_at) && clock.utc(doc.knowledge_as_of) &&
      clock.instantMicros(doc.knowledge_as_of)<=clock.instantMicros(doc.generated_at) && sha(rosterSha) &&
      doc.source_roster_sha256===rosterSha && sha(doc.registry_sha256) && Array.isArray(doc.archive_sha256s) &&
      doc.archive_sha256s.length===2 && doc.archive_sha256s.every(sha) && new Set(doc.archive_sha256s).size===2 &&
      Array.isArray(doc.races) && doc.races.length<=300);
    const knowledgeDayJST=new Date(Date.parse(doc.knowledge_as_of)+9*3600000).toISOString().slice(0,10);
    const byRace=new Map(rows.map(row=>[row.id,row])),seen=new Set();
    for(const race of doc.races) {
      need(exact(race,['race_id','riders']) && byRace.has(race.race_id) && !seen.has(race.race_id));
      seen.add(race.race_id);
      const row=byRace.get(race.race_id), observed=new Set(), ids=new Set();
      need(Array.isArray(race.riders) && race.riders.length>=3 && race.riders.length===row.riders.length);
      for(const person of race.riders) {
        need(exact(person,['car','name','registration','history']) && Number.isInteger(person.car) && !observed.has(person.car) &&
          registration(person.registration) && !ids.has(person.registration) && normalized(person.name));
        const rider=row.riders.find(p=>p.number===person.car),joint=row.jointForecast?.riders.find(p=>p.car===person.car);
        need(rider && normalized(rider.name)===normalized(person.name) &&
          [rider,joint].every(p=>!p || p.registration==null || p.registration===person.registration));
        validateHistory(person.history,person,date,clock.day);
        const latest=person.history.periods.all.latest_observed_day;
        need(latest===null || latest<=knowledgeDayJST);
        observed.add(person.car);ids.add(person.registration);
      }
      const supplement=Object.fromEntries(meta.map(key=>[key,doc[key]]));
      supplement.race_id=race.race_id;supplement.riders=race.riders;
      const cutoff=clock.instantMicros(row.cutoff);
      supplement.generated_at_or_after_cutoff=cutoff!==null&&clock.instantMicros(doc.generated_at)>=cutoff;
      const snapshot=freeze(JSON.parse(JSON.stringify(supplement)));
      admitted.add(snapshot);row.riderHistory=snapshot;row.riderHistoryVersions=[];
    }
  }
  function render(row, car) {
    const s=row.riderHistory;
    if(!s || !admitted.has(s)) return '';
    const p=s.riders.find(person=>person.car===car),r=row.riders.find(person=>person.number===car);
    if(!p || !r || s.race_id!==row.id || normalized(p.name)!==normalized(r.name) ||
      (r.registration!=null && p.registration!==r.registration))return '';
    const h=p.history, all=h.periods.all;
    function sample(label,item) {
      const n=item.observed_count;
      const pct=places=>n?(100*ranks.slice(0,places).reduce((v,rank)=>v+item.finish_counts[rank],0)/n).toFixed(1)+'%':'—';
      const placeCounts=ranks.map(rank=>item.finish_counts[rank]).join(' / ');
      const dates=n?item.first_observed_day+' ～ '+item.latest_observed_day:'観測なし';
      return '<tr><th scope="row">'+label+'</th><td>'+n+'走</td><td>'+pct(1)+'</td><td>'+pct(2)+'</td><td>'+pct(3)+'</td><td>'+placeCounts+'</td><td>'+dates+'</td></tr>';
    }
    const rows=Object.keys(periods).map(key=>sample(labels[key],h.periods[key]))
      .concat(starts.map(n=>sample('直近'+n+'走',h.last_starts[n]))).join('');
    const short=all.observed_count && all.first_observed_day>h.periods['3_years'].start_day_inclusive;
    const timing=s.generated_at_or_after_cutoff?'（掲載締切後に作成）':'';
    return '<details class="kn-details kn-rider-history"><summary>長期・直近の着順履歴</summary><p>履歴の登録番号 '+p.registration+
      '。集計対象は '+h.as_of_exclusive+' より前の確認済み着順です。勝率・連対率・3連対率は各行の観測走数を分母にした実績です。</p>'+
      '<p>資料の取得基準 '+s.knowledge_as_of+' · 履歴集計の作成 '+s.generated_at+timing+'。保存済みの予測確率・買い目は別に表示します。</p>'+
      '<div class="kn-table-scroll"><table><thead><tr><th>対象</th><th>観測走数</th><th>1着</th><th>2着以内</th><th>3着以内</th><th>1～9着の件数</th><th>観測日範囲</th></tr></thead><tbody>'+rows+'</tbody></table></div>'+
      '<p>資料に含まれない出走の件数は不明です。直近の集計は確認できた着順に限り、同日の先後が判別できない境界を除きます。'+
      (short?'この選手で確認できた履歴の範囲は3年未満です。':'')+'</p></details>';
  }
  return {attach,render};
});
