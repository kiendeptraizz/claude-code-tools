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

## 🔐 Login hàng loạt (check sống/chết) — MỚI
Cùng tool này giờ có thêm chế độ **đăng nhập hàng loạt** và **phân loại** từng acc.

- **GUI:** mở `run_gui.bat` → bấm nút **🔐 Login hàng loạt** → dán danh sách `email|pass|2fa` →
  **▶ Bắt đầu login**.
- **Web:** mở `run_web.bat` → tab **🔐 Login hàng loạt** → dán acc → chạy.

Mỗi acc: tạo/mở profile GPM tên = email → tự đăng nhập (sinh 2FA từ secret TOTP) →
**phân loại kết quả**:

| Code | Nghĩa |
|------|-------|
| `ok` / `already` | ✅ Đăng nhập được (còn sống) — phiên được GIỮ trong profile GPM |
| `wrong_pass` | 🔑 Sai mật khẩu |
| `no_account` | 🚫 Email không tồn tại |
| `disabled` | ⛔ Acc bị khóa / vô hiệu hóa |
| `locked_temp` | ⏳ Tạm khóa (thử quá nhiều lần) |
| `need_2fa` | 🔢 Cần 2FA nhưng dòng acc thiếu secret |
| `wrong_2fa` | 🔢 Sai mã 2FA (secret sai / lệch đồng hồ) |
| `verify_phone` | 📱 Google đòi xác minh SĐT (xử lý tay) |
| `verify_you` | 🕵️ Google đòi "verify it's you" (xử lý tay) |
| `captcha` | 🤖 Dính CAPTCHA (**phải tự giải tay** — tool không giải) |

- Kết quả: `data/login_results.txt` (`email|code|nhãn|lý_do`) + lịch sử `data/login_history.jsonl`.
- Bật **Đánh dấu GPM** để tô 🟢 xanh (sống) / 🟣 tím (lỗi) + ghi chú lên profile.
- Phiên đăng nhập nằm trong profile GPM → các lần sau (và tool check family) dùng lại không cần login.

### ⏸ Gặp CAPTCHA/verify → chờ xác minh tay rồi chạy tiếp
Bật switch **"Gặp CAPTCHA/verify thì DỪNG chờ tôi xác minh tay"** (mặc định BẬT):
- Khi acc dính `captcha` / `verify_phone` / `verify_you` / `challenge`, tool **GIỮ cửa sổ GPM mở**
  và dừng acc đó lại (các acc khác vẫn chạy nếu để nhiều luồng).
- Bạn tự xử lý trong cửa sổ GPM (giải captcha / xác minh SĐT / "it's you") → bấm **▶ Tiếp tục**
  (GUI: khung cam; Web: thẻ "Đang chờ bạn xác minh tay"). Tool **kiểm tra lại** trạng thái và chạy bước tiếp.
- Chờ tối đa `PAUSE_TIMEOUT` (mặc định 600s) rồi tự bỏ qua. Tool **không tự giải** CAPTCHA — bạn giải.

### 🌐 Proxy cho profile
- Proxy riêng từng acc: thêm vào cuối dòng `email|pass|2fa|proxy`.
- Proxy chung: ô **Proxy chung** (Web) / file `data/proxies.txt` (hub ghi vào đây) — xoay vòng cho acc không ghi proxy riêng.
- Định dạng nhận: `host:port`, `host:port:user:pass`, hoặc `socks5://host:port:user:pass`
  (dạng URL `scheme://user:pass@host:port` cũng được, tool tự đổi).
- Proxy được **gán cả cho profile ĐÃ CÓ** (trước đây chỉ set lúc tạo mới → profile cũ vẫn IP máy).
- Mở xong, tool **log IP thật** của từng profile; nếu IP vẫn = IP máy → báo `⚠️ proxy KHÔNG ăn`.

> ⚠️ Tool chỉ dành cho **acc trong kho bạn sở hữu/được quyền quản lý**. Nó không giải CAPTCHA
> và không né bot-detection — chỉ dừng lại để **bạn** xử lý tay. Để luồng **1–2** và có delay để
> chính acc của bạn không bị Google gắn cờ.

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
