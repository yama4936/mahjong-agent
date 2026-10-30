# 三麻盤面OCRの観測候補

三麻友人戦の3画像（`artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-05-55-331Z-before.png`、`2026-10-30T16-30-00-848Z-before.png`、`2026-10-30T17-20-14-718Z-after.png`）に既存OCRをオフライン適用したトークンを `test/fixtures/sanma-board-tokens/` に保存した。三麻の左右・上の位置と東南西の席対応は同画像を元にしている。高信頼の自風・局・3点数・供託・本場が揃い、供託込み総点と清算済みが呼び出し側から明示され、整合する場合だけ候補を返す。右点数・欠損・重複・総点不一致は拒否する。

**画像のゲーム種別・座席・清算済み状態やOCRの正確性を独立検証する仕組みではない。** 候補は常に `verified: false` で、操作や自動判断には接続していない。3枚の画像を用いた観測であり、別のUI設定・解像度・点数・供託表示、誤認識への網羅的な検証ではない。段位戦や自動運転の成功を示さない。

## 画像からの候補と標本監査（2026-10-31）

`python/sanma_board_image.py` は既存の画面分類・OCRと上記のトークン検証を、保存画像について呼び出す読み取り専用経路である。常に `verified: false` を返し、実行中の操作者には接続しない。画面分類が対局以外の場合、または必要な値が欠ける場合は候補を生成しない。供給された点数総計・清算状態が不明な場合も整合済みとは扱わない。

手動支援の三麻友人戦の連続画像2985枚から100枚ごとに抽出した30枚に、和了・点数移動・終局前後の8枚と設定・結果画面の2枚を加えた40枚を監査した。総点105000・清算済みを仮定し、30枚が点数保存則に整合する候補、10枚は `not_gameplay_screen` で候補なし。通常盤面と見られる `frame-000246` は実画面の東1局、自家西34000・左南34000・上東35000、供託2・本場0と照合した。四麻盤面の既存fixture 9枚は候補なし（右点数による拒否3、不足・曖昧6）。候補すべての独立した正解照合はしていない。標本の大半は同一試合の繰り返しであり、別の部屋・画面設定・順位・点数・決済過程での精度は未確認。画像分類の誤認も既知のため、保存則一致だけで画面種別やOCRの正しさは保証できない。

個別結果はローカルの `artifacts/sanma-board-image-audit-20261031/results.jsonl` と `four-player-negatives.jsonl` に保存した。これらと元画像はgit管理外で、実施環境に画像・OCR依存物がある場合のみ追試できる。次の手順は標本と条件を再現し、JSON Linesを標準出力へ出す。実際の対局や操作は行わない。

```bash
PYTHONPATH=python .runtime/python-auto-venv/bin/python - <<'PY'
import json
from pathlib import Path
from sanma_board_image import recognize_sanma_board_candidate

base = Path('artifacts/sanma-manual-e48c562-20261031')
frames = sorted((base / 'continuous').glob('frame-*.png'))
assert len(frames) == 2985, '元の連続画像が必要です'
selected = frames[::100]
for index in (246, 249, 251, 252, 254, 2910, 2911, 2980):
    selected.extend(frames[index - 1:index])
selected += [base / 'preflight.png', base / 'final-result.png']
selected += list(Path('test/fixtures').glob('board-*.png'))[:12]
selected += list(Path('test/fixtures').glob('board-*.jpg'))[:12]
for path in dict.fromkeys(selected):
    result = recognize_sanma_board_candidate(path, expected_total_points=105000,
                                             payment_phase='settled')
    result.pop('tokens', None)
    print(json.dumps({'path': str(path), 'result': result}, ensure_ascii=False))
PY
```

関連テスト: `PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python/test_sanma_board_image.py python/test_sanma_board_tokens.py python/test_sanma_board_consistency.py`。元画像やOCR依存物がない環境では実画像テストがskipされる。
