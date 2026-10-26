# Competitor Monitor

By Tripti Gupta

A web tool that takes a competitor's domain, finds its blog posts with my own scraper, remembers what it has seen, and alerts Slack about new posts with keyword and search volume data.

**Live demo:** <https://competitor-monitor-twyb.onrender.com/>
(Free hosting: the first load after inactivity takes 30-60 seconds.)

## How it works

Pipeline per domain: **discover posts -> diff against stored posts -> enrich new posts with keyword data -> Slack alert**

### 1. Discovery (own scraper, no scraping API)

Tried in order until posts are found:

1. **RSS/Atom feed**: found via `<link rel="alternate">` on the homepage and /blog, then common feed paths. Gives real titles and publish dates.
2. **Sitemap**: from `robots.txt` or `/sitemap.xml`, following sitemap indexes and preferring blog-related sitemaps. URLs are filtered to article-like paths (category, tag and author pages excluded).
3. **HTML crawl**: homepage links plus `/blog`, `/resources`, `/articles`, `/news`, `/insights`, `/learn` and `blog.<domain>`.

For sitemap and crawl results, each new post page is fetched to read the title (`og:title`, `<title>`, `h1`), date (`article:published_time`, JSON-LD `datePublished`, `<time>`) and meta description. At most 25 new pages are fetched per run, with a short delay between requests.

### 2. Change detection

- Posts are stored in a database (`domain, url UNIQUE, title, published_at, description, first_seen_at`).
- URLs are normalized (lowercase host, no `www.`, no trailing slash, no fragments, no `utm_` params).
- **"New" means the normalized URL is not in the database yet.** It does not depend on dates, because many sites have unreliable dates. Running twice reports nothing the second time.
- **First run behavior:** the first scan of a domain is a baseline. All posts are stored, but the alert shows only the latest 5, with a headline such as "tracking started, indexed N posts".

### 3. Keyword enrichment

- No API gives a post's "target keyword", so candidates are derived from the title (text before a colon, stop words and numbers removed, several shorter variants).
- Search volumes come from the DataForSEO Google Ads Search Volume API in one batched request, and are cached per keyword.
- The most specific candidate that has volume is chosen. If none has data, the volume shows as "unavailable".
- Known limitation: this is a heuristic, not true target-keyword detection, so some keywords are generic or odd.

### 4. Alerts

A Slack Block Kit message via an incoming webhook: headline, linked titles, dates, keyword and volume. Nothing is sent when there are no new posts.

### 5. Pricing change tracking

On every check, the pricing page text is hashed and compared with the stored hash. A change triggers a Slack alert and a warning in the UI.

## Error handling

| Situation | Behavior |
| --- | --- |
| Invalid domain / DNS failure | `invalid_domain` message |
| No blog found | `no_blog`: "No blog/content section detected" |
| 403/429/503 on the homepage | Feed, sitemap and crawl are still tried. Only if all fail: `blocked` message |
| Site not responding | `unreachable` message |
| Missing or invalid keyword API key / unverified account | Warning shown in the UI and Slack. Posts are still reported with volume "unavailable" |
| Slack webhook missing or failing | Reported in the UI, no crash |

## Tech

Python, FastAPI, httpx, BeautifulSoup/lxml, SQLite locally and Postgres (Neon) in production, Render hosting.

## Run locally

    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
    copy .env.example .env     # then fill in values
    uvicorn app:app --reload
CLI: `python run.py example.com`

## Environment variables

| Name | Purpose |
| --- | --- |
| `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` | DataForSEO API credentials |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook |
| `DATABASE_URL` | Postgres connection string (optional; SQLite is used when unset) |

## Known limitations

- Blogs rendered only by JavaScript with no feed or sitemap can't be crawled. A headless browser (Playwright) would be the next step.
- Aggressive bot protection (Cloudflare challenges) can block all layers.
- Meta descriptions are fetched for at most 25 new posts per run, so very large first scans leave older posts without one.
- Large first scans can take up to a minute.
- Pricing tracking hashes the visible text of /pricing, /plans, /pricing-plans or /price. Pages that rotate content (banners, dates) can cause false "changed" alerts, and JavaScript-only pricing pages may not be detected.
- Keyword volumes depend on DataForSEO trial credit. When the credit is exhausted (HTTP 402) the tool shows a warning and reports posts with volume "unavailable". Keywords already fetched are cached and still show their volumes.