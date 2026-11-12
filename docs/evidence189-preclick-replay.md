# evidence189: 打牌直前の拒否の再現

`python/replay_evidence189_preclick.py` は、友人戦189で最後の次巡候補を受理した後、打牌直前に生じた3件の拒否を入力なしで再現する。既定の証拠保存先は `/home/yama1/server/data/dev-work/jantama/evidence189` で、証拠ファイルはこのリポジトリに含まれていない。別の場所へ同一構造で保管した場合は `--source-root` で指定する。

このPCの依存環境と保存先を使う例:

```sh
/home/yama1/.local/bin/jantama-dev run -- env PYTHONPATH=python /home/yama1/server/data/dev-work/jantama/evidence187-review-fix/test-venv/bin/python -B python/replay_evidence189_preclick.py
/home/yama1/.local/bin/jantama-dev run -- env PYTHONPATH=python /home/yama1/server/data/dev-work/jantama/evidence187-review-fix/test-venv/bin/python -B -m unittest python/test_replay_evidence189_preclick.py
```

固定したログのSHA256と、ログに記録された画像・認識記録のSHA256を照合し、保存済み認識結果を用いて現行の画面差分ガードを再実行する。3件は順に `hand_faces`、`binary_frame`、`hand_faces` で拒否される。二値画像の拒否は座標 `(960,384)` の32×32領域で変化17画素、閾値14だった。手牌の拒否2件はいずれも左から2枚目の牌面で差分を検出した。

認識結果を再計算しておらず、画像差分が照明変化か牌の変化かは判別できない。対局の連続性、打牌の確定、入力の安全性、友人戦自動完走や段位戦の成績を証明するものではない。証拠ログが存在しない環境では証拠依存の2テストだけをスキップする。ログが存在する場合、欠損・改変された証拠は失敗として扱う。
