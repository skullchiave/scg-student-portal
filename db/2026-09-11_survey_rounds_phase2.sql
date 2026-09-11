-- =====================================================================
-- アンケートの月次化 — 段階2（「1人1本」の縛りを外す）  2026-09-11
--
--   ★段階1は db/2026-09-10_four_layers.sql（survey_rounds の表と round_id 列）。
--     そこでは**器だけ**作って止めてあった。理由＝一意制約を外すと、その瞬間に
--     学生画面の提出が壊れるため（src/assets/api.js の upsert が制約名を指名して動く）。
--     このファイルは **src/index.html の提出処理を round 対応にするのと同時に流す。**
--
-- ■ なぜ要るか
--   いまは (student_id, survey_key) が一意＝**再提出は上書き**。毎月おなじアンケートを
--   集めても、残るのは最新1件だけ。進路の月次アンケートは **12月〜1月開始**（今の1年生）。
--   ★回答が入る前が、直す唯一の安いタイミング。
--
-- ■ 決めた形: **すべてのアンケートを「回」経由にする**
--   「回のあるものと無いものが混在する」形にすると、画面も一意制約も二重になる。
--   そこで、いまの4本それぞれに **「常設」の回**（closes_at = null ＝ 閉じない）を1つ作り、
--   すでにある回答をそこへ紐づける。以後は**月ごとに回を足す**だけ。
--   ・常設の回 … これまで通り「1人1本」。締切なし
--   ・月次の回 … 「2026年12月」のように題名を付けて毎月1本。1人1本は回ごとに効く
--
-- ■ 一意制約の張り替え
--   drop  : survey_responses_student_id_survey_key_key（(student_id, survey_key)）
--   残る  : survey_responses_one_per_round（(student_id, round_id)）★段階1で作成済み
--   足す  : survey_responses_one_per_key_legacy … round_id が null の行だけ従来どおり1人1本
--           （検査用に作られた test_* の行が該当。実運用の行は全部 round を持つ）
--   ⚠ 部分索引は PostgREST の on_conflict では使えない。**段階2のあとの提出は
--     必ず round_id 付きで on_conflict=student_id,round_id を使うこと。**
--
-- ■ このファイルで消えるもの
--   **回答は1行も消さない。** 消すのは制約1本だけで、行は round_id が埋まるだけ。
-- =====================================================================

begin;

-- ---------- 1. 同じ題名の回を二重に作らない ----------
-- ★常設の回を作り直しても増えないようにするための保険（このファイルは1回しか流さないが、
--   月次の回を画面から作るときにも効く）。
create unique index if not exists survey_rounds_key_title_uniq
  on public.survey_rounds (survey_key, title);


-- ---------- 2. いまの4本に「常設」の回を作る ----------
-- ★survey_key は src/assets/surveys.js の SURVEYS[].key と対応する。
--   定義そのものは DB に持たない方針なので、ここに書き写している。
--   **アンケートを1本足したら、画面から「回」を作ること**（この表に行が無いと学生に出ない）。
insert into public.survey_rounds (survey_key, title, opens_at, closes_at)
values ('shinro_2026',          '常設', now(), null),
       ('seikatsu_sumai_2026',  '常設', now(), null),
       ('seikatsu_kenko_2026',  '常設', now(), null),
       ('gakuhi_2026',          '常設', now(), null),
       -- ★検査専用の回。`src/assets/surveys.js` に定義が無いので**学生の画面には出ない**
       --   （画面は定義が見つからない回を出さない作りにしてある）。
       --   これがあるおかげで、検査は**毎回この回へ上書き**でき、行が溜まらない。
       --   ⚠ 2026-09-11 まで検査は毎回ちがう survey_key を作っていて、
       --     survey_responses に test_multi_ui_<時刻> が9件たまっていた（消す口が無いため消せない）。
       --     「回答は消さない」方針なので、**溜めない作りにするのが唯一の直し方**。
       ('test_ui',              '検査用', now(), null),
       -- ★2本目。「**同じアンケートでも、回が違えば別の行になる**」＝月次化の本体を
       --   検査するために要る（1本だと上書きの確認しかできない）。
       ('test_ui',              '検査用2', now(), null)
on conflict (survey_key, title) do nothing;


-- ---------- 3. すでにある回答を「常設」の回へ紐づける ----------
-- ★これをやらないと、学生の画面で「まだ答えていない」に戻って二重に答えることになる。
update public.survey_responses r
   set round_id = sr.id
  from public.survey_rounds sr
 where r.round_id is null
   and sr.survey_key = r.survey_key
   and sr.title = '常設';
-- ⚠ 検査用に作られた test_* の行は、対応する回が無いので round_id = null のまま残る。
--   下の legacy 索引がそれらを従来どおり1人1本に保つ。


-- ---------- 4. 一意制約の張り替え ----------
alter table public.survey_responses
  drop constraint if exists survey_responses_student_id_survey_key_key;

create unique index if not exists survey_responses_one_per_key_legacy
  on public.survey_responses (student_id, survey_key) where round_id is null;


-- ---------- 5. 学生: いま自分に開いているアンケートの回 ----------
-- quiz の my_open_runs と同じ考え方。★対象は「条件」ではなく「結果のリスト」で見る。
create or replace function public.my_open_survey_rounds()
returns jsonb
language sql
stable security definer
set search_path = public, pg_temp
as $$
  select coalesce(jsonb_agg(jsonb_build_object(
           'round_id', r.id, 'survey_key', r.survey_key, 'title', r.title,
           'opens_at', r.opens_at, 'closes_at', r.closes_at)
         order by r.opens_at), '[]'::jsonb)
    from public.survey_rounds r
   where auth.uid() is not null
     and not r.is_void
     and r.opens_at <= now()
     and (r.closes_at is null or now() < r.closes_at)
     and (
       (coalesce(array_length(r.class_names, 1), 0) = 0
        and coalesce(array_length(r.student_ids, 1), 0) = 0)
       or auth.uid() = any (r.student_ids)
       or (select class_name from public.profiles where id = auth.uid()) = any (r.class_names)
     )
$$;

revoke all on function public.my_open_survey_rounds() from public;
revoke execute on function public.my_open_survey_rounds() from anon;
grant execute on function public.my_open_survey_rounds() to authenticated;


-- ---------- 6. 教師: アンケートの回をはじめる ----------
-- ★小テスト（quiz_runs）と違い、**複数クラスに出せる**（月×学年で1本）。
--   クラスごとに5本作ると全体の傾向が出せなくなる（ヨリソルの縦割りと同じ形）。
create or replace function public.start_survey_round(
  p_survey_key   text,
  p_title        text,
  p_class_names  text[] default '{}',
  p_student_ids  uuid[] default '{}',
  p_closes_at    timestamptz default null
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_round survey_rounds%rowtype;
  v_n     integer;
begin
  if not app_hidden.is_teacher() then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  if p_survey_key is null or btrim(p_survey_key) = '' then
    raise exception 'survey_key が空です' using errcode = '22023';
  end if;
  if p_title is null or btrim(p_title) = '' then
    raise exception '題名が空です（「2026年12月」のように、あとで見分けられる名前を付けてください）'
      using errcode = '22023';
  end if;
  if p_closes_at is not null and p_closes_at <= now() then
    raise exception '締切が過去です' using errcode = '22023';
  end if;

  insert into public.survey_rounds
        (survey_key, title, class_names, student_ids, opens_at, closes_at, created_by)
  values (p_survey_key, btrim(p_title), coalesce(p_class_names, '{}'), coalesce(p_student_ids, '{}'),
          now(), p_closes_at, auth.uid())
  returning * into v_round;

  v_n := public.run_target_count(v_round.class_names, v_round.student_ids);

  return jsonb_build_object(
    'round_id', v_round.id, 'survey_key', v_round.survey_key, 'title', v_round.title,
    'class_names', to_jsonb(v_round.class_names), 'target_count', v_n,
    'opens_at', v_round.opens_at, 'closes_at', v_round.closes_at);
exception
  when unique_violation then
    raise exception '「%」はもう作ってあります（題名を変えてください）', btrim(p_title)
      using errcode = '23505';
end $$;

revoke all on function public.start_survey_round(text, text, text[], uuid[], timestamptz) from public;
revoke execute on function public.start_survey_round(text, text, text[], uuid[], timestamptz) from anon;
grant execute on function public.start_survey_round(text, text, text[], uuid[], timestamptz) to authenticated;


-- ---------- 7. 教師: 回を閉じる・取り消す ----------
-- 🔴 取り消しても**回答は消さない**（集計から外れるだけ）。quiz_runs と同じ思想。
create or replace function public.close_survey_round(p_round_id uuid, p_void boolean default false)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare v_round survey_rounds%rowtype;
begin
  if not app_hidden.is_teacher() then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  update public.survey_rounds
     set closes_at = least(coalesce(closes_at, now()), now()),
         is_void   = is_void or coalesce(p_void, false)
   where id = p_round_id
  returning * into v_round;
  if v_round.id is null then
    raise exception 'no such round' using errcode = '22023';
  end if;
  return jsonb_build_object('round_id', v_round.id, 'closes_at', v_round.closes_at,
                            'is_void', v_round.is_void);
end $$;

revoke all on function public.close_survey_round(uuid, boolean) from public;
revoke execute on function public.close_survey_round(uuid, boolean) from anon;
grant execute on function public.close_survey_round(uuid, boolean) to authenticated;

commit;


-- =====================================================================
-- 流したあとの確認
--   py -X utf8 tests\test_security.py
--   py -X utf8 tests\test_surveys.py --live
--   py -X utf8 tests\run_e2e_survey.py
--   py -X utf8 -m unittest discover -s tests -p "test_db_migrations.py"
--
--   ⚠ 許容WARN が 12件 → 15件（public の RPC が3本増える：
--     my_open_survey_rounds / start_survey_round / close_survey_round）。
--     CLAUDE.md の一覧に書き足してから基準を上げること。
--
-- 🔴 **これを流したら、学生画面の提出は round_id 付きでなければ通らない。**
--    src/index.html と src/assets/api.js を同時に出すこと（同じコミットに入れてある）。
--
-- 巻き戻し
--   begin;
--   drop function if exists public.close_survey_round(uuid, boolean);
--   drop function if exists public.start_survey_round(text, text, text[], uuid[], timestamptz);
--   drop function if exists public.my_open_survey_rounds();
--   drop index if exists public.survey_responses_one_per_key_legacy;
--   -- ★戻すには、round_id を外してから制約を張り直す（回答は消さない）
--   update public.survey_responses set round_id = null;
--   alter table public.survey_responses
--     add constraint survey_responses_student_id_survey_key_key unique (student_id, survey_key);
--   delete from public.survey_rounds where title = '常設';
--   drop index if exists public.survey_rounds_key_title_uniq;
--   commit;
--   ※ ⚠ 月次の回に回答が入ったあとに巻き戻すと、同じ survey_key の回答が複数あるため
--     制約を張り直せない。**回答が入る前だけ安全に戻せる。**
-- =====================================================================
