"""Tüm hisseler için kurala dayalı içsel değer (gizli sürüm). Her iş günü son fiyatla yeniden hesaplanır.

Sanayi şirketleri: reel FCFF İNA (valuation.dcf). Girdiler son 12 ay TMS 29 düzeltmeli rakamlardan otomatik gelir:
  - hasılat: son 12 ay reel; büyüme: son çeyreğin reel yıllık büyümesi, %0–%15 aralığına sıkıştırılır, 5 yılda %2'ye iner
  - marj: son 12 ay esas faaliyet marjından (%0–%40) 10 yılda şirket ve sektör medyanının ortasına yaklaşır
  - reel AOSM: özkaynak maliyeti (reel risksiz %4 + beta × %6) ile vergi sonrası reel borç maliyetinin (%6) ağırlıklı ortalaması, %8–%16
  - net borç: son bilanço; azınlık payı: toplam özkaynak × (1 − ana ortaklık kârı / toplam kâr)
  - değer baz tarih TL'sinden bugünün TL'sine son aylık TÜFE ile taşınır
Banka ve sigorta: kalıntı gelir (gerekçeli PD/DD) = (reel ÖK kârlılığı − %2) / (reel özkaynak maliyeti − %2), 0,3–4 aralığı;
  reel ÖK kârlılığı = (1 + nominal) / (1 + 12 ay sonrası beklenen TÜFE, TCMB anketi) − 1 — sanayi İNA ile aynı reel çerçeve.
Potansiyeli %100'ün üstündeki değerler "düşük güven" sayılır.
12 aylık nominal hedef = bugünkü değer × (1 + son 12 ay TÜFE): fiyatın değere 12 ayda yakınsadığı varsayımı.
Bu bir model çıktısıdır; varsayımlar değişince değer değişir. Yatırım tavsiyesi değildir.
"""
from __future__ import annotations

import html
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from . import pipeline, theme
from . import valuation as val
from .normalize import tms29

RF_REAL, ERP = 0.04, 0.06
KD_REAL = 0.06               # reel borçlanma maliyeti (vergi öncesi)
UZUN_ENF = 0.15             # enflasyon verisi yoksa yedek varsayım
FIN_G_REAL = 0.02           # banka/sigorta: sürekli reel büyüme
# Banka/sigorta reel ÖK kârlılığında kullanılan ileriye dönük enflasyon: TCMB Piyasa Katılımcıları Anketi, 12 ay sonrası yıllık TÜFE
# beklentisi (%23,95). config/takip.json "enflasyon_beklentisi_12a" ile güncellenebilir; yoksa son 12 ay TÜFE kullanılır.
BEKLENEN_ENF = 0.2395
HOLDING_ISKONTO = 0.30       # hasılatı olmayan holding/yatırım şirketlerinde defter değerine uygulanan iskonto
UC_POTANSIYEL = 1.0          # potansiyel bunun üstündeyse model şirketi iyi temsil etmiyor olabilir: güven "düşük"
WACC_MIN, WACC_MAX = 0.08, 0.16
G_MIN, G_MAX, MARGIN_MAX = 0.0, 0.15, 0.40


def _f(v) -> float:
    try:
        v = float(v)
        return v if np.isfinite(v) else np.nan
    except (TypeError, ValueError):
        return np.nan


def _cpi_today_factor(root: Path, base: pd.Period, cpi_q: pd.Series) -> tuple[float, float]:
    """(baz çeyrek sonundan bugüne TÜFE çarpanı, son 12 ay TÜFE)."""
    f = root / "data" / "gercek" / "tufe_aylik.csv"
    try:
        m = pd.read_csv(f, parse_dates=["tarih"]).set_index("tarih")["tufe"].astype(float).dropna()
        last = m.iloc[-1]
        base_m = m[m.index <= base.end_time]
        k = last / base_m.iloc[-1] if len(base_m) else 1.0
        infl = last / m.iloc[-13] - 1 if len(m) > 13 else np.nan
        return float(k), float(infl)
    except Exception:  # noqa: BLE001
        return 1.0, float(cpi_q.iloc[-1] / cpi_q.iloc[-5] - 1) if len(cpi_q) > 5 else np.nan


def value_one(t: str, a, price: float, mcap: float, beta: float, k_today: float, infl: float, sector_margin: float = np.nan,
              sector: str = "", erp: float = ERP) -> dict:
    out = {"fiyat": price, "deger": np.nan, "potansiyel": np.nan, "hedef_12a": np.nan, "yontem": "", "aosm_reel": np.nan,
           "buyume": np.nan, "marj": np.nan, "tv_payi": np.nan, "guven": "", "deger_not": ""}
    if not (price > 0 and mcap > 0):
        out["deger_not"] = "fiyat veya piyasa değeri yok"
        return out
    shares = mcap / price
    b = beta if pd.notna(beta) else 1.0
    coe_real = RF_REAL + b * erp
    from .report import NoDCF, inputs_from_analysis, is_financial
    if is_financial(a):
        out["yontem"] = "kalıntı gelir (PD/DD)"
        try:
            item = "net_income_parent" if "net_income_parent" in a.quarterly.index and a.quarterly.loc["net_income_parent"].notna().any() else "net_income"
            ni = a.ttm(item)
            eq = a.quarterly.loc["total_equity"].dropna().iloc[-1]
        except Exception as e:  # noqa: BLE001
            out["deger_not"] = f"veri yok ({e})"
            return out
        # Reel ve tutarlı: nominal ÖK kârlılığı son 12 ay enflasyonundan arındırılır; özkaynak maliyeti de reel (sanayi İNA ile aynı çerçeve)
        roe_nom = ni / eq if eq > 0 else np.nan
        if not (pd.notna(roe_nom) and eq > 0):
            out["deger_not"] = "özkaynak/kâr yok"
            return out
        pi = BEKLENEN_ENF if pd.notna(BEKLENEN_ENF) else (infl if pd.notna(infl) else UZUN_ENF)
        roe = (1 + roe_nom) / (1 + pi) - 1
        g = FIN_G_REAL
        pb = float(np.clip((roe - g) / (coe_real - g), 0.3, 4.0))
        out.update(deger=pb * eq / shares, aosm_reel=coe_real, buyume=g, marj=roe,
                   deger_not=f"reel ÖK kârlılığı %{roe*100:.0f} (nominal %{roe_nom*100:.0f}, beklenen enflasyon %{pi*100:.1f})")
    else:
        out["yontem"] = "reel FCFF İNA"
        try:
            inp = inputs_from_analysis(a)
        except (NoDCF, ValueError, KeyError) as e:
            # Hasılatı olmayan holding/yatırım şirketleri ya da son 12 ayı hesaplanamayanlar: defter değeri bazlı NAV
            try:
                q = a.quarterly
                eq = float(q.loc["total_equity"].dropna().iloc[-1])
                minority = 0.0
                try:
                    nit, nip = a.ttm("net_income"), a.ttm("net_income_parent")
                    if nit > 0 and 0 <= nip / nit <= 1:
                        minority = eq * (1 - nip / nit)
                except Exception:  # noqa: BLE001
                    pass
                disc = HOLDING_ISKONTO if "hasılat yok" in str(e) else 0.0
                out.update(deger=(eq - minority) * (1 - disc) * k_today / shares, yontem=f"defter değeri NAV (iskonto %{disc*100:.0f})",
                           deger_not=f"İNA uygulanamadı: {str(e)[:60]}", _zayif=True)
            except Exception:  # noqa: BLE001
                out["deger_not"] = str(e)[:80]
                return out
            v = out["deger"]
            out["potansiyel"] = v / price - 1
            out["hedef_12a"] = v * (1 + (infl if pd.notna(infl) else 0.0))
            out["guven"] = "düşük" if v > 0 else "negatif"
            out.pop("_zayif", None)
            return out
        m0 = float(np.clip(inp.margin0 if inp.margin0 is not None else inp.ebit_margin, 0.0, MARGIN_MAX))
        # hedef marj: şirket ile sektör medyanının ortası (ortalamaya dönüş); TMS 29 son 12 ay marjı tek başına kalıcı sayılmaz
        mt = float(np.clip(0.5 * m0 + 0.5 * sector_margin, 0.0, MARGIN_MAX)) if pd.notna(sector_margin) else m0
        g0 = float(np.clip(inp.growth_high, G_MIN, G_MAX))
        nd_pos = max(inp.net_debt, 0.0) if pd.notna(inp.net_debt) else 0.0
        wd = nd_pos / (nd_pos + mcap)
        w = float(np.clip((1 - wd) * coe_real + wd * KD_REAL * (1 - inp.tax_rate), WACC_MIN, WACC_MAX))
        minority = 0.0
        try:
            nit, nip = a.ttm("net_income"), a.ttm("net_income_parent")
            eq = a.quarterly.loc["total_equity"].dropna().iloc[-1]
            if nit > 0 and 0 <= nip / nit <= 1:
                minority = eq * (1 - nip / nit)
        except Exception:  # noqa: BLE001
            pass
        inp = replace(inp, growth_high=g0, margin0=m0, ebit_margin=mt, real_wacc=w, shares=shares, minority_and_other=minority)
        try:
            r = val.dcf(inp)
        except ValueError as e:
            out["deger_not"] = str(e)[:80]
            return out
        out.update(deger=r["per_share"] * k_today, aosm_reel=w, buyume=g0, marj=mt, tv_payi=r["tv_share"])
        weak = []
        if "holding" in (sector or "").lower() or "gayrimenkul" in (sector or "").lower():
            weak.append("holding/GYO: İNA yerine NAV uygun")
        if m0 < 0.03:
            weak.append("son 12 ay marjı %3'ün altında")
        if wd > 0.5:
            weak.append("borç ağırlığı yüksek (kiralama dahil olabilir)")
        if weak:
            out["_zayif"] = True
            out["deger_not"] = "; ".join(weak)
        if m0 <= 0:
            out["deger_not"] = "faaliyet marjı ≤ 0: değer yalnızca borç/nakitten"
    v = out["deger"]
    if pd.notna(v):
        out["potansiyel"] = v / price - 1
        out["hedef_12a"] = v * (1 + (infl if pd.notna(infl) else 0.0))
        p = out["potansiyel"]
        if v <= 0:
            out["guven"] = "negatif"
        elif out.pop("_zayif", False):
            out["guven"] = "düşük"
        elif p > UC_POTANSIYEL or p < -0.8 or (pd.notna(out["tv_payi"]) and out["tv_payi"] > 0.85):
            out["guven"] = "düşük"
        elif abs(p) > 1:
            out["guven"] = "orta"
        else:
            out["guven"] = "yüksek"
    out.pop("_zayif", None)
    return out


def build(root: Path, sc: pd.DataFrame, prices: dict[str, float]) -> pd.DataFrame:
    """Tarama tablosundaki her hisse için değer, potansiyel ve 12 aylık hedef."""
    root = Path(root)
    data = root / "data" / "gercek"
    cpi, fx = pipeline.load_macro_csv(data / "makro_ceyrek.csv")
    global BEKLENEN_ENF
    try:                                                      # canlı (EVDS/haber) → config → varsayılan
        from .oranlar import deger as _oran
        BEKLENEN_ENF = float(_oran(root, "enflasyon_beklentisi_12a")[0])
    except Exception:  # noqa: BLE001
        pass
    try:
        from .gundem import load as _gload
        erp = ERP + float(_gload(root).get("erp_ek", 0.0) or 0.0)
    except Exception:  # noqa: BLE001
        erp = ERP
    an, err = {}, {}
    for t in sc.index:
        try:
            an[t] = pipeline.analyze(t, pipeline.load_company(data / "kap", t), cpi, fx)
        except Exception as e:  # noqa: BLE001
            err[t] = f"hata: {str(e)[:60]}"
    margins = {}
    for t, a in an.items():
        try:
            margins[t] = a.ttm("operating_profit") / a.ttm("revenue")
        except Exception:  # noqa: BLE001
            pass
    sec = sc["sektor"] if "sektor" in sc else pd.Series("", index=sc.index)
    msec = pd.Series(margins).clip(-0.5, 0.6).groupby(sec.reindex(list(margins))).median()
    rows = {t: {"deger_not": m} for t, m in err.items()}
    for t, a in an.items():
        r = sc.loc[t]
        try:
            k, infl = _cpi_today_factor(root, a.last, cpi)
            mcap = _f(r.get("piyasa_degeri_mn_tl")) * 1e6
            rows[t] = value_one(t, a, _f(prices.get(t)), mcap, _f(r.get("beta")), k, infl, _f(msec.get(sec.get(t), np.nan)),
                               str(sec.get(t) or ""), erp)
        except Exception as e:  # noqa: BLE001
            rows[t] = {"deger_not": f"hata: {str(e)[:60]}"}
    return pd.DataFrame(rows).T


# ---------------------------------------------------------------- seviye geçmişi ve azaltma oranı

def azaltma_orani(seviye: str, bayraklar: str, potansiyel: float) -> float:
    """AZALT için kurala dayalı azaltma oranı: %25 taban, her ağır bayrak +%25, 2'yi aşan her hafif bayrak +%10,
    İNA potansiyeli < −%20 ise +%15; en fazla %75. SAT %100. Diğer seviyeler 0."""
    from .siniflar import AGIR
    if seviye == "SAT":
        return 1.0
    if seviye != "AZALT":
        return 0.0
    fl = (bayraklar or "").split()
    a = sum(f in AGIR for f in fl)
    h = len(fl) - a
    x = 0.25 + 0.25 * a + 0.10 * max(0, h - 2) + (0.15 if pd.notna(potansiyel) and potansiyel < -0.20 else 0.0)
    return float(min(x, 0.75))


def update_history(root: Path, sc: pd.DataFrame, stamp: str) -> pd.DataFrame:
    """data/gercek/seviye_gecmis.csv: her güncellemede (tarih saat) bir satır/hisse. Değişimleri döner."""
    f = Path(root) / "data" / "gercek" / "seviye_gecmis.csv"
    h = pd.read_csv(f, dtype=str) if f.exists() else pd.DataFrame(columns=["tarih", "kod", "seviye"])
    h = h[h["tarih"] != stamp]
    new = pd.DataFrame({"tarih": stamp, "kod": sc.index.astype(str), "seviye": sc["seviye"].astype(str).values,
                        "kural": sc["kural"].astype(str).values if "kural" in sc else "v1"})
    h = pd.concat([h, new], ignore_index=True).sort_values(["tarih", "kod"])
    h.to_csv(f, index=False)
    return changes(h)


def changes(h: pd.DataFrame, days: int = 30) -> pd.DataFrame:
    """Her hissenin ardışık iki kaydı arasındaki seviye değişimleri (son `days` güne ait kayıtlar)."""
    if h.empty:
        return pd.DataFrame(columns=["tarih", "kod", "onceki", "yeni"])
    h = h.sort_values(["kod", "tarih"]).copy()
    h["onceki"] = h.groupby("kod")["seviye"].shift()
    c = h[h["onceki"].notna() & (h["onceki"] != h["seviye"])].rename(columns={"seviye": "yeni"})
    days_ = sorted({str(x)[:10] for x in h["tarih"]})
    cutoff = days_[-days] if len(days_) >= days else days_[0]
    return c[c["tarih"].str[:10] >= cutoff][["tarih", "kod", "onceki", "yeni"]].sort_values(["tarih", "kod"], ascending=[False, True])


RANK = {"SAT": 0, "AZALT": 1, "VERİ YOK": 1.5, "TUT": 2, "AL": 3}


# ---------------------------------------------------------------- sayfa

def _p(v, d=1):
    v = _f(v)
    return "–" if pd.isna(v) else ("−" if v < 0 else "+" if v > 0 else "") + f"%{abs(v)*100:.{d}f}".replace(".", ",")


def _tl(v):
    v = _f(v)
    if pd.isna(v):
        return "–"
    return (f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}").replace(",", "X").replace(".", ",").replace("X", ".")


def changes_section(ch: pd.DataFrame) -> str:
    from .siniflar import badge
    e = html.escape
    head = "<h2 id='degisenler'>Seviye değişenler</h2>"
    if ch.empty:
        return (head + "<p class='muted'>Son 30 günde seviye değişimi yok. Her güncellemede tüm seviyeler kaydedilir; bir hissenin seviyesi "
                "değiştiği anda burada görünür.</p>")
    last = ch["tarih"].max()
    today = ch[ch["tarih"] == last]
    up = sum(RANK.get(r.yeni, 1) > RANK.get(r.onceki, 1) for r in today.itertuples())
    summary = (f"<p class='muted'>Son güncelleme ({e(last)}): {len(today)} hissenin seviyesi değişti; {up} yükseldi, {len(today) - up} düştü. "
               f"Son 30 günde toplam {len(ch)} değişim.</p>")
    rows = "".join(f"<tr><td class='l'>{e(str(r.tarih))}</td><td class='l'><a href='{e(r.kod)}.html'><b>{e(r.kod)}</b></a></td>"
                   f"<td class='l'>{badge(r.onceki)} → {badge(r.yeni)}</td>"
                   f"<td class='l'>{'▲ yükseldi' if RANK.get(r.yeni, 1) > RANK.get(r.onceki, 1) else '▼ düştü'}</td></tr>"
                   for r in ch.head(300).itertuples())
    return (head + summary + "<div class='wrap' style='max-height:480px;overflow:auto'><table><tr><th class='l'>Tarih</th><th class='l'>Kod</th>"
            f"<th class='l'>Değişim</th><th class='l'>Yön</th></tr>{rows}</table></div>")


def page(df: pd.DataFrame, stamp: str, infl: float) -> str:
    from .sectors import SORT_JS, sortable_table
    from .siniflar import badgify
    e = html.escape
    d = df.copy()
    for c in ("fiyat", "deger", "potansiyel", "hedef_12a", "aosm_reel", "buyume", "marj", "tv_payi", "azaltma"):
        if c in d:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    ok = d[d["deger"].notna() & (d["deger"] > 0)]
    med = ok["potansiyel"].median() if len(ok) else np.nan
    hi = ok[ok["guven"].isin(["yüksek", "orta"])].sort_values("potansiyel", ascending=False)
    cols = [("seviye", "Seviye", "t"), ("ad", "Şirket", "t"), ("fiyat", "Fiyat (TL)", "n"), ("deger", "İNA değeri (TL)", "n"),
            ("potansiyel", "Potansiyel", "p"), ("hedef_12a", "12 ay hedef (TL)", "n"), ("guven", "Güven", "t"),
            ("azaltma", "Azaltma oranı", "p"), ("yontem", "Yöntem", "t"), ("aosm_reel", "Reel AOSM / ÖK maliyeti", "p"),
            ("buyume", "Büyüme (ilk 5 yıl)", "p"), ("marj", "Faaliyet marjı / ÖK kârlılığı", "p"), ("tv_payi", "Uç değer payı", "p"),
            ("deger_not", "Not", "t")]
    d = d.sort_values("potansiyel", ascending=False, na_position="last")
    tbl = sortable_table(d, cols, "{}.html")
    top = "".join(f"<tr><td class='l'><a href='{e(t)}.html'><b>{e(t)}</b></a></td><td class='l'>{e(str(r.get('seviye','')))}</td>"
                  f"<td>{_tl(r['fiyat'])}</td><td>{_tl(r['deger'])}</td><td><b>{_p(r['potansiyel'])}</b></td></tr>"
                  for t, r in hi.head(10).iterrows())
    body = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Değerleme · KAPSAM (gizli)</title><style></style></head><body>
<div class="eyebrow">Gizli sürüm · Değerleme</div><h1>Her hisse, bir İNA değeri.</h1>
<p class="lead">{len(d)} hissenin {len(ok)} tanesinde pozitif model değeri var. Medyan potansiyel {_p(med)}. Her iş günü son kapanış fiyatıyla yeniden hesaplanır.</p>
<div class="warn">Değerler otomatik varsayımlarla üretilmiş model çıktısıdır, kişisel yatırım tavsiyesi değildir. Büyüme, marj ve iskonto oranı her şirket için
aynı kurallarla seçilir; şirkete özel bilgi (yeni yatırım, imtiyaz süresi, iştirakler, tek seferlik kalemler) içermez. "Güven: düşük" olan satırlarda
model şirketi iyi temsil etmiyor olabilir. 12 ay hedef = bugünkü değer × (1 + son 12 ay TÜFE {_p(infl)}), fiyatın değere 12 ayda yakınsadığı varsayımıyla.
{e(stamp[:16].replace('T', ' '))} UTC.</div>
<h2>En yüksek potansiyel (güveni orta/yüksek)</h2>
<table><tr><th class='l'>Kod</th><th class='l'>Seviye</th><th>Fiyat</th><th>İNA değeri</th><th>Potansiyel</th></tr>{top}</table>
<h2>Tüm hisseler</h2><input id="q" placeholder="Kod, şirket ya da seviye ara" oninput="f()">
{tbl}
<h3>Yöntem</h3>
<p class="m">Sanayi: reel serbest nakit akımı (FCFF) İNA, 10 yıl + sürekli dönem. Hasılat son 12 ay (TMS 29 düzeltmeli); büyüme son çeyreğin reel yıllık
büyümesi, %0–%15 aralığında, 5 yıl sonra %2'ye iner; marj son 12 ay esas faaliyet marjından 10 yılda şirket ve sektör medyanının ortasına yaklaşır;
reel AOSM = özkaynak maliyeti (%{RF_REAL*100:.0f} + beta × %{ERP*100:.0f}) ile vergi sonrası reel borç maliyeti (%{KD_REAL*100:.0f}) ağırlıklı ortalaması
(%{WACC_MIN*100:.0f}–%{WACC_MAX*100:.0f}); net borç ve azınlık payı düşülür; değer son aylık TÜFE ile bugünün TL'sine taşınır.
Banka ve sigorta: gerekçeli PD/DD = (ÖK kârlılığı − %{UZUN_ENF*100:.0f}) / (özkaynak maliyeti − %{UZUN_ENF*100:.0f}), 0,3–4 aralığı; %{UZUN_ENF*100:.0f} uzun vadeli enflasyon varsayımı.
Azaltma oranı (yalnızca AZALT/SAT): %25 taban, her ağır bayrak +%25, 2'yi aşan her hafif bayrak +%10, potansiyel −%20'nin altındaysa +%15, en fazla %75; SAT %100.</p>
{SORT_JS}</body></html>"""
    return badgify(body)
