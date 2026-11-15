"""Tiny fictional BGR PNGs only, no real athlete/video/identity in CI."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import base64
import json
import os
import unittest

from race_ai.keirin_blind_rider_holdout_gate import make_proposals
from race_ai.keirin_color_ab_stability import (
    conservative_blobs,compare_a_b_regions,
)
from race_ai.keirin_visual_jersey_proposals import detect_color_regions
from race_ai.keirin_bicycle_shape_context import BicycleContextError
from race_ai.keirin_color_ab_stability import ABStabilityError
from scripts.keirin_private_bicycle_shape_motion_audit import run


class PrivateBicycleCameraResearchFixture(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np

        self.cv2=cv2
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        os.chmod(self.base,0o700)
        frames=[]
        self.expected=[0,0,0,0]
        for ix in range(2):
            img=np.full((292,515,3),150,np.uint8)
            cv2.rectangle(img,(181+ix*8,123),(206+ix*8,137),
                          (225,145,50),-1)
            for x in (178,220):
                cv2.circle(img,(x+ix*8,190),20,(8,8,8),2)
            ok,encoded=cv2.imencode(".png",img)
            self.assertTrue(ok)
            source_sha=sha256(img.tobytes()).hexdigest()
            found=detect_color_regions(img,roster=list(range(1,8)),
                                      source_crop_sha256=source_sha)
            props=[{
                "bbox_xywh":[x/1024,y/584,w/1024,h/584],
                "car_color_candidate":p["car_color_candidate"],
                "identification_source":"COLOR_ONLY",
            } for p in found["proposals"]
              for x,y,w,h in [p["bbox_xywh_1024x584"]]]
            b=conservative_blobs(img,expected_frame_sha256=source_sha)
            pair=compare_a_b_regions(props,b)
            for i,k in enumerate((
                "a_frozen_blob_count","b_stricter_blob_count",
                "a_b_spatially_paired_color_blobs",
                "a_b_spatial_and_color_consistent_blobs",
            )):
                self.expected[i]+=pair[k]
            frames.append({
                "frame_sha256":source_sha,"recording_sec":ix*2,
                "proposals":props,
                "image_data_url":"data:image/png;base64,"+
                                 base64.b64encode(encoded.tobytes()).decode(),
            })
        self.pred=make_proposals(
            race_id="203001151201",recording_sha256="a"*64,
            model_code_sha256="b"*64,model_train_race_ids=[],
            frames=[{k:v for k,v in f.items() if k!="image_data_url"}
                    for f in frames],
            frozen_at="2030-01-15T08:00:00+09:00",
            target_kind="JERSEY_COLOR_REGION")
        self.pred_file=self.base/"frozen.json"
        self.pred_file.write_text(json.dumps(self.pred))
        self.files={}
        for identity in ("blind_A_01","blind_B_02"):
            obj={
                "draft_schema":"RACE_AI_KEIRIN_PRIVATE_BLIND_ANNOTATION_DRAFT_V1",
                "race_id":self.pred["race_id"],
                "recording_sha256":self.pred["recording_sha256"],
                "proposal_sha256":self.pred["proposal_sha256"],
                "reviewer_id":identity,
                "target_kind":"JERSEY_COLOR_REGION",
                "packet_manifest_sha256":"f"*64,
                "frames":[{k:v for k,v in row.items() if k!="proposals"}
                          for row in frames],
            }
            f=self.base/(identity+".html")
            f.write_text('<script id="payload" type="application/json">'+
                         json.dumps(obj,separators=(",",":"))+
                         '</script>')
            self.files[identity]=f
        self.sha_A=sha256(self.files["blind_A_01"].read_bytes()).hexdigest()
        self.sha_B=sha256(self.files["blind_B_02"].read_bytes()).hexdigest()

    def audit(self,*,baseline=None,sha_A=None):
        return run(
            frozen_proposals=self.pred_file,
            private_html_a=self.files["blind_A_01"],
            private_html_b=self.files["blind_B_02"],
            html_a_sha256=self.sha_A if sha_A is None else sha_A,
            html_b_sha256=self.sha_B,
            expected_baseline=tuple(self.expected) if baseline is None else baseline)

    def test_original_exact_source_and_bicycle_context_end_to_end(self):
        result=self.audit()
        self.assertEqual(result["original_source_bound_frame_hashes_verified"],2)
        self.assertEqual(result["bicycle_shape_context"]["frozen_A_color_regions"],
                         self.expected[0])
        self.assertGreaterEqual(
            result["bicycle_shape_context"][
                "research_weak_bicycle_context_counts"]["WEAK_WHEEL_PAIR_CONTEXT"],1)
        self.assertEqual(result["camera_background_motion_quality"][
            "source_frame_pairs"],1)
        self.assertEqual(result["color_candidate_track_scene_break"][
            "source_frames"],2)
        self.assertFalse(result["actual_rider_number_or_person_identity_proven"])
        self.assertIsNone(result["true_rider_recall_or_precision_pct"])
        self.assertFalse(result["existing_model_or_official_PDCA_modified"])

    def test_wrong_stored_html_bytes_not_accepted(self):
        with self.assertRaisesRegex(
            ABStabilityError,"PRIVATE_HTML_BYTES_SHA_MISMATCH"):
            self.audit(sha_A="f"*64)

    def test_original_A_B_counts_must_not_change_to_fit_desired_report(self):
        tampered=(self.expected[0]+1,*self.expected[1:])
        with self.assertRaisesRegex(
            BicycleContextError,"FROZEN_A_B_COUNTS_CHANGED"):
            self.audit(baseline=tampered)

    def test_wrong_private_png_frame_sha_fails_instead_of_marking_missed(self):
        obj=json.loads(self.pred_file.read_text())
        obj["frames"][0]["frame_sha256"]="f"*64
        from race_ai.keirin_blind_rider_holdout_gate import digest
        obj["proposal_sha256"]=digest({
            k:v for k,v in obj.items() if k!="proposal_sha256"})
        self.pred_file.write_text(json.dumps(obj))
        with self.assertRaises(Exception):
            self.audit()


if __name__=="__main__":
    unittest.main()
