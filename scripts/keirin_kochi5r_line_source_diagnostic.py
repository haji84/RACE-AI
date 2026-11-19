"""2026-11-18 Kochi5R actual Kdreams page structure, sanitized diagnostic.

Single ordinary GET; no raw HTML, lineup, rider info or page snippet in logs.
Only distinguish line-prefix ambiguity and HTML heading structure. This
diagnostic never creates a forecast or recategorizes a race.
"""
from __future__ import annotations
from datetime import datetime,timezone
from unicodedata import normalize
from bs4 import BeautifulSoup
import json
import re

from scripts.keirin_capture_public_two_sources import fetch_once,SourceCaptureError
from race_ai.keirin_public_two_source_normalizer import _text,TOKENS,FORM

URL="https://keirin.kdreams.jp/kochi/racedetail/7420261117020005/"
CUTOFF=datetime.fromisoformat("2026-11-18T21:55:00+09:00")


def diagnostic():
    if (CUTOFF-datetime.now(timezone.utc)).total_seconds()<65:
        return {"state":"HOLD_AFTER_PUBLISHED_CUTOFF","provider_GETs":0}
    try:
        raw=fetch_once(URL)
        html,txt,_=_text(raw)
        soup=BeautifulSoup(html,"html.parser")
        heads=[x.get_text(" ",strip=True) for x in
               soup.find_all(["h1","h2","h3","h4","h5","h6"])]
        sec=txt.rsplit("並び予想",1)[1] if "並び予想" in txt else ""
        sec=sec.split("レース評",1)[0].split("予想担当",1)[0]
        mat=list(TOKENS.finditer(sec))
        prefix=sec[:mat[0].start()] if mat else sec[:120]
        before=normalize("NFKC",prefix).strip()
        values=re.findall("[0-9]+",before)
        result={
            "state":"SANITIZED_KOCHI5_LINE_STRUCTURE_ONLY",
            "provider_GETs":1,
            "heading_count":len(heads),
            "explicit_line_heading_count":sum(x=="並び予想" for x in heads),
            "line_marker_count_in_page":txt.count("並び予想"),
            "pre_role_fragment_characters":len(before),
            "pre_role_fragment_contains_digit":bool(values),
            "pre_role_digit_token_count":len(values),
            "pre_role_digit_token_lengths":[len(x) for x in values][:16],
            "pre_role_contains_arrow":"←" in before,
            "pre_role_contains_slash":"/" in before or "／" in before,
            "recognized_car_role_tokens":len(mat),
            "role_sequence_types":[x.group(2) for x in mat],
            "explicit_slash_line_pattern_present":bool(FORM.search("並び予想"+sec)),
            "source_copy_or_rider_names_logged":False,
            "actual_A_B_sealed":False,
        }
        return result
    except (SourceCaptureError,ValueError,TypeError,KeyError,IndexError):
        return {"state":"HOLD_REAL_LINE_HTML_UNAVAILABLE_OR_AMBIGUOUS",
                "provider_GETs_max":1,"actual_A_B_sealed":False}


if __name__=="__main__":
    print(json.dumps(diagnostic(),sort_keys=True,ensure_ascii=False))
