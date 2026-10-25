import re
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from db import init, save_new
from discovery import discover_posts, clean_domain
from keywords import best_keywords
from pricing import check_pricing
from alerts import send_slack, send_pricing_alert

app = FastAPI()
FIRST_RUN_SHOW = 5


def run_check(raw):
    domain = clean_domain(raw)
    con = init()
    is_first = con.execute("SELECT COUNT(*) FROM posts WHERE domain=?", (domain,)).fetchone()[0] == 0
    res = discover_posts(raw, con)
    if res["status"] != "ok":
        return {"status": res["status"], "domain": domain, "message": res["message"], "new": []}

    new = save_new(con, domain, res["posts"])
    total = con.execute("SELECT COUNT(*) FROM posts WHERE domain=?", (domain,)).fetchone()[0]

    # Pricing page check (runs on every check, even if there are no new posts)
    try:
        pr = check_pricing(con, domain)
    except Exception:
        pr = {"status": "none", "url": None}
    pricing_msg = {"none": "No pricing page found.",
                   "baseline": "Pricing page recorded as baseline.",
                   "unchanged": "Pricing page unchanged.",
                   "changed": "PRICING CHANGED since last check."}[pr["status"]]
    if pr["status"] == "changed":
        send_pricing_alert(domain, pr["url"])

    out = {"status": "ok", "domain": domain, "source": res["source"], "found": res["total"],
           "new_count": len(new), "previously_seen": total - len(new), "first_run": is_first,
           "warning": None, "slack": None, "new": [], "message": "", "pricing": pricing_msg}
    if not new:
        out["message"] = "Nothing new since the last check."
        return out

    shown = new[:FIRST_RUN_SHOW] if is_first else new
    headline = None
    if is_first:
        headline = f"{domain}: tracking started, indexed {len(new)} posts (latest {len(shown)} shown)"
        out["message"] = f"First scan: baseline of {len(new)} posts stored. Showing the latest {len(shown)}."
    picks, warning = best_keywords(con, [t for t, _, _ in shown])
    out["warning"] = warning
    items = []
    for (title, link, date), (kw, vol) in zip(shown, picks):
        desc = con.execute("SELECT description FROM posts WHERE url=?", (link,)).fetchone()
        out["new"].append({"title": title, "url": link, "date": date, "keyword": kw,
                           "volume": vol, "description": desc[0] if desc else None})
        items.append((title, link, date, kw, vol))
    ok, msg = send_slack(domain, items, warning, headline)
    out["slack"] = msg
    return out

@app.get("/api/check")
def api_check(domain: str):
    try:
        return run_check(domain)
    except Exception as e:
        return {"status": "error", "message": f"Unexpected error: {e}", "new": []}


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Competitor Monitor</title>
<style>
body{font-family:system-ui,sans-serif;max-width:860px;margin:40px auto;padding:0 16px;color:#222}
input{padding:10px;width:60%;font-size:16px} button{padding:10px 18px;font-size:16px;cursor:pointer}
.box{margin-top:20px;padding:12px 16px;border-radius:8px;background:#f3f4f6}
.warn{background:#fff7e0}.err{background:#fde8e8}.ok{background:#e8f7ec}
table{border-collapse:collapse;width:100%;margin-top:16px} td,th{border-bottom:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}
small{color:#666}
</style></head><body>
<h1>Competitor Monitor</h1>
<p>Enter a competitor domain. The tool finds its blog posts and reports only what is new since the last check.</p>
<input id="d" placeholder="example.com"> <button onclick="run()">Run check</button>
<div id="out"></div>
<script>
function esc(s){return (s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
async function run(){
  const out=document.getElementById("out");
  const d=document.getElementById("d").value.trim();
  if(!d){return}
  out.innerHTML='<div class="box">Checking... this can take up to a minute on a first scan.</div>';
  let r;
  try{ r=await (await fetch("/api/check?domain="+encodeURIComponent(d))).json(); }
  catch(e){ out.innerHTML='<div class="box err">Request failed: '+esc(String(e))+'</div>'; return; }
  if(r.status!=="ok"){ out.innerHTML='<div class="box err"><b>'+esc(r.status)+'</b>: '+esc(r.message)+'</div>'; return; }
  let h='<div class="box ok"><b>'+esc(r.domain)+'</b>: found '+r.found+' posts via '+esc(r.source)+
        ' | '+r.new_count+' new | '+r.previously_seen+' previously seen<br>'+esc(r.message)+'</div>';
  if(r.warning) h+='<div class="box warn">Warning: '+esc(r.warning)+'</div>';
      if(r.pricing) h+='<div class="box '+(r.pricing.startsWith("PRICING")?"warn":"")+'">Pricing: '+esc(r.pricing)+'</div>';
  if(r.slack) h+='<div class="box">Slack: '+esc(r.slack)+'</div>';
  if(r.new.length){
    h+='<table><tr><th>Post</th><th>Date</th><th>Keyword</th><th>Volume</th></tr>';
    for(const p of r.new){
      h+='<tr><td><a href="'+esc(p.url)+'" target="_blank">'+esc(p.title)+'</a><br><small>'+esc(p.description)+'</small></td><td>'+
         esc(p.date||"unknown")+'</td><td>'+esc(p.keyword)+'</td><td>'+(p.volume==null?"unavailable":p.volume.toLocaleString())+'</td></tr>';
    }
    h+='</table>';
  }
  out.innerHTML=h;
}
document.getElementById("d").addEventListener("keydown",e=>{if(e.key==="Enter")run()});
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE