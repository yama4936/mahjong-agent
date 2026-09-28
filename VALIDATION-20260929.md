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
