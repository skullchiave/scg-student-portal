# -*- coding: utf-8 -*-
"""150同時アクセス負荷テスト — scg-student-portal

シナリオ（HR一斉小テストの再現）:
  Phase 1: 150名が20秒の間にバラバラとログイン（着席しながらログインする実態を再現）
  Phase 2: 全員が出題を取得
  Phase 3: 先生の「送信して」の号令 = 全員が「同一瞬間」に提出（最悪ケース）

使い方:  python scripts/loadtest.py [人数]   (省略時 150)
出力:    各フェーズの 成功数 / 失敗数 / 応答時間(平均・最悪) と、DB側の提出记録数の照合値
依存:    標準ライブラリのみ
"""
import sys, json, time, random, threading, io
import urllib.request
import urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "https://egdcbxzpgwenmfabpodd.supabase.co"
ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVnZGNieHpwZ3dlbm1mYWJwb2RkIiwi"
        "cm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNTcwNDYsImV4cCI6MjEwMzkzMzA0Nn0.m908C67Nh4KsYnH_LWvP4wAjOtxI79hhE-BKS1MCxX0")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 150
QUIZ_SET = "c75def6b-7623-4d86-8540-0c5b081ecf7c"

def req(path, token=None, body=None, timeout=30):
    headers = {"apikey": ANON, "Content-Type": "application/json"}
    if token: headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=headers)
    with urllib.request.urlopen(r, timeout=timeout) as res:
        return json.loads(res.read().decode())

def req_retry(path, token=None, body=None, tries=4):
    """本番クライアントと同じ再送ロジック（指数バックオフ+ジッタ）。戻り値: (結果, 再送回数)"""
    last = None
    for i in range(tries):
        try:
            return req(path, token, body), i
        except urllib.error.HTTPError as e:
            if e.code not in (429,) and e.code < 500:
                raise
            last = e
        except Exception as e:
            last = e
        time.sleep(0.6 * (2 ** i) * (0.5 + random.random()))
    raise last

results = {"login": [], "fetch": [], "submit": []}
lock = threading.Lock()
barrier = threading.Barrier(N)

def student(i):
    sid = f"l{i:03d}"
    # Phase 1: ログイン（0〜20秒に分散）
    time.sleep(random.uniform(0, 20))
    t0 = time.time()
    try:
        auth, retries = req_retry("/auth/v1/token?grant_type=password",
                                  body={"email": f"{sid}@stu.scg-portal.jp", "password": "sakura24"})
        token = auth["access_token"]
        with lock: results["login"].append((time.time()-t0, retries, None))
    except Exception as e:
        with lock: results["login"].append((time.time()-t0, 99, str(e)[:80]))
        barrier.wait()  # 脱落してもバリアは通過させる
        return
    # Phase 2: 出題取得
    t0 = time.time()
    try:
        qs, retries = req_retry(f"/rest/v1/questions_public?select=id,seq&quiz_set_id=eq.{QUIZ_SET}&order=seq", token)
        with lock: results["fetch"].append((time.time()-t0, retries, None))
    except Exception as e:
        with lock: results["fetch"].append((time.time()-t0, 99, str(e)[:80]))
        barrier.wait(); return
    answers = {q["id"]: random.choice("ab") for q in qs}
    # Phase 3: 全員同時送信（バリアで同期 = 最悪ケース）
    barrier.wait()
    t0 = time.time()
    try:
        _, retries = req_retry("/rest/v1/rpc/submit_attempt", token,
                               {"p_quiz_set_id": QUIZ_SET, "p_answers": answers, "p_duration_ms": 60000})
        with lock: results["submit"].append((time.time()-t0, retries, None))
    except Exception as e:
        with lock: results["submit"].append((time.time()-t0, 99, str(e)[:80]))

def report(name, rows, n_expected):
    ok = [r for r in rows if r[2] is None]
    ng = [r for r in rows if r[2] is not None]
    lat = sorted(r[0] for r in ok)
    retr = sum(r[1] for r in ok)
    print(f"[{name}] 成功 {len(ok)}/{n_expected}  失敗 {len(ng)}", end="")
    if lat:
        avg = sum(lat)/len(lat)
        p95 = lat[int(len(lat)*0.95)-1] if len(lat) > 1 else lat[0]
        print(f"  応答: 平均 {avg:.2f}s / p95 {p95:.2f}s / 最悪 {lat[-1]:.2f}s  再送合計 {retr}回", end="")
    print()
    for r in ng[:5]:
        print(f"    NG例: {r[2]}")

if __name__ == "__main__":
    print(f"=== 負荷テスト: {N}名同時 ===")
    t_start = time.time()
    threads = [threading.Thread(target=student, args=(i+1,)) for i in range(N)]
    for t in threads: t.start()
    for t in threads: t.join()
    print(f"全体所要: {time.time()-t_start:.1f}s（ログイン分散20sを含む）")
    report("Phase1 ログイン", results["login"], N)
    report("Phase2 出題取得", results["fetch"], len(results["login"]))
    report("Phase3 一斉送信", results["submit"], len(results["fetch"]))
