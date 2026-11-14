# Upcoming races and venue results

The owner requested removing finished races from the next-prediction list, a venue-selectable race-results tab, clear outcomes for each race, and renaming Results/Balance to AI prediction results. Implement within the existing race page: Upcoming / Race results, with the same venue selection. The AI prediction results page retains existing model summaries and budget simulation.

- [x] Test lifecycle classification and the visible upcoming/results split, venue continuity, actual result/payout/pending labels, automatic cutoff transition and AI prediction results naming.
- [x] Implement read-only phase filtering, deadline ordering, compact venue results and a separate unknown-deadline view. Passing the cutoff means closed for prediction, not proof the race has finished; unknown/pending/held cases never become misses.
- [x] Run relevant Node contracts and phone/desktop/browser Crypto regressions. Update historical-race navigation in existing checks for the new results tab.
- [x] Publish reviewed presentation bytes preserving forecast ciphertext, portraits and live statistics. Update the minimal read-only verifier pin through required main CI, verify the live owner flow and retain count-only evidence.

Preserve every original, selected forecast/rationale, official result/revision, research diagnostics, betting-draft behavior and financial calculation policy. No result collection/provider/key changes. Tests use controlled clocks and invented data; live off-hours observations are not measured race-finish latency.
