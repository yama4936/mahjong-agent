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
- 対局開始を実画面で確認。結果は未確定。

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
