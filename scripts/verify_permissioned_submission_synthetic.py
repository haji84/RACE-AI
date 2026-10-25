"""Original case -> consumed intent -> fictional writer/read-only recovery.

The pinned models run once on one authored BOAT case. Admissions, HTTP answers,
timestamps and witnesses are fictional. No credentials/default network, real
source collection, external submission or protected cloud persistence.
"""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def main():
    if not __debug__:
        raise RuntimeError("Verification requires enabled assertions")
    sys.path.insert(0, str(ROOT))
    from scripts.verify_offline_model_run_synthetic import check_reference, REFERENCE, PIN
    check_reference()
    git_root = REFERENCE if (REFERENCE / ".git").exists() else ROOT
    verifier = "race_ai/github_freeze_receipt.py"
    pinned = subprocess.check_output(["git", "-C", str(git_root), "show", PIN + ":" + verifier])
    if (REFERENCE / verifier).read_bytes().replace(b"\r\n", b"\n") != pinned.replace(b"\r\n", b"\n"):
        raise RuntimeError("Pinned external verifier changed")
    from tests.test_permissioned_model_case import fixture, authorities
    from tests.test_offline_model_run import Clock, LATE, canonical
    from race_ai.permissioned_model_case import prepare_case, load_case
    from race_ai.permissioned_case_submission import dispatch_prepared_case, recover_submission_attempts
    from race_ai.github_freeze_receipt import verify_github_freeze

    branch = "audit/freeze-fictional-submission"
    base = "https://api.github.com/repos/haji84/RACE-AI"
    request, raw, policy = fixture()
    clock = Clock()
    calls, files = [], {}
    fail = [None]

    def transport(url, method, data):
        calls.append((url, method))
        if method == fail[0]:
            raise RuntimeError("FICTIONAL_TRANSPORT_FAILURE")
        if method == "PUT":
            body = json.loads(data)
            assert set(body) == {"message", "content", "branch"}
            assert body["branch"] == branch
            commit = hashlib.sha1(url.encode()).hexdigest()
            files[url + "?ref=" + commit] = base64.b64decode(body["content"], validate=True)
            return {"commit": {"sha": commit}}
        assert method == "GET" and data is None
        return {"type": "file", "encoding": "base64", "content": base64.b64encode(files[url]).decode()}

    # These deliberately fictional gates do not implement real ACL, source,
    # public-release or storage authorization. No credential enters this script.
    gates = {"private_path_verifier": lambda path, **kw: True,
             "admit_store": lambda path, manifest, **kw: True,
             "verify_source": lambda claim, snapshot: True,
             "verify_cutoff": lambda claim, row: True,
             "admit_model_roster": lambda claim, declarations: True,
             "independent_release_check": lambda claim: True,
             "admit_transport": lambda claim, actual: actual is transport}
    with tempfile.TemporaryDirectory(prefix="race-ai-fictional-submission-") as directory:
        path = Path(directory)
        original = path / "case.sqlite"
        prepared = prepare_case(original, request, raw, policy, clock=clock, **authorities(request))
        assert prepared["status"] == "PREPARED_NOT_EXTERNAL_FROZEN"
        loaded = load_case(original, expected_request_sha256=prepared["request_sha256"],
                           private_path_verifier=gates["private_path_verifier"])
        original_bytes = original.read_bytes()
        identity = {"expected_request_sha256": prepared["request_sha256"],
                    "expected_branch": branch, "submission_source_sha40": "e" * 40, "clock": clock}
        common = {**identity, **gates, "transport": transport}

        # Entirely absent public/source/store capabilities deny before creation.
        denied = dispatch_prepared_case(path / "denied.sqlite", original, **identity)
        assert denied["status"] == "DENIED" and not (path / "denied.sqlite").exists() and not calls
        normal = dispatch_prepared_case(path / "normal.sqlite", original, **common)
        assert normal["status"] == "NORMAL_READBACKS_COMPLETE_RECEIPTS_PENDING"
        assert normal["github_reads"] == 4
        assert all(item["normal_acknowledged"] for item in normal["models"])
        assert [method for _, method in calls] == ["PUT", "GET"] * 4
        count = len(calls)
        replay = dispatch_prepared_case(path / "normal.sqlite", original,
            **identity, private_path_verifier=gates["private_path_verifier"], admit_store=gates["admit_store"])
        expected_replay = deepcopy(normal)
        expected_replay["github_reads"] = 0
        assert replay == expected_replay and len(calls) == count

        # A successful PUT's concrete commit survives failure of pinned GET.
        # A separate authored transport world has no files from the normal
        # scenario. Fictional store admissions are not clone protection.
        files.clear()
        known_start = len(calls)
        fail[0] = "GET"
        uncertain = dispatch_prepared_case(path / "known.sqlite", original, **common)
        first = uncertain["models"][0]
        assert uncertain["dispatch_barrier"] and first["commit_sha"] and not first["normal_acknowledged"]
        assert uncertain["github_reads"] == 1
        assert [item["status"] for item in uncertain["models"]][1:] == ["NOT_ATTEMPTED"] * 3
        assert [method for _, method in calls[known_start:]] == ["PUT", "GET"]
        assert len(files) == 1
        sent_url, sent_anchor = next(iter(files.items()))
        plan = loaded["plans"][0]
        assert sent_url == base + "/contents/" + plan["path"] + "?ref=" + first["commit_sha"]
        assert sent_anchor == (canonical(plan["anchor"]) + "\n").encode()
        count = len(calls)
        stopped = dispatch_prepared_case(path / "known.sqlite", original, **common)
        assert stopped["dispatch_barrier"] and stopped["github_reads"] == 0 and len(calls) == count
        clock.at = LATE
        run = {"id": 42, "event": "push", "head_sha": first["commit_sha"], "head_branch": branch,
               "repository": {"full_name": "haji84/RACE-AI"}, "created_at": "2030-01-15T09:16:00+09:00"}
        answers = {base + "/actions/runs?head_sha=" + first["commit_sha"] + "&event=push&per_page=100":
                   {"total_count": 1, "workflow_runs": [run]}, base + "/actions/runs/42": run,
                   base + "/contents/" + plan["path"] + "?ref=" + first["commit_sha"]:
                   {"type": "file", "encoding": "base64", "content":
                    base64.b64encode(sent_anchor).decode()}}
        reads = []
        def fetch(url):
            reads.append(url)
            return deepcopy(answers[url])
        reader = {**identity, "private_path_verifier": gates["private_path_verifier"],
                  "admit_store": gates["admit_store"]}
        recovered = recover_submission_attempts(path / "known.sqlite", original, **reader,
            admit_reader=lambda *args: True, github_fetch=fetch, trusted_legacy_verifier=verify_github_freeze)
        assert len(reads) == 3 and recovered["github_reads"] == 3 and recovered["dispatch_barrier"]
        assert recovered["models"][0]["witness"]["external_pre_cutoff_presence_verified"]
        assert not recovered["models"][0]["normal_acknowledged"]
        cached = recover_submission_attempts(path / "known.sqlite", original, **reader)
        assert cached["models"] == recovered["models"] and cached["github_reads"] == 0 and len(reads) == 3
        stopped = dispatch_prepared_case(path / "known.sqlite", original, **common)
        assert stopped["dispatch_barrier"] and stopped["github_reads"] == 0 and len(calls) == count
        assert original.read_bytes() == original_bytes
        for outcome in (normal, uncertain, recovered):
            for flag in ("official_prediction", "eligible_for_hit_at_8", "source_rights_verified",
                         "producer_execution_authenticated", "full_private_payload_retention_verified",
                         "global_exactly_once_verified", "cloned_store_protection_verified"):
                assert outcome[flag] is False
        print(json.dumps({"scope": "FICTIONAL_PERMISSIONED_SUBMISSION_INTEGRATION_ONLY",
            "original_cases": 1, "models": 4, "normal_recording_puts": 4,
            "uncertain_recording_puts": sum(method == "PUT" for _, method in calls[known_start:]),
            "known_commit_read_only_recovery_gets": len(reads),
            "cached_recovery_gets": 0, "replayed_puts": 0, "unacknowledged_barrier_preserved": True,
            "original_case_bytes_preserved": True, "source_requests": 0, "external_writes": 0,
            "protected_cloud_retention_verified": False, "real_forecasts": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    def no_network(*args, **kwargs):
        raise AssertionError("network forbidden")
    with patch("socket.create_connection", side_effect=no_network), \
         patch("socket.socket.connect", side_effect=no_network), \
         patch("urllib.request.OpenerDirector.open", side_effect=no_network):
        raise SystemExit(main())
