'use strict';
/* Read-only proof against the existing private owner view. Never print its URL. */
const fs=require('node:fs'),assert=require('node:assert/strict');


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
function requireNativeGroups(context,values){
  const actual=new Set();
  for(const value of values){
    let parts;try{parts=JSON.parse(value);}catch{continue;}
    if(Array.isArray(parts)&&parts[1]==='boat'&&parts[2]==='P1')
      actual.add(JSON.stringify([parts[3]??null,parts[4]??null,parts[5]??null,parts[6]??null]));
  }
  for(const expected of context.native_groups)assert.ok(actual.has(JSON.stringify(expected)));
}

function validate(context){
  assert.equal(context.schema,'RACE_AI_PRIVATE_LIVE_SITE_CHECK_CONTEXT_V1');
  const url=new URL(context.owner_url);
  assert.equal(url.origin,'https://haji84.github.io');
  assert.equal(url.pathname,'/RACE-AI/');assert.equal(url.search,'');
  assert.equal(url.username,'');assert.equal(url.password,'');
  assert.match(url.hash,/^#saved=[a-f0-9]{64}\.[A-Za-z0-9_-]{43}$/);
  assert.match(context.day,/^\d{4}-\d{2}-\d{2}$/);
  assert.ok(Number.isSafeInteger(context.generation)&&context.generation>0);
  for(const name of ['minimum_results','native_p1_groups','old_completed'])
    assert.ok(Number.isSafeInteger(context[name])&&context[name]>=0);
  assert.ok(context.native_p1_groups>0);
  assert.ok(Number.isSafeInteger(context.day_races)&&context.day_races>=1&&context.day_races<=288);
  assert.ok(Array.isArray(context.native_groups)&&context.native_groups.length===context.native_p1_groups);
  for(const group of context.native_groups){
    assert.ok(Array.isArray(group)&&group.length===4&&typeof group[0]==='string'&&group[0].length>0);
    assert.ok(group.slice(1).every(value=>value===null||typeof value==='string'));
  }
  assert.ok(context.native_probe&&typeof context.native_probe==='object');
  if(context.old_day!==null)assert.match(context.old_day,/^\d{4}-\d{2}-\d{2}$/);
  for(const future of [context.native_probe,context.future_native].filter(Boolean)){assert.match(future.race_id,/^\d{8}-\d{2}-\d{2}$/);
    assert.ok(Number.isSafeInteger(future.index)&&future.index>=0&&future.index<32768);
    assert.ok(Number.isFinite(Date.parse(future.cutoff_at)));
  }
  return url.hash.split('.')[1];
}

async function run(context){
  const key=validate(context),{chromium}=require('playwright');
  const executablePath=['/usr/bin/google-chrome','/opt/google/chrome/google-chrome',
    '/opt/google/chrome/chrome','/usr/bin/chromium'].find(path=>fs.existsSync(path));
  assert.ok(executablePath,'installed browser required');
  const browser=await chromium.launch({headless:true,executablePath,args:['--no-sandbox']});
  let blocked=0,leaked=false,checked=0,futureVisible=false,nativeVisible=false,currentResults=0,p1Groups=0;
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
    await page.waitForFunction(()=>document.querySelector('#file-message')?.textContent.includes('保存済み予想'),{},{timeout:90000});
    await page.waitForFunction(expected=>Number(document.querySelector('#saved-view-sync')?.dataset.generation)>=expected,
      context.generation,{timeout:90000});
    async function selectDate(day){
      await page.locator('#selected-date').fill(day);await page.locator('#selected-date').dispatchEvent('change');
      await page.waitForFunction(expected=>{
        const status=document.querySelector('#saved-view-sync');
        if(status?.textContent.includes('の保存原本を読み込んでいます'))return false;
        if(!document.querySelector('#display-day')?.textContent.includes(expected))return false;
        return !status?.textContent.includes('保存履歴は日付を選んで表示できます')||status.dataset.historyDay===expected;
      },day,{timeout:90000});
    }
    for(const width of [390,1440]){
      await page.setViewportSize({width,height:1000});await selectDate(context.day);
      await page.locator('[data-page="races"]').filter({visible:true}).first().click();
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
        const target=await revealRace(page,probe.race_id,context.day_races);await target.click();
        const selected=String(probe.index);
        assert.match(await page.locator('#prediction-select option[value="'+selected+'"]').innerText(),/^P1 /);
        await page.locator('#prediction-select').selectOption(selected);
        assert.equal(await page.locator('#detail-tab-content .forecast-panel h2').first().innerText(),'取り込んだ予想');
        nativeVisible=true;
        if(context.future_native&&!futureVisible){
          assert.ok(Date.now()<Date.parse(context.future_native.cutoff_at));futureVisible=true;
        }
      }
      await page.locator('[data-page="results"]').filter({visible:true}).first().click();
      p1Groups=await page.locator('#results-model option').evaluateAll(options=>options.filter(o=>o.textContent.startsWith('P1 ')).length);
      assert.ok(p1Groups>=context.native_p1_groups);
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
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);checked++;
    }
    assert.deepEqual(errors,[]);assert.equal(leaked,false);
    assert.equal((await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).includes(key),false);
    return {schema:'RACE_AI_LIVE_SITE_CHECK_COUNTS_V1',status:'LIVE_OWNER_SITE_VERIFIED',
      verified_at:new Date().toISOString(),widths_checked:checked,
      feed_generation:Number(await page.locator('#saved-view-sync').getAttribute('data-generation')),
      current_day_results:currentResults,current_day_p1_groups:p1Groups,
      native_p1_groups_required:context.native_p1_groups,native_p1_detail_visible:nativeVisible,
      future_native_visible_before_cutoff:futureVisible,previous_day_checked:context.old_day!==null,
      participant_names:true,editable_daily_budget:true,per_race_1000_simulation:true,
      hit_miss_rate_roi_and_settled_pending_net_visible:true,
      key_in_requests_or_storage:false,blocked_external_requests:blocked,official_source_requests:0,plaintext_published:false};
  }finally{await browser.close();}
}

if(require.main===module){
  (async()=>run(JSON.parse(fs.readFileSync(process.argv[2],'utf8'))))()
    .then(report=>process.stdout.write(JSON.stringify(report)+'\n'))
    .catch(()=>{process.stdout.write(JSON.stringify({status:'LIVE_OWNER_SITE_REJECTED',reason:'SAVED_SITE_BROWSER_CHECK_FAILED'})+'\n');process.exitCode=2;});
}
module.exports={validate,requestAdmission,revealRace,requireNativeGroups,run};
