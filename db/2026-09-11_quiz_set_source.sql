-- =====================================================================
-- quiz_sets に「どこから来たか」を持たせる（教材Excelの出どころ）  2026-09-11
--
-- ■ なぜ要るか
--   これから教材Excelから本物の設問 1,087問（99シート）を取り込む。
--   ところがいまの quiz_sets には「どのExcelのどのシートから来たか」を記録する列が無い。
--   このまま入れると:
--     ・二重に取り込んでも気づけない（同じシートを2回流しても、見た目では分からない）
--     ・間違いに気づいても、選んで消せない（どれが問題の行か特定できない）
--     ・2027-02 の再取り込みができない（前回どこまで入れたか分からない）
--
-- ■ 足す3列（すべて null 許容。既存2件のデモ回は source_* が null のまま＝それでよい）
--   source_book  … 教材フォルダ名。例「001.つなぐ日本語初級」
--   source_file  … 教材フォルダのルートからの相対パス。
--                   例「001.つなぐ日本語初級\まとめテスト\Ⅰ\★ヨリソル_まとめテストⅠ（作成用）.xlsx」
--   source_sheet … シート名。例「①1-3 （新）」
--
-- ■ 一意索引（部分索引）
--   (source_file, source_sheet) の組を一意にする。**ただし source_file が null の行は対象外**
--   （手で作った回・デモ回は source_file が無いので、この索引には当たらない）。
--   これが「同じシートを2回流したら気づける」の実体。
--
--   取り込みスクリプト側（scripts/import_fmt_xlsx.py）は、insert の前に
--   「同じ (source_file, source_sheet) が既にあるか」を見て、あれば raise notice を出して飛ばす。
--   ★索引はその**最後の保険**（スクリプトを経由しない手動 insert からも守る。二重登録は
--     スクリプトのチェックだけに頼らない）。
--
--   source_book にも普通の索引を足す（教師の画面が教材で絞り込むときに使う）。
--
-- ■ このファイルの性質
--   列を3本足して、索引を2本足すだけ。既存の列・制約・RLS には触らない。
--   新しいポリシーも関数も作らない＝ to authenticated / revoke from anon の追加は無い
--   （既存の quiz_sets のポリシーは行単位。列を足しても「誰の行が見えるか」は変わらない）。
-- =====================================================================

begin;

alter table public.quiz_sets add column if not exists source_book  text;
alter table public.quiz_sets add column if not exists source_file  text;
alter table public.quiz_sets add column if not exists source_sheet text;

create unique index if not exists quiz_sets_source_file_sheet_uniq
  on public.quiz_sets (source_file, source_sheet)
  where source_file is not null;

create index if not exists quiz_sets_by_source_book
  on public.quiz_sets (source_book);

commit;


-- =====================================================================
-- 流したあとの確認
--   py -X utf8 -m unittest discover -s tests -p "test_db_migrations.py"
--   py -X utf8 -m unittest discover -s tests -p "test_import_fmt_xlsx.py"
--   py -X utf8 scripts\import_fmt_xlsx.py --xlsx "...(作成用).xlsx" ^
--       --source-book "001.つなぐ日本語初級" ^
--       --source-file "001.つなぐ日本語初級\まとめテスト\Ⅰ\★....xlsx" ^
--       --out-sql tmp\q.sql
--     → SQL の insert into quiz_sets(...) に source_book / source_file / source_sheet が出ること
--   同じシートでもう一度 SQL を作って流すと、insert のかわりに
--     raise notice「すでに入っています（飛ばしました）」が出て、二重に入らないこと
--
-- 巻き戻し（★列を落とすと、そこに入れた値は消える。索引だけを戻すなら値は失わない）
--   begin;
--   drop index if exists public.quiz_sets_by_source_book;
--   drop index if exists public.quiz_sets_source_file_sheet_uniq;
--   alter table public.quiz_sets drop column if exists source_sheet;
--   alter table public.quiz_sets drop column if exists source_file;
--   alter table public.quiz_sets drop column if exists source_book;
--   commit;
-- =====================================================================
