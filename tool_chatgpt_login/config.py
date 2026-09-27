# -*- coding: utf-8 -*-
"""Cấu hình tool login ChatGPT (OpenAI) hàng loạt qua GPM Login."""

INPUT_FILE = "data/accounts.txt"        # mỗi dòng: email|pass|2fa[|proxy]
RESULT_FILE = "data/results.txt"
HISTORY_FILE = "data/history.jsonl"

# GPM Login API
GPM_PORT = 19995
GPM_GROUP = "All"                        # nhóm mặc định khi tạo profile
WIN_SCALE = 0.8

# chạy
THREADS = 1
DELAY_BETWEEN = 5                        # giây nghỉ giữa 2 acc (login OpenAI nên chậm)
PAGE_TIMEOUT = 60000                     # ms (OpenAI + Cloudflare hay chậm)
CLOSE_PROFILE_AFTER = True

# retry khi LOGIN lỗi (Cloudflare/mạng) — chỉ áp dụng cho lỗi ở bước đăng nhập, KHÔNG retry thao tác
LOGIN_RETRIES = 2                        # số lần thử LẠI (tổng số lần = 1 + LOGIN_RETRIES)
RETRY_DELAY = 8                          # giây chờ trước khi thử lại
CF_WAIT = 20                             # giây tối đa chờ Cloudflare tự qua (fingerprint GPM)

# URL
LOGIN_URL = "https://auth.openai.com/log-in"
CHATGPT_URL = "https://chatgpt.com/"
