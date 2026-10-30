# 三麻の手牌認識と物理位置の静止画像確認（2026-10-31）

この確認は、手動完走した友人戦（東風・300+0秒）の記録画像について、画像からの牌認識と座標提案をオフラインで調べたもの。操作者やブラウザには接続していない。操作成功、三麻での自動対局、段位戦の勝率を証明するものではない。画面への実際の入力は行っていない。

## 門前・重複・赤牌・ツモ牌

`artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-05-55-331Z-before.png` の目視上の手牌は、左から `1m 9m 9m 4p 0p 5p 6p 8p 2s 6s S S N`、離れたツモ牌 `E`。`config/layout-runtime.json` と `proposeLiveHandLayout` を使用した手牌認識は、`templates/live-slim`、`templates/bootstrap` のどちらでもこの並びと一致した。

| 画像上の牌 | 0始まり位置 | 提案中心座標 |
| --- | ---: | ---: |
| 9萬の1枚目、2枚目 | 1、2 | (363.5, 996.5)、(458.5, 996.5) |
| 赤5筒、通常5筒 | 4、5 | (648, 996.5)、(743, 996.5) |
| 南の1枚目、2枚目 | 10、11 | (1217.5, 996.5)、(1312.5, 996.5) |
| 離れたツモ東 | 13 | (1532, 996.5) |

各中心は画像の該当する牌の範囲内にある。これは同牌・赤牌・ツモ牌についての座標対応の確認であって、その中心への入力が正しく処理される証明ではない。recognition server の既存コードは選択された牌の文字列を `lastIndexOf` で検索するため、同名牌が複数あれば最後の位置を選び、赤5筒 `0p` と通常5筒 `5p` は区別する。これらの結果は静止画像とコードからの確認であり、三麻用の判断結果ではない。

この画像は北抜きボタンが表示されている。手牌の並びと位置が一致しても打牌を優先してよいとは判断できない。`recognition.safe` は両テンプレートとも false（最小信頼度 live-slim 0.9264、bootstrap 0.8563）。

## 副露後のツモ位置と認識の差

`artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-16-46-070Z-after.png` は緑發の明槓が表示され、手牌10枚と離れたツモ牌2筒が見える。既知の副露数を1として `calibratedOpenHandProposal` と `resolveOpenDrawGap` を用いると、提案中心は10枚目が (1122.5, 996.5)、ツモ牌が (1247.5, 996.5) となり、目視上の位置と一致した。閉門のツモ中心 (1532, 996.5) をそのまま使わない。

bootstrap の認識は `1p 1p 3p 7p 8p 5s 8s 9s W C 2p` で、画面上の牌と一致した。live-slim の認識は `1p 1p 3p 6p 8p 5s 8s 9s W C 2p` であり、4枚目の7筒を6筒と誤認した。どちらも `safe:false`（bootstrap 最小信頼度 0.9772、live-slim 0.9692）。この結果は1画像の比較であり、どちらのテンプレートの全体的な性能を示すものではない。

以下の再現例は入力画像・テンプレートを読み取るだけで、画面への入力を行わない。テンプレートと手動対局画像は git 管理外のローカルデータであり、欠けている環境では実行できない。

```sh
node --import tsx --input-type=module - <<'JS'
import { readFile } from 'node:fs/promises';
import { layoutSchema } from './src/recognition/layout.ts';
import { proposeLiveHandLayout, calibratedOpenHandProposal, resolveOpenDrawGap } from './src/recognition/handLayoutProposal.ts';
import { recognizeHand } from './src/recognition/templateMatcher.ts';
const layout = layoutSchema.parse(JSON.parse(await readFile('config/layout-runtime.json', 'utf8')));
for (const [name, melds] of [
  ['2026-10-30T16-05-55-331Z-before.png', 0],
  ['2026-10-30T16-16-46-070Z-after.png', 1],
]) {
  const screenshot = `artifacts/sanma-manual-e48c562-20261031/actions/${name}`;
  const proposal = melds
    ? await resolveOpenDrawGap(screenshot, layout, calibratedOpenHandProposal(layout, melds))
    : await proposeLiveHandLayout(screenshot);
  for (const templates of ['templates/live-slim', 'templates/bootstrap']) {
    const result = await recognizeHand(screenshot, { ...layout, ...proposal }, templates);
    console.log(JSON.stringify({ name, melds, templates, tiles: result.tiles,
      safe: result.safe, confidence: result.confidence, margin: result.ambiguityMargin,
      clickPoints: proposal.clickPoints }));
  }
}
JS
```

## 自動操作の接続点と未検証事項

既存の `recognitionServer.ts` は認識した牌列と同じレイアウトから選択インデックス・座標を返し、Python 操作者は手牌範囲、画像の変化、選択牌の浮き上がりを確認する処理を持つ。通常 auto は `recognition.safe` と信頼度を要求するが、force-auto はこの判定を直接必須にしていない。したがって今回の `safe:false` の画像を三麻自動操作の安全根拠にはできない。これらは既存コードの読み取り結果で、実画像に対するクリック検証ではない。

三麻対応には、同じ画面から得た牌列・副露数・抜き北・選択可能操作と物理位置を整合させ、牌認識に不確実性がある場合の停止条件を設ける必要がある。北抜きや和了ボタンの優先、鳴き直後とツモ後の区別、立直後のツモ切り、実際の入力後の確認はこの静止画像確認だけでは検証できていない。現状の三麻起動ガードを解除する根拠にはならない。
