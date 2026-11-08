"""Offline complete 210/504 odds intake with invented data only."""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
from itertools import permutations
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_owner_manual import PersonalOwnerObservations, PERSONAL_MARKER
from race_ai.keirin_owner_odds_csv import (
    OwnerOddsCsvError, parse_full_odds_csv, stage_owner_saved_odds_csv
)

NOW="2030-01-15T09:22:00+09:00"
CUTOFF="2030-01-15T10:00:00+09:00"
RID="keirin:2030-01-15:fictional-venue:3"


def fixture(starters=range(1,8)):
    buff=io.StringIO(newline="")
    writer=csv.writer(buff,lineterminator="\n")
    writer.writerow(("first","second","third","decimal_odds"))
    for i,t in enumerate(permutations(starters,3)):
        writer.writerow((*t,100.0+i))
    raw=buff.getvalue().encode()
    meta={
        "race_id":RID,"official_cutoff_at":CUTOFF,
        "starters":list(starters),
        "source_url":"https://example.invalid/fixture-odds",
        "rights_ref":PERSONAL_MARKER,
        "csv_sha256":sha256(raw).hexdigest(),
    }
    return raw,meta


def admitted():
    return PersonalOwnerObservations(
        source_hosts=["example.invalid"],now=NOW).allowed


class OwnerOddsCsvTests(unittest.TestCase):
    def test_210_complete_synthetic_issued_at_runtime_not_backdated(self):
        raw,meta=fixture()
        result=parse_full_odds_csv(raw,meta,now=NOW,grant_check=admitted())
        self.assertEqual(result["schema"],
                         "RACE_AI_KEIRIN_TRIFECTA_ODDS_SNAPSHOT_V1")
        self.assertEqual(len(result["prices"]),210)
        self.assertEqual(result["captured_at"],"2030-01-15T00:22:00+00:00")
        self.assertEqual(len({
            tuple(p["triple"]) for p in result["prices"]}),210)

    def test_504_nine_riders_complete(self):
        raw,meta=fixture(range(1,10))
        value=parse_full_odds_csv(raw,meta,now=NOW,grant_check=admitted())
        self.assertEqual(len(value["prices"]),504)

    def test_no_guessing_missing_or_duplicated_combinations(self):
        raw,meta=fixture()
        s=raw.decode().splitlines()
        for broken in ("\n".join(s[:-1])+"\n",
                       "\n".join(s[:2]+[s[1]]+s[3:])+"\n"):
            content=broken.encode()
            other={**meta,"csv_sha256":sha256(content).hexdigest()}
            with self.assertRaises(OwnerOddsCsvError):
                parse_full_odds_csv(content,other,now=NOW,
                                    grant_check=admitted())

    def test_sha_tampering_and_invalid_odds_and_capped_placeholder(self):
        raw,meta=fixture()
        with self.assertRaisesRegex(OwnerOddsCsvError,"HASH"):
            parse_full_odds_csv(raw[:-1],meta,now=NOW,
                                grant_check=admitted())
        for price in ("0","nan","9999.9","1.0","-2","inf"):
            broken=raw.decode().replace(",100.0\n",","+price+"\n",1).encode()
            changed={**meta,"csv_sha256":sha256(broken).hexdigest()}
            with self.subTest(price=price),self.assertRaises(OwnerOddsCsvError):
                parse_full_odds_csv(broken,changed,now=NOW,
                                    grant_check=admitted())

    def test_rakuten_and_disallowed_origin_refused(self):
        raw,meta=fixture()
        for url in ("https://keirin.kdreams.jp/odds",
                    "https://evil.invalid/odds"):
            with self.subTest(url=url):
                with self.assertRaises(OwnerOddsCsvError):
                    parse_full_odds_csv(raw,{**meta,"source_url":url},
                                        now=NOW,grant_check=admitted())

    def test_future_after_cutoff_and_65s_margin_refused(self):
        raw,meta=fixture()
        for now in ("2030-01-15T09:59:00+09:00",
                    "2030-01-15T10:01:00+09:00"):
            with self.assertRaisesRegex(OwnerOddsCsvError,"CUTOFF"):
                parse_full_odds_csv(raw,meta,now=now,
                                    grant_check=admitted())

    def test_no_provider_fetch_and_create_only_private_odds_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/"odds_csv").mkdir()
            raw,meta=fixture()
            (root/"odds_csv"/"one.csv").write_bytes(raw)
            (root/"odds_csv"/"one.meta.json").write_text(
                json.dumps(meta),encoding="utf8")
            first=stage_owner_saved_odds_csv(
                root,now=NOW,grant_check=admitted())
            self.assertEqual(first["files_seen"],1)
            self.assertEqual(first["created"],1)
            self.assertEqual(first["provider_network_requests"],0)
            private=list((root/"odds").glob("*.json"))
            self.assertEqual(len(private),1)
            doc=json.loads(private[0].read_text())
            self.assertEqual(len(doc["prices"]),210)
            again=stage_owner_saved_odds_csv(
                root,now=NOW,grant_check=admitted())
            self.assertEqual(again["already_same"],1)
            self.assertEqual(again["created"],0)
            next_cycle=stage_owner_saved_odds_csv(
                root,now="2030-01-15T09:23:00+09:00",
                grant_check=admitted())
            self.assertEqual(next_cycle["rejected"],0)
            self.assertEqual(next_cycle["already_same"],1)
            old_at_cutoff=stage_owner_saved_odds_csv(
                root,now="2030-01-15T10:05:00+09:00",
                grant_check=admitted())
            self.assertEqual(old_at_cutoff["already_same"],1)
            self.assertEqual(private[0].read_text(),
                             json.dumps(doc,ensure_ascii=False,
                                        separators=(",",":"),sort_keys=True))
            self.assertFalse(first["official_rights_verified"])
            self.assertFalse(first["external_capture_time_verified"])

    def test_modified_owner_csv_does_not_replace_frozen_first_odds(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/"odds_csv").mkdir()
            raw,meta=fixture()
            src=root/"odds_csv"/"one.csv"
            entry=root/"odds_csv"/"one.meta.json"
            src.write_bytes(raw)
            entry.write_text(json.dumps(meta),encoding="utf8")
            self.assertEqual(stage_owner_saved_odds_csv(
                root,now=NOW,grant_check=admitted())["created"],1)
            saved=next((root/"odds").glob("*.json"))
            prior=saved.read_bytes()
            altered=raw.replace(b",100.0\\n",b",101.0\\n",1)
            # Preserve accurate SHA for the altered bytes. The immutable
            # source binding still refuses a different value after freeze.
            src.write_bytes(altered)
            meta["csv_sha256"]=sha256(altered).hexdigest()
            entry.write_text(json.dumps(meta),encoding="utf8")
            again=stage_owner_saved_odds_csv(
                root,now="2030-01-15T09:23:00+09:00",
                grant_check=admitted())
            self.assertEqual(again["rejected"],1)
            self.assertEqual(saved.read_bytes(),prior)

    def test_invalid_metadata_never_creates_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/"odds_csv").mkdir()
            raw,meta=fixture()
            (root/"odds_csv"/"one.csv").write_bytes(raw)
            meta.pop("csv_sha256")
            (root/"odds_csv"/"one.meta.json").write_text(
                json.dumps(meta),encoding="utf8")
            status=stage_owner_saved_odds_csv(
                root,now=NOW,grant_check=admitted())
            self.assertEqual(status["rejected"],1)
            self.assertEqual(status["created"],0)
            self.assertFalse(list((root/"odds").glob("*.json")))


if __name__=="__main__":
    unittest.main()
