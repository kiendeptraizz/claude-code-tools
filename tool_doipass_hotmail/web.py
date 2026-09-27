# -*- coding: utf-8 -*-
"""Web UI (FastAPI) cho tool đổi mật khẩu Hotmail/Outlook hàng loạt.
Mở: http://127.0.0.1:8700   (chạy: run_web.bat). KHÔNG cần GPM (Playwright riêng).
"""
import os
import sys
import json
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa
    pass

from fastapi import FastAPI, Body
from fastapi.responses import HTMLResponse, JSONResponse

import config
import main as core

app = FastAPI(title="Hotmail Changer")

STATE = {"running": False, "mode": "", "done": 0, "total": 0, "ok": 0, "fail": 0,
         "logs": [], "results": [], "finished": False}
LOCK = threading.Lock()
LOG_MAX = 800
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_index.html")


def _log(line):
    with LOCK:
        STATE["logs"].append(line)
        ex = len(STATE["logs"]) - LOG_MAX
        if ex > 0:
            del STATE["logs"][:ex]


def _progress(d, t, a, b):
    with LOCK:
        STATE["done"], STATE["total"], STATE["ok"], STATE["fail"] = d, t, a, b


def _result(rec):
    with LOCK:
        STATE["results"].append(rec)


@app.get("/", response_class=HTMLResponse)
def index():
    try:
        with open(INDEX, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:  # noqa
        return HTMLResponse(f"<h3>Thiếu web_index.html: {e}</h3>", status_code=500)


@app.get("/api/status")
def api_status():
    with LOCK:
        return {"running": STATE["running"], "mode": STATE["mode"], "done": STATE["done"],
                "total": STATE["total"], "ok": STATE["ok"], "fail": STATE["fail"],
                "logs": STATE["logs"][-250:], "results": STATE["results"], "finished": STATE["finished"]}


@app.post("/api/run")
def api_run(payload: dict = Body(...)):
    with LOCK:
        if STATE["running"]:
            return JSONResponse({"ok": False, "error": "Đang chạy rồi"}, status_code=409)
    accs = core.parse_accounts_text(payload.get("accounts", "") or "")
    if not accs:
        return {"ok": False, "error": "Chưa có account (email|pass|refresh_token|client_id)"}
    mode = payload.get("mode", "change")
    threads = max(1, min(int(payload.get("threads", 1)), 8))
    proxies = [p.strip() for p in (payload.get("proxies", "") or "").splitlines()
               if p.strip() and not p.strip().startswith("#")]
    if not proxies:  # ô proxy trống -> proxy CHUNG (data/proxies.txt do Hub ghi)
        proxies = core.load_proxies()
    if payload.get("password_mode") == "random":
        config.PASSWORD_MODE = "random"
        config.RANDOM_LENGTH = int(payload.get("random_length", 14))
    else:
        config.PASSWORD_MODE = "fixed"
        np = (payload.get("new_password") or "").strip()
        if mode == "change" and not np:
            return {"ok": False, "error": "Chưa nhập mật khẩu mới (hoặc chọn ngẫu nhiên)"}
        if np:
            config.NEW_PASSWORD = np
    config.HEADLESS = bool(payload.get("headless", True))
    if mode == "change" and len(accs) < 2:
        return {"ok": False, "error": "Đổi pass cần ≥2 acc (recovery chéo). Chỉ test thì bấm 'Kiểm tra token'."}
    try:
        os.makedirs("data", exist_ok=True)
        with open(config.INPUT_FILE, "w", encoding="utf-8") as f:
            f.write(payload.get("accounts", "").strip() + "\n")
    except Exception:  # noqa
        pass
    with LOCK:
        STATE.update(running=True, mode=mode, done=0, total=0, ok=0, fail=0,
                     logs=[], results=[], finished=False)
    core.STOP_EVENT.clear()
    core.LOG_CALLBACK = _log

    def worker():
        try:
            if mode == "test":
                core.test_tokens(accs, on_progress=_progress)
            else:
                core.run_pipeline(accs, on_progress=_progress, threads=threads,
                                  on_result=_result, proxies=proxies)
        except Exception as e:  # noqa
            _log(f"LỖI: {e}")
        finally:
            core.LOG_CALLBACK = None
            with LOCK:
                STATE["running"] = False
                STATE["finished"] = True

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True}


@app.post("/api/stop")
def api_stop():
    core.STOP_EVENT.set()
    return {"ok": True}


@app.get("/api/history")
def api_history():
    runs = []
    p = core.HISTORY_FILE
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            runs.append(json.loads(line))
                        except Exception:  # noqa
                            pass
        except Exception:  # noqa
            pass
    return {"runs": runs[-50:][::-1]}
