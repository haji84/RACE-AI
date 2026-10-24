import hashlib
import unittest
from datetime import date
from race_ai.core import SourceError
from race_ai.venue_real_html_evidence import verify_real_html

DAY=date(2026,10,14)
URL="https://www.boatrace.jp/owpc/pc/race/raceresult?rno=3&jcd=18&hd=20261014"
MAP={"finish":0,"lane":1,"registration":2,"name":3,"st":4}
HTML=("<table>"+"".join(f"<tr><td>{i}</td><td>{i}</td><td>{4000+i}</td><td>選手{i}</td><td>0.1{i}</td></tr>" for i in range(1,7))+"</table>").encode()
ENTRIES=[{"race_id":"20261014-18-03","lane":i,"racer_registration_id":str(4000+i)}
         for i in range(1,7)]


class RealHtmlEvidenceContractTests(unittest.TestCase):
    def run_case(self,raw=HTML,sha=None):
        return verify_real_html(html_bytes=raw,source_url=URL,day=DAY,race_no=3,
            table_index=0,column_map=MAP,entries=ENTRIES,
            captured_at="2026-10-14T12:00:00+09:00",
            expected_sha256=sha or hashlib.sha256(HTML).hexdigest(),
            reviewed_by="synthetic-fixture-review")

    def test_synthetic_contract_only(self):
        result=self.run_case()
        self.assertEqual(result["matched_entries"],6)
        self.assertEqual(result["status"],"EVIDENCE_MAPPED_STRUCTURAL_JOIN_NOT_PUBLICATION_PERMISSION")

    def test_tampered_html_rejected(self):
        with self.assertRaises(SourceError):
            self.run_case(raw=HTML+b"changed")

    def test_missing_source_rejected(self):
        with self.assertRaises(SourceError):
            self.run_case(raw=b"")
