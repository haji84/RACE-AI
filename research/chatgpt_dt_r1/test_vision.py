"""Synthetic coloured blobs only; no rider-recognition accuracy evidence."""
from dataclasses import asdict
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw


class VisionTests(unittest.TestCase):
    def setUp(self):
        try:
            self.v = importlib.import_module("research.chatgpt_dt_r1.vision")
        except ModuleNotFoundError as exc:
            if exc.name != "research.chatgpt_dt_r1.vision":
                raise
            self.v = None
        self.assertIsNotNone(self.v, "Automatic candidate detection and tracking are not implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def detector(self, **kwargs):
        settings = dict(bands=(self.v.HSVBand("synthetic-red-patch",.95,.05,.8,.5),),
            min_area_px=4,max_area_px=100,min_aspect_ratio=.5,max_aspect_ratio=2.,min_fill_ratio=.6)
        settings.update(kwargs)
        return self.v.DetectorConfig(**settings)

    def tracking(self, **kwargs):
        settings = dict(max_distance_px=15.,max_gap_seconds=.5,max_missed_frames=2,
                        max_speed_px_s=200.,ambiguity_margin_px=2.,scene_cut_threshold=.4)
        settings.update(kwargs)
        return self.v.TrackingConfig(**settings)

    def frames(self, positions, *, background=None, shots=None):
        entries = []
        for index,centres in enumerate(positions):
            image = Image.new("RGB",(48,32),background[index] if background else (0,0,0))
            draw = ImageDraw.Draw(image)
            for x in centres:
                draw.rectangle((x-1,14,x+1,16),fill=(255,0,0))
            name = f"frame_{index:03d}.png"
            image.save(self.root/name)
            entry = {"file":name,"pts_seconds":round(index*.1,5),"camera_id":"synthetic-camera"}
            if shots:
                entry["shot_id"] = shots[index]
            entries.append(entry)
        manifest = {"schema":"dt-r1-local-frames-v1","source_sha256":"a"*64,
            "source_fps":10.,"event_clock_verified":False,"playback_rate":None,
            "extracted_at":"2026-01-02T10:00:00Z","frames":entries}
        path = self.root/"frames.json"
        path.write_text(json.dumps(manifest))
        return path,manifest

    def identity(self, rider="synthetic-rider", kind="reviewed_video", track_hash=None):
        return {"rider_id":rider,"confidence":.99,"source_video_sha256":"a"*64,"track_sha256":track_hash,
            "provenance":{"kind":kind,"source_url":"https://example.test/synthetic-review",
                "source_sha256":"a"*64,"retrieved_at":"2026-01-02T10:00:00Z",
                "available_at":"2026-01-02T12:00:00Z",
                "reviewer_id":"synthetic-reviewer" if kind=="reviewed_video" else None,
                "reviewed_at":"2026-01-02T11:00:00Z" if kind=="reviewed_video" else None}}

    def test_detects_components_from_pixels_and_enforces_roi_size_shape(self):
        image = Image.new("RGB",(64,32),(0,0,0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8,8,11,11),fill=(255,0,0))
        draw.rectangle((20,8,20,8),fill=(255,0,0))
        draw.rectangle((28,8,38,8),fill=(255,0,0))
        draw.rectangle((52,8,55,11),fill=(255,0,0))
        candidates = self.v.detect_candidates(image,self.detector(roi_xyxy=(0,0,48,32)))
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0].centroid,(9.5,9.5))
        self.assertEqual(candidates[0].bbox,(8,8,12,12))
        self.assertEqual(candidates[0].area_px,16)

    def test_tracks_detected_moving_blobs_without_supplied_tracks(self):
        _,manifest = self.frames([[6],[10],[14]])
        result = self.v.track_frames(manifest,self.detector(),self.tracking(),frame_root=self.root)
        self.assertEqual(len(result["tracks"]),1)
        samples = result["tracks"][0]["samples"]
        self.assertEqual([r["x"] for r in samples],[6.,10.,14.])
        self.assertEqual([r["t_seconds"] for r in samples],[0.,.1,.2])
        self.assertEqual(result["quality"]["detected_candidates"],3)
        self.assertEqual(result["source_kind"],"ai_estimate")

    def test_camera_cuts_reset_identity_for_visual_or_declared_shot_changes(self):
        for backgrounds,shots in (([(0,0,0),(255,255,255)],None),(None,["one","two"])):
            with self.subTest(backgrounds=backgrounds,shots=shots):
                _,manifest = self.frames([[10],[11]],background=backgrounds,shots=shots)
                result = self.v.track_frames(manifest,self.detector(),self.tracking(),frame_root=self.root)
                self.assertEqual(len(result["tracks"]),2)
                self.assertEqual(result["quality"]["camera_cut_resets"],1)
                self.assertNotEqual(result["tracks"][0]["shot_id"],result["tracks"][1]["shot_id"])

    def test_missing_frames_mark_reacquisition_and_long_gaps_expire_tracks(self):
        _,manifest = self.frames([[8],[12],[16]])
        (self.root/manifest["frames"][1]["file"]).unlink()
        result = self.v.track_frames(manifest,self.detector(),self.tracking(),frame_root=self.root)
        self.assertEqual(result["quality"]["missing_frames"],1)
        self.assertEqual(len(result["tracks"]),1)
        self.assertTrue(result["tracks"][0]["samples"][-1]["occluded"])
        expired = self.v.track_frames(manifest,self.detector(),self.tracking(max_gap_seconds=.15),frame_root=self.root)
        self.assertEqual(len(expired["tracks"]),2)
        self.assertEqual(expired["quality"]["expired_tracks"],1)

    def test_cut_on_missing_frame_is_not_lost_when_the_next_frame_returns(self):
        _,manifest = self.frames([[8],[12],[16]])
        manifest["frames"][1]["camera_cut"] = True
        (self.root/manifest["frames"][1]["file"]).unlink()
        result = self.v.track_frames(manifest,self.detector(),self.tracking(),frame_root=self.root)
        self.assertEqual(len(result["tracks"]),2)
        self.assertEqual(result["quality"]["camera_cut_resets"],1)

    def test_hungarian_motion_assignment_does_not_swap_crossing_tracks_at_merge(self):
        _,manifest = self.frames([[8,32],[14,26],[20],[14,26]])
        result = self.v.track_frames(manifest,self.detector(),self.tracking(),frame_root=self.root)
        self.assertEqual(len(result["tracks"]),2)
        tracks = sorted(result["tracks"],key=lambda t:t["samples"][0]["x"])
        self.assertEqual([s["x"] for s in tracks[0]["samples"]],[8.,14.,26.])
        self.assertEqual([s["x"] for s in tracks[1]["samples"]],[32.,26.,14.])
        self.assertEqual(result["quality"]["ambiguous_detections"],1)
        self.assertTrue(tracks[0]["samples"][-1]["occluded"])

    def test_identity_and_wheel_anchor_reviews_are_required_for_timed_crossings(self):
        from research.chatgpt_dt_r1.observations import Gate,VideoTimingConfig
        path,_ = self.frames([[8],[12]])
        basic = self.v.process_manifest(path,self.detector(),self.tracking())
        tid = basic["tracks"][0]["track_id"]
        identity = self.identity(track_hash=basic["tracks"][0]["track_sha256"])
        self.assertEqual(basic["quality"]["timing_eligible_samples"],0)
        self.assertEqual(basic["track_samples"][0]["identity_confidence"],0.)
        self.assertEqual(basic["track_samples"][0]["point_kind"],"candidate_centroid")
        estimated = self.v.process_manifest(path,self.detector(),self.tracking(),identity_map={tid:self.identity(kind="ai_estimate")})
        self.assertLess(estimated["track_samples"][0]["identity_confidence"],.9)
        self.assertEqual(estimated["quality"]["timing_eligible_samples"],0)
        reviewed_identity = self.v.process_manifest(path,self.detector(),self.tracking(),identity_map={tid:identity})
        self.assertEqual(reviewed_identity["quality"]["timing_eligible_samples"],0)
        reviews = [{"track_id":tid,"frame_index":i,"x":x,"y":15.,
            "frame_sha256":hashlib.sha256((self.root/f"frame_{i:03d}.png").read_bytes()).hexdigest(),
            "provenance":self.identity()["provenance"]} for i,x in enumerate((8.,12.))]
        gate = Gate("synthetic-home","FINAL_HOME",(10.,20.),(10.,10.),"synthetic-camera",
            basic["tracks"][0]["shot_id"],"synthetic-line","synthetic-reviewed-line")
        config = VideoTimingConfig(10.,True,"synthetic-event-clock",1.,max_gap_seconds=.2)
        checked = self.v.process_manifest(path,self.detector(),self.tracking(),identity_map={tid:identity},
            reviewed_points=reviews,gates=[gate],timing_config=config)
        self.assertEqual(checked["quality"]["timing_eligible_samples"],2)
        self.assertEqual(len(checked["crossings"]),1)
        self.assertAlmostEqual(checked["crossings"][0]["t_seconds"],.05)
        self.assertEqual(checked["source_kind"],"ai_estimate")
        reviews[0]["frame_sha256"] = "0"*64
        with self.assertRaises(ValueError):
            self.v.process_manifest(path,self.detector(),self.tracking(),identity_map={tid:identity},reviewed_points=reviews)

    def test_rejects_nonmonotonic_timestamps_and_simultaneous_duplicate_identity(self):
        path,manifest = self.frames([[8,32],[10,30]])
        result = self.v.process_manifest(path,self.detector(),self.tracking())
        mapping = {t["track_id"]:self.identity(track_hash=t["track_sha256"]) for t in result["tracks"]}
        with self.assertRaises(ValueError):
            self.v.process_manifest(path,self.detector(),self.tracking(),identity_map=mapping)
        manifest["frames"][1]["pts_seconds"] = 0.
        with self.assertRaises(ValueError):
            self.v.track_frames(manifest,self.detector(),self.tracking(),frame_root=self.root)

    def test_reviewed_point_must_be_in_the_bound_frame_and_clock_must_have_identity(self):
        from research.chatgpt_dt_r1.observations import VideoTimingConfig
        path,_ = self.frames([[8],[12]])
        basic = self.v.process_manifest(path,self.detector(),self.tracking())
        track = basic["tracks"][0]
        reviews = [{"track_id":track["track_id"],"frame_index":0,"x":1000.,"y":15.,
            "frame_sha256":hashlib.sha256((self.root/"frame_000.png").read_bytes()).hexdigest(),
            "provenance":self.identity()["provenance"]}]
        with self.assertRaises(ValueError):
            self.v.process_manifest(path,self.detector(),self.tracking(),
                identity_map={track["track_id"]:self.identity(track_hash=track["track_sha256"])},reviewed_points=reviews)
        unbound = self.v.process_manifest(path,self.detector(),self.tracking(),
            timing_config=VideoTimingConfig(10.,True,"",1.))
        self.assertFalse(unbound["event_clock_verified"])

    def test_cli_produces_local_candidate_json_and_leaves_identity_unverified(self):
        path,_ = self.frames([[8],[10]])
        config = self.root/"detector.json"
        config.write_text(json.dumps({"detector":asdict(self.detector()),"tracking":asdict(self.tracking())}))
        target = self.root/"candidates.json"
        result = subprocess.run([sys.executable,"-m","research.chatgpt_dt_r1.vision","process",
            "--manifest",str(path),"--config",str(config),"--output",str(target)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        output = json.loads(target.read_text())
        self.assertEqual(len(output["tracks"]),1)
        self.assertEqual(output["quality"]["timing_eligible_samples"],0)
        self.assertEqual(output["real_recognition_validation_count"],0)


if __name__ == "__main__":
    unittest.main()
