import json, re, time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

base_url = "https://mie.ru"
ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'

categories = {
    '/ukrasheniya/sergi/':    'sergi',
    '/ukrasheniya/kaffy/':    'sergi',
    '/ukrasheniya/kole/':     'kole',
    '/ukrasheniya/braslety/': 'braslety',
    '/ukrasheniya/koltsa/':   'koltsa',
}

class Scraper:
    def __init__(self):
        self.out = Path("mie_dataset")
        self.out.mkdir(exist_ok=True)
        self.session = requests.Session()
        self.session.headers['User-Agent'] = ua

    def get(self, url):
        for _ in range(3):
            try:
                r = self.session.get(url, timeout=30)
                if r.status_code == 200:
                    return BeautifulSoup(r.text, 'lxml')
                if r.status_code == 404:
                    return None
            except Exception as e:
                print(f"ошибка {e}"); time.sleep(2)
        return None

    def parse_cards(self, soup, folder):
        out = []
        for card in soup.select('div.product-wrapper'):
            try:
                parts = card.get('id', '').split('_')
                pid = parts[2] if len(parts) >= 3 else card.get('id', '')
                a = card.select_one('a.wrapper[href]')
                if not pid or not a: continue
                name_el  = card.select_one('a.product__name')
                price_el = card.select_one('[itemprop="price"]')
                out.append({
                    'id':    pid,
                    'title': (name_el.get_text(strip=True) if name_el else f'товар {pid}')[:200],
                    'price': price_el.get('content', '').strip() if price_el else '',
                    'url':   base_url + a['href'].rstrip('/'),
                    'cat':   folder,
                })
            except: continue
        return out

    def product_images(self, url):
        soup = self.get(url)
        if not soup: return []
        imgs, seen = [], set()
        preview = soup.select_one('div.preview-slider')
        if not preview: return []
        for img in preview.select('img.preview__image'):
            src = img.get('src', '').strip()
            if src and src not in seen:
                seen.add(src)
                imgs.append(base_url + src if src.startswith('/') else src)
        return imgs[:12]

    def crawl_category(self, path, folder):
        products, seen = [], set()
        print(f"\n{path}")
        page_url = base_url + path
        page = 1
        while page_url:
            print(f"стр {page}", end=" ", flush=True)
            soup = self.get(page_url)
            if not soup: break
            new = 0
            for p in self.parse_cards(soup, folder):
                if p['id'] not in seen:
                    products.append(p); seen.add(p['id']); new += 1
            print(f"{new} всего {len(products)}")
            if not new: break
            btn = soup.select_one('button.js-show-more-btn[data-link]')
            page_url = base_url + btn['data-link'] if btn else None
            page += 1
            time.sleep(0.6)
        return products

    def download(self, url, path):
        try:
            r = self.session.get(url, timeout=30)
            if r.status_code == 200 and len(r.content) > 500:
                path.write_bytes(r.content); return True
        except: pass
        return False

    def process(self, prod, idx, total):
        print(f"\r{idx}/{total} {prod['title'][:50]}", end="", flush=True)
        imgs = self.product_images(prod['url'])
        time.sleep(0.4)
        if not imgs: print(" нет изображений"); return None

        d = self.out / prod['cat'] / f"{idx:04d}"
        d.mkdir(parents=True, exist_ok=True)
        saved = []
        for i, u in enumerate(imgs):
            ext = '.webp' if '.webp' in u else '.png' if '.png' in u else '.jpg'
            p = d / f"image_{i}{ext}"
            if self.download(u, p): saved.append(str(p))

        if not saved: print(" не скачалось"); return None
        meta = {'id': prod['id'], 'title': prod['title'], 'price': prod['price'],
                'category': prod['cat'], 'url': prod['url'], 'images': saved}
        (d / 'info.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f" {len(saved)} фото")
        return meta

    def run(self):
        metadata, all_products = [], []
        try:
            for path, folder in categories.items():
                all_products += self.crawl_category(path, folder)
            unique = list({p['id']: p for p in all_products}.values())
            print(f"всего {len(unique)}")
            for i, prod in enumerate(unique, 1):
                m = self.process(prod, i, len(unique))
                if m: metadata.append(m)
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("стоп")
        out = self.out / 'metadata.json'
        out.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"готово {len(metadata)} товаров → {out}")


if __name__ == "__main__":
    Scraper().run()