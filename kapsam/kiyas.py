"""Faiz, enflasyon ve aracı kurum karşılaştırması (gizli sürüm).

Her hisse için modelin 12 aylık nominal hedefinden beklenen getiri hesaplanır ve üç çıtayla karşılaştırılır:
politika faizi (mevduata yakın risksiz getiri), 12 ay sonrası beklenen enflasyon ve son 12 ay TÜFE.
Aracı kurum görüşü config/kurum_konsensus.csv dosyasından okunur (kaç kurumun model portföyünde, medyan hedef, kaynak, tarih);
bu dosya elle güncellenir, tarihi eskidikçe sayfada "eski" diye işaretlenir.
Çıktı mekanik bir karşılaştırmadır; kişisel yatırım tavsiyesi değildir.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import theme

VARSAYILAN = {"politika_faizi": 0.36, "politika_tarih": "2026-10", "enflasyon_beklentisi_12a": 0.2395}
ESKI_GUN = 90
GRUPLAR = ["Faizi geçiyor", "Enflasyonu geçiyor", "Enflasyonun altında", "Güven düşük", "Değer yok"]
GRUP_RENK = {"Faizi geçiyor": "AL", "Enflasyonu geçiyor": "TUT", "Enflasyonun altında": "SAT", "Güven düşük": "VERİ YOK", "Değer yok": "VERİ YOK"}


def esikler(root: Path, infl: float = np.nan) -> dict:
    """Çıtalar: canlı (EVDS/haber, data/gercek/oranlar.json) → config/takip.json → varsayılan."""
    from . import oranlar
    d = {}
    for k in ("politika_faizi", "enflasyon_beklentisi_12a"):
        v, t, src = oranlar.deger(root, k)
        d[k], d[k + "_tarih"], d[k + "_kaynak"] = v, t, src
    d["politika_tarih"] = f"{d['politika_faizi_tarih']} · {d['politika_faizi_kaynak']}".strip(" ·")
    d["son_tufe"] = infl
    return d


def konsensus(root: Path, prices: dict | None = None) -> pd.DataFrame:
    """Canlı haber taraması (kurumlar.ozet) esas; olmayan hisselerde config/kurum_konsensus.csv (model portföy derlemesi)."""
    from . import kurumlar
    f = Path(root) / "config" / "kurum_konsensus.csv"
    st = pd.DataFrame(columns=["kurum_sayisi", "medyan_hedef", "kaynak", "tarih"])
    if f.exists():
        st = pd.read_csv(f, dtype={"kod": str}).set_index("kod")
        st["medyan_hedef"] = pd.to_numeric(st["medyan_hedef"], errors="coerce")
        st["kurum_sayisi"] = pd.to_numeric(st["kurum_sayisi"], errors="coerce")
    try:
        live = kurumlar.ozet(root, prices)
    except Exception:  # noqa: BLE001
        live = pd.DataFrame()
    if not len(live):
        return st
    st = st.reindex(columns=list(dict.fromkeys(list(st.columns) + list(live.columns))))
    return pd.concat([live, st.drop(index=[i for i in st.index if i in live.index])])


def build(sc: pd.DataFrame, root: Path, infl: float = np.nan, today: pd.Timestamp | None = None) -> tuple[pd.DataFrame, dict]:
    es = esikler(root, infl)
    today = today or pd.Timestamp.today().normalize()
    d = pd.DataFrame(index=sc.index)
    for c in ["ad", "sektor", "seviye", "fiyat", "hedef_12a", "potansiyel", "guven", "bayraklar"]:
        d[c] = sc[c] if c in sc else np.nan
    f = pd.to_numeric(d["fiyat"], errors="coerce")
    h = pd.to_numeric(d["hedef_12a"], errors="coerce")
    d["model_getiri"] = np.where((f > 0) & h.notna(), h / f - 1, np.nan)
    d["faiz_farki"] = d["model_getiri"] - es["politika_faizi"]
    d["enf_farki"] = d["model_getiri"] - es["enflasyon_beklentisi_12a"]

    def grup(r):
        if pd.isna(r["model_getiri"]) or r["seviye"] == "VERİ YOK":
            return "Değer yok"
        if r["guven"] not in ("yüksek", "orta"):
            return "Güven düşük"
        if r["model_getiri"] > es["politika_faizi"]:
            return "Faizi geçiyor"
        if r["model_getiri"] > es["enflasyon_beklentisi_12a"]:
            return "Enflasyonu geçiyor"
        return "Enflasyonun altında"
    d["grup"] = d.apply(grup, axis=1)
    prices = {t: v for t, v in pd.to_numeric(d["fiyat"], errors="coerce").items() if pd.notna(v)}
    k = konsensus(root, prices)
    d = d.join(k, how="left")
    d["kurum_getiri"] = np.where((f > 0) & d["medyan_hedef"].notna(), d["medyan_hedef"] / f - 1, np.nan)
    age = (today - pd.to_datetime(d["tarih"], errors="coerce")).dt.days
    d["kurum_eski"] = age > ESKI_GUN
    d["uyum"] = [_uyum(r, es) for _, r in d.iterrows()]
    return d, es


def _uyum(r, es) -> str:
    """Model ile aracı kurumların aynı yönde olup olmadığı (yalnızca kurum verisi olan hisseler)."""
    if pd.isna(r.get("kurum_sayisi")) and pd.isna(r.get("medyan_hedef")):
        return ""
    m = r["grup"] in ("Faizi geçiyor",)
    if r["grup"] in ("Güven düşük", "Değer yok"):
        return "Model emin değil, kurumlar olumlu"
    return "İkisi de olumlu" if m else "Kurumlar olumlu, model temkinli"


def _p(x) -> str:
    return theme.pct(x) if pd.notna(x) else "–"


def section(d: pd.DataFrame, es: dict) -> str:
    e = html.escape
    cnt = d["grup"].value_counts()
    tiles = "".join(f"<div class='kpi'><span>{e(g)}</span><b>{int(cnt.get(g, 0))}</b></div>" for g in GRUPLAR[:3])

    def row(t, r, kurum=True):
        kur = ""
        if kurum:
            eski = " <span class='muted'>(eski)</span>" if r.get("kurum_eski") else ""
            ks = "" if pd.isna(r.get("kurum_sayisi")) else str(int(r["kurum_sayisi"]))
            tip = e(str(r.get("kurumlar") or r.get("kaynak") or "") if pd.notna(r.get("kurumlar", np.nan)) or pd.notna(r.get("kaynak", np.nan)) else "")
            kur = (f"<td title='{tip}'>{ks}</td><td>{theme.num(r['medyan_hedef']) if pd.notna(r.get('medyan_hedef')) else '–'}</td>"
                   f"<td>{_p(r.get('kurum_getiri'))}{eski}</td><td class='l'>{e(str(r.get('uyum') or ''))}</td>")
        return (f"<tr><td class='l'><a href='{e(t)}.html'><b>{e(t)}</b></a></td><td class='l'>{e(str(r.get('ad') or ''))[:28]}</td>"
                f"<td class='l'>{e(str(r.get('seviye') or ''))}</td><td>{theme.num(r['fiyat']) if pd.notna(r.get('fiyat')) else '–'}</td>"
                f"<td>{theme.num(r['hedef_12a']) if pd.notna(r.get('hedef_12a')) else '–'}</td><td><b>{_p(r['model_getiri'])}</b></td>"
                f"<td>{_p(r['faiz_farki'])}</td><td class='l'>{e(str(r.get('bayraklar') or '') if pd.notna(r.get('bayraklar')) else '')}</td>{kur}</tr>")
    head = ("<tr><th class='l'>Kod</th><th class='l'>Şirket</th><th class='l'>Seviye</th><th>Fiyat</th><th>12a hedef</th><th>Model getirisi</th>"
            "<th>Faiz farkı</th><th class='l'>Bayraklar</th>")
    khead = "<th>Kurum sayısı</th><th>Kurum hedefi</th><th>Kurum getirisi</th><th class='l'>Uyum</th></tr>"
    parts = []
    for g in GRUPLAR[:2]:
        x = d[d["grup"] == g].sort_values("model_getiri", ascending=False)
        if len(x):
            parts.append(f"<h3>{e(g)} <span class='muted'>{len(x)} şirket</span></h3><div class='wrap'><table>{head}{khead}"
                         + "".join(row(t, r) for t, r in x.iterrows()) + "</table></div>")
    kr = d[d["kurum_sayisi"].notna() | d["medyan_hedef"].notna()].sort_values(["kurum_sayisi", "model_getiri"], ascending=False)
    parts.append(f"<h3>Aracı kurumların öne çıkardıkları <span class='muted'>{len(kr)} şirket · model ile yan yana</span></h3>"
                 f"<div class='wrap'><table>{head}{khead}" + "".join(row(t, r) for t, r in kr.iterrows()) + "</table></div>")
    return f"""<h2 id='kiyas'>Faiz, enflasyon ve aracı kurumlarla karşılaştırma</h2>
<p class='lead'>Modelin 12 aylık nominal hedefinden çıkan beklenen getiri, üç çıtayla karşılaştırılır:
politika faizi <b>{_p(es['politika_faizi'])}</b> ({e(str(es.get('politika_tarih', '')))}; mevduata yakın risksiz getiri),
12 ay sonrası beklenen enflasyon <b>{_p(es['enflasyon_beklentisi_12a'])}</b> (TCMB piyasa katılımcıları anketi · {e(str(es.get('enflasyon_beklentisi_12a_tarih', '')))} · {e(str(es.get('enflasyon_beklentisi_12a_kaynak', '')))}) ve son 12 ay TÜFE <b>{_p(es.get('son_tufe'))}</b>.
Hisse riskli olduğu için yalnızca faizi geçmek yetmez; faiz farkı ne kadar büyükse risk primi o kadar yüksektir.</p>
<div class='kpis'>{tiles}</div>
<p class='muted'>Güveni düşük İNA'lar ({int(cnt.get('Güven düşük', 0))}) ve değeri olmayanlar ({int(cnt.get('Değer yok', 0))}) gruplara katılmaz.
Aracı kurum verisi her gün haber ve araştırma sayfalarından taranır (son 120 günde her kurumun son hedefi; kurum sayısının üstüne gelince kurumlar ve hedefleri görünür);
taramada bulunmayan hisselerde config/kurum_konsensus.csv'deki model portföy derlemesi kullanılır; {ESKI_GUN} günden eski hedefler "eski" diye işaretlenir. Bölünme ya da bedelsiz sonrası
eski hedefler fiyatla karşılaştırılamaz. Kurum tavsiyelerinin çoğu "al" yönündedir; "kurumlar olumlu, model temkinli" satırlarında
farkın nedeni gerekçe sütunundadır (çoğunlukla reel ve nominal fark ile kalite bayrakları).</p>
{''.join(parts)}
<p class='m'>Bu bölüm mekanik bir karşılaştırmadır; kişisel yatırım tavsiyesi değildir.</p>"""


def _n(v) -> str:
    v = pd.to_numeric(v, errors="coerce")
    return f"{v:.2f}" if pd.notna(v) else "–"


def summary_md(d: pd.DataFrame, es: dict, n: int = 40) -> str:
    """GitHub Actions iş özeti (siteye girmeden okunabilir)."""
    cnt = d["grup"].value_counts()
    L = [f"## Faiz/enflasyon/kurum karşılaştırması",
         f"Politika faizi {es['politika_faizi']:.1%} · beklenen enflasyon {es['enflasyon_beklentisi_12a']:.1%} · son 12a TÜFE "
         f"{es['son_tufe']:.1%}" if pd.notna(es.get('son_tufe')) else f"Politika faizi {es['politika_faizi']:.1%}",
         "",
         "", " · ".join(f"{g}: {int(cnt.get(g, 0))}" for g in GRUPLAR), ""]

    def tab(x):
        out = ["| Kod | Seviye | Fiyat | 12a hedef | Model | Faiz farkı | Bayrak | Kurum | Kurum hedefi | Kurum getirisi | Uyum |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
        for t, r in x.iterrows():
            f = lambda v: f"{v:.1%}" if pd.notna(v) else "–"  # noqa: E731
            out.append(f"| {t} | {r['seviye']} | {_n(r['fiyat'])} | {_n(r['hedef_12a'])} | {f(r['model_getiri'])} | {f(r['faiz_farki'])} | "
                       f"{r['bayraklar'] if pd.notna(r['bayraklar']) else ''} | "
                       f"{'' if pd.isna(r['kurum_sayisi']) else int(r['kurum_sayisi'])} | "
                       f"{'' if pd.isna(r['medyan_hedef']) else round(r['medyan_hedef'], 2)} | {f(r['kurum_getiri'])}{' (eski)' if r['kurum_eski'] else ''} | {r['uyum']} |")
        return out
    for g in GRUPLAR[:2]:
        x = d[d["grup"] == g].sort_values("model_getiri", ascending=False).head(n)
        L += [f"### {g}", *tab(x), ""]
    kr = d[(d["kurum_sayisi"].notna() | d["medyan_hedef"].notna()) & d["fiyat"].notna()].sort_values("kurum_sayisi", ascending=False)
    L += ["### Aracı kurumların öne çıkardıkları", *tab(kr), "", "_Mekanik karşılaştırma; yatırım tavsiyesi değildir._"]
    return "\n".join(L)
