# 三麻友人戦 回帰187（2026-11-12）

## 判定

同一対局を補助操作で終局まで完了。自動完走は不合格。最終順位は自家2位29,100点、CPUは59,200点・16,700点。終局実画面は `manual-64-observe.png`（13:46:08 JST取得）。段位戦の勝率評価ではなく、短時間制限での動作保証もしない。

## 条件と統合

- 使用commit: `36314ba13c88453d0d1d00fd426ee60c67077c5c`。main/origin/main `525f4de` からfast-forwardし、origin/mainへpush済み。
- 友人戦98577、三麻東風、CPU簡単2人、300+0秒、初期35,000点・返し40,000点。
- `--action-deadline-ms 300000 --force-auto-click-budget-ms 8000`。完全な起動引数は `run-operator-3.sh`、条件は `settings.json`。
- Python 19件、TypeScript 13件、build成功。`riichi-tests.log`、`observation-tests.log`、`build.log`、`push.log`。
- サブエージェント review_integration が統合関係、開始画面差分、停止原因と速度を独立調査。
- 初期確認でブラウザ・操作者・認識サーバーは停止していた。ブラウザ1個を復旧し、ロビー実画面を確認。既存対局や正常な操作者を停止していない。

## 自動操作の結果と制約

開始前の2回は設定画面の背景アニメーション差分で照合を通過せず、開始クリックなしで終了。元画像を改変せず再選択し、同じ部屋の設定とCPUを実画面で確認して3回目に開始した。照合閾値・コード・設定は変更していない。

13:11:40 JST開始。13:20:18 JST、東1局の `discard_recovery_action_requires_review` で操作者が自然停止（exit 0）。終了コード0でも対局成功を意味しない。打牌確認が未確定の復帰処理中に北抜き候補が現れ、安全停止した。停止時の実画面は残り148秒であり、300秒期限超過が原因ではない。

自動操作は北抜き1回と打牌試行3回。実画面で自家河の1索・9萬・南を確認したが、ログ上は `selection_confirmed` / `discard_not_verified`、遷移は `visual_change_unconfirmed` であり、打牌確認機構の成功とは判定しない。停止前に他家リーチはなく、河認識修正のリーチ局面での実戦検証は未達。

独立集計では自摸番観測86回、認識時間中央値1,684.5ms（最大3,778ms）、観測全体中央値4,213ms（最大6,208ms）。画像変化による再観測74回、クリック直前再観測4回。安全確認の反復で初回の観測時計開始から打牌試行まで約142秒を要した。実戦速度・安定した進行には課題が残る。

8,000msのclick budgetは起動引数に指定済み。ただし実験的三麻の `execute_friend_draw_candidate` → `execute_friend_discard` 経路は共通の `require_force_auto_click_budget` を呼ばず、独自の期限・鮮度検査を使用している。南の候補から試行まで約8.73秒（元フレームから約12.26秒）。したがって全入力が8秒以内という合格判定はできない。今回この実装は変更していない。

## 停止後の補助と証拠

操作者の停止を確認後、再起動せず、毎回実画面を確認して同じ対局を補助した。北抜き、打牌、リーチ、ロン、ポン、局間確認を実施。リーチ後はゲーム標準の自動打牌が進行した。東1局、東1局1本場、東2局の流局、東3局1本場を経て終局。補助部分を自動操作者の成功件数に含めない。

入力時刻・座標・種別は `assistance.jsonl`、各入力前後と観測画面は `manual-*.png`。画像ファイル名中の牌名は操作時の仮ラベルで、正確な牌譜ではない。実画像を根拠とする。補助スクリプトは証拠ディレクトリ内だけに保存し、対局中の実行コード・設定は変更していない。終局後に保存済みSHA256の4ファイルすべて一致を確認した。ブラウザは終局画面で維持し、操作者・認識サーバーの再起動はしていない。

証拠の保存先: `/home/yama1/server/data/dev-work/jantama/evidence187`。
主要証拠: `operations.md`、`settings.json`、`operator-console-3.log`、`attempt3/artifacts/`、`transitions/`、`stopped-current.png`、`assistance.jsonl`、`manual-64-observe.png`、`code-config-sha256.txt`。全開発用一時ファイルは `jantama-dev run` のSSD設定を使用。
