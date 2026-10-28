# 雀魂ライブ観戦

公開ページ: https://jantama.yama.asia/live.html
配信元: https://jantama-live.yama.asia/

対局PC上のDockerが、既存の雀魂タブをCDPで読み取り、最大3fps・1280×720のJPEGをWebSocketで配信します。音声・遠隔操作・判断ログの公開はありません。動画コーデックによる30fpsの配信ではなく、低フレームレートの連続画像配信です。

## 起動・停止

リポジトリルートで実行:

```sh
docker compose -f deploy/live/compose.yml up -d --build
docker compose -f deploy/live/compose.yml ps
curl http://127.0.0.1:4383/health
docker compose -f deploy/live/compose.yml logs --tail 30
# 配信だけを停止（操作者やブラウザは停止しない）
docker compose -f deploy/live/compose.yml stop
```

Linuxのhost networkでループバックのCDP（9222）へ接続し、HTTPは127.0.0.1:4383だけで待ち受けます。ブラウザを新規起動したり、既存のscreencastを開始・停止したりしません。閲覧者がいないときは画面取得を休止します。Chromeやゲームが停止したら待機・再接続し、復旧後に再開します。Docker起動時はunless-stoppedで再起動します。

コンテナは非root、read-only、cap_drop ALL、メモリ256MiB、CPU上限1、ログローテーション付き。ブラウザプロファイル、運用ログ、Dockerソケットはマウントしません。ゲームURLと画面分類で公開可否を判定し、match/round_result/match_resultかつconfidence=1、1920×1080だけを縮小して送ります。不明・ログイン・ロビーなどは画像を送らず待機へ切り替えます。画像分類は絶対的な保証ではないため、プライベートな作業をする場合は配信を停止してください。

## 公開経路

既存のgenesia Tunnel（386d9cad-1ab0-4d3d-8903-7c7b9aa2de48）に次のingressを追加。ホスト側設定は `/home/yama1/services/genesia-site/cloudflared/config.yml`。

```yaml
  - hostname: jantama-live.yama.asia
    service: http://127.0.0.1:4383
```

末尾の404ルールより前に置き、`cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate`で検証してconnectorを再起動します。DNSは同Tunnelのcfargotunnel.com宛のproxied CNAMEです。CDPポートをTunnelに公開しないでください。既存ホストのルールを保持してください。

公開APIはGET `/health`と受信専用`/ws`のみ。ファイル配信は3つの固定アセットのみで、リクエストからCDPメソッドや対象URLを指定できません。WebSocketはブラウザOriginを許可リストで確認し、最大16接続、各接続1フレームのキュー、送信期限3秒です。未知のOriginやクライアントからのデータ送信を拒否します。一般公開の閲覧サービスであり、Originチェックはユーザー認証ではありません。

WebSocketはmetadata JSONとJPEGバイナリの順で送信します。状態・撮影時刻・連番のみを公開し、生のCDP応答やエラー内容は送りません。待機状態・切断・4秒以上の映像停止でプレイヤーは画像を隠します。古い画像を新規閲覧者へ再送しません。非表示タブでは接続を閉じ、再表示で接続します。

## サイト更新

`web/results/src/live.html`が公開プレイヤーをiframeで表示します。Sitesへの反映は`web/results/README.md`の手順で、既存Site IDと一般公開の設定を維持します。配信サービスのUI変更はDockerを再ビルド、アーカイブ側の変更はSitesを再公開してください。

## 検証

```sh
node --check web/live/live.js
docker run --rm --network none -v "$PWD/web/live:/app/web/live:ro" jantama-live:local python -m unittest discover -s web/live -p test_server.py -v
```

`VALIDATION.md`に公開経路とブラウザの実測確認を記録しています。操作者のライブ機能・回帰テストを実施する場合は友人戦300+0、操作期限300000msを明示し、段位戦の成績評価とは分離します。

停止・撤去時はcompose stop/downを実行し、このホストのDNSとingressだけを削除します。他のTunnelルールやサービスは保持します。

参照: [aiohttp WebSocketResponse](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.WebSocketResponse)、[CDP Page.captureScreenshot](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-captureScreenshot)、[Cloudflareのローカル設定](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)。
