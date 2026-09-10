# SCG 学生ポータル（scg-student-portal）

学生が自分のスマホでログインして使う学校の入口。第一弾は**小テスト**（選択式・即時採点・教師ライブ集計）。
将来はアンケート・志望校提出・ポートフォリオ閲覧などを同じ土台に載せる。

| | |
|---|---|
| 学生用URL | https://skullchiave.github.io/scg-student-portal/ |
| 教師モニター | https://skullchiave.github.io/scg-student-portal/teacher.html |
| 裏方 | Supabase（無料枠・東京リージョン・project ref: `egdcbxzpgwenmfabpodd`） |
| 状態 | **デモ**（2026-09-04 MTG用。データは全部ダミー・実在の学生情報ゼロ） |

## デモアカウント

| 役割 | ID | パスワード |
|---|---|---|
| 学生（デモ用） | s001 〜 s040 | sakura24 |
| 教師 | t001 | sensei-scg-2026 |
| 負荷試験用学生 | l001 〜 l150 | sakura24 |

## 仕組み（3行で）

1. 画面は GitHub Pages の静的HTML（軽い・キャッシュされる・ライブラリ依存ゼロ）
2. データとログインは Supabase。**正解データは学生に一切送られず**、採点はサーバー側で実行
3. 全通信に自動再送（バックオフ）つき。150人が一斉にタップしても自然に分散する

## セキュリティの考え方（なぜ安全と言えるか）

- コード内の `SB_ANON` キーは**公開してよい鍵**（設計上そういうもの）。実際の門番は
  データベースの行単位アクセス制御（RLS）で、「学生は自分の行しか読めない」を**DB層で強制**している。
  画面側にバグがあっても他人のデータは漏れない。
- **正解は `questions` に入っていない**。別表 `question_answers` に分けてあり、学生ロールからは読めない。
  学生が読めるのは `questions`（正解列を持たない）を RLS で「公開中の回だけ」に絞ったもの。
  採点はRPC `submit_attempt` がサーバー側で行う。
  ※ 以前ここに「`questions_public` ビュー」と書いてあったが、**そのビューは実在しない**
  （2026-09-06 に実物を書き出して判明）。守られている中身は同じで、直したのは記述だけ。
- 成績の偽造（attemptsへの直接insert）は拒否される。
- 以上は全部 `tests/test_security.py` が機械的に再検証する（下記）。

## 起動方法・使い方

- 学生: 学生用URLを開く → 学籍番号＋パスワードでログイン → テストを選んで回答 → 送信で即採点
- 教師（管理画面 teacher.html）: t001でログイン → 左メニューから「問題の登録・解放」「小テスト ライブ集計」
  「アンケート 回答一覧」（いずれも本物）、「学生用QRを表示」で教室投影用のQR。
  「これから作る画面（イメージ）」はアンケート作成・学生アカウント・お知らせ・点検
- 言語: 学生画面のヘッダー右上 🌐 から日本語/English。選んだ言語は端末に記憶される（他言語は準備中）

## 検証スクリプト

**まとめて回すのはこの1行**（2026-09-10 に1コマンド化）:

```
python -m unittest discover -s tests -p "test_*.py"       # 全部（218項目・DB系は既定でskip）
SP_LIVE=1 python -m unittest discover -s tests -p "test_*.py"   # 本物のDBへの往復も込みで全部
```

※ DBに実際に触る部分（`test_security.py` の全項目、他4ファイルの `--live` 相当）は
**まとめて回したときだけ既定で skip** する。まとめ実行で本物のDBを次々叩かないための安全策で、
`SP_LIVE=1` を付けると全部走る。DBに繋がらない環境（会社PC・CI）でも **skip になるだけで落ちない**。

🔴 **スキーマ・RLS を変えたときは、まとめ実行では足りない。** 下の単体実行を使うこと
（`test_security.py` だけは単体実行なら**引数なしでも常にDBを叩く**＝これまで通り）。

```
python tests/test_security.py       # セキュリティ回帰テスト（スキーマ変更したら必ず。18項目・要DB）
python tests/test_db_migrations.py  # db/*.sql の見張り（DB不要・27項目。★流す前に）
python tests/test_surveys.py --live # アンケート定義の検査＋DB往復（surveys.js を変えたら）
python tests/test_choices.py --live # 選択肢まわり（ダミーの3択・4択を作って試し、最後に消す）
python tests/test_drafts.py --live  # 途中保存の往復
python tests/test_integrity.py --live  # 出題順・離席記録・方針どおりか
python tests/run_e2e_quiz.py        # ブラウザ実操作: 小テスト（Chrome必要）
python tests/run_e2e_survey.py      # ブラウザ実操作: ログイン→アンケート一覧→回答→提出済みが下へ沈む（Chrome必要）
python scripts/loadtest.py tokens   # 負荷テスト準備: 150名分のログイン（低速・30分）
python scripts/loadtest.py burst    # 負荷テスト本番: ログイン済み150名の一斉受験
python -m unittest discover -s tests -p "test_import_yorisol.py"   # ヨリソル設問の変換（DB不要・23項目）
python -m unittest discover -s tests -p "test_import_fmt_xlsx.py"  # 課題登録FMT(Excel)の変換（DB不要・77項目）
python -m unittest discover -s tests -p "test_audit_fmt.py"        # 教材フォルダの検査（DB不要・24項目）
python -m unittest discover -s tests -p "test_ruby.py"             # ルビ表示と innerHTML の見張り（DB不要・17項目）
```

※ 1ファイルだけ狙うときは `--live` も引き続き使える。**`discover` 越しでは `--live` は効かない**ので
`SP_LIVE=1` を使うこと。

- 入力: なし（対象URL・アカウントはスクリプト内に定義）
- 出力: 各項目の PASS/FAIL、負荷テストは成功率と応答時間（平均/p95/最悪）
- 失敗時の見方: `test_security.py` の ❌ 行がそのまま「破られた防御」。負荷テストの NG例 行に
  エラー内容の先頭80字が出る

## 問題を登録する（先生の画面・Excelから取り込み）

`teacher.html` の「✏️ 問題の登録・解放」から、課題登録FMT の Excel を**直接読み込んで登録**できる。
**①Excelを選ぶ → ②プレビューで確認 → ③1問ずつ修正 → ④登録** の4段。
★**アップロードはしない**（ブラウザの中だけで読む）。DBに書き込むのは「④登録」を押したときだけ。

🔴 **登録した時点では学生に見えない（下書き）。** 見せるのは一覧で「公開」を押したとき。
取り込んだ瞬間に学生へ出る事故を無くすため（2026-09-11）。

- 入力: 課題登録FMT形式の `.xlsx`（ローカルのファイルを選ぶだけ）
- 出力: `quiz_sets(is_open=false ＝下書き)` → `questions` → `question_choices` → `question_answers`
  （🔴 **解説は `question_answers` 側**＝学生は提出したあとだけ読める）
- 場所は URL で決まる: `#qsets`（一覧）／`#qsets/import/1〜4`（各段）。戻る・ブックマークが効く
- 失敗時の見方: ①で**同じ課の範囲のシートを2枚選ぶと「②プレビューへ」が押せない**（理由が画面に出る）。
  Excel が壊れている（計算結果が無い等）場合はプレビューにエラーとして出る
- ⓘ 4列の有無を事前に確かめ、無ければその4つを外して insert する
  （列は 2026-09-10 に投入済みだが、列の無い環境でも落ちない）

### 一覧からできること（2026-09-11）

| 操作 | 何が起きるか |
|---|---|
| **公開** | その回が学生の画面に出る（`is_open=true`） |
| **停止** | 学生の画面から引っ込む。記録は残る |
| **消す** | 🔴 **受験記録が1件も無い回だけ**消せる。設問も一緒に消える |

🔴 **1人でも受けた回は消せません**（「停止」を使う）。`quiz_sets` を直接 DELETE すると
外部キーの cascade で**受験記録まで消え、しかも cascade は RLS を通りません**。
画面は RPC `delete_quiz_set` を通し、その中で受験記録を数えて断ります。

```
py -X utf8 -m unittest discover -s tests -p "test_qsets_import.py"   # DB不要・構造+Nodeパリティ
py -X utf8 tests/run_e2e_qsets_import.py                             # ブラウザ実操作・デモDBへ往復（要Chrome）
```

🔴 **取り込みの規則は `scripts/import_fmt_xlsx.py` と `src/assets/fmt-import.js` の2か所にある**（Python と JS）。
片方だけ直すと「コマンドでは通るのに画面では落ちる」が起きるので、**必ず両方直すこと**。
それを見張るために `tests/test_qsets_import.py` が**両者に同じシナリオを42件**流している。

## 教材フォルダの不備を検査する（作問側チェック）

先生が書いた Excel を全部読んで、**取り込めない設問**と**直してもらうもの**を一覧にする。
2027年2月に作問側が直したあと、もう一度これを回して再検査する。

```
python scripts/audit_fmt.py
    # 教材フォルダ331本を検査し、tmp/教材の不備一覧.html（先生に渡す用）と
    # tmp/教材の不備一覧.json（再集計用の明細）を書く。所要 約140秒

python scripts/audit_fmt.py --dir "会社PCでの教材フォルダのパス" --out tmp/report.html
    # 場所が違う環境ではこの2つで切り替える

python -m unittest discover -s tests -p "test_audit_fmt.py"   # 回帰テスト（DB不要・24項目）
```

- 入力: 教材フォルダ（既定パスは `scripts/audit_fmt.py` の `DEFAULT_BASE`）。
  **DBには接続しない。Excel も書き換えない（読むだけ）**
- 出力: `tmp/教材の不備一覧.html`（先生に見せる一覧・**母数つき**）／同名 `.json`（再集計用の全明細）
- 失敗時の見方: 標準出力に「■ 母数」「■ 🔴 不備で取り込めなかった設問」の内訳が出る。
  終了コードは **0=不備なし／1=不備あり（正常終了）／2=`--dir` が見つからない**。
  ★2 と「0件」を混同しないための切り分け
- ⓘ **「配点がそろっていない」も出る**（同じテストの中で配点が2種類以上＝たいてい打ち間違い）。
  採点に配点は使っていないので**取り込みは止まらない**。作問側に見てもらうためだけの警告。
  実データでの検出は5シート（設問のある667シートのうち 662枚は全問おなじ配点）

## データベースの変更

`db/` に日付つきの SQL を置いてから流す。`db/0000_baseline.sql`（2026-09-06 時点の全構造）は**書き換えない**。

🔴 **流す前に `python tests/test_db_migrations.py`**（DB不要）。ポリシーの `to authenticated` 忘れ・
RPC の `revoke execute ... from anon` 忘れ・列の削除・巻き戻し手順の欠落を、**流す前に**落とす。
どちらも 2026-09-06 に実際に踏みかけた穴。

| ファイル | 中身 | 状態 |
|---|---|---|
| `0000_baseline.sql` | 2026-09-06 時点の全構造 | 投入済み |
| `2026-09-06_attempt_drafts.sql` | 回答の途中保存 | 投入済み |
| `2026-09-06_attempt_focus.sql` | 画面を離れた記録 | 投入済み |
| `2026-09-06_multi_choice.sql` | 選択肢を2個固定から「いくつでも」へ | 投入済み |
| `2026-09-10_question_columns.sql` | 画像・カテゴリ・配点・解説の4列 | 投入済み |
| `2026-09-10_four_layers.sql` | 設問／問題セット／実施回／回答の4層 | 投入済み |
| `2026-09-11_delete_quiz_set.sql` | 回を消す RPC（受験記録があれば断る） | 投入済み |

2026-09-10 の2本は**クライアント（`src/`）を1行も変えずに**流した（新しい引数はすべて既定値つき）。
確認＝全テスト218件 OK・ブラウザ実操作3本とも 0 FAIL・`get_advisors` で ERROR 0件／WARN 11件
（2026-09-11 の `delete_quiz_set` で 12件になる見込み）。
巻き戻し手順は各 SQL の末尾にある。

🔴 **意図的に止めてある2つ**（どちらも「片方だけ変えると壊れる」ため）:
1. `submit_attempt` / `save_draft` が設問を引く先は **`questions.quiz_set_id` のまま**。
   `quiz_set_questions` へ切り替えるのは `src/index.html` の取得と**同時に1回で**
2. `survey_responses` の一意制約 `(student_id, survey_key)` は**外していない**。
   外すと `src/assets/api.js` の upsert が即失敗する。段階2の手順は SQL の末尾に

### ヨリソルの設問を取り込む

```
python scripts/import_yorisol.py --questions 設問.csv --answers 回答.csv --out-sql tmp/q.sql
```

DBには接続しない。SQL を書き出すだけなので、中身を見てから Supabase の SQL エディタで流す。
取り込みは `is_open=false`（学生には見えない）で作られるので、確認してから教師画面で公開する。
契約終了は 2027年2月。**設問と受験履歴はそれまでにしか書き出せない。**

負荷テストが2段なのは実運用と同じ形だから: サインインAPIには同一IPからの回数制限が
あるため、学生のログインは「事前に各自1回」（アプリが保持し続ける）。小テスト当日に
一斉に走るのはデータAPIだけで、そちらに制限はない。

### 課題登録FMT（先生が書く Excel）を取り込む

```
py -X utf8 scripts/import_fmt_xlsx.py --xlsx "...（作成用）.xlsx" ^
    --title-prefix "つなぐ日本語初級 まとめテストⅠ" --out-json tmp/q.json --out-sql tmp/q.sql
```

DBには接続しない。SQL を書き出すだけ。`is_open=false` で作られるので、確認してから教師画面で公開する。

- 既定の `--schema 2026-09-10` は**画像・カテゴリ・配点・解説も書く**（列は投入済み）。
  列を足していない別の環境へ書き出すときだけ `--schema 2026-09-06`（**その4つは捨てられる**）
- 🔴 **同じ課の範囲のシートが2枚あると SQL を書かずに止まる**（`①1-3` と `①1-3 （新）`）。
  二重登録は起きてからでは戻せない。`--sheet` / `--exclude` で選ぶ

## 本番移行時にやること（デモのままにしない）

- [ ] Supabase プロジェクトを**学校管理のアカウント**に作り直す（今は個人アカウントの無料枠）
- [ ] Pro プラン（$25/月）に上げる（無料枠は1週間放置で休眠する）
- [ ] デモ用アカウントを全削除し、実学生の発行フローを設計（初期PW・変更強制）
- [ ] 個人情報の外部サーバー処理について同意書に織り込む（2027年度同意書と連動）
- [ ] バックアップ復元訓練を1回実施する
