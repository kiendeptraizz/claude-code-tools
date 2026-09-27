#!/usr/bin/env python3
"""Báo cáo kinh doanh nâng cao (markdown) cho Claude Project đọc qua URL. Chạy định kỳ (cron).
Chỉ số liệu TỔNG HỢP (không PII). MySQL đọc qua claude_ro; SQLite bot read-only."""
import subprocess
import datetime
import sqlite3
import os

MYCNF = "/root/.claude_ro.cnf"
DB = "truycuu"
BOTDB = "/opt/telegrambot/autopayment.db"
OUT = "/opt/crm-mcp/report.md"
TARGET_FILE = "/opt/crm-mcp/target.txt"  # mục tiêu doanh thu tháng (VNĐ), 1 số/ dòng
CH = {"shop_web": "Web lẻ", "bot_le": "Bot lẻ", "bot_si": "Bot sỉ (CTV)", "dropship": "Dropship",
      "telegram": "CRM Bot (Telegram)", "web": "CRM Web", "crm_web": "CRM/Nhập tay", "khac": "Khác"}
td = datetime.timedelta


def mq(sql):
    p = subprocess.run(["mysql", f"--defaults-extra-file={MYCNF}", DB, "-N", "--batch", "-e", sql],
                       capture_output=True, text=True, timeout=40)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "err").strip())
    return [ln.split("\t") for ln in p.stdout.strip().split("\n") if ln]


def q1(sql):
    r = mq(sql)
    return r[0] if r else []


def _i(x):
    try:
        return int(float(x))
    except (ValueError, TypeError):
        return 0


def vnd(x):
    return f"{_i(x):,}đ"


def pct(cur, prev):
    if prev == 0:
        return "(mới)" if cur > 0 else ""
    ch = (cur - prev) / prev * 100
    return f"({'▲' if ch >= 0 else '▼'}{abs(ch):.0f}% )".replace(" )", ")")


def margin(rev, prof):
    if rev <= 0 or prof > rev:
        return "—"  # đơn cũ chỉ ghi lãi không ghi DT → biên vô nghĩa
    return f"{prof / rev * 100:.0f}%"


def period(f, t):
    """(số đơn, doanh thu, lợi nhuận) = PendingOrder(paid) + CS không qua PO."""
    po = q1(f"SELECT COUNT(*),COALESCE(SUM(amount),0),COALESCE(SUM(profit_amount),0) FROM pending_orders WHERE paid_at IS NOT NULL AND status!='cancelled' AND DATE(paid_at) BETWEEN '{f}' AND '{t}'")
    cso = q1(f"SELECT COUNT(*),COALESCE(SUM(order_amount),0) FROM customer_services WHERE pending_order_id IS NULL AND status!='cancelled' AND DATE(activated_at) BETWEEN '{f}' AND '{t}'")
    csp = q1(f"SELECT COALESCE(SUM(p.profit_amount),0) FROM profits p JOIN customer_services c ON c.id=p.customer_service_id WHERE c.pending_order_id IS NULL AND c.status!='cancelled' AND DATE(c.activated_at) BETWEEN '{f}' AND '{t}'")
    return _i(po[0]) + _i(cso[0]), _i(po[1]) + _i(cso[1]), _i(po[2]) + _i(csp[0])


now = datetime.datetime.now()
today = now.date()
D = today.isoformat()
yst = (today - td(days=1)).isoformat()
wk = today - td(days=today.weekday())
lwk = wk - td(days=7)
days_wk = (today - wk).days
mo = today.replace(day=1)
lmo = (mo - td(days=1)).replace(day=1)
days_mo = (today - mo).days
yr = today.replace(month=1, day=1).isoformat()

o = ["# 📊 Báo cáo kinh doanh (tự động)", f"_Cập nhật: {now.strftime('%H:%M %d/%m/%Y')}_", ""]

# ============ 1. TỔNG QUAN + SO SÁNH ============
o.append("## 1) Tổng quan (kèm so sánh)")
to_o, to_r, to_p = period(D, D)
_, yr_, yp_ = period(yst, yst)
o.append(f"- **Hôm nay**: {to_o} đơn · DT {vnd(to_r)} {pct(to_r, yr_)} · LN {vnd(to_p)} {pct(to_p, yp_)}")
w_o, w_r, w_p = period(wk.isoformat(), D)
_, lw_r, lw_p = period(lwk.isoformat(), (lwk + td(days=days_wk)).isoformat())
o.append(f"- **Tuần này**: {w_o} đơn · DT {vnd(w_r)} {pct(w_r, lw_r)} · LN {vnd(w_p)} {pct(w_p, lw_p)}")
m_o, m_r, m_p = period(mo.isoformat(), D)
_, lm_r, lm_p = period(lmo.isoformat(), (lmo + td(days=days_mo)).isoformat())
aov = m_r // m_o if m_o else 0
o.append(f"- **Tháng này**: {m_o} đơn · DT {vnd(m_r)} {pct(m_r, lm_r)} · LN {vnd(m_p)} {pct(m_p, lm_p)} · AOV {vnd(aov)}")
y_o, y_r, y_p = period(yr, D)
o.append(f"- **Năm nay**: {y_o} đơn · DT {vnd(y_r)} · LN {vnd(y_p)}")
# Mục tiêu tháng
try:
    tgt = _i(open(TARGET_FILE).read().strip()) if os.path.exists(TARGET_FILE) else 0
except Exception:
    tgt = 0
if tgt > 0:
    o.append(f"- **🎯 Mục tiêu tháng**: {vnd(tgt)} — đã đạt **{m_r / tgt * 100:.0f}%** (còn thiếu {vnd(max(0, tgt - m_r))})")
else:
    o.append("- 🎯 _Mục tiêu tháng: chưa đặt (báo trợ lý con số mục tiêu để bật theo dõi)._")
o.append("")

# ============ 2. NHÌN VỀ PHÍA TRƯỚC ============
o.append("## 2) Sắp tới — doanh thu gia hạn đang chờ")
for lbl, n in [("3 ngày tới", 3), ("7 ngày tới", 7), ("30 ngày tới", 30)]:
    r = q1(f"SELECT COUNT(*),COALESCE(SUM(order_amount),0) FROM customer_services WHERE status='active' AND expires_at>=CURDATE() AND expires_at<CURDATE()+INTERVAL {n} DAY")
    o.append(f"- **Hết hạn trong {lbl}**: {_i(r[0])} dịch vụ · giá trị ghi nhận ≥ {vnd(r[1])}")
# Tỷ lệ gia hạn 30 ngày qua (ước tính)
base = _i(q1("SELECT COUNT(*) FROM customer_services e WHERE e.customer_id IS NOT NULL AND e.expires_at>=CURDATE()-INTERVAL 30 DAY AND e.expires_at<CURDATE()")[0])
renew = _i(q1("SELECT COUNT(*) FROM customer_services e WHERE e.customer_id IS NOT NULL AND e.expires_at>=CURDATE()-INTERVAL 30 DAY AND e.expires_at<CURDATE() AND EXISTS(SELECT 1 FROM customer_services r WHERE r.customer_id=e.customer_id AND r.service_package_id=e.service_package_id AND r.id!=e.id AND r.activated_at>=e.expires_at-INTERVAL 7 DAY)")[0])
rate = renew / base * 100 if base else 0
o.append(f"- **Tỷ lệ gia hạn (30 ngày qua)**: ~{rate:.0f}% ({renew}/{base} dịch vụ đến hạn được gia hạn) _(ước tính)_")
# Dự phóng thu gia hạn 30 ngày tới
exp30 = q1("SELECT COUNT(*),COALESCE(SUM(order_amount),0) FROM customer_services WHERE status='active' AND expires_at>=CURDATE() AND expires_at<CURDATE()+INTERVAL 30 DAY")
proj = int(_i(exp30[1]) * rate / 100)
o.append(f"- **Dự phóng thực thu gia hạn (30 ngày tới)**: ~{vnd(proj)} _(= giá trị đến hạn × tỷ lệ gia hạn, ước tính)_")
o.append("")

# ============ 3. SỨC KHỎE KHÁCH HÀNG ============
o.append("## 3) Sức khỏe khách hàng ⭐")
active = _i(q1("SELECT COUNT(*) FROM customer_services WHERE status='active'")[0])
new_act = _i(q1(f"SELECT COUNT(*) FROM customer_services WHERE activated_at>='{mo} 00:00:00'")[0])
exp_mo = _i(q1(f"SELECT COUNT(*) FROM customer_services WHERE expires_at>='{mo} 00:00:00' AND expires_at<CURDATE()")[0])
o.append(f"- **Dịch vụ đang active (nền subscription)**: **{active}** — tháng này +{new_act} kích hoạt mới, −{exp_mo} hết hạn (net {new_act - exp_mo:+d})")
new_c = _i(q1(f"SELECT COUNT(*) FROM customers WHERE created_at>='{mo} 00:00:00'")[0])
ret_c = _i(q1(f"SELECT COUNT(DISTINCT cs.customer_id) FROM customer_services cs JOIN customers c ON c.id=cs.customer_id WHERE cs.activated_at>='{mo} 00:00:00' AND c.created_at<'{mo} 00:00:00'")[0])
o.append(f"- **Khách tháng này**: mới {new_c} · quay lại {ret_c}")
churn = _i(q1("SELECT COUNT(DISTINCT e.customer_id) FROM customer_services e WHERE e.customer_id IS NOT NULL AND e.expires_at>=CURDATE()-INTERVAL 30 DAY AND e.expires_at<CURDATE() AND NOT EXISTS(SELECT 1 FROM customer_services a WHERE a.customer_id=e.customer_id AND a.status='active' AND a.expires_at>=CURDATE())")[0])
o.append(f"- **Churn (30 ngày)**: ~{churn} khách hết hạn chưa quay lại _(cần win-back)_")
# LTV + VIP
try:
    rows = mq("SELECT cs.customer_id, SUM(p.profit_amount) FROM profits p JOIN customer_services cs ON cs.id=p.customer_service_id WHERE cs.customer_id IS NOT NULL GROUP BY cs.customer_id")
    profs = sorted((_i(r[1]) for r in rows), reverse=True)
    total = sum(profs)
    ncus = len(profs)
    ltv = total // ncus if ncus else 0
    n20 = max(1, round(ncus * 0.2))
    share = sum(profs[:n20]) / total * 100 if total else 0
    o.append(f"- **LTV trung bình**: {vnd(ltv)}/khách ({ncus} khách có phát sinh lãi)")
    o.append(f"- **Khách VIP**: top 20% ({n20} khách) tạo **{share:.0f}%** lợi nhuận")
except Exception as e:
    o.append(f"- (LTV/VIP lỗi: {e})")
o.append("")

# ============ 4. THEO KÊNH + BIÊN LN ============
o.append(f"## 4) Doanh thu theo kênh (tháng này) + biên LN")
rows = mq(f"SELECT COALESCE(NULLIF(channel,''),created_via,'khac'),COUNT(*),COALESCE(SUM(amount),0),COALESCE(SUM(profit_amount),0) FROM pending_orders WHERE paid_at IS NOT NULL AND status!='cancelled' AND DATE(paid_at) BETWEEN '{mo}' AND '{D}' GROUP BY 1 ORDER BY 3 DESC")
for r in rows:
    rev, pr = _i(r[2]), _i(r[3])
    o.append(f"- {CH.get(r[0], r[0])}: {_i(r[1])} đơn · DT {vnd(rev)} · LN {vnd(pr)} · Biên {margin(rev, pr)}")
cs = q1(f"SELECT COUNT(*),COALESCE(SUM(cs.order_amount),0),COALESCE((SELECT SUM(p.profit_amount) FROM profits p JOIN customer_services c ON c.id=p.customer_service_id WHERE c.pending_order_id IS NULL AND c.status!='cancelled' AND DATE(c.activated_at) BETWEEN '{mo}' AND '{D}'),0) FROM customer_services cs WHERE cs.pending_order_id IS NULL AND cs.status!='cancelled' AND DATE(cs.activated_at) BETWEEN '{mo}' AND '{D}'")
if _i(cs[0]) > 0:
    o.append(f"- {CH['crm_web']}: {_i(cs[0])} đơn · DT {vnd(cs[1])} · LN {vnd(cs[2])} · Biên {margin(_i(cs[1]), _i(cs[2]))} _(đơn cũ nhiều đơn không ghi DT → biên '—')_")
o.append("")

# ============ 5. SẢN PHẨM ============
o.append("## 5) Sản phẩm (tháng này)")
o.append("**Top 8 theo LỢI NHUẬN:**")
for n, r in enumerate(mq(f"SELECT sp.name,COUNT(*),COALESCE(SUM(po.amount),0),COALESCE(SUM(po.profit_amount),0) FROM pending_orders po JOIN service_packages sp ON sp.id=po.service_package_id WHERE po.paid_at IS NOT NULL AND po.status!='cancelled' AND DATE(po.paid_at) BETWEEN '{mo}' AND '{D}' GROUP BY sp.id ORDER BY 4 DESC LIMIT 8"), 1):
    o.append(f"{n}. {r[0]}: {_i(r[1])} đơn · LN {vnd(r[3])} · Biên {margin(_i(r[2]), _i(r[3]))}")
o.append("")
o.append("**Top 8 theo SỐ ĐƠN (món kéo khách):**")
for n, r in enumerate(mq(f"SELECT sp.name,COUNT(*) c,COALESCE(SUM(po.amount),0),COALESCE(SUM(po.profit_amount),0) FROM pending_orders po JOIN service_packages sp ON sp.id=po.service_package_id WHERE po.paid_at IS NOT NULL AND po.status!='cancelled' AND DATE(po.paid_at) BETWEEN '{mo}' AND '{D}' GROUP BY sp.id ORDER BY c DESC LIMIT 8"), 1):
    o.append(f"{n}. {r[0]}: **{_i(r[1])} đơn** · DT {vnd(r[2])} · LN {vnd(r[3])}")
o.append("")

# ============ 6. XU HƯỚNG ============
o.append("## 6) Xu hướng")
o.append("**7 ngày gần nhất (doanh thu):**")
dd = {r[0]: (_i(r[1]), _i(r[2])) for r in mq(f"SELECT DATE(paid_at),SUM(amount),SUM(profit_amount) FROM pending_orders WHERE paid_at IS NOT NULL AND status!='cancelled' AND DATE(paid_at)>=CURDATE()-INTERVAL 6 DAY GROUP BY 1")}
days = [(today - td(days=i)) for i in range(6, -1, -1)]
mx = max([dd.get(x.isoformat(), (0, 0))[0] for x in days] + [1])
for x in days:
    rev, pr = dd.get(x.isoformat(), (0, 0))
    bar = "█" * max(0, round(rev / mx * 18))
    o.append(f"- {x.strftime('%d/%m')}: {bar} {vnd(rev)} (LN {vnd(pr)})")
o.append("")
o.append("**6 tháng gần nhất (doanh thu · lợi nhuận):**")
mm = {r[0]: (_i(r[1]), _i(r[2])) for r in mq("SELECT DATE_FORMAT(paid_at,'%Y-%m'),SUM(amount),SUM(profit_amount) FROM pending_orders WHERE paid_at IS NOT NULL AND status!='cancelled' AND paid_at>=DATE_FORMAT(CURDATE()-INTERVAL 5 MONTH,'%Y-%m-01') GROUP BY 1")}
for i in range(5, -1, -1):
    mkey = (mo - td(days=1)).replace(day=1) if False else None
    ym = (today.replace(day=1) - td(days=1))
    # tính tháng thứ i về trước
    yv = today.year
    mv = today.month - i
    while mv <= 0:
        mv += 12
        yv -= 1
    key = f"{yv:04d}-{mv:02d}"
    rev, pr = mm.get(key, (0, 0))
    o.append(f"- {mv:02d}/{yv}: DT {vnd(rev)} · LN {vnd(pr)}")
o.append("")

# ============ TỒN KHO ============
o.append("## Tồn kho bot (account còn hàng)")
try:
    con = sqlite3.connect(f"file:{BOTDB}?mode=ro", uri=True)
    for name, tbl in con.execute("SELECT name,table_name FROM products WHERE active=1 ORDER BY name").fetchall():
        try:
            c = con.execute(f"SELECT COUNT(*) FROM \"{tbl}\" WHERE status='available'").fetchone()[0]
        except Exception:
            c = "?"
        o.append(f"- {name}: {c}")
    con.close()
except Exception as e:
    o.append(f"(lỗi tồn kho: {e})")
o.append("")
o.append("---")
o.append("_Ghi chú: (1) Đơn CŨ chỉ ghi LỢI NHUẬN, không ghi doanh thu → phần 'CRM/Nhập tay' có biên LN '—' và DT thấp hơn thực. "
         "(2) Giá trị gia hạn tính theo đơn có ghi giá (order_amount) nên là mức 'sàn'. "
         "(3) Tỷ lệ gia hạn/churn/dự phóng là ƯỚC TÍNH theo dữ liệu dịch vụ có gắn khách._")

md = "\n".join(o)
tmp = OUT + ".tmp"
with open(tmp, "w", encoding="utf-8") as fp:
    fp.write(md)
os.replace(tmp, OUT)
print("wrote", OUT, len(md), "bytes")
