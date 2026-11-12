# 25061dc の撮影遅延・鮮度修正

`25061dc` から SSD 独立 worktree `freshness-25061dc` と branch
`ssd/freshness-25061dc` を作成。実装と独立レビュー・refresh 試験を
サブエージェントに分担した。main、実ブラウザ、操作者、稼働コード・設定は
変更せず、ライブ対局への操作・デプロイは行っていない。

## 問題と変更

`reviews/freshness-probe-25061dc.py` と同名ログは、撮影開始時の画像が
99 秒後に返っても、初回撮影・選択後撮影の双方で 2 回クリックする再現。
取得完了時刻を鮮度起点にすることと、後続撮影による起点更新が原因だった。

- 初回撮影要求の直前から確認クリック直前まで **5 秒未満** を要求する。
  基準画像の確認撮影、選択確認撮影、再ポーリングで起点を更新しない。
- 各撮影にも開始時刻を設け、返却時に遅延・時計逆行を検査する。
  検証、保存、ログ、コールバック、マウス呼出し、待機を含む累積時間も制限する。
- 元の手番開始から **300000 ms 未満**、セッション有効性の検査を維持する。
  refresh の時間切れを画像不一致による再試行可能エラーへ変換しない。
  選択後の取得・鮮度失敗はポインターを退避し、`SelectionStateUncertainAbort`
  として確認クリックを止める。
- refresh ログの既存完了時刻フィールドを維持し、撮影開始時刻を別途記録する。

## オフライン検証

証拠は `/home/yama1/server/data/dev-work/jantama/reviews/freshness-25061dc-fix/`。
全コマンドの一時領域を `jantama-dev run` で SSD に設定した。
既存の隔離検証用 Python 環境
`/home/yama1/server/data/dev-work/jantama/evidence187-review-fix/test-venv/bin/python`
を使用し、依存・稼働環境は変更していない。

- 修正前の実装に新規試験を適用して 8 負例が失敗することを確認
  (`new-tests-before.log`)。正常例は通過する。
- 修正対象・refresh 試験 **57 件成功** (`target-tests.log`)。
  99 秒撮影、5 秒境界、累積遅延、繰返しポーリング、初回クリック呼出し遅延、
  時計逆行・非有限値、元の手番期限、失効、保存・ログ・検証遅延を検査する。
- 保存済み 7p 画像を実際の `send_discard_click` と牌持上げ判定へ通す。
  初回撮影遅延は 0 クリック、選択後遅延は 1 クリック、正常例は
  `(1027.5, 999)` と `(1027.5, 951.0, delay=80)` の 2 クリックを検証する。
  マウスはモックなので実入力は送信しない。
- refresh の 5 試験も実 sender を使用。各撮影 99 秒・3+3 秒は 0 クリック、
  2+2+2 秒は 1 クリック、1+1+1 秒は 2 クリック。合成画像の牌判定はモック。
- 保存画像のオフライン再生 6 ケース成功 (`replay.json`)。
- 周辺 7 モジュール **59 件中 56 成功・3 skip** (`regression.log`)。
  freshness、確認撮影、打牌復帰、実行証拠、証拠連鎖、牌字診断、南の持上げ確認を
  検査した。skip は保存画像を必要とする既存試験。対象と合わせて
  **116 件中 113 成功・3 skip**。最終差分の `git diff --check` も成功。

再実行はリポジトリルートから:

```bash
/home/yama1/.local/bin/jantama-dev run -- env PYTHONPATH=python /home/yama1/server/data/dev-work/jantama/evidence187-review-fix/test-venv/bin/python -B -m unittest test_sanma_friend_discard_experiment test_sanma_discard_refresh_capture_latency
```

セッション条件は友人戦 `300+0` / `actionDeadlineMs=300000`。
遅延は仮想時計で注入した。ライブ機能試験、打牌成立、対局完了、短時間設定や
段位戦勝率の評価ではない。同期撮影自体のブロックを中断する変更ではなく、
返却後の古い画像に基づくクリックを拒否する。撮影開始は画像年齢の保守的な
起点であり、ブラウザ内で要求以前からキャッシュされた画像の時刻証明ではない。
5 秒を超える遅い環境で拒否が増える可能性がある。
