# KEIRIN video AI: four-lap evidence and private learning (v0.1)

## Ground truth and scope
2026-11-08 Matsuyama 9R WINTICKET live screen recording was independently confirmed: 626.320 seconds, 1280x720 VP8, SHA256 9f8f8a487ebcea6f001f4f4159953c6d0f9a79b7e545fd1b53d6391d83fb7dab. Player images include the start area, racing, finish area, and a result screen. Full-four-lap machine identification is NOT yet demonstrated.
Private frame-feature extraction sanity run decoded 313 low-resolution frames at 2-second spacing without exporting frames or feeding any result. That proves only decode/feature feasibility, not reliable semantic labels.

## Implemented gates
- race_ai/keirin_video_learning.py: bounded video feature extraction, SHA256 and pHash provenance, private reviewed-frame-only scene classifier with independent race holdout, identical source recording and frame duplicate checks. Reviewed label files cannot invent feature vectors: every label must join an exact private extracted frame SHA and source recording SHA. Only START, HOME_PASS, GOAL, REPLAY, RESULT, RACING and PRESTART classes can be learned.
- race_ai/keirin_video_inference.py: a trained model proposes timestamped start, lap pass, finish, replay and result events. Isolated one-frame detections are discarded. The inference output cannot authorize itself.
- race_ai/keirin_video_events.py: requires a chronological start, exactly four distinct live pass events, goal and post-goal result; rejects repeat-frame hashes/perceptual duplicates, replay intervals, weak confidence, implausible lap intervals, and spurious after-goal laps. A separate trusted_visual_verifier callback must verify the actual source and labeled frames for approval.
- race_ai/keirin_video_postrace_pdca.py: produces only an owner-private postrace learning candidate after independent full-lap, frozen original forecast, verified official result, and permission checks. Never feeds post-race footage into the same race's pre-cutoff prediction.
- scripts/keirin_video_ai_owner_cli.py: extract/train/infer CLI for owner-side private execution. Rejects real footage extraction on public GitHub-hosted CI. Refuses to overwrite prior output.

## Acceptance boundaries
1. Actual reviewed examples from at least THREE different real races are required. Training and validation race IDs, recording hashes, frame hashes must be disjoint.
2. Holdout macro-F1 >=0.85 with every class represented by >=2 images is a future gate, not an observed accuracy figure. Output scores are NOT calibrated probabilities.
3. The event verifier must independently confirm all four passes in original live footage and exclude replay shots from the count; synthetic CI never proves this.
4. A verified lap report is not enough to update live prediction; rights checks and frozen pre-cutoff prediction/official-result attestation must independently pass.
5. Keep RACE-AI PR Draft. Do not expose video, labels, secrets, raw derived visual features, or copyrighted frames in public GitHub source/artifacts/logs.

## Owner-local usage
python -m scripts.keirin_video_ai_owner_cli extract --race-id 20261108-matsuyama-9R --video /private/9r.webm --every-seconds 2 --output /private/9r-features.json
python -m scripts.keirin_video_ai_owner_cli train --features /private/features/raceA.json --reviewed-labels /private/review/raceA.json --features /private/features/raceB.json --reviewed-labels /private/review/raceB.json --features /private/features/raceC.json --reviewed-labels /private/review/raceC.json --output /private/scene-model.json
python -m scripts.keirin_video_ai_owner_cli infer --features /private/9r-features.json --model /private/scene-model.json --output /private/9r-candidates.json

## Current status
Synthetic tests passed for frame decoding, candidate production, replay/duplicate rejection, scene classifier holdout, and post-race leakage guards. Real 9R video frame extraction was checked privately, but a real independently validated multi-race scene model has not yet been trained. Actual hands-free four-lap count and replay detection accuracy remain NOT VERIFIED.
Only advance to broader races after the heldout test and private evidentiary review pass. Never touch existing PR71 forecast weights or pre-cutoff originals merely to claim progress.

## 2026-11-09 owner policy update: verified short clips
- **Full four-lap footage has priority, not exclusivity.** If all laps are not accessible, an independently reviewed short historic replay can still train attack, final sprint, positioning, finish/goal and replay SCENE categories that are visibly present.
- Partial highlights NEVER establish four full laps or the non-occurrence of an unseen tactic. Review-derived positives are stored separately from unknown/off-camera actions, without setting missing=0.
- Implementation: race_ai/keirin_video_clip_policy.py, race_ai/keirin_video_partial_learning.py and create_partial_postrace_learning_candidate in race_ai/keirin_video_postrace_pdca.py. Older full-lap proof and official-model-promotion gates remain strict.
- Detailed authoritative rules: docs/KEIRIN_PARTIAL_VIDEO_TRAINING_POLICY_20261109.md.
- WINTICKET 2026-10-30 Yahiko 1R was played successfully at 80.164s; it is a PARTIAL_HIGHLIGHTS **candidate**, NOT yet an externally permitted, reviewed or trained video. Do not claim improved forecast accuracy.
