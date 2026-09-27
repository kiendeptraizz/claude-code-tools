# -*- coding: utf-8 -*-
"""Hub tổng hợp các tool MMO — 1 trang chọn tool, tự khởi động tool khi bấm.
Mở:  http://127.0.0.1:8000   (chạy: run_hub.bat)
Mỗi tool là 1 web app FastAPI riêng (cổng riêng); hub spawn uvicorn của tool đó khi cần
rồi nhúng vào iframe.
"""
import os
import sys
import json
import socket
import subprocess
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa
    pass

from fastapi import FastAPI, Body
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Tool MMO Hub")

BASE = r"C:\claude code"
TOOLS = {
    "chatgpt": {"name": "Login ChatGPT", "dir": os.path.join(BASE, "tool_chatgpt_login"),
                "port": 8600, "icon": "🤖", "desc": "Login OpenAI + hủy gói / xóa chat / đổi pass / logout"},
    "capcut":  {"name": "Login CapCut",  "dir": os.path.join(BASE, "tool_capcut_login"),
                "port": 8080, "icon": "🎬", "desc": "Login CapCut (email + mật khẩu)"},
    "google":  {"name": "Check Google Family", "dir": os.path.join(BASE, "tool_google_family"),
                "port": 8500, "icon": "👨‍👩‍👧", "desc": "Đọc thành viên + slot trống Google Family"},
    "hotmail": {"name": "Đổi mật khẩu Hotmail", "dir": os.path.join(BASE, "tool_doipass_hotmail"),
                "port": 8700, "icon": "📧", "desc": "Đổi pass Outlook/Hotmail hàng loạt (KHÔNG cần GPM)"},
}
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hub_index.html")
SHARED_PROXY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "shared_proxies.txt")


def _listening(port):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", int(port))) == 0
    except Exception:  # noqa
        return False
    finally:
        s.close()


def _spawn(t):
    """Khởi động uvicorn của 1 tool (không mở browser, không cửa sổ). stdio -> file log để uvicorn không chết."""
    py = os.path.join(t["dir"], "venv", "Scripts", "python.exe")
    if not os.path.exists(py):
        raise RuntimeError(f"thiếu venv: {py}")
    os.makedirs(os.path.join(t["dir"], "logs"), exist_ok=True)
    logf = open(os.path.join(t["dir"], "logs", "hub_server.log"), "a", encoding="utf-8")
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [py, "-m", "uvicorn", "web:app", "--host", "127.0.0.1", "--port", str(t["port"])],
        cwd=t["dir"], stdout=logf, stderr=logf, stdin=subprocess.DEVNULL, creationflags=flags,
    )


def _kill_port(port):
    """Kill tiến trình đang NGHE cổng (Windows) để nạp lại code mới cho tool."""
    killed = 0
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:  # noqa
        return 0
    pids = set()
    for line in out.splitlines():
        if f":{port} " in line and "LISTENING" in line.upper():
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.add(parts[-1])
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True, timeout=10)
            killed += 1
        except Exception:  # noqa
            pass
    return killed


@app.get("/api/restart")
def api_restart(tool: str):
    """Nạp lại CODE MỚI: kill server tool đang chạy (code cũ) rồi spawn lại. Client poll /api/ready."""
    t = TOOLS.get(tool)
    if not t:
        return JSONResponse({"ok": False, "error": "tool không tồn tại"}, status_code=400)
    killed = _kill_port(t["port"])
    time.sleep(1.5)   # chờ cổng nhả
    try:
        _spawn(t)
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}
    return {"ok": True, "killed": killed, "url": f"http://127.0.0.1:{t['port']}/"}


@app.get("/", response_class=HTMLResponse)
def index():
    try:
        with open(INDEX, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:  # noqa
        return HTMLResponse(f"<h3>Thiếu hub_index.html: {e}</h3>", status_code=500)


@app.get("/api/tools")
def api_tools():
    return {"tools": [{"key": k, "name": v["name"], "port": v["port"], "icon": v["icon"],
                       "desc": v["desc"], "running": _listening(v["port"])}
                      for k, v in TOOLS.items()]}


@app.get("/api/start")
def api_start(tool: str):
    """Spawn tool nếu chưa chạy rồi TRẢ VỀ NGAY (không chờ) — client tự poll /api/ready.
    Tránh request treo lâu gây 'Failed to fetch' trên trình duyệt."""
    t = TOOLS.get(tool)
    if not t:
        return JSONResponse({"ok": False, "error": "tool không tồn tại"}, status_code=400)
    running = _listening(t["port"])
    if not running:
        try:
            _spawn(t)
        except Exception as e:  # noqa
            return {"ok": False, "error": str(e)}
    return {"ok": True, "url": f"http://127.0.0.1:{t['port']}/", "running": running}


@app.get("/api/ready")
def api_ready(tool: str):
    t = TOOLS.get(tool)
    if not t:
        return JSONResponse({"ready": False, "error": "tool không tồn tại"}, status_code=400)
    return {"ready": _listening(t["port"]), "url": f"http://127.0.0.1:{t['port']}/"}


@app.get("/api/proxies")
def api_get_proxies():
    txt = ""
    if os.path.exists(SHARED_PROXY):
        try:
            with open(SHARED_PROXY, "r", encoding="utf-8") as f:
                txt = f.read()
        except Exception:  # noqa
            pass
    return {"proxies": txt}


@app.post("/api/proxies")
def api_set_proxies(payload: dict = Body(...)):
    """Lưu proxy CHUNG + đẩy vào data/proxies.txt của TẤT CẢ tool (xoay vòng khi tool chạy)."""
    txt = (payload.get("proxies") or "").strip()
    os.makedirs(os.path.dirname(SHARED_PROXY), exist_ok=True)
    with open(SHARED_PROXY, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    n = 0
    for t in TOOLS.values():
        try:
            d = os.path.join(t["dir"], "data")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "proxies.txt"), "w", encoding="utf-8") as f:
                f.write(txt + "\n")
            n += 1
        except Exception:  # noqa
            pass
    cnt = len([l for l in txt.splitlines() if l.strip() and not l.strip().startswith("#")])
    return {"ok": True, "count": cnt, "tools": n}


def _read_history(tooldir):
    p = os.path.join(tooldir, "data", "history.jsonl")
    runs = []
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
    return runs


@app.get("/api/search")
def api_search(q: str = ""):
    """Tra cứu 1 email/chuỗi qua LỊCH SỬ của TẤT CẢ tool → gom mọi bản ghi khớp."""
    q = (q or "").strip().lower()
    if not q:
        return {"results": [], "count": 0}
    out = []
    for key, t in TOOLS.items():
        for run in _read_history(t["dir"]):
            items = run.get("accounts") or run.get("profiles") or []
            for a in items:
                parts = [str(a.get(k, "")) for k in ("email", "line", "profile", "note", "newpass", "role")]
                mem = a.get("members")
                if isinstance(mem, list):
                    parts.append(" ".join(str(m) for m in mem))
                if q in " ".join(parts).lower():
                    out.append({"tool": t["name"], "toolKey": key, "icon": t["icon"],
                                "time": run.get("time", ""), "rec": a})
    out.sort(key=lambda x: x.get("time", ""), reverse=True)
    return {"results": out, "count": len(out)}
