import json, re, time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

base_url = "https://sbleskom.ru"
per_page = 48
ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'

categories = {
    'sergi':    'sergi',
    'kaffy':    'sergi',
    'kolie':    'kolie',
    'braslety': 'braslety',
    'kolca':    'kolca',
}

class Scraper:
    def __init__(self):
        self.out = Path("sbleskom_dataset")
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

    def to_original(self, src):
        m = re.search(r'/plain/(images/products/.+?)(?:@\w+)?$', src)
        if m:
            return f"https://static.insales-cdn.com/{m.group(1)}"
        if '/images/products/' in src:
            return src.split('?')[0].split('@')[0]
        return src

    def parse_cards(self, soup, folder):
        out = []
        for card in [el for el in soup.select('[class*="catalog__item"]') if el.get('data-product-id')]:
            try:
                pid = card.get('data-product-id', '').strip()
                a = card.select_one('.catalog__item-images a[href]')
                if not pid or not a: continue
                href = a['href']
                out.append({
                    'id':  pid,
                    'url': base_url + href if href.startswith('/') else href,
                    'cat': folder,
                })
            except: continue
        return out

    def product_images(self, url):
        soup = self.get(url)
        if not soup: return []
        imgs, seen = [], set()

        for a in soup.select('a.download-item[href]'):
            href = a.get('href', '').strip()
            if href and 'insales-cdn.com' in href and href not in seen \
                    and not re.search(r'\.(mov|mp4)$', href, re.I):
                seen.add(href); imgs.append(href)

        if not imgs:
            for div in soup.select('[class*="card__photo-item-img"][href]'):
                href = div.get('href', '').strip()
                if not href or re.search(r'\.(mov|mp4)$', href, re.I): continue
                orig = self.to_original(href)
                if orig and orig not in seen:
                    seen.add(orig); imgs.append(orig)

        return imgs[:12]

    def crawl_category(self, handle, folder):
        products, seen = [], set()
        print(f"\n{handle}")
        page = 1
        while True:
            url = f"{base_url}/collection/{handle}?page={page}&per_page={per_page}"
            print(f"стр {page}", end=" ", flush=True)
            soup = self.get(url)
            if not soup: break
            new = 0
            for p in self.parse_cards(soup, folder):
                if p['id'] not in seen:
                    products.append(p); seen.add(p['id']); new += 1
            print(f"{new} всего {len(products)}")
            if not new: break
            el = soup.select_one('#next-page-num-pagination-loading')
            try:   next_p = int(el.get('data-next-page-num', 0)) if el else 0
            except ValueError: next_p = 0
            if next_p <= 1: break
            page = next_p
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
        print(f"\r{idx}/{total} {prod['id']}", end="", flush=True)
        imgs = self.product_images(prod['url'])
        time.sleep(0.4)
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
        metadata, all_products = [], []
        try:
            for handle, folder in categories.items():
                all_products += self.crawl_category(handle, folder)
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