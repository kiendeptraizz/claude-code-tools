# Tool check Google Family (qua GPM Login)

Kiểm tra mỗi tài khoản Google: đang ở family nào, ai là thành viên (email), là chủ hay
thành viên, **còn dư bao nhiêu slot** (family tối đa 6 người).

Vì Google chặn đăng nhập tự động bằng trình duyệt thường, tool **gắn vào trình duyệt của
GPM Login** (antidetect) qua API → không bị chặn.

## Yêu cầu
1. **GPM Login** đã cài + đang mở, **bật API** (trong GPM: Cài đặt → API, cổng mặc định `19995`).
2. Cài tool: nhấp đúp **`setup.bat`** (không cần tải Chromium — dùng browser của GPM).

## Định dạng account (`data/accounts.txt`)
```
email|pass|2fa
```
- `2fa` = secret TOTP (base32) để tool tự sinh mã 6 số.
- Nếu profile GPM **đã đăng nhập sẵn** → `pass`/`2fa` để trống cũng được.

## Cách dùng
1. Mở **GPM Login** (bật API).
2. Nhấp đúp **`run_gui.bat`**.
3. Dán acc vào ô bên trái → bấm **🔌 Kiểm tra kết nối GPM** (phải báo OK).
4. Bấm **▶ Bắt đầu check family**.

Tool sẽ: tìm profile GPM tên = email (chưa có thì tạo + tự đăng nhập) → mở → đọc family.

## Kết quả
- `data/results.txt` — `email|vai_trò|số_thành_viên|slot_trống|danh_sách_email_thành_viên`
- Nút **📜 Lịch sử** — xem lại các lần check (thành viên + slot từng acc)
- `screenshots/` — ảnh trang family mỗi acc (để chỉnh selector nếu đọc thiếu)

## Lưu ý
- Đăng nhập Google tự động dễ bị đòi xác minh SĐT / "verify it's you". **Chắc nhất là dùng
  profile GPM đã đăng nhập sẵn** (chỉ cần email ở mỗi dòng, pass/2fa để trống).
- `families.google.com` hay đổi giao diện → nếu đọc thiếu thành viên, gửi ảnh trong
  `screenshots/` để chỉnh selector.
- Số luồng: GPM nặng, nên để **1-2**.

## Cấu trúc
| File | Vai trò |
|------|---------|
| `gpm.py` | Gọi API GPM Login (mở/đóng/tạo/liệt kê profile) |
| `google_login.py` | Đăng nhập Google + tự sinh mã 2FA (TOTP) |
| `family.py` | Đọc thành viên family từ families.google.com |
| `main.py` | Luồng chính (GPM → Playwright CDP → login → đọc family) |
| `gui.py` | Giao diện |
| `config.py` | Cấu hình (cổng GPM, số luồng, tên profile...) |
