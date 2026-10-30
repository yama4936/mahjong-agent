# Sanma button crops: experimental only

Crops are taken at 1920×1080 from `artifacts/sanma-manual-e48c562-20261031/actions/` after the match, rectangle x=890, y=785, width=245, height=90. They are unresized, contain no player names and share the same match, game theme, position and capture conditions.

| File | Source filename in actions directory | Logged intended action |
| --- | --- | --- |
| kita.png | 2026-10-30T16-05-55-331Z-before.png | extract_north |
| kita2.png | 2026-10-30T16-21-44-430Z-before.png | extract_north_east2 |
| riichi.png | 2026-10-30T16-12-07-300Z-before.png | declare_riichi |
| tsumo.png | 2026-10-30T16-14-57-162Z-before.png | tsumo_win |
| kan.png | 2026-10-30T16-16-46-070Z-before.png | kan_hatsu |
| pon.png | 2026-10-30T16-35-03-075Z-before.png | pon_1p |
| empty.png | 2026-10-30T16-05-55-331Z-after.png | after extract_north |

The action log and screenshots document intended clicks, not independent evaluation labels. The test includes exact-reference images for the negative action labels; it establishes only basic separation on these frames. `kita2` is a separate crop but shares the same match. No independent accuracy, accessibility across skins, variable button positions, ron/skip/kyuushu separation or live-action safety is established. Missing or ambiguous evidence must not authorize clicks.
