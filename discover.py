import sys
import httpx
import xml.etree.ElementTree as ET

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CompetitorMonitor/0.1)"}
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

def get(url):
    r = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
    r.raise_for_status()
    return r.text

def find_sitemaps(domain):
    base = f"https://{domain}"
    found = []
    try:
        for line in get(base + "/robots.txt").splitlines():
            if line.lower().startswith("sitemap:"):
                found.append(line.split(":", 1)[1].strip())
    except Exception as e:
        print("robots.txt failed:", e)
    return found or [base + "/sitemap.xml"]

def read_sitemap(url, depth=0):
    results = []
    try:
        root = ET.fromstring(get(url))
    except Exception as e:
        print("Could not read", url, "->", e)
        return results
    # a sitemap can point to other sitemaps
    for loc in root.findall(f"{NS}sitemap/{NS}loc"):
        if depth < 2:
            results += read_sitemap(loc.text.strip(), depth + 1)
    for u in root.findall(f"{NS}url"):
        loc = u.find(f"{NS}loc").text.strip()
        lastmod = u.find(f"{NS}lastmod")
        results.append((loc, lastmod.text if lastmod is not None else None))
    return results

if __name__ == "__main__":
    domain = sys.argv[1]
    sitemaps = find_sitemaps(domain)
    print("Sitemaps found:", len(sitemaps))

    keywords = ("blog", "post", "article", "news", "resource", "insight")
    preferred = [s for s in sitemaps if any(k in s.lower() for k in keywords)]
    to_read = preferred or sitemaps
    print("Reading:", to_read)

    all_urls = []
    for sm in to_read:
        urls = read_sitemap(sm)
        print(f"  {sm} -> {len(urls)} URLs")
        all_urls += urls

    print(f"Total URLs: {len(all_urls)}")
    for url, date in all_urls[:10]:
        print(date, url)