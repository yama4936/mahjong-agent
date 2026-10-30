# 友人戦 002df4d 再検証（2026-10-30）

## 条件と結果

- 雀魂四人友人戦、東風、CPU（簡単）3人、300+0秒、部屋 22201。使用コミット `002df4d`。操作者の `--action-deadline-ms 300000`、`--force-auto-click-budget-ms 2600`。対局途中で同じ設定の操作者に再接続した。
- 結果は自家1位 32,000点、CPU 24,500点、24,500点、19,000点。東4局終了時に終了せず南場へ延長した。最終結果画像は `artifacts/friend-300-002df4d-resume-20261030/frames/2026-10-30T11-38-19.240155+00-00.match_result.png`。結果画面の確認クリックは同ディレクトリの `python-operator.jsonl` 末尾の `screen_advanced` に記録されている。
- 手動の打牌、リーチ後の選択打牌、チーのスキップ等による介入と操作者再接続を含むため、**自律操作の回帰試験は不合格**。CPU友人戦の機能確認であり、段位戦の勝率を示さない。

## 操作・状態認識の証拠

時刻は UTC。主ログは `artifacts/friend-300-002df4d-retry-20261030/python-operator.jsonl`、再接続後は `artifacts/friend-300-002df4d-resume-20261030/python-operator.jsonl`。

- 10:52:19、打牌 deadline 300000 ms が開始。10:52:21 の `force_auto_discard_selection_window_insufficient` は `effectiveActionBudgetMs=295000` に対し、画像鮮度に基づく `remainingMs=874` が確認クリック予約の 1000 ms に不足し、`action_aborted` となった。長い対局予算自体の適用は確認できるが、短いクリック鮮度制限との組み合わせで打牌を繰り返し中止した。
- 11:14:09、`selection_uncertainty_safety_stop` は `later_draw_without_confirmed_own_river`、baseline draw 48、現在 draw 51 を記録。直前に自河観測は baseline 12 から13への増加を確認したが、操作との紐付けを確実にできないまま停止した。リーチ時の待ち牌表示による河画像の遮蔽は有力な仮説であり、画像と前後ログによる再現検証が必要。原因を断定しない。
- 再接続後 11:37:53 のロンは `reaction_win` にて自動クリック、ボタン消失を確認。11:38:19 に最終結果を認識し確認画面を進めた。再接続後も `selection_uncertainty_wait` が発生しており、この単発のロン成功は一連の自律操作成功を意味しない。

## 未完了

鮮度予算と選択打牌確認の停止原因をそれぞれ修正・再現テストし、新しいコミットで 300+0 秒、deadline 300000 ms の友人戦を完走して再評価する。手動介入を含むこの結果から判断ロジックや段位戦の勝率改善は結論できない。
