"""ONE bounded, no-secret public-source smoke for a *real future race*.

Official visible published cutoff 2026-11-18 20:45 JST Utsunomiya1R.
Normal public source URLs already corroborated, not invented. At most two
GETs, zero retries, no private keys, bets or source bytes in GitHub logs.
Reports HOLD if denied/unstable or after close; never says all 79 worked.
"""
from __future__ import annotations

from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from race_ai import keirin_nationwide_auto_generator as auto
from scripts import keirin_capture_public_two_sources as cap
from scripts.keirin_nationwide_auto_forecast import registered_race_ids

RACE="202611182401"
NET="https://keirin.netkeiba.com/race/entry/?race_id=202611182401"
KD="https://keirin.kdreams.jp/utsunomiya/racedetail/2420261117020001/"
CUTOFF="2026-11-18T20:45:00+09:00"
REG=Path(__file__).resolve().parents[1]/"docs/evidence/2026-11-18/keirin_all79_nationwide_AB_registered_v1.json"


def probe():
    now=datetime.now(timezone.utc)
    if (auto.when(CUTOFF)-now).total_seconds()<65:
        return {"state":"HOLD_RACE_NO_LONGER_PRE_CUTOFF",
                "real_source_pages_checked":0,"real_AB_generated":0}
    manifest={
        "schema":cap.SCHEMA,"day_jst":"2026-11-18",
        "source_use_scope":"OWNER_PERSONAL_RESEARCH_ONLY",
        "races":[{
            "race_id":RACE,"netkeirin_url":NET,
            "kdreams_url":KD,"cutoff_hint":CUTOFF}]}
    registered=registered_race_ids(json.loads(REG.read_text(encoding="utf-8")))
    with TemporaryDirectory() as d:
        root=Path(d)
        cards=root/"cards";raw=root/"raw"
        for sub in (cards,raw):
            sub.mkdir(mode=0o700)
            sub.chmod(0o700)
        try:
            response=cap.capture_cycle(
                day_manifest=manifest,registered_ids=registered,
                private_cards_dir=cards,private_raw_dir=raw,
                max_races=1)
        except (cap.SourceCaptureError,ValueError,TypeError):
            return {"state":"HOLD_REAL_PUBLIC_SOURCE_UNAVAILABLE",
                    "real_AB_generated":0}
        if response["normalized_private_cards"]!=1:
            return {"state":"HOLD_REAL_PUBLIC_SOURCE_OR_PARSER",
                    "source_HOLD_states":response["states"],
                    "maximum_public_GETs_in_probe":2,
                    "confirmed_complete_source_pair":False,
                    "real_AB_generated":0}
        snap=json.loads((cards/(RACE+".json")).read_text())
        output=auto.generate_A_B(
            snap,generated_at=datetime.now(timezone.utc).isoformat())
        return {"state":"REAL_SOURCED_PRE_CUTOFF_AUTO_RESEARCH_ONLY",
                "race_id":RACE,
                "real_source_pages_checked":2,
                "source_pair_sha256":auto.digest(snap),
                "starter_count":len(snap["riders"]),
                "A_tickets":len(output["A"]["ranked_tickets"]),
                "B_tickets":len(output["B"]["ranked_tickets"]),
                "six_phase_scenarios":len(output["B"]["six_phase_scenarios"]),
                "independent_organizer_cutoff_verified":False,
                "owner_AES_persisted":False,
                "actual_result_scored":False,
                "national_79_coverage_achieved":False}


if __name__=="__main__":
    try:
        print(json.dumps(probe(),sort_keys=True,ensure_ascii=False))
    except Exception:
        print(json.dumps({"state":"HOLD_PUBLIC_SOURCE_SMOKE_FAILED",
                          "real_AB_generated":0},sort_keys=True))
