# 27aca1f 友人戦の操作回帰（2026-10-30）

CPU 3人との友人戦、東風戦、持ち時間300+0秒。使用コミットは `27aca1f`。
操作者の起動記録は `artifacts/friend-300-27aca1f-east-retry2-20261030/operator-lifecycle.jsonl`。
`--action-deadline-ms 300000 --force-auto-click-budget-ms 2600 --board-metadata --match-length east --advance-screens --resume-away` を明示した。復旧後の `east-resume-20261030`、`east-resume2-20261030` でも同じ deadline と click budget を使用した。

結果は自家2位、28400点（実画面の観察）。打牌、鳴きのスキップ、和了などで複数回手動介入したため、無人の自動操作回帰は失敗。これはCPU友人戦の機能確認であり、段位戦の勝率評価ではない。結果画像はこれらの操作者成果物には保存されておらず、上記の順位・点数は操作者ログだけでは独立に検証できない。

## 停止の証拠

- `retry2` の `python-operator.jsonl` 2026-10-30 06:27:13.245 UTC: `force_auto_click_budget_expired`、`decisionBudgetMs:0`、`actionEvidenceAgeMs:40059`、`effectiveActionBudgetMs:10000`。次に `recognition_deferred_stale_capture`。画面キャプチャ年齢は305msで、明示の300秒 deadline とは別の内部予算が尽きた状態。
- `resume2` の同ログ 07:39:01.429 UTC でも `decisionBudgetMs:0`、`actionEvidenceAgeMs:196664`、キャプチャ年齢365ms。新しい画面でも判断前に保留している。各 launcher の終了は lifecycle に `SIGTERM` と記録されており、原因不明の自然終了とは扱わない。
- `retry2` 05:53:50.776 UTC は `unverified_selection_evidence`、`receipt:null`。選択の確認証拠を取得できていない。
- `retry2` 05:57:56.017 UTC はリーチ打牌の `riichi_discard_confirmation_rejected`、理由 `river_changed`、河領域差11.3908%（閾値0.1%）。同時刻の `selection-before.png` と `selection-receipt.png` が保存され、後続は `action_aborted`、`selectionMayRemain:true`。ポップアップによる遮蔽が疑われるが、画像差だけでは実際の河変化を否定できず、原因確定には再現・照合が必要。

ログ、認識結果、盤面画像と判断詳細は各成果物の `python-operator.jsonl`、`frames/`、`replays/` を参照。手動操作は自動操作者のクリックとして記録されていないため、ログだけから全操作の成否や判断の妥当性は判定できない。別途原因を再現して修正し、手動介入のない300+0回帰が必要。
