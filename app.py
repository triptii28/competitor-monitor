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
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Competitor Monitor</title>
<style>
:root{--bg:#f6f7fb;--card:#fff;--text:#1d2433;--muted:#6b7385;--line:#e4e7ef;--accent:#4f46e5;
--okbg:#e6f6ec;--ok:#157a3c;--warnbg:#fff4d6;--warn:#8a5a00;--errbg:#fde8e8;--err:#b42318;--chip:#eef0ff}
@media (prefers-color-scheme:dark){:root{--bg:#10131a;--card:#181c26;--text:#e8ebf3;--muted:#98a1b5;--line:#2a3040;
--accent:#818cf8;--okbg:#14301f;--ok:#6ee7a0;--warnbg:#3a2f10;--warn:#fbd36b;--errbg:#3b1717;--err:#ff9b92;--chip:#232845}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.5}
.wrap{max-width:880px;margin:0 auto;padding:32px 16px 64px}
h1{margin:0 0 4px;font-size:28px}
.sub{color:var(--muted);margin:0 0 24px}
.bar{display:flex;gap:8px;flex-wrap:wrap}
.bar input{flex:1;min-width:200px;padding:12px 14px;font-size:16px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--text)}
.bar button{padding:12px 22px;font-size:16px;font-weight:600;border:0;border-radius:10px;background:var(--accent);color:#fff;cursor:pointer;display:flex;align-items:center;gap:8px}
.bar button:disabled{opacity:.6;cursor:wait}
.spin{width:16px;height:16px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;animation:s .8s linear infinite;display:none}
button:disabled .spin{display:inline-block}
@keyframes s{to{transform:rotate(360deg)}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-top:16px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:13px;font-weight:600}
.b-ok{background:var(--okbg);color:var(--ok)}.b-warn{background:var(--warnbg);color:var(--warn)}
.b-err{background:var(--errbg);color:var(--err)}.b-info{background:var(--chip);color:var(--accent)}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px}
.stat{background:var(--bg);border-radius:10px;padding:10px;text-align:center}
.stat b{display:block;font-size:22px}.stat span{color:var(--muted);font-size:13px}
.post h3{margin:0 0 4px;font-size:17px}
.post a{color:var(--text);text-decoration:none}.post a:hover{color:var(--accent);text-decoration:underline}
.desc{color:var(--muted);font-size:14px;margin:4px 0 10px}
.chip{display:inline-block;background:var(--chip);color:var(--accent);padding:3px 10px;border-radius:8px;font-size:13px;font-weight:600}
.date{color:var(--muted);font-size:13px}
.note{margin-top:12px;padding:10px 14px;border-radius:10px;font-size:14px}
.n-warn{background:var(--warnbg);color:var(--warn)}.n-err{background:var(--errbg);color:var(--err)}
.n-ok{background:var(--okbg);color:var(--ok)}
@media (max-width:520px){.stats{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<h1>Competitor Monitor</h1>
<p class="sub">Enter a competitor domain. The tool finds its blog posts and reports only what is new since the last check.</p>
<div class="bar">
<input id="d" placeholder="example.com" autocomplete="off">
<button id="go" onclick="run()"><span class="spin"></span><span id="lbl">Run check</span></button>
</div>
<div id="out"></div>
</div>
<script>
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
const LABELS={invalid_domain:"Invalid domain",no_blog:"No blog found",blocked:"Blocked by site",unreachable:"Site unreachable",error:"Error"};
async function run(){
  const out=document.getElementById("out"),btn=document.getElementById("go"),lbl=document.getElementById("lbl");
  const d=document.getElementById("d").value.trim();
  if(!d){return}
  btn.disabled=true;lbl.textContent="Checking...";
  out.innerHTML='<div class="card">Working on it. A first scan of a large site can take up to a minute.</div>';
    let r;
  try{
    const resp=await fetch("/api/check?domain="+encodeURIComponent(d));
    const txt=await resp.text();
    try{ r=JSON.parse(txt); }
    catch(e2){ r={status:"error",message:"The server did not return a valid answer (HTTP "+resp.status+"). It may be waking up or the check timed out. Wait a minute and try again."}; }
  }
  catch(e){ out.innerHTML='<div class="card"><span class="badge b-err">Request failed</span> '+esc(e)+'</div>'; done(); return; }
  if(r.status!=="ok"){
    out.innerHTML='<div class="card"><span class="badge b-err">'+esc(LABELS[r.status]||r.status)+'</span><div class="note n-err">'+esc(r.message)+'</div></div>';
    done(); return;
  }
  let h='<div class="card"><div class="row"><b style="font-size:18px">'+esc(r.domain)+'</b>'+
    '<span class="badge b-info">via '+esc(r.source)+'</span>'+
    (r.first_run?'<span class="badge b-warn">First scan (baseline)</span>':'')+
    (r.new_count>0?'<span class="badge b-ok">'+r.new_count+' new</span>':'<span class="badge b-info">Nothing new</span>')+'</div>'+
    '<div class="stats"><div class="stat"><b>'+r.found+'</b><span>posts found</span></div>'+
    '<div class="stat"><b>'+r.new_count+'</b><span>new</span></div>'+
    '<div class="stat"><b>'+r.previously_seen+'</b><span>previously seen</span></div></div>'+
    (r.message?'<div class="note n-ok">'+esc(r.message)+'</div>':'')+
    (r.warning?'<div class="note n-warn">Warning: '+esc(r.warning)+'</div>':'')+
    (r.pricing?'<div class="note '+(r.pricing.startsWith("PRICING")?'n-warn':'n-ok')+'">Pricing: '+esc(r.pricing)+'</div>':'')+
    (r.slack?'<div class="note '+(r.slack==="sent"?'n-ok':'n-warn')+'">Slack: '+esc(r.slack)+'</div>':'')+
    '</div>';
  for(const p of (r.new||[])){
    const vol=(p.volume==null)?'<span class="chip" style="opacity:.6">volume unavailable</span>':'<span class="chip">'+p.volume.toLocaleString()+' searches/mo</span>';
    h+='<div class="card post"><h3><a href="'+esc(p.url)+'" target="_blank" rel="noopener">'+esc(p.title)+'</a></h3>'+
      '<div class="date">'+esc(p.date||"date unknown")+'</div>'+
      (p.description?'<div class="desc">'+esc(p.description)+'</div>':'<div class="desc"></div>')+
      '<div class="row"><span class="chip">'+esc(p.keyword)+'</span>'+vol+'</div></div>';
  }
  out.innerHTML=h;
  done();
}
function done(){const b=document.getElementById("go");b.disabled=false;document.getElementById("lbl").textContent="Run check";}
document.getElementById("d").addEventListener("keydown",e=>{if(e.key==="Enter")run()});
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE