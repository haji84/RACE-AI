#!/usr/bin/env python3
"""Capture ordinary public official history to an owner-only local directory.

Only observed profile GET and published result form POST are sent. Cookies are
kept as in an ordinary session. A denial/challenge stops collection; no client,
proxy, identity, endpoint or credential substitution is attempted. The output
is private source evidence, not a forecast or a proof of server-timed storage.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from race_ai import keirin_official_form_history as form


class CaptureError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise CaptureError(code)


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()


def _private_directory(path):
    path = Path(path).absolute()
    checkout = Path(__file__).resolve().parents[1]
    need(not path.is_relative_to(checkout), "HOLD_PRIVATE_OUTPUT_INSIDE_CHECKOUT")
    for parent in (path, *path.parents):
        need(not parent.is_symlink() and not (parent / ".git").exists(), "HOLD_PRIVATE_PATH_UNSAFE")
    if not path.exists():
        path.mkdir(mode=0o700, parents=False)
    mode = path.stat()
    need(stat.S_ISDIR(mode.st_mode) and stat.S_IMODE(mode.st_mode) == 0o700 and
         mode.st_uid == os.geteuid(), "HOLD_PRIVATE_DIRECTORY_PERMISSIONS")
    return path


def _save_once(path, raw):
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        need(not path.is_symlink() and path.read_bytes() == raw and
             stat.S_IMODE(path.stat().st_mode) == 0o600, "HOLD_CREATE_ONLY_CONFLICT")
        return
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


class OfficialHistoryCapture:
    def __init__(self, output_dir, *, cutoff_at, target_race_id, max_requests=150):
        self.root = _private_directory(output_dir)
        self.cutoff = form._aware(cutoff_at)
        need(re.fullmatch(r"20[0-9]{10}", target_race_id) is not None, "HOLD_TARGET_RACE_INVALID")
        self.target_race_id = target_race_id
        self.target_date = datetime.strptime(target_race_id[:8], "%Y%m%d").date()
        need(type(max_requests) is int and 1 <= max_requests <= 300, "HOLD_REQUEST_BUDGET_INVALID")
        self.max_requests = max_requests
        self.count = 0
        self.cache = {}
        self.receipts = []
        self.http_status_counts = {}
        self.cookie_path = self.root / "ordinary_official_session.cookies"
        _save_once(self.cookie_path, b"")
        self.last_request = 0.0
        self.profile_url = None

    def check(self):
        need(datetime.now(timezone.utc) < self.cutoff - timedelta(seconds=65), "HOLD_CAPTURE_TOO_LATE")
        need(self.count < self.max_requests, "HOLD_REQUEST_BUDGET")

    def fetch(self, url, *, token=None):
        need(type(url) is str and (re.fullmatch(r"https://keirin\.jp/sp/racerracentrecord\?snum=[0-9]{6}", url)
             and token is None or url == "https://keirin.jp/sp/race" and type(token) is str
             and re.fullmatch(r"[A-Za-z0-9_-]{43}", token)), "HOLD_UNPUBLISHED_ROUTE")
        key = (url, token)
        if key in self.cache:
            return self.cache[key]
        self.check()
        remaining = 1.0 - (time.monotonic() - self.last_request)
        if remaining > 0:
            time.sleep(remaining)
        self.check()
        body_fd, body_name = tempfile.mkstemp(prefix="capture-", dir=self.root)
        head_fd, head_name = tempfile.mkstemp(prefix="headers-", dir=self.root)
        os.close(body_fd)
        os.close(head_fd)
        body_path, header_path = Path(body_name), Path(head_name)
        args = ["curl", "--silent", "--show-error", "--max-time", "25", "--max-filesize", "8000000",
                "--cookie", str(self.cookie_path), "--cookie-jar", str(self.cookie_path),
                "--output", str(body_path), "--dump-header", str(header_path), "--write-out", "%{http_code}"]
        fields = None
        if token is not None:
            need(self.profile_url is not None, "HOLD_RESULT_WITHOUT_PROFILE_SESSION")
            fields = {"encp": token, "disp": "SJ0326"}
            args += ["--referer", self.profile_url, "--data", urlencode(fields)]
        args.append(url)
        self.count += 1
        self.last_request = time.monotonic()
        proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
        captured = datetime.now(timezone.utc).isoformat()
        code = proc.stdout.strip()
        need(re.fullmatch(r"[0-9]{3}", code) is not None, "HOLD_TRANSPORT_STATUS_UNKNOWN")
        self.http_status_counts[code] = self.http_status_counts.get(code, 0) + 1
        raw, headers = body_path.read_bytes(), header_path.read_bytes()
        digest, header_digest = sha256(raw).hexdigest(), sha256(headers).hexdigest()
        _save_once(self.root / (digest + ".html"), raw)
        _save_once(self.root / (header_digest + ".headers"), headers)
        body_path.unlink()
        header_path.unlink()
        receipt = dict(source_url=url, method="POST" if token else "GET", form_fields=fields,
                       http_status=int(code), captured_at=captured, bytes_sha256=digest,
                       headers_sha256=header_digest, kind="PROGRAM")
        self.receipts.append(receipt)
        need(code not in ("401", "403", "407", "429"), "HOLD_PROVIDER_DENIED")
        need(proc.returncode == 0 and code == "200", "HOLD_OFFICIAL_SOURCE_UNAVAILABLE")
        need(not re.search(rb"captcha|turnstile|challenge-platform|just a moment|verify you are", raw, re.I),
             "HOLD_PROVIDER_CHALLENGE")
        self.check()
        self.cache[key] = (raw, receipt)
        if token is None:
            self.profile_url = url
        return raw, receipt

    def capture_rider(self, *, car, registration_id):
        form._registration(registration_id)
        need(type(car) is int and 1 <= car <= 9, "HOLD_ROSTER_CAR_INVALID")
        raw, source = self.fetch("https://keirin.jp/sp/racerracentrecord?snum=" + registration_id)
        profile = form.parse_profile(raw, expected_registration_id=registration_id,
                                     observed_at=source["captured_at"])
        groups = {}
        for ref in profile["history_references"]:
            key = (ref["current_meeting"], ref["meeting_label"], ref["venue_label"])
            groups.setdefault(key, []).append(ref)
        newest = [ref for group in groups.values() for ref in reversed(group)]
        results, seen, finished = [], set(), 0

        def acquire(ref):
            if ref["token"] in seen:
                return
            result_raw, result_source = self.fetch(ref["source_url"], token=ref["token"])
            parsed = form.parse_history_result(result_raw, expected_registration_id=registration_id,
                                               observed_at=result_source["captured_at"], expected_reference=ref)
            need(parsed["race_id"] != self.target_race_id and
                 datetime.strptime(parsed["race_date"], "%Y-%m-%d").date() < self.target_date,
                 "HOLD_HISTORY_NOT_BEFORE_TARGET_DAY")
            seen.add(ref["token"])
            results.append(parsed)
            return parsed

        for ref in newest:
            if ref["observed_status_symbol"] not in frozenset("123456789"):
                continue
            value = acquire(ref)
            if value and value["status"] == "FINISHED":
                finished += 1
            if finished >= 6:
                break
        need(finished >= 6, "HOLD_FEWER_THAN_SIX_VERIFIED_FINISHES")
        crash = next((i for i, ref in enumerate(newest) if ref["observed_status_symbol"] in ("落", "落再")), None)
        if crash is not None:
            acquire(newest[crash])
            # Both sides are selected from the source's ordered meeting rows;
            # dates and result states are still verified from every actual page.
            before = [r for r in newest[crash + 1:] if r["observed_status_symbol"] in frozenset("123456789")][:3]
            after = [r for r in reversed(newest[:crash]) if r["observed_status_symbol"] in frozenset("123456789")][:3]
            for ref in before + after:
                acquire(ref)
        return dict(car=car, registration_id=registration_id, profile=profile,
                    results=sorted(results, key=lambda x: (x["race_date"], x["race_id"])),
                    six_prior_finishes_verified=True,
                    known_absences=profile["absence_observations"],
                    comments_availability=profile["comments_availability"])


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--riders-json", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--target-race-id", required=True)
    parser.add_argument("--cutoff-at", required=True)
    parser.add_argument("--max-requests", type=int, default=150)
    args = parser.parse_args(argv)
    collector = None
    payload = dict(schema="RACE_AI_KEIRIN_OFFICIAL_FORM_CAPTURE_V1", state="HOLD_UNSTARTED",
                   target_race_id=args.target_race_id, riders=[], source_receipts=[])
    try:
        data = json.loads(Path(args.riders_json).read_text())
        riders = data["riders"] if type(data) is dict else data
        need(type(riders) is list and 5 <= len(riders) <= 9, "HOLD_ROSTER_INVALID")
        selected = [(r["car"], r.get("registration_id", r.get("athlete_id"))) for r in riders]
        need(len({c for c, _ in selected}) == len(selected) and
             len({s for _, s in selected}) == len(selected), "HOLD_ROSTER_DUPLICATED")
        collector = OfficialHistoryCapture(args.output_dir, cutoff_at=args.cutoff_at,
                                           target_race_id=args.target_race_id, max_requests=args.max_requests)
        for car, registration in selected:
            payload["riders"].append(collector.capture_rider(car=car, registration_id=registration))
            checkpoint = _json_bytes(dict(payload, state="PARTIAL_CAPTURE_IN_PROGRESS",
                                         source_receipts=collector.receipts))
            _save_once(collector.root / (sha256(checkpoint).hexdigest() + ".checkpoint.json"), checkpoint)
        collector.check()
        payload["state"] = "OFFICIAL_FORM_HISTORY_CAPTURED"
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        payload["state"] = str(error) if type(error) in (CaptureError, form.OfficialFormHistoryError) else "HOLD_LOCAL_CAPTURE_ERROR"
    if collector is not None:
        payload["source_receipts"] = collector.receipts
        payload["captured_at"] = datetime.now(timezone.utc).isoformat()
        raw = _json_bytes(payload)
        _save_once(collector.root / (sha256(raw).hexdigest() + ".form-capture.json"), raw)
        print(json.dumps(dict(state=payload["state"], riders_completed=len(payload["riders"]),
                              http_status_counts=collector.http_status_counts,
                              request_count=collector.count, manifest_sha256=sha256(raw).hexdigest())))
    else:
        print(json.dumps(dict(state=payload["state"], riders_completed=0)))
    return 0 if payload["state"] == "OFFICIAL_FORM_HISTORY_CAPTURED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
