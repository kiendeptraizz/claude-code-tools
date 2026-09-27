# -*- coding: utf-8 -*-
"""Đăng nhập ChatGPT (OpenAI, email+mật khẩu) trong browser GPM qua CDP.
Tự sinh mã 2FA (TOTP) nếu acc bật.

LƯU Ý: selector auth.openai.com hay đổi + có Cloudflare "Verify you are human".
Hàm dùng nhiều selector dự phòng + chụp màn hình khi kẹt để chỉnh khi chạy thật.
"""
import re
import time

import pyotp

import config

EMAIL_SEL = ['input[name="email"]', 'input#email-input', 'input[type="email"]',
             'input[autocomplete="username"]', 'input[inputmode="email"]']
PASS_SEL = ['input[name="password"]', 'input[type="password"]',
            'input[autocomplete="current-password"]']
OTP_SEL = ['input[name="code"]', 'input[autocomplete="one-time-code"]',
           'input[inputmode="numeric"]', 'input[type="tel"]']
CONTINUE_SEL = ['button[type="submit"]', 'button:has-text("Continue")',
                'button:has-text("Tiếp tục")', 'button:has-text("Next")',
                'input[type="submit"]']


def totp_now(secret):
    if not secret:
        return None
    secret = secret.strip()
    if secret.lower().startswith("otpauth://"):
        try:
            return pyotp.parse_uri(secret).now()
        except Exception:  # noqa
            m = re.search(r"secret=([A-Za-z0-9]+)", secret)
            secret = m.group(1) if m else secret
    secret = secret.replace(" ", "").replace("-", "")
    try:
        return pyotp.TOTP(secret).now()
    except Exception:  # noqa
        return None


def _body(page):
    try:
        return page.inner_text("body")
    except Exception:  # noqa
        return ""


def is_logged_in(page):
    """Đã đăng nhập ChatGPT. chatgpt.com vào được KHÔNG cần login, nên phải xét:
    còn nút 'Đăng nhập'/'Log in' trên trang => CHƯA đăng nhập."""
    url = page.url or ""
    if "auth.openai.com" in url or "/auth/login" in url or "/log-in" in url:
        return False
    if "chatgpt.com" not in url and "platform.openai.com" not in url:
        return False
    # CHỈ tính nút "Đăng nhập"/"Log in" ĐANG HIỂN THỊ (trang đã login vẫn còn element ẩn trong DOM)
    try:
        for sel in ['button:has-text("Đăng nhập")', 'a:has-text("Đăng nhập")',
                    'button:has-text("Log in")', 'a:has-text("Log in")',
                    '[data-testid="login-button"]']:
            loc = page.locator(sel)
            for i in range(min(loc.count(), 5)):
                try:
                    if loc.nth(i).is_visible():
                        return False
                except Exception:  # noqa
                    pass
    except Exception:  # noqa
        pass
    return True


def session_alive(page, log=print):
    """Xác minh phiên ĐANG login còn SỐNG thật (tránh is_logged_in false-positive):
    mở #settings/Account, nếu bị đá về auth.openai.com/log-in hoặc không hiện modal -> phiên chết."""
    try:
        page.goto("https://chatgpt.com/#settings/Account", timeout=config.PAGE_TIMEOUT)
    except Exception:  # noqa
        pass
    time.sleep(2)
    url = page.url or ""
    if "auth.openai.com" in url or "/log-in" in url:
        return False
    for _ in range(3):  # chờ modal settings hiện
        try:
            if page.locator('[role="dialog"]').count():
                return True
        except Exception:  # noqa
            pass
        time.sleep(1.5)
    return False


def account_state(page, log=print):
    """Hỏi THẲNG backend OpenAI xem phiên hiện tại có phải TÀI KHOẢN CÒN SỐNG không — đáng tin hơn
    is_logged_in()/session_alive() (chỉ nhìn UI) vì tài khoản đã bị vô hiệu hoá VẪN có thể còn
    cookie/JWT ở client một lúc → 'đã login sẵn' giả. Gọi 2 API same-origin trên chatgpt.com:
      1) /api/auth/session  -> lấy accessToken (không có => 'nosession': chưa/đã hết phiên)
      2) /backend-api/me (Bearer token) -> 200 => tài khoản sống; 401/403 => phiên bị thu hồi
    Trả 'live' | 'dead' | 'nosession' | 'unknown'. KHÔNG điều hướng, ~1-2s.
    (Acc CHƯA từng login -> 'nosession' -> caller tự đăng nhập bằng mật khẩu như bình thường.)"""
    url = page.url or ""
    if "chatgpt.com" not in url:
        try:
            page.goto(config.CHATGPT_URL, timeout=config.PAGE_TIMEOUT)
            time.sleep(2)
        except Exception:  # noqa
            return "unknown"
    js = """async () => {
      const out = {tok: 0, st: 0, body: ""};
      try {
        const s = await fetch('/api/auth/session', {credentials:'include', cache:'no-store'})
                        .then(r => r.ok ? r.json() : null).catch(() => null);
        const tok = s && s.accessToken;
        if (!tok) return out;
        out.tok = 1;
        const r = await fetch('/backend-api/me', {
          headers: {'Authorization': 'Bearer ' + tok},
          credentials: 'include', cache: 'no-store'
        });
        out.st = r.status;
        try { out.body = (await r.text()).slice(0, 400); } catch (e) {}
      } catch (e) { out.err = String(e); }
      return out;
    }"""
    try:
        r = page.evaluate(js)
    except Exception:  # noqa
        return "unknown"
    if not isinstance(r, dict):
        return "unknown"
    st = r.get("st") or 0
    if st == 200:
        try:
            log("    ✓ backend /me 200 → tài khoản còn sống")
        except Exception:  # noqa
            pass
        return "live"
    body = (r.get("body") or "").lower()
    if any(k in body for k in ("deactivated", "suspended", "disabled", "banned", "đã bị xóa", "vô hiệu")):
        return "dead"
    if not r.get("tok"):
        return "nosession"
    if st in (401, 403):
        return "nosession"   # phiên bị thu hồi → login lại để phân biệt die (deactivated) hay chỉ hết hạn
    return "unknown"


def _first_visible(page, selectors, timeout=8000):
    for sel in selectors:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=timeout)
            return el
        except Exception:  # noqa
            continue
    return None


def _click(page, selectors, timeout=6000):
    el = _first_visible(page, selectors, timeout)
    if el:
        try:
            el.click()
            return True
        except Exception:  # noqa
            return False
    return False


def _cloudflare(page):
    b = _body(page).lower()
    if any(k in b for k in ("verify you are human", "checking your browser",
                            "cloudflare", "just a moment")):
        return True
    # iframe turnstile
    try:
        if page.locator('iframe[src*="challenges.cloudflare.com"]').count():
            return True
    except Exception:  # noqa
        pass
    return False


def login(page, email, password, twofa_secret, log=print, shot=None):
    """Đăng nhập OpenAI. Raise nếu lỗi/bị chặn. Trả về True nếu xong."""
    page.goto(config.LOGIN_URL, timeout=config.PAGE_TIMEOUT)
    time.sleep(4)

    if _cloudflare(page):
        # chờ Cloudflare tự qua (fingerprint GPM) — poll tới CF_WAIT giây
        waited = 0
        cf_max = getattr(config, "CF_WAIT", 20)
        while _cloudflare(page) and waited < cf_max:
            time.sleep(4)
            waited += 4
        if _cloudflare(page):
            if shot:
                shot(page, email, "cloudflare")
            raise RuntimeError("bị Cloudflare chặn (verify you are human)")

    # ----- 0) Trang "Phiên đã kết thúc" -> bấm "Đăng nhập"/"Log in" để vào form -----
    if not _first_visible(page, EMAIL_SEL, 3000):
        _click(page, ['button:has-text("Đăng nhập")', 'a:has-text("Đăng nhập")',
                      'button:has-text("Log in")', 'a:has-text("Log in")',
                      '[role="button"]:has-text("Đăng nhập")', ':text-is("Đăng nhập")',
                      ':text-is("Log in")'], 5000)
        time.sleep(3)

    # ----- 1) Email -----
    ebox = _first_visible(page, EMAIL_SEL, 12000)
    if not ebox:
        if is_logged_in(page):
            return True
        if shot:
            shot(page, email, "no_email_field")
        raise RuntimeError("không thấy ô email (trang lạ / Cloudflare?)")
    log(f"    nhập email {email}")
    ebox.fill(email)
    _click(page, CONTINUE_SEL, 6000)
    time.sleep(3)

    # ----- 2) Mật khẩu -----
    pbox = _first_visible(page, PASS_SEL, 12000)
    if not pbox:
        b = _body(page)
        if re.search(r"(no account|couldn.t find|not found|isn.t an account)", b, re.I):
            raise RuntimeError("email không tồn tại / chưa có acc")
        if shot:
            shot(page, email, "no_password_field")
        raise RuntimeError("không tới được ô mật khẩu")
    log("    nhập mật khẩu")
    pbox.fill(password)
    _click(page, CONTINUE_SEL, 6000)
    time.sleep(4)

    b = _body(page)
    if re.search(r"(đã bị xóa|vô hiệu hóa|deleted or disabled|deactivated|đình chỉ|suspended|banned)", b, re.I):
        if shot:
            shot(page, email, "account_disabled")
        raise RuntimeError("tài khoản đã bị xóa/vô hiệu hóa")
    if re.search(r"(wrong password|incorrect|not correct|sai mật khẩu)", b, re.I):
        if shot:
            shot(page, email, "wrong_password")
        raise RuntimeError("sai mật khẩu")

    # ----- 3) 2FA (TOTP) nếu hỏi -----
    obox = _first_visible(page, OTP_SEL, 6000)
    if obox:
        code = totp_now(twofa_secret)
        if not code:
            if shot:
                shot(page, email, "need_2fa_no_secret")
            raise RuntimeError("cần 2FA nhưng không có secret TOTP")
        log(f"    nhập mã 2FA {code}")
        obox.fill(code)
        _click(page, CONTINUE_SEL, 6000)
        time.sleep(4)

    # ----- 4) Xác nhận: chờ về chatgpt.com -----
    try:
        page.wait_for_url("**chatgpt.com/**", timeout=15000)
    except Exception:  # noqa
        pass
    # còn màn hình phụ trên auth (passkey / "tiếp tục") -> bỏ qua
    if "auth.openai.com" in (page.url or ""):
        _click(page, ['button:has-text("Not now")', 'button:has-text("Để sau")',
                      'button:has-text("Skip")', 'button:has-text("Bỏ qua")',
                      'button:has-text("Tiếp tục")', 'button:has-text("Continue")'], 3000)
        time.sleep(2)
    # vào thẳng chatgpt.com để xác nhận
    try:
        page.goto(config.CHATGPT_URL, timeout=config.PAGE_TIMEOUT)
        time.sleep(3)
    except Exception:  # noqa
        pass
    if is_logged_in(page):
        return True
    heads = ""
    try:
        heads = " | ".join(page.eval_on_selector_all(
            "h1,h2", "e=>e.map(x=>x.innerText.trim()).filter(Boolean)")[:3])
    except Exception:  # noqa
        pass
    if shot:
        shot(page, email, "challenge")
    raise RuntimeError(f"chưa xác nhận đăng nhập (thử thách?): {heads or _body(page)[:60]}")
