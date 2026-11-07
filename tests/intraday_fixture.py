"""Invented official SP structures. No real racer statistics or production key."""
import hashlib,json

def result_document(*,day='20261107',venue='01',number=1,pending=False):
    deadlines=[dict(rno=n,deadline='10:00' if n==1 else f'{11+n//2:02d}:{30*(n%2):02d}',changeflag=0,resultflag=1 if n==1 else 0) for n in range(1,13)]
    body=dict(hd=day,jcd=venue,rno=number,rstop=0,
      teiinfolist=[dict(chk=str(n),teino=str(n),registno=str(4000+n),racername='架空選手'+str(n),racetime='1.50.0') for n in range(1,7)],
      stinfolist=[dict(cs=c,teino=str(n),csdisp=str(c),boatflag=1,boatst=0,st=f'.{10+n}',wintech='') for n,c in [(6,5),(1,2),(5,6),(2,1),(4,4),(3,3)]])
    return dict(dataheader=dict(dataid='TRACS110A',datakey=dict(hd=day,jcd=venue,rno=number),statuscd=0,statusstr='',messageid='',messagestr='',ztcd='',gdate=day,cdatetime='synthetic clock'),
      holdingheader=dict(hd=day,jcd=venue),raceheader=dict(rno=number,rlinklist=deadlines),maindata=None if pending else body)

def packet(doc=None,*,captured='2026-11-07T01:10:00Z'):
    doc=result_document() if doc is None else doc
    raw=json.dumps(doc,ensure_ascii=False,separators=(',',':')).encode()
    key=doc['dataheader']['datakey'];url=f'https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd={key["hd"]}&jcd={key["jcd"]}&rno={key["rno"]}'
    return raw,dict(source_url=url,captured_at=captured,http_status=200,source_sha256=hashlib.sha256(raw).hexdigest())
