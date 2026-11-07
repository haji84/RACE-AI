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
let browser,server;
(async()=>{
  const errors=[],requests=[];
  server=http.createServer((req,res)=>{
    const relative=new URL(req.url,'http://localhost').pathname.replace(/^\/RACE-AI\//,'/'),file=path.resolve(root,'.'+(relative==='/'?'/index.html':relative));
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
    await page.clock.install({time:new Date('2030-01-01T00:30:00Z')});await page.goto(base);
    const nav=name=>page.locator(`[data-page="${name}"]`).filter({visible:true}).first().click();
    const load=async data=>{
      await page.evaluate(()=>document.getElementById('file-message').textContent='');
      await page.locator('#race-file').setInputFiles({name:'invented-explorer-ui.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(data))});
      await page.waitForFunction(()=>document.querySelector('#file-message').textContent.length>0);
      await nav('home');await page.locator('#page-home .racer-card').first().waitFor();
    };
    await load(fixture);
    if(section!=='navigation'){
      const opener=page.locator('#page-home [data-open-participant="3415"]');
      assert.equal(await opener.count(),1,'athlete names and illustrations must open the in-page athlete card');
      await opener.click();const dialog=page.locator('#participant-dialog');
      assert.equal(await dialog.isVisible(),true);assert.match(await dialog.innerText(),/松井繁/);
      const fact=label=>dialog.locator('dt').filter({hasText:new RegExp('^'+label+'$')}).evaluate(n=>n.nextElementSibling.textContent);
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
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await context.close();
  }
  assert.deepEqual(errors,[]);assert.equal(requests.some(url=>url.startsWith('https://www.boatrace.jp/')),false);
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));});
