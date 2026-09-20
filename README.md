# Jantama Advisor

判定GUIは`npm run dashboard -- --operator-log artifacts/python-face-trial/python-operator.jsonl`で起動できます。ライブ画面とは別に、保存ログの判定時刻・認識手牌・推奨打牌・認識スコア・クリック実行記録・停止理由を表示します。操作者を別のログ保存先で起動した場合は`--operator-log`も変更してください。GUIは閲覧専用で、自動操作を開始しません。

雀魂のスクリーンショットを固定座標＋牌テンプレートで読み取り、合法な打牌候補のシャンテン・受け入れを計算し、任意でTypeSafe Jevに最終候補を選択させるMVPです。

## 現在の安全方針

- 既定はAdvisor Modeで、クリックしません。
- 牌認識の最小confidenceが`0.98`未満なら停止します。
- 各手牌スロットの明るい牌面占有率が`minimumTilePresence`未満なら、重い照合を行わず非手番として停止します。
- 画面サイズ、手牌枚数、既知牌の4枚上限、合法手、Jevの候補IDと確率分布を検証します。
- Python操作者はログイン、ロビー、段位戦メニュー、マッチング、対局、離席、退出確認を分類し、対局以外では牌座標へ触れません。未知画面も停止します。
- Python操作者は判断時と追加2フレームの手牌認識が一致することを確認します（`--consensus-frames=3`）。その後、クリック直前の画像変化も確認します。同じ誤認が続く場合を解消する仕組みではありません。
- 雀魂の選択→確定に合わせて同一点をダブルクリックし、直後にポインタを卓中央へ退避してホバー誤認を防ぎます。
- クリック後8秒以内に手牌領域と自分の河の両方が変化し、再認識した13枚が「指定牌だけを除いた牌集合」と一致しなければ、操作未確認として停止します。
- Auto ModeではJevが未設定・失敗・低confidenceの場合も停止します。
- Auto Modeでは手牌認識とは別に、河・点数・巡目など公開局面の`publicStateConfidence >= 0.98`も必須です。
- Auto Modeでは局、ドラ、残り牌、東南西北4人分の点数、自家を除く一意な他家3人が揃わない場合も停止します。
- Autoクリックには、赤5を含む37種各5枚以上（合計185枚以上）の独立holdoutが全件合格した証跡をレイアウトの`autoOperation`へ明示的に設定する必要があります。サンプル設定は意図的に未設定です。
- リーチ・チー・ポン・カン・ロン・ツモ・見逃し・九種九牌はアクション別の証明書を要求します。打牌認識の合格だけでは、これらのクリックは解禁されません。

## セットアップ

```bash
npm install
npm test
npm run build
npm run advisor -- examples/state.json
```

画像解析、牌効率計算、安全判定はローカルで実行されます。Jevを有効にした場合だけ、構造化した局面候補をJev APIへ送ります。スクリーンショットや認証CookieはJevへ送りません。

Jevを使う場合、キーはシェル環境またはGit除外された権限600の`.env.local`だけに設定します。ソースへコミットしないでください。

```bash
export TYPESAFE_API_KEY='...'
npm run advisor -- examples/state.json --jev

# .env.localを使用する疎通確認
chmod 600 .env.local
npm run jev:smoke:local
```

### Jevの調整と評価

既定の`balanced-v2`プロファイルは、候補を`state`と`criteria`へ二重送信せず、候補ごとのシャンテン・受け入れ・打点・和了率・聴牌率・放銃率・局収支EVを構造化した`criteria`として送ります。旧方式は比較用の`legacy-v1`として残しています。モデル更新による評価の混入を防ぐため、調整中は`.env.local`の`JEV_MODEL`を`jev-1.13.0`のような固定バージョンにしてください。

リプレイごとの`actualResult.expertActionId`へ、専門家が選んだ合法なアクションID（例:`discard_E`）を付けると、両プロファイルの一致率、正解アクションへの平均確率、log loss、confidence閾値ごとのカバレッジと精度を比較できます。

```bash
npm run jev:tune:local -- artifacts/replays \
  --profiles=legacy-v1,balanced-v2 \
  --model=jev-1.13.0
```

保存時の判断と現在の決定論方策を同じリプレイで比較するには次を使います。方策間一致率、専門家ラベル精度、方策ごとの失敗数を出力します。`--jev`を付ける場合だけJev APIを呼び出します。

```bash
npm run policy:compare -- artifacts/replays
node --env-file=.env.local --import tsx src/cli.ts policy-compare artifacts/replays --jev
```

新しく保存する各リプレイには、操作の状態を`executionEvidence.status`（`verified` / `failed` / `not_attempted`）として必ず記録します。Python操作者は局結果・対局結果画面を検出すると、その画面の保存先、検出時刻、分類confidenceを、該当する全リプレイの`actualResult.round` / `actualResult.match`へ追記します。結果の追記は`--advance-screens`の有無に依存しません。数値の点差・最終順位など、画面分類だけでは確定できない値は推測せず、従来どおり`npm run result:attach -- <decision.json> <actual-result.json>`で明示的に追加します。

局結果だけでは個々の打牌の正解ラベルにならないため、`won`や`pointsDelta`を`expertActionId`の代用にはしません。ラベルがないデータセットでは調整コマンドは停止します。現在の`confidence`閾値`0.55`は未校正の暫定値であり、十分な独立ラベルが集まるまでは引き下げません。

## 画面認識

### 2026-09-20 認識改善実験

実行用レイアウトとサンプルでは`tileMatcher: "face"`を採用しました。牌面の明るい連結領域を切り出し、余白や隣牌の影響を減らします。`raw`は補正なし、`face_all`は補正後に全種類を照合します。斜視・回転の推定補正は未実装です。

| 方法 | 公開画像105枚 | 実画面83枚 |
| --- | ---: | ---: |
| 従来方式 | 48/105（45.7%） | 78/83（94.0%） |
| 牌面補正 | 73/105（69.5%） | 83/83（100%） |
| 牌面補正＋全種類照合 | 76/105（72.4%） | 83/83（100%） |

実画面は6フレーム・14種類のみで、1フレームずつ学習から外し、同一画像のバイト重複も除いた比較です。同一対局内なので他対局への精度保証ではありません。14枚揃った5フレームの全牌正解は1/5→5/5に改善しましたが、固定閾値（0.98、次候補との差0.01）を全牌が通ったフレームは0/5です。正解率と操作可能率を混同しないでください。

37出力の小型CNNも実験し、別枠の2フレーム28枚で28/28正解でした。赤5萬・赤5筒は学習データがなく、運用未採用です。既存ViTは実画面59/83、テンプレートとの厳格一致判定は採用0枚だったため、併用しても現状の操作可能率は上がりません。

`confidence`は未校正のスコアであり、正解確率ではありません。集計にはスコア帯別の実測正解率・採用率・採用中の誤認数を保存します。参考のWilson区間は独立試行を仮定するため、相関のある今回の画像群の保証には使えません。対局勝率は測っていません。

```bash
npm run recognition:benchmark
npm run recognition:benchmark-live
npm run recognition:train-cnn
npm run recognition:statistics
```

結果は`artifacts/recognition-ablation/`の`report.json`、`live-report.json`、`cnn37-report.json`、`statistics.json`に保存します。CNN学習には既存の隔離vision環境が必要です。空白画像は高信頼の白として扱わず、実行時もholdout画像をテンプレートから除外します。検証時は学習・holdout間の同一画像も検出します。認証は照合方式・バージョンにも紐付けたため、旧認証は再検証が必要です。

```bash
npm run templates:validate -- templates/live --holdout=holdout --matcher=face
```

残る検証は別対局・別描画条件の正解ラベル付き画像、赤牌を含む37種類、河・副露・リーチ表示です。今回の手牌の結果だけではこれらを検証済みとしません。

`config/layout.example.json`は1920×1080向けの既存実測値を初期値にしています。現在のUnity版と実際のブラウザのスクリーンショットに合わせて校正し、`templates/`へ34種の牌テンプレートを置きます。複数画像は`1m__01.png`のように追加できます。

Apache-2.0の雀魂牌データセットから34種の初期テンプレートを再取得できます。

```bash
npm run templates:fetch
```

現在の画面スタイルでは、通常34種をcvmaj、赤5判定だけをAutoMajsoulに担当させるハイブリッド認識器を既定で使用します。導入時に固定リビジョンとSHA-256でモデルを取得します。

```bash
npm run hybrid-vision:setup
npm run watch -- examples/state.json config/layout.json templates/bootstrap \
  --cdp=http://127.0.0.1:9222 --mode=advisor
```

AutoMajsoulのモデルはCC BY-NC-SA 4.0のため、この構成は非商用利用に限られます。cvmajはMITです。比較結果は`artifacts/model-comparison/comparison.md`にあります。ハイブリッドは赤5を分類できますが、別対局holdoutによるAuto認証はまだないためAdvisor専用です。

同じ公開データで学習されたApache-2.0のViTも、比較用として隔離された`.runtime/`環境へ導入できます。モデルは実画面holdoutの代わりにはならず、赤5は別分類が必要です。

```bash
npm run vision:setup
npm run watch -- examples/state.json config/layout.json templates/bootstrap \
  --cdp=http://127.0.0.1:9222 --mode=advisor --recognizer=vit
```

参照画像では14枚を一括処理して14/14を認識しました。CPU常駐後の推論時間は約2～3秒ですが、これは現在の実クライアント精度を証明する値ではありません。ViTの34分類は赤5を通常5として返すため、Auto認証には赤5を含む37分類の別holdoutが必要です。

テンプレートの`capture`／`holdout`／`test`画像を学習側から除外して、クラス別精度とAuto基準を測定できます。Auto合格には赤5を含む最低5枚×37種（185枚）、全件正解、confidenceと曖昧度の全件通過が必要です。

```bash
npm run templates:validate -- templates/bootstrap --holdout=capture --max-per-class=2
npm run templates:validate -- templates/bootstrap --holdout=holdout --max-per-class=2 --orientation=upright
```

実画面校正では別々の局面から`train`と`holdout`を採取します。同じスクリーンショットを両方へ使わないでください。
採取時には`manifest.jsonl`へ元画像の絶対パス、SHA-256、スロット、ラベル、分割を自動記録します。また、検証時は同一画像内容が複数ラベルに存在するとAuto不合格になります。

```bash
npx tsx src/cli.ts collect-templates frame-train.png config/layout.json \
  1m,2m,3m,4m,5m,6m,7m,8m,9m,1p,2p,3p,4p,5p templates/live --split=train
npx tsx src/cli.ts collect-templates frame-holdout.png config/layout.json \
  1m,2m,3m,4m,5m,6m,7m,8m,9m,1p,2p,3p,4p,5p templates/live --split=holdout
npm run templates:validate -- templates/live --holdout=holdout
```

検証結果をJSON保存した後、合格レポートだけを使ってAuto用レイアウトを生成します。証明書にはテンプレート集合のSHA-256が入り、実行時に1ファイルでも差し替わっていればクリックを停止します。

```bash
npx tsx src/cli.ts validate-templates templates/live --holdout=holdout > validation.json
npm run layout:certify -- config/layout.json validation.json config/layout.auto.json
```

```bash
npm run recognize -- screenshot.png config/layout.json templates/
```

河・副露の座標校正用に、設定済みROIから明るい牌面候補の矩形だけを抽出できます。これは検出支援であり、候補を牌種や公開局面へ自動採用はしません。ログイン画面などの大きな白いパネルは寸法ゲートで除外します。

```bash
npm run regions:detect -- screenshot.png config/layout.json
npm run regions:recognize -- screenshot.png config/layout.json templates/live
npm run actions:recognize -- screenshot.png config/layout.json templates/actions
```

中央盤面は`centerBoardRegions`で局、本場、供託、残り牌、自風、4方向の点数ROIを設定し、正解値を付けた参照フレームとの一致で読み取れます。参照にない値、候補差が小さい値、点数が100点単位でない状態、または4人の点数と供託の合計が100000点にならない状態は不完全として停止します。

```bash
npm run center:recognize -- screenshot.png config/layout.json center-reference-manifest.json
```

参照マニフェストは`schemaVersion`、`viewport`と、`screenshot`、`round`、`honba`、`riichiSticks`、`remainingTiles`、`ownSeat`、東南西北の`scores`を持つ`samples`配列で構成します。同一対局の保存画像2状態では全項目を再認識できましたが、これは学習元への再照合であり独立精度ではありません。そのため出力は常に`trusted: false`で、Autoの`publicStateConfidence`を上げません。3フレーム一致ゲートも実装済みです。

`regions:recognize`はドラ表示と各家の公開領域を分類し、各家には`rotationToUpright`を適用します。ドラ表示は河・副露の既知牌と重複させず、明示的に有効化したAdvisor観測へ渡します。横向き牌をリーチ証拠として抽出し、完全かつ曖昧でない3～4枚組だけをチー・ポン・明槓へ構造化します。空領域や低信頼候補は安全扱いにしません。また、候補分類だけでは河全体を取りこぼしていないことを証明できないため、この結果だけで`publicStateConfidence`を上げることはありません。

`publicTileRegions`の初期値は1920px幅の公開実測実装と一致する値ですが、クライアント版・ウィンドウ比率ごとに実画面で再校正してください。

自分の手番のスクリーンショットに14枚と分離されたツモ牌が見えていれば、手牌座標とクリック中心の校正案を生成できます。これは座標案だけで、Auto用証明にはなりません。

```bash
npm run layout:propose-hand -- screenshot.png
```

ログイン後の最初の自手番を待って校正案と根拠スクリーンショットを保存する読み取り専用ウォッチャーも利用できます。

```bash
npm run layout:watch-hand -- --cdp=http://127.0.0.1:9222 --output=artifacts/calibration
```

校正から実画面テンプレートによる手牌認識、牌効率計算、Advisor表示までを一続きで実行する場合は次を使います。既定では`templates/live-verified`を使用します。省略時は公開情報を未知として扱うため、打牌推薦は表示しますが自動クリックには使いません。公開状態JSONを第1引数に指定することもできます。

```bash
npm run live:advisor -- --cdp=http://127.0.0.1:9222 --max-turns=1
# または
npm run live:advisor -- examples/state.json --cdp=http://127.0.0.1:9222 --max-turns=1
```

既定はハイブリッドです。テンプレート集合やViTを比較する場合だけ明示的に指定します。

```bash
npm run live:advisor -- --templates=templates/live-verified --recognizer=template
npm run live:advisor -- --recognizer=vit
npm run live:advisor -- --recognizer=hybrid
```

保存済みスクリーンショットを一括解析し、`recommended_action` と `tile` を含むJSONを得る場合:

```bash
npm run analyze:screenshot -- screenshot.png
# 最初の完成条件と同じ最小JSONだけを出す場合
npm run analyze:screenshot -- screenshot.png --compact
# 公開状態とJevを併用する場合
TYPESAFE_API_KEY=... npm run analyze:screenshot -- screenshot.png --state=state.json --jev
```

未校正の河・副露ViT認識は診断情報としてのみ返し、既定では判断状態へ混ぜません。Advisorで実験的に適用する場合だけ`--use-public-observation`を指定できます。このフラグはAuto Modeでは拒否されます。

現在の画面スタイルの河は、各家の向きを正規化した6列×3段の固定グリッドとして処理します。段内の数pxの遠近差では捨て牌順を変えず、牌面が重なって輪郭分離できない最終段は、先頭2段からセル位置を外挿して在席を判定します。段の欠落、19枚以上、途中が空いた不正な並びは安全でない観測として棄却します。横向き牌は同じ河の標準寸法に対する外れ値としてリーチ宣言を検出します。

ブラウザ自動化はCDP接続を使用します。雀魂を開くChromiumを`--remote-debugging-port=9222`付きで起動し、`connectJantama("http://127.0.0.1:9222")`で既存ログインセッションへ接続します。

永続プロファイル付きの専用Chromiumは次で起動できます。認証Cookieは`.runtime/browser-profile`に残り、CDPはlocalhostの9222だけで待ち受けます。

```bash
npm run browser:start
```

Windowsではインストール済みの通常版Google Chromeを自動検出し、既定でGPU描画とログイン操作用の表示ありで起動します。別のChrome実行ファイルや保存先を使う場合は`JANTAMA_CHROME_BIN`、`JANTAMA_BROWSER_PROFILE`、`JANTAMA_CDP_PORT`を指定します。非表示で動かす場合は`JANTAMA_HEADLESS=true`、GPUが利用できない環境でSwiftShaderへ戻す場合だけ`JANTAMA_SOFTWARE_RENDERING=true`を指定します。OS依存ライブラリがユーザー領域にある環境では、起動前にその`LD_LIBRARY_PATH`も設定します。

1局面を取得・判断するコマンド:

```bash
npm run turn -- examples/state.json config/layout.json templates/bootstrap \
  --cdp=http://127.0.0.1:9222 --mode=advisor
```

対局を連続監視する場合は`watch`を使います。同一局面は一度だけ処理し、3フレーム連続で認識不能な状態（打牌後・他家手番など）へ遷移してから次の判断を受け付けます。

```bash
npm run watch -- examples/state.json config/layout.json templates/bootstrap \
  --cdp=http://127.0.0.1:9222 --mode=advisor --poll=100
```

検証時は`--max-turns=1`のように処理回数を制限できます。`Ctrl+C`で安全に監視を終了します。

`--mode=auto`は、実画面テンプレート、Jevキー、認識・判断confidence、画面安定性の全ゲートが通った場合だけクリックします。

## Python常駐オペレーター

実運用のマウス操作はPythonプロセスに任せられます。TypeScript側はスクリーンショットを受け取って構造化状態と意思決定JSONを返すだけで、ブラウザには触れません。Python側はCDP接続、安定フレーム確認、座標クリック、手牌と自家河の変化による実行確認、JSONL記録を担当します。

現在の雀魂画面と画面状態をローカルブラウザから確認する読み取り専用モニターも起動できます。

```bash
npm run dashboard
# http://127.0.0.1:8787
```

```bash
./scripts/setup-python-operator.sh
npm run build

# 読み取り・構造化だけ（クリックなし）
.runtime/python-auto-venv/bin/python python/auto_operator.py \
  --layout config/layout.json \
  --templates templates/live \
  --state examples/public-unknown.json \
  --mode observer

# 全安全ゲートとAuto証明書が揃った後だけ使用。
# 既定で権限600の.env.localを評価プロセスだけに読み込みます。
.runtime/python-auto-venv/bin/python python/auto_operator.py \
  --layout config/layout.auto.json \
  --templates templates/live \
  --state state.live.json \
  --mode auto
```

認識や判断の曖昧さを無視して候補を常にクリックする必要がある場合は、明示的な`force-auto`モードを使用できます。このモードは牌認識confidence、曖昧度、Jev confidence、公開局面confidence、Auto証明書、アクション別証明書を操作許可に使いません。ただし、候補座標が存在しない場合、クリック直前に画面が変化した場合、クリック後の変化を確認できない場合は停止します。誤打牌・誤操作を起こし得るため、通常の`auto`とは分離されています。

```bash
.runtime/python-auto-venv/bin/python python/auto_operator.py \
  --layout config/layout.json \
  --templates templates/live \
  --action-templates templates/actions \
  --state examples/public-unknown.json \
  --mode force-auto
```

実画面テンプレートを収集中に、手牌14枚のconfidenceと曖昧度、合法手、前後フレーム確認だけで打牌する限定モードもあります。これはJev・河・点数・リーチを使わない牌効率専用であり、守備判断を行いません。明示的に指定した場合だけ有効です。実画面では、打牌後13枚が打牌前14枚から指定牌だけを除いた集合と一致するところまで確認済みです。

```bash
.runtime/python-auto-venv/bin/python python/auto_operator.py \
  --layout artifacts/live/<layout>.json \
  --templates templates/live-verified \
  --state examples/public-unknown.json \
  --mode advisor \
  --allow-local-discard \
  --resume-away
```

終了は`Ctrl+C`です。記録は既定で`artifacts/python-auto/python-operator.jsonl`へ保存されます。`--mode auto`でも、認識confidence、公開局面confidence、Jev、テンプレート指紋、クリック位置のいずれかが不正ならクリックしません。

`--log`を付けた判断は`artifacts/replays/`にJSONLと個別JSONで保存できます。`replay`コマンドは保存局面を現在の決定ロジックで再評価し、選択差分を出力します。

局終了後の結果は個別判断JSONへ添付でき、ディレクトリ単位で和了率・放銃率・平均点数差・平均順位を集計できます。

```bash
npm run result:attach -- artifacts/replays/<id>.json actual-result.json
npm run benchmark -- artifacts/replays
```

`actual-result.json`の標準フィールドは`expertActionId`、`won`、`dealIn`、`tenpaiAtDraw`、`pointsDelta`、`finalRank`、`note`です。`expertActionId`はJev調整用の局面単位ラベルで、残りは局・対局結果です。

状態JSONの`visibleTiles`（または`visible_tiles`）には、`doraIndicators`、`ownDiscards`、`melds`、`opponents[].discards`に既に入れた牌を重複して入れず、他フィールドで表現していない既知牌だけを指定します。`remainingTiles`、`ownDiscards`、`melds`はsnake_caseでも入力できます。

候補には`estimatedValue`、`winProbability`、`tenpaiProbability`、`dealInProbability`、`expectedRoundValue`を付与します。現在の値は`heuristic-v1`による比較用推定であり、実戦ログによる校正済み確率ではありません。この推定値だけでAuto Modeが解禁されることはありません。

## 未完了

- 実画面に基づく座標校正と34種テンプレート採取
- 河・副露の牌候補領域検出後の分類、および点数・巡目の認識
- リーチ・副露・和了ボタンの実画面テンプレート採取と独立holdout認証（認識器とアクション別クリック禁止ゲートは実装済み）
- 守備・打点・局収支EVの実戦ログ校正（`heuristic-v1`は実装済み）
- リプレイ可視化UIと十分な実戦母数でのベンチマーク（記録・再評価・結果集計CLIは実装済み）

自動操作は、実画面で認識精度を測定してから有効化してください。
