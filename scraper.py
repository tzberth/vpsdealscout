# ::ILANG [TYPE:module][ROLE:verify-public-offer-sources]
# ::RULE{Read providers from .ilang/site.ilang; respect robots.txt}
# ::BOUNDARY{never:guess prices or dates bypass access controls|scope:permanent}
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from html.parser import HTMLParser
from pathlib import Path

from config import load_config

ROOT = Path(__file__).parent
AGENT = 'VPSDealsRadar/1.0 (+public-source-check; contact via repository)'


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ''
        self.description = ''
        self.in_title = False
        self.hidden_depth = 0
        self.visible_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.hidden_depth += 1
            return
        if self.hidden_depth:
            return
        if tag == 'title':
            self.in_title = True
        if tag == 'meta' and attrs.get('name', '').lower() == 'description':
            self.description = attrs.get('content', '')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg') and self.hidden_depth:
            self.hidden_depth -= 1
            return
        if self.hidden_depth:
            return
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.hidden_depth:
            return
        if self.in_title:
            self.title += data
        self.visible_text.append(data)


NOT_FOUND = 'Not found this check'


def current_offer(provider, title, description, visible_text):
    """Extract only unambiguous facts from text on the configured official page."""
    name = NOT_FOUND
    price = currency = price_display = None
    conditions = NOT_FOUND
    text = re.sub(r'\s+', ' ', visible_text)

    if provider == 'IONOS':
        match = re.search(r'VPS S\+\s*Save\s+17%\s*\$6\s*\$\s*2\s*/month\s*for 3 months\s*with a 1-year term', text, re.I)
        if match:
            name, price, price_display, conditions = 'VPS S+ — Save 17%', '2', '$2/month', 'for 3 months with a 1-year term'
            # The page prints "$" but does not state an ISO currency code in the extracted offer text.
    elif provider == 'VPS.NET':
        match = re.search(r'(\$20 credit when you sign up)\s+Voucher Code\s+(20CREDIT)', text, re.I)
        if match:
            name = f'{match.group(2)} — {match.group(1)}'
            condition = re.search(r'Available on V2 and above products\. Terms and conditions apply\.', text, re.I)
            conditions = condition.group(0) if condition else 'When you sign up'
    elif provider == 'OVHcloud US':
        match = re.search(r'VPS-1\s+Starting at\s+\$([0-9]+(?:\.[0-9]{1,2})?)\s*/month', text, re.I)
        if match:
            name, price, price_display = 'VPS-1', match.group(1), f'${match.group(1)}/month'
            conditions = NOT_FOUND
            currency = 'USD'  # Also present as priceCurrency in the official page's Product JSON-LD.
    elif provider == 'Clouvider':
        match = re.search(r'VPS\s+We offer cloud VPS solutions.*?Check out our latest VPS plans\.\s*From\s+£([0-9]+(?:\.[0-9]{1,2})?)\s+GBP', text, re.I)
        if match:
            name, price, currency, price_display = 'VPS', match.group(1), 'GBP', f'£{match.group(1)} GBP'
            conditions = NOT_FOUND
    elif provider == 'CloudCone':
        match = re.search(r'SSD VPS 1\s+\$([0-9]+(?:\.[0-9]{1,2})?)\s*/MO\s+Billed\s+\$([0-9]+(?:\.[0-9]{1,2})?)\s+per year,\s*USD', text, re.I)
        if match:
            name, price, currency, price_display = 'SSD VPS 1', match.group(2), 'USD', f'${match.group(2)} per year'
            conditions = f'Billed ${match.group(1)} /MO Billed ${match.group(2)} per year, USD'
    elif provider == 'Serverspace':
        match = re.search(r'Cloud VPS Ready in 40 seconds.*?from\s*([0-9]+(?:\.[0-9]{1,2})?)\s*€/mo', title, re.I)
        billing = re.search(r'We use the Pay-as-you-go model, which means that there are no fixed price plans\. You are billed every 10 minutes for the machinery that you use\.', text, re.I)
        if match:
            name, price, currency, price_display = 'Cloud VPS', match.group(1), 'EUR', f'{match.group(1)} €/mo'
            conditions = billing.group(0) if billing else NOT_FOUND

    result = {
        'offer_name': name,
        'price_status': 'Found' if price is not None else NOT_FOUND,
        'currency_status': 'Found' if currency is not None else NOT_FOUND,
        'conditions': conditions,
        'valid_until_status': NOT_FOUND,
    }
    date_match = re.search(
        r'(?:valid until|valid through|expires? (?:on|at)?|offer ends? (?:on|at)?)\s*[:,-]?\s*'
        r'((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|'
        r'Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}|'
        r'\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})', text, re.I)
    if date_match:
        date_text = date_match.group(1)
        for date_format in ('%B %d, %Y', '%B %d %Y', '%b %d, %Y', '%b %d %Y', '%Y-%m-%d', '%m/%d/%Y'):
            try:
                result['valid_until'] = datetime.strptime(date_text, date_format).date().isoformat()
                result.pop('valid_until_status', None)
                break
            except ValueError:
                continue
    if price is not None:
        result['price'] = price
        result['price_display'] = price_display
    if currency is not None:
        result['currency'] = currency
    return result


def allowed(url):
    parsed = urllib.parse.urlparse(url)
    robots = urllib.robotparser.RobotFileParser()
    robots.set_url(f'{parsed.scheme}://{parsed.netloc}/robots.txt')
    try:
        robots.read()
        return robots.can_fetch(AGENT, url)
    except (OSError, urllib.error.URLError):
        return False


def fetch(provider):
    url = provider['source']
    if not allowed(url):
        print(f'Skipped (robots unavailable or disallowed): {url}')
        return None
    request = urllib.request.Request(url, headers={'User-Agent': AGENT, 'Accept-Language': 'en-US,en;q=0.9'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content_type = response.headers.get('Content-Type', '')
            if 'html' not in content_type:
                return None
            html = response.read(2_000_000).decode('utf-8', errors='replace')
    except (OSError, urllib.error.URLError) as exc:
        print(f'Skipped (fetch failed): {url}: {exc}')
        return None
    page = Page()
    page.feed(html)
    title = re.sub(r'\s+', ' ', page.title).strip()
    if not title:
        return None
    item = {
        'id': re.sub(r'[^a-z0-9]+', '-', provider['name'].lower()).strip('-'),
        'provider': provider['name'],
        'title': title[:160],
        'description': re.sub(r'\s+', ' ', page.description).strip()[:300],
        'kind': provider['kind'],
        'offer_url': provider['affiliate'] or url,
        'source_url': url,
        'fetched_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    item.update(current_offer(provider['name'], title, page.description, ' '.join(page.visible_text)))
    item['source_url'] = url
    item['reviewed_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
    return item


def main():
    _, providers = load_config()
    existing_path = ROOT / 'data' / 'offers.json'
    existing = json.loads(existing_path.read_text(encoding='utf-8')) if existing_path.exists() else []
    previous = {item['provider']: item for item in existing if item.get('provider')}
    results = []
    for provider in providers:
        item = fetch(provider)
        if item:
            results.append(item)
        elif provider['name'] in previous:
            # Keep the last fetched metadata, but clear offer facts that could not be rechecked.
            stale = dict(previous[provider['name']])
            stale.pop('price', None)
            stale.pop('currency', None)
            stale.update({'offer_name': NOT_FOUND, 'price_status': NOT_FOUND,
                          'currency_status': NOT_FOUND, 'conditions': NOT_FOUND,
                          'valid_until_status': NOT_FOUND,
                          'reviewed_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')})
            results.append(stale)
    existing_path.parent.mkdir(exist_ok=True)
    existing_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(results)} verified source entries saved')


if __name__ == '__main__':
    main()
