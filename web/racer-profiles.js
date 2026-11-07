/* Official public references and conditional course study; never writes saved predictions. */
'use strict';
(() => {
  const data = typeof module === 'object' && module.exports ? require('./racer-profiles-data.js') : globalThis.RaceRacerProfileData;
  const portraits = typeof module === 'object' && module.exports ? require('./racer-portraits.js') : globalThis.RaceRacerPortraits;
  const freeze = value => { if (value && typeof value === 'object' && !Object.isFrozen(value)) { Object.values(value).forEach(freeze); Object.freeze(value); } return value; };
  const all = freeze(data?.schema === 'RACE_AI_RACER_PROFILES_V1' && Array.isArray(data.people) ? data.people : []);
  const byId = new Map(all.map(person => [person.registration, person]));
  const minimumStarts = 10;
  function get(race, person) {
    const identity = portraits?.get(race, person), profile = identity && byId.get(identity.registration);
    return profile && profile.name === identity.name ? profile : null;
  }
  function preferredCourses(profile, {baselines = data.cohort_top2_percent} = {}) {
    const rows = (profile?.term?.courses || []).filter(c => Number.isInteger(c.starts) && c.starts >= minimumStarts && Number.isFinite(c.top2_percent));
    const adjusted = rows.map(c => ({...c, advantage: Number.isFinite(baselines?.[c.course - 1]) ? c.top2_percent - baselines[c.course - 1] : null}));
    const positive = adjusted.filter(c => c.advantage > 0).sort((a, b) => b.advantage - a.advantage || b.starts - a.starts || a.course - b.course);
    return {basis: positive.length ? 'COHORT_ADJUSTED' : rows.length ? 'WITHIN_RACER' : 'INSUFFICIENT', minimumStarts,
      courses: (positive.length ? positive : adjusted.sort((a, b) => b.top2_percent - a.top2_percent || b.starts - a.starts || a.course - b.course)).slice(0, 2)};
  }
  const position = p => {
    const values = ['number', 'lane'].filter(key => Object.hasOwn(p, key)).map(key => p[key]);
    return values.length && values.every(v => Number.isInteger(v) && v >= 1 && v <= 6 && v === values[0]) ? values[0] : null;
  };
  const withdrawn = p => p?.entry_status === 'withdrawn' || p?.withdrawn === true;
  const paths = [
    ['逃げを狙う形', 'スタートが互角で内側の優位を保てれば、先に1マークを回る形。', '外からの仕掛けや回り足次第で差される可能性もある。'],
    ['差しを狙う形', '内艇の旋回に空きができれば、その内側を差す形。', '内艇の回り方と外隣のスタートに左右される。'],
    ['まくり・まくり差しを考える形', '内側に対してスタートで優位なら外を攻め、旋回に空きがあれば差し込む形。', '内側を攻め切れない場合や外の艇に先行される場合を分けて考える。'],
    ['外からの攻めを考える形', 'ダッシュ位置を取れてスタートで優位なら、内側への攻めが選択肢になる。', '4コースというだけではカドと確定できない。スロー・ダッシュと内外の並びを確認する。'],
    ['まくり差し・展開を拾う形', '内側の攻めで生まれた空きを使って差し込む形。', '内側の艇が動かなければ距離の不利が残る。'],
    ['最外から展開を拾う形', '内側の競り合いや空いた進路を利用して追走する形。', '大外の距離があり、コース成績だけで先着を判断しない。']
  ];
  function scenario(race, person, course, {entryMap = null, referenceApi = null} = {}) {
    const lookup = referenceApi ? (race, person) => referenceApi.get(race, person) : get;
    const period = referenceApi?.period || data.period;
    const profile = lookup(race, person), empty = (status, message) => ({status, message, comparisons: []});
    if (!profile) return empty('NO_PROFILE', '登録番号と選手名を照合できません。');
    if (withdrawn(person)) return empty('WITHDRAWN', '欠場として記録されているため、このレースの展開予想は表示しません。');
    if (!Number.isInteger(course) || course < 1 || course > 6) return empty('NO_COURSE', '参考にするコースを選んでください。');
    if (!profile.term) return empty('NO_TERM', 'この選手は今回の期別資料に未収録です。基本情報は確認できます。');
    const day = race.event_date_jst, clock = typeof day === 'string' ? Date.parse(day + 'T00:00:00Z') : NaN;
    if (!Number.isFinite(clock) || new Date(clock).toISOString().slice(0, 10) !== day) return empty('DATE_UNKNOWN', '対象日を確認できないため、コース成績のみ表示します。');
    if (day <= period.end) return empty('HISTORICAL_REFERENCE', 'この集計は対象レース以降を含むため、当時の展開予想には使用しません。');
    if (referenceApi?.asOf) {
      const cutoff = typeof race.cutoff_at === 'string' ? Date.parse(race.cutoff_at) : NaN;
      if (!Number.isFinite(cutoff)) return empty('CUTOFF_UNKNOWN', '締切時刻を確認できないため、この時点の成績で展開を評価しません。');
      if (cutoff <= Date.parse(referenceApi.asOf)) return empty('HISTORICAL_REFERENCE', 'この集計は対象レースの締切以降に更新されているため、当時の展開予想には使用しません。');
    }
    const stats = profile.term.courses.find(c => c.course === course);
    if (!stats || stats.starts < minimumStarts) return empty('INSUFFICIENT', 'このコースは10走未満のため、成績から展開を評価しません。');
    const people = Array.isArray(race.participants) ? race.participants : [], positions = people.map(position);
    const references = people.map(p => lookup(race, p));
    const complete = people.length === 6 && positions.every(Number.isInteger) && new Set(positions).size === 6 &&
      references.every(Boolean) && new Set(references.map(p => p?.registration)).size === 6 && !people.some(withdrawn);
    const reported = people.filter(p => p.preview_course !== null && p.preview_course !== undefined);
    if (entryMap === null && reported.length) entryMap = Object.fromEntries(reported.map(p => [position(p), p.preview_course]));
    let mapping = null, basis = 'HYPOTHETICAL', entryStatus = 'ABSENT', entryMessage = null, status = 'READY';
    if (entryMap !== null) {
      const keys = typeof entryMap === 'object' && !Array.isArray(entryMap) ? Object.keys(entryMap) : [];
      if (!complete || !keys.length || keys.some(key => String(Number(key)) !== key || !positions.includes(Number(key)) ||
          !Number.isInteger(entryMap[key]) || entryMap[key] < 1 || entryMap[key] > 6) || new Set(Object.values(entryMap)).size !== keys.length) {
        entryStatus = 'CONFLICT'; status = 'ENTRY_CONFLICT'; entryMessage = '進入の対応を照合できないため、本人の条件別説明のみ表示し、相手との位置関係は評価しません。';
      } else if (keys.length !== 6) {
        entryStatus = 'PARTIAL'; entryMessage = '展示進入は一部のみ取得しています。全艇の並びが揃わないため、相手とのコース比較は表示しません。';
      } else {
        entryStatus = 'COMPLETE';
        if (entryMap[position(person)] === course) { mapping = entryMap; basis = 'EXHIBITION'; }
      }
    } else if (complete && position(person) === course) {
      mapping = Object.fromEntries(positions.map(lane => [lane, lane])); basis = 'FRAME_ASSUMPTION';
    }
    const comparisons = [];
    if (mapping) for (let i = 0; i < people.length; i++) {
      const lane = position(people[i]), otherCourse = mapping[lane];
      if (references[i].registration === profile.registration || Math.abs(otherCourse - course) !== 1) continue;
      const other = references[i].term?.courses.find(c => c.course === otherCourse);
      if (!other || other.starts < minimumStarts) continue;
      comparisons.push({registration: references[i].registration, name: references[i].name, course: otherCourse, stats: other,
        stDelta: Number.isFinite(stats.average_st) && Number.isFinite(other.average_st) ? stats.average_st - other.average_st : null});
    }
    const [path, condition, caution] = paths[course - 1];
    return {status, basis, entryStatus, entryMessage, course, path, condition, caution, stats, comparisons,
      message: 'コースの一般的な攻め方と公式期別成績を照らし合わせた参考シナリオです。決まり手の得意不得意や今回の着順を確定するものではありません。'};
  }
  const api = Object.freeze({all, get, preferredCourses, scenario, period: freeze(data?.period), source: freeze(data?.source), capturedAt: data?.captured_at});
  if (typeof module === 'object' && module.exports) module.exports = api;
  else globalThis.RaceRacerProfiles = api;
})();
