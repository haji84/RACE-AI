#!/usr/bin/env python3
"""Inspect public keirin historical replay pages for unedited multi-lap media.

Does not download stream URLs, record copyrighted media, log cookies, bypass
authentication, or assume a long video is an uncut race. Metadata only.
"""
from __future__ import annotations
import asyncio
import json
from datetime import datetime,timezone
from pathlib import Path
import sys
from playwright.async_api import async_playwright

SOURCES=(
 ("oddspark_archive", "https://www.oddspark.com/keirin/yosou/movie/archive/"),
 ("oddspark_past_race_sample",
  "https://www.oddspark.com/keirin/yosou/movie/archive/?editionNo=00&gradeCd=02&joCode=25&kaisaiBi=20261104&raceNo=2"),
 ("keirin_mobile_archives",
  "https://www.keirin-mobile.jp/Android/docomo/Content/m05/logs.php"),
)

async def inspect(page):
    return await page.evaluate("""() => {
        const vids=[...document.querySelectorAll('video')].slice(0,6)
          .map(v=>({duration:Number.isFinite(v.duration)?v.duration:null,
             ready:v.readyState,paused:v.paused,width:v.videoWidth,
             height:v.videoHeight,seekable:[...Array(v.seekable?.length||0).keys()]
                .slice(0,3).map(i=>[v.seekable.start(i),v.seekable.end(i)])}));
        const options=[...document.querySelectorAll('select')].slice(0,8)
          .map(s=>({name:s.name,options:[...s.options].slice(0,8)
                    .map(o=>({value:o.value,text:o.text.slice(0,50)}))}));
        const matching=[...document.querySelectorAll('a[href]')]
          .filter(a=>/動画|映像|1.?R|レース/.test((a.innerText||'').trim()))
          .slice(0,16).map(a=>({title:(a.innerText||'').trim().slice(0,65),
              href:a.href.startsWith('https://')?a.href.slice(0,240):null}));
        return {videos:vids,selects:options,
                visible_replay_links:matching,
                iframe_count:document.querySelectorAll('iframe').length,
                video_count:document.querySelectorAll('video').length};
      }""")

async def main():
    result={"schema":"RACE_AI_HISTORICAL_FULL_RACE_SOURCE_CHECK_V1",
            "captured_at_utc":datetime.now(timezone.utc).isoformat(),
            "no_video_download":True,"no_frame_storage":True,"pages":[]}
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(headless=True,channel="chrome",
                 args=["--no-sandbox"])
        context=await browser.new_context(locale="ja-JP")
        for name,url in SOURCES:
            page=await context.new_page()
            row={"source":name,"url":url}
            try:
                response=await page.goto(url,wait_until="domcontentloaded",
                                         timeout=23000)
                await page.wait_for_timeout(2800)
                row["http_code"]=response.status if response else None
                row["final_url"]=page.url[:270]
                row["title"]=(await page.title())[:160]
                row["metadata"]=await inspect(page)
            except Exception as exc:
                row["error_type"]=type(exc).__name__
            finally:
                result["pages"].append(row)
                await page.close()
        await context.close()
        await browser.close()
    Path(sys.argv[1]).write_text(json.dumps(
        result,ensure_ascii=False,indent=2),encoding="utf-8")
    for p in result["pages"]:
        print(json.dumps({
          "source":p["source"],"http_code":p.get("http_code"),
          "title":p.get("title"),"error_type":p.get("error_type"),
          "metadata":p.get("metadata")},
          ensure_ascii=False))
if __name__=="__main__":
    asyncio.run(main())
