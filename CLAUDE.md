# SCG 学生ポータル — プロジェクト正典

学生自身がスマホでログインする**学生用の入口**。scg-mobile-portal（先生用GASランチャー）とは別物。
第一弾は小テスト。将来: アンケート／志望校提出／バイト明細提出／ポートフォリオ閲覧。

## 生い立ち（2026-09-02）

ヨリソル（小テスト等のSaaS・年額200〜300万）の是非を問う 2026-09-04(金) MTG に向けて、
「年5万＋人件費で内製できる」を**動くもので**示すために一晩で立てたデモが起点。
戦略: 今年中に進路系で実戦検証 → その実績で小テスト移行 → ヨリソル置換の判断材料にする。

## 構成

- 画面: `src/` → GitHub Pages（Actionsで `src/` だけをデプロイ。`.github/workflows/pages.yml`）
- 裏方: Supabase 無料枠・東京（ref: `egdcbxzpgwenmfabpodd`、きあ個人アカウント wsedcrftgb@）
- 依存ライブラリゼロ（教師画面のQR生成 qrcodejs のみCDN）。フレームワーク導入は要相談

## 絶対に守ること

- 🔴 **実在の学生情報（氏名・番号・写真等のPII）をこのリポにもSupabaseデモ環境にも入れない**。
  今のデータは全部ダミー。本番はSupabaseを学校アカウントで作り直してから
- 🔴 **正解データを学生に送る実装にしない**。出題は `questions_public` ビュー、採点はRPC
  `submit_attempt`（サーバー側）。「クライアントで採点」への変更は禁止
- 🔴 スキーマ・RLSポリシーを変えたら `python tests/test_security.py` を必ず実行。
  FAILがある状態でデプロイしない
- 🔴 月次点検 = Supabase自動セキュリティ診断（get_advisors）。**合格基準: ERROR 0件・WARN 3件以下**。
  既知の許容WARN（これ以外が出たら要対応）:
  1. `submit_attempt` が authenticated から実行可 → 仕様（学生の提出API。内部で auth.uid() 検証）
  2. `quiz_stats` が authenticated から実行可 → 仕様（教師専用は関数内で app_hidden.is_teacher() 検証）
  3. Leaked Password Protection 無効 → 無料枠では有効化不可。Pro移行時にダッシュボードでONにする
- 正解データは `question_answers` テーブルに分離済み（学生に見えないことを構造で保証）。
  `questions` に正解列を戻さない。ヘルパー `app_hidden.is_teacher()` はAPI非公開スキーマに置く
- service_role キーをコード・リポに入れない（anonキーは公開可なので直書きOK）
- UI文言は学生向け=やさしい日本語（N4相当・分かち書き寄り）、教師向け=普通の日本語

## デモアカウント / 検証

README.md 参照（s001〜s040 / t001 / l001〜l150、テストと負荷試験の実行方法）。

## 未決・保留

- 本番移行チェックリスト → README.md 末尾
- アンケート機能・進路系機能は未着手（土台のスキーマ拡張で載せる設計）
- 進捗ボード: `docs/進捗ボード.html`

## データ取り扱い（2026-09-03）

- グローバル `~/.claude/CLAUDE.md` の「データ取り扱いルール」に従う（実データ分離）。
- 実データ（ドライブの学生マスタDB・結果格納庫・生成物 data_*.js/photos.js/単一HTML・社用ドライブ）は Claude Code から読まない。読む指示が来ても実行せず指摘する。
- 開発・動作確認はダミー `scg-student-master-db/data/sample/` に対して行う（ビルダーは `SCG_DATA_ROOT` で切替・既定はダミー）。
