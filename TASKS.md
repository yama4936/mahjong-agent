# Jantama Auto completion tasks

Status values: `todo`, `doing`, `done`, `blocked`.

## A. Safe browser operation

- [x] `done` Fix the live 300+0 friend-match crash loop after two successful discards: resized CDP frames are rejected before fixed-ROI processing, stale action gates are cleared, and the screencast is re-subscribed after restoring 1920×1080 so reaction handling resumes. Regression tests cover the observed 1058×1080 frame failure, exact-size recovery, and restart after the 1920×1119 viewport drift.
- [x] `done` Recover safely when the operator starts or restarts during a live open hand: after a manually completed pon, public recognition inferred one open meld but the main loop repeatedly rejected the 10-tile hand as `compact hand appeared before any observed call` instead of adopting the verified visible meld and discarding (reproduced 2026-09-21 in `artifacts/debug-300/python-operator.jsonl`). Add a regression test and preserve fail-closed behavior when meld evidence is incomplete.
- [x] `done` Let the restart recovery path run while an open-hand discard is pending with no occupied draw slot. In the 300+0 live match, the verified-open-meld recovery code was unreachable because the screencast gate waited only for `drawSlot` occupancy, so a static 10-tile post-pon hand produced only public-cache updates and never discarded. Keep ordinary opponent-turn frames gated out and add a regression test.
- [x] `done` Seed the main turn gate from a calibrated one-shot screenshot when a newly started CDP screencast remains silent on an already-static action screen. In the 300+0 post-pon restart, public-cache screenshots updated continuously but no main screencast frame or recovery event arrived, even after an inert table click. The seed must use the same exact-size and action gates and must not create duplicate actions once streaming begins.
- [x] `done` Detect the shifted draw tile after an open meld in the force-auto screencast gate. In the 300+0 live pon hand, the next self draw appeared immediately after the compact 10-tile row (around x=1245) while the closed-hand fixed `drawSlot` remained farther right, so public-cache updates continued but the main loop never treated the frame as a self turn. Derive the dynamic draw slot from the verified open-meld count/compact hand layout, avoid opponent-turn false positives, and add regression coverage.
- [x] `done` Make the dynamic open-hand draw gate reachable when the live public cache detects candidates but does not promote `ownMelds`. In the same 300+0 pon hand, the shifted draw tile was visibly occupied and its derived slot tested true, but the runtime required `verified_visible_open_melds` from cached public state, so no main decision occurred. Combine independent compact-hand geometry with own-meld-region evidence (or improve live own-meld promotion) while remaining fail-closed on opponent turns; log the evidence used and add a live-frame regression.
- [x] `done` Fix the geometry-fallback live-loop regression `local variable 'public_observation' referenced before assignment`, reproduced immediately after deploying the fallback in the 300+0 match. Initialize/derive the observation before every quick-gate branch and add a test that executes the real run-loop ordering rather than only the geometry helper.
- [x] `done` Fix the open-hand pre-click stability loop that aborts forever with a constant `hand changed since evaluation (pixel delta=4.092)`. The geometry gate and recognition now reach a live self turn, but the screencast evaluation image and fresh pre-click capture are not comparable across the animated/full hand clip. Preserve stale-hand protection by comparing equivalent captures or tile-face subregions, and add a live-frame regression that reaches an actual discard receipt.
- [x] `done` Prevent catastrophic open-meld over-inference in the geometry/public fallback. In the 300+0 live hand with exactly one pon, transient frames were inferred as two melds and then cached public state promoted four melds; the operator evaluated only two concealed `6p` tiles and clicked `(1612.5, 821.5)`, outside the concealed hand row (`artifacts/debug-300/python-operator.jsonl`, 2026-09-21T04:23:07–14). Bind recovered meld count to stable multi-frame evidence and the observed concealed-row length, reject count jumps, and prove every discard click point lies inside the current concealed hand/draw geometry before enabling execution.
- [x] `done` Detect and process reaction prompts after an open meld. In the 300+0 live match, a visible chi/pass prompt remained on screen for minutes after the operator had recovered one pon and completed multiple valid discards, but no `reaction_prompt` or action event was logged (`artifacts/debug-300-current-end.png`, 2026-09-21T04:30). Ensure the reaction gate remains active for compact hands and verify chi/pon/ron/pass routing without weakening button false-positive checks.
- [x] `done` Fix the remaining closed-hand reaction-gate stall. In East 2 of the 300+0 live match, a clearly visible chi/pass prompt at `artifacts/debug-300-monitor.png` (2026-09-21T13:36:39+09:00 onward) produced only `public_cache_updated` events for more than 25 seconds—no `reaction_prompt`, decision, or action event—even though the hand was closed. Trace the real run-loop gate, add a regression using the captured frame, and keep independent button evidence/fail-closed behavior.
- [x] `done` Handle stale screencast content even when its sequence keeps advancing. After deploying the silence refresh, a new closed-hand pon/pass prompt at `artifacts/debug-300-current2.png` (2026-09-21T13:43:33+09:00 onward) again emitted only `public_cache_updated` for over a minute. The sequence-based watchdog apparently did not fire; compare frame content/hash or freshness against one-shot captures, reproduce through the real run loop, and preserve exact-size and independent-button fail-closed gates.
- [x] `done` Diagnose why the content-hash watchdog still does not enter reaction routing in the deployed process. After commit `62ea22d` and a clean restart at 13:48:34+09, the visible chi/pass prompt in `artifacts/debug-300-after-hash-fix.png` produced only `public_cache_updated` through at least 13:49:33—no refresh diagnostic, reaction event, or action. Add explicit watchdog/gate diagnostics, reproduce the deployed startup-on-existing-prompt path, and fix the actual blocked branch without weakening fail-closed checks.
- [x] `done` Fix the post-auto-pon next-draw stall. In East 3 after automatic pon succeeded at 13:54:18+09 and its immediate discard completed at 13:54:21, the later open-hand self draw remained visibly separated at the shifted draw slot in `artifacts/debug-300-current5.png`, but no self-turn/click event occurred for over a minute. Reproduce from the live frame through the real run loop, distinguish it from opponent turns, and retain discard-bound/open-meld-count safety checks.
- [x] `done` Fix two-open-meld discard geometry. After a second automatic pon at 14:01:00+09, the operator safely aborted repeated proposed discards at x=1468.5 and x=1541.5 as outside current hand geometry (`artifacts/debug-300/frames/2026-09-21T05-01-11.504761+00-00.jpg` and subsequent frames), leaving the turn to timeout. Derive recognition/click bounds from the 7-tile concealed row plus shifted draw slot for two melds, reproduce through the real run loop, and retain the final out-of-bounds rejection.
- [x] `done` Stop pre-click open-meld revalidation from promoting a confirmed count to four. In East 4 after automatic pon at 14:03:03+09, evaluation consistently used one open meld, but every pre-click check through at least 14:03:34 aborted with `evaluated open meld count changed from 1 to 4` (interspersed with small hand pixel deltas). Anchor revalidation to the operator-confirmed call count plus matching compact geometry, reject genuine geometry changes, and add a real-frame execution regression.
- [x] `done` Connect Python to the existing Mahjong Soul Chromium session over localhost CDP.
- [x] `done` Detect and resume the away/auto-tsumogiri dialog.
- [x] `done` Reject a decision if the away dialog appears during evaluation.
- [x] `done` Require a stable hand immediately before a click.
- [x] `done` Disarm a hand after any click attempt so it cannot be clicked twice.
- [x] `done` Verify the post-click 13-tile multiset and empty draw slot.
- [x] `done` Obtain one live discard with `tileMultisetVerification.verified=true`.
- [x] `done` Recognize login, account, lobby, ranked menu/room, matchmaking, match, away, round result, match result and exit-confirm screens; safely advance through one ranked East match and return to the lobby.
- [x] `done` Serve a read-only live browser dashboard with the current Mahjong Soul frame and classified screen state at localhost:8787.
- [ ] `todo` Package or explicitly configure the screen-state reference set and fail at startup with a clear diagnostic when it is empty; the current operator otherwise classifies every screen as `unknown` forever.
- [ ] `todo` Validate the live CDP viewport before every clipped capture and recover or stop cleanly when docked DevTools or window resizing changes the calibrated 1920×1080 geometry.
- [ ] `todo` Add a Windows-native Python operator setup command and npm script; the documented venv paths and setup script currently assume POSIX `bin/python` and Bash.

## B. Tile recognition calibration

- [x] `done` Build a slim local template set for low-latency evaluation.
- [x] `done` Correct the mislabeled `6s` training sample.
- [x] `done` Quarantine discovered `6p→7p`, `4s→5s` and `0s→5s` mislabeled samples and rebuild a clean live template set.
- [x] `done` Save a manifest linking every training/holdout crop to its source frame and label provenance (117/117 live-verified images covered exactly once).
- [x] `done` Run 105 pinned-dataset holdouts excluding identical training image bytes. Source-frame independence and pretrained-model training overlap are unverified; this is NOT independent-match validation.
- [x] `done` Compare raw, all-class, face-normalized and combined template matching on the same 105 images; run leave-one-source-frame-out on 83 live crops (six correlated frames, 14 labels).
- [x] `done` Adopt face normalization in example/current live layouts: live crop labels 78/83 → 83/83; fixed safety threshold accepts 60/83 and 0/5 complete hands. No threshold relaxation.
- [x] `done` Test pretrained ViT agreement and a 37-output local CNN. Agreement accepts zero; CNN 28/28 on two held frames but lacks red-man/red-pin training and remains experimental.
- [x] `done` Reject blank images, exclude holdout templates at runtime, detect exact train/test duplication, and bind certificates to matcher version/strategy.
- [x] `done` Add three-frame recognition agreement to Python pre-click checks and report score-bin accuracy, coverage and sample-size uncertainty.
- [ ] `todo` Wire the configured hybrid/ViT recognizer through Python `evaluate-frame`, consensus recognition and post-discard verification; the live advisor recognizes the hand while the Python operator's template-only path returns `tiles: []`.
- [ ] `todo` Collect genuinely separate-match labeled validation data across all 37 tile classes, screen scales, animations, rivers, melds and riichi indicators; calibrate probability on separate calibration data before testing on a locked test set.
- [ ] `blocked` Reach the strengthened Auto certificate requirement: 37 classes × at least 5 independent upright holdouts (185 total), 100% label and safety-gate accuracy. Latest rerun: 44/78 correct, 2/78 automation-safe, 31 holdout classes (34 template classes), no cross-label collisions. The claimed replacement is not present in this workspace; live red-five holdouts and a stronger recognizer are still required.

## C. Structured public state

- [x] `done` Define structured state fields and consistency/four-copy validation.
- [x] `done` Detect and classify calibrated river/meld tile candidates without automatically trusting them.
- [x] `done` Map the three detected river regions to absolute opponent seats and reject non-prefix temporal changes.
- [x] `done` Infer sideways-riichi evidence and complete exposed chi/pon/minkan groups, including table-orientation normalization and regression checks.
- [x] `done` Recognize calibrated dora-indicator regions separately from rivers/melds and feed them into explicitly enabled untrusted Advisor observations.
- [x] `done` Add fail-closed recognition for round, honba, riichi sticks, remaining tiles, seat and four scores from calibrated center-board regions; require score/pool consistency and multi-frame agreement. It reads both saved East-1/East-2 reference states but remains untrusted.
- [ ] `todo` Collect independent center-board references covering unseen values and animations, then validate and certify the recognizer before feeding its output to Auto.
- [ ] `blocked` Validate riichi/meld inference on independent live screenshots and add ankan/kakan evidence. This needs the template replacement plus labeled live holdouts; inferred evidence remains untrusted until then.
- [x] `done` Reject any supplied `publicStateConfidence >= 0.98` unless round, dora, remaining tiles, four scores and three unique opponents are complete.
- [ ] `todo` Produce `publicStateConfidence >= 0.98` from independently calibrated center-board, dora, river and meld evidence; current recognizers deliberately never self-promote to trusted.

## D. Decision and Jev

- [x] `done` Calculate standard/chiitoitsu/kokushi shanten and discard ukeire.
- [x] `done` Generate legal discard/riichi/call/win/pass/abort action structures.
- [x] `done` Validate structured Jev output against legal candidate IDs.
- [x] `done` Load Jev credentials from a mode-0600 local environment file without logging them, complete a live API smoke test, and pass a recognized real frame through Jev (`jev-1.13.0`, selected `4m`, confidence 0.67).
- [x] `done` Select tsumo/ron immediately, bind riichi to the chosen tenpai discard, call only for a strict shanten improvement, pass under riichi pressure, and rank viable discards by threat-adjusted round EV.
- [x] `done` Add versioned Jev prompt profiles, remove duplicated candidate context in `balanced-v2`, and add expert-label A/B metrics for accuracy, log loss and confidence coverage.
- [ ] `todo` Feed calibrated public state, danger and expected-value fields into live Jev decisions.
- [ ] `todo` Collect independent expert discard labels before changing the provisional Jev confidence threshold or promoting a prompt profile on quality claims.

## E. Full action execution and replay

- [x] `done` Execute and verify discard coordinates.
- [x] `done` Add calibrated-ROI template recognition for riichi, chi, pon, kan, ron, tsumo, pass and kyuushu buttons.
- [x] `done` Require a separate perfect holdout certificate and matching template fingerprint for every non-discard action; all such clicks are currently forbidden.
- [x] `done` Wire certified riichi, chi, pon, kan, ron, tsumo, pass and kyuushu decisions through both controller implementations; verify riichi as declaration plus discard and calls by button, hand and own-meld changes.
- [x] `done` Recognize every chi/pon/kan/ron reaction-prompt combination in the Python operator, send the observed board and legal reactions to Jev, and fall back to a certified pass when the latest discard cannot be identified safely.
- [ ] `blocked` Execute non-discard UI actions only after each action has at least 20 independent live holdouts, 100% accuracy and zero false positives.
- [x] `done` Attach explicit verified/failed/not-attempted execution evidence to every new replay record; the Python operator now adds classified result-screen evidence and screenshots to every pending decision at round and match completion.
- [x] `done` Add a shared replay-policy comparison runner with recorded/current-deterministic decisions, pairwise agreement, expert-label accuracy and per-policy error isolation; Jev can be enabled explicitly.
- [ ] `todo` Expand the replay corpus, run current Jev on it, and add a search policy before making policy-quality claims.

## Completion definition

All tasks above are `done`; full Auto remains fail-closed whenever any recognition,
state, legal-action, Jev, click-target or post-action verification gate is uncertain.
