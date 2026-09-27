import config
config.HEADLESS = True; config.SLOW_MO = 0
import main, mail_otp
from playwright.sync_api import sync_playwright
accs = {a['email']: a for a in main.load_accounts()}
D = accs["darellhardi5357@hotmail.com"]; M = accs["madererooth61@hotmail.com"]
with sync_playwright() as pw:
    b, c, pg = main._new_page(pw)
    try:
        main.new_login(pg, D)
        pg.goto(main.CHANGE_URL, timeout=30000); pg.wait_for_timeout(3000)
        # tìm element chứa @hotmail.com
        info = pg.eval_on_selector_all("*", """els=>els.filter(e=>{
            const t=(e.innerText||'').trim();
            return t && t.includes('@hotmail.com') && t.length<60 && e.children.length<=2;
        }).map(e=>({tag:e.tagName, id:e.id, cls:(e.className||'').toString().slice(0,40), role:e.getAttribute('role'), text:e.innerText.trim().slice(0,45)}))""")
        print("Elements chứa @hotmail.com:")
        for x in info: print("  ", x)
        imap, _ = mail_otp.imap_open(M['email'], M['rt'], M['cid'])
        base = mail_otp.code_keys(imap) if imap else set()
        # thử click dòng proof
        clicked = False
        for sel in ['div[role="button"]:has-text("@hotmail.com")',
                    '[role="button"]:has-text("hotmail")',
                    'div[data-bind]:has-text("@hotmail")']:
            try:
                el = pg.locator(sel).first
                if el.is_visible(): el.click(); clicked = True; print("CLICKED:", sel); break
            except Exception as e: pass
        print("clicked:", clicked)
        pg.wait_for_timeout(3000)
        for i in pg.eval_on_selector_all("input","""e=>e.filter(x=>x.type!=='hidden').map(x=>({id:x.id,type:x.type,ph:x.placeholder}))"""):
            print("  IN", i)
        pg.screenshot(path="screenshots/_su2.png", full_page=True)
        if imap:
            code = mail_otp.wait_new_code(imap, base, 70)
            print(">>> CODE:", code)
    finally:
        main._close(b, c)
