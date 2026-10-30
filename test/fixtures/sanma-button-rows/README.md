# Offline sanma action-row crops

Native 1920×1080 friend match screenshots under `artifacts/sanma-manual-e48c562-20261031/actions/`, rectangle x=600, y=785, width=825, height=90. Crops omit avatar and names. Source and visual observations:

| crop | source before action | visible row |
| --- | --- | --- |
| kita | 2026-10-30T16-05-55-331Z-before.png | 北抜き, スキップ |
| kita2 | 2026-10-30T16-21-44-430Z-before.png | 北抜き, スキップ |
| riichi | 2026-10-30T16-12-07-300Z-before.png | 立直, スキップ partly overlapped |
| pon-kan | 2026-10-30T16-16-46-070Z-before.png | ポン, カン, スキップ |
| empty | 2026-10-30T16-07-32-642Z-before.png | no action buttons visible |
| empty2 | 2026-10-30T17-22-00-241Z-before.png | no action buttons visible; extracted north overlaps right slot |
| tsumo | 2026-10-30T16-14-57-162Z-before.png | ツモ, スキップ partly overlapped |

Same match, theme and resolution only. The skip and empty references are exact fixture images; these tests are not independent validation. One partially overlapped skip is intentionally unresolved. Other actions (ron, abort, choices), more-left positions, countdowns, transitions, scale and skin remain untested. `empty_candidate` and `candidate` are diagnostic only and cannot prove the full set of available actions or authorize clicks.
