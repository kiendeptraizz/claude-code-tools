# -*- coding: utf-8 -*-
"""
Lấy mã OTP mà Microsoft gửi về CHÍNH hòm mail của account,
bằng cách dùng refresh_token + client_id để đăng nhập IMAP (OAuth2 XOAUTH2).
"""
import imaplib
import email
import re
import time
import requests

import config

TOKEN_ENDPOINTS = [
    "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    "https://login.live.com/oauth20_token.srf",
]
IMAP_SCOPE = (
    "https://outlook.office.com/IMAP.AccessAsUser.All "
    "https://outlook.office.com/SMTP.Send offline_access"
)


def get_access_token(refresh_token: str, client_id: str):
    """Đổi refresh_token lấy access_token. Trả về (access_token, new_refresh_token) hoặc (None, None)."""
    last_err = None
    for url in TOKEN_ENDPOINTS:
        try:
            data = {
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": IMAP_SCOPE,
            }
            r = requests.post(url, data=data, timeout=30)
            j = r.json()
            if "access_token" in j:
                return j["access_token"], j.get("refresh_token", refresh_token)
            last_err = j.get("error_description", j.get("error", str(j)))
        except Exception as e:  # noqa
            last_err = str(e)
    print(f"    [otp] không lấy được access_token: {last_err}")
    return None, None


def _imap_connect(email_addr: str, access_token: str):
    auth_string = f"user={email_addr}\x01auth=Bearer {access_token}\x01\x01"
    imap = imaplib.IMAP4_SSL(config.IMAP_SERVER)
    imap.authenticate("XOAUTH2", lambda x: auth_string.encode())
    return imap


def _extract_code(text: str):
    """Tìm mã 6-8 số trong nội dung mail."""
    if not text:
        return None
    # Ưu tiên đoạn gần chữ 'code'/'mã'
    m = re.search(r"(?:security code|mã bảo mật|code)[^0-9]{0,40}(\d{6,8})", text, re.I)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{6,8})\b", text)
    return m.group(1) if m else None


def _read_body(msg):
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html"):
                try:
                    parts.append(part.get_payload(decode=True).decode(errors="ignore"))
                except Exception:  # noqa
                    pass
    else:
        try:
            parts.append(msg.get_payload(decode=True).decode(errors="ignore"))
        except Exception:  # noqa
            pass
    return " ".join(parts)


def imap_open(email_addr: str, refresh_token: str, client_id: str):
    """Mở kết nối IMAP. Trả về (imap, new_refresh_token) hoặc (None, refresh_token)."""
    token, new_rt = get_access_token(refresh_token, client_id)
    if not token:
        return None, refresh_token
    try:
        return _imap_connect(email_addr, token), new_rt
    except Exception as e:  # noqa
        print(f"    [otp] IMAP connect lỗi: {e}")
        return None, new_rt


def code_keys(imap):
    """Tập (folder, uid) của các mail bảo mật ĐANG có — dùng làm mốc trước khi gửi mã."""
    keys = set()
    for folder in ("INBOX", "Junk"):
        try:
            imap.select(folder)
        except Exception:  # noqa
            continue
        for sender in config.OTP_SENDERS:
            typ, data = imap.uid("search", None, f'(FROM "{sender}")')
            if typ == "OK" and data and data[0]:
                for u in data[0].split():
                    keys.add((folder, u))
    return keys


def wait_new_code(imap, baseline, wait=None):
    """Chờ mail bảo mật MỚI (không nằm trong baseline) rồi trích mã. Trả về code hoặc None."""
    if wait is None:
        wait = config.OTP_WAIT
    deadline = time.time() + wait
    while time.time() < deadline:
        for folder in ("INBOX", "Junk"):
            try:
                imap.select(folder)
            except Exception:  # noqa
                continue
            for sender in config.OTP_SENDERS:
                typ, data = imap.uid("search", None, f'(FROM "{sender}")')
                if typ != "OK" or not data or not data[0]:
                    continue
                new_uids = [u for u in data[0].split() if (folder, u) not in baseline]
                for u in sorted(new_uids, key=lambda x: int(x), reverse=True):
                    typ, md = imap.uid("fetch", u, "(RFC822)")
                    if typ != "OK" or not md or not md[0]:
                        continue
                    msg = email.message_from_bytes(md[0][1])
                    body = (msg.get("Subject", "") or "") + " " + _read_body(msg)
                    code = _extract_code(body)
                    if code:
                        return code
        time.sleep(5)
    return None


def fetch_otp(email_addr: str, refresh_token: str, client_id: str):
    """
    Chờ và lấy mã OTP mới nhất từ Microsoft. Trả về (code, new_refresh_token) hoặc (None, refresh_token).
    """
    access_token, new_rt = get_access_token(refresh_token, client_id)
    if not access_token:
        return None, refresh_token

    deadline = time.time() + config.OTP_WAIT
    while time.time() < deadline:
        try:
            imap = _imap_connect(email_addr, access_token)
            for folder in ("INBOX", "Junk"):
                try:
                    imap.select(folder)
                except Exception:  # noqa
                    continue
                # Lấy các mail gần nhất từ người gửi bảo mật
                for sender in config.OTP_SENDERS:
                    typ, data = imap.search(None, f'(FROM "{sender}")')
                    if typ != "OK" or not data or not data[0]:
                        continue
                    ids = data[0].split()[-3:]  # 3 mail mới nhất
                    for mid in reversed(ids):
                        typ, mdata = imap.fetch(mid, "(RFC822)")
                        if typ != "OK":
                            continue
                        msg = email.message_from_bytes(mdata[0][1])
                        body = (msg.get("Subject", "") or "") + " " + _read_body(msg)
                        code = _extract_code(body)
                        if code:
                            try:
                                imap.logout()
                            except Exception:  # noqa
                                pass
                            return code, new_rt
            imap.logout()
        except Exception as e:  # noqa
            print(f"    [otp] lỗi IMAP: {e}")
        time.sleep(5)
    return None, new_rt
