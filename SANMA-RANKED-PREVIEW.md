# 三麻段位戦：保存画像による事前確認

`python/sanma_ranked_preview.py` は、2026-10-31 の銅の間の保存画面から切り出した見出し・四人東・三人東・三人東の左枠の4領域を、1920×1080の画像と照合するオフライン調査用の関数です。4領域が一致すると候補として報告します。上段の四人東を三人東の位置に重ねた画像、段位メニュー、プロフィール、過去の入場拒否画面、3つの文字領域だけを黒背景に貼った画像、文字または左枠を覆う合成遮蔽では候補にならないことを確認しました。参照は単一の保存画面で、画像の別の場所にあるダイアログや、4領域すべてを偽造した画像は検出できません。他スキン、描画変化、実際の入場可否も検証していません。候補を実機操作の許可に使用してはいけません。

この調査用関数は操作者から呼び出していません。従来の三麻段位戦ガードと、三麻に四麻の座標を渡さないガードは維持しています。三人東の実画面でのクリックと参加可否は未確認です。

再現（保存画像を持つ環境で実行）：

```sh
SANMA_PREFLIGHT_ROOT=/home/yama1/projects/jantama-auto/artifacts/sanma-preflight-20261031 JANTAMA_LIVE_ROOT=/home/yama1/projects/jantama-auto/artifacts/live PYTHONPATH=python /home/yama1/.local/bin/jantama-dev run -- /home/yama1/projects/jantama-auto/.runtime/python-auto-venv/bin/python -m unittest -v python.test_sanma_ranked_preview python.test_sanma_ranked_navigation_guard
```
