"""Yöntem sayfası (TR/EN): formüller, veri kaynakları, güncelleme takvimi ve bilinen sınırlar."""
from __future__ import annotations

TR = """<div class="eyebrow">Yöntem</div><h1>Nasıl hesaplıyoruz?</h1>
<p class="lead">KAPSAM'daki her rakamın nereden geldiği, nasıl dönüştürüldüğü ve nerede yanılabileceği.</p>

<h2>1. Veri kaynakları ve güncelleme</h2>
<table><tr><th class='l'>Veri</th><th class='l'>Kaynak</th><th class='l'>Sıklık</th></tr>
<tr><td class='l'>Finansal tablolar (konsolide, kümülatif)</td><td class='l'>KAP bildirimleri (ekofin yansısı); eksik kalemler İş Yatırım mali tablo servisi</td><td class='l'>Yeni rapor dönemlerinde, günde en fazla 150 şirket</td></tr>
<tr><td class='l'>TÜFE, dolar/TL</td><td class='l'>TCMB EVDS (TÜİK 2003=100, 2026'dan itibaren 2025=100 zincirlenmiş)</td><td class='l'>Her iş günü</td></tr>
<tr><td class='l'>Hisse listesi, piyasa değeri, sektör</td><td class='l'>İş Yatırım</td><td class='l'>Her iş günü</td></tr>
<tr><td class='l'>Fiyatlar, küresel göstergeler</td><td class='l'>Yahoo Finance (gecikmeli)</td><td class='l'>Her iş günü</td></tr>
<tr><td class='l'>Haber başlıkları</td><td class='l'>Google Haberler RSS (yalnızca başlık ve bağlantı)</td><td class='l'>Her iş günü</td></tr></table>
<p class="m">Güncelleme hafta içi her gün 18:40'ta (İstanbul) GitHub Actions üzerinde otomatik çalışır; durumu <a href='durum.html'>Sistem durumu</a> sayfasındadır.</p>

<h2>2. TMS 29 ve doğru çeyrek</h2>
<p>TMS 29 altında her rapor kendi tarihinin satın alma gücüyle yazılır. Şirketler yılbaşından bu yana kümülatif rakam açıklar; 9 aylık rakamdan 6 aylığı
düz çıkarmak iki farklı TL'yi karıştırır. KAPSAM önceki dönemi TÜFE oranıyla bugünün TL'sine taşır:</p>
<div class="card"><b>Çeyrek(t) = Kümülatif(t) − Kümülatif(t−1) × TÜFE(t) / TÜFE(t−1)</b></div>
<p><b>Düz fark hatası</b>, düzeltmesiz çıkarmanın doğru çeyrekten sapmasıdır. Banka ve sigortalar TMS 29 uygulamaz; bunlarda çeyrekler nominal çıkarılır,
reel eğilim TÜFE ile baz tarihe taşınarak gösterilir.</p>

<h2>3. Temel kâr ve kâr kalitesi</h2>
<p><b>Temel net kâr = net kâr − net parasal pozisyon kazancı.</b> Parasal kazanç enflasyonun borcu eritmesinden doğar, nakit değildir.
Son 12 ay (TTM) değerleri = yılbaşından bu yana + önceki yıl − önceki yılın aynı dönemi, hepsi bugünün TL'siyle. 9 aylık rakamlar otomatik yıllıklandırılmaz.</p>
<table><tr><th class='l'>Bayrak</th><th class='l'>Kural</th></tr>
<tr><td class='l'>Zarar (ağır)</td><td class='l'>Son 12 ay ana ortaklık net kârı ≤ 0</td></tr>
<tr><td class='l'>Parasal kazanç olmasa zarar (ağır)</td><td class='l'>Net kâr − parasal kazanç &lt; 0</td></tr>
<tr><td class='l'>Negatif nakit akışı (ağır)</td><td class='l'>Son 12 ay işletme nakit akışı ≤ 0</td></tr>
<tr><td class='l'>Yüksek borç (ağır)</td><td class='l'>Net borç / FAVÖK &gt; 3 ya da net borç / özkaynak &gt; 1</td></tr>
<tr><td class='l'>Kâr parasal kazanca dayalı</td><td class='l'>Parasal kazanç &gt; net kârın %30'u</td></tr>
<tr><td class='l'>Zayıf nakit dönüşümü</td><td class='l'>İşletme nakit akışı / net kâr &lt; 0,5</td></tr>
<tr><td class='l'>Faaliyet dışı kâr</td><td class='l'>Net kâr &gt; 1,5 × esas faaliyet kârı</td></tr>
<tr><td class='l'>Reel küçülme</td><td class='l'>9 aylık reel hasılat değişimi &lt; −%15</td></tr>
<tr><td class='l'>Capex &gt; nakit akışı</td><td class='l'>İşletme nakit akışı − yatırım harcaması &lt; 0 (serbest nakit akışı değildir)</td></tr>
<tr><td class='l'>Sektöre göre pahalı F/K</td><td class='l'>F/K &gt; sektör medyanı × 1,5</td></tr>
<tr><td class='l'>Olumsuz haber akışı</td><td class='l'>Son 14 günde ≥ 2 olumsuz başlık ve olumsuz &gt; olumlu (kelime tabanlı, hatalı olabilir)</td></tr></table>

<h2>4. İNA (DCF) değerlemesi</h2>
<p>Sanayi şirketlerinde reel serbest nakit akımı (FCFF) iskonto edilir: 10 yıllık açık dönem + sürekli dönem. Hasılat son 12 ay (TMS 29 düzeltmeli),
faaliyet marjı son 12 ay esas faaliyet marjı (parasal kazanç hariç), yeniden yatırım satış / yatırılan sermaye oranından, vergi %25, reel AOSM %10,
sürekli reel büyüme %2. Sonuçlar duyarlılık tablosuyla (AOSM × büyüme) ve piyasa fiyatının ima ettiği büyüme/marj (ters İNA) ile birlikte verilir;
her şirket için formüllü Excel modeli indirilebilir. Banka ve sigortalarda İNA yerine PD/DD, F/K ve özkaynak kârlılığı kullanılır.</p>
<p class="m">İNA varsayımları otomatik ve tüm şirketlere aynıdır; şirkete özel bilgi (yeni yatırım, imtiyaz süresi, iştirakler, tek seferlik kalemler)
içermez. Değer, varsayımlara çok duyarlıdır; Excel modelinde varsayımları değiştirerek sınayın.</p>

<h2>5. Risk</h2>
<p>Günlük log getiriler, son 252 işlem günü. Yıllık oynaklık, aşağı yön oynaklığı, en büyük düşüş, %95 VaR ve beklenen kayıp (ES), BIST 100'e göre beta
ve özgün risk. Korelasyon ve kovaryans ikili tam gözlemle (en az 20 ortak gün); büyük matris için <b>Ledoit–Wolf</b> küçültme (sabit korelasyon hedefi)
ve pozitif yarı tanımlı izdüşüm. 120 günden az ortak veri "düşük güvenilirlik" olarak işaretlenir.</p>

<h2>6. Gündem</h2>
<p>12 küresel/yerel gösterge (BIST 100, dolar/TL, VIX, S&amp;P 500, Brent, altın, ABD 10 yıllık faiz…) ve haber başlıkları. VIX &gt; 25 ya da dolar/TL'nin
bir ayda %5'ten fazla artması, İNA iskonto oranındaki hisse risk primine +1 puan ekler.</p>

<h2>7. Bilinen sınırlar</h2>
<ul><li>Ücretsiz veri kaynakları gecikmeli ve zaman zaman eksiktir; eksik kalemler yedek kaynaktan tamamlanır, kalanlar "veri yok" olarak gösterilir.</li>
<li>Yeni halka arz edilen şirketlerde son 12 ay hesaplanamayabilir.</li>
<li>Şirket sayıları sayfaya göre değişir (finansal tablosu olan şirketler, fiyat serisi olan hisseler, tüm evren).</li>
<li>Haber tonu otomatik ve kabadır; kaynağı okuyun.</li>
<li>Bu site bir araştırma aracının çıktısıdır; al/sat önerisi, hedef fiyat ya da yatırım tavsiyesi içermez.</li></ul>
<p class="m">Kaynak kod ve testler: <a href='https://github.com/serhanyokus/kapsam'>github.com/serhanyokus/kapsam</a>.</p>"""

EN = """<div class="eyebrow">Methodology</div><h1>How we calculate.</h1>
<p class="lead">Where every number on KAPSAM comes from, how it is transformed and where it can go wrong.</p>

<h2>1. Data sources and schedule</h2>
<table><tr><th class='l'>Data</th><th class='l'>Source</th><th class='l'>Frequency</th></tr>
<tr><td class='l'>Financial statements (consolidated, cumulative)</td><td class='l'>KAP filings (ekofin mirror); missing items from İş Yatırım's statement service</td><td class='l'>On new reporting periods, up to 150 companies per day</td></tr>
<tr><td class='l'>CPI, USD/TRY</td><td class='l'>CBRT EVDS (TurkStat 2003=100, chained to 2025=100 from 2026)</td><td class='l'>Every business day</td></tr>
<tr><td class='l'>Stock list, market cap, sector</td><td class='l'>İş Yatırım</td><td class='l'>Every business day</td></tr>
<tr><td class='l'>Prices, global indicators</td><td class='l'>Yahoo Finance (delayed)</td><td class='l'>Every business day</td></tr>
<tr><td class='l'>News headlines</td><td class='l'>Google News RSS (headline and link only)</td><td class='l'>Every business day</td></tr></table>
<p class="m">The update runs automatically on GitHub Actions at 18:40 Istanbul time on business days; see <a href='durum.html'>System status</a>.</p>

<h2>2. IAS 29 and the correct quarter</h2>
<p>Under IAS 29 each report is stated in the purchasing power of its own date. Companies publish year-to-date figures; subtracting 6M from 9M mixes
two different liras. KAPSAM restates the prior period to current lira with the CPI ratio:</p>
<div class="card"><b>Quarter(t) = YTD(t) − YTD(t−1) × CPI(t) / CPI(t−1)</b></div>
<p>The <b>unadjusted-difference error</b> is the deviation of naive subtraction from the correct quarter. Banks and insurers do not apply IAS 29;
their quarters are derived nominally and real trends are shown by restating with CPI.</p>

<h2>3. Core earnings and earnings quality</h2>
<p><b>Core net income = net income − net monetary position gain.</b> Monetary gains arise from inflation eroding debt and are not cash.
Trailing-twelve-month figures = YTD + prior year − prior-year same period, all in current lira. Nine-month figures are never annualised automatically.</p>
<table><tr><th class='l'>Flag</th><th class='l'>Rule</th></tr>
<tr><td class='l'>Loss (severe)</td><td class='l'>TTM net income attributable to parent ≤ 0</td></tr>
<tr><td class='l'>Loss without monetary gain (severe)</td><td class='l'>Net income − monetary gain &lt; 0</td></tr>
<tr><td class='l'>Negative operating cash flow (severe)</td><td class='l'>TTM operating cash flow ≤ 0</td></tr>
<tr><td class='l'>High leverage (severe)</td><td class='l'>Net debt / EBITDA &gt; 3 or net debt / equity &gt; 1</td></tr>
<tr><td class='l'>Monetary-gain-driven profit</td><td class='l'>Monetary gain &gt; 30% of net income</td></tr>
<tr><td class='l'>Weak cash conversion</td><td class='l'>Operating cash flow / net income &lt; 0.5</td></tr>
<tr><td class='l'>Non-operating profit</td><td class='l'>Net income &gt; 1.5 × operating profit</td></tr>
<tr><td class='l'>Real contraction</td><td class='l'>9-month real revenue change &lt; −15%</td></tr>
<tr><td class='l'>Capex &gt; cash flow</td><td class='l'>Operating cash flow − capex &lt; 0 (not free cash flow)</td></tr>
<tr><td class='l'>Expensive vs sector</td><td class='l'>P/E &gt; 1.5 × sector median</td></tr>
<tr><td class='l'>Negative news flow</td><td class='l'>≥ 2 negative headlines in 14 days and negative &gt; positive (keyword-based, may be wrong)</td></tr></table>

<h2>4. DCF valuation</h2>
<p>For industrial companies real free cash flow to the firm is discounted: a 10-year explicit period plus terminal value. Revenue is TTM (IAS 29-adjusted),
operating margin is the TTM core operating margin (excluding monetary gains), reinvestment follows the sales-to-capital ratio, tax 25%, real WACC 10%,
terminal real growth 2%. Results come with a sensitivity table (WACC × growth) and the market-implied growth and margin (reverse DCF); a formula-driven
Excel model can be downloaded for each company. Banks and insurers use P/B, P/E and return on equity instead.</p>
<p class="m">DCF assumptions are automatic and identical for all companies; they exclude company-specific information (new investments, concession terms,
affiliates, one-offs). Values are highly sensitive to assumptions; test them in the Excel model.</p>

<h2>5. Risk</h2>
<p>Daily log returns over the last 252 trading days. Annualised volatility, downside volatility, maximum drawdown, 95% VaR and expected shortfall, beta to
BIST 100 and idiosyncratic risk. Correlation and covariance use pairwise complete observations (at least 20 common days); the large matrix uses
<b>Ledoit–Wolf</b> shrinkage (constant-correlation target) and a positive semi-definite projection. Fewer than 120 common days is flagged as low reliability.</p>

<h2>6. Agenda</h2>
<p>Twelve global/local indicators (BIST 100, USD/TRY, VIX, S&amp;P 500, Brent, gold, US 10-year yield…) and news headlines. VIX above 25 or a monthly USD/TRY
rise above 5% adds one point to the equity risk premium in the DCF discount rate.</p>

<h2>7. Known limitations</h2>
<ul><li>Free data sources are delayed and occasionally incomplete; missing items are filled from a backup source and the rest are shown as "no data".</li>
<li>TTM figures may not be computable for recent IPOs.</li>
<li>Company counts differ by page (companies with statements, stocks with price series, the full universe).</li>
<li>News tone is automatic and crude; read the source.</li>
<li>This site is the output of a research tool; it contains no buy/sell calls, price targets or investment advice.</li></ul>
<p class="m">Source code and tests: <a href='https://github.com/serhanyokus/kapsam'>github.com/serhanyokus/kapsam</a>.</p>"""


def page(lang: str = "tr") -> str:
    body = TR if lang == "tr" else EN
    title = "Yöntem · KAPSAM" if lang == "tr" else "Methodology · KAPSAM"
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{title}</title><style></style></head><body>{body}</body></html>")
