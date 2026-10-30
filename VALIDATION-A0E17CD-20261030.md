# 友人戦回帰: a0e17cd（2026-10-30）

## 条件と結果

- 四人東、CPU（簡単）3人、友人戦 300+0 秒。開始前照合画像は `artifacts/friend-300-a0e17cd-retry-20261030/preflight-room.png`。開始照合は8枚中2枚が不一致だったが、後続の連続一致を経て `reviewed_friend_start_clicked` が `verifiedFriend300=true` を記録した。
- 実行コミット `a0e17cd7d2d8486f2daefa91a6831c35da95752f`。`operator-lifecycle.jsonl` に `--action-deadline-ms 300000 --force-auto-click-budget-ms 8000 --board-metadata --match-length east --advance-screens --resume-away` が記録されている。
- 結果画像 `frames/2026-10-30T12-49-53.437663+00-00.match_result.png`: 自家2位 29,700点、CPU 36,500 / 17,500 / 16,300点。友人戦の動作確認であり、段位戦の勝率改善を示さない。

## 操作と判定

- 操作者は同一 PID で開始から `match_completed_stop` まで記録し、終了コード0。結果確認ボタンの `screen_advanced` も記録。ログ上は手動介入や安全停止の記録はなく、途中の観察でも介入は報告されていない。自律的な試合完走と結果画面操作は確認できた。ただし全局面の認識・操作の正確性を証明するものではなく、機能全般の無条件合格とはしない。
- 49 decision、48 click_sent、44 own_discard_reconciled、44 public_own_river_append_confirmed。東1局は自動リーチ・ツモ、東3局は `reaction_win` によるロンが結果画面まで記録。東2局のチーは手牌・副露変化で確認、後の手牌・河との整合も一例確認。48件と44件の差を全て異常と断定できない（鳴かれた牌や局終了などがある）。
- 12:41:32 UTC の `action_aborted` は手牌変化による再試行可能な中止。12:47:38 の `recognition_retry` は手牌行抽出失敗。どちらも後続の操作があり、停止はしなかった。12:40:53 および12:48:51 に河照合 `unresolved` が記録されたため、全打牌の独立確認を主張できない。
- 東3局・東4局のポンについて、以前は `pendingDiscard.fromSeat` と `verifiedCallDiscard.fromSeat` の不一致を要調査としたが、追加照合で座席表現の違いと確認した。前者は自家の実座席に変換した値、後者は画像側の相対座席（自家を東とする基準）である。東3局は自家北で raw `north` → 実座席 `west`、東4局は自家西で raw `south` → 実座席 `north`。画像・河とも整合し、両方の `called_river_reconciled` で `removedSnapshots=1`。座席変換は `python/board_metadata.py` の `remap_seats`、確認値の保存は `python/auto_operator.py` の `evaluation["verifiedCallDiscard"]` を参照。この2件は鳴き元の取り違えの証拠ではない。
- 東4局 12:48:15 の `ambiguous_open_draw_fallback` は P を却下し 6m を選択。認識不確実性を回避して継続した記録であり、判断の正否は未検証。2萬/8萬補正が本対局で対象場面に発動した証拠は未確認。
- 12:49:49 の `verified_friend_300_proof_revoked` は `ranked_menu` 判定によるもので、その後同じ結果画像を `match_result` と認識して確認操作・正常終了した。結果演出中の画面誤分類の可能性はあるが、本記録だけでは確定しない。

時刻はログの UTC。詳細は `artifacts/friend-300-a0e17cd-retry-20261030/python-operator.jsonl`、`operator-lifecycle.jsonl` と同ディレクトリの frames / replays を参照。
