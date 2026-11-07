/* UI-only invented races and values. Named illustrations prove identity, never real racing statistics. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../web'),section=process.env.EXPLORER_SECTION||'all';
const entries=[['3415','松井繁'],['3897','白井英治'],['3941','池田浩二'],['4238','毒島誠'],['4320','峰竜太'],['4444','桐生順平']];
const first={race_id:'20300101-03-01',sport:'boat',venue:'場コード03',race_no:1,event_date_jst:'2030-01-01',
  cutoff_at:'2030-01-01T10:00:00+09:00',offering_status:'TRIFECTA_OFFERED',scope:'research',
  source_provenance:'UI_TEST_ONLY_INVENTED_STATS_NOT_REAL_RACES',source_sha256:'a'.repeat(64),
  observed_at:'2030-01-01T09:00:00+09:00',prediction:null,result:null,
  no_forecast_reason:'画面確認用の架空レース・数値です。実際の出走表や成績ではありません。',
  participants:entries.map(([registration_no,name],i)=>({number:i+1,registration_no,name,grade:'A1',branch:'テスト支部',
    national_win_rate:i===0?0:6.25,local_win_rate:5.55,average_st:i===0?0:0.15,motor_no:10+i,boat_no:20+i,motor_top2_rate:0}))};
const fixture={schema:'RACE_AI_FORECAST_AUDIT_V1',dataset_status:'REAL_REPORTED',records:[first]};
let browser,server,dailyData=null;
(async()=>{
  const errors=[],requests=[];
  server=http.createServer((req,res)=>{
    const relative=new URL(req.url,'http://localhost').pathname.replace(/^\/RACE-AI\//,'/'),file=path.resolve(root,'.'+(relative==='/'?'/index.html':relative));
    if(relative==='/data/racer-daily.json'&&dailyData){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(dailyData));}
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.statusCode=404;return res.end();}
    res.setHeader('Content-Type',{'.js':'text/javascript','.css':'text/css','.html':'text/html','.json':'application/json','.webp':'image/webp'}[path.extname(file)]||'application/octet-stream');
    res.end(fs.readFileSync(file));
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const base=process.env.EXPLORER_DEPLOYED_URL||`http://127.0.0.1:${server.address().port}/RACE-AI/`;
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
  const evidence=path.resolve(process.env.UI_EXPLORER_EVIDENCE||'artifacts/ui-explorer');fs.mkdirSync(evidence,{recursive:true});
  for(const width of [320,390,1440]){
    const context=await browser.newContext({viewport:{width,height:900}}),page=await context.newPage();
    page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
    await page.addInitScript(testWidth=>{if(!localStorage.getItem('race-ai-display-v1'))localStorage.setItem('race-ai-display-v1',testWidth===390?'null':JSON.stringify({favoriteVenues:[null,42,{},'not-a-venue']}));},width);
    await page.clock.install({time:new Date('2030-01-01T00:30:00Z')});await page.goto(base);
    assert.ok(await page.locator('#home-venues [data-venue]').count()>0,'invalid saved preferences must not prevent browsing');
    const nav=name=>page.locator(`[data-page="${name}"]`).filter({visible:true}).first().click();
    const load=async data=>{
      await page.evaluate(()=>document.getElementById('file-message').textContent='');
      await page.locator('#selected-date').fill(data.records[0].event_date_jst);await page.locator('#selected-date').dispatchEvent('change');
      await page.locator('#race-file').setInputFiles({name:'invented-explorer-ui.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(data))});
      await page.waitForFunction(()=>document.querySelector('#file-message').textContent.length>0);
      await nav('home');await page.locator('#page-home .racer-card').first().waitFor();
    };
    if(!process.env.EXPLORER_DEPLOYED_URL&&(section==='all'||section==='daily')){
      dailyData=require('./racer_daily_fixture.cjs').fixture();
      assert.equal(await page.evaluate(()=>typeof globalThis.RaceRacerDaily?.load),'function','daily results must load without research JSON input');
      await page.evaluate(()=>RaceRacerDaily.load({refresh:true}));await load(fixture);
      await page.locator('#page-home [data-open-participant="4320"]').click();
      const daily=page.locator('#racer-daily-reference');assert.equal(await daily.locator('.daily-course').count(),6);
      assert.match(await daily.innerText(),/90日/);assert.match(await daily.innerText(),/40\.0%/);assert.match(await daily.innerText(),/89.*90/s);
      await daily.locator('[data-daily-course="6"]').click();assert.match(await daily.locator('.daily-scenario').innerText(),/20走/);
      dailyData.model_inputs_changed=true;await page.evaluate(()=>RaceRacerDaily.load({refresh:true}));
      assert.match(await daily.innerText(),/前回の集計/);assert.match(await daily.innerText(),/40\.0%/);
      await page.keyboard.press('Escape');const synthetic=structuredClone(fixture);synthetic.dataset_status='SYNTHETIC_ONLY';await load(synthetic);
      await page.locator('#page-home [data-open-participant="4320"]').click();assert.equal(await page.locator('#racer-daily-reference').count(),0);await page.keyboard.press('Escape');
      dailyData=null;await page.reload();
      console.log(`PASS daily athlete reference ${width}px: automatic fetch, real-course sample display, gap disclosure, stale preservation and synthetic isolation`);
    }
    await load(fixture);
    if(section==='all'||section==='reference'){
      const sparse=structuredClone(fixture);
      sparse.records[0].participants=sparse.records[0].participants.map(({number,registration_no,name})=>({number,registration_no,name}));
      await load(sparse);await page.locator('#page-home [data-open-participant="4320"]').click();
      const reference=page.locator('#racer-reference');
      assert.equal(await reference.count(),1,'a sparse production-style participant must receive actual official athlete information');
      assert.match(await reference.innerText(),/8\.05/);assert.match(await reference.innerText(),/105/);
      assert.match(await reference.innerText(),/2025-11-01.*2026-04-30/s);assert.match(await reference.innerText(),/佐賀/);
      assert.match(await reference.locator('.reference-basic').innerText(),/登録番号\s*4320/);
      assert.equal(await reference.locator('.reference-course').count(),6);
      await page.screenshot({path:path.join(evidence,`official-reference-top-${width}.png`)});
      await reference.locator('[data-study-course="4"]').click();
      const scenario=reference.locator('.reference-scenario');assert.match(await scenario.innerText(),/19走/);
      assert.match(await scenario.innerText(),/84\.2%/);assert.match(await scenario.innerText(),/仮定/);
      await reference.locator('[data-study-course="1"]').click();assert.match(await scenario.innerText(),/逃げ/);
      await page.screenshot({path:path.join(evidence,`official-reference-${width}.png`),fullPage:true});
      await page.locator('#participant-dialog').evaluate(n=>n.scrollTop=n.scrollHeight);
      await page.keyboard.press('Escape');await page.locator('#page-home [data-open-participant="3415"]').click();
      assert.equal(await page.locator('#participant-dialog').evaluate(n=>n.scrollTop),0,'each newly opened athlete card starts at its basic information');
      await page.keyboard.press('Escape');
      const partialOutcomes=[];
      for(const kind of ['participant','supplement']){
        const partial=structuredClone(sparse),r=partial.records[0];
        if(kind==='participant')r.participants[1].preview_course=3;
        else r.boat_observation_context={forecast_inputs_used:false,beforeinfo:{
          schema:'RACE_AI_BOAT_OBSERVATION_CONTEXT_V1',kind:'beforeinfo',race_id:r.race_id,status:'PARSED',roster_binding_status:'VERIFIED',forecast_ready:false,
          source:{source_url:'https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=1&jcd=03&hd=20300101',sha256:'c'.repeat(64),captured_at:'2030-01-01T09:40:00+09:00',published_at:null},
          source_cutoff_at:r.cutoff_at,captured_before_cutoff:true,
          participants:[{lane:2,registration_number:'3897',name:'白井英治',exhibition_course:3}]}};
        await load(partial);await page.locator('#page-home [data-open-participant="3415"]').click();
        const text=await page.locator('.reference-scenario').innerText();
        partialOutcomes.push({kind,conditional:text.includes('逃げ'),partial:/進入.*一部/s.test(text),noInventedNeighbor:!text.includes('2コース 白井英治')&&!text.includes('枠なりを仮定')});
        await page.keyboard.press('Escape');
      }
      assert.deepEqual(partialOutcomes,['participant','supplement'].map(kind=>({kind,conditional:true,partial:true,noInventedNeighbor:true})));
      const newcomer=structuredClone(sparse);newcomer.records[0].participants[0]={number:1,registration_no:'5497',name:'藤山芽依'};
      await load(newcomer);await page.locator('#page-home [data-open-participant="5497"]').click();
      assert.match(await page.locator('#racer-reference .reference-basic').innerText(),/B2/);
      assert.match(await page.locator('#racer-reference').innerText(),/期別資料に未収録/);
      assert.equal(await page.locator('#racer-reference .reference-course').count(),0);await page.keyboard.press('Escape');
      const synthetic=structuredClone(sparse);synthetic.dataset_status='SYNTHETIC_ONLY';
      await load(synthetic);await page.locator('#page-home [data-open-participant="4320"]').click();
      assert.equal(await page.locator('#racer-reference').count(),0);await page.keyboard.press('Escape');
      console.log(`PASS official athlete reference ${width}px: sparse production-style inputs, real period/course data, conditional courses, basic-only profiles and synthetic isolation`);
    }
    if(section==='all'||section==='profiles'){
      await load(fixture);
      const opener=page.locator('#page-home [data-open-participant="3415"]');
      assert.equal(await opener.count(),1,'athlete names and illustrations must open the in-page athlete card');
      await opener.click();const dialog=page.locator('#participant-dialog');
      assert.equal(await dialog.isVisible(),true);assert.match(await dialog.innerText(),/松井繁/);
      const fact=label=>dialog.locator('.profile-values dt').filter({hasText:new RegExp('^'+label+'$')}).evaluate(n=>n.nextElementSibling.textContent);
      assert.equal(await fact('全国勝率'),'0.00');assert.equal(await fact('平均ST'),'0.00');
      assert.equal(await fact('モーター2連率'),'0.00%');assert.match(await dialog.innerText(),/テスト支部/);
      const profile=dialog.locator('a[data-official-profile]');
      assert.equal(await profile.getAttribute('href'),'https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban=3415');
      assert.equal(await profile.getAttribute('referrerpolicy'),'no-referrer');assert.equal(await profile.getAttribute('target'),'_blank');
      await page.screenshot({path:path.join(evidence,`athlete-${width}.png`),fullPage:true});
      await dialog.locator('[data-close-participant]').click();assert.equal(await dialog.isVisible(),false);
      assert.equal(await page.evaluate(()=>document.activeElement.dataset.openParticipant),'3415');
      await opener.press('Enter');assert.equal(await dialog.isVisible(),true);await page.keyboard.press('Escape');
      assert.equal(await dialog.isVisible(),false);assert.equal(await page.evaluate(()=>document.activeElement.dataset.openParticipant),'3415');
      const mismatch=structuredClone(fixture);mismatch.records[0].participants[0].participant_id='4320';
      await load(mismatch);await page.locator('#page-home .racer-card').first().locator('[data-open-participant]').click();
      assert.equal(await dialog.locator('a[data-official-profile]').count(),0);assert.equal(await dialog.locator('img').count(),0);
      await page.keyboard.press('Escape');
      const synthetic=structuredClone(fixture);synthetic.dataset_status='SYNTHETIC_ONLY';
      await load(synthetic);await page.locator('#page-home .racer-card').first().locator('[data-open-participant]').click();
      assert.equal(await dialog.locator('a[data-official-profile]').count(),0);assert.equal(await dialog.locator('img').count(),0);
      assert.match(await dialog.innerText(),/合成/);await page.keyboard.press('Escape');
      console.log(`PASS athlete card ${width}px: saved values including zero, identity gates, keyboard, focus and safe official link`);
    }
    if(section==='all'||section==='navigation'){
      const navigation=structuredClone(fixture);
      navigation.records.push({...structuredClone(first),race_id:'20300101-03-02',race_no:2,cutoff_at:'2030-01-01T11:00:00+09:00'});
      navigation.records.push({...structuredClone(first),race_id:'20300101-24-01',venue:'大村',cutoff_at:'2030-01-01T12:00:00+09:00'});
      navigation.records.push({...structuredClone(first),race_id:'20291231-03-03',race_no:3,event_date_jst:'2029-12-31',cutoff_at:'2029-12-31T12:00:00+09:00'});
      await load(navigation);
      const venue=page.locator('#home-venues [data-venue="江戸川"]');
      assert.equal(await venue.count(),1,'the home page must offer a venue-first way into the races');
      await venue.click();assert.equal(await page.locator('#page-races').isVisible(),true);
      assert.equal(await page.locator('#venue-title').innerText(),'江戸川');
      assert.equal(await page.locator('#all-races .race-card').count(),2);
      await page.locator('#pin-venue').click();assert.equal(await page.locator('#pin-venue').getAttribute('aria-pressed'),'true');
      await page.locator('#race-search').fill('白井');
      const second=page.locator('#all-races .race-card').filter({has:page.locator('[data-open-race="20300101-03-02"]')});
      await second.locator('[data-race-tab="preview"]').click();
      assert.equal(await page.locator('#detail-tab-preview').getAttribute('aria-selected'),'true');
      await page.locator('#same-venue-races [data-race-number="1"]').click();
      assert.equal(await page.locator('#race-detail .detail-title h2').innerText(),'江戸川 1R');
      assert.equal(await page.locator('#detail-tab-preview').getAttribute('aria-selected'),'true');
      assert.equal(await page.locator('#same-venue-races [data-race-number="3"]').isDisabled(),true);
      const official=page.locator('#race-detail [data-official-race="preview"]');
      const url=new URL(await official.getAttribute('href'));
      assert.equal(url.searchParams.get('hd'),'20300101');assert.equal(url.searchParams.get('jcd'),'03');assert.equal(url.searchParams.get('rno'),'1');
      assert.equal(await official.getAttribute('referrerpolicy'),'no-referrer');
      await page.locator('#page-detail .back-button').click();
      assert.equal(await page.locator('#race-search').inputValue(),'白井');assert.equal(await page.locator('#venue-title').innerText(),'江戸川');
      await page.locator('#all-races [data-open-race="20300101-03-01"]').click();await nav('picks');
      await page.locator('#ticket-form button[type="submit"]').click();assert.equal(await page.locator('.ticket-row').count(),1);
      await nav('races');await page.locator('#all-races [data-open-race="20300101-03-01"]').click();
      await page.locator('#page-detail [data-open-participant="3415"]').click();await page.keyboard.press('Escape');
      await page.locator('#same-venue-races [data-race-number="2"]').click();await page.locator('#same-venue-races [data-race-number="1"]').click();
      await nav('picks');assert.equal(await page.locator('.ticket-row').count(),1,'race and athlete navigation must retain the original draft');
      const stored=await page.evaluate(()=>localStorage.getItem('race-ai-display-v1'));
      assert.ok(JSON.parse(stored).favoriteVenues.includes('boat:江戸川'));
      assert.doesNotMatch(stored,/松井繁|national_win_rate|source_sha256|ordered_top8/);
      await page.reload();await load(navigation);
      assert.equal(await page.locator('#home-venues [data-venue]').first().getAttribute('data-venue'),'江戸川','favorite venues survive reloading');
      await page.locator('#home-venues [data-venue="江戸川"]').click();
      const heading=await page.locator('#all-races .race-card h3').first().boundingBox();
      assert.ok(heading.y+heading.height<900-60,'the first race heading is visible without scrolling after selecting a venue');
      for(const img of await page.locator('#all-races img').all())await img.scrollIntoViewIfNeeded();
      await page.waitForFunction(()=>[...document.querySelectorAll('#all-races img')].every(img=>img.complete&&img.naturalWidth>0));
      await page.evaluate(()=>window.scrollTo(0,0));
      await page.screenshot({path:path.join(evidence,`venue-explorer-${width}.png`),fullPage:true});
      if(!await page.locator('#venue-picker').evaluate(n=>n.open))await page.locator('#venue-picker>summary').click();
      await page.locator('#venue-buttons [data-venue="尼崎"]').click();
      assert.equal(await page.locator('#all-races .race-card').count(),0);
      assert.equal(await page.locator('#venue-title').innerText(),'尼崎');assert.match(await page.locator('#all-races').innerText(),/未取得/);
      await page.locator('#selected-date').fill('2030-01-02');await page.locator('#selected-date').dispatchEvent('change');
      assert.equal(await page.locator('#venue-title').innerText(),'尼崎','an empty venue stays selected when the day changes');
      console.log(`PASS race explorer ${width}px: favorites, venues, shortcuts, same-day races, official links, drafts and empty dates`);
    }
    if(section==='all'||section==='preview'){
      const preview=structuredClone(fixture),row=preview.records[0];
      row.participants[0].display_time=6.71;row.participants[0].preview_st='F.01';row.participants[1].preview_st=0;
      row.participants[0].comment='UI用の架空コメント <img src=x onerror="alert(1)">';
      row.weather={weather_label:'晴',air_temperature_c:12,wind_speed_mps:0,wave_height_cm:0,water_temperature_c:15};
      await load(preview);await page.locator('#page-home [data-race-tab="preview"]').click();
      const weather=page.getByRole('region',{name:'保存された気象・水面'});
      assert.equal(await weather.count(),1,'weather must be presented as labeled, readable values with units');
      assert.match(await weather.innerText(),/0 m\/s/);assert.match(await weather.innerText(),/0 cm/);
      const cards=page.locator('#detail-tab-content .preview-boat');assert.equal(await cards.count(),6);
      assert.match(await cards.first().innerText(),/6\.71/);assert.match(await cards.first().innerText(),/F\.01/);
      assert.match(await cards.first().innerText(),/<img src=x/);assert.equal(await cards.first().locator('img').count(),0);
      await cards.first().locator('[data-open-participant]').click();
      assert.match(await page.locator('#participant-dialog').innerText(),/F\.01/);await page.keyboard.press('Escape');
      await page.screenshot({path:path.join(evidence,`preview-${width}.png`),fullPage:true});
      const invalid=structuredClone(preview);delete invalid.records[0].weather;
      invalid.records[0].boat_observation_context={beforeinfo:{schema:'RACE_AI_BOAT_OBSERVATION_CONTEXT_V1',participants:[{lane:1,display_time:99.99}]}};
      await load(invalid);await page.locator('#page-home [data-race-tab="preview"]').click();
      assert.match(await page.locator('#boat-observation-context').innerText(),/照合できません/);
      assert.doesNotMatch(await page.locator('#boat-observation-context').innerText(),/99\.99/);
      console.log(`PASS pre-race view ${width}px: labeled weather, zero values, F flags, athlete access, literal comments and rejected supplements`);
    }
    if(section==='all'||section==='review'){
      const observed=structuredClone(fixture),row=observed.records[0];
      const source=(kind,hash,time)=>({source_url:`https://www.boatrace.jp/owpc/pc/race/${kind}?rno=1&jcd=03&hd=20300101`,sha256:hash.repeat(64),captured_at:`2030-01-01T09:${time}:00+09:00`,published_at:null});
      row.boat_observation_context={forecast_inputs_used:false,
        beforeinfo:{schema:'RACE_AI_BOAT_OBSERVATION_CONTEXT_V1',kind:'beforeinfo',race_id:row.race_id,status:'PARSED',roster_binding_status:'VERIFIED',forecast_ready:false,
          source:source('beforeinfo','c','40'),source_cutoff_at:row.cutoff_at,captured_before_cutoff:true,
          participants:[{lane:1,registration_number:'3415',name:'松井繁',display_time:6.88,exhibition_st:0.04,exhibition_st_raw:'F.04',exhibition_st_status:'F',tilt:0}]},
        pitreport:{schema:'RACE_AI_BOAT_OBSERVATION_CONTEXT_V1',kind:'pitreport',race_id:row.race_id,status:'PARSED',roster_binding_status:'VERIFIED',forecast_ready:false,
          source:source('pitreport','d','42'),participants:[{lane:1,registration_number:'3415',name:'松井繁',comment:'UI用の架空補足コメント'}]}};
      await load(observed);await page.locator('#page-home [data-open-participant="3415"]').click();
      const supplement=page.locator('#profile-supplement');
      assert.equal(await supplement.count(),1,'athlete cards must include already loaded matching supplemental observations');
      assert.match(await supplement.innerText(),/6\.88/);assert.match(await supplement.innerText(),/F\.04/);
      assert.match(await supplement.innerText(),/UI用の架空補足コメント/);assert.match(await supplement.innerText(),/09:40/);assert.match(await supplement.innerText(),/09:42/);
      assert.match(await supplement.innerText(),/保存予想への反映は未検証/);
      await page.keyboard.press('Escape');await page.locator('#page-home [data-race-tab="preview"]').click();
      assert.equal(await page.locator('#detail-tab-content .preview-boat').count(),0,'supplemental exhibition values must not be copied into saved forecast inputs');
      for(const patch of [{lane:2},{registration_number:'3897'},{name:'別の選手'}]){
        const mismatch=structuredClone(observed);
        for(const page of [mismatch.records[0].boat_observation_context.beforeinfo,mismatch.records[0].boat_observation_context.pitreport])Object.assign(page.participants[0],patch);
        await load(mismatch);await page.locator('#page-home [data-open-participant="3415"]').click();
        assert.equal(await page.locator('#profile-supplement').count(),0,'supplemental observations require the exact athlete identity and lane');
        await page.keyboard.press('Escape');
      }
      await nav('races');if(!await page.locator('#venue-picker').evaluate(n=>n.open))await page.locator('#venue-picker>summary').click();
      await page.locator('#venue-buttons [data-venue="尼崎"]').click();
      const officialVenue=page.locator('#all-races [data-official-venue="stadium"]');
      assert.equal(await officialVenue.count(),1,'an unloaded venue needs an official-information entrance');
      assert.equal(new URL(await officialVenue.getAttribute('href')).searchParams.get('jcd'),'13');
      assert.equal(await officialVenue.getAttribute('referrerpolicy'),'no-referrer');
      await page.locator('#selected-date').fill('2030-01-02');await page.locator('#selected-date').dispatchEvent('change');
      assert.equal(new URL(await page.locator('#all-races [data-official-venue="calendar"]').getAttribute('href')).searchParams.get('hd'),'20300102');
      assert.equal(await page.locator('#all-races .race-card').count(),0);
      console.log(`PASS reviewed edge cases ${width}px: matching supplementary athlete values, observation boundaries and official empty-venue routes`);
    }
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await context.close();
  }
  assert.deepEqual(errors,[]);assert.equal(requests.some(url=>url.startsWith('https://www.boatrace.jp/')),false);
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));});
