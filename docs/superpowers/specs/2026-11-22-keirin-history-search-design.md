# KEIRIN saved-history search

The owner points out that choosing from a growing strip of dates makes old data hard to find. Improve the existing owner-only GitHub KEIRIN guide so someone can find saved races without remembering their date. Existing single-day operation remains the default.

## Approach

Selected implementation choice: extend the existing browser-side view/model with a calendar jump, explicit single-day/range/all-saved scope, cross-day text search, exact race-number filtering, and paginated cards. Keep at most seven shortcut day buttons. Every result shows its saved date.

Alternatives considered: a longer date strip still requires scrolling; a new server/search service violates the GitHub-only constraints and is unnecessary for the saved browser data. No new source, hosting, search index on public Git, or dependency is introduced. These implementation choices are the agent's defaults under the owner's continuing development request.

## Behavior

- A calendar chooses an exact day, including an empty saved-data day. Do not silently substitute a different date.
- Scope options are one day, inclusive date range, and all saved dates. Offer latest-day, recent-seven-calendar-days and all-period shortcuts.
- Search can combine venue, athlete, title, saved date and an exact `1R`/`11R` token. Normalize full-width characters and whitespace. Multiple terms use AND. Venue and race-number filters combine with existing model/confidence/selection controls.
- Opening history/all-period search clears the future-only toggle; preserve candidate selection and budget/exclusions across pages and searches.
- Render 20 cards per page, with previous/next and visible total. Never cap or discard the stored dataset. Filter changes reset to page one; background refresh preserves filters and clamps the existing page only if needed.
- Multi-day cards show full dates. Single-day nationwide and research summaries keep their existing denominator; hide those day-specific summaries in multi-day search rather than displaying misleading aggregates.
- Invalid ranges show a visible explanation and no results. Empty results and an empty dataset remain usable.

## Constraints and acceptance

Keep all queries within the browser. Preserve original forecast/result revisions, prices, allocation, encryption and key handling. Change no models, producer/study pins, workflow graph, permissions or paid services. No new PR without an explicit exception to the owner's earlier prohibition. Existing open PRs49/71/148 are unrelated or frozen, and no closed-unmerged reusable PR was found; complete implementation, review and a concrete preview before addressing protected-main integration.

Use existing JS modules and the existing allowlisted app/style bundle. Add synthetic Node tests and browser tests covering cross-day discovery, exact race numbers, reversed ranges, hundreds of dates, 2,000+ races, bounded card rendering, refresh and selection retention. Verify mobile320/390 and desktop1440 widths. Physical iPhone remains separate.

This change bounds navigation/DOM work and makes already-loaded saved data searchable. It does not change the current encrypted history-loading protocol or claim arbitrary-history download latency.
