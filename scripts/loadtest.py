# -*- coding: utf-8 -*-
"""150同時アクセス負荷テスト — scg-student-portal

実運用の形を再現する2段構成:
  [準備] python scripts/loadtest.py tokens
     l001〜l150 のログイントークンをゆっくり取得して tmp/tokens.json に貯める。
     ※サインインAPIには同一IPからの回数制限があるため意図的に低速（30分ほど）。
       実運用でも学生のログインは「各自のスマホで事前に1回」であり、ここは本番負荷ではない。
  [本番] python scripts/loadtest.py burst
     ログイン済み150名が「同一瞬間」に出題取得→一斉送信する最悪ケースを計測。
     これがHR一斉小テストの実態に対応する数字。

出力: 成功数/失敗数/応答時間(平均・p95・最悪)/再送回数
依存: 標準ライブラリのみ
"""
import sys, os, json, time, random, threading, io
import urllib.request
import urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "https://egdcbxzpgwenmfabpodd.supabase.co"
ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVnZGNieHpwZ3dlbm1mYWJwb2RkIiwi"
        "cm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNTcwNDYsImV4cCI6MjEwMzkzMzA0Nn0.m908C67Nh4KsYnH_LWvP4wAjOtxI79hhE-BKS1MCxX0")
QUIZ_SET = "c75def6b-7623-4d86-8540-0c5b081ecf7c"
N = 150
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKENS_FILE = os.path.join(HERE, "tmp", "tokens.json")

def req(path, token=None, body=None, timeout=30):
    headers = {"apikey": ANON, "Content-Type": "application/json"}
    if token: headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=headers)
    with urllib.request.urlopen(r, timeout=timeout) as res:
        return json.loads(res.read().decode())

def req_retry(path, token=None, body=None, tries=4):
    """本番クライアントと同じ再送ロジック。戻り値: (結果, 再送回数)"""
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

# ---------- tokens: ゆっくり取得して貯める（レジューム可能） ----------
def get_tokens():
    os.makedirs(os.path.dirname(TOKENS_FILE), exist_ok=True)
    tokens = {}
    if os.path.exists(TOKENS_FILE):
        tokens = json.load(open(TOKENS_FILE, encoding="utf-8"))
        print(f"既存トークン {len(tokens)} 件から再開")
    for i in range(1, N + 1):
        sid = f"l{i:03d}"
        if sid in tokens: continue
        for attempt in range(10):
            try:
                auth = req("/auth/v1/token?grant_type=password",
                           body={"email": f"{sid}@stu.scg-portal.jp", "password": "sakura24"})
                tokens[sid] = auth["access_token"]
                json.dump(tokens, open(TOKENS_FILE, "w", encoding="utf-8"))
                print(f"{sid} OK ({len(tokens)}/{N})", flush=True)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    print(f"{sid} 429 → 60秒待機", flush=True)
                    time.sleep(60)
                else:
                    raise
        time.sleep(10)  # 制限に触れない安全ペース
    print(f"完了: {len(tokens)} 件 → {TOKENS_FILE}")

# ---------- burst: ログイン済み150名の一斉受験 ----------
results = {"fetch": [], "submit": []}
lock = threading.Lock()

def student(sid, token, barrier):
    barrier.wait()  # 全員同時に開始（アプリを開く瞬間）
    t0 = time.time()
    try:
        qs, retries = req_retry(f"/rest/v1/questions_public?select=id,seq&quiz_set_id=eq.{QUIZ_SET}&order=seq", token)
        with lock: results["fetch"].append((time.time()-t0, retries, None))
    except Exception as e:
        with lock: results["fetch"].append((time.time()-t0, 99, str(e)[:80]))
        barrier.wait(); return
    answers = {q["id"]: random.choice("ab") for q in qs}
    barrier.wait()  # 「送信して」の号令 = 全員同一瞬間に提出
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
    line = f"[{name}] 成功 {len(ok)}/{n_expected}  失敗 {len(ng)}"
    if lat:
        avg = sum(lat)/len(lat)
        p95 = lat[max(0, int(len(lat)*0.95)-1)]
        line += f"  応答: 平均 {avg:.2f}s / p95 {p95:.2f}s / 最悪 {lat[-1]:.2f}s  再送合計 {retr}回"
    print(line)
    for r in ng[:5]:
        print(f"    NG例: {r[2]}")

def burst():
    tokens = json.load(open(TOKENS_FILE, encoding="utf-8"))
    n = len(tokens)
    print(f"=== 一斉受験テスト: ログイン済み {n} 名 ===")
    barrier = threading.Barrier(n)
    threads = [threading.Thread(target=student, args=(sid, tok, barrier)) for sid, tok in tokens.items()]
    t0 = time.time()
    for t in threads: t.start()
    for t in threads: t.join()
    print(f"全体所要: {time.time()-t0:.1f}s")
    report("出題取得(同時)", results["fetch"], n)
    report("一斉送信(同時)", results["submit"], len([r for r in results["fetch"] if r[2] is None]))

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "burst"
    if mode == "tokens": get_tokens()
    elif mode == "burst": burst()
    else: print("usage: loadtest.py [tokens|burst]")
