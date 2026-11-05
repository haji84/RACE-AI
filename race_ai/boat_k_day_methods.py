"""Historical K labels only; never infer a winning method from finish or frame."""
import re
import unicodedata

METHOD = {'逃げ':'nige','差し':'sashi','まくり':'makuri','捲り':'makuri','まくり差し':'makurizashi','捲り差し':'makurizashi','抜き':'nuki','恵まれ':'megumare'}
HEADER = re.compile(r'^\s*(\d{1,2})R\s+.*?H\s*\d{3,4}m',re.I|re.M)

def method_of(text):
    found=[]
    for line in unicodedata.normalize('NFKC',text).splitlines():
        compact=''.join(line.split())
        if compact in METHOD: found.append(METHOD[compact]);continue
        header=re.match(r'^\s*着\s+艇\s+登番\s+.*?\s+レースタイム\s+(.+?)\s*$',line)
        if header:
            token=''.join(header[1].split())
            if token in METHOD:found.append(METHOD[token])
            continue
        if re.match(r'^\s*0?1\s+[1-6]\s+[0-9]{4}\s+',line):
            m=re.search(r'\s(?:[0-9]+[.:][0-9]+[.:][0-9]+)\s+(.+?)\s*$',line)
            token=''.join(m[1].split()) if m else ''
            if token in METHOD:found.append(METHOD[token])
    return found[0] if len(found)==1 else None

def join_k(raw,day,venue,closing,captured_at,digest,blocks,parse_k):
    """Keep individual normal races; reject ambiguity and verify date inside source body."""
    txt=unicodedata.normalize('NFKC',raw.decode('cp932')); records=[]; excluded={}
    target=[b for code,b in blocks(txt,'K') if code==int(venue)]
    if len(target)!=1:raise ValueError('K_VENUE_MISSING_OR_AMBIGUOUS')
    body=target[0]; headers=list(HEADER.finditer(body)); pre=body[:headers[0].start()] if headers else ''
    dates=re.findall(r'(20\d\d)\s*(?:/|年)\s*(\d{1,2})\s*(?:/|月)\s*(\d{1,2})',pre)
    if not dates or {(int(y),int(m),int(d)) for y,m,d in dates}!={(day.year,day.month,day.day)}:raise ValueError('K_INTERNAL_DATE_UNVERIFIED')
    seen=set()
    for i,h in enumerate(headers):
        n=int(h.group(1));rid=f'{day:%Y%m%d}-{venue}-{n:02d}'
        if n not in range(1,13) or n in seen:raise ValueError('K_RACE_ID_INVALID');
        seen.add(n);segment=body[h.start():(headers[i+1].start() if i+1<len(headers) else len(body))]; method=method_of(segment)
        if not method:excluded[rid]='METHOD_MISSING_OR_AMBIGUOUS';continue
        try:
            packet=('STARTK\n'+venue+'KBGN\n'+pre+'\n'+segment+'\n'+venue+'KEND\n').encode('cp932');rows=parse_k(packet,day.isoformat())
            if len(rows)!=6 or {r['race_id'] for r in rows}!={rid} or {r['finish'] for r in rows}!=set(range(1,7)) or {r['course'] for r in rows}!=set(range(1,7)) or any(r['st_status']!='OK' for r in rows):raise ValueError('special finish')
            records.append({'race_id':rid,'cutoff_at':closing[n].isoformat(),'result_captured_at':captured_at,'source_sha256':digest,'winner_method':method,'entries':[{'frame':r['lane'],'course':r['course'],'finish':r['finish'],'racer_id':r['racer_id']} for r in rows]})
        except (KeyError,ValueError,UnicodeError):excluded[rid]='UNVERIFIED_OR_SPECIAL_FINISH'
    return records,excluded
