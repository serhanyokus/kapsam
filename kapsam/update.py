"""Otomatik gerçek veri güncellemesi.

GitHub Actions bu modülü her iş günü çalıştırır (bkz. .github/workflows/guncelle.yml):

1. TCMB EVDS: aylık TÜFE ve günlük USD/TRY  → data/gercek/tufe_aylik.csv, kur_gunluk.csv, makro_ceyrek.csv
2. Piyasa: takip listesindeki hisselerin ve XU100'ün günlük fiyatları → data/gercek/fiyatlar.csv
3. KAP finansal tabloları: data/gercek/kap/ klasörüne bırakılan HISSE_YYYY_A.xlsx dosyaları
   → her şirket için araştırma notu ve Excel modeli (docs/rapor/)
4. Olay çalışması: config/takip.json'daki olaylar için gerçek fiyatlarla CAR
5. Durum sayfası: docs/rapor/index.html ve durum.json

Bir kaynak hata verirse önceki veri korunur ve hata durum sayfasında gösterilir; hiçbir adım
diğerlerini durdurmaz.
"""
from __future__ import annotations

import base64
import html
import io
import json
import os
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import graph as kg
from . import pipeline, risk, report, valuation
from .data import evds as evds_mod
from .data.market import Market, returns, summary

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Paths:
    root: Path = ROOT

    @property
    def config(self): return self.root / "config" / "takip.json"
    @property
    def data(self): return self.root / "data" / "gercek"
    @property
    def kap(self): return self.data / "kap"
    @property
    def out(self): return self.root / "docs" / "rapor"


@dataclass
class Status:
    started: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    steps: dict = field(default_factory=dict)

    def ok(self, step, detail=""):
        self.steps[step] = {"durum": "tamam", "detay": detail}

    def fail(self, step, err):
        self.steps[step] = {"durum": "hata", "detay": str(err)[:300]}

    def skip(self, step, why):
        self.steps[step] = {"durum": "atlandı", "detay": why}


def load_config(p: Paths) -> dict:
    cfg = json.loads(p.config.read_text(encoding="utf-8"))
    cfg.setdefault("baslangic", "2022-01-01")
    cfg.setdefault("hisseler", [])
    cfg.setdefault("olaylar", [])
    return cfg


def _ddmmyyyy(d: str) -> str:
    return pd.Timestamp(d).strftime("%d-%m-%Y")


def step_macro(p: Paths, cfg: dict, st: Status, client=None):
    key = os.getenv("EVDS_API_KEY")
    if client is None and not key:
        st.skip("makro", "EVDS_API_KEY tanımlı değil (GitHub → Settings → Secrets → Actions)")
        return
    try:
        c = client or evds_mod.EVDSClient(key)
        start, end = _ddmmyyyy(cfg["baslangic"]), datetime.now().strftime("%d-%m-%Y")
        cpi_old = c.series(evds_mod.SERIES["cpi"], start, end)   # TÜFE 2003=100 (Ocak 2026'da durdu)
        fx = c.series(evds_mod.SERIES["usdtry"], start, end)
        if cpi_old.empty or fx.empty:
            raise ValueError("EVDS boş yanıt döndü")
        code_new = cfg.get("tufe_2025_kodu") or (c.find_cpi_2025() if hasattr(c, "find_cpi_2025") else None)
        cpi_new = None
        if code_new:
            try:
                cpi_new = c.series(code_new, start, end)
            except Exception:  # noqa: BLE001
                cpi_new = None
        tf = p.data / "tufe_aylik.csv"
        existing, src = None, pd.Series(dtype=object)
        if tf.exists():
            old_df = pd.read_csv(tf, index_col=0, parse_dates=True)
            old_df.index = old_df.index + pd.offsets.MonthEnd(0)
            existing = old_df.iloc[:, 0]
            src = old_df["kaynak"] if "kaynak" in old_df else src
        cpi_old.index = cpi_old.index + pd.offsets.MonthEnd(0)
        if cpi_new is not None:
            cpi_new.index = cpi_new.index + pd.offsets.MonthEnd(0)
        cpi, note = evds_mod.merge_cpi(existing, cpi_old, cpi_new)
        kaynak = src.reindex(cpi.index)
        kaynak.loc[cpi_old.index] = "TÜİK TÜFE 2003=100 (EVDS TP.FG.J0)"
        if cpi_new is not None:
            kaynak.loc[cpi.index > cpi_old.index[-1]] = f"zincirlenmiş: TÜİK 2025=100 (EVDS {code_new}) aylık değişim"
        p.data.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"tufe": cpi, "kaynak": kaynak.fillna("kayıtlı seri")}).to_csv(tf, index_label="tarih")
        fx.rename("usdtry").to_csv(p.data / "kur_gunluk.csv", index_label="tarih")
        q = evds_mod.to_quarter_end(cpi, fx)
        mq = p.data / "makro_ceyrek.csv"
        if mq.exists():   # kur verisi gelmeyen eski çeyrekleri koru
            prev = pd.read_csv(mq).set_index("period")
            q.index = q.index.astype(str)
            q = q.combine_first(prev[["cpi", "usdtry"]])
        pd.DataFrame({"period": q.index.astype(str), "cpi": q["cpi"].values, "usdtry": q["usdtry"].values}).to_csv(
            mq, index=False)
        st.ok("makro", f"TÜFE son: {cpi.index[-1]:%Y-%m} ({note}{'; 2025=100 kodu: ' + code_new if code_new else '; 2025=100 serisi bulunamadı, config/takip.json → tufe_2025_kodu'}), kur son: {fx.index[-1]:%Y-%m-%d}")
    except Exception as e:  # noqa: BLE001
        st.fail("makro", e)


def _download_chunks(m: Market, tickers: list[str], start: str, chunk: int = 60, pause: float = 1.0) -> tuple[pd.DataFrame, list[str]]:
    """Çok sayıda hisseyi parça parça indirir; bir parça hata verirse diğerleri etkilenmez."""
    import time
    frames, failed = [], []
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i + chunk]
        try:
            df = m.prices(part, start, with_index=(i == 0))
            frames.append(df)
        except Exception:  # noqa: BLE001
            failed += part
        if pause and i + chunk < len(tickers):
            time.sleep(pause)
    if not frames:
        return pd.DataFrame(), failed
    px = pd.concat(frames, axis=1)
    px = px.loc[:, ~px.columns.duplicated()].sort_index()
    return px, failed


def step_prices(p: Paths, cfg: dict, st: Status, market: Market | None = None, universe_df: pd.DataFrame | None = None):
    """Takip listesi + (evren='tum' ise) borsadaki TÜM hisselerin günlük düzeltilmiş fiyatları.
    Tüm hisseler data/gercek/fiyat/YYYY.csv dosyalarına yıllara bölünerek yazılır; fiyatlar.csv takip listesidir."""
    watch = [h["kod"] for h in cfg["hisseler"]]
    every = list(universe_df["kod"]) if (cfg.get("evren") == "tum" and universe_df is not None and len(universe_df)) else []
    tickers = list(dict.fromkeys(watch + every))
    if not tickers:
        st.skip("fiyat", "Takip listesi boş")
        return
    try:
        m = market or Market()
        px, failed = _download_chunks(m, tickers, cfg["baslangic"], pause=0 if market else 1.0)
        if px.empty:
            raise ValueError("Fiyat verisi boş")
        p.data.mkdir(parents=True, exist_ok=True)
        cols = [c for c in watch if c in px.columns] + (["XU100"] if "XU100" in px.columns else [])
        px[cols].dropna(how="all").to_csv(p.data / "fiyatlar.csv", index_label="tarih")
        if every:
            risk.save_prices_by_year(px, p.data / "fiyat")
        shares = {}
        for h in cfg["hisseler"]:
            shares[h["kod"]] = h.get("hisse_sayisi") or m.shares(h["kod"])
        (p.data / "hisse_sayilari.json").write_text(json.dumps(shares, indent=1), encoding="utf-8")
        have = [t for t in tickers if t in px.columns and px[t].notna().any()]
        miss_w = [t for t in watch if t not in have]
        st.ok("fiyat", f"{len(have)}/{len(tickers)} hisse (takip listesi {len(watch) - len(miss_w)}/{len(watch)}), "
              f"son tarih {px.index[-1]:%Y-%m-%d}" + (f"; takipte eksik: {', '.join(miss_w)}" if miss_w else ""))
    except Exception as e:  # noqa: BLE001
        st.fail("fiyat", e)


def _all_prices(p: Paths) -> pd.DataFrame:
    full = risk.load_prices(p.data / "fiyat") if (p.data / "fiyat").exists() else pd.DataFrame()
    if not full.empty:
        return full
    fp = p.data / "fiyatlar.csv"
    return pd.read_csv(fp, index_col=0, parse_dates=True) if fp.exists() else pd.DataFrame()


def step_risk(p: Paths, cfg: dict, st: Status, universe_df: pd.DataFrame | None = None,
              today: pd.Timestamp | None = None) -> pd.DataFrame | None:
    """Tüm hisseler için risk tablosu; takip listesi ve sektör korelasyonu her gün, tüm piyasa matrisleri haftalık."""
    px = _all_prices(p)
    if px.empty or "XU100" not in px:
        st.skip("risk", "Fiyat verisi yok")
        return None
    try:
        today = today or pd.Timestamp.today()
        out = p.out / "risk"
        out.mkdir(parents=True, exist_ok=True)
        r = risk.window(risk.log_returns(px))
        cov, corr = risk.cov_corr(r)
        cpi = _read_csv_series(p.data / "tufe_aylik.csv") if (p.data / "tufe_aylik.csv").exists() else None
        fx = _read_csv_series(p.data / "kur_gunluk.csv") if (p.data / "kur_gunluk.csv").exists() else None
        tab = risk.risk_table(px, cpi_monthly=cpi, usdtry=fx, corr=corr)
        meta = universe_df.set_index("kod")[["ad", "sektor"]] if universe_df is not None and len(universe_df) else None
        if meta is None and (p.root / "config" / "bist_evren.csv").exists():
            meta = pd.read_csv(p.root / "config" / "bist_evren.csv").set_index("kod")[["ad", "sektor"]]
        if meta is not None:
            attrs = dict(tab.attrs)
            tab = meta.reindex(tab.index).join(tab)
            tab.attrs.update(attrs)
        tab.to_csv(out / "risk_ozet.csv")
        watch = [h["kod"] for h in cfg["hisseler"] if h["kod"] in corr.index]
        corr.loc[watch, watch].round(4).to_csv(out / "takip_korelasyon.csv")
        cov.loc[watch, watch].round(6).to_csv(out / "takip_kovaryans.csv")
        sec = risk.sector_corr(corr.drop(index="XU100", columns="XU100", errors="ignore"), meta["sektor"]) if meta is not None else None
        if sec is not None:
            sec.round(3).to_csv(out / "sektor_korelasyon.csv")
        info_f = out / "matris_bilgi.json"
        info = json.loads(info_f.read_text(encoding="utf-8")) if info_f.exists() else {}
        last = pd.Timestamp(info.get("tarih", "2000-01-01"))
        weekly = (not (out / "korelasyon_tum.csv.gz").exists()) or today.weekday() == 4 or (today - last).days >= 7
        if weekly:
            corr.round(4).to_csv(out / "korelasyon_tum.csv.gz", compression="gzip")
            cov.round(6).to_csv(out / "kovaryans_tum.csv.gz", compression="gzip")
            lw, delta = risk.ledoit_wolf(r.drop(columns="XU100", errors="ignore"))
            lw.round(6).to_csv(out / "kovaryans_ledoit_wolf.csv.gz", compression="gzip")
            info = {"tarih": f"{today:%Y-%m-%d}", "pencere": tab.attrs.get("baslangic", "") + " – " + tab.attrs.get("bitis", ""),
                    "hisse_sayisi": int(len(corr)), "lw_hisse_sayisi": int(len(lw)), "lw_kucultme": delta}
            info_f.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "index.html").write_text(risk_page(tab, corr.loc[watch, watch], sec, info, st.started), encoding="utf-8")
        avg = tab["ort_korelasyon"].median() if "ort_korelasyon" in tab else np.nan
        st.ok("risk", f"{len(tab)} hisse; medyan yıllık oynaklık %{tab['oynaklik_yillik'].median()*100:.0f}, "
              f"medyan beta {tab['beta'].median():.2f}, ort. korelasyon {avg:.2f}; tüm piyasa matrisleri "
              + ("güncellendi" if weekly else f"haftalık ({info.get('tarih', '')})"))
        return tab
    except Exception as e:  # noqa: BLE001
        st.fail("risk", e)
        return None


def risk_page(tab: pd.DataFrame, wcorr: pd.DataFrame, sec: pd.DataFrame | None, info: dict, stamp: str) -> str:
    e = html.escape
    cols = [("ad", "Şirket", "t"), ("sektor", "Sektör", "t"), ("getiri_yillik", "Getiri 1Y", "p"), ("reel_getiri_yillik", "Reel getiri", "p"),
            ("usd_getiri_yillik", "USD getiri", "p"), ("oynaklik_yillik", "Oynaklık", "p"), ("beta", "Beta", "x"),
            ("korelasyon_xu100", "Kor. XU100", "x"), ("ozgun_oynaklik", "Özgün oynaklık", "p"), ("max_dusus", "Max düşüş", "p"),
            ("var95_gunluk", "VaR95 (gün)", "p"), ("es95_gunluk", "ES95 (gün)", "p"), ("getiri_oynaklik_orani", "Getiri/oynaklık", "x"),
            ("ort_korelasyon", "Ort. korelasyon", "x"), ("en_yakin_3", "En çok birlikte hareket eden", "t")]
    cols = [c for c in cols if c[0] in tab.columns]

    def cell(v, kind):
        if kind == "t" or isinstance(v, str):
            return f"<td class='l'>{e('' if pd.isna(v) else str(v))}</td>"
        if pd.isna(v):
            return "<td data-v=''>–</td>"
        return f"<td data-v='{v:.6f}'>{v*100:.1f}%</td>" if kind == "p" else f"<td data-v='{v:.6f}'>{v:.2f}</td>"
    head = "<th>Kod</th>" + "".join(f"<th>{e(lab)}</th>" for _, lab, _ in cols)
    body = "".join(f"<tr><td class='l'><b>{e(t)}</b></td>" + "".join(cell(r.get(c), k) for c, _, k in cols) + "</tr>"
                   for t, r in tab.iterrows())
    imgs = ""
    if len(wcorr) > 2:
        order = risk.cluster_order(wcorr)
        imgs += f"<h2>Takip listesi korelasyon ısı haritası (kümelenmiş)</h2><img src='{risk.heatmap_png(wcorr.loc[order, order])}' alt='Korelasyon'>"
    if sec is not None and len(sec) > 2:
        imgs += f"<h2>Sektörler arası ortalama korelasyon</h2><img src='{risk.heatmap_png(sec)}' alt='Sektör korelasyonu'>"
    files = [("risk_ozet.csv", "Risk tablosu (tüm hisseler)"), ("takip_korelasyon.csv", "Takip listesi korelasyon"),
             ("takip_kovaryans.csv", "Takip listesi kovaryans (yıllık)"), ("sektor_korelasyon.csv", "Sektör korelasyonu"),
             ("korelasyon_tum.csv.gz", "Tüm hisseler korelasyon matrisi"), ("kovaryans_tum.csv.gz", "Tüm hisseler kovaryans (yıllık, örnek)"),
             ("kovaryans_ledoit_wolf.csv.gz", "Tüm hisseler Ledoit–Wolf kovaryans (pozitif tanımlı)")]
    links = " · ".join(f"<a href='{f}'>{e(lab)}</a>" for f, lab in files)
    lw = info.get("lw_kucultme")
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KAPSAM · Risk ve korelasyon</title><style>
body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:16px;color:#1d2433}}h2{{font-size:15px;margin-top:22px}}
input{{font-size:14px;padding:6px 10px;width:280px;max-width:100%}}.wrap{{overflow-x:auto}}img{{max-width:100%}}
table{{border-collapse:collapse;font-size:12px;white-space:nowrap}}th{{position:sticky;top:0;background:#f5f7fb;cursor:pointer}}
th,td{{border-bottom:1px solid #eef1f5;padding:4px 8px;text-align:right}}.l{{text-align:left}}.m{{color:#6b7385;font-size:12px}}
</style></head><body><h1>KAPSAM · Risk ve korelasyon (tüm BIST)</h1>
<p class="m">{len(tab)} hisse · pencere: son 252 işlem günü ({e(tab.attrs.get('baslangic', ''))} – {e(tab.attrs.get('bitis', ''))}) · {e(stamp)} (UTC).
Günlük log getiri; yıllıklaştırma 252 gün. Beta ve korelasyon BIST 100'e göre. Reel getiri TÜFE, USD getiri TCMB kuru ile.
Yıllık enflasyon: {'' if pd.isna(tab.attrs.get('yillik_enflasyon')) else f"%{tab.attrs['yillik_enflasyon']*100:.1f}"}.
Tüm piyasa matrisleri haftalık güncellenir (son: {e(str(info.get('tarih', '–')))}; Ledoit–Wolf küçültme katsayısı {'' if lw is None else f'{lw:.2f}'}, {info.get('lw_hisse_sayisi', '–')} hisse).</p>
<p>İndir: {links}</p>
{imgs}
<h2>Risk tablosu</h2><input id="q" placeholder="Kod, şirket veya sektör ara" oninput="f()">
<div class="wrap"><table id="t"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>
<p class="m">VaR95/ES95: günlük %5 en kötü getiri eşiği ve o günlerin ortalama kaybı (tarihsel). Özgün oynaklık: piyasa (beta) etkisi çıkarıldıktan sonra kalan.
Getiri/oynaklık: risksiz faiz düşülmemiş basit oran. Fiyatlar Yahoo Finance (gecikmeli, bölünme ve bedelsize göre düzeltilmiş). Yatırım tavsiyesi değildir.</p>
<script>
function f(){{const q=document.getElementById('q').value.toLocaleLowerCase('tr');for(const r of document.querySelectorAll('#t tbody tr'))r.style.display=r.innerText.toLocaleLowerCase('tr').includes(q)?'':'none'}}
document.querySelectorAll('#t th').forEach((th,i)=>th.onclick=()=>{{const tb=document.querySelector('#t tbody');const rs=[...tb.rows];const d=th.dataset.d=th.dataset.d==='1'?'0':'1';
rs.sort((a,b)=>{{const x=a.cells[i].dataset.v??a.cells[i].innerText,y=b.cells[i].dataset.v??b.cells[i].innerText;const nx=parseFloat(x),ny=parseFloat(y);
const c=(isNaN(nx)||isNaN(ny))?String(x).localeCompare(String(y),'tr'):nx-ny;return d==='1'?-c:c}});rs.forEach(r=>tb.appendChild(r))}});
</script></body></html>"""


def _read_csv_series(path: Path) -> pd.Series:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return df.iloc[:, 0]


FILING_LAG_DAYS = {1: 75, 2: 75, 3: 75, 4: 100}     # çeyrek sonundan sonra raporun beklendiği en geç gün (yaklaşık)
WINDOW_OPEN_DAYS = 25                                 # bu günden itibaren yeni rapor gelebilir
RECHECK_DAYS = 3


def expected_latest(today: pd.Timestamp) -> pd.Period:
    """Bugün itibarıyla tüm şirketlerin yayımlamış olması beklenen en son çeyrek."""
    q = pd.Period(today, freq="Q") - 1
    while today < q.end_time + pd.Timedelta(days=FILING_LAG_DAYS[q.quarter]):
        q -= 1
    return q


def needs_check(today: pd.Timestamp, latest_stored: pd.Period | None, last_check: pd.Timestamp | None) -> bool:
    """Yeni bir rapor gelmiş olabilir mi ve son kontrolden beri yeterli zaman geçti mi?"""
    if latest_stored is None or last_check is None:
        return True
    exp = expected_latest(today)
    if latest_stored < exp:                                   # beklenen rapor eksik: kontrol et
        return (today - last_check).days >= RECHECK_DAYS
    nxt = latest_stored + 1
    window_open = today >= nxt.end_time + pd.Timedelta(days=WINDOW_OPEN_DAYS)
    return window_open and (today - last_check).days >= RECHECK_DAYS


def step_universe(p: Paths, cfg: dict, st: Status, getter=None) -> pd.DataFrame | None:
    """Tüm BIST hisselerinin listesi, sektörü, fiyatı ve piyasa değeri (tek istek)."""
    from .data import universe
    path = p.root / "config" / "bist_evren.csv"
    if cfg.get("evren", "takip") != "tum" and getter is None and not cfg.get("evren_fiyat", True):
        st.skip("evren", "Evren kapalı")
        return universe.load(path) if path.exists() else None
    try:
        df = universe.fetch(getter)
        if len(df) < 50 and getter is None:
            raise ValueError(f"yalnızca {len(df)} hisse okundu; kaynak düzeni değişmiş olabilir")
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        counts = df["tur"].value_counts().to_dict()
        st.ok("evren", f"{len(df)} hisse ({', '.join(f'{k}: {v}' for k, v in counts.items())})")
        return df
    except Exception as e:  # noqa: BLE001
        if path.exists():
            st.fail("evren", f"{e}; son kayıtlı liste kullanıldı")
            return universe.load(path)
        st.fail("evren", e)
        return None


def _latest_stored(folder: Path) -> dict[str, pd.Period]:
    out: dict[str, pd.Period] = {}
    for t, files in pipeline.discover(folder).items() if folder.exists() else []:
        out[t] = max(pd.Period(year=int(f.stem.split("_")[1]), quarter=(int(f.stem.split("_")[2]) - 1) // 3 + 1, freq="Q")
                     for f in files)
    return out


def plan_tables(p: Paths, cfg: dict, universe_df: pd.DataFrame | None, today: pd.Timestamp | None = None) -> list[str]:
    """Bugün hangi hisselerin tabloları okunacak: takip listesi önce, sonra hiç bakılmamışlar, sonra en eski kontrol."""
    today = today or pd.Timestamp.today().normalize()
    watch = [h["kod"] for h in cfg["hisseler"]]
    pool = list(dict.fromkeys(watch + (list(universe_df["kod"]) if cfg.get("evren") == "tum" and universe_df is not None else [])))
    track = json.loads((p.data / "kontrol.json").read_text()) if (p.data / "kontrol.json").exists() else {}
    stored = _latest_stored(p.kap)
    due = []
    for t in pool:
        last = pd.Timestamp(track[t]["son_kontrol"]) if t in track else None
        if track.get(t, {}).get("durum") == "desteklenmiyor" and last is not None and (today - last).days < 90:
            continue
        if needs_check(today, stored.get(t), last):
            due.append((0 if t in watch else 1, 0 if last is None else 1, last or pd.Timestamp(0), t))
    due.sort()
    limit = int(cfg.get("gunluk_limit", 150))
    return [t for *_, t in due[:limit]]


def step_tables(p: Paths, cfg: dict, st: Status, source=None, universe_df: pd.DataFrame | None = None,
                today: pd.Timestamp | None = None) -> None:
    """Takip listesindeki her hisse için finansal tabloları çeker; yalnızca YENİ dönemleri kaydeder."""
    if cfg.get("tablo_kaynagi", "ekofin") in (None, "yok"):
        st.skip("tablo", "Otomatik tablo kaynağı kapalı (config: tablo_kaynagi)")
        return
    today = today or pd.Timestamp.today().normalize()
    tickers = plan_tables(p, cfg, universe_df, today)
    if not tickers:
        st.ok("tablo", "Yeni rapor beklenen hisse yok (tüm kayıtlar güncel)")
        return
    from .data.sources import EkofinSource, UnsupportedFormat, store
    src = source or EkofinSource()
    track_path = p.data / "kontrol.json"
    track = json.loads(track_path.read_text()) if track_path.exists() else {}
    new, notes, failed, unsupported = 0, [], [], 0
    for t in tickers:
        rec = {"son_kontrol": str(today.date())}
        try:
            f = src.fetch(t)
            n = len(store(f, p.kap))
            new += n
            notes += f.warnings[:1]
            rec.update(durum="tamam", tur=f.kind, son_donem=max(f.periods) if f.periods else None, yeni=n)
        except UnsupportedFormat as e:
            unsupported += 1
            rec.update(durum="desteklenmiyor", neden=str(e))
        except Exception as e:  # noqa: BLE001
            failed.append(f"{t}: {e}")
            rec.update(durum="hata", neden=str(e)[:200])
        track[t] = rec
        p.data.mkdir(parents=True, exist_ok=True)
        track_path.write_text(json.dumps(track, ensure_ascii=False, indent=1), encoding="utf-8")
    detail = (f"{len(tickers)} hisse kontrol edildi, {new} yeni rapor kaydedildi"
              + (f", {unsupported} desteklenmiyor" if unsupported else "") + (f", {len(failed)} hata" if failed else ""))
    if notes:
        detail += "; " + "; ".join(notes[:5]) + (" …" if len(notes) > 5 else "")
    if failed and len(failed) == len(tickers):
        st.fail("tablo", "; ".join(failed[:5]))
    else:
        st.ok("tablo", detail)


def step_reports(p: Paths, cfg: dict, st: Status, universe_df: pd.DataFrame | None = None) -> list[dict]:
    """Takip listesindeki hisseler için not üretir. Sanayi: TMS 29 + reel İNA + Excel; banka/sigorta: finansal sektör notu.
    Hisse sayısı ayarda yoksa evrendeki piyasa değeri / kapanış fiyatından bulunur. Tüm evren için tarama ayrı adımdır."""
    made = []
    mq = p.data / "makro_ceyrek.csv"
    if not p.kap.exists() or not any(p.kap.iterdir()):
        st.skip("rapor", f"KAP dosyası yok: tabloları {p.kap.relative_to(p.root)}/HISSE_YYYY_A.xlsx olarak ekleyin")
        return made
    if not mq.exists():
        st.skip("rapor", "Makro veri yok (EVDS anahtarı gerekli)")
        return made
    cpi, fx = pipeline.load_macro_csv(mq)
    px = pd.read_csv(p.data / "fiyatlar.csv", index_col=0, parse_dates=True) if (p.data / "fiyatlar.csv").exists() else None
    shares = json.loads((p.data / "hisse_sayilari.json").read_text()) if (p.data / "hisse_sayilari.json").exists() else {}
    uni = universe_df.set_index("kod") if universe_df is not None and len(universe_df) else None
    watch = [h["kod"] for h in cfg.get("hisseler", [])]
    have = set(pipeline.discover(p.kap))
    tickers = [t for t in watch if t in have] if watch else sorted(have)
    p.out.mkdir(parents=True, exist_ok=True)
    errors = []
    for t in tickers:
        try:
            a = pipeline.analyze(t, pipeline.load_company(p.kap, t), cpi, fx)
            price = float(px[t].dropna().iloc[-1]) if px is not None and t in px and px[t].notna().any() else None
            sh = shares.get(t)
            if uni is not None and t in uni.index:
                u = uni.loc[t]
                price = price or (float(u["kapanis"]) if pd.notna(u.get("kapanis")) else None)
                if not sh and pd.notna(u.get("piyasa_degeri_mn_tl")) and price:
                    sh = float(u["piyasa_degeri_mn_tl"]) * 1e6 / float(u["kapanis"])
            name = str(uni.at[t, "ad"]) if uni is not None and t in uni.index and "ad" in uni else None
            if report.is_financial(a):
                mcap = price * float(sh) if (price and sh) else None
                (p.out / f"{t}.html").write_text(report.financial_note(a, mcap, name), encoding="utf-8")
                made.append({"hisse": t, "tur": "finansal", "son_ceyrek": str(a.last), "fiyat": price,
                             "ima_edilen_marj": float("nan"), "temel_net_marj": float(a.metrics.at["net_margin", a.last])})
                continue
            if not (sh and price):
                raise ValueError("fiyat veya hisse sayısı yok")
            inp = report.inputs_from_analysis(a, shares=float(sh))
            mcap = price * float(sh)
            if pd.isna(inp.net_debt):
                inp = report.val.DCFInputs(**{**inp.__dict__, "net_debt": 0.0})
            (p.out / f"{t}.html").write_text(report.html_note(a, inp, mcap), encoding="utf-8")
            report.excel_model(a, inp, mcap, p.out / f"{t}_model.xlsx")
            res = valuation.dcf(inp)
            made.append({"hisse": t, "tur": "sanayi", "son_ceyrek": str(a.last), "fiyat": price, "ina_deger": res["per_share"],
                         "ima_edilen_reel_buyume": valuation.implied_growth(mcap + inp.net_debt, inp),
                         "ima_edilen_marj": valuation.implied_margin(mcap + inp.net_debt, inp),
                         "temel_net_marj": float(a.metrics.at["core_net_margin", a.last])})
        except Exception as e:  # noqa: BLE001
            errors.append(f"{t}: {e}")
    if made:
        st.ok("rapor", f"{len(made)} şirket notu" + (f"; hatalar: {'; '.join(errors)}" if errors else ""))
    elif errors:
        st.fail("rapor", "; ".join(errors))
    else:
        st.skip("rapor", "Takip listesindeki hisselerin tablosu henüz yok")
    return made


def step_events(p: Paths, cfg: dict, st: Status) -> pd.DataFrame | None:
    if not cfg["olaylar"]:
        st.skip("olay", "config/takip.json içinde olay yok")
        return None
    px = _all_prices(p)
    if px.empty:
        st.skip("olay", "Fiyat verisi yok")
        return None
    try:
        r = returns(px)
        graph = kg.load_with_disclosures(p.data / "ag.json")[0] if (p.data / "ag.json").exists() else None
        rows = []
        for ev in cfg["olaylar"]:
            t = ev["hisse"]
            targets, expected = [t], {}
            if graph is not None and t in graph.g and ev.get("sok", 0):
                imps = graph.propagate(t, ev["sok"])[:5]
                targets += [i.ticker for i in imps]
                expected = {i.ticker: i.score for i in imps}
            targets = [x for x in dict.fromkeys(targets) if x in r.columns]
            if not targets or "XU100" not in r.columns:
                continue
            es = kg.event_study(r[targets].dropna(how="all").fillna(0), r["XU100"].fillna(0), ev["tarih"], targets)
            for tk, row in es.iterrows():
                exp = ev.get("sok", float("nan")) if tk == t else expected.get(tk, float("nan"))
                rows.append({"olay": ev.get("baslik", ""), "tarih": ev["tarih"], "hisse": tk,
                             "rol": "olay şirketi" if tk == t else "ağın öngördüğü", "beklenen": exp,
                             "CAR": row["CAR"], "t": row["t_istatistigi"], "kaynak": ev.get("kaynak", "")})
        df = pd.DataFrame(rows)
        if not df.empty:
            df.to_csv(p.data / "olay_calismasi.csv", index=False)
        msg = f"{len(cfg['olaylar'])} olay, {len(df)} hisse-olay gözlemi"
        if not df.empty:
            own = df[(df["rol"] == "olay şirketi") & (df["beklenen"].fillna(0) != 0)]
            if len(own):
                hit = (np.sign(own["CAR"]) == np.sign(own["beklenen"])).mean()
                msg += f"; olay şirketinde yön isabeti %{hit*100:.0f}, |t|>2: {(own['t'].abs() > 2).sum()}/{len(own)}"
        st.ok("olay", msg)
        return df
    except Exception as e:  # noqa: BLE001
        st.fail("olay", e)
        return None


def _png(fig) -> str:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def build_status_page(p: Paths, st: Status, reports: list[dict], events: pd.DataFrame | None,
                      screen: pd.DataFrame | None = None) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    e = html.escape
    p.out.mkdir(parents=True, exist_ok=True)
    blocks = []
    cpi = _read_csv_series(p.data / "tufe_aylik.csv") if (p.data / "tufe_aylik.csv").exists() else None
    if cpi is not None and len(cpi) > 13:
        yoy = (cpi / cpi.shift(12) - 1).dropna() * 100
        fig, ax = plt.subplots(figsize=(6.4, 2.6))
        ax.plot(yoy.index, yoy.values, color="#1f5fbf")
        ax.set_title(f"Yıllık TÜFE (%) · son: %{yoy.iloc[-1]:.1f}".replace(".", ","), loc="left", fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)
        blocks.append(f"<h2>Makro</h2><p>Yıllık TÜFE: <b>%{yoy.iloc[-1]:.1f}</b> ({yoy.index[-1]:%m/%Y})".replace(".", ",", 1)
                      + f"</p><img src='{_png(fig)}' alt='Enflasyon'>")
    if (p.data / "fiyatlar.csv").exists():
        px = pd.read_csv(p.data / "fiyatlar.csv", index_col=0, parse_dates=True)
        sm = summary(px, cpi)
        cols = [c for c in ["son_fiyat", "getiri_1a", "getiri_3a", "getiri_1y", "reel_getiri_1y"] if c in sm]
        head = "".join(f"<th>{e(c.replace('_', ' '))}</th>" for c in cols)
        body = "".join("<tr><td>" + e(t) + "</td>" + "".join(
            f"<td>{v:,.2f}</td>" if c == "son_fiyat" else f"<td>{v*100:+.1f}%</td>" for c, v in row[cols].items()) + "</tr>"
            for t, row in sm.iterrows())
        blocks.append(f"<h2>Piyasa</h2><table><tr><th>Hisse</th>{head}</tr>{body}</table>"
                      "<p class='m'>Reel getiri, aynı dönemin TÜFE'siyle arındırılmıştır.</p>")
    if reports:
        f2 = lambda v, fmt: "–" if v is None or pd.isna(v) else format(v, fmt)  # noqa: E731
        body = "".join(f"<tr><td><a href='{e(r['hisse'])}.html'>{e(r['hisse'])}</a></td><td>{e(r['son_ceyrek'])}</td>"
                       f"<td>{f2(r.get('fiyat'), ',.2f')}</td><td>{f2(r.get('ima_edilen_marj'), '.1%')}</td>"
                       f"<td>{f2(r.get('temel_net_marj'), '.1%')}</td><td>"
                       + ("finansal sektör notu" if r.get("tur") == "finansal" else f"<a href='{e(r['hisse'])}_model.xlsx'>Excel</a>")
                       + "</td></tr>" for r in reports)
        blocks.append("<h2>Takip listesi notları</h2><table><tr><th>Hisse</th><th>Son çeyrek</th><th>Fiyat</th>"
                      f"<th>Fiyatlanan kalıcı faaliyet marjı</th><th>Temel net marj</th><th></th></tr>{body}</table>"
                      "<p class='m'>Sanayi şirketleri: TMS 29 düzeltmeli reel İNA. Banka ve sigorta: nominal tablolar, PD/DD, F/K, özkaynak kârlılığı.</p>")
    if screen is not None and not screen.empty:
        pct = lambda v: "–" if v is None or pd.isna(v) else f"{float(v)*100:.1f}%"  # noqa: E731
        screen = screen.sort_values("duz_fark_hatasi_hasilat", ascending=False, na_position="last") if "duz_fark_hatasi_hasilat" in screen else screen
        body = "".join(
            f"<tr><td>{e(t)}</td><td>{e(str(r.get('son_ceyrek', '–')))}</td><td>{pct(r.get('duz_fark_hatasi_net_kar'))}</td>"
            f"<td>{pct(r.get('duz_fark_hatasi_hasilat'))}</td><td>{pct(r.get('parasal_kazanc_net_kar_ytd'))}</td>"
            f"<td>{pct(r.get('raporlanan_net_marj'))}</td><td>{pct(r.get('temel_net_marj'))}</td><td class='l'>{e(str(r.get('not', '') or ''))}</td></tr>"
            for t, r in screen.head(25).iterrows())
        blocks.append(f"<h2>TMS 29 taraması ({len(screen)} şirket; ilk 25, <a href='tarama.html'>tümü</a>)</h2><table><tr><th>Hisse</th><th>Son çeyrek</th>"
                      "<th>Düz fark hatası: net kâr</th><th>Düz fark hatası: hasılat</th><th>Parasal kazanç / net kâr (YB)</th>"
                      f"<th>Net marj</th><th>Temel net marj</th><th class='l'>Not</th></tr>{body}</table>"
                      "<p class='m'>Düz fark hatası: 9A−6A gibi kümülatif rakamları TÜFE düzeltmesi yapmadan çıkarmanın son çeyrekteki sapması.</p>")
    if events is not None and not events.empty:
        def _src(u):
            return f"<a href='{e(u)}'>kaynak</a>" if isinstance(u, str) and u.startswith("http") else ""

        def _dir(exp, car):
            if pd.isna(exp) or exp == 0:
                return "–"
            return "✓" if np.sign(exp) == np.sign(car) else "✗"
        ev_sorted = events.sort_values(["tarih", "rol"], ascending=[False, False])
        body = "".join(f"<tr><td class='l'>{e(str(r.olay))} {_src(getattr(r, 'kaynak', ''))}</td><td>{e(str(r.tarih))}</td><td>{e(r.hisse)}</td>"
                       f"<td>{e(r.rol)}</td><td>{'–' if pd.isna(getattr(r, 'beklenen', float('nan'))) else format(r.beklenen, '+.2f')}</td>"
                       f"<td>{r.CAR*100:+.2f}%</td><td>{r.t:+.2f}</td><td>{_dir(getattr(r, 'beklenen', float('nan')), r.CAR)}</td></tr>"
                       for r in ev_sorted.itertuples())
        blocks.append("<h2>Olay çalışması: KAP açıklamaları ve gerçek fiyat tepkisi</h2><table><tr><th class='l'>Olay</th><th>0. gün</th><th>Hisse</th>"
                      f"<th>Rol</th><th>Beklenen</th><th>CAR [-1,+3]</th><th>t</th><th>Yön</th></tr>{body}</table>"
                      "<p class='m'>CAR: piyasa modeline (BIST 100) göre kümülatif anormal getiri, [-1,+3] işlem günü. |t| &gt; 2 kabaca %5 düzeyinde anlamlı. "
                      "Beklenen: olay şirketinde analist varsayımı (−1..+1), bağlantılı şirketlerde ilişki ağının öngördüğü etki. "
                      "18:10'dan sonraki açıklamalarda 0. gün ertesi işlem günüdür.</p>")
    rf = p.out / "risk" / "risk_ozet.csv"
    if rf.exists():
        rt = pd.read_csv(rf, index_col=0)
        top = lambda col, asc: ", ".join(f"{t} {v*100:.0f}%" for t, v in rt[col].dropna().sort_values(ascending=asc).head(5).items())  # noqa: E731
        blocks.append(f"<h2>Risk ve korelasyon ({len(rt)} hisse, <a href='risk/index.html'>tümü ve matrisler</a>)</h2>"
                      f"<p>Medyan yıllık oynaklık %{rt['oynaklik_yillik'].median()*100:.0f} · medyan beta {rt['beta'].median():.2f}"
                      + (f" · ortalama korelasyon {rt['ort_korelasyon'].median():.2f}" if "ort_korelasyon" in rt else "") + "</p>"
                      + (f"<p class='m'>Son 1 yılda en yüksek reel getiri: {e(top('reel_getiri_yillik', False))}<br>"
                         f"En düşük reel getiri: {e(top('reel_getiri_yillik', True))}</p>" if "reel_getiri_yillik" in rt else "")
                      + "<p class='m'>Korelasyon ve kovaryans matrisleri (örnek ve Ledoit–Wolf), sektör korelasyonu ve takip listesi ısı haritası risk sayfasındadır.</p>")
    icon = {"tamam": "✓", "hata": "✗", "atlandı": "–"}
    srows = "".join(f"<tr><td>{e(k)}</td><td>{icon[v['durum']]} {e(v['durum'])}</td><td class='l'>{e(v['detay'])}</td></tr>"
                    for k, v in st.steps.items())
    page = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KAPSAM · Gerçek veri durumu</title><style>
body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#1d2433}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0}}th,td{{border-bottom:1px solid #eef1f5;padding:5px 8px;text-align:right}}
th:first-child,td:first-child,.l{{text-align:left}}h2{{font-size:15px;margin-top:24px}}.m{{color:#6b7385;font-size:12px}}img{{max-width:640px;width:100%}}
td.l{{overflow-wrap:anywhere}}@media(max-width:700px){{table{{display:block;overflow-x:auto}}td.l{{min-width:220px}}}}
</style></head><body><h1>KAPSAM · Gerçek veri</h1><p class="m">Son güncelleme: {e(st.started)} (UTC). Her iş günü otomatik yenilenir.</p>
<h2>Kaynak durumu</h2><table><tr><th>Adım</th><th>Durum</th><th class='l'>Ayrıntı</th></tr>{srows}</table>
{''.join(blocks)}
<p class="m">Kaynaklar: TCMB EVDS, Yahoo Finance (gecikmeli), KAP. Yatırım tavsiyesi değildir.</p></body></html>"""
    out = p.out / "index.html"
    out.write_text(page, encoding="utf-8")
    (p.out / "durum.json").write_text(json.dumps({"guncelleme": st.started, "adimlar": st.steps}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    return out


def step_screen(p: Paths, st: Status, universe_df: pd.DataFrame | None = None,
                risk_tab: pd.DataFrame | None = None) -> pd.DataFrame | None:
    mq = p.data / "makro_ceyrek.csv"
    if not mq.exists() or not p.kap.exists() or not pipeline.discover(p.kap):
        return None
    cpi, fx = pipeline.load_macro_csv(mq)
    px = pd.read_csv(p.data / "fiyatlar.csv", index_col=0, parse_dates=True) if (p.data / "fiyatlar.csv").exists() else None
    prices = {t: float(px[t].dropna().iloc[-1]) for t in (px.columns if px is not None else []) if px[t].notna().any()}
    shares = json.loads((p.data / "hisse_sayilari.json").read_text()) if (p.data / "hisse_sayilari.json").exists() else {}
    from .data.universe import market_caps
    caps = market_caps(universe_df) if universe_df is not None else {}
    sc = pipeline.screen(p.kap, cpi, fx, prices, shares, market_caps=caps, meta=universe_df)
    if risk_tab is not None and len(risk_tab):
        rc = [c for c in ["reel_getiri_yillik", "oynaklik_yillik", "beta", "max_dusus"] if c in risk_tab]
        sc = sc.join(risk_tab[rc].astype(float), how="left")
    p.out.mkdir(parents=True, exist_ok=True)
    sc.to_csv(p.out / "tarama.csv")
    (p.out / "tarama.html").write_text(screen_page(sc, st.started), encoding="utf-8")
    ok = sc["not"].astype(str).str.startswith("hata").sum() if "not" in sc else 0
    st.ok("tarama", f"{len(sc)} şirket tarandı" + (f", {ok} şirkette hata" if ok else ""))
    return sc


def screen_page(sc: pd.DataFrame, stamp: str) -> str:
    """Tüm şirketler için sıralanabilir, aranabilir tarama sayfası (tek dosya, dış bağımlılık yok)."""
    e = html.escape
    cols = [("ad", "Şirket", "t"), ("sektor", "Sektör", "t"), ("tur", "Tür", "t"), ("son_ceyrek", "Son çeyrek", "t"),
            ("duz_fark_hatasi_hasilat", "Düz fark hatası: hasılat", "p"), ("duz_fark_hatasi_net_kar", "Düz fark hatası: net kâr", "p"),
            ("parasal_kazanc_net_kar_ytd", "Parasal kazanç / net kâr (YB)", "p"), ("raporlanan_net_marj", "Net marj", "p"),
            ("temel_net_marj", "Temel net marj", "p"), ("reel_hasilat_yillik", "Reel büyüme (yıllık)", "p"),
            ("ozkaynak_karliligi_yillik", "ÖK kârlılığı (yıllık)", "p"), ("fk_ttm", "F/K", "x"), ("pd_dd", "PD/DD", "x"),
            ("fiyatlanan_faaliyet_marji", "Fiyatlanan faaliyet marjı", "p"), ("reel_getiri_yillik", "Reel getiri 1Y", "p"),
            ("oynaklik_yillik", "Oynaklık", "p"), ("beta", "Beta", "x"), ("max_dusus", "Max düşüş", "p"), ("not", "Not", "t")]
    cols = [c for c in cols if c[0] in sc.columns]

    def cell(v, kind):
        if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
            return "<td data-v=''>–</td>"
        if kind == "p":
            return f"<td data-v='{float(v):.6f}'>{float(v)*100:.1f}%</td>"
        if kind == "x":
            return f"<td data-v='{float(v):.6f}'>{float(v):.1f}x</td>"
        return f"<td data-v='{e(str(v))}' class='l'>{e(str(v))}</td>"
    head = "<th>Kod</th>" + "".join(f"<th>{e(lab)}</th>" for _, lab, _ in cols)
    body = "".join(f"<tr><td class='l'><b>{e(str(t))}</b></td>" + "".join(cell(r.get(c), k) for c, _, k in cols) + "</tr>"
                   for t, r in sc.iterrows())
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KAPSAM · BIST taraması</title><style>
body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:16px;color:#1d2433}}
input{{font-size:14px;padding:6px 10px;width:280px;max-width:100%}}.wrap{{overflow-x:auto}}
table{{border-collapse:collapse;font-size:12px;white-space:nowrap}}th{{position:sticky;top:0;background:#f5f7fb;cursor:pointer}}
th,td{{border-bottom:1px solid #eef1f5;padding:4px 8px;text-align:right}}.l{{text-align:left}}.m{{color:#6b7385;font-size:12px}}
</style></head><body><h1>KAPSAM · BIST taraması</h1>
<p class="m">{len(sc)} şirket · {e(stamp)} (UTC) · Sütun başlığına tıklayarak sıralayın. Banka ve sigorta şirketleri TMS 29 uygulamaz; nominal modda gösterilir. Yatırım tavsiyesi değildir.</p>
<input id="q" placeholder="Kod, şirket veya sektör ara" oninput="f()">
<div class="wrap"><table id="t"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>
<script>
function f(){{const q=document.getElementById('q').value.toLocaleLowerCase('tr');for(const r of document.querySelectorAll('#t tbody tr'))r.style.display=r.innerText.toLocaleLowerCase('tr').includes(q)?'':'none'}}
document.querySelectorAll('#t th').forEach((th,i)=>th.onclick=()=>{{const tb=document.querySelector('#t tbody');const rs=[...tb.rows];const d=th.dataset.d=th.dataset.d==='1'?'0':'1';
rs.sort((a,b)=>{{const x=a.cells[i].dataset.v??a.cells[i].innerText,y=b.cells[i].dataset.v??b.cells[i].innerText;const nx=parseFloat(x),ny=parseFloat(y);
const c=(isNaN(nx)||isNaN(ny))?String(x).localeCompare(String(y),'tr'):nx-ny;return d==='1'?-c:c}});rs.forEach(r=>tb.appendChild(r))}});
</script></body></html>"""


def run(root: Path = ROOT, evds_client=None, market: Market | None = None, source=None,
        universe_getter=None, today: pd.Timestamp | None = None) -> Status:
    p = Paths(root)
    st = Status()
    try:
        cfg = load_config(p)
    except Exception as e:  # noqa: BLE001
        st.fail("ayar", e)
        build_status_page(p, st, [], None)
        return st
    step_macro(p, cfg, st, evds_client)
    uni = step_universe(p, cfg, st, universe_getter) if (cfg.get("evren") == "tum" or universe_getter) else None
    step_prices(p, cfg, st, market, uni)
    step_tables(p, cfg, st, source, uni, today)
    reports = []
    try:
        reports = step_reports(p, cfg, st, uni)
    except Exception:  # noqa: BLE001
        st.fail("rapor", traceback.format_exc(limit=1))
    events = step_events(p, cfg, st)
    rk = step_risk(p, cfg, st, uni, today)
    sc = None
    try:
        sc = step_screen(p, st, uni, rk)
    except Exception as e:  # noqa: BLE001
        st.fail("tarama", e)
    build_status_page(p, st, reports, events, sc)
    return st
