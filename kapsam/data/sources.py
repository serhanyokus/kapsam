"""Herhangi bir BIST hissesi için finansal tablo kaynağı.

Varsayılan kaynak, KAP verilerini şirket bazında tablo olarak sunan ekofin.net sayfalarıdır
(gelir tablosu, bilanço, nakit akış; son 5 dönem, kümülatif, her dönem kendi raporunun TL'siyle).
Sayfalar yalnızca son 5 dönemi gösterdiği için KAPSAM her çalıştırmada YENİ dönemleri
`HISSE_YYYY_A.csv` olarak kaydeder ve eskilerin üzerine yazmaz; geçmiş zamanla birikir.

Kullanım notları:
* Kişisel araştırma içindir; istekler hisse başına 3 sayfa, aralarda bekleme ile yapılır.
  Kaynağın kullanım koşullarına uyun; ticari kullanımda lisanslı veri sağlayıcıya geçin.
* Bankalar ve sigorta şirketlerinin tablo biçimi farklıdır; bunlar 'desteklenmiyor' olarak atlanır.
* Net parasal pozisyon satırı hiç olmayan şirketler (ör. fonksiyonel para birimi USD olanlar)
  işaretlenir: TMS 29 düzeltmesi bunlara uygulanmamalıdır.
"""
from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from ..textutil import norm, parse_tr_number

BASE = "https://www.ekofin.net/sirket/detay/{ticker}/{page}"
PAGES = ("gelir-tablosu", "bilancolar", "nakit-akim-tablosu")
USER_AGENT = "KAPSAM-arastirma/0.9 (+https://github.com/serhanyokus/kapsam)"
_PERIOD = re.compile(r"^\s*(\d{4})[-/](\d{1,2})\s*$")
_NUM = re.compile(r"^\s*(-?[\d.]+(?:,\d+)?)")

# Kaynak etiketi → KAPSAM kodu. Liste sırası önceliktir (ilk sıradaki tercih edilir).
LABELS: list[tuple[str, str]] = [
    ("Satış Gelirleri", "revenue"), ("Hasılat", "revenue"),
    ("Satışların Maliyeti (-)", "cogs"),
    ("Ticari Faaliyetlerden Brüt Kar (Zarar)", "gross_profit"), ("Brüt Kar (Zarar)", "gross_profit"),
    ("Esas Faaliyet Karı (Zararı)", "operating_profit"), ("Faaliyet Karı (Zararı)", "operating_profit"),
    ("Net Parasal Pozisyon Kazançları (Kayıpları)", "net_monetary_gain"),
    ("Sürdürülen Faaliyetler Vergi Öncesi Karı (Zararı)", "pretax_profit"),
    ("Dönem Karı (Zararı)", "net_income"),
    ("Ana Ortaklık Payları", "net_income_parent"),
    ("Amortisman ve İtfa Gideri İle İlgili Düzeltmeler", "depreciation"),
    ("Maddi ve Maddi Olmayan Duran Varlıkların Alımından Kaynaklanan Nakit Çıkışları", "capex"),
    ("İşletme Faaliyetlerinden Nakit Akışları", "operating_cash_flow"),
    ("Nakit ve Nakit Benzerleri", "cash"),
    ("Toplam Varlıklar", "total_assets"),
    ("Toplam Kaynaklar", "total_liabilities_equity"),
    ("Toplam Özkaynaklar", "total_equity"),
]
_LBL = {norm(k): (code, i) for i, (k, code) in enumerate(LABELS)}

# Bankacılık tablo biçimi (BDDK). Bankalar TMS 29 uygulamaz.
BANK_LABELS: list[tuple[str, str]] = [
    ("FAİZ GELİRLERİ", "interest_income"), ("FAİZ GİDERLERİ (-)", "interest_expense"),
    ("NET FAİZ GELİRİ VEYA GİDERİ", "net_interest_income"),
    ("NET ÜCRET VE KOMİSYON GELİRLERİ VEYA GİDERLERİ", "net_fee_income"),
    ("FAALİYET BRÜT KÂRI", "operating_income"), ("Beklenen Zarar Karşılıkları (-)", "credit_provisions"),
    ("SÜRDÜRÜLEN FAALİYETLER VERGİ ÖNCESİ KARI (ZARARI)", "pretax_profit"),
    ("DÖNEM NET KARI VEYA ZARARI", "net_income"), ("Grubun Karı (Zararı)", "net_income_parent"),
    ("VARLIKLAR TOPLAMI", "total_assets"), ("KREDİLER (Net)", "loans"), ("Mevduat", "deposits"),
    ("ÖZKAYNAKLAR", "total_equity"),
]
# Sigorta tablo biçimi (SEDDK). Sigorta şirketleri TMS 29 uygulamaz.
INSURER_LABELS: list[tuple[str, str]] = [
    ("Brüt Yazılan Primler (+)", "gross_premiums"),
    ("Yazılan Primler (Reasürör Payı Düşülmüş Olarak)", "net_premiums"),
    ("TEKNİK BÖLÜM DENGESİ - HAYAT DIŞI", "technical_result_nonlife"),
    ("GENEL TEKNİK BÖLÜM DENGESİ", "technical_result"),
    ("Dönem Net Karı Veya Zararı", "net_income"), ("Ana Ortaklık Payları", "net_income_parent"),
    ("Toplam Varlıklar", "total_assets"), ("VARLIKLAR TOPLAMI", "total_assets"),
    ("Toplam Özkaynaklar", "total_equity"), ("ÖZKAYNAKLAR", "total_equity"),
]
LABEL_SETS = {"sanayi": _LBL,
              "banka": {norm(k): (c, i) for i, (k, c) in enumerate(BANK_LABELS)},
              "sigorta": {norm(k): (c, i) for i, (k, c) in enumerate(INSURER_LABELS)}}
# CSV'ye yazılırken kullanılan KAP etiketi (statements.ACCOUNT_SYNONYMS ile okunabilir)
CANONICAL = {
    "revenue": "Hasılat", "cogs": "Satışların Maliyeti (-)", "gross_profit": "Brüt Kar (Zarar)",
    "operating_profit": "Esas Faaliyet Karı (Zararı)", "net_monetary_gain": "Net Parasal Pozisyon Kazançları (Kayıpları)",
    "pretax_profit": "Sürdürülen Faaliyetler Vergi Öncesi Karı (Zararı)", "net_income": "Dönem Karı (Zararı)",
    "net_income_parent": "Ana Ortaklık Payları", "depreciation": "Amortisman ve İtfa Gideri İle İlgili Düzeltmeler",
    "capex": "Maddi ve Maddi Olmayan Duran Varlıkların Alımından Kaynaklanan Nakit Çıkışları",
    "operating_cash_flow": "İşletme Faaliyetlerinden Nakit Akışları", "cash": "Nakit ve Nakit Benzerleri",
    "total_assets": "Toplam Varlıklar", "total_liabilities_equity": "Toplam Kaynaklar", "total_equity": "Toplam Özkaynaklar",
    "short_term_debt": "Kısa Vadeli Borçlanmalar", "long_term_debt": "Uzun Vadeli Borçlanmalar",
    # banka
    "interest_income": "Faiz Gelirleri", "interest_expense": "Faiz Giderleri (-)", "net_interest_income": "Net Faiz Geliri",
    "net_fee_income": "Net Ücret ve Komisyon Gelirleri", "operating_income": "Faaliyet Brüt Kârı",
    "credit_provisions": "Beklenen Zarar Karşılıkları (-)", "loans": "Krediler (Net)", "deposits": "Mevduat",
    # sigorta
    "gross_premiums": "Brüt Yazılan Primler", "net_premiums": "Net Yazılan Primler",
    "technical_result_nonlife": "Teknik Bölüm Dengesi - Hayat Dışı", "technical_result": "Genel Teknik Bölüm Dengesi",
}
_FIN_SECTOR = ("faiz gelirleri", "kar payi gelirleri", "kredi riski", "sigortacilik", "prim gelirleri", "katilim bankaciligi")


class UnsupportedFormat(Exception):
    pass


@dataclass
class Fetched:
    ticker: str
    periods: dict[str, dict[str, float]]                 # "2026/9" → {kod: değer}
    warnings: list[str] = field(default_factory=list)
    kind: str = "sanayi"


def clean_cell(x) -> float:
    """'720.477.782.000%8' → 720477782000.0; boş → NaN."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return float("nan")
    if isinstance(x, (int, float)):
        return float(x)
    m = _NUM.match(str(x).replace(" ", " "))
    return parse_tr_number(m.group(1)) if m else float("nan")


def detect_kind(tables: list[pd.DataFrame]) -> str:
    """Tablo biçimini satır etiketlerinden çıkarır: 'banka', 'sigorta' veya 'sanayi'."""
    text = " ".join(norm(str(x)) for t in tables for x in t.iloc[:, 0].tolist())
    if "net faiz geliri veya gideri" in text or ("faiz gelirleri" in text and "mevduat" in text):
        return "banka"
    if "yazilan primler" in text or "teknik bolum dengesi" in text:
        return "sigorta"
    return "sanayi"


def parse_table(df: pd.DataFrame, kind: str = "sanayi") -> dict[str, dict[str, float]]:
    """Kalem sütunu + 'YYYY-AA' dönem sütunlu tabloyu {dönem: {kod: değer}} yapısına çevirir.

    Bilançoda 'Finansal Borçlar' iki kez geçer; içinde bulunduğu bölüm başlığına (Kısa / Uzun Vadeli
    Yükümlülükler) göre kısa veya uzun vadeli borca atanır.
    """
    cols = [c for c in df.columns[1:] if _PERIOD.match(str(c))]
    out: dict[str, dict[str, float]] = {}
    prio: dict[tuple[str, str], int] = {}
    section = ""
    for _, row in df.iterrows():
        label = str(row.iloc[0]).strip()
        n = norm(label)
        if "kisa vadeli yukumluluk" in n:
            section = "kisa"
        elif "uzun vadeli yukumluluk" in n:
            section = "uzun"
        elif "ozkaynak" in n and "toplam" not in n:
            section = "ozkaynak"
        labels = LABEL_SETS[kind]
        if kind == "sanayi" and n.startswith("finansal borclar") and section in {"kisa", "uzun"}:
            code, p = ("short_term_debt" if section == "kisa" else "long_term_debt"), 0
        elif n in labels:
            code, p = labels[n]
        else:
            continue
        for c in cols:
            v = clean_cell(row[c])
            if pd.isna(v):
                continue
            y, mth = _PERIOD.match(str(c)).groups()
            per = f"{int(y)}/{int(mth)}"
            key = (per, code)
            if key not in prio or p < prio[key]:
                out.setdefault(per, {})[code] = v
                prio[key] = p
    return out


def _best_table(html: str) -> pd.DataFrame | None:
    try:
        tables = pd.read_html(io.StringIO(html), thousands=None, decimal=",", flavor="lxml")
    except (ValueError, ImportError):
        return None
    scored = [(sum(bool(_PERIOD.match(str(c))) for c in t.columns), t) for t in tables]
    scored = [s for s in scored if s[0] > 0]
    return max(scored, key=lambda s: (s[0], len(s[1])))[1] if scored else None


class EkofinSource:
    def __init__(self, getter: Callable[[str], str] | None = None, delay: float = 2.0):
        self.getter = getter or self._http_get
        self.delay = delay

    @staticmethod
    def _http_get(url: str) -> str:
        import requests
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        r.raise_for_status()
        return r.text

    def fetch(self, ticker: str) -> Fetched:
        ticker = ticker.upper()
        tables = []
        for i, page in enumerate(PAGES):
            if i and self.delay:
                time.sleep(self.delay)
            t = _best_table(self.getter(BASE.format(ticker=ticker, page=page)))
            if t is not None:
                tables.append(t)
        if not tables:
            raise ValueError(f"{ticker}: tablo bulunamadı (hisse kodu doğru mu?)")
        kind = detect_kind(tables)
        merged: dict[str, dict[str, float]] = {}
        for t in tables:
            for per, vals in parse_table(t, kind).items():
                merged.setdefault(per, {}).update({k: v for k, v in vals.items() if k not in merged.get(per, {})})
        warnings = []
        if kind == "sanayi":
            if not any("revenue" in v for v in merged.values()):
                raise UnsupportedFormat(f"{ticker}: hasılat satırı yok; tablo biçimi tanınmadı")
            if not any("net_monetary_gain" in v for v in merged.values()):
                warnings.append(f"{ticker}: net parasal pozisyon satırı yok; şirket TMS 29 uygulamıyor olabilir "
                                "(ör. fonksiyonel para birimi USD). Nominal modda analiz edilir.")
        elif not any("net_income" in v for v in merged.values()):
            raise UnsupportedFormat(f"{ticker}: {kind} tablosunda dönem kârı satırı bulunamadı")
        return Fetched(ticker, merged, warnings, kind)


def store(f: Fetched, folder: str | Path, overwrite: bool = False) -> list[Path]:
    """Her dönemi 'HISSE_YYYY_A.csv' olarak yazar. Var olan dosyalara dokunmaz (raporlandığı haliyle saklanır)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for per, vals in sorted(f.periods.items()):
        y, m = per.split("/")
        path = folder / f"{f.ticker}_{y}_{m}.csv"
        if path.exists() and not overwrite:
            continue
        rows = [(CANONICAL[k], v) for k, v in vals.items() if k in CANONICAL]
        if not any(k in vals for k in ("revenue", "net_income")):   # yalnızca bilanço olan dönem: çeyrek analizi için yetersiz
            continue
        pd.DataFrame({"Kalem": [r[0] for r in rows], per: [r[1] for r in rows]}).to_csv(path, index=False)
        written.append(path)
    return written
