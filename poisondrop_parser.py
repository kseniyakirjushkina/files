import json, re, time
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, InvalidSessionIdException

base_url  = "https://poisondrop.ru"
max_items = 1000
ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'


class Scraper:
    def __init__(self):
        self.out = Path("poisondrop_dataset")
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

    def get(self, url, sel=None, timeout=15):
        try:
            self.driver.get(url); time.sleep(1.5)
            if sel:
                try: WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                except TimeoutException: return None
            return BeautifulSoup(self.driver.page_source, 'lxml')
        except (InvalidSessionIdException, WebDriverException) as e:
            print(f"браузер {e}"); return None

    def parse_cards(self, soup):
        out = []
        for card in soup.find_all('div', class_='catalog__card'):
            try:
                link = card.find('a', href=re.compile(r'/catalog/'))
                if not link: continue
                href = link['href']
                m = re.search(r'_(\d+)/?$', href)
                if not m: continue
                name  = card.find('a', class_='catalog-card__name')
                price = card.find(class_=re.compile(r'price', re.I))
                out.append({'id': m.group(1),
                            'title': (name.get_text(strip=True) if name else f"товар {m.group(1)}")[:200],
                            'price': price.get_text(strip=True) if price else '',
                            'url': urljoin(base_url, href)})
            except: continue
        return out

    def product_images(self, url):
        soup = self.get(url)
        if not soup: return []
        imgs, section = [], soup.select_one('section.product-photos, .product__photos')
        if not section: return []
        for item in section.select('div.product-photos__item'):
            src = item.select_one('source[media*="min-width: 1024px"][srcset*=".jpeg"]')
            if src:
                parts = [s.strip().split()[0] for s in src.get('srcset', '').split(',') if s.strip()]
                u = parts[-1] if parts else ''
            else:
                img = item.select_one('img')
                u = (img.get('src') or '') if img else ''
            if u and "item_sku/img/" in u and u not in imgs: imgs.append(u)
        return imgs[:10]

    def crawl_category(self, cat_url, cat_name):
        products, seen = [], set()
        print(f"\n{cat_name}")
        for page in range(1, 501):
            if len(products) >= max_items: break
            url = f"{base_url}{cat_url}" + (f"?page={page}" if page > 1 else "")
            print(f"стр {page}", end=" ", flush=True)
            soup = self.get(url, "div.catalog__card", timeout=10)
            if not soup: break
            new = 0
            for p in self.parse_cards(soup):
                if p['id'] not in seen and len(products) < max_items:
                    p['cat'] = cat_name; products.append(p); seen.add(p['id']); new += 1
            print(f"{new} всего {len(products)}")
            if not new: break
            time.sleep(1.0)
        return products

    def download(self, url, path):
        clean = re.sub(r'/resize_cache/[^/]+/[^/]+/', '/iblock/', url)
        for u in (clean, url):
            try:
                r = self.session.get(u, timeout=30)
                if r.status_code == 200 and len(r.content) > 1000:
                    path.write_bytes(r.content); return True
            except: continue
        return False

    def process(self, prod, idx, total):
        print(f"\r{idx} {total} {prod['title'][:50]}", end="", flush=True)
        all_imgs = self.product_images(prod['url'])
        if not all_imgs: print("нет изображений"); return None

        d = self.out / prod['cat'] / f"{idx:04d}"
        d.mkdir(parents=True, exist_ok=True)
        saved = []
        for i, u in enumerate(all_imgs):
            p = d / f"image_{i}{'.png' if '.png' in u else '.webp' if '.webp' in u else '.jpg'}"
            if self.download(u, p): saved.append(str(p))

        if not saved: print("не скачалось"); return None
        meta = {'id': prod['id'], 'title': prod['title'], 'price': prod['price'],
                'category': prod['cat'], 'url': prod['url'], 'images': saved}
        (d / 'info.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"{len(saved)} фото")
        return meta

    def run(self):
        self.start()
        metadata, all_products = [], []
        try:
            for url, name in {'/catalog/braslety/': 'браслеты'}.items():
                all_products += self.crawl_category(url, name)
            unique = list({p['id']: p for p in all_products}.values())
            print(f"всего {len(unique)}")
            for i, prod in enumerate(unique, 1):
                m = self.process(prod, i, len(unique))
                if m: metadata.append(m)
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("стоп")
        finally:
            self.stop()
        out = self.out / 'metadata.json'
        out.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"готово {len(metadata)} товаров {out}")


if __name__ == "__main__":
    Scraper().run()