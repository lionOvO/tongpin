"""Inspect final desktop and mobile assets against running frontend."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts'
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
    page=b.new_page(viewport={'width':1440,'height':1050})
    page.goto('http://127.0.0.1:8501')
    page.wait_for_selector('.page-heading h1')
    page.wait_for_selector('[data-testid=stApp][data-test-script-state=notRunning]',timeout=60000)
    broken=page.evaluate('Array.from(document.images).filter(i=>!i.complete||i.naturalWidth===0).map(i=>i.alt)')
    assert not broken,broken
    assert page.locator('.eyebrow').bounding_box()['y']>=55
    page.screenshot(path=str(OUT/'desktop-matches.png'))
    page.set_viewport_size({'width':390,'height':844})
    page.wait_for_timeout(600)
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 2')
    page.screenshot(path=str(OUT/'mobile-matches.png'))
    result={'asset_loading':'passed','desktop_heading_visibility':'passed','mobile_390px':'passed'}
    (OUT/'visual-results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(result)
    b.close()
