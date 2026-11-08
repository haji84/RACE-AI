#!/usr/bin/env python3
"""Research-only source discovery. Never downloads video or stream URLs.

Find an actual uncut Matsuyama 2026-11-08 1R replay; this file is metadata-only.
Don't infer full-race coverage from a YouTube video title or duration.
"""
import asyncio
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime,timezone
from playwright.async_api import async_playwright

CHANNELS={
    "matsuyama_official":"UCX3xb9FwC7jL_ZnVmoyzgDg",
    "chariloto_pechannel":"UCr4eIfuNdlZWSDMjFwDTabA",
}

def rss_feed(channel):
    url=f"https://www.youtube.com/feeds/videos.xml?channel_id={channel}"
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (compatible; RaceAISourceProbe/1.0)"})
    try:
        with urllib.request.urlopen(req,timeout=12) as response:
            raw=response.read(200_000)
        root=ET.fromstring(raw)
        ns={"a":"http://www.w3.org/2005/Atom",
            "y":"http://www.youtube.com/xml/schemas/2015"}
        entries=[]
        for e in root.findall("a:entry",ns)[:18]:
            entries.append({
                "title":e.findtext("a:title",default="",namespaces=ns),
                "video_id":e.findtext("y:videoId",default="",namespaces=ns),
                "published":e.findtext("a:published",default="",namespaces=ns)})
        return {"status":"OK","entries":entries}
    except Exception as exc:
        return {"status":"INACCESSIBLE","error_type":type(exc).__name__}

async def browse(browser,channel):
    result={}
    context=await browser.new_context(locale="ja-JP",timezone_id="Asia/Tokyo")
    for suffix in ("streams","live"):
        url=f"https://www.youtube.com/channel/{channel}/{suffix}"
        try:
            p=await context.new_page()
            await p.goto(url,wait_until="domcontentloaded",timeout=20000)
            await p.wait_for_timeout(2000)
            player=await p.evaluate("""() => {
                const pr=window.ytInitialPlayerResponse||{};
                const vd=pr.videoDetails||{};
                const live=pr.microformat?.playerMicroformatRenderer?.liveBroadcastDetails||{};
                const v=document.querySelector('video');
                let ranges=[];
                if (v && v.seekable) {
                    for (let i=0;i<v.seekable.length;i++) {
                        ranges.push([v.seekable.start(i),v.seekable.end(i)]);
                    }
                }
                return {
                  video_id:vd.videoId||null,
                  channel_id:vd.channelId||null,
                  video_title:vd.title||null,
                  is_live:vd.isLive||false,
                  is_live_content:vd.isLiveContent||false,
                  start_timestamp:live.startTimestamp||null,
                  actual_end_timestamp:live.endTimestamp||null,
                  player_status:pr.playabilityStatus?.status||null,
                  element_count:document.querySelectorAll('video').length,
                  video_state:v?{current_time:v.currentTime,
                    duration:Number.isFinite(v.duration)?v.duration:null,
                    ended:v.ended,paused:v.paused,
                    ready_state:v.readyState,seekable:ranges}:null
                }; }""")
            result[suffix]={"player":player,
                "url":p.url[:350],
                "title":(await p.title())[:250],
                "watch_links":await p.evaluate("""() => [...document.querySelectorAll('a[href]')]
                .filter(a=>a.href.includes('watch?v=') || a.href.includes('/live/'))
                .slice(0,36).map(a=>({
                   label:(a.getAttribute('title')||a.innerText||'').slice(0,220),
                   href:a.href.split('&')[0]}))"""),
            }
            await p.close()
        except Exception as exc:
            result[suffix]={"status":"ERROR","error_type":type(exc).__name__}
    await context.close()
    return result

async def main():
    report={"schema":"RACE_AI_FULL_RACE_SOURCE_DISCOVERY_V1",
      "race_id":"20261108-matsuyama-01",
      "note":"METADATA_ONLY: NO_CAPTURE_NO_RACE_VERIFICATION",
      "at_utc":datetime.now(timezone.utc).isoformat(),
      "channels":{}}
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,
          channel="chrome",args=["--no-sandbox"])
        for label,channel in CHANNELS.items():
            report["channels"][label]={
                "rss":rss_feed(channel),
                "browser":await browse(browser,channel)}
        await browser.close()
    with open(sys.argv[1],"w",encoding="utf-8") as f:
        json.dump(report,f,indent=2,ensure_ascii=False)
    for label,obj in report["channels"].items():
        print(label,"RSS",obj["rss"]["status"],"entries",len(obj["rss"].get("entries",[])))
        for entry in obj["rss"].get("entries",[])[:6]:
            print(" ",entry)
        for tab in ("streams","live"):
            x=obj["browser"][tab]
            print(tab,x.get("title"),x.get("url"),"player",x.get("player"),"links",x.get("watch_links",[])[:7])

if __name__=="__main__":
    asyncio.run(main())
