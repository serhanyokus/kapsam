"""Eksik tablolar için yedek kaynak: İş Yatırım mali tablo servisi (KAP'a bildirilen konsolide tablolar).

Birincil kaynak (ekofin) bazı şirketlerde kalemleri eksik getirir (ör. özkaynak, nakit akışı). Bu modül yalnızca eksik
şirketler için çalışır, son 8 çeyreğin kümülatif tablolarını indirir ve KAP biçimindeki CSV'lere (data/gercek/kap) yazar.
Kibar kullanım: istekler arasında bekleme, günlük üst sınır.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

URL = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo"
GROUPS = ["XI_29", "UFRS", "UFRS_K"]          # sanayi (TMS/TFRS), banka/finans biçimleri

# İş Yatırım kalem kodu → KAP etiketi (statements.ACCOUNT_SYNONYMS içinde tanınan ilk etiket)
ITEMS = {
    "3C": "Hasılat", "3CA": "Satışların Maliyeti (-)", "3D": "Brüt Kar (Zarar)", "3DF": "Esas Faaliyet Karı (Zararı)",
    "3I": "Sürdürülen Faaliyetler Vergi Öncesi Karı (Zararı)", "3L": "Dönem Karı (Zararı)", "3Z": "Ana Ortaklık Payları",
    "4B": "Amortisman ve İtfa Gideri İle İlgili Düzeltmeler", "4C": "İşletme Faaliyetlerinden Nakit Akışları",
    "4CAI": "Maddi ve Maddi Olmayan Duran Varlıkların Alımından Kaynaklanan Nakit Çıkışları",
    "1AA": "Nakit ve Nakit Benzerleri", "1BL": "Toplam Varlıklar", "2ODB": "Toplam Kaynaklar", "2N": "Toplam Özkaynaklar",
    "2AA": "Kısa Vadeli Borçlanmalar", "2BA": "Uzun Vadeli Borçlanmalar",
}
# Banka ve sigorta (UFRS biçimi): ortak kodlar
ITEMS_FIN = {"1Z": "Toplam Varlıklar", "2O": "Toplam Özkaynaklar", "3Z": "Dönem Karı (Zararı)", "1A": "Nakit ve Nakit Benzerleri",
             "3AAR": "Net Faiz Geliri", "1ABG": "Krediler (Net)"}
FIN_LABELS = ["Faiz Gelirleri", "Net Faiz Geliri", "Brüt Yazılan Primler", "Net Yazılan Primler", "Krediler (Net)", "Mevduat",
              "Teknik Bölüm Dengesi - Hayat Dışı"]
# Vergi öncesi kârı oluşturan kalemler; farkı parasal pozisyon kazancıdır (İş Yatırım ayrı satır vermez)
PRETAX_PARTS = ["3DF", "3HA", "3HAA", "3HAB", "3HAC", "3HB", "3HC"]
KEY_ITEMS = ["revenue", "operating_cash_flow", "total_equity", "net_income"]


def periods(last: pd.Period, n: int = 8) -> list[pd.Period]:
    return [last - i for i in range(n)]


def parse(value: list[dict], pers: list[pd.Period], fin: bool = False) -> dict[pd.Period, dict[str, float]]:
    """Servis yanıtını {dönem: {KAP etiketi: değer}} biçimine çevirir. fin: banka/sigorta (UFRS) kod tablosu."""
    by = {str(r.get("itemCode")): r for r in value}
    out = {}
    for i, per in enumerate(pers, start=1):
        k = f"value{i}"
        vals = {}
        for code, label in (ITEMS_FIN if fin else ITEMS).items():
            v = by.get(code, {}).get(k)
            if v not in (None, ""):
                vals[label] = float(v)
        if not vals or all(x == 0 for x in vals.values()):
            continue
        parts = [by.get(c, {}).get(k) for c in PRETAX_PARTS]
        pre = by.get("3I", {}).get(k)
        if not fin and pre not in (None, "") and all(x not in (None, "") for x in parts[:1]):
            gap = float(pre) - sum(float(x) for x in parts if x not in (None, ""))
            if abs(gap) > 1e-6 * max(1.0, abs(float(pre))) and abs(gap) > 1000:
                vals["Net Parasal Pozisyon Kazançları (Kayıpları)"] = gap
        out[per] = vals
    return out


def fetch(ticker: str, last: pd.Period, session=None, pause: float = 1.0, fin: bool = False) -> dict[pd.Period, dict[str, float]]:
    import requests
    s = session or requests.Session()
    pers = periods(last, 8)
    for g in (["UFRS", "UFRS_K"] if fin else GROUPS):
        got = {}
        for chunk in (pers[:4], pers[4:]):
            q = {"companyCode": ticker, "exchange": "TRY", "financialGroup": g}
            for i, per in enumerate(chunk, start=1):
                q[f"year{i}"], q[f"period{i}"] = per.year, per.quarter * 3
            r = s.get(URL, params=q, headers={"User-Agent": "Mozilla/5.0 (KAPSAM arastirma)"}, timeout=30)
            r.raise_for_status()
            j = r.json()
            if j.get("ok") and j.get("value"):
                got.update(parse(j["value"], chunk, fin or g != "XI_29"))
            time.sleep(pause)
        if got:
            return got
    return {}


def write(ticker: str, data: dict[pd.Period, dict[str, float]], folder: Path) -> list[Path]:
    """Her dönem için KAP biçiminde CSV (Kalem,YYYY/M). Mevcut dosyadaki kalemler korunur, eksikler eklenir."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for per, vals in data.items():
        f = folder / f"{ticker}_{per.year}_{per.quarter * 3}.csv"
        col = f"{per.year}/{per.quarter * 3}"
        old = {}
        if f.exists():
            try:
                d = pd.read_csv(f, dtype=str)
                old = dict(zip(d.iloc[:, 0], d.iloc[:, 1]))
            except Exception:  # noqa: BLE001
                old = {}
        merged = dict(old)
        for k, v in vals.items():
            if k not in merged or merged[k] in (None, "", "nan"):
                merged[k] = v
        if merged != old:
            pd.DataFrame({"Kalem": list(merged), col: list(merged.values())}).to_csv(f, index=False)
            written.append(f)
    return written


def is_financial(folder: Path, ticker: str) -> bool:
    from ..textutil import norm
    fl = {norm(x) for x in FIN_LABELS}
    for f in sorted(folder.glob(f"{ticker}_*.csv"))[-3:]:
        try:
            if fl & {norm(x) for x in pd.read_csv(f, dtype=str).iloc[:, 0]}:
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def incomplete(folder: Path, tickers: list[str], depth: int = 5) -> list[str]:
    """Son `depth` raporundan birinde temel kalemi eksik ya da 4'ten az raporu olan hisseler.
    Sanayi: hasılat, işletme nakit akışı, özkaynak, net kâr. Banka/sigorta: özkaynak, net kâr."""
    from .statements import ACCOUNT_SYNONYMS
    from ..textutil import norm
    labels = {k: {norm(x) for x in ACCOUNT_SYNONYMS[k]} for k in KEY_ITEMS}
    out = []
    for t in tickers:
        fs = sorted(folder.glob(f"{t}_*.csv"), key=lambda p: (int(p.stem.split("_")[-2]), int(p.stem.split("_")[-1])))
        if len(fs) < 4:
            out.append(t)
            continue
        fin = is_financial(folder, t)
        keys = ["total_equity", "net_income"] if fin else KEY_ITEMS
        bad = False
        for f in fs[-(1 if fin else depth):]:          # banka/sigortada servis yalnızca son dönemi verebiliyor
            try:
                have = {norm(x) for x in pd.read_csv(f, dtype=str).iloc[:, 0]}
            except Exception:  # noqa: BLE001
                bad = True
                break
            if any(not (labels[k] & have) for k in keys):
                bad = True
                break
        if bad:
            out.append(t)
    return out
