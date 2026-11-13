"""Fixed official factual-result GETs; no redirects, login, inline retry or bets."""
from datetime import datetime,timezone
import re,time,ssl
from urllib.parse import urlsplit,parse_qs
import httpx
from .racer_daily import need
from .racer_intraday_source import identity,MAX_RESULT
from .source_retry_policy import SourceWait,plan_http_wait

def allowed(url):
    u=urlsplit(url);q=parse_qs(u.query,keep_blank_values=True)
    if u.scheme=='https' and u.netloc=='www.boatrace.jp' and u.path=='/owpc/pc/race/beforeinfo' and not u.fragment and set(q)=={'hd','jcd','rno'} and all(len(v)==1 for v in q.values()):
        from .racer_beforeinfo import RACE
        rid=q['hd'][0]+'-'+q['jcd'][0]+'-'+q['rno'][0].zfill(2)
        need(RACE.fullmatch(rid) and re.fullmatch('[1-9]|1[0-2]',q['rno'][0]),'BEFOREINFO_HTTP_IDENTITY')
        datetime.strptime(q['hd'][0],'%Y%m%d');return 1000000
    if u.path=='/owsp/sp/spdata':identity(url);return MAX_RESULT
    if u.scheme=='https' and u.netloc=='www.boatrace.jp' and u.path=='/owpc/pc/race/index' and not u.fragment and set(q)=={'hd'} and len(q['hd'])==1 and re.fullmatch('[0-9]{8}',q['hd'][0]):
        datetime.strptime(q['hd'][0],'%Y%m%d');return 1024*1024
    if re.fullmatch(r'https://www1\.mbrace\.or\.jp/od2/K/[0-9]{6}/k[0-9]{6}\.lzh',url):return 1024*1024
    raise ValueError('INTRADAY_HTTP_URL_REJECTED')

class OfficialClient:
    def __init__(self,*,client=None,interval_seconds=1):
        need(type(interval_seconds) is int and 1<=interval_seconds<=3,'INTRADAY_HTTP_PACING_INVALID')
        self.interval_seconds=interval_seconds
        self.client=client or httpx.Client(verify=ssl.create_default_context(),follow_redirects=False,trust_env=True,timeout=15,limits=httpx.Limits(max_connections=1,max_keepalive_connections=1));self.next_start=0
    def __enter__(self):return self
    def __exit__(self,*args):self.client.close()
    def __call__(self,url):
        limit=allowed(url);time.sleep(max(0,self.next_start-time.monotonic()));self.next_start=time.monotonic()+self.interval_seconds
        self.client.cookies.clear()
        try:
            with self.client.stream('GET',url,headers={'User-Agent':'RACE-AI-owner-official-result-statistics/1','Accept':'application/json,text/html'}) as response:
                if response.status_code!=200:
                    p=plan_http_wait(response.status_code,response.headers,datetime.now(timezone.utc));error=SourceWait(p['reason'],p['retry_at'],state=p['state']);error.plan=p;raise error
                need(str(response.url)==url,'INTRADAY_HTTP_IDENTITY');parts=[];size=0
                for part in response.iter_bytes():
                    size+=len(part);need(size<=limit,'INTRADAY_HTTP_SIZE_BOUND');parts.append(part)
                need(size>0,'INTRADAY_HTTP_EMPTY')
            return b''.join(parts),datetime.now(timezone.utc).isoformat()
        except (httpx.HTTPError,TimeoutError,OSError):
            p=plan_http_wait(None,{},datetime.now(timezone.utc));error=SourceWait(p['reason'],p['retry_at'],state=p['state']);error.plan=p;raise error from None
