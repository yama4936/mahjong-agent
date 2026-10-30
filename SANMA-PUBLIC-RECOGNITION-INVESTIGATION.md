# 三麻公開牌認識の実画像調査（操作未接続）

実画像は `artifacts/sanma-manual-e48c562-20261031/actions/`、同じ三麻 CPU 友人戦の記録。画面・牌姿は目視で確認。操作者は使用せず、保存画像だけを再解析した。使用ブランチ基準 `ad5f373`。次のコマンドをリポジトリのルートから実行した（`templates/live-verified` はローカルのテンプレートセット、hybrid モデルはローカル `.runtime` に依存）。

```sh
node --import tsx src/cli.ts public-observation artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-05-55-331Z-before.png config/layout-runtime.json templates/live-verified --backend=hybrid --seat=west
node --import tsx src/cli.ts public-observation artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-30-00-848Z-before.png config/layout-runtime.json templates/live-verified --backend=hybrid --seat=south
```

- 最初の画面では河の対面の南と左の東、ドラ表示牌の西を取れた。ただし四麻用変換は架空の north 対戦者を追加し、候補ゼロの副露領域を `meldsObserved: true` と出力した。
- 2番目の画像では対面の河が目視で 9p・9m・東の3枚であるのに、認識は 9m・9p の2枚を `discardsObserved: true` と出力した。左の河も目視で 1s・東・6p・4p の4枚に対し、東を抜いた3枚を `discardsObserved: true` と出力した。漏れた牌は画像上で青く強調表示されている。検出候補がすべて分類できても、画面内の全牌を検出した証拠にはならない。
- この画面では左の中ポンは正しく検出できた。自分の副露は目視で7枚あるが、`ownMeldsObserved: false` で不完全。個々のポン検出成功は他の副露や暗槓の網羅を意味しない。
- `2026-10-30T16-05-55-331Z-after.png` では自分の抜き北が概ね x=1390, y=765 に表示され、カウントダウンに遮られている。四麻用 `ownMelds` 領域（x=1560,y=930 以降）の外にあり、抜き北認識経路もない。2番目の画像には対面側にも抜き北が見える。北が未検出であることは北がゼロである証拠ではない。

三麻で安全に利用するには少なくとも、実画面の席に合う2対手への変換、点灯・遮蔽状態を含む各河領域の検出完全性の独立した検証、副露の位置と暗槓や複数副露への対応、各席の抜き北専用領域と遮蔽時の不明扱い、枚数の物理制約と複数フレームの整合性が必要。席変換のみでは既存の `discardsObserved` や `meldsObserved` を信頼できない。各画像は同一試合の2時点であり、別試合・各座席・鳴き・遮蔽の広い組み合わせへの一般化は未検証。自動運転の成功や勝率の根拠ではない。
