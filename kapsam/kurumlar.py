"""Aracı kurum hedef fiyat takibi: her çalıştırmada haber/araştırma sayfaları taranır, yeni hedefler birikir.

Kaynaklar config/kurum_kaynaklari.json'da (RSS ya da liste sayfası). Liste sayfalarında adresinde "hedef" geçen haberler açılır;
RSS'te tam metin (content:encoded) okunur. Her cümlede kurum adı, hisse (kod ya da şirket adı) ve "hedef" + "… TL" aranır;
"X TL'den Y TL'ye" kalıbında yeni hedef (Y) alınır. Hisse fiyatının 0,4–4 katı dışındaki hedefler (bölünme/bedelsiz öncesi, yanlış eşleşme) atılır.
Kayıtlar data/gercek/kurum_hedefleri.csv'de birikir; özet: son 120 günde her kurumun son hedefi → kurum sayısı, medyan hedef, al payı.
Kibar kullanım: günde en fazla `limit` yeni haber, istekler arasında bekleme, açılan adresler hatırlanır.
"""
from __future__ import annotations

import html as _html
import json
import re
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd

from .textutil import norm

KAYIT = ("data", "gercek", "kurum_hedefleri.csv")
GORULEN = ("data", "gercek", "kurum_gorulen.json")
PENCERE_GUN = 120
VARSAYILAN_KAYNAK = [
    {"tur": "rss", "url": "https://paratic.com/feed/"},
    {"tur": "liste", "url": "https://www.hisse.net/haber/"},
    {"tur": "liste", "url": "https://www.cnbce.com/borsa"},
    {"tur": "liste", "url": "https://www.bloomberght.com/borsa"},
    {"tur": "liste", "url": "https://www.dunya.com/finans/borsa"},
]
KURUMLAR = [
    "A1 Capital", "Ahlatcı Yatırım", "Ak Yatırım", "Albaraka", "Alnus Yatırım", "Anadolu Yatırım", "Ata Yatırım", "Bizim Menkul",
    "Burgan Yatırım", "Deniz Yatırım", "Destek Yatırım", "Galata Yatırım", "Garanti BBVA Yatırım", "Gedik Yatırım", "Global Menkul",
    "Halk Yatırım", "ICBC Turkey Yatırım", "Info Yatırım", "Integral Yatırım", "İş Yatırım", "Kuveyt Türk Yatırım", "Marbaş", "Meksa",
    "Osmanlı Yatırım", "Oyak Yatırım", "Phillip Capital", "Pusula Yatırım", "QNB Yatırım", "QNB Invest", "Şeker Yatırım", "Strateji Menkul",
    "Tacirler Yatırım", "Tera Yatırım", "Ünlü & Co", "Vakıf Yatırım", "Yapı Kredi Yatırım", "Ziraat Yatırım", "Garanti Yatırım",
    "HSBC Yatırım", "Ekspres Invest", "Piramit Menkul", "Inveo Yatırım", "Colendi Menkul", "Midas", "Gcm Yatırım",
    "JPMorgan", "JP Morgan", "Morgan Stanley", "Goldman Sachs", "Citi", "Bank of America", "BofA", "Barclays", "UBS", "HSBC",
    "Deutsche Bank", "Wood & Company", "Erste", "Jefferies", "BNP Paribas", "Santander", "Renaissance", "Raiffeisen",
]
TAVSIYE = [("endeks üstü", "AL"), ("endeksin üzerinde", "AL"), ("ağırlığı artır", "AL"), ("güçlü al", "AL"), ("overweight", "AL"),
           ("outperform", "AL"), ("buy", "AL"), ("endekse paralel", "TUT"), ("endeks paralel", "TUT"), ("nötr", "TUT"),
           ("ağırlığı azalt", "SAT"), ("endeks altı", "SAT"), ("endeksin altında", "SAT"), ("underweight", "SAT"),
           ("“al”", "AL"), ('"al"', "AL"), ("'al'", "AL"), ("al tavsiye", "AL"), ("“tut”", "TUT"), ('"tut"', "TUT"), ("tut tavsiye", "TUT"),
           ("“sat”", "SAT"), ('"sat"', "SAT"), ("sat tavsiye", "SAT")]
GENEL = {"türk", "türkiye", "anadolu", "global", "turkcell", "yatırım", "holding", "enerji", "gayrimenkul", "sanayi", "ticaret",
         "grup", "group", "teknoloji", "elektrik", "çimento", "gıda", "tekstil", "sigorta", "bankası", "bank", "kimya", "metal",
         "petrol", "doğan", "hedef", "fiyat", "borsa", "piyasa", "endeks", "getiri", "tavsiye", "rapor", "sektör", "kurum", "menkul", "değerler", "capital", "katılım", "bursa", "beyaz", "çelik", "dünya", "denge", "emlak", "atlas", "bizim", "duran", "arena", "istanbul", "ankara", "izmir", "avrupa", "mega", "marka", "yeni", "merkez", "ege", "akdeniz", "karadeniz", "ulusal", "orta", "doğu", "batı", "kuzey", "güney", "otomotiv", "madencilik", "inşaat", "boya", "ilaç", "tarım", "kağıt", "cam", "liman", "deniz", "hava"}
_TL = re.compile(r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*(?:TL|lira)", re.I)
_KOD = re.compile(r"\b([A-ZÇĞİÖŞÜ]{4,6})\b")


AYLAR = {"ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6, "temmuz": 7, "agustos": 8, "eylul": 9, "ekim": 10,
         "kasim": 11, "aralik": 12}
TOPLU = ("ortalama", "en yuksek", "en dusuk", "medyan", "konsensus", "arasinda degis")


def nrm(t: str) -> str:
    """norm(), ama parantez içini atmadan ("… (Vakıf Yatırım)" gibi)."""
    return norm(str(t).replace("(", " ").replace(")", " "))


def _trtarih(t: str) -> str:
    m = re.search(r"(\d{1,2})[./ ]+([a-zçğıöşü]+|\d{1,2})[./ ]+(\d{4})", nrm(t) if not re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", t) else t)
    if not m:
        return ""
    mo = AYLAR.get(m.group(2)) if not m.group(2).isdigit() else int(m.group(2))
    try:
        return pd.Timestamp(int(m.group(3)), int(mo), int(m.group(1))).strftime("%Y-%m-%d") if mo else ""
    except ValueError:
        return ""


def tablolar(h: str, kodlar: set[str], alias: dict[str, str], kurumlar: list[str] = KURUMLAR) -> list[dict]:
    """Sayfadaki 'Aracı Kurum | Tarih | Hedef | Tavsiye' tabloları. Hisse kodu sayfa başlığından/adresinden bulunur."""
    title = " ".join(re.findall(r"(?is)<title[^>]*>(.*?)</title>|<h1[^>]*>(.*?)</h1>", h) and
                     [a or b for a, b in re.findall(r"(?is)<title[^>]*>(.*?)</title>|<h1[^>]*>(.*?)</h1>", h)])
    title = _html.unescape(re.sub(r"<[^>]+>", " ", title))
    kods = [k for k in _KOD.findall(title) if k in kodlar]
    if not kods:
        nt = nrm(title)
        kods = [v for a, v in sorted(alias.items(), key=lambda x: -len(x[0])) if re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", nt)][:1]
    if not kods:
        return []
    kn = sorted(((nrm(k), k) for k in kurumlar), key=lambda x: -len(x[0]))
    out = []
    for tb in re.findall(r"(?is)<table.*?</table>", h):
        rows = [[_html.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"(?is)<t[hd][^>]*>(.*?)</t[hd]>", tr)]
                for tr in re.findall(r"(?is)<tr.*?</tr>", tb)]
        if not rows:
            continue
        hd = [nrm(c) for c in rows[0]]
        ik = next((i for i, c in enumerate(hd) if "kurum" in c), None)
        ih = next((i for i, c in enumerate(hd) if "hedef" in c), None)
        if ik is None or ih is None:
            continue
        it_ = next((i for i, c in enumerate(hd) if "tarih" in c), None)
        iv = next((i for i, c in enumerate(hd) if "tavsiye" in c or "oneri" in c), None)
        for r in rows[1:]:
            if len(r) <= max(ik, ih):
                continue
            name = r[ik]
            nn = nrm(name)
            if not nn or any(w in nn for w in TOPLU):
                continue
            kur = next((k for n_, k in kn if n_ == nn or n_ in nn or nn in n_), re.sub(r"\s+", " ", name)[:40])
            try:
                hedef = _sayi(re.search(r"\d[\d.,]*", r[ih]).group(0))
            except (AttributeError, ValueError):
                continue
            tv = (r[iv] if iv is not None and iv < len(r) else "").lower()
            tav = next((v for w, v in TAVSIYE if w in tv), "AL" if tv.strip() == "al" else "TUT" if tv.strip() == "tut" else
                       "SAT" if tv.strip() == "sat" else "")
            out.append({"kod": kods[0], "kurum": kur, "hedef": hedef, "tavsiye": tav,
                        "tarih": _trtarih(r[it_]) if it_ is not None and it_ < len(r) else "", "cumle": " | ".join(r)[:220]})
    return out


def _sayi(x: str) -> float:
    return float(x.replace(".", "").replace(",", "."))


def alias_map(universe: pd.DataFrame) -> dict[str, str]:
    """Şirket adı parçası (normalize) → kod. Çok genel ilk kelimeler tek başına kullanılmaz."""
    m: dict[str, str] = {}
    for _, r in universe.iterrows():
        ad = str(r.get("ad") or "")
        w = [x for x in re.split(r"\s+", ad) if x]
        if len(w) >= 2:
            m.setdefault(norm(" ".join(w[:2])), r["kod"])
        if w and len(w[0]) >= 5 and norm(w[0]) not in {norm(g) for g in GENEL}:
            m.setdefault(norm(w[0]), r["kod"])
    m = {a: c for a, c in m.items() if len(a) >= 4 and a not in {norm(g) for g in GENEL}}
    for k, v in {"türk hava yolları": "THYAO", "thy": "THYAO", "tüpraş": "TUPRS", "coca-cola içecek": "CCOLA", "coca cola": "CCOLA",
                 "türk telekom": "TTKOM", "turkcell": "TCELL", "şişecam": "SISE", "bim": "BIMAS", "migros": "MGROS",
                 "koç holding": "KCHOL", "sabancı holding": "SAHOL", "ford otosan": "FROTO", "tofaş": "TOASO", "aselsan": "ASELS",
                 "pegasus": "PGSUS", "garanti bbva": "GARAN", "akbank": "AKBNK", "yapı kredi": "YKBNK", "iş bankası": "ISCTR",
                 "halkbank": "HALKB", "vakıfbank": "VAKBN", "emlak konut": "EKGYO", "tav havalimanları": "TAVHL", "arçelik": "ARCLK",
                 "türkiye sigorta": "TURSG", "ereğli": "EREGL", "erdemir": "EREGL", "kardemir": "KRDMD", "enka": "ENKAI"}.items():
        m[norm(k)] = v
    return m


def _metin(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|nav|footer|aside)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<\s*(br|/p|/li|/h\d|/div|/tr)[^>]*>", "\n", h)
    return _html.unescape(re.sub(r"<[^>]+>", " ", h))


def _cumleler(text: str) -> list[str]:
    out = []
    for line in text.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ])", line) if s.strip()]
    return out


def _parcala(cumleler: list[str], kn) -> list[str]:
    """Bir cümlede birden çok kurum varsa her kurumun adından böler ("A, X için … açıklarken B, Y için …")."""
    out = []
    pats = [re.compile(r"(?<![\w])" + re.escape(k) + r"(?![\w])", re.I) for _, k in kn]
    for c in cumleler:
        pos = sorted({m.start() for p in pats for m in p.finditer(c)})
        keep = [p for i, p in enumerate(pos) if i == 0 or p - pos[i - 1] > 3]
        if len(keep) < 2:
            out.append(c)
            continue
        cuts = [0] + keep[1:] + [len(c)]
        out += [c[a:b].strip(" ,;") for a, b in zip(cuts, cuts[1:]) if c[a:b].strip(" ,;")]
    return out


def parse(text: str, kodlar: set[str], alias: dict[str, str], kurumlar: list[str] = KURUMLAR) -> list[dict]:
    """Metinden (kod, kurum, hedef, tavsiye) kayıtları. Kurum/hisse cümlede yoksa önceki başlık/cümleden taşınır."""
    kn = sorted(((nrm(k), k) for k in kurumlar), key=lambda x: -len(x[0]))
    an = sorted(alias.items(), key=lambda x: -len(x[0]))
    ctx_k = ctx_t = None
    out = []
    for s in _parcala(_cumleler(text), kn):
        ns = nrm(s)
        if any(w in ns for w in TOPLU):                 # toplu cümle (ortalama/en yüksek/en düşük hedef): kuruma ait değil
            continue
        kur = next((k for nk, k in kn if re.search(r"(?<![a-z0-9])" + re.escape(nk) + r"(?![a-z0-9])", ns)), None)
        rest = ns
        for nk, _k in kn:                               # kurum adı hisse adı sanılmasın (Şeker Yatırım → SKYMD gibi)
            rest = re.sub(r"(?<![a-z0-9])" + re.escape(nk) + r"(?![a-z0-9])", " ", rest)
        kods = [k for k in _KOD.findall(s) if k in kodlar and norm(k) in rest.split()]
        if not kods:
            hit = next((v for a, v in an if re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", rest)), None)
            kods = [hit] if hit else []
        has_t = "hedef" in ns and _TL.search(s)
        if not has_t:                                   # başlık/bağlam satırı
            if kur and len(s) < 80:
                ctx_k = kur
            if kods:
                ctx_t = kods[0]
            continue
        kur = kur or ctx_k
        kod = kods[0] if kods else ctx_t
        if kods:
            ctx_t = kods[0]
        if not (kur and kod):
            continue
        m = re.search(r"(\d[\d.,]*)\s*TL['’]?den\s*(\d[\d.,]*)\s*TL", s)
        try:
            hedef = _sayi(m.group(2)) if m else _sayi(_TL.search(s).group(1))
        except ValueError:
            continue
        tav = next((v for w, v in TAVSIYE if w in s.lower()), "")
        out.append({"kod": kod, "kurum": kur, "hedef": hedef, "tavsiye": tav, "cumle": s[:220]})
    return out


def _tarih(h: str) -> str:
    m = re.search(r'(?:article:modified_time|og:updated_time|dateModified)["\']?\s*(?:content=|:)\s*["\'](\d{4}-\d{2}-\d{2})', h) or \
        re.search(r'(?:article:published_time|datePublished)["\']?\s*(?:content=|:)\s*["\'](\d{4}-\d{2}-\d{2})', h)
    return m.group(1) if m else ""


def kaynaklar(root: Path) -> list[dict]:
    try:
        return json.loads((Path(root) / "config" / "kurum_kaynaklari.json").read_text(encoding="utf-8"))["kaynaklar"]
    except Exception:  # noqa: BLE001
        return VARSAYILAN_KAYNAK


def guncelle(root: Path, universe: pd.DataFrame, prices: dict[str, float] | None = None, session=None, limit: int = 60,
             pause: float = 1.0) -> dict:
    import requests
    root = Path(root)
    s = session or requests.Session()
    hdr = {"User-Agent": "Mozilla/5.0 (KAPSAM arastirma)"}
    kodlar = set(universe["kod"])
    alias = alias_map(universe)
    gf = root.joinpath(*GORULEN)
    try:
        seen = json.loads(gf.read_text(encoding="utf-8"))
        seen = seen if isinstance(seen, dict) else {u: "2000-01-01" for u in seen}
    except Exception:  # noqa: BLE001
        seen = {}
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    rows, errs, opened = [], [], 0
    for src in kaynaklar(root):
        try:
            r = s.get(src["url"], headers=hdr, timeout=25)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            errs.append(f"{src['url']}: {e}")
            continue
        if src.get("tur") == "rss":
            import xml.etree.ElementTree as ET
            ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
            for it in ET.fromstring(r.content).iter("item"):
                link = it.findtext("link") or ""
                title = it.findtext("title") or ""
                if link in seen or "hedef" not in norm(title + " " + (it.findtext("description") or "")):
                    continue
                body = it.findtext("content:encoded", namespaces=ns) or it.findtext("description") or ""
                try:
                    d = parsedate_to_datetime(it.findtext("pubDate") or "").strftime("%Y-%m-%d")
                except Exception:  # noqa: BLE001
                    d = today
                for x in parse(title + "\n" + _metin(body), kodlar, alias):
                    rows.append({**x, "tarih": d, "kaynak": link})
                seen[link] = today
        else:
            links = re.findall(r'href=["\']([^"\'#]+)["\']', r.text)
            links = [urljoin(src["url"], u) for u in links if "hedef" in u.lower()]
            yenile = int(src.get("yenile_gun", 100000))
            for u in dict.fromkeys(links):
                if opened >= limit:
                    break
                if u in seen and (pd.Timestamp(today) - pd.Timestamp(seen[u])).days < yenile:
                    continue
                time.sleep(pause)
                try:
                    a = s.get(u, headers=hdr, timeout=25)
                    a.raise_for_status()
                except Exception as e:  # noqa: BLE001
                    errs.append(f"{u}: {e}")
                    continue
                opened += 1
                seen[u] = today
                d = _tarih(a.text) or today
                for x in tablolar(a.text, kodlar, alias):
                    rows.append({**x, "tarih": x["tarih"] or d, "kaynak": u})
                for x in parse(_metin(re.sub(r"(?is)<table.*?</table>", " ", a.text)), kodlar, alias):
                    rows.append({**x, "tarih": d, "kaynak": u})
        time.sleep(pause)
    new = pd.DataFrame(rows, columns=["tarih", "kod", "kurum", "hedef", "tavsiye", "cumle", "kaynak"])
    if prices and len(new):                                     # bölünme öncesi / yanlış eşleşme süzgeci
        px = new["kod"].map(prices)
        new = new[px.isna() | ((new["hedef"] / px).between(0.4, 4.0))]
    kf = root.joinpath(*KAYIT)
    old = pd.read_csv(kf) if kf.exists() else new.iloc[0:0]
    if len(old):                                                # eski sürümün yanlış eşlediği toplu cümleleri temizle
        old = old[~old["cumle"].fillna("").map(lambda c: any(w in nrm(c) for w in TOPLU))]
    allr = pd.concat([old, new], ignore_index=True).drop_duplicates(["tarih", "kod", "kurum", "hedef"])
    kf.parent.mkdir(parents=True, exist_ok=True)
    allr.sort_values(["tarih", "kod"]).to_csv(kf, index=False)
    keep = dict(sorted(seen.items(), key=lambda kv: kv[1])[-3000:])
    gf.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
    return {"yeni": len(new), "toplam": len(allr), "haber": opened, "hatalar": errs}


def ozet(root: Path, prices: dict[str, float] | None = None, today: pd.Timestamp | None = None) -> pd.DataFrame:
    """Son PENCERE_GUN günde her kurumun son hedefi → kod başına kurum sayısı, medyan hedef, al payı, son tarih, kurumlar."""
    kf = Path(root).joinpath(*KAYIT)
    if not kf.exists():
        return pd.DataFrame()
    d = pd.read_csv(kf)
    d["tarih"] = pd.to_datetime(d["tarih"], errors="coerce")
    today = today or pd.Timestamp.today().normalize()
    d = d[d["tarih"] >= today - pd.Timedelta(days=PENCERE_GUN)]
    if prices:
        px = d["kod"].map(prices)
        d = d[px.isna() | ((d["hedef"] / px).between(0.4, 4.0))]
    if not len(d):
        return pd.DataFrame()
    d["kurum_n"] = d["kurum"].map(lambda k: norm(k).replace("invest", "yatirim"))
    last = d.sort_values("tarih").groupby(["kod", "kurum_n"]).tail(1)
    g = last.groupby("kod")
    return pd.DataFrame({
        "kurum_sayisi": g["kurum"].nunique(),
        "medyan_hedef": g["hedef"].median(),
        "al_payi": g["tavsiye"].apply(lambda s: (s == "AL").sum() / max(1, (s.fillna("") != "").sum())),
        "tarih": g["tarih"].max().dt.strftime("%Y-%m-%d"),
        "kurumlar": g.apply(lambda x: ", ".join(f"{k} {h:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                                                for k, h in zip(x["kurum"], x["hedef"]))),
        "kaynak": "haber taraması (son 120 gün)",
    })
