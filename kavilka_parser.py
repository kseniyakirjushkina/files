import json, re, time
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, InvalidSessionIdException

base_url     = "https://kavilka.store"
store_rec_id = "464477089"
ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'

categories = {
    'Серьги':            'sergi',
    'Браслеты':          'braslety',
    'Чокеры+и+ожерелья': 'kole',
    'Цепочки':           'kole',
}

class Scraper:
    def __init__(self):
        self.out = Path("kavilka_dataset")
        self.out.mkdir(exist_ok=True)
        self.session = requests.Session()
        self.session.headers['User-Agent'] = ua
        self.driver = None

    def start(self):
        opts = Options()
        opts.add_argument("--headless=new")
        for a in ("--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                  "--window-size=1920,1080", "--disable-blink-features=AutomationControlled"):
            opts.add_argument(a)
        opts.add_argument(f"user-agent={ua}")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("prefs", {
            "profile.managed_default_content_settings.images": 2,
            "profile.managed_default_content_settings.fonts": 2,
        })
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            svc = Service(ChromeDriverManager().install())
        except ImportError:
            svc = Service()
        self.driver = webdriver.Chrome(service=svc, options=opts)
        self.driver.set_page_load_timeout(60)

    def stop(self):
        if self.driver:
            try: self.driver.quit()
            except: pass

    def get(self, url, sel=None, timeout=20):
        try:
            self.driver.get(url); time.sleep(1.0)
            if sel:
                try: WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                except TimeoutException: return None
            return BeautifulSoup(self.driver.page_source, 'lxml')
        except (InvalidSessionIdException, WebDriverException) as e:
            print(f"браузер {e}"); return None

    def load_more(self):
        BTN = '.js-store-load-more-btn, .t-store__load-more-btn, .t-store__pagination__loadmore'
        for _ in range(200):
            try:
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.4)
                btns = [b for b in self.driver.find_elements(By.CSS_SELECTOR, BTN)
                        if b.is_displayed() and not b.get_attribute('disabled')]
                if not btns: break
                before = len(self.driver.find_elements(By.CSS_SELECTOR, 'div.t-store__card[data-product-uid]'))
                self.driver.execute_script("arguments[0].click();", btns[0])
                for _ in range(12):
                    time.sleep(0.5)
                    after = len(self.driver.find_elements(By.CSS_SELECTOR, 'div.t-store__card[data-product-uid]'))
                    if after > before: break
                else: break
            except: break

    def parse_cards(self, soup, folder):
        out = []
        for card in soup.select('div.t-store__card[data-product-uid]'):
            try:
                pid = card.get('data-product-uid', '').strip()
                url = card.get('data-product-url', '').strip()
                if not pid or not url: continue
                out.append({
                    'id':  pid,
                    'url': url,
                    'cat': folder,
                })
            except: continue
        return out

    def product_images(self, url):
        soup = self.get(url, '.t-store__product-popup, .t-store__prod-popup__info')
        if not soup: return []
        imgs, seen = [], set()
        area = soup.select_one('.t-store__product-popup') or soup
        for meta in area.select('meta[itemprop="image"]'):
            src = meta.get('content', '').strip()
            if src and 'tildacdn.com' in src and src not in seen:
                seen.add(src); imgs.append(src)
        return imgs[:10]

    def crawl_category(self, cat_param, folder):
        products, seen = [], set()
        print(f"\n{cat_param}")
        url = f"{base_url}/katalog?tfc_storepartuid%5B{store_rec_id}%5D={cat_param}&tfc_div=:::"
        soup = self.get(url, 'div.t-store__card[data-product-uid]', timeout=25)
        if not soup: return products
        self.load_more()
        soup = BeautifulSoup(self.driver.page_source, 'lxml')
        for p in self.parse_cards(soup, folder):
            if p['id'] not in seen:
                products.append(p); seen.add(p['id'])
        print(f"всего {len(products)}")
        return products

    def download(self, url, path):
        try:
            r = self.session.get(url, timeout=30)
            if r.status_code == 200 and len(r.content) > 500:
                path.write_bytes(r.content); return True
        except: pass
        return False

    def process(self, prod, idx, total):
        print(f"\r{idx}/{total} {prod['id']}", end="", flush=True)
        imgs = self.product_images(prod['url'])
        if not imgs: print(" нет изображений"); return None

        d = self.out / prod['cat'] / f"{idx:04d}"
        d.mkdir(parents=True, exist_ok=True)
        saved = []
        for i, u in enumerate(imgs):
            ext = '.png' if '.png' in u else '.webp' if '.webp' in u else '.jpg'
            p = d / f"image_{i}{ext}"
            if self.download(u, p): saved.append(str(p))

        if not saved: print(" не скачалось"); return None
        meta = {'id': prod['id'], 'category': prod['cat'],
                'url': prod['url'], 'images': saved}
        (d / 'info.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f" {len(saved)} фото")
        return meta

    def run(self):
        self.start()
        metadata, all_products = [], []
        try:
            for cat_param, folder in categories.items():
                all_products += self.crawl_category(cat_param, folder)
            unique = list({p['id']: p for p in all_products}.values())
            print(f"всего {len(unique)}")
            for i, prod in enumerate(unique, 1):
                m = self.process(prod, i, len(unique))
                if m: metadata.append(m)
                time.sleep(0.3)
        except KeyboardInterrupt:
            print("стоп")
        finally:
            self.stop()
        out = self.out / 'metadata.json'
        out.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"готово {len(metadata)} товаров → {out}")


if __name__ == "__main__":
    Scraper().run()