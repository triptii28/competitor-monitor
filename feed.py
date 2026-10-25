import sys
import httpx
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CompetitorMonitor/0.1)"}
COMMON = ["/blog/feed", "/blog/rss", "/feed", "/rss.xml", "/feed.xml", "/blog/feed.xml", "/blog/rss.xml"]

def fetch(url):
    r = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
    r.raise_for_status()
    return r.text

def find_feed_urls(domain):
    base = f"https://{domain}"
    candidates = []
    # 1. look for <link rel="alternate"> on the homepage and /blog
    for page in [base, base + "/blog"]:
        try:
            soup = BeautifulSoup(fetch(page), "lxml")
            for link in soup.find_all("link", rel="alternate"):
                t = link.get("type", "")
                if "rss" in t or "atom" in t:
                    href = link.get("href")
                    candidates.append(httpx.URL(page).join(href).__str__())
        except Exception as e:
            pass
    # 2. fall back to common feed paths
    candidates += [base + p for p in COMMON]
    return list(dict.fromkeys(candidates))  # remove duplicates, keep order

def read_feed(url):
    soup = BeautifulSoup(fetch(url), "xml")
    posts = []
    for item in soup.find_all(["item", "entry"]):
        title = item.find("title")
        link = item.find("link")
        link_url = (link.get("href") or link.text) if link else None
        date = item.find(["pubDate", "published", "updated"])
        posts.append((title.text.strip() if title else None,
                      link_url.strip() if link_url else None,
                      date.text.strip() if date else None))
    return posts

if __name__ == "__main__":
    domain = sys.argv[1]
    for url in find_feed_urls(domain):
        try:
            posts = read_feed(url)
        except Exception as e:
            print("x", url, "->", e)
            continue
        if posts:
            print(f"FOUND feed: {url} ({len(posts)} posts)")
            for p in posts[:5]:
                print("  ", p)
            break
    else:
        print("No working feed found")