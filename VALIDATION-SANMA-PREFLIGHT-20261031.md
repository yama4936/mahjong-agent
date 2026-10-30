# 三麻の実行前確認（2026-10-31）

## 実行状況

- 確認時のリポジトリ HEAD: `801fe7f`。
- 専用ブラウザは既存の CDP ポート 9222 で稼働していた。操作者と、その子プロセスとして起動する認識サーバーは稼働していなかった。
- 当初の画面は四人友人戦ルーム 60771 上の「他の場所でログインされました」という表示だった。別端末は対局中でなく再接続してよいというユーザーの許可を受け、既存ブラウザで再ログインした。ログイン後はホーム画面であり、進行中の対局は表示されなかった。
- 三麻友人戦ルームを作成し、開始前の待機画面で止めた。操作者を起動せず、対局開始ボタンは押していない。

## 三麻友人戦ルーム

- ルーム ID: `69669`。三人麻雀、東風戦、長考時間 `300+0秒`。
- プレイヤー本人と CPU（簡単）2人が準備済み。開始時 35000 点、1位必要点数 40000 点、飛び有効、赤ドラ2、ツモ損有効、喰い断有効、一飜縛り。
- ルーム設定と準備画面の記録: `artifacts/sanma-preflight-20261031/jantama-sanma-settings.png`、`artifacts/sanma-preflight-20261031/jantama-sanma-ready.png`。
- この時点で操作者は起動していないため action deadline の実行時設定はない。友人戦を実施するときは `--action-deadline-ms=300000` を明示する。

## 段位戦画面

- 銅の間の対象として画面に「初心者、雀士」と表示され、選択肢には四人東、四人南、三人東、三人南があった。三人東の選択肢を押しての参加可否確認やマッチングは行っていない。
- プロフィール画面の大きな段位表示は雀士1、31/600。三麻友人戦の本人枠には初心・星1が表示されていた。
- 記録: `artifacts/sanma-preflight-20261031/jantama-profile.png`、`artifacts/sanma-preflight-20261031/jantama-ranked-menu.png`、`artifacts/sanma-preflight-20261031/jantama-bronze-menu.png`。

## 直前の友人戦試行

- `artifacts/friend-300-a11259e-20261031/operator-lifecycle.jsonl` によると、この試行は `--action-deadline-ms 300000`、`--force-auto-click-budget-ms 8000` で起動され、操作者は終了コード 1 で停止した。
- `operator-stderr.log` には、確認済み友人戦ルームの画面との照合が16回連続で一致せず `RuntimeError: friend room did not match reviewed preflight in consecutive captures` になったことが記録されている。この試行の完走は確認できない。

三麻友人戦の事前確認部品は操作者の開始経路に未接続で、自動対局は未実装である。CPU2人と準備状態は人手で確認した画像との一致によって確認するもので、独立した状態認識ではない。部品の Python 試験22件はメインの実行環境で全件成功し、スキップはなかった。詳細は `SANMA-FRIEND-PREFLIGHT-VALIDATION.md` を参照。三麻の実対局による機能試験・300+0秒の回帰試験は未実施である。CPU友人戦は機能確認用であり、段位戦の勝率評価は未実施である。画面画像と実行ログはローカルの artifacts に保存されている。
