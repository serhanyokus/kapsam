"""Ortak görsel tema: tüm sayfalar (durum, tarama, risk, şirket notları) aynı sade tasarımı kullanır.

Sayfa şablonları içeriği üretir; `restyle()` mevcut <style> bloğunu tema CSS'iyle değiştirir, üste gezinme çubuğu
ve alta altbilgi ekler. Böylece içerik ile tasarım ayrı kalır ve tasarım tek yerden değişir.
Açık/koyu mod sistem ayarını izler.
"""
from __future__ import annotations

import re

# Grafik paleti (matplotlib) — CSS değişkenleriyle aynı aile
ACCENT, ORANGE, GREY, GREEN, RED = "#0071e3", "#ff9f0a", "#86868b", "#34c759", "#ff3b30"
TEXT = "#1d1d1f"

CSS = """
:root{--bg:#f5f5f7;--card:#ffffff;--text:#1d1d1f;--muted:#6e6e73;--line:#e5e5ea;--accent:#0071e3;--accent-weak:#e8f1fc;
--pos:#248a3d;--neg:#d70015;--warn:#fff8e6;--warn-line:#f5d48a;--nav:rgba(245,245,247,.72);--shadow:0 1px 2px rgba(0,0,0,.04),0 8px 24px rgba(0,0,0,.04)}
@media (prefers-color-scheme:dark){:root{--bg:#000;--card:#1c1c1e;--text:#f5f5f7;--muted:#a1a1a6;--line:#2c2c2e;--accent:#2997ff;
--accent-weak:#0a2a4a;--pos:#30d158;--neg:#ff453a;--warn:#2b2412;--warn-line:#6b5420;--nav:rgba(22,22,23,.72);--shadow:none}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:17px/1.47 -apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display","Helvetica Neue",Inter,system-ui,sans-serif;
letter-spacing:-.01em;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.nav{position:sticky;top:0;z-index:10;background:var(--nav);backdrop-filter:saturate(180%) blur(20px);-webkit-backdrop-filter:saturate(180%) blur(20px);
border-bottom:1px solid var(--line)}
.nav .in{max-width:1080px;margin:0 auto;padding:0 22px;height:48px;display:flex;align-items:center;gap:26px;font-size:13px}
.nav .brand{font-weight:600;font-size:15px;color:var(--text);margin-right:auto;letter-spacing:-.02em}
.nav a{color:var(--text);opacity:.8}.nav a:hover{opacity:1;text-decoration:none}.nav a.on{opacity:1;font-weight:600}
main{max-width:1080px;margin:0 auto;padding:56px 22px 40px}
h1{font-size:clamp(32px,5vw,48px);line-height:1.08;font-weight:700;letter-spacing:-.03em;margin:4px 0 14px}
h2{font-size:24px;line-height:1.17;font-weight:600;letter-spacing:-.02em;margin:56px 0 16px;border:0;padding:0}
h3{font-size:19px;font-weight:600;margin:28px 0 10px}
p{margin:0 0 14px}
.muted,.m{color:var(--muted);font-size:13px;line-height:1.5}
.eyebrow{color:var(--muted);font-size:14px;font-weight:500;margin-bottom:6px}
.lead{font-size:21px;line-height:1.38;color:var(--muted);max-width:760px;margin-bottom:28px}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:26px 0}
.kpi{background:var(--card);border-radius:18px;padding:20px 22px;box-shadow:var(--shadow)}
.kpi span{display:block;font-size:13px;color:var(--muted);line-height:1.35}
.kpi b{display:block;font-size:30px;font-weight:600;letter-spacing:-.025em;margin:6px 0 2px;font-variant-numeric:tabular-nums}
.card{background:var(--card);border-radius:18px;padding:22px 24px;box-shadow:var(--shadow);margin:14px 0}
.warn{background:var(--warn);border:1px solid var(--warn-line);border-radius:14px;padding:14px 18px;margin:18px 0;font-size:15px}
.tag{background:var(--accent-weak);color:var(--accent);padding:2px 10px;border-radius:999px;font-size:13px;font-weight:500}
.grid2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}.grid2>*{min-width:0}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:14px;font-variant-numeric:tabular-nums;background:var(--card);
border-radius:18px;box-shadow:var(--shadow);overflow:hidden;margin:10px 0 8px}
th,td{padding:11px 14px;text-align:right;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
th{font-size:12px;font-weight:600;color:var(--muted);text-transform:none;letter-spacing:0;background:var(--card);white-space:nowrap}
th:first-child,td:first-child,.l{text-align:left}
tbody tr:hover td{background:color-mix(in srgb,var(--accent) 4%,transparent)}
.wrap{overflow-x:auto;border-radius:18px;box-shadow:var(--shadow);background:var(--card);margin:10px 0}
.wrap table{box-shadow:none;border-radius:0;margin:0;white-space:nowrap}
.wrap th{position:sticky;top:0;z-index:1;cursor:pointer;user-select:none}
.wrap th:hover{color:var(--text)}
input{font:inherit;font-size:15px;padding:11px 16px;width:360px;max-width:100%;border-radius:12px;border:1px solid var(--line);
background:var(--card);color:var(--text);outline:none;margin:8px 0 10px}
input:focus{border-color:var(--accent);box-shadow:0 0 0 4px var(--accent-weak)}
img{max-width:100%;height:auto;display:block;border-radius:14px;background:#fff;margin:10px 0}
img.narrow{max-width:min(560px,100%)}
ul{padding-left:20px}
footer{max-width:1080px;margin:0 auto;padding:28px 22px 60px;color:var(--muted);font-size:12px;border-top:1px solid var(--line)}
@media(max-width:760px){main{padding-top:36px}.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.grid2{grid-template-columns:minmax(0,1fr)}
table{display:block;overflow-x:auto}.nav .in{gap:16px}.kpi b{font-size:24px}h2{margin-top:40px}}
@media print{.nav,footer{display:none}body{background:#fff}table,.kpi,.card{box-shadow:none}}
"""

NAV = [("index.html", "Genel bakış"), ("tarama.html", "Tarama"), ("risk/index.html", "Risk")]


def restyle(page: str, active: str = "", root: str = "") -> str:
    """Şablonun <style> bloğunu tema ile değiştirir; gezinme çubuğu, <main> sarmalayıcı ve altbilgi ekler.
    root: sayfanın site köküne göre konumu ('' kök, '../' bir alt klasör)."""
    page = re.sub(r"<style>.*?</style>", "<style>" + CSS + "</style>", page, count=1, flags=re.S)
    if "<style>" not in page:
        page = page.replace("</head>", "<style>" + CSS + "</style></head>", 1)
    links = "".join(f"<a href='{root}{href}'{' class=on' if href == active else ''}>{label}</a>" for href, label in NAV)
    nav = f"<nav class='nav'><div class='in'><a class='brand' href='{root}index.html'>KAPSAM</a>{links}</div></nav><main>"
    foot = ("</main><footer>KAPSAM · TMS 29 farkındalıklı BIST araştırma asistanı · Veri: KAP, TCMB EVDS, Yahoo Finance (gecikmeli). "
            "Bu sayfalar bir araştırma aracının çıktısıdır; yatırım tavsiyesi değildir.</footer>")
    page = re.sub(r"<body[^>]*>", lambda m: m.group(0) + nav, page, count=1)
    return page.replace("</body>", foot + "</body>", 1)


def style_axes(ax, title: str = ""):
    """Grafiklerde sade görünüm: başlık solda, yalnızca alt eksen, ince yatay ızgara."""
    if title:
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color=TEXT, pad=10)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#d2d2d7")
    ax.tick_params(colors="#6e6e73", labelsize=8, length=0)
    ax.grid(axis="y", color="#ececf0", linewidth=0.8)
    ax.set_axisbelow(True)
