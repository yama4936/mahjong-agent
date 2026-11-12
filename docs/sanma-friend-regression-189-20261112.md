# 三麻友人戦189: 回帰停止とポン期限の観測

2026-11-12 JST。三麻東風、CPU簡単2人、部屋58217、300+0秒。操作者の設定は `action-deadline-ms=300000`、`force-auto-click-budget-ms=8000`、使用コミット `40a1cf413eea1cc0a6f95f7c7084c4693c17eab6`。開始画面を確認後、14:33:58に開始入力が送信された。起動設定とログ、画像・操作記録は `/home/yama1/server/data/dev-work/jantama/evidence189` に保存。

## 自動回帰

自動操作者による打牌選択と画面上の捨て牌の増加を観察したが、操作の確定は認識ログ上未確認のまま。14:42:16、東1局の打牌復帰中に `discard_recovery_session_or_deadline` で停止。停止ログでは元の期限から301247ms、期限300000ms、監視invalid=false。画面に新たな自摸と残り時間が見えても、元の不確実な操作に結び付いた期限は延長されない。終了コード0は完走を意味しない。自動回帰は不合格であり、ポン待ちの自動復帰も検証されていない。

停止直前の復帰候補について、保存画像のハッシュを検証し、実装の候補判定と期限ガードを入力なしで再実行する `python/replay_evidence189_deadline.py` を追加した。保存記録から算出した候補受理時の経過は約91135ms、停止時は301247msで、候補判定は前者を受理し後者を拒否した。復帰後は次の入力まで旧期限を保持し、その間、画面差分による再観測や打牌直前の検査拒否があった。リプレイでは接続継続を仮定しており、画像間の操作や対局継続を証明しない。

```sh
/home/yama1/.local/bin/jantama-dev run -- env PYTHONPATH=python /home/yama1/server/data/dev-work/jantama/evidence187-review-fix/test-venv/bin/python -B python/replay_evidence189_deadline.py /home/yama1/server/data/dev-work/jantama/evidence189
```

## 無入力でのポン待ち

操作者の停止後、補助入力で進めた東2局で、左家の東に対するポン／スキップ待ちを観測。14:46:35に残り296秒、山47。操作せず概ね5秒間隔で撮影し、単調時刻と画像のSHA256を `pon-watch/observations.jsonl` に記録した。

- 14:51:25 JST `pon-watch/053.png`: 残り4秒、東2局、山47、ポン／スキップ表示。
- 14:51:30 JST `pon-watch/054.png`: ポン／スキップ表示が消え、山46、自分の分離した牌と新たな残り299秒が見える。

観測スクリプトは入力しておらず、同期間の補助操作記録にも入力はない。この1例では期限前後にポンせず対局が進んだ。秒数の表示と撮影間隔から期限切れに伴う進行と整合するが、内部イベントは取得していない。他の鳴き、ロンやツモ等の操作では検証していない。

同2画像の独立した保存画像再認識は `pon-watch-recognition/README.md`, `reproduce.py`, `result.log` にある。山47→46、同じ東2局・点数の整合候補、後画像の1索自摸候補を得た一方、三麻右家配置は未確定、後画像の白2枚はconfidence 0、操作列も未確定であり、認識結果は操作を許可しない。自動再開のための同一対局の連続性や新規ターン開始の安全な証明には不足する。今回は判定閾値、操作コード、期限の更新方法を変更していない。

## 補助後の結果

終局画面 `manual-observe-39-before.png`（15:14:13 JST）ではCPUが56900点・27100点、当方が21000点で3位。多数の手動補助を含み、エージェントの自動完走や段位戦の勝率として扱わない。各補助入力と画像の時刻・座標は `operations.jsonl` に記録した。

証拠のSHA256（相対パスは上記 evidence189）:

- `pon-watch/053.png`: `72eae3e0da9d541ac3b527b6b83b5de024fe42262df31853495ad642d0892f97`
- `pon-watch/054.png`: `7f5f0c281c1a692cbdfe41c9613adaa914c5d809b739c7abe1227d35e529de4a`
- `pon-watch/observations.jsonl`: `30b35c7dbe2a9a097fc135d8ef4e669bcaa81ef33f515e27f17af570f1e8216c`
- `manual-observe-39-before.png`: `9d47c36abff2486f924bf093dc4e5c9a8a8ebb9f8c31654125c152da905f8d71`
- `operations.jsonl`: `79675574efeea12d1886e42e58c3e5622e77b518c8fa4d27d0eb7716e0cf239b`
