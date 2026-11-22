"""Gündem: Türkiye ve dünyadaki güncel gelişmeler (gizli sürüm). Her iş günü yenilenir ve ölçüme destek olarak kullanılır.

1) Piyasa göstergeleri (Yahoo Finance, gecikmeli): BIST 100, dolar/TL, euro/TL, S&P 500, Nasdaq, VIX, dolar endeksi,
   ABD 10 yıllık faiz, Brent, altın, Euro Stoxx 50, Türkiye ETF'i (TUR).
2) Haber başlıkları (Google Haberler RSS): Türkiye makro, küresel piyasalar ve şirket bazında (seviyesi AL/AZALT/SAT olanlar,
   seviye değiştirenler ve en büyük şirketler). Başlıklar basit bir Türkçe/İngilizce sözlükle olumlu/olumsuz puanlanır.
Ölçüme etkisi (açık kurallar):
   - Hisse risk primi: temel %6; VIX > 25 ise +1 puan; dolar/TL son 1 ayda > %5 arttıysa +1 puan (İNA iskonto oranına girer).
   - Şirket haberleri: son 14 günde en az 2 olumsuz başlık ve olumsuz > olumlu ise "HABER-" hafif bayrağı.
Başlıklar yalnızca başlık ve bağlantı olarak saklanır; haber metni kopyalanmaz.
"""
from __future__ import annotations

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd

INDICATORS = {"XU100.IS": "BIST 100", "USDTRY=X": "Dolar/TL", "EURTRY=X": "Euro/TL", "^GSPC": "S&P 500", "^IXIC": "Nasdaq",
              "^VIX": "VIX (küresel korku endeksi)", "DX-Y.NYB": "Dolar endeksi (DXY)", "^TNX": "ABD 10 yıllık faiz",
              "BZ=F": "Brent petrol", "GC=F": "Altın (ons)", "^STOXX50E": "Euro Stoxx 50", "TUR": "Türkiye ETF (TUR, USD)"}
MACRO_Q = {"tr": ["Merkez Bankası faiz kararı", "TÜİK enflasyon", "Borsa İstanbul", "dolar TL kur", "Türkiye ekonomi büyüme",
                  "Türkiye CDS risk primi"],
           "global": ["Federal Reserve interest rates", "global stock markets", "oil prices OPEC", "ECB interest rates",
                      "China economy", "emerging markets"]}
POS = ["rekor", "artış", "arttı", "yükseldi", "yükseliş", "büyüme", "büyüdü", "kâr", "kar açıkladı", "temettü", "anlaşma", "sözleşme imzaladı",
       "ihale kazandı", "yatırım", "onay", "ihracat", "güçlü", "hedef fiyat", "al tavsiyesi", "geri alım", "bedelsiz", "sipariş",
       "record", "rally", "surge", "gain", "beat", "upgrade", "growth", "rise", "rose", "cut rates", "rate cut"]
NEG = ["zarar", "düştü", "düşüş", "ceza", "soruşturma", "iflas", "konkordato", "dava", "haciz", "iptal", "geriledi", "gerileme", "kayıp",
       "uyarı", "satış baskısı", "temerrüt", "durdur", "grev", "yangın", "kaza", "sert düş", "değer kaybı", "sat tavsiyesi", "tedbir",
       "loss", "plunge", "fall", "fell", "drop", "downgrade", "default", "recession", "crisis", "sell-off", "probe", "lawsuit", "hike"]
ERP_BASE = 0.06


def score(title: str) -> int:
    t = title.lower()
    return sum(w in t for w in POS) - sum(w in t for w in NEG)


def rss(query: str, lang: str = "tr", days: int = 14, session=None, limit: int = 8) -> list[dict]:
    import requests
    hl, gl, ceid = ("tr", "TR", "TR:tr") if lang == "tr" else ("en-US", "US", "US:en")
    url = f"https://news.google.com/rss/search?q={quote(query + f' when:{days}d')}&hl={hl}&gl={gl}&ceid={ceid}"
    r = (session or requests).get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (KAPSAM arastirma)"})
    r.raise_for_status()
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        title = (it.findtext("title") or "").strip()
        try:
            dt = parsedate_to_datetime(it.findtext("pubDate") or "")
        except Exception:  # noqa: BLE001
            dt = None
        src = it.find("source")
        out.append({"baslik": title, "link": it.findtext("link") or "", "tarih": dt.strftime("%Y-%m-%d") if dt else "",
                    "kaynak": src.text if src is not None else "", "puan": score(title)})
        if len(out) >= limit:
            break
    return out


def indicators(downloader=None) -> pd.DataFrame:
    if downloader is None:
        import yfinance as yf
        downloader = lambda syms: yf.download(syms, period="13mo", auto_adjust=True, progress=False)["Close"]  # noqa: E731
    px = downloader(list(INDICATORS)).ffill()
    rows = {}
    for s, name in INDICATORS.items():
        if s not in px or px[s].dropna().empty:
            continue
        x = px[s].dropna()
        last = float(x.iloc[-1])

        def ch(n):
            return float(last / x.iloc[-1 - n] - 1) if len(x) > n else np.nan
        rows[s] = {"ad": name, "son": last, "tarih": str(x.index[-1].date()), "gun": ch(1), "ay": ch(21), "yil": ch(252)}
    return pd.DataFrame(rows).T


def erp_adjustment(ind: pd.DataFrame) -> tuple[float, list[str]]:
    adj, why = 0.0, []
    try:
        vix = float(ind.at["^VIX", "son"])
        if vix > 25:
            adj += 0.01
            why.append(f"VIX {vix:.0f} > 25: küresel risk iştahı zayıf (+1 puan)")
    except Exception:  # noqa: BLE001
        pass
    try:
        usd = float(ind.at["USDTRY=X", "ay"])
        if usd > 0.05:
            adj += 0.01
            why.append(f"dolar/TL son 1 ayda %{usd*100:.1f} arttı (+1 puan)")
    except Exception:  # noqa: BLE001
        pass
    return adj, why or ["olağan koşullar: ek risk primi yok"]


def regime(g: dict) -> dict:
    """Piyasa rejimi: 'riskten kaçış' ise AL için gereken İNA potansiyeli %15'ten %25'e çıkar."""
    ind = g.get("gostergeler", {}) or {}
    why = []

    def v(sym, k):
        try:
            return float(ind[sym][k])
        except Exception:  # noqa: BLE001
            return np.nan
    if v("^VIX", "son") > 25:
        why.append(f"VIX {v('^VIX', 'son'):.0f} (> 25)")
    if v("USDTRY=X", "ay") > 0.05:
        why.append(f"dolar/TL 1 ayda %{v('USDTRY=X', 'ay')*100:.1f}")
    if v("XU100.IS", "ay") < -0.10:
        why.append(f"BIST 100 1 ayda %{v('XU100.IS', 'ay')*100:.1f}")
    off = bool(why)
    return {"riskten_kacis": off, "neden": why, "al_esik": 0.25 if off else 0.15}


def build(root: Path, names: dict[str, str], focus: list[str], downloader=None, session=None, pause: float = 0.4) -> dict:
    """Göstergeleri ve haberleri toplar, data/gercek/gundem.json'a yazar. names: kod → şirket adı."""
    import requests
    s = session or requests.Session()
    out = {"guncelleme": datetime.now(timezone.utc).isoformat(timespec="minutes"), "gostergeler": {}, "erp_ek": 0.0, "erp_neden": [],
           "makro_tr": [], "makro_global": [], "sirket": {}, "hatalar": []}
    try:
        ind = indicators(downloader)
        out["gostergeler"] = json.loads(ind.to_json(orient="index"))
        out["erp_ek"], out["erp_neden"] = erp_adjustment(ind)
    except Exception as e:  # noqa: BLE001
        out["hatalar"].append(f"göstergeler: {e}")
    for key, lang in (("tr", "tr"), ("global", "en")):
        items = []
        for q in MACRO_Q[key]:
            try:
                items += [dict(x, konu=q) for x in rss(q, lang, 7, s, 5)]
            except Exception as e:  # noqa: BLE001
                out["hatalar"].append(f"{q}: {e}")
            time.sleep(pause)
        out["makro_" + key] = items
    for t in focus:
        nm = re.sub(r"\b(A\.?Ş\.?|T\.A\.Ş\.?|Holding)\b", "", names.get(t, t)).strip() or t
        try:
            items = rss(f'"{nm}" OR {t} hisse', "tr", 14, s, 8)
            pos = sum(x["puan"] > 0 for x in items)
            neg = sum(x["puan"] < 0 for x in items)
            out["sirket"][t] = {"haberler": items, "olumlu": pos, "olumsuz": neg,
                                "bayrak": "HABER-" if neg >= 2 and neg > pos else ("HABER+" if pos >= 2 and pos > neg else "")}
        except Exception as e:  # noqa: BLE001
            out["hatalar"].append(f"{t}: {e}")
        time.sleep(pause)
    f = Path(root) / "data" / "gercek" / "gundem.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def load(root: Path) -> dict:
    f = Path(root) / "data" / "gercek" / "gundem.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def focus_list(out_root: Path, universe: pd.DataFrame | None, n_big: int = 60) -> list[str]:
    """Haber taranacak hisseler: önceki çalıştırmada AL/AZALT/SAT olanların en büyükleri, seviye değiştirenler, en büyük şirketler."""
    pick = []
    try:
        ch = pd.read_csv(Path(out_root) / "seviye_degisim.csv")
        pick += list(ch.sort_values("tarih", ascending=False)["kod"].head(30))
    except Exception:  # noqa: BLE001
        pass
    try:
        s = pd.read_csv(Path(out_root) / "siniflar.csv", index_col=0)
        pick += list(s[s["seviye"] == "AL"].index)
    except Exception:  # noqa: BLE001
        pass
    if universe is not None and "kod" in universe:
        from .data.universe import market_caps
        caps = pd.Series(market_caps(universe)).sort_values(ascending=False)
        pick += list(caps.index[:n_big])
    seen, out = set(), []
    for t in pick:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:120]


# ------------------------------------------------------------------ sayfa

def _p(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "–"
    if not np.isfinite(v):
        return "–"
    return ("+" if v > 0 else "−" if v < 0 else "") + f"%{abs(v)*100:.1f}".replace(".", ",")


def _news(items: list[dict], n: int = 12) -> str:
    e = html.escape
    if not items:
        return "<p class='muted'>Başlık bulunamadı.</p>"
    rows = "".join(f"<tr><td class='l'>{e(x.get('tarih',''))}</td><td class='l'><a href='{e(x.get('link',''))}' rel='noopener' target='_blank'>"
                   f"{e(x.get('baslik',''))}</a></td><td class='l'>{e(x.get('kaynak') or '')}</td>"
                   f"<td>{'▲' if x.get('puan',0) > 0 else '▼' if x.get('puan',0) < 0 else '·'}</td></tr>"
                   for x in sorted(items, key=lambda z: z.get("tarih", ""), reverse=True)[:n])
    return f"<table><tr><th class='l'>Tarih</th><th class='l'>Başlık</th><th class='l'>Kaynak</th><th>Ton</th></tr>{rows}</table>"


def section(g: dict) -> str:
    """Seviyeler sayfasına gömülen gündem bölümü (göstergeler + makro/küresel başlıklar + şirket haber akışı özeti)."""
    e = html.escape
    ind = g.get("gostergeler", {})
    irows = "".join(f"<tr><td class='l'>{e(v.get('ad',''))}</td><td>{float(v.get('son',0)):,.2f}</td><td>{_p(v.get('gun'))}</td>"
                    f"<td>{_p(v.get('ay'))}</td><td>{_p(v.get('yil'))}</td></tr>"
                    for v in ind.values()).replace(",", "X").replace(".", ",").replace("X", ".")
    comp = g.get("sirket", {})
    neg = sorted([(t, d) for t, d in comp.items() if d.get("bayrak") == "HABER-"], key=lambda z: -z[1]["olumsuz"])
    pos = sorted([(t, d) for t, d in comp.items() if d.get("bayrak") == "HABER+"], key=lambda z: -z[1]["olumlu"])

    def lst(xs):
        return ", ".join(f"<a href='{e(t)}.html'><b>{e(t)}</b></a> ({d['olumlu']}▲/{d['olumsuz']}▼)" for t, d in xs) or "–"
    return f"""<h2 id='gundem'>Gündem: Türkiye ve dünya</h2>
<div class='grid2'><div><h3>Piyasa göstergeleri</h3><table><tr><th class='l'>Gösterge</th><th>Son</th><th>1 gün</th><th>1 ay</th><th>1 yıl</th></tr>{irows}</table></div>
<div><h3>Şirket haber akışı (son 14 gün)</h3><p class='muted'>Olumsuz (HABER-, seviyeyi etkiler): {lst(neg)}</p>
<p class='muted'>Olumlu (HABER+, gerekçede belirtilir): {lst(pos)}</p></div></div>
<div class='grid2'><div><h3>Türkiye</h3>{_news(g.get('makro_tr', []), 8)}</div><div><h3>Dünya</h3>{_news(g.get('makro_global', []), 8)}</div></div>
<p class="m">Kaynak: Yahoo Finance (gecikmeli), Google Haberler RSS (yalnızca başlık ve bağlantı). Haber tonu başlıktaki kelimelerden otomatik çıkarılır.</p>"""


def page(g: dict, stamp: str) -> str:
    e = html.escape
    ind = g.get("gostergeler", {})
    irows = "".join(f"<tr><td class='l'>{e(v.get('ad',''))}</td><td>{float(v.get('son',0)):,.2f}</td><td>{_p(v.get('gun'))}</td>"
                    f"<td>{_p(v.get('ay'))}</td><td>{_p(v.get('yil'))}</td><td class='l'>{e(str(v.get('tarih','')))}</td></tr>"
                    for v in ind.values()).replace(",", "X").replace(".", ",").replace("X", ".")
    comp = g.get("sirket", {})
    neg = sorted([(t, d) for t, d in comp.items() if d.get("bayrak") == "HABER-"], key=lambda z: -z[1]["olumsuz"])
    pos = sorted([(t, d) for t, d in comp.items() if d.get("bayrak") == "HABER+"], key=lambda z: -z[1]["olumlu"])
    def lst(xs):
        return ", ".join(f"<a href='{e(t)}.html'><b>{e(t)}</b></a> ({d['olumlu']}▲/{d['olumsuz']}▼)" for t, d in xs) or "–"
    blocks = "".join(f"<h3 id='h-{e(t)}'><a href='{e(t)}.html'>{e(t)}</a> <span class='muted'>{d['olumlu']}▲ {d['olumsuz']}▼ {e(d.get('bayrak',''))}</span></h3>"
                     + _news(d.get("haberler", []), 6) for t, d in comp.items() if d.get("haberler"))
    erp = g.get("erp_ek", 0.0)
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Gündem · KAPSAM (gizli)</title><style></style></head><body>
<div class="eyebrow">Gündem · her iş günü yenilenir</div><h1>Türkiye ve dünya, bugün.</h1>
<p class="lead">Piyasa göstergeleri, makro ve küresel başlıklar, {len(comp)} şirketin son 14 günlük haberleri. Bu veriler şirket notlarındaki İNA
iskonto oranına ve kalite bayraklarına açık kurallarla girer.</p>
<div class="kpis"><div class="kpi"><span>Hisse risk primi</span><b>%{(ERP_BASE+erp)*100:.0f}</b><span>temel %6 + gündem eki %{erp*100:.0f}</span></div>
<div class="kpi"><span>Olumsuz haber bayrağı</span><b>{len(neg)}</b><span>HABER- (hafif bayrak)</span></div>
<div class="kpi"><span>Olumlu haber akışı</span><b>{len(pos)}</b><span>bilgi amaçlı</span></div>
<div class="kpi"><span>Taranan şirket</span><b>{len(comp)}</b><span>son 14 gün</span></div></div>
<div class="warn">Gündem eki: {e('; '.join(g.get('erp_neden', [])))}. Haber tonu başlıktaki kelimelerden otomatik çıkarılır ve hatalı olabilir; başlığa tıklayıp
kaynağı okuyun. Yatırım tavsiyesi değildir. {e(stamp[:16].replace('T',' '))} UTC.</div>
<h2>Piyasa göstergeleri</h2><table><tr><th class='l'>Gösterge</th><th>Son</th><th>1 gün</th><th>1 ay</th><th>1 yıl</th><th class='l'>Tarih</th></tr>{irows}</table>
<h2>Türkiye</h2>{_news(g.get('makro_tr', []), 15)}
<h2>Dünya</h2>{_news(g.get('makro_global', []), 15)}
<h2>Şirket haberleri</h2><p class='muted'>Olumsuz akış (HABER-): {lst(neg)}<br>Olumlu akış (HABER+): {lst(pos)}</p>
{blocks}
<p class="m">Kaynaklar: Yahoo Finance (göstergeler, gecikmeli), Google Haberler RSS (başlık ve bağlantı). Haber metinleri saklanmaz.</p>
</body></html>"""
