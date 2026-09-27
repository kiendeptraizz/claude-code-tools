# -*- coding: utf-8 -*-
"""
Kiểm tra nhanh: refresh_token + client_id có còn sống không và đọc được mail không.
Chạy trước khi đổi pass để biết acc nào token còn dùng được.

  python test_token.py
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa
    pass

import config
from mail_otp import get_access_token, _imap_connect
from main import load_accounts


def main():
    accs = load_accounts()
    if not accs:
        print(f"Không có acc trong {config.INPUT_FILE}")
        return
    print(f"Kiểm tra {len(accs)} account...\n")
    ok = dead = 0
    for acc in accs:
        if not acc["rt"]:
            print(f"  -  {acc['email']}: KHÔNG có refresh_token")
            dead += 1
            continue
        token, _ = get_access_token(acc["rt"], acc["cid"])
        if not token:
            print(f"  ✗  {acc['email']}: token CHẾT")
            dead += 1
            continue
        try:
            imap = _imap_connect(acc["email"], token)
            imap.select("INBOX")
            typ, data = imap.search(None, "ALL")
            n = len(data[0].split()) if data and data[0] else 0
            imap.logout()
            print(f"  ✓  {acc['email']}: OK ({n} mail trong INBOX)")
            ok += 1
        except Exception as e:  # noqa
            print(f"  ✗  {acc['email']}: token sống nhưng IMAP lỗi -> {e}")
            dead += 1
    print(f"\nKết quả: {ok} sống / {dead} lỗi")


if __name__ == "__main__":
    main()
