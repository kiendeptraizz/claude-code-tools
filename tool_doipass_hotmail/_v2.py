import config
config.HEADLESS = True
import main
from playwright.sync_api import sync_playwright
accs = {a['email']: a for a in main.load_accounts()}
NEW = "Doipass@2026Abc"
with sync_playwright() as pw:
    for em in ["madererooth61@hotmail.com", "darellhardi5357@hotmail.com"]:
        acc = accs[em]
        try:
            main.change_only(pw, acc, NEW)
            print(f"✓ {em}: ĐỔI PASS OK -> {NEW}")
        except Exception as e:
            print(f"✗ {em}: {e}")
