# SCG 学生ポータル — プロジェクト正典

学生自身がスマホでログインする**学生用の入口**。scg-mobile-portal（先生用GASランチャー）とは別物。
第一弾は小テスト。将来: アンケート／志望校提出／バイト明細提出／ポートフォリオ閲覧。

## 生い立ち（2026-09-02）

ヨリソル（小テスト等のSaaS・年額200〜300万）の是非を問う 2026-09-04(金) MTG に向けて、
「年5万＋人件費で内製できる」を**動くもので**示すために一晩で立てたデモが起点。
戦略: 今年中に進路系で実戦検証 → その実績で小テスト移行 → ヨリソル置換の判断材料にする。

## 構成

- 画面: `src/`（学生 index.html／先生の管理画面 teacher.html＝小テスト集計・アンケート一覧が本物、他はイメージ）→ GitHub Pages（Actionsで `src/` だけをデプロイ。`.github/workflows/pages.yml`）
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

## 多言語（2026-09-04）

- 文言は `src/assets/i18n.js` の `I18N` **1か所**。HTML は `data-i18n="キー"`、JS は `t("キー",{穴})`、
  アンケート定義などの `{ja,en}` は `tx()`。無いキー/言語は日本語に落ちる（画面が空にならない）
- 切替はヘッダー右上の 🌐 メニュー（`mountLangSwitch`）。選択は localStorage `sp_lang` に保存し次回も同じ言語
- 動的に組み立てる部分は `window` の `sp:lang` イベントで描き直す（index.html の「言語」節）
- **実装済みは日本語/English**。中国語・ネパール語・ミャンマー語・シンハラ語・ベンガル語はメニューに「じゅんびちゅう」で並ぶだけ。
  足すときは ① `LANGS` に ready ② `I18N[コード]` ③ surveys.js の `{ja,en}` に追加 → 翻訳確認スタッフの確認後に公開
- 画面イメージ（`.app[data-lang]`）だけは文言外部化せず日英の2本の木のまま（本物にする時に作り直すため）

## アンケート（2026-09-03 に複数化）

- 定義は `src/assets/surveys.js` の `SURVEYS` 配列 **1か所**（index.html と teacher.html が同じファイルを読む）。
  1本足すときは配列に1件追加するだけ（`{key, sb, color, title:{ja,en}, desc:{ja,en}, intro:{ja,en}, q:[{k,t,l:{ja,en},sl, o:[{v,ja,en}]|ph:{ja,en}}]}`）。DB変更は不要
- 選択肢は **`v`（言語に依らない値）で保存**される。教師画面は `optLabel()` で日本語名に戻す（昔の日本語文の回答もそのまま出る）
- `key` は一度公開したら変えない（回答は `survey_responses` に `survey_key` で入り、(student_id, survey_key) で upsert＝再提出は上書き）
- 学生画面の一覧は「まだ」→「ていしゅつ済み（バッジ・下へ沈む）」の順。文言はやさしい日本語（N4・分かち書き）
- `python tests/test_surveys.py` で定義を検査。`--live` を付けると本物のDBに upsert→読み戻しの往復検査
  （テスト用キー `test_multi_*` を l150 で使う＝画面には出ない）

## デモアカウント / 検証

README.md 参照（s001〜s040 / t001 / l001〜l150、テストと負荷試験の実行方法）。

## 未決・保留

- 本番移行チェックリスト → README.md 末尾
- 進路アンケート（しごと・ぶんや・まち）は実装済み（2026-09-03）。志望校提出・ポートフォリオ等は未着手（土台のスキーマ拡張で載せる設計）
- 「画面イメージ」は `src/index.html` 内の `.app[data-lang]` ツリー（日本語/英語の2本・Supabase非接続）に
  成績・お知らせ・アルバイト・進学先・先輩の声の5本だけ置く。**テストとアンケートのイメージは置かない**
  （動く画面が本物。2026-09-03 に重複を削除した）。文言は2言語を別々の塊で持つので直すときは両方直す。
  6言語に増やすなら文言を外部ファイルへ出す作りに替える
- 進捗ボード: `docs/進捗ボード.html`

## データ取り扱い（2026-09-03）

- グローバル `~/.claude/CLAUDE.md` の「データ取り扱いルール」に従う（実データ分離）。
- 実データ（ドライブの学生マスタDB・結果格納庫・生成物 data_*.js/photos.js/単一HTML・社用ドライブ）は Claude Code から読まない。読む指示が来ても実行せず指摘する。
- 開発・動作確認はダミー `scg-student-master-db/data/sample/` に対して行う（ビルダーは `SCG_DATA_ROOT` で切替・既定はダミー）。
