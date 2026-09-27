# -*- coding: utf-8 -*-
"""Đăng nhập Google trong browser GPM (qua CDP). Tự sinh mã 2FA từ secret TOTP.
Selector đã dò đúng với UI Google 2026: email #identifierId (type=text),
mật khẩu input[name="Passwd"], 2FA input[name="totpPin"]."""
import re
import time

import pyotp


def totp_now(secret):
    """Sinh mã 6 số từ secret TOTP. Hỗ trợ secret có dấu cách / dạng otpauth://."""
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


def is_logged_in(page):
    """Đã đăng nhập = đang ở myaccount, hoặc KHÔNG còn ở trang signin/challenge."""
    url = page.url or ""
    if "myaccount.google.com" in url:
        return True
    if re.search(r"accounts\.google\.com/(v3/)?(signin|challenge|signup|speedbump)", url):
        return False
    # còn ô nhập email/pass => chưa xong
    try:
        if page.locator("#identifierId").count() and page.locator("#identifierId").first.is_visible():
            return False
    except Exception:  # noqa
        pass
    return True


def _click(page, selectors, timeout=4000):
    for sel in selectors:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=timeout)
            el.click()
            return True
        except Exception:  # noqa
            continue
    return False


def _body(page):
    try:
        return page.inner_text("body")
    except Exception:  # noqa
        return ""


def login(page, email, password, twofa_secret, log=print, shot=None):
    """Đăng nhập Google. Raise RuntimeError nếu lỗi/bị thử thách. Trả về True nếu xong."""
    # ----- 1) Email -----
    try:
        page.wait_for_selector("#identifierId", state="visible", timeout=15000)
    except Exception:  # noqa
        if is_logged_in(page):
            return True
        if shot:
            shot(page, email, "no_email_field")
        raise RuntimeError("không thấy ô email (trang lạ/đã đăng nhập?)")
    log(f"    nhập email {email}")
    page.fill("#identifierId", email)
    _click(page, ["#identifierNext", '#identifierNext button', 'button:has-text("Next")',
                  'button:has-text("Tiếp theo")'], 5000)

    # ----- 2) Mật khẩu (đợi ô Passwd hiện) -----
    try:
        page.wait_for_selector('input[name="Passwd"]', state="visible", timeout=20000)
    except Exception:  # noqa
        b = _body(page)
        if re.search(r"Couldn.t find your Google Account|Không tìm thấy", b, re.I):
            raise RuntimeError("email không tồn tại")
        if shot:
            shot(page, email, "no_password_page")
        raise RuntimeError("không tới được trang mật khẩu (email sai / bị chặn)")

    b = _body(page)
    if re.search(r"Too many failed attempts|Quá nhiều lần|try again later|thử lại sau", b, re.I):
        if shot:
            shot(page, email, "too_many_attempts")
        raise RuntimeError("acc bị Google tạm khóa (too many failed attempts) — chờ rồi thử lại")

    log("    nhập mật khẩu")
    page.fill('input[name="Passwd"]', password)
    time.sleep(0.4)
    _click(page, ["#passwordNext", '#passwordNext button', 'button:has-text("Next")',
                  'button:has-text("Tiếp theo")'], 5000)
    time.sleep(4)

    b = _body(page)
    if re.search(r"Wrong password|mật khẩu.*không đúng|incorrect password", b, re.I):
        if shot:
            shot(page, email, "wrong_password")
        raise RuntimeError("sai mật khẩu")
    if re.search(r"Too many failed attempts|try again later|thử lại sau", b, re.I):
        if shot:
            shot(page, email, "too_many_attempts")
        raise RuntimeError("acc bị Google tạm khóa (too many failed attempts)")

    # ----- 3) 2FA (TOTP) nếu được hỏi -----
    try:
        page.wait_for_selector('input[name="totpPin"], input[type="tel"]', state="visible", timeout=8000)
        code = totp_now(twofa_secret)
        if not code:
            if shot:
                shot(page, email, "need_2fa_no_secret")
            raise RuntimeError("cần mã 2FA nhưng không có secret TOTP")
        log(f"    nhập mã 2FA {code}")
        for sel in ['input[name="totpPin"]', 'input[type="tel"]']:
            try:
                el = page.locator(sel).first
                if el.is_visible():
                    el.fill(code)
                    break
            except Exception:  # noqa
                continue
        _click(page, ["#totpNext", '#totpNext button', 'button:has-text("Next")',
                      'button:has-text("Tiếp theo")'], 5000)
        time.sleep(4)
    except RuntimeError:
        raise
    except Exception:  # noqa
        pass  # không có bước 2FA (đăng nhập 1 lớp) hoặc đã qua

    # ----- 4) Bỏ qua các lời mời sau đăng nhập -----
    _click(page, ['button:has-text("Not now")', 'button:has-text("Để sau")',
                  'button:has-text("Skip")', 'button:has-text("Bỏ qua")',
                  'button:has-text("Confirm")'], 3000)
    time.sleep(2)

    # ----- 5) Xác nhận / báo thử thách -----
    if is_logged_in(page):
        return True
    b = _body(page)
    heads = ""
    try:
        heads = " | ".join(page.eval_on_selector_all("h1,h2", "e=>e.map(x=>x.innerText.trim()).filter(Boolean)")[:3])
    except Exception:  # noqa
        pass
    if shot:
        shot(page, email, "challenge")
    raise RuntimeError(f"Google đòi xác minh thêm (không tự qua được): {heads or b[:60]}")
