# c4a049f 独立レビューの修正（2026-11-12）

`ssd/evidence187-audit` (`c4a049f`) を起点に、`jantama-dev worktree` の dry-run 後、SSD 上に `ssd/evidence187-review-fix` を新規作成した。修正担当と独立レビュー担当のサブエージェントを分離した。main の作業ツリー、ブラウザ、対局、稼働コード・サービスは変更していない。

根拠は `/home/yama1/server/data/dev-work/jantama/review-c4a049f-20261112/failure-probes.log` および `/home/yama1/server/data/dev-work/jantama/evidence187/improvement-review.jsonl`。旧実装では確認画像保存に99秒かかっても入力へ進み、umask 022 では画像が0644となり、fsync失敗後にも最終名のファイルが残った。

## 変更

- 画像取得完了からの経過時間を **5秒未満** に制限。候補・確認画像の保存と検証後、採用ログ後、操作前コールバック・ログ・セッション確認後に検査する。候補画像の時刻を保存後の時刻に更新しない。2回目のクリックでは選択確認画像の取得完了時刻を使い、検証処理中の遅延も検出する。
- 元の手番開始から **300000 ms** の操作期限とセッション失効検査を維持。画像更新で操作期限を延長しない。既存の画像差分、領域、牌面、ボタン、山牌、安全確認の閾値は変更しない。
- 同一ディレクトリに0600の一時ファイルを作成し、書込み・flush・fsync・再読ハッシュ照合後にハードリンクで原子的に最終名を公開する。既存ファイルを上書きせず、競合した書込みは失敗する。失敗時は自分が公開したファイルと一時ファイルを清掃し、他の書込みの成功ファイルを削除しない。
- 保存失敗の役割、ハッシュ、取得時刻、エラーを証拠イベントへ残す。保存後の入力ゲート拒否にもrefresh IDと保存証拠を結び付ける。

## 隔離検証

証拠ディレクトリ: `/home/yama1/server/data/dev-work/jantama/evidence187-review-fix`。
新規Python 3.12環境を同ディレクトリの `test-venv` に作成し、リポジトリのPillow/PlaywrightとOCR依存を導入した。依存一覧は `dependencies.txt`。一時ファイルは `jantama-dev run` によりSSDへ保存した。実ブラウザ・実入力を使用せず、セッション条件は友人戦 `300+0`、`actionDeadlineMs=300000`。

- 変更対象: **50テスト成功** (`fix-tests.log`)。正常系、保存3段階・採用/操作ログ・コールバック・セッション確認での99秒遅延、4.999秒/5秒の境界、逆行/非有限時計、元の操作期限、セッション失効を検証。
- 実際の送信関数をモックマウスで通し、正常系は2クリック、選択確認画像の陳腐化・期限切れ・失効では最初の1クリックだけで停止。保存遅延ケースでは送信関数への到達自体を拒否。
- 並行書込みをバリアで同期させ、完全な勝者1件のみが残ることを検証。部分書込み、ファイル/ディレクトリfsync、再読ハッシュ失敗で最終名・一時ファイルが残らないこと、umask 000/022の双方で作成時・公開後とも0600になることを検証。
- 独立レビュー担当も追加8テストを別途実行し全件成功。差分に重大な未修正問題なし。
- 保存実画像のオフライン再生 **6ケース成功** (`replay.json`)。
- 周辺8モジュール **86件中84成功・2 skip** (`regression-configured.log`)。freshness、hand region、kita rearm、resident observe、discard recovery、glyph diagnostics、confirmation captureを含む。skipは隔離worktreeにない保存画像・実認識環境を必要とする既存試験。変更対象と合わせて **136件中134成功・2 skip**。初回の周辺実行は誤った作業ディレクトリとnumpy/OpenCV未導入のため12失敗・5エラー・2 skip (`regression.log`)。ルートディレクトリと依存を整えた再実行で解消した。システムPythonのvenv作成もensurepip不在で失敗したため、uvのPython 3.12による独立環境を使用した。

再実行例（リポジトリルート）:

```bash
/home/yama1/.local/bin/jantama-dev run -- env PYTHONPATH=python /home/yama1/server/data/dev-work/jantama/evidence187-review-fix/test-venv/bin/python -B -m unittest test_sanma_friend_discard_experiment
/home/yama1/.local/bin/jantama-dev run -- /home/yama1/server/data/dev-work/jantama/evidence187-review-fix/test-venv/bin/python -B python/replay_evidence187.py
```

## 制約

遅延は仮想時計による注入で、画像取得・マウス・選択牌の判定にはモックを使用している。ライブ機能試験、実際の打牌成立、対局完了、短い持ち時間や段位戦勝率は検証していない。取得時刻は撮影要求完了時刻であり、シャッター時刻ではない。5秒制限により遅い環境で拒否が増える可能性がある。

Linux上の同一ファイルシステムでハードリンクとディレクトリfsyncを使用する。fsync自体が失敗するストレージで、清掃のクラッシュ耐久性までは保証しない。プロセス強制終了時の一時ファイル回収、画像とログの一括トランザクション化は対象外。既存の0644画像は変更しない。今回の修正はデプロイしていない。
