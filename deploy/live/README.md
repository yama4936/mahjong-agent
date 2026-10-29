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

コンテナは非root、read-only、cap_drop ALL、メモリ256MiB、CPU上限1、ログローテーション付き。ブラウザプロファイルとDockerソケットはマウントしません。artifactsを読み取り専用でマウントし、最新の操作者JSONLから公開用の判断・イベントだけを抽出します。元ログ、パス、例外全文、認証情報を配信する経路はありません。画面取得の前後で雀魂のURLを確認し、そのタブ内の全画面（ログイン・ロビー・設定・読み込み・対局・結果）を配信します。画面分類や1920×1080固定の条件は使用しません。縦横比を保って最大1280×720へ縮小し、状態はliveとして通知します。対象タブがない場合や取得に失敗した場合は待機・再接続します。

映像上部には選択行動、推定和了率・推定放銃率、認識信頼度、安全判定、シャンテン数と判断時刻を表示します。確率は選択した候補の評価値で、実測勝率ではありません。値がない場合は「—」、15秒以上前の判断や配信停止中は過去の判断と表示します。局・対局結果や操作者停止で判断をクリアします。右側は最大100件の公開用ログで、末尾表示中だけ自動追従します。スマートフォンでは映像の下に配置します。

ログ読み取りは100msごと、最新ファイル探索は1秒ごと。映像とは独立した受信専用WebSocket `/events` で、変更時に判断と最新100件のログを通知します。映像停止中も通知でき、接続切断は3秒後に再接続します。ログ欄のLIVEは接続状態、データ受信時刻と最新ログ時刻はそれぞれ別に表示します。「↓ 最新へ」で末尾追従へ戻せます。初回読み取り・1回の追記読み取りは512KiB以内です。

これはログ記録後の配信遅延を短縮する仕組みです。現在の操作者の `decision` イベントは打牌操作と確認の完了後に記録されるため、その処理時間は加わります。判断確定直後の通知には操作者側の記録タイミングの変更と次回起動が必要です。対局中は操作者のコードや起動設定を変えずに観測します。

## 公開経路

既存のgenesia Tunnel（386d9cad-1ab0-4d3d-8903-7c7b9aa2de48）に次のingressを追加。ホスト側設定は `/home/yama1/services/genesia-site/cloudflared/config.yml`。

```yaml
  - hostname: jantama-live.yama.asia
    service: http://127.0.0.1:4383
```

末尾の404ルールより前に置き、`cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate`で検証してconnectorを再起動します。DNSは同Tunnelのcfargotunnel.com宛のproxied CNAMEです。CDPポートをTunnelに公開しないでください。既存ホストのルールを保持してください。

公開APIはGET `/health`、受信専用`/ws`、GET `/results/data.json`です。ファイル配信はプレイヤーの3アセットと、公開用に書き出した24桁ハッシュ名のWebP画像に限定し、リクエストからCDPメソッドや対象URLを指定できません。WebSocketはブラウザOriginを許可リストで確認し、最大16接続、各接続1フレームのキュー、送信期限3秒です。未知のOriginやクライアントからのデータ送信を拒否します。一般公開の閲覧サービスであり、Originチェックはユーザー認証ではありません。

WebSocketはmetadata JSONとJPEGバイナリの順で送信します。状態・撮影時刻・連番のみを公開し、生のCDP応答やエラー内容は送りません。待機状態・切断・4秒以上の映像停止でプレイヤーは画像を隠します。古い画像を新規閲覧者へ再送しません。非表示タブでは接続を閉じ、再表示で接続します。

## サイト更新

`web/results/src/live.html`がプレイヤーを直接表示し、公開WebSocketを受信します（iframeは使用しません）。Sitesへの反映は`web/results/README.md`の手順で、既存Site IDと一般公開の設定を維持します。配信サービスのUI変更はDockerを再ビルド、アーカイブ側の変更はSitesを再公開してください。

## 検証

```sh
node --check web/live/live.js
docker run --rm --network none -v "$PWD/web/live:/app/web/live:ro" jantama-live:local python -m unittest discover -s web/live -p test_server.py -v
```

`VALIDATION.md`に公開経路とブラウザの実測確認を記録しています。操作者のライブ機能・回帰テストを実施する場合は友人戦300+0、操作期限300000msを明示し、段位戦の成績評価とは分離します。

停止・撤去時はcompose stop/downを実行し、このホストのDNSとingressだけを削除します。他のTunnelルールやサービスは保持します。

参照: [aiohttp WebSocketResponse](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.WebSocketResponse)、[CDP Page.captureScreenshot](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-captureScreenshot)、[Cloudflareのローカル設定](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)。

対局一覧の自動更新には `../results/README.md` のsystemdタイマーを使用します。コンテナには `.runtime/public-results` だけを読み取り専用でマウントし、元のログは公開しません。
