# -*- coding: utf-8 -*-
"""
Tool đổi mật khẩu Hotmail/Outlook hàng loạt (giao diện login MỚI của Microsoft 2024+).
Định dạng input mỗi dòng: email|password|refresh_token|client_id

Quy trình (đã kiểm chứng thực tế):
  Microsoft bắt thêm email khôi phục TRƯỚC khi cho đổi pass (nút Skip bị khóa).
  -> Dùng các acc Hotmail làm email khôi phục CHÉO cho nhau; đọc mã xác minh
     gửi về hòm thư acc kia qua token (IMAP).
  Chạy 2 GIAI ĐOẠN để né lỗi token chết:
    GĐ1: thêm recovery chéo cho TẤT CẢ acc (mọi token còn sống -> đọc mã được)
    GĐ2: đổi mật khẩu đồng loạt (không cần token nữa)

Chạy giao diện:  python gui.py   (hoặc nhấp đúp run_gui.bat)
Chạy dòng lệnh:  python main.py
"""
import os
import sys
import time
import json
import random
import string
import datetime
import threading
import concurrent.futures
from urllib.parse import urlparse, parse_qs

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa
    pass

# Dùng trình duyệt ở đường dẫn KHÔNG DẤU (tên user "Trung Kiên" có dấu làm
# Chromium không khởi động được: lỗi spawn UNKNOWN).
_ASCII_BROWSERS = r"C:\Users\Public\ms-playwright"
if os.path.isdir(_ASCII_BROWSERS):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _ASCII_BROWSERS

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config
import mail_otp

LOGIN_URL = "https://login.live.com/"
CHANGE_URL = "https://account.live.com/password/change"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Hook cho GUI
LOG_CALLBACK = None
STOP_EVENT = threading.Event()

# Sổ token hiện hành (cập nhật token MỚI sau mỗi lần đổi pass) — dùng chung giữa các luồng.
_TOKENS = {}          # email -> {"rt": refresh_token, "cid": client_id}
_TOKENS_LOCK = threading.Lock()

HISTORY_FILE = "data/history.jsonl"

# OAuth để xin token MỚI sau khi đổi pass (token cũ bị thu hồi)
OAUTH_REDIR = "https://login.microsoftonline.com/common/oauth2/nativeclient"
OAUTH_SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
OAUTH_AUTHORIZE = "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize"
OAUTH_TOKEN = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"


def _set_token(email, rt, cid):
    with _TOKENS_LOCK:
        _TOKENS[email] = {"rt": rt, "cid": cid}


def _get_token(email):
    with _TOKENS_LOCK:
        d = _TOKENS.get(email)
        return (d["rt"], d["cid"]) if d else (None, None)


# ---------------- tiện ích ----------------

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


def gen_password():
    if config.PASSWORD_MODE == "random":
        chars = string.ascii_letters + string.digits
        body = "".join(random.choice(chars) for _ in range(max(8, config.RANDOM_LENGTH) - 2))
        return "A" + body + "@9"
    return config.NEW_PASSWORD


def build_proxy(raw):
    """ip:port:user:pass | user:pass@ip:port | ip:port | có/không http://,socks5:// -> dict Playwright."""
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    scheme = "http"
    for s in ("socks5://", "socks4://", "https://", "http://"):
        if raw.lower().startswith(s):
            scheme = s[:-3]
            raw = raw[len(s):]
            break
    user = pwd = None
    if "@" in raw:
        creds, hostport = raw.rsplit("@", 1)
        if ":" in creds:
            user, pwd = creds.split(":", 1)
        else:
            user = creds
    else:
        parts = raw.split(":")
        if len(parts) == 4:
            host, port, user, pwd = parts
            hostport = f"{host}:{port}"
        elif len(parts) == 3:
            host, port, user = parts
            hostport = f"{host}:{port}"
        else:
            hostport = raw
    proxy = {"server": f"{scheme}://{hostport}"}
    if user:
        proxy["username"] = user
    if pwd:
        proxy["password"] = pwd
    return proxy


# ---------------- đọc / ghi account ----------------

def parse_account_line(raw):
    line = raw.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("[") and "]" in line[:6]:
        line = line.split("]", 1)[1].strip()
    parts = line.split("|")
    if len(parts) < 2:
        return None
    return {
        "email": parts[0].strip(),
        "pass": parts[1].strip(),
        "rt": parts[2].strip() if len(parts) > 2 else "",
        "cid": parts[3].strip() if len(parts) > 3 else "",
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


def save_success(email, newpass, rt, cid):
    os.makedirs(os.path.dirname(config.SUCCESS_FILE), exist_ok=True)
    with open(config.SUCCESS_FILE, "a", encoding="utf-8") as f:
        f.write(f"{email}|{newpass}|{rt}|{cid}\n")


def save_failed(acc, reason):
    os.makedirs(os.path.dirname(config.FAILED_FILE), exist_ok=True)
    with open(config.FAILED_FILE, "a", encoding="utf-8") as f:
        f.write(f"{acc['email']}|{acc['pass']}|{acc['rt']}|{acc['cid']}|{reason}\n")


# ---------------- helper Playwright ----------------

def first_visible(page, selectors, timeout=4000):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            return loc
        except PWTimeout:
            continue
        except Exception:  # noqa
            continue
    return None


def click_if(page, selectors, timeout=2500):
    loc = first_visible(page, selectors, timeout)
    if loc:
        try:
            loc.click()
            return True
        except Exception:  # noqa
            return False
    return False


def shot(page, email, tag):
    safe = email.replace("@", "_at_").replace(".", "_")
    path = f"screenshots/{safe}_{tag}.png"
    try:
        os.makedirs("screenshots", exist_ok=True)
        page.screenshot(path=path, full_page=True)
    except Exception:  # noqa
        pass
    return path


NEXT_BTNS = ['#iNext', 'button[type="submit"]', 'input[type="submit"]', '#idSIButton9']


def _new_page(pw, proxy=None):
    browser = pw.chromium.launch(
        headless=config.HEADLESS, slow_mo=config.SLOW_MO,
        proxy=build_proxy(proxy or config.PROXY),
        args=["--disable-blink-features=AutomationControlled"])
    context = browser.new_context(locale="en-US", user_agent=UA)
    context.set_default_timeout(config.PAGE_TIMEOUT)
    return browser, context, context.new_page()


def _close(browser, context):
    try:
        context.close()
        browser.close()
    except Exception:  # noqa
        pass


# ---------------- các bước (giao diện MỚI) ----------------

def new_login(page, acc):
    """Đăng nhập login.live.com (UI mới). Raise nếu lỗi."""
    page.goto(LOGIN_URL, timeout=config.PAGE_TIMEOUT)

    email_box = first_visible(page, ['#usernameEntry', 'input[type="email"]',
                                     'input[name="loginfmt"]'], 9000)
    if not email_box:
        if "account." in page.url:
            return True  # đã đăng nhập sẵn
        shot(page, acc["email"], "no_email_field")
        raise RuntimeError("không thấy ô email (trang lỗi/đổi giao diện?)")
    email_box.fill(acc["email"])
    click_if(page, NEXT_BTNS, 5000)
    time.sleep(2.5)

    pass_box = first_visible(page, ['#passwordEntry', 'input[name="passwd"]'], 5000)
    if not pass_box:
        # Acc đã có recovery -> Microsoft hiện "Verify your email" (gửi mã).
        # Chọn "Use your password" để đăng nhập bằng mật khẩu.
        if click_if(page, ['text="Use your password"',
                           'a:has-text("Use your password")',
                           'button:has-text("Use your password")',
                           '#idA_PWD_SwitchToPassword'], 3000):
            time.sleep(2)
            pass_box = first_visible(page, ['#passwordEntry', 'input[name="passwd"]'], 8000)
    if not pass_box:
        # đôi khi phải mở "Other ways to sign in" trước
        if click_if(page, ['text="Other ways to sign in"', 'text="Sign-in options"',
                           'a:has-text("Other ways")'], 2500):
            time.sleep(1.5)
            click_if(page, ['text="Use your password"',
                            'button:has-text("password")', 'a:has-text("password")'], 3000)
            time.sleep(2)
            pass_box = first_visible(page, ['#passwordEntry', 'input[name="passwd"]'], 8000)
    if not pass_box:
        if first_visible(page, ['#usernameError', 'text=/doesn.t exist|couldn.t find|no account/i'], 1200):
            raise RuntimeError("email không tồn tại")
        shot(page, acc["email"], "no_pass_field")
        raise RuntimeError("không thấy ô mật khẩu (acc bị Microsoft chặn/thử thách?)")
    pass_box.fill(acc["pass"])
    click_if(page, NEXT_BTNS, 5000)
    time.sleep(3.5)

    if first_visible(page, ['text=/incorrect password|wrong|không chính xác/i'], 1200):
        raise RuntimeError("mật khẩu cũ sai")

    # trang "A quick note" (privacy) -> OK
    click_if(page, ['button:has-text("OK")'], 2500)
    time.sleep(1.5)
    # "Stay signed in?" -> Yes
    click_if(page, ['button:has-text("Yes")', '#idSIButton9'], 1500)
    time.sleep(1)
    return True


def mint_token(page, email, cid, password):
    """Sau khi đổi pass (page đang đăng nhập), chạy OAuth xin refresh_token MỚI.
    Có thể bị 'Verify your email' -> bấm 'Use your password' + nhập pass mới -> consent.
    Trả về token mới hoặc None."""
    try:
        auth = (f"{OAUTH_AUTHORIZE}?client_id={cid}&response_type=code"
                f"&redirect_uri={OAUTH_REDIR}&response_mode=query"
                f"&scope={OAUTH_SCOPE.replace(' ', '%20')}")
        page.goto(auth, timeout=config.PAGE_TIMEOUT)
        for _ in range(9):
            if "code=" in page.url:
                break
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:  # noqa
                pass
            # 1) bị đòi xác minh email -> chọn dùng mật khẩu
            if click_if(page, ['text="Use your password"',
                               'a:has-text("Use your password")'], 2000):
                page.wait_for_timeout(2000)
                continue
            # 2) có ô mật khẩu -> điền pass MỚI
            pb = first_visible(page, ['#passwordEntry', 'input[name="passwd"]'], 2000)
            if pb:
                pb.fill(password)
                click_if(page, NEXT_BTNS, 4000)
                page.wait_for_timeout(2500)
                continue
            # 3) màn hình đồng ý quyền / "Stay signed in"
            click_if(page, ['#idSIButton9', '#idBtn_Accept',
                            'button:has-text("Accept")', 'button:has-text("Yes")',
                            'button:has-text("Continue")', 'input[value="Yes"]',
                            'input[value="Accept"]', 'button[type="submit"]'], 3000)
            page.wait_for_timeout(2500)
        code = parse_qs(urlparse(page.url).query).get("code", [None])[0]
        if not code:
            shot(page, email, "mint_no_code")
            return None
        r = requests.post(OAUTH_TOKEN, data={
            "client_id": cid, "code": code, "redirect_uri": OAUTH_REDIR,
            "grant_type": "authorization_code", "scope": OAUTH_SCOPE}, timeout=30)
        return r.json().get("refresh_token")
    except Exception as e:  # noqa
        log(f"    (mint token lỗi: {e})")
        return None


def _read_provider_code(provider_email, trigger_fn):
    """Lấy token hiện hành của provider từ sổ (retry nếu provider đang đổi pass/mint),
    mở IMAP, chốt mốc, gọi trigger_fn() để MS gửi mã, chờ mã MỚI. Trả về (code|None, alive)."""
    imap = None
    for _ in range(7):
        if should_stop():
            return None, False
        rt, cid = _get_token(provider_email)
        if rt:
            im, new_rt = mail_otp.imap_open(provider_email, rt, cid)
            if im:
                _set_token(provider_email, new_rt, cid)
                imap = im
                break
        time.sleep(5)
    if not imap:
        return None, False
    baseline = mail_otp.code_keys(imap)
    try:
        trigger_fn()
    except Exception:  # noqa
        pass
    code = mail_otp.wait_new_code(imap, baseline, config.OTP_WAIT)
    try:
        imap.logout()
    except Exception:  # noqa
        pass
    return code, True


def _enter_code(page, acc, code):
    otp = first_visible(page, ['#iOttText', 'input[name="otc"]',
                               'input[inputmode="numeric"]', 'input[type="tel"]'], 8000)
    if not otp:
        shot(page, acc["email"], "no_code_field")
        raise RuntimeError("không thấy ô nhập mã")
    otp.fill(code)
    click_if(page, NEXT_BTNS, 5000)
    time.sleep(3.5)
    if first_visible(page, ['text=/wrong|incorrect|try again|expired/i'], 1500):
        shot(page, acc["email"], "code_rejected")
        raise RuntimeError("mã bị từ chối (sai/hết hạn)")


def _solve_wall(page, acc, provider_email):
    """Trang 'Let's protect your account' -> thêm provider làm recovery + nhập mã."""
    def trigger():
        page.fill("#EmailAddress", provider_email)
        click_if(page, NEXT_BTNS, 5000)
    code, alive = _read_provider_code(provider_email, trigger)
    if not alive:
        raise RuntimeError(f"token nguồn-mã {provider_email} đã chết")
    if not code:
        shot(page, acc["email"], "no_recovery_code")
        raise RuntimeError(f"không đọc được mã gửi về {provider_email}")
    _enter_code(page, acc, code)
    log(f"    ✓ đã thêm recovery {provider_email} (mã {code})")


def _solve_stepup(page, acc, provider_email):
    """Trang 'Verify your identity' (acc đã có recovery sẵn) -> chọn proof email + nhập mã."""
    def trigger():
        if not click_if(page, ['div[role="button"]:has-text("@")',
                               'div[role="button"]:has-text("Email")',
                               'text=/Email \\S+@/'], 4000):
            click_if(page, ['text="I have a code"', 'a:has-text("have a code")'], 2500)
    code, alive = _read_provider_code(provider_email, trigger)
    if not alive:
        raise RuntimeError(f"token nguồn-mã {provider_email} đã chết")
    if not code:
        shot(page, acc["email"], "no_stepup_code")
        raise RuntimeError(f"không đọc được mã xác minh gửi về {provider_email}")
    _enter_code(page, acc, code)
    log(f"    ✓ đã qua xác minh danh tính (mã {code})")


def _do_change(page, acc, newpass):
    newp = first_visible(page, ['#iPassword', 'input[name="Password"]'], 9000)
    rep = first_visible(page, ['#iRetypePassword', 'input[name="RetypePassword"]'], 5000)
    if not (newp and rep):
        shot(page, acc["email"], "no_change_form")
        raise RuntimeError("không thấy form đổi mật khẩu")
    newp.fill(newpass)
    rep.fill(newpass)
    click_if(page, ['#UpdatePasswordAction', 'button:has-text("Save")',
                    'input[type="submit"]'], 5000)
    time.sleep(4)
    if first_visible(page, ['#iPassword'], 2500):
        txt = ""
        e = first_visible(page, ['div[role="alert"]', '.error', 'span[role="alert"]'], 1200)
        if e:
            try:
                txt = e.inner_text().strip()
            except Exception:  # noqa
                txt = ""
        shot(page, acc["email"], "change_failed")
        raise RuntimeError(f"đổi pass không lưu được (mật khẩu yếu/trùng pass cũ?). {txt[:50]}")
    shot(page, acc["email"], "after_change")


def process_account(pw, acc, provider_email, newpass, proxy=None):
    """1 phiên: đăng nhập -> qua tường/step-up -> đổi pass -> xin token MỚI.
    Trả về token mới (hoặc '' nếu mint hỏng)."""
    browser, context, page = _new_page(pw, proxy)
    try:
        new_login(page, acc)
        page.goto(CHANGE_URL, timeout=config.PAGE_TIMEOUT)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:  # noqa
            pass
        time.sleep(2)

        if page.locator("#iPassword").count() > 0:
            pass  # vào thẳng form đổi pass
        elif page.locator("#EmailAddress").count() > 0:
            _solve_wall(page, acc, provider_email)     # acc chưa có recovery
            page.goto(CHANGE_URL, timeout=config.PAGE_TIMEOUT)
            time.sleep(3)
        else:
            _solve_stepup(page, acc, provider_email)   # acc đã có recovery -> xác minh lại
            page.goto(CHANGE_URL, timeout=config.PAGE_TIMEOUT)
            time.sleep(3)

        _do_change(page, acc, newpass)

        # đổi pass xong -> token cũ bị thu hồi -> xin token MỚI bằng pass mới
        new_rt = mint_token(page, acc["email"], acc["cid"], newpass)
        if new_rt:
            _set_token(acc["email"], new_rt, acc["cid"])
        return new_rt or ""
    finally:
        _close(browser, context)


def write_history(record):
    try:
        os.makedirs("data", exist_ok=True)
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa
        pass


def load_proxies():
    """Đọc proxy pool data/proxies.txt (mỗi dòng ip:port:user:pass) — dùng khi web không truyền proxy."""
    path = "data/proxies.txt"
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]


def run_pipeline(accs, on_progress=None, threads=1, on_result=None, proxies=None):
    """Chuỗi recovery acc[i]->acc[i+1] (acc cuối->acc[0]). Mỗi acc trọn 1 phiên:
    thêm recovery + đổi pass + XIN TOKEN MỚI. Chạy song song `threads` luồng.
    Nhờ cấp token mới sau đổi pass, acc nguồn-mã luôn sống -> KHÔNG còn orphan."""
    STOP_EVENT.clear()
    for d in ("logs", "screenshots", "data"):
        os.makedirs(d, exist_ok=True)

    n = len(accs)
    if n < 2:
        log("⚠️ Cần ít nhất 2 account để recovery chéo.")
        return 0, 0

    for a in accs:                      # nạp sổ token ban đầu
        _set_token(a["email"], a["rt"], a["cid"])

    threads = max(1, min(int(threads or 1), 8))
    proxies = [p.strip() for p in (proxies or []) if p.strip()]
    start_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"=== BẮT ĐẦU: {n} acc | {threads} luồng"
        + (f" | {len(proxies)} proxy (xoay vòng)" if proxies else " | KHÔNG proxy") + " ===")

    results = {}
    lock = threading.Lock()
    done = [0]

    def work(i):
        if should_stop():
            return
        acc = accs[i]
        provider_email = accs[(i + 1) % n]["email"]
        newpass = gen_password()
        rec = {"email": acc["email"], "provider": provider_email}
        rp = proxies[i % len(proxies)] if proxies else None
        try:
            log(f"[{i+1}/{n}] BẮT ĐẦU {acc['email']}  (recovery: {provider_email})"
                + (f"  (proxy {rp.split(':')[0]})" if rp else ""))
            with sync_playwright() as pw:
                new_rt = process_account(pw, acc, provider_email, newpass, rp)
            fin_rt = new_rt or acc["rt"]
            save_success(acc["email"], newpass, fin_rt, acc["cid"])
            rec.update(status="ok", newpass=newpass, new_token=bool(new_rt),
                       line=f"{acc['email']}|{newpass}|{fin_rt}|{acc['cid']}")
            log(f"    ✅ {acc['email']} | pass mới: {newpass} | token mới: "
                f"{'CÓ' if new_rt else 'không lấy được'}")
        except Exception as e:  # noqa
            save_failed(acc, str(e))
            rec.update(status="fail", reason=str(e),
                       line=f"{acc['email']}|{acc['pass']}|{acc['rt']}|{acc['cid']}")
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

    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as ex:
        list(concurrent.futures.as_completed([ex.submit(work, i) for i in range(n)]))

    ok = sum(1 for r in results.values() if r.get("status") == "ok")
    fail = sum(1 for r in results.values() if r.get("status") == "fail")
    log(f"=== XONG: {ok} thành công / {fail} lỗi (trên {n} acc) ===")
    write_history({
        "time": start_ts, "total": n, "success": ok, "failed": fail, "threads": threads,
        "accounts": [results.get(a["email"], {"email": a["email"], "status": "?"}) for a in accs],
    })
    return ok, fail


def test_tokens(accs, on_progress=None):
    """Kiểm tra refresh_token còn sống & đọc được mail không."""
    STOP_EVENT.clear()
    total = len(accs)
    ok = dead = 0
    log(f"=== Kiểm tra token: {total} account ===")
    for i, acc in enumerate(accs, 1):
        if should_stop():
            log("=== ĐÃ DỪNG ==="); break
        if not acc["rt"]:
            log(f"  -  {acc['email']}: KHÔNG có refresh_token"); dead += 1
        else:
            imap, _ = mail_otp.imap_open(acc["email"], acc["rt"], acc["cid"])
            if not imap:
                log(f"  ✗  {acc['email']}: token CHẾT / IMAP lỗi"); dead += 1
            else:
                try:
                    imap.select("INBOX")
                    typ, data = imap.search(None, "ALL")
                    cnt = len(data[0].split()) if data and data[0] else 0
                    imap.logout()
                    log(f"  ✓  {acc['email']}: OK ({cnt} mail trong INBOX)"); ok += 1
                except Exception as e:  # noqa
                    log(f"  ✗  {acc['email']}: IMAP lỗi -> {e}"); dead += 1
        if on_progress:
            try:
                on_progress(i, total, ok, dead)
            except Exception:  # noqa
                pass
    log(f"=== Token: {ok} sống / {dead} lỗi ===")
    return ok, dead


def main():
    accs = load_accounts()
    if not accs:
        print(f"Không có account nào trong {config.INPUT_FILE}")
        return
    run_pipeline(accs)


if __name__ == "__main__":
    main()
