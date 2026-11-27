"""Read back the retained, externally pinned study without keys or retraining.

The GitHub CI runs this on a fresh runner. Only the fixed public/encrypted
members are downloaded; source authentication and owner decryption remain
separate gates. No branch writes, credentials, or storage service are used.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen

from .preserve_verified_bundle import (MANIFEST_SHA, NAMES, STATE_REF, TARGET,
                                       manifest_info, need, verify_directory)

ARCHIVE_COMMIT = '410596da678beddcef6f8ca645cdc4e970f2d0fb'
ARCHIVE_PARENT = '3523e23734e79c721c4c32ceb88f6d3fc65e618a'
ROOT = ('https://raw.githubusercontent.com/haji84/RACE-AI/' +
        ARCHIVE_COMMIT + '/' + TARGET.as_posix())


def fetch_exact(name, size, expected_sha256):
    need(name in NAMES, 'RETAINED_MEMBER_INVALID')
    url = ROOT + '/' + name
    request = Request(url, headers={'User-Agent': 'RACE-AI-DT-R1-cipher-readback/1'})
    with urlopen(request, timeout=45) as response:
        need(response.geturl() == url, 'RETAINED_URL_CHANGED')
        raw = response.read(size + 1)
    need(len(raw) == size and sha256(raw).hexdigest() == expected_sha256,
         'RETAINED_FILE_INTEGRITY:' + name)
    return raw


def readback():
    raw = fetch_exact('manifest.json', 5577, MANIFEST_SHA)
    members = manifest_info(raw)
    with tempfile.TemporaryDirectory(prefix='dt-r1-retained-readback-') as root:
        folder = Path(root)
        (folder / 'manifest.json').write_bytes(raw)
        for name, expected in sorted(members.items()):
            (folder / name).write_bytes(fetch_exact(name, expected['bytes'], expected['sha256']))
        verified = verify_directory(folder)
    runner = os.environ.get('GITHUB_ACTIONS') == 'true'
    return dict(verified, schema='DT_R1_RETAINED_CIPHERTEXT_READBACK_V1',
                archive_commit=ARCHIVE_COMMIT, archive_parent=ARCHIVE_PARENT,
                state_ref=STATE_REF, path=TARGET.as_posix(),
                observed_at=datetime.now(timezone.utc).isoformat(),
                reader_environment='github_actions' if runner else 'local',
                reader_run_id=os.environ.get('GITHUB_RUN_ID') if runner else None,
                reader_code_commit=os.environ.get('GITHUB_SHA') if runner else None,
                # A successful CI run must be read independently before acceptance.
                source_authenticated=False, production_promoted=False,
                provider_source_requests=0, state_writes=0, private_key_used=False)


def main():
    print('DT_R1_RETAINED_READBACK ' + json.dumps(readback(), sort_keys=True))


if __name__ == '__main__':
    main()
