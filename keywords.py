import os
import re
import httpx
from dotenv import load_dotenv

load_dotenv()

URL = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
STOP = {"how", "to", "the", "a", "an", "what", "is", "it", "why", "best",
        "your", "for", "and", "you", "in", "we", "our", "this", "that",
        "from", "with", "their", "share", "of", "on", "at", "by", "or",
        "are", "can", "will", "now", "just", "top", "new", "wtf", "i",
        "my", "do", "does", "get", "use", "using", "into", "about",
        "as", "an", "be", "its", "so", "if", "than", "then", "when"}

def extract_keyword(title):
    """Take the part before ':' or ' - ', drop filler words, keep up to 4 words."""
    t = (title or "").replace("\xa0", " ")
    t = re.sub(r"[’']s\b", "", t)
    head = re.split(r":|\s[-–—|]\s|\|", t)[0].strip() or t
    head = re.sub(r"[^\w\s-]", " ", head.lower())
    head = re.sub(r"\b(19|20)\d{2}\b", " ", head)  # remove years like 2026
    words = [w for w in head.split() if w not in STOP and not w.isdigit()]
    return " ".join(words[:4]) or t.lower()

def _init_cache(con):
    con.execute("""CREATE TABLE IF NOT EXISTS keyword_cache(
        keyword TEXT PRIMARY KEY, volume INTEGER,
        fetched_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    con.commit()

def _fetch(keywords):
    """Returns (dict keyword->volume, warning or None). Never raises."""
    login = os.getenv("DATAFORSEO_LOGIN")
    password = os.getenv("DATAFORSEO_PASSWORD")
    if not login or not password:
        return {}, "No DataForSEO credentials set (keyword data unavailable)"
    body = [{"keywords": keywords, "location_code": 2840, "language_code": "en"}]
    try:
        r = httpx.post(URL, auth=(login, password), json=body, timeout=60)
    except httpx.HTTPError as e:
        return {}, f"Keyword API unreachable: {e}"
    if r.status_code == 401:
        return {}, "Invalid DataForSEO credentials (keyword data unavailable)"
    if r.status_code == 403:
        try:
            msg = r.json().get("status_message", "access denied")
        except Exception:
            msg = "access denied"
        return {}, f"DataForSEO access denied: {msg[:120]}"
    if r.status_code == 402:
        return {}, "DataForSEO balance exhausted (HTTP 402): keyword data unavailable"
    if r.status_code != 200:
        return {}, f"Keyword API error: HTTP {r.status_code}"
    try:
        data = r.json()
        if data.get("status_code") != 20000:
            return {}, f"Keyword API: {data.get('status_message')}"
        task = data["tasks"][0]
        if task.get("status_code") != 20000:
            return {}, f"Keyword API: {task.get('status_message')}"
        return {i["keyword"].lower(): i.get("search_volume")
                for i in (task.get("result") or [])}, None
    except Exception as e:
        return {}, f"Could not read keyword API response: {e}"

def get_volumes(con, keywords):
    """Returns (dict keyword->volume or None, warning or None). Uses cache first."""
    _init_cache(con)
    keywords = list(dict.fromkeys(k.lower() for k in keywords))
    result, missing = {}, []
    for k in keywords:
        row = con.execute("SELECT volume FROM keyword_cache WHERE keyword=?", (k,)).fetchone()
        if row:
            result[k] = row[0]
        else:
            missing.append(k)
    warning = None
    if missing:
        fetched, warning = _fetch(missing)
        for k, v in fetched.items():
            con.execute("INSERT OR REPLACE INTO keyword_cache(keyword, volume) VALUES (?,?)", (k, v))
            result[k] = v
        con.commit()
    return result, warning
def candidates(title):
    """Several keyword guesses for one title, longest first."""
    words = extract_keyword(title).split()
    cands = []
    for n in (len(words), 3, 2):
        if 1 <= n <= len(words):
            cands.append(" ".join(words[:n]))
    if len(words) >= 3:
        cands.append(" ".join(words[-2:]))
    return list(dict.fromkeys(cands))

def best_keywords(con, titles):
    """Returns (list of (keyword, volume) matching titles, warning)."""
    cmap = [candidates(t) for t in titles]
    all_c = [c for cs in cmap for c in cs]
    volumes, warning = get_volumes(con, all_c)
    picks = []
    for cs in cmap:
        scored = [(c, volumes.get(c)) for c in cs]
        valid = [(c, v) for c, v in scored if isinstance(v, int) and v > 0]
        if valid:
            best, vol = max(valid, key=lambda x: (len(x[0].split()), x[1]))
        else:
            best, vol = cs[0], None
        picks.append((best, vol))
    return picks, warning