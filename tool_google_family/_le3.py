import sys, time
sys.stdout.reconfigure(encoding='utf-8')
import gpm
from playwright.sync_api import sync_playwright
print("version pho bien nhat:", gpm._sample_browser_version(), flush=True)
# don sach moi profile ZZZ_TEST_DELETE
while True:
    d = gpm.find_profile_by_name("ZZZ_TEST_DELETE")
    if not d: break
    ok = gpm.delete_profile(gpm.get_profile_id(d))
    print("xoa profile rac:", ok, flush=True)
    if not ok: break
p = gpm.create_profile("ZZZ_TEST_DELETE")
pid = gpm.get_profile_id(p)
print("tao moi, version:", p.get("browser_version"), flush=True)
try:
    addr, _ = gpm.start_profile(pid)
    print("START OK:", addr, flush=True)
    with sync_playwright() as pw:
        b = pw.chromium.connect_over_cdp("http://" + addr)
        ctx = b.contexts[0]; page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(30000)
        page.goto("https://accounts.google.com/signin/v2/identifier?flowName=GlifWebSignIn&hl=en", timeout=30000)
        time.sleep(4)
        print("URL:", page.url[:65], flush=True)
        ins = page.eval_on_selector_all("input", "e=>e.filter(x=>x.type!=='hidden').map(x=>({id:x.id,name:x.name,type:x.type}))")
        for i in ins: print("  IN", i, flush=True)
        page.screenshot(path="screenshots/_login_page.png", full_page=True)
        b.close()
    gpm.close_profile(pid)
except Exception as e:
    print("LOI:", e, flush=True)
finally:
    d = gpm.find_profile_by_name("ZZZ_TEST_DELETE")
    if d: print("don cuoi:", gpm.delete_profile(gpm.get_profile_id(d)), flush=True)
