import hashlib
import re

import httpx
from bs4 import BeautifulSoup

from discovery import HEADERS, get

PRICING_PATHS = ["/pricing", "/plans", "/pricing-plans", "/price"]


def _init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS pricing(
        domain TEXT PRIMARY KEY,
        url TEXT,
        hash TEXT,
        snippet TEXT,
        checked_at TEXT)""")
    con.commit()


def _visible_text(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)


def check_pricing(con, domain):
    """Returns dict: status = 'none' | 'baseline' | 'unchanged' | 'changed' | 'error'."""
    _init(con)
    for path in PRICING_PATHS:
        url = f"https://{domain}{path}"
        html, status = get(url)
        if not html:
            continue
        text = _visible_text(html)
        if len(text) < 200:  # nearly empty page, probably JS-rendered
            continue
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        row = con.execute("SELECT hash FROM pricing WHERE domain=?", (domain,)).fetchone()
        snippet = text[:200]
        if row is None:
            con.execute("INSERT INTO pricing(domain, url, hash, snippet, checked_at) VALUES (?,?,?,?,?)",
                        (domain, url, h, snippet, _now()))
            con.commit()
            return {"status": "baseline", "url": url}
        if row[0] == h:
            return {"status": "unchanged", "url": url}
        con.execute("UPDATE pricing SET hash=?, snippet=?, url=?, checked_at=? WHERE domain=?",
                    (h, snippet, url, _now(), domain))
        con.commit()
        return {"status": "changed", "url": url}
    return {"status": "none", "url": None}


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")