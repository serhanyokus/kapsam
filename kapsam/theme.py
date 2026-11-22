"""Ortak görsel tema: tüm sayfalar (durum, tarama, risk, şirket notları) aynı sade tasarımı kullanır.

Sayfa şablonları içeriği üretir; `restyle()` mevcut <style> bloğunu tema CSS'iyle değiştirir, üste gezinme çubuğu
ve alta altbilgi ekler. Böylece içerik ile tasarım ayrı kalır ve tasarım tek yerden değişir.
Açık/koyu mod sistem ayarını izler.
"""
from __future__ import annotations

import os
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
.tw{overflow-x:auto;border-radius:18px;box-shadow:var(--shadow);background:var(--card);margin:10px 0 8px}
.tw>table{box-shadow:none;border-radius:0;margin:0}
.wrap .tw{box-shadow:none;border-radius:0;margin:0;overflow:visible}
.wrap{overflow-x:auto;border-radius:18px;box-shadow:var(--shadow);background:var(--card);margin:10px 0}
.wrap table{box-shadow:none;border-radius:0;margin:0;white-space:nowrap}
.wrap th{position:sticky;top:0;z-index:1;cursor:pointer;user-select:none}
input{font:inherit;font-size:15px;padding:11px 16px;width:360px;max-width:100%;border-radius:12px;border:1px solid var(--line);
background:var(--card);color:var(--text);outline:none;margin:8px 0 10px}
input:focus{border-color:var(--accent);box-shadow:0 0 0 4px var(--accent-weak)}
img{max-width:100%;height:auto;display:block;border-radius:14px;background:#fff;margin:10px 0}
img.narrow{max-width:min(560px,100%)}
ul{padding-left:20px}
.more{display:inline-block;margin-top:10px;font-size:15px;font-weight:500}
.search{position:relative;max-width:520px}
.search input{width:100%;font-size:17px;padding:14px 18px;border-radius:14px}
.hits{position:absolute;left:0;right:0;top:58px;background:var(--card);border-radius:14px;box-shadow:0 12px 32px rgba(0,0,0,.12);z-index:5;overflow:hidden}
.hits a{display:flex;justify-content:space-between;gap:12px;padding:10px 18px;color:var(--text);border-bottom:1px solid var(--line);font-size:15px}
.hits a:last-child{border-bottom:0}.hits a span{color:var(--muted);font-size:13px}.hits a.sel{background:var(--accent-weak);text-decoration:none}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:6px 12px;font-size:14px;display:inline-flex;gap:8px;align-items:center}
.chip button{border:0;background:none;color:var(--muted);cursor:pointer;font-size:15px;padding:0}
.btn{font:inherit;font-size:15px;border:0;border-radius:12px;padding:11px 18px;background:var(--accent);color:#fff;cursor:pointer}
.btn.sec{background:var(--card);color:var(--accent);border:1px solid var(--line)}
.lang{border:1px solid var(--line);border-radius:999px;padding:2px 10px;font-size:12px}
footer{max-width:1080px;margin:0 auto;padding:28px 22px 60px;color:var(--muted);font-size:12px;border-top:1px solid var(--line)}
@media(max-width:760px){main{padding-top:36px}.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.grid2{grid-template-columns:minmax(0,1fr)}
.nav .in{gap:16px}.kpi b{font-size:24px}h2{margin-top:40px}}
.lvl{display:inline-block;min-width:52px;text-align:center;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700;letter-spacing:.02em;color:#fff;white-space:nowrap}
.lvl.al{background:#248a3d}.lvl.tut{background:#8e8e93}.lvl.azalt{background:#ff9f0a}.lvl.sat{background:#d70015}.lvl.yok{background:#e5e5ea;color:#1d1d1f}
.lvl.big{font-size:15px;padding:6px 16px;vertical-align:middle;margin-left:10px}
.kpi span.lvl{display:inline-block;color:#fff;font-size:13px;line-height:1.4}.kpi span.lvl.yok{color:#1d1d1f}
.wrap{background:linear-gradient(to right,var(--card) 30%,rgba(255,255,255,0)) left/40px 100% no-repeat local,
linear-gradient(to left,var(--card) 30%,rgba(255,255,255,0)) right/40px 100% no-repeat local,
radial-gradient(farthest-side at 0 50%,rgba(0,0,0,.12),transparent) left/12px 100% no-repeat scroll,
radial-gradient(farthest-side at 100% 50%,rgba(0,0,0,.12),transparent) right/12px 100% no-repeat scroll,var(--card)}
.wrap td.l{white-space:normal;min-width:110px;max-width:420px}.wrap td:first-child{white-space:nowrap;min-width:0}
.tw td.l{max-width:520px}
footer a{color:var(--muted);text-decoration:underline}footer .links{margin-bottom:8px;display:flex;flex-wrap:wrap;gap:14px}
@media print{.nav,footer{display:none}body{background:#fff}table,.kpi,.card{box-shadow:none}}
"""

NAV = {"tr": [("index.html", "Genel bakış"), ("tarama.html", "Tarama"), ("sektor/index.html", "Sektörler"), ("risk/index.html", "Risk")],
       "en": [("index.html", "Overview"), ("tarama.html", "Screener"), ("sektor/index.html", "Sectors"), ("risk/index.html", "Risk")]}
SITE = "https://serhanyokus.github.io/kapsam/"
REPO = "https://github.com/serhanyokus/kapsam"
GSC_VERIFY = "m1HmCEtdRpV9c6KnBaNNnEVRQq2Z4N7As5znHe2d05o"   # Google Search Console doğrulaması (herkese açık etiket)
FOOT = {"tr": ("KAPSAM · TMS 29 farkındalıklı BIST araştırma asistanı · Veri: KAP, TCMB EVDS, Yahoo Finance (gecikmeli). "
               "Bu sayfalar bir araştırma aracının çıktısıdır; yatırım tavsiyesi değildir."),
        "en": ("KAPSAM · IAS 29-aware Borsa Istanbul research assistant · Data: KAP, CBRT EVDS, Yahoo Finance (delayed). "
               "These pages are the output of a research tool; not investment advice.")}


FOOT_LINKS = {"tr": [("yontem.html", "Yöntem"), ("durum.html", "Sistem durumu"), (REPO, "Kaynak kod (GitHub)"),
                      (REPO + "/issues", "Geri bildirim")],
              "en": [("yontem.html", "Methodology"), ("durum.html", "System status"), (REPO, "Source code (GitHub)"),
                      (REPO + "/issues", "Feedback")]}
FOOT_NOTE = {"tr": "Şirket sayıları sayfaya göre değişir: tarama ve notlar finansal tablosu olan şirketleri, risk sayfası fiyat serisi olan "
                   "hisseleri, evren İş Yatırım'ın tüm BIST listesini kapsar.",
             "en": "Company counts differ by page: the screener and notes cover companies with financial statements, the risk page covers "
                   "stocks with price series, and the universe is the full BIST list from İş Yatırım."}


def foot_html(lang: str = "tr", root: str = "") -> str:
    gizli = os.environ.get("KAPSAM_GIZLI") == "1"
    links = "" if gizli else "<div class='links'>" + "".join(
        f"<a href='{h if h.startswith('http') else root + h}'>{lab}</a>" for h, lab in FOOT_LINKS[lang]) + "</div>"
    return f"<footer>{links}{FOOT[lang]}<br>{FOOT_NOTE[lang]}</footer>"


def seo_head(title: str, lang: str = "tr", here: str = "") -> str:
    """Arama motoru ve paylaşım etiketleri. Gizli sürümde yalnızca noindex."""
    import html as _h
    if os.environ.get("KAPSAM_GIZLI") == "1":
        return "<!--seo--><meta name='robots' content='noindex,nofollow'><!--/seo-->"
    here = here or "index.html"
    tr_url, en_url = SITE + here, SITE + "en/" + here
    url = tr_url if lang == "tr" else en_url
    t = _h.escape(re.sub(r"\s+", " ", title).strip() or "KAPSAM")
    desc = ({"tr": f"{t} — TMS 29'a göre düzeltilmiş çeyrekler, temel kâr, İNA (DCF) değerlemesi, kâr kalitesi ve risk göstergeleri. "
                   "Borsa İstanbul, her iş günü güncellenir.",
             "en": f"{t} — IAS 29-adjusted quarters, core earnings, DCF valuation, earnings quality and risk metrics. "
                   "Borsa Istanbul, updated every business day."})[lang]
    img = SITE + "og.png"
    return ("<!--seo-->"
            f"<meta name='google-site-verification' content='{GSC_VERIFY}'>"
            f"<meta name='description' content='{desc}'><link rel='canonical' href='{url}'>"
            f"<link rel='alternate' hreflang='tr' href='{tr_url}'><link rel='alternate' hreflang='en' href='{en_url}'>"
            f"<link rel='alternate' hreflang='x-default' href='{tr_url}'>"
            f"<meta property='og:type' content='website'><meta property='og:site_name' content='KAPSAM'>"
            f"<meta property='og:title' content='{t}'><meta property='og:description' content='{desc}'>"
            f"<meta property='og:url' content='{url}'><meta property='og:image' content='{img}'>"
            f"<meta property='og:locale' content='{'tr_TR' if lang == 'tr' else 'en_US'}'>"
            f"<meta name='twitter:card' content='summary_large_image'><meta name='twitter:image' content='{img}'>"
            "<!--/seo-->")


def _title_of(page: str) -> str:
    m = re.search(r"<title>(.*?)</title>", page, flags=re.S)
    import html as _h
    return _h.unescape(m.group(1)) if m else "KAPSAM"


def pct(v, d: int = 1, sign: bool = False) -> str:
    """Türkçe yüzde: %18,6 (işaretli: +%2,4 / −%2,4). Geçersizse –."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "–"
    if v != v or v in (float("inf"), float("-inf")):
        return "–"
    s = ("+" if v > 0 else "−" if v < 0 else "") if sign else ("−" if v < 0 else "")
    return s + "%" + f"{abs(v) * 100:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def num(v, d: int = 2) -> str:
    """Türkçe sayı: 11.131,30."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "–"
    if v != v or v in (float("inf"), float("-inf")):
        return "–"
    return ("−" if v < 0 else "") + f"{abs(v):,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def mult(v, d: int = 1) -> str:
    s = num(v, d)
    return s if s == "–" else s + "x"


def nav_html(active: str, root: str, lang: str = "tr", here: str = "") -> str:
    items = NAV[lang] + ([("siniflar.html", "Seviyeler · değerleme · gündem" if lang == "tr" else "Levels · valuation · agenda")]
                         if os.environ.get("KAPSAM_GIZLI") == "1" else
                         [("kalite.html", "Kalite" if lang == "tr" else "Quality"), ("gundem.html", "Gündem" if lang == "tr" else "Agenda")])
    links = "".join(f"<a href='{root}{href}'{' class=on' if href == active else ''}>{label}</a>" for href, label in items)
    other = (f"<a class='lang' href='{root}en/{here}'>EN</a>" if lang == "tr" else f"<a class='lang' href='{root}../{here}'>TR</a>") if here else ""
    return f"<nav class='nav'><div class='in'><a class='brand' href='{root}index.html'>KAPSAM</a>{links}{other}</div></nav>"


def restyle(page: str, active: str = "", root: str = "", lang: str = "tr", here: str = "") -> str:
    """Şablonun <style> bloğunu tema ile değiştirir; gezinme çubuğu, <main> sarmalayıcı ve altbilgi ekler.
    root: sayfanın site köküne göre konumu ('' kök, '../' bir alt klasör). here: sayfanın kökten yolu (dil geçişi için)."""
    page = re.sub(r"<style>.*?</style>", lambda m: "<style>" + CSS + "</style>", page, count=1, flags=re.S)
    if "<style>" not in page:
        page = page.replace("</head>", "<style>" + CSS + "</style></head>", 1)
    nav = nav_html(active, root, lang, here) + "<main>"
    foot = "</main>" + foot_html(lang, root)
    if "<!--seo-->" not in page:
        page = page.replace("</head>", seo_head(_title_of(page), lang, here) + "</head>", 1)
    page = re.sub(r"<body[^>]*>", lambda m: m.group(0) + nav, page, count=1)
    parts = re.split(r"(<script.*?</script>)", page, flags=re.S)          # betiklerin içine dokunma
    page = "".join(x if x.startswith("<script") else
                   re.sub(r"<table(?=[\s>])", "<div class='tw'><table", x).replace("</table>", "</table></div>") for x in parts)
    if lang == "en":
        page = page.replace('<html lang="tr">', '<html lang="en">', 1)
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


_TR = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosuCGIOSUaiu")


def slug(name: str) -> str:
    """Sektör adından dosya adı: 'Perakande - Ticaret' → 'perakande-ticaret'."""
    s = (name or "diger").translate(_TR).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "diger"
