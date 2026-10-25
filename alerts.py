import os
import httpx
from dotenv import load_dotenv

load_dotenv()

def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def send_slack(domain, items, warning=None, headline=None):
    """items = list of (title, link, date, keyword, volume). Returns (ok, message)."""
    url = os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        return False, "SLACK_WEBHOOK_URL not set"
    n = len(items)
    headline = headline or f"{domain} published {n} new post{'s' if n != 1 else ''}"
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": headline}}]
    for title, link, date, kw, vol in items[:10]:
        vol_text = f"{vol:,}" if isinstance(vol, int) else "unavailable"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text":
            f"*<{link}|{_esc(title)}>*\n{date or 'date unknown'}\nKeyword: `{kw}` | Volume: {vol_text}"}})
    if n > 10:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"...and {n - 10} more"}]})
    if warning:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f":warning: {warning}"}]})
    try:
        r = httpx.post(url, json={"text": headline, "blocks": blocks}, timeout=15)
    except httpx.HTTPError as e:
        return False, f"Slack unreachable: {e}"
    if r.status_code != 200:
        return False, f"Slack error {r.status_code}: {r.text[:100]}"
    return True, "sent"

def send_pricing_alert(domain, url):
    hook = os.getenv("SLACK_WEBHOOK_URL")
    if not hook:
        return False, "SLACK_WEBHOOK_URL not set"
    text = f":moneybag: Pricing page changed on {domain}: {url}"
    try:
        r = httpx.post(hook, json={"text": text}, timeout=15)
    except httpx.HTTPError as e:
        return False, f"Slack unreachable: {e}"
    return (r.status_code == 200), ("sent" if r.status_code == 200 else f"Slack error {r.status_code}")