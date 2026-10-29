# 対局記録の自動反映

対局PCのユーザーsystemdサービスが終了記録を公開形式へ書き出します。完了から60秒後に次回集計を開始し、同時実行はしません。集計時間とページの取得間隔30秒を含め、反映まで通常数分かかります。終了イベントが未記録の対局は掲載しません。

出力先はリポジトリの `.runtime/public-results`。画像変換完了後、data.json.tmpをdata.jsonへ同一ディレクトリ内でrenameします。失敗時は直前のdata.jsonを保持します。生成画像はハッシュ名で不変、古い画像も表示中のページ用に保持します。

## 設置

このPCは /home/yama1/projects/jantama-auto、Nodeは /usr/bin/node を使用します。別PCではサービスのWorkingDirectoryとExecStartを調整してください。

```sh
mkdir -p .runtime/public-results
node web/results/export.mjs . .runtime/public-results
mkdir -p ~/.config/systemd/user
cp deploy/results/jantama-results.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now jantama-results.timer
docker compose -f deploy/live/compose.yml up -d --build
```

公開サービスはこの出力ディレクトリだけを読み取り専用マウント。JSONと24桁ハッシュ名の画像のみGETで公開し、集計の実行や元ログ取得のAPIは提供しません。許可されたサイトにCORSを付与し、JSONはno-storeで返します。

## ページの動作

一覧・役の分析・グラフは30秒ごとに取得。非表示中は取得を休止し、再表示やオンライン復帰で即時取得します。検索・種別・表示件数・開いている結果詳細は維持します。詳細を閉じて開き直すと新しい記録内容が表示されます。

初回接続失敗時はSites同梱データへフォールバック。その後も再接続します。更新中の障害では表示済みデータを保持します。生成時刻が5分以上前の場合は更新遅延を表示します。PC停止中も同梱データを閲覧できます。

## 運用

```sh
systemctl --user list-timers jantama-results.timer
systemctl --user status jantama-results.service
journalctl --user -u jantama-results.service -n 20
# 即時集計
systemctl --user start jantama-results.service
# 自動更新の停止
systemctl --user stop jantama-results.timer
```

このPCはユーザーlingerが有効で、ログアウト後もタイマーを実行します。出力ディスク容量とサービス失敗は上記で確認できます。Sitesの再公開は画面変更時だけ必要です。
