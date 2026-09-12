#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""import_fmt_bulk.py が書いた JSON を、実際に DB へ入れる。

■ なぜ SQL ではなく JSON を入れるのか
  取り込み口は SQL も JSON も書くが、**入れるのは JSON のほう**にした。理由は3つ:
    ① 先生の画面（src/assets/fmt-import.js）とまったく同じ経路（PostgREST＋RLS）を通る。
       ＝画面で通る道だけを使う＝画面で起きないことはここでも起きない。
    ② SQL を流すには DB の管理者権限が要る。この経路は**先生の権限**で足りる。
       権限を強くしないと入らない作りにしない。
    ③ 途中で止まっても、どこまで入ったかが DB 側に残る（下の「飛ばす」で続きから再開できる）。

■ 二重に入れない
  (source_file, source_sheet) が既にあれば**その回まるごと飛ばす**。
  DB 側にも部分一意索引があるので、ここを通さない手動投入からも守られる
  （db/2026-09-11_quiz_set_source.sql）。

■ 入るのは必ず下書き
  is_open は **false 固定**。JSON に true が入っていても false にする。
  ＝入れた瞬間に学生へ出ることは、この経路では起こらない。公開は先生が画面で押す。

使い方:
    py -X utf8 scripts\\load_fmt_json.py --json-dir tmp\\tsunagu --dry-run
    py -X utf8 scripts\\load_fmt_json.py --json-dir tmp\\tsunagu

🔴 標準出力に設問の本文を出さない（件数・シート名・題名まで）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
from env_creds import get_teacher_pw, NO_ENV_MSG  # 資格情報は共通ヘルパーから読む（tests/env_creds.py）


def _from_api_js() -> tuple[str, str]:
    """接続先と anon キーは `src/assets/api.js` を正本として読む。

    ★ここに書き写さない。写すと2か所になり、片方だけ古くなる。
      （anon キーは RLS で守る前提の**公開してよい**鍵。service_role は絶対に扱わない）
    """
    import re
    js = (REPO / "src" / "assets" / "api.js").read_text(encoding="utf-8")
    url = re.search(r"['\"](https://[a-z0-9]+\.supabase\.co)['\"]", js)
    key = re.search(r"['\"](eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)['\"]", js)
    if not url or not key:
        raise SystemExit("🔴 src/assets/api.js から接続先か anon キーを読めませんでした。")
    return url.group(1), key.group(1)


BASE, ANON = _from_api_js()
BASE = os.environ.get("SP_URL", BASE)


def req(path: str, method: str = "GET", body=None, token: str | None = None,
        prefer: str | None = None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("apikey", ANON)
    r.add_header("Authorization", "Bearer " + (token or ANON))
    if data is not None:
        r.add_header("Content-Type", "application/json")
    if prefer:
        r.add_header("Prefer", prefer)
    try:
        with urllib.request.urlopen(r, timeout=60) as f:
            raw = f.read().decode("utf-8")
            return f.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:300]}


def login(no: str, pw: str) -> str | None:
    st, body = req("/auth/v1/token?grant_type=password", "POST",
                   {"email": f"{no}@stu.scg-portal.jp", "password": pw})
    return body.get("access_token") if st == 200 and isinstance(body, dict) else None


def existing_keys(token: str) -> set[tuple[str, str]]:
    """もう入っている (source_file, source_sheet) を全部取る。"""
    out: set[tuple[str, str]] = set()
    offset, page = 0, 1000
    while True:
        st, rows = req(
            "/rest/v1/quiz_sets?select=source_file,source_sheet"
            f"&source_file=not.is.null&limit={page}&offset={offset}", token=token)
        if st != 200 or not rows:
            break
        for r in rows:
            out.add((r["source_file"], r["source_sheet"]))
        if len(rows) < page:
            break
        offset += page
    return out


def load_set(token: str, s: dict) -> tuple[bool, str]:
    """1回ぶんを入れる。(成功したか, ひとこと) を返す。"""
    st, rows = req("/rest/v1/quiz_sets", "POST", {
        "title": s["title"],
        "lesson": s.get("lesson"),
        # 教科書の順に並べるための値。入れたあと scripts/retitle_tsunagu.py が付け直す
        # （出どころから機械的に決めるので、ここでは持たせない＝2か所で決めない）
        "sort_key": s.get("sort_key"),
        "is_open": False,                     # ★ 必ず下書き
        "source_book": s.get("source_book"),
        "source_file": s.get("source_file"),
        "source_sheet": s.get("source_sheet"),
    }, token=token, prefer="return=representation")
    if st not in (200, 201) or not rows:
        return False, f"回を作れなかった（HTTP {st}）: {str(rows)[:160]}"
    set_id = rows[0]["id"]

    qs = s.get("questions") or []

    # ★ questions には (quiz_set_id, seq) の一意制約がある。
    #   「全体」のような寄せ集めシートは問題番号が 1〜10 のくり返しなので、そのままだと入らない
    #   （2026-09-11 に HTTP 409 で実際に落ちた）。番号を 1..N で付け直す。
    #   🔴 黙って付け直さない。付け直したことは呼び出し側に返して必ず画面に出す。
    seqs = [q["seq"] for q in qs]
    renumbered = len(set(seqs)) != len(seqs)
    if renumbered:
        qs = [dict(q, seq=i) for i, q in enumerate(qs, start=1)]

    payload = [{"quiz_set_id": set_id, "seq": q["seq"], "prompt": q["prompt"],
                "image_name": q.get("image_name"), "category": q.get("category"),
                "points": q.get("points")} for q in qs]
    st, qrows = req("/rest/v1/questions", "POST", payload,
                    token=token, prefer="return=representation")
    got = len(qrows) if isinstance(qrows, list) else 0
    if st not in (200, 201) or got != len(qs):
        return False, (f"設問を入れられなかった（HTTP {st}／{got}/{len(qs)}件）"
                       f": {str(qrows)[:200]}")

    # seq で突き合わせる（返る順を当てにしない）
    by_seq = {r["seq"]: r["id"] for r in qrows}
    choices, answers = [], []
    for q in qs:
        qid = by_seq.get(q["seq"])
        if not qid:
            return False, f"seq={q['seq']} の設問が見つからない"
        for i, label in enumerate(q["choices"], start=1):
            choices.append({"question_id": qid, "idx": i, "label": label})
        answers.append({"question_id": qid, "correct_idx": q["correct_idx"],
                        "explanation": q.get("explanation")})

    st, _ = req("/rest/v1/question_choices", "POST", choices, token=token)
    if st not in (200, 201, 204):
        return False, f"選択肢を入れられなかった（HTTP {st}）"
    st, _ = req("/rest/v1/question_answers", "POST", answers, token=token)
    if st not in (200, 201, 204):
        return False, f"正解を入れられなかった（HTTP {st}）"

    note = f"{len(qs)}問"
    if renumbered:
        note += "（★問題番号に重複があったので 1〜%d に付け直した）" % len(qs)
    return True, note


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="取り込んだ JSON を DB へ入れる（下書きで）")
    ap.add_argument("--json-dir", type=Path, required=True)
    ap.add_argument("--teacher", default="t001")
    ap.add_argument("--password", default=get_teacher_pw(),
                     help="既定は .env / 環境変数 SP_TEACHER_PW（フォールバックの既定値は無い）")
    ap.add_argument("--dry-run", action="store_true", help="入れずに、何件入るかだけ出す")
    ap.add_argument("--limit", type=int, default=0, help="先頭 N 回だけ入れる（試すとき用）")
    a = ap.parse_args(argv)

    if not a.password:
        print(f"🔴 {NO_ENV_MSG}")
        return 2

    files = sorted(a.json_dir.glob("*.json"))
    if not files:
        print(f"🔴 {a.json_dir} に JSON がありません。先に import_fmt_bulk.py を回してください。")
        return 2

    token = login(a.teacher, a.password)
    if not token:
        print("🔴 先生としてログインできませんでした。")
        return 2

    have = existing_keys(token)
    print(f"すでに入っている回（出どころ付き）: {len(have)} 件")

    sets: list[dict] = []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        sets += d["sets"] if isinstance(d, dict) and "sets" in d else d

    todo = [s for s in sets
            if (s.get("source_file"), s.get("source_sheet")) not in have]
    skip = len(sets) - len(todo)
    if a.limit:
        todo = todo[:a.limit]

    print(f"JSON にある回: {len(sets)} 件 ／ 入れる {len(todo)} 件 ／ 飛ばす {skip} 件（もう入っている）")
    print(f"入れる設問: {sum(len(s.get('questions') or []) for s in todo):,} 問")
    if a.dry_run:
        print("（--dry-run。入れていません）")
        return 0

    ok = ng = 0
    done_q = 0
    for i, s in enumerate(todo, 1):
        good, note = load_set(token, s)
        if good:
            ok += 1
            done_q += len(s.get("questions") or [])
            if "★" in note:   # 黙って直さない＝手を入れた回は必ず1行出す
                print(f"  ⓘ {s.get('title')!r}: {note}")
            if i % 10 == 0 or i == len(todo):
                print(f"  {i:>3}/{len(todo)}  入れた回 {ok} ／ 設問 {done_q:,}")
        else:
            ng += 1
            print(f"  🔴 {s.get('source_sheet')!r}（{s.get('title')!r}）: {note}")
            if ng >= 3:
                print("  🔴 失敗が3件続いたので止めます。入ったぶんはそのまま残っています"
                      "（出どころで消せます）。")
                break

    print()
    print(f"入った回: {ok} 件 ／ 設問 {done_q:,} 問" + (f" ／ 失敗 {ng} 件" if ng else ""))
    print("★ すべて下書きです。学生には出ていません。公開は先生の画面で押してください。")
    return 1 if ng else 0


if __name__ == "__main__":
    raise SystemExit(main())
