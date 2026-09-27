# Tool đổi mật khẩu Hotmail/Outlook hàng loạt

Tự động đăng nhập `account.live.com` rồi đổi mật khẩu cho nhiều account.
Khi Microsoft hỏi mã xác minh, tool tự dùng `refresh_token` đọc mail lấy mã (OTP) → điền tự động.

## Định dạng account (`data/accounts.txt`)
Mỗi dòng:
```
email|password|refresh_token|client_id
```
Dán nguyên định dạng có `[1] ` ở đầu cũng được, tool tự bỏ.

## Cài đặt (chạy 1 lần)
Nhấp đúp **`setup.bat`** (hoặc chạy thủ công):
```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Cách dùng
1. Dán account vào `data/accounts.txt`
2. Mở `config.py` chỉnh mật khẩu mới:
   - `PASSWORD_MODE = "fixed"` + `NEW_PASSWORD = "..."` → tất cả dùng chung 1 pass
   - `PASSWORD_MODE = "random"` → mỗi acc 1 pass ngẫu nhiên (xem ở `data/success.txt`)
3. **Kiểm tra token trước:** nhấp đúp `run_test.bat` → biết acc nào token còn sống
4. **Đổi pass:** nhấp đúp `run.bat`

## Kết quả
- `data/success.txt` — `email|pass_mới|refresh_token|client_id` (acc thành công)
- `data/failed.txt` — `email|pass_cũ|...|lý_do_lỗi` (acc lỗi, để chạy lại / xử lý tay)
- `screenshots/` — ảnh chụp màn hình mỗi khi lỗi (để biết lỗi ở bước nào)
- `logs/run.log` — log chi tiết

## Lưu ý quan trọng
- **Đổi pass xong, refresh_token thường bị Microsoft thu hồi.** Nếu cần token để đọc
  mail về sau, phải tạo token mới bằng luồng OAuth riêng.
- Để `HEADLESS = False` lúc đầu để nhìn trình duyệt chạy & soi lỗi. Quen rồi thì để `True`.
- Microsoft hay đổi giao diện. Nếu nhiều acc cùng lỗi 1 bước, mở ảnh trong
  `screenshots/` xem kẹt ở đâu rồi báo để chỉnh selector.
- Không chạy quá nhanh/nhiều cùng lúc → dễ bị chặn. Có thể tăng `DELAY_BETWEEN`
  hoặc dùng `PROXY` trong `config.py`.

## Cấu trúc
| File | Vai trò |
|------|---------|
| `config.py` | Cấu hình (file, mật khẩu mới, headless, proxy...) |
| `main.py` | Luồng chính: đăng nhập + đổi pass bằng Playwright |
| `mail_otp.py` | Dùng refresh_token đọc mail lấy mã OTP |
| `test_token.py` | Kiểm tra token còn sống / đọc được mail không |
