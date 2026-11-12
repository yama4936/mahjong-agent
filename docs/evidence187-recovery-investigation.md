# evidence187 の打牌復帰停止調査

## 結論

`discard_recovery_action_requires_review` の直接原因は、南の未確認打牌について後続自摸番の証拠候補を受け入れた後、北抜き候補が現れたこと。既存実装は復帰監視中の操作候補を一律停止するため、北抜きの通常実行検査まで到達しなかった。

ただし、実際の停止時点で元の復帰期限は約317.22秒経過していた。画面に残り時間があっても、元の300000ms期限を保持する設計上、この時刻からの自動入力を安全と認定できない。一律停止を単に北抜き例外へ変える修正では不十分。旧期限、セッション継続性、操作候補、鮮度、クリック直前検査を維持し、期限切れの本事例は拒否する必要がある。

## 調査範囲

サブエージェントが保存済みログ・receipt・画像を読み、下記画像を `view_image` で目視確認した。ブラウザ操作、現行対局操作、サービス起動は行っていない。対局は補助操作で終局済み。元証拠は読み取りのみとし、新規作業は専用SSD worktreeで行った。

証拠ルート: `/home/yama1/server/data/dev-work/jantama/evidence187`。

`settings.json` の条件は友人戦98577、三麻東風、CPU簡単2人、300+0秒、`actionDeadlineMs=300000`、`clickBudgetMs=8000`、使用commit `36314ba13c88453d0d1d00fd426ee60c67077c5c`。本調査は機能回帰であり、段位戦勝率や短時間設定の評価ではない。

## 保存証拠の時系列（JST）

ログは `operator-console-3.log`。時刻はログのUTCに9時間を加算した。

| 時刻 | 証拠・観測 |
| --- | --- |
| 13:14:20 | 1索打牌が `selection_confirmed` / `discard_not_verified`。後続の復帰候補を13:14:43に受理。 |
| 13:14:52 | 9萬打牌も同じ未確認結果。後続の復帰候補を13:15:17に受理。 |
| 13:17:55 | 南打牌前画像。自河は1索・9萬、自摸は南、残り山46、画面時計122秒。 |
| 13:17:58.951334 | 南打牌のjournal `attempted`。`attemptedMonotonic=71089.12084513`。 |
| 13:18:09.614105 | journal `selection_confirmed`。`selectedMonotonic=71099.783619209`。打牌成功扱いではない。 |
| 13:18:27.757796 | `visual_change_unconfirmed`。`confirmed=false`。 |
| 13:18:28 / 13:18:34 | 復帰判定用の2観測。13:18:28画像では自河に南が追加され、残り山43、自摸北、北抜き・スキップ表示、画面時計285秒。 |
| 13:18:43.421062 | 復帰候補を受理。`originalStart=70911.441652807`、`confirmed=false`、`operationAuthorized=false`。 |
| 13:18:43–13:20:13 | `observation_changed_reobserve` が20回（受理時のreceiptに対する1回と、その後19回）。最終streakの経過90.2秒。手牌・他領域・壁色などの鮮度検査に通らず再観測。 |
| 13:20:15 | 停止直前の認識元画像。自河1索・9萬・南、残り山43、自摸北、北抜き・スキップ、画面時計179秒。 |
| 13:20:18.312890 | `stable_kita_glyph_candidate`。kita guardはcenterでacceptedだが、receipt全体は未承認。 |
| 13:20:18.494377 | `discard_recovery_action_requires_review`、`operationAuthorized=false`。 |

停止後の `stopped-current.png` は同じ局面で148秒を表示する。これは停止瞬間の画像ではなく、停止後の保存画像である。

目視した打牌前後画像のパス（上記証拠ルートからの相対パス）:

- `attempt3/artifacts/frames/2026-11-12T04-17-55.539280+00-00.d8eca9a4ca564a6fb7a13fecf27c10a3.sanma-self-turn.png`
- `attempt3/artifacts/frames/2026-11-12T04-18-28.979426+00-00.9262fc3604624b21974f1c8e13566341.sanma-self-turn.png`
- `attempt3/artifacts/frames/2026-11-12T04-20-15.221390+00-00.3a50907bd0af4c8898a0a9e826ea7e83.sanma-self-turn.png`
- `stopped-current.png`

南が河に移り、他家も進行し、自摸が北になったことはこれらの実画像から確認できる。ただし、人間による事後の目視確認を、実行時の打牌確認機構が成功した証拠に置き換えてはならない。

## 旧期限と画面時計の区別

`sanma_friend_discard_recovery_candidate` の南のjournalから、対応する壁時計と単調時計を使って旧開始時刻を推定できる。

```text
attempted timestamp = 2026-11-12T04:17:58.951334+00:00
attemptedMonotonic  = 71089.12084513
originalStart      = 70911.441652807
旧開始UTC ≈ attempted timestamp - (attemptedMonotonic - originalStart)
          = 2026-11-12T04:15:01.272142+00:00
旧期限UTC ≈ 2026-11-12T04:20:01.272142+00:00
復帰候補受理時の経過 ≈ 222149ms
停止時の経過         ≈ 317222ms
```

壁時計と単調時計は同時に取得されないため推定値だが、17秒超の期限超過を覆す程度の差ではない。画像ファイル名は保存時刻であり観測開始時刻ではないため、ファイル名を`originalStart`の厳密な対応時刻として扱わない。

元実装は復帰候補受理時に新観測の時計を設定する一方、`_sanma_friend_resume_guard`には元の開始時刻と300000msを保持する。これは次入力まで旧期限を保持する明示的な設計。`MatchContinuity.alive()`は通信・画面セッションの継続性を検査し、経過期限を検査する関数ではない。20回の再観測中に旧期限が失効した点が、画面上の179秒／148秒とは別に重要である。

## 安全性上の制約

停止直前receiptの候補は北抜き1件、`northIndexes=[13]`、conflictsなし。ただし`operationAuthorized=false`で、手牌・手番・リーチ状態・公開牌・物理操作位置などの未検証項目を含む。`stable_kita_glyph_candidate`だけで操作を許可できない。

時間内に限定的な北抜き再評価を認める場合でも、既存の通常北抜き実行検査とクリック直前検査を必ず通し、旧打牌の再クリックや期限のリセットは認めない。本事例の停止時刻を忠実に再現したテストでは入力ゼロで停止すべきである。

実画像の差分による過剰な再観測、打牌結果が未確認のままになる問題、実験経路の8秒click budget適用範囲は別課題として残る。保存証拠のオフライン検証だけでは、新しい北抜き操作の成功や対局自動完走を実証できない。

## 実装・検証結果

修正は `python/auto_operator.py` の復帰監視中の検査位置に限定した。鮮度変化による再観測へ進む前に、保持した元の期限・接続継続性・友人戦状態を検査する。停止時は画像、候補操作、元開始時刻、経過時間、期限、接続診断を記録する。既存の `discard_recovery_action_requires_review` は維持し、北抜き等の許可範囲や期限を緩めない。

`python/test_sanma_recovery_deadline_187.py` は5テスト／8ケースで、300秒境界、期限超過時の変更画像・安定北抜き画像、接続断、友人戦状態失効、期限内の再観測と既存の操作停止を確認する。元コードをメモリ上に読み込んだ比較では6ケースが失敗し、期限内の2ケースは通過した。テストではブラウザをモックし、復帰証拠の受理後の制御を検査する。

別途 `python/replay_evidence187_deadline.py` が元ログの南のjournalと3枚の画像・receiptを読み、実際の証拠判定器をオフライン実行する。結果は受理時刻（約222149ms）で候補受理、停止時刻（約317222ms）で拒否、既存のクリック前復帰ガードでも拒否だった。接続継続性はこのリプレイでは仮定し、OCR処理時間は歴史的な時刻の再現対象外とする。ライブ入力の可否や成功を認定するものではない。

実行例（専用worktreeルートから）:

```sh
/home/yama1/.local/bin/jantama-dev run -- env PYTHONDONTWRITEBYTECODE=1 \
  /home/yama1/projects/jantama-auto/.runtime/python-auto-venv/bin/python \
  python/replay_evidence187_deadline.py \
  /home/yama1/server/data/dev-work/jantama/evidence187
```

検証ログ保存先: `/home/yama1/server/data/dev-work/jantama/evidence187-recovery-checks/`。
`replay.json` にオフライン判定、`python-tests.log` に関連テスト、`build.log` にビルド結果を保存する。
関連7モジュールは180テストを実行し、初回は北抜きテスト10件のうち6失敗・4エラーが発生した。新規worktreeに未追跡の `templates/bootstrap` がなく、認識が `ENOENT` で失敗することを確認し、元コードでも同じ失敗を再現した（`baseline-kita-tests.log`）。元のテンプレートをworktreeへコピーした後、当該10テストを再実行して全件成功した（`kita-tests-with-assets.log`）。残り170テストは初回から成功しており、関連180件の検証を完了した。`npm run build` と `git diff --check` も成功した。

関連モジュール: `test_sanma_recovery_deadline_187`、`test_sanma_friend_discard_recovery`、`test_experimental_sanma_friend_loop`、`test_sanma_friend_freshness`、`test_sanma_friend_kita_click`、`test_sanma_kita_reobserve_gate`、`test_sanma_friend_discard_experiment`。実行は上記と同じSSD用ラッパー・Pythonで、`PYTHONPATH=python` を設定して `-m unittest` に各モジュール名を渡した。認識テンプレート、依存パッケージ、検証ログはコミット対象に含めない。

今回のライブ試験は実施していない。メインブランチへの統合も行っていない。
