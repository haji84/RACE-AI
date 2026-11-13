"""One-time candidate-only patch; removed before the final reviewed PR head."""
from pathlib import Path
import subprocess

OLD='0c158d99366b8e15130f6d0659be67125c39d545'
NEW='203ca70a2ea04124b2cb0ceba9dc4bdad7cc8da9'
p=Path('.github/workflows/boat-racer-daily.yml')
g=Path('scripts/boat_main_dispatch_gate.py')
for path,expected in ((p,'33ad1b4ab174b897b7f30272d23d0ab48ff86261'),
                      (g,'21bf6de21bb54d990599efccea64ae1e3f7e3917')):
    assert subprocess.check_output(['git','hash-object',str(path)]).decode().strip()==expected
text=p.read_text()
assert text.count(OLD)==8
prefix,job=text.split('  owner_p0_p1_dispatch:\n',1)
assert job.count('timeout-minutes: 5')==1 and job.count('contents: read')==1
assert job.count('python -m scripts.boat_main_dispatch_gate')==1
job=job.replace('timeout-minutes: 5','timeout-minutes: 15').replace('contents: read','contents: write')
job=job.replace('python -m scripts.boat_main_dispatch_gate','python -m scripts.boat_recovery_dispatch_gate')
anchor='      - name: Dispatch only the existing owner P0/P1 workflow\n'
assert job.count(anchor)==1
addition='''      - name: Install original parser only when a failed owner needs recovery
        if: steps.owner_gate.outputs.recovery_required == 'true'
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
        with: {persist-credentials: false, ref: 761247bee0209e37b1af6b8885e92cad3e9260a5, path: boat-owner-reader/pr64-reference}
      - name: Install original adapter only when a failed owner needs recovery
        if: steps.owner_gate.outputs.recovery_required == 'true'
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
        with: {persist-credentials: false, ref: 7a432e5acc4d3495a0e82bd79726929e2f8085fe, path: boat-owner-reader/pr72-reference}
      - name: Install source-free recovery dependencies only when needed
        if: steps.owner_gate.outputs.recovery_required == 'true'
        run: python -m pip install --disable-pip-version-check -r boat-owner-reader/requirements-history.txt
      - name: Recover exact failed owner originals on this fresh runner
        id: owner_recovery
        if: steps.owner_gate.outputs.recovery_required == 'true'
        working-directory: boat-owner-reader
        env:
          GH_TOKEN: ${{ github.token }}
          RACE_AI_STATE_KEY: ${{ secrets.RACE_AI_STATE_KEY }}
          RACE_AI_ORIGINAL_VAULT_ENABLED: 'true'
        run: >-
          python -m scripts.boat_recover_failed_owner
          --history "$RUNNER_TEMP/boat-owner-runs.json"
          --expected-head 203ca70a2ea04124b2cb0ceba9dc4bdad7cc8da9
          --output "$RUNNER_TEMP/boat-owner-recovery-proof.json"
      - name: Recheck fresh owner history and recovered originals before successor admission
        id: recovered_gate
        if: steps.owner_recovery.outcome == 'success'
        env:
          GH_TOKEN: ${{ github.token }}
          PYTHONPATH: ${{ github.workspace }}/boat-owner-reader
        shell: bash
        run: |
          set -euo pipefail
          gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/production/boat-p0-p1-20261111" > "$RUNNER_TEMP/boat-owner-release.json"
          gh api "repos/$GITHUB_REPOSITORY/contents/docs/RACE_AI_LATEST_STATUS.md?ref=production%2Fboat-p0-p1-20261111" > "$RUNNER_TEMP/boat-owner-policy.json"
          gh api "repos/$GITHUB_REPOSITORY/actions/workflows/boat-nationwide-ab-one-shot.yml/runs?branch=production%2Fboat-p0-p1-20261111&per_page=100" > "$RUNNER_TEMP/boat-owner-runs.json"
          python -m scripts.boat_recovery_dispatch_gate --release "$RUNNER_TEMP/boat-owner-release.json" --owner-doc "$RUNNER_TEMP/boat-owner-policy.json" --history "$RUNNER_TEMP/boat-owner-runs.json" --verify-source-handoff --recovery-proof "$RUNNER_TEMP/boat-owner-recovery-proof.json" --github-output "$GITHUB_OUTPUT"
'''
job=job.replace(anchor,addition+anchor)
old="if: steps.owner_gate.outputs.ready == 'true'"
assert job.count(old)==1
job=job.replace(old,"if: steps.owner_gate.outputs.ready == 'true' || steps.recovered_gate.outputs.ready == 'true'")
# Preserve every other job, scheduling expression, result collector and scorer.
text=(prefix+'  owner_p0_p1_dispatch:\n'+job).replace(OLD,NEW)
p.write_text(text+'\n' if not text.endswith('\n') else text)
gate=g.read_text();assert gate.count(OLD)==1
g.write_text(gate.replace(OLD,NEW)+'\n' if not gate.endswith('\n') else gate.replace(OLD,NEW))
Path('.github/workflows/boat-main-recovery-assemble.yml').unlink()
Path(__file__).unlink()
