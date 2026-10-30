# 三麻友人戦の操作者起動経路

既存の四麻操作者は CLI の引数検証後、CDP接続先ごとの `operator_lease` を取得してから認識サーバーを起動し、ブラウザ接続する。同一接続先は別チェックアウトや localhost の別表記でも同じ排他対象となり、重複起動は `operator-startup.jsonl` に記録する。通常の処理・観測は `python-operator.jsonl`、`frames/`、`replays/` に保存する。友人戦の確認済み画像と `action-deadline-ms=300000` が揃った場合だけ長時間の予算扱いを有効にする。一方、この既存の全経路は四麻用の画面・操作・判断を使う。

三麻はNodeランチャーとPython CLIで明示ルールを拒否し、友人戦開始分岐にも部屋確認後に例外で止める防護がある。しかし、Python `PythonAutoOperator` をCLIを通さず直接生成すると、従来は三麻指定でもルール検査前に設定ファイルを読み、認識サーバーを起動できた。この経路を利用した実害は観測していない。今回、コンストラクタ先頭で三麻を拒否し、画面参照・設定読込・子プロセス起動に到達しないことを確認した。通常の四麻は同じ初期化経路を使用し、既存の接続先別排他・ログ・設定処理を変更しない。

```sh
PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python.test_sanma_constructor_guard python.test_sanma_mode_guard python.test_sanma_friend_navigation python.test_sanma_friend_start python.test_operator_lock
```

19テストが通過。重複検査には別の一時接続先を用いて実際の排他を検証し、模擬した認識サーバーやブラウザが起動しないことも検査した。実ブラウザや実対局には触れていない。

開始前の三麻部屋ラベルと2回連続フレームの照合は準備済みだが、現時点ではログ値の引継ぎだけで三麻の手牌・河・抜き北・選択肢が完全に認識できるとは証明できない。手動検査の後も開始操作を拒否し、実自動起動と300+0友人戦の回帰完走は未実施。三麻の判断と操作が実装・検証されるまで排他取得やログ準備を理由にガードを解除しない。
