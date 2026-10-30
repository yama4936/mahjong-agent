# 1dc0efd 友人戦検証（2026-10-30）

- 対象: commit `1dc0efd`、友人戦 四人東、CPU（簡単）3人、300+0秒、部屋 22201。機能確認であり、段位戦の勝率評価ではない。
- 操作者: `force-auto --action-deadline-ms 300000 --force-auto-click-budget-ms 8000 --board-metadata --match-length east --advance-screens --resume-away`。各起動の正確な引数は各成果物の `operator-lifecycle.jsonl` にある。時刻は以下 UTC。
- 結果: 2位 26,300点（CPU 31,300 / 23,100 / 19,300点）。`friend-300-1dc0efd-resume2-20261030/frames/2026-10-30T12-27-30.444730+00-00.match_result.png` の終局画面で確認。12:27:30 に `match_result` を検出して確認を押し、`match_completed_stop`、終了コード0。東風戦だが南場に延長した。
- 判定: 手動介入、プロセス消失と安全停止があったため、自律運用の回帰試験としては不合格。結果は判断ロジック単独の強さを証明しない。

## 実行と証拠

1. `artifacts/friend-300-1dc0efd-room22201-20261030` は開始前の確認画像との一致を得られず、11:45:50 SIGTERM で終了。対局開始の証拠ではない。
2. `artifacts/friend-300-1dc0efd-room22201-retry-20261030` から開始。自動打牌を複数回確認したが、11:49:07 の `replay_saved` を最後にログが途切れ、lifecycle に終了イベントがない。プロセス消失の原因や終了シグナルはこのログからは確定できない。停止手番は手動で補い、同じ対局へ再接続した。
3. `artifacts/friend-300-1dc0efd-resume-detached-20261030` は 11:53:20 に再接続。12:05:49 に要求 1920×1080 に対して 233×98 のフレームを検出、viewport restore failed で安全停止し、12:05:50 に終了コード1。表示領域を復旧し、リーチ選択とツモを手動操作した。
4. `artifacts/friend-300-1dc0efd-resume2-20261030` で 12:11:52 に再接続。南1局の手番でも手動介入があった。その後対局終了まで進行。

## 河照合と時間切れ

resume2 の `python-operator.jsonl` によると、12:15:42 と 12:15:51 に別々の手番で 2m を打牌した。前者は 12:15:51 に独立観測で確認済み。後者と続く 9m は 12:16:01 に `own_discard_receipts_queued` の expected `[2m,9m]` として並ぶため、同一打牌の重複登録とは判断できない。

12:16:05 に候補河に両牌を含む `public_own_river_append_pending`、12:16:08 の独立観測は `rawOwnDiscardsObserved:false` で前の河を保持。12:16:15 に `force_auto_click_budget_expired`（8000ms、decisionBudgetMs 0）が記録され、再観測中にクリック予算を消費したことが確認できる。河検出失敗の画像上の具体的要因、および改善後の実卓再現防止は未確認。

## 未完了

プロセス消失の原因調査、viewport 異常への復旧、河独立観測失敗と時間予算の扱いを検証し、修正後に 300+0・deadline 300000ms の友人戦で再回帰する。CPU戦の結果を段位戦の勝率改善と混同しない。
