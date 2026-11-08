#!/usr/bin/env python3
"""Metadata-only look at historic KEIRIN-mobile video archive page.

A public video index does not mean the clip contains all laps or grants copying
rights. We do not fetch video bytes, download originals, or use raw stream URLs.
"""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright

URL="https://www.keirin-mobile.jp/Android/docomo/Content/movie2/backmovie201704.php?date=20261108&jno=74&grade=2"

async def main():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,channel="chrome",args=["--no-sandbox"])
        context=await browser.new_context(locale="ja-JP")
        page=await context.new_page()
        data={"public_archive_page":URL,"metadata_only":True}
        try:
            response=await page.goto(URL,wait_until="domcontentloaded",timeout=23000)
            await page.wait_for_timeout(3500)
            data["http_code"]=response.status if response else None
            data["title"]=(await page.title())[:150]
            data["description"]=(await page.locator("body").inner_text())[:2200]
            data["evidence"]=await page.evaluate("""() => {
                let v=[...document.querySelectorAll('video')].slice(0,4).map(x=>({
                    duration:Number.isFinite(x.duration)?x.duration:null,
                    ready:x.readyState,width:x.videoWidth,height:x.videoHeight}));
                let a=[...document.querySelectorAll('a[href]')].filter(x =>
                    /[0-9１２３４５６７８９]+\s*[ＲR]/.test((x.innerText||'').trim()))
                    .slice(0,25).map(x=>({
                        text:(x.innerText||'').trim().slice(0,70),
                        is_direct_media:/\.(?:mp4|wmv|m3u8|mkv)(?:\?|$)/i.test(x.href),
                        link_host:(new URL(x.href)).hostname,
                        path:(new URL(x.href)).pathname.slice(0,120)
                    }));
                return {video_count:document.querySelectorAll('video').length,
                   videos:v,race_links:a,
                   iframe_count:document.querySelectorAll('iframe').length};
              }""")
        except Exception as exc:
            data["error_type"]=type(exc).__name__
            data["error_summary"]=str(exc)[:120]
        await context.close()
        await browser.close()
    Path(sys.argv[1]).write_text(json.dumps(data,ensure_ascii=False,indent=2))
    print(json.dumps(data,ensure_ascii=False))
if __name__=="__main__":asyncio.run(main())
