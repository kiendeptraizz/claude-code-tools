# -*- coding: utf-8 -*-
"""Tool check Google Family qua GPM Login.
Input mỗi dòng: email|pass|2fa(secret TOTP)   (2fa có thể để trống nếu acc không bật)

Chạy GUI:  python gui.py   (hoặc nhấp đúp run_gui.bat)
Chạy CLI:  python main.py
"""
import os
import re
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
import google_login
import family

LOG_CALLBACK = None
STOP_EVENT = threading.Event()

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def get_logged_in_email(page):
    """Đọc email đang đăng nhập từ thanh tài khoản Google (One Google Bar aria-label)."""
    try:
        labels = page.eval_on_selector_all(
            "[aria-label]", "els => els.map(e => e.getAttribute('aria-label')).filter(Boolean)")
    except Exception:  # noqa
        labels = []
    # ưu tiên label nhắc tới "Account/Tài khoản" + có email
    for al in labels:
        if "@" in al and re.search(r"account|tài khoản", al, re.I):
            m = _EMAIL_RE.search(al)
            if m:
                return m.group(0).lower()
    for al in labels:
        m = _EMAIL_RE.search(al or "")
        if m and "google" not in m.group(0).lower():
            return m.group(0).lower()
    return None


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
        "proxy": parts[3].strip() if len(parts) > 3 else "",  # tùy chọn: email|pass|2fa|proxy
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


def member_label(m):
    nm = (m.get("name") or "").strip()
    em = (m.get("email") or "").strip()
    if nm and em:
        return f"{nm} <{em}>"
    return em or nm


def save_result(info):
    os.makedirs(os.path.dirname(config.RESULT_FILE), exist_ok=True)
    mem = ", ".join(member_label(m) for m in info.get("members", []))
    with open(config.RESULT_FILE, "a", encoding="utf-8") as f:
        f.write(f"{info.get('profile','')}|{info.get('email','?')}|{info.get('role','?')}|"
                f"{info.get('member_count',0)}|{info.get('free_slots','?')}|{mem}\n")


def write_history(record):
    try:
        os.makedirs("data", exist_ok=True)
        with open(config.HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa
        pass


# ---------- xử lý 1 profile (read-only) ----------

def process_profile(prof):
    """Mở profile GPM -> gắn Playwright -> đọc email đăng nhập + family. Read-only.
    Nếu profile chưa đăng nhập Google thì báo (không tự login)."""
    pid = gpm.get_profile_id(prof)
    pname = prof.get("name") or prof.get("profile_name") or str(pid)
    if not pid:
        raise RuntimeError(f"profile thiếu id: {prof}")

    addr, _ = gpm.start_profile(pid)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://{addr}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(config.PAGE_TIMEOUT)

            page.goto(config.FAMILY_URL, timeout=config.PAGE_TIMEOUT)
            time.sleep(3)

            if not google_login.is_logged_in(page):
                shot(page, pname, "not_logged_in")
                info = {"profile": pname, "email": "", "status": "not_logged_in",
                        "role": "-", "member_count": 0, "free_slots": "-", "members": []}
            else:
                email = get_logged_in_email(page) or "?"
                info = family.read_family(page, email, log=log, shot=shot)
                info["profile"] = pname
                info["email"] = email
                info["status"] = "error" if info.get("error") else "ok"
            try:
                browser.close()
            except Exception:  # noqa
                pass
            return info
    finally:
        if config.CLOSE_PROFILE_AFTER:
            gpm.close_profile(pid)


# ---------- chạy theo NHÓM ----------

def run_group(group_id, group_name="", on_progress=None, threads=None, on_result=None, mark=False):
    STOP_EVENT.clear()
    for d in ("logs", "screenshots", "data"):
        os.makedirs(d, exist_ok=True)

    if not gpm.ping():
        log("❌ Không kết nối GPM Login API (cổng %d). Hãy MỞ GPM Login + bật API." % config.GPM_PORT)
        return 0, 0
    try:
        profiles = gpm.list_profiles(group_id=group_id)
    except Exception as e:  # noqa
        log(f"❌ Không lấy được profile của nhóm: {e}")
        return 0, 0

    n = len(profiles)
    if n == 0:
        log("Nhóm này không có profile nào.")
        return 0, 0

    threads = max(1, min(int(threads or config.THREADS), 5))
    start_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"=== BẮT ĐẦU nhóm '{group_name}': {n} profile | {threads} luồng ===")

    results = {}
    lock = threading.Lock()
    done = [0]

    def work(i):
        if should_stop():
            return
        prof = profiles[i]
        pname = prof.get("name") or str(i)
        pid = gpm.get_profile_id(prof)
        rec = {"profile": pname}
        try:
            log(f"[{i+1}/{n}] {pname}")
            info = process_profile(prof)
            save_result(info)
            st = info.get("status")
            if st == "not_logged_in":
                rec.update(status="skip", reason="chưa đăng nhập Google")
                log(f"    ⏭  {pname}: chưa đăng nhập Google")
            elif st == "error":
                rec.update(status="error", email=info.get("email"),
                           reason=info.get("note") or "không đọc được family")
                log(f"    ⚠️  {pname}: {info.get('note')}")
            else:
                rec.update(status="ok", email=info.get("email"), role=info.get("role"),
                           member_count=info.get("member_count"), free_slots=info.get("free_slots"),
                           members=[member_label(m) for m in info.get("members", [])])
                log(f"    ✅ {pname} | {info.get('email','?')} | {info.get('role','?')} | "
                    f"{info.get('member_count',0)} tv | còn {info.get('free_slots','?')} slot"
                    + (f" | {rec['members']}" if rec.get("members") else ""))
                if info.get("note"):
                    log(f"       ({info['note']})")
        except Exception as e:  # noqa
            rec.update(status="fail", reason=str(e))
            log(f"    ❌ {pname}: {e}")
        # ĐÁNH DẤU vào GPM (ghi đè note + gửi color best-effort) nếu bật
        if mark and pid:
            try:
                fs = rec.get("free_slots")
                if rec.get("status") == "ok" and isinstance(fs, int) and fs > 0:
                    gpm.update_profile(pid, note=f"🔴 còn {fs} slot", color=gpm.COLOR_RED)
                    log(f"    🔴 đánh dấu GPM: còn {fs} slot")
                elif rec.get("status") == "ok":
                    gpm.update_profile(pid, note="còn 0 slot (đầy)")
                else:   # skip / error / fail = chưa vào được / lỗi
                    gpm.update_profile(pid, note="🟣 chưa vào được / lỗi", color=gpm.COLOR_PURPLE)
                    log(f"    🟣 đánh dấu GPM: lỗi/chưa vào được")
            except Exception:  # noqa
                pass
        with lock:
            results[pname] = rec
            done[0] += 1
            ok = sum(1 for r in results.values() if r.get("status") == "ok")
            fail = sum(1 for r in results.values() if r.get("status") in ("fail", "error"))
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
    skip = sum(1 for r in results.values() if r.get("status") == "skip")
    log(f"=== XONG nhóm '{group_name}': {ok} đọc được / {skip} chưa login / {fail} lỗi (trên {n}) ===")
    write_history({"time": start_ts, "group": group_name, "total": n,
                   "ok": ok, "skip": skip, "failed": fail,
                   "profiles": [results.get(p.get("name"), {"profile": p.get("name")}) for p in profiles]})
    return ok, fail


# ---------- LOGIN hàng loạt ----------

GLOGIN_URL = "https://accounts.google.com/signin/v2/identifier?flowName=GlifWebSignIn&hl=en"


def login_one(acc, group_name="", raw_proxy=""):
    """Tạo profile (tên=email) nếu chưa có -> đăng nhập Google -> để lại profile đã login.
    Trả về 'ok' | 'already'."""
    email = acc["email"]
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
            page.goto(GLOGIN_URL, timeout=config.PAGE_TIMEOUT)
            time.sleep(3)
            if google_login.is_logged_in(page):
                return "already"
            google_login.login(page, email, acc["pass"], acc["twofa"], log=log, shot=shot)
            time.sleep(2)
            url = page.url or ""
            ok = ("myaccount.google.com" in url) or google_login.is_logged_in(page) \
                or ("/signin" not in url and "accounts.google.com/v3/signin" not in url)
            try:
                browser.close()
            except Exception:  # noqa
                pass
            if not ok:
                shot(page, email, "login_unverified")
                raise RuntimeError("không xác nhận được đăng nhập (có thể bị thử thách)")
            return "ok"
    finally:
        if config.CLOSE_PROFILE_AFTER:
            gpm.close_profile(pid)


def run_login(accs, group_name="", threads=None, on_progress=None, on_result=None, proxies=None):
    STOP_EVENT.clear()
    for d in ("logs", "screenshots", "data"):
        os.makedirs(d, exist_ok=True)
    if not gpm.ping():
        log("❌ Không kết nối GPM API."); return 0, 0
    n = len(accs)
    if n == 0:
        log("Không có account."); return 0, 0
    proxies = [p.strip() for p in (proxies or []) if p.strip()]
    threads = max(1, min(int(threads or 1), 5))
    start_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"=== LOGIN {n} acc -> nhóm '{group_name or 'All'}' | {threads} luồng ===")
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
            st = login_one(acc, group_name, raw_proxy=rp)
            rec["status"] = "ok"
            rec["note"] = "đã login sẵn" if st == "already" else ""
            log(f"    ✅ {acc['email']}" + (" (đã login sẵn)" if st == "already" else " đăng nhập OK"))
        except Exception as e:  # noqa
            rec.update(status="fail", reason=str(e))
            log(f"    ❌ {acc['email']}: {e}")
        with lock:
            results[acc["email"]] = rec
            done[0] += 1
            ok = sum(1 for r in results.values() if r.get("status") == "ok")
            fail = sum(1 for r in results.values() if r.get("status") in ("fail", "error"))
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
    log(f"=== LOGIN XONG: {ok} OK / {fail} lỗi (trên {n}) ===")
    write_history({"time": start_ts, "action": "login", "group": group_name, "total": n,
                   "ok": ok, "failed": fail,
                   "accounts": [results.get(a["email"], {"email": a["email"]}) for a in accs]})
    return ok, fail


def main():
    if not gpm.ping():
        print("Không kết nối GPM Login API. Mở GPM Login + bật API rồi chạy lại.")
        return
    groups = gpm.list_groups()
    print("Các nhóm GPM:")
    for g in groups:
        print(f"  id={g.get('id')}  {g.get('name')}")
    print("\nDùng GUI (python gui.py) để chọn nhóm và check.")


if __name__ == "__main__":
    main()
