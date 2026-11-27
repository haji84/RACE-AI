"""One-time create-only preservation of the already trained DT-R1 owner bundle.

Uses existing Git authentication; never reads a private key or retrains. Only the
externally pinned ZIP and its approved public/encrypted members are accepted.
Run from the existing authenticated RACE-AI checkout, outside production jobs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ZIP_SHA = '4a505164a76897ad3978cdf96625bf00f7b40fc68df235cf433083f2cf7e777e'
MANIFEST_SHA = '497154664f90725024836fbfe7cc84def152ccadb13868ccae0edb7b14c8cc4f'
MODEL_SHA = '5e022092a35c0258954090c6f3d0f8fa14f03f22511b28d6aa9183f5a38c381c'
OWNER_PIN = '1963d13558d115ce261f224b97d385bd09c65a70c91fb23237f91aa9840bb3a1'
STATE_REF = 'refs/heads/state/keirin-encrypted-history'
TARGET = Path('research/chatgpt-dt-r1/20261128') / MANIFEST_SHA
PUBLIC = {'frozen_model.json', 'public_report.json', 'dashboard.html'}
SHARDS = {f'shard-{i:06d}.sealed.json' for i in range(8)}
NAMES = PUBLIC | SHARDS | {'manifest.json'}
ORIGINS = {'https://github.com/haji84/RACE-AI.git', 'https://github.com/haji84/RACE-AI',
           'git@github.com:haji84/RACE-AI.git', 'ssh://git@github.com/haji84/RACE-AI.git'}


def need(condition, error):
    if not condition:
        raise ValueError(error)


def hash_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest_info(raw):
    need(hashlib.sha256(raw).hexdigest() == MANIFEST_SHA, 'EXTERNAL_MANIFEST_MISMATCH')
    m = json.loads(raw)
    need(m['schema'] == 'DT_R1_ENCRYPTED_STUDY_BUNDLE_V1' and
         m['model_sha256'] == MODEL_SHA and m['owner_spki_sha256'] == OWNER_PIN and
         m['production_promoted'] is False and m['owner_decryption_verified'] is False and
         len(m['files']) == 24, 'MANIFEST_CONTRACT_MISMATCH')
    need(len(m['public_files']) == 3 and len(m['shards']) == 8 and
         {x['file'] for x in m['public_files']} == PUBLIC and
         {x['file'] for x in m['shards']} == SHARDS, 'MANIFEST_MEMBER_SET')
    return {x['file']: x for x in m['public_files'] + m['shards']}


def verify_directory(folder):
    need(folder.is_dir() and not folder.is_symlink(), 'BUNDLE_DIR_INVALID')
    need({p.name for p in folder.iterdir()} == NAMES, 'BUNDLE_MEMBER_SET')
    need(all(p.is_file() and not p.is_symlink() for p in folder.iterdir()), 'BUNDLE_MEMBER_TYPE')
    expected = manifest_info((folder / 'manifest.json').read_bytes())
    for name, entry in expected.items():
        p = folder / name
        need(p.stat().st_size == entry['bytes'] and hash_file(p) == entry['sha256'], 'BUNDLE_FILE_HASH:' + name)
    return {'manifest_sha256': MANIFEST_SHA, 'model_sha256': MODEL_SHA,
            'encrypted_shards': 8, 'public_files': 3, 'files_verified': 12,
            'owner_decryption_verified': False}


def extract_verified(archive, folder):
    need(archive.is_file() and not archive.is_symlink(), 'ZIP_INVALID')
    need(archive.stat().st_size == 28916650 and hash_file(archive) == ZIP_SHA, 'ZIP_PIN_MISMATCH')
    need(not folder.exists(), 'DESTINATION_EXISTS')
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        need(len(infos) == len(NAMES) and {i.filename for i in infos} == NAMES, 'ZIP_MEMBER_SET')
        need(all(not i.is_dir() and (i.external_attr >> 16) & 0o170000 in (0, 0o100000)
                 for i in infos), 'ZIP_MEMBER_TYPE')
        expected = manifest_info(z.read('manifest.json'))
        for name, entry in expected.items():
            need(z.getinfo(name).file_size == entry['bytes'], 'ZIP_MEMBER_SIZE:' + name)
        folder.mkdir(mode=0o700, parents=True)
        for i in infos:
            with z.open(i) as src, (folder / i.filename).open('xb') as dst:
                shutil.copyfileobj(src, dst)
    return verify_directory(folder)


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], check=True,
                            text=True, stdout=subprocess.PIPE)
    return result.stdout.strip()


def checkout_state(work, origin):
    work.mkdir()
    git(work, 'init', '-q')
    git(work, 'remote', 'add', 'origin', origin)
    git(work, 'fetch', '--no-tags', '--depth=1', 'origin', STATE_REF)
    git(work, 'checkout', '--quiet', '--detach', 'FETCH_HEAD')
    return git(work, 'rev-parse', 'HEAD')


def archive_to_existing_state(bundle, repo):
    origin = git(repo, 'remote', 'get-url', 'origin')
    need(origin in ORIGINS, 'UNAPPROVED_REMOTE')
    verify_directory(bundle)
    name, email = git(repo, 'config', 'user.name'), git(repo, 'config', 'user.email')
    need(bool(name and email), 'EXISTING_GIT_IDENTITY_REQUIRED')
    with tempfile.TemporaryDirectory(prefix='dt-r1-retain-') as tmp:
        work = Path(tmp) / 'write'
        base = checkout_state(work, origin)
        dest = work / TARGET
        need(not any(p.is_symlink() for p in (dest, *dest.parents) if p != work.parent), 'STATE_PATH_SYMLINK')
        if dest.exists():
            verify_directory(dest)  # idempotent; mismatched existing content stops
            commit = base
            already_present = True
        else:
            shutil.copytree(bundle, dest)
            verify_directory(dest)
            git(work, 'add', '-f', '--', TARGET.as_posix())
            git(work, '-c', f'user.name={name}', '-c', f'user.email={email}', 'commit', '-qm',
                'Preserve externally pinned DT-R1 owner-encrypted research study')
            commit = git(work, 'rev-parse', 'HEAD')
            changed = git(work, 'diff-tree', '--no-commit-id', '--name-only', '-r', commit).splitlines()
            need(set(changed) == {(TARGET / n).as_posix() for n in NAMES}, 'COMMIT_PATH_SET')
            for filename in NAMES:
                rel = (TARGET / filename).as_posix()
                raw = subprocess.check_output(['git', '-C', str(work), 'show', f'{commit}:{rel}'])
                need(hashlib.sha256(raw).hexdigest() == hash_file(dest / filename), 'GIT_BLOB_CHANGED:' + filename)
            git(work, 'push', 'origin', f'{commit}:{STATE_REF}')  # no force; concurrent write fails safely
            already_present = False
        witness = Path(tmp) / 'readback'
        head = checkout_state(witness, origin)
        check = verify_directory(witness / TARGET)
        # Explicitly verify GitHub-returned bytes; a second isolated local checkout, not a separate runner.
        return {**check, 'state_ref': STATE_REF, 'path': TARGET.as_posix(), 'commit': commit,
                'readback_head': head, 'already_present': already_present,
                'separate_checkout_readback': True, 'independent_runner_readback': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip', type=Path)
    parser.add_argument('--publish-from-existing-checkout', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='dt-r1-verified-') as tmp:
        bundle = Path(tmp) / 'bundle'
        report = extract_verified(args.zip.resolve(), bundle)
        if args.publish_from_existing_checkout:
            report = archive_to_existing_state(bundle, args.publish_from_existing_checkout.resolve())
        print(json.dumps({**report, 'zip_sha256': ZIP_SHA}, sort_keys=True))


if __name__ == '__main__':
    main()
