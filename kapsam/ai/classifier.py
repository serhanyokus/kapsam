"""KAP bildirim sınıflandırıcısı ve önem skoru.

İki katmanlı tasarım:
1. Kural tabanlı temel model (bu dosya): çevrimdışı, açıklanabilir, hızlı. Etiketli veri
   toplanırken başlangıç modeli ve LLM çıktıları için ikinci görüş olarak çalışır.
2. LLM katmanı (llm.py): özet ve gerekçe üretir; çıktısı validate.grounded ile denetlenir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..textutil import norm, parse_tr_number

CATEGORIES: dict[str, dict] = {
    "finansal_rapor": {"kw": ["finansal rapor", "finansal tablo", "faaliyet raporu", "bagimsiz denetim"], "base": 0.6},
    "yeni_is_iliskisi": {"kw": ["yeni is iliskisi", "sozlesme imzalan", "sozlesmesi imzalan", "tedarik sozlesmesi", "ihale", "siparis", "anlasma imzala"], "base": 0.55},
    "sermaye_artirimi": {"kw": ["bedelli sermaye", "bedelsiz sermaye", "sermaye artirimi", "kayitli sermaye tavani"], "base": 0.6},
    "kar_payi": {"kw": ["kar payi", "temettu", "kar dagitim"], "base": 0.5},
    "pay_geri_alim": {"kw": ["geri alim", "pay geri al"], "base": 0.45},
    "birlesme_devralma": {"kw": ["birlesme", "devralma", "satin alma", "pay devri", "istirak edin"], "base": 0.7},
    "yatirim_kapasite": {"kw": ["yatirim karari", "kapasite artis", "yeni tesis", "fabrika", "yatirim tesvik"], "base": 0.5},
    "borclanma_araci": {"kw": ["borclanma araci", "tahvil", "bono", "sukuk", "kira sertifikasi"], "base": 0.3},
    "dava_ceza": {"kw": ["dava", "idari para cezasi", "sorusturma", "rekabet kurulu", "ceza"], "base": 0.55},
    "derecelendirme": {"kw": ["kredi derecelendirme", "not artir", "not indir", "rating"], "base": 0.45},
    "yonetim_degisikligi": {"kw": ["genel mudur", "yonetim kurulu uyesi", "istifa", "atanmasi"], "base": 0.35},
}

POSITIVE = ["artis", "rekor", "yeni is", "kazanildi", "imzalandi", "imzalanmis", "onaylandi", "not artir", "buyume", "kar payi dagit", "geri alim"]
NEGATIVE = ["azalis", "zarar", "iptal", "fesih", "ceza", "dava", "not indir", "erteleme", "durdur", "yangin", "iflas", "konkordato"]

_AMOUNT_RE = re.compile(
    r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?)\s*(milyar|milyon|bin)?\s*(tl|try|usd|abd dolari|dolar|eur|avro)",
    re.IGNORECASE,
)
_SCALE = {"milyar": 1e9, "milyon": 1e6, "bin": 1e3, None: 1.0, "": 1.0}
_FX_HINT = {"usd": "USD", "abd dolari": "USD", "dolar": "USD", "eur": "EUR", "avro": "EUR", "tl": "TRY", "try": "TRY"}


@dataclass
class Classification:
    category: str
    confidence: float
    sentiment: int              # -1, 0, +1
    importance: float           # 0-1
    amounts: list[tuple[float, str]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


def extract_amounts(text: str) -> list[tuple[float, str]]:
    out = []
    for num, scale, cur in _AMOUNT_RE.findall(text):
        try:
            v = parse_tr_number(num) * _SCALE[(scale or "").lower() or None]
        except (ValueError, KeyError):
            continue
        out.append((v, _FX_HINT.get(norm(cur), cur.upper())))
    return out


def classify(text: str, market_cap_try: float | None = None, usdtry: float | None = None) -> Classification:
    """Bildirimi sınıflandırır, yön (+/-) ve 0-1 arası önem skoru üretir.

    market_cap_try verilirse, bildirimdeki tutarın piyasa değerine oranı önem skoruna eklenir.
    """
    t = norm(text)
    scores = {c: sum(t.count(k) for k in spec["kw"]) for c, spec in CATEGORIES.items()}
    best = max(scores, key=scores.get)
    total = sum(scores.values())
    if total == 0:
        best, conf = "diger", 0.0
    else:
        conf = scores[best] / total
    pos = sum(t.count(k) for k in POSITIVE)
    neg = sum(t.count(k) for k in NEGATIVE)
    sentiment = (pos > neg) - (neg > pos)

    amounts = extract_amounts(text)
    importance = CATEGORIES.get(best, {"base": 0.2})["base"]
    if market_cap_try and amounts:
        biggest = max(v * (usdtry if c == "USD" and usdtry else 1.0) for v, c in amounts)
        ratio = biggest / market_cap_try
        importance = min(1.0, importance + min(0.4, ratio * 4))   # piyasa değerinin %10'u → +0.4
    evidence = [k for k in CATEGORIES.get(best, {"kw": []})["kw"] if k in t]
    return Classification(best, round(conf, 2), sentiment, round(importance, 2), amounts, evidence)
