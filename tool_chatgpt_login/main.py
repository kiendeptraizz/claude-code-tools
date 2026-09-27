# -*- coding: utf-8 -*-
"""Tool login ChatGPT (OpenAI) hàng loạt qua GPM Login.
Input mỗi dòng: email|pass|2fa[|proxy]   (2fa = secret TOTP, có thể trống)

Tạo profile GPM (tên=email) + gắn proxy -> đăng nhập OpenAI -> để lại profile đã login.
Chạy CLI:  python main.py
"""
import os
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
import chatgpt_login
import chatgpt_actions

LOG_CALLBACK = None
STOP_EVENT = threading.Event()
ACTIVE_PIDS = set()               # profile GPM đang mở (để DỪNG NGAY = đóng hết)
ACTIVE_LOCK = threading.Lock()


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


def _register_pid(pid):
    with ACTIVE_LOCK:
        ACTIVE_PIDS.add(pid)


def _unregister_pid(pid):
    with ACTIVE_LOCK:
        ACTIVE_PIDS.discard(pid)


def stop_all():
    """DỪNG NGAY: bật cờ dừng + ĐÓNG mọi profile đang mở → thao tác Playwright đang chạy sẽ
    văng lỗi (CDP mất) và thoát ngay, thay vì phải chờ hết acc. Gọi từ /api/stop."""
    STOP_EVENT.set()
    with ACTIVE_LOCK:
        pids = list(ACTIVE_PIDS)
    for pid in pids:
        try:
            gpm.close_profile(pid)
        except Exception:  # noqa
            pass
    log(f"⏹ ĐÃ DỪNG — đóng {len(pids)} profile đang chạy.")


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
    # Trường 4 CHỈ là proxy khi TRÔNG GIỐNG proxy (host:port...). Nhiều nguồn acc để trường 4 là
    # mã KHÔI PHỤC / backup 2FA (vd '83QDCF578TD2') — KHÔNG phải proxy; coi nhầm sẽ lỗi
    # ERR_NO_SUPPORTED_PROXIES. Proxy luôn có ':' (host:port); mã khôi phục thì không.
    p4 = parts[3].strip() if len(parts) > 3 else ""
    is_proxy = ":" in p4
    return {
        "email": parts[0].strip(),
        "pass": parts[1].strip() if len(parts) > 1 else "",
        "twofa": parts[2].strip() if len(parts) > 2 else "",
        "proxy": p4 if is_proxy else "",
        "backup": "" if is_proxy else p4,   # mã khôi phục/backup (nếu có) — giữ lại, KHÔNG dùng khi login
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


def save_result(email, status, note=""):
    os.makedirs(os.path.dirname(config.RESULT_FILE), exist_ok=True)
    with open(config.RESULT_FILE, "a", encoding="utf-8") as f:
        f.write(f"{email}|{status}|{note}\n")


def save_account_line(line, actions):
    """Ghi tài khoản MỚI để tái dùng + tra cứu:
    - data/tai_khoan_moi.txt: dòng sạch email|pass|2fa (dán lại dùng ngay)
    - data/ket_qua_chi_tiet.txt: thời gian | email|pass|2fa | thao tác đã làm"""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs("data", exist_ok=True)
        with open("data/tai_khoan_moi.txt", "a", encoding="utf-8") as f:
            f.write(line + "\n")
        with open("data/ket_qua_chi_tiet.txt", "a", encoding="utf-8") as f:
            f.write(f"{ts} | {line} | {', '.join(actions)}\n")
    except Exception:  # noqa
        pass


def write_history(record):
    try:
        os.makedirs("data", exist_ok=True)
        with open(config.HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa
        pass


# ---------- xử lý 1 acc ----------

def _run_actions(page, acc, actions, new_password, extra):
    """Chạy từng thao tác ĐỘC LẬP: lỗi 1 cái thì BỎ QUA, chạy tiếp cái khác.
    Thứ tự AN TOÀN: RESET 2FA (đầu tiên, ngay sau login) -> hủy gói -> xóa chat ->
    đổi pass (tự đá hết phiên) -> logout all.
    - reset 2FA chạy ĐẦU vì phiên tươi nhất -> ít bị OpenAI đòi xác minh email + tránh
      redirect sau hủy gói chen ngang lúc mở trang Security.
    - reset 2FA + đổi pass phải TRƯỚC logout vì logout/đổi-pass làm mất phiên đang đăng nhập.
    Ghi lại từng thao tác ✓/✗ vào extra['ops']."""
    actions = set(actions or [])
    ops = []

    def do(name, fn):
        if should_stop():          # đã bấm Dừng -> bỏ các thao tác còn lại
            return False
        log(f"    ⟳ {name} {acc['email']}...")
        try:
            fn()
            ops.append({"name": name, "ok": True})
            log(f"    ✅ {name} OK")
            return True
        except Exception as e:  # noqa
            ops.append({"name": name, "ok": False, "err": str(e)})
            log(f"    ⚠️ {name} lỗi — BỎ QUA, chạy tiếp: {e}")
            return False

    # RESET 2FA chạy ĐẦU TIÊN (phiên tươi nhất). Cập nhật acc["twofa"] để ĐỔI PASS sau dùng OTP MỚI.
    if "reset2fa" in actions:
        def _do_reset2fa():
            sec = chatgpt_actions.reset_2fa(page, acc, log=log, shot=shot)
            if sec:
                extra["new_2fa"] = sec
                acc["twofa"] = sec
        do("reset 2FA", _do_reset2fa)
    if "cancel" in actions:
        if do("hủy gói", lambda: chatgpt_actions.cancel_plan(page, acc, log=log, shot=shot)):
            time.sleep(5)   # hủy gói xong OpenAI tự redirect (?refresh_account=true) -> chờ settle
    if "delchat" in actions:
        do("xóa chat", lambda: chatgpt_actions.delete_all_chats(page, acc, log=log, shot=shot))
    changed_pw = False
    if "password" in actions and new_password:
        changed_pw = do("đổi pass", lambda: chatgpt_actions.change_password(page, acc, new_password, log=log, shot=shot))
        if changed_pw:
            extra["new_pass"] = new_password
    if "logout" in actions:
        if changed_pw:  # đổi pass đã tự đăng xuất mọi phiên
            ops.append({"name": "logout", "ok": True})
        else:
            do("logout", lambda: chatgpt_actions.logout_all(page, acc, log=log, shot=shot))
    extra["ops"] = ops


def login_one(acc, group_name="", raw_proxy="", actions=None, new_password="", recreate=False,
              keep_open=False, force_login=False, delete_after=False):
    """Tạo profile (tên=email) nếu chưa có + proxy -> login OpenAI -> chạy actions.
    recreate=True (khi RETRY): xóa profile cũ để tạo lại với PROXY MỚI (xoay proxy).
    keep_open=True: KHÔNG đóng profile khi xong (giữ cửa sổ mở để vào kiểm tra thủ công).
    force_login=True: LÀM TƯƠI PHIÊN — bỏ qua phiên cũ (kể cả còn sống), xoá cookie + đăng nhập lại
      bằng mật khẩu. Dùng khi ĐỔI PASS / THAY 2FA để giảm việc OpenAI đòi xác minh email trên phiên cũ.
    delete_after=True: XÓA HẲN profile GPM sau khi xong (dọn sạch; lần sau phải login lại từ đầu).
    Trả về (status, extra) với status 'ok'|'already', extra chứa new_pass nếu có đổi pass."""
    email = acc["email"]
    extra = {}
    prof = gpm.find_profile_by_name(email)
    # Profile cũ dính raw_proxy RÁC (có giá trị nhưng KHÔNG phải host:port — di chứng bug cũ coi
    # mã khôi phục/backup ở trường 4 là proxy) → Chromium lỗi ERR_NO_SUPPORTED_PROXIES lặp mãi.
    # Phát hiện → tạo lại profile với proxy ĐÚNG (rp hiện tại).
    if prof and not recreate:
        old_px = (prof.get("raw_proxy") or "").strip()
        if old_px and ":" not in old_px:
            log(f"    (profile cũ dính proxy rác {old_px!r} → xoá + tạo lại với proxy đúng)")
            recreate = True
    if prof and recreate:                       # retry / proxy rác: tạo lại profile
        if gpm.delete_profile(gpm.get_profile_id(prof)):
            prof = None
    if not prof:
        prof = gpm.create_profile(email, group_name=group_name, raw_proxy=raw_proxy)
    pid = gpm.get_profile_id(prof)
    if not pid:
        raise RuntimeError(f"không tạo được profile cho {email}")
    addr, _ = gpm.start_profile(pid)
    _register_pid(pid)            # để stop_all() đóng được profile này khi user bấm Dừng
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://{addr}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(config.PAGE_TIMEOUT)
            page.goto(config.CHATGPT_URL, timeout=config.PAGE_TIMEOUT)
            time.sleep(3)
            if should_stop():
                return "stopped", extra
            if force_login:
                # LÀM TƯƠI PHIÊN: bỏ qua phiên cũ dù còn sống → xoá cookie + đăng nhập lại bằng mật
                # khẩu (giảm khả năng OpenAI đòi xác minh EMAIL khi đổi pass / thay 2FA).
                log("    🔄 làm tươi phiên: bỏ qua phiên cũ → đăng nhập lại")
                try:
                    ctx.clear_cookies()
                except Exception:  # noqa
                    pass
                status = "ok"
                chatgpt_login.login(page, email, acc["pass"], acc["twofa"], log=log, shot=shot)
            else:
                # Đã login sẵn? KHÔNG chỉ tin cookie/UI — HỎI THẲNG backend (/backend-api/me):
                #   live -> tài khoản sống thật -> "đã login sẵn" (nhanh); khác -> xoá cookie + login lại.
                state = chatgpt_login.account_state(page, log=log)
                if state == "live":
                    status = "already"
                else:
                    status = "ok"
                    if chatgpt_login.is_logged_in(page):   # có phiên cũ nhưng backend không nhận
                        log(f"    (phiên 'đã login sẵn' backend KHÔNG xác nhận [{state}] → xoá cookie, "
                            f"đăng nhập lại để rõ live/die)")
                        try:
                            ctx.clear_cookies()   # buộc hiện form đăng nhập → mật khẩu mới lộ được acc die
                        except Exception:  # noqa
                            pass
                    if should_stop():
                        return "stopped", extra
                    chatgpt_login.login(page, email, acc["pass"], acc["twofa"], log=log, shot=shot)
            if actions and not should_stop():
                _run_actions(page, acc, actions, new_password, extra)
            try:
                browser.close()   # chỉ NGẮT kết nối Playwright; cửa sổ GPM vẫn mở nếu không close_profile
            except Exception:  # noqa
                pass
            return status, extra
    finally:
        _unregister_pid(pid)
        if delete_after and not should_stop():
            # XÓA HẲN profile sau khi xong (dọn sạch): đóng cửa sổ trước rồi delete. Ưu tiên hơn
            # keep_open. Lần sau acc này phải login lại từ đầu (mất phiên đã lưu). KHÔNG xoá khi ĐANG DỪNG.
            try:
                gpm.close_profile(pid)
            except Exception:  # noqa
                pass
            time.sleep(1)   # chờ cửa sổ nhả để GPM cho xoá
            try:
                if gpm.delete_profile(pid):
                    log(f"    🗑️ đã xoá profile {email}")
                else:
                    log(f"    (không xoá được profile {email} — có thể đang mở)")
            except Exception:  # noqa
                pass
        # keep_open=True -> GIỮ profile mở để user vào xem/kiểm tra (phiên vẫn đăng nhập)
        # Nhưng nếu ĐANG DỪNG thì vẫn đóng (stop_all cũng đã đóng) để thoát dứt điểm.
        elif (config.CLOSE_PROFILE_AFTER and not keep_open) or should_stop():
            try:
                gpm.close_profile(pid)
            except Exception:  # noqa
                pass


# Lỗi ở bước LOGIN/hạ tầng -> nên retry (đổi proxy). KHÔNG gồm lỗi vĩnh viễn
# (sai pass, email không tồn tại, acc bị xóa) — retry vô ích.
_RETRYABLE = ("cloudflare", "verify you are human", "không thấy ô email", "trang lạ",
              "không tới được ô mật khẩu", "chưa xác nhận đăng nhập", "thử thách",
              "connect_over_cdp", "econnrefused", "connection", "timeout", "target closed",
              "mở profile", "không tạo được profile", "remote_debug", "ws://", "cdp")
_NEVER_RETRY = ("sai mật khẩu", "email không tồn tại", "chưa có acc",
                "đã bị xóa", "vô hiệu hóa", "deleted or disabled")


def _is_retryable(msg):
    m = (msg or "").lower()
    if any(k in m for k in _NEVER_RETRY):
        return False
    return any(k in m for k in _RETRYABLE)


def run_login(accs, group_name="", threads=None, on_progress=None, on_result=None, proxies=None,
              actions=None, new_password="", keep_open=False, force_login=False, delete_after=False):
    STOP_EVENT.clear()
    for d in ("logs", "screenshots", "data"):
        os.makedirs(d, exist_ok=True)
    if not gpm.ping():
        log("❌ Không kết nối GPM API (cổng %d). Mở GPM Login + bật API." % config.GPM_PORT)
        return 0, 0
    n = len(accs)
    if n == 0:
        log("Không có account."); return 0, 0
    proxies = [p.strip() for p in (proxies or []) if p.strip()]
    threads = max(1, min(int(threads or config.THREADS), 5))
    actions = list(actions or [])
    act_txt = ("login + " + "+".join(actions)) if actions else "login"
    start_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"=== {act_txt.upper()} CHATGPT {n} acc -> nhóm '{group_name or 'All'}' | {threads} luồng ===")
    results = {}
    lock = threading.Lock()
    done = [0]

    def work(i):
        if should_stop():
            return
        acc = accs[i]
        rec = {"email": acc["email"]}
        # ---- RETRY LOOP: chỉ retry lỗi LOGIN/mạng, xoay proxy mỗi lần thử ----
        attempts = 1 + max(0, int(getattr(config, "LOGIN_RETRIES", 0)))
        st = None
        extra = {}
        err = None
        for t in range(attempts):
            if should_stop():
                return
            # proxy: pin theo dòng acc (field 4) > pool (XOAY theo lần thử để đổi proxy)
            if acc.get("proxy"):
                rp = acc["proxy"]
            elif proxies:
                rp = proxies[(i + t) % len(proxies)]
            else:
                rp = ""
            try:
                tag = f"[{i+1}/{n}]" + (f" ↻lần {t+1}" if t else "")
                log(f"{tag} {acc['email']}" + (f"  (proxy {rp.split(':')[0]})" if rp else ""))
                st, extra = login_one(acc, group_name, raw_proxy=rp, actions=actions,
                                      new_password=new_password, recreate=(t > 0), keep_open=keep_open,
                                      force_login=force_login, delete_after=delete_after)
                err = None
                break
            except Exception as e:  # noqa
                err = e
                if t < attempts - 1 and _is_retryable(str(e)) and not should_stop():
                    log(f"    ↻ {acc['email']} lỗi login: {str(e)[:60]} — thử lại proxy khác sau {config.RETRY_DELAY}s ({t+2}/{attempts})")
                    time.sleep(config.RETRY_DELAY)
                    continue
                break
        if st == "stopped" or (err is not None and should_stop()):
            rec.update(status="fail", reason="đã dừng theo yêu cầu")
            rec["line"] = f"{acc['email']}|{acc.get('pass','')}|{acc.get('twofa','')}"
            log(f"    ⏹ {acc['email']}: đã dừng")
        elif err is None:
            rec["status"] = "ok"
            acts = ["login"] if st != "already" else ["đã login sẵn"]
            errs = []
            for o in extra.get("ops", []):
                acts.append(o["name"] + (" ✓" if o["ok"] else " ✗"))
                if not o["ok"]:
                    errs.append(f"{o['name']}: {o.get('err', '')}")
            # dòng tài khoản MỚI: email|pass|2fa (pass/2fa mới nếu đã đổi)
            final_pass = extra.get("new_pass") or acc.get("pass", "")
            twofa = extra.get("new_2fa") or acc.get("twofa", "")
            rec["actions"] = acts
            rec["new_pass"] = extra.get("new_pass", "")
            rec["twofa"] = twofa
            rec["line"] = f"{acc['email']}|{final_pass}|{twofa}"
            rec["note"] = " | ".join(acts) + (("  —  " + "; ".join(errs)) if errs else "")
            save_result(acc["email"], "ok", rec["note"])
            save_account_line(rec["line"], acts)
            log(f"    ✅ {acc['email']} " + rec["note"] + f"  →  {rec['line']}")
        else:
            rec.update(status="fail", reason=str(err))
            rec["line"] = f"{acc['email']}|{acc.get('pass','')}|{acc.get('twofa','')}"
            save_result(acc["email"], "fail", str(err))
            log(f"    ❌ {acc['email']}: {err}")
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
        if not should_stop():
            time.sleep(config.DELAY_BETWEEN)

    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as ex:
        list(concurrent.futures.as_completed([ex.submit(work, i) for i in range(n)]))
    ok = sum(1 for r in results.values() if r.get("status") == "ok")
    fail = sum(1 for r in results.values() if r.get("status") == "fail")
    log(f"=== XONG: {ok} OK / {fail} lỗi (trên {n}) ===")
    write_history({"time": start_ts, "group": group_name, "total": n, "ok": ok, "failed": fail,
                   "accounts": [results.get(a["email"], {"email": a["email"]}) for a in accs]})
    return ok, fail


def load_proxies():
    """Đọc proxy pool từ data/proxies.txt (mỗi dòng ip:port:user:pass), gán vòng cho acc."""
    path = "data/proxies.txt"
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]


def main():
    accs = load_accounts()
    if not accs:
        print(f"Không có account trong {config.INPUT_FILE} (mỗi dòng: email|pass|2fa[|proxy])")
        return
    run_login(accs, group_name=config.GPM_GROUP, threads=config.THREADS, proxies=load_proxies())


if __name__ == "__main__":
    main()
