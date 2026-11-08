# BOAT six-course tactics, research-only implementation

This code-only candidate is deliberately NOT wired into the live P0/P1 scheduler.
It reads existing authenticated private B/K history without initiating official GET,
creating a new model series, changing prediction weights, or modifying any vault.

Implemented analysis:
- Current meeting results by a source-identified start date and venue;
  last 10, last 30, last 90/365 days, and each actual entry course's last 10.
  The optional private HistoryStore adapter adds ST/absence context and motor data
  remains in the existing source-backed motor_profile() without interpolation.
- Course 1: escape plus losses whose *winning race method* was makuri,
  sashi, or makurizashi. Those are not verified direct attacks.
- Course 2: nigashi (number of 1-course escapes while the racer ran 2nd),
  sashi, makuri. A 2nd-course makurizashi is intentionally not fabricated.
- Courses 3-6: separate sashi, makuri, and makurizashi wins,
  both per actual-course start and among wins. **5 and 6 included.**
- Course 3: 3:3 corner-uke observational proxy, only when a separate
  prior formation receipt verifies a fourth-course kado. No inferred blocking.
- Six-entrant pre-race matchups: 20 unique factor channels including
  separate fifth/sixth-course makuri and makurizashi. All six IDs,
  observed course assignments and the same as-of are required.
- Prior matched-cohort escape proportion + Wilson interval only
  with >=30 prior independently verified eligible examples. This is
  uncalibrated retrospective evidence, not a forecast probability.

Required follow-on acceptance (NOT achieved by these synthetic unit tests):
- Reconcile real private day data, source timestamps and formation evidence.
- Preserve missing/F/L/unsupported cases; independently verify result revisions.
- Fit/calibrate on earlier dates and compare on never-seen future races.
- Read-only render in existing dashboard after source-free readback and review.
- Prove Top8, holdout, man-shu capture and reference ROI improvement before
  any opt-in shadow scoring or owner-approved production change.

Existing source issuer/capsule/OLD_UNKNOWN24/HOLD gates must remain untouched.
Do not change workflow, branch ref, scheduler, concurrency, rights, main, secrets
or the original P0/P1 forecast record to accommodate this candidate.
