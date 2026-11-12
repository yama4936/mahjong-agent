# 三麻・相手リーチ時の河欠損調査

調査・修正は `ssd/sanma-riichi-river`（分岐元 `525f4de`）で実施。
サブエージェントが証拠調査と修正レビューを担当した。main の作業ファイル・ブランチ、ブラウザ、対局は変更していない。

## 根拠と原因

- `/home/yama1/server/data/dev-work/jantama/evidence186/baseline/board-runtime.json` は、保存画像 `manual-15-before.png` に対し `board.reason=expected_total_points_unknown` と `layoutCandidate={verified:false, opponents:["left","right"]}` を同時に返している。
- `python/board_metadata.py` は左右配置候補を保持しつつ、点数整合性の検証結果で `reason` を上書きする。一方 `src/recognition/sanmaAutoFrameObservation.ts` は `unsupported_right_opponent_layout` という単一の理由だけで左右河の観測を許可していた。
- 結果として `leftRiver` / `rightRiver` が欠損する。`python/sanma_friend_discard_experiment.py` の `friend_genbutsu_candidate` は `None` を返し、相手リーチ候補がある場合に `opponent riichi candidate; safe discard unverified` を送出する。操作者の例外処理は `sanma_friend_stopped` を記録して終了する。
- evidence186 の `baseline/repaired-riichi-runtime.log` に同じ実画像 resident テストの失敗がある。本 worktree の修正前再実行も frame15 の `result=None` で失敗した。
- 指定された `python/sanma_friend_riichi_threat.py` は存在しない。該当テストは `python/test_sanma_friend_riichi_threat.py`、実装は上記 discard experiment モジュール。

調査した既存ログから実対局中の当該停止は確認できなかった。ここで実証したのは保存実画像での河欠損と、その場合の停止コード経路であり、新たな実対局の結果ではない。

## 修正

左右の物理河生成は、`reason` ではなく明示的な未検証の左右配置候補を条件とする。点数情報や風の確定は河画像の観測条件にしない。点数合計不明時は左右河の推論も report 完了を待ち、自河と同じ直列キューを使用する。

同一画像 digest、候補の未検証・不完全・操作不許可属性、現物候補の信頼度と全リーチ相手との一致条件、欠損時の停止条件は維持する。

## オフライン検証

作業場所: `/home/yama1/server/data/dev-work/jantama/worktrees/sanma-riichi-river`。
コマンドは `jantama-dev run --` 経由。Python は `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=python` を指定。
既存の node_modules、Python/model runtime、bootstrap templates を参照し、インストールや更新は行っていない。

- 修正前: `python -m unittest -v test_sanma_friend_riichi_threat.ResidentRiverCandidateTests` — 1件エラー（frame15 の候補欠損）。
- 修正後: `python -m unittest -v test_sanma_friend_riichi_threat test_sanma_friend_riichi_experiment test_sanma_friend_riichi_multi` — 19件成功、skipなし。保存画像15/21/23/42を resident 認識器で処理し、単独リーチの現物候補、複数リーチ時の一致・不一致、危険なクリック拒否を含む。ページとクリック送信はモック。
- `node --import tsx --test test/sanmaAutoOwnRiver.test.ts test/sanmaIndependentRivers.test.ts` — 13件成功、skipなし。点数不明時の左右河生成、誤配置・候補欠損の拒否、推論失敗、同一画像属性、推論直列化、点数検証成功時の配置保持を検証。
- `npm run build` — 成功。

ログ保存先: `/home/yama1/server/data/dev-work/jantama/evidence-sanma-riichi-river/` の `baseline.log`、`riichi-tests.log`、`observation-tests.log`、`build.log`。

## 残るリスク

物理配置候補を保持する他の点数検証結果でも河生成を行うため、以前は省略されていた推論時間が加わる。実対局での遅延・連続運転・認識精度は未評価。河と現物候補は引き続き未検証であり、安全牌や合法操作を保証しない。配置・河・一致牌が確認できない停止は残る。

本作業では対局を行っていない。後続の機能確認は友人戦 `300+0`、操作者の `action_deadline_ms=300000` を明示して行い、設定と結果を記録する。段位戦の勝率評価や短時間制限への性能主張とは分ける。
