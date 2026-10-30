# b0a46eb 友人戦の回帰（2026-10-30）

CPU（簡単）3人との四人東風友人戦。1戦目は開始時の部屋確認で300+0秒を確認し、`reviewed_friend_start_clicked` に `verifiedFriend300:true` が記録された。操作者は `--action-deadline-ms 300000 --force-auto-click-budget-ms 2600 --board-metadata --match-length east --advance-screens --resume-away`。使用コミット `b0a46eb`。起動・再起動の引数は各成果物の `operator-lifecycle.jsonl` を参照。

1戦目は自家2位28,000点。結果画像は `artifacts/friend-300-b0a46eb-resume3-20261030/frames/2026-10-30T09-04-59.029110+00-00.match_result.png`。打牌、鳴きの選択・スキップ、リーチ打牌などに複数回手動介入したため無人回帰は失敗。東2局の二索放銃は手動打牌によるもので、エージェントの打牌判断とは区別する。実行中の操作者は一部 SIGTERM で終了し、その後も安全停止して再起動した。

2戦目は自家1位33,500点。32,500点は東4局途中の点数であり最終点ではない。結果画像は `artifacts/friend-300-b0a46eb-next-resume2-20261030/frames/2026-10-30T10-18-11.447461+00-00.match_result.png`。開始主体と開始時の300+0秒設定は保存ログから独立に確認できていない。途中からの操作者は上記と同じ deadline・click budget で起動した。打牌、鳴き、リーチ打牌、ロンを手動で補ったため、こちらも無人回帰失敗。2試合ともCPU友人戦の機能検証であり段位戦の勝率評価ではない。

## ログに残る停止

- 1戦目の `artifacts/friend-300-b0a46eb-20261030/python-operator.jsonl` 07:50:02.487 UTC に友人戦開始を確認した直後、07:50:04.590 UTC に現画面 `matchmaking` と判定し `verified_friend_300_proof_revoked`、理由 `matchmaking`。長時間設定の証拠が卓到着前に失効した。
- 同ログ 07:51:33.481 UTC に `force_auto_click_budget_expired`、`phase:before_recognition`、新しいキャプチャ年齢291msでも `decisionBudgetMs:0`。2戦目の `next-resume` 09:14:38.253 UTC には同一ツモ猶予が適用されても `effectiveActionBudgetMs:10000`。再接続時は開始画面の証拠も復元されないため、この観測だけで開始時失効の影響とは断定しない。
- 1戦目 `resume2` 08:46:07.310 UTC、2戦目 `next-resume` 09:27:52.480 UTC に `selection_uncertainty_safety_stop`、理由 `later_draw_without_confirmed_own_river`。いずれも後続の操作を止め、再起動を要した。
- 1戦目開始時 07:50:37.065 UTC はチー選択前にクリック予算切れ、07:51:31.783 UTC は打牌確定の時間不足で `action_aborted`。フレーム・判断・操作詳細は各 `frames/`、`replays/`、`python-operator.jsonl` にある。手動操作は操作者ログだけでは網羅できない。

開始遷移の修正後、開始画面から証拠の維持を確認し、手動介入なしで300+0秒の回帰を再実施する必要がある。安全停止や選択確定の問題は別途再現して調べる。
