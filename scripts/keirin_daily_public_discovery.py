#!/usr/bin/env python3
"""Discover today's actual national KEIRIN racecards through public UI only.

No hidden API, network request interception, embedded stream URL, odds,
outcome, or private user data. A missing/mismatched WINTICKET date is a STOP,
not a reason to reuse yesterday's race inventory.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
from playwright.async_api import async_playwright

from race_ai.keirin_daily_public_catalog import (
    JST, SOURCE_RACECARD, SOURCE_RESULTS, combine, assess_daily_manifest
)

async def _read_index(page,url):
    response=await page.goto(url,wait_until="domcontentloaded",timeout=24000)
    if response is None or response.status!=200:
        raise RuntimeError(f"DAILY_INDEX_HTTP_{response.status if response else 'EMPTY'}")
    await page.wait_for_timeout(1350)
    return await page.evaluate("""() => {
        const headings=[...document.querySelectorAll('h1,h2,h3')]
            .map(n=>n.innerText.trim()).filter(x=>/本日\\s*\\d{4}年\\d{1,2}月\\d{1,2}日/.test(x));
        return {
            source_url: window.location.origin+window.location.pathname,
            heading: headings.join(' | '),
            links:[...document.querySelectorAll('a[href]')]
              .filter(a=>a.href.startsWith('https://www.winticket.jp/keirin/'))
              .map(a=>({href:a.href,text:(a.innerText||'').trim().slice(0,60)}))
              .slice(0,800)
        };
      }""")

async def discover(day_jst):
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(
            headless=True,channel="chrome",args=["--no-sandbox"])
        context=await browser.new_context(locale="ja-JP",
                 timezone_id="Asia/Tokyo")
        page=await context.new_page()
        try:
            card=await _read_index(page,SOURCE_RACECARD)
            result=await _read_index(page,SOURCE_RESULTS)
            manifest=combine(day_jst,[card,result])
            assess_daily_manifest(manifest,target_day_jst=day_jst)
        finally:
            await context.close()
            await browser.close()
    return manifest

async def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",required=True,type=Path)
    ap.add_argument("--date-jst",help="Only for independent testing; runner supplies actual today")
    options=ap.parse_args()
    now=datetime.now(JST)
    date_jst=now.date().isoformat()
    if options.date_jst is not None and options.date_jst!=date_jst:
        raise SystemExit("CALENDAR_DATE_CANNOT_BE_BACKDATED_OR_FAST_FORWARDED")
    doc=await discover(date_jst)
    options.output.parent.mkdir(parents=True,exist_ok=True)
    options.output.write_text(json.dumps(doc,ensure_ascii=False,indent=2))
    print(json.dumps({
        "date_jst":date_jst,
        "venues_discovered":doc["discovered_venue_count"],
        "races_discovered":doc["discovered_race_count"],
        "results_index_races":sum(x["listed_on_raceresult_index"] for x in doc["races"]),
        "manifest_sha256":doc["manifest_sha256"],
        "source":"WINTICKET_PUBLIC_PAGE_ANCHORS_NOT_PLAYER_PROOF"
    },ensure_ascii=False))

if __name__=="__main__":
    asyncio.run(main())
