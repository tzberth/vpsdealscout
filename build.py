# ::ILANG [TYPE:module][ROLE:render-static-pages]
# ::RULE{Read brand domain and providers from .ilang/site.ilang}
# ::BOUNDARY{never:render unverified price or fabricated expiry|scope:permanent}
import html
import json
import re
import argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from config import load_config

ROOT = Path(__file__).parent
OUT = ROOT / 'site'
TEMPLATES = ROOT / 'templates'


def esc(value):
    return html.escape(str(value or ''), quote=True)


def slug(value):
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')


def render(template, **values):
    content = (TEMPLATES / template).read_text(encoding='utf-8')
    for key, value in values.items():
        content = content.replace('{{' + key + '}}', str(value))
    return content


def write(relative, content):
    path = OUT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def reviewed_day(records):
    dates = [r.get('reviewed_at', '')[:10] for r in records if re.match(r'^\d{4}-\d{2}-\d{2}', r.get('reviewed_at', ''))]
    if not dates:
        raise ValueError('No verified review timestamp available for sitemap lastmod')
    return max(dates)


def existing_routes(site):
    routes = []
    for index in OUT.rglob('index.html'):
        rel = index.relative_to(OUT).as_posix()
        route = '/' if rel == 'index.html' else '/' + rel[:-len('index.html')]
        routes.append(route)
    return sorted(set(routes))


def write_sitemap(site, routes, lastmod):
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path in routes:
        sitemap.append(f'<url><loc>https://{esc(site["domain"])}{esc(path)}</loc><lastmod>{lastmod}</lastmod></url>')
    sitemap.append('</urlset>')
    write('sitemap.xml', '\n'.join(sitemap))


def jsonld(value):
    return '<script type="application/ld+json">' + json.dumps(value, ensure_ascii=False).replace('<', '\\u003c') + '</script>'


def legal_page(eyebrow, heading, intro, sections):
    content = ''.join(
        f'<h2>{esc(title)}</h2>' + ''.join(f'<p>{esc(paragraph)}</p>' for paragraph in paragraphs)
        for title, paragraphs in sections
    )
    return render('legal.html', eyebrow=esc(eyebrow), heading=esc(heading), intro=esc(intro), content=content)


def layout(site, path, title, description, body, schema):
    url = f"https://{site['domain']}{path}"
    return render('base.html', lang=esc(site.get('locale', 'en-US')), brand=esc(site['brand']),
                  title=esc(title), description=esc(description), canonical=esc(url),
                  og_image=esc(f"https://{site['domain']}/og.svg"), body=body, schema=jsonld(schema), year=datetime.now().year)


def card(item):
    page = f"/deals/{slug(item['provider'])}/"
    return render('card.html', provider=esc(item['provider']), title=esc(item['title']), kind=esc(item['kind'].upper() + ' SOURCE'),
                  description=esc(item.get('description') or 'Explore the current terms at the official source.'),
                  page=page, checked=esc(item['fetched_at'][:10]))


def store_card(item):
    return render('store_card.html', provider=esc(item['provider']), kind=esc(item['kind'].upper() + ' SOURCE'),
                  description=esc(item.get('description') or 'Explore the current terms at the official source.'),
                  page=f"/providers/{slug(item['provider'])}/", checked=esc(item['fetched_at'][:10]))


def offer_material(item):
    price = (item.get('price_display') or f"{item['price']} {item['currency']}" if item.get('price') and item.get('currency')
             else item.get('price_display') or item.get('price') or NOT_FOUND)
    currency = item.get('currency') or NOT_FOUND
    valid_until = item.get('valid_until') or item.get('valid_until_status') or NOT_FOUND
    checked = item.get('reviewed_at') or item.get('fetched_at') or NOT_FOUND
    fields = [
        ('Offer / plan name', item.get('offer_name') or NOT_FOUND),
        ('Price', price),
        ('Currency', currency),
        ('Conditions', item.get('conditions') or NOT_FOUND),
        ('Valid until', valid_until),
        ('Reviewed', checked[:10] if checked != NOT_FOUND else NOT_FOUND),
        ('Official source', f'<a href="{esc(item["source_url"])}" rel="noopener noreferrer">{esc(item["source_url"])}</a>'),
    ]
    rows = ''.join(f'<div><dt>{esc(label)}</dt><dd>{value if label == "Official source" else esc(value)}</dd></div>'
                   for label, value in fields)
    return '<section class="feature"><span class="pill">OFFICIAL OFFER / PLAN CHECK</span><h2>Current offer details</h2><dl>' + rows + '</dl></section>'


def offer_schema(item):
    if not item.get('price') or not item.get('currency'):
        return None
    result = {'@type': 'Offer', 'url': item.get('offer_url') or item['source_url'],
              'price': item['price'], 'priceCurrency': item['currency']}
    if item.get('valid_until'):
        result['priceValidUntil'] = item['valid_until']
    return result


NOT_FOUND = 'Not found this check'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sitemap-only', action='store_true', help='Refresh sitemap from already generated routes without rewriting pages')
    parser.add_argument('--provider-only', help='Render one configured provider page and refresh sitemap without rewriting other pages')
    args = parser.parse_args()
    site, providers = load_config()
    provider_map = {p['name']: p for p in providers}
    data_path = ROOT / 'data' / 'offers.json'
    records = json.loads(data_path.read_text(encoding='utf-8')) if data_path.exists() else []
    records = [r for r in records if r.get('provider') in provider_map and r.get('source_url') == provider_map[r['provider']]['source']]
    records = [r for r in records if not r.get('valid_until') or r['valid_until'] >= datetime.now().date().isoformat()]
    OUT.mkdir(exist_ok=True)
    if args.sitemap_only:
        routes = existing_routes(site)
        write_sitemap(site, routes, reviewed_day(records))
        print(f'Updated sitemap only: {len(routes)} existing routes; lastmod {reviewed_day(records)}')
        return
    if args.provider_only:
        provider = provider_map.get(args.provider_only)
        record = next((r for r in records if r.get('provider') == args.provider_only), None)
        if not provider or not record or provider.get('mode', 'dual') != 'single':
            raise SystemExit(f'No retained single-page source record for {args.provider_only}')
        provider_path = f"/providers/{slug(record['provider'])}/"
        checked = (record.get('reviewed_at') or record.get('fetched_at') or NOT_FOUND)[:10]
        page = layout(site, provider_path, f"{record['provider']} VPS source | {site['brand']}",
                      f"Official {record['provider']} VPS source, last checked {checked}.",
                      render('store.html', provider=esc(record['provider']), title=esc(record['title']),
                             description=esc(record.get('description') or 'See the official provider page for current terms.'),
                             kind=esc(record['kind'].upper() + ' SOURCE'), source=esc(record['source_url']),
                             checked=esc(checked), offer_material=offer_material(record)),
                      {'@context': 'https://schema.org', '@type': 'Service',
                       'name': f"{record['provider']} VPS hosting", 'provider': {'@type': 'Organization', 'name': record['provider']},
                       'url': f"https://{site['domain']}{provider_path}"})
        write(provider_path.lstrip('/').rstrip('/') + '/index.html', page)
        routes = existing_routes(site)
        write_sitemap(site, routes, reviewed_day(records))
        print(f'Rendered {provider_path} only; sitemap has {len(routes)} existing routes')
        return
    cards = ''.join(card(r) for r in records if provider_map[r['provider']].get('mode', 'dual') == 'dual') or '<p class="empty">No verified sources are available yet. Check back after the next update.</p>'
    stores = ''.join(store_card(r) for r in records if provider_map[r['provider']].get('mode', 'dual') == 'single')
    dual_records = [r for r in records if provider_map[r['provider']].get('mode', 'dual') == 'dual']
    list_items = [{'@type': 'ListItem', 'position': i, 'url': f"https://{site['domain']}/deals/{slug(r['provider'])}/"} for i, r in enumerate(dual_records, 1)]
    pages = []

    def add(path, title, description, body, schema, lastmod=None):
        write(path.lstrip('/') + 'index.html' if path != '/' else 'index.html', layout(site, path, title, description, body, schema))
        pages.append((path, lastmod))

    add('/', f"VPS offers and official plans | {site['brand']}",
        'Verified official VPS offer and plan pages, with source links and last checked dates.',
        render('index.html', cards=cards, count=len([r for r in records if provider_map[r['provider']].get('mode', 'dual') == 'dual']), stores=stores,
               store_count=len([r for r in records if provider_map[r['provider']].get('mode', 'dual') == 'single'])),
        {'@context': 'https://schema.org', '@type': 'ItemList', 'itemListElement': list_items},
        max((r['fetched_at'][:10] for r in records), default=None))
    add('/compare/', f"Compare VPS sources | {site['brand']}",
        'Compare official VPS offer and pricing sources. Check live terms with each provider.',
        render('compare.html', rows=''.join(render('row.html', provider=esc(r['provider']), title=esc(r['title']),
                                           page=f"/deals/{slug(r['provider'])}/", source=esc(r['source_url']),
                                           checked=esc(r['fetched_at'][:10])) for r in dual_records)),
        {'@context': 'https://schema.org', '@type': 'ItemList', 'itemListElement': list_items})
    add('/about/', f"About | {site['brand']}",
        f"About {site['brand']} and how it tracks official VPS source pages.",
        legal_page('ABOUT', f"About {site['brand']}",
                   f"{site['brand']} is an independent VPS source tracker built for readers who want to check provider pages before they buy.",
                   [
                       ('What this site does', [
                           f"{site['brand']} collects a small set of official VPS provider pages and shows the source link, page type, and last checked date in one place.",
                           'The site separates promotion sources from standard pricing sources so readers can see whether a page is an offer page or a regular pricing page.'
                       ]),
                       ('Where the data comes from', [
                           'The site only uses public provider pages that can be reached without a private account. The current source list is defined in the site configuration and rebuilt on a schedule.',
                           'Each listing links back to the provider page because prices, eligibility, renewal terms, and availability can change at the provider.'
                       ]),
                       ('Who runs it', [
                           f"The site is published under the {site['brand']} name. It does not use a personal author name on public pages."
                       ])
                   ]),
        {'@context': 'https://schema.org', '@type': 'AboutPage', 'name': f"About {site['brand']}",
         'url': f"https://{site['domain']}/about/"})
    add('/privacy/', f"Privacy Policy | {site['brand']}",
        f"Privacy policy for {site['brand']}.",
        legal_page('PRIVACY', 'Privacy Policy',
                   f"{site['brand']} is a static website that tracks public VPS provider pages and sends readers to the original source pages.",
                   [
                       ('Information this site uses', [
                           'The site collects information from public provider pages, such as the provider name, the source URL, the page title, a short public description, and the date the source was last checked.',
                           'The site does not run a contact form and does not ask visitors to create an account.'
                       ]),
                       ('Advertising and affiliate links', [
                           'This site is built to include third-party advertising and affiliate links. If a link is sponsored or affiliate, the page will disclose it where the link appears.',
                           'When visitors click out to a provider, ad network, affiliate network, or other third-party website, that third party handles its own logs, cookies, and privacy practices under its own policy.'
                       ]),
                       ('Server and platform logs', [
                           'The site is hosted on Cloudflare Pages. Cloudflare may process basic request data needed to serve the website, protect it, and provide platform analytics.',
                           f"For privacy questions about this site, contact contact@{site['domain']}."
                       ])
                   ]),
        {'@context': 'https://schema.org', '@type': 'WebPage', 'name': 'Privacy Policy',
         'url': f"https://{site['domain']}/privacy/"})
    contact_email = f"contact@{site['domain']}"
    contact_body = render('legal.html', eyebrow='CONTACT', heading='Contact',
                          intro=esc("Use the email address on this page for site questions, source corrections, or partnership inquiries."),
                          content=(f'<h2>Email</h2><p>The only contact channel for this static site is '
                                   f'<a href="mailto:contact%40{esc(site["domain"])}">contact&#64;{esc(site["domain"])}</a>.</p>'
                                   '<p>There is no contact form because the site is published as static pages without a custom application server.</p>'))
    add('/contact/', f"Contact | {site['brand']}",
        f"Contact {site['brand']}.",
        contact_body,
        {'@context': 'https://schema.org', '@type': 'ContactPage', 'name': f"Contact {site['brand']}",
         'url': f"https://{site['domain']}/contact/"})
    for r in records:
        provider = provider_map[r['provider']]
        provider_path = f"/providers/{slug(r['provider'])}/"
        detail_path = f"/deals/{slug(r['provider'])}/"
        if provider.get('mode', 'dual') == 'single':
            add(provider_path, f"{r['provider']} VPS source | {site['brand']}",
                f"Official {r['provider']} VPS source, last checked {r['fetched_at'][:10]}.",
                render('store.html', provider=esc(r['provider']), title=esc(r['title']),
                       description=esc(r.get('description') or 'See the official provider page for current terms.'),
                       kind=esc(r['kind'].upper() + ' SOURCE'), source=esc(r['source_url']),
                       checked=esc((r.get('reviewed_at') or r['fetched_at'])[:10]),
                       offer_material=offer_material(r)),
                {'@context': 'https://schema.org', '@type': 'Service',
                 'name': f"{r['provider']} VPS hosting", 'provider': {'@type': 'Organization', 'name': r['provider']},
                 'url': f"https://{site['domain']}{provider_path}",
                 **({'offers': offer_schema(r)} if offer_schema(r) else {})}, r['fetched_at'][:10])
            continue
        breadcrumb = {'@type': 'BreadcrumbList', 'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': 'Home', 'item': f"https://{site['domain']}/"},
            {'@type': 'ListItem', 'position': 2, 'name': r['provider'], 'item': f"https://{site['domain']}{provider_path}"}]}
        add(provider_path, f"{r['provider']} VPS source | {site['brand']}",
            f"Official {r['provider']} VPS source, last checked {r['fetched_at'][:10]}.",
            render('provider.html', provider=esc(r['provider']), title=esc(r['title']), detail=detail_path, kind=esc(r['kind'].upper() + ' SOURCE'),
                   website=esc(provider['website']), checked=esc((r.get('reviewed_at') or r['fetched_at'])[:10]),
                   offer_material=offer_material(r)),
            {'@context': 'https://schema.org', '@graph': [
                {'@type': 'Service', 'name': f"{r['provider']} VPS hosting", 'provider': {'@type': 'Organization', 'name': r['provider']},
                 'url': f"https://{site['domain']}{provider_path}",
                 **({'offers': offer_schema(r)} if offer_schema(r) else {})}, breadcrumb]}, r['fetched_at'][:10])
        service = {'@type': 'Service', 'name': r['title'], 'provider': {'@type': 'Organization', 'name': r['provider']}, 'url': r['source_url']}
        if offer_schema(r):
            service['offers'] = offer_schema(r)
        add(detail_path, f"{r['provider']}: {r['title']} | {site['brand']}",
            f"Official {r['provider']} source. Verify current terms and availability before buying.",
            render('deal.html', provider=esc(r['provider']), title=esc(r['title']), kind=esc(r['kind'].upper() + ' SOURCE'),
                   description=esc(r.get('description') or 'See the provider page for current terms.'),
                   source=esc(r['source_url']), outbound=esc(r['offer_url']),
                   checked=esc((r.get('reviewed_at') or r['fetched_at'])[:10]), provider_page=provider_path,
                   offer_material=offer_material(r),
                   price=(f"{esc(r['price'])} {esc(r['currency'])}" if 'price' in r and 'currency' in r else 'See official page')),
            {'@context': 'https://schema.org', '@graph': [
                service, breadcrumb]}, r['fetched_at'][:10])
    # Preserve sitemap routes that already have generated pages but could not be
    # refreshed this round (for example, a source blocked by robots/TLS failure).
    routes = {path for path, _ in pages}
    routes.update(set(existing_routes(site)) - routes)
    write_sitemap(site, sorted(routes), reviewed_day(records))
    write('robots.txt', f'User-agent: *\nAllow: /\nSitemap: https://{site["domain"]}/sitemap.xml\n')
    print(f'Built {len(pages)} pages from {len(records)} verified sources')


if __name__ == '__main__':
    main()
