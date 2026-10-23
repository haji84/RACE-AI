# One-hop automatic Actions continuation trial
## Scope
One trusted PR65 source run may launch one workflow_dispatch child on the same branch. Synthetic checkpoint only. No real developer, deployment, repository writeback, new secrets, paid runner or ongoing loop.
## Rulings and constraints
No suitable local executor; use connector CAS edits and Actions tests. A workflow cannot pin its own future SHA literally. Prepare and independently review disabled code, then activation-only diff pins the prepared commit as direct parent plus exact next workflow run_number and run_attempt1. Unexpected intervening event consumes the number and safely skips; no automatic adjustment.
Only designated dispatcher job receives contents:read/actions:write at activation. Token technically has repository-wide Actions-write scope; fixed code restricts requests to this same workflow and one POST. No checkout or PR script execution in privileged job. Receiver read-only and remaining_hops0. No retry after ambiguous POST.
## Interfaces
Pure injected-API protocol dispatchOnce validates source event/head/branch/actor/attempt/run number, direct prepared parent, live ref, synthetic artifact metadata and duplicate chain before one POST. validateReceiver checks input/source/artifact linkage and returns read-only continuation contract. Producer and receiver reuse existing completion-mock-trial checkpoint files.
## Steps
1. Expected RED for missing protocol interfaces.
2. Deterministic tests for scope/parent/head/attempt/artifact/duplicates/ambiguousPOST; disabled workflow and implementation; independent review and CI.
3. Activation-only reviewed diff with fixed next run number and prepared commit, actions:write on dispatcher only. One child maximum, source waits for existing checks before POST; parent does not wait child.
4. Observe exact source/child run provenance, synthetic resume and terminal success or exact blocker. Do not retry uncertain dispatch.
## Completion
Automatic single-hop triggering is separate from generic autonomous AI development and durable canonical writeback. Main/default workflow absence may still be an API feasibility blocker, to be tested rather than assumed.
