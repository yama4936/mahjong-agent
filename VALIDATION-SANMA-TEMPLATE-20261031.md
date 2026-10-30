# 三麻の手牌画像とローカルテンプレートの確認（2026-10-31）

## 副露後の5索

`artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-16-46-070Z-after.png` の6枚目は緑の索子4本と中央の赤い索子1本が描かれた通常の5索。 `templates/live-slim/5s__train_mu99h1rc_08.png` と同じ意匠であり、認識結果 `5s` はこの画像に限って正しい。赤索子には全面に赤い索子が描かれる。中央だけ赤い通常5索を赤5索と判断してはいけない。

## 7索の誤ラベル

ローカルの `templates/live-slim` は git 管理対象外。以下の6ファイルは `0s`（赤5索）と名付けられているが、いずれも赤1本・緑6本の7索を表示している。

- `0s__train_mu99ang8_10.png`
- `0s__train_mu99cjl9_10.png`
- `0s__train_mu99eoxc_09.png`
- `0s__train_mu99h1rc_09.png`
- `0s__train_mu99hgpr_09.png`
- `0s__train_mu99irvl_09.png`

名前は手牌から収集した学習用クロップの命名形式と一致するが、当ディレクトリに manifest がなく、元画像と誤ラベル発生経緯は特定できていない。残る3つの `0s` クロップには赤5索の意匠が見える。

実際の友人戦の独立画像 `artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T17-19-32-323Z-before.png` を `config/layout-runtime.json`、`dynamicLayout:true`、`openMelds:0`、`templates/live-slim` で読み取ると、見た目が7索の6・7枚目を `0s`, `0s` と誤認した。信頼度と候補差はそれぞれ 0.9945 / 0.0375、0.9882 / 0.0202。画像全体は他に空欄を含み `safe:false` なので、この画像が操作に使われた証拠はない。

元ディレクトリを変更せず、別ディレクトリにコピーして上記6ファイルのみ除くと、同じ画像の2枚は `7s`, `7s` に変わった。`templates/bootstrap` でもこの2枚は `7s` だった。`scripts/run-operator.mjs` の既定は `templates/bootstrap` であり、`templates/live-slim` は明示指定した場合に影響する。既定テンプレートに問題がないという包括的な保証ではない。

再現例（認識のみ、ブラウザ操作なし。事前にビルドが必要）：

```sh
printf '%s\n' '{"id":1,"screenshot":"artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T17-19-32-323Z-before.png","dynamicLayout":true,"openMelds":0}' | node dist/src/recognition/recognitionServer.js config/layout-runtime.json templates/live-slim
```

修正候補は `templates/live-slim` を別の作業ディレクトリにコピーし、上記6枚をそのコピーから除くこと。元のテンプレートは変更していない。除外後に誤認が減ることは上記1画像でのみ確認しており、他の牌・赤5索の独立した画像を含む holdout と実対局全体の性能は未検証である。既存の `templates:validate` で十分な独立 holdout と全クラスを確認する前に、そのコピーを自動運用向けに承認しない。テンプレートの内容が変わるため、以前のテンプレート検証結果を流用しない。
