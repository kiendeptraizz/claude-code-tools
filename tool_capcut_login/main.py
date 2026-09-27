# -*- coding: utf-8 -*-
"""Tool login CapCut hàng loạt qua GPM Login.
Input mỗi dòng: email|pass[|2fa][|proxy]

Tạo profile GPM (tên=email) + gắn proxy -> đăng nhập CapCut -> để lại profile đã login.
Chạy CLI:  python main.py
"""
import os
import sys
import json
import time
import datetime
import threading
import concurrent.futures

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa
    pass

from playwright.sync_api import sync_playwright

import config
import gpm
import capcut_login

LOG_CALLBACK = None
STOP_EVENT = threading.Event()


def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line)
    except Exception:  # noqa
        pass
    try:
        os.makedirs("logs", exist_ok=True)
        with open("logs/run.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa
        pass
    if LOG_CALLBACK:
        try:
            LOG_CALLBACK(line)
        except Exception:  # noqa
            pass


def should_stop():
    return STOP_EVENT.is_set()


# ---------- account ----------

def parse_account_line(raw):
    line = raw.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("[") and "]" in line[:6]:
        line = line.split("]", 1)[1].strip()
    parts = line.split("|")
    if not parts or not parts[0].strip():
        return None
    return {
        "email": parts[0].strip(),
        "pass": parts[1].strip() if len(parts) > 1 else "",
        "twofa": parts[2].strip() if len(parts) > 2 else "",
        "proxy": parts[3].strip() if len(parts) > 3 else "",
    }


def parse_accounts_text(text):
    out = []
    for raw in text.splitlines():
        acc = parse_account_line(raw)
        if acc:
            out.append(acc)
    return out


def load_accounts():
    if not os.path.exists(config.INPUT_FILE):
        return []
    with open(config.INPUT_FILE, "r", encoding="utf-8") as f:
        return parse_accounts_text(f.read())


def shot(page, email, tag):
    safe = email.replace("@", "_at_").replace(".", "_")
    path = f"screenshots/{safe}_{tag}.png"
    try:
        os.makedirs("screenshots", exist_ok=True)
        page.screenshot(path=path, full_page=True)
    except Exception:  # noqa
        pass
    return path


def save_result(email, status, note=""):
    os.makedirs(os.path.dirname(config.RESULT_FILE), exist_ok=True)
    with open(config.RESULT_FILE, "a", encoding="utf-8") as f:
        f.write(f"{email}|{status}|{note}\n")


def save_account_line(line, actions):
    """Ghi tài khoản để tái dùng + tra cứu:
    - data/tai_khoan_moi.txt: dòng sạch email|pass[|2fa]
    - data/ket_qua_chi_tiet.txt: thời gian | dòng | thao tác"""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs("data", exist_ok=True)
        with open("data/tai_khoan_moi.txt", "a", encoding="utf-8") as f:
            f.write(line + "\n")
        with open("data/ket_qua_chi_tiet.txt", "a", encoding="utf-8") as f:
            f.write(f"{ts} | {line} | {', '.join(actions)}\n")
    except Exception:  # noqa
        pass


def write_history(record):
    try:
        os.makedirs("data", exist_ok=True)
        with open(config.HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa
        pass


# ---------- xử lý 1 acc ----------

def login_one(acc, group_name="", raw_proxy="", check_offer=False):
    """Tạo profile (tên=email) nếu chưa có + proxy -> login CapCut (+ check offer nếu bật).
    Trả về (status, extra): status 'ok'|'already', extra chứa 'offer' nếu check_offer."""
    email = acc["email"]
    extra = {}
    prof = gpm.find_profile_by_name(email)
    if not prof:
        prof = gpm.create_profile(email, group_name=group_name, raw_proxy=raw_proxy)
    pid = gpm.get_profile_id(prof)
    if not pid:
        raise RuntimeError(f"không tạo được profile cho {email}")
    addr, _ = gpm.start_profile(pid)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://{addr}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(config.PAGE_TIMEOUT)
            page.goto(config.CAPCUT_URL, timeout=config.PAGE_TIMEOUT)
            time.sleep(3)
            status = "already" if capcut_login.is_logged_in(page) else "ok"
            if status == "ok":
                capcut_login.login(page, email, acc["pass"], acc["twofa"], log=log, shot=shot)
            if check_offer:
                extra["offer"] = capcut_login.check_offer(page, log=log, shot=shot)
            try:
                browser.close()
            except Exception:  # noqa
                pass
            return status, extra
    finally:
        if config.CLOSE_PROFILE_AFTER:
            gpm.close_profile(pid)


def run_login(accs, group_name="", threads=None, on_progress=None, on_result=None, proxies=None,
              check_offer=False):
    STOP_EVENT.clear()
    for d in ("logs", "screenshots", "data"):
        os.makedirs(d, exist_ok=True)
    if not gpm.ping():
        log("❌ Không kết nối GPM API (cổng %d). Mở GPM Login + bật API." % config.GPM_PORT)
        return 0, 0
    n = len(accs)
    if n == 0:
        log("Không có account."); return 0, 0
    proxies = [p.strip() for p in (proxies or []) if p.strip()]
    threads = max(1, min(int(threads or config.THREADS), 5))
    start_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"=== {'CHECK OFFER' if check_offer else 'LOGIN'} CAPCUT {n} acc -> nhóm '{group_name or 'All'}' | {threads} luồng ===")
    results = {}
    lock = threading.Lock()
    done = [0]

    def work(i):
        if should_stop():
            return
        acc = accs[i]
        rec = {"email": acc["email"]}
        rp = acc.get("proxy") or (proxies[i % len(proxies)] if proxies else "")
        try:
            log(f"[{i+1}/{n}] {acc['email']}" + (f"  (proxy {rp.split(':')[0]})" if rp else ""))
            st, extra = login_one(acc, group_name, raw_proxy=rp, check_offer=check_offer)
            rec["status"] = "ok"
            ops = ["đã login sẵn"] if st == "already" else ["login"]
            twofa = acc.get("twofa", "")
            line = acc["email"] + "|" + acc.get("pass", "") + (("|" + twofa) if twofa else "")
            offer = extra.get("offer") if extra else None
            if offer:
                rec["has_offer"] = offer.get("has_offer")
                rec["offer"] = offer.get("offer")
                rec["offer_detail"] = offer.get("detail")
                tag = "🎁 CÓ OFFER" if offer.get("has_offer") else ("KHÔNG offer" if offer.get("has_offer") is False else "?offer")
                ops.append(tag + (f" ({offer.get('detail')})" if offer.get("detail") else ""))
            rec["actions"] = ops
            rec["line"] = line
            rec["note"] = " | ".join(ops)
            save_result(acc["email"], "ok", rec["note"])
            save_account_line(line, ops)
            log(f"    ✅ {acc['email']} " + rec["note"])
        except Exception as e:  # noqa
            rec.update(status="fail", reason=str(e))
            rec["line"] = acc["email"] + "|" + acc.get("pass", "") + (("|" + acc.get("twofa", "")) if acc.get("twofa") else "")
            save_result(acc["email"], "fail", str(e))
            log(f"    ❌ {acc['email']}: {e}")
        with lock:
            results[acc["email"]] = rec
            done[0] += 1
            ok = sum(1 for r in results.values() if r.get("status") == "ok")
            fail = sum(1 for r in results.values() if r.get("status") == "fail")
            if on_progress:
                try:
                    on_progress(done[0], n, ok, fail)
                except Exception:  # noqa
                    pass
            if on_result:
                try:
                    on_result(rec)
                except Exception:  # noqa
                    pass
        if not should_stop():
            time.sleep(config.DELAY_BETWEEN)

    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as ex:
        list(concurrent.futures.as_completed([ex.submit(work, i) for i in range(n)]))
    ok = sum(1 for r in results.values() if r.get("status") == "ok")
    fail = sum(1 for r in results.values() if r.get("status") == "fail")
    log(f"=== XONG: {ok} OK / {fail} lỗi (trên {n}) ===")
    write_history({"time": start_ts, "group": group_name, "total": n, "ok": ok, "failed": fail,
                   "accounts": [results.get(a["email"], {"email": a["email"]}) for a in accs]})
    return ok, fail


def load_proxies():
    """Đọc proxy pool từ data/proxies.txt (mỗi dòng ip:port:user:pass), gán vòng cho acc."""
    path = "data/proxies.txt"
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]


def main():
    accs = load_accounts()
    if not accs:
        print(f"Không có account trong {config.INPUT_FILE} (mỗi dòng: email|pass[|2fa][|proxy])")
        return
    run_login(accs, group_name=config.GPM_GROUP, threads=config.THREADS, proxies=load_proxies())


if __name__ == "__main__":
    main()
