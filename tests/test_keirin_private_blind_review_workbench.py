"""Synthetic private PNG only. No real footage or actual human signed labels."""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import re
import unittest

from race_ai.keirin_blind_rider_holdout_gate import (
    make_proposals,checked_review,HoldoutGateError,
)
from scripts.keirin_private_blind_review_workbench import (
    build,checked_packet,WorkbenchError,DRAFT_SCHEMA,HTML,
)
from scripts.keirin_finalize_blind_review_private import (
    finalize,ReviewFinalizeError,
)

JST=timezone(timedelta(hours=9))
RID="203001151201"
SOURCE="a"*64


class PrivateBlindAnnotationWorkbenchTests(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        os.chmod(self.base,0o700)
        self.packet=self.base/"reviewer_A"
        self.packet.mkdir(mode=0o700)
        self.frames=[]
        for k in range(2):
            image=np.zeros((120,200,3),dtype=np.uint8)
            cv2.rectangle(image,(40+k*20,40),(80+k*20,70),(220,110,30),-1)
            ok,png=cv2.imencode(".png",image)
            self.assertTrue(ok)
            data=png.tobytes()
            frame_sha=sha256(("real_frame_"+str(k)).encode()).hexdigest()
            name=f"source_{k:03d}.png"
            target=self.packet/name
            target.write_bytes(data);os.chmod(target,0o600)
            self.frames.append({
                "frame_sha256":frame_sha,
                "recording_sec":k*2,
                "source_image_file":name,
                "png_bytes_sha256":sha256(data).hexdigest(),
            })
        frozen=make_proposals(
            race_id=RID,recording_sha256=SOURCE,
            model_code_sha256="b"*64,
            model_train_race_ids=[],
            frozen_at="2030-01-15T09:00:00+09:00",
            target_kind="JERSEY_COLOR_REGION",
            frames=[{"frame_sha256":f["frame_sha256"],
                     "recording_sec":f["recording_sec"],
                     "proposals":[]} for f in self.frames],
        )
        self.frozen=self.base/"frozen.json"
        self.frozen.write_text(json.dumps(frozen));os.chmod(self.frozen,0o600)
        self.manifest={
            "schema":"RACE_AI_KEIRIN_PRIVATE_BLIND_REVIEW_PACKET_V1",
            "race_id":RID,
            "recording_sha256":SOURCE,
            "proposal_sha256":frozen["proposal_sha256"],
            "reviewer_id":"reviewer_A_local",
            "frozen_input_exact":True,"review_frame_count":2,
            "frames":self.frames,
            "does_not_contain_model_predictions_or_rider_labels":True,
            "independent_review_completed":False,
            "not_for_public_GitHub_artifacts":True,
        }
        self.form={
            "schema":"RACE_AI_KEIRIN_BLIND_HOLDOUT_INDEPENDENT_REVIEW_V1",
            "race_id":RID,
            "recording_sha256":SOURCE,
            "proposal_sha256":frozen["proposal_sha256"],
            "reviewer_id":"reviewer_A_local",
            "reviewed_at":None,
            "target_kind":"JERSEY_COLOR_REGION",
            "independent_source_frame_read":False,
            "frames":[{"frame_sha256":x["frame_sha256"],
                       "exhaustive_visible_targets":False,"annotations":[]}
                      for x in self.frames],
            "review_sha256":None,
        }
        self.mfile=self.packet/"manifest.json"
        self.formfile=self.packet/"review_UNFINISHED.json"
        self.save()
        self.html=self.base/"local_review_A.html"
        self.draft=self.base/"DRAFT.json"
        self.finished=self.base/"completed_review.json"

    def save(self):
        self.mfile.write_text(json.dumps(self.manifest))
        self.formfile.write_text(json.dumps(self.form))
        os.chmod(self.mfile,0o600)
        os.chmod(self.formfile,0o600)

    def make_draft(self):
        info=checked_packet(self.packet)
        row=[]
        for frame in info["frames"]:
            row.append({
                "frame_sha256":frame["frame_sha256"],
                "exhaustive_visible_targets":True,
                "annotations":[
                    {"bbox_xywh":[.2,.3,.15,.1],
                     "car_number":4,"number_evidence":"COLOR_ONLY",
                     "race_position":"UNKNOWN","line_role":"UNKNOWN"},
                ],
            })
        obj={k:info[k] for k in ("race_id","recording_sha256",
              "proposal_sha256","reviewer_id","target_kind",
              "packet_manifest_sha256")}
        obj["schema"]=DRAFT_SCHEMA
        obj["frames"]=row
        self.draft.write_text(json.dumps(obj))
        os.chmod(self.draft,0o600)
        return obj

    def finalize(self):
        return finalize(packet_dir=self.packet,
                        exported_draft=self.draft,
                        owner_frozen_proposal=self.frozen,
                        private_completed_review=self.finished,
                        clock_now=lambda:datetime(2030,1,15,10,0,tzinfo=JST))

    def test_offline_46_frame_style_workbench_has_no_source_proposals(self):
        result=build(packet_dir=self.packet,output_file=self.html)
        self.assertEqual(result["source_image_count"],2)
        self.assertTrue(result["contains_unencrypted_private_video_frames"])
        self.assertFalse(result["prediction_boxes_or_CI_result_visible"])
        page=self.html.read_text()
        self.assertIn("data:image/png;base64,",page)
        self.assertNotIn('"car_color_candidate"',page)
        self.assertNotIn('"bbox_xywh":',page)
        self.assertNotIn("localStorage.",page)
        self.assertNotIn("fetch(",page)
        self.assertEqual(self.html.stat().st_mode&0o077,0)
        self.assertEqual(result["workbench_sha256"],
                         sha256(self.html.read_bytes()).hexdigest())
        with self.assertRaisesRegex(
            WorkbenchError,"PRIVATE_WORKBENCH_MUST_BE_CREATE_ONCE"):
            build(packet_dir=self.packet,output_file=self.html)

    def test_owner_finalizes_all_frames_and_existing_review_gate_reads_it(self):
        self.make_draft()
        result=self.finalize()
        self.assertEqual(result["fully_reviewed_source_frames"],2)
        self.assertFalse(result["independent_reviewer_identity_authenticated"])
        self.assertFalse(result["reviewer_signature_created"])
        completed=json.loads(self.finished.read_text())
        original=json.loads(self.frozen.read_text())
        checked_review(completed,original)
        self.assertEqual(completed["reviewer_id"],self.form["reviewer_id"])
        self.assertEqual(completed["frames"][0]["annotations"][0]["car_number"],4)
        self.assertEqual(self.finished.stat().st_mode&0o077,0)
        self.assertNotIn("proposals",self.finished.read_text())
        with self.assertRaisesRegex(
            ReviewFinalizeError,"PRIVATE_COMPLETED_REVIEW_MUST_BE_CREATE_ONCE"):
            self.finalize()

    def test_unchecked_frame_blocks_completion_even_with_other_correct_labels(self):
        obj=self.make_draft()
        obj["frames"][1]["exhaustive_visible_targets"]=False
        self.draft.write_text(json.dumps(obj))
        with self.assertRaisesRegex(
            ReviewFinalizeError,"EXHAUSTIVE_SOURCE_FRAME_ANNOTATION_MISSING"):
            self.finalize()
        self.assertFalse(self.finished.exists())

    def test_swapped_frame_sha_and_wrong_packet_reference_are_rejected(self):
        obj=self.make_draft()
        obj["frames"][0]["frame_sha256"]="f"*64
        self.draft.write_text(json.dumps(obj))
        with self.assertRaisesRegex(
            ReviewFinalizeError,"EXHAUSTIVE_SOURCE_FRAME_ANNOTATION_MISSING"):
            self.finalize()
        obj=self.make_draft()
        obj["packet_manifest_sha256"]="d"*64
        self.draft.write_text(json.dumps(obj))
        with self.assertRaisesRegex(
            ReviewFinalizeError,"PRIVATE_BLIND_REVIEW_PACKET_MISMATCH"):
            self.finalize()

    def test_duplicate_car_and_unknown_field_schema_block(self):
        obj=self.make_draft()
        obj["frames"][0]["annotations"].append(
            dict(obj["frames"][0]["annotations"][0]))
        self.draft.write_text(json.dumps(obj))
        with self.assertRaisesRegex(
            ReviewFinalizeError,"KNOWN_RIDER_NUMBER_DUPLICATED_IN_FRAME"):
            self.finalize()
        obj=self.make_draft()
        obj["frames"][0]["annotations"][0]["number_evidence"]="FAKE"
        self.draft.write_text(json.dumps(obj))
        with self.assertRaises(HoldoutGateError):
            self.finalize()

    def test_tampered_private_png_or_prelabelled_packet_block(self):
        source=self.packet/"source_000.png"
        source.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        with self.assertRaisesRegex(
            WorkbenchError,"PRIVATE_SOURCE_IMAGE_SHA_INVALID"):
            build(packet_dir=self.packet,output_file=self.html)
        # restore original valid PNG bytes from the other frame is still a
        # SHA mismatch, not a route to secretly alter the source image.
        source.write_bytes((self.packet/"source_001.png").read_bytes())
        with self.assertRaisesRegex(
            WorkbenchError,"PRIVATE_SOURCE_IMAGE_SHA_INVALID"):
            build(packet_dir=self.packet,output_file=self.html)
        self.form["frames"][0]["exhaustive_visible_targets"]=True
        self.save()
        with self.assertRaisesRegex(
            WorkbenchError,"BLIND_FRAME_METADATA_OR_UNFINISHED_LABEL_INVALID"):
            checked_packet(self.packet)

    def test_public_directory_and_public_png_do_not_get_published(self):
        os.chmod(self.packet,0o755)
        with self.assertRaisesRegex(
            WorkbenchError,"PRIVATE_PACKET_MUST_REMAIN_OWNER_ONLY"):
            build(packet_dir=self.packet,output_file=self.html)
        os.chmod(self.packet,0o700)
        os.chmod(self.packet/"source_001.png",0o644)
        with self.assertRaisesRegex(
            WorkbenchError,"PRIVATE_PACKET_MUST_REMAIN_OWNER_ONLY"):
            build(packet_dir=self.packet,output_file=self.html)


if __name__=="__main__":
    unittest.main()
