# -*- coding: utf-8 -*-
"""Cấu hình tool login CapCut hàng loạt qua GPM Login."""

INPUT_FILE = "data/accounts.txt"        # mỗi dòng: email|pass[|2fa][|proxy]
RESULT_FILE = "data/results.txt"
HISTORY_FILE = "data/history.jsonl"

# GPM Login API
GPM_PORT = 19995
GPM_GROUP = "All"                        # nhóm mặc định khi tạo profile
WIN_SCALE = 0.8

# chạy
THREADS = 1
DELAY_BETWEEN = 5                        # giây nghỉ giữa 2 acc
PAGE_TIMEOUT = 60000                     # ms (CapCut/ByteDance có thể chậm + captcha)
CLOSE_PROFILE_AFTER = True

# URL CapCut
LOGIN_URL = "https://www.capcut.com/login"
CAPCUT_URL = "https://www.capcut.com/"
