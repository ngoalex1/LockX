"""Optional normal-browser listing intake. No stealth, proxy rotation or challenge bypass.

Install: pip install -r requirements-browser.txt && python -m playwright install chromium
Enable: LOCKX_BROWSER_SEARCH=1 (worker host needs the browser installed).
"""
from __future__ import annotations
import os
from urllib.parse import urlsplit
from marketplace_search import search_plan

# Read only listing cards rendered by the site's normal search page.
EXTRACT = r'''source => {
  const selector = source === 'craigslist' ? 'a.posting-title' : 'a[href*="/marketplace/item/"]';
  const seen = new Set(), rows = [];
  for (const a of document.querySelectorAll(selector)) {
    if (!a.getClientRects().length) continue;
    const url = new URL(a.href); url.search = ''; url.hash = '';
    const id = source === 'facebook_marketplace' ? url.pathname.match(/\/item\/(\d+)/)?.[1] : url.pathname.split('/').filter(Boolean).pop();
    if (!id || seen.has(id)) continue;
    const card = source === 'craigslist' ? a.closest('.gallery-card') : a;
    if (!card) continue;
    const title = source === 'craigslist' ? a.innerText.trim() : (a.getAttribute('aria-label') || a.innerText).trim();
    if (!title) continue;
    const image_urls = [...new Set([...card.querySelectorAll('img')].map(i=>i.currentSrc || i.src).filter(u=>u.startsWith('https://')))].slice(0,4);
    rows.push({source,external_id:id,url:url.href,title,description:card.innerText.trim(),image_urls,
      location:card.querySelector('.result-location')?.innerText || null,
      price:card.querySelector('.priceinfo')?.innerText || null});
    seen.add(id);
    if (rows.length >= 100) break;
  }
  return rows;
}'''


def blocker(text, url):
    text = text.lower()
    if any(s in text for s in ('verify you are human','unusual traffic','complete the security check','temporarily blocked','access denied','captcha')):
        return 'blocked_or_challenge'
    if '/login' in url or '/checkpoint' in url:
        return 'sign_in_required'
    return None


async def collect_page(page, source, url):
    await page.goto(url, wait_until='domcontentloaded', timeout=45000)
    # Dismiss only the site's optional promotion modal. Never submit sign-in or challenges.
    if source == 'facebook_marketplace':
        close = page.get_by_role('button', name='Close', exact=True)
        if await close.count() == 1 and await close.is_visible():
            await close.click()
    selector = 'a.posting-title' if source == 'craigslist' else 'a[href*="/marketplace/item/"]'
    try:
        await page.locator(selector).first.wait_for(state='visible',timeout=15000)
    except Exception:
        text = await page.locator('body').inner_text(timeout=5000)
        reason = blocker(text, page.url)
        if not reason and any(s in text.lower() for s in ('no results found','no results for','nothing found')):
            return [], {'status':'completed','count':0,'scope':'search_page_only'}
        return [], {'status': reason or 'page_unreadable_or_layout_changed'}
    reason = blocker(await page.locator('body').inner_text(timeout=5000), page.url)
    if reason:
        return [], {'status':reason}
    rows = await page.evaluate(EXTRACT, source)
    if not rows:
        return [], {'status':'page_unreadable_or_layout_changed'}
    # Search pages can lazy-load images. Bounded scrolling only, no crawling all listings.
    for _ in range(2):
        await page.mouse.wheel(0,700)
        newer = await page.evaluate(EXTRACT, source)
        by_id = {r['external_id']:r for r in rows}
        by_id.update({r['external_id']:r for r in newer})
        rows = list(by_id.values())[:100]
    return rows, {'status':'completed','count':len(rows),'scope':'bounded_search_page',
                  'search_url':page.url,'location_verified':source == 'craigslist',
                  'note': 'Facebook retains its own location; verify saved search filters' if source != 'craigslist' else 'Search page may append separately labeled nearby results'}


async def collect_browser(profile, settings):
    statuses, records = {}, []
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return [], {s:{'status':'browser_dependency_missing'} for s in ('craigslist','facebook_marketplace')}
    data = {'query':' '.join(filter(None,(profile.brand,profile.model))) or 'lost item',
            'region':settings.get('region','www'),'postal':settings.get('postal',''),
            'radius':settings.get('radius',50),'facebook_url':settings.get('facebook_url','')}
    plan = search_plan(data)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, chromium_sandbox=True)
            try:
                context = await browser.new_context()
                page = await context.new_page()
                for source, prepared in zip(('craigslist','facebook_marketplace'), plan['sources']):
                    try:
                        rows, status = await collect_page(page,source,prepared['url'])
                        records.extend(rows)
                        statuses[source] = status
                    except Exception:
                        statuses[source] = {'status':'browser_or_source_failed'}
            finally:
                await browser.close()
    except Exception:
        return [], {s:{'status':'browser_unavailable'} for s in ('craigslist','facebook_marketplace')}
    return records, statuses


async def browser_runtime_check():
    """Check sandboxed launch only; this makes no marketplace requests."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return 'browser_dependency_missing'
    try:
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True,chromium_sandbox=True)
            await browser.close()
        return 'available'
    except Exception:
        return 'browser_unavailable'
