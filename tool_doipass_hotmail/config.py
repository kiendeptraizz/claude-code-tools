# -*- coding: utf-8 -*-
"""
Cấu hình cho tool đổi mật khẩu Hotmail/Outlook hàng loạt.
Sửa các giá trị bên dưới cho phù hợp nhu cầu của bạn.
"""

# ============ FILE ============
# File chứa account, mỗi dòng 1 acc, định dạng:
#   email|password|refresh_token|client_id
INPUT_FILE = "data/accounts.txt"

# Kết quả
SUCCESS_FILE = "data/success.txt"   # email|pass_moi|refresh_token|client_id
FAILED_FILE = "data/failed.txt"     # email|pass_cu|...|LY_DO_LOI

# ============ MẬT KHẨU MỚI ============
# Cách sinh mật khẩu mới:
#   "fixed"  -> tất cả acc dùng chung 1 mật khẩu (NEW_PASSWORD)
#   "random" -> mỗi acc 1 mật khẩu ngẫu nhiên mạnh
PASSWORD_MODE = "fixed"

NEW_PASSWORD = "Doipass@2026Abc"   # dùng khi PASSWORD_MODE = "fixed"

RANDOM_LENGTH = 14                  # dùng khi PASSWORD_MODE = "random"

# ============ CHẠY ============
HEADLESS = False        # False = hiện trình duyệt (nên để False lúc test); True = chạy ngầm
SLOW_MO = 80            # ms chậm lại giữa các thao tác cho giống người + ổn định hơn
PAGE_TIMEOUT = 45000    # ms timeout mỗi thao tác
DELAY_BETWEEN = 5       # giây nghỉ giữa 2 account (tránh bị Microsoft chặn)

# ============ PROXY (tùy chọn) ============
# Để None nếu không dùng. Ví dụ: "http://user:pass@ip:port"
PROXY = None

# ============ ĐỌC OTP TỪ MAIL ============
IMAP_SERVER = "outlook.office365.com"
# Người gửi mã bảo mật của Microsoft
OTP_SENDERS = [
    "account-security-noreply@accountprotection.microsoft.com",
    "account-security-noreply@account.microsoft.com",
]
OTP_WAIT = 90   # giây tối đa chờ mail OTP về
