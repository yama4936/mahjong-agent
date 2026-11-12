# freshness 3コミットの独立レビューとmain統合

対象は `origin/ssd/freshness-25061dc` の `c4a049f`、`25061dc`、
`d0034fe`。mainの既存報告 `048606d` を保持し、対象3コミットを
競合なしでマージした。別担当の停止原因調査worktreeは変更していない。
ブラウザ・対局・サービスの操作やデプロイは実施していない。

## 独立レビュー

2名のサブエージェントが安全性とテスト・保存処理を独立レビューし、
統合を止める欠陥は見つからなかった。

- 撮影開始から確認クリック直前までの累積5秒未満の鮮度制限を確認。
  保存・ログ・確認撮影・検証の遅延で起点を更新しない。
- 選択後の取得・鮮度失敗は不確定選択状態として確認クリックを停止する。
- PNGは0600の一時ファイルに保存し、fsync・再読ハッシュ検査・
  上書きしないhard-link公開・ディレクトリfsyncを行う。
- 手牌領域診断は画像digestに結び付けられ、fullFrameや既存guardを緩和しない。
- 安全性担当は76件成功。テスト担当は94件中92成功・既存2 skip、
  保存画像replay 6ケース成功。両担当ともソースは変更していない。

## 検証の範囲

全てオフライン試験で、友人戦の試験条件は `300+0`、
`actionDeadlineMs=300000`。マウス・ページはモックであり実入力はない。
同期撮影や保存のブロック自体は中断せず、復帰後に古い画像による入力を拒否する。
ライブでの打牌成立、短時間設定、段位戦勝率は評価していない。
過去refreshの欠落画像は復元できず、未知の牌変化を網羅する保証もない。

証拠は `/home/yama1/server/data/dev-work/jantama/reviews/integration-freshness-1112/`。
一時領域は `jantama-dev run` でSSDに設定し、既存の隔離Python環境を使用した。
統合前の主担当実行ではモジュール名を1件誤記しimport errorとなったが、
正しい `test_discard_confirmation_capture` を別途実行して通過した。
誤記の初回ログも保持し、統合後は修正したコマンドで再実行した。

## 統合後の結果

- 関連13モジュール **162件成功、skipなし**（160.420秒）。mainにある
  保存fixtureも利用でき、独立worktreeでskipされた試験も通過した。
  ログは `postmerge-tests.log`。
- SHA256で結び付けた保存画像replay **6ケース成功**。
  結果は `postmerge-replay.json`。
- `git diff --cached --check` 成功。友人戦187報告は元のmainと同一。

再実行コマンド（リポジトリルートから）:

```bash
/home/yama1/.local/bin/jantama-dev run -- env PYTHONPATH=python /home/yama1/server/data/dev-work/jantama/evidence187-review-fix/test-venv/bin/python -B -m unittest test_sanma_friend_discard_experiment test_sanma_discard_refresh_capture_latency test_sanma_hand_region_diagnostics test_sanma_friend_kita_rearm test_sanma_resident_observe test_sanma_friend_freshness test_sanma_freshness_diagnostics test_discard_confirmation_capture test_sanma_friend_discard_recovery test_sanma_discard_execution_evidence test_sanma_discard_evidence_chain test_sanma_discard_glyph_diagnostic test_south_raised_confirmation
/home/yama1/.local/bin/jantama-dev run -- /home/yama1/server/data/dev-work/jantama/evidence187-review-fix/test-venv/bin/python -B python/replay_evidence187.py
```
