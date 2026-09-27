#!/usr/bin/env python3
"""Remote MCP (CHỈ-ĐỌC, TỔNG HỢP) cho Claude Project 'kinh doanh tài khoản'.
- Chỉ công cụ tham số hoá theo khoảng ngày → trả SỐ LIỆU TỔNG HỢP (doanh thu/lợi nhuận/kênh/SP/tồn kho).
- KHÔNG nhận SQL tự do, KHÔNG trả PII khách (tên/SĐT/email). Kể cả endpoint lộ cũng chỉ ra con số.
- MySQL đọc qua user claude_ro (SELECT-only); SQLite bot mở read-only.
Chạy: streamable-http trên 127.0.0.1:8790, đường dẫn = nội dung /opt/crm-mcp/path.txt (bí mật, chỉ trên VPS)."""
import subprocess
import datetime
import sqlite3
import pathlib
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

MYCNF = "/root/.claude_ro.cnf"
DB = "truycuu"
BOTDB = "/opt/telegrambot/autopayment.db"
SECRET = pathlib.Path("/opt/crm-mcp/path.txt").read_text().strip()

mcp = FastMCP("truycuu-kinhdoanh", host="127.0.0.1", port=8790, streamable_http_path="/" + SECRET,
              transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

CH = {"shop_web": "Web lẻ", "bot_le": "Bot lẻ", "bot_si": "Bot sỉ (CTV)", "dropship": "Dropship",
      "telegram": "CRM Bot (Telegram)", "web": "CRM Web", "crm_web": "CRM/Nhập tay", "khac": "Khác"}


def _d(s: str) -> str:
    datetime.date.fromisoformat(s)  # raise nếu sai định dạng → chống SQL injection qua ngày
    return s


def _mysql(sql: str):
    p = subprocess.run(["mysql", f"--defaults-extra-file={MYCNF}", DB, "-N", "--batch", "-e", sql],
                       capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "mysql error").strip().splitlines()[-1])
    return [ln.split("\t") for ln in p.stdout.strip().split("\n") if ln]


def _i(x) -> int:
    return int(float(x))  # MySQL SUM trả "123.00" → int qua float


def _vnd(x) -> str:
    try:
        return f"{int(float(x)):,}đ"
    except (ValueError, TypeError):
        return str(x)


@mcp.tool()
def summary(from_date: str, to_date: str) -> str:
    """Tổng doanh thu, lợi nhuận, số đơn, khách mới trong khoảng ngày [from_date..to_date] (YYYY-MM-DD)."""
    f, t = _d(from_date), _d(to_date)
    po = _mysql(f"SELECT COUNT(*),COALESCE(SUM(amount),0),COALESCE(SUM(profit_amount),0) FROM pending_orders WHERE paid_at IS NOT NULL AND status!='cancelled' AND DATE(paid_at) BETWEEN '{f}' AND '{t}'")[0]
    cs = _mysql(f"SELECT COUNT(*),COALESCE(SUM(order_amount),0) FROM customer_services WHERE pending_order_id IS NULL AND status!='cancelled' AND DATE(activated_at) BETWEEN '{f}' AND '{t}'")[0]
    csp = _mysql(f"SELECT COALESCE(SUM(p.profit_amount),0) FROM profits p JOIN customer_services c ON c.id=p.customer_service_id WHERE c.pending_order_id IS NULL AND c.status!='cancelled' AND DATE(c.activated_at) BETWEEN '{f}' AND '{t}'")[0]
    nc = _mysql(f"SELECT COUNT(*) FROM customers WHERE DATE(created_at) BETWEEN '{f}' AND '{t}'")[0]
    orders = _i(po[0]) + _i(cs[0])
    rev = _i(po[1]) + _i(cs[1])
    prof = _i(po[2]) + _i(csp[0])
    return (f"Khoảng {f} → {t}:\n- Số đơn: {orders}\n- Doanh thu: {_vnd(rev)}\n"
            f"- Lợi nhuận: {_vnd(prof)}\n- Khách mới: {nc[0]}\n"
            f"(Lưu ý: đơn CŨ chỉ ghi lợi nhuận, không ghi doanh thu → doanh thu phần 'CRM/Nhập tay' thấp hơn thực tế.)")


@mcp.tool()
def revenue_by_channel(from_date: str, to_date: str) -> str:
    """Doanh thu & lợi nhuận theo KÊNH bán (Web lẻ/Bot lẻ/Bot sỉ/Dropship/CRM Bot/CRM nhập tay) trong khoảng ngày."""
    f, t = _d(from_date), _d(to_date)
    rows = _mysql(f"SELECT COALESCE(NULLIF(channel,''),created_via,'khac') ch,COUNT(*),COALESCE(SUM(amount),0),COALESCE(SUM(profit_amount),0) FROM pending_orders WHERE paid_at IS NOT NULL AND status!='cancelled' AND DATE(paid_at) BETWEEN '{f}' AND '{t}' GROUP BY ch")
    cs = _mysql(f"SELECT COUNT(*),COALESCE(SUM(cs.order_amount),0),COALESCE((SELECT SUM(p.profit_amount) FROM profits p JOIN customer_services c ON c.id=p.customer_service_id WHERE c.pending_order_id IS NULL AND c.status!='cancelled' AND DATE(c.activated_at) BETWEEN '{f}' AND '{t}'),0) FROM customer_services cs WHERE cs.pending_order_id IS NULL AND cs.status!='cancelled' AND DATE(cs.activated_at) BETWEEN '{f}' AND '{t}'")[0]
    out = [f"Doanh thu theo kênh {f} → {t}:"]
    to_, tr, tp = 0, 0, 0
    for r in rows:
        o, rev, pr = _i(r[1]), _i(r[2]), _i(r[3])
        to_ += o; tr += rev; tp += pr
        out.append(f"- {CH.get(r[0], r[0])}: {o} đơn · DT {_vnd(rev)} · LN {_vnd(pr)}")
    if _i(cs[0]) > 0:
        o, rev, pr = _i(cs[0]), _i(cs[1]), _i(cs[2])
        to_ += o; tr += rev; tp += pr
        out.append(f"- {CH['crm_web']}: {o} đơn · DT {_vnd(rev)} · LN {_vnd(pr)} (nhiều đơn cũ không ghi DT)")
    out.append(f"TỔNG: {to_} đơn · DT {_vnd(tr)} · LN {_vnd(tp)}")
    return "\n".join(out)


@mcp.tool()
def revenue_by_day(from_date: str, to_date: str) -> str:
    """Doanh thu & lợi nhuận theo TỪNG NGÀY trong khoảng (đơn qua bot/CRM-bot)."""
    f, t = _d(from_date), _d(to_date)
    rows = _mysql(f"SELECT DATE(paid_at),COUNT(*),COALESCE(SUM(amount),0),COALESCE(SUM(profit_amount),0) FROM pending_orders WHERE paid_at IS NOT NULL AND status!='cancelled' AND DATE(paid_at) BETWEEN '{f}' AND '{t}' GROUP BY DATE(paid_at) ORDER BY DATE(paid_at)")
    out = [f"Theo ngày {f} → {t}:"]
    for r in rows:
        out.append(f"- {r[0]}: {r[1]} đơn · DT {_vnd(r[2])} · LN {_vnd(r[3])}")
    if len(out) == 1:
        out.append("(không có đơn)")
    return "\n".join(out)


@mcp.tool()
def top_products(from_date: str, to_date: str, limit: int = 10) -> str:
    """Top sản phẩm/gói theo lợi nhuận trong khoảng (KHÔNG kèm thông tin khách)."""
    f, t = _d(from_date), _d(to_date)
    lim = max(1, min(int(limit), 50))
    rows = _mysql(f"SELECT sp.name,COUNT(*),COALESCE(SUM(po.amount),0),COALESCE(SUM(po.profit_amount),0) FROM pending_orders po JOIN service_packages sp ON sp.id=po.service_package_id WHERE po.paid_at IS NOT NULL AND po.status!='cancelled' AND DATE(po.paid_at) BETWEEN '{f}' AND '{t}' GROUP BY sp.id ORDER BY 4 DESC LIMIT {lim}")
    out = [f"Top {lim} sản phẩm theo lợi nhuận {f} → {t}:"]
    for i, r in enumerate(rows, 1):
        out.append(f"{i}. {r[0]}: {r[1]} đơn · DT {_vnd(r[2])} · LN {_vnd(r[3])}")
    if len(out) == 1:
        out.append("(không có đơn)")
    return "\n".join(out)


@mcp.tool()
def bot_stock() -> str:
    """Tồn kho bot: số account 'còn hàng' của mỗi sản phẩm đang bán."""
    con = sqlite3.connect(f"file:{BOTDB}?mode=ro", uri=True)
    try:
        prods = con.execute("SELECT name, table_name FROM products WHERE active=1 ORDER BY name").fetchall()
        out = ["Tồn kho bot (account còn hàng):"]
        for name, tbl in prods:
            try:
                n = con.execute(f"SELECT COUNT(*) FROM \"{tbl}\" WHERE status='available'").fetchone()[0]
            except Exception:
                n = "?"
            out.append(f"- {name}: {n}")
        return "\n".join(out)
    finally:
        con.close()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
