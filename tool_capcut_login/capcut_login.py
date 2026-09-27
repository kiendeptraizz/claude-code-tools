# -*- coding: utf-8 -*-
"""Đăng nhập CapCut (email + mật khẩu) bằng Playwright trên browser GPM.
Luồng: capcut.com/login -> (chọn đăng nhập bằng email) -> email -> mật khẩu -> đăng nhập.
Lưu ý: CapCut (ByteDance) hay hiện CAPTCHA SLIDER trên thiết bị/proxy lạ.
"""
import re
import time

import pyotp
import config

EMAIL_SEL = ['input[name="username"]', 'input[type="email"]', 'input[name="email"]',
             'input[placeholder*="mail" i]', 'input[aria-label*="mail" i]',
             'input[type="text"]']
PASS_SEL = ['input[type="password"]', 'input[name="password"]',
            'input[placeholder*="assword" i]', 'input[placeholder*="mật khẩu" i]']
OTP_SEL = ['input[name="code"]', 'input[autocomplete="one-time-code"]',
           'input[inputmode="numeric"]', 'input[type="tel"]']
SIGNIN_SEL = ['button:has-text("Sign in")', 'button:has-text("Đăng nhập")',
              'button:has-text("Log in")', 'button:has-text("Continue")',
              'button:has-text("Tiếp tục")', 'button[type="submit"]']
# bước chọn phương thức "đăng nhập bằng email" (là <span>, phải click ĐÚNG element bằng exact-text)
EMAIL_TAB_SEL = [':text-is("Tiếp tục bằng email")', ':text-is("Continue with email")',
                 ':text-is("Sign in with email")', ':text-is("Đăng nhập bằng email")',
                 'span:has-text("Tiếp tục bằng email")', 'span:has-text("Continue with email")']


def totp_now(secret):
    secret = (secret or "").replace(" ", "").strip()
    if not secret:
        return ""
    try:
        return pyotp.TOTP(secret).now()
    except Exception:  # noqa
        return ""


def _body(page):
    try:
        return page.locator("body").inner_text(timeout=4000) or ""
    except Exception:  # noqa
        return ""


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
            try:
                el.click(force=True)
                return True
            except Exception:  # noqa
                pass
    return False


def has_captcha(page):
    b = _body(page)
    return bool(re.search(r"(Drag the|kéo|slide to|Slide|puzzle|xác minh|Verify to continue|security check)", b, re.I))


# trang chỉ vào được khi ĐÃ đăng nhập (capcut.com/ tự redirect sang đây nếu đã login)
AUTHED_URL = re.compile(r"/(my-edit|my-space|my-cloud|my-draft|workspace|cloud)")


def is_logged_in(page):
    """Đã login CapCut. Dấu hiệu CHẮC CHẮN = capcut.com tự redirect sang trang workspace
    (/my-edit ...). Mặc định CHƯA login nếu không có tín hiệu dương (tránh false-positive)."""
    url = page.url or ""
    if any(x in url for x in ("/login", "/signup", "/signin", "/sign-in")):
        return False
    if AUTHED_URL.search(url):
        return True
    if "capcut.com" not in url:
        return False
    # còn nút "Đăng nhập / Sign in" đang hiện -> chưa login
    for t in ("Đăng nhập", "Sign in", "Log in"):
        loc = page.get_by_text(t, exact=True)
        for i in range(min(loc.count(), 6)):
            try:
                if loc.nth(i).is_visible():
                    return False
            except Exception:  # noqa
                pass
    # tín hiệu dương phụ: avatar người dùng ở header
    try:
        av = page.locator('header [class*="avatar" i], [class*="header" i] [class*="avatar" i]')
        for i in range(min(av.count(), 6)):
            if av.nth(i).is_visible():
                return True
    except Exception:  # noqa
        pass
    return False


def open_plan_modal(page, log=print):
    """Mở bảng giá 'Choose your plan' (bấm nút Upgrade trên my-edit). Trả True nếu mở được."""
    try:
        page.goto("https://www.capcut.com/my-edit", timeout=config.PAGE_TIMEOUT)
    except Exception:  # noqa
        pass
    time.sleep(4)
    for _ in range(2):
        # nút Upgrade là <div class="LvHeaderUpgradeVipNew"> — click bằng JS (bị lớp header chặn click thường)
        try:
            page.eval_on_selector('.LvHeaderUpgradeVipNew', 'e=>e.click()')
        except Exception:  # noqa
            _click(page, ['[class*="upgrade" i]', ':text-is("Upgrade")', ':text-is("Nâng cấp")',
                          'button:has-text("Upgrade")'], 4000)
        # chờ modal
        for _ in range(10):
            try:
                if re.search(r"Choose your plan|Chọn gói", page.locator("body").inner_text(timeout=3000), re.I):
                    return True
            except Exception:  # noqa
                pass
            time.sleep(1)
    return False


_PCT_RE = re.compile(r"up to\s*(\d+)\s*%\s*off|(\d+)\s*%\s*off", re.I)
_TRIAL_RE = re.compile(r"for\s+(\d+)\s+days?|for the first month|tháng đầu|dùng thử|free trial", re.I)


def check_offer(page, log=print, shot=None):
    """Kiểm tra acc có ƯU ĐÃI (giảm giá / dùng thử) trên trang bảng giá không.
    Tín hiệu: giá gốc BỊ GẠCH (class *origin*) + 'for 7 days'/'first month'.
    Trả {has_offer, offer, detail}. LƯU Ý: kết quả phụ thuộc PROXY của profile."""
    if not open_plan_modal(page, log):
        if shot:
            shot(page, "offer", "no_modal")
        return {"has_offer": None, "offer": "không mở được bảng giá", "detail": ""}
    time.sleep(2)
    if shot:
        shot(page, "offer", "plan")
    body = ""
    try:
        body = page.locator("body").inner_text(timeout=4000)
    except Exception:  # noqa
        pass
    # giá gốc bị gạch = có giảm giá cho acc này
    origin = 0
    try:
        origin = page.locator('[class*="origin" i], del, s, [style*="line-through"]').count()
    except Exception:  # noqa
        pass
    m_pct = _PCT_RE.search(body)
    m_trial = _TRIAL_RE.search(body)
    # QUYẾT ĐỊNH dựa vào GIÁ GỐC BỊ GẠCH (chỉ có khi acc được giảm giá thật).
    # ('up to 80% off' là nhãn tab luôn hiện -> KHÔNG dùng để quyết định.)
    has_offer = origin > 0
    detail = []
    if origin > 0:
        detail.append(f"giá gốc bị gạch x{origin}")
    if m_trial:
        detail.append(m_trial.group(0))
    if m_pct:
        detail.append(m_pct.group(0))
    return {"has_offer": has_offer,
            "offer": ("CÓ ưu đãi" if has_offer else "KHÔNG ưu đãi"),
            "detail": " | ".join(detail)}


def login(page, email, password, twofa_secret="", log=print, shot=None):
    log("    mở trang login CapCut")
    page.goto(config.LOGIN_URL, timeout=config.PAGE_TIMEOUT)
    time.sleep(4)
    if is_logged_in(page):
        return True

    # nếu chưa thấy ô email -> có thể phải bấm "đăng nhập bằng email"
    if not _first_visible(page, EMAIL_SEL, 3000):
        _click(page, EMAIL_TAB_SEL, 4000)
        time.sleep(2)

    # ----- email -----
    ebox = _first_visible(page, EMAIL_SEL, 12000)
    if not ebox:
        if is_logged_in(page):
            return True
        if has_captcha(page) and shot:
            shot(page, email, "captcha_early")
        if shot:
            shot(page, email, "no_email_field")
        raise RuntimeError("không thấy ô email (trang lạ / captcha?)")
    log(f"    nhập email {email}")
    ebox.fill(email)

    # ----- mật khẩu (có thể cùng trang, hoặc bấm continue mới hiện) -----
    pbox = _first_visible(page, PASS_SEL, 3000)
    if not pbox:
        _click(page, SIGNIN_SEL, 5000)
        time.sleep(2)
        pbox = _first_visible(page, PASS_SEL, 10000)
    if not pbox:
        b = _body(page)
        if re.search(r"(no account|not registered|chưa đăng ký|không tồn tại|isn.t registered)", b, re.I):
            raise RuntimeError("email chưa đăng ký CapCut")
        if shot:
            shot(page, email, "no_password_field")
        raise RuntimeError("không tới được ô mật khẩu")
    log("    nhập mật khẩu")
    pbox.fill(password)
    _click(page, SIGNIN_SEL, 6000)
    time.sleep(5)

    b = _body(page)
    if re.search(r"(incorrect|wrong password|not correct|sai mật khẩu|mật khẩu không đúng|Incorrect email)", b, re.I):
        if shot:
            shot(page, email, "wrong_password")
        raise RuntimeError("sai email hoặc mật khẩu")

    # ----- 2FA nếu có -----
    obox = _first_visible(page, OTP_SEL, 4000)
    if obox and twofa_secret:
        code = totp_now(twofa_secret)
        log(f"    nhập mã 2FA {code}")
        obox.fill(code)
        _click(page, SIGNIN_SEL, 6000)
        time.sleep(4)

    # ----- xác nhận: capcut.com phải tự redirect sang trang workspace (/my-edit) -----
    for _ in range(3):
        page.goto(config.CAPCUT_URL, timeout=config.PAGE_TIMEOUT)
        try:
            page.wait_for_url(AUTHED_URL, timeout=8000)
        except Exception:  # noqa
            pass
        time.sleep(2)
        if is_logged_in(page):
            return True
    # không vào được -> có thể dính captcha ByteDance / sai thông tin
    if shot:
        shot(page, email, "verify_fail")
    cap = " (có thể dính CAPTCHA ByteDance — cần proxy tốt hơn)" if has_captcha(page) else ""
    raise RuntimeError("chưa xác nhận đăng nhập" + cap)
