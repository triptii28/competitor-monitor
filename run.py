import sys
from db import init, save_new
from discovery import discover_posts, clean_domain
from keywords import best_keywords
from alerts import send_slack

FIRST_RUN_SHOW = 5  # on a brand-new domain, only alert on the newest N

raw = sys.argv[1]
domain = clean_domain(raw)
con = init()
is_first = con.execute("SELECT COUNT(*) FROM posts WHERE domain=?", (domain,)).fetchone()[0] == 0

res = discover_posts(raw, con)
if res["status"] != "ok":
    print(f"[{res['status']}] {res['message']}")
    sys.exit(0)

new = save_new(con, domain, res["posts"])
print(f"Source: {res['source']} | {res['total']} posts found, {len(new)} NEW")

if not new:
    print("  Nothing new, no alert sent.")
    sys.exit(0)

shown = new[:FIRST_RUN_SHOW] if is_first else new
headline = None
if is_first:
    headline = f"{domain}: tracking started, indexed {len(new)} posts (latest {len(shown)} shown)"
    print(f"  First run: baseline of {len(new)} posts stored, alerting on the latest {len(shown)}")

picks, warning = best_keywords(con, [t for t, _, _ in shown])
if warning:
    print("  WARNING:", warning)
items = []
for (title, link, date), (kw, vol) in zip(shown, picks):
    vol_text = f"{vol:,}" if isinstance(vol, int) else "unavailable"
    print(f"  + {title}\n      keyword: {kw} | volume: {vol_text}")
    items.append((title, link, date, kw, vol))
ok, msg = send_slack(domain, items, warning, headline)
print("  Slack:", msg)