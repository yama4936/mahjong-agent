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

## 1f18f5dの銅の間・四人東（有効標本、4位／待機なしの持ち上がり誤打牌）

- 銅の間・四人東を段位戦用の `--ranked-loop --action-deadline-ms=300000 --force-auto-click-budget-ms=2600` で実行した。実画面の結果は `artifacts/live/1f18f5d-ranked-terminal-20261003.png` に保存し、自家「テストjev」は14800点・4位・PT -25だった。離席自動打牌、期限超過、安全停止はなく、有効な段位戦標本としてCPU回帰とは分離する。
- 43判断・43通常クリック・17反応操作で、`own_discard_mismatch` 11件、`own_discard_reconciliation_failed` 13件を記録した。レシートを照合すると、期待 `C` が `2s/6s/2s/5p/6m`、期待 `N` が `1m`、期待 `3p` が `3m` など、選択牌と無関係な河牌に置き換わった。持ち上がった牌の第2確認クリックを y-44 へ送るだけでは、牌が上がるアニメーションより早い場合があることを示す直接証拠である。
- 後続 `fff8ff0` では、第1クリック後に選択状態を最大120ms待ってから同じ牌の持ち上がり位置へ第2クリックを送る。単体テストは152成功・33 skipで、変更とpush済みである。

## fff8ff0の300+0秒CPU回帰（完走、2位／持ち上がり待機修正を確認）

- 新規友人戦部屋10133。画面 `artifacts/live/fff8ff0-friend-room-20261003.png` で、四人CPU戦・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を確認した。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-fff8ff0-room10133-20261003 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。開始前にNode/Pythonの両PIDを確認し、対局中はコード・設定を変更していない。
- 10判断・10通常クリック・10反応期限記録で、`own_discard_mismatch`、`own_discard_reconciliation_failed`、`action_deadline_missed`、`action_aborted` はいずれも0。全打牌で明示的な300000ms deadlineを満たし、自己河は `public_own_river_append_confirmed` と `own_discard_reconciled` で追従した。`match_completed_stop confidence=1.0` を記録して自動停止した。
- 結果画面 `artifacts/friend-300-fff8ff0-room10133-20261003/final-screen.png` は自家「テストjev」24000点・2位、CPUは30000/24000/22000点を示す。この結果は持ち上がり待機、牌認識・状態認識・判断・操作のCPU機能回帰であり、段位戦の勝率評価には含めない。段位戦ではなお有効標本が連続4位であり、勝率上向きの十分な標本は未達であるため、次回も原因分析を優先する。

## bca8399のツモ遷移停止修正と300+0秒CPU回帰（完走、4位）

- 銅の間・四人東の実戦では、ツモボタンが事前安定性確認中に変化したとき `RuntimeError` が未処理となり操作者が停止した。画面は東4局で継続していたため同じ設定で復旧したが、停止から復旧までの自動打牌混入を否定できない。終局画面 `artifacts/live/b39086f-ranked-recovery-terminal-20261003.png` は自家14800点・4位・PT -25である。この順位は有効な段位戦勝率標本に含めない。
- `bca8399` はツモボタンの同じ表示遷移を、クリック前の `RetryableSafetyAbort` として再観測するよう修正した。リーチの既存安全経路と同じく、卓全体を停止させず、未クリックを保証する。`PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python/test_auto_operator.py` は153成功・33 skip。コミットとpush済み。
- 新規友人戦部屋31845で、四人CPU戦・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を `artifacts/live/bca8399-friend-room-20261003.png` で確認した。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-bca8399-room31845-20261003 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。開始前にNode/Python PIDを確認し、対局中にコード・設定は変更していない。
- 7判断・7通常クリックで `match_completed_stop confidence=1.0` により完走した。`own_discard_mismatch`、`own_discard_reconciliation_failed`、`action_aborted`、期限超過、`safety_stop` はすべて0。終局画面 `artifacts/friend-300-bca8399-room31845-20261003/final-screen.png` は自家18600点・4位、CPU31400/25000/25000点を示す。このCPU結果はツモ遷移復旧を含む機能回帰であり、段位戦成績とは分離する。

## 2026-10-05 起動復旧の事前確認（対局未開始）

- 作業開始時は `167e2fb`、clean な `main` と `origin/main` を確認した。専用ブラウザ、操作者、認識サーバーの稼働はなく、実行中の対局もなかった。このチェックアウトには除外対象の `.runtime`、牌テンプレート、対局ログが存在しなかった。
- `npm ci`、TypeScript build、Python仮想環境とOCR依存関係、固定リビジョン `8c0f22e7c6b64be55bb1d2767fe1a63981788de7` の牌テンプレート1091ファイルを用意した。`uv venv` が作る環境には `pip` がないため、`operator:setup` は従来失敗した。セットアップを `uv pip` にフォールバックさせ、再実行成功を確認した。
- 専用Chromeの通常表示とソフトウェア描画ではCDP画面取得が30秒でタイムアウトし、安全停止した。ヘッドレスかつソフトウェア描画では画面取得と認識サーバーが稼働した。読み取り専用操作者の初回ログは `artifacts/preflight-headless-snapshot-167e2fb-20261005/python-operator.jsonl`。保存画面 `artifacts/live/login-screen-20261005.png` はログイン画面だったが、従来の画面認識は `matchmaking confidence=1.0` と誤判定していた。
- 金色のログインボタンを識別して `login` を先に判定する修正後、`artifacts/preflight-login-fixed-20261005/python-operator.jsonl` に `login confidence=1.0` と画面スナップショットを確認した。読み取り専用操作者は重複起動せず、実戦操作はしていない。新規プロファイルは未ログインのため、友人戦300+0秒の設定、`--action-deadline-ms=300000` の実戦回帰、段位戦再評価はまだ実施できない。対局成績標本は追加しない。
- 関連チェックは `python/test_screen_state.py` 3件、`python/test_auto_operator.py` 153件成功・34件skip、`npm run build`、`npm run operator:setup` が成功。全体 `npm test` と `npm run test:python` は、この新規チェックアウトに存在しない旧・Git除外の検証画像を参照するテストで失敗した。失敗は今回の実戦成績ではない。

## 2026-10-05 ログイン復旧の追加診断（対局未開始）

- `ab5b45f` の読み取りでは専用プロファイルが `login confidence=1.0` のままだった。対局・友人戦部屋は存在せず、旧操作者を止めてから `--action-deadline-ms=300000 --force-auto-click-budget-ms=8000` でログインボタンを一度だけ押した。`artifacts/login-recovery-ab5b45f-20261005/python-operator.jsonl` にクリック座標 `(1495.68,469.8)` を記録した。
- クリック後の実画面 `artifacts/live/account-modal-20261005.png` は YOSTAR のメールアドレス・認証コード入力画面だった。画面認識がこれも `matchmaking` と誤判定していた。中央の白い認証ダイアログを `account_modal` と識別するよう修正した。
- 修正後の `artifacts/login-required-stop-20261005/python-operator.jsonl` は `login_required_stop state=account_modal confidence=1.0` を記録し、操作者はゲーム操作をせず正常終了した。自動で利用できるログイン済みセッションは存在しない。認証入力はユーザー操作が必要で、300+0秒友人戦回帰と段位戦は未開始のままである。
- 操作者にはログインボタンの一度だけの試行、認証画面の安全停止、画面種別ごとの任意スナップショットを追加した。空白画面を認証画面と誤認しない判定も確認した。`python/test_screen_state.py python/test_auto_operator.py` の関連157件は34件skipを除き成功し、`npm run build` も成功した。

## 2026-10-05 友人戦36717・認識環境復旧（診断標本、回帰不合格）

- Yostarメール認証と利用規約への同意後、アカウント「テストjev」で友人戦部屋36717を開始した。四人CPU(簡単)・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3などの設定画像は `artifacts/friend-300-8bb7941-room36717-20261005/preflight-room.png`。使用コミットは `8bb7941`。初回操作者は `--action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` で実行した。
- `artifacts/friend-300-8bb7941-room36717-20261005/python-operator.jsonl` に `public_cache_failed`（`.runtime/vision-venv/bin/python ENOENT`）と `public_context_deferred` の反復を記録した。盤面認識は東1局・残り66枚を読み続けたが打牌できず、持ち時間切れでゲーム側の自動打牌が混入した。初回操作者の機能回帰は失敗。画像だけで原因を断定せず、認識サーバーのspawnエラーと実行環境の不存在を照合した。
- ソース・設定を対局中に変更せず、欠けていた `.runtime/vision-venv` と固定ハッシュのハイブリッド認識モデルを導入した。`npm run hybrid-vision:setup` はmacOSに `sha256sum` がなく失敗したため、固定SHA-256を `shasum -a 256` で検証してモデルを配置した。稼働中サーバーは失敗したworkerのPromiseを保持して回復しなかった。異常な操作者のみ停止し、ゲーム対局を退出せず同じ設定で再接続した。
- 復旧実行は `artifacts/friend-300-8bb7941-room36717-recovery-20261005/python-operator.jsonl`。公開情報キャッシュ更新、牌認識、判断、実クリック、河と手牌の変化による操作確認、リプレイ28件を記録した。東1局は流局、東2局の終局で `match_completed_stop confidence=1.0`。結果は自家「テストjev」33300点・1位、CPU22900/22900/20900点。終局画像は同ディレクトリの `frames/2026-10-05T03-13-32.511836+00-00.match_result.png`。序盤にゲーム側自動打牌があったため、順位はクリーンな機能回帰標本にも段位戦勝率標本にも含めない。
- セットアップをmacOSで動くSHA-256検証へ修正し、workerの起動失敗後に次要求で再試行できるよう修正した。`npm run hybrid-vision:setup` の再実行、`npm run build`、`node --import tsx --test test/hybridTileRecognizer.test.ts`（6件成功）は通過した。全体`npm test`は193件中186成功・6skip・1失敗で、既存の`test/recognitionServer.test.ts`が`cached-hand-drift-20260928.jpg`を11枚の副露手牌として期待する一方、現認識では14枚と判定する。単独再実行でも同じ失敗を確認した。この失敗は今回修正した起動再試行分岐とは別に残る。

## 1b4137f のクリーンな300+0秒CPU友人戦回帰（完走、1位）

- 友人戦部屋36717を新しく開始し、四人CPU(簡単)・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を `artifacts/friend-300-1b4137f-room36717-clean-20261005/preflight-room.png` で再確認した。使用コミットはpush済みの`1b4137f`。開始前に操作者・認識サーバーの不在を確認してから一組だけ起動した。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-1b4137f-room36717-clean-20261005 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中はコード・設定を変更していない。
- 最初の手番から公開情報認識が成功した。`python-operator.jsonl` とリプレイ13件に、牌認識、状態認識、判断、実クリック、および手牌・自己河変化による13件すべての操作確認を記録した。13判断すべて `deadlineMs=300000`、`deadlineMet=true`、最大 `evidenceToClickMs=19870`。`public_cache_failed`、`action_aborted`、`own_discard_mismatch`、`safety_stop`、期限超過はいずれも0。2局を経て `match_completed_stop confidence=1.0` で正常終了した。
- 終局画像 `artifacts/friend-300-1b4137f-room36717-clean-20261005/frames/2026-10-05T03-28-33.314509+00-00.match_result.png` で、自家「テストjev」31200点・1位、CPU26000/22000/20800点を確認した。これは300+0秒CPU友人戦の機能回帰合格であり、短時間の段位戦での成績や勝率改善を示す標本には含めない。

## 2026-10-05 銅の間・四人東の短時間診断（無効な成績標本）

- 実画面 `artifacts/live/ranked-entry-1b4137f-20261005.png` はアカウント「初心」と銅の間の対象段位「初心者、雀士」を示す。銅の間パネルを `(1385,412)` で選ぶと `artifacts/live/copper-selected-1b4137f-20261005.png` に四人東・四人南が表示された。四人東を `(1379,403)` で選んだ `artifacts/live/copper-east-click-d956490-20261005.png` は「エラーコード1308、マッチング成功。まもなく対局が開始します」と示す。実際に銅の間・四人東の卓に入り、入場条件の拒否はなかった。
- 操作者はpush済み`d956490`、`--ranked-loop --force-auto-click-budget-ms=2600 --board-metadata --advance-screens --no-dashboard`、既定 `action-deadline-ms=5000` で開始した。最初の実行 `artifacts/ranked-d956490-copper-east-20261005/python-operator.jsonl` は成功通知を `connection_error` と誤認し、打牌0で安全停止した。ゲーム対局は中断せず、同じ設定で `artifacts/ranked-d956490-copper-east-recovery-20261005` に再接続した。
- 復旧操作者は公開情報と局・点数を認識したが、打牌判断までの7〜10秒程度が5000ms期限を超え、`action_deadline_expired` 39件、`action_aborted` 39件、操作者による打牌0件となった。後半には局結果の直後に一時画面を `matchmaking` と誤認し、`ranked_terminal_transition_stop` で安全停止した。終局実画面 `artifacts/live/ranked-after-transition-stop-20261005.png` は自家「テストjev」5300点・4位・PT -34。操作者が打牌していないので、この結果は段位戦勝率の有効標本に含めない。
- 成功通知と接続エラーは同じ枠・確認ボタンであり、中央のメッセージ部分の画像差は0.059、従来の共通枠を含む比較範囲では0.030で誤一致した。通知文の領域を別に照合して区別する修正を行い、実画像を `matchmaking`、接続エラー画像を `connection_error` と再判定できた。結果後の一時的な`matchmaking`検出には5秒の猶予を設け、継続する不正な遷移だけを安全停止する。短時間打牌の処理時間問題は別に継続検証する。

## 短時間段位戦向けの盤面OCR先行キャッシュ（回帰待ち）

- 先の段位戦ログでは、打牌可能の検出から認識用フレームの保存まで約3〜4秒、局・点数OCR完了までさらに約2秒、打牌判断まで合計約7〜10秒であった。保存済み段位戦フレームを使った単独実測では、局・点数OCRが初回4966ms、ウォーム後3289/2658msだった。5秒操作期限で一律中断する主要因と照合できる。
- 相手の手番中のストリーム画面から局・点数OCRを別スレッドで先行させる。自手番では8秒以内の検証済み結果を、局・四家点数・本場/供託表示の画像が現在の画面と一致する場合のみ使用する。差があれば元の同期OCRへ戻し、先行認識がまだ動作中なら安全に再試行する。結果画面ではキャッシュを消す。保存済み画面の同局・異局の比較はそれぞれ一致・不一致となり、保存済み東2局画面での先行OCRは4871ms、キャッシュ適用は10msだった。
- `PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python.test_screen_state python.test_auto_operator` は160件中34件skipを除き成功した。これは処理時間改善の単体確認であり、300+0秒実戦回帰と短時間段位戦での有効打牌はまだ未確認。

## 2026-10-05 友人戦再試行時のアカウント利用停止

- 使用コミット `6925f35` の300+0秒CPU友人戦を準備したが、四人麻雀・CPU戦・一局戦・300+0秒の作成ボタンから部屋へ進まなかった。ブラウザ再読み込み後、ゲーム側が「対局を放棄する行為が頻繁に検出されたため」アカウントを **2026/10/05 14:52（JST）まで一時利用停止** と表示した。証跡は `artifacts/live/account-suspension-20261005.png`。このため新規対局は開始できず、回帰結果・段位戦成績の標本は得られていない。
- 先行する短時間段位戦では操作期限切れで39回打牌できず、対局自体は継続した。今回の制限と関連する可能性はあるが、ゲーム側が個別の原因対局を示していないため断定しない。解除後は300+0秒の回帰を完走し、打牌確認が取れる設定で段位戦を再評価する。制限中は再入場や追加の対局操作を行わない。

## c6ceee6 の300+0秒CPU友人戦回帰（完走、2位）

- 2026-10-05 14:52 JSTの制限解除後、同じYostarアカウントで再ログインできた。新規ルーム20598で四人CPU(簡単)・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を確認した。設定と開始前画面は `artifacts/friend-300-c6ceee6-room20598-20261005/preflight-settings.png` と `preflight-room.png`。使用コミットはpush済み `c6ceee6`。
- 開始前に操作者・認識サーバーがないことを確認し、`node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-c6ceee6-room20598-20261005 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` を一組だけ起動した。対局中はソース・設定を変更していない。
- `python-operator.jsonl` と19件のリプレイで牌認識・公開状態認識・判断・実クリック・手牌と河の変化による確認を記録した。19判断・19通常クリック・6反応操作、19件全て `deadlineMs=300000` と `deadlineMet=true`、最大 `evidenceToClickMs=12562`。`action_aborted`、`action_deadline_expired`、`safety_stop`、`own_discard_mismatch`、`own_discard_reconciliation_failed` は0。局・点数OCRの検証25件、公開情報キャッシュ更新44件を記録し、`match_completed_stop` で正常終了した。
- 終局画像 `artifacts/friend-300-c6ceee6-room20598-20261005/frames/2026-10-05T06-15-20.843948+00-00.match_result.png` は自家「テストjev」25000点・2位、CPUは30000/23000/22000点。この対局は最新修正の300+0秒での機能回帰合格であり、段位戦勝率評価には含めない。

## 2026-10-06 銅の間・四人東の障害試合（4位、勝率標本から除外）

- 使用コードはpush済み `e4e99e8`。`--ranked-loop --force-auto-click-budget-ms=2600 --action-deadline-ms=300000 --board-metadata --advance-screens --no-dashboard` で銅の間・四人東に入場した。アカウント段位「初心」で入場拒否はなかった。`artifacts/ranked-e4e99e8-copper-east-20261006/operator-stdout.log` と `operator-restart-stdout.log` に牌認識・公開状態・判断・クリック時刻・自己河照合を保存した。
- 最初の操作者は22打牌すべて期限内にクリックし、22件とも手牌と河の変化を確認したが、監視用の別Playwright/CDP接続後に実ブラウザの内側表示が `1920x1080` から `275x105` へ縮小した。操作者は `viewport restore failed` で安全停止した。ゲームは進行して離席自動ツモ切り画面になり、同一設定の操作者１系統だけで対局を復旧した。独立CDP接続が縮小の原因である可能性が高いが、CDPのどの操作が変更したかは未特定。以後の進行中対局の監視は操作者保存フレームを使用し、独立Playwright/CDP接続を避ける。
- 復旧後は21打牌をすべて期限内で確認した。２つの操作者ログに `action_deadline_expired` は0、`own_discard_mismatch` は合計7、`own_discard_reconciliation_failed` は合計11。終局画像 `artifacts/ranked-e4e99e8-copper-east-20261006/frames/2026-10-06T02-51-41.554923+00-00.match_result.png` では自家「テストjev」は4500点・4位・PT -35。離席自動打牌と操作停止が混入したため、段位勝率の有効標本から除外する。牌不一致も後続の敗因調査対象とする。
- 結果後、操作者は昇段ゲージ画面を `matchmaking` と誤分類し、`ranked_terminal_transition_stop` で停止した。再起動しても同じ画面を `matchmaking` として８分以上監視し、次の対局は始まっていなかった。実画面は `artifacts/live/ranked-rank-progress-20261006.png`。結果確認後の報酬画面は `artifacts/live/ranked-post-match-reward-20261006.png`。誤認識時の安全停止は放棄を防いだが、`--ranked-loop` の継続を妨げた。

## 昇段ゲージ画面の分類修正と300+0秒CPU回帰（完走、2位）

- 実際の昇段ゲージ画面では、従来の検出条件で使うシアン色の割合が0.009で、しきい値0.025を下回り、同じ画面が `matchmaking` に分類された。一方、四人順位画面の同領域は0.017である。シアン色だけの閾値を下げず、昇段ゲージ背後の右側盤面が暗い割合も条件に加えた。実画像を使うテストでは昇段ゲージが `rank_progress`、次の報酬画面が `post_match_reward` になり、`match_result` と区別できる。`PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python/test_screen_state.py python/test_auto_operator.py` は161件実行、34 skip、残り成功。
- コード修正後、コミット前の作業ツリー（基点 `e4e99e8`）で新規友人戦ルーム43851を作成。`artifacts/friend-300-rank-progress-fix-room43851-20261006/preflight-room.png` に四人CPU（簡単）・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を記録した。操作者は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-rank-progress-fix-room43851-20261006 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` を一系統だけ起動し、対局中にソース・設定を変更していない。
- `operator-stdout.log` と14件のリプレイに牌認識・公開情報・局点数認識・判断・実クリック・自己河確認を保存した。14判断・14打牌・5反応操作、14件すべて `deadlineMet=true`、最大 `evidenceToClickMs=9877`。`action_aborted`、`action_deadline_expired`、`safety_stop`、`own_discard_mismatch`、`own_discard_reconciliation_failed` は0。`match_completed_stop` により完走し、終局画面 `artifacts/friend-300-rank-progress-fix-room43851-20261006/frames/2026-10-06T03-21-45.460788+00-00.match_result.png` で自家24000点・2位、CPUは30000/24000/22000点だった。このCPU機能結果は段位勝率に含めない。

## 29a7a57 の銅の間・四人東（障害事例、4位）

- push済み `29a7a57`、`--ranked-loop --force-auto-click-budget-ms=2600 --action-deadline-ms=300000 --board-metadata --advance-screens --no-dashboard` で銅の間・四人東に入場。`artifacts/ranked-29a7a57-copper-east-20261006/operator-stdout.log` と26件のリプレイに牌認識・局点数・公開状態・判断・クリック時刻・自己河照合を保存した。26判断・26打牌は全て `deadlineMet=true`、最大 `evidenceToClickMs=20271`。ゲーム内の残り時間は3+5秒など短く、300000msの内部期限達成だけでは自動打牌を否定できない。
- `own_discard_mismatch` 6件、`own_discard_reconciliation_failed` 4件、`away_resumed` 3件、`action_aborted` 5件、`screencast_frame_rejected` 60件、内部期限切れ0件。監視側Playwright接続を行わない対局でも187x105/275x105/1920x733等の縮小フレームが出たため、先の「独立CDP監視が縮小の原因」という推定は確定できず、操作者のCDP/screencast経路も調査対象とする。終局画像 `artifacts/ranked-29a7a57-copper-east-20261006/frames/2026-10-06T03-46-41.649048+00-00.match_result.png` は自家15900点・4位・PT -24。捨て牌不一致と離席復帰が混入した障害試合として、有効な段位勝率標本には含めない。
- 終局画面から遷移中、段位ゲージを再び一時的に `matchmaking` と誤分類し `ranked_terminal_transition_stop` で停止した。停止後の実画面 `artifacts/live/ranked-rank-progress-after-stop-20261006.png` は `rank_progress` で、実際の新規マッチングではない。従来のシアン弧条件はアニメーション初期に満たされないため、黄色確認ボタンと暗い右側盤面を用いて検出する修正を行った。結果画面は明るい順位盤面なので区別できる。修正後の関連ユニットテストは162件、34 skip、残り成功した。

## 段位ゲージ初期アニメーション修正後の300+0秒CPU友人戦

- 修正作業ツリー（基点 `29a7a57`）で友人戦ルーム86076を作成。`artifacts/friend-300-rank-progress-arc-fix-20261006/preflight-room.png` は四人CPU（簡単）・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を示す。操作者は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-rank-progress-arc-fix-20261006 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` を一系統だけ起動し、対局中にソース・設定を変更しなかった。
- `operator-stdout.log` と30件のリプレイに牌認識・状態認識・判断・クリック位置・操作時刻・自己河照合を保存した。30判断・30打牌、全て `deadlineMet=true`、最大 `evidenceToClickMs=19323`。期限切れ・安全停止・離席復帰は0、`match_completed_stop` で完走した。終局画像 `artifacts/friend-300-rank-progress-arc-fix-20261006/frames/2026-10-06T04-12-57.879070+00-00.match_result.png` は自家32900点・1位、CPU26600/21400/19100点。このCPU結果は段位勝率に含めない。
- ただし `own_discard_mismatch` 1件と再照合失敗1件があった。初手フレーム `artifacts/friend-300-rank-progress-arc-fix-20261006/frames/2026-10-06T03-58-34.422670+00-00.jpg` のindex9には浮き上がった二索があるが、牌認識は同じ位置を南と読んだ（confidence 0.628）。クリック座標 `(1122.5,999)` の実捨て牌は二索で、牌認識の誤りを画像と自己河ログで裏付けた。操作者起動後に友人戦の開始ボタンを手動クリックした座標が手牌index9と重なり、開始前のポインター退避より後にホバーが残ったことが発生条件とみられる。原因別再現と再回帰が必要であり、この対局を牌認識まで正常な回帰標本とは扱わない。

## ポインター退避修正後の300+0秒CPU友人戦（ルーム86076、2回目）

- 基点コミット `29a7a57` の作業ツリーで、開始クリック後に操作者を起動した。四人CPU（簡単）・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。`artifacts/friend-300-pointer-retreat-room86076-r2-20261006/preflight-room.png` に開始直前の画面を保存。操作者設定は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-pointer-retreat-room86076-r2-20261006 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中のソース・設定変更や手動操作はしていない。
- `operator-stdout.log` と29件のリプレイに手牌・公開牌・局点数の認識、判断、クリック位置と時刻、自己河照合を保存。29判断・29打牌はすべて `deadlineMet=true`、最大 `evidenceToClickMs=27303`。期限切れ・安全停止・離席復帰は0、`match_completed_stop` で完走した。終局画像 `artifacts/friend-300-pointer-retreat-room86076-r2-20261006/frames/2026-10-06T04-37-45.229071+00-00.match_result.png` は自家20900点・4位、CPU33300/22900/22900点。このCPU結果は段位勝率に含めない。
- 初手フレーム `artifacts/friend-300-pointer-retreat-room86076-r2-20261006/frames/2026-10-06T04-21-23.682318+00-00.jpg` では手牌が浮かず、初手クリック後の自己河も一致。ポインター退避修正の発生条件に対する回帰は成功した。一方、`own_discard_mismatch` 1件と後続の再照合失敗1件が残った。東1局の `2026-10-06T04-28-41.919624+00-00.jpg` では手牌index9が東で、`(1122.5,999)` のクリック後、`2026-10-06T04-29-34.887164+00-00.jpg` の自己河の新牌も東と読める。しかし公開牌認識は北と返した。これは操作不一致ではなく、自己河の東を北と誤認した事例であり、認識原因の調査と再現テストが必要。牌認識まで完全な回帰標本とは扱わない。

## 自己河の切り出し閾値変更と300+0秒CPU友人戦（ルーム96794、1回目）

- 基点コミット `b5686c5` の作業ツリーで、自己河の輝度閾値を190から210に変更した。保存された東の画像 `artifacts/live/own-river-east-as-north-20261006.jpg` は、元の閾値で北（信頼度0.558）、210では東（0.561）となる。先の友人戦29判断フレームと段位戦26判断フレームを同じ認識器で再処理すると、東の訂正以外の自己河牌種は変わらなかった。`npm run build` と `test/publicTileRecognizer.test.ts` の26件が成功した。
- 新規ルーム96794は四人CPU（簡単）・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。画面 `artifacts/friend-300-own-river-threshold-room86076-r3-20261006/preflight-cpus.png` に設定と参加者を保存。操作者は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-own-river-threshold-room86076-r3-20261006 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` を一系統起動し、対局中のコード・設定変更、手動操作はしていない。
- `operator-stdout.log` と21件のリプレイに牌・状態認識、判断、クリック時刻、自己河照合を保存。21判断・21打牌すべて `deadlineMet=true`、最大 `evidenceToClickMs=20042`、期限切れ・停止・離席復帰は0。終局画像 `artifacts/friend-300-own-river-threshold-room86076-r3-20261006/frames/2026-10-06T05-11-45.722930+00-00.match_result.png` では自家27000点・2位、CPU31000/25000/17000点。CPU結果は段位勝率に含めない。
- `own_discard_mismatch` と後続の再照合失敗が各1件。手牌フレーム `2026-10-06T05-09-58.103315+00-00.jpg` は引いた八萬を示し、クリックはindex13の `(1532,999)`、後続フレーム `2026-10-06T05-10-41.203243+00-00.jpg` の自己河も八萬。しかし公開牌認識は六萬（信頼度0.535）と返した。東の例と同じく、実操作ではなく狭い切り出しでの低信頼度な自己河認識が原因。輝度210だけでは回帰を満たさなかった。

## 自己河の低信頼度牌だけ拡張再判定した300+0秒CPU友人戦

- 東と八萬の保存画像を比較すると、自己河の明るい領域だけを切ると各々北/六萬、周囲を4px広げると東（信頼度0.863）/八萬（0.967）となった。一方、すべての牌を4px広げると既存の赤五萬が別牌になるフレームがある。そこで自己河で元の信頼度0.7未満の場合だけ拡張し、拡張後が0.8以上、改善幅0.15以上、次点との差0.5以上の場合だけ置換する。保存画像の実認識テストでは東と八萬を正しく読み、赤五萬を保持した。`npm run build` と `test/publicTileRecognizer.test.ts` の26件が成功した。
- 基点コミット `b5686c5` の作業ツリーで同じルーム96794、四人CPU（簡単）・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。`artifacts/friend-300-own-river-padding-20261006/preflight-room.png` に設定と参加者を保存。操作者は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-own-river-padding-20261006 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` を一系統起動し、対局中のコード・設定変更と手動操作はしていない。
- `operator-stdout.log` と7件のリプレイに牌・状態認識、判断、クリック時刻、自己河照合を保存。7判断・7打牌はすべて `deadlineMet=true`、最大 `evidenceToClickMs=23444`。期限切れ・`own_discard_mismatch`・再照合失敗・安全停止・離席復帰は0。`match_completed_stop` で完走し、終局画像 `artifacts/friend-300-own-river-padding-20261006/frames/2026-10-06T05-26-09.544571+00-00.match_result.png` は自家16000点・4位、CPU34000/25000/25000点。このCPU機能結果は段位勝率に含めない。7打牌の回帰は狭い事象確認であり、十分な勝率標本でも短い段位戦時計の証明でもない。
- 直近の銅の間・四人東ログでは26打牌中6件の `evidenceToClickMs` が8秒を超え、最大20271msだった。段位戦の3+5秒表示と比較すると、内部期限300000msを守ってもゲーム内自動打牌が起こりうる。段位戦再開前の操作速度改善を別途検証する。
## 公開牌スキャンの重複画面分類を省いた300+0秒CPU友人戦（ルーム59748）

- 基点コミット `c5b58fa` の作業ツリーで、主ループが同じフレームを `match` と判定済みの場合に公開牌スキャン側で再分類しない変更を試した。保存済み段位戦フレームでは `classify_screen` の中央値が約480ms（6回計測）で、主ループとスキャンで同じ画像を分類していた。公開牌スキャンは1920×1080の画像寸法を引き続き確認し、未検証画面では従来通り分類する。
- 2026-10-06のルーム59748は四人CPU（簡単）・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。設定と全参加者は `artifacts/friend-300-classification-reuse-room59748-20261006/preflight-room.png`。操作者は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-classification-reuse-room59748-20261006 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` を一系統のみ起動。対局中のソース・設定変更と手動操作はしていない。
- `operator-stdout.log` と50件のリプレイに牌・状態認識、判断、クリック時刻・座標、自己河照合を保存。50判断・50打牌は全て `deadlineMet=true`、中央値 `evidenceToClickMs=9542.5`、最大17711ms。`own_discard_mismatch`、再照合失敗、`action_aborted`、期限切れ、離席復帰、安全停止は0。サイズ不一致のscreencastフレームは117件拒否したが操作者は停止せず、`match_completed_stop` で完走した。
- 終局画像 `artifacts/friend-300-classification-reuse-room59748-20261006/frames/2026-10-06T06-29-29.506338+00-00.match_result.png` は自家「テストjev」24000点・3位、CPU35900/25000/15100点。CPU戦の機能回帰であり段位勝率には含めない。50打牌中46件が8秒を超えたため、この小変更だけでは段位戦の3+5秒時計に十分でない。自己河の二回照合待ちと残る主ループ処理時間を引き続き分解し、短時間で有効打牌できる証拠が出るまで段位戦を再開しない。
- `PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python.test_auto_operator -q` は156件中34件skipを除き成功、`npm run build` と `git diff --check` も成功。全Pythonテストは195件中、変更箇所とは無関係な `test_board_metadata.BoardMetadataTest.test_room_74709_zero_score_frame_recovers_with_conservation` の参照画像 `artifacts/friend-300-628c989-room74709-20261003/frames/2026-10-02T15-51-12.615825+00-00.jpg` が存在せず1件失敗した。既存の証跡欠落として記録し、この変更のために当該テストを変更しない。

## 結果画面判定の画像演算高速化と300+0秒CPU友人戦（ルーム59748、再戦）

- 基点コミット `a8e74a3` の作業ツリーで、段位結果と段位ゲージの色割合判定を、同じしきい値のままPillowの画像演算へ置き換えた。保存済み対局フレームで `classify_screen` の中央値は旧454.5ms、新79.3ms（各8回）。保存フレーム74枚で旧実装と新実装の分類差は0件。`PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python.test_screen_state python.test_auto_operator -q` は164件中34件skipを除き成功した。
- 同じルーム59748で、四人CPU（簡単）・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を再確認した。設定と全参加者は `artifacts/friend-300-fast-screen-state-room59748-20261006/preflight-room.png`。操作者は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-fast-screen-state-room59748-20261006 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` を一系統のみ起動し、対局中のソース・設定変更と手動操作はしていない。
- `operator-stdout.log` と20件のリプレイに牌・状態認識、判断、クリック時刻・座標、自己河照合を保存した。20判断・20打牌すべて `deadlineMet=true`、`evidenceToClickMs` 中央値9013.5ms、最大13611ms、8秒超13件。`own_discard_mismatch`、再照合失敗、`action_aborted`、期限切れ、離席復帰、安全停止は0。サイズ不一致のscreencastフレーム36件を拒否して操作者は停止せず、`match_completed_stop` で完走した。
- 終局画像 `artifacts/friend-300-fast-screen-state-room59748-20261006/frames/2026-10-06T07-00-03.669595+00-00.match_result.png` は自家「テストjev」18500点・3位、CPU46000/18500/17000点。これはCPU機能回帰であり段位勝率に含めない。画面分類は実測で速くなったが、20打牌中13件が8秒超で、盤面OCRの同期実行と自己河二回確認が残る。短時間段位戦は引き続き保留する。
## ef81effの誤終局停止修正と300+0秒CPU回帰（完走、3位）

- 銅の間・四人東の実戦で、局結果の後に進行中の卓フレームを `matchmaking` と誤分類し、`ranked_terminal_transition_stop` が東3局・残り66枚で発火した。画面 `artifacts/live/167e2fb-ranked-terminal-20261003.png` は東3局の継続を示す一方、初回ログには停止イベントがあり、これは操作者停止の直接証拠である。復旧後の最終実画面 `artifacts/live/167e2fb-ranked-recovery-terminal-20261003.png` は自家23500点・3位・PT -6だが、停止期間と公開河照合不一致があるため段位戦の勝率標本から除外する。
- `ef81eff` は局結果 `round_result` で段位戦の終局遷移ガードを立てず、確認済みの `match_result` / `rank_progress` / `post_match_reward` だけを停止対象にした。新局の閉じた手牌を確認した場合も残存ガードを解除する。東1局結果の後に東2局中フレームが `matchmaking` と誤分類されても停止しない回帰を追加した。`PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python/test_auto_operator.py` は154成功・33 skip。
- 新規友人戦部屋66121は四人CPU戦・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効である。設定証跡は `artifacts/live/ef81eff-friend-room-20261003.png`。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-ef81eff-room66121-20261003 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。開始前にNode/Python PIDを確認し、対局中にコード・設定を変更していない。
- 28打牌・9反応操作で `match_completed_stop confidence=1.0` により完走した。全アクションは明示的な300000ms期限内で、`own_discard_mismatch`、`own_discard_reconciliation_failed`、`action_aborted`、期限超過、`safety_stop` はすべて0。終局画面 `artifacts/friend-300-ef81eff-room66121-20261003/frames/2026-10-03T05-02-44.386064+00-00.match_result.png` は自家「テストjev」23500点・3位、CPU31400/23500/21600点を示す。この結果は終局遷移・牌認識・状態認識・操作経路のCPU機能回帰であり、段位戦の勝率評価とは明確に分離する。

## b665727の副露中「局結果」誤判定修正と300+0秒CPU友人戦（ルーム12868、完走、1位）

- ルーム73637の初回再開中、実卓（東1局・残り57枚・自家副露後）を `round_result` と判定して `round_terminal_wait` を繰り返した。保存フレーム `artifacts/friend-300-eaacede-room73637-20261011/frames/2026-10-11T08-17-50.273158+00-00.round_result.png` とログを照合すると、局結果確認ボタンの緩い青色条件が右下の副露牌と卓背景を拾っていた。停止・復旧が混入した73637はクリーンな回帰結果から除外する。
- `b665727` は確認ボタンに飽和した青色を必須にし、さらに閉じた13牌列または副露を含む実手牌ジオメトリが見える場合は `round_result` を拒否する。保存フレームを `match` とする画面分類テスト、および実際の局結果画面では拒否しないテストを追加した。`PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python.test_screen_state python.test_auto_operator -q` は167件成功、33件skip。
- 新規ルーム12868は四人CPU（簡単）・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。開始前の設定・参加者は `artifacts/live/b665727-friend-room-20261011.png`。操作者は一系統だけ、`node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-b665727-room12868-20261011 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` で起動し、対局中にコード・設定を変更していない。
- 東1局（流局）から東2局を経て `match_completed_stop confidence=1.0` で完走した。26判断、26通常クリック、16アクションボタン操作、13回の副露手牌ジオメトリ検出を記録し、期限超過・安全停止・`round_result_rejected_live_table` は0。終局画像 `artifacts/friend-300-b665727-room12868-20261011/frames/2026-10-11T09-08-26.528559+00-00.match_result.png` は自家「テストjev」31500点・1位、CPU25000/25000/18500点を示す。一方で自己河の `own_discard_mismatch` と再照合失敗が各1件、行動中止が1件あるため、当該経路は後続調査対象として残す。このCPU対局は終局誤判定修正の機能回帰であり、段位戦の勝率標本には含めない。

## 2026-10-11 銅の間の短時間操作予算障害と安全停止

- push済み `fc524df` は、force-auto の評価に使ったscreencastフレームの受信時刻を引き継ぎ、`--force-auto-click-budget-ms=2600` では打牌・リーチ選択直前にフレーム年齢を再確認する。2600ms以上なら `force_auto_click_budget_expired` としてクリックせず `RetryableSafetyAbort` で再観測する。リーチはボタン領域差分だけでなく、手牌変化、灰色の選択UI、`match` 状態の三条件がそろう場合だけ確認済みとする。統合ユニットテストは172成功、33 skip。
- 銅の間・四人東の既存続行局を `artifacts/ranked-fc524df-copper-east-recovery-20261011` で再開した。起動設定は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/ranked-fc524df-copper-east-recovery-20261011 --ranked-loop --action-deadline-ms=300000 --force-auto-click-budget-ms=2600 --board-metadata --advance-screens --no-dashboard`。同ログでは評価フレーム年齢が 5636--7683ms で、各回 `force_auto_click_budget_expired` と `action_aborted` が記録され、対応する打牌 `click_sent` はない。旧来の6--14秒後の古い打牌を再発させなかった直接証拠である。
- ただし期限超過後に `--resume-away` が離席ダイアログを再開し続け、`away_resumed` が繰り返された。さらにranked-loopが新規局を開始したため、操作者を停止した。この続行局と後続局は、離席自動ツモ切り・停止・復旧が混入しており、段位戦の勝率標本から除外する。遅延分析では、旧ログ120判断のcapture age中央値2644ms、認識・判断処理中央値1153ms、証拠から判断中央値3265ms、判断からクリック中央値3083msであり、2600ms内の有効打牌を満たしていない。
- push済み `fd33dd9` はranked-loopに限り、連続3回のクリック予算超過で `ranked_click_budget_safety_stop` を記録して、離席ダイアログに触れずrun loopを終了する。実地確認 `artifacts/ranked-fd33dd9-budget-stop-20261011/python-operator.jsonl` では3回目（frame age 5893ms）に同イベントが記録され、プロセスは終了した。安全停止前に反応パスが `evidenceToClickMs=6994` でクリックされたことを発見したため、この試行も勝率標本から除外する。
- push済み `c2a582e` は反応のpass・鳴き・ronにも同じcapture時刻予算チェックを追加した。2600msを超える反応評価はクリック前に中止する。`PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python.test_auto_operator python.test_screen_state -q` は179成功、33 skip。短時間の段位戦を再開する前に、最新コミットで300+0秒CPU友人戦を完走し、短時間操作速度の根本改善も別途必要である。
- push済み `285f1c8` はCDPフレーム受信時刻でframe ageを計算し、force-autoの手牌認識を始める前に2600ms予算を使い切ったフレームを `recognition_deferred_stale_capture` として再観測する。クリック直前の保護は残す。click budget未指定の300+0秒経路には影響させない。統合テストは180成功、33 skip。これは期限超過後の無駄な認識を削る安全な前処理であり、2600ms内の有効打牌達成はまだ実地で確認していない。

## 2026-10-11 反応パス鮮度修正と300+0秒CPU復帰局

- 新規CPU友人戦ルーム35795は四人麻雀・一局戦・CPU戦・300+0秒で、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。作成画面は `artifacts/live/285f1c8-friend-create-20261011.png`、ルーム設定は `artifacts/live/285f1c8-friend-room-20261011.png`。初回 `6a1a888` の操作者は明示的な `--action-deadline-ms=300000 --force-auto-click-budget-ms=8000` で一系統だけ起動した。
- 初回は反応passで、独立に最新ボタンを安定確認済みであるにもかかわらず、古い評価フレーム時刻（10--11秒）を8秒予算と比較して繰り返し中止した。これは `artifacts/friend-300-6a1a888-room35795-20261011/python-operator.jsonl` の `reaction_pass_deferred` と `force_auto_click_budget_expired` にある。停止前には手牌変化による中止1件、反応鳴き候補の安全中止、通常打牌・副露・自己河照合を確認したが、この初回は完走しなかった。
- push済み `1ae7770` はpassだけ、クリック直前の安定ボタン再確認で取得した新鮮な時刻から予算を測るよう修正した。鳴き・ロンは依然として評価フレームの鮮度を必須にする。統合テスト `PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python.test_auto_operator python.test_screen_state -q` は180成功、33 skip。
- 同ルームの復帰実行 `artifacts/friend-300-1ae7770-room35795-recovery-20261011` は同じ300+0秒／300000ms期限／8000ms予算で、遅延していたpassを `action_click_sent` として一度だけ確認し、その後通常打牌へ復帰して `match_completed_stop` で完走した。終局画像は `frames/2026-10-11T12-35-18.022897+00-00.match_result.png`、自家24000点・3位。復帰ログには13通常打牌、2反応ボタン操作、1件の期限超過打牌中止、1件の期限超過鳴き中止がある。初回停止の前に発生した自己河不一致（期待二萬、観測八萬）と再照合失敗、および途中再起動が混入したため、この対局はクリーンなCPU回帰標本・段位勝率標本から除外する。新規クリーンCPU戦で再検証が必要である。

## 2026-10-11 1ae7770のクリーン300+0秒CPU回帰（ルーム35795、完走）

- 同じ設定の空ルーム35795を再利用し、途中操作・再起動なしで `83d310a`（コードは `1ae7770` を含む）の操作者を一系統だけ起動した。実行は `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-83d310a-room35795-clean-20261011 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。設定証跡は `artifacts/live/285f1c8-friend-room-20261011.png` にあり、四人CPU・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効を示す。対局中にコード・設定変更や手動操作はしていない。
- `match_completed_stop confidence=1.0` で完走。51通常打牌、22反応ボタン操作、52リプレイを保存し、自己河の `own_discard_mismatch` と `own_discard_reconciliation_failed`、`safety_stop`、`away_resumed` は全て0だった。手牌変化による安全中止は1件。反応鳴き候補は9件が8秒の鮮度予算（8103--8230ms）を超えてクリック前に中止され、遅い鳴き・ロンを誤操作しなかった。通常打牌の`evidenceToClickMs`は平均8713.9ms、最大16783msで、これは300秒設定では動作したが、銅の間の短時間要件を満たす証拠ではない。
- 終局画面 `artifacts/friend-300-83d310a-room35795-clean-20261011/frames/2026-10-11T13-02-27.885527+00-00.match_result.png` は自家「テストjev」25000点・3位、CPU37600/26000/11400点。これは鮮度保護、反応pass、状態遷移、副露を含むCPU機能回帰の成功記録であり、段位勝率評価には含めない。

## 2026-10-15 段位戦再開の事前確認（入場不可）

- 実行環境のブラウザが停止していたため、既存プロファイルを使ってheadless Chromiumを復旧した。`libnspr4.so` が標準探索パスにないため、ローカルの `~/.local/share/jantama-auto/chromium-libs/usr/lib/x86_64-linux-gnu` を `LD_LIBRARY_PATH` に加えて起動した。CDP `127.0.0.1:9222` へ接続し、ログイン済みの自家「テストjev」と、操作者プロセスおよび進行中の対局がないことを確認した。
- ホームを覆っていた「累計参拝報酬」は未受領の1回分を受け取り、確認後に閉じた。対局設定は変更していない。ロビーと銅の間選択の証跡はそれぞれ `artifacts/live/b2a16a7-lobby-unblocked-20261015.png`、`artifacts/live/b2a16a7-copper-menu-20261015.png`。
- 銅の間を選ぶとゲームは「現在の段位では入場不可。適した部屋に参加しましょう。」と表示した。証跡は `artifacts/live/b2a16a7-copper-menu-20261015.png` と `artifacts/live/b2a16a7-novice-ranked-menu-20261015.png`。アカウント表示は「初心」であり、キュー投入も操作者起動もしていない。このため今回の段位戦結果・勝率標本は0件で、入場制限を回避する操作は行わない。
- 直近の300+0秒CPU機能回帰は成功している一方、通常打牌の平均 `evidenceToClickMs=8713.9` が短時間段位戦用2600ms予算を満たす根拠はまだない。入場可能になった場合も、最初に一局だけ `--ranked-loop --action-deadline-ms=300000 --force-auto-click-budget-ms=2600` を明示して実行し、旧いフレームによるクリック、離席復帰、自己河不一致がないかを段位結果とは別に照合する。

### 銅の間・四人東の実選択、操作安全停止、アカウント停止

- 上の「入場不可」は銅の間ではなく、段位一覧で誤って y=750 の金の間を選んだときのメッセージだった。段位一覧へ戻り、銅の間（y=410）を選択してから、同室内の四人東（y=410）を選択すると `予約中` となった。証跡は `artifacts/live/48925ca-copper-preflight-20261015.png`、`artifacts/live/48925ca-copper-east-selected-20261015.png`。この訂正後は銅の間への入室に成功しており、アカウント段位を理由とする入場拒否は確認されていない。
- 使用コードはpush済み `48925ca`。操作者は一系統だけ、`node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/ranked-48925ca-copper-east-20261015 --ranked-loop --action-deadline-ms=300000 --force-auto-click-budget-ms=2600 --board-metadata --advance-screens --no-dashboard` で開始した。ログには `click_sent` / `action_click_sent` / 自己河照合イベントが0件で、最初の2局面でキャプチャ年齢2981ms、2998ms、3137msを測定して `force_auto_click_budget_expired` が3件、3件目で `ranked_click_budget_safety_stop` が1件ある。したがって、操作はすべてクリック前に中止され、誤打牌は送られていない。
- 安全停止後は離席自動ツモ切りに移行したため、再開・再起動・対局中のコードや設定変更は行わず、終局まで待機した。最終表示は自家3位・PT -8だが、操作者停止後の自動ツモ切りが混入しているため、段位戦の勝率標本から除外する。終局結果とゲーム側のダイアログは `artifacts/live/48925ca-ranked-state-recheck3-20261015.png` に保存され、「エラーコード: 503 このアカウントは利用停止されています」と明示された。
- アカウント停止中は対局キュー、再開ボタン、段位画面の再試行を行わない。解除後に、ストリームフレームの鮮度予算を使い切る前に実行される画面判定・公開情報処理をプロファイルし、根拠に基づく修正を300+0秒CPU友人戦（`--action-deadline-ms=300000`）で完走確認してから、2600ms予算の銅の間へ戻る。

## 36876de の段位戦前処理重複削減（アカウント停止中のオフライン検証）

- 段位戦の実フレーム `artifacts/ranked-48925ca-copper-east-20261015/frames/2026-10-15T07-22-47.536959+00-00.public-cache.jpg` を再計測した。CDPゲート側では画面分類約297ms、鳴きボタン走査約336ms、自己アクション走査約166msを行った後、同じバイト列に対して通常経路で分類約126ms、鳴き走査約325ms、自己アクション走査約153msを再実行していた。後半の重複は約0.6秒で、2600ms予算では無視できない。
- `36876de` は、CDPゲートで既に `match` と確認した**同一フレーム**に限って、後段の画面分類と反応ボタン走査を再利用する。同期再撮影・異なるフレームは従来どおり独立検査し、クリック直前の鮮度・手牌・自己河確認も変更していない。これは停止を無効化する変更ではなく、同じ安全根拠を二度計算しない最適化である。
- `PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python.test_auto_operator python.test_screen_state -q` は180件成功、33件skip。ゲーム側の503利用停止が継続しているため、修正後の300+0秒CPU友人戦および銅の間の実機検証は未実施であり、勝率改善の根拠にはしない。
- 同じ実フレームを常駐認識器へ単独再投入すると、14牌のテンプレート認識とローカル判断の `processingElapsedMs` は1236ms（Jevなしのローカルfallback 25msを含む）だった。先行ゲートの重複削減前測定は約1.7秒であり、重複除去後も2600ms内のクリックを実証するには認識側の高速化が必要である。これは画像推測ではなく、サーバー返却の実測値に基づく次の調査対象とする。

## 2026-10-15 段位戦前の短時間練習ゲート

- 段位戦に入る前に、友人戦の「5+20」設定で短時間操作の実戦練習を追加する。順序は、修正後の300+0秒CPU友人戦（機能回帰、`--action-deadline-ms=300000`）を完走し、その後5+20で操作鮮度・自己河照合・離席停止がないことを確認してから、銅の間を `--ranked-loop --force-auto-click-budget-ms=2600` で開始する。
- 5+20の結果はCPU友人戦の練習・操作評価として記録し、300+0機能回帰および段位戦勝率のいずれとも混同しない。現在はゲーム側の503利用停止中のため、作成・予約・再入場を試行していない。解除後に設定画面、使用コミット、操作ログ、最終結果を保存して実施する。

## 2026-10-15 利用停止期限の再確認

- 保存済みログイン画面を再確認し、停止理由は「対局を放棄する行為が頻繁に検出されたため」、表示された解除時刻は **2026/10/15 18:39（JST）** であることを確定した。証跡は `artifacts/live/d486ef4-auto-login-settled-20261015.png`。現在はブラウザだけがこのダイアログを表示しており、操作者・認識サーバー・進行中対局はいずれもない。
- この期限まで対局キュー、友人戦作成、ログイン再試行を行わない。解除後は、最新コードで300+0秒CPU機能回帰（`--action-deadline-ms=300000`）、5+20練習、2600ms銅の間の順に再開する。

## 段位戦フレームのテンプレート認識重複計算削減（オフライン）

- 保存済み段位戦フレーム `artifacts/ranked-48925ca-copper-east-20261015/frames/2026-10-15T07-22-47.536959+00-00.public-cache.jpg` をCPUプロファイルした。段位用レイアウトは `raw` マッチャーで既に4クラスへ候補を絞っている一方、採用されない候補についても25オフセットのコサイン信頼度を計算していた。この値は返却されず、牌の選択・マージン・安全判定にも影響しない。
- `templateMatcher.ts` では、従来と同じ識別スコアで勝者とマージンを決めた後、勝者の3テンプレート候補だけでコサイン信頼度を計算するようにした。保存フレームの認識牌列、confidence `0.5142128845106297`、ambiguityMargin `0.07096426514411319`、`safe=false` は変更前後で同一である。認識サーバーの `processingElapsedMs` は1236msから944msへ短縮した。
- `npm run build`、`npm test -- --runInBand test/pipeline.test.ts test/recognitionImprovements.test.ts`、`git diff --check` は成功した。これはオフライン最適化であり、利用停止中のため300+0秒CPU回帰・5+20練習・段位戦の結果や勝率には含めない。

## CDPゲート鮮度の計測追加（利用停止中）

- 既存の銅の間ログでは、3回の `recognition_deferred_stale_capture` が認識開始前のキャプチャ年齢2981ms、2998ms、3138msを記録している。一方で認識器の最適化後単体処理は944msであり、残りの短時間予算障害を画像から推測してはならない。
- 次の実機回帰で原因を分離するため、同イベントへ `gateTiming` を追加した。CDPフレーム受信時の年齢、画面分類・鳴き/自己アクション・手牌形状を含むゲート走査時間、認識直前までの合計時間を記録するだけで、ゲート・クリック・安全停止の条件は変更していない。
- `PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python.test_auto_operator python.test_screen_state -q` は180件成功、33件skip、`git diff --check` は成功した。解除後の300+0秒CPU回帰で測定値を取得してから、同一フレームの安定確認や同期処理を変更する。

## CDPゲートの同一フレーム安定化を禁止

- 旧実装は同じ `screencast_sequence` のままでもループごとに安定フレーム数を増やせた。その結果、最初のフレームを受信してからゲート処理中に数秒経過しても、同じ画像を認識へ渡しうる。これは2981--3138msの認識開始前キャプチャ年齢と整合する実装上の経路である。
- `auto_operator.py` は、同じシーケンスなら新しいCDPフレームを待つようにした。5回の短いポーリングでストリームが沈黙している場合だけ、既存の安定したスクリーンショット再撮影を使う。したがって、二重の安定確認は異なるフレーム受信または再撮影済みフレームにのみ基づく。クリック条件・2600ms安全停止・離席処理は変更していない。
- `PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python.test_auto_operator -q` は171件成功、33件skip、`python.test_screen_state` は9件成功、`git diff --check` は成功した。利用停止中のため実機300+0秒回帰は未実施であり、解除後に新しい `gateTiming` とともに検証する。

## 2026-10-16 fe9c3b4 の300+0秒CPU友人戦（完走、鮮度超過の診断標本）

- 利用停止解除後にYostarログインを復旧し、友人戦ルーム53493を新規作成した。開始前の画面は `artifacts/live/browser-recovery-20261016/friend-300-room-created.png`、設定は四人麻雀・CPU戦（簡単）・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効である。使用コミットはpush済みの `fe9c3b4`。開始前に操作者・認識サーバーの不在を確認した。
- 操作者は一系統だけ `node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-fe9c3b4-room53493-20261016 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` で起動した。対局中にコード・設定・操作者構成を変更していない。`match_completed_stop confidence=1.0` で完走し、終局画像 `frames/2026-10-16T01-35-40.008965+00-00.match_result.png` は自家「テストjev」30500点・1位、CPU27000/24000/18500点を示す。CPU友人戦結果であり、段位戦勝率には含めない。
- `python-operator.jsonl` は23判断・23打牌・12反応操作・23リプレイを記録した。判断23件はすべて `deadlineMs=300000` と `deadlineMet=true`（`evidenceToClickMs` 5297--10033ms、平均7165ms）。自己河の `own_discard_mismatch`／`own_discard_reconciliation_failed` はともに0、副露手牌ジオメトリ17件、鳴き牌と河の `called_river_reconciled` 1件を確認した。残り山・局点数・供託もログで更新された。
- 東2局で立直ボタンを送信した後、打牌前のキャプチャ年齢が10590msとなり、`force_auto_click_budget_expired` と `action_aborted` が各1件発生した。古いフレームの打牌は送信されず、後にゲーム側の時計で局面が進行した。この安全中止と一時的な自動進行が混入するため、最新修正のクリーンな300+0秒機能回帰合格とは扱わない。根拠は画像だけでなく同ログのクリック、期限、自己河、副露・河照合イベントである。5+20練習と銅の間は、この鮮度超過の原因をログから再現・修正し、改めて300+0秒をクリーンに完走してから実施する。

## 2026-10-16 立直選択UIの鮮度基準修正と300+0秒CPU再回帰

- 上記の立直後中止は、`post_riichi_full` で確認済みの選択UIを取得済みにもかかわらず、後続の牌選択予算が立直前の `evaluated_captured_at` を使い続けたことが直接原因だった。`2c8472a` は、force-autoで立直宣言の確認後に同期取得し、match画面かつdimmed選択UIであることを確認したフレームだけを後続捨て牌予算の基準にする。未確認の立直と他アクションの基準は変更しない。新規テストは、旧評価から5秒経過後でも確認済み選択UIから2.5秒なら2600ms予算内で立直→打牌が可能で、期限切れを出さないことを確認する。`PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python.test_auto_operator -q` は172件成功・33件skip、`git diff --check` は成功し、変更はコミット・push済み。
- 同じCPU友人戦ルーム53493を新規開始し、使用コミット`2c8472a`で `--action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` を一系統だけ実行した。終局画像 `artifacts/friend-300-2c8472a-room53493-r2-20261016/frames/2026-10-16T01-50-33.294056+00-00.match_result.png` は自家30200点・1位、CPU25000/25000/19800点、操作者は `match_completed_stop` で終了した。これはCPU機能確認であり、段位戦勝率には含めない。
- 実機で立直 `action_click_sent`（01:49:59.769Z）の後に選択牌2sの `click_sent`（01:50:02.665Z）まで到達し、前回の「立直後に古い基準で打牌を遮断する」事象は再発しなかった。12判断・12打牌・7反応操作・12リプレイ、300000ms期限超過0、自己河不一致0、再照合失敗0である。
- ただし直前に、8.17ms/8.22msではなく **8167ms/8221ms** の古い評価フレームを2回 `before_action_button_click` で安全中止して再観測した。旧フレームのクリック、離席、自己河不一致はないが、この中止があるためクリーンな300+0秒合格および5+20/2600ms段位戦の開始根拠にはしない。小さいiframe/高さ808pxのscreencastフレームが続く時の、次の有効フレーム取得までの遅延を別途測定・改善する。

## 不正寸法screencastの受信時刻失効

- `2c8472a` 実機の8167/8221ms中止を時系列で確認した。最初の有効ゲートフレーム受信から評価フレーム保存まで約3.35秒、局・点数OCRに約1.16秒、その後の認識・判断・事前確認を含めて8221msとなった。小さい174x98/233x98と高さ808pxのフレームは認識中に到着しており、直接の期限超過原因は同期評価経路の遅延である。したがって、これらを削るだけで2600msを達成できるとは扱わない。
- ただし、不正寸法フレームを受けた既存コードは `latest_screencast_frame` とdraw状態を消す一方で、そのフレームの受信時刻を残していた。`bf05e6b` は同時に `latest_screencast_captured_at` も`None`へ失効させ、無効なストリーム画像と古い時刻を後続のfallbackへ混在させない。回帰テストは不正寸法受信後に画像・時刻・draw状態が揃って失効することを確認する。
- `PYTHONPATH=python .runtime/python-auto-venv/bin/python -m unittest python.test_auto_operator -q` は172件成功・33件skip、`git diff --check` は成功し、変更はコミット・push済み。次の300+0秒実機では、このfail-closed修正の回帰と評価経路の各時間を分離して確認する。5+20練習と銅の間は依然保留する。

## 2600ms段位戦予算の経路プロファイル

- `friend-300-2c8472a-room53493-r2-20261016` の実測では、盤面OCRのウォーム後時間は1239--1321ms、同一フレームの常駐認識器による手牌認識と判断は1025ms、対局中の認識・判断処理は1220--1530msだった。従って盤面OCRと認識判断の直列だけで約2460--2850msとなり、2600ms予算にはクリック前の安全確認を残せない。`actionTiming.decisionToClickMs` は認識前から測るため、単純に「判断後3秒」と解釈せず、個別計測と照合した。
- 既存のboard metadataキャッシュ候補3組は、HUD差分が最大15.4/22.4など厳格な適用閾値（3）を超えて全て不適用だった。閾値を緩めるとscoreやremainingTilesを古い画面から再利用し、残り山0枚の安全条件を壊し得るため実装しない。
- 2600msを安全に達成するには、OCRと手牌認識を並列で実施してメタデータ投入済み状態だけを後段で判断するプロトコル分割、または静的HUDをキャッシュしremainingTilesだけを現フレームで厳格認識する専用経路が必要である。いずれも小さな閾値変更ではなく、追加の設計・再現テスト・300+0秒回帰を要する。根拠のない高速化はせず、5+20練習および銅の間は保留する。

## 2026-10-16 aa5dfd4 の並列認識と300+0秒CPU回帰

- push済み `aa5dfd4` は、resident recognizer 内で同一スクリーンショットのSHA-256とレイアウト文脈に束縛した手牌認識だけを後段評価に渡す。盤面OCRと手牌認識を並列化し、公開情報キャッシュの署名照合は変更していない。`npm run build`、recognition server staged-digest test、Python操作者173件（33 skip）、`git diff --check` を通過した。
- ルーム53493（四人CPU・簡単・一局戦・300+0秒、開始25000、返し30000、飛び・赤3・喰い断・一翻縛り有効）で、`--action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` を一系統だけ実行した。成果物は `artifacts/friend-300-aa5dfd4-room53493-20261016`。対局中のコード・設定変更はない。
- `match_completed_stop` で完走。結果画面は `frames/2026-10-16T02-26-47.255346+00-00.match_result.png`（自家25000・3位、CPU37000/25000/13000）。11判断・11通常打牌、自己河不一致と再照合失敗は0。初手に手牌同一性確認の不一致で安全中止が1回あり、古いクリックは送信されず再観測後に継続した。よってCPU機能回帰の実行証跡ではあるが、5+20および2600ms段位戦へ進むためのクリーンな鮮度合格とは扱わない。

## 2026-10-16 3170364 の字形同一性確認と300+0秒CPU回帰

- push済み `3170364` は、閉じた手牌のフォールバック確認を別プロセスのhybrid再認識から14枠の字形比較へ置換した。実際の前回不一致はindex 9の牌面差分41.096であり安全中止は維持する。Python操作者テスト173件成功（33 skip）。
- ルーム53493で同一の四人CPU・一局戦・300+0秒設定を用い、`--action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` を一系統だけ実行。成果物は `artifacts/friend-300-3170364-room53493-20261016`。46リプレイ、45判断・45通常打牌、13アクション操作を記録し、`match_completed_stop` で完走した。結果画面は `frames/2026-10-16T02-51-05.301776+00-00.match_result.png`（自家24500・4位）。これはCPU機能回帰であり段位勝率には含めない。
- 自己河不一致・再照合失敗・クリック予算超過は0。初手には牌面差分2.141で安全中止が1回あり、古いクリックは送信されなかった。従って修正は誤認識由来の中止を除去したが、実際の局面変化を安全に中止できることも確認した。短時間2600msでは通常打牌の実測が約5--11秒であり、5+20および段位戦へはまだ進めない。

## 2026-10-16 3fa1156 の並列経路計測と300+0秒CPU回帰

- ルーム53493で、四人CPU（簡単）・一局戦・300+0秒、開始25000点、返し30000点、飛び有効、赤ドラ3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効のまま、push済み `3fa1156` を使用した。操作者は一系統のみで、`node scripts/run-operator.mjs force-auto --layout=config/layout-300-regression.json --artifacts=artifacts/friend-300-3fa1156-room53493-20261016 --action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard` を実行した。対局中にコード、設定、操作者構成の変更や手動操作は行っていない。
- `match_completed_stop confidence=1.0` で完走し、62判断・62通常打牌・20アクション操作・62リプレイを保存した。終局画面 `artifacts/friend-300-3fa1156-room53493-20261016/frames/2026-10-16T03-16-13.097090+00-00.match_result.png` は自家「テストjev」25400点・2位（CPU32500/21500/20600）を示す。これはCPU友人戦の機能回帰であり、段位戦の勝率標本には含めない。
- ログに `own_discard_mismatch`、`own_discard_reconciliation_failed`、`force_auto_click_budget_expired`、`action_aborted` は0件で、58件の自己河追記確認・照合を記録した。反応鳴きは17件を方針で安全に不採用とし、公開情報・自己河・副露を使う経路で完走した。無効寸法のscreencastは171件が拒否されたが、拒否後の不正時刻再利用や誤クリックは生じていない。
- `3fa1156` が追加した62判断の区間計測は、手牌認識の中央値1290ms、盤面メタデータの中央値1244ms、並列完了後の判断中央値396ms、認識から判断完了まで中央値1624msだった。一方、検出から判断開始までの中央値は4015ms、判断開始から物理クリックまで中央値2108ms、根拠フレームからクリックまで中央値6444ms（最小4893ms）である。従って並列化はOCRと認識の直列待ちを解消したが、2600ms短時間予算を満たす証拠にはならない。5+20練習と銅の間は開始せず、次は検出ゲートとクリック前検証を区間別に縮めつつ安全根拠を維持する。

## 2026-10-20 8f195fc の300+0秒回帰完走と銅の間の再確認

- 再開時、ローカルのブラウザ・操作者・認識サーバーは不在。既存プロファイルとローカルChromium依存ライブラリでブラウザを復旧し、ログイン済みロビーと進行中対局なしを確認した。残っていた同一フレームの複数領域切り出し／ポインタ退避後ストリーム再利用の変更を検証し、`8f195fc` としてcommit・pushした。Python操作者・画面分類テスト184件（33 skip）は成功、build・diff checkも成功。
- 新規ルーム33989は四人CPU（簡単）・一局戦・300+0秒、25000点開始／30000点返し、飛び有効、赤3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。設定画像は `artifacts/live/recovery-20261020/room33989.png`。操作者は一系統、`--action-deadline-ms=300000 --force-auto-click-budget-ms=8000 --board-metadata --advance-screens --no-dashboard`。対局中のコード・設定変更、再起動、手動打牌はない。
- 成果物 `artifacts/friend-300-8f195fc-room33989-20261020` のmanifest、JSONL、summary、42リプレイ、終局画像を保存。24通常打牌・3反応操作で `match_completed_stop`、exit 0。自家21100点・4位、CPU30900/24000/24000。全通常打牌は300000ms期限内、検出→クリック2909--7250ms、中央値6534ms。自己河不一致・再照合失敗・クリック予算超過・離席復帰・安全停止は0。18件の `action_aborted` はすべて自己河確認候補の到着による再観測であり、誤クリックや期限超過ではない。機能回帰の完走は確認したが、認識全牌の正解や短時間性能・勝率改善を証明しない。
- 銅の間を実画面の(1393,410)で選択すると今回は入場拒否なく「銅の間／四人東・四人南・三人東」の選択画面を開けた。`artifacts/live/recovery-20261020/ranked-rooms.png` と `copper-entered.png` に初心表示、初心者・雀士という銅の間条件、遷移結果を保存。まだキュー投入・段位対局開始の証拠ではない。
- 依頼された5+20秒練習用に新規CPUルーム33675を作成。300+0回帰とは別枠で2600msクリック予算の実測を行う。友人戦のoperator action deadlineは指示どおり300000msを維持するが、ゲーム側の5+20時計を延長するものではない。段位戦の勝率評価には含めない。
- 5+20練習は `b93e9da` で開始。成果物は `artifacts/practice-5plus20-b93e9da-room33675-20261020`、設定画像は `artifacts/live/recovery-20261020/room33675-5plus20.png`。`--action-deadline-ms=300000 --force-auto-click-budget-ms=2600 --board-metadata --advance-screens --no-dashboard`、ranked-loop無効で一系統を起動した。00:05:26 UTC時点で実行中。2通常打牌・1反応操作に対し、予算超過25件・離席復帰4件・自己河不一致1件が発生し、短時間練習の合格とは扱わない。期限超過例はクリック直前2622/2661/2681/2725msであり、2600msの境界を繰り返し超えている。対局中はコード・設定を変更せず、ゲーム側自動打牌との競合を含む時刻／状態照合を後続調査とする。段位戦の開始・継続および勝率改善は未達で、ゴールは継続中。

## 2026-10-20 5+20診断：受信時刻とファイルmtimeの予算基準差

- 前ターンからのCPU練習ルーム33675（5+20秒、実行コード8f195fcを含むb93e9da、action deadline 300000ms、click budget 2600ms）は正常に生存しており、重複起動・途中コード変更は行わなかった。00:17 UTC時点で東4局の進行中。対局結果は未確定であり、離席復帰・自動ツモ切りが混入した診断標本として扱う。
- 00:04:51.773764の四萬クリックは手番検出から5302ms後。対応する `frames/2026-10-20T00-04-54.097339+00-00.post-discard.png` は四萬が手牌に残り、自己河に八萬が追加された状態を示す。00:04:58.910614の `own_discard_mismatch` もexpected=4m、actual=8m。5秒基本時間を超えた自動ツモ切りとの競合が強く疑われ、単なる河認識誤りとは分類しない。
- Pythonのクリック鮮度基準はstream受信時刻だが、resident serverは画像ファイルmtimeを予算基準としていた。認識開始までのゲート・分類・保存前処理がJev予算から抜ける。44件の超過標本について、`expired.captureAgeBeforeDecisionMs - (2600 - 150 - arbitration.deadlineMs + arbitration.elapsedMs)` は594--1418ms、中央値958ms。これは保存前時間とクリック前処理などの合計であり、全量をJev遅延と呼ばない。
- 別作業ツリー `/tmp/jantama-capture-age-fix` に修正を準備した。受信monotonic時刻からwall-clock timestampを算出してresidentへ渡し、serverはmtimeとの早い方を使う。未来のtimestampで鮮度を若返らせない。並列認識後の評価と動的レイアウト再評価にも引き継ぐ。クリック直前の2600ms保護は変更しない。
- Pythonの時刻変換・並列引き継ぎテストを追加し、176件中33skip、1件のfixture不足を除き成功。不足していた別作業ツリーの `artifacts/live/round-result.png` を接続して当該1件を再実行し成功。recognition serverの3テストは成功し、staged評価へ5秒前の受信時刻を渡すと新しいファイルmtimeでもdecision budgetが1msになることを確認した。build、diff check成功。検証中に同一ホストでテスト負荷が加わった期間は、無負荷での短時間性能標本には扱わない。
- 修正コミット36c9929と本記録をupstreamへ保存するが、進行中対局のroot作業ツリーは3255330のまま維持する。次の継続では最初にPID971189と成果物を再確認し、終了確認後だけ `git merge --ff-only origin/main` で反映・buildして、300+0秒／action deadline 300000msの回帰を実施する。5+20再評価とranked-loop（2600ms）は未完了。今回の修正だけで短時間性能を達成したとは主張しない。

## 2026-10-20 5+20練習の終局と修正適用

- ルーム33675は00:22:46 UTCに `match_completed_stop` で終了し、PID971189の消失を確認した。終局画像 `artifacts/practice-5plus20-b93e9da-room33675-20261020/frames/2026-10-20T00-22-46.200655+00-00.match_result.png` （正確な保存名は同JSONLのoutcome_observed参照）は自家20000点・4位、CPU30000/27000/23000。manifestとsummaryをcompletedへ更新した。18通常打牌、16反応操作、予算超過137、離席復帰19、自己河不一致3、再照合失敗1。5+20の短時間練習は不合格であり、段位成績・機能回帰合格として扱わない。
- 終局と操作者終了を確認してからroot作業ツリーを8b64edcまでfast-forwardしpush、build成功。受信時刻の判断サーバー引き継ぎ修正に加え、離席判定の厳密RGB条件を既存Pillowネイティブ色マスクへ置換した。保存フレーム12枚の判定差0、中央値119.46→11.97ms。別の実離席画像でも両実装True、色境界・面積比率の回帰テストを追加。Python操作者・画面分類186件（33skip）成功。速度計測は保存画像の判定部分だけで、対局全体の2600ms達成とは区別する。
- 最新修正の300+0秒回帰を次に開始する。5+20再評価・ranked-loopの開始継続・勝率改善はまだ未完了。

## 7ae6f46の300+0秒・2600ms予算回帰（ルーム68209、完走）

- 設定画像 `artifacts/live/recovery-20261020/room68209-300.png` は四人CPU・簡単・一局戦・300+0秒、25000点開始／30000点返し、飛び有効、赤3、ローカル役無効、喰い断有効、一翻縛り、便利表示有効。`--action-deadline-ms=300000 --force-auto-click-budget-ms=2600 --board-metadata --advance-screens --no-dashboard` を一系統で実行した。受信時刻の修正を直接検証するため、ゲーム時計は300秒のままクリック予算のみ短時間値とした。途中のコード・設定変更と手動打牌はない。
- `artifacts/friend-300-7ae6f46-budget2600-room68209-20261020` にmanifest、summary、JSONL、画像、リプレイを保存。00:29:49 UTCに `match_completed_stop`、プロセスexit 0。自家25000点・3位、CPU30800/25000/19200。16通常打牌・5反応操作、自己河不一致・再照合失敗・離席復帰・安全停止0。CPU機能回帰の完走であり段位勝率とは区別する。
- 予算超過は13件（通常打牌11、鳴き2）。通常打牌の典型例2616--2665msではJevが283--329msの予算内に終わってもクリック前検証の150ms枠を超えていた。検出→クリックは中央値4546.5ms、最大10733msで、再観測待ちを含むためフレーム鮮度2600msと同一指標ではない。鳴きの7143/7254msは別経路の課題である。
- 終局確認後にクリック前確保時間を150→350msへ変更する。保護期限2600msは延長せず、そのぶんJev待ちを短縮してローカル判断へ戻せるようにする。2秒前の受信フレームに対して判断予算を250ms以下にする再現テストを追加。次の300+0秒回帰と5+20再評価を要する。
- 上記350ms確保の変更は `npm run build`、recognition serverテスト3件、`git diff --check` を通過した。ルーム68209の同一300+0秒設定で、action deadline 300000ms／click budget 2600msの再回帰を行う。

## 2026-10-20 1e89489回帰中の立直前期限超過と配信フレーム確認の修正

- ルーム68209の四人CPU・300+0秒回帰は `--action-deadline-ms=300000 --force-auto-click-budget-ms=2600` で継続中。成果物は `artifacts/friend-300-1e89489-budget2600-room68209-20261020`。00:42 UTC時点の期限超過61件中56件が `before_action_button_click` で、東2局・残り37枚の立直ボタン表示から進まない。代表例00:42:38は4312ms。完走・短時間性能合格・段位勝率のいずれも主張しない。
- 実行中rootは1e89489のまま固定し、別作業ツリーで修正した。手牌・同一ツモの検証を通過し、評価フレームと現在の配信フレームの受信時刻が120ms以上離れている場合、ボタンの2回の同期撮影をこの2フレームの切り出し比較へ置換する。ボタン変化時の中止、2600ms期限、確認後の操作receiptは維持。時刻や画像がない・時間差不足・手牌ガード不成立なら従来の同期確認を使う。
- 新テストは安定ボタンで同期撮影なし、ボタン変化でクリック禁止、時間差50msで同期撮影2回への復帰、およびクリック直前の期限確認維持を検証。Python操作者・画面分類187件（33skip）成功、diff check成功。同一ホストでテストした期間は無負荷の速度標本から除外する。
- 修正はupstreamへ保存するが進行中の操作者には適用しない。終局・プロセス終了後にrootをfast-forwardしてから300+0秒回帰が必要。5+20再評価、2600msでのranked-loop、勝率改善の検証は未完了。

## 2026-10-20 1e89489回帰中のviewport停止と同一コード復旧

- 00:44:16 UTC、操作者は `viewport restore failed: expected 1920x1080, actual 233x98` でexit 1。PID997625・認識サーバーの消失と実行セッションの終了を確認した。直前に外部Playwright接続で保存した画面も、1920x1080画像内のゲームが233x98に縮小していた。同期clip撮影中に確認用CDP接続が一時サイズを引き継いだ可能性があり、外部確認の干渉として記録する（単独運用での再現は未確認）。稼働中の画面確認は既存操作者の保存フレームを用い、二重のPlaywright撮影接続を避ける。
- ブラウザは生存・対局は東2局残り25枚だった。操作者不在を確認後、viewportを1920x1080へ戻し、実測寸法と `viewport-recovered.png` を保存した。ゲーム画面・立直表示・238秒残を確認。対局を退出・再作成せず、rootコミット1e89489と同一引数（300000ms action deadline、2600ms click budget）で再起動し、PID1008987・認識サーバー1008990の生存と盤面認識の再開を確認した。
- 同じ成果物のstdout/JSONLへ追記し、run-manifestに停止理由と復旧を記録。新修正c777dc1は適用していない。立直前の旧コード期限超過は再発しており、この対局を無停止の回帰合格とは扱わない。終局後の結果記録と新修正での再回帰が必要。

## 2026-10-20 1e89489の300+0秒回帰終局とc777dc1適用

- ルーム68209、四人CPU・300+0秒、action deadline 300000ms／click budget 2600msは01:04:39 UTCに `match_completed_stop` で終了。復旧後セッションexit 0とPID1008987消失を確認した。終局画像 `artifacts/friend-300-1e89489-budget2600-room68209-20261020/frames/2026-10-20T01-04-39.724740+00-00.match_result.png` は自家19000点・4位、CPU28500/27000/25500。manifestとrun-summaryを保存。これはCPU機能回帰の不合格であり段位勝率には含めない。
- 通常打牌67、反応処理18、action aborted 221、予算超過195（ボタン直前184、通常打牌直前6、事前検証3、鳴き直前2）。自己河不一致・再照合失敗・離席復帰0、viewportによる安全停止1。立直を選んでも同期撮影により約4.1秒かかり、複数手番で300秒時計を使い切った。対局中の実行コード・設定変更は行わず、停止時も同一版で復旧した。
- 終局後に再起動前の未添付リプレイへ結果を補完した。東2局1本場・時刻を照合した88件に流局結果、118件に同対局の終局結果を付与し、個別JSONとdecisions.jsonlを同期。根拠は `recovery-round-outcome-map.json`、件数は `recovery-outcome-repair.json` に保存。
- 待機中、保存された立直フレーム12組のボタン領域画素差は最大0.120（閾値1.5）。切り出し＋比較の中央値28.5ms、最大39.4ms。これは画像処理部分の測定であり実クリックの2600ms達成を意味しない。
- 終局確認後にrootを6dd2c9eへfast-forwardし、c777dc1の時間差を持つ配信フレームによるボタン確認を適用。Python187件（33skip）は準備時に成功済み、適用後build成功。次の300+0秒回帰もaction deadline 300000ms／click budget 2600msで行い、立直操作が実際に成立するか検証する。5+20再評価とranked-loopは未完了。

## 2026-10-20 8dbdccbの300+0秒完走・立直修正確認と鳴き経路短縮

- ルーム68209、四人CPU・一局戦・300+0秒、action deadline 300000ms／click budget 2600ms。01:20:59 UTCに `match_completed_stop` とexit 0、PID1026802終了を確認。自家24600点・3位、CPU31000/27200/17200。成果物 `artifacts/friend-300-8dbdccb-budget2600-room68209-20261020` のmanifest、run-summary、終局画像を保存。段位戦の勝率標本には含めない。
- 59打牌判断（立直1を含む）、反応prompt11、ロン1、aborted22。自己河不一致・再照合失敗・離席復帰・安全停止0。東2局に2600ms保護下で立直ボタンを押し、6s宣言牌を確認、後に3mロンで1600点増を確認した。`streamed-button-regression-evidence.json` に宣言・打牌receipt・和了画像をまとめた。立直ボタン直前の期限超過0で、c777dc1の対象動作を確認できた。
- 期限超過は6（通常打牌直前1、事前検証1、鳴き直前4）。東3局1本場の東ポンは戦略承認・捨て牌ハイライト検証後でも7036--7250msとなり、クリックを中止した。従って立直経路と無停止完走は確認済みだが、短時間の鳴きを含む全経路合格ではない。
- rootの実行コードは対局中8dbdccbに固定し、別作業ツリーで修正。公開牌認識を常駐モデルへ統合し、キャッシュ認識との完全な要求・応答交換を排他制御する。反応フレームのハイライト認識と座席指定を維持し、ID不一致・認識失敗でキャッシュを代用しない。保存画面で従来CLI3115ms、常駐cold2457ms／warm252・279ms、従来CLIの認識結果と一致、無効座席を拒否した。
- 同一保存フレームの公開牌・手牌・盤面メタデータを並列化し、未検証メタデータの拒否を維持する。さらにブラウザ・校正・レポート等を読み込むCLIから鳴き専用入口 `reactionEvaluator.ts` を分離。既存の状態検証・鳴き戦略を用い、13枚／副露後10枚等の物理枚数を照合する。Jev待ちは元の受信時刻と2600ms予算から、起動・クリック用650msを差し引いて決定する。物理クリック直前の期限判定は変更しない。
- 最終版の保存フレーム経路測定はcold3328ms、warm2307・2189msで、全て東ポンと対象捨て牌を維持。`reaction-pipeline-benchmark.json` に保存。実ゲームの取得・ゲート・クリックは含まないため、実戦で2600msを満たす証明にはしない。同一ホストでテストした時間帯は無負荷性能の標本から除外する。
- Python193件（33skip）成功。新TSテストは従来CLIとの状態・選択・合法手の一致、5枚目の牌の拒否、副露後枚数の検証を通過。実モデルの公開牌CLI一致、build、diff checkも成功。終局後だけrootへ反映し、次の300+0秒回帰で実際の鳴きを検証する。5+20再評価、ranked-loopと勝率改善の証明は引き続き未完了。

## 2026-10-20 9396b08の300+0秒回帰完走と5+20秒再評価への移行

- ルーム68209・四人CPU・一局戦・300+0秒、action deadline 300000ms／click budget 2600msを一系統で実行。01:34:43 UTCに `match_completed_stop`、exit 0、PID1048148終了。自家21100点・4位、CPU32900/23000/23000。成果物 `artifacts/friend-300-9396b08-budget2600-room68209-20261020` に設定画像・manifest・summary・全ログ・終局画像を保存した。
- 14打牌・2パス、自己河不一致・再照合失敗・離席復帰・安全停止0。aborted11、うち通常打牌直前の期限超過2（2635/2614ms）。並列反応認識は1416ms、2126msで動作したが、2件ともチー対象の捨て牌を確定できず安全にパスした。従って無停止の機能完走は確認したが、選択されたポンのクリックや全経路の2600ms達成は未確認。段位勝率の標本とはしない。
- 実装は対局中変更せず、終了後も同じ9396b08の実装で5+20秒の短時間練習を追加する。友人戦のoperator action deadlineは引き続き300000msとし、ゲーム側の短い時計・クリック予算2600msと混同しない。鳴きの未確認範囲も継続観察する。段位戦開始・勝率改善の証明は未完了。

## 2026-10-20 5+20 practice at 6654705 and streamed pass guard

- CPU friend room 96260, four players / one-round configuration, 5+20 seconds, 25000 start / 30000 return; operator explicitly used `--action-deadline-ms=300000 --force-auto-click-budget-ms=2600 --board-metadata --advance-screens`, no ranked loop. Implementation 9396b08, launch commit 6654705. Artifacts: `artifacts/practice-5plus20-6654705-room96260-20261020/` (manifest, stdout, frames, replays, summary).
- Finished at 01:54:26 UTC: self 25500 / second; CPU 30500, 23500, 20500. 58 decisions, 21 pass prompts, 29 aborted evaluations, 22 budget expiries (1 self action / 7 discard / 7 prevalidation / 7 call), 4 away resumptions, 1 own-discard mismatch, zero reconciliation failures or safety stops. This is a failed short-time functional practice, not ranked evidence or demonstrated win-rate improvement. Riichi declaration and discard were confirmed, but that does not establish short-time stability overall.
- The own-discard mismatch at 01:48:28 expected 8m, observed P. The decision image `frames/2026-10-20T01-48-17.493489+00-00.jpg` visibly shows a white dragon in the draw slot; the evaluator classified that draw as 8m (overall confidence 0.424). Click index 13 discarded that slot. Thus this example supplies direct evidence of tile recognition error, not just an inferred timeout race. Evidence is grouped in `mismatch-evidence.json`; recognition repair remains outstanding.
- Actual approved calls now exercised the new reaction pipeline: pon C and chi 1m were selected, but seven strict original-frame age checks rejected their clicks. These are missed calls, not successful live call coverage. Do not relax the 2600ms budget to hide them.
- Pass policy decisions finished in about 0.4 seconds after parallel recognition; the subsequent repeated hand recognition and synchronous button screenshots delayed the click by about 2.7 seconds in sampled events, with additional post-click confirmation time. `pass-latency-evidence.json` records the timeline. First away was 01:42:49, before test load. Python test runs around 01:44–01:46:30 UTC partly overlapped and contaminated later latency measurements; do not attribute all expiries to operator changes alone.
- Prepared the pass-button fix in an isolated worktree, then applied it as 4545b4c only after the operator exited. Force-auto can compare the evaluated prompt with a distinct stream observation separated by at least 120ms, with the latter received within 250ms. Both must independently show the pass affordance; the stylized variant also requires a green call button. Pixel stability and action deadline checks remain, and the click budget uses the stream receipt timestamp, not the time the comparison finished. Missing/stale/undated evidence retains the synchronous check. Calls/ron keep their original-frame budgets.
- Validation: Python discovery 226 tests, OK with 33 existing skips; diff check passed. Added cases cover fresh and changed buttons, same timestamp, stale/missing timestamps, stylized pass and absent contextual call button. Saved practice frames confirm the stylized detector path applies. Live 300+0 regression of 4545b4c is pending; no live performance improvement is claimed yet.

## 2026-10-20 300+0 regression at 5597b0f; call masks and shadowed white correction

- Room 34443, four-player CPU friend / 300+0 seconds / 25000 start / 30000 return, explicit action deadline 300000ms, click budget 2600ms, board metadata and screen advance enabled, no ranked loop. Frozen launch commit 5597b0f (pass guard implementation 4545b4c). No parallel test workloads during the match. Artifacts: `artifacts/friend-300-5597b0f-room34443-20261020/`.
- Terminal at 02:17:20 UTC: self 33600 / first, CPU 22800 / 22800 / 20800, confirmed from final image. 41 decisions, 13 pass prompts, 16 aborted evaluations, 40 expired clicks (4 discard, 3 prevalidation, 33 call), zero own-discard mismatch / away / safety-stop, one own-discard reconciliation failure. The game completed but overall functional regression is not passed because approved calls repeatedly missed their budget. One CPU first place is not sufficient evidence of ranked win-rate improvement.
- The reconciliation failure followed riichi discard 8s at 02:16:27. The stored post-discard frame at 02:16:30 is covered by the riichi animation. The later observation at 02:16:52 contained four appended tiles rather than one; the single-append verifier rejected it. `reconciliation-failure-evidence.json` retains the decision/execution/failure. This does not prove a wrong physical click; exact reconciliation across this animation/automatic-discard interval remains unresolved.
- Pass samples still took about 3.2–3.4s from decision start to click, so no broad short-clock improvement is claimed for the prior stream guard. Approved calls commonly reached the strict click guard at 2.8–3.0s. Reading the live path identified repeated full ROI Python pixel scans in call-button detection.
- 7bb2497 replaces these scans with equivalent Pillow channel masks and native column histograms. The green/cyan predicates, separate palette grouping, five-pixel column requirement, bounds, overlap trimming and magenta rejection stay the same. A 28-frame offline comparison against the pre-change function matched every returned button exactly: mean 229.81ms old vs 53.14ms new. Benchmark and frame list: prior practice artifact `call-mask-parity-benchmark.json`. This measures the detector only, not end-to-end click readiness.
- 030ad28 addresses the prior practice's white-draw misclassification. The central face of that white draw has no dark/chromatic ink (minimum channel 217), while the actual 8m in its hand has 463 ink pixels out of 1380. A fully bright neutral core now follows the existing uncertain-blank P policy despite broad lighting gradients. Confidence remains zero with rejectBlank, so this does not certify glare/empty images for auto mode. The stored whole-frame fixture verifies P and all thirteen other labelled tiles together; synthetic gradient tests exercise lighting edges.
- Tests run only after the live operator exited: Python 227 tests OK (33 existing skips); targeted TS recognition tests 9/9 passed; TypeScript build and diff check passed. Applied changes only after terminal confirmation. New 300+0 live regression remains required; ranked play has not begun.

## 2026-10-20 a6eee00 300+0 completion and riichi river verification

- Reused CPU friend room 34443 with visually checked 300+0 seconds, 25000 start / 30000 return. Launch commit a6eee00, implementation 030ad28, explicit operator deadline 300000ms, click budget 2600ms, no ranked loop or concurrent tests. Artifact root: `artifacts/friend-300-a6eee00-room34443-20261020/`.
- Finished 02:27:00 UTC, self 34200 / first, CPU 23000 / 21900 / 20900. 22 decisions, 5 pass prompts, 9 aborted evaluations, one pre-discard budget expiry, zero own-discard mismatches / away / safety stops, one own-river reconciliation failure. Riichi and tsumo were clicked and confirmed. All observed call candidates were rejected by policy/evidence, so approved-call performance remains untested for the native masks. This is CPU functional evidence, not ranked win-rate data.
- Two P draws were discarded and independently reconciled at 02:21:59 and 02:23:53. The second decision screenshot visibly shows the white draw; `white-draw-live-evidence.json` groups both decisions and reconciliations. The fixed white path is now exercised live.
- Riichi discard F at 02:25:27 was compared later against before `[8s]`, observed `[8s,F,4m,5p]`. The first appended tile is correct, but two automatic discards during riichi caused the strict single-append check to fail. This differs from an arbitrary multi-tile jump or finding the desired tile elsewhere in the tail.
- After process exit, added a narrow riichi branch: pending action must be a confirmed riichi declaration; public observation must independently show own riichi; original river prefix must match; and the first appended tile must match the declaration discard. Existing two-scan public confirmation stays mandatory. Following automatic discards are logged, and the concealed-hand cache is invalidated instead of reused. Non-riichi, missing observed-riichi, wrong-first-tile and changed-prefix inputs still fail as before.
- Validation: full Python suite 228 tests OK / 33 existing skips, followed by the added two-scan integration test (1/1 passed); diff check passed. A new 300+0 live regression is required for this branch. Two successive CPU first places are promising samples but do not establish ranked readiness or a statistically supported win-rate increase.

## 2026-10-20 608d9bc 300+0 baseline completion

- CPU friend room 34443, visually verified 300+0 seconds, 25000 start / 30000 return. Code/launch 608d9bc, explicit action deadline 300000ms, click budget 2600ms, metadata and screen advance enabled, no ranked loop. No concurrent test workload or mid-match source/config changes. Artifacts: `artifacts/friend-300-608d9bc-room34443-20261020/`.
- Completed 02:35:09 UTC: self 24700 / third; CPU 36700 / 26100 / 12500. 16 decisions, one pass prompt, two aborted evaluations, one prevalidation budget expiry; zero own-discard mismatch, reconciliation failure, away recovery or safety stop. Self lost 300 points in the first CPU win; the final 12000-point transfer was between CPUs, with self score unchanged, so do not classify the final loss as our discard failure.
- Basic discard/advance/completion regression passed within observed coverage. No riichi declaration or approved call occurred, so neither the new multi-append branch nor end-to-end accepted-call performance was covered; overall manifest remains coverage-incomplete rather than a blanket functional pass. Continue the user-requested 5+20 practice with the same implementation, keeping its evidence separate from this 300-second run and from ranked results.

## 2026-10-20 717368c short-clock baseline completion

- CPU friend room 26408, four players / 5+20 seconds, 25000 start / 30000 return; launch 717368c, unchanged implementation 608d9bc. Explicit operator action deadline 300000ms and click budget 2600ms, no ranked loop. No parallel tests or mid-match changes. Artifacts: `artifacts/practice-5plus20-717368c-room26408-20261020/`.
- Completed 02:42:00 UTC, self 21800 / second; CPU 35600 / 21800 / 20800. 16 decisions, eight pass prompts, two aborted evaluations, one prevalidation expiry; zero own-discard mismatches, reconciliation failures, away resumptions or safety stops. Final score transfer reduced self by 3200, equal to another nondealer, rather than identifying a self-discard loss.
- This one 5+20 match passed observed basic discard/pass/completion coverage. Riichi and accepted calls did not occur; their coverage is still missing, so no blanket all-action certification or ranked win-rate claim is made. Keep 300+0 functional observations, this short-time practice and eventual ranked evaluation separate. Repeat short-clock practice without implementation changes to gather more representative action coverage and outcomes.

## 2026-10-20 ef4f5a9 short-clock failure and open draw crop correction

- CPU friend room 26408, 5+20 seconds, 25000 start / 30000 return, launch ef4f5a9 / implementation 608d9bc. Explicit action deadline 300000ms, click budget 2600ms, no ranked loop. Completed 02:47:39 UTC at 19000 / fourth; CPUs 38000 / 22000 / 21000. Artifacts: `artifacts/practice-5plus20-ef4f5a9-room26408-20261020/`. Ten decisions, one pass, seven aborted evaluations, ten budget expiries (one prevalidation, four discard, five call), one own-discard mismatch, one away recovery, zero reconciliation failures or safety stops. Functional practice failed; this is not ranked evidence.
- Accepted chi 8s with 6s/7s at 02:45:13 was confirmed by both hand and meld changes, with original evidence-to-click 2548ms and subsequent open-hand discards. Five approved pon C attempts still expired. Thus one accepted call is covered, but reliable short-clock calls are not established.
- At 02:46:41 the decision frame visibly has one second remaining and a separated 6s draw. Recognition instead reported 1m; the calibrated compact draw crop began at x1171 rather than x1201. The chosen 1p click followed about 1.75s later; river observation appended 6s, consistent with timeout auto-discard, not proof of a wrong physical click. Repeated retries and full-turn timing remain unresolved.
- Added a geometric draw-gap resolver for confirmed open hands. Blank top-face strips distinguish contiguous post-call rows from separated draws; only the draw crop and its click center move by the calibrated gap. Concealed-only reaction recognition is unchanged. The actual failing fixture now recognizes 6s instead of 1m; the immediate post-chi fixture keeps its contiguous C and original click center. Bright/empty synthetic regions across one through four melds do not invent gaps.
- Checks after the match ended: targeted TypeScript tests 20 total, 16 passed / four existing skips / zero failed, including resident-server draw-only integration; TypeScript build and diff check passed. No concurrent live-match test workload. Live 300+0 regression is next; this crop correction does not claim to solve short-clock retries or pon latency.

## 2026-10-20 e7d5305 300+0 completion and sideways river normalization

- CPU friend room 85002, verified 300+0 seconds, 25000 start / 30000 return, launch e7d5305, explicit deadline 300000ms and click budget 2600ms, no ranked loop. Completed 05:05:19 UTC at 33000 / first; CPUs 25000 / 25000 / 17000. Artifacts: `artifacts/friend-300-e7d5305-room85002-20261020/`. One recorded discard decision (riichi), seven aborted evaluations, five budget expiries (two prevalidation / three action-button), one own-discard mismatch, zero reconciliation failures / away / safety stops. No own call occurred, so the separated-open-draw change remains unexercised live. No parallel tests or source changes during play.
- Decision at 05:03:48 correctly recognized drawn 2p and selected riichi discarding it. The post-click frame shows the riichi animation; later frame 05:04:36 clearly shows sideways 2p first in our river. Yet public recognition reported 1p at 0.933 confidence and triggered the mismatch. This is supported as a public recognition error, not a physical wrong-discard finding. The first-turn 300-second clock still had 286 seconds in the decision frame, unlike the previous short-clock timeout.
- Reproduction found the discard-grid detector already marked that candidate sideways (78x41), but normalization added 90 degrees only when the region had a meld-specific aspect-ratio option. Enabling the rotation for the same candidate yields 2p at near-1.0 confidence with every other river label unchanged. Normalization now honors the detected sideways flag for rivers too; the low-confidence padded retry uses the same rotation. No expected-action label is used to force the answer.
- Validation after operator exit: public recognition suite 28/28 passed, including existing real-model river/meld fixtures, a new complete nine-tile river fixture and a padding-orientation test. Fixed the test stub's missing runner-up type field; TypeScript build and the affected padding test then passed, as did diff check. New 300+0 regression required; CPU first place does not establish ranked win-rate or certify short-clock behavior.

## 2026-10-20 9e73995 300+0 baseline regression completion

- CPU friend room 85002, visually verified 300+0 seconds, 25000 start / 30000 return; frozen launch 9e73995, explicit action deadline 300000ms and click budget 2600ms, no ranked loop. Completed 05:19:55 UTC at 28800 / second; CPUs 33500 / 24200 / 13500. Artifact root: `artifacts/friend-300-9e73995-room85002-20261020/`. No concurrent tests or source changes.
- 43 discard decisions, 13 pass prompts, one confirmed ron, four aborted evaluations, one prevalidation budget expiry; zero own-discard mismatch, reconciliation failure, away recovery or safety stop. Three aborts were fresh own-river confirmation arriving during evaluation. Basic discard/pass/ron/advance/completion coverage passed. No own call or own riichi occurred, so live confirmation of both new recognition branches is still missing; overall coverage is explicitly incomplete.
- The final score transfer was between CPUs, leaving self at 28800. This CPU second place and the prior first place are not ranked win-rate measurements. Continue the requested 5+20 practice with unchanged implementation before claiming short-clock reliability.

## 2026-10-20 531f28a 5+20 practice completion before Copper evaluation

- CPU friend room 71276, visually verified 5+20 seconds, 25000 start / 30000 return; launch 531f28a / unchanged implementation 9e73995, explicit action deadline 300000ms and click budget 2600ms, no ranked loop. Completed 05:29:24 UTC at 36300 / first; CPUs 24000 / 24000 / 15700. Artifacts: `artifacts/practice-5plus20-531f28a-room71276-20261020/`. No tests or code changes during play.
- 28 discard decisions, four passes, nine aborted evaluations, three pre-discard budget expiries; zero own-discard mismatches, reconciliation failures, away recoveries or safety stops. Riichi discard 0m at 05:28:44 was independently reconciled at 05:28:52, and ron at 05:28:58 was confirmed. Basic short-clock discard/pass/riichi/ron/completion coverage passed. No own call occurred and no riichi multi-append reconciliation was observed, so those branches remain coverage-incomplete.
- The 300+0 baseline and this short-clock sample support resuming the requested Copper entry/continuation evaluation with the 2600ms budget and ranked loop. They do not establish statistically supported ranked improvement. Keep subsequent ranked outcomes separate; continue diagnosing any missed call or operation issue from saved screenshots and logs.

## 2026-10-20 first Copper ranked outcome; short-clock budget stops

- Launch d9bbd41 / implementation 9e73995, account rank observed 初心, room visually confirmed 銅の間・四人東. Menu click (1390,410) entered successfully with no rank restriction. Live turn frames show 5+20 seconds. Explicit action deadline 300000ms, click budget 2600ms and ranked loop enabled. Artifacts: `artifacts/ranked-copper-d9bbd41-20261020/`. This is the first ranked cohort, separate from every CPU result above.
- Completed 05:58:00 UTC: self 22500 / third / rank points -7; opponents 40500 / 27800 / 9200. One match is insufficient to claim ranked win-rate improvement. The observed 2500-point self loss came from two noten payments (1000 and 1500); the other hand-end score transfers were between opponents. This does not excuse missed opportunities or operation failures.
- 58 recorded discard decisions, 22 passes, two confirmed calls (pon N and chi 2m/3m/4m), 14 aborted evaluations / budget expiries (two prevalidation, eleven discard, one call); zero logged own-discard mismatch or reconciliation failure. Original evidence-to-click for pon was 2554ms. Chi followed a budget-rejected attempt and then succeeded; do not treat its aggregate 6104ms action timing as a 2600ms full-turn guarantee.
- The open-draw correction is exercised: after pon, the 05:46:43 frame has separated S, recognized correctly with draw center x1247.5. The actual execution chose recognized white P at x1122.5 via the ambiguity fallback, so retain the execution receipt rather than attributing the evaluator's S recommendation to the physical click. The immediate post-call rows and later separated draws both progressed. `accepted-call-and-open-draw-evidence.json` groups these records.
- Ranked budget safety stops occurred twice at 05:51:03 and 05:53:10 after three consecutive expiries. The final observed ages were 2611ms and 2687ms. Confirmed process exit before each restart, retained the same code / 2600ms budget / ranked loop, and resumed two away dialogs. The second restart continued through the match end. Thus continuous ranked operation is not passed. `stop-and-recovery-evidence.json` and the final manifest explicitly record both stops and recoveries. No runtime code/config changes or tests occurred during play.
- Stopped the operator only after independently observed match-result evidence to investigate timing before another match. Existing generic lobby/menu recognition can also appear during result fades; navigation event counts do not equal completed matches or prove successful next-match entry. A subsequent complete reentry remains to be verified.
- After all operators exited, replaced the orange/red action-button pixel loops with equivalent native Pillow masks and column histograms. Preserve the original orange/red predicates, inclusive green/blue ratio, five-pixel column count, grouping and geometry bounds. A deterministic 71-frame comparison (ranked/practice normal turns, prompts, failures, riichi and ron) returned exactly the same button dictionaries; mean 99.26ms before vs 28.22ms after. `self-action-mask-parity-benchmark.json` records every frame and timing. This is detector-only evidence, not proof that end-to-end budget stops are solved.
- Also reuse the already extracted stable hand crop in the fallback pre-click comparison, preserving the same immutable frame and rectangle. Full Python suite after the final change: 230 tests OK / 33 existing skips, including red-ratio boundary tests and existing pre-click safety tests; diff check passed. The 2600ms budget and three-expiry stop remain unchanged. Next step is live 300+0 regression with explicit deadline 300000ms, followed by short-clock practice and renewed ranked continuation verification.

## 2026-10-20 3dd58b4 300+0 completion; own-river crop and early riichi fixes

- CPU friend room 25128, visually verified 300+0 seconds, 25000 start / 30000 return. Frozen launch 3dd58b4, explicit action deadline 300000ms, click budget 2600ms, no ranked loop. Completed 06:21:00 UTC at 26700 / second; CPUs 29400 / 24600 / 19300. Artifacts: `artifacts/friend-300-3dd58b4-room25128-20261020/`. No parallel tests or runtime changes during play.
- 63 discard decisions, 20 pass prompts, confirmed riichi and ron; three hand-change aborts, zero click-budget expiries / away recoveries / safety stops, two own-discard mismatches and one subsequent river reconciliation failure. Native action-button detection is exercised live, and timing was clean in this 300-second sample. Overall functional regression failed due to river recognition; ranked/short-clock continuity remains unproven.
- At 06:09:24, expected 3m was reported as 5m. The decision, click at x269 and stored river image agree on 3m. The calibrated own-river region began at x770, cutting the third row's first tile at x759 from width62 to width51. Its incorrect confidence was 0.711, above the weak-crop retry threshold. Extending only the left edge to x750 (same right edge1160) restores 3m at 0.953 without changing the other twelve labels. The subsequent 8m was correctly appended, but the earlier unconfirmed river prefix caused the multi-append verifier to reject it; do not label that second event a wrong physical 8m click.
- At 06:20:10, confirmed riichi discard W was reported as 6m. The image shows sideways W. Its 76x41 component was not tagged sideways: the aspect median of a two-tile river included the sideways tile itself and raised its threshold. Rotation by the existing +90 degrees yields W at confidence1.0; reverse rotation yields N, so the rotation direction stays unchanged. Estimate perspective from upright candidates only, falling back to nominal aspect1 when the lone candidate is sideways. This fixes one- and two-tile early-riichi detection without relying on the expected discard label.
- Updated the regression/example own-river rectangles and the discard-grid aspect baseline only after process exit. Added both full-frame fixtures, a complete thirteen-label river assertion, early-W classification/riichi assertion, and one-/two-tile geometry checks. Public recognition and region-detection suites 38/38 passed; TypeScript build and diff check passed. `river-recognition-reproduction.jsonl` and `river-failure-evidence.json` preserve the before-change evidence. Another 300+0 regression is required before 5+20 and ranked continuation evaluation.

## 2026-10-20 8bac462 300+0 regression completion

- CPU friend room 25128, visually verified 300+0 seconds, 25000 start / 30000 return; frozen launch 8bac462, explicit action deadline 300000ms and click budget 2600ms, no ranked loop. Completed 06:41:13 UTC at 27500 / first; CPUs 26000 / 26000 / 20500. Artifacts: `artifacts/friend-300-8bac462-room25128-20261020/`. No parallel tests or source/config changes during play.
- 59 discard decisions, 16 passes, riichi 6s and confirmed ron, six aborted evaluations / budget expiries (one prevalidation, five discard); zero own-discard mismatches, river reconciliation failures, away recoveries or safety stops. Own rivers reached the third row without mismatch; `third-row-live-evidence.json` records independent river confirmations. Riichi was followed quickly by ron, so this does not prove the early-W or riichi multi-append branches were exercised. No own call occurred.
- Basic observed discard/pass/riichi/ron/advance/completion coverage passed. Full coverage and short-clock continuity remain incomplete. Expiring discard frames reached 2604–2705ms, leaving the original 2600ms guard intact. The last four-hand CPU match is not ranked win-rate evidence. Continue the requested 5+20 practice with unchanged code to measure timing under the shorter game clock before resuming Copper continuity evaluation.

## 2026-10-20 d0baf76 5+20 failure; compact opponent-turn gate correction

- CPU friend room 96538, visually verified 5+20 seconds, 25000 start / 30000 return; launch d0baf76 / implementation 8bac462, explicit action deadline 300000ms, click budget 2600ms, no ranked loop. Completed 06:53:56 UTC at 33300 / first; CPUs 25000 / 25000 / 16700. Artifacts: `artifacts/practice-5plus20-d0baf76-room96538-20261020/`. No tests or source/config edits during play. This first place does not constitute a functional pass or ranked win-rate evidence.
- 28 discard decisions, five passes, confirmed pon P and chi 8s/6s/7s, confirmed ron; seven aborted evaluations / budget expiries (two prevalidation, two call, three discard), three own-discard mismatches, one reconciliation failure, zero away recoveries or safety stops. Pon original evidence-to-click was 2561ms. Chi succeeded after earlier budget-rejected attempts; aggregate action timing includes those retries.
- After the second call, opponent frames were repeatedly evaluated as self turns: 22 `Expected 8 concealed tiles before discard, got 0` retries. At 06:48:37 the real compact draw slot is empty, while the closed-hand draw ROI is occupied by the exposed white pon. The streamed gate used the latter. The exact-frame fallback also chose that closed ROI when self-turn geometric evidence was absent, so it never reached its opponent-turn path. Each failed parallel evaluation then repeated board OCR synchronously before rejecting the same screenshot.
- The first mismatch selected 2m but observed automatic-looking 6m. The decision image at 06:48:44 shows the correct 6m draw and two seconds remaining; clicking followed about1.7s later, after repeated opponent-frame evaluations had blocked stream handling. The other mismatches selected 1s/4m but observed their 5m/6m draws, with 10.3s/30.0s action timelines. These support timeout involvement; do not mislabel every result as a tile-recognition or direct wrong-coordinate finding. `compact-opponent-retry-evidence.json` retains calls, retries and failures.
- After operator exit, made the streamed occupancy/generation gate, dynamic probe and exact-frame negative gate use the already confirmed open-meld count to locate the compact draw. This is a location hint only; the existing geometry/count/click checks still govern positive actions. Concealed-only fallback recognition also uses the confirmed compact layout. Preserve post-call discard handling and closed-round reset behavior; no game-clock/budget/expiry-stop threshold was relaxed.
- Added actual opponent/own-draw frame fixtures. The regression proves the old closed ROI is bright on both frames, compact occupancy changes only on the real draw, repeated identical draws do not advance generations, and the opponent frame skips synchronous self-turn recognition in the run loop. Normal asynchronous public/board refreshes remain enabled. Full Python suite 231 tests OK / 33 existing skips; diff check passed. Live 300+0 regression and subsequent 5+20 coverage are required before claiming short-clock or ranked continuity improvement.

## 2026-10-20 c24240e 300+0 baseline completion

- CPU friend room 44258, visually verified 300+0 seconds, 25000 start / 30000 return; launch c24240e / implementation 5d3d76f, explicit action deadline 300000ms and click budget 2600ms, no ranked loop. Completed 07:18:29 UTC at 23000 / third; CPUs 29600 / 26000 / 21400. Artifact root: `artifacts/friend-300-c24240e-room44258-20261020/`. No tests or source/config changes during play.
- 61 discard decisions, 19 passes, three prevalidation budget expiries / aborted evaluations; zero own-discard mismatches, reconciliation failures, recognition retries, away recoveries or safety stops. Basic closed-hand discard/pass/advance/completion coverage passed. No own riichi or approved call occurred, so the confirmed compact-draw gate remains unexercised in this live sample; overall coverage is incomplete.
- Self lost two 1000-point noten payments across the four hands; the other observed win transfer was between CPUs. This third place is CPU functional evidence, not a ranked sample. Continue unchanged implementation in the requested 5+20 practice to seek actual open-hand opponent/self-turn transitions and measure remaining timing issues before renewed Copper continuity evaluation.

## 2026-10-20 d2eeeba 5+20 compact-gate coverage and geometry batching

- CPU friend room 25486, visually verified 5+20 seconds, 25000 start / 30000 return; launch d2eeeba / implementation 5d3d76f, explicit action deadline 300000ms and click budget 2600ms, no ranked loop. Completed 07:37:25 UTC at 34900 / first; CPUs 25000 / 24000 / 16100. Artifacts: `artifacts/practice-5plus20-d2eeeba-room25486-20261020/`. No tests or source/config changes during play. This CPU first place is not ranked win-rate evidence or a functional pass.
- 67 discard decisions, 14 passes, one confirmed pon 9m, riichi and ron; 15 aborted evaluations, twelve budget expiries (two prevalidation, nine discard, one action button), one own-discard mismatch, one reconciliation failure, zero away recoveries or safety stops. The compact opponent gate was exercised after pon: no `Expected 11 concealed tiles ... got 0` retry loop occurred. The sole recognition retry was unverified board scores. Thus the false self-turn loop is fixed within this live one-meld coverage, while the prior two-meld reproduction remains covered offline.
- At 07:33:29 the decision screenshot correctly shows drawn 2s and a one-second clock; selected 5m was clicked at 07:33:30.921, about1.8s after the stored frame. Later river recognition appended 2s instead. With preceding budget retries, this supports game-timeout involvement rather than a 2s-label error. The following river-prefix reconciliation failure remains recorded separately. `remaining-timing-failure-evidence.json` keeps the evidence.
- The earlier narrow riichi multi-append fix was exercised live: 07:36:36 reconciled declaration discard 5s with one following automatic discard and invalidated the concealed cache. `riichi-following-automatic-discard-live-evidence.json` records that confirmation. This does not establish every riichi/call branch or reliable short-clock operation.
- Profiling only after operator exit found one compact geometry check averaging366ms across three profiled calls; repeated full-frame JPEG decoding and Python pixel loops dominated. The same check runs in multiple gate stages. Added batched ivory-presence checks: decode once, retain identical rectangles and strict RGB thresholds, and use native masks for the same pixel fraction. Closed-row, compact self-turn and compact opponent-turn geometry preserve their existing conditions and count preference. No click budget, deadline, evidence age, score-verification or stop guard was relaxed.
- A deterministic comparison across 32 actual frames and eight synthetic one-through-four-meld self/opponent frames matched all four geometry results exactly. Mean combined closed-row/meld-surface/self-geometry/reaction-geometry time was457.50ms before vs68.81ms after; this measures the geometry helpers, not end-to-end readiness. `compact-geometry-profile.txt` and `compact-geometry-parity-benchmark.json` retain profiling, frames and outputs, alongside reproducible baseline functions and benchmark script.
- Final checks: full Python suite232 tests OK /33 existing skips, including strict color-boundary and20-percent occupancy cases; diff check passed. New300+0 regression is required, followed by5+20 before renewed Copper continuity evaluation. Do not infer ranked win-rate improvement from these CPU outcomes.

## 2026-10-20 ba2a921 300+0 riichi-selection stall and correction

- CPU friend room60557, visually verified300+0 seconds,25000 start /30000 return; launch ba2a921, explicit action deadline300000ms and click budget2600ms, no ranked loop. Completed08:02:20 UTC at23000 / third; CPUs30300 /26600 /20100. Artifacts: `artifacts/friend-300-ba2a921-room60557-20261020/`. No tests or runtime source/config edits during play.
- 34 discard decisions,11 passes, two aborted evaluations; zero click-budget expiries, own-discard mismatches, reconciliation failures, away resumes or safety stops. Functional regression failed: declaration click at07:51:20 entered a valid dimmed riichi selection, but the operator rejected it and remained waiting. Stopped the stalled operator, attempted one external first-tile click, then restarted the same commit and settings to complete the match. The external click was not independently confirmed before the round transition; do not label it a verified declaration discard. Intervention and final result are recorded separately in the run manifest.
- Both ordinary and selection full frames classify as match at confidence1.0. The selection hand has51.96% muted neutral pixels and22.92% bright faces; the previous bright-face ceiling20% rejected this real UI, where 1m and3m remain selectable. The dimmed draw then fails the ordinary bright draw gate, explaining the persistent wait. The original hand has7.67% muted /64.03% bright pixels. Saved source frames and `riichi-selection-signature-evidence.json` preserve the diagnosis.
- After match exit, changed the selection signature to retain the45% muted minimum and require muted pixels to outnumber bright faces. Added tracked ordinary/selection full-frame fixtures, a bright-majority negative test, and changed the existing declaration-to-discard execution test to use these actual images without mocking the selection signature. Match classification, declaration confirmation, deadline and2600ms budget remain enforced.
- Full Python suite233 tests OK /33 existing skips; diff check passed. New live300+0 regression is required, followed by5+20 practice. Zero budget expiries in this interrupted CPU match do not establish short-clock or ranked continuity, and the result is not ranked win-rate evidence.

## 2026-10-20 5dfe9ae 300+0 and5+20 completion; riichi exercised live

- CPU friend room60557, visually verified300+0 seconds,25000 start /30000 return; launch5dfe9ae, explicit action deadline300000ms, click budget2600ms, no ranked loop. Completed08:16:10 UTC at19300 / fourth; CPUs34100 /23300 /23300. Artifact root: `artifacts/friend-300-5dfe9ae-room60557-20261020/`.32 discard decisions, four passes, confirmed red5p pon and subsequent compact-hand draws/discards; two retryable aborts when river reconciliation arrived during evaluation. Zero budget expiries, own-discard mismatches, reconciliation failures, recognition retries, away recoveries, safety stops or external interventions. Basic observed functional coverage passed; own riichi/win absent, so targeted live coverage remained incomplete at this point.
- The300+0 loss was3000 points for sole noten, followed by2700 paid on a CPU dealer tsumo including honba. The result screens and observed score transitions agree; no wrong-discard operation was observed. `loss-analysis.json` records the distinction between policy outcome and operation evidence. This CPU result does not evaluate ranked win rate.
- Same frozen implementation, CPU friend room57727, visually verified5+20 seconds with otherwise identical settings/deadline/budget. Completed08:26:26 UTC at31100 / first; CPUs25300 /22300 /21300. Artifacts: `artifacts/practice-5plus20-5dfe9ae-room57727-20261020/`.40 discard decisions, ten passes, confirmed riichi3s and tsumo. Zero aborted evaluations, budget expiries, own-discard mismatches, reconciliation failures, away recoveries, safety stops or external interventions. No own call in this sample. No tests or runtime source/config edits during either match.
- Riichi was clicked08:25:48.370, declaration confirmed, selection signature accepted,3s clicked08:25:51.154 and confirmed in the river. Tsumo clicked08:26:00.247 and confirmed. This covers the repaired declaration-to-discard path live, without claiming the exact two-candidate pixel composition was repeated. `riichi-tsumo-live-evidence.json` retains decision/execution and public confirmations. The two-stage riichi timeline5439ms spans two independently guarded clicks; the selection capture remains its existing second-click budget boundary. No guard was relaxed.
- Observed short-clock functional coverage passed in this match. The previous batched-geometry timing improvement is consistent with these clean samples, but no controlled end-to-end speedup or ranked continuity improvement is established. Prior code checks:233 Python tests OK /33 existing skips. Documentation diff check passed. Resume Copper ranked evaluation with2600ms and`--ranked-loop`, recording genuine match transitions separately from generic navigation events.

## 2026-10-20 e7b9784 Copper completion; withdrawn river-candidate correction

- Ranked Copper four-player East, confirmed account初心 and correct room before launch; frozen implementation5dfe9ae / launch e7b9784,5+20 clock, click budget2600ms, explicit action deadline300000ms,`--ranked-loop`. Completed08:48:06 UTC at22700 / second, rank points+8; opponents33800 /22500 /21000. Artifacts: `artifacts/ranked-copper-e7b9784-20261020/`.42 discard decisions,16 passes, two confirmed pons; ten budget expiries / aborted evaluations, two mismatch reports, one river reconciliation failure, one three-expiry ranked safety stop, one same-commit restart and away resume. No source/config changes or tests during play. Continuous ranked operation failed, despite second place. Only two genuine ranked samples across runs remain insufficient for win-rate conclusions.
- Original operator1370378 stopped08:37:33 on three consecutive2600ms expiries; restarted1378457 with identical settings, retaining the guard. A separate observer stopped the launcher only after independently logged final match result, before another queue, for maintenance. `boundary-maintenance-stop.json` records the final trigger; no live match was interrupted for maintenance. Final result was attached to replays from both operator instances. This run does not prove result-to-next-game continuity.
- At08:31:38,3m was clicked atx269 while the stored hand visibly held3m there and the clock showed4+20. At08:31:41.935 a public scan saw the correct3m append; after a call, scans08:31:44.526 and08:31:46.665 reverted to the prior river. The latter recognizes the opponent chi[4m,2m,3m]. The first append candidate stayed pending indefinitely because no later append agreed with it. At08:32:00 the next own turn explicitly waited; eventually automatic-looking8m replaced the absent append and was reported as a3m/8m mismatch. Do not call the original3m click a proven physical misclick. A similar4s-candidate wait preceded an8p mismatch in East4; retain it separately rather than assuming all mismatches share a cause. The East2 multi-append failure is also recorded separately.
- After match exit, replayed the immutable source frames through the unchanged hybrid public recognizer and saved all outputs. Exact before/after reproduction: old poll remained blocking after all three scans; corrected poll releases after the two distinct subsequent baseline observations and invalidates the concealed cache. This retires an unresolved click; it does not certify a discard or infer a successful opponent call. Public river history and the normal two-scan append confirmation remain unchanged.
- Retire a pending river candidate only after two later timestamp-distinct observations exactly match the trusted pre-click river. Repeated/older captures, partial/absent/misread rivers and missing timestamps cannot release the wait; a changed candidate resets withdrawal evidence. The next hand must be recognized again, and its own click/river receipt stands separately. Added actual public-scan fixtures plus negative and subsequent-discard tests. Full Python235 tests OK /33 existing skips; diff check passed. Live300+0 regression is next, followed by5+20 and renewed ranked evaluation. Remaining ranked timing overruns are not claimed fixed by this change.

## 2026-10-20 b29b355 friend coverage and lossless pre-click crop timing

- CPU friend room49983, visually verified300+0 seconds,25000 start /30000 return; frozen b29b355, explicit action deadline300000ms, click budget2600ms, no ranked loop. Completed08:59:41 UTC at21000 / third; CPUs38000 /22000 /19000. Artifacts: `artifacts/friend-300-b29b355-room49983-20261020/`.13 discard decisions, six passes, confirmed riichi; one prevalidation budget expiry/retry, zero own-discard mismatches, reconciliation failures, away resumes, safety stops or external interventions. Basic observed coverage passed. No withdrawn candidate or own call occurred; the repaired branch remains covered offline. Self lost1000 for riichi plus3000 on a CPU tsumo, rather than an observed wrong-discard operation.
- Same implementation, CPU friend room37156, visually verified5+20 with otherwise identical settings/deadline/budget. Completed09:15:21 UTC at23500 / third; CPUs53300 /24100 /-900. Artifacts: `artifacts/practice-5plus20-b29b355-room37156-20261020/`.63 discard decisions,18 passes, three prevalidation budget expiries/retries, zero own-discard mismatches, reconciliation failures, away resumes, safety stops or external interventions. Two initial all-noten draws retained25000, later self lost1500; the final large transfer was between CPUs. No own riichi/call/win or withdrawn candidate branch in this sample, so full coverage remains incomplete. No concurrent tests or runtime source/config edits during either match. CPU results remain separate from ranked evaluation.
- Profiled only after operator exit. On a saved ranked closed-hand frame,20 mocked-input executions (excluding browser communication, evaluator and queued stream callbacks) averaged141ms; default PNG compression accounted for about96ms per execution. The in-memory batched crops are used only for immediate pixel comparisons and discard confirmation. Store their PNG data at compression level0, retaining exact pixels, regions and all downstream safety checks. Saved screenshots and recognizer transport are unchanged.
- Across32 actual ranked/practice frames, every decoded crop matched exactly; average three-region crop time78.36ms before vs26.96ms after. The20-execution profile fell141ms to67ms. Transient encoded crop bytes increased from14.51MB to41.74MB summed across the32 cases; this trades temporary memory for compression time, not a loss of image evidence. `preclick-crops-parity-benchmark.json`, before/after profiles, baseline function and scripts retain scope and results. These are helper/mock-input measurements, not a measured whole-pipeline speedup or proof of ranked continuity.
- Updated the existing single-decode crop test to compare decoded mode, size and every pixel instead of compressed file bytes. Full Python235 tests OK /33 existing skips; diff check passed. Deadline300000ms, click budget2600ms and the three-expiry stop remain unchanged. Run new300+0 regression, then5+20 and ranked continuation evaluation.

## 2026-10-20 46d5db5 transient-crop live regression and practice

- CPU friend room86934, visually verified300+0 seconds,25000 start /30000 return; frozen46d5db5, explicit action deadline300000ms, click budget2600ms, no ranked loop. Completed09:28:09 UTC at21000 / third; CPUs38000 /21000 /20000. Artifacts: `artifacts/friend-300-46d5db5-room86934-20261020/`.12 discard decisions, one pass prompt, confirmed chi1p/2p/3p followed by compact-hand draws and discards; one prevalidation budget expiry, zero discard-click expiries, own-discard mismatches, reconciliation failures, away resumes, safety stops or external interventions. Loss was4000 paid on CPU dealer tsumo. An access-busy dialog during room creation was dismissed and retried before play; `artifacts/friend-300-46d5db5-preflight-20261020/access-busy.png` preserves it.
- Same frozen implementation, CPU friend room72877, visually verified5+20 with otherwise identical settings/deadline/budget. Completed09:37:44 UTC at22900 / third; CPUs33300 /22900 /20900. Artifacts: `artifacts/practice-5plus20-46d5db5-room72877-20261020/`.28 discard decisions, three pass prompts, confirmed pon F and subsequent compact-hand draws/discards; one rejected call due to2600ms budget, zero discard-click expiries, aborted discard evaluations, own-discard mismatches, reconciliation failures, away resumes, safety stops or external interventions. No tests or runtime source/config edits during either match.
- Basic observed operation passed in both matches. Neither had own riichi/win or a withdrawn river candidate, so full/targeted live coverage remains incomplete. Earlier unchanged riichi logic was exercised live on5dfe9ae; the withdrawn-candidate branch is covered by immutable-frame public-recognition reproduction and negative tests. Do not equate these CPU results or clean discard timing with a statistical ranked win-rate improvement or reliable ranked continuation. Resume correct Copper four-player East evaluation with2600ms and`--ranked-loop`; retain all deadline and stop guards. Prior code validation235 Python tests OK /33 existing skips; documentation diff check passed.

## 2026-10-20 9866a60 Copper match completion and first verified automatic next match

- Frozen implementation46d5db5 / doc-only launch9866a60, correct Copper four-player East,5+20 clock, explicit action deadline300000ms, click budget2600ms,`--ranked-loop`. First match completed10:22:47 UTC at20100 / fourth, rank points-19; opponents32300 /26100 /21500. Artifacts: `artifacts/ranked-copper-9866a60-20261020/`.131 discard decisions,28 passes, three confirmed calls, own riichi and ron; seven aborted evaluations (two prevalidation budget expiries and five changed-hand aborts), two mismatch reports, one reconciliation failure, two unresolved withdrawn candidates. Zero ranked budget stops, screen-loss stops, away resumes, restarts or external interventions. No runtime source/config changes or tests during play. Overall functional result failed because the timing/mismatch issues remain.
- The withdrawn-candidate correction was exercised twice:8m at09:52:32 and C at10:05:23 were retired only after two distinct baseline observations, with concealed-cache invalidation. Saved public observation independently recognizes the opponent8m pon. Subsequent fresh-hand decisions continued; the old indefinite pending-candidate wait did not recur in these cases. `withdrawn-candidate-live-evidence.json` retains timestamps and subsequent click/reconciliation events. Unresolved retirement does not certify the original discard.
- At10:01:00 the actual two-meld hand and drawn F were correctly represented, but the game clock already showed one second. Requested5m click followed10:01:01.700, about1.4s later; river appended F. This supports game-timeout involvement rather than a proven label/coordinate error. A subsequent5m receipt encountered that earlier untrusted F prefix, producing a multi-append reconciliation failure. Later1p/9p mismatch had4949ms from initial evidence; retain separately. `two-meld-timing-failure-evidence.json` records the decision, frame and mismatch evidence. The crop optimization did not solve all short-clock timing issues.
- Five1500-point noten payments reduced self25000 to17500 before East4; own riichi and final ron recovered2600 net to20100. The poor placement therefore includes repeated noten losses, with separate operational defects; do not attribute all lost points to misclicks or claim improved ranked win rate. Only three completed ranked samples across runs are available.
- Genuine final-result-to-next-game continuity is now verified once: same operator PID1428767, one process start, final match-result screenshot10:22:47.995, navigation, then a different opponent roster on a fresh Copper table with east_1/all25000, verified10:23:46.196 and confirmed discard10:23:46.672. `ranked-continuation-evidence.json` contains the final result, navigation, fresh board and first next-match decision. Generic lobby/menu events alone were not used as proof. Ranked process continuity passed this transition; full functional correctness and statistical playing improvement remain unproven. The second match is running; no live game was interrupted. Only this validation record was updated after continuation; running code/config remain frozen. Documentation diff check passed.

## 2026-10-20 ranked second-match browser closure and recovery

- After the independently verified next-match start, browser launcher1202672 and its browser disappeared. Operator1428767 logged`safety_stop` at10:24:04.225 with`Page.wait_for_timeout: Target page, context or browser has been closed` and exited. Thus the first final-result-to-next-match transition remains verified, but uninterrupted second-match operation failed. Do not describe the ongoing run as wholly intervention-free.
- Restarted the same persistent browser profile with headless software rendering (launcher1465613), observed the same opponent names and East2/self22400 on reconnection, then restarted operator1467669 with unchanged runtime implementation46d5db5, same2600ms budget/deadline/ranked-loop settings. Checkout7e8dc45 differs only in validation records. Away resume and subsequent confirmed discards were observed. Browser and operator each have one live instance; no runtime source/config edits or tests during the game.
- `browser-close-recovery.json`, `browser-restored-same-match.png` and`browser-recovery-stdout.log` preserve failure and recovery evidence. Exact browser exit cause remains unknown: inspected kernel messages did not establish a browser-specific OOM or segfault. Repeated Weston RDP backend faults were present, but are not evidence of the headless browser's cause. Current match/result tracking continues in the same artifact root. This addendum updates validation only; diff check passed.

## 2026-10-20 second ranked result and scoreboard-cache rim correction

- The second Copper four-player East match in `artifacts/ranked-copper-9866a60-20261020/` completed10:46:21 UTC at19600 / third, rank points-10; opponents37200 /26700 /16500. Runtime implementation remained46d5db5,5+20 clock, explicit deadline300000ms, click budget2600ms and`--ranked-loop`. After the previously recorded browser closure, operator1467669 resumed and completed the same match. A boundary observer stopped only after its final result, before a third queue, for maintenance. `second-match-boundary-maintenance-stop.json` records the trigger. Four completed ranked samples across runs remain insufficient for an improvement claim; their placements are3/2/4/3, not evidence of an upward trend.
- Second-match recorded events:47 completed discard decisions (48 clicks; the browser closed during one confirmation),15 pass prompts, own riichi and ron, one prevalidation expiry and one changed-hand abort. No new own-discard mismatch, reconciliation failure, ranked-budget stop or screen-loss stop. One unresolved withdrawn river candidate was retired, with subsequent normal operation. Browser outage/away recovery makes overall uninterrupted operation and full coverage fail. Self score sequence25000→22400 during unobserved outage round→20900 after1500 noten→22200 after1300 net riichi/ron→19600 after2600 dealer payment on opponent tsumo. The unobserved first-round loss was not assigned a fabricated cause. Final result attached only to second-match replays missing that evidence; outage round outcome remains unobserved. See `ranked-match-results.jsonl` and`second-match-recovery-outcome-repair.json`.
- After operator exit, investigated remaining short-clock OCR cost.139 pairs had identical verified scores/round, cache age at most8 seconds and no intervening outcome. Only7 passed the existing board signature. Mean RGB difference was15.04 in the own-score region,6.42 opposite and4.29 left despite unchanged numbers: the rectangles included the changing illuminated turn rim. `board-cache-signature-miss-reproduction.json` preserves every pair and per-region deltas.
- Tightened only the four score rectangles to retain the complete numeric glyphs inside their plaques and exclude the illuminated rims. Round/counter rectangles, RGB threshold3.0, cache TTL8 seconds, OCR confidence/conservation gates and click/deadline guards remain unchanged. With these rectangles119/139 unchanged pairs match; all21 actual score/round/honba/riichi transition pairs reject.20 remaining unchanged pairs still fall back to OCR. `proposed-board-boxes-reproduction.json` and`score-only-crop-change-evidence.json` retain positives and negatives. A one-digit opposite-score change26400→25400 has delta3.63 and rejects even with all other image pixels held fixed.
- Added four actual frame fixtures. Tests cover recent-cache reuse across turn illumination, expiry immediately beyond8 seconds, and the isolated digit change. Full Python237 tests OK /33 existing skips; focused final tests2/2; diff check passed. One actual unchanged-board pair with a warmed OCR engine took1071.28ms and one synchronous OCR call before vs10.84ms and zero OCR calls after; verified seat/round/scores/honba/riichi fields agreed. This is a single-pair cache-path measurement, not a whole-pipeline or ranked speedup claim. Existing cached remainingTiles/8-second freshness behavior is unchanged. New300+0 regression, then5+20 practice and renewed ranked evaluation are required. Browser-exit cause and durable recovery remain separate unresolved work.


## 2026-10-20 978be3a CPU regression and short-clock practice

- CPU friend room97062, verified300+0 seconds,25000 start/30000 target/red3, frozen978be3a, explicit action deadline300000ms, click budget2600ms, no ranked loop. Completed11:17:43 UTC at22500/fourth; CPUs28100/25900/23500. `artifacts/friend-300-978be3a-room97062-20261020/` retains settings, frames, recognition/decision/action logs and final result.69 decisions,17 passes, confirmed own riichi, two post-riichi changed-hand aborts; zero budget expiry, mismatch, reconciliation failure, away resume, safety stop or external intervention. No own call/win/withdrawn-candidate branch occurred, so basic observed coverage passed but full functional coverage remains incomplete.
- Score sequence25000→24000 after noten1000→22000 after CPU tsumo2000→21000 after riichi1000→22500 after final two-tenpai draw1500. Board cache applied63 times;69 decision timings had medians hand996ms, board15ms, recognition-and-decision1323ms. Descriptive single-match measurements do not establish a controlled pipeline speedup. `board-cache-live-summary.json` and `board-cache-live-transition-evidence.json` retain counts, timings and score/round/honba/riichi transitions.
- CPU friend room58836, visually verified5+20 seconds, same frozen978be3a, points/red/deadline/budget settings and no ranked loop. Completed11:25:55 UTC at30200/first; CPUs25000/25000/19800. Artifacts: `artifacts/friend-5plus20-978be3a-room58836-20261020/`. Four completed discard decisions, two passes, own riichi and ron (5200 plus returned own riichi stick), three post-riichi changed-hand aborts; zero budget expiry, mismatch, reconciliation failure, away resume, safety stop or external intervention. No own call/withdrawn-candidate branch; full coverage remains incomplete. Ron button disappearance was confirmed; its detection-to-click action timeline was3496ms, separate from the guarded discard/call click budget. Cache applied three times. No source/config changes or tests during either game.
- Both results are CPU functional/practice evidence, separate from ranked performance. The ranked sample remains four completed games with placements3/2/4/3; no win-rate improvement is established.

## 2026-10-20 Linux operator/browser supervision

- Added `python/operator_supervisor.py` around the existing launchers. Exact repository script/cwd process discovery adopts a live operator without connecting another Playwright client. Repository flock prevents a second supervisor. Existing launcher/profile processes prevent duplicate browser starts on CDP timeout; live operators are never stopped or restarted by the supervisor. SIGTERM/interrupt stops supervision only.
- After confirmed operator exit, preserve its terminal event and wait10 seconds before recovery. Only the known browser-close safety exception or exits without a terminal safety stop may restart automatically. Budget/recognition safety stops and normal friend completion persist a hold across supervisor restarts. The adopted log/pid is saved atomically so an exit while supervision is offline is still inspected. Each component is capped at three launches within10 minutes of supervision; browser and operator have separate limits. Each newly started ranked operator has2600ms budget,300000ms explicit deadline, ranked loop, a commit/command manifest and separate artifacts. Browser exit root cause remains unknown; this change supplies recovery rather than claiming a cause fix.
- Tests exercise actual process discovery and second-process lock rejection, live adoption without CDP, closed-browser recovery, short-clock launch settings, launcher startup, CDP timeout with surviving browser/profile, duplicate detection, bounded crashes, early/offline terminal safety stops and persisted holds. Full Python suite249 tests OK/33 existing skips; after separating component limits, final supervisor-focused13 tests OK and diff check passed. Live supervision evidence follows after verification. Linux-only; a hung surviving browser is intentionally left for diagnosis, and authentication failures are not solved automatically.


## 2026-10-20 dbc63bc supervised300+0 completion

- CPU room96571, visually verified300+0,25000 start/30000 target/red3; frozen dbc63bc, deadline300000ms/click budget2600ms, no ranked loop. Completed11:40:22 UTC at22900/second; CPUs34300/21500/21300. `artifacts/friend-300-dbc63bc-room96571-20261020/` retains manifest, preflight, full recognition/state/decision/action logs and final result.32 decisions,12 passes, own riichi, one initial prevalidation expiry (capture age2834ms; no click) and two post-riichi changed-hand aborts; zero mismatch/reconciliation failure/away/safety stop/external intervention. No own call/win/withdrawn branch, so full coverage remains incomplete; observed basic coverage passed. CPU placement is not ranked evaluation.
- Supervisor1517745 adopted already running operator1517623 at11:33:04 without modifying its friend settings or starting another operator/browser. Same operator ran through completion without restart. At11:40:27, supervisor recorded exit with `match_completed_stop` and persisted `operator_terminal_stop` hold, starting nothing further. Evidence: `artifacts/supervisor-dbc63bc-20261020/supervisor.jsonl` and `friend-completion-hold.json`. This verifies live adoption and normal-completion holding, not yet live browser-loss recovery. Supervisor was then stopped for the intentional transition to ranked operation; no live game was interrupted. Documentation diff check passed.


## 2026-10-20 automatic startup and supervised Copper entry

- After the completed CPU game, confirmed the lobby and absence of any live match. Archived/inspected the expected normal-completion hold, stopped supervision, and gracefully exited the existing browser before starting the supervisor again. At11:42:02 supervisor1525104 automatically started browser1525105; at11:42:12 it started ranked launcher1525285/operator1525292, using checkout75509d2 (runtime supervisor dbc63bc, playing implementation978be3a),2600ms click budget, explicit300000ms deadline and ranked loop. No manual ranked-menu clicks or second Playwright connection were used after supervisor start.
- Automatic lobby/ranked-menu navigation led to a real match. Viewed the first confirmed-decision screenshot `operator-20261020T114212657675Z/frames/2026-10-20T11-43-14.961329+00-00.jpg`: visibly Copper four-player East, distinct human opponent names, East1/all25000 and a live action timer. This proves both-absent automatic startup and actual ranked entry, beyond generic navigation events. `artifacts/supervisor-dbc63bc-20261020/automatic-startup-ranked-entry-evidence.json` retains startup/adoption/navigation and first-decision evidence. The operator remains running under supervision; result and uninterrupted continuity are pending. First prevalidation expiry2760ms was followed by normal reobservation/confirmed discard. No mismatch or reconciliation failure at this checkpoint. No runtime source/config edits or tests during play.
- Live unexpected browser-closure recovery has not been injected during a game; its branch is covered by tests using the previously observed real exception. The controlled lobby browser exit above verifies automatic startup without interrupting a match. Documentation diff check passed.


## 2026-10-20 supervised ranked result and opposite-river seven-pin failure

- Supervised Copper four-player East run `artifacts/supervisor-dbc63bc-20261020/operator-20261020T114212657675Z/` completed12:07:32 UTC at12000/fourth, rank points-28; opponents48100/27300/12600. Launch75509d2/runtime playing978be3a/supervisor dbc63bc, explicit deadline300000ms/click budget2600ms/ranked loop. Same operator1525292 and browser1525105 throughout;63 discard decisions,21 pass prompts, one chi, own riichi and ron, two prevalidation expiries and11 changed-hand aborts; one recognition retry. Zero own-discard mismatch/reconciliation failure/away/safety stop/browser or operator recovery during play. This verifies uninterrupted operation for this match, not full recognition correctness. After its final result, a boundary observer stopped supervisor and launcher before the next queue to investigate the confirmed defect; no active match was interrupted. Final-result attachment was repaired for one replay interrupted by the boundary stop. Worker EPIPE during shutdown was after final result, separate from in-game failures.
- Ranked samples now total five, placements3/2/4/3/4, average3.2; cumulative rank-point change-56. No improvement claim. CPU practice/regression outcomes remain separate. Score sequence in this game25000→24000 riichi→22000 opponent tsumo→10000 dealer ron12000→7300 opponent tsumo2700→6300 riichi→11500 own ron→10500 riichi→12000 two-tenpai draw. Own ron net after own riichi was4200; the final draw left the own stick on table. Final opponent ron did not change self12000.
- At East3/0, three opponents were in riichi. The correct own hand/draw was recognized,6p was selected and actually discarded at11:54:40.237 with hand/river-change confirmation; dealer then ron, self22000→10000. The dealer river in the decision incorrectly ended6p, while the saved frame visibly ends7p. `east3-12000-loss-evidence.json`, full frame and upright river detail preserve input/action/result. Actual full Hybrid recognition reproduced6p with7p runner-up at0.599085 on the background source and0.621043 on the decision frame; both were incorrectly marked safe. Adding crop padding did not reliably recover7p and was not adopted.
- The existing hand-only `isKnownSixSevenPinConfusion` gate already rejects Hybrid6p/7p competition below0.788. Applied the same unchanged gate to public Hybrid predictions. This prevents the wrong6p becoming verified genbutsu and allows the existing bounded discard-boundary retry to run. On both saved frames it preserves all15 river candidates/the sideways5m/accepted tiles and recovers the final7p at0.754089/0.735245. No unconditional6p→7p relabel, clock/budget change, expanded retry loop or policy change. If refinement cannot resolve the face, the uncertain region is not published as known tiles.
- Input-only causal control: correcting only the dealer's last tile6p→7p changes6p's dealer danger from0/genbutsu to0.0816, combined0.136704→0.207149. The actual Jev candidate-filtering path offers only6p with the wrong input, versus8s/2p after correction. Thus the recognition error affected the selected action's eligibility, independent of a speculative remote model rerun. This establishes an input/decision defect; it does not prove a different final rank or future win rate. See `opposite-pin-causal-counterfactual.json`, before/after reproduction and padding-probe JSONs.
- Added a tracked real frame/state fixture, live Hybrid refinement regression, ambiguity-boundary controls including accepted correct6p competition at0.788, and a no-network test of the actual Jev filtering path. Build passed; full TypeScript suite209 tests:204 passed/5 existing skips/0 failures; diff check passed. New300+0 regression and5+20 practice are required before renewed ranked evaluation. No source/config changes or tests during the ranked game.


## 2026-10-20 2f1d212300+0 regression and active5+20 practice

- CPU friend room20612, verified300+0 seconds/25000 start/30000 target/red3, frozen2f1d212, explicit deadline300000ms/click budget2600ms/no ranked loop. Completed12:22:01 UTC at13000/fourth; CPUs49000/19000/19000. `artifacts/friend-300-2f1d212-room20612-20261020/` contains preflight, command/settings/commit manifest, full recognition/state/decision/action logs and result.18 completed discard decisions, four passes, confirmed pon with hand/meld changes and subsequent compact-hand discards; zero budget expiry/aborted evaluation/mismatch/reconciliation failure/away/safety stop/external intervention. Last opponent tsumo moved self25000→13000 as dealer; no own deal-in is inferred from the fourth place. Observed discard/pass/pon/post-call/completion coverage passed; no own riichi/win/withdrawn-candidate branch, so full functional coverage remains incomplete. The specific ambiguous7p refinement is covered by the real-frame offline regression, not claimed as independently exercised in this match.
- Supervisor1556557 adopted operator1556249 and held on normal CPU completion, without starting another game. Archived normal-completion hold before the intentional transition to the next practice game. No source/config edits or tests during play.
- Same frozen2f1d212 started CPU room96152, visually verified5+20 seconds, same points/red/deadline/budget settings/no ranked loop. `artifacts/friend-5plus20-2f1d212-room96152-20261020/` retains settings/preflight/logs. Operator1561643 runs under supervisor1562012; final result pending. Through East3/1:45 decisions, ten passes, confirmed own ron, zero budget expiry/aborted evaluation/mismatch/reconciliation failure/away/safety stop/external intervention. East1 all-noten draw kept25000; East2/1 own ron moved self28900; East3 three-opponent-tenpai draw cost3000, self25900. Do not promote this checkpoint to a completed short-clock regression or ranked-performance evidence. Documentation diff check passed.


## 2026-10-20 2f1d2125+20 completion

- CPU room96152 completed12:36:00 UTC at36200/first; CPUs26000/22100/15700. Frozen2f1d212, visually verified5+20 clock/25000 start/30000 target/red3, explicit action deadline300000ms, click budget2600ms, no ranked loop. `artifacts/friend-5plus20-2f1d212-room96152-20261020/` contains settings/commit, recognition/state/decision/action logs, frames and final result.50 completed discard decisions,13 passes, own riichi and two confirmed rons; no own call. One `before_reaction_call_click` expiry at capture age2765ms caused no call click, plus three post-riichi hand-change aborts. Zero mismatch/reconciliation failure/away/safety stop/external intervention. Basic observed short-clock operation passed, while full coverage remains incomplete (no own call/withdrawn branch in this match). No source/config edits or tests during play.
- Score sequence25000→28900 first ron→25900 three-opponent-tenpai draw→24900 own riichi→36200 final ron including table sticks. This first place is CPU practice evidence, not ranked improvement. Supervisor1562012 adopted operator1561643 and persisted the expected normal-completion hold; archived the hold before stopping supervision only after completion to prepare renewed ranked evaluation. Relevant documentation diff check passed; prior209-test TypeScript suite/build remain the implementation checks for unchanged runtime2f1d212.
