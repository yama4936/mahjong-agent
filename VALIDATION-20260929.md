# 修正版6e67ff0の300+0秒実機回帰

- 部屋75408、四人半荘、300+0秒、簡単CPU3人。
- 25000点開始、1位必要30000点、飛び有効、赤ドラ3、喰い断有効、
  ローカル役無効、一翻縛り。画面で設定を確認。
- 実行コード6e67ff0、layout=config/layout-300-regression.json。
- action-deadline-ms=300000、force-auto-click-budget-ms=8000。
- 実行開始2026-09-28T15:03:07.559555Z（日本時間9月29日）。
- artifacts/friend-300-fixed-6e67ff0-20260929/に操作ログ・画面を保存。
- 設定画面：artifacts/live/friend-300-settings-6e67ff0-20260929.png。
- 待機画面：artifacts/live/friend-300-room75408-6e67ff0-20260929.png。
- 終局結果画像を確認：自家34700点・1位、簡単CPUは27200/24700/13400点。
  結果画像：artifacts/friend-300-fixed-6e67ff0-20260929/frames/2026-09-28T15-45-38.697601+00-00.match_result.png。
  これは6e67ff0固定時の結果であり、後続の赤牌・キャッシュ・副露修正の実機結果ではない。

鳴き対象認識の修正後の機能回帰であり、段位戦の勝率評価とは分離する。
対局中は実行経路のコード・設定を変更しない。

## 新規に再現した公開情報キャッシュ汚染

- 15:03:12.890159Zの対戦待機画面を直接public-observationで認識すると、
  存在しないドラ表示牌9p/8pと他家河1mを返す。画像上は待機画面である。
- 15:04:41.719902Zの実対局画像は表示牌W（西）で、同じ画像の直接Hybrid認識も
  doraIndicators=[W]。しかし固定プロセスの判断ログには9p/8pが残る。
- merge_public_observationsは既存列と前方一致しない更新を捨てるため、
  待機画面で誤採用した列を正しい列で置換できない。
- 既知のmatchmaking等は早期回避されるが、この待機画面はunknown分類だった。
  force-autoのunknown許容経路で公開情報走査が走ることをコードで確認。
- 対局中には修正せず、非対局画面からの採用阻止と対局境界での破棄を
  終局後の修正対象とする。今回の戦略判断を正常なドラ入力の検証とは扱わない。
- 東1局の18個のdecision.stateをparseGameState+deterministicAdviceで再計算し、
  表示牌だけ[W]へ変更した対照と比較。1/18判断が変化。
  15:05:19.436810Zでは誤入力7p切り、表示牌訂正のみでは3p切り。
  実行ログも7p切り。これは入力と判断の因果的な差を示すが、和了率や最終順位の
  改善を証明しない。他の認識誤りまで訂正した比較でもない。
- 東2局の最初の2判断は表示牌[1p]となり、局終了時のキャッシュ破棄後は
  東1局の9p/8p列が持ち越されていないことをログで確認。

## 発ポンの実機成功と副露情報の欠落

- 東2局1本場15:08:59.950204Zに左家（north）の発を
  verified_prompt_highlightで確認、15:09:03.634452Zにponクリック。
- reaction_callのconfirmation=hand_and_own_meld_changed、openMelds=1、
  evidenceToClickMs=8719、deadlineMet=true。ポン後の北切りも
  hand_and_own_river_changedで確認。今回の発は左家であり、
  修正対象だった右家の隣接索子による競合の完全な実機再現ではない。
- ポン後15:09:10.198668Zの画像から直接Hybrid公開情報認識を行うと、
  ownMelds=[pon FFF]（confidence 0.98675）を返す。
- しかし15:09:10以降の少なくとも5判断のstateはopenMelds=1、melds=[]。
  cachedPublicStatePatchはownMeldTilesをvisibleTilesとして渡すだけで、
  observation.ownMeldsを型付きmeldsへ渡していないことをコードで確認。
  また単調増加河は鳴かれたFを保持し、少なくとも1牌がrejectedTilesに計上される。
- 副露数の認識・操作成功と、役を評価できる完全な状態入力は別の検証項目。
  終局後は型付き副露と鳴かれた河の整合性も修正・テスト対象とする。

## 守備追加控除の感度分析

- scripts/audit-defense-penalty.mjsで判断ログを読み、他の並べ替え条件を維持して
  比較時の追加危険度控除だけを除去。基礎期待値の放銃控除は維持。
- 実行時点の57判断でローカル選択差は1件、例外0。
  東2局12巡15:09:30.531641Zは現行1m→追加控除なし4s。
  どちらも1シャンテンで、テンパイ維持2p切りには変わらない。
- 型付き発ポンと鳴かれた河の訂正のみでも同じ判断のローカル選択は1mのまま。
  不足している副露入力の修正だけでは、このテンパイ崩しの原因を解消しない。
- 比較はローカル評価の感度分析で、Jevの反実仮想や勝率改善を証明しない。
  node --checkと実ログで実行確認。実対局のコードには未接続。

## 赤牌の現物照合の不一致（独立再現）

- evaluateTileDangerは候補牌をnormalizeTileするが、相手の河には
  discards.includes(tile)を直接適用する。赤牌の表記0pと通常牌5pが一致しない。
- 同じ合法な14枚手牌・リーチ相手について、相手河[5p]では候補5pの危険度0、
  相手河[0p]では危険度0.12とriichi_threatを返すことをdist関数で再現。
- 赤5牌の正規化を現物・筋の照合双方に適用する回帰を終局後に追加する。
  この独立再現だけでは今回の特定打牌への因果効果は未証明。
- scripts/audit-red-rivers.mjsを追加。相手の河だけ正規化したローカル対照を実行。
  前回完走ログ120判断で危険度差51件・選択差14件、例外0。
  今回の途中87判断では危険度差17件・選択差1件、例外0。
  現物と筋の照合を同時に訂正した対照であり、選択差すべてを現物だけの効果とはしない。
  構文チェック・前回実ログでスクリプト実行成功。Jev選択や勝率への効果は未検証。

## 非対局画面採用条件の回帰準備

- キャッシュ汚染を起こした正確な待機フレームを
  artifacts/live/friend-room-public-cache-contamination-20260929.pngへ保存。
- board_metadataはこの画像をunknown/not_gameplay_screenで拒否する。
  当該ケースをtest_board_metadataへ追加し、関連16件成功。
  公開情報走査側が同等の採用条件を持つことはまだ未達。
- 手牌13枚または副露牌面の明るさだけの判定は、盤面確認済み130画像で
  実対局の誤除外0だったが、設定画面を副露ありと判定する反例がある。
  この単独条件を採用せず、既存のmatch分類・盤面確認と整合させる。

## 赤牌の守備照合修正と回帰結果

- evaluateTileDangerの相手河を照合時だけnormalizeTileし、現物・筋の両方で
  赤5と通常5を同じ牌種として比較する。元の河や赤ドラ情報は変更しない。
- 萬・筒・索それぞれについて赤/通常候補と赤/通常河の全組合せ、2・8の筋、
  無関係牌、別の相手には現物でないこと、入力河の保持を回帰テストで確認。
- npm test: 183件成功、npm run test:python: 153件成功、npm run build成功。
- 修正後のaudit-red-riversで前回120判断と今回177判断を再計算。
  明示的に河を正規化した対照との差は、危険度・選択とも0、例外0。
  これは修正した照合の同値性の検証であり、実対局や勝率改善の証明ではない。
- 公開情報キャッシュの非対局画面汚染と型付き副露の欠落は未修正。

## 非同期公開情報キャッシュの非対局走査を拒否

- schedule_public_recognitionで、1920x1080かつclassify_screen(frame, {})が
  matchであることを必須にした。board_metadataと同じ画面採用条件。
  force=Trueでも省略しないため、周期走査・欠損情報の強制再走査に適用される。
- 実際に汚染した友人戦待機画像、設定画像、流局結果画像、破損画像、
  非校正サイズを渡してもワーカー・要求番号・フレームハッシュを作らない回帰を追加。
- 既存の盤面確認済み実画像ではワーカー開始と要求フレーム保存を確認。
  非同期結果の旧generation拒否の既存テストも含めPython全155件成功。
- 同期observe_public_boardの全経路への防御や、今回修正後の300+0実機再検証は
  まだ未実施。型付き副露と鳴かれた河の重複計上も引き続き未修正。

## 型付き自家副露の受け渡し

- cachedPublicStatePatchへ独立推定副露数を渡すよう変更。
  ownMeldsの数、グループの牌数、ownMeldTilesとの一致、4枚上限を満たす
  完全な副露だけmeldsへ渡す。型付き牌はvisibleTilesには重複して渡さない。
- recognitionServerで最後にmelds=[]を上書きしていた経路を修正し、
  キャッシュ由来meldsを状態解析へ渡す。キャッシュ不採用時は引き続き未知扱い。
- 発ポンを型付き状態へ渡してknownTilesの発が3枚になる回帰に加え、
  副露数不一致、2枚だけの部分認識、4枚上限との矛盾では型付き採用しないことを確認。
- ビルド・関連4テスト・TypeScript全184テスト成功。実対局ログの古い河には鳴かれた発が残るため、
  今回修正だけでは当該ログの発ポンを採用できない。河の整合性修正と
  実際の常駐サーバーを通した副露受け渡し検証は引き続き必要。

## 確認済み自家鳴きの河キャッシュ補正

- 戦略承認に用いた確認済みpendingDiscardを保持し、実行結果が
  hand_and_own_meld_changedになった後だけ河キャッシュを補正する。
- 対象席の末尾牌が完全一致するスナップショットのみ、その1枚を除去する。
  他家の同牌・河の途中の同牌・一致しない末尾は変更しない。
- キャッシュgenerationを更新して鳴く前の非同期結果による復活を防ぎ、
  次の公開情報走査を再開できるよう走査間隔・ハッシュをリセットする。
- 発ポン3枚と別家の発1枚が合計4枚となる回帰、元画像観測の不変性、
  席の限定、リーチ保持、旧generation拒否をテスト。Python全156件成功。
- この対応は操作者が確認した自家鳴きに限定。相手同士の鳴き、赤/通常表記の
  不一致、末尾が未認識のケース、鳴かれた牌を別途保持する守備用河履歴は未対応。
  実機300+0の再検証と常駐サーバーまでの統合確認もまだ残る。

## 常駐サーバーの副露受け渡し統合回帰

- recognitionServerを別プロセスで起動し、11枚の画像認識からforce-auto評価まで実行。
  副露数1と完全な発ポンを渡すと、result.state.melds=[pon FFF]、visibleTiles=[]、
  publicCache.applied=true、rejectedTiles=0、decisionありを確認。
- 副露数1に対しownMeldsが空の対照では、型付きmeldsは空のまま、
  見えている発3枚だけがvisibleTilesへ入り、役を捏造しないことを確認。
- 既存の画像から意図的に11枚分の領域を指定したテストであり、
  実対局のコンパクト手牌位置検出の証明ではない。モデルAPIキーなしで実行。
- 常駐サーバー関連2テスト・TypeScript全185テスト・ビルド成功。
  300+0実機再検証は引き続き未実施。

## b73cc2d以降の引き継ぎ再開

- 作業開始時のローカル `main` は `7740425` でクリーンだった。その時点では指定資料2件がローカルに存在しなかったが、最初のpush時に `origin/main` が58コミット進んでいることが判明した。fetch後に本資料と `VALIDATION-698264b-20260929.md` を読み、先行作業を取り込んで重複を整理した。
- 旧operator（プロセスグループ2746632）はログ上 `matchmaking` を繰り返していたため、変更前にSIGINTで正常停止した。CDPの実画面は終了済み段位戦の切断ダイアログで、screencastと実画面が乖離していた。当該ログは勝率評価に使わない。

### 今回の修正

- 起動時ポインタ退避は先行コミット `42daf1f` に既に存在した。共通helperへ切り出し、screencast開始前に呼ばれる順序を回帰テストで固定した。
- 保存済み実画像2枚で実際の7pを6pと読む際、次点が7p、信頼度が約0.70だった。正常な低信頼度フレームを一括拒否しないよう、6p/次点7p/信頼度0.75未満という確認済みの混同だけを `safe=false` にした。誤認画像の拒否と正常画像の採用を実モデル回帰にした。
- 自家副露領域の個別cropが安全でも、合法な面子を構成しない牌列は `ownMeldTiles` に公開しない。副露0を手牌状態で確認済みかつ最新副露領域を完全に空と観測した場合、過去の偽自家副露キャッシュを消す。実副露が確認済みなら保持する。
- `ghost-white-kan-cache-698264b-20260929.jpg` の白カンは相手eastの偽副露だった。相手副露領域を候補0枚まで完全に観測した場合を「空を確認」として伝播し、Pythonの観測マージとTypeScriptの状態変換の両方で過去の未確認副露を消す。欠損領域や解読不能な領域では消さない。
- `remainingTiles=0` では将来和了確率を0、未聴牌からの聴牌確率を0にした。すでに聴牌している状態だけ聴牌確率1を保つ。

### オフライン検証と次の実機確認

- rebase前の変更に対し `npm run build` 成功、TypeScript対象31件成功、`npm test` は166件中161成功・既存fixture不足5件skip・失敗0、`npm run test:python` は152件中114成功・38件skip・失敗0、`git diff --check` 成功。
- 先行58コミットを統合した状態で `npm run build` 成功、`npm test` は189件中184成功・既存fixture不足5件skip・失敗0、`npm run test:python` は159件中121成功・38件skip・失敗0。保存済みghost-white-kan実画像のHybrid回帰も成功。
- 固定コミットをpush後、友人戦・四人半荘・簡単CPU3名・300+0秒、`--action-deadline-ms=300000` で実機回帰する。初回フレーム、公開情報キャッシュ、自家副露・河、残り山0の入力を確認する。CPU友人戦は機能確認であり、段位戦の勝率評価とは分離する。

## 13d0f43の300+0秒実機回帰

### 条件と初回環境不備

- 実行コードはpush済み `13d0f43`。四人半荘、300+0秒、簡単CPU3名、25000点開始、1位必要30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。`layout=config/layout-300-regression.json`、`--action-deadline-ms=300000`、`--force-auto-click-budget-ms=8000`、board-metadata・advance-screens有効。対局中はコード・設定を変更していない。
- 部屋56845の初回起動は最初の打牌前に `safety_stop: No module named 'numpy'` となった。成果物は `artifacts/friend-300-fixed-13d0f43-20260929/`。打牌せず部屋を退出してから、既存の `python/requirements-ocr.txt` を `.runtime/python-auto-venv` へ導入した。`PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python/test_board_metadata.py` は16件成功。この中断は対局結果や機能回帰の成功例に数えない。

### 部屋39481の完走結果

- 設定・待機画面は `artifacts/live/300-fixed-13d0f43-room39481-ready-20260929.jpg`。成果物は `artifacts/friend-300-fixed-13d0f43-retry-20260929/`。開始は2026-09-28T17:10:20Z（日本時間9月29日）。
- 最終結果は自家35100点・1位。CPUは26900/21000/17000点。結果画像は `artifacts/live/300-fixed-13d0f43-room39481-first-place-20260929.jpg`。
- 140判断、反応プロンプト32件、和了操作2件。重複を除いたactionTiming 174件は期限超過0、最大evidenceToClickMs=23690。`safety_stop` 0。手牌変化を検出したretryableなaction abortが1件あり、その操作は送らず後続フレームで継続した。
- 初局の最初の判断は正しい局・座席・25000点4家・残69枚から開始し、待機画面由来の公開情報を持ち越していない。全140判断に偽 `minkan PPPP` はなく、実在した他家の `pon CCC`、`pon WWW`、チーは保持された。
- この半荘では自家鳴きが発生せず、残り山0枚の自家判断も発生しなかった。後者はオフライン境界回帰のみ成功で、実機境界の証拠にはしない。

### 部屋18288の自家鳴き回帰

- 自家鳴きを実機で確認するため、同じ設定・同じ `13d0f43` で追加完走。設定・待機画面は `artifacts/live/300-fixed-13d0f43-room18288-ready-20260929.jpg`、成果物は `artifacts/friend-300-fixed-13d0f43-call-regression-20260929/`。開始は2026-09-29T09:56:25Z。
- 最終結果は自家36100点・2位。CPUは41600/23500/-1200点で、飛びにより東4局4本場で終了。結果画像は `artifacts/live/300-fixed-13d0f43-room18288-second-place-20260929.jpg`。
- 128判断、actionTiming 167件は期限超過0、最大evidenceToClickMs=16995。`safety_stop` 0。手牌同一性不一致によるretryable abort 3件はクリックせず再取得した。
- 東1局09:59:58Z、対面northの東をポン。`confirmation=hand_and_own_meld_changed`、openMelds=1、evidenceToClickMs=9603。次判断は10枚手牌、`melds=[pon EEE]`、`openMelds=1`、鳴き後3m切りを `hand_and_own_river_changed` で確認し、north河末尾の東は消えている。その直後にロン操作も成功した。
- 東4局10:24:19Zにも対面northの9sをポン。evidenceToClickMs=10625。次判断以降6件で `melds=[pon 9s9s9s]` を保持し、north河に鳴かれた9sを残さず、鳴き後F切り以降の自家河を伸長した。次局では自家副露が残留していない。
- `reaction_discard_verified` と `verifiedCallDiscard` は静的public-stateのeast基準座標で記録され、`state.pendingDiscard` はboard metadataで実座席へremapされる。最初の東はログ上west→実座席north、9sはsouth→north。両方の `called_river_reconciled.removedSnapshots=0` はキャッシュが鳴き牌追加前だったためで、直後の公開情報再走査と評価状態では実座席northの河から鳴き牌が除去済み。画像・型付き状態・河・操作結果を合わせると、座席違いによる誤補正ではない。
- 追加戦128判断にも偽 `minkan PPPP` は0。残り山0枚の自家判断は発生しなかった。

### 0.75境界を超えた7p→6p false-safeと修正

- 東4局10:34:38Zのクリック直前同一性確認で、実牌7pを6pと誤認した。confidence=0.775317、runner-up=7p/0.223618、`recognitionSafe=true`。前段判断との牌不一致を別検査が検出したためクリックは中止され、誤打牌には至っていない。反例画像は `artifacts/live/seven-pin-read-six-safe-counterexample-13d0f43-20260929.jpg`。
- 先の既知混同vetoはconfidence<0.75だったため、この反例を通した。保存画像の実モデル再生で同じ値を再現した。正しい6p/次点7pの既存対照はconfidence=0.788003なので、確認済みの間隙だけを使ってvetoをconfidence<0.78へ拡張した。
- 純粋な境界テストで0.775317を拒否、0.788003を許可し、実モデル回帰で新反例を`safe=false`、既存の正しいshimmer対照を`safe=true`と確認した。全6pや全低信頼度認識を拒否する変更ではない。
- 修正後に `npm run build` 成功。対象テスト5件成功。`npm test` は190件中185件成功・既存fixture不足5件skip・失敗0。`npm run test:python` は全159件を実行し、126件成功・33件skip・失敗0（OCR依存を導入したため、修正前よりskipが5件減少）。

### 評価範囲

- 2半荘はCPU友人戦の動作・回帰確認である。1位35100点と2位36100点は、段位戦の勝率改善や短い制限時間での性能を証明しない。段位戦の勝率評価は別サンプルとして継続する。
- `remainingTiles=0` の終端確率修正は単体回帰済みだが、今回の固定コード実機2半荘では該当する自家判断がなく、実機境界は未観測のまま。

## 6af901eの300+0秒追加回帰と鳴き判断の修正

### 部屋18288・3局目の条件と結果

- 実行コードはpush済み `6af901e`。四人半荘、300+0秒、簡単CPU3名、25000点開始、1位必要30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。設定・待機画面は `artifacts/live/300-fixed-6af901e-room18288-ready-20260929.jpg`。
- 実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-fixed-6af901e-sample3-20260929 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中はコード・設定を変更していない。
- 待機画面をmatchmakingと分類したため操作者が開始ボタンを押さず、画面確認後に開始ボタンだけを手動クリックした。対局中の打牌・鳴き・和了操作は操作者が実行した。この待機画面分類は運用上の未解決事項である。
- 自家29000点・2位。CPUは29400/23400/18200点。南4終了時に30000点以上がいなかったため西4局まで延長した。結果画像は `artifacts/live/300-fixed-6af901e-sample3-second-place-20260929.jpg`。
- 219判断、反応プロンプト56件、自家鳴き2件、ロン操作2件。重複を除いたactionTiming 279件は打牌221、反応56、和了2で、期限超過0、最大evidenceToClickMs=38886。`safety_stop` 0。同一性不一致等によるretryableなaction abort 11件はいずれもクリックせず再取得した。

### 状態認識と操作の回帰

- 南1局の白ポンは2→1シャンテンの厳格改善かつ役牌確定、南4局の234mチーは2→1シャンテンでラス目だった。両方とも自家副露を型付きで保持し、鳴かれた牌と自家河の更新に破綻はなかった。
- 7pを6pと読む既知混同を9フレームで `recognitionSafe=false` にした。confidence=0.775317の反例も拒否し、全件で操作を中止したため誤打牌はない。実フレームは `artifacts/live/seven-pin-veto-live-confirmed-6af901e-20260929.jpg`。
- 存在しない白カンは観測せず、実在する他家副露は保持した。`remainingTiles=0` の自家判断は今回も発生せず、終端確率修正の実機境界は未観測のまま。

### 得失点から見た敗因と改善点

- 東1局に確認できた放銃は2000点1回。自家は南1局1本場に3900点増、最終の西4局4本場はリーチ後のロンで18800点から29000点へ回復した。4着で迎えた最終局から2着へ逆転しており、今回の主因を放銃過多とは断定しない。
- 流局時のノーテン支払いは東3局1本場1500、南1局1500、南4局1000、西2局1000の計5000点。西1局・西3局の流局時はテンパイで点数変動がなく、後半は速度が改善した。
- 反応ログでは、ローカルの鳴き評価が承認したのにJevのpassで取り消された例を4件確認した。11:31:25Zの789mチーは3→2、11:48:44Zの345pチーは2→1、11:53:34Zの中ポンは3→2かつ役牌確定、12:01:23Zの8pポンは1→0シャンテンだった。最後の3件は4着時で、ノーテン支払いと合わせて速度不足の具体的な改善候補とした。
- `decideReaction` は先に最良の承認済み鳴きを選んでも、Jevがpassを返すと無条件にpassへ上書きしていた。相手リーチなしで承認済み鳴きがある場合は、Jevのpassまたは不承認鳴きで取り消さず、Jevが別の承認済み鳴きを選んだ場合だけ差し替えるよう修正した。相手リーチ下でローカル鳴きを強制しない既存挙動は維持する。
- Jevがpassを選ぶ合成ケースでも厳格改善・役牌確定のポンを維持する回帰テストを追加。全TypeScriptテストは191件中186件成功・既存fixture不足5件skip・失敗0、TypeScriptビルドも成功した。
- 全Pythonテストの初回実行で、pass確認期限を事前画像判定より先に開始する既存不具合が顕在化した。画像判定時間だけで短い確認期限を使い切り、反応画面から自摸番への遷移を見逃していた。期限開始を事前判定後へ移し、対象テストと全159件（126件成功・33件skip・失敗0）で確認した。変更後の実対局回帰は次の300+0秒CPU友人戦で確認する。

### 評価範囲

- ここまでのCPU友人戦の完走結果は1位35100点、2位36100点、2位29000点。認識・操作の機能回帰としては改善傾向だが、同一CPU条件の3半荘だけであり、段位戦の勝率改善とは扱わない。修正後の300+0秒回帰を終えてから、別サンプルとして銅の間を評価する。

## 6bac195の300+0秒回帰と追加修正

### 部屋18288・4局目の条件と結果

- 実行コードはpush済み `6bac195`。四人半荘、300+0秒、簡単CPU3名、25000点開始、1位必要30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-fixed-6bac195-regression-20260929 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中はコード・設定を変更していない。
- 最終結果は自家16900点・3位。CPUは52900/21100/9100点。結果画像は `artifacts/live/300-fixed-6bac195-room18288-third-place-20260929.png`。201判断、反応プロンプト58件、自家鳴き3件、和了操作2件。期限超過0、最大 `evidenceToClickMs=112540`、`safety_stop` 0。
- 東2局の8mポンはローカル評価が2→1シャンテンで承認し、Jevはpassを返したが、`6bac195` の修正により `pon_8m` を維持した。操作は `hand_and_own_meld_changed` で確認でき、鳴き判断修正の実機回帰になった。
- 東2局と東3局の2回、`remainingTiles=0` の自家判断を実機で観測した。全候補の `winProbability=0`、`tenpaiProbability=0`（未聴牌）であり、残り山0枚の終端確率修正を実機でも確認した。
- pass後にボタン画素差が小さいまま自摸番へ遷移したケースを `confirmation=reaction_to_self_draw`、`buttonPixelDelta=2.424` で確認した。`6bac195` に含めた確認期限開始位置の修正が実対局でも機能した。
- 全判断で存在しない白カンは0。既知の7p→6p反例による誤クリックもなかった。

### 敗因と鳴き後状態の不具合

- 南1局7本場、親リーチに対して3シャンテンから安全度優先で降りたが、8巡目に同程度の候補から8mを切り、親の8000点に7本場分を加えた9800点を放銃した。判断ログの推定放銃率は12.47425%。牌画像と入力は一致しており、今回の最大失点は牌誤認ではなく、完全安全牌が尽きた後の守備選択と結果の分散である。証拠は `artifacts/live/300-fixed-6bac195-south1-7-dealin-20260929.png`。
- 南1局5本場の234sチーは、選択・クリック・手牌および副露領域の変化までは確認できたが、以後 `openMelds=1` に対し `melds=[]` が局終了まで続いた。実画面では234sが存在する一方、公開牌分類は2s/9s/3s、各confidence 0.527/0.391/0.710で `classificationSafe=false` となり、型付き副露へ昇格できなかった。証拠は `artifacts/live/300-fixed-6bac195-own-chi-untyped-20260929.jpg`。
- 東4局3本場の5mチー候補では、公開牌との4枚超過エラー `reaction_tile_count_conflict` を約10秒ごとに10回再評価し、最終的に安全なpassを送るまで112.54秒かかった。誤鳴きや期限超過はなかったが、同じ矛盾に対する再試行上限がないことが原因。証拠は `artifacts/live/300-fixed-6bac195-call-conflict-20260929.png`。

### 修正とオフライン回帰

- 鳴き操作が手牌・自家副露領域の両方の変化で確認できた場合、選択済みactionの鳴き牌と消費牌から型付き自家副露を作り、公開牌キャッシュへ保持する。視覚分類が失敗しても操作で確定した234sを失わず、鳴かれた河末尾の除去とvisible tileの再構築を同時に行う。
- 複数のチー候補が表示された場合、従来の常時左端クリックをやめ、legal actionの順序と選択action IDから対応する選択肢をクリックする。候補数や対応が一致しなければ操作しない。
- `reaction_tile_count_conflict` は20秒まで再取得を許し、それ以上同じ矛盾が続けば認証不能な鳴きを諦めて安全なpassへ進む。その他の一時エラーは従来どおり再試行する。
- `npm test` は191件中186件成功・既存fixture不足5件skip・失敗0。`npm run test:python` は162件中129件成功・33件skip・失敗0。`npm run build` 成功。変更後の300+0秒実機回帰では、型付き自家副露が次判断へ残ることと、永続的な鳴き矛盾が約20秒でpassになることを継続確認する。

### 評価範囲

- CPU友人戦4半荘の順位は1位、2位、2位、3位。今回の3位を含め、機能確認と段位戦勝率は分離する。CPU戦で直近修正の実機回帰を済ませ、勝率改善を追加サンプルで裏づけるまでは銅の間へ進まない。

## 6b6fd2aの300+0秒回帰、1位完走と自風OCR修正

### 部屋18288・5局目の条件と結果

- 実行コードはpush済み `6b6fd2a`。四人半荘、300+0秒、簡単CPU3名、25000点開始、1位必要30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-fixed-6b6fd2a-regression-20260929 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。開始は2026-09-29T13:48:36Z、対局中はコード・設定を変更していない。
- 最終結果は自家61800点・1位。CPUは17500/11500/9200点。結果画像は `artifacts/live/300-fixed-6b6fd2a-first-place-20260929.png`。192判断、反応プロンプト56件、自家鳴き4件、和了操作5件（ロン2・ツモ3）。期限超過0、最大 `evidenceToClickMs=83708`、`safety_stop` 0。
- CPU友人戦5半荘の順位は1位、2位、2位、3位、1位で、平均順位1.8、連対率80%、1位率40%、4位0。これは300+0秒CPU戦の機能回帰サンプルであり、段位戦の勝率改善とは分離する。

### 型付き副露、河、競合上限の実機回帰

- 東4局の234mチー、南2局1本場の赤5sを含む567sチー、南2局3本場の発ポン、南3局5本場の9pポンを実行。すべて `called_river_reconciled` にconfidence 1.0の型付き副露として保存され、後続判断で `openMelds=1` と正しい `melds` を局末まで保持した。新局では副露を消去した。赤5sは捨て牌表記0sから副露牌5sへ正規化された。
- 567sチー後は後続打牌を行い、その局にロンして27500点から39400点へ増加した。発ポン後も後続打牌とツモ和了を行い、58000点から62800点へ増加した。鳴き後の自家副露・河・判断・和了操作の一連を確認した。
- `reaction_tile_count_conflict` の永続例は2件。安全passまで36636msと23433msで、前回112540msから短縮した。後者は `persistent_tile_count_conflict_safe_pass elapsedMs=23433` を明示的に記録した。20秒を超えるのは再取得1周期分の処理時間で、誤鳴き・期限超過はなかった。
- `remainingTiles=0` の自家判断を東4局と南1局1本場で観測し、全候補の `winProbability=0`、未聴牌の `tenpaiProbability=0` を再確認した。全192判断で存在しない白カンは0。通常判断の `recognition.safe` は全件falseで、既知の誤認なのにsafe=trueとなる反例は再発しなかった。クリック前の手牌同一性確認3件はすべて一致し、持ち上がった手牌による誤クリックもなかった。

### 83.708秒の状態認識遅延の原因と修正

- 東2局の1打で `seat_or_round_not_verified` を10回繰り返し、検出からクリックまで83708msかかった。保存画像は東2局・自家東・残41枚を安定表示し、手牌・公開情報も変化していない。直接OCRで局表示 `東2局` はconfidence 0.99909、自風 `東` は0.96970だった。全トークン共通の0.98閾値を自風だけが下回ったことが原因で、牌認識・戦略判断・操作の遅延ではない。
- 共通閾値を下げず、通常検出で自風が0.98未満のときだけ校正済み自風領域を単文字OCRする。実フレームでは `東` をconfidence 0.98736で再取得し、局・座席・4家点数・供託・本場・残り山と既存の点数保存則をすべて通して検証できる。
- 反例画像を `artifacts/live/board-seat-wind-low-confidence-20260929.jpg` に保存し、固定領域フォールバックの実モデル回帰を追加。`python/test_board_metadata.py` は17件成功。`npm test` は191件中186件成功・既存fixture不足5件skip・失敗0、`npm run test:python` は163件中130件成功・33件skip・失敗0、`npm run build` 成功。

### 評価範囲と次段階

- 直近修正後の完走・1位、5和了、型付きチー/ポン4件、残り山0、競合上限を実機で確認したため、CPU機能回帰の条件は満たした。CPU戦の成績だけを段位戦勝率の証明にはしない。
- 自風OCR修正をオフライン回帰・コミット・push後、次の実対局は銅の間を独立サンプルとして評価する。段位戦では結果、使用コミット、時間設定、放銃・ノーテン・認識/判断/操作ログを記録し、負けが続けば同じ手順で原因を裏づけてから練習・修正する。

## 2026-09-30 銅の間・四人南 第1標本（短時間設定の分離評価）

- 使用コードはpush済み `ef29b4e`。銅の間の四人南、段位戦標準時間で、操作者は `--action-deadline-ms=300000`、`--force-auto-click-budget-ms=8000`、`--board-metadata`、`--advance-screens` を明示した。成果物は `artifacts/ranked-bronze-south-ef29b4e-sample1-20260930/`。開始は2026-09-29T15:20Z、終局は16:11Z。CPU友人戦300+0の機能回帰とは別標本である。
- 最終結果は自家12900点の3位、段位点-17。1位47600、2位42400、4位-2900で、4位飛びにより南3局3本場で終了した。順位結果画面は `frames/2026-09-29T16-11-30.544375+00-00.match_result.png`。
- ただし、この順位を純粋な戦術評価には使えない。104打の `evidenceToClickMs` は最小5612、中央値6811、平均7087、最大22922msだった。全打が設定上の300000ms deadline内ではあるが、段位戦の画面内持ち時間には遅い。次の自家河がちょうど1枚伸びた63組を照合すると、選択牌と実河牌の一致32、不一致31だった。不一致は「少なくとも31打で時間切れツモ切りまたは別操作が起きた」という下限であり、一致側にも偶然同じ牌をツモ切った例を含み得る。
- 主因は、300+0 CPU回帰用に広げた8000msクリック予算を段位戦にも流用したことだった。短時間用の既定値は2600msであり、次の段位戦は `--force-auto-click-budget-ms=2600` を明示して分離評価する。
- 東4局1本場では自家21500点から15400点へ6100点減った。15:41:56の評価フレームでツモは3筒、操作者の選択は西、クリック証拠は西の座標だったが、15:42:04の事後画面では西が手牌に残り、3筒が自家河へ出ている。直後に親 `jntmwks` が3筒ロン（5800点+1本場300点）。画像だけでなく、選択ログ、クリック座標、事後手牌・河、局結果、次局点数を照合して、時間切れツモ切りによる放銃と判断した。
- 反応見送り後の確認が2回 `pass click was not confirmed by its button region changing` で停止し、同じ固定コードを再起動した。15:22:28/15:34:32のクリック後、同じ固定位置へ次の反応ボタンが現れると領域差分だけでは進行を確認できなかった。再起動中の自動ツモ切りを含むため、本標本は操作障害の影響ありと明記する。操作者の `away_resumed` は計3回。
- 牌同一性の独立再確認は7回あり、`recognitionSafe=true` でも画素差で2回中止、牌不一致（7筒→6筒）を伴う `recognitionSafe=false` で1回中止、手牌0枚認識で2回中止した。誤認識時の操作防止は働いたが、通常打牌の事後確認は「手牌と河が変化した」ことしか見ず、意図牌と実河牌の不一致を成功扱いして高速手牌キャッシュを誤更新する欠陥が判明した。
- 鳴きは東2局1本場の白ポン1回で、`hand_and_own_meld_changed` を確認した。公開キャッシュに存在しない白カンは観測されず、自分の白ポンは型付き副露として残った。南1局の手牌同一性再確認など、`recognition.safe=true` でも画面変化を別ゲートで中止する例も継続確認した。

## 2026-09-30 段位戦で判明した操作・キャッシュ障害の修正

- 打牌後に、選択牌、打牌前の自河、`evidenceToClickMs` を保留するようにした。非同期公開情報で自河が1枚伸びた時に実牌を照合し、一致するまで高速手牌キャッシュを再利用しない。不一致なら `own_discard_mismatch` を記録してキャッシュを破棄し、次巡は手牌全体を再認識する。赤5と通常5は同じ物理牌として比較する。
- 見送り確認では、ボタン領域が同じでも、いずれかの河領域が独立に進行した場合を `reaction_river_advanced` として受理する。これは元の反応がクリックまたは時間切れで終了した証拠で、同位置に次の見送りボタンが現れた際の誤停止を防ぐ。
- 追加テストは、同位置ボタン+河進行、意図牌/実河牌不一致時のキャッシュ破棄、一致時のキャッシュ保持を含む。Pythonは166件成功・33件skip、TypeScriptは191件中186件成功・5件skip、buildと`git diff --check`も成功した。
- この修正後の実対局回帰は、まず友人戦300+0・`--action-deadline-ms=300000`で実施する。その後の銅の間は短時間用2600msクリック予算を明示し、意図牌/実河牌の一致率、`own_discard_mismatch`、見送り確認、最終順位を独立評価する。

## 659733dの300+0秒回帰（中断、結果評価から除外）

- 使用コードはpush済み `659733d`。友人戦部屋12981、四人半荘、簡単CPU3名、300+0秒、25000点開始、1位必要30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を開始前画面で確認した。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-fixed-659733d-regression-20260930 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` であり、対局中はコード・設定を変更していない。
- 東1〜南2局まで少なくとも103判断を保存したが、南3局相当の打牌確認（`2026-09-29T17-11-23.148356+00-00.post-discard.png`）の後に操作者とCDPブラウザの両方が終了していた。成果物には結果画面がなく、終了原因をアーティファクトから特定できない。このため順位・点数・勝率・CPU回帰の成功/失敗には数えない。
- 捨て牌後の独立公開情報照合は83回成功した。`own_discard_mismatch` は2回（期待5s→観測8s、期待2m→観測1m）あり、いずれも高速手牌キャッシュを破棄して次巡を全手牌再認識した。河が一度に複数巡進んだ1回も `own_discard_reconciliation_failed` としてキャッシュを破棄した。誤った操作成功扱いを継続しないことの実機証拠である。
- 東3局の1pポンと南1局の789sチーは、いずれも `called_river_reconciled` とconfidence 1.0の型付き副露で確認された。後続の開いた手は10枚手牌、対応副露、河の更新として認識・打牌を継続した。
- 残り山0枚の自家判断を1回観測し、候補の `winProbability=0`、未聴牌の `tenpaiProbability=0` だった。`safety_stop`、`reaction_river_advanced`、存在しない白カンはいずれも0件。なお、最長の `evidenceToClickMs=110615` は複数の相手巡をまたぐ既存の期限開始記録を含むため、操作遅延の証拠には使わない。
- この中断後、ブラウザを再起動しようとしたところ、実行環境に `libnspr4.so` がないためPlaywright Chromiumを起動できなかった。これはリポジトリのコード変更ではなくOS依存関係の欠落であり、追加の実機回帰と銅の間の短時間2600ms評価はブラウザ環境の復旧後に再開する。

## 1798d70の300+0秒完走回帰と7p/6p境界修正

### 部屋97243・条件と結果

- 実行コードはpush済み `1798d70`。友人戦部屋97243、四人半荘、簡単CPU3名、300+0秒、25000点開始、1位必要30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を開始前画面 `artifacts/live/300-fixed-1798d70-room97243-ready-20260930.png` で確認した。
- 実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-fixed-1798d70-regression-20260930 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。開始は2026-09-30T11:36:32Z、対局中にコード・設定を変更していない。
- 最終結果は自家19000点・3位。CPUは34500/27800/18700点。確定画面は `artifacts/friend-300-fixed-1798d70-regression-20260930/frames/2026-09-30T12-27-39.843349+00-00.match_result.png`。CPU友人戦の動作・回帰結果であり、銅の間の勝率評価には含めない。

### 操作・状態照合の結果

- 154打牌判断、53反応プロンプト、2自家鳴きを記録した。`safety_stop` 0、期限超過0。打牌・反応のすべての記録済みactionTimingは `deadlineMs=300000` を満たした。
- `own_discard_reconciled` は126回、`called_river_reconciled` は2回。南4局の2sポン後には、10枚の副露後手牌、`melds=[pon 2s2s2s]`、`openMelds=1`、縮小手牌領域ゲート、および後続自河の伸長を連続して確認した。鳴き後の自分の副露・河整合性は実対局で再確認できた。
- 公開情報の白カンは発生せず、`minkan` の誤登録も観測されなかった。残り山は南2局で2枚まで到達したが、今回は残り0枚の自家判断はなかった（既存の実機・単体回帰結果を維持）。
- 意図牌と実河の差異は今回も1回（期待1p、観測9p）検出し、`own_discard_mismatch` として高速キャッシュを破棄した。複数牌進行の `own_discard_reconciliation_failed` も1回あり、同様にキャッシュを再利用しなかった。結果画面だけでなく、選択・クリック・河照合ログを使って扱った。

### false-safeの再発と修正

- 2026-09-30T11:54:21Zの閉じた手牌同一性確認で、期待7pを6pと読んだにもかかわらず `recognitionSafe=true` だった。confidence=0.7803、観測数14、手牌順序の不一致は検出され、`action_aborted` となったため誤クリックはない。
- 原因は既知の6p/7p vetoが `confidence < 0.78` で、今回の0.7803をわずかに通していたこと。確認済みの正しい6p・次点7p対照は0.788003なので、`confidence < 0.788`へ拡張し、0.7803を拒否・0.788003を許可する単体回帰を追加した。
- 修正後の `npm test` は191件中186件成功・5件skip・失敗0、`npm run build` 成功、`npm run test:python` は166件実行・133件成功・33件skip・失敗0。次の300+0秒CPU友人戦で、修正済み境界を実機回帰する。

### 敗因の扱いと次段階

- 今回の3位はCPU戦1半荘だけで戦術的な敗因を断定しない。副露・河・認識保護は動作した一方、意図牌不一致1回とfalse-safe境界の再発を具体的な改善対象として修正した。
- 修正の実機回帰を完走してから、銅の間を独立評価する。その際は段位戦標準時間に合わせて `--action-deadline-ms=300000 --force-auto-click-budget-ms=2600` を明示し、CPU戦結果と混在させない。

## 3141509の300+0秒CPU回帰（完走・1位）

- 使用コードはpush済み `3141509`。友人戦部屋97243、四人南、簡単CPU3名、300+0秒、25000点開始、1位必要30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。開始前設定画面は `artifacts/live/300-fixed-3141509-preflight-20260930.png`。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-fixed-3141509-regression-20260930 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。開始は2026-09-30T12:32:31Zで、対局中にコード・設定を変更していない。
- 最終結果は自家34000点・1位、CPUは32400/17400/16200点。確定画面は `artifacts/friend-300-fixed-3141509-regression-20260930/frames/2026-09-30T13-38-25.637160+00-00.match_result.png`。これは300+0秒CPU友人戦の機能・回帰結果であり、銅の間の段位戦勝率評価とは分離する。
- 214判断、51反応プロンプト、7自家鳴き、ロン2回を記録した。全214件で `deadlineMs=300000`、期限超過0、最長 `evidenceToClickMs=31075`、`safety_stop` 0。自河は188回照合して追従し、意図牌不一致5回ではキャッシュを再利用しなかった。鳴きは7回すべて `called_river_reconciled`（失敗0）となり、南4局の東ポンでは `openMelds=1`、10枚の副露後手牌、型付き `pon EEE`、後続の河更新を連続確認した。
- 未解決項目の実機照合では、存在しない白カン・minkanは0件。残り山0枚の自家判断は2回あり、いずれも `winProbability=0`、`tenpaiProbability=0`。持ち上がりを含む手牌同一性照合は15回で、13回一致、2回はクリック前に `action_aborted` となり誤操作はなかった。
- ただし13:03:06Zに期待3p・独立再認識Pという不一致で `recognitionSafe=true` が記録された。直前フレームの再実行ではPがconfidence 0.9989であり、独立照合フレームとの差が牌誤認か画面状態遷移かを現ログだけでは分離できない。既知の7p→6pとは異なり、一般化したvetoを追加する根拠は不足しているため、safeフラグだけで操作を許可していない既存の独立同一性ゲートを維持し、このフレーム対を次の認識調査用の反例として保留する。
- CPU完走標本は既存の1位・2位・2位・3位・1位・3位に今回の1位を加えて7件、平均順位1.86、連対率約71%、1位率約43%となった。CPU難易度「簡単」の小標本であり段位戦の勝率改善証明ではないが、最新の認識・副露・残り山保護を完走回帰で確認できた。次の銅の間標本は別成果物で `--action-deadline-ms=300000 --force-auto-click-budget-ms=2600` を明示する。

## 2026-09-30 銅の間への挑戦可否

- `84230ae`でCPU回帰後、ロビーから銅の間を選択した。画面は「現在の段位では入場不可。適した部屋に参加しましょう。」と表示して入場を拒否した。証拠は `artifacts/live/bronze-84230ae-bronze-menu-20260930.png`。
- よって銅の間の段位戦は開始しておらず、対局設定・操作プロセス・対局結果は存在しない。`--action-deadline-ms=300000 --force-auto-click-budget-ms=2600` を設定した実行は行っていない。このアカウントが銅の間の参加条件を満たすまで、CPU友人戦の機能回帰と段位戦評価は引き続き分離する。

## 84230aeの300+0秒CPU回帰と副露後手牌の誤認修正

### 部屋38420・条件と結果

- 使用コードはpush済み `84230ae`。友人戦部屋38420、四人南、簡単CPU3名、300+0秒、25000点開始、1位必要30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を開始前画面 `artifacts/live/300-84230ae-room38420-ready-20260930.png` で確認した。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-fixed-84230ae-regression-20260930 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。開始は2026-09-30T13:49:44Zで、対局中はコード・設定を変更していない。
- 最終結果は自家45900点・1位、CPUは27800/27100/-800点。確定画面は `artifacts/friend-300-fixed-84230ae-regression-20260930/frames/2026-09-30T14-16-35.603391+00-00.match_result.png`。CPU友人戦の機能・回帰結果であり、銅の間の段位戦勝率には含めない。
- 89判断、反応プロンプト51件、自家鳴き1件。重複を除いた107件の actionTiming はすべて `deadlineMs=300000`、期限超過0、最大 `evidenceToClickMs=19094`、`safety_stop` 0。存在しない白のカン／`minkan` は0、残り山0枚の自家判断は0件だった。

### 照合結果と原因

- 東2局で西家の東をポンし、`confirmation=hand_and_own_meld_changed`、`called_river_reconciled`、型付き `pon EEE`、`openMelds=1`、副露後10枚手牌を確認した。従って鳴き後の副露・河の更新自体は成立していた。
- ただし同局の副露後に `own_discard_mismatch` を4件検出した（期待2m→実河8mが2件、期待5s→8s、期待5s→6s）。河キャッシュを破棄したため不整合状態を次巡へ持ち越してはいないが、画像・判断・クリック・河を照合すると実際に意図外の牌を切っていた。
- 反例フレーム `frames/2026-09-30T13-55-24.962822+00-00.jpg` は実牌が `3m 4m 7m 8m 8m 9m 2p 2p 0p 6p 6p`。bright-component動的提案は上端11pxを除いた `y=937,height=134` の矩形を返し、raw template認識は `5m 4m 7m 2m 2m 9m ...` と崩れ、4番目の2mを選んで8mの位置をクリックした。したがって敗因候補は河照合の遅れではなく、副露後に検出器がトリミングした手牌cropと通常テンプレートの不整合である。
- 同一フレームを校正済み矩形で再認識すると上記11枚すべてが一致した。特に副露後の引き牌は従来の `x=1201`（閉じた手の隙間を残す座標）ではなく、通常列の次slot `x=1171,width=93` にあることを画像で確認した。
- 14:10:35Zには期待7p2枚を6p2枚と読む独立同一性確認が再発したが、confidence=0.69989、`recognitionSafe=false` で `action_aborted` となりクリックしていない。`3141509` の0.788境界vetoが実機でfalse-safeを遮断した証拠である。

### 修正と回帰

- 確定済みの副露数がある場合、認識サーバーはbright-component提案を採用せず、校正済みの副露後矩形を使うよう変更した。Python操作者の引き牌監視・比較領域・クリック幾何も同一の「副露後の最初の通常slot」を使う。これにより認識とクリック座標の出所を一致させた。
- 実フレームを使う回帰で、校正後の11枚が完全一致することを追加した。`npm run build`、`test/handLayoutProposal.test.ts`（9成功・4 fixture skip）、`python/test_auto_operator.py`（101成功・33 skip）に加え、全 `npm test` と全 `npm run test:python`（134実行、101成功・33 skip）を通過した。
- CPU完走標本は8件となり、順位は1位・2位・2位・3位・1位・3位・1位・1位、平均順位1.75、連対率75%、1位率50%、4位0。ただし「簡単」CPUの小標本であり、銅の間の勝率改善の根拠にはしない。銅の間はアカウントの入場拒否が継続しているため、条件を満たした後に `--action-deadline-ms=300000 --force-auto-click-budget-ms=2600` で別評価する。

## f9d3665の300+0秒副露後回帰（中断・結果評価から除外）

- 使用コードはpush済み `f9d3665`。友人戦部屋38420、四人南、簡単CPU3名、300+0秒、開始25000点、1位必要30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を開始前画面 `artifacts/live/300-f9d3665-lobby-20260930.png` で確認した。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-fixed-f9d3665-regression-20260930 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。開始は2026-09-30T14:31:03Zで、対局中にコード・設定を変更していない。
- 東1局・全員25000点・残67枚から開始した。自家鳴き1回は `called_river_reconciled` と型付き副露で確認され、その後の自河照合2回は一致した。`own_discard_mismatch`、`safety_stop`、`action_aborted` はいずれも0件であり、修正対象だった副露後の意図外打牌は中断まで再発しなかった。
- ただし14:50:29Zを最後に、操作者とCDPブラウザがともに消滅した。終了直前ログには `rearmed`、`opponent_turn_confirmed`、公開情報更新だけがあり、例外・安全停止・結果画面はない。CDPへの再接続は `ECONNREFUSED 127.0.0.1:9222`。成果物に `match_result` は存在しないため、順位・点数・CPU回帰成功/失敗・勝率には数えない。
- 副露後の実画面は `artifacts/live/300-f9d3665-stall-20260930.png`。画面だけで停止原因を断定せず、操作ログとの照合からはブラウザ外部終了までしか確定できない。再開時はブラウザの生存を先に確認し、同一コミット・同一300+0条件で完走回帰をやり直す。

## a6b8506の300+0秒CPU回帰（完走・1位、次の調査対象あり）

### 部屋20071・条件と結果

- 使用コードは `a6b8506`。友人戦部屋20071、四人半荘、簡単CPU3名、300+0秒、開始25000点、1位必要30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を、終局後の待機画面と実行ログで再確認した。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-fixed-a6b8506-room20071-20261001 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中にコード・設定は変更していない。
- 最終結果は自家54600点・1位、CPUは26000/11500/7900点。結果画面は `artifacts/friend-300-fixed-a6b8506-room20071-20261001/frames/2026-09-30T23-36-24.081877+00-00.match_result.png`。これはCPU友人戦の機能・回帰結果であり、段位戦勝率評価には含めない。
- 116打牌判断、32反応プロンプト、4自家鳴き、3ロン操作を保存した。116件すべての記録済み打牌actionTimingで `deadlineMs=300000` と `deadlineMet=true`。副露は4件すべて `called_river_reconciled` となり、チー・ポン後の `open_hand_geometry_gate`、自家手番、後続打牌・河更新を実機で確認した。

### 証拠と未解決事項

- 初回の反応見送りで `pass button changed during pre-click stability check` により操作者が停止した。対局は継続していたため、同一コミット・同一コマンド・同一300000ms deadlineで操作者だけを再起動し、以後は完走した。これは結果とは分離して停止事象として保持する。
- `own_discard_mismatch` は16件、`own_discard_reconciliation_failed` は2件、`action_aborted` は3件だった。不一致では既存の安全策どおり高速手牌キャッシュを破棄し、後続の全手牌再認識・河照合へ復帰した。今回のログだけでは、公開牌認識の遅延/誤認識と意図外クリックを区別できないため、画像だけで意図外打牌と断定しない。選択・クリック・次フレームの河・手牌比較を使う再現テストが未完了である。
- 南3局のロン操作では、反応直前に自席下部の赤いロンボタンが表示され、`action_click_sent`、ボタン消失、結果画面が連続している。終局画面は自家54600点・1位である。一方、現行の `reaction_win` は「ボタンが消えた」までしか結果として記録せず、和了者や点数を構造化していない。座席方位の点数配列は自家点と同一視できないため、今後は結果画面または牌譜から帰属を構造化して、操作成功と対局結果を混同しない。
- 存在しない白のカン／`minkan` は今回も0件。残り山0枚の自家判断は今回発生しなかったため、既存の0枚時確率ゼロ回帰を維持し、別局面で継続確認する。

## ca569deの300+0秒CPU回帰（完走・3位、同期不一致を継続調査）

- 使用コードは `ca569de`。友人戦部屋20071、四人半荘、簡単CPU3名、300+0秒、開始25000点、1位必要30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効で実施した。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-fixed-ca569de-room20071-20261001 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中にコード・設定は変更していない。
- 最終結果は自家「テストjev」18300点・3位、CPUは42800/21200/17700点。結果画面は `artifacts/friend-300-fixed-ca569de-room20071-20261001/frames/2026-10-01T00-38-05.655748+00-00.match_result.png`。これはCPU友人戦の機能・回帰結果であり、段位戦の勝率評価には含めない。
- 191打牌判断、46反応プロンプト、5自家鳴き、1ロン操作を保存した。全191件で `deadlineMs=300000`、期限超過0、`safety_stop` 0、`reaction_call_unconfirmed` 0。鳴きは5件すべて `called_river_reconciled` となり、チー・ポン後の副露手牌ジオメトリ、自家手番、後続河更新まで実機で確認した。存在しない白のカン／`minkan` は0件だった。
- 19件の `own_discard_mismatch`、2件の認識再試行、2件の手牌変化による安全中止があった。全て後続の再認識または河照合へ復帰し、クリック期限違反はない。ただし不一致ログは期待牌と観測末尾牌だけで、評価基準河や観測河全体を保持していなかったため、誤クリックと公開認識の時系列ずれをこの結果だけで区別できない。今回の3位の戦術的敗因を画像だけで断定しない。
- 終局後に `own_discard_mismatch` へ `before`、`observed`、`capturedAt` を追加した。安全側のキャッシュ破棄は維持する。次の300+0秒回帰でこの証拠を取り、河認識・状態認識・判断・クリックを同一事例で照合してから、一般化した同期修正を判断する。

## ed844f7の300+0秒CPU回帰（安全停止・結果評価から除外）

- 使用コードは `ed844f7`。友人戦部屋20071、四人半荘、簡単CPU3名、300+0秒、開始25000点、1位必要30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効で実施した。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-fixed-ed844f7-room20071-20261001 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中はコード・設定を変更していない。
- 東4局で盤面メタデータが `scores_and_riichi_sticks_total_mismatch` を継続して返し、通常打牌の `recognition_retry` と反応の `reaction_call_policy_deferred` が反復した。5秒反応期限も `reaction_pass_deferred` となり、時間切れ後の `away_resumed` を経ても再発した。操作者は異常な安全停止として終了した。離席後に表示された自家37100点・2位、CPU44800/11600/6500点の画面（`frames/2026-10-01T01-45-00+00-00.match_result.after_away.png`）は東4局後の一時順位表示であり、最終結果ではない。自動ツモ切りを含むため順位・CPU回帰成績・段位戦評価には含めない。
- 同一失敗フレーム `frames/2026-10-01T01-37-41.252528+00-00.jpg` を直接再実行すると、全盤面OCRは対面点数を高信頼度の反転値 `0086` と読んだが、180度補正クロップは高信頼度で正しい `9800` を返した。修正後は南家44400、西家18900、北家9800、東家23900、供託3本、場供3、残39枚として保存則を満たし `verified=true` となる。保存則や信頼度閾値は緩めていない。
- 副露後には `called_river_reconciled` と後続の6筒照合成功があった。一方、期待1萬に対して既存の6筒を河末尾として再読んだ事例、期待白に対して既存の7索を再読んだ事例を含む単一追加の `own_discard_mismatch` が観測された。画像単独で誤クリックと断定せず、河OCRの単発追加を2回一致まで保留する修正を追加した。これにより単発誤認識は公開状態・安全評価・残り牌計算に採用されない。
- 修正後の `python -m unittest test_auto_operator.py test_board_metadata.py` は153件成功・33件skip、失敗0。次の友人戦300+0秒回帰で、対面スコア補正、単発河追加の保留、鳴き後の副露・河整合性を完走確認する。CPU友人戦の結果は段位戦の勝率評価とは引き続き分離する。

## 76819beの300+0秒CPU回帰（無効：確認待ちが自動打牌まで継続）

- 友人戦部屋55723。四人半荘・300+0秒・簡単CPU3人、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を部屋画面で確認した。実行は `76819be`、`layout=config/layout-300-regression.json`、`--action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens`。設定画像は `artifacts/friend-300-fixed-76819be-room55723-20261002/preflight-started.png` と部屋画面、ログ・フレームは同成果物に保存した。
- 初回打牌は期待2sに対し公開河が4sとして2回確認され、`own_discard_mismatch` が安全側で高速手牌キャッシュを破棄した。画像単独では誤クリックと河OCR誤認を区別しない。
- 次の期待5sでは公開河候補がない状態でも確認待ちになった。300秒後、ゲーム側の自動打牌後に河が `[4s,5p]` と観測され、`own_discard_mismatch expected=5s actual=5p` となった。ログの `own_discard_reconciliation_wait`、`public_own_river_append_confirmed`、画面・クリック確認を照合し、候補なしのpending全体を保留した実装が自動打牌を待つ停止不具合と確定した。
- 操作者を停止して部屋を退出した。最終順位・点数・勝率には含めず、段位戦評価にも使わない。後続 `1e9017d` で、実際の河候補がある場合だけ次手番を保留し、候補なしの偽確認では待機しないよう修正した。関連Python 153件成功・33件skip。最新修正の完走300+0秒回帰は未実施。

## 1e9017dの300+0秒CPU回帰（無効：結果画面後の停止漏れ）

- 友人戦部屋78780。四人半荘・300+0秒・簡単CPU3人、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を部屋画面で確認した。実行は `1e9017d`、`layout=config/layout-300-regression.json`、`--action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。成果物は `artifacts/friend-300-fixed-1e9017d-room78780-20261002` に保存した。対局中にコード・設定は変更していない。
- 操作ログには04:33:15Zの `screen_advanced state=match_result confidence=1.0` がある一方、`match_completed_stop` は記録されなかった。その直後に結果画面を進めて `matchmaking` と認識し、約10,499回ポーリングを継続した。最終画面の「長時間無操作のため、接続が切断されました。」とログを照合し、対局自体の停止ではなく結果画面後の操作者停止漏れと確定した。
- 東2局の反復ではなく、局ラベルの再登場を含む213件の判断（east_2=93）だった。反応見送り58件は57件が `pass` のみで確認・期限内、打牌も概ね6--10秒で `deadlineMet=true` であり、300秒の操作待ちを敗因とはしない。終盤には副露後を含む自己河不一致が10件まで増えたため、画像だけで誤クリックと断定せず、公開河OCR／副露状態キャッシュ汚染の候補として扱った。
- この試行は切断後に手動停止しており、最終順位・点数・CPU回帰成績・段位戦勝率には含めない。後続 `5a4fa8b` で、force-autoかつ非rankedの友人戦は `match_result` を観測した時点で画面遷移前に停止するよう修正した。また `own_discard_mismatch` 時は誤認された自己河末尾を公開キャッシュから隔離し、danger／残存牌推定へ流用しない。Python関連単体テストを追加し、`python -m unittest test_auto_operator.py test_board_metadata.py` の完走を確認した。改修版の300+0秒CPU完走回帰は、雀魂の専用セッションが利用可能になってから実施する。

## fb0de0aの銅の間・四人東（無効：期限超過と終局後遷移漏れ）

- 使用コードは `fb0de0a`。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/ranked-fb0de0a-recovery-20261002 --ranked-loop --force-auto-click-budget-ms=2600 --board-metadata --no-dashboard`。300+0秒CPU友人戦の回帰ではなく、段位戦用の短時間設定として分離して記録する。開始時には既存の銅の間・四人東対局が東3局で離席自動ツモ切り画面になっており、操作者が未実行であることを確認してから再開・復旧した。
- 東3局では自家19500点・残21枚から、チー候補を戦略上パスと判定した。一方、反応評価は `detectionToDecisionMs=13783--14674`、通常打牌は `5440--6006`msなど、5秒期限を超えて `action_deadline_expired`／`action_aborted` となった。東4局でも同種の安全中止が継続し、離席復帰を2回記録した。盤面画像・状態メタデータ・判断・操作ログを照合すると、牌の誤クリックではなく、盤面認識・評価のレイテンシが段位戦期限を越えたことが直接原因である。
- 終局画面は自家「テストjev」10200点・4位（-29pt）、他家42900/29000/17900点。証拠は `artifacts/ranked-fb0de0a-recovery-20261002/frames/2026-10-02T07-42-26.438849+00-00.match_result.png`。自動打牌を伴うため、この順位は勝率改善の有効標本に含めない。
- `match_result`を07:42:26Zに観測して結果を添付・画面遷移した後、操作者は検証済みの段位画面を経ずに`matchmaking`として約3時間ポーリングを続け、長時間無操作による接続切断モーダルへ至った。終局画面、`match_result`ログ、後続の`screen_state_bypassed`、切断モーダルを照合して遷移認識漏れと確定した。操作者を停止した。
- 後続修正では、ranked-loopが結果画面を観測した後に、検証済みのlobby/ranked_menu/ranked_roomを経ず`matchmaking`へ移った場合は安全停止する。新規起動時の正当な予約待ちは維持する。関連単体テスト（`test_auto_operator.py` 140成功・33 skip、`test_board_metadata.py` 17成功）を通過した。修正後は先に300+0秒CPU友人戦を完走回帰し、段位戦評価と混同しない。

## a9ac400の300+0秒CPU回帰（無効：雀魂タブの置換）

- 友人戦部屋65400。四人南・300+0秒・簡単CPU3人、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を部屋画面 `artifacts/live/300-a9ac400-room65400-ready-20261002.png` で確認した。使用コードはpush済み `a9ac400`。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-a9ac400-room65400-20261002 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。開始後はコード・設定を変更していない。
- 東1局・全員25000点・残66枚から始まり、少なくとも10判断を記録した。各記録済み打牌は `deadlineMs=300000` と `deadlineMet=true` で、期限超過、`safety_stop`、`action_aborted`、`own_discard_mismatch` はいずれも0件だった。自河は `public_own_river_append_confirmed` と `own_discard_reconciled` で追従した。チー候補は河の提示フレームを検証できなかったため `reaction_call_policy_rejected` とし、passを選んだ。
- 11:01:29Zに操作者の画面取得が期待1920x1080から1920x733へ変化し、`screencast_frame_rejected` を記録した。CDPの唯一のタブは雀魂ではなく `Ticket Observatory` で、後続フレーム `frames/2026-10-02T11-02-48.351179+00-00.png` は黒画面、ログは `screen_state_bypassed state=unknown` と `open_hand_geometry_gate` の反復だけになった。画像、CDPタブ、操作ログを照合して、手牌認識・判断・クリックの失敗ではなく、雀魂タブが置換されて操作者が対局画面を失ったことまでを確定した。
- 11:03:02Zに操作者を停止した。`match_result` はなく、終局順位・点数・CPU回帰成績・段位戦勝率には含めない。次の修正では、許容されない画面寸法又は雀魂以外のページが連続したとき、未知画面を無限反復せず明示的な安全停止にする。その単体テスト後、雀魂専用タブが維持される環境で同一300+0秒CPU回帰をやり直す。

## f1d8571の300+0秒CPU回帰（無効：早期終局経路の停止漏れ）

- 友人戦部屋57225。四人南・300+0秒・簡単CPU3人、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を開始前画面 `artifacts/live/f1d8571-room57225-ready-20261002.png` で確認した。使用コードはpush済み `f1d8571`。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-f1d8571-room57225-20261002 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中にコード・設定を変更していない。
- 東4局の飛び終了で自家「テストjev」31900点・2位、CPUは41800/31000/-4700点となった。結果画面は `artifacts/friend-300-f1d8571-room57225-20261002/frames/2026-10-02T13-06-35.641773+00-00.match_result.png`。78判断はすべて `deadlineMs=300000`、期限超過・`safety_stop`・`screen_loss_stop` は0件だった。`action_aborted` 3件、`own_discard_mismatch` 4件、`own_discard_reconciliation_failed` 3件はキャッシュ隔離・再認識へ戻ったため、画面だけで誤クリックとは断定しない。自家鳴き1件は `called_river_reconciled` を記録し、リーチ、ロン操作と局結果もログで連続確認した。
- ただし13:06:35Zに `screen_advanced match_result` を記録した直後、早期スクリーン判定経路が結果画面を進めて `matchmaking` とし、通常の `match_completed_stop` 判定へ到達しなかった。`round_terminal_wait` が反復したため13:07:32Zに手動停止した。よってこの2位はCPU機能回帰の完走結果・段位戦勝率のいずれにも含めない。
- 原因はscreencastの早期結果判定が、通常の全画面経路にある友人戦終了停止より先に `--advance-screens` を実行していたことだった。後続修正では早期経路でも結果遷移前に `match_completed_stop` を要求し、画面遷移しない単体回帰を追加した。修正後の同一300+0秒CPU完走回帰が必要である。

## 43bd5d6の300+0秒CPU回帰（完走・停止修正を確認）

- 友人戦部屋57225。四人南・300+0秒・簡単CPU3人、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を `artifacts/live/43bd5d6-preflight-browser-20261002.png` と開始直後の `artifacts/friend-300-43bd5d6-room57225-20261002/preflight-started.png` で確認した。使用コードは `43bd5d6`。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-43bd5d6-room57225-20261002 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中にコード・設定を変更していない。
- 終局画面は `artifacts/friend-300-43bd5d6-room57225-20261002/frames/2026-10-02T14-09-33.457422+00-00.match_result.png`。自家「テストjev」は16400点・4位、CPUは47000/19400/17200点だった。CPU友人戦の機能・回帰結果であり、段位戦の勝率評価には含めない。
- 174打牌判断、176 replay、3自家鳴きの `called_river_reconciled` を記録した。期限開始はすべて `deadlineMs=300000`、`action_deadline_expired`、`safety_stop`、`screen_loss_stop` は0件。副露後の10枚手牌・shifted draw slot は実画面で通過した。残り山0枚の判断は2件あり、候補の `winProbability=0` と `tenpaiProbability=0` を確認した。存在しない白のカン／`minkan` はログに0件だった。
- 終局を14:09:33Zに `match_result` として観測し、同じ早期判定経路で `match_completed_stop confidence=1.0` を記録してプロセスが終了した。結果画面を進めてmatchmakingを反復した前回の停止漏れは再発しなかった。
- 自河照合では `own_discard_mismatch` 9件、`own_discard_reconciliation_failed` 10件、`action_aborted` 2件（いずれもクリック前の手牌変化）を記録した。不一致は公開キャッシュから隔離された。期待P→観測9m、期待1m→2m等の対は存在するが、観測が単一追加ではなく複数追加になった事例もあり、現ログだけでは河OCRの時系列ずれと意図外クリックを分離できない。画像だけで敗因と断定せず、クリック前後の河全体・手牌・ポインタを同一識別子で結ぶ調査を未完了として継続する。

## a8c2391の銅の間・四人東（無効：操作者安全停止後の自動ツモ切り）

- 銅の間は実画面で入場可能と確認し、四人東を選択した。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/ranked-a8c2391-copper-east-20261002 --ranked-loop --action-deadline-ms=300000 --force-auto-click-budget-ms=2600 --board-metadata --no-dashboard`。これは300+0秒CPU友人戦と分離した段位戦用設定である。
- 卓は東1局から開始したが、開始直後に実際には盤面であったフレームを `connection_error` と誤分類して安全停止した。操作者はクリック前で、画面確認後に同一設定で再接続した。東4局ではリーチボタンが事前安定性確認中に変化し、未確認クリックを避けて `safety_stop` した。離席自動ツモ切りモーダルを確認して「再開」し、操作者を再接続した。
- 最終画面 `artifacts/ranked-a8c2391-copper-east-20261002/after-ranked-stop.png` は自家「テストjev」16300点・4位、-23pt（他家41400/26000/16300）。42判断、全記録済み期限は `deadlineMs=300000`、期限超過0。自己河不一致7件・照合失敗6件はキャッシュ隔離した。`ranked_terminal_transition_stop` は結果後に検証済み段位画面を経ずmatchmakingを観測して停止した安全策である。
- 安全停止後に自動ツモ切りを含むため、この4位とポイント変動は段位戦勝率の有効標本に含めない。敗因を牌画像だけで断定しない。次の修正候補は、リーチボタンの表示遷移を安定性失敗として卓全体を停止せず、ボタン消失・手牌／河変化を再観測してリトライ可能にする経路である。修正前に該当フレームで再現テストを追加する。

## 98b5fa0の300+0秒CPU回帰（完走・リーチ遷移の再試行修正を確認）

- 友人戦部屋75634。四人南・簡単CPU3名・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を開始前画面 `artifacts/live/friend-300-98b5fa0-room75634-ready-20261002.png` で確認した。使用コードはpush済み `98b5fa0`。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-98b5fa0-room75634-20261002 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中にコード・設定は変更していない。
- 最終結果は自家「テストjev」51300点・1位、CPUは32000/27400/-10700点。結果画面は `artifacts/friend-300-98b5fa0-room75634-20261002/frames/2026-10-02T15-07-44.494586+00-00.match_result.png`。これはCPU友人戦の機能・回帰結果であり、銅の間を含む段位戦の勝率評価には含めない。
- 46打牌判断、48 replay、反応期限を含む102件の記録済み actionTiming はすべて `deadlineMs=300000`、`deadlineMet=true`（最大 `evidenceToClickMs=11813`）。`action_deadline_expired`、`safety_stop`、`retryable_safety_abort` はいずれも0件で、終局後は `match_completed_stop` を記録して自動停止した。ロンは3回、鳴き候補は7回とも河と戦略を照合して見送った。
- 前回の銅の間で卓全体を安全停止させた「リーチボタンが事前安定性確認中に変化」の経路は、この回帰では再発しなかった。修正はリーチだけを `RetryableSafetyAbort` として再観測させるものであり、他の操作ボタンの表示変化に対する安全停止は維持している。実機で該当遷移そのものは発生していないため、分岐の直接カバレッジは引き続き単体再現で補う。
- 自河の確定照合は41回、`called_river_reconciled` は0回（自家鳴きなし）。存在しない白のカン／`minkan` は0件、残り山0枚の自家判断も0件だった。途中の公開河候補の時系列ずれはログに残るため、意図外クリックとはこの結果だけで断定せず、既存のキャッシュ隔離・再認識方針を維持する。

## 2026-10-03 銅の間の再確認（入場不可）

- 最新CPU回帰完走後、ロビーの段位戦メニューから銅の間を実画面で選択した。アカウント表示は「称号なし」、銅の間の必要条件は「雀士・雀傑」であり、画面は「現在の段位では入場不可。適した部屋に参加しましょう。」と返した。証拠は `artifacts/live/copper-room-fc882f1-20261003.png`。
- 対局待ち・操作者・打牌は開始していない。従って段位戦の設定、成績、勝率標本は新たに発生していない。アカウントの段位条件が満たされるまで、段位戦評価には進まず、CPU友人戦の回帰とは分離して扱う。

## 628c989の300+0秒CPU試行（無効：0点スコアOCRで認識再試行が継続）

- 友人戦部屋74709。四人南・簡単CPU3名・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を `artifacts/live/friend-300-628c989-room74709-ready-20261003.png` で確認した。使用コードは `628c989`、実行は `--action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` を明示した。対局中はコード・設定を変更していない。
- 東一局で自家副露後の10枚手牌・shifted draw slot・自河更新を実機で確認した。東三局では北家が実際に0点、供託1本、他家48000/27000/24000点であり、保存則は成立していた。しかし0のOCR confidence=0.97473が通常の0.98閾値未満で、`four_scores_not_verified` となった。再試行は約14分継続しクリックされず、離席自動ツモ切りモーダルを確認して操作者を停止した。証拠は `artifacts/friend-300-628c989-room74709-20261003/metadata-retry-live.png`、`metadata-retry-late.png`、`after-operator-stop.png` と同成果物のJSONL・フレーム群である。
- 自動ツモ切りを含むため、対局結果・順位・CPU回帰成績・段位戦勝率には含めない。画像だけで1000点の誤読と断定せず、OCRトークン、中心盤面、四者合計、供託を照合して実0点と確定した。
- 後続修正では校正済みスコア位置の単独`0`だけをconfidence 0.95以上で候補化し、多桁の0.98基準と四者合計＋供託=100000の保存則を維持した。実失敗フレームの回帰、0.95未満拒否、1000以上を0へ誤読した保存則不一致拒否を追加する。
- 修正後の `9723910` で同一対局の離席モーダルを再開したところ、操作者はすでに `match_result` を観測し、`match_completed_stop` を記録して正常終了した。終局画面は自家17700点・3位、CPU48300/31700/2300点（`artifacts/friend-300-9723910-room74709-recovery-20261003/frames/2026-10-02T16-08-08.693270+00-00.match_result.png`）。先行した自動ツモ切りを含むため、これは修正後CPU回帰の成績には含めない。

## 9723910の300+0秒CPU回帰（完走・0点スコア修正を確認、4位）

- 友人戦部屋51086。四人南・簡単CPU3名・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を `artifacts/live/9723910-room51086-cpus-20261003.png` で確認した。使用コードは `9723910`（実行時HEADは記録のみ追加した `efc64b6`）。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-9723910-room51086-20261003 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中にコード・設定を変更していない。
- 終局画面は `artifacts/friend-300-9723910-room51086-20261003/frames/2026-10-02T17-07-30.291442+00-00.match_result.png`。自家「テストjev」は19000点・4位、CPUは36900/24300/19800点だった。CPU友人戦の機能回帰結果であり、段位戦の勝率評価には含めない。
- 153打牌判断、161 replay、2件の `called_river_reconciled` を記録した。重複を除く359件の actionTiming はすべて `deadlineMs=300000`、期限超過0、最大 `evidenceToClickMs=33245`、`safety_stop` 0。副露後の10枚手牌・shifted draw slot は34回の `open_hand_geometry_gate` として実機で継続確認した。存在しない白のカン／`minkan` は0件。
- 残り山0枚の自家判断は東3・南1〜4の計5件で、各候補の `winProbability=0`、`tenpaiProbability=0` を確認した。従って「残り山0枚でも将来和了確率を評価する」問題はこの実機回帰では再発しなかった。
- 自河の `own_discard_mismatch` は9件、`own_discard_reconciliation_failed` は13件だった。ログ・手牌認識・河画像を照合すると、9件はすべて直前の認識が `safe=false`（confidence 0.644〜0.833）の force-auto打牌であり、`safe=true` の誤認識は0件。代表例は選択1mに対して安定後の河が9pとなったものだが、直前認識もsafe=falseだった。13件の失敗は隔離済みの未確認追加牌が次の打牌までに累積して `river_history_not_single_append` になった二次事象である。`own_discard_mismatch_cache_quarantined` が公開キャッシュを隔離できており、照合ロジック変更の根拠は得られなかった。force-autoのunsafe認識クリックは明示仕様のため、今回の証拠だけでは変更しない。
- 終局を `match_result` として観測後、`match_completed_stop confidence=1.0` を記録して操作者は自動停止した。0点スコア修正、終局停止、副露・河整合性の実機経路を完走確認したが、今回の4位は簡単CPUに対する成績不振の追加標本である。段位戦への昇格判断には使用せず、勝率改善はより多い有効CPU標本と原因別の練習で継続する。

## 038767bの銅の間・四人東（無効：先行安全停止後の離席自動ツモ切り）

- 銅の間は実画面の先頭行（初心者・雀士）を選び、四人東を開始した。初回実行は `f68ad89`、`node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/ranked-f68ad89-copper-east-20261003 --ranked-loop --action-deadline-ms=300000 --force-auto-click-budget-ms=2600 --board-metadata --no-dashboard` であり、段位戦用の短時間クリック予算と明示した300000msの action deadline を使用した。開始直後のパスボタンがクリック前安定性確認中に変化し、クリックを送らず `safety_stop: pass button changed during pre-click stability check`（JSONL 212行目）で停止した。
- この停止はボタン遷移の再観測として扱うべきであるため、`038767b` でパスボタンの同じ変化を `RetryableSafetyAbort` にして反応状態を再観測する修正と単体回帰を追加した。`python -m unittest test_auto_operator.py` は146件成功・33件skip、失敗0。コミット・push済みである。
- 初回停止後はゲーム側の離席自動ツモ切りが発生した。したがって、復帰実行 `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/ranked-038767b-copper-east-recovery-20261003 --ranked-loop --action-deadline-ms=300000 --force-auto-click-budget-ms=2600 --board-metadata --no-dashboard` は、修正済み動作の確認には使うが段位戦の勝率標本には含めない。`away_resumed` 後に南1局まで打牌・反応を継続し、記録済み action timing は300000ms期限内だった。結果後は検証済みの段位画面を経ず `matchmaking` へ遷移したことを検出し、`ranked_terminal_transition_stop` で停止した。
- 終局後に同じ雀魂タブを再確認すると、結果画面は自家「テストjev」21000点・4位・-19pt、他家31200/24800/23000点だった（`artifacts/live/post-ranked-c5fcb1a-20261003.png`）。ただし復帰ログには `match_result` がなく、初回停止後の自動ツモ切りを含む。画像だけで敗因を断定せず、この順位・ポイントを段位戦の成績評価から除外する。次の有効な段位戦前に、`038767b` の300+0秒・簡単CPU3名・四人南の完走回帰を行い、CPU結果と段位戦成績を分離して記録する。

## 038767bの300+0秒CPU友人戦（一局戦・完走、3位）

- 雀魂のCPU戦を選ぶと局数が一局戦に固定される画面挙動を確認したため、四人麻雀・CPU戦（一局戦）・300+0秒で部屋61662を作成した。設定は `artifacts/live/friend-300-038767b-cpu-settings-20261003.png`、部屋画面は `artifacts/live/friend-300-038767b-cpu-room-20261003.png` に保存した。使用コードは `038767b`（実行時HEADは記録のみ追加した `bcf58cb`）。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-038767b-room61662-20261003 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中にコード・設定を変更していない。
- 終局画面は `artifacts/friend-300-038767b-room61662-20261003/frames/2026-10-02T18-04-28.302375+00-00.match_result.png`。自家「テストjev」は23500点・3位、CPUは30400/25500/20600点だった。これはCPU友人戦の機能回帰であり、段位戦の勝率評価には含めない。
- 打牌33件と反応9件のすべては `deadlineMs=300000`、`deadlineMet=true`（打牌最大 `evidenceToClickMs=24854`、反応最大11807）。`safety_stop`、期限超過、`screen_loss_stop` は0件。副露後の10枚手牌とshifted draw slotは21件の `open_hand_geometry_gate` で確認し、鳴き候補の捨て牌検証・戦略的passも7件実行確認した。低信頼度のラウンド結果を一度進めた後に、最終 `match_result` を再検出して `match_completed_stop confidence=1.0` で停止した。
- 自河不一致は3件（期待W→観測Sが2件、期待1m→観測7pが1件）で、全て公開キャッシュを隔離した。33判断すべての手牌認識は `safe=false`（confidence 0.515〜0.797）であり、safe=true誤認を示す証拠はない。一方、手牌同一性チェックのクリック前 `action_aborted` が東2局で7件あり、pixel delta 1.680〜3.831と7p/6pの再読差を記録した。自動打牌を含まず完走したが、これは無操作になり得る劣化候補であるため、フレーム・クリック・状態ログを突合して別途原因を調査する。

## de45071の300+0秒CPU友人戦（一局戦・完走、1位）

- 前試行で確認した閉じ手牌の行発光による偽 `action_aborted` を、RGB平均差ではなく牌面構造差で判定するよう修正した。実フレームでは旧RGB差が1.680〜3.831（閾値1.5超）である一方、構造差は最大1.119（閾値未満）、実6p/7pの牌面差は34.594であることを確認し、回帰テストを追加した。`python -m unittest test_auto_operator.py` は147件成功・33件skip。使用コードはpush済み `de45071`。
- 友人戦部屋43582、四人CPU戦（一局戦）・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を `artifacts/live/friend-300-de45071-cpu-settings-20261003.png` と `artifacts/live/friend-300-de45071-cpu-room-pending-20261003.png` で確認した。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-de45071-room43582-20261003 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中にコード・設定を変更していない。
- 終局画面は `artifacts/friend-300-de45071-room43582-20261003/frames/2026-10-02T18-22-43.427599+00-00.match_result.png`。自家「テストjev」は33300点・1位、CPUは24900/21900/19900点。CPU友人戦の機能回帰であり、段位戦の勝率評価には含めない。

## 1a56964の300+0秒CPU友人戦（完走、3位）と公開河基準修正

- 段位戦ログで、クリック座標の異常を示す一次証拠は得られなかった一方、`pending_own_discard.before` が評価器の古い `state.ownDiscards` を使い、非同期公開キャッシュより数牌遅れることを確認した。これにより正しい単一追加を複数牌ジャンプとして隔離することがあった。`1a56964` は照合基準をクリック時の公開キャッシュ河へ固定し、古い評価河を使わない単体回帰を追加した。Pythonテストは148件成功・33件skip。
- 友人戦部屋12817、四人CPU戦（一局戦）・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を `artifacts/live/friend-create-settings-1a56964-20261003.png` と `artifacts/live/friend-300-1a56964-room-pending-20261003.png` で確認した。使用コードはpush済み `1a56964`。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-1a56964-room12817-20261003 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中にコード・設定は変更していない。
- 終局画面は `artifacts/friend-300-1a56964-room12817-20261003/frames/2026-10-02T19-47-31.773388+00-00.match_result.png`。自家「テストjev」は25000点・3位、CPUは33300/25000/16700点。32打牌はすべて`deadlineMs=300000`内（最大`evidenceToClickMs=8233`）、`action_aborted`、`own_discard_mismatch`、安全停止は0。公開河の二重確認は29候補中28件が一致した。
- ただし開始直後、最初の打牌 `S` の公開観測がまだ候補化される前に次の`E`を打牌し、後続スキャンが`[S,E]`を返したため、旧pendingの基準`[]`に対して`own_discard_reconciliation_failed`が1件発生した。これは誤クリックの証拠ではなく、候補到着と次打牌の間の非同期競合である。公開河基準の遅延混入は解消されたが、この候補到着直前の上書き競合は未完了として次修正で防ぐ。
- `match_completed_stop confidence=1.0`で正常終了した。このCPU結果は実動作・回帰確認であり、段位戦の順位／勝率評価とは分離する。

## 1dd294dの300+0秒CPU友人戦（完走、要修正の副露後ツモ牌誤認）

- `1dd294d` は公開河候補が評価後・クリック前に到着した場合に再照合を優先するガードを追加した。Pythonテストは149件成功・33件skip。友人戦部屋12817、四人CPU戦（一局戦）・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。開始前設定は `artifacts/live/friend-300-1dd294d-settings-20261003.png`。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-1dd294d-room12817-20261003 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中にコード・設定は変更していない。
- `match_completed_stop confidence=1.0`で完走したが、これは不一致が残った原因調査用のCPU回帰であり、成績を勝率改善根拠には使わない。副露後の19:54:52Zフレーム `frames/2026-10-02T19-54-52.522704+00-00.jpg` では、独立したツモ牌スロット（clickIndex 10, x=1217.5）に実際は`8p`がある。認識は同スロットを`1m`と返し、confidence=0.60364、ambiguityMargin=0.00283、safe=falseだった。クリック後の二重公開河観測は`8p`を確認し、`expected=1m / actual=8p`を記録した。
- これは座標ずれや公開河遅延ではない。副露後の持ち上がった／独立ツモ牌の低信頼誤認をforce-autoが意図牌として使用したことが原因である。したがって次の修正対象は、safe=falseかつ極小余裕の独立ツモ牌を、通常手牌と同じ確定牌として戦略評価・クリック対象にしないことである。
- CPU友人戦は機能確認であり、この試行の順位・結果を段位戦の勝率評価と混同しない。

## b608021 / 01729d5の副露後ツモ牌保護試行（無効）と復旧確認

- `b608021` は低信頼・曖昧な独立ツモ牌を直接force-auto打牌しない保護を追加した（Python 150成功・33 skip）。部屋12817の同一300+0 CPU戦で、保護自体は発火したが、同じフレームを31回以上再試行して局時計を消費した。操作者を停止したため、この試行は結果・勝率・CPU回帰成績から除外する。
- `01729d5` は、独立ツモ牌が曖昧な場合、評価候補から確実に認識された副露後の既存手牌を選び直す代替打牌へ変更した（Python 151成功・33 skip）。先行試行で操作者を停止した対局へ復旧実行したため、順位・点数は回帰成績に含めない。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-01729d5-room12817-recovery-20261003 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。
- 復旧後は `ambiguous_open_draw_fallback` が2回発火し、無限再試行・`action_aborted`は0。32判断はすべて300000ms期限内で、`match_completed_stop confidence=1.0`により終局した。公開河不一致2件は停止前の非同期状態を引き継いだためで、座標誤りの根拠にはしない。終局画像は `artifacts/friend-300-01729d5-room12817-recovery-20261003/frames/2026-10-02T20-21-25.778306+00-00.match_result.png`。
- 次の評価は、終了済みの新規部屋から`01729d5`以降のクリーンな300+0 CPU回帰として開始し、CPU機能結果と段位戦成績を分離する。
- 打牌25件と反応3件はすべて `deadlineMs=300000`、`deadlineMet=true`（打牌最大 `evidenceToClickMs=11565`、反応最大12691）。`action_aborted`、`safety_stop`、期限超過、`screen_loss_stop` は0件。前回の低信頼度ラウンド画面も経由したが、最終 `match_result` を確定検出して `match_completed_stop confidence=1.0` で停止した。自己河不一致は期待E→観測Cの1件で公開キャッシュを隔離した。safe=true誤認の証拠ではなく、以後の打牌は継続・照合されている。

## 01729d5のクリーン300+0秒CPU回帰（完走、診断用・不合格）

- 新規開始の友人戦部屋12817・四人CPU戦（一局戦）・300+0秒を `artifacts/live/friend-300-01729d5-clean-settings-20261003.png` で確認した。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-01729d5-clean-room12817-20261003 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中にコード・設定を変更していない。
- 68判断・68クリックで完走し、期限超過0、`match_completed_stop confidence=1.0`。自家は19500点・3位、CPUは37100/26500/16900点（`artifacts/friend-300-01729d5-clean-room12817-20261003/frames/2026-10-02T20-45-19.803317+00-00.match_result.png`）。CPU友人戦の機能結果であり、段位戦勝率には含めない。
- ただし`action_aborted` 6件、`own_discard_mismatch` 2件、`ambiguous_open_draw_fallback` 1件を記録したため合格標本にはしない。うち後者の不一致は、fallbackで実クリックした2mに対して評価器の元の1mをpending照合していた実装不整合だった。もう一件（期待E、観測N）は、クリック座標x=1407.5の手牌Eと河画像を照合し、公開河OCRがEをNと誤読した証拠であり、物理クリック誤りとは断定しない。公開河は隔離され、安全側で継続した。

## 251ad86の300+0秒CPU回帰（完走・実クリック牌照合修正を確認、1位）

- `251ad86` は曖昧な独立ツモ牌のfallback後、評価時の選択ではなく実際にクリックした牌・indexをpending河照合と手牌キャッシュへ渡す修正である。`PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python/test_auto_operator.py` は151件成功・33件skip。コミットとpush済み。
- 友人戦部屋12817、四人CPU戦（一局戦）・300+0秒の設定は `artifacts/live/friend-300-251ad86-settings-20261003.png` に保存した。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-251ad86-room12817-20261003 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中にコード・設定を変更していない。
- 18判断・18クリック、`action_aborted` 0、`own_discard_mismatch` 0、fallback 0、期限超過0で、`match_completed_stop confidence=1.0`により自動停止した。結果は自家「テストjev」32200点・1位、CPUは25000/23000/19800点。終局証拠は `artifacts/friend-300-251ad86-room12817-20261003/frames/2026-10-02T20-57-10.312610+00-00.match_result.png`。
- これは実クリック牌の通常照合を壊していないクリーンなCPU機能・回帰標本である。ただしfallbackそのものはこの局では発火していないため、該当分岐の実機直接再検証は将来の発火局で継続する。CPU友人戦の1位は段位戦の勝率改善の証明ではなく、段位戦成績とは明確に分離する。

## 251ad86の銅の間・四人南（有効標本、4位）

- アカウントは実画面で「初」と表示され、段位戦の銅の間には「初心者・雀士」と明記されていたため参加可能と確認した。銅の間の四人南を選択し、`artifacts/live/ranked-copper-east-251ad86-start-20261003.png` に開始画面、`artifacts/live/copper-match-type-20261003.png` に卓種選択画面を保存した。
- 実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/ranked-251ad86-copper-east-20261003 --ranked-loop --action-deadline-ms=300000 --force-auto-click-budget-ms=2600 --board-metadata --no-dashboard`。CPU友人戦の8000msを流用せず、段位戦用2600msと明示的な300000ms deadlineを用いた。
- 終局画面 `artifacts/live/ranked-251ad86-terminal-20261003.png` は自家「テストjev」13400点・4位・-26pt、他家36300/34200/16100点を示す。対局ログは129打牌判断・130操作、記録済み期限超過0、クリック前の`action_aborted`2件は未クリックの再観測後に復帰した。離席自動ツモ切り、`safety_stop`、期限切れは0件であり、この4位は段位戦の有効な成績標本としてCPU結果とは分離して扱う。
- `own_discard_mismatch`は23件、`own_discard_reconciliation_failed`も存在した。各事象では公開河キャッシュを隔離し、直ちに物理クリック誤りとは結論しない。終局遷移ではゲームがmatchmakingへ移ったことを検出して`ranked_terminal_transition_stop`となったが、直後の実画面で結果を確認した。結果画面を安定して保存する遷移は、次回の修正・回帰対象とする。

## 3bf0e37の銅の間・四人南（有効標本、4位）と終局遷移の診断

- 銅の間・四人南を `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/ranked-3bf0e37-copper-south-20261003 --ranked-loop --action-deadline-ms=300000 --force-auto-click-budget-ms=2600 --board-metadata --no-dashboard` で実行した。CPU友人戦とは別の段位戦用2600ms設定で、期限は全記録で300000ms、期限超過0だった。
- 実画面の最終結果は `artifacts/live/ranked-3bf0e37-terminal-2-20261003.png` に保存した。自家「テストjev」は18400点・4位・-21pt、他家は30700/28600/22300点。離席自動ツモ切り、`safety_stop`、期限超過は0であるため、この4位は段位戦の有効標本であり、CPU回帰結果には含めない。
- 36判断・36通常打牌、13反応操作を記録した。公開河の `own_discard_mismatch` 8件と `own_discard_reconciliation_failed` 9件は、直前の実行レシート（選択牌・手牌index・クリック座標）と突合して、評価／実クリックとも期待牌で一致し、公開河OCRだけが別牌を返した事象だった。物理誤クリックの証拠にはしない。
- 東2・東3局の結果画面を確認後、暗転フレームを`lobby`と誤認して一時的に`ranked_terminal_reentry_verified`とした。最終結果では`matchmaking`を観測し、`ranked_terminal_transition_stop`で安全停止した。終了時の実画面は結果画面であり、停止は正当だった。

## f997003の終局遷移保護修正と300+0秒CPU回帰（完走、2位）

- 上記の実戦フレームに基づき、`lobby`単独では結果遷移保護を解除せず、`ranked_menu`または`ranked_room`を観測して初めて再入場を確認するよう修正した。ユニットテストには、lobby風の暗転では保護を維持し、その後のランクメニューでのみ解除する回帰を追加した。`PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python/test_auto_operator.py` は151件成功・33件skip。コミット`f997003`をpush済み。
- 友人戦部屋75005は四人CPU戦（一局戦）・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。設定の証跡は `artifacts/live/f997003-friend-300-settings-20261003.png`。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-f997003-room75005-20261003 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中にコード・設定は変更していない。
- 29打牌判断・29通常操作・13反応操作で完走し、`match_completed_stop`で意図どおり停止した。`own_discard_mismatch`、`own_discard_reconciliation_failed`、`action_aborted`、`safety_stop`、期限超過はすべて0。結果画面は `artifacts/friend-300-f997003-room75005-20261003/frames/2026-10-02T22-56-58.036762+00-00.match_result.png`、自家「テストjev」は25000点・2位、CPUは31000/23000/23000点だった。
- この結果は終局遷移保護と牌・状態・操作経路のCPU機能回帰であり、段位戦の勝率評価や上記の銅の間2局の成績とは明確に分離する。

## d51a64dの銅の間・四人南（有効標本、3位）

- 銅の間・四人南を `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/ranked-d51a64d-copper-south-20261003 --ranked-loop --action-deadline-ms=300000 --force-auto-click-budget-ms=2600 --board-metadata --no-dashboard` で実行した。CPU友人戦の機能確認とは別の段位戦評価であり、300000ms deadline と段位戦用2600msクリック予算を明示した。
- 終局画面は `artifacts/live/d51a64d-ranked-terminal-20261003.png`。自家「テストjev」は13800点・3位・-16.2（PT -16）、他家は56600/24500/5100点だった。160判断・160通常クリック・51反応操作、記録済み期限超過0。`action_aborted` 6件は離席ダイアログ2件または手牌変化4件を検出した未クリックの再観測であり、操作取り違えではない。
- 自家河では `own_discard_mismatch` 20件、`own_discard_reconciliation_failed` 26件を記録した。前者の期待→観測は `S→9p`、`E→3p`、`4m→7s` など相互に無関係な組合せで、単一方向の座標ずれを支持しない。後者はすべて `river_history_not_single_append` であり、公開河の非同期OCRが一枚ずつの履歴追加を観測できなかったものだった。キャッシュは既存の隔離経路へ移行し、物理誤クリックと断定しない。次の改善では、各不一致に実行レシート（クリック牌・index・座標）を直接関連付けて、OCR誤読と操作誤りをログ単独で分離できるようにする。
- 副露後は `called_river_reconciled` と `open_hand_geometry_gate` を複数回観測し、実対局で自分の副露・河・自手番の整合が継続した。終局後は検証済みの段位メニューを経ず `matchmaking` を観測して `ranked_terminal_transition_stop` となった。結果画面が実在することを上記画像で確認しており、無関係なロビー操作を防いだ安全停止である。

## f0eb441の不一致レシート記録と300+0秒CPU回帰（完走、3位）

- `f0eb441` は公開河の `own_discard_mismatch` と `own_discard_reconciliation_failed` に、実クリック牌に加え click index・座標・クリック時刻・受領確認を直接記録する改善である。これにより将来の不一致をOCR誤読か物理操作かへログ単独で分類できる。ユニットテストは `PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python/test_auto_operator.py` で152成功・33 skip。コミット・push済み。
- 先行した部屋80901は、バックグラウンド起動が親シェル終了で消えたためゲーム側が無操作切断した。`artifacts/live/f0eb441-friend-after-launch-20261003.png` に切断表示を保存した。この試行は自動ツモ切りを含むため回帰・成績標本から除外する。以後は部屋開始前に `nohup setsid` でNode/Python PIDと成果物ディレクトリが実在することを確認してから開始する。
- 有効な新規部屋70494は四人CPU戦（一局戦）・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。設定証跡は `artifacts/live/f0eb441-friend-300-settings2-20261003.png` と `artifacts/live/f0eb441-friend-room3-20261003.png`。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-f0eb441-room70494-20261003 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。
- 31判断・31通常クリック・10反応操作、`action_aborted`、`own_discard_mismatch`、`own_discard_reconciliation_failed`、`safety_stop`、期限超過はすべて0で、`match_completed_stop`により完走した。結果画面は `artifacts/live/f0eb441-friend-300-result-20261003.png`、自家「テストjev」は22000点・3位、CPUは32500/25000/20500点。この結果は新ログ相関と副露・河・操作経路のCPU機能回帰であり、段位戦の勝率評価には含めない。

## cd3fc96の銅の間・四人東（有効標本、4位／誤打牌の直接証拠）

- 段位戦は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/ranked-cd3fc96-copper-south-20261003 --ranked-loop --action-deadline-ms=300000 --force-auto-click-budget-ms=2600 --board-metadata --no-dashboard` で開始した。成果物名は先行操作時の `south` のままだが、実画面の卓種は `artifacts/live/cd3fc96-ranked-terminal-20261003.png` の左上にあるとおり銅の間・四人東であり、本記録では実画面を正として四人東とする。CPU友人戦の機能回帰とは別の段位戦評価である。
- 終局画面は同画像に保存した。自家「テストjev」は18200点・4位・-41.8（PT -41）、他家は44000/31800/26000点だった。23通常打牌判断・23クリック・13反応操作、期限超過0である。`ranked_terminal_transition_stop` は結果遷移後に `result_transition_missing_verified_ranked_navigation` を検出して停止したもので、未検証の自動再入場は行っていない。
- 自河照合は `own_discard_mismatch` 3件、`own_discard_reconciliation_failed` 5件だった。不一致のうち二件は同じ座標の系統的な誤操作を直接示す。認識・判断は發 (`F`) を選び index 12、座標 `(1407.5,999)` をクリックし、手牌／自河の変化も受領確認したが、安定後の自河はツモ牌8筒（`F→8p`）と赤5筒（`F→0p`）だった。もう一件も `4m` を index 0・`(269,999)` でクリックした後に北（`N`）となった。各レシートは JSONL の `2026-10-03T02:13:39.895180+00:00`、`02:14:32.673077+00:00`、`02:16:11.213637+00:00` にある。
- 特に `F→8p` の直前フレーム `frames/2026-10-03T02-14-13.020380+00-00.jpg` は認識結果・選択 index・クリック座標・実河を同時に照合できる。これは公開河OCRだけの誤読ではなく、持ち上がり／クリック時の手牌位置変化による誤打牌を調査・修正する根拠である。対局終了後にのみ、このクリック経路を修正対象として切り出した。

## 699d317の300+0秒CPU回帰（完走、1位／持ち上がり確認クリック修正）

- `699d317` は、実段位戦の `4m→N`、`F→8p`、`F→0p` のレシートから確認した、ブラウザ二重クリックの第2打が独立ツモ牌へ入る問題を修正する。第1打で牌を選択後、第2打を同じx・44px上の持ち上がった牌面内に送る。単体回帰は `PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python/test_auto_operator.py` で152成功・33 skip、コミット・push済みである。
- 友人戦部屋50067は四人CPU戦（一局戦）・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。設定証跡は `artifacts/live/699d317-friend-room-20261003.png`。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-699d317-room50067-20261003 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` であり、対局中にコード・設定は変更していない。
- `match_completed_stop` により完走した。10判断・9通常クリック・4反応操作、`own_discard_mismatch`、`own_discard_reconciliation_failed`、期限超過はいずれも0で、1件の `action_aborted` は未クリックの再観測である。結果画面は `artifacts/live/699d317-friend-300-result-20261003.png`、自家「テストjev」は37000点・1位、CPUは21000/21000/21000点だった。この結果は持ち上がり確認クリックと牌・河・操作経路のCPU機能回帰であり、段位戦の勝率評価には含めない。
