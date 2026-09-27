# -*- coding: utf-8 -*-
"""Web UI (FastAPI) cho tool check Google Family — chạy ngay tại máy có GPM Login.
Mở:  http://localhost:8500   (hoặc http://<IP-máy>:8500 trong mạng LAN)

Chạy:  python -m uvicorn web:app --host 0.0.0.0 --port 8500
       (hoặc nhấp đúp run_web.bat)
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
import gpm
import main as core

app = FastAPI(title="Google Family Checker")

STATE = {
    "running": False, "group": "", "done": 0, "total": 0,
    "ok": 0, "fail": 0, "logs": [], "results": [], "finished": False,
}
LOCK = threading.Lock()
LOG_MAX = 800
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_index.html")


def _log(line):
    with LOCK:
        STATE["logs"].append(line)
        extra = len(STATE["logs"]) - LOG_MAX
        if extra > 0:
            del STATE["logs"][:extra]


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


@app.get("/api/ping")
def api_ping(port: int = 0):
    if port:
        config.GPM_PORT = port
    return {"ok": gpm.ping(), "port": config.GPM_PORT}


@app.get("/api/groups")
def api_groups(port: int = 0):
    if port:
        config.GPM_PORT = port
    try:
        gs = gpm.list_groups()
        return {"ok": True, "groups": [{"id": g.get("id"), "name": g.get("name")} for g in gs]}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}


@app.get("/api/profiles")
def api_profiles(group_id: int, port: int = 0):
    if port:
        config.GPM_PORT = port
    try:
        ps = gpm.list_profiles(group_id=group_id)
        return {"ok": True, "count": len(ps), "names": [p.get("name") for p in ps]}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}


@app.get("/api/status")
def api_status():
    with LOCK:
        return {
            "running": STATE["running"], "group": STATE["group"],
            "done": STATE["done"], "total": STATE["total"],
            "ok": STATE["ok"], "fail": STATE["fail"],
            "logs": STATE["logs"][-250:], "results": STATE["results"],
            "finished": STATE["finished"],
        }


@app.post("/api/run")
def api_run(payload: dict = Body(...)):
    with LOCK:
        if STATE["running"]:
            return JSONResponse({"ok": False, "error": "Đang chạy rồi"}, status_code=409)
    gid = payload.get("group_id")
    if gid is None:
        return {"ok": False, "error": "thiếu group_id"}
    gname = payload.get("group_name", "")
    config.GPM_PORT = int(payload.get("port", config.GPM_PORT))
    threads = max(1, min(int(payload.get("threads", 1)), 5))
    config.GET_MEMBER_EMAILS = bool(payload.get("get_emails", True))
    config.CLOSE_PROFILE_AFTER = bool(payload.get("close_after", True))
    mark = bool(payload.get("mark", False))
    with LOCK:
        STATE.update(running=True, group=gname, done=0, total=0, ok=0, fail=0,
                     logs=[], results=[], finished=False)
    core.STOP_EVENT.clear()
    core.LOG_CALLBACK = _log

    def worker():
        try:
            core.run_group(gid, gname, on_progress=_progress, threads=threads, on_result=_result, mark=mark)
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
    p = config.HISTORY_FILE
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
