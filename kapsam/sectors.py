"""Sektör sayfaları ve ortak sıralanabilir tablo.

docs/rapor/sektor/index.html: tüm sektörlerin medyan göstergeleri.
docs/rapor/sektor/<sektör>.html: sektördeki şirketler, özet kutucuklar, en iyi/en kötü reel getiri.
"""
from __future__ import annotations

import html
from pathlib import Path

import numpy as np
import pandas as pd

from . import theme

SORT_JS = """<script>
function f(){const q=document.getElementById('q').value.toLocaleLowerCase('tr');for(const r of document.querySelectorAll('#t tbody tr'))r.style.display=r.innerText.toLocaleLowerCase('tr').includes(q)?'':'none'}
document.querySelectorAll('#t th').forEach((th,i)=>th.onclick=()=>{const tb=document.querySelector('#t tbody');const rs=[...tb.rows];const d=th.dataset.d=th.dataset.d==='1'?'0':'1';
rs.sort((a,b)=>{const x=a.cells[i].dataset.v??a.cells[i].innerText,y=b.cells[i].dataset.v??b.cells[i].innerText;const nx=parseFloat(x),ny=parseFloat(y);
const c=(isNaN(nx)||isNaN(ny))?String(x).localeCompare(String(y),'tr'):nx-ny;return d==='1'?-c:c});rs.forEach(r=>tb.appendChild(r))});
</script>"""

SECTOR_COLS = [("ad", "Şirket", "t"), ("piyasa_degeri_mn_tl", "Piyasa değeri (mn TL)", "i"), ("son_ceyrek", "Son çeyrek", "t"),
               ("raporlanan_net_marj", "Net marj", "p"), ("temel_net_marj", "Temel net marj", "p"),
               ("parasal_kazanc_net_kar_ytd", "Parasal kazanç / net kâr", "p"), ("duz_fark_hatasi_hasilat", "Düz fark hatası", "p"),
               ("fk_ttm", "F/K", "x"), ("pd_dd", "PD/DD", "x"), ("reel_getiri_yillik", "Reel getiri 1Y", "p"),
               ("oynaklik_yillik", "Oynaklık", "p"), ("beta", "Beta", "n")]

INDEX_COLS = [("sirket", "Şirket", "i"), ("piyasa_degeri_mn_tl", "Toplam piyasa değeri (mn TL)", "i"),
              ("temel_net_marj", "Medyan temel net marj", "p"), ("raporlanan_net_marj", "Medyan net marj", "p"),
              ("fk_ttm", "Medyan F/K", "x"), ("pd_dd", "Medyan PD/DD", "x"), ("reel_getiri_yillik", "Medyan reel getiri", "p"),
              ("oynaklik_yillik", "Medyan oynaklık", "p"), ("beta", "Medyan beta", "n"), ("sektor_ici_korelasyon", "Sektör içi korelasyon", "n")]


def cell(v, kind: str) -> str:
    e = html.escape
    if kind == "t" or isinstance(v, str):
        return f"<td class='l'>{e('' if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))}</td>"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "<td data-v=''>–</td>"
    if pd.isna(v) or not np.isfinite(v):
        return "<td data-v=''>–</td>"
    if kind == "p":
        return f"<td data-v='{v:.6f}'>{v*100:.1f}%</td>"
    if kind == "x":
        return f"<td data-v='{v:.6f}'>{v:.1f}x</td>"
    if kind == "i":
        return f"<td data-v='{v:.6f}'>{v:,.0f}</td>".replace(",", ".")
    return f"<td data-v='{v:.6f}'>{v:.2f}</td>"


def sortable_table(df: pd.DataFrame, cols: list[tuple], link: str | None = "{}.html", key_label: str = "Kod") -> str:
    """Aranabilir ve sıralanabilir tablo (id='t'). cols: [(sütun, başlık, tür)];
    tür: t metin, p yüzde, x çarpan, i tam sayı, n ondalık. link: ilk sütundaki anahtarın bağlantı kalıbı."""
    e = html.escape
    cols = [c for c in cols if c[0] in df.columns]
    head = f"<th class='l'>{e(key_label)}</th>" + "".join(f"<th{' class=l' if k == 't' else ''}>{e(lab)}</th>" for _, lab, k in cols)

    def key(t):
        if link is None:
            return f"<b>{e(str(t))}</b>"
        return f"<a href='{link.format(t)}'><b>{e(str(t))}</b></a>"
    body = "".join(f"<tr><td class='l'>{key(t)}</td>" + "".join(cell(r.get(c), k) for c, _, k in cols) + "</tr>"
                   for t, r in df.iterrows())
    return f"<div class='wrap'><table id='t'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def _pf(v) -> str:
    if v is None or pd.isna(v):
        return "–"
    return ("−" if v < 0 else "") + f"%{abs(v)*100:.1f}".replace(".", ",")


def _kpi(label, val, sub="") -> str:
    return f"<div class='kpi'><span>{label}</span><b>{val}</b><span>{sub}</span></div>"


def build(out_root: Path, stab: pd.DataFrame, sector_corr: pd.DataFrame | None = None) -> int:
    """Sektör sayfalarını yazar; yazılan sektör sayısını döner."""
    e = html.escape
    out = out_root / "sektor"
    out.mkdir(parents=True, exist_ok=True)
    stab = stab[stab["sektor"].notna()].copy()
    num = [c for c, _, k in SECTOR_COLS if k != "t" and c in stab]
    g = stab.groupby("sektor")
    summ = g[num].median(numeric_only=True)
    summ["sirket"] = g.size()
    if "piyasa_degeri_mn_tl" in stab:
        summ["piyasa_degeri_mn_tl"] = g["piyasa_degeri_mn_tl"].sum(min_count=1)
    if sector_corr is not None:
        diag = {k: sector_corr.at[k, k] for k in sector_corr.index if k in sector_corr.columns}
        summ["sektor_ici_korelasyon"] = pd.Series(diag).reindex(summ.index)
    if "piyasa_degeri_mn_tl" in summ:
        summ = summ.sort_values("piyasa_degeri_mn_tl", ascending=False)
    for sec, grp in g:
        if "piyasa_degeri_mn_tl" in grp:
            grp = grp.sort_values("piyasa_degeri_mn_tl", ascending=False)
        r = summ.loc[sec]
        rg = grp["reel_getiri_yillik"].dropna().sort_values() if "reel_getiri_yillik" in grp else pd.Series(dtype=float)
        hi = ", ".join(f"<a href='../{e(t)}.html'>{e(t)}</a> {_pf(v)}" for t, v in rg.iloc[::-1].head(3).items())
        lo = ", ".join(f"<a href='../{e(t)}.html'>{e(t)}</a> {_pf(v)}" for t, v in rg.head(3).items())
        cv = r.get("sektor_ici_korelasyon", np.nan)
        mc = r.get("piyasa_degeri_mn_tl", np.nan)
        tiles = (_kpi("Toplam piyasa değeri", "–" if pd.isna(mc) else f"{mc/1e3:,.0f} mr TL".replace(",", "."))
                 + (_kpi("Medyan temel net marj", _pf(r.get("temel_net_marj")), "parasal etki hariç")
                    if pd.notna(r.get("temel_net_marj")) else _kpi("Medyan net marj", _pf(r.get("raporlanan_net_marj")), "raporlanan (TMS 29 uygulanmaz)"))
                 + _kpi("Medyan reel getiri", _pf(r.get("reel_getiri_yillik")), "son 1 yıl, TÜFE'ye göre")
                 + _kpi("Sektör içi korelasyon", "–" if pd.isna(cv) else f"{cv:.2f}".replace(".", ","), "ortalama, son 1 yıl"))
        slug = theme.slug(sec)
        page = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(sec)} · KAPSAM</title><style></style></head><body>
<div class="eyebrow"><a href="index.html">Sektörler</a></div><h1>{e(sec)}</h1>
<p class="lead">{int(r['sirket'])} şirket. Medyanlar son çeyrek (TMS 29 düzeltmeli) ve son 1 yıl fiyat verisinden.</p>
<div class="kpis">{tiles}</div>
{f"<p class='muted'>Son 1 yılda en yüksek reel getiri: {hi}<br>En düşük reel getiri: {lo}</p>" if hi else ""}
<h2>Şirketler</h2><input id="q" placeholder="Kod veya şirket ara" oninput="f()">
{sortable_table(grp, SECTOR_COLS, "../{}.html")}
<p class="m">Sütun başlığına tıklayarak sıralayın. Düz fark hatası: kümülatif rakamları TÜFE düzeltmesi yapmadan çıkarmanın son çeyrek hasılatındaki sapması.</p>
{SORT_JS}</body></html>"""
        (out / f"{slug}.html").write_text(theme.restyle(page, "sektor/index.html", "../", "tr", f"sektor/{slug}.html"), encoding="utf-8")
    table = sortable_table(summ, INDEX_COLS, None, "Sektör")
    for sec in summ.index:
        table = table.replace(f"<td class='l'><b>{e(sec)}</b></td>",
                              f"<td class='l'><a href='{theme.slug(sec)}.html'><b>{e(sec)}</b></a></td>", 1)
    page = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sektörler · KAPSAM</title><style></style></head><body>
<div class="eyebrow">Sektörler</div><h1>Sektörler, yan yana.</h1>
<p class="lead">{len(summ)} sektör, {int(summ['sirket'].sum())} şirket. Her sektörün medyan kârlılığı, çarpanları, reel getirisi ve riski. Bir sektöre tıklayın, şirketleri açılır.</p>
<input id="q" placeholder="Sektör ara" oninput="f()">
{table}
<p class="m">Toplam piyasa değerine göre sıralı. Sütun başlığına tıklayarak yeniden sıralayın.</p>
{SORT_JS}</body></html>"""
    (out / "index.html").write_text(theme.restyle(page, "sektor/index.html", "../", "tr", "sektor/index.html"), encoding="utf-8")
    return len(summ)
