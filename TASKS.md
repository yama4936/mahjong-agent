# Jantama Auto completion tasks

Status values: `todo`, `doing`, `done`, `blocked`.

## A. Safe browser operation

- [x] `done` Connect Python to the existing Mahjong Soul Chromium session over localhost CDP.
- [x] `done` Detect and resume the away/auto-tsumogiri dialog.
- [x] `done` Reject a decision if the away dialog appears during evaluation.
- [x] `done` Require a stable hand immediately before a click.
- [x] `done` Disarm a hand after any click attempt so it cannot be clicked twice.
- [x] `done` Verify the post-click 13-tile multiset and empty draw slot.
- [x] `done` Obtain one live discard with `tileMultisetVerification.verified=true`.
- [x] `done` Recognize login, account, lobby, ranked menu/room, matchmaking, match, away, round result, match result and exit-confirm screens; safely advance through one ranked East match and return to the lobby.
- [x] `done` Serve a read-only live browser dashboard with the current Mahjong Soul frame and classified screen state at localhost:8787.

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
- [ ] `todo` Collect genuinely separate-match labeled validation data across all 37 tile classes, screen scales, animations, rivers, melds and riichi indicators; calibrate probability on separate calibration data before testing on a locked test set.
- [ ] `blocked` Reach the strengthened Auto certificate requirement: 37 classes × at least 5 independent upright holdouts (185 total), 100% label and safety-gate accuracy. Latest rerun: 44/78 correct, 2/78 automation-safe, 31 holdout classes (34 template classes), no cross-label collisions. The claimed replacement is not present in this workspace; live red-five holdouts and a stronger recognizer are still required.

## C. Structured public state

- [x] `done` Define structured state fields and consistency/four-copy validation.
- [x] `done` Detect and classify calibrated river/meld tile candidates without automatically trusting them.
- [x] `done` Map the three detected river regions to absolute opponent seats and reject non-prefix temporal changes.
- [x] `done` Infer sideways-riichi evidence and complete exposed chi/pon/minkan groups, including table-orientation normalization and regression checks.
- [ ] `todo` Recognize round, honba, riichi sticks, remaining tiles, seat and four scores from the center board.
- [ ] `blocked` Validate riichi/meld inference on independent live screenshots and add ankan/kakan evidence. This needs the template replacement plus labeled live holdouts; inferred evidence remains untrusted until then.
- [ ] `todo` Produce `publicStateConfidence >= 0.98` only when all required evidence is complete.

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
- [ ] `blocked` Execute non-discard UI actions only after each action has at least 20 independent live holdouts, 100% accuracy and zero false positives.
- [ ] `todo` Attach verified execution evidence and eventual round/match outcomes to every replay record.
- [ ] `todo` Run the same replay corpus through deterministic, Jev and future search policies for comparison.

## Completion definition

All tasks above are `done`; full Auto remains fail-closed whenever any recognition,
state, legal-action, Jev, click-target or post-action verification gate is uncertain.
