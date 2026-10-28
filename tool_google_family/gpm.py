# -*- coding: utf-8 -*-
"""Client gọi API GPM Login (v3) để liệt kê / tạo / mở / đóng profile.

Mở profile trả về remote_debugging_address -> Playwright gắn vào qua CDP.
Tài liệu: http://127.0.0.1:19995/api/v3  (xem docs.gpmloginapp.com)
"""
import requests

import config


class GPMError(Exception):
    pass


def _base():
    return f"http://127.0.0.1:{config.GPM_PORT}/api/v3"


def _get(path, **params):
    r = requests.get(f"{_base()}{path}", params=params or None, timeout=60)
    try:
        return r.json()
    except Exception:  # noqa
        raise GPMError(f"GPM trả về không phải JSON ({r.status_code}): {r.text[:200]}")


def ping():
    """Kiểm tra GPM Login có đang chạy + bật API không."""
    try:
        _get("/profiles", page=1, per_page=1)
        return True
    except Exception:  # noqa
        return False


def _data_list(j):
    data = j.get("data", j)
    if isinstance(data, dict):
        data = data.get("data") or data.get("profiles") or data.get("items") or []
    return data or []


def list_groups():
    """Trả về list nhóm [{id, name, ...}]."""
    return _data_list(_get("/groups", page=1, per_page=500))


def list_profiles(per_page=200, group_id=None):
    """Lấy TẤT CẢ profile (tự lật trang). Lọc theo group_id nếu có."""
    out = []
    page = 1
    while True:
        params = {"page": page, "per_page": per_page}
        if group_id is not None:
            params["group_id"] = group_id
        j = _get("/profiles", **params)
        batch = _data_list(j)
        out.extend(batch)
        pg = j.get("pagination") or {}
        total_page = pg.get("total_page") or 1
        if page >= total_page or not batch:
            break
        page += 1
    return out


def find_profile_by_name(name):
    name = (name or "").strip().lower()
    for p in list_profiles():
        if (p.get("name") or p.get("profile_name") or "").strip().lower() == name:
            return p
    return None


_CACHED_VERSION = None


def _sample_browser_version():
    """Version trình duyệt PHỔ BIẾN NHẤT trong các profile (bản GPM chắc chắn đã cài). Có cache."""
    global _CACHED_VERSION
    if _CACHED_VERSION:
        return _CACHED_VERSION
    try:
        from collections import Counter
        vers = [p.get("browser_version") for p in list_profiles(per_page=300)]
        vers = [v for v in vers if v]
        if vers:
            _CACHED_VERSION = Counter(vers).most_common(1)[0][0]
            return _CACHED_VERSION
    except Exception:  # noqa
        pass
    return ""


def create_profile(name, group_name=None, raw_proxy="", browser_version=None):
    """Tạo profile mới. Dùng version trình duyệt CÓ SẴN (tránh lỗi 'cần cập browser')."""
    if browser_version is None:
        browser_version = _sample_browser_version()
    body = {
        "profile_name": name,
        "group_name": group_name or config.GPM_GROUP,
        "browser_core": "chromium",
        "browser_name": "Chrome",
        "browser_version": browser_version,
        "is_random_browser_version": False,
        "raw_proxy": raw_proxy or "",
        "startup_urls": "",
        "is_masked_font": True,
        "is_noise_canvas": True,
        "is_noise_webgl": True,
        "is_noise_audio_context": True,
        "is_random_screen": False,
        "is_auto_update_core": True,
    }
    r = requests.post(f"{_base()}/profiles/create", json=body, timeout=60)
    try:
        j = r.json()
    except Exception:  # noqa
        raise GPMError(f"create profile lỗi ({r.status_code}): {r.text[:200]}")
    if not j.get("success", True):
        raise GPMError(f"create profile thất bại: {j.get('message', j)}")
    return j.get("data", j)


# màu đánh dấu (best-effort — GPM API v3 có thể BỎ QUA field color, chỉ note chắc chắn ghi được)
COLOR_RED = "#EF4444"
COLOR_PURPLE = "#A855F7"
COLOR_GREEN = "#22C55E"


def update_profile(profile_id, note=None, color=None, raw_proxy=None):
    """Cập nhật ghi chú (note) + màu (color) + proxy (raw_proxy) của profile.
    POST /api/v3/profiles/update/{id}. Trả True nếu API báo success."""
    body = {}
    if note is not None:
        body["note"] = note
    if color is not None:
        body["color"] = color   # hex "#RRGGBB" — GPM ĐỔI MÀU profile thật (SET ăn dù GET không trả về field này)
    if raw_proxy is not None:
        body["raw_proxy"] = raw_proxy   # GÁN proxy cho profile ĐÃ CÓ (không chỉ lúc tạo mới)
    if not body:
        return False
    try:
        r = requests.post(f"{_base()}/profiles/update/{profile_id}", json=body, timeout=30)
        return bool(r.json().get("success", False))
    except Exception:  # noqa
        return False


def delete_profile(profile_id):
    """Xóa profile: DELETE /api/v3/profiles/{id}."""
    try:
        r = requests.delete(f"{_base()}/profiles/{profile_id}", timeout=30)
        return r.status_code == 200 and r.json().get("success", False)
    except Exception:  # noqa
        return False


def start_profile(profile_id):
    """Mở profile. Trả về (remote_debugging_address, raw_data)."""
    j = _get(f"/profiles/start/{profile_id}", win_scale=config.WIN_SCALE)
    if not j.get("success", True):
        raise GPMError(f"mở profile thất bại: {j.get('message', j)}")
    d = j.get("data", j) or {}
    addr = (d.get("remote_debugging_address") or d.get("remote_debug_address")
            or d.get("debug_address") or d.get("remoteDebuggingAddress"))
    if not addr:
        raise GPMError(f"không thấy remote_debugging_address trong phản hồi: {d}")
    return addr, d


def close_profile(profile_id):
    try:
        _get(f"/profiles/close/{profile_id}")
        return True
    except Exception:  # noqa
        return False


def get_profile_id(prof):
    """Lấy id từ dict profile (các phiên bản dùng key khác nhau)."""
    return prof.get("id") or prof.get("profile_id") or prof.get("_id") or prof.get("uuid")
