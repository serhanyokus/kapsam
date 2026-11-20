"""Çıktılar: tek dosyalık HTML araştırma notu ve formüllü Excel modeli."""
from __future__ import annotations

import base64
import html
import io
from dataclasses import asdict
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

from . import valuation as val  # noqa: E402
from .pipeline import Analysis  # noqa: E402

BLUE, ORANGE, GREY = "#1f5fbf", "#e07b00", "#8a94a6"


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _style(ax, title):
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    ax.tick_params(labelsize=8)


def charts(a: Analysis) -> dict[str, str]:
    x = [str(p) for p in a.real.columns]
    out = {}

    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    ax.plot(x, a.quarterly.loc["revenue"] / 1e6, color=GREY, marker="o", ms=3, label="Rapor TL'si (her çeyrek kendi tarihinde)")
    ax.plot(x, a.real.loc["revenue"] / 1e6, color=BLUE, marker="o", ms=3, lw=2, label=f"Reel ({a.base} TL'si)")
    _style(ax, "Çeyreklik hasılat (mn TL)")
    ax.legend(fontsize=7, frameon=False)
    out["revenue"] = _png(fig)

    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    ax.plot(x, a.metrics.loc["net_margin"] * 100, color=GREY, marker="o", ms=3, label="Raporlanan net marj")
    ax.plot(x, a.metrics.loc["core_net_margin"] * 100, color=BLUE, marker="o", ms=3, lw=2, label="Temel net marj (parasal etki hariç)")
    ax.plot(x, a.metrics.loc["gross_margin"] * 100, color=ORANGE, ls="--", lw=1.2, label="Brüt marj")
    _style(ax, "Marjlar (%)")
    ax.legend(fontsize=7, frameon=False)
    out["margins"] = _png(fig)

    if len(a.naive):
        fig, ax = plt.subplots(figsize=(6.4, 2.4))
        ax.bar([str(p) for p in a.naive.index], a.naive["error_pct"] * 100, color=ORANGE)
        _style(ax, "Düzeltmesiz çeyrek hesabının hasılat hatası (%)")
        out["naive"] = _png(fig)
    return out


def _pct(x, d=1):
    """Türkçe yüzde biçimi: %6,1"""
    if pd.isna(x):
        return "–"
    v = f"{abs(x)*100:.{d}f}".replace(".", ",")
    return ("-" if x < 0 else "") + "%" + v


CATEGORY_TR = {"finansal_rapor": "Finansal rapor", "yeni_is_iliskisi": "Yeni iş ilişkisi", "sermaye_artirimi": "Sermaye artırımı",
               "kar_payi": "Kâr payı", "pay_geri_alim": "Pay geri alımı", "birlesme_devralma": "Birleşme / devralma",
               "yatirim_kapasite": "Yatırım / kapasite", "borclanma_araci": "Borçlanma aracı", "dava_ceza": "Dava / ceza",
               "derecelendirme": "Derecelendirme", "yonetim_degisikligi": "Yönetim değişikliği", "diger": "Diğer"}
YON = {1: "Olumlu", 0: "Nötr", -1: "Olumsuz"}


def _num(x, d=0):
    return "–" if pd.isna(x) else f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def network_section(graph, ticker: str, events) -> dict:
    """Notun 'Bağlantılı şirketler' bölümü için veri: ilişkiler, benzer şirketler, maruz kalınan olaylar, ağ görseli."""
    from . import graph as kg
    rel = graph.relations()
    mine = rel[(rel["kaynak"] == ticker) | (rel["hedef"] == ticker)]
    mine = mine[mine["tür"] != "peer"]
    lines = []
    for _, r in mine.iterrows():
        other = r["hedef"] if r["kaynak"] == ticker else r["kaynak"]
        if r["tür"] == "owner":
            txt = f"{r['kaynak']}, {r['hedef']} şirketinin %{r['ağırlık']*100:.0f} ortağı"
        else:
            txt = f"{r['kaynak']}, {r['hedef']} şirketinin {kg.REL_TR[r['tür']]}"
        lines.append((other, txt, r["kanıt"]))
    exposures = []
    for e in events:
        if e.ticker == ticker:
            continue
        for i in graph.propagate(e.ticker, e.shock):
            if i.ticker == ticker:
                exposures.append((e.title, i.score, i.explanation))
    exposures.sort(key=lambda x: -abs(x[1]))
    fig, ax = plt.subplots(figsize=(7.5, 5.0))
    kg.draw(graph, focus=ticker, ax=ax)
    return {"relations": lines, "peers": graph.similar(ticker, 3), "exposures": exposures, "img": _png(fig)}


def html_note(a: Analysis, inp: val.DCFInputs, market_cap: float, thesis: dict | None = None,
              disclosures: list[dict] | None = None, synthetic: bool = False, network: dict | None = None) -> str:
    """Analistin yöneticisine gönderebileceği tek sayfalık (yazdırılabilir) araştırma notu."""
    m, p = a.metrics, a.last
    res = val.dcf(inp)
    ig = val.implied_growth(market_cap + inp.net_debt + inp.minority_and_other, inp)
    im = val.implied_margin(market_cap + inp.net_debt + inp.minority_and_other, inp)
    sens = val.sensitivity(inp, [inp.real_wacc - 0.01, inp.real_wacc, inp.real_wacc + 0.01],
                           [inp.growth_high - 0.02, inp.growth_high, inp.growth_high + 0.02])
    mult = val.multiples(a.real, market_cap, inp.net_debt)
    price = market_cap / inp.shares
    upside = res["per_share"] / price - 1
    ch = charts(a)
    passed = sum(c.passed for c in a.checks)
    q3 = [c for c in a.checks if c.name.startswith("3_aylık")]
    q3_txt = (f"; KAP'ın kendi 3 aylık rakamlarıyla çapraz kontrol: {sum(c.passed for c in q3)}/{len(q3)} uyumlu" if q3 else "")
    est, _why = estimate_sales_to_capital(a)
    s2c_src = "nakit akışından tahmin" if est is not None and abs(est - inp.sales_to_capital) < 1e-9 else "varsayım"
    e = html.escape

    sens_rows = "".join(  # noqa
        f"<tr><th>{_pct(w)}</th>" + "".join(f"<td>{_num(v, 2)}</td>" for v in sens.loc[w]) + "</tr>" for w in sens.index)
    sens_head = "".join(f"<th>{_pct(g)}</th>" for g in sens.columns)
    th_html = ""
    if thesis:
        items = "".join(f"<li>{'veri yok' if r['saglandi'] is None else ('✓' if r['saglandi'] else '✗')} {e(r['kural'])}"
                        f"{'' if pd.isna(r['deger']) else ' <span class=muted>(' + format(r['deger'], '.3f') + ')</span>'}</li>" for r in thesis["kurallar"])
        th_html = f"<h2>4. Yatırım tezi: {e(thesis['tez'])} → <span class='tag'>{e(thesis['durum'])}</span></h2><ul>{items}</ul>"
    disc_html = ""
    if disclosures:
        rows = "".join(f"<tr><td>{e(d['baslik'])}</td><td>{e(CATEGORY_TR.get(d['kategori'], d['kategori']))}</td><td>{YON[d['yon']]}</td><td>{d['onem']:.2f}</td></tr>" for d in disclosures)
        disc_html = f"<h2>Son KAP bildirimleri</h2><table><tr><th>Bildirim</th><th>Kategori</th><th>Yön</th><th>Önem</th></tr>{rows}</table>"
    banner = "<div class='warn'>SENTETİK DEMO VERİSİ: gerçek bir şirkete veya gerçek TÜFE'ye ait değildir.</div>" if synthetic else ""
    net_html = ""
    if network:
        rel_rows = "".join(f"<tr><td>{e(o)}</td><td class='l'>{e(t)}</td><td class='muted l'>{e(ev[:80])}</td></tr>" for o, t, ev in network["relations"])
        exp_rows = "".join(f"<tr><td>{e(title)}</td><td>{'+' if s_ > 0 else ''}{_num(s_, 3)}</td><td class='muted l'>{e(x)}</td></tr>"
                           for title, s_, x in network["exposures"][:6]) or "<tr><td colspan=3>Son olaylardan dolaylı etki yok.</td></tr>"
        peers = ", ".join(f"{e(t)} ({_num(v, 2)})" for t, v in network["peers"].items())
        net_html = f"""<h2>3. Bağlantılı şirketler (bilgi grafiği)</h2>
<div class="grid2"><img src="{network['img']}" alt="İlişki ağı"><div>
<table><tr><th>Şirket</th><th class='l'>İlişki</th><th class='l'>Kanıt</th></tr>{rel_rows}</table>
<p class="muted">Rol olarak en benzer şirketler: {peers}</p></div></div>
<table><tr><th>Başka şirketteki olay</th><th>Bu şirkete etkisi</th><th class='l'>Yol</th></tr>{exp_rows}</table>
<p class="muted">Etki = olay şoku × ilişki katsayıları × mesafe azalması. Her sonuç, hangi ilişki zinciriyle geldiğini gösterir.</p>"""
    mult_rows = "".join(f"<tr><td>{k}</td><td>{_num(v, 1)}x</td></tr>" for k, v in mult.items())

    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(a.ticker)} · KAPSAM araştırma notu</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1d2433;max-width:860px;margin:24px auto;padding:0 16px;line-height:1.45}}
h1{{margin:0;font-size:24px}} h2{{font-size:15px;margin:22px 0 8px;border-bottom:1px solid #e3e7ee;padding-bottom:4px}}
.muted{{color:#6b7385;font-size:12px}} .warn{{background:#fff4e0;border:1px solid #f0c27a;padding:8px 12px;border-radius:6px;margin:12px 0;font-size:13px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}} .kpi{{background:#f5f7fb;border-radius:8px;padding:10px}}
.kpi b{{display:block;font-size:20px}} .kpi span{{font-size:11px;color:#6b7385}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid #eef1f5;padding:5px 8px;text-align:right}}
th:first-child,td:first-child,.l{{text-align:left}} img{{width:100%;margin:6px 0}} img.narrow{{max-width:520px;display:block}} .tag{{background:#e8f0ff;color:{BLUE};padding:1px 8px;border-radius:10px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} @media(max-width:640px){{.kpis{{grid-template-columns:repeat(2,1fr)}}.grid2{{grid-template-columns:1fr}}}}
@media print{{body{{margin:0}} h2{{break-after:avoid}} img{{break-inside:avoid}}}}
</style></head><body>
<div class="muted">KAPSAM araştırma notu · {date.today():%d.%m.%Y} · Son veri: {p} · Tutarlar {a.base} TL'si (reel)</div>
<h1>{e(a.ticker)}: Enflasyondan arındırılmış görünüm ve değerleme</h1>
{banner}
<div class="kpis">
<div class="kpi"><span>Reel hasılat büyümesi (yıllık)</span><b>{_pct(m.at['revenue_real_yoy', p])}</b></div>
<div class="kpi"><span>Temel net marj / raporlanan</span><b>{_pct(m.at['core_net_margin', p])}</b><span>raporlanan {_pct(m.at['net_margin', p])}</span></div>
<div class="kpi"><span>İNA hisse başı değer</span><b>{_num(res['per_share'], 2)}</b><span>fiyat {_num(price, 2)} · potansiyel {_pct(upside)}</span></div>
<div class="kpi"><span>Piyasanın fiyatladığı {'reel büyüme' if pd.notna(ig) else 'kalıcı faaliyet marjı'}</span><b>{_pct(ig) if pd.notna(ig) else _pct(im)}</b><span>{'bizim varsayım ' + _pct(inp.growth_high) if pd.notna(ig) else 'son 12 ay ' + _pct(inp.margin0 if inp.margin0 is not None else inp.ebit_margin)}</span></div>
</div>
<h2>1. Neden düzeltme gerekli?</h2>
<p>Raporlanan rakamlar her çeyrekte farklı bir TL ile ifade edilir. Aşağıda gri çizgi şirketin raporladığı çeyreklik hasılatı, mavi çizgi ise aynı satın alma gücüne taşınmış reel hasılatı gösterir.
Parasal kazanç/kayıp, son çeyrekte net kârın <b>{_pct(m.at['monetary_gain_share', p])}</b> kadarını oluşturuyor.</p>
<div class="grid2"><img src="{ch['revenue']}" alt="Hasılat"><img src="{ch['margins']}" alt="Marjlar"></div>
{'<img class="narrow" src="'+ch['naive']+'" alt="Düzeltmesiz yöntem hatası">' if 'naive' in ch else ''}
<h2>2. Değerleme (reel İNA)</h2>
{'<div class="warn">Model değeri piyasa fiyatından çok uzak (' + _pct(upside) + '). Bu genellikle bir girdinin şirketin ekonomisini yansıtmadığını gösterir: TMS 29 sonrası faaliyet marjı yeniden değerlenmiş amortismanla düşük görünebilir; negatif işletme sermayesinden gelen parasal kazanç ekonomik bir getiri olabilir ama faaliyet kârında yoktur. Bu durumda ters İNA (piyasanın fiyatladığı marj veya büyüme) daha anlamlı bir başlangıçtır. Yatırım görüşü değildir.</div>' if abs(upside) > 0.5 else ''}
<div class="grid2"><div><table>
<tr><td>Son 12 ay reel hasılat</td><td>{_num(inp.revenue0/1e6)} mn</td></tr>
<tr><td>Reel büyüme (ilk {inp.high_years} yıl → sürekli)</td><td>{_pct(inp.growth_high)} → {_pct(inp.growth_terminal)}</td></tr>
<tr><td>Hedef faaliyet marjı</td><td>{_pct(inp.ebit_margin)}</td></tr>
<tr><td>Reel AOSM</td><td>{_pct(inp.real_wacc)}</td></tr>
<tr><td>Satış / yatırılan sermaye <span class="muted">({e(s2c_src)})</span></td><td>{_num(inp.sales_to_capital, 1)}</td></tr>
<tr><td>Firma değeri</td><td>{_num(res['ev']/1e6)} mn</td></tr>
<tr><td>Net borç</td><td>{_num(inp.net_debt/1e6)} mn</td></tr>
<tr><td><b>Özkaynak değeri</b></td><td><b>{_num(res['equity']/1e6)} mn</b></td></tr>
<tr><td>Sürekli değerin payı</td><td>{_pct(res['tv_share'])}</td></tr>
</table></div><div>
<table><tr><th>Hisse başı değer</th>{sens_head}</tr>{sens_rows}</table>
<p class="muted">Satırlar reel AOSM, sütunlar ilk dönem reel büyüme.</p>
<table><tr><th>Çarpan (son 12 ay, reel)</th><th></th></tr>{mult_rows}</table></div></div>
{net_html}
{th_html}
{disc_html}
<h2>Veri kalitesi ve yöntem</h2>
<p class="muted">{len(a.reports)} KAP raporu işlendi. Sayısal kontroller: {passed}/{len(a.checks)} geçti{q3_txt}. Çeyreklik akışlar, önceki kümülatif rakam TÜFE ile cari rapor tarihine taşınarak ayrıştırılmıştır.
Reel seriler {a.base} TL'sidir. USD çevrimi TMS 21 par. 42'ye göre rapor tarihi kuruyla yapılmıştır. İNA reel nakit akışları ve Fisher denklemiyle bulunan reel AOSM ile hesaplanır.
Bu not bir araştırma aracının çıktısıdır; yatırım tavsiyesi değildir.</p>
</body></html>"""


def excel_model(a: Analysis, inp: val.DCFInputs, market_cap: float, path: str | Path) -> Path:
    """Analistin üzerinde çalışabileceği, formülleri canlı Excel modeli."""
    wb = Workbook()
    hdr = PatternFill("solid", fgColor="1F5FBF")
    inp_fill = PatternFill("solid", fgColor="FFF4D6")
    bold_w = Font(bold=True, color="FFFFFF")

    # 1) Normalize seriler
    ws = wb.active
    ws.title = "Normalize"
    labels = {"revenue": "Hasılat", "gross_profit": "Brüt kâr", "operating_profit": "Esas faaliyet kârı",
              "net_monetary_gain": "Net parasal pozisyon kazancı", "net_income": "Net kâr"}
    ws["A1"] = f"{a.ticker}: reel çeyreklik seriler ({a.base} TL'si)"
    ws["A1"].font = Font(bold=True, size=12)
    ws.cell(3, 1, "Kalem").font = bold_w
    ws.cell(3, 1).fill = hdr
    for j, p in enumerate(a.real.columns, 2):
        c = ws.cell(3, j, str(p))
        c.font, c.fill = bold_w, hdr
    for i, (k, lab) in enumerate(labels.items(), 4):
        ws.cell(i, 1, lab)
        for j, p in enumerate(a.real.columns, 2):
            v = a.real.at[k, p] if k in a.real.index else None
            ws.cell(i, j, None if pd.isna(v) else float(v)).number_format = "#,##0"
    r = 4 + len(labels)
    ws.cell(r, 1, "Temel net kâr (formül)")
    for j in range(2, 2 + len(a.real.columns)):
        col = get_column_letter(j)
        ws.cell(r, j, f"={col}8-{col}7").number_format = "#,##0"
    ws.cell(r + 1, 1, "Brüt marj (formül)")
    for j in range(2, 2 + len(a.real.columns)):
        col = get_column_letter(j)
        ws.cell(r + 1, j, f"=IFERROR({col}5/{col}4,\"\")").number_format = "0.0%"
    ws.column_dimensions["A"].width = 32

    # 2) İNA
    d = wb.create_sheet("INA")
    d["A1"] = "Reel İNA (sarı hücreler girdi; diğerleri formül)"
    d["A1"].font = Font(bold=True, size=12)
    fields = [("Son 12 ay reel hasılat", inp.revenue0, "#,##0"), ("Reel büyüme (yüksek dönem)", inp.growth_high, "0.0%"),
              ("Sürekli reel büyüme", inp.growth_terminal, "0.0%"), ("Yüksek büyüme yılı", inp.high_years, "0"),
              ("Geçiş yılı", inp.fade_years, "0"), ("Başlangıç faaliyet marjı", inp.margin0 if inp.margin0 is not None else inp.ebit_margin, "0.0%"),
              ("Hedef faaliyet marjı", inp.ebit_margin, "0.0%"), ("Vergi oranı", inp.tax_rate, "0.0%"),
              ("Satış / yatırılan sermaye", inp.sales_to_capital, "0.00"), ("Reel AOSM", inp.real_wacc, "0.0%"),
              ("Net borç", inp.net_debt, "#,##0"), ("Hisse sayısı", inp.shares, "#,##0"),
              ("Azınlık payları ve diğer", inp.minority_and_other, "#,##0"), ("Piyasa değeri", market_cap, "#,##0")]
    for i, (lab, v, fmt) in enumerate(fields, 3):
        d.cell(i, 1, lab)
        c = d.cell(i, 2, float(v))
        c.number_format, c.fill = fmt, inp_fill
    # B3 hasılat, B4 g_h, B5 g_t, B6 yüksek yıl, B7 geçiş, B8 m0, B9 m, B10 vergi, B11 s2c, B12 aosm, B13 net borç, B14 hisse, B15 azınlık, B16 piyasa değeri
    heads = ["Yıl", "Reel büyüme", "Hasılat", "Faaliyet marjı", "FVÖK", "NOPAT", "Yeniden yatırım", "FCFF", "İskonto faktörü", "BD(FCFF)"]
    top = 19
    for j, h in enumerate(heads, 1):
        c = d.cell(top, j, h)
        c.font, c.fill = bold_w, hdr
        c.alignment = Alignment(wrap_text=True)
    n = inp.high_years + inp.fade_years
    for t in range(1, n + 1):
        r = top + t
        prev_rev = "$B$3" if t == 1 else f"C{r-1}"
        d.cell(r, 1, t)
        d.cell(r, 2, f"=IF(A{r}<=$B$6,$B$4,$B$4+($B$5-$B$4)*(A{r}-$B$6)/$B$7)").number_format = "0.0%"
        d.cell(r, 3, f"={prev_rev}*(1+B{r})").number_format = "#,##0"
        d.cell(r, 4, f"=$B$8+($B$9-$B$8)*A{r}/($B$6+$B$7)").number_format = "0.0%"
        d.cell(r, 5, f"=C{r}*D{r}").number_format = "#,##0"
        d.cell(r, 6, f"=E{r}*(1-$B$10)").number_format = "#,##0"
        d.cell(r, 7, f"=(C{r}-{prev_rev})/$B$11").number_format = "#,##0"
        d.cell(r, 8, f"=F{r}-G{r}").number_format = "#,##0"
        d.cell(r, 9, f"=1/(1+$B$12)^A{r}").number_format = "0.0000"
        d.cell(r, 10, f"=H{r}*I{r}").number_format = "#,##0"
    last = top + n
    s = last + 2
    out_rows = [("Sürekli değer", f"=F{last}*(1+$B$5)*(1-IF($B$5>0,$B$5/$B$12,0))/($B$12-$B$5)", "#,##0"),
                ("BD(sürekli değer)", f"=B{s}*I{last}", "#,##0"),
                ("Firma değeri", f"=SUM(J{top+1}:J{last})+B{s+1}", "#,##0"),
                ("Özkaynak değeri", f"=B{s+2}-$B$13-$B$15", "#,##0"),
                ("Hisse başı değer", f"=B{s+3}/$B$14", "#,##0.00"),
                ("Piyasa fiyatı", "=$B$16/$B$14", "#,##0.00"),
                ("Potansiyel", f"=B{s+4}/B{s+5}-1", "0.0%")]
    for i, (lab, f, fmt) in enumerate(out_rows):
        d.cell(s + i, 1, lab).font = Font(bold=True)
        d.cell(s + i, 2, f).number_format = fmt
    d.column_dimensions["A"].width = 30
    for j in range(2, 11):
        d.column_dimensions[get_column_letter(j)].width = 15

    # 3) Notlar
    nt = wb.create_sheet("Yöntem")
    for i, line in enumerate([
        "KAPSAM tarafından üretildi. Tutarlar baz tarih TL'si (reel).",
        "Çeyreklik akış: Q_R = YTD_R - YTD_(R-1) x TÜFE_R / TÜFE_(R-1)",
        "Reel AOSM = (1 + nominal AOSM) / (1 + beklenen enflasyon) - 1",
        "Yeniden yatırım = hasılat artışı / (satış / yatırılan sermaye)",
        "Sürekli dönemde yeniden yatırım oranı = g / AOSM (getiri = sermaye maliyeti varsayımı)",
        "Yatırım tavsiyesi değildir.",
    ], 1):
        nt.cell(i, 1, line)
    nt.column_dimensions["A"].width = 90
    path = Path(path)
    wb.save(path)
    return path


def estimate_sales_to_capital(a: Analysis, lo: float = 0.5, hi: float = 5.0) -> tuple[float | None, str]:
    """Son 12 ay reel net yatırım (|capex| − amortisman) ile reel hasılat artışından satış/sermaye oranı.

    Veri yoksa ya da net yatırım ≤ 0 ise None döner (varsayılan kullanılır). Sonuç [lo, hi] aralığına sınırlanır.
    """
    r = a.real
    if not {"capex", "depreciation", "revenue"} <= set(r.index) or r.shape[1] < 8:
        return None, "nakit akış verisi yetersiz"
    try:
        net_inv = val.ttm(r.loc["capex"].abs()) - val.ttm(r.loc["depreciation"])
        d_rev = val.ttm(r.loc["revenue"]) - float(r.loc["revenue"].iloc[-8:-4].sum())
    except ValueError:
        return None, "nakit akış verisi yetersiz"
    if net_inv <= 0 or d_rev <= 0:
        return None, "net yatırım veya büyüme negatif"
    s2c = float(np.clip(d_rev / net_inv, lo, hi))
    return s2c, f"son 12 ay: Δhasılat {d_rev/1e6:,.0f} mn / net yatırım {net_inv/1e6:,.0f} mn"


def inputs_from_analysis(a: Analysis, **overrides) -> val.DCFInputs:
    """Analizden makul başlangıç girdileri üretir; analist her birini değiştirebilir."""
    rev0 = val.ttm(a.real.loc["revenue"])
    m0 = val.ttm(a.real.loc["operating_profit"]) / rev0
    p = a.last
    nd = a.metrics.loc["net_debt"].dropna()          # reel seri: son bilanço eksikse en son bilanço (baz TL'ye taşınmış)
    g = a.metrics.at["revenue_real_yoy", p]
    defaults = dict(revenue0=rev0, growth_high=max(0.0, float(g)) if pd.notna(g) else 0.0,
                    growth_terminal=0.02, margin0=m0, ebit_margin=m0, net_debt=float(nd.iloc[-1]) if len(nd) else 0.0)
    s2c, _ = estimate_sales_to_capital(a)
    if s2c is not None:
        defaults["sales_to_capital"] = s2c
    defaults.update(overrides)
    return val.DCFInputs(**defaults)


def inputs_dict(inp: val.DCFInputs) -> dict:
    return asdict(inp)


def is_financial(a: Analysis) -> bool:
    return "operating_profit" not in a.quarterly.index and (
        "net_interest_income" in a.quarterly.index or "gross_premiums" in a.quarterly.index)


def financial_note(a: Analysis, market_cap: float | None = None, name: str | None = None) -> str:
    """Banka ve sigorta şirketleri için not. Faaliyet kârı/serbest nakit akımı tanımı farklı olduğundan İNA yerine
    özkaynak çarpanları ve kârlılık/risk göstergeleri kullanılır. Tablolar TMS 29'a göre düzeltilmez (BDDK/SEDDK);
    çeyrekler nominal çıkarmayla ayrıştırılır, reel eğilim TÜFE ile baz tarihe taşınarak gösterilir."""
    q, m, p, e = a.quarterly, a.metrics, a.last, html.escape
    bank = "net_interest_income" in q.index
    row = lambda k: q.loc[k] if k in q.index else pd.Series(np.nan, index=q.columns)  # noqa: E731
    ni = row("net_income_parent") if row("net_income_parent").notna().any() else row("net_income")
    ttm = ni.iloc[-4:].sum() if ni.iloc[-4:].notna().all() and len(ni) >= 4 else np.nan
    eq = row("total_equity").get(p, np.nan)
    pb = market_cap / eq if market_cap and pd.notna(eq) and eq > 0 else np.nan
    pe = market_cap / ttm if market_cap and pd.notna(ttm) and ttm > 0 else np.nan
    roe = ttm / eq if pd.notna(ttm) and pd.notna(eq) and eq > 0 else m.at["roe_annualized", p] if "roe_annualized" in m.index else np.nan
    g = lambda k: m.at[k, p] if k in m.index else np.nan  # noqa: E731
    if bank:
        kpis = [("Faaliyet geliri reel büyüme (yıllık)", g("revenue_real_yoy")), ("Ücret/komisyon payı", g("fee_share")),
                ("Karşılık / net faiz geliri", g("provision_to_nii")), ("Kredi / mevduat", g("loan_to_deposit"))]
        lines = [("net_interest_income", "Net faiz geliri"), ("net_fee_income", "Net ücret ve komisyon"),
                 ("credit_provisions", "Beklenen zarar karşılıkları"), ("net_income", "Net kâr")]
    else:
        kpis = [("Brüt prim reel büyüme (yıllık)", g("revenue_real_yoy")), ("Saklama oranı", g("retention")),
                ("Net marj (kâr / brüt prim)", g("net_margin")), ("Yıllık ÖK kârlılığı (çeyrek)", g("roe_annualized"))]
        lines = [("gross_premiums", "Brüt yazılan primler"), ("net_premiums", "Net primler"),
                 ("technical_result", "Teknik bölüm dengesi"), ("net_income", "Net kâr")]
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    x = [str(c) for c in a.real.columns]
    for (k, lab), col in zip(lines, [BLUE, ORANGE, GREY, "#2e8b57"]):
        if k in a.real.index and a.real.loc[k].notna().any():
            ax.plot(x, a.real.loc[k] / 1e6, marker="o", ms=3, color=col, label=lab)
    _style(ax, f"Çeyreklik kalemler, reel ({a.base} TL'si, mn)")
    ax.legend(fontsize=7, frameon=False)
    img = _png(fig)
    tbl_rows = "".join(f"<tr><td>{lab}</td>" + "".join(f"<td>{_num(q.at[k, c] / 1e6)}</td>" for c in q.columns[-5:]) + "</tr>"
                       for k, lab in lines if k in q.index)
    tbl_head = "".join(f"<th>{c}</th>" for c in q.columns[-5:])
    kind = "Banka" if bank else "Sigorta"
    title = f"{e(a.ticker)}" + (f" · {e(name)}" if name else "")
    kpi_html = "".join(f"<div class='kpi'><span>{e(k)}</span><b>{_pct(v)}</b></div>" for k, v in kpis)
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(a.ticker)} · KAPSAM finansal sektör notu</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1d2433;max-width:860px;margin:24px auto;padding:0 16px;line-height:1.45}}
h1{{margin:0;font-size:24px}} h2{{font-size:15px;margin:22px 0 8px;border-bottom:1px solid #e3e7ee;padding-bottom:4px}}
.muted{{color:#6b7385;font-size:12px}} .kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}}
.kpi{{background:#f5f7fb;border-radius:8px;padding:10px}} .kpi b{{display:block;font-size:20px}} .kpi span{{font-size:11px;color:#6b7385}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid #eef1f5;padding:5px 8px;text-align:right}}
th:first-child,td:first-child{{text-align:left}} img{{width:100%;margin:6px 0}}
@media(max-width:640px){{.kpis{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body>
<div class="muted">KAPSAM finansal sektör notu · {date.today():%d.%m.%Y} · Son veri: {p} · {kind} tablo biçimi</div>
<h1>{title}</h1>
<div class="kpis">
<div class="kpi"><span>Piyasa değeri / özkaynak</span><b>{_num(pb, 2)}x</b></div>
<div class="kpi"><span>F/K (son 12 ay)</span><b>{_num(pe, 1)}x</b></div>
<div class="kpi"><span>Özkaynak kârlılığı (son 12 ay)</span><b>{_pct(roe)}</b></div>
<div class="kpi"><span>Özkaynak</span><b>{_num(eq / 1e9, 1)} mr</b></div>
</div>
<div class="kpis">{kpi_html}</div>
<h2>Çeyreklik görünüm</h2>
<img src="{img}" alt="Çeyreklik kalemler">
<table><tr><th>mn TL (nominal)</th>{tbl_head}</tr>{tbl_rows}</table>
<h2>Yöntem</h2>
<p class="muted">{kind} şirketleri BDDK/SEDDK düzenlemesi gereği TMS 29 enflasyon düzeltmesi uygulamaz; bu yüzden çeyrekler kümülatif
rakamların düz farkıyla bulunur (düzeltme yapılırsa hata olurdu). Grafikteki reel seri, her çeyreği TÜFE ile {a.base} TL'sine taşır.
Faaliyet kârı ve serbest nakit akımı bankacılıkta anlamlı olmadığından İNA yerine PD/DD, F/K ve özkaynak kârlılığı gösterilir.
{len(a.reports)} rapor işlendi. Bu not bir araştırma aracının çıktısıdır; yatırım tavsiyesi değildir.</p>
</body></html>"""
