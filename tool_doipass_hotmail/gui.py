# -*- coding: utf-8 -*-
"""
Giao diện đổi mật khẩu Hotmail/Outlook hàng loạt.
Chạy:  python gui.py   (hoặc nhấp đúp run_gui.bat)

Mọi thao tác làm trong 1 cửa sổ: dán acc -> đặt pass -> bấm chạy -> xem log.
"""
import os
import sys
import json
import queue
import threading
import subprocess

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa
    pass

import customtkinter as ctk

import config
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
        os.startfile(os.path.abspath(path))  # Windows
    except Exception:  # noqa
        pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Đổi mật khẩu Hotmail / Outlook hàng loạt")
        self.geometry("1040x720")
        self.minsize(900, 620)

        self.msg_q = queue.Queue()
        self.worker = None
        self.settings = load_settings()

        self._build_ui()
        self._load_accounts_into_box()
        self._apply_settings_to_widgets()

        # bơm log realtime
        self.after(120, self._drain)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- UI ----------------
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # ----- tiêu đề -----
        header = ctk.CTkLabel(
            self, text="🔐  Đổi mật khẩu Hotmail / Outlook hàng loạt",
            font=ctk.CTkFont(size=20, weight="bold"))
        header.grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 6), sticky="w")

        # ----- cột trái: ô dán account -----
        left = ctk.CTkFrame(self)
        left.grid(row=1, column=0, rowspan=2, padx=(16, 8), pady=8, sticky="nsew")
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            left, text="Dán tài khoản (mỗi dòng 1 acc):  email|pass|refresh_token|client_id",
            font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, padx=12, pady=(12, 4), sticky="w")

        self.acc_box = ctk.CTkTextbox(left, font=ctk.CTkFont(family="Consolas", size=12))
        self.acc_box.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="nsew")

        self.acc_count = ctk.CTkLabel(left, text="0 tài khoản", text_color="#9aa0a6")
        self.acc_count.grid(row=2, column=0, padx=12, pady=(0, 2), sticky="w")
        self.acc_box.bind("<KeyRelease>", lambda e: self._update_acc_count())

        note = ("ℹ️ Microsoft bắt thêm email khôi phục trước khi cho đổi pass. Tool tự lấy các "
                "Hotmail làm email khôi phục CHÉO theo chuỗi (acc1→acc2→…→acc cuối→acc1), tự đọc "
                "mã xác minh qua token rồi đổi pass — gọn trong 1 lần/acc. Cần ≥2 acc. Lưu ý: acc "
                "CUỐI trong danh sách có thể phải đổi thủ công (đã hết acc còn token để nhận mã).")
        ctk.CTkLabel(left, text=note, text_color="#8ab4f8", wraplength=520,
                     justify="left", font=ctk.CTkFont(size=11)).grid(
            row=3, column=0, padx=12, pady=(0, 10), sticky="w")

        # ----- cột phải: cài đặt + nút -----
        right = ctk.CTkFrame(self)
        right.grid(row=1, column=1, padx=(8, 16), pady=8, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="⚙️  Cài đặt",
                     font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, padx=14, pady=(12, 8), sticky="w")

        # chế độ mật khẩu
        ctk.CTkLabel(right, text="Kiểu mật khẩu mới:").grid(
            row=1, column=0, padx=14, pady=(2, 2), sticky="w")
        self.mode = ctk.CTkSegmentedButton(
            right, values=["Chung 1 pass", "Ngẫu nhiên"],
            command=lambda v: self._toggle_mode())
        self.mode.grid(row=2, column=0, padx=14, pady=(0, 8), sticky="ew")

        # ô nhập pass chung
        self.pass_entry = ctk.CTkEntry(right, placeholder_text="Mật khẩu mới (vd: Doipass@2026Abc)")
        self.pass_entry.grid(row=3, column=0, padx=14, pady=(0, 4), sticky="ew")
        self.pass_hint = ctk.CTkLabel(
            right, text="Cần ≥8 ký tự, có hoa+thường+số+ký tự đặc biệt.",
            text_color="#9aa0a6", font=ctk.CTkFont(size=11))
        self.pass_hint.grid(row=4, column=0, padx=14, pady=(0, 8), sticky="w")

        # độ dài random
        self.len_frame = ctk.CTkFrame(right, fg_color="transparent")
        self.len_frame.grid(row=5, column=0, padx=14, pady=(0, 8), sticky="ew")
        ctk.CTkLabel(self.len_frame, text="Độ dài pass ngẫu nhiên:").pack(side="left")
        self.len_entry = ctk.CTkEntry(self.len_frame, width=60)
        self.len_entry.pack(side="left", padx=8)

        # hiện trình duyệt
        self.headless_sw = ctk.CTkSwitch(right, text="Chạy ẩn trình duyệt (headless)")
        self.headless_sw.grid(row=6, column=0, padx=14, pady=(2, 8), sticky="w")

        # nghỉ giữa acc + số luồng
        delay_fr = ctk.CTkFrame(right, fg_color="transparent")
        delay_fr.grid(row=7, column=0, padx=14, pady=(0, 8), sticky="ew")
        ctk.CTkLabel(delay_fr, text="Nghỉ (giây):").pack(side="left")
        self.delay_entry = ctk.CTkEntry(delay_fr, width=45)
        self.delay_entry.pack(side="left", padx=(6, 14))
        ctk.CTkLabel(delay_fr, text="Số luồng song song:").pack(side="left")
        self.threads_entry = ctk.CTkEntry(delay_fr, width=45)
        self.threads_entry.pack(side="left", padx=6)

        # proxy
        self.proxy_entry = ctk.CTkEntry(
            right, placeholder_text="Proxy (tùy chọn): ip:port:user:pass")
        self.proxy_entry.grid(row=8, column=0, padx=14, pady=(0, 12), sticky="ew")

        # nút hành động
        self.btn_test = ctk.CTkButton(
            right, text="🔎  Kiểm tra token", fg_color="#3a3f44", hover_color="#4a5056",
            command=self.on_test)
        self.btn_test.grid(row=9, column=0, padx=14, pady=(4, 6), sticky="ew")

        self.btn_start = ctk.CTkButton(
            right, text="🚀  Bắt đầu đổi mật khẩu",
            font=ctk.CTkFont(size=14, weight="bold"), height=42,
            command=self.on_start)
        self.btn_start.grid(row=10, column=0, padx=14, pady=(0, 6), sticky="ew")

        self.btn_stop = ctk.CTkButton(
            right, text="⏹  Dừng", fg_color="#8a2b2b", hover_color="#a13434",
            state="disabled", command=self.on_stop)
        self.btn_stop.grid(row=11, column=0, padx=14, pady=(0, 10), sticky="ew")

        res_fr = ctk.CTkFrame(right, fg_color="transparent")
        res_fr.grid(row=12, column=0, padx=14, pady=(0, 10), sticky="ew")
        ctk.CTkButton(res_fr, text="📁 Kết quả", width=90, fg_color="#3a3f44",
                      hover_color="#4a5056",
                      command=lambda: open_folder("data")).pack(side="left", padx=(0, 6))
        ctk.CTkButton(res_fr, text="🖼 Ảnh lỗi", width=80, fg_color="#3a3f44",
                      hover_color="#4a5056",
                      command=lambda: open_folder("screenshots")).pack(side="left", padx=(0, 6))
        ctk.CTkButton(res_fr, text="📜 Lịch sử", width=80, fg_color="#3a3f44",
                      hover_color="#4a5056",
                      command=self.show_history).pack(side="left")

        # ----- log + tiến trình (full width dưới cùng) -----
        bottom = ctk.CTkFrame(self)
        bottom.grid(row=2, column=1, padx=(8, 16), pady=(0, 8), sticky="nsew")
        bottom.grid_rowconfigure(2, weight=1)
        bottom.grid_columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(bottom)
        self.progress.set(0)
        self.progress.grid(row=0, column=0, padx=12, pady=(12, 4), sticky="ew")

        self.counter = ctk.CTkLabel(
            bottom, text="Sẵn sàng", font=ctk.CTkFont(size=13, weight="bold"))
        self.counter.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="w")

        self.log_box = ctk.CTkTextbox(
            bottom, font=ctk.CTkFont(family="Consolas", size=11), wrap="word")
        self.log_box.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self.log_box.configure(state="disabled")

    # ---------------- settings ----------------
    def _apply_settings_to_widgets(self):
        s = self.settings
        self.mode.set("Ngẫu nhiên" if s.get("password_mode") == "random" else "Chung 1 pass")
        self.pass_entry.insert(0, s.get("new_password", config.NEW_PASSWORD))
        self.len_entry.insert(0, str(s.get("random_length", config.RANDOM_LENGTH)))
        self.delay_entry.insert(0, str(s.get("delay", config.DELAY_BETWEEN)))
        self.threads_entry.insert(0, str(s.get("threads", 2)))
        if s.get("proxy"):
            self.proxy_entry.insert(0, s["proxy"])
        if s.get("headless"):
            self.headless_sw.select()
        self._toggle_mode()
        self._update_acc_count()

    def _collect_settings(self):
        mode = "random" if self.mode.get() == "Ngẫu nhiên" else "fixed"
        try:
            rlen = int(self.len_entry.get().strip() or 14)
        except ValueError:
            rlen = 14
        try:
            delay = int(self.delay_entry.get().strip() or 5)
        except ValueError:
            delay = 5
        try:
            threads = max(1, min(int(self.threads_entry.get().strip() or 2), 8))
        except ValueError:
            threads = 2
        return {
            "password_mode": mode,
            "new_password": self.pass_entry.get().strip(),
            "random_length": rlen,
            "delay": delay,
            "threads": threads,
            "headless": bool(self.headless_sw.get()),
            "proxy": self.proxy_entry.get().strip(),
        }

    def _apply_to_config(self):
        s = self._collect_settings()
        config.PASSWORD_MODE = s["password_mode"]
        config.NEW_PASSWORD = s["new_password"]
        config.RANDOM_LENGTH = s["random_length"]
        config.DELAY_BETWEEN = s["delay"]
        config.HEADLESS = s["headless"]
        config.PROXY = s["proxy"] or None
        save_settings(s)
        return s

    def _toggle_mode(self):
        if self.mode.get() == "Ngẫu nhiên":
            self.pass_entry.configure(state="disabled")
            self.pass_hint.configure(text="Mỗi acc 1 mật khẩu ngẫu nhiên — xem ở data/success.txt")
            for w in self.len_frame.winfo_children():
                try:
                    w.configure(state="normal")
                except Exception:  # noqa
                    pass
        else:
            self.pass_entry.configure(state="normal")
            self.pass_hint.configure(text="Cần ≥8 ký tự, có hoa+thường+số+ký tự đặc biệt.")

    # ---------------- account box ----------------
    def _load_accounts_into_box(self):
        if os.path.exists(config.INPUT_FILE):
            try:
                with open(config.INPUT_FILE, "r", encoding="utf-8") as f:
                    txt = "\n".join(
                        ln for ln in f.read().splitlines()
                        if ln.strip() and not ln.strip().startswith("#"))
                self.acc_box.insert("1.0", txt)
            except Exception:  # noqa
                pass

    def _get_accounts(self):
        text = self.acc_box.get("1.0", "end")
        return core.parse_accounts_text(text)

    def _save_accounts_box(self):
        try:
            os.makedirs("data", exist_ok=True)
            with open(config.INPUT_FILE, "w", encoding="utf-8") as f:
                f.write(self.acc_box.get("1.0", "end").strip() + "\n")
        except Exception:  # noqa
            pass

    def _update_acc_count(self):
        n = len(self._get_accounts())
        self.acc_count.configure(text=f"{n} tài khoản")

    # ---------------- chạy ----------------
    def _set_running(self, running):
        st = "disabled" if running else "normal"
        self.btn_start.configure(state=st)
        self.btn_test.configure(state=st)
        self.btn_stop.configure(state="normal" if running else "disabled")

    def _start_worker(self, target, **kwargs):
        accs = self._get_accounts()
        if not accs:
            self._log("⚠️  Chưa có tài khoản nào! Dán acc vào ô bên trái.")
            return
        self._apply_to_config()
        self._save_accounts_box()
        self._clear_log()
        self.progress.set(0)
        self._set_running(True)
        core.LOG_CALLBACK = lambda line: self.msg_q.put(("log", line))
        self.worker = threading.Thread(
            target=self._run_target, args=(target, accs, kwargs), daemon=True)
        self.worker.start()

    def _run_target(self, target, accs, kwargs):
        try:
            target(accs, on_progress=lambda d, t, a, b: self.msg_q.put(("prog", d, t, a, b)),
                   **kwargs)
        except Exception as e:  # noqa
            self.msg_q.put(("log", f"LỖI: {e}"))
        finally:
            self.msg_q.put(("done",))

    def on_start(self):
        threads = self._collect_settings()["threads"]
        self._start_worker(core.run_pipeline, threads=threads)

    def on_test(self):
        self._start_worker(core.test_tokens)

    def show_history(self):
        HistoryWindow(self)

    def on_stop(self):
        core.STOP_EVENT.set()
        self._log("⏹  Đang dừng... (chờ acc hiện tại xong)")

    # ---------------- log realtime ----------------
    def _drain(self):
        try:
            while True:
                item = self.msg_q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._log(item[1])
                elif kind == "prog":
                    _, done, total, a, b = item
                    self.progress.set(done / total if total else 0)
                    self.counter.configure(text=f"✅ {a}   ❌ {b}   ({done}/{total})")
                elif kind == "done":
                    self._set_running(False)
                    core.LOG_CALLBACK = None
        except queue.Empty:
            pass
        self.after(120, self._drain)

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
    """Cửa sổ xem lịch sử các lần chạy (đọc data/history.jsonl)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("📜 Lịch sử các lần chạy")
        self.geometry("760x540")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, padx=12, pady=(12, 4), sticky="ew")
        ctk.CTkLabel(top, text="Lịch sử (mới nhất ở trên)",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")
        ctk.CTkButton(top, text="🔄 Tải lại", width=80, command=self._load).pack(side="right")
        ctk.CTkButton(top, text="📁 Mở file", width=90, fg_color="#3a3f44",
                      command=lambda: open_folder("data")).pack(side="right", padx=6)

        self.box = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Consolas", size=12), wrap="word")
        self.box.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self._load()
        self.after(200, self.lift)

    def _load(self):
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        path = core.HISTORY_FILE
        if not os.path.exists(path):
            self.box.insert("end", "Chưa có lịch sử lần chạy nào.\n")
            self.box.configure(state="disabled")
            return
        runs = []
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
            self.box.insert("end", "Chưa có lịch sử lần chạy nào.\n")
        for r in reversed(runs):
            self.box.insert("end", f"🕒 {r.get('time','?')}    "
                                   f"✅ {r.get('success',0)} thành công   "
                                   f"❌ {r.get('failed',0)} lỗi   "
                                   f"({r.get('total','?')} acc, {r.get('threads','?')} luồng)\n")
            for a in r.get("accounts", []):
                st = a.get("status")
                mark = "✅" if st == "ok" else ("❌" if st == "fail" else "•")
                detail = ""
                if st == "ok":
                    tok = "token mới ✓" if a.get("new_token") else "token mới ✗"
                    detail = f"pass: {a.get('newpass','?')} | {tok}"
                elif st == "fail":
                    detail = f"lỗi: {a.get('reason','')[:60]}"
                self.box.insert("end", f"      {mark} {a.get('email','?'):<38} {detail}\n")
            self.box.insert("end", "─" * 80 + "\n")
        self.box.configure(state="disabled")


if __name__ == "__main__":
    App().mainloop()
