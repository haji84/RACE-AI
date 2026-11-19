#!/usr/bin/env python3
"""Research-only historical published-lineup backfill. No inferred lines or bypass."""
from __future__ import annotations
import argparse,csv,hashlib,json,re,time,urllib.parse,urllib.request,urllib.error,urllib.robotparser
from collections import Counter,defaultdict
from datetime import datetime,timezone
from html.parser import HTMLParser
from pathlib import Path
from line_classifier import classify_order

class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style"):self.hidden+=1
        if tag in ("h1","h2","h3","h4","p","div","section","article","br","li","tr"):self.parts.append("\n")
    def handle_endtag(self,tag):
        if tag in ("script","style") and self.hidden:self.hidden-=1
        if tag in ("h1","h2","h3","h4","p","div","section","article","li","tr"):self.parts.append("\n")
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)
    def value(self):return re.sub(r"\n\s*\n+","\n","".join(self.parts))

def extract(page):
    p=Text();p.feed(page);s=p.value()
    hs=list(re.finditer(r"(?m)^\s*(0?[1-9]|1[0-2])R(?=\s|\W|$)",s))
    found={};conflict=set()
    for i,h in enumerate(hs):
        no=int(h.group(1))
        part=s[h.end(): hs[i+1].start() if i+1<len(hs) else len(s)]
        m=re.search(r"ライン並び\s*([1-9][1-9\s│|／/]*)",part)
        if not m:continue
        raw=re.sub(r"\s+"," ",m.group(1)).strip()
        if no in found and found[no]!=raw:conflict.add(no)
        found[no]=raw
    return found,conflict

def load_rows(folder):
    rows=[]
    for p in sorted(folder.glob("race_results_2026??.csv")):
        with p.open(encoding="utf-8-sig",newline="") as f:rows+=list(csv.DictReader(f))
    if len(rows)!=24291:raise ValueError("SETTLED_RACE_DENOMINATOR_CHANGED")
    if len({r["race_key"] for r in rows})!=len(rows):raise ValueError("DUPLICATE_RACE_KEY")
    return rows

def read_jsonl(path):
    if not path.exists():return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]

def append_jsonl(path,value):
    with path.open("a",encoding="utf-8") as f:f.write(json.dumps(value,ensure_ascii=False,sort_keys=True)+"\n")

def run(root,out,max_pages,delay):
    rows=load_rows(root);male=[r for r in rows if r["gender"]=="男子"]
    if len(male)!=22245:raise ValueError("MALE_DENOMINATOR_CHANGED")
    out.mkdir(parents=True,exist_ok=True)
    log=out/"source_fetch_audit.jsonl";store=out/"lineups_collected.jsonl";store.touch(exist_ok=True)
    seen_urls={r["source_url"] for r in read_jsonl(log) if r.get("status") in ("OK","NO_PAGE","NO_VALID_LINES")}
    known={r["race_key"]:r for r in read_jsonl(root/"published_lineup_pilot_20261118.jsonl")}
    for r in read_jsonl(store):
        old=known.get(r["race_key"])
        if old and old["lineup"]!=r["lineup"]:raise ValueError("SOURCE_LINEUP_CONFLICT")
        known[r["race_key"]]=r
    groups=defaultdict(dict)
    for row in male:
        u=urllib.parse.urlparse(row["race_source_url"])
        slug=u.path.strip("/").split("/")[0]
        if not re.fullmatch(r"[a-z0-9-]+",slug):continue
        groups[(row["date"],slug)][int(row["race_no"])]=row
    agent="RACE-AI-historical-line-research/1.0 (+https://github.com/haji84/RACE-AI)"
    can_fetch=None; attempted=0; added=0; stopped=False
    for (date,slug),rr in sorted(groups.items(),reverse=True):
        if attempted>=max_pages or stopped:break
        url=f"https://kantoumon.jp/{date.replace('-','')}_{slug}"
        if url in seen_urls:continue
        checked=datetime.now(timezone.utc).isoformat()
        status="NO_VALID_LINES";reason="";valid=0;rejected=0
        try:
            if can_fetch is None:
                robot="https://kantoumon.jp/robots.txt"
                try:
                    with urllib.request.urlopen(urllib.request.Request(robot,headers={"User-Agent":agent}),timeout=12) as resp:
                        robots=resp.read(131072).decode("utf-8","replace")
                    rp=urllib.robotparser.RobotFileParser();rp.parse(robots.splitlines())
                    can_fetch=rp.can_fetch(agent,url)
                except urllib.error.HTTPError as e:
                    if e.code==404:can_fetch=True
                    else:raise RuntimeError("ROBOTS_UNAVAILABLE") from e
            if not can_fetch:
                status="ROBOTS_DISALLOWED";stopped=True
            else:
                req=urllib.request.Request(url,headers={"User-Agent":agent,"Accept":"text/html"})
                with urllib.request.urlopen(req,timeout=12) as resp:
                    data=resp.read(2_000_001)
                    if len(data)>2_000_000:raise ValueError("OVERSIZE_SOURCE")
                found,conflict=extract(data.decode("utf-8","replace"))
                digest=hashlib.sha256(data).hexdigest()
                for no,row in sorted(rr.items()):
                    raw=found.get(no)
                    if not raw or no in conflict:continue
                    chars=[int(x) for x in re.findall("[1-9]",raw)]
                    starters=[int(x) for x in row["actual_starters"].split("-")]
                    if len(chars)!=len(starters) or set(chars)!=set(starters):
                        rejected+=1;continue
                    if row["race_key"] in known:
                        if known[row["race_key"]]["lineup"]!=raw:rejected+=1
                        continue
                    obj={"race_key":row["race_key"],"lineup":raw,"source_url":url,
                         "captured_utc":checked,"source_sha256":digest,
                         "source_kind":"historically_published_predicted_lineup",
                         "not_verified_as_pre_cutoff":True}
                    append_jsonl(store,obj);known[row["race_key"]]=obj
                    added+=1;valid+=1
                if valid:status="OK"
        except urllib.error.HTTPError as e:
            reason=str(e.code)
            status="NO_PAGE" if e.code==404 else "PROVIDER_DENIED_HOLD" if e.code in (401,403,429,451,503) else "HTTP_ERROR"
            if status=="PROVIDER_DENIED_HOLD":stopped=True
        except Exception as e:
            reason=type(e).__name__+":"+str(e)[:60];status="FETCH_ERROR_HOLD";stopped=True
        append_jsonl(log,{"checked_utc":checked,"source_url":url,"status":status,
            "new_lineups":valid,"invalid_lines":rejected,"expected_male_races":len(rr),"reason":reason})
        attempted+=1
        if stopped:break
        time.sleep(delay)
    counts=defaultdict(Counter);noted=Counter()
    for row in male:
        n=len(row["actual_starters"].split("-"));cat=f"{n}車"
        for key in ("全国男子",cat):counts[key]["eligible"]+=1
        rec=known.get(row["race_key"])
        if not rec:
            for key in ("全国男子",cat):counts[key]["missing"]+=1
            continue
        try:
            groups2=[[int(x) for x in group.split()] for group in re.split("[│|／/]",rec["lineup"])]
            start={int(x) for x in row["actual_starters"].split("-")}
            if not all(groups2) or {x for g in groups2 for x in g}!=start or sum(map(len,groups2))!=len(start):raise ValueError("STARTERS_DISAGREE")
            orders=row["winning_orders"].split("|")
            payouts=row["payout_yen_100"].split("|")
            if len(orders)!=len(payouts):raise ValueError("TIE_PAYOUT_MISMATCH")
            kinds=[classify_order(groups2,[int(x) for x in s.split("-")],sorted(start))["class"] for s in orders]
            k=kinds[0] if len(set(kinds))==1 else "MULTI_CLASS_TIE"
        except Exception:
            for key in ("全国男子",cat):counts[key]["invalid"]+=1
            continue
        for key in ("全国男子",cat):counts[key]["matched"]+=1;counts[key][k]+=1
        noted[k]+=1
    for label,c in counts.items():
        if c["eligible"]!=c["missing"]+c["invalid"]+c["matched"]:raise AssertionError("AUDIT_DENOMINATOR:"+label)
    summary={"period":"2026-01-01_to_2026-11-18","settled_total":len(rows),
             "male_eligible":len(male),"excluded_girls":len(rows)-len(male),
             "coverage":{k:dict(v) for k,v in sorted(counts.items())},
             "last_batch":{"attempted_pages":attempted,"new_lineups":added,"stopped":stopped,
                           "robots_permission":can_fetch,"candidate_day_venues":len(groups)},
             "source":"https://kantoumon.jp/","claim":"published_pre_race_lineup_only_not_video"}
    (out/"line_coverage.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"batch_result.json").write_text(json.dumps(summary["last_batch"],ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"eligible":len(male),"matched":counts["全国男子"]["matched"],
                      "missing":counts["全国男子"]["missing"],"invalid":counts["全国男子"]["invalid"],
                      **summary["last_batch"]},ensure_ascii=False))
    return summary

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--max-pages",type=int,default=12)
    ap.add_argument("--delay",type=float,default=2.0)
    a=ap.parse_args()
    if not 1<=a.max_pages<=100 or a.delay<1.5:ap.error("limited requests only")
    run(a.root,a.out,a.max_pages,a.delay)
