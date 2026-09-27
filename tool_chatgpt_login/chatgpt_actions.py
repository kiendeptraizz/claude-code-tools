# -*- coding: utf-8 -*-
"""Các thao tác trên tài khoản ChatGPT (OpenAI) sau khi đã đăng nhập:
- change_password: đổi mật khẩu (re-auth -> form pass mới)
- logout_all: đăng xuất tất cả phiên
- reset_2fa: thay mã 2FA (tắt cũ -> bật lại -> lấy secret MỚI)

Điều hướng bằng URL hash trực tiếp (ổn định hơn click menu):
  #settings/Security                     (mật khẩu / 2FA)
  #settings/Security/active-sessions     (phiên đăng nhập)
"""
import re
import time

import config
import chatgpt_login as cg

SEC_URL = "https://chatgpt.com/#settings/Security"
SESS_URL = "https://chatgpt.com/#settings/Security/active-sessions"
BILLING_URL = "https://chatgpt.com/#settings/Billing"
DATA_URL = "https://chatgpt.com/#settings/DataControls"
ACCOUNT_URL = "https://chatgpt.com/#settings/Account"


def _goto_safe(page, url, tries=3):
    """goto BỀN với điều hướng chen ngang: sau vài thao tác (vd HỦY GÓI) OpenAI tự redirect
    (?refresh_account=true...) làm goto bị 'interrupted by another navigation' hoặc timeout.
    Chờ redirect kia xong rồi thử lại."""
    for k in range(tries):
        try:
            page.goto(url, timeout=config.PAGE_TIMEOUT)
            return True
        except Exception as e:  # noqa
            msg = str(e).lower()
            if any(s in msg for s in ("interrupted", "another navigation", "timeout", "navigation")):
                time.sleep(2.5)   # để cú redirect kia hoàn tất rồi mở lại
                continue
            time.sleep(1)
    return False


def _settings_ready(page):
    """Modal settings đã RENDER THẬT (có tablist/tab), không chỉ [role=dialog] rỗng."""
    try:
        return page.locator('[data-testid$="-tab"], [role="dialog"] [role="tablist"]').count() > 0
    except Exception:  # noqa
        return False


def _open(page, url, tries=2):
    """Mở modal cài đặt CHẮC CHẮN: về trang gốc rồi mở URL #hash (hashchange kích hoạt modal).
    Chờ modal RENDER THẬT (có tab) — tránh bấm khi nội dung chưa load (gây 'không thấy nút').
    Thử lại mở nếu modal chưa render sau lần đầu."""
    settings = "#settings" in url
    for attempt in range(tries):
        if settings:
            _goto_safe(page, "https://chatgpt.com/")
            time.sleep(1.5)
        _goto_safe(page, url)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:  # noqa
            pass
        time.sleep(1.5)
        if not settings:
            return
        # chờ tab settings render thật (~12s)
        ok = False
        for _ in range(8):
            if _settings_ready(page):
                ok = True
                break
            time.sleep(1.5)
        if ok:
            time.sleep(1)   # để nội dung tab kịp vẽ
            return
        # chưa render -> thử mở lại (attempt sau)
    # hết lượt: trả về dù chưa chắc render (action sẽ tự báo lỗi nếu không thấy nút)


_WRONG_PW_RE = re.compile(r"(incorrect email address or password|sai mật khẩu|mật khẩu không đúng|"
                          r"không chính xác|wrong password)", re.I)
# Trang xác minh của OpenAI là Remix/React — submit TRƯỚC khi JS hydrate xong → form gửi kiểu điều
# hướng native → server trả '(400) Invalid content type: text/html' (Route Error). KHÔNG phải sai pass.
_ROUTE_ERR_RE = re.compile(r"(route error|invalid content type|lỗi không xác định)", re.I)


def _reauth_try(page, acc, pwd, log=print):
    """Xác minh danh tính với mật khẩu `pwd` để đổi pass. OpenAI (7/2026) có thể hỏi MẬT KHẨU
    HIỆN TẠI TỚI 2 LẦN (modal 'xác minh danh tính' trong chatgpt.com + trang auth.openai.com)
    rồi OTP. Vòng lặp xử lý; trả:
      'reached'      = đã tới form đặt mật khẩu MỚI (re-auth OK)
      'wrong'        = pwd SAI ('Incorrect email address or password')
      'email_verify' = OpenAI đòi xác minh EMAIL (phiên cũ/acc rủi ro) — tool không đọc được email
      'stuck'        = kẹt khác."""
    try:
        page.wait_for_selector('input[name="current-password"]', timeout=15000, state="visible")
    except Exception:  # noqa
        pass
    # CHỜ TRANG XÁC MINH (Remix) HYDRATE trước khi submit: bấm 'Tiếp tục' quá sớm → form gửi kiểu
    # điều hướng native → OpenAI trả 'Route Error 400 Invalid content type' (KHÔNG phải sai pass).
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:  # noqa
        pass
    time.sleep(5)   # để Remix hydrate xong (3s đôi khi hụt → Route Error); nhánh dưới vẫn retry nếu lỡ
    pass_n = otp_n = route_n = 0
    for _ in range(14):
        # tới form đặt MẬT KHẨU MỚI -> re-auth xong
        try:
            np = page.locator('input[name="new-password"]')
            if np.count() and np.first.is_visible():
                return "reached"
        except Exception:  # noqa
            pass
        # OpenAI đòi XÁC MINH EMAIL (hay gặp khi phiên CŨ) -> tool không đọc được email -> báo riêng
        if "email-verification" in (page.url or ""):
            return "email_verify"
        # Route Error (submit trước hydrate) -> bấm 'Thử lại' + chờ hydrate rồi nhập lại (KHÔNG phải wrong)
        try:
            if route_n < 3 and _ROUTE_ERR_RE.search(page.inner_text("body") or ""):
                log("    → Route Error (submit sớm) → 'Thử lại' + chờ hydrate, nhập lại")
                cg._click(page, ['button:has-text("Thử lại")', 'button:has-text("Try again")'], 5000)
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:  # noqa
                    pass
                time.sleep(3)
                pass_n = 0
                route_n += 1
                continue
        except Exception:  # noqa
            pass
        # đã nhập pwd rồi mà báo SAI -> dừng NGAY (tránh thử nhiều lần bị OpenAI khóa).
        # CHỈ coi là sai pass khi VẪN ở màn nhập mật khẩu (còn ô current-password) — tránh bắt nhầm
        # text 'incorrect' còn sót lại sau khi ĐÃ qua bước pass (đang ở OTP / new-password).
        if pass_n >= 1:
            try:
                if _WRONG_PW_RE.search(page.inner_text("body") or "") and _vis(page, 'input[name="current-password"]'):
                    return "wrong"
            except Exception:  # noqa
                pass
        # ô MẬT KHẨU HIỆN TẠI (có thể xuất hiện 1-2 lần)
        cp = _vis(page, 'input[name="current-password"]')
        if cp and pass_n < 2:
            log(f"    → nhập mật khẩu hiện tại (lần {pass_n+1})")
            try:
                cp.fill("")
                cp.fill(pwd)
            except Exception:  # noqa
                pass
            cg._click(page, cg.CONTINUE_SEL, 5000)
            pass_n += 1
            time.sleep(3)
            continue
        # ô OTP (mfa-challenge)
        o = None
        for s in cg.OTP_SEL:
            o = _vis(page, s)
            if o:
                break
        if o and otp_n < 2:
            code = cg.totp_now(acc["twofa"])
            if code:
                log(f"    → nhập OTP {code}")
                try:
                    o.fill(code)
                except Exception:  # noqa
                    pass
                cg._click(page, cg.CONTINUE_SEL, 5000)
                otp_n += 1
                time.sleep(3)
                continue
        time.sleep(1.5)
    if "email-verification" in (page.url or ""):
        return "email_verify"
    try:
        if _WRONG_PW_RE.search(page.inner_text("body") or "") and _vis(page, 'input[name="current-password"]'):
            return "wrong"
    except Exception:  # noqa
        pass
    return "stuck"


def _dump(page, tag, log):
    """In các input/nút đang hiện để học selector khi flow lạ."""
    try:
        log(f"    [dump {tag}] url={page.url}")
        for el in page.locator("input").all()[:12]:
            try:
                if el.is_visible():
                    log("      input name=%r type=%r ph=%r" % (
                        el.get_attribute("name"), el.get_attribute("type"),
                        el.get_attribute("placeholder")))
            except Exception:  # noqa
                pass
        for b in page.locator("button").all()[:20]:
            try:
                if b.is_visible():
                    t = (b.inner_text() or "").strip().replace("\n", " ")
                    if t:
                        log("      button %r" % t[:40])
            except Exception:  # noqa
                pass
    except Exception as e:  # noqa
        log(f"    [dump {tag}] loi {e}")


# ==================== RESET 2FA (thay mã 2FA) ====================
# Cảnh báo: OpenAI chống tự động hóa Ở BƯỚC TẮT 2FA (đã từng bị chặn nhiều lần).
# Chiến lược: tắt 2FA cũ (re-auth pass + OTP cũ) -> kiểm tra toggle đã OFF ->
# bật lại -> đọc secret base32 MỚI -> tự sinh mã xác nhận -> trả secret mới.
# Nếu toggle KHÔNG chịu OFF (OpenAI chặn) -> raise để main BỎ QUA, chạy tiếp acc khác.

_B32_ONLY = re.compile(r'^[A-Z2-7]+$')


def _switch_state(sw):
    """True nếu toggle đang BẬT (aria-checked='true' hoặc data-state='checked')."""
    try:
        if (sw.get_attribute("aria-checked") or "").lower() == "true":
            return True
        if (sw.get_attribute("data-state") or "").lower() == "checked":
            return True
    except Exception:  # noqa
        pass
    return False


def _auth_switch(page):
    """Tìm toggle 'Authenticator app' (2FA) trong trang Security.
    Trả (locator, is_on) hoặc (None, None). Ưu tiên data-testid ổn định, sau đó dò text quanh switch."""
    # fast-path: testid ổn định của OpenAI
    try:
        t = page.locator('button[data-testid="mfa-authenticator-toggle"]')
        if t.count() and t.first.is_visible():
            return t.first, _switch_state(t.first)
    except Exception:  # noqa
        pass
    try:
        sws = page.locator('[role="switch"], button[aria-checked]')
        n = min(sws.count(), 12)
    except Exception:  # noqa
        return None, None
    visible = []
    for i in range(n):
        sw = sws.nth(i)
        try:
            if not sw.is_visible():
                continue
        except Exception:  # noqa
            continue
        visible.append(sw)
        # đọc text vùng cha (tối đa vài cấp) để nhận diện 'Authenticator'
        around = ""
        try:
            around = sw.evaluate(
                "el => { let p = el; for (let k=0;k<5 && p;k++){ p = p.parentElement; "
                "if (p && p.innerText && p.innerText.trim().length>3) return p.innerText; } return ''; }") or ""
        except Exception:  # noqa
            pass
        if re.search(r"(authenticator|xác thực|two[- ]?factor|đa yếu tố|multi[- ]?factor|\bmfa\b|totp|ứng dụng)",
                     around, re.I):
            return sw, _switch_state(sw)
    # fallback: chỉ có đúng 1 switch hiện trên trang Security -> nhiều khả năng là nó
    if len(visible) == 1:
        return visible[0], _switch_state(visible[0])
    return None, None


def _grab_secret(page):
    """Đọc secret base32 khi OpenAI hiện màn 'thêm authenticator' (QR + mã thủ công)."""
    # 1) otpauth://...secret=XXXX nằm đâu đó trong DOM (QR hay encode URI này)
    try:
        html = page.content()
    except Exception:  # noqa
        html = ""
    m = re.search(r'otpauth://totp/[^\s"\'<>]+', html or "")
    if m:
        ms = re.search(r'secret=([A-Za-z0-9]+)', m.group(0), re.I)
        if ms:
            return ms.group(1).upper()
    # 2) ô readonly / code / phần tử có class|testid chứa 'secret'
    for sel in ('input[readonly]', 'code', 'pre', '[data-testid*="secret" i]',
                '[class*="secret" i]', '[aria-label*="secret" i]'):
        try:
            for el in page.locator(sel).all()[:8]:
                raw = (el.get_attribute("value") or "")
                if not raw:
                    try:
                        raw = el.inner_text()
                    except Exception:  # noqa
                        raw = ""
                v = re.sub(r'[\s-]', '', raw or "").upper()
                if 16 <= len(v) <= 64 and _B32_ONLY.match(v):
                    return v
        except Exception:  # noqa
            pass
    # 3) quét text hiện trên trang: cụm base32 dài (đề phòng secret in dạng các nhóm cách nhau)
    try:
        txt = page.inner_text("body")
    except Exception:  # noqa
        txt = ""
    joined = re.sub(r'[\s-]', '', txt or "").upper()
    m = re.search(r'[A-Z2-7]{16,64}', joined)
    if m:
        return m.group(0)
    return None


def _reveal_manual(page):
    """Bấm 'Nhập thủ công' / 'Không quét được QR' để lộ secret text (nếu có nút đó)."""
    cg._click(page, ['button:has-text("Nhập thủ công")', 'button:has-text("nhập mã")',
                     'button:has-text("thủ công")', 'a:has-text("thủ công")',
                     'button:has-text("Enter manually")', 'button:has-text("Enter code manually")',
                     "button:has-text(\"Can't scan\")", 'button:has-text("Không quét được")',
                     'a:has-text("manually")', 'button:has-text("Setup key")',
                     'button:has-text("mã thiết lập")'], 2000)
    time.sleep(1)


# Ô nhập mã 6 số khi ĐĂNG KÝ authenticator (khác OTP lúc login: name='totp_otp', type=text).
_TOTP_ENROLL_SEL = ['input[name="totp_otp"]',
                    '[aria-labelledby="enroll-totp-modal-title"] input[type="text"]',
                    'input[placeholder*="6 chữ số"]', 'input[placeholder*="6 chữ"]',
                    'input[placeholder*="6-digit"]']

# Click nút trong hộp thoại theo TEXT bằng JS (bền hơn :has-text khi trang đang điều hướng;
# chọn phần tử clickable có innerText ĐÚNG BẰNG target, nhỏ/sâu nhất). Trả text đã click hoặc None.
_JS_CLICK_DIALOG = r"""
(targets) => {
  const dlgs = [...document.querySelectorAll('[role=dialog],[role=alertdialog]')];
  for (const d of dlgs) {
    const els = [...d.querySelectorAll('button,[role=button],a')];
    let best=null, bestLen=1e9;
    for (const e of els) {
      const t=(e.innerText||'').trim();
      if (targets.includes(t) && e.getClientRects().length>0 && t.length<bestLen){best=e;bestLen=t.length;}
    }
    if (best){ best.click(); return best.innerText.trim(); }
  }
  return null;
}
"""


def _click_dialog_btn(page, texts):
    try:
        return page.evaluate(_JS_CLICK_DIALOG, texts)
    except Exception:  # noqa
        return None


def _vis(page, sel):
    """locator đầu tiên đang HIỂN THỊ cho selector (không chờ), hoặc None."""
    try:
        loc = page.locator(sel)
        if loc.count() and loc.first.is_visible():
            return loc.first
    except Exception:  # noqa
        pass
    return None


def _disable_2fa(page, acc, sw, log=print, shot=None):
    """Tắt 2FA: click toggle OFF rồi xử lý theo TRÌNH TỰ OpenAI đưa ra (thứ tự có thể đổi tùy lúc):
    hộp xác nhận 'Xóa' + re-auth (pass hiện tại + OTP CŨ). Vòng lặp state-machine, mỗi trạng
    thái xuất hiện thì xử lý ngay. OpenAI (7/2026) hiện hộp 'Xóa ứng dụng xác thực' NGAY sau khi
    gạt toggle, bấm 'Xóa' xong mới hỏi lại pass/OTP."""
    try:
        sw.click()
    except Exception:  # noqa
        try:
            sw.evaluate("el => el.click()")
        except Exception:  # noqa
            pass
    time.sleep(2)
    pass_used = otp_used = confirmed = False
    idle = 0
    for k in range(40):
        acted = False
        # a) hộp xác nhận 'Xóa' (JS click theo text — bền, không treo khi đang điều hướng)
        r = _click_dialog_btn(page, ["Xóa", "Remove", "Delete", "Disable", "Vô hiệu hóa"])
        if r:
            log(f"    → xác nhận '{r}' (vòng {k})")
            confirmed = True
            acted = True
            time.sleep(3)
        # b) ô mật khẩu hiện tại (re-auth) — hay đến TRƯỚC hộp 'Xóa' khi phiên cũ
        if not acted:
            cp = _vis(page, 'input[name="current-password"]')
            if cp and not pass_used:
                log("    → nhập mật khẩu (re-auth)")
                try:
                    cp.fill(acc["pass"])
                except Exception:  # noqa
                    pass
                cg._click(page, cg.CONTINUE_SEL, 4000)
                pass_used = True
                acted = True
                time.sleep(3)
        # c) ô OTP — dùng secret CŨ
        if not acted and not otp_used:
            o = None
            for s in cg.OTP_SEL:
                o = _vis(page, s)
                if o:
                    break
            if o:
                code = cg.totp_now(acc["twofa"])
                if code:
                    log(f"    → nhập OTP cũ {code}")
                    try:
                        o.fill(code)
                    except Exception:  # noqa
                        pass
                    cg._click(page, cg.CONTINUE_SEL, 4000)
                    otp_used = True
                    acted = True
                    time.sleep(3)
        if acted:
            idle = 0
            continue
        if confirmed:            # đã bấm 'Xóa' + không còn bước nào -> xong
            idle += 1
            if idle >= 3:
                break
        time.sleep(1)
    if not confirmed:
        log("    (không bấm được xác nhận 'Xóa' — có thể bị chặn)")
    time.sleep(2)


def _find_enroll_box(page):
    """Ô nhập mã 6 số của modal đăng ký authenticator (không chờ)."""
    for s in _TOTP_ENROLL_SEL + cg.OTP_SEL:
        o = _vis(page, s)
        if o:
            return o
    return None


def _enable_2fa(page, acc, log=print, shot=None):
    """Bật 2FA mới: gạt toggle ON -> (reauth nếu bị hỏi) -> đọc secret từ otpauth trong DOM
    -> sinh mã -> điền ô 'totp_otp' -> Xác minh (retry 1 lần nếu mã hết hạn).
    Trả secret base32 MỚI (str) hoặc None."""
    sw, on = _auth_switch(page)
    if sw is not None and not on:
        try:
            sw.click()
        except Exception:  # noqa
            try:
                sw.evaluate("el => el.click()")
            except Exception:  # noqa
                pass
    else:
        cg._click(page, ['button:has-text("Bật")', 'button:has-text("Enable")',
                         'button:has-text("Thêm")', 'button:has-text("Set up")',
                         'button:has-text("Thiết lập")', 'button:has-text("Add")'], 4000)
    time.sleep(3)
    # đọc secret (otpauth trong DOM) + xử lý reauth pass nếu bị hỏi — vòng lặp ngắn, không treo
    secret = None
    pass_used = False
    for _ in range(20):
        # OpenAI đòi XÁC MINH EMAIL trước khi bật (hay gặp khi phiên "cũ") -> tool không đọc được email acc
        if "email-verification" in (page.url or ""):
            if shot:
                shot(page, "2fa", "email_verify")
            raise RuntimeError("OpenAI đòi xác minh EMAIL khi bật 2FA (tool không đọc được email acc này) "
                               "— thử chạy lại ngay sau khi login để phiên còn 'tươi'")
        cp = _vis(page, 'input[name="current-password"]')
        if cp and not pass_used:
            log("    → reauth: nhập mật khẩu")
            try:
                cp.fill(acc["pass"])
            except Exception:  # noqa
                pass
            cg._click(page, cg.CONTINUE_SEL, 4000)
            pass_used = True
            time.sleep(3)
            continue
        secret = _grab_secret(page)
        if secret:
            break
        time.sleep(1)
    if not secret:
        if shot:
            shot(page, "2fa", "no_secret")
        _dump(page, "enable_2fa", log)
        return None
    log(f"    đọc secret mới: {secret}")
    # nhập mã xác nhận (sinh MỚI mỗi lần thử để tránh mã hết hạn giữa chừng)
    verify_btns = ['button:has-text("Xác minh")', 'button:has-text("Verify")'] + cg.CONTINUE_SEL + \
                  ['button:has-text("Kích hoạt")', 'button:has-text("Activate")']
    for attempt in range(2):
        o = _find_enroll_box(page)
        if not o:
            if attempt == 0:
                if shot:
                    shot(page, "2fa", "no_codebox")
                _dump(page, "enable_codebox", log)
                return None
            break  # attempt 2: không còn ô -> đã chấp nhận
        code = cg.totp_now(secret)
        log(f"    nhập mã xác nhận {code} (lần {attempt+1})")
        try:
            o.fill("")
            o.fill(code)
        except Exception:  # noqa
            pass
        cg._click(page, verify_btns, 5000)
        time.sleep(3)
        if not _find_enroll_box(page):   # ô biến mất -> mã được chấp nhận
            break
        log("    mã chưa được chấp nhận, thử lại...")
    # màn 'mã khôi phục' / 'xong' -> lưu/đóng để hoàn tất
    cg._click(page, ['button:has-text("Tôi đã lưu")', 'button:has-text("I saved")',
                     'button:has-text("Tiếp tục")', 'button:has-text("Continue")',
                     'button:has-text("Xong")', 'button:has-text("Done")',
                     'button:has-text("Đóng")', 'button:has-text("Close")'], 3000)
    time.sleep(2)
    return secret


def reset_2fa(page, acc, log=print, shot=None):
    """Thay mã 2FA: tắt 2FA cũ -> bật lại -> lấy secret MỚI. Trả secret mới (str).
    ⚠️ Bước TẮT từng bị OpenAI chặn (chống bot). Nếu toggle không chịu OFF -> raise
    (main sẽ BỎ QUA thao tác này và chạy tiếp acc khác)."""
    _open(page, SEC_URL)
    sw, on = _auth_switch(page)
    if sw is None:
        if shot:
            shot(page, "2fa", "no_switch")
        _dump(page, "sec_2fa", log)
        raise RuntimeError("không thấy toggle Authenticator (2FA) trong Security")

    if on:
        log("    2FA đang BẬT → tắt trước khi thay")
        _disable_2fa(page, acc, sw, log, shot)
        _open(page, SEC_URL)               # mở lại để đọc trạng thái mới
        sw, on = _auth_switch(page)
        if on:
            if shot:
                shot(page, "2fa", "still_on")
            raise RuntimeError("OpenAI chặn TẮT 2FA (toggle vẫn bật sau pass+OTP) — bỏ qua acc này")
        log("    ✅ đã tắt 2FA cũ")
    else:
        log("    2FA đang TẮT → bật mã mới luôn")

    new_secret = _enable_2fa(page, acc, log, shot)
    if not new_secret:
        raise RuntimeError("bật lại 2FA nhưng không đọc được secret mới")
    # XÁC NHẬN đã bật thật sự (nếu chưa BẬT -> mã xác minh thất bại -> KHÔNG báo secret giả)
    _open(page, SEC_URL)
    _sw2, on2 = _auth_switch(page)
    if not on2:
        if shot:
            shot(page, "2fa", "enable_failed")
        raise RuntimeError(f"đã nhập secret mới ({new_secret}) nhưng 2FA CHƯA bật (xác minh mã thất bại)")
    log(f"    ✅ 2FA MỚI: {new_secret}")
    if shot:
        shot(page, "2fa", "done")
    return new_secret


_JS_CLICK_MATKHAU = r"""
() => {
  // ưu tiên testid ổn định; nếu không, nút có text BẮT ĐẦU bằng 'Mật khẩu'
  // (KHÔNG khớp 'Khóa bảo mật & khóa truy cập' = passkeys).
  let el = document.querySelector('[data-testid="password-setting"]');
  if (!el) {
    el = [...document.querySelectorAll('[role=dialog] button, button, [role=button]')]
      .find(b => (b.innerText||'').trim().toLowerCase().startsWith('mật khẩu')
              || (b.innerText||'').trim().toLowerCase().startsWith('password'));
  }
  if (el && el.getClientRects().length) { el.click(); return true; }
  return false;
}
"""


def _click_matkhau(page):
    """Bấm mục 'Mật khẩu' (đổi pass) trong Security. CHỈ khớp testid password-setting HOẶC nút có
    text bắt đầu bằng 'Mật khẩu' — tránh bấm nhầm 'Khóa bảo mật & khóa truy cập' (passkeys).
    Trả False nếu acc KHÔNG có mục Mật khẩu (đăng nhập Google/SSO...). Thử vài lần vì load chậm.
    (Acc bật 'Chế độ nhà phát triển' đẩy mục Mật khẩu xuống/ẩn → dùng ô 'Tìm kiếm cài đặt' render trước.)"""
    for i in range(5):
        try:
            if page.evaluate(_JS_CLICK_MATKHAU):
                return True
        except Exception:  # noqa
            pass
        # sau vài lần không thấy: gõ 'mật khẩu' vào ô tìm kiếm cài đặt để render mục (rồi thử lại)
        if i == 1:
            try:
                s = page.locator('input[name="settings-search"]').first
                if s.count() and s.is_visible():
                    s.click(); s.fill(""); s.type("mật khẩu", delay=25); time.sleep(1.2)
                    page.keyboard.press("Escape")
            except Exception:  # noqa
                pass
        time.sleep(1.5)
    return False


def change_password(page, acc, new_password, log=print, shot=None):
    """Đổi mật khẩu: #settings/Security -> 'Mật khẩu' -> re-auth (pass HIỆN TẠI + 2FA) -> form pass mới.
    Nếu pass hiện tại (dòng acc) SAI: thử MẬT KHẨU ĐÍCH (acc có thể đã đổi ở lần trước) — nếu đúng
    thì coi như đã đổi rồi; nếu vẫn sai -> báo rõ 'SAI MẬT KHẨU HIỆN TẠI'."""
    _open(page, SEC_URL)
    if not _click_matkhau(page):
        if shot:
            shot(page, "pass", "no_mkbtn")
        _dump(page, "pass_no_mkbtn", log)
        raise RuntimeError("acc KHÔNG có mục 'Mật khẩu' trong Bảo mật (thường do đăng nhập qua "
                           "Google/SSO, hoặc chưa đặt mật khẩu OpenAI) → không đổi pass qua web được")
    time.sleep(4)
    # re-auth với pass HIỆN TẠI (dòng acc)
    st = _reauth_try(page, acc, acc["pass"], log)
    # OpenAI đòi XÁC MINH EMAIL (phiên cũ/acc rủi ro) -> KHÔNG đổi pass được (tool không đọc email)
    if st == "email_verify":
        if shot:
            shot(page, "pass", "email_verify")
        raise RuntimeError("OpenAI đòi XÁC MINH EMAIL khi đổi pass (phiên cũ / acc rủi ro) — pass HIỆN "
                           "TẠI vẫn ĐÚNG nhưng tool không đọc được email acc nên không đổi được. Mẹo: "
                           "chạy đổi pass NGAY sau khi login (phiên tươi) sẽ ít bị đòi email hơn.")
    # pass hiện tại SAI -> thử MẬT KHẨU ĐÍCH (acc có thể đã đổi thành công ở lần chạy trước)
    if st == "wrong" and new_password and new_password != acc["pass"]:
        log("    ⚠️ mật khẩu hiện tại SAI → thử với MẬT KHẨU ĐÍCH (acc có thể đã đổi trước đó)")
        _open(page, SEC_URL)
        if _click_matkhau(page):
            time.sleep(4)
            if _reauth_try(page, acc, new_password, log) == "reached":
                log("    ✅ mật khẩu ĐÃ là mật khẩu đích (đã đổi ở lần trước) — cập nhật dòng")
                acc["pass"] = new_password
                return True     # đã ở mật khẩu đích rồi, không cần đặt lại
            st = "wrong"
    if st == "wrong":
        if shot:
            shot(page, "pass", "wrong_current")
        raise RuntimeError("SAI MẬT KHẨU HIỆN TẠI — dòng acc dùng pass CŨ? (acc có thể đã đổi pass "
                           "trước đó). Hãy dùng dòng kết quả MỚI NHẤT của acc.")
    if st != "reached":
        if shot:
            shot(page, "pass", "reauth_stuck")
        _dump(page, "newpass_form", log)
        raise RuntimeError("không tới form mật khẩu mới (re-auth chưa qua)")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)   # form new-password hydrate xong mới điền
    except Exception:  # noqa
        pass
    time.sleep(2)
    _dump(page, "newpass_form", log)
    # điền mật khẩu MỚI: ưu tiên ô new/confirm; nếu không, mọi ô password KHÁC current-password
    filled = 0
    for sel in ['input[name="new-password"]', 'input[name="confirm-password"]',
                'input[name="password"]']:
        for el in page.locator(sel).all():
            try:
                if el.is_visible():
                    el.fill(new_password)
                    filled += 1
            except Exception:  # noqa
                pass
    if filled == 0:  # fallback: ô password hiện, bỏ current-password
        for el in page.locator('input[type="password"]').all():
            try:
                if el.is_visible() and el.get_attribute("name") != "current-password":
                    el.fill(new_password)
                    filled += 1
            except Exception:  # noqa
                pass
    log(f"    da dien {filled} o password moi")
    if filled == 0:
        if shot:
            shot(page, "pass", "no_newform")
        raise RuntimeError("không thấy form mật khẩu mới (re-auth có thể chưa qua)")
    cg._click(page, cg.CONTINUE_SEL + ['button:has-text("Lưu")', 'button:has-text("Save")',
                                       'button:has-text("Cập nhật")', 'button:has-text("Update")',
                                       'button:has-text("Đổi mật khẩu")'], 6000)
    time.sleep(4)
    # sau khi đặt pass mới, OpenAI thường đòi 2FA lần cuối (mfa-challenge)
    o = cg._first_visible(page, cg.OTP_SEL, 8000)
    if o:
        log("    xac minh 2FA sau doi pass...")
        o.fill(cg.totp_now(acc["twofa"]))
        cg._click(page, cg.CONTINUE_SEL, 6000)
        time.sleep(4)
    log(f"    URL cuoi: {page.url}")
    if shot:
        shot(page, "pass", "done")
    return True


# testid ổn định (đã xác minh trên acc sống) đứng ĐẦU; còn lại là dự phòng theo text.
_LOGOUT_ALL_BTN = ['[data-testid="logout-all-button"]',
                   'button:has-text("Đăng xuất tất cả")', 'button:has-text("Đăng xuất khỏi tất cả")',
                   'button:has-text("Đăng xuất tất cả thiết bị")', 'button:has-text("Log out all")',
                   'button:has-text("Log out of all")', 'button:has-text("Sign out all")',
                   'button:has-text("Log out all devices")']


def _pass_otp_if_asked(page, acc, log=print):
    """Điền mật khẩu hiện tại + OTP nếu OpenAI hỏi RE-AUTH (thao tác nhạy cảm hay bắt xác minh lại).
    Không thấy ô nào thì thôi. Cần acc (có 'pass'/'twofa')."""
    if not acc:
        return
    for _ in range(6):
        cp = _vis(page, 'input[name="current-password"]')
        if cp:
            log("    → (re-auth) nhập mật khẩu hiện tại")
            try:
                cp.fill(acc.get("pass", ""))
            except Exception:  # noqa
                pass
            cg._click(page, cg.CONTINUE_SEL, 4000)
            time.sleep(3)
            continue
        o = None
        for s in cg.OTP_SEL:
            o = _vis(page, s)
            if o:
                break
        if o:
            code = cg.totp_now(acc.get("twofa", ""))
            if code:
                log("    → (re-auth) nhập OTP")
                try:
                    o.fill(code)
                except Exception:  # noqa
                    pass
                cg._click(page, cg.CONTINUE_SEL, 4000)
                time.sleep(3)
                continue
        break


def logout_all(page, acc=None, log=print, shot=None):
    """Đăng xuất TẤT CẢ thiết bị. Nút = data-testid='logout-all-button' (tab Bảo mật) -> hộp xác nhận
    'Đăng xuất khỏi tất cả thiết bị' -> (re-auth nếu bị hỏi) -> XÁC MINH phiên hiện tại ĐÃ bị đăng
    xuất (logout-all đá CẢ phiên hiện tại). Nếu VẪN đăng nhập -> raise (KHÔNG báo ✓ giả)."""
    # 1) PHẢI mở khu 'Phiên đang hoạt động' (my-devices-menu) TRƯỚC — nút 'Đăng xuất tất cả' chỉ
    #    hoạt động ở trang active-sessions (bấm thẳng trên tab Security ra nút ẩn -> click giả -> ko confirm).
    _open(page, SEC_URL)
    cg._click(page, ['[data-testid="my-devices-menu"]',
                     'button:has-text("Phiên đang hoạt động")',
                     'button:has-text("Xem tất cả")', 'a:has-text("Xem tất cả")'], 5000)
    time.sleep(2)
    # 2) nút 'Đăng xuất tất cả' (logout-all-button)
    if not cg._click(page, ['[data-testid="logout-all-button"]', 'button:has-text("Đăng xuất tất cả")'], 6000):
        _open(page, SESS_URL)                # dự phòng: vào thẳng trang active-sessions
        cg._click(page, ['[data-testid="my-devices-menu"]', 'button:has-text("Phiên đang hoạt động")'], 3000)
        time.sleep(1.5)
        if not cg._click(page, ['[data-testid="logout-all-button"]', 'button:has-text("Đăng xuất tất cả")'], 6000):
            if shot:
                shot(page, "logout", "no_btn")
            _dump(page, "logout_no_btn", log)
            raise RuntimeError("không thấy nút 'Đăng xuất tất cả'")
    time.sleep(2)
    # 3) hộp xác nhận: testid ỔN ĐỊNH 'confirm-logout-all-devices-button'. Click BỀN (React hay
    #    không "ăn" .click() thường) -> force + JS.
    cf = cg._first_visible(page, ['[data-testid="confirm-logout-all-devices-button"]',
                                  '[role="dialog"] button:has-text("khỏi tất cả thiết bị")',
                                  'button:has-text("Đăng xuất khỏi tất cả thiết bị")',
                                  'button:has-text("Log out of all")'], 6000)
    if cf:
        try:
            cf.click(timeout=5000)
        except Exception:  # noqa
            try:
                cf.click(force=True, timeout=4000)
            except Exception:  # noqa
                try:
                    cf.evaluate("el => el.click()")
                except Exception:  # noqa
                    pass
    else:
        _click_dialog_btn(page, ["Đăng xuất khỏi tất cả thiết bị", "Log out of all devices"])
    time.sleep(3)
    _pass_otp_if_asked(page, acc, log)       # OpenAI có thể đòi xác minh lại
    # XÁC MINH THẬT (logout-all đá CẢ phiên hiện tại): chờ logout lan -> kiểm is_logged_in NHIỀU LẦN.
    logged = True
    for _ in range(4):
        try:
            page.goto(config.CHATGPT_URL, timeout=config.PAGE_TIMEOUT)
            time.sleep(2)
        except Exception:  # noqa
            pass
        if not cg.is_logged_in(page):
            logged = False
            break
        time.sleep(2)
    if logged:
        if shot:
            shot(page, "logout", "still_in")
        _dump(page, "logout_still_in", log)
        raise RuntimeError("đã bấm 'Đăng xuất tất cả' nhưng phiên VẪN đăng nhập sau ~15s — thiết bị "
                           "CHƯA bị đăng xuất (nút xác nhận không ăn / OpenAI đòi xác minh lại).")
    log("    ✓ xác minh: phiên đã bị đăng xuất (mọi thiết bị)")
    if shot:
        shot(page, "logout", "done")
    return True


# Nút BỎ QUA ưu đãi giữ chân (downsell) để đi tiếp tới bước hủy. KHÔNG chứa nút nhận ưu đãi.
_DECLINE_CONTINUE = ['Không, cảm ơn', 'Không dùng', 'Không phải bây giờ', 'No thanks', 'No, thanks',
                     'Not now', 'Continue to cancel', 'Continue canceling',
                     'Continue with cancellation', 'Tiếp tục hủy']
# Nút XÁC NHẬN HỦY CUỐI (bấm xong là gói bị hủy). KHÔNG chứa "Quay lại"/"Giữ".
_FINAL_CONFIRM = ['Hủy gói đăng ký', 'Hủy đăng ký', 'Cancel subscription', 'Cancel my subscription',
                  'Cancel plan', 'Cancel my plan', 'Hủy gói', 'Xác nhận hủy', 'Confirm cancellation']


def _click_any(page, texts, timeout=2000):
    for t in texts:
        if cg._click(page, [f'[role="dialog"] button:has-text("{t}")',
                            f'button:has-text("{t}")'], timeout):
            return t
    return None


def _dismiss_blocker(page, log=print):
    """Đóng popup CHE lên trang Billing (vd 'Không gia hạn được gói Plus' — lỗi thanh toán)
    để lộ nút Hủy. KHÔNG bấm 'Cập nhật phương thức thanh toán'."""
    try:
        blk = page.locator('[data-testid="modal-subscription-failure"], #modal-subscription-failure')
        if blk.count() and blk.first.is_visible():
            log("    (đóng popup lỗi thanh toán che nút Hủy)")
            if not cg._click(page, ['[data-testid="modal-subscription-failure"] button[aria-label="Đóng"]',
                                    '#modal-subscription-failure button[aria-label="Đóng"]',
                                    '[data-testid="modal-subscription-failure"] button[aria-label="Close"]'], 2000):
                try:
                    page.keyboard.press("Escape")
                except Exception:  # noqa
                    pass
            time.sleep(1)
    except Exception:  # noqa
        pass


def _click_menuitem(page, texts, timeout=3500):
    """Click 1 mục trong dropdown menu (DIV role=menuitem, KHÔNG phải <button>) theo text."""
    sels = []
    for t in texts:
        sels += [f'[role="menuitem"]:has-text("{t}")',
                 f'[role="menu"] [role="menuitem"]:has-text("{t}")',
                 f'[data-radix-menu-content] :has-text("{t}")']
    return cg._click(page, sels, timeout)


def cancel_plan(page, acc, log=print, shot=None):
    """Hủy gói đăng ký. OpenAI (7/2026) để nút hủy trong TAB TÀI KHOẢN:
    'Quản lý' (button) -> 'Hủy gói đăng ký' (menuitem). Bản cũ ở tab Thanh toán. Thử CẢ HAI
    -> bỏ qua ưu đãi -> xác nhận hủy cuối. ⚠️ PHÁ HỦY (gói vẫn dùng tới hết kỳ)."""
    entered = False
    # ===== 1) TAB TÀI KHOẢN: 'Quản lý' -> 'Hủy gói đăng ký' (menuitem) =====
    _open(page, ACCOUNT_URL)
    mbtns = page.locator('button:has-text("Quản lý"), button:has-text("Manage")')
    try:
        ntry = min(mbtns.count(), 4)
    except Exception:  # noqa
        ntry = 0
    for i in range(ntry):     # có thể có nhiều nút 'Quản lý' -> thử từng cái tới khi menu có 'Hủy gói'
        try:
            btn = mbtns.nth(i)
            if not btn.is_visible():
                continue
            btn.click()
        except Exception:  # noqa
            continue
        time.sleep(1.5)
        if _click_menuitem(page, ["Hủy gói đăng ký", "Hủy gói", "Cancel subscription", "Cancel plan"], 3500):
            log("    → (Tài khoản) Quản lý → Hủy gói đăng ký")
            entered = True
            break
        try:
            page.keyboard.press("Escape")
        except Exception:  # noqa
            pass
        time.sleep(0.5)
    # ===== 2) TAB THANH TOÁN (dự phòng, bản UI cũ) =====
    if not entered:
        cancel_sel = ['button:has-text("Hủy gói")', 'button:has-text("Cancel plan")',
                      'button:has-text("Hủy")', 'button:has-text("Cancel")']
        cancel_btn = None
        for attempt in range(2):
            _open(page, BILLING_URL)
            for k in range(12):
                _dismiss_blocker(page, log)
                cancel_btn = cg._first_visible(page, cancel_sel, 700)
                if cancel_btn:
                    break
                if page.locator('button:has-text("Nâng cấp"), button:has-text("Upgrade")').count() and k >= 3:
                    break
                time.sleep(1)
            if cancel_btn:
                break
        if cancel_btn:
            _dismiss_blocker(page, log)
            try:
                cancel_btn.click(timeout=8000)   # timeout ngắn, không treo 60s
            except Exception:  # noqa
                log("    (nút Hủy bị che/kẹt — thử force + JS click)")
                try:
                    cancel_btn.scroll_into_view_if_needed(timeout=3000)
                except Exception:  # noqa
                    pass
                try:
                    cancel_btn.click(force=True, timeout=5000)
                except Exception:  # noqa
                    try:
                        cancel_btn.evaluate("el => el.click()")
                    except Exception:  # noqa
                        pass
            log("    → (Thanh toán) bấm Hủy")
            entered = True
    if not entered:
        if shot:
            shot(page, "cancel", "no_entry")
        _dump(page, "cancel_no_entry", log)
        has_any = page.locator('button:has-text("Quản lý"), button:has-text("Manage"), '
                               'button:has-text("Thanh toán"), button:has-text("Nâng cấp")').count() > 0
        if not has_any:
            raise RuntimeError("không thấy 'Quản lý'/Thanh toán/Nâng cấp — gói mua qua App/Apple/Google → không hủy web được")
        raise RuntimeError("không vào được flow hủy gói (không có gói trả phí / đã hủy / UI lạ)")
    time.sleep(3)
    # 2) đi qua flow: mỗi vòng thử nút XÁC NHẬN CUỐI trước; nếu chưa tới thì BỎ QUA ưu đãi
    for _ in range(6):
        done = _click_any(page, _FINAL_CONFIRM, 2000)
        if done:
            log(f"    ✔ xác nhận hủy: '{done}'")
            try:
                time.sleep(3)  # xong: KHÔNG đụng page nữa (trang reload hay rớt CDP)
            except Exception:  # noqa
                pass
            return True
        cont = _click_any(page, _DECLINE_CONTINUE, 2000)
        if not cont:
            break
        log(f"    → bỏ qua ưu đãi: '{cont}'")
        time.sleep(3)
    if shot:
        shot(page, "cancel", "stuck")
    raise RuntimeError("không hoàn tất được flow hủy (UI lạ / không có gói?)")


def delete_all_chats(page, acc=None, log=print, shot=None):
    """Xóa tất cả đoạn chat: #settings/DataControls -> 'Xóa tất cả' -> 'Xác nhận xóa'.
    ⚠️ PHÁ HỦY: xóa sạch lịch sử chat của tài khoản, không khôi phục được."""
    _open(page, DATA_URL)
    # 1) tìm nút "Xóa tất cả" (KHÁC "Lưu trữ tất cả"). Nút này KHÔNG có testid -> theo text.
    #    Chờ nội dung DataControls load (async).
    del_btn = None
    for _ in range(6):
        for sel in ('button:has-text("Xóa tất cả")', 'button:has-text("Delete all")'):
            loc = page.locator(sel)
            try:
                if loc.count() and loc.first.is_visible():
                    del_btn = loc.first
                    break
            except Exception:  # noqa
                pass
        if del_btn:
            break
        time.sleep(1.5)
    if not del_btn:
        if shot:
            shot(page, "delchat", "no_btn")
        _dump(page, "delchat_no_btn", log)
        raise RuntimeError("không thấy nút 'Xóa tất cả'")
    # acc KHÔNG có đoạn chat -> nút bị VÔ HIỆU (disabled). Coi như đã sạch, BỎ QUA (tránh treo 60s).
    try:
        if not del_btn.is_enabled():
            log("    (không có đoạn chat để xóa — coi như đã sạch)")
            return True
    except Exception:  # noqa
        pass
    # click (timeout NGẮN + force/JS, không để treo 60s)
    try:
        del_btn.click(timeout=8000)
    except Exception:  # noqa
        try:
            del_btn.click(force=True, timeout=4000)
        except Exception:  # noqa
            try:
                del_btn.evaluate("el => el.click()")
            except Exception:  # noqa
                pass
    time.sleep(2)
    # 2) hộp xác nhận -> testid ổn định 'confirm-delete-all-chats-button' ("Xác nhận xóa")
    if not (cg._click(page, ['[data-testid="confirm-delete-all-chats-button"]',
                             '[role="dialog"] button:has-text("Xác nhận xóa")',
                             'button:has-text("Xác nhận xóa")', 'button:has-text("Confirm deletion")',
                             'button:has-text("Xác nhận")', 'button:has-text("Confirm")'], 6000)
            or _click_dialog_btn(page, ["Xác nhận xóa", "Xác nhận", "Confirm deletion", "Confirm"])):
        if shot:
            shot(page, "delchat", "no_confirm")
        raise RuntimeError("không thấy nút xác nhận 'Xác nhận xóa'")
    time.sleep(3)
    if shot:
        shot(page, "delchat", "done")
    return True
