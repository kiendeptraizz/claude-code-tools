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

# ===== CHỜ XÁC MINH TAY (captcha / verify) =====
# Khi gặp các loại phải xử lý tay, tool DỪNG, GIỮ cửa sổ GPM mở để bạn tự xác minh,
# rồi bấm "Tiếp tục" (GUI) / gọi /api/resume (web) -> tool kiểm tra lại + chạy tiếp.
PAUSE_FOR_MANUAL = False
MANUAL_CODES = {"captcha", "verify_phone", "verify_you", "challenge"}
BACKUP_PASS = ""                  # pass dự phòng CHUNG cho cả pool (pass chính sai thì thử pass này)
_PAUSED = {}                      # email -> {"event", "code", "label", "since"}
_PAUSE_LOCK = threading.Lock()
_MACHINE_IP = ""                  # IP công khai của MÁY (không proxy) — để so biết proxy có ăn không


def list_paused():
    """Danh sách acc đang CHỜ bạn xác minh tay (để UI hiện nút 'Tiếp tục')."""
    with _PAUSE_LOCK:
        return [{"email": e, "code": d["code"], "label": d["label"], "since": d["since"]}
                for e, d in _PAUSED.items()]


def resume_paused(email=None):
    """Báo 'đã xác minh xong' cho 1 acc (email) hoặc TẤT CẢ (email=None)."""
    with _PAUSE_LOCK:
        if email:
            d = _PAUSED.get(email)
            if d:
                d["event"].set()
                return True
            return False
        for d in _PAUSED.values():
            d["event"].set()
        return True


def normalize_proxy(raw):
    """Chuẩn hóa 1 dòng proxy về định dạng GPM nhận:
       - bỏ dòng trống / ghi chú / nhãn [..] đầu dòng
       - URL  scheme://user:pass@host:port  ->  scheme://host:port:user:pass
       - giữ nguyên  host:port  /  host:port:user:pass  (GPM coi là HTTP)
    """
    s = (raw or "").strip()
    if not s or s.startswith("#"):
        return ""
    if s.startswith("[") and "]" in s[:60]:
        s = s.split("]", 1)[1].strip()
    m = re.match(r"^(https?|socks5|socks4)://(?:([^:@/]+):([^@/]+)@)?([^:/@]+):(\d+)/?$", s, re.I)
    if m:
        scheme, user, pw, host, port = m.groups()
        base = f"{host}:{port}"
        if user and pw:
            base += f":{user}:{pw}"
        return f"{scheme.lower()}://{base}"
    return s


def load_proxies():
    """Đọc proxy CHUNG từ data/proxies.txt (file hub ghi vào) -> list đã chuẩn hóa."""
    out = []
    p = config.PROXY_FILE
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    s = normalize_proxy(line)
                    if s:
                        out.append(s)
        except Exception:  # noqa
            pass
    return out


def _machine_public_ip():
    """IP công khai của máy (gọi TRỰC TIẾP, không qua proxy)."""
    import requests
    try:
        return requests.get(config.IP_CHECK_URL, timeout=10).text.strip()
    except Exception:  # noqa
        return ""


_START_LOCK = threading.Lock()


def _open_profile_cdp(pw, pid):
    """Mở profile GPM rồi GẮN Playwright qua CDP — có RETRY chờ cổng debug mở.
    Chống lỗi 'connect_over_cdp ECONNREFUSED' khi mở nhiều profile cùng lúc
    (GPM trả địa chỉ ngay nhưng Chrome chưa kịp bind cổng). Trả (browser, addr)."""
    # Giãn cách lúc START để GPM không phải dựng nhiều Chrome cùng lúc
    with _START_LOCK:
        addr, _ = gpm.start_profile(pid)
        time.sleep(config.START_STAGGER)
    last = None
    for attempt in range(config.CDP_CONNECT_TRIES):
        if should_stop():
            raise RuntimeError("đã dừng khi đang mở profile")
        try:
            return pw.chromium.connect_over_cdp(f"http://{addr}"), addr
        except Exception as e:  # noqa
            last = e
            if attempt == 2:
                log(f"    ⏳ chờ Chrome của profile mở cổng debug ({addr})...")
            time.sleep(config.CDP_CONNECT_DELAY)
    raise RuntimeError(f"không gắn được CDP {addr} sau {config.CDP_CONNECT_TRIES} lần "
                       f"(~{int(config.CDP_CONNECT_TRIES * config.CDP_CONNECT_DELAY)}s) — "
                       f"GPM mở profile chưa xong/thất bại: {last}")


def _egress_ip(page):
    """Đọc IP ra ngoài của PROFILE (để xác nhận proxy có ăn không)."""
    for u in (config.IP_CHECK_URL, "https://ifconfig.me/ip", "https://icanhazip.com"):
        try:
            page.goto(u, timeout=15000)
            txt = (page.inner_text("body") or "").strip()
            m = re.search(r"\d{1,3}(?:\.\d{1,3}){3}", txt)
            if m:
                return m.group(0)
        except Exception:  # noqa
            continue
    return ""


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

    try:
        with sync_playwright() as pw:
            browser, addr = _open_profile_cdp(pw, pid)
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


def _mark_profile(pid, code):
    """Đánh dấu note + màu profile GPM theo kết quả login (best-effort)."""
    label = google_login.LABELS.get(code, code)
    if code in google_login.GOOD_CODES:
        gpm.update_profile(pid, note=label, color=gpm.COLOR_GREEN)
    else:
        gpm.update_profile(pid, note=label, color=gpm.COLOR_PURPLE)


def _wait_manual(page, acc, code):
    """GẶP captcha/verify: GIỮ cửa sổ GPM mở, chờ bạn tự xác minh rồi bấm 'Tiếp tục'.
    Sau khi bạn báo xong -> TIẾP TỤC đăng nhập (điền nốt email/pass/2FA) chứ không
    chỉ reload. Trả (code_mới, msg). Không tự giải captcha."""
    email = acc["email"]
    label = google_login.LABELS.get(code, code)
    ev = threading.Event()
    since = datetime.datetime.now().strftime("%H:%M:%S")
    with _PAUSE_LOCK:
        _PAUSED[email] = {"event": ev, "code": code, "label": label, "since": since}
    log(f"    ⏸ CHỜ XÁC MINH TAY: {email} [{label}] — cửa sổ GPM của acc đang MỞ, "
        f"bạn tự xử lý (giải captcha / xác minh SĐT / 'it's you') xong rồi bấm '▶ Tiếp tục'.")
    waited = 0
    try:
        while not ev.wait(1):
            waited += 1
            if should_stop():
                log(f"    ⏹ Bỏ chờ {email} (đã dừng).")
                return code, "đã dừng khi đang chờ xác minh tay"
            if waited >= config.PAUSE_TIMEOUT:
                log(f"    ⌛ Hết giờ chờ xác minh tay {email} ({config.PAUSE_TIMEOUT}s) — bỏ qua.")
                return code, f"hết giờ chờ xác minh tay ({config.PAUSE_TIMEOUT}s)"
    finally:
        with _PAUSE_LOCK:
            _PAUSED.pop(email, None)
    # bạn báo xong -> TIẾP TỤC đăng nhập từ trang hiện tại (điền nốt pass/2FA)
    log(f"    ▶ {email}: bạn báo đã xác minh xong — tiếp tục đăng nhập (điền nốt pass/2FA)...")
    try:
        if google_login.continue_login(page, email, acc.get("pass", ""), acc.get("twofa", ""),
                                       log=log, shot=shot, backup_pass=BACKUP_PASS):
            log(f"    ✅ {email}: đã vào được sau khi bạn xác minh tay.")
            return "ok", "đăng nhập được sau khi bạn xác minh tay"
    except google_login.LoginError as e:  # noqa
        return e.code, str(e)
    except Exception as e:  # noqa
        return google_login.categorize(str(e)), str(e)
    return code, "vẫn chưa xong sau xác minh tay (thử lại / để sau)"


def login_one(acc, group_name="", raw_proxy="", mark=False):
    """Tạo profile (tên=email) nếu chưa có -> đăng nhập Google -> để lại profile đã login.
    KHÔNG raise: trả về dict {code, pid, msg}. code xem google_login.LABELS.
    Phiên đăng nhập được giữ lại trong profile GPM (đóng cửa sổ vẫn còn cookie)."""
    email = acc["email"]
    rp = normalize_proxy(raw_proxy)
    prof = gpm.find_profile_by_name(email)
    existed = bool(prof)
    if not prof:
        prof = gpm.create_profile(email, group_name=group_name, raw_proxy=rp)
    pid = gpm.get_profile_id(prof)
    if not pid:
        return {"code": "error", "pid": None, "msg": f"không tạo được profile cho {email}"}
    # Profile ĐÃ CÓ: gán proxy mới (create chỉ set proxy lúc tạo -> profile cũ vẫn IP máy)
    if existed and rp:
        try:
            ok_set = gpm.update_profile(pid, raw_proxy=rp)
            log(f"    🔧 gán proxy cho profile sẵn có ({rp.split('://')[-1].split(':')[0]})"
                + ("" if ok_set else " — GPM báo không set được"))
        except Exception:  # noqa
            pass

    code, msg = "ok", ""
    try:
        with sync_playwright() as pw:
            browser, addr = _open_profile_cdp(pw, pid)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(config.PAGE_TIMEOUT)
            # Kiểm tra IP thật của profile (xem proxy có ăn không)
            if rp and config.CHECK_IP:
                ip = _egress_ip(page)
                if ip and _MACHINE_IP and ip == _MACHINE_IP:
                    log(f"    ⚠️ proxy KHÔNG ăn — profile vẫn IP máy ({ip}). Kiểm tra lại proxy/định dạng.")
                elif ip:
                    log(f"    🌐 IP profile: {ip}")
                else:
                    log("    ⚠️ không đọc được IP (mạng/proxy có thể lỗi).")
            page.goto(GLOGIN_URL, timeout=config.PAGE_TIMEOUT)
            time.sleep(3)
            if google_login.is_logged_in(page):
                code = "already"
            else:
                try:
                    google_login.login(page, email, acc["pass"], acc["twofa"], log=log, shot=shot,
                                       backup_pass=BACKUP_PASS)
                    time.sleep(2)
                    url = page.url or ""
                    ok = ("myaccount.google.com" in url) or google_login.is_logged_in(page) \
                        or ("/signin" not in url and "accounts.google.com/v3/signin" not in url)
                    if not ok:
                        shot(page, email, "login_unverified")
                        code, msg = "challenge", "không xác nhận được đăng nhập (có thể bị thử thách)"
                except google_login.LoginError as e:  # noqa
                    code, msg = e.code, str(e)
                except Exception as e:  # noqa
                    code, msg = google_login.categorize(str(e)), str(e)
                # GẶP captcha/verify + bật chế độ chờ -> GIỮ cửa sổ mở, chờ bạn xác minh tay
                if PAUSE_FOR_MANUAL and code in MANUAL_CODES and not should_stop():
                    code, msg = _wait_manual(page, acc, code)
            try:
                browser.close()
            except Exception:  # noqa
                pass
    except Exception as e:  # noqa (lỗi mở profile / CDP)
        code, msg = "error", str(e)
    finally:
        if mark and pid:
            try:
                _mark_profile(pid, code)
            except Exception:  # noqa
                pass
        if config.CLOSE_PROFILE_AFTER:
            gpm.close_profile(pid)
    return {"code": code, "pid": pid, "msg": msg}


def save_login_result(rec):
    """Ghi 1 dòng kết quả login: email|code|nhãn|lý_do."""
    try:
        os.makedirs("data", exist_ok=True)
        with open(config.LOGIN_RESULT_FILE, "a", encoding="utf-8") as f:
            f.write(f"{rec.get('email','?')}|{rec.get('code','?')}|"
                    f"{rec.get('label','')}|{rec.get('reason','')}\n")
    except Exception:  # noqa
        pass


def write_login_history(record):
    try:
        os.makedirs("data", exist_ok=True)
        with open(config.LOGIN_HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa
        pass


def run_login(accs, group_name="", threads=None, on_progress=None, on_result=None,
              proxies=None, mark=False, pause=False, backup_pass=""):
    """Login hàng loạt + PHÂN LOẠI từng acc (sống/chết + lý do). Giữ phiên trong profile GPM.
    pause=True: gặp captcha/verify thì DỪNG chờ bạn xác minh tay rồi chạy tiếp.
    backup_pass: pass dự phòng chung — pass chính sai thì thử pass này.
    Trả về (số acc còn login được, số acc không login được)."""
    global PAUSE_FOR_MANUAL, _MACHINE_IP, BACKUP_PASS
    STOP_EVENT.clear()
    with _PAUSE_LOCK:
        _PAUSED.clear()
    PAUSE_FOR_MANUAL = bool(pause)
    BACKUP_PASS = (backup_pass or "").strip()
    for d in ("logs", "screenshots", "data"):
        os.makedirs(d, exist_ok=True)
    if not gpm.ping():
        log("❌ Không kết nối GPM API."); return 0, 0
    n = len(accs)
    if n == 0:
        log("Không có account."); return 0, 0
    # Proxy: gộp proxy truyền vào + proxy chung từ data/proxies.txt (hub ghi)
    proxies = [normalize_proxy(p) for p in (proxies or [])]
    proxies = [p for p in proxies if p]
    if not proxies:
        proxies = load_proxies()
    threads = max(1, min(int(threads or 1), 5))
    start_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Lấy IP máy 1 lần (để so biết proxy có ăn không)
    _MACHINE_IP = _machine_public_ip() if config.CHECK_IP else ""
    log(f"=== LOGIN {n} acc -> nhóm '{group_name or 'All'}' | {threads} luồng"
        + (f" | {len(proxies)} proxy" if proxies else " | KHÔNG proxy")
        + (" | CHỜ xác minh tay: BẬT" if PAUSE_FOR_MANUAL else "")
        + (" | có pass dự phòng" if BACKUP_PASS else "") + " ===")
    if _MACHINE_IP:
        log(f"    (IP máy hiện tại: {_MACHINE_IP} — profile có proxy phải KHÁC IP này)")
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
            r = login_one(acc, group_name, raw_proxy=rp, mark=mark)
            code, msg = r.get("code", "error"), r.get("msg", "")
        except Exception as e:  # noqa
            code, msg = google_login.categorize(str(e)), str(e)
        label = google_login.LABELS.get(code, code)
        good = code in google_login.GOOD_CODES
        rec.update(status="ok" if good else "fail", code=code, label=label, reason=msg)
        save_login_result(rec)
        log(("    ✅ " if good else "    ❌ ") + f"{acc['email']}  {label}"
            + (f"  ({msg})" if msg and not good else ""))
        with lock:
            results[acc["email"]] = rec
            done[0] += 1
            ok = sum(1 for r in results.values() if r.get("status") == "ok")
            fail = sum(1 for r in results.values() if r.get("status") != "ok")
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

    # tổng kết theo từng loại
    from collections import Counter
    cnt = Counter(r.get("code", "error") for r in results.values())
    ok = sum(cnt.get(c, 0) for c in google_login.GOOD_CODES)
    fail = n - ok
    log(f"=== LOGIN XONG: {ok} còn login được / {fail} không (trên {n}) ===")
    for c, lbl in google_login.LABELS.items():
        if cnt.get(c):
            log(f"      {lbl}: {cnt[c]}")
    write_login_history({"time": start_ts, "action": "login", "group": group_name, "total": n,
                         "ok": ok, "failed": fail, "counts": dict(cnt),
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
