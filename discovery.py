import re
import socket
import time
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from db import normalize_url
from feed import find_feed_urls, read_feed

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CompetitorMonitor/0.1)"}
BLOG_WORDS = {"blog", "resources", "articles", "article", "news", "insights",
              "learn", "stories", "posts"}
SKIP_WORDS = {"category", "categories", "tag", "tags", "author", "authors",
              "page", "topics", "topic", "feed"}
MAX_NEW_PAGES = 25  # max pages fetched for metadata per run


def clean_domain(raw):
    d = re.sub(r"^https?://", "", raw.strip().lower()).split("/")[0]
    return d[4:] if d.startswith("www.") else d


def dns_ok(domain):
    try:
        socket.getaddrinfo(domain, 443)
        return True
    except socket.gaierror:
        return False


def get(url):
    """Returns (text or None, status code or None)."""
    try:
        r = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        return (r.text if r.status_code == 200 else None), r.status_code
    except httpx.HTTPError:
        return None, None


def slug_title(url):
    return url.rstrip("/").split("/")[-1].replace("-", " ").title()


def looks_like_post(url, domain):
    p = urlparse(url)
    host = p.netloc.lower().removeprefix("www.")
    if host != domain and not host.endswith("." + domain):
        return False
    if re.search(r"\.(jpg|png|gif|svg|xml|pdf)$", p.path.lower()):
        return False
    segs = [s for s in p.path.split("/") if s]
    if not segs or any(s in SKIP_WORDS for s in segs):
        return False
    if host.startswith("blog."):
        return True
    return len(segs) >= 2 and any(s in BLOG_WORDS for s in segs[:-1])


def _read_sitemaps(start):
    out, seen, queue = [], set(), [(s, 0) for s in start]
    while queue and len(seen) < 15:
        sm, depth = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        xml, _ = get(sm)
        if not xml:
            continue
        soup = BeautifulSoup(xml, "xml")
        children = [s.find("loc").text.strip() for s in soup.find_all("sitemap") if s.find("loc")]
        pref = [c for c in children if any(w in c.lower() for w in BLOG_WORDS)]
        if depth < 2:
            queue += [(c, depth + 1) for c in (pref or children)]
        for u in soup.find_all("url"):
            loc, lm = u.find("loc"), u.find("lastmod")
            if loc:
                out.append((loc.text.strip(), lm.text.strip() if lm else None))
    return out


def sitemap_candidates(domain):
    base = f"https://{domain}"
    txt, _ = get(base + "/robots.txt")
    maps = [l.split(":", 1)[1].strip() for l in (txt or "").splitlines()
            if l.lower().startswith("sitemap:")]
    maps = maps or [base + "/sitemap.xml"]
    pref = [m for m in maps if any(w in m.lower() for w in BLOG_WORDS)]
    posts = [(u, d) for u, d in (_read_sitemaps(pref) if pref else []) if looks_like_post(u, domain)]
    if not posts:
        posts = [(u, d) for u, d in _read_sitemaps(maps) if looks_like_post(u, domain)]
    posts.sort(key=lambda x: x[1] or "", reverse=True)
    return posts


def crawl_candidates(domain):
    base = f"https://{domain}"
    listings = [base + p for p in ("/blog", "/resources", "/articles", "/news", "/insights", "/learn")]
    listings.append(f"https://blog.{domain}")
    html, _ = get(base)
    if html:
        for a in BeautifulSoup(html, "lxml").find_all("a", href=True):
            u = urljoin(base, a["href"]).split("#")[0].split("?")[0]
            p = urlparse(u)
            segs = [s for s in p.path.split("/") if s]
            host = p.netloc.lower().removeprefix("www.")
            if host == domain or host.endswith("." + domain):
                if (len(segs) == 1 and segs[0] in BLOG_WORDS) or (not segs and host.startswith("blog.")):
                    listings.append(u)
    found, seen = [], set()
    for lp in dict.fromkeys(listings):
        html, _ = get(lp)
        if not html:
            continue
        for a in BeautifulSoup(html, "lxml").find_all("a", href=True):
            u = urljoin(lp, a["href"]).split("#")[0].split("?")[0]
            if u not in seen and looks_like_post(u, domain) and u.rstrip("/") != lp.rstrip("/"):
                seen.add(u)
                found.append((u, None))
        if found:
            break
    return found


def page_meta(url):
    """Returns (title, date, description) read from the post page itself."""
    html, _ = get(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")

    def meta(*names):
        for n in names:
            t = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if t and t.get("content"):
                return t["content"].strip()

    title = meta("og:title")
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title and soup.h1:
        title = soup.h1.get_text(strip=True)
    date = meta("article:published_time", "datePublished")
    if not date:
        for s in soup.find_all("script", type="application/ld+json"):
            m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', s.string or "")
            if m:
                date = m.group(1)
                break
    if not date:
        t = soup.find("time", attrs={"datetime": True})
        date = t["datetime"] if t else None
    return title, date, meta("description", "og:description")


def _from_candidates(cands, known):
    seen, uniq = set(), []
    for u, d in cands:
        n = normalize_url(u)
        if n not in seen:
            seen.add(n)
            uniq.append((n, d))
    posts, fetched = [], 0
    for n, d in uniq:
        if n in known:
            posts.append((slug_title(n), n, d, None))
        elif fetched < MAX_NEW_PAGES:
            fetched += 1
            time.sleep(0.3)  # be polite
            meta = page_meta(n)
            title, date, desc = meta if meta else (None, None, None)
            posts.append(((title or slug_title(n)).replace("\xa0", " "), n, date or d, desc))
    return posts, len(uniq)

def _enrich_feed(posts, known):
    """Fill in description (and a missing date) for new feed posts by reading their pages."""
    out, fetched = [], 0
    for t, l, d in posts:
        desc = None
        if normalize_url(l) not in known and fetched < MAX_NEW_PAGES:
            fetched += 1
            time.sleep(0.3)  # be polite
            meta = page_meta(l)
            if meta:
                _, pdate, desc = meta
                d = d or pdate
        out.append((t, l, d, desc))
    return out

CHALLENGE = ("checking your browser", "just a moment", "attention required",
             "verify you are human", "captcha", "access denied",
             "are you a robot", "unusual traffic")


def looks_blocked(posts):
    """True if most fetched 'posts' are really bot-check pages."""
    if not posts:
        return False
    bad = sum(1 for p in posts if any(m in (p[0] or "").lower() for m in CHALLENGE))
    return bad >= max(1, len(posts) // 2)

def _result(status, domain, message, posts=None, total=0, source=None):
    return {"status": status, "domain": domain, "message": message,
            "posts": posts or [], "total": total, "source": source}


def discover_posts(raw, con):
    domain = clean_domain(raw)
    if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", domain) or not dns_ok(domain):
        return _result("invalid_domain", domain,
                       f"'{raw}' is not a valid or reachable domain. Check the spelling.")
    _, home_status = get(f"https://{domain}")
    blocked = home_status in (403, 429, 503)
    known = {r[0] for r in con.execute("SELECT url FROM posts")}

    # Layer 1: RSS/Atom feed
    for url in find_feed_urls(domain):
        try:
            posts = read_feed(url)
        except Exception:
            continue
        posts = [((t or "").replace("\xa0", " ") or None, l, d) for t, l, d in posts if l]
        if posts:
            posts = _enrich_feed(posts, known)
            return _result("ok", domain, "", posts, len(posts), f"feed ({url})")

    # Layer 2: sitemap, Layer 3: crawl blog listing pages
    for source, finder in (("sitemap", sitemap_candidates), ("crawl", crawl_candidates)):
        cands = finder(domain)
        if cands:
            posts, total = _from_candidates(cands, known)
            new_posts = [p for p in posts if p[1] not in known]
            if new_posts and all(p[0] == slug_title(p[1]) for p in new_posts):
                return _result("blocked", domain,
                               "Site listed its posts but refused every page fetch, "
                               "so titles and dates could not be read (automated access blocked).")
            if looks_blocked(posts):
                return _result("blocked", domain,
                               "Site served a bot-check/CAPTCHA page instead of content, "
                               "so it blocked automated access.")
            return _result("ok", domain, "", posts, total, source)

    if blocked:
        return _result("blocked", domain,
                       f"Site blocked automated access (HTTP {home_status}). "
                       "Tried feed, sitemap and crawl, and found no posts.")
    if home_status is None:
        return _result("unreachable", domain, "The site did not respond. Try again later.")
    return _result("no_blog", domain, "No blog/content section detected on this site.")