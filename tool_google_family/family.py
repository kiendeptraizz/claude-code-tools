# -*- coding: utf-8 -*-
"""Đọc Google Family từ trang 'Your family on Google' (myaccount.google.com/family).

Trang chỉ hiện TÊN thành viên + nhãn vai trò (Family manager / Member) — KHÔNG hiện email.
Nên tool đọc theo TÊN + đếm số người: slot trống = 6 − số người.
"""
import re
import time

import config

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# nhãn vai trò (Anh + Việt)
MANAGER_LABELS = ("family manager", "người quản lý gia đình", "quản lý gia đình")
MEMBER_LABELS = ("member", "thành viên")
ROLE_LABELS = MANAGER_LABELS + MEMBER_LABELS

NO_FAMILY_RE = re.compile(
    r"create a family group|set up (your )?family|don.t have a family|"
    r"tạo nhóm gia đình|chưa có (nhóm )?gia đình|bắt đầu.*gia đình", re.I)
MANAGER_VIEW_RE = re.compile(
    r"Delete (your )?Family Group|Xóa nhóm gia đình|Stop sharing|Ngừng chia sẻ", re.I)
MEMBER_VIEW_RE = re.compile(r"Leave family group|Rời nhóm gia đình|Leave family", re.I)


# Cấu trúc trong RPC:  "<gaiaId>","<ho/ten>","<ten/ho>","<email>", ...
PAIR_RE = re.compile(
    r'"([^"]{1,80})","([^"]{0,80})","([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})"')


def _parse_pairs(body):
    if not body:
        return []
    b = body.replace('\\"', '"')   # body batchexecute escape dấu ngoặc -> bỏ escape
    pairs = []
    for fn, ln, em in PAIR_RE.findall(b):
        if "google.com" in em.lower():
            continue
        name = (fn + " " + ln).strip()
        pairs.append((name, em.lower()))
    return pairs


def _click_member(page, name):
    """Bấm vào 1 thành viên theo tên. Trả về True nếu đã sang trang chi tiết."""
    for exact in (True, False):
        try:
            el = page.get_by_text(name, exact=exact).first
            if el.count() and el.is_visible():
                el.click()
                try:
                    page.wait_for_url("**/family/member/**", timeout=10000)
                except Exception:  # noqa
                    pass
                time.sleep(1.5)
                return True
        except Exception:  # noqa
            continue
    return False


def _fetch_member_emails(page, members, self_email, log, rpc_bodies):
    """NHANH: bấm 1 thành viên -> RPC chứa TOÀN BỘ tên+email (đã thu sẵn ở rpc_bodies) -> ghép 1 lần.
    Fallback: bấm riêng từng người còn thiếu email. Chỉ chạy khi acc là QUẢN LÝ."""
    self_l = (self_email or "").lower()
    for m in members:
        if m["role"] == "manager":
            m["email"] = self_email or ""
    targets = [m for m in members if m["role"] != "manager" and m["name"]]
    if not targets:
        return

    # bấm 1 người bất kỳ để kích hoạt RPC đầy đủ (collector ở read_family thu body)
    if "/family/member" in (page.url or "") or "family" not in (page.url or ""):
        page.goto(config.FAMILY_URL, timeout=config.PAGE_TIMEOUT)
        time.sleep(2.5)
    for m in targets:
        if _click_member(page, m["name"]):
            break
    page.wait_for_timeout(5000)

    best = ""
    for t in list(rpc_bodies):
        if t and "@" in t and len(_parse_pairs(t)) > len(_parse_pairs(best)):
            best = t
    by_name = {}
    for nm, em in _parse_pairs(best):
        if em != self_l:
            by_name[nm.strip().lower()] = em
    got = 0
    for m in members:
        if m.get("email"):
            continue
        em = by_name.get(m["name"].strip().lower())
        if em:
            m["email"] = em
            got += 1
    if log:
        log(f"       lấy nhanh {got}/{len(targets)} email (1 lần tải)")

    # Fallback: người nào còn thiếu -> bấm riêng đọc trang chi tiết
    missing = [m for m in members if m["role"] != "manager" and not m.get("email")]
    for m in missing:
        try:
            page.goto(config.FAMILY_URL, timeout=config.PAGE_TIMEOUT)
            time.sleep(2)
            if not _click_member(page, m["name"]):
                continue
            detail = page.inner_text("body")
            ems = [e.lower() for e in EMAIL_RE.findall(detail)
                   if "google" not in e.lower() and e.lower() != self_l]
            if ems:
                m["email"] = ems[0]
                if log:
                    log(f"       • {m['name']} → {ems[0]} (chi tiết)")
        except Exception:  # noqa
            pass


def read_family(page, self_email, log=print, shot=None):
    # Thu body các RPC batchexecute NGAY TỪ ĐẦU (trước khi tải trang) để bắt được
    # response chứa toàn bộ tên+email thành viên khi bấm 1 người.
    rpc_bodies = []

    def _collect(r):
        try:
            if "batchexecute" in r.url:
                rpc_bodies.append(r.text())
        except Exception:  # noqa
            pass

    try:
        page.on("response", _collect)
    except Exception:  # noqa
        pass

    page.goto(config.FAMILY_URL, timeout=config.PAGE_TIMEOUT)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:  # noqa
        pass
    time.sleep(3)
    if shot:
        shot(page, self_email, "family_page")

    body = ""
    try:
        body = page.inner_text("body")
    except Exception:  # noqa
        pass
    lines = [l.strip() for l in body.splitlines()]

    url = (page.url or "").lower()
    signed_out = ("signin" in url or "accounts.google.com" in url
                  or bool(re.search(r"(Sign in|Đăng nhập|Verify it.?s you|Use your Google Account|to continue to)", body, re.I)))
    on_family = ("myaccount.google.com" in url) and ("family" in url)

    result = {
        "role": "?", "is_manager": False, "members": [], "member_count": 0,
        "free_slots": None, "has_family": False, "note": "", "error": False,
    }

    # Ghép cặp: dòng nhãn vai trò -> tên là dòng (không rỗng) ngay TRƯỚC nó.
    members = []
    seen = set()
    for idx, line in enumerate(lines):
        low = line.lower()
        if low in ROLE_LABELS:
            j = idx - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            name = lines[j].strip() if j >= 0 else ""
            if not name or name.lower() in ROLE_LABELS:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            is_mgr = low in MANAGER_LABELS
            members.append({"name": name, "email": "",
                            "role": "manager" if is_mgr else "member"})

    if not members:
        # CHỈ tin "chưa có family (trống)" NẾU thật sự đang ở trang QUẢN LÝ (myaccount.google.com).
        if on_family and NO_FAMILY_RE.search(body):
            result["note"] = "chưa có family group (trống)"
            result["free_slots"] = config.FAMILY_MAX
            result["has_family"] = False
            return result
        # Còn lại = KHÔNG vào được trang quản lý -> BÁO LỖI (không suy ra 6 slot).
        result["error"] = True
        result["free_slots"] = None
        result["role"] = "-"
        if "families.google" in url and not on_family:
            result["note"] = "KHÔNG vào được trang quản lý Family (bị đưa ra trang tiếp thị families.google — acc chưa vào được / chưa xác thực đủ)"
        elif signed_out or not on_family:
            result["note"] = "KHÔNG vào được Family (acc chưa đăng nhập / bị đá ra / challenge)"
        else:
            result["note"] = "vào được Family nhưng không đọc được thành viên (xem screenshots/)"
        return result

    is_manager = bool(MANAGER_VIEW_RE.search(body)) or any(m["role"] == "manager" for m in members)
    if MEMBER_VIEW_RE.search(body) and not MANAGER_VIEW_RE.search(body):
        is_manager = False

    # Lấy email từng thành viên (bấm vào chi tiết) — chỉ khi là quản lý
    if config.GET_MEMBER_EMAILS and is_manager and members:
        if log:
            log("    đang lấy email thành viên...")
        _fetch_member_emails(page, members, self_email, log, rpc_bodies)

    try:
        page.remove_listener("response", _collect)
    except Exception:  # noqa
        pass

    result["members"] = members
    result["member_count"] = len(members)
    result["has_family"] = True
    result["is_manager"] = is_manager
    result["role"] = "quản lý" if is_manager else "thành viên"
    result["free_slots"] = max(0, config.FAMILY_MAX - len(members))
    return result
