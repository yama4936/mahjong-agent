# 三麻友人戦の通信監査

この監視は通信先の同定に使う読み取り専用の診断です。対局の安全条件、入力可否、切断時の停止条件には影響しません。通信内容や URL、認証情報は保存せず、接続 ID とホスト名の SHA-256、送受信回数だけを記録します。

既存の雀魂ページを開いたまま、次のログイン・再接続操作より前に、SSD 上の保存先を指定して起動します。

```sh
/home/yama1/.local/bin/jantama-dev run -- /home/yama1/projects/jantama-auto/.runtime/python-auto-venv/bin/python python/sanma_socket_watch.py --cdp http://127.0.0.1:9222 --output /home/yama1/server/data/dev-work/jantama/socket-audit/session.jsonl
```

`socket_watch_attached` と `sanma_socket_audit_started` が記録されたことを確認してから、別の操作担当がログインまたは再接続を行います。ページの追加・移動・クリックやブラウザの起動・終了は行いません。既に存在する接続について CDP は作成イベントを遡及しないため、そのホストは不明です。送受信があれば ID と回数は記録できますが、ゲーム用接続である証明にはなりません。監視開始後に新たに開いた接続だけは、作成と閉鎖を ID で対応付けられます。ページが閉じられたら監視も終了します。

同時に起動できる監視は1つです。監視を終了する際は監視プロセスへ SIGTERM または Ctrl-C を送ります。監視終了は既存ブラウザの終了を意図しません。ログがなければ監視できたとは扱わず、確認済みの停止条件を維持します。
