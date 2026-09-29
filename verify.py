# ::ILANG [TYPE:module][ROLE:verify-publishable-static-output]
# ::RULE{Check generated canonical URLs, JSON-LD, sitemap, and source evidence}
# ::BOUNDARY{never:accept missing provenance or invented price|scope:permanent}
import json
import re
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from config import load_config


def verify_price(value):
    assert Decimal(str(value)).is_finite() and Decimal(str(value)) >= 0, 'Invalid price'


def verify_source(offer):
    assert offer['source_url'].startswith('https://') and offer['fetched_at']
    # Official pages may state a price without identifying the ISO currency.
    # Preserve independently verified facts; never infer a currency from "$".
    if 'price' in offer:
        verify_price(offer['price'])
    if 'currency' in offer:
        assert re.fullmatch(r'[A-Z]{3}', offer['currency']), 'Invalid currency'


def verify_schema(value):
    if isinstance(value, dict):
        if value.get('@type') == 'Offer':
            assert 'price' in value and 'priceCurrency' in value, 'Incomplete structured Offer'
            verify_price(value['price'])
            assert re.fullmatch(r'[A-Z]{3}', value['priceCurrency']), 'Invalid structured currency'
            assert value.get('url', '').startswith('https://'), 'Missing official Offer URL'
        for child in value.values():
            verify_schema(child)
    elif isinstance(value, list):
        for child in value:
            verify_schema(child)


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.canonicals = []
        self.jsonld = []
        self.capture = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonicals.append(attrs.get('href'))
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.capture = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.jsonld.append(json.loads(data))


def main():
    root = Path(__file__).parent
    site, _ = load_config()
    domain = site['domain']
    offers = json.loads((root / 'data/offers.json').read_text(encoding='utf-8'))
    for offer in offers:
        verify_source(offer)
    pages = list((root / 'site').rglob('*.html'))
    for page in pages:
        relative = page.relative_to(root / 'site')
        path = '/' if relative == Path('index.html') else '/' + relative.parent.as_posix() + '/'
        doc = Metadata()
        doc.feed(page.read_text(encoding='utf-8'))
        assert doc.canonicals == [f'https://{domain}{path}'], page
        assert len(doc.jsonld) == 1, page
        verify_schema(doc.jsonld[0])
    xml = ElementTree.parse(root / 'site/sitemap.xml').getroot()
    ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    urls = [element.text for element in xml.findall('s:url/s:loc', ns)]
    assert len(urls) == len(pages) and all(url.startswith(f'https://{domain}/') for url in urls)
    print(f'Verified {len(pages)} HTML pages, JSON-LD, canonicals, and sitemap URLs')


if __name__ == '__main__':
    main()
