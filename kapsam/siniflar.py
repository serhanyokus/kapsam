"""Kurala dayalı tarama sınıfları ve kalite bayrakları (yalnızca gizli sürümde, KAPSAM_GIZLI=1).

Bu bir mekanik eleme aracıdır, yatırım tavsiyesi değildir. Her sınıfın gerekçesi satırdaki bayraklarda yazar;
kurallar bu dosyada açıkça tanımlıdır ve eşikler SINIR sözlüğünden değiştirilebilir.

Bayraklar (A: ağır, H: hafif):
  ZARAR   (A) son 12 ay ana ortaklık net kârı ≤ 0
  PARASAL0(A) parasal kazanç olmasa yılbaşından beri zarar
  NAKIT-  (A) son 12 ay işletme nakit akışı ≤ 0
  BORC    (A) net borç / FAVÖK > 3 veya net borç / özkaynak > 1
  PARASAL (H) yılbaşından beri net kârın > %30'u parasal kazanç
  NAKIT   (H) işletme nakit akışı / net kâr < 0,5
  FDISI   (H) net kâr > 1,5 × esas faaliyet kârı (iştirak, finansman veya parasal kalemlere dayalı kâr)
  KUCULME (H) 9 aylık (yılbaşından beri) reel hasılat < −%15
  SERBEST (H) işletme nakit akışı − yatırım harcaması < 0
  PAHALI  (H) F/K sektör medyanının 1,5 katından fazla

Sınıflar (ilk uyan):
  Veri Eksik     F/K, işletme nakit akışı veya ≥ 4 rapor yok; ya da hesaplama hatası
  Uzak Dur       ZARAR veya PARASAL0, ya da ≥ 2 ağır bayrak
  Temkinli İzle  1 ağır bayrak veya ≥ 3 hafif bayrak
  Seçici İzle    1–2 hafif bayrak; ya da bayrak yok ama değerleme koşulu sağlanmıyor
  Kademeli Al    bayrak yok, F/K ≤ sektör medyanı, F/K ≤ 15 ve temel ÖK kârlılığı ≥ %15
Banka ve sigortalarda nakit ve borç bayrakları anlamsızdır; yalnızca ZARAR, PAHALI ve ÖK/çarpan koşulu kullanılır.
"""
from __future__ import annotations

import html

import numpy as np
import pandas as pd

from . import theme
from .sectors import SORT_JS, sortable_table

SINIFLAR = ["Kademeli Al", "Seçici İzle", "Temkinli İzle", "Uzak Dur", "Veri Eksik"]
# Sınıftan renkli seviyeye: AL yeşil, TUT gri, AZALT turuncu, SAT kırmızı, VERİ YOK açık gri
SEVIYE = {"Kademeli Al": ("AL", "al"), "Seçici İzle": ("TUT", "tut"), "Temkinli İzle": ("AZALT", "azalt"),
          "Uzak Dur": ("SAT", "sat"), "Veri Eksik": ("VERİ YOK", "yok")}
SEVIYE_ACIKLAMA = {"AL": "kalite bayrağı yok, F/K sektör medyanının ve 15'in altında, temel ÖK kârlılığı ≥ %15 ve İNA değeri fiyatın en az %15 "
                         "üstünde (güveni orta/yüksek)",
                   "TUT": "1–2 hafif bayrak; ya da kalite iyi ama çarpanlar veya İNA değeri alımı desteklemiyor",
                   "AZALT": "1 ağır ya da ≥ 3 hafif bayrak", "SAT": "son 12 ay zarar, parasal kazanç olmasa zarar ya da ≥ 2 ağır bayrak",
                   "VERİ YOK": "F/K, işletme nakit akışı ya da en az 4 rapor yok"}
BADGE_CSS = (".lvl{display:inline-block;min-width:52px;text-align:center;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700;"
             "letter-spacing:.02em;color:#fff;white-space:nowrap}.lvl.al{background:#248a3d}.lvl.tut{background:#8e8e93}"
             ".lvl.azalt{background:#ff9f0a}.lvl.sat{background:#d70015}.lvl.yok{background:#e5e5ea;color:#1d1d1f}"
             ".lvl.big{font-size:15px;padding:6px 16px;vertical-align:middle;margin-left:10px}")


def badge(level: str, big: bool = False) -> str:
    cls = {v[0]: v[1] for v in SEVIYE.values()}.get(level, "yok")
    return f"<span class='lvl {cls}{' big' if big else ''}'>{html.escape(level)}</span>"


def badgify(page_html: str) -> str:
    """Tablolardaki seviye hücrelerini renkli rozete çevirir."""
    for lv, _ in SEVIYE.values():
        e = html.escape(lv)
        page_html = page_html.replace(f"<td class='l'>{e}</td>", f"<td class='l'>{badge(lv)}</td>")
        page_html = page_html.replace(f"<td data-v='{e}' class='l'>{e}</td>", f"<td data-v='{e}' class='l'>{badge(lv)}</td>")
    return page_html
SINIR = {"parasal": 0.30, "nakit": 0.5, "fdisi": 1.5, "kuculme": -0.15, "borc_favok": 3.0, "borc_ok": 1.0,
         "pahali": 1.5, "fk_max": 15.0, "roe_min": 0.15}
ACIKLAMA = {"ZARAR": "son 12 ay zarar", "PARASAL0": "parasal kazanç olmasa zarar", "NAKIT-": "işletme nakit akışı negatif",
            "BORC": "borç yüksek", "PARASAL": "kârın büyük kısmı parasal kazanç", "NAKIT": "kâr nakde zayıf dönüşüyor",
            "FDISI": "kâr ağırlıkla faaliyet dışı", "KUCULME": "reel hasılat küçülüyor", "SERBEST": "yatırım harcaması nakit akışını aşıyor",
            "PAHALI": "F/K sektörüne göre yüksek", "INA-": "İNA değeri fiyatın %30'dan fazla altında",
            "INA0": "İNA değeri negatif (borç, işletme değerini aşıyor)", "HABER-": "son 14 günde olumsuz haber akışı"}
INA = {"al_min": 0.15, "pahali": -0.30}
AGIR = {"ZARAR", "PARASAL0", "NAKIT-", "BORC"}


def _f(v) -> float:
    try:
        v = float(v)
        return v if np.isfinite(v) else np.nan
    except (TypeError, ValueError):
        return np.nan


def flags(r: pd.Series, sektor_fk: float = np.nan) -> list[str]:
    g = lambda k: _f(r.get(k))  # noqa: E731
    sanayi = str(r.get("tur", "sanayi")) == "sanayi"
    out = []
    ni = g("net_kar_ana_ttm_mn")
    if pd.notna(ni) and ni <= 0:
        out.append("ZARAR")
    if sanayi:
        if str(r.get("parasal_kazanc_olmadan_zarar")).lower() == "true":
            out.append("PARASAL0")
        ocf = g("isletme_na_ttm_mn")
        if pd.notna(ocf) and ocf <= 0:
            out.append("NAKIT-")
        if g("net_borc_favok") > SINIR["borc_favok"] or (pd.notna(g("net_borc_mn")) and g("net_borc_mn") > 0 and
                                                            _f(r.get("_net_borc_ok")) > SINIR["borc_ok"]):
            out.append("BORC")
        if g("parasal_kazanc_net_kar_ytd") > SINIR["parasal"]:
            out.append("PARASAL")
        if pd.notna(ocf) and ocf > 0 and g("nakit_donusumu") < SINIR["nakit"]:
            out.append("NAKIT")
        if g("faaliyet_disi_pay") > SINIR["fdisi"]:
            out.append("FDISI")
        if g("reel_hasilat_9a") < SINIR["kuculme"]:
            out.append("KUCULME")
        if g("serbest_nakit_ttm_mn") < 0 and "NAKIT-" not in out:
            out.append("SERBEST")
    fk = g("fk_ttm")
    if pd.notna(fk) and pd.notna(sektor_fk) and fk > SINIR["pahali"] * sektor_fk:
        out.append("PAHALI")
    guv, pot = str(r.get("guven") or ""), g("potansiyel")
    if guv in ("yüksek", "orta") and pot < INA["pahali"]:
        out.append("INA-")
    if guv == "negatif":
        out.append("INA0")
    if str(r.get("haber_bayrak") or "") == "HABER-":
        out.append("HABER-")
    return out


def classify(r: pd.Series, fl: list[str], sektor_fk: float = np.nan) -> str:
    sanayi = str(r.get("tur", "sanayi")) == "sanayi"
    if str(r.get("not", "")).startswith("hata") or _f(r.get("rapor_sayisi")) < 4 or pd.isna(_f(r.get("fk_ttm"))) and "ZARAR" not in fl \
            or (sanayi and pd.isna(_f(r.get("isletme_na_ttm_mn")))):
        return "Veri Eksik"
    a = sum(f in AGIR for f in fl)
    h = len(fl) - a
    if "ZARAR" in fl or "PARASAL0" in fl or a >= 2:
        return "Uzak Dur"
    if a == 1 or h >= 3:
        return "Temkinli İzle"
    if h:
        return "Seçici İzle"
    fk, roe = _f(r.get("fk_ttm")), _f(r.get("ozkaynak_karliligi_yillik"))
    ucuz = fk <= SINIR["fk_max"] and (pd.isna(sektor_fk) or fk <= sektor_fk)
    ina_ok = str(r.get("guven") or "") in ("yüksek", "orta") and _f(r.get("potansiyel")) >= INA["al_min"]  # rejime göre %15/%25
    return "Kademeli Al" if ucuz and roe >= SINIR["roe_min"] and ina_ok else "Seçici İzle"


def _pct(v, sign=True) -> str:
    v = _f(v)
    if pd.isna(v):
        return "–"
    return (("+" if v > 0 else "−" if v < 0 else "") if sign else ("−" if v < 0 else "")) + f"%{abs(v)*100:.0f}"


def _tl(v) -> str:
    v = _f(v)
    return "–" if pd.isna(v) else f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerekce(r: pd.Series, fl: list[str], sinif: str, sektor_fk: float = np.nan) -> str:
    """Seviyenin açık gerekçesi: kalite, çarpan ve İNA koşullarından hangisi sağlandı, hangisi sağlanmadı."""
    lv = SEVIYE[sinif][0]
    fk, roe, pot, guv = _f(r.get("fk_ttm")), _f(r.get("ozkaynak_karliligi_yillik")), _f(r.get("potansiyel")), str(r.get("guven") or "")
    dv = _f(r.get("deger"))
    hab = str(r.get("haber_ozet") or "")
    hab = f" Gündem: {hab}." if hab and hab != "nan" else ""
    ina = (f"İNA değeri {_tl(dv)} TL, fiyat {_tl(r.get('fiyat'))} TL, potansiyel {_pct(pot)} (güven: {guv})"
           if pd.notna(dv) else f"İNA değeri hesaplanamadı ({r.get('deger_not') or 'veri yok'})")
    q = ("kalite bayrağı yok" if not [f for f in fl if f not in ("INA-", "INA0", "PAHALI", "HABER-")]
         else "kalite sorunları: " + ", ".join(ACIKLAMA[f] for f in fl if f not in ("INA-", "INA0", "PAHALI", "HABER-")))
    val_ = (f"F/K {fk:.1f}".replace(".", ",") + (f" (sektör medyanı {sektor_fk:.1f})".replace(".", ",") if pd.notna(sektor_fk) else "")
            if pd.notna(fk) else "F/K yok")
    roe_ = f"temel ÖK kârlılığı {_pct(roe, False)}"
    if lv == "VERİ YOK":
        return "Yeterli veri yok: F/K, işletme nakit akışı ya da en az 4 dönem rapor eksik. " + ina
    if lv == "AL":
        return f"Neden AL: {q}; {val_}, {roe_}; {ina}. Kalite, çarpan ve İNA koşullarının üçü birden sağlanıyor.{hab}"
    if lv == "TUT":
        why = []
        if any(f not in ("INA-", "INA0") for f in fl):
            why.append(", ".join(ACIKLAMA[f] for f in fl if f not in ("INA-", "INA0")))
        if "INA-" in fl:
            why.append("İNA değeri fiyatın belirgin altında")
        if not fl:
            if not (pd.notna(fk) and fk <= SINIR["fk_max"] and (pd.isna(sektor_fk) or fk <= sektor_fk)):
                why.append("F/K sektörüne veya 15'e göre yüksek")
            if not (roe >= SINIR["roe_min"]):
                why.append("temel ÖK kârlılığı %15'in altında")
            if not (guv in ("yüksek", "orta") and pot >= INA["al_min"]):
                why.append(f"İNA potansiyeli AL eşiğinin (%{INA['al_min']*100:.0f}) altında" if pd.notna(pot) and guv in ("yüksek", "orta")
                           else "İNA değeri güvenilir değil")
        return f"Neden TUT (AL değil): {'; '.join(why) or 'koşullar sınırda'}. {val_}, {roe_}; {ina}.{hab}"
    if lv == "AZALT":
        return f"Neden AZALT: {', '.join(ACIKLAMA[f] for f in fl)}. {val_}; {ina}.{hab}"
    return f"Neden SAT: {', '.join(ACIKLAMA[f] for f in fl)}. {ina}.{hab}"


def risk_note(r: pd.Series, fl: list[str], sinif: str) -> str:
    """Kademeli alım & risk notu: sınıfın gerekçesi ve piyasa riski. Kişisel pozisyon kararı kullanıcınındır."""
    g = lambda k: _f(r.get(k))  # noqa: E731
    parts = [", ".join(ACIKLAMA[f] for f in fl) if fl else "kalite bayrağı yok"]
    vol, dd, beta = g("oynaklik_yillik"), g("max_dusus"), g("beta")
    if pd.notna(vol):
        parts.append(f"oynaklık %{vol*100:.0f}" + (f", 1 yılda en büyük düşüş %{abs(dd)*100:.0f}" if pd.notna(dd) else "")
                     + (f", beta {beta:.2f}" if pd.notna(beta) else ""))
        if sinif == "Kademeli Al":
            parts.append("tek seferde değil parçalı giriş, yüksek oynaklıkta daha küçük parçalar" if vol > 0.45 else "parçalı giriş")
    return "; ".join(parts)


def build(sc: pd.DataFrame, al_esik: float = 0.15) -> pd.DataFrame:
    """Tarama tablosuna sinif, bayraklar ve risk_notu sütunlarını ekler. al_esik: AL için gereken İNA potansiyeli (gündem rejimi)."""
    INA["al_min"] = al_esik
    df = sc.copy()
    for c in ("ad", "sektor"):
        if c not in df:
            df[c] = ""
    for c in df.columns:
        if c not in ("ad", "sektor", "tur", "son_ceyrek", "not", "parasal_kazanc_olmadan_zarar", "tms29", "guven", "yontem", "deger_not", "haber_bayrak", "haber_ozet"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["_net_borc_ok"] = df.get("net_borc_mn", np.nan) / (df["piyasa_degeri_mn_tl"] / df["pd_dd"]) if "pd_dd" in df else np.nan
    med = df.groupby("sektor")["fk_ttm"].median() if "sektor" in df else pd.Series(dtype=float)
    S, B, N, G = {}, {}, {}, {}
    for t, r in df.iterrows():
        sfk = _f(med.get(r.get("sektor"), np.nan))
        fl = flags(r, sfk)
        s = classify(r, fl, sfk)
        S[t], B[t], N[t] = s, " ".join(fl), risk_note(r, fl, s)
        G[t] = gerekce(r, fl, s, sfk)
    out = sc.copy()
    out["sinif"], out["bayraklar"], out["risk_notu"] = pd.Series(S), pd.Series(B), pd.Series(N)
    out["seviye"] = out["sinif"].map(lambda x: SEVIYE.get(x, ("VERİ YOK", ""))[0])
    out["gerekce"] = pd.Series(G)
    out["sektor_fk_medyan"] = df["sektor"].map(med) if "sektor" in df else np.nan
    return out


COLS = [("seviye", "Seviye", "t"), ("ad", "Şirket", "t"), ("gerekce", "Gerekçe (her iş günü yeniden yazılır)", "t"),
        ("fiyat", "Fiyat (TL)", "n"), ("deger", "İNA değeri (TL)", "n"), ("potansiyel", "Potansiyel", "p"), ("hedef_12a", "12 ay hedef (TL)", "n"),
        ("guven", "İNA güveni", "t"), ("azaltma", "Azaltma oranı", "p"), ("bayraklar", "Bayraklar", "t"), ("sektor", "Sektör", "t"),
        ("fk_ttm", "F/K", "x"), ("pd_dd", "PD/DD", "x"), ("ozkaynak_karliligi_yillik", "Temel ÖK kârlılığı", "p"),
        ("parasal_kazanc_net_kar_ytd", "Parasal / net kâr", "p"), ("nakit_donusumu", "İşl. NA / net kâr", "n"),
        ("net_borc_favok", "Net borç / FAVÖK", "n"), ("reel_hasilat_9a", "Reel hasılat 9A", "p"),
        ("aosm_reel", "Reel AOSM", "p"), ("buyume", "İNA büyüme", "p"), ("marj", "İNA hedef marj", "p"),
        ("oynaklik_yillik", "Oynaklık", "p"), ("risk_notu", "Risk notu", "t"), ("deger_not", "İNA notu", "t")]


MP = {"hisse_tavan": 0.15, "sektor_tavan": 0.30}


def model_portfolio(df: pd.DataFrame) -> pd.DataFrame:
    """Kurala dayalı model portföy: yalnızca AL seviyesindeki hisseler, ters oynaklık ağırlığı (düşük oynaklık → yüksek ağırlık),
    hisse başına en fazla %15, sektör başına en fazla %30. Oynaklık yoksa medyan oynaklık kullanılır.
    Kişiye özel değildir; kullanıcının birikimini, vadesini ve risk toleransını bilmez."""
    g = df[df["seviye"] == "AL"].copy() if "seviye" in df else df.iloc[0:0].copy()
    if g.empty:
        return pd.DataFrame(columns=["ad", "sektor", "agirlik", "oynaklik_yillik"])
    vol = pd.to_numeric(g["oynaklik_yillik"], errors="coerce") if "oynaklik_yillik" in g else pd.Series(np.nan, index=g.index)
    vol = vol.fillna(vol.median() if vol.notna().any() else 0.4).clip(lower=0.10)
    w = (1 / vol) / (1 / vol).sum()
    sec = g["sektor"].fillna("Diğer")
    nsec = sec.nunique()
    scap = max(MP["sektor_tavan"], 1.0 / nsec)              # az sektör varsa tavan yükselir (uygulanabilirlik)
    hcap = max(MP["hisse_tavan"], 1.0 / len(g))
    for _ in range(200):
        changed = False
        over = w > hcap + 1e-12
        if over.any():
            ex = (w[over] - hcap).sum(); w[over] = hcap
            free = ~over & (w < hcap - 1e-12)
            if free.any():
                w[free] += ex * w[free] / w[free].sum()
            changed = True
        ss = w.groupby(sec).sum()
        big = ss[ss > scap + 1e-12]
        for k, v in big.items():
            m = sec == k
            w[m] *= scap / v
            ex = v - scap
            free = ~sec.isin(ss[ss >= scap - 1e-12].index)
            if free.any():
                w[free] += ex * w[free] / w[free].sum()
            changed = True
        w = w / w.sum()
        if not changed:
            break
    out = g.reindex(columns=["ad", "sektor"]).copy()
    out["agirlik"], out["oynaklik_yillik"] = w, vol
    return out.sort_values("agirlik", ascending=False)


def portfolio_section(mp: pd.DataFrame) -> str:
    e = html.escape
    if mp.empty:
        return "<h2 id='model-portfoy'>Model portföy</h2><p class='muted'>Bugün AL seviyesinde hisse yok; model portföy nakitte.</p>"
    rows = "".join(f"<tr><td class='l'><a href='{e(t)}.html'><b>{e(t)}</b></a></td><td class='l'>{badge('AL')}</td><td class='l'>{e(str(r['ad']))}</td>"
                   f"<td class='l'>{e(str(r['sektor']))}</td><td><b>%{r['agirlik']*100:.1f}</b></td><td>%{r['oynaklik_yillik']*100:.0f}</td></tr>"
                   for t, r in mp.iterrows())
    sec = mp.groupby("sektor")["agirlik"].sum().sort_values(ascending=False)
    srows = "".join(f"<tr><td class='l'>{e(str(k))}</td><td>%{v*100:.1f}</td></tr>" for k, v in sec.items())
    return f"""<h2 id='model-portfoy'>Model portföy</h2>
<p class='muted'>Kurala dayalı: yalnızca {badge('AL')} hisseler, ters oynaklık ağırlığı (oynaklığı düşük olana daha fazla), hisse başına en fazla
%{MP['hisse_tavan']*100:.0f}, sektör başına en fazla %{MP['sektor_tavan']*100:.0f}. Her güncellemede yeniden hesaplanır. Kişiye özel değildir;
birikim, vade ve risk toleransını bilmez. Yatırım tavsiyesi değildir.</p>
<div class='grid2'><div><table><tr><th class='l'>Kod</th><th class='l'>Seviye</th><th class='l'>Şirket</th><th class='l'>Sektör</th><th>Ağırlık</th><th>Oynaklık</th></tr>{rows}</table></div>
<div><table><tr><th class='l'>Sektör</th><th>Toplam ağırlık</th></tr>{srows}</table></div></div>"""


def yorum(df: pd.DataFrame, g: dict, ch: pd.DataFrame | None, infl: float = np.nan) -> str:
    """Günün yorumu: gündem, rejim, iskonto oranı, seviye değişimleri ve AL listesini tek metinde bağlar (kurallardan üretilir)."""
    from . import gundem as gd
    e = html.escape
    ind = (g or {}).get("gostergeler", {}) or {}

    def iv(sym, k):
        try:
            return float(ind[sym][k])
        except Exception:  # noqa: BLE001
            return np.nan
    rg = gd.regime(g or {})
    erp = gd.ERP_BASE + float((g or {}).get("erp_ek", 0) or 0)
    p1 = []
    _bist = f"{iv('XU100.IS', 'son'):,.0f}".replace(",", ".") if pd.notna(iv("XU100.IS", "son")) else "–"
    if pd.notna(iv("XU100.IS", "son")):
        p1.append(f"BIST 100 {_bist} puanda; "
                  f"günlük {_pct(iv('XU100.IS', 'gun'))}, aylık {_pct(iv('XU100.IS', 'ay'))}.")
    if pd.notna(iv("USDTRY=X", "son")):
        p1.append(f"Dolar/TL {iv('USDTRY=X', 'son'):.2f}".replace(".", ",") + f" (1 ay {_pct(iv('USDTRY=X', 'ay'))}); yıllık TÜFE {_pct(infl)}.")
    if pd.notna(iv("^VIX", "son")):
        p1.append(f"Küresel tarafta VIX {iv('^VIX', 'son'):.1f}".replace(".", ",") + f", S&P 500 aylık {_pct(iv('^GSPC', 'ay'))}, Brent aylık {_pct(iv('BZ=F', 'ay'))}, "
                  f"ABD 10 yıllık faiz %{iv('^TNX', 'son'):.2f}".replace(".", ",") + ".")
    rej = ("<b>Rejim: riskten kaçış</b> (" + ", ".join(rg["neden"]) + "). Bu yüzden AL için gereken İNA potansiyeli %25'e yükseltildi."
           if rg["riskten_kacis"] else "<b>Rejim: olağan.</b> AL için gereken İNA potansiyeli %15.")
    p2 = (f"{rej} İNA iskonto oranındaki hisse risk primi %{erp*100:.0f} "
          f"({'; '.join((g or {}).get('erp_neden', [])) or 'ek yok'}).")
    cnt = df["seviye"].value_counts()
    al = df[df["seviye"] == "AL"].copy()
    al["_p"] = pd.to_numeric(al.get("potansiyel"), errors="coerce")
    al = al.sort_values("_p", ascending=False)
    al_txt = ", ".join(f"<a href='{e(t)}.html'><b>{e(t)}</b></a> ({_pct(r['_p'])})" for t, r in al.iterrows()) or "yok"
    p3 = (f"Bugün {int(cnt.get('AL', 0))} hisse AL, {int(cnt.get('TUT', 0))} TUT, {int(cnt.get('AZALT', 0))} AZALT, {int(cnt.get('SAT', 0))} SAT. "
          f"AL listesi (İNA potansiyeline göre): {al_txt}.")
    p4 = ""
    if ch is not None and len(ch):
        last = ch["tarih"].max()
        today = ch[ch["tarih"] == last]
        from .deger import RANK
        up = [r.kod for r in today.itertuples() if RANK.get(r.yeni, 1) > RANK.get(r.onceki, 1)]
        dn = [r.kod for r in today.itertuples() if RANK.get(r.yeni, 1) < RANK.get(r.onceki, 1)]
        p4 = (f"Son güncellemede {len(today)} seviye değişti: yükselen {', '.join(up[:12]) or '–'}; düşen {', '.join(dn[:12]) or '–'}"
              + (" …" if len(up) > 12 or len(dn) > 12 else "") + ".")
    neg = [t for t, d in (g or {}).get("sirket", {}).items() if d.get("bayrak") == "HABER-"]
    p5 = (f"Olumsuz haber akışı nedeniyle {len(neg)} hissede HABER- bayrağı var ({', '.join(neg[:10])}); bu bayrak bir hisseyi AL'dan çıkarır."
          if neg else "Olumsuz haber akışı bayrağı taşıyan hisse yok.")
    tr = (g or {}).get("makro_tr", [])[:3]
    gl = (g or {}).get("makro_global", [])[:3]
    heads = "".join(f"<li>{e(x.get('baslik',''))} <span class='muted'>({e(x.get('kaynak') or '')})</span></li>" for x in tr + gl)
    return (f"<h2 id='yorum'>Günün yorumu</h2><div class='card'><p>{' '.join(p1)}</p><p>{p2}</p><p>{p3}</p>"
            f"{'<p>' + p4 + '</p>' if p4 else ''}<p>{p5}</p>"
            + (f"<p class='muted' style='margin-bottom:4px'>Öne çıkan başlıklar:</p><ul class='muted'>{heads}</ul>" if heads else "")
            + "<p class='m'>Bu yorum, göstergeler ve kurallardan her iş günü otomatik yazılır; kişisel yatırım tavsiyesi değildir.</p></div>")


def page(df: pd.DataFrame, stamp: str, changes_html: str = "", infl: float = np.nan, g: dict | None = None,
         ch: pd.DataFrame | None = None) -> str:
    """Birleşik Seviyeler + Değerleme + Gündem sayfası."""
    from . import gundem as _gd
    gdict = g or {}
    e = html.escape
    counts = df["sinif"].value_counts()
    tiles = "".join(f"<div class='kpi'><span>{badge(SEVIYE[s][0])}</span><b>{int(counts.get(s, 0))}</b>"
                    f"<span><a href='#{theme.slug(SEVIYE[s][0])}'>listeyi aç</a></span></div>" for s in SINIFLAR[:4])
    d = df.copy()
    pot = pd.to_numeric(d.get("potansiyel"), errors="coerce") if "potansiyel" in d else pd.Series(np.nan, index=d.index)
    d["_pot"] = pot
    secs = []
    for s in SINIFLAR:
        lv = SEVIYE[s][0]
        g = d[d["sinif"] == s].sort_values("_pot", ascending=(lv in ("AZALT", "SAT")), na_position="last")
        tbl = sortable_table(g, COLS, "{}.html").replace("id='t'", f"id='t{theme.slug(lv)}'")
        secs.append(f"<h2 id='{theme.slug(lv)}'>{badge(lv, True)} <span class='muted'>{len(g)} şirket · {e(SEVIYE_ACIKLAMA[lv])}</span></h2>{tbl}")
    ok = d[d.get("guven", pd.Series("", index=d.index)).isin(["yüksek", "orta"])] if "guven" in d else d.iloc[0:0]
    med = ok["_pot"].median() if len(ok) else np.nan
    top = "".join(f"<tr><td class='l'><a href='{e(t)}.html'><b>{e(t)}</b></a></td><td class='l'>{badge(str(r['seviye']))}</td>"
                  f"<td>{_tl(r.get('fiyat'))}</td><td>{_tl(r.get('deger'))}</td><td><b>{_pct(r['_pot'])}</b></td>"
                  f"<td class='l'>{e(str(r.get('gerekce') or ''))[:220]}</td></tr>" for t, r in ok.sort_values("_pot", ascending=False).head(10).iterrows())
    rules = "".join(f"<tr><td class='l'><b>{k}</b></td><td class='l'>{'ağır' if k in AGIR else 'hafif'}</td><td class='l'>{e(v)}</td></tr>"
                    for k, v in ACIKLAMA.items())
    levels = "".join(f"<tr><td class='l'>{badge(k)}</td><td class='l'>{e(v)}</td></tr>" for k, v in SEVIYE_ACIKLAMA.items())
    sort_js = SORT_JS.replace("#t th", "table[id^=t] th").replace("document.querySelector('#t tbody')", "th.closest('table').tBodies[0]")
    sort_js = sort_js.replace("document.querySelectorAll('#t tbody tr')", "document.querySelectorAll('table[id^=t] tbody tr')")
    from . import deger as _dg
    body = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Seviyeler, değerleme ve gündem · KAPSAM (gizli)</title><style></style></head><body>
<div class="eyebrow">Gizli sürüm · Seviyeler, değerleme ve gündem · her iş günü yeniden hesaplanır</div><h1>AL, TUT, AZALT, SAT.</h1>
<p class="lead">{len(df)} şirket; kâr kalitesi, nakit, borç, çarpanlar ve İNA değerine göre. Her satırda seviyenin gerekçesi, İNA değeri, potansiyel ve
12 aylık hedef var. Güveni orta/yüksek İNA'larda medyan potansiyel {_pct(med)}.</p>
<div class="warn">Seviyeler ve değerler mekanik bir kural setinin çıktısıdır; kişisel yatırım tavsiyesi değildir. AL için kalite, çarpan, İNA ve gündem koşullarının
hepsi birden sağlanmalıdır: İNA değeri fiyatın altında kalan bir hisse AL olamaz. İNA varsayımları her şirkete aynı kurallarla uygulanır ve şirkete özel bilgi
içermez. 12 ay hedef = İNA değeri × (1 + son 12 ay TÜFE {_pct(infl)}). {e(stamp[:16].replace('T', ' '))} UTC.</div>
<div class="kpis">{tiles}</div>
<p class="muted">{badge('VERİ YOK')} {int(counts.get('Veri Eksik', 0))} şirket · <a href='#degisenler'>Seviye değişenler</a> ·
<a href='#yorum'>Günün yorumu</a> · <a href='#gundem'>Gündem</a> · <a href='#model-portfoy'>Model portföy</a> ·
<a href='#potansiyel'>En yüksek potansiyel</a> · <a href='#veri-yok'>Veri yok listesi</a></p>
<input id="q" placeholder="Kod, şirket ya da seviye ara (tüm tablolarda)" oninput="f()">
{yorum(df, gdict, ch, infl)}
{changes_html}
{_gd.section(gdict) if gdict else ""}
{portfolio_section(model_portfolio(df))}
<h2 id='potansiyel'>En yüksek İNA potansiyeli <span class='muted'>(güveni orta/yüksek)</span></h2>
<p class='muted'>Potansiyeli yüksek ama AL olmayan hisselerin gerekçesi satırda yazar (çoğunlukla kalite bayrağı ya da çarpan koşulu).</p>
<table><tr><th class='l'>Kod</th><th class='l'>Seviye</th><th>Fiyat</th><th>İNA değeri</th><th>Potansiyel</th><th class='l'>Gerekçe</th></tr>{top}</table>
{''.join(secs)}
<h2>Kurallar</h2><table><tr><th class='l'>Seviye</th><th class='l'>Kural</th></tr>{levels}</table>
<h3>Bayraklar</h3><table><tr><th class='l'>Bayrak</th><th class='l'>Ağırlık</th><th class='l'>Anlamı</th></tr>{rules}</table>
<p class="m">İNA: sanayide reel FCFF (10 yıl + sürekli dönem; büyüme son çeyreğin reel yıllık büyümesi, %0–%15, 5 yılda %2'ye iner; marj son 12 ay esas
faaliyet marjından şirket ve sektör medyanının ortasına yaklaşır; reel AOSM özkaynak maliyeti %{_dg.RF_REAL*100:.0f} + beta × %{_dg.ERP*100:.0f} ile vergi
sonrası reel borç maliyetinin ağırlıklı ortalaması, %{_dg.WACC_MIN*100:.0f}–%{_dg.WACC_MAX*100:.0f}). Banka ve sigortada gerekçeli PD/DD.
İNA güveni: holding/GYO, marjı %3'ün altında, borç ağırlığı yüksek ya da uç değer payı %85'in üstünde olanlarda "düşük".
Azaltma oranı (AZALT): %25 taban, her ağır bayrak +%25, 2'yi aşan her hafif bayrak +%10, potansiyel −%20'nin altındaysa +%15, en fazla %75; SAT %100.
İşletme nakit akışı − yatırım harcaması serbest nakit akışı (FCFF) değildir.</p>
{sort_js}</body></html>"""
    return badgify(body)


def badge_pages(out_root, df: pd.DataFrame) -> int:
    """Şirket notlarının başlığına renkli seviye rozeti ekler (yalnızca gizli sürüm)."""
    import re
    from pathlib import Path
    n = 0
    for t, r in df.iterrows():
        f = Path(out_root) / f"{t}.html"
        lv = r.get("seviye")
        if not f.exists() or not isinstance(lv, str):
            continue
        txt = f.read_text(encoding="utf-8")
        if "class='lvl" in txt:
            continue
        note = html.escape(str(r.get("risk_notu") or ""))
        dv, pt, az = _f(r.get("deger")), _f(r.get("potansiyel")), _f(r.get("azaltma"))
        if pd.notna(dv) and dv > 0:
            note += f" · İNA değeri {dv:,.2f} TL (potansiyel {pt*100:+.0f}%, güven: {html.escape(str(r.get('guven') or '–'))})".replace(",", "X").replace(".", ",").replace("X", ".")
        if pd.notna(az) and az > 0:
            note += f" · azaltma oranı %{az*100:.0f}"
        new, k = re.subn(r"(<h1[^>]*>.*?)(</h1>)", lambda m: m.group(1) + badge(lv, True) + m.group(2), txt, count=1, flags=re.S)
        if k:
            new = new.replace("</h1>", f"</h1><p class='muted'>Seviye gerekçesi: {note} · <a href='siniflar.html'>kurallar</a></p>", 1)
            f.write_text(new, encoding="utf-8")
            n += 1
    return n


KALITE_COLS = [("ad", "Şirket", "t"), ("sektor", "Sektör", "t"), ("bayraklar", "Bayraklar", "t"), ("kalite_aciklama", "Açıklama", "t"),
               ("parasal_kazanc_net_kar_ytd", "Parasal / net kâr", "p"), ("nakit_donusumu", "İşl. NA / net kâr", "n"),
               ("faaliyet_disi_pay", "Net kâr / esas faal.", "n"), ("net_borc_favok", "Net borç / FAVÖK", "n"),
               ("reel_hasilat_9a", "Reel hasılat 9A", "p"), ("serbest_nakit_ttm_mn", "İşl. NA − capex (mn)", "i"),
               ("fk_ttm", "F/K", "x"), ("pd_dd", "PD/DD", "x"), ("haber_ozet", "Haber akışı", "t")]


def kalite_page(df: pd.DataFrame, stamp: str) -> str:
    """Herkese açık sürüm: nötr kalite bayrakları. Seviye, öneri, hedef fiyat ya da portföy içermez."""
    e = html.escape
    d = df.copy()
    for c in ("ad", "sektor", "bayraklar"):
        if c not in d:
            d[c] = ""
    d["kalite_aciklama"] = d["bayraklar"].fillna("").map(
        lambda b: "; ".join(ACIKLAMA.get(f, f) for f in b.split() if f not in ("INA-", "INA0")) or "bayrak yok")
    d["_n"] = d["bayraklar"].fillna("").str.split().map(len)
    d = d.sort_values(["_n", "ad"])
    from collections import Counter
    cnt = Counter(f for b in d["bayraklar"].fillna("") for f in b.split() if f not in ("INA-", "INA0"))
    tiles = "".join(f"<div class='kpi'><span>{e(ACIKLAMA.get(k, k))}</span><b>{v}</b><span>{'ağır' if k in AGIR else 'hafif'} bayrak</span></div>"
                    for k, v in cnt.most_common(4))
    rules = "".join(f"<tr><td class='l'><b>{k}</b></td><td class='l'>{'ağır' if k in AGIR else 'hafif'}</td><td class='l'>{e(v)}</td></tr>"
                    for k, v in ACIKLAMA.items() if k not in ("INA-", "INA0"))
    tbl = sortable_table(d, KALITE_COLS, "{}.html")
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kalite bayrakları · KAPSAM</title><style></style></head><body>
<div class="eyebrow">Kalite</div><h1>Kâr kalitesi, tek bakışta.</h1>
<p class="lead">{len(d)} şirketin kâr kalitesi, nakit üretimi, borç ve büyüme göstergeleri; açık kurallarla işaretlenmiş bayraklar. Her iş günü yenilenir.</p>
<div class="warn">Bayraklar yalnızca finansal tablolardaki örüntüleri gösterir; al/sat önerisi, hedef fiyat ya da seviye içermez. Yatırım tavsiyesi değildir.
{e(stamp[:16].replace('T', ' '))} UTC.</div>
<div class="kpis">{tiles}</div>
<input id="q" placeholder="Kod, şirket, sektör ya da bayrak ara" oninput="f()">
{tbl}
<h2>Kurallar</h2><table><tr><th class='l'>Bayrak</th><th class='l'>Ağırlık</th><th class='l'>Anlamı</th></tr>{rules}</table>
<p class="m">Akış ve kâr rakamları son 12 ay, TMS 29 düzeltmeli. İşletme nakit akışı − yatırım harcaması serbest nakit akışı (FCFF) değildir.
Haber akışı: son 14 günün başlıkları, kelime tabanlı otomatik ton; hatalı olabilir.</p>
{SORT_JS}</body></html>"""
