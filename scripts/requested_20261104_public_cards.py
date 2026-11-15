"""Bounded requested Nov-4 racecard facts; no predictions, schedules or bets."""
from datetime import datetime,timezone,timedelta
from html.parser import HTMLParser
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from urllib.parse import urlparse
from pathlib import Path
import argparse,hashlib,json,re,time,sys
JST=timezone(timedelta(hours=9))
DAY='2026-11-04'
def has_date(text):
    return bool(re.search(r'2026\s*年\s*11\s*月\s*0?4\s*日',text))
def linked_cards(sources):
    found=set()
    for s in sources:
        root=s['url']
        if root not in ('https://www.winticket.jp/keirin/racecard/20261104','https://www.winticket.jp/autorace/racecard/20261104') and not (root.startswith('https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceList?') and '2026%2F11%2F04' in root):continue
        for u in s.get('links',[]):
            m=re.fullmatch(r'https://www\.winticket\.jp/(keirin|autorace)/[^/]+/racecard/\d{10}/\d+/\d+',u)
            if m:found.add((m[1],u))
            elif u.startswith('https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?') and '2026%2F11%2F04' in u:found.add(('horse',u))
    return sorted(found)
class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.skip=0;self.text=[];self.rows=[];self.stack=[];self.cell=None;self.links=[]
    def handle_starttag(self,t,a):
        a=dict(a)
        if t in ('style','script','noscript'):self.skip+=1
        if t=='a' and a.get('href'):self.links.append(a['href'])
        if self.skip:return
        if t=='tr':self.stack.append([])
        if t in ('td','th') and self.stack:self.cell=[]
    def handle_endtag(self,t):
        if t in ('style','script','noscript'):self.skip=max(0,self.skip-1)
        if t in ('td','th') and self.cell is not None:
            if self.stack:self.stack[-1].append('\n'.join(self.cell))
            self.cell=None
        if t=='tr' and self.stack:
            row=self.stack.pop()
            if row:self.rows.append(row)
    def handle_data(self,d):
        if self.skip or not d.strip():return
        d=d.strip();self.text.append(d)
        if self.cell is not None:self.cell.append(d)
def page(url):
    req=Request(url,headers={'User-Agent':'RACE-AI-owner-requested-private-racecards/1.0','Accept':'text/html'})
    with urlopen(req,timeout=12) as r:
        raw=r.read(2000001);ct=r.headers.get('Content-Type','');final=r.geturl()
        if r.status!=200 or len(raw)>2000000 or urlparse(final).hostname!=urlparse(url).hostname:raise ValueError('BAD_RESPONSE')
    enc=re.search(r'charset=([\w-]+)',ct,re.I);text=None
    for e in ([enc[1]] if enc else [])+['utf-8','cp932','euc-jp']:
        try:text=raw.decode(e);break
        except (UnicodeDecodeError,LookupError):pass
    if text is None:raise ValueError('ENCODING_UNVERIFIED')
    p=Visible();p.feed(text);visible='\n'.join(p.text)
    if not has_date(visible):raise ValueError('CURRENT_DAY_IDENTITY_NOT_FOUND')
    head=visible.split('ヘルプ')[0].split('HOME\n地方競馬全国協会')[0]
    return {'url':url,'final_url':final,'observed_at':datetime.now(timezone.utc).isoformat(),'source_sha256':hashlib.sha256(raw).hexdigest(),'visible_text':head[:40000],'table_rows':p.rows[:400],'links':p.links[:350],'state':'CURRENT_DATE_CARD_OBSERVED'}
def b_diagnostic():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    import race_ai
    race_ai.__path__.append(str(root/'pr64-reference/race_ai'))
    from race_ai.official_archive_probe import official_url,inspect_lzh,MAX_ARCHIVE_BYTES
    from race_ai.official_lzh_extract import extract_daily_lzh
    from race_ai.core import _blocks,_decode
    from datetime import date
    import unicodedata
    day=date(2026,11,4);u=official_url(day,'B')
    with urlopen(Request(u,headers={'User-Agent':'RACE-AI-owner-B-layout-check/1.0'}),timeout=12) as r:raw=r.read(MAX_ARCHIVE_BYTES+1)
    info=inspect_lzh(raw);body=extract_daily_lzh(raw,f'B{day:%y%m%d}.TXT')
    text=unicodedata.normalize('NFKC',_decode(body));out={}
    for v,block in _blocks(text,'B'):
        if v!=17:continue
        for part in re.split(r'(?=^\s*\d{1,2}R\s+.*?H\s*\d{3,4}m)',block,flags=re.M):
            m=re.match(r'^\s*(\d{1,2})R\s+',part)
            if m and int(m[1]) in (8,12):out[m[1]]=part
    return {'url':u,'observed_at':datetime.now(timezone.utc).isoformat(),'source_sha256':hashlib.sha256(raw).hexdigest(),'text_sha256':hashlib.sha256(body).hexdigest(),'race_slices':out}
def main():
    p=argparse.ArgumentParser();p.add_argument('--index',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    if datetime.now(JST).date().isoformat()!=DAY:raise SystemExit('DATE_SCOPE_ENDED')
    source=json.loads(Path(a.index).read_text());targets=linked_cards(source['sources'])
    if not 1<=len(targets)<=160:raise SystemExit('UNBOUNDED_CARD_SET')
    output={'schema':'RACE_AI_OWNER_REQUESTED_PUBLIC_CARDS_V1','date_jst':DAY,'forecast_count':0,'not_all_models_ready':True,'sources':[],'source_failures':[]}
    blocked_hosts=set();requests=0
    targets.sort(key=lambda x:(0 if '/toride/' in x[1] else 1 if x[0]=='horse' else 2,x[1]))
    for sport,u in targets:
        host=urlparse(u).hostname
        if host in blocked_hosts:output['source_failures'].append({'sport':sport,'url':u,'reason':'HOST_RATE_OR_ACCESS_STOP'});continue
        requests+=1
        try:output['sources'].append(dict(sport=sport,**page(u)))
        except Exception as e:
            if isinstance(e,HTTPError) and e.code in (401,403,429):blocked_hosts.add(host)
            output['source_failures'].append({'sport':sport,'url':u,'reason':type(e).__name__+': '+str(e)[:180]})
        time.sleep(.8)
    try:output['boat_missing_race_layout']=b_diagnostic()
    except Exception as e:output['boat_missing_race_layout']={'error':type(e).__name__+': '+str(e)[:200]}
    output.update(completed_at=datetime.now(timezone.utc).isoformat(),source_request_count=requests+1)
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x') as f:json.dump(output,f,ensure_ascii=False,separators=(',',':'))
    from collections import Counter
    print('CURRENT_CARDS',dict(Counter(s['sport'] for s in output['sources'])),'FAILURES',len(output['source_failures']))
if __name__=='__main__':main()
