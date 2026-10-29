# -*- coding: utf-8 -*-
"""Cấu hình tool check Google Family qua GPM Login."""

# ====== FILE ======
INPUT_FILE = "data/accounts.txt"      # mỗi dòng: email|pass|2fa(secret TOTP)
RESULT_FILE = "data/results.txt"      # email|vai_trò|số_tv|slot_trống|ds_email_tv
HISTORY_FILE = "data/history.jsonl"

# ====== LOGIN HÀNG LOẠT ======
LOGIN_RESULT_FILE = "data/login_results.txt"   # email|code|nhãn|lý_do
LOGIN_HISTORY_FILE = "data/login_history.jsonl"

# ====== PROXY ======
PROXY_FILE = "data/proxies.txt"        # proxy chung (hub ghi vào đây) — xoay vòng cho acc không ghi proxy riêng
CHECK_IP = True                        # mở xong profile thì kiểm tra IP thật (để biết proxy có ăn không)
IP_CHECK_URL = "https://api.ipify.org?format=text"

# ====== CHỜ XÁC MINH TAY (captcha / verify) ======
PAUSE_TIMEOUT = 600                    # giây tối đa chờ bạn xác minh tay 1 acc (10 phút) rồi tự bỏ qua

# ====== GPM LOGIN API ======
GPM_PORT = 19995                       # cổng API GPM Login (mặc định 19995)
GPM_BASE = f"http://127.0.0.1:{GPM_PORT}/api/v3"
WIN_SCALE = 0.8                        # tỉ lệ cửa sổ khi mở profile

# Tên profile GPM ứng với mỗi acc. {email} sẽ được thay bằng email.
# Tool tìm profile theo tên này; không thấy thì TẠO mới rồi tự đăng nhập.
PROFILE_NAME_TEMPLATE = "{email}"
GPM_GROUP = "All"                      # nhóm khi tạo profile mới

# ====== CHẠY ======
THREADS = 1                            # số profile mở song song (GPM nặng -> để 1-2)
DELAY_BETWEEN = 3                      # giây nghỉ giữa 2 acc
PAGE_TIMEOUT = 45000                   # ms
CLOSE_PROFILE_AFTER = True             # đóng profile GPM sau khi check xong

# ====== MỞ PROFILE / GẮN CDP (chống lỗi ECONNREFUSED khi nhiều luồng) ======
START_STAGGER = 2.0                    # giây giãn cách giữa 2 lần MỞ profile (GPM khỏi quá tải)
CDP_CONNECT_TRIES = 20                 # số lần thử gắn CDP (chờ cổng debug của Chrome mở)
CDP_CONNECT_DELAY = 1.5               # giây giữa 2 lần thử gắn CDP  (20 x 1.5 = ~30s chờ tối đa)

# ====== FAMILY ======
FAMILY_MAX = 6                         # tối đa 6 người (1 chủ + 5 thành viên)
FAMILY_URL = "https://families.google.com/families"
GET_MEMBER_EMAILS = True               # bấm vào từng thành viên để lấy email (chậm hơn ~vài giây/người)
