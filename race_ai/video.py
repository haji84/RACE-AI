"""Rights-gated local video frame evidence index. NOT boat tracking or power scoring."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

from .core import SourceError


def index_video(path: str | Path, *, rights_confirmed: bool, sample_seconds: float = 2.0,
                max_samples: int = 200) -> dict:
    """Decode local video and record reproducible frame timestamps/fingerprints.

    No images uploaded or redistributed; no assertion of player identification or
    mechanical performance. Frame image SHA depends on decoded color pixels.
    """
    if not rights_confirmed:
        raise SourceError('explicit permitted use of this local video required')
    if not (math.isfinite(sample_seconds) and 0.2 <= sample_seconds <= 60):
        raise SourceError('sampling step must be between 0.2 and 60 seconds')
    if not 1 <= max_samples <= 1000:
        raise SourceError('invalid max_samples')
    try:
        import cv2  # Optional and available only when the operator installs it.
    except ImportError as exc:
        raise SourceError('local video indexing requires opencv-python') from exc
    path=Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise SourceError('missing or empty video file')
    # Enforce bounded file size, no URLs. Local video may be large but not unbounded.
    if path.stat().st_size > 2 * 1024**3:
        raise SourceError('video exceeds 2GB local index limit')
    media_hash=hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024),b''):
            media_hash.update(chunk)
    cap=cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SourceError('unable to decode this local video')
    frames=[]
    try:
        fps=float(cap.get(cv2.CAP_PROP_FPS))
        total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not math.isfinite(fps) or fps<=0 or total<=0:
            raise SourceError('invalid video metadata; frame timing unknown')
        step=max(1,round(fps*sample_seconds))
        for index in range(0,total,step):
            if len(frames)>=max_samples:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES,index)
            ok,frame=cap.read()
            if not ok:
                raise SourceError('video decode failed at sampled frame')
            frames.append({'frame_index':index,'video_seconds':round(index/fps,3),
                           'decoded_sha256':hashlib.sha256(frame.tobytes()).hexdigest()})
    finally:
        cap.release()
    if not frames:
        raise SourceError('no readable video frames')
    return {'source_sha256':media_hash.hexdigest(),'frame_count':total,
            'fps':round(fps,3),'duration_seconds_estimate':round(total/fps,3),
            'samples':frames,'rights_confirmed_by_operator':True,
            'boat_identity':'UNKNOWN','start_acceleration':'UNKNOWN',
            'straight_speed':'UNKNOWN','turn_performance':'UNKNOWN',
            'analysis_status':'FRAME_INDEX_ONLY_REQUIRES_MANUAL_REVIEW'}
