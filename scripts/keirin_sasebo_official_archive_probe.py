#!/usr/bin/env python3
"""Find historical full-broadcast candidates from Sasebo official sources.

Metadata-only public browser inspection. Do not record, download or inspect
stream URLs/cookies. Any access-control or rights uncertainty is a stop signal.
"""
from __future__ import annotations
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

from playwright.async_api import async_playwright

INDEX="https://www.sasebokeirin.jp/vtr"
BROADCASTS=(
    {"id":"sasebo-2025-12-05-official-broadcast","url":"https://www.youtube.com/watch?v=fIkUTVa7L_c",
     "race_timestamps":[{"race_no":1,"start_hms":"00:49:06"},{"race_no":2,"start_hms":"01:14:54"},{"race_no":3,"start_hms":"01:42:06"}]},
    {"id":"sasebo-2025-08-03-official-broadcast","url":"https://www.youtube.com/watch?v=8A9h6vL10cs",
     "race_timestamps":[{"race_no":1,"start_hms":"00:42:49"},{"race_no":2,"start_hms":"01:06:57"},{"race_no":3,"start_hms":"01:30:58"}]},
)

async def get_index(page):
    response=await page.goto(INDEX,wait_until="domcontentloaded",timeout=22000)
    await page.wait_for_timeout(1500)
    result={"url":INDEX,"http_status":response.status if response else None,
            "title":(await page.title())[:170]}
    result["controls"]=await page.evaluate("""() => ({
       selects:[...document.querySelectorAll('select')].slice(0,10).map(s=>({
         name:s.name,id:s.id,options:[...s.options].slice(0,24).map(o=>({
            text:o.text.trim().slice(0,80),value:o.value.slice(0,80)
         }))})),
       links:[...document.querySelectorAll('a[href]')].filter(a=>
         a.href.includes('youtube.com')||a.href.includes('youtu.be'))
         .slice(0,10).map(a=>({label:(a.innerText||'').slice(0,90),
                                host:(new URL(a.href)).hostname})),
       has_ended_2025_march:document.body.innerText.includes('2025年3月末')
    })""")
    return result

async def player_info(page,url):
    result={"source_url":url,"metadata_only":True}
    try:
        response=await page.goto(url,wait_until="domcontentloaded",timeout=22000)
        await page.wait_for_timeout(2500)
        result["http_status"]=response.status if response else None
        result["title"]=(await page.title())[:190]
        result["player"]=await page.evaluate("""() => {
          const r=window.ytInitialPlayerResponse||{};
          const v=r.videoDetails||{};
          const e=document.querySelector('video');
          return {player_status:r.playabilityStatus?.status||'UNKNOWN',
            video_id:v.videoId||null, title:(v.title||'').slice(0,190),
            channel_id:v.channelId||null,
            duration:Number.isFinite(e?.duration)?e.duration:null,
            video_ready:e?.readyState||0,
            video_width:e?.videoWidth||0,video_height:e?.videoHeight||0,
            playback_test_performed:false};
        }""")
        result["status"]="PUBLIC_PAGE_READ_ONLY"
    except Exception as exc:
        result["status"]="UNAVAILABLE"
        result["error_type"]=type(exc).__name__
    return result

async def main(out):
    report={"schema":"KEIRIN_SASEBO_HISTORICAL_FULL_BROADCAST_DISCOVERY_V1",
      "checked_utc":datetime.now(timezone.utc).isoformat(),
      "metadata_only":True,"copyrighted_media_saved":False,
      "rights_status":"JCI_CONFIRMATION_PENDING",
      "archive_index":None,"candidates":[]}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,channel="chrome",
                        args=["--no-sandbox"])
        context=await browser.new_context(locale="ja-JP")
        page=await context.new_page()
        try:
            report["archive_index"]=await get_index(page)
        except Exception as exc:
            report["archive_index"]={"status":"UNAVAILABLE",
                                     "error_type":type(exc).__name__}
        for target in BROADCASTS:
            state=await player_info(page,target["url"])
            state["source_id"]=target["id"]
            state["race_timestamps"]=target["race_timestamps"]
            state["full_four_laps_verified"]=False
            state["usable_for_training"]=False
            state["rights"]="UNVERIFIED"
            report["candidates"].append(state)
        await context.close()
        await browser.close()
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2),
                   encoding="utf-8")
    print(json.dumps({"index_http_status":report["archive_index"].get("http_status"),
                      "index_selects":report["archive_index"].get("controls",{}).get("selects"),
                      "candidates":[{"id":c["source_id"],"http":c.get("http_status"),
                          "player":c.get("player"),"status":c["status"]}
                          for c in report["candidates"]],
                      "rights":"JCI_CONFIRMATION_PENDING",
                      "real_full_four_lap_clips_acquired":0},
                      ensure_ascii=False))

if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: probe.py <report.json>")
    asyncio.run(main(Path(sys.argv[1])))
