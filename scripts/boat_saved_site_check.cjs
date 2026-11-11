'use strict';
/* Read-only proof against the existing private owner view. Never print its URL. */
const fs=require('node:fs'),assert=require('node:assert/strict');

// Error messages and Playwright call logs can contain private owner URLs or
// saved values. Expose only the local checker location and fixed error kinds.
function browserFailure(error){
  const location=String(error?.stack||'').match(/boat_saved_site_check\.cjs:(\d+):(\d+)/);
  return {status:'LIVE_OWNER_SITE_REJECTED',reason:'SAVED_SITE_BROWSER_CHECK_FAILED',
    error_kind:['AssertionError','TimeoutError','Error'].includes(error?.name)?error.name:'Error',
    checker_line:location?Number(location[1]):null,checker_column:location?Number(location[2]):null};
}
async function assertRationaleHeading(page){
  const heading=page.locator('#race-detail').getByRole('heading',{name:'予想根拠',exact:true});
  assert.equal(await heading.count(),1);assert.equal(await heading.isVisible(),true);
}

const allowedHosts=new Set(['haji84.github.io','api.github.com','raw.githubusercontent.com']);
function requestAdmission(request,key){
  try{
    const body=request.postData()||'',details=request.url()+JSON.stringify(request.headers())+body;
    const leaked=details.includes(key),url=new URL(request.url());
    const allowed=!leaked&&!body&&['GET','HEAD'].includes(request.method())&&
      (['data:','blob:'].includes(url.protocol)||url.protocol==='https:'&&allowedHosts.has(url.hostname));
    return {allowed,leaked};
  }catch{return {allowed:false,leaked:false};}
}
async function revealRace(page,raceId,dayRaces){
  assert.match(raceId,/^\d{8}-\d{2}-\d{2}$/);
  assert.ok(Number.isSafeInteger(dayRaces)&&dayRaces>=1&&dayRaces<=288);
  const target=page.locator('#page-races [data-open-race="'+raceId+'"]');
  for(let block=0;await target.count()===0;block++){
    assert.ok(block<Math.ceil(dayRaces/60)-1);
    const more=page.getByRole('button',{name:/さらに60件表示/});
    assert.ok(await more.isVisible());await more.click();
  }
  return target;
}
function nativeStage(context){
  const stage=context.stage===undefined?'P1':context.stage;
  assert.ok(['P0','P1'].includes(stage));return stage;
}
function nativeCount(context){
  const stage=nativeStage(context),count=context.native_group_count??(stage==='P1'?context.native_p1_groups:undefined);
  assert.ok(Number.isSafeInteger(count)&&count>0);
  for(const candidate of ['P0','P1']){
    const value=context['native_'+candidate.toLowerCase()+'_groups'];
    if(value!==undefined)assert.equal(value,candidate===stage?count:0);
  }
  return count;
}
function requireNativeGroups(context,values){
  const stage=nativeStage(context);
  const actual=new Set();
  for(const value of values){
    let parts;try{parts=JSON.parse(value);}catch{continue;}
    if(Array.isArray(parts)&&parts[1]==='boat'&&parts[2]===stage)
      actual.add(JSON.stringify([parts[3]??null,parts[4]??null,parts[5]??null,parts[6]??null]));
  }
  for(const expected of context.native_groups)assert.ok(actual.has(JSON.stringify(expected)));
}
function requireNativeDetail(context,probe,detail){
  const stage=nativeStage(context);
  assert.match(detail.label,new RegExp('^'+stage+' '));
  assert.equal(detail.nativeDispatch,stage==='P1'?'true':'false');
  if(stage==='P0'){
    assert.equal(probe.stage,stage);assert.equal(detail.modelId,probe.model_id);
    assert.equal(require('node:crypto').createHash('sha256').update(JSON.stringify(detail.tickets)).digest('hex'),probe.tickets_sha256);
  }
}
function requireExpectedOriginal(context,probe){
  const expected=context.expected_original;
  if(expected===undefined)return;
  assert.equal(nativeStage(context),'P0');
  assert.deepEqual(Object.keys(expected).sort(),['day_jst','json_sha256','original_id','source_sha']);
  assert.equal(expected.day_jst,context.day);
  assert.ok(Number.isSafeInteger(expected.original_id)&&expected.original_id>0);
  assert.match(expected.json_sha256,/^[a-f0-9]{64}$/);assert.match(expected.source_sha,/^[a-f0-9]{40}$/);
  assert.equal(probe.artifact_id,expected.original_id);
  assert.equal(probe.original_json_sha256,expected.json_sha256);
  assert.equal(probe.source_code_commit,expected.source_sha);
}
function requireNativeAudit(context,probe,audit){
  assert.equal(nativeStage(context),'P0');assert.equal(audit.stage,'P0');
  requireExpectedOriginal(context,probe);
  assert.equal(audit.modelId,probe.model_id);
  for(const [label,expected] of [['原本artifact ID',String(probe.artifact_id)],
    ['原本JSON SHA',probe.original_json_sha256],['予想SHA',probe.prediction_sha256],
    ['モデル / 学習物SHA',probe.model_sha256],['保存コードのコミット',probe.source_code_commit]]){
    const matches=audit.fields.filter(pair=>pair[0]===label);
    assert.equal(matches.length,1);assert.equal(matches[0][1],expected);
  }
}

function validate(context){
  assert.equal(context.schema,'RACE_AI_PRIVATE_LIVE_SITE_CHECK_CONTEXT_V1');
  const stage=nativeStage(context),groupCount=nativeCount(context);
  const url=new URL(context.owner_url);
  assert.equal(url.origin,'https://haji84.github.io');
  assert.equal(url.pathname,'/RACE-AI/');assert.equal(url.search,'');
  assert.equal(url.username,'');assert.equal(url.password,'');
  assert.match(url.hash,/^#saved=[a-f0-9]{64}\.[A-Za-z0-9_-]{43}$/);
  assert.match(context.day,/^\d{4}-\d{2}-\d{2}$/);
  dateEvidence(context,0,0);
  assert.ok(Number.isSafeInteger(context.generation)&&context.generation>0);
  for(const name of ['minimum_results','old_completed'])
    assert.ok(Number.isSafeInteger(context[name])&&context[name]>=0);
  assert.ok(Number.isSafeInteger(context.day_races)&&context.day_races>=1&&context.day_races<=288);
  assert.ok(Array.isArray(context.native_groups)&&context.native_groups.length===groupCount);
  for(const group of context.native_groups){
    assert.ok(Array.isArray(group)&&group.length===4&&typeof group[0]==='string'&&group[0].length>0);
    assert.ok(group.slice(1).every(value=>value===null||typeof value==='string'));
  }
  assert.ok(context.native_probe&&typeof context.native_probe==='object');
  if(context.old_day!==null)assert.match(context.old_day,/^\d{4}-\d{2}-\d{2}$/);
  for(const future of [context.native_probe,context.future_native].filter(Boolean)){assert.match(future.race_id,/^\d{8}-\d{2}-\d{2}$/);
    assert.ok(Number.isSafeInteger(future.index)&&future.index>=0&&future.index<32768);
    assert.ok(Number.isFinite(Date.parse(future.cutoff_at)));
    if(stage==='P0'||future.stage!==undefined)assert.equal(future.stage,stage);
    if(stage==='P0'){
      assert.ok(typeof future.model_id==='string'&&future.model_id.length>0&&future.model_id.length<=256);
      assert.ok(Number.isSafeInteger(future.artifact_id)&&future.artifact_id>0);
      for(const field of ['tickets_sha256','original_json_sha256','prediction_sha256','model_sha256'])assert.match(future[field],/^[a-f0-9]{64}$/);
      assert.equal(future.prediction_sha256,future.model_sha256);assert.match(future.source_code_commit,/^[a-f0-9]{40}$/);
    }
    requireExpectedOriginal(context,future);
  }
  return url.hash.split('.')[1];
}

function dateEvidence(context,results,nativeGroups,lifecycleDay){
  const stage=nativeStage(context),prefix=stage.toLowerCase();
  const valid=day=>typeof day==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(day)&&
    Number.isFinite(Date.parse(day+'T00:00:00Z'))&&new Date(day+'T00:00:00Z').toISOString().slice(0,10)===day;
  const current=context.current_day??context.day;
  assert.ok(valid(context.day)&&valid(current)&&context.day<=current);
  if(lifecycleDay!==undefined)assert.equal(lifecycleDay,current,'lifecycle date changed during verification');
  const scope=context.day===current?'CURRENT_DAY':'HISTORICAL_DAY';
  if(context.date_scope!==undefined)assert.equal(context.date_scope,scope);
  assert.ok(Number.isSafeInteger(results)&&results>=0&&Number.isSafeInteger(nativeGroups)&&nativeGroups>=0);
  return {checked_day:context.day,current_day:current,date_scope:scope,
    stage,checked_day_native_groups:nativeGroups,
    current_day_native_groups:scope==='CURRENT_DAY'?nativeGroups:null,
    checked_day_results:results,['checked_day_'+prefix+'_groups']:nativeGroups,
    current_day_results:scope==='CURRENT_DAY'?results:null,
    ['current_day_'+prefix+'_groups']:scope==='CURRENT_DAY'?nativeGroups:null};
}

async function run(context,{compactResults=false,probeRaceId=null,checkCurrentDay=false,checkBeforeinfo=false}={}){
  const key=validate(context),{chromium}=require('playwright');
  const stage=nativeStage(context),groupCount=nativeCount(context);
  // P0 proof uses the existing compact-result research audit to bind the
  // exact original receipt, not just another original with matching tickets.
  assert.ok(stage==='P1'||compactResults);
  if(checkBeforeinfo){assert.ok(context.live_beforeinfo_races>0);assert.match(context.live_beforeinfo_probe?.race_id,/^\d{8}-\d{2}-\d{2}$/);assert.ok(Number.isFinite(Date.parse(context.live_beforeinfo_probe.cutoff_at)));}
  let beforeinfoViews=0,beforeinfoTimes=0;
  let modelSwitchViews=0,modelSwitchOriginals=0;
  const modelProbe=context.model_switch_probe;
  if(modelProbe){assert.match(modelProbe.race_id,/^\d{8}-\d{2}-\d{2}$/);assert.ok(Number.isFinite(Date.parse(modelProbe.cutoff_at)));assert.equal(modelProbe.choices.length,2);assert.notEqual(modelProbe.choices[0].model_id,modelProbe.choices[1].model_id);for(const p of modelProbe.choices){assert.ok(Number.isSafeInteger(p.index)&&p.index>=0);assert.match(p.tickets_sha256,/^[a-f0-9]{64}$/);}}
  if(probeRaceId){assert.match(probeRaceId,/^\d{8}-\d{2}-\d{2}$/);assert.equal(probeRaceId.slice(0,8),context.day.replaceAll('-',''));}
  const executablePath=['/usr/bin/google-chrome','/opt/google/chrome/google-chrome',
    '/opt/google/chrome/chrome','/usr/bin/chromium'].find(path=>fs.existsSync(path));
  assert.ok(executablePath,'installed browser required');
  const browser=await chromium.launch({headless:true,executablePath,args:['--no-sandbox']});
  let blocked=0,leaked=false,checked=0,futureVisible=false,nativeVisible=false,currentResults=0,nativeGroups=0,rationaleViewsChecked=0,upcomingRowsChecked=0,venueResultsChecked=0,currentDayLifecycleViews=0,currentDayUpcomingRows=0,currentDayUpcomingCount=null,currentDayClosedCount=null,currentDayPendingCount=null;
  try{
    const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];
    page.setDefaultTimeout(45000);
    page.on('pageerror',error=>errors.push(error.name));
    page.on('request',request=>{if((request.url()+JSON.stringify(request.headers())).includes(key))leaked=true;});
    await page.route('**/*',route=>{
      const admission=requestAdmission(route.request(),key);
      if(admission.leaked)leaked=true;
      if(admission.allowed)return route.continue();
      blocked++;return route.abort('blockedbyclient');
    });
    await page.goto(context.owner_url,{waitUntil:'domcontentloaded'});
    let currentPresentation=false;
    for(let attempt=0;attempt<5;attempt++){
      if(attempt){await page.waitForTimeout(10000);await page.reload({waitUntil:'domcontentloaded'});}
      await page.waitForFunction(()=>document.querySelector('#file-message')?.textContent.includes('保存済み予想'),{},{timeout:90000});
      const selection=await page.evaluate(()=>({ids:globalThis.RaceExistingModelCatalog?.models.map(m=>m.model_id),
        retired:globalThis.RaceExistingModelCatalog?.retired_model_ids || []}));
      currentPresentation=selection.ids?.length===15 && !selection.ids.includes('seller-shadow-v1-20261104')
        && selection.retired.includes('seller-shadow-v1-20261104');
      if(currentPresentation)break;
      // Only the exact known old presentation may wait for Pages deployment.
      assert.ok(selection.ids?.length===16 && selection.ids.includes('seller-shadow-v1-20261104')
        && selection.retired.length===0,'unexpected presentation selection');
    }
    assert.ok(currentPresentation,'retired seller still present in deployed assets');
    await page.waitForFunction(expected=>Number(document.querySelector('#saved-view-sync')?.dataset.generation)>=expected,
      context.generation,{timeout:compactResults?360000:90000});
    async function selectDate(day){
      await page.locator('#selected-date').fill(day);await page.locator('#selected-date').dispatchEvent('change');
      await page.waitForFunction(expected=>{
        const status=document.querySelector('#saved-view-sync');
        if(status?.textContent.includes('の保存原本を読み込んでいます'))return false;
        if(!document.querySelector('#display-day')?.textContent.includes(expected))return false;
        return !status?.textContent.includes('保存履歴は日付を選んで表示できます')||status.dataset.historyDay===expected;
      },day,{timeout:90000});
    }
    for(const width of compactResults?[320,390,1440]:[390,1440]){
      await page.setViewportSize({width,height:1000});await selectDate(context.day);
      await page.locator('[data-page="races"]').filter({visible:true}).first().click();
      if(await page.locator('#all-venues').isVisible())await page.locator('#all-venues').click();
      await page.locator('[data-race-view="upcoming"]').click();
      const upcoming=await page.locator('#all-races [data-cutoff-at]').evaluateAll(nodes=>nodes.map(n=>({at:Date.parse(n.dataset.cutoffAt),phase:n.dataset.racePhase})));
      for(const value of upcoming){assert.equal(value.phase,'upcoming');assert.ok(value.at>Date.now());}for(let i=1;i<upcoming.length;i++)assert.ok(upcoming[i-1].at<=upcoming[i].at);upcomingRowsChecked+=upcoming.length;
      if(context.day<context.current_day)assert.equal(upcoming.length,0);
      await page.locator('[data-race-view="results"]').click();
      if(context.minimum_results)assert.ok(await page.locator('#all-races .race-result-card').count()>0);
      if(await page.locator('#all-races .race-result-card').count()){
        const venue=await page.locator('#all-races .race-result-card').first().getAttribute('data-venue');
        await page.locator('#venue-buttons [data-venue]').filter({has:page.getByText(venue,{exact:true})}).first().click();
        assert.equal(await page.locator('#venue-filter').inputValue(),venue);
        assert.ok((await page.locator('#all-races .race-result-card').evaluateAll((nodes,v)=>nodes.every(n=>n.dataset.venue===v),venue)));
        await page.locator('[data-race-view="upcoming"]').click();assert.equal(await page.locator('#venue-filter').inputValue(),venue);
        await page.locator('[data-race-view="results"]').click();assert.equal(await page.locator('#venue-filter').inputValue(),venue);venueResultsChecked++;
        await page.locator('#all-venues').click();
      }
      if(!await page.locator('#page-races [data-open-race]').count())await page.locator('[data-race-view="upcoming"]').click();
      await page.locator('#page-races [data-open-race]').first().click();
      const grid=page.locator('#detail-tab-content .racer-grid[data-entrants]');
      assert.equal(await grid.count(),1);
      const entrants=Number(await grid.getAttribute('data-entrants'));
      assert.ok(entrants>=3&&entrants<=6);
      assert.equal(await page.locator('#detail-tab-content .placeholder-entrants').count(),0);
      const names=await grid.locator('.racer-name').allTextContents();
      assert.equal(names.length,entrants);
      for(const name of names){
        assert.ok(name.trim().length>0);
        assert.doesNotMatch(name,/(?:名前|出走者)\s*未取得|^\s*(?:選手\s*)?\d+\s*$/);
      }
      assert.ok(await page.locator('#prediction-select option').count()>=2);
      {
        const probe=context.future_native||context.native_probe;
        await page.locator('[data-page="races"]').filter({visible:true}).first().click();
        await page.locator('[data-race-view="'+(Date.now()<Date.parse(probe.cutoff_at)?'upcoming':'results')+'"]').click();
        const target=await revealRace(page,probe.race_id,context.day_races);await target.click();
        const selected=String(probe.index);
        const label=await page.locator('#prediction-select option[value="'+selected+'"]').innerText();
        await page.locator('#prediction-select').selectOption(selected);
        const panel=page.locator('#detail-tab-content .forecast-panel').first();
        requireNativeDetail(context,probe,{label,nativeDispatch:await panel.getAttribute('data-native-dispatch'),
          modelId:await panel.getAttribute('data-model-id'),tickets:stage==='P0'?await panel.locator('.saved-ticket .combo')
            .evaluateAll(nodes=>nodes.map(node=>[...node.querySelectorAll('.lane')].map(n=>Number(n.textContent)))):null});
        nativeVisible=true;
        if(context.future_native&&!futureVisible){
          assert.ok(Date.now()<Date.parse(context.future_native.cutoff_at));futureVisible=true;
        }
      }
      if(compactResults){
        if(probeRaceId){await page.locator('[data-page="races"]').filter({visible:true}).first().click();await page.locator('[data-race-view="results"]').click();await (await revealRace(page,probeRaceId,context.day_races)).click();await page.locator('#prediction-select').selectOption('0');}
        assert.equal(await page.locator('.race-result-summary').isVisible(),true);
        if(probeRaceId)assert.match(await page.locator('.race-result-summary .saved-outcome').innerText(),/的中|不的中/);
        const normal=await page.locator('#race-detail').innerText();assert.doesNotMatch(normal,/SAVED FORECAST|PRIVATE_CYCLE|INDEPENDENT_RECEIPT|予想SHA/);
        assert.equal(await page.locator('#race-detail .forecast-panel').count(),1);assert.equal(await page.locator('#race-detail .race-audit-details').count(),0);
        const expectedRace=probeRaceId||(context.future_native||context.native_probe).race_id;
        const selected=await page.locator('#prediction-select').inputValue(),modelId=await page.locator('#race-detail .forecast-panel').getAttribute('data-model-id');
        const rationale=await page.locator('#race-detail .forecast-rationale').count()?await page.locator('#race-detail .forecast-rationale').innerText():null;
        await page.locator('[data-page="research"]').filter({visible:true}).first().click();
        const audit=page.locator('#research-race-audit');assert.equal(await audit.isVisible(),true);assert.equal(await page.locator('#research-race-select').inputValue(),expectedRace);assert.equal(await page.locator('#research-prediction-select').inputValue(),selected);
        assert.equal(await audit.locator('.race-audit-details').evaluate(n=>n.tagName),'SECTION');assert.equal(await audit.locator('.race-audit-details').getAttribute('data-model-id'),modelId);assert.match(await audit.innerText(),/予想SHA/);
        if(stage==='P0'){
          const probe=context.future_native||context.native_probe;
          assert.equal(expectedRace,probe.race_id);assert.equal(selected,String(probe.index));
          const details=audit.locator('.race-audit-details');
          requireNativeAudit(context,probe,{stage:await details.getAttribute('data-prediction-stage'),
            modelId:await details.getAttribute('data-model-id'),fields:await details.locator('.race-audit-body > dl.provenance').first()
              .evaluate(dl=>[...dl.querySelectorAll('dt')].map(dt=>[dt.textContent,dt.nextElementSibling?.textContent]))});
        }
        await audit.locator('[data-return-to-race]').click();assert.equal(await page.locator('#prediction-select').inputValue(),selected);
        assert.equal(await page.locator('#race-detail .forecast-rationale').count()?await page.locator('#race-detail .forecast-rationale').innerText():null,rationale);
        if(rationale){await assertRationaleHeading(page);rationaleViewsChecked++;}

      }
      assert.match(await page.locator('[data-page="results"]').filter({visible:true}).first().innerText(),/AI予想結果/);
      await page.locator('[data-page="results"]').filter({visible:true}).first().click();
      nativeGroups=await page.locator('#results-model option').evaluateAll((options,phase)=>options.filter(o=>o.textContent.startsWith(phase+' ')).length,stage);
      assert.ok(nativeGroups>=groupCount);
      requireNativeGroups(context,await page.locator('#results-model option').evaluateAll(options=>options.map(option=>option.value)));
      const metrics=await page.locator('#saved-result-metrics').innerText();
      currentResults=Number(metrics.match(/取得結果\s*(\d+)レース/)?.[1]);
      assert.ok(currentResults>=context.minimum_results);
      for(const label of ['的中','不的中','保存Top8的中率','結果待ち'])assert.ok(metrics.includes(label));
      for(const budget of ['10000','5000']){
        await page.locator('#simulation-budget').fill(budget);await page.locator('#simulation-budget').dispatchEvent('change');
        await page.locator('#simulation-race-budget').selectOption('1000');
        assert.equal(await page.locator('#simulation-budget').inputValue(),budget);
        const simulation=await page.locator('#simulation-metrics').innerText();
        for(const label of ['確定分の収支','確定分の回収率','未確定購入額','全体の収支'])assert.ok(simulation.includes(label));
        assert.doesNotMatch(simulation,/試算を表示できません/);
      }
      if(context.old_day){
        await selectDate(context.old_day);await page.locator('[data-page="results"]').filter({visible:true}).first().click();
        const old=Number((await page.locator('#saved-result-metrics').innerText()).match(/取得結果\s*(\d+)レース/)?.[1]);
        assert.ok(old>=context.old_completed);
      }
      if(checkCurrentDay){
        await selectDate(context.current_day);
        await page.locator('[data-page="races"]').filter({visible:true}).first().click();
        if(await page.locator('#all-venues').isVisible())await page.locator('#all-venues').click();
        await page.locator('[data-race-view="upcoming"]').click();
        const visible=await page.locator('#all-races [data-cutoff-at]').evaluateAll(nodes=>nodes.map(n=>({at:Date.parse(n.dataset.cutoffAt),label:n.innerText})));
        for(const row of visible){assert.ok(row.at>Date.now());assert.doesNotMatch(row.label,/結果待ち/);}
        currentDayUpcomingRows+=visible.length;
        const count=async view=>Number((await page.locator('[data-race-view="'+view+'"]').innerText()).match(/（(\d+)）/)?.[1]);
        currentDayUpcomingCount=await count('upcoming');currentDayClosedCount=await count('results');
        assert.ok(Number.isSafeInteger(currentDayUpcomingCount)&&Number.isSafeInteger(currentDayClosedCount));
        if(currentDayUpcomingCount>0)assert.ok(visible.length>0);
        await page.locator('[data-page="results"]').filter({visible:true}).first().click();
        const metric=label=>page.locator('#saved-result-metrics .metric').filter({has:page.getByText(label,{exact:true})}).locator('strong');
        assert.equal(await metric('レース前').innerText(),currentDayUpcomingCount+'レース');
        currentDayPendingCount=Number((await metric('結果待ち').innerText()).match(/^(\d+)レース$/)?.[1]);
        assert.ok(Number.isSafeInteger(currentDayPendingCount)&&currentDayPendingCount<=currentDayClosedCount);
        if(!currentDayClosedCount){assert.equal(currentDayPendingCount,0);assert.equal(await page.locator('#saved-results-table .result-mobile-card').count(),0);}
        assert.equal(await page.locator('#saved-results-table .outcome-upcoming').count(),0);currentDayLifecycleViews++;
      }
      if(checkBeforeinfo){
        await selectDate(context.day);await page.locator('[data-page="races"]').filter({visible:true}).first().click();
        if(await page.locator('#all-venues').isVisible())await page.locator('#all-venues').click();
        const probe=context.live_beforeinfo_probe;
        await page.locator('[data-race-view="'+(Date.parse(probe.cutoff_at)>Date.now()?'upcoming':'results')+'"]').click();
        await (await revealRace(page,probe.race_id,context.day_races)).click();await page.locator('[data-detail-tab="preview"]').click();
        const live=page.locator('#live-beforeinfo');assert.equal(await live.isVisible(),true);assert.equal(await live.locator('.preview-boat').count(),6);
        const values=await live.locator('.preview-metrics div').filter({has:page.getByText('展示タイム',{exact:true})}).locator('dd').allTextContents();
        const count=values.filter(value=>/^\d+\.\d+$/.test(value.trim())).length;assert.ok(count>0);beforeinfoTimes+=count;
        assert.ok(await live.locator('.weather-panel').count()>0);assert.match(await live.innerText(),/公式情報の取得/);
        assert.doesNotMatch(await page.locator('#detail-tab-content').innerText(),/保存予想原本の気象・直前情報は未取得|元ページSHA/);beforeinfoViews++;
      }
      if(modelProbe){
        await selectDate(context.day);await page.locator('[data-page="races"]').filter({visible:true}).first().click();
        if(await page.locator('#all-venues').isVisible())await page.locator('#all-venues').click();
        await page.locator('[data-race-view="'+(Date.parse(modelProbe.cutoff_at)>Date.now()?'upcoming':'results')+'"]').click();
        await (await revealRace(page,modelProbe.race_id,context.day_races)).click();await page.locator('[data-detail-tab="outlook"]').click();
        // Bind each model to its expected stored version, then exercise only
        // the model selector. The original picker must not mask a broken switch.
        for(const choice of modelProbe.choices)await page.locator('#prediction-select').selectOption(String(choice.index));
        for(const choice of modelProbe.choices){
          await page.locator('#detail-model-select').selectOption(choice.model_id);
          assert.equal(await page.locator('#prediction-select').inputValue(),String(choice.index));
          const panel=page.locator('#detail-tab-content .forecast-panel');assert.equal(await panel.getAttribute('data-model-id'),choice.model_id);
          const tickets=await panel.locator('.saved-ticket .combo').evaluateAll(nodes=>nodes.map(node=>[...node.querySelectorAll('.lane')].map(n=>Number(n.textContent))));
          assert.equal(require('node:crypto').createHash('sha256').update(JSON.stringify(tickets)).digest('hex'),choice.tickets_sha256);modelSwitchOriginals++;
        }
        await page.locator('[data-page="research"]').filter({visible:true}).first().click();
        assert.equal(await page.locator('#research-model-select').inputValue(),modelProbe.choices[1].model_id);
        await page.locator('#research-race-audit [data-return-to-race]').click();assert.equal(await page.locator('#detail-model-select').inputValue(),modelProbe.choices[1].model_id);modelSwitchViews++;
      }
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);checked++;
    }
    assert.deepEqual(errors,[]);assert.equal(leaked,false);
    assert.equal((await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).includes(key),false);
    const verifiedAt=new Date(),currentDay=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo'}).format(verifiedAt);
    return {schema:'RACE_AI_LIVE_SITE_CHECK_COUNTS_V1',status:'LIVE_OWNER_SITE_VERIFIED',
      verified_at:verifiedAt.toISOString(),widths_checked:checked,
      feed_generation:Number(await page.locator('#saved-view-sync').getAttribute('data-generation')),
      ...dateEvidence({...context,current_day:currentDay,date_scope:undefined},currentResults,nativeGroups,checkCurrentDay?context.current_day:undefined),
      lifecycle_checked_day:checkCurrentDay?context.current_day:null,
      selected_saved_day:context.day,current_day_lifecycle_views_checked:currentDayLifecycleViews,current_day_upcoming_rows_checked:currentDayUpcomingRows,current_day_upcoming_races:currentDayUpcomingCount,current_day_closed_races:currentDayClosedCount,current_day_pending_result_races:currentDayPendingCount,race_lifecycle_tabs_verified:true,upcoming_rows_checked:upcomingRowsChecked,venue_result_views_checked:venueResultsChecked,ai_results_navigation_verified:true,compact_result_ui_verified:compactResults,research_audit_verified:compactResults,available_rationale_preserved:compactResults,rationale_views_checked:rationaleViewsChecked,probe_result_matched:Boolean(compactResults&&probeRaceId),
      native_groups_required:groupCount,native_detail_visible:nativeVisible,
      ['native_'+stage.toLowerCase()+'_groups_required']:groupCount,['native_'+stage.toLowerCase()+'_detail_visible']:nativeVisible,
      ...(stage==='P0'?{native_original_audit_verified:true,expected_original_matched:context.expected_original!==undefined}:{}),
      future_native_visible_before_cutoff:futureVisible,previous_day_checked:context.old_day!==null,
      active_model_families:15,removed_seller_hidden:true,
      live_beforeinfo_views_checked:beforeinfoViews,live_beforeinfo_times_checked:beforeinfoTimes,
      model_switch_views_checked:modelSwitchViews,model_switch_originals_checked:modelSwitchOriginals,
      participant_names:true,editable_daily_budget:true,per_race_1000_simulation:true,
      hit_miss_rate_roi_and_settled_pending_net_visible:true,
      key_in_requests_or_storage:false,blocked_external_requests:blocked,official_source_requests:0,plaintext_published:false};
  }finally{await browser.close();}
}

if(require.main===module){
  (async()=>run(JSON.parse(fs.readFileSync(process.argv[2],'utf8')),{compactResults:process.argv.includes('--compact-results'),checkCurrentDay:process.argv.includes('--check-current-day'),checkBeforeinfo:process.argv.includes('--check-beforeinfo'),probeRaceId:process.argv.find(v=>v.startsWith('--race-id='))?.slice(10)||null}))()
    .then(report=>process.stdout.write(JSON.stringify(report)+'\n'))
    .catch(error=>{process.stdout.write(JSON.stringify(browserFailure(error))+'\n');process.exitCode=2;});
}
module.exports={validate,dateEvidence,requestAdmission,revealRace,requireNativeGroups,requireNativeDetail,requireNativeAudit,browserFailure,assertRationaleHeading,run};
