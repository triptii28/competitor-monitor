import os
import sqlite3
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from dotenv import load_dotenv

load_dotenv()

DB = "monitor.db"
DATABASE_URL = os.getenv("DATABASE_URL")


def normalize_url(url):
    """Make equivalent URLs identical so they aren't counted as new."""
    p = urlparse(url.strip())
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/") or "/"
    query = urlencode([(k, v) for k, v in parse_qsl(p.query)
                       if not k.lower().startswith("utm_")])
    return urlunparse(("https", host, path, "", query, ""))


class PG:
    """Makes a Postgres connection behave like the SQLite one the rest of the code uses."""

    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=()):
        s = sql.strip()
        if s.startswith("INSERT OR IGNORE INTO"):
            s = s.replace("INSERT OR IGNORE INTO", "INSERT INTO", 1) + " ON CONFLICT DO NOTHING"
        elif s.startswith("INSERT OR REPLACE INTO keyword_cache"):
            s = ("INSERT INTO keyword_cache(keyword, volume) VALUES (?,?) "
                 "ON CONFLICT (keyword) DO UPDATE SET volume=EXCLUDED.volume")
        s = s.replace("?", "%s")
        cur = self.conn.cursor()
        cur.execute(s, params)
        return cur

    def commit(self):
        self.conn.commit()


def init():
    if DATABASE_URL:
        import psycopg
        con = PG(psycopg.connect(DATABASE_URL))
        con.execute("""CREATE TABLE IF NOT EXISTS posts(
            id SERIAL PRIMARY KEY,
            domain TEXT,
            url TEXT UNIQUE,
            title TEXT,
            published_at TEXT,
            description TEXT,
            first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        con.commit()
        return con
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS posts(
        id INTEGER PRIMARY KEY,
        domain TEXT,
        url TEXT UNIQUE,
        title TEXT,
        published_at TEXT,
        first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cols = [r[1] for r in con.execute("PRAGMA table_info(posts)")]
    if "description" not in cols:
        con.execute("ALTER TABLE posts ADD COLUMN description TEXT")
    con.commit()
    return con


def save_new(con, domain, posts):
    """posts = list of (title, url, date[, description]). Returns new ones as (title, url, date)."""
    new = []
    for p in posts:
        title, url, date = p[0], p[1], p[2]
        desc = p[3] if len(p) > 3 else None
        url = normalize_url(url)
        cur = con.execute(
            "INSERT OR IGNORE INTO posts(domain, url, title, published_at, description) VALUES (?,?,?,?,?)",
            (domain, url, title, date, desc))
        if cur.rowcount == 1:
            new.append((title, url, date))
    con.commit()
    return new