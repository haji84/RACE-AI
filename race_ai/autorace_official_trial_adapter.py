"""Official AUTORACE.JP one-race trial-time HTML adapter. No I/O.

The official Program pages contain generic hidden cancellation notices and
trial-time legends even during races that were held. NEVER interpret an
unscoped '該当レースの開催は中止となりました' as a cancellation fact.
Only race-bound *table cells* under a 試走T heading count as observed trials.

This parser does not verify historical first publication time, source license,
final betting cutoff, or official competition/participant IDs beyond the car
slot. No odds or result content enters the prediction snapshot.
"""
from __future__ import annotations
from html.parser import HTMLParser
from datetime import datetime
from urllib.parse import urlsplit
import hashlib
import re
import unicodedata

SCHEMA="RACE_AI_AUTORACE_RACE_SCOPED_TRIAL_OBSERVATION_V1"
URL=re.compile(r"/race_info/Program/(kawaguchi|isesaki|hamamatsu|iizuka|sanyo)/"
               r"(\d{4}-\d{2}-\d{2})(?:_([1-9]|1[0-2]))?$")
NUM=re.compile(r"3\.[0-9]{2}")
CAR=re.compile(r"[1-8]")
FILL={"","-","--","―","－","－","—","未発表","中止","欠車"}

class TrialContractError(ValueError):pass

def _s(x):
    return " ".join(unicodedata.normalize("NFKC",x or "").split())

class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables=[]
        self.table=None
        self.row=None
        self.cell=None
        self.cell_depth=0
        self.ignored=0
        self.body=[]
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript","template"):
            self.ignored+=1
        if tag=="table":
            if self.table is not None:raise TrialContractError("nested table not supported")
            self.table=[]
        if tag=="tr" and self.table is not None:
            self.row=[]
        if tag in ("th","td") and self.row is not None:
            if self.cell is None:
                self.cell=[];self.cell_depth=1
            else:self.cell_depth+=1
    def handle_data(self,data):
        if not self.ignored:
            if self.cell is not None:self.cell.append(data)
            if self.table is None:self.body.append(data)
    def handle_endtag(self,tag):
        if tag in ("th","td") and self.cell is not None:
            self.cell_depth-=1
            if self.cell_depth==0:
                self.row.append(_s("".join(self.cell)));self.cell=None
        if tag=="tr" and self.row is not None:
            self.table.append(self.row);self.row=None
        if tag=="table" and self.table is not None:
            self.tables.append(self.table);self.table=None
        if tag in ("script","style","noscript","template"):
            self.ignored=max(0,self.ignored-1)

def parse_official_trial(raw,*,source_url,race_day,venue,race_no,captured_at,
                         scheduled_cutoff_at=None):
    if not isinstance(raw,bytes) or not 0<len(raw)<=900000:
        raise TrialContractError("bounded source HTML required")
    u=urlsplit(source_url)
    m=URL.fullmatch(u.path)
    if (u.scheme!="https" or u.netloc!="autorace.jp" or u.query or
        not m or m[1]!=venue or m[2]!=race_day or (m[3] and int(m[3])!=race_no)):
        raise TrialContractError("source identity mismatch")
    if not 1<=race_no<=12:raise TrialContractError("race number invalid")
    try:
        captured=datetime.fromisoformat(captured_at.replace("Z","+00:00"))
    except (AttributeError,ValueError) as e:raise TrialContractError("capture time invalid") from e
    if captured.utcoffset() is None:raise TrialContractError("timezone required")
    if scheduled_cutoff_at is not None:
        limit=datetime.fromisoformat(scheduled_cutoff_at.replace("Z","+00:00"))
        if limit.utcoffset() is None or captured>=limit:
            raise TrialContractError("captured at/after cutoff")
    try:
        text=raw.decode("utf-8",errors="strict")
    except UnicodeDecodeError as e:
        raise TrialContractError("unverified official charset") from e
    parser=Tables();parser.feed(text);parser.close()
    body=_s(" ".join(parser.body))
    # Date and selected race must occur in actual document BODY. Generic
    # event dates are not enough alone. Direct field table is also required.
    daytext=race_day.replace("-","/")
    jpday=f"{int(race_day[5:7])}月{int(race_day[8:10])}日"
    date_found=daytext in body or race_day in body or jpday in body
    number_found=bool(re.search(rf"(?<!\d){race_no}\s*R\b|(?<!\d){race_no}\s*レース",body))
    collected=[]
    qualifying=0
    trial_labeled_table_rows=0
    trial_header_shape_counts={}
    # Aggregate DOM diagnostics only, no source row/athlete values.
    # Existing provider may use paired headings (試走T | 試走T) with
    # four rows of 1-4 / 5-8 in parallel columns.
    table_signatures=[]
    for table in parser.tables:
        widths={}
        for row in table:widths[str(len(row))]=widths.get(str(len(row)),0)+1
        table_signatures.append({
            "rows":len(table),
            "column_width_histogram":widths,
            "numeric_trial_cells_total":sum(
                bool(NUM.fullmatch(_s(cell))) for row in table for cell in row),
            "numbered_car_cells_total":sum(
                bool(CAR.fullmatch(_s(cell))) for row in table for cell in row),
            "trial_heading_cells_total":sum(
                "試走" in _s(cell) for row in table for cell in row),
        })
    for table in parser.tables:
        for i,row in enumerate(table):
            if any("試走" in _s(v) for v in row):
                trial_labeled_table_rows+=1
                shape="|".join("TRIAL" if "試走" in _s(v) else
                               "CAR" if _s(v) in ("車","車番") else
                               "HANDICAP" if _s(v)=="ハンデ" else
                               "OTHER" for v in row[:16])
                trial_header_shape_counts[shape]=trial_header_shape_counts.get(shape,0)+1
            headers=[_s(v).lower() for v in row]
            trial_ids=[j for j,v in enumerate(headers) if v in ("試走t","試走タイム")]
            lane_ids=[j for j,v in enumerate(headers) if v in ("車","車番")]
            if len(trial_ids)!=1 or len(lane_ids)!=1:
                continue
            tr=trial_ids[0];car=lane_ids[0]
            if tr==car:raise TrialContractError("trial and car columns overlap")
            accepted=set()
            measured=0
            missing=0
            for record in table[i+1:]:
                if len(record)<=max(tr,car):continue
                slot=_s(record[car])
                if not CAR.fullmatch(slot):continue
                n=int(slot)
                if n in accepted:raise TrialContractError("duplicate official car number")
                accepted.add(n)
                val=_s(record[tr])
                if NUM.fullmatch(val):measured+=1
                elif val in FILL or val.startswith(("再","F","L")):missing+=1
                else:raise TrialContractError("unrecognized official trial data")
            if accepted:
                qualifying+=1
                collected.append((len(accepted),measured,missing))
    if qualifying!=1:
        # The generic replay title or '試走T' explanatory legend alone
        # is not an actual same-race trial confirmation.
        observed=0;status="TRIAL_RACE_BOUND_TABLE_NOT_FOUND"
        actual=0
    else:
        actual,observed,missing=collected[0]
        status=("TRIAL_NUMERIC_ALL_REGISTERED" if observed==actual and actual>=6
                else "TRIAL_PUBLISHED_PARTIAL" if observed>0
                else "TRIAL_VALUES_NOT_PUBLISHED")
    # Generic text can be present on a valid held race. Its appearance
    # never changes event status. Actual cancellation needs an independent
    # race-specific provider result.
    return {"schema":SCHEMA,
        "source_url":source_url,"race_day":race_day,"venue":venue,"race_no":race_no,
        "source_sha256":hashlib.sha256(raw).hexdigest(),
        "captured_at":captured_at,
        "date_in_body":date_found,
        "race_number_in_body":number_found,
        "race_identity_structurally_sufficient":bool(date_found and number_found and qualifying==1),
        "official_trial_header_tables":qualifying,
        "official_html_tables_seen":len(parser.tables),
        "trial_label_table_rows_seen":trial_labeled_table_rows,
        "trial_label_header_shapes_anonymized":trial_header_shape_counts,
        "anonymized_table_signatures":table_signatures,
        "car_slots_observed":actual,
        "numeric_trial_car_count":observed,
        "status":status if date_found and number_found else "RACE_BODY_IDENTITY_UNVERIFIED",
        "generic_cancel_notice_ignored":True,
        "official_race_cancellation_verified":False,
        "upstream_original_publication_verified":False,
        "source_analysis_rights_admitted":False,
        "model_prediction_executed":False,
        "official_prediction":False}
