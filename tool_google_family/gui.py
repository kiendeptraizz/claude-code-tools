# -*- coding: utf-8 -*-
"""Giao diện check Google Family theo NHÓM profile GPM Login.
Chọn nhóm -> đọc mọi profile trong nhóm -> email đang login + thành viên family + slot trống.
Chạy: python gui.py  (hoặc nhấp đúp run_gui.bat)
"""
import os
import sys
import json
import queue
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa
    pass

import customtkinter as ctk

import config
import gpm
import main as core

SETTINGS_FILE = "settings.json"
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa
            pass
    return {}


def save_settings(d):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa
        pass


def open_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        os.startfile(os.path.abspath(path))
    except Exception:  # noqa
        pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Check Google Family theo nhóm (GPM Login)")
        self.geometry("1080x720")
        self.minsize(960, 620)
        self.msg_q = queue.Queue()
        self.worker = None
        self.settings = load_settings()
        self.groups = []                 # [{id,name}]
        self.group_by_display = {}       # "name · id N" -> {id,name}
        self.sel_group = None            # {id,name}
        self._build_ui()
        self._apply_settings_to_widgets()
        self.after(120, self._drain)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(400, self.on_load_groups)   # tự tải nhóm khi mở

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(self, text="👨‍👩‍👧 Check Google Family theo nhóm GPM",
                     font=ctk.CTkFont(size=20, weight="bold")).grid(
            row=0, column=0, columnspan=2, padx=16, pady=(14, 6), sticky="w")

        # ---- trái: chọn nhóm + xem profile ----
        left = ctk.CTkFrame(self)
        left.grid(row=1, column=0, rowspan=2, padx=(16, 8), pady=8, sticky="nsew")
        left.grid_rowconfigure(3, weight=1)
        left.grid_columnconfigure(0, weight=1)

        gr = ctk.CTkFrame(left, fg_color="transparent")
        gr.grid(row=0, column=0, padx=12, pady=(12, 4), sticky="ew")
        ctk.CTkLabel(gr, text="Nhóm:", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        self.group_menu = ctk.CTkOptionMenu(gr, values=["(bấm Tải nhóm)"], width=300,
                                            command=self.on_select_group)
        self.group_menu.pack(side="left", padx=8)
        ctk.CTkButton(gr, text="🔄 Tải nhóm", width=90, command=self.on_load_groups).pack(side="left")

        self.group_info = ctk.CTkLabel(left, text="", text_color="#9aa0a6")
        self.group_info.grid(row=1, column=0, padx=12, pady=(0, 2), sticky="w")

        ctk.CTkLabel(left, text="Profile trong nhóm:", font=ctk.CTkFont(size=12)).grid(
            row=2, column=0, padx=12, pady=(6, 2), sticky="w")
        self.preview = ctk.CTkTextbox(left, font=ctk.CTkFont(family="Consolas", size=11))
        self.preview.grid(row=3, column=0, padx=12, pady=(0, 6), sticky="nsew")
        self.preview.configure(state="disabled")

        note = ("ℹ️ Cần mở GPM Login (bật API). Chọn nhóm → tool mở từng profile trong nhóm, "
                "tự đọc email đang đăng nhập + thành viên family + slot trống (6 − số người). "
                "Profile chưa đăng nhập Google sẽ được báo 'chưa login' (tool KHÔNG tự đăng nhập).")
        ctk.CTkLabel(left, text=note, text_color="#8ab4f8", wraplength=540,
                     justify="left", font=ctk.CTkFont(size=11)).grid(
            row=4, column=0, padx=12, pady=(0, 10), sticky="w")

        # ---- phải: cài đặt ----
        right = ctk.CTkFrame(self)
        right.grid(row=1, column=1, padx=(8, 16), pady=8, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(right, text="⚙️  Cài đặt", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, padx=14, pady=(12, 8), sticky="w")

        row1 = ctk.CTkFrame(right, fg_color="transparent")
        row1.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="ew")
        ctk.CTkLabel(row1, text="Cổng API GPM:").pack(side="left")
        self.port_entry = ctk.CTkEntry(row1, width=80)
        self.port_entry.pack(side="left", padx=(6, 16))
        ctk.CTkLabel(row1, text="Số luồng:").pack(side="left")
        self.threads_entry = ctk.CTkEntry(row1, width=45)
        self.threads_entry.pack(side="left", padx=6)

        sw_fr = ctk.CTkFrame(right, fg_color="transparent")
        sw_fr.grid(row=2, column=0, padx=14, pady=(2, 10), sticky="w")
        self.close_sw = ctk.CTkSwitch(sw_fr, text="Đóng profile GPM sau khi check xong")
        self.close_sw.pack(anchor="w", pady=2)
        self.email_sw = ctk.CTkSwitch(sw_fr, text="Lấy cả email thành viên (lâu hơn ~10s/acc)")
        self.email_sw.pack(anchor="w", pady=2)

        self.btn_ping = ctk.CTkButton(right, text="🔌  Kiểm tra kết nối GPM",
                                      fg_color="#3a3f44", hover_color="#4a5056", command=self.on_ping)
        self.btn_ping.grid(row=3, column=0, padx=14, pady=(2, 6), sticky="ew")
        self.btn_start = ctk.CTkButton(right, text="▶  Bắt đầu check nhóm",
                                       font=ctk.CTkFont(size=14, weight="bold"), height=42,
                                       command=self.on_start)
        self.btn_start.grid(row=4, column=0, padx=14, pady=(0, 6), sticky="ew")
        self.btn_stop = ctk.CTkButton(right, text="⏹  Dừng", fg_color="#8a2b2b",
                                      hover_color="#a13434", state="disabled", command=self.on_stop)
        self.btn_stop.grid(row=5, column=0, padx=14, pady=(0, 10), sticky="ew")

        res_fr = ctk.CTkFrame(right, fg_color="transparent")
        res_fr.grid(row=6, column=0, padx=14, pady=(0, 10), sticky="ew")
        ctk.CTkButton(res_fr, text="📊 Kết quả", width=80, fg_color="#3a3f44", hover_color="#4a5056",
                      command=lambda: open_folder("data")).pack(side="left", padx=(0, 6))
        ctk.CTkButton(res_fr, text="🖼 Ảnh", width=70, fg_color="#3a3f44", hover_color="#4a5056",
                      command=lambda: open_folder("screenshots")).pack(side="left", padx=(0, 6))
        ctk.CTkButton(res_fr, text="📜 Lịch sử", width=80, fg_color="#3a3f44", hover_color="#4a5056",
                      command=self.show_history).pack(side="left")

        # ---- dưới phải: tiến trình + log ----
        bottom = ctk.CTkFrame(self)
        bottom.grid(row=2, column=1, padx=(8, 16), pady=(0, 8), sticky="nsew")
        bottom.grid_rowconfigure(2, weight=1)
        bottom.grid_columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(bottom)
        self.progress.set(0)
        self.progress.grid(row=0, column=0, padx=12, pady=(12, 4), sticky="ew")
        self.counter = ctk.CTkLabel(bottom, text="Sẵn sàng", font=ctk.CTkFont(size=13, weight="bold"))
        self.counter.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="w")
        self.log_box = ctk.CTkTextbox(bottom, font=ctk.CTkFont(family="Consolas", size=11), wrap="word")
        self.log_box.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self.log_box.configure(state="disabled")

    # ---- settings ----
    def _apply_settings_to_widgets(self):
        s = self.settings
        self.port_entry.insert(0, str(s.get("gpm_port", config.GPM_PORT)))
        self.threads_entry.insert(0, str(s.get("threads", config.THREADS)))
        if s.get("close_after", config.CLOSE_PROFILE_AFTER):
            self.close_sw.select()
        if s.get("get_emails", config.GET_MEMBER_EMAILS):
            self.email_sw.select()

    def _apply_to_config(self):
        try:
            port = int(self.port_entry.get().strip() or 19995)
        except ValueError:
            port = 19995
        try:
            threads = max(1, min(int(self.threads_entry.get().strip() or 1), 5))
        except ValueError:
            threads = 1
        config.GPM_PORT = port
        config.THREADS = threads
        config.CLOSE_PROFILE_AFTER = bool(self.close_sw.get())
        config.GET_MEMBER_EMAILS = bool(self.email_sw.get())
        save_settings({"gpm_port": port, "threads": threads,
                       "close_after": config.CLOSE_PROFILE_AFTER,
                       "get_emails": config.GET_MEMBER_EMAILS})
        return threads

    # ---- nhóm ----
    def on_load_groups(self):
        self._apply_to_config()
        self._log("🔄 Đang tải danh sách nhóm từ GPM...")

        def task():
            if not gpm.ping():
                self.msg_q.put(("log", "❌ Chưa kết nối được GPM. Mở GPM Login + bật API (cổng %d)."
                                % config.GPM_PORT))
                return
            try:
                groups = gpm.list_groups()
                self.msg_q.put(("groups", groups))
            except Exception as e:  # noqa
                self.msg_q.put(("log", f"❌ Lỗi tải nhóm: {e}"))
        threading.Thread(target=task, daemon=True).start()

    def on_select_group(self, display):
        g = self.group_by_display.get(display)
        if not g:
            return
        self.sel_group = g
        self.group_info.configure(text="Đang đếm profile...")

        def task():
            try:
                profs = gpm.list_profiles(group_id=g["id"])
                names = [p.get("name", "?") for p in profs]
                self.msg_q.put(("preview", g, names))
            except Exception as e:  # noqa
                self.msg_q.put(("log", f"❌ Lỗi đọc profile nhóm: {e}"))
        threading.Thread(target=task, daemon=True).start()

    # ---- chạy ----
    def _set_running(self, running):
        st = "disabled" if running else "normal"
        self.btn_start.configure(state=st)
        self.btn_ping.configure(state=st)
        self.btn_stop.configure(state="normal" if running else "disabled")

    def on_ping(self):
        self._apply_to_config()
        self._log("🔌 Đang kiểm tra GPM Login...")

        def chk():
            ok = gpm.ping()
            self.msg_q.put(("log", "✅ GPM Login OK!" if ok
                            else "❌ Không kết nối được GPM. Mở GPM Login + bật API."))
        threading.Thread(target=chk, daemon=True).start()

    def on_start(self):
        if not self.sel_group:
            self._log("⚠️  Chưa chọn nhóm! Bấm 🔄 Tải nhóm rồi chọn 1 nhóm.")
            return
        threads = self._apply_to_config()
        self._clear_log()
        self.progress.set(0)
        self._set_running(True)
        core.LOG_CALLBACK = lambda line: self.msg_q.put(("log", line))
        g = self.sel_group
        self.worker = threading.Thread(
            target=self._run_target, args=(g["id"], g.get("name", ""), threads), daemon=True)
        self.worker.start()

    def _run_target(self, gid, gname, threads):
        try:
            core.run_group(gid, gname,
                           on_progress=lambda d, t, a, b: self.msg_q.put(("prog", d, t, a, b)),
                           threads=threads)
        except Exception as e:  # noqa
            self.msg_q.put(("log", f"LỖI: {e}"))
        finally:
            self.msg_q.put(("done",))

    def on_stop(self):
        core.STOP_EVENT.set()
        self._log("⏹  Đang dừng...")

    def show_history(self):
        HistoryWindow(self)

    # ---- log / queue ----
    def _drain(self):
        try:
            while True:
                item = self.msg_q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._log(item[1])
                elif kind == "prog":
                    _, d, t, a, b = item
                    self.progress.set(d / t if t else 0)
                    self.counter.configure(text=f"✅ {a}   ❌ {b}   ({d}/{t})")
                elif kind == "done":
                    self._set_running(False)
                    core.LOG_CALLBACK = None
                elif kind == "groups":
                    self._populate_groups(item[1])
                elif kind == "preview":
                    self._show_preview(item[1], item[2])
        except queue.Empty:
            pass
        self.after(120, self._drain)

    def _populate_groups(self, groups):
        self.groups = groups or []
        self.group_by_display = {}
        displays = []
        for g in self.groups:
            disp = f"{g.get('name', '?')}  ·  id {g.get('id')}"
            self.group_by_display[disp] = {"id": g.get("id"), "name": g.get("name", "")}
            displays.append(disp)
        if displays:
            self.group_menu.configure(values=displays)
            self.group_menu.set(displays[0])
            self.on_select_group(displays[0])
            self._log(f"✅ Đã tải {len(displays)} nhóm. Chọn nhóm rồi bấm ▶ Bắt đầu.")
        else:
            self.group_menu.configure(values=["(không có nhóm)"])
            self._log("⚠️ Không có nhóm nào.")

    def _show_preview(self, g, names):
        self.group_info.configure(text=f"Nhóm '{g.get('name','')}' — {len(names)} profile")
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", "\n".join(names) if names else "(nhóm trống)")
        self.preview.configure(state="disabled")

    def _log(self, line):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _on_close(self):
        core.STOP_EVENT.set()
        self.destroy()


class HistoryWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("📜 Lịch sử check family")
        self.geometry("820x560")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, padx=12, pady=(12, 4), sticky="ew")
        ctk.CTkLabel(top, text="Lịch sử (mới nhất ở trên)",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")
        ctk.CTkButton(top, text="🔄 Tải lại", width=80, command=self._load).pack(side="right")
        self.box = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Consolas", size=12), wrap="word")
        self.box.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self._load()
        self.after(200, self.lift)

    def _load(self):
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        path = config.HISTORY_FILE
        runs = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                runs.append(json.loads(line))
                            except Exception:  # noqa
                                pass
            except Exception:  # noqa
                pass
        if not runs:
            self.box.insert("end", "Chưa có lịch sử.\n")
        for r in reversed(runs):
            self.box.insert("end", f"🕒 {r.get('time','?')}   nhóm '{r.get('group','')}'   "
                                   f"✅ {r.get('ok',0)} đọc được / ⏭ {r.get('skip',0)} chưa login / "
                                   f"❌ {r.get('failed',0)} lỗi\n")
            for a in r.get("profiles", []):
                st = a.get("status")
                if st == "ok":
                    mem = a.get("members") or []
                    self.box.insert("end", f"      ✅ {a.get('profile',''):<20} {a.get('email','?'):<30} "
                                           f"{a.get('role','?')} | {a.get('member_count',0)} tv | "
                                           f"còn {a.get('free_slots','?')} slot"
                                           + (f"  [{', '.join(mem)}]" if mem else "") + "\n")
                elif st == "skip":
                    self.box.insert("end", f"      ⏭ {a.get('profile',''):<20} chưa đăng nhập Google\n")
                elif st == "fail":
                    self.box.insert("end", f"      ❌ {a.get('profile',''):<20} {a.get('reason','')[:50]}\n")
            self.box.insert("end", "─" * 90 + "\n")
        self.box.configure(state="disabled")


if __name__ == "__main__":
    App().mainloop()
