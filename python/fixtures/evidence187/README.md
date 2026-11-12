# evidence187 保存画像によるオフライン回帰

`live-analysis.jsonl` の最終報告を起点に、保存済み PNG と receipt を読み取り専用で再検証した。ブラウザ、対局、main のコード・設定には接続も変更もしていない。元試験は三麻東風友人戦 `300+0`、操作期限 `300000 ms`。本変更の試験はオフラインのみで、ライブ機能試験や段位戦勝率評価ではない。

## 再現

リポジトリルートから Pillow を含む Python で実行する。

```bash
/home/yama1/.local/bin/jantama-dev run -- /home/yama1/projects/jantama-auto/.runtime/python-auto-venv/bin/python -B python/replay_evidence187.py
```

`--source-root` で evidence187 ディレクトリの移転先を指定できる。スクリプトは元 JSONL、PNG、抽出した recognition report の SHA256 を manifest と照合し、不一致や期待判定違いで失敗する。元画像のバイト列は加工しない。Git には小さい manifest/report と結果だけ保存し、約2.4 MB/枚の原画像は SSD evidence187 に保持する。manifest の report は receipt の `sourceObservation.report` をそのまま抽出したもの。ログ時刻と撮影ファイル名時刻を別に記録し、両者を撮影完了時刻と混同しない。

今回の詳細結果: `/home/yama1/server/data/dev-work/jantama/evidence187-improvement/offline-replay.json`。表示用に保存した画像: 同ディレクトリ `negative-review.png` (上からログ23、28、96、192のy=750以降の切り出し)。この表示画像は合成で、判定入力ではない。

## 実画像の再観測と負例

| 比較 | 出所 | 結果 |
|---|---|---|
| ログ28 source → freshness | 無加工保存画像 | 実手牌外接領域 `(223,921)-(1578,1072)` の RGB 差は0。旧 hand 矩形の時計除外後の差は539画素。新 hand=false、旧広域差=true、actions=true、fullFrame=true。 |
| ログ28 source → 96 source | 無加工保存画像 | 1s がなくなり並び替え、ツモ3p。hand=true、fullFrame=trueで拒否。 |
| ログ23 source → 28 source | 無加工保存画像 | ツモ北→8s、北抜き/skipボタン消失。hand=true、actions=true、fullFrame=trueで拒否。 |
| ログ23 action crop → ログ28へ移植 | **合成負例** | ボタン領域だけ変化。hand=false、actions=true、fullFrame=trueで拒否。 |
| ログ23 ツモ北 crop → ログ28へ移植 | **合成負例** | 牌だけ変化。hand=true、actions=false、fullFrame=trueで拒否。 |
| ログ28 牌面の RGB 1bit反転 | **合成負例** | 微小差も hand=true、fullFrame=true。厳密比較は拒否するが、draw glyph guardは許容（下記）。 |

実画像は目視も照合した。実牌変更ケースは異なる時点を組み合わせた保存画像対であり、隣接フレームの単一変化と主張しない。実ボタン消失には牌変更も同時にあるため、ボタンだけの独立性は合成負例で確認した。

新判定は digest に結び付いた既知の手牌スロットがある場合だけ領域ごとの RGB 完全差分を使う。閾値の緩和はしていない。実手牌変化の誤帰属を修正したが、fullFrame と既存 guard は拒否を維持する。ログ28では山牌付近の二値差分33画素 > 14 の拒否も残るので、再観測ループ自体を解消したとは主張しない。actions の既存広域矩形にも背景が入り得るため、actions=true はボタン自体の変更の断定ではない。

## 実際の既存 guard 経路

fullFrame の厳密拒否だけでは操作拒否の証明にならないため、実画像・合成対を既存 kita/draw/pon glyph guard にも通した。実牌変更は draw=`hand_faces`、実ボタン消失+牌変更は kita=`hand_faces` / draw=`partial_prompt`、合成ボタンのみは draw=`button_glyphs`、合成牌のみは draw=`hand_faces`。この4負例で3 guard 全てが false、refresh 初期条件（draw の `binary_frame` 拒否のみ）も false を assert した。これは refresh 全処理を偽のページで通した試験ではなく、実際の入口で候補から除外されることの検証である。

1bit 負例では draw guard が `center` 段階まで通って **true** となる。したがって「画素1bitの変化なら必ず操作を止める」という保証はない。既存の光沢・構造比較許容と、今回の厳密な領域診断を分ける必要がある。今回、保存画像で確認できた実牌置換・並び替えとボタン出現/消失は拒否されたが、全ての未知変化に対する保証ではない。

ログ28では kita/draw/pon 全 false、draw の拒否が `binary_frame`（33>14）であることも再現した。refresh 初期条件は満たすが、これは採用成功の意味ではなく、早期 freshness で実際に refresh が呼ばれる意味でもない。

## refresh 保存不足の再確認

86観測の source PNG・receipt・freshness PNG 計258件を元ログの SHA256 と照合し、全件一致した。ログ187の reference `96fe7462…e0c2f96` は保存 PNG から見つかったが、採用 baseline `d28aa01616bdb140d58e223a51582d0fa4ca0964ffd94dd51d88fb3e6b082262` と確認 `18d68257d7635812e0b5922984fa0ab8f11e1952b6b6a1ff8f371f8f215ee234` は attempt3/artifacts/frames の全 PNG のハッシュ集合に存在しなかった。過去の採用・確認バイト列はハッシュから復元できず、成功判断の画像三枚組は再検証不能である。新しい保存処理のテストを、過去の成功画像を再検証した証拠に読み替えない。

## 新しい refresh の保存

改善実装は refresh 試行の reference・candidate・confirmation を固有 refresh ID と役割に分けて保存し、各 PNG の SHA256、保存パス、撮影の monotonic/Unix 時刻（判明する場合）、保存時刻、参照元 screenshot をイベントへ結び付ける。採用時は baseline が candidate と同じ保存証拠を参照する。保存できない場合は採用しない。元画像の未知の撮影時刻は null とし、候補・確認の時刻は screenshot 呼び出しの完了時刻である。fsync と再読 hash 照合は追加遅延を生むため、保存後も元の300秒期限を再確認する。期限超過時に入力しないこともテストした。

## 限界

保存画像集合は有限であり、未知レイアウトや全種類の牌・ボタン変化を実戦で必ず検出する証明ではない。既知スロット内の任意の RGB 変化は非ゼロ差として扱い、未知・欠落・digest不一致のgeometryは保守的な旧広域判定へ戻る。時計マスクの下は観測できない。今回の厳密な領域診断に光沢の許容は追加していない。既存 glyph guard の許容は変更しておらず、誤認識の解消や複数フレーム再認識も対象外。ライブ適用、クリック成立、対局完了、短い持ち時間での性能、段位戦勝率の改善は未検証である。

## 関連テスト

変更対象の打牌・手牌診断・北抜き再許可テストは計61件成功（skipなし）。SSD保存ログ: `/home/yama1/server/data/dev-work/jantama/evidence187-improvement/changed-tests.log`。保存実画像の再生6ケースも成功。

周辺10モジュールの初回検査は166件中、観測テストの旧fixture（args欠落）による12エラーと、未配置の保存画像・モデルによる5 skipがあった。fixtureのargsと実PNG初期化を修正し、新診断がreceiptへ保存される統合assertを追加。観測モジュール再検査は18件、エラーなし・2 skip。他モジュールは初回検査でエラーなし。重複を除く最終対象は228件、223成功・5 skip。ログは同SSDディレクトリの `related-tests.log`（初回失敗も保持）と `resident-tests.log`。
