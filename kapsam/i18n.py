"""İngilizce sürüm: Türkçe sayfalardan /en/ altına İngilizce kopya üretir.

* Sabit metinler: ifade sözlüğü (uzundan kısaya uygulanır; kısa ifadeler uzunların içini bozmasın diye).
* Değişken cümleler: düzenli ifade kalıpları (ör. "Son 1 yılda hisse %8,6 (BIST 100 %1,4)").
* Sayılar: yalnızca etiket dışındaki metinde Türkçe biçimden İngilizceye ("%3,2" → "3.2%", "1.234,5" → "1,234.5").
* Bağlantılar: Excel/CSV/matris dosyaları Türkçe sayfaların yanında durur; İngilizce sayfalar onları gösterir.
* Şirket ve sektör adları, KAP olay başlıkları ve grafik içi yazılar olduğu gibi kalır.
"""
from __future__ import annotations

import html as _html
import re
from pathlib import Path

from . import theme

PHRASES: dict[str, str] = {
    # --- kalite, gündem, durum (yeni sayfalar)
    "Kâr kalitesi, tek bakışta.": "Earnings quality at a glance.", "Kalite bayrakları · KAPSAM": "Quality flags · KAPSAM",
    "Bayraklar yalnızca finansal tablolardaki örüntüleri gösterir; al/sat önerisi, hedef fiyat ya da seviye içermez. Yatırım tavsiyesi değildir.":
        "Flags only show patterns in financial statements; they contain no buy/sell calls, price targets or ratings. Not investment advice.",
    "Kod, şirket, sektör ya da bayrak ara": "Search ticker, company, sector or flag", "Kurallar": "Rules", "Bayrak": "Flag", "Ağırlık": "Weight",
    "Anlamı": "Meaning", "ağır": "severe", "hafif": "minor", "ağır bayrak": "severe flag", "hafif bayrak": "minor flag",
    "Bayraklar": "Flags", "Sayı": "Count", "Parasal / net kâr": "Monetary / net income", "İşl. NA / net kâr": "Op. CF / net income",
    "Net kâr / esas faal.": "Net income / op. profit", "Net borç / FAVÖK": "Net debt / EBITDA", "Reel hasılat 9A": "Real revenue 9M",
    "İşl. NA − capex (mn)": "Op. CF − capex (mn)", "Haber akışı": "News flow", "Kalite bayrakları": "Quality flags",
    "Tablo yatay kaydırılabilir.": "The table scrolls horizontally.",
    "Akış ve kâr rakamları son 12 ay, TMS 29 düzeltmeli.": "Flow and profit figures are trailing 12 months, IAS 29-adjusted.",
    "İşletme nakit akışı − yatırım harcaması serbest nakit akışı (FCFF) değildir.": "Operating cash flow − capex is not free cash flow (FCFF).",
    "Haber akışı: son 14 günün başlıkları, kelime tabanlı otomatik ton; hatalı olabilir.": "News flow: last 14 days of headlines, keyword-based automatic tone; may be wrong.",
    "Bayrak yok": "No flags", "Zarar": "Loss", "Parasal kazanç olmasa zarar": "Loss without monetary gain", "Negatif nakit akışı": "Negative cash flow",
    "Yüksek borç": "High leverage", "Kâr parasal kazanca dayalı": "Monetary-gain-driven profit", "Zayıf nakit dönüşümü": "Weak cash conversion",
    "Faaliyet dışı kâr": "Non-operating profit", "Reel küçülme": "Real contraction", "Capex > nakit akışı": "Capex > cash flow",
    "Sektöre göre pahalı F/K": "Expensive P/E vs sector", "Olumsuz haber akışı": "Negative news flow",
    "son 12 ay zarar": "loss over the last 12 months", "parasal kazanç olmasa zarar": "loss without monetary gain",
    "işletme nakit akışı negatif": "negative operating cash flow", "borç yüksek": "high leverage",
    "kârın büyük kısmı parasal kazanç": "most of profit is monetary gain", "kâr nakde zayıf dönüşüyor": "profit converts poorly to cash",
    "kâr ağırlıkla faaliyet dışı": "profit mostly non-operating", "reel hasılat küçülüyor": "real revenue shrinking",
    "yatırım harcaması nakit akışını aşıyor": "capex exceeds operating cash flow", "F/K sektörüne göre yüksek": "P/E high vs sector",
    "son 14 günde olumsuz haber akışı": "negative news flow in the last 14 days",
    "Türkiye ve dünya, bugün.": "Turkey and the world, today.", "Gündem · her iş günü yenilenir": "Agenda · refreshed every business day",
    "Piyasa göstergeleri": "Market indicators", "Türkiye": "Turkey", "Dünya": "World", "Şirket haberleri": "Company news",
    "Gösterge": "Indicator", "Son": "Last", "1 gün": "1 day", "Tarih": "Date", "Başlık": "Headline", "Kaynak": "Source", "Ton": "Tone",
    "Hisse risk primi": "Equity risk premium", "Olumsuz haber bayrağı": "Negative news flag", "Olumlu haber akışı": "Positive news flow",
    "Taranan şirket": "Companies scanned", "son 14 gün": "last 14 days", "bilgi amaçlı": "informational",
    "Başlık bulunamadı.": "No headlines found.", "Olumsuz akış (HABER-):": "Negative flow (HABER-):", "Olumlu akış (HABER+):": "Positive flow (HABER+):",
    "Kaynaklar: Yahoo Finance (göstergeler, gecikmeli), Google Haberler RSS (başlık ve bağlantı). Haber metinleri saklanmaz.":
        "Sources: Yahoo Finance (indicators, delayed), Google News RSS (headline and link). Article text is not stored.",
    "Piyasa göstergeleri, makro ve küresel başlıklar,": "Market indicators, macro and global headlines,",
    "şirketin son 14 günlük haberleri.": "companies' news from the last 14 days.",
    "Bu veriler şirket notlarındaki İNA\niskonto oranına ve kalite bayraklarına açık kurallarla girer.":
        "These feed the DCF discount rate in company notes and the quality flags through explicit rules.",
    "Haber tonu başlıktaki kelimelerden otomatik çıkarılır ve hatalı olabilir; başlığa tıklayıp\nkaynağı okuyun.":
        "News tone is inferred automatically from headline words and may be wrong; click the headline to read the source.",
    "Gündem eki:": "Agenda add-on:", "olağan koşullar: ek risk primi yok": "normal conditions: no extra risk premium",
    "Sistem durumu · KAPSAM": "System status · KAPSAM", "Tüm sistemler çalışıyor.": "All systems operational.",
    "Bazı adımlarda hata var.": "Some steps reported errors.", "Son güncelleme": "Last update",
    "Güncelleme hafta içi her gün 18:40'ta (İstanbul) otomatik çalışır.": "The update runs automatically at 18:40 (Istanbul) every business day.",
    "Yöntemi aç →": "Open methodology →", "Yöntem": "Methodology",
    "Kaynaklar: KAP finansal tabloları, TCMB EVDS (TÜFE, kur), İş Yatırım (hisse listesi, eksik tablolar), Yahoo Finance (gecikmeli fiyatlar),\nGoogle Haberler (başlıklar).":
        "Sources: KAP financial statements, CBRT EVDS (CPI, FX), İş Yatırım (stock list, missing statements), Yahoo Finance (delayed prices), Google News (headlines).",
    "Eksik veri tamamlama": "Missing-data completion", "Gündem (gösterge ve haber)": "Agenda (indicators and news)", "Kalite bayrakları": "Quality flags",
    "seo": "SEO",
    # --- gezinme, ana sayfa
    "KAPSAM · BIST araştırma asistanı": "KAPSAM · Borsa Istanbul research assistant",
    "Tüm sistemler çalışıyor": "All systems operational", "Bazı adımlarda hata var": "Some steps reported errors",
    "güncelleme": "updated", "Borsa İstanbul'un tamamı,": "All of Borsa Istanbul,", "enflasyondan arındırılmış.": "adjusted for inflation.",
    "KAPSAM, KAP finansal tablolarını TMS 29'a göre doğru çeyreklere ayırır; her şirket için not, model ve risk analizi üretir.":
        "KAPSAM splits KAP financial statements into correct quarters under IAS 29 and produces a note, a model and a risk analysis for every company.",
    "Şirket ara: kod veya ad (ör. THYAO, Aselsan)": "Search companies: ticker or name (e.g. THYAO, Aselsan)", "Sonuç yok": "No results",
    "Şirket notu ve model": "Company notes and models", "her iş günü yenilenir": "refreshed every business day",
    "TMS 29 taraması": "IAS 29 screener", "şirket, 0 hata": "companies, 0 errors", "Yıllık enflasyon": "Annual inflation",
    "TÜFE, TCMB EVDS": "CPI, CBRT EVDS", "Medyan oynaklık": "Median volatility",
    "Tüm BIST, tek tabloda": "All of BIST in one table",
    "Her şirketin düzeltmesiz çeyrek hatası, parasal kazanç payı, temel marj, çarpanlar, beta ve reel getiri.":
        "For every company: the unadjusted-quarter error, monetary-gain share, core margin, multiples, beta and real return.",
    "Taramayı aç →": "Open the screener →", "Sektörler, yan yana": "Sectors, side by side",
    "Her sektörün medyan kârlılığı, çarpanları, reel getirisi ve sektör içi korelasyonu.":
        "Median profitability, multiples, real return and within-sector correlation for every sector.",
    "Sektörleri aç →": "Open sectors →", "Korelasyon ve kovaryans": "Correlation and covariance",
    "Oynaklık, beta, VaR, en büyük düşüş; kendi portföyünüzün oynaklığını hesaplayan araç.":
        "Volatility, beta, VaR, maximum drawdown, and a tool that computes the volatility of your own portfolio.",
    "Risk sayfasını aç →": "Open the risk page →", "Neden düzeltme gerekli?": "Why adjust?",
    "TMS 29 altında her rapor kendi tarihinin TL'siyle yazılır. Kümülatif rakamları düz çıkarmak son çeyrek hasılatını şişirir; KAPSAM önceki dönemi TÜFE ile taşıyarak doğru çeyreği bulur.":
        "Under IAS 29 each report is stated in lira of its own date. Simply subtracting cumulative figures inflates last-quarter revenue; KAPSAM restates the prior period with CPI to find the correct quarter.",
    "Tüm reel hesaplar bu seriye dayanır.": "All real figures rely on this series.", "Yıllık TÜFE": "Annual CPI",
    "Enflasyon": "Inflation", "Takip listesi: piyasa": "Watchlist: market", "Son fiyat": "Last price", "1 yıl reel": "1 year real",
    "1 yıl": "1 year", "3 ay": "3 months", "1 ay": "1 month",
    "Reel getiri, aynı dönemin TÜFE'siyle arındırılmıştır.": "Real returns are deflated by CPI over the same period.",
    "Şirket notları": "Company notes", "burada takip listesi, tümü": "watchlist shown here, all in the", "taramada": "screener",
    "Son çeyrek": "Last quarter", "Tür": "Type", "Fiyat": "Price", "Fiyatlanan kalıcı faaliyet marjı": "Market-implied steady-state operating margin",
    "Temel net marj": "Core net margin", "sanayi: TMS 29 düzeltmeli reel İNA ve formüllü model": "industrial: IAS 29-adjusted real DCF and formula model",
    "finansal: banka/sigorta, nominal tablolar, PD/DD, F/K, özkaynak kârlılığı": "financial: bank/insurer, nominal statements, P/B, P/E, return on equity",
    "temel: İNA'ya uygun olmayan (hasılatsız holding/GYO), TMS 29 analizi ve çarpanlar": "basic: not suitable for DCF (holding/REIT without revenue), IAS 29 analysis and multiples",
    "Hepsinde piyasa riski bölümü vardır.": "All include a market risk section.",
    "TMS 29 taraması (": "IAS 29 screener (", "şirket; ilk 25,": "companies; top 25,", "tümü": "all",
    "Düz fark hatası: 9A−6A gibi kümülatif rakamları TÜFE düzeltmesi yapmadan çıkarmanın son çeyrekteki sapması.":
        "Unadjusted-difference error: the last-quarter deviation from subtracting cumulative figures (e.g. 9M−6M) without CPI restatement.",
    "Risk ve korelasyon (": "Risk and correlation (", "hisse,": "stocks,", "tümü ve matrisler": "all and matrices",
    "Korelasyon ve kovaryans matrisleri (örnek ve Ledoit–Wolf), sektör korelasyonu ve takip listesi ısı haritası risk sayfasındadır.":
        "Correlation and covariance matrices (sample and Ledoit–Wolf), sector correlation and the watchlist heat map are on the risk page.",
    "Son 1 yılda en yüksek reel getiri:": "Highest real return over the last year:", "En düşük reel getiri:": "Lowest real return:",
    "Olay çalışması: KAP açıklamaları ve gerçek fiyat tepkisi": "Event study: KAP disclosures and actual price reaction",
    "0. gün": "Day 0", "Beklenen": "Expected", "Yön": "Direction", "Olay": "Event", "Rol": "Role",
    "olay şirketi": "event company", "ağın öngördüğü": "network-predicted",
    "Sistem durumu": "System status", "TÜFE ve kur (TCMB)": "CPI and FX (CBRT)", "Hisse listesi": "Stock list", "Fiyatlar": "Prices",
    "KAP tabloları": "KAP statements", "Risk ve korelasyon": "Risk and correlation", "Olay çalışması": "Event study",
    "Kaynaklar: KAP finansal tabloları, TCMB EVDS (TÜFE, kur), İş Yatırım (hisse listesi), Yahoo Finance (gecikmeli fiyatlar).":
        "Sources: KAP financial statements, CBRT EVDS (CPI, FX), İş Yatırım (stock list), Yahoo Finance (delayed prices).",
    "Medyan yıllık oynaklık": "Median annual volatility", "medyan beta": "median beta", "ortalama korelasyon": "average correlation",
    # --- tarama
    "KAPSAM · BIST taraması": "KAPSAM · BIST screener", "Tarama": "Screener", "Tüm BIST, tek tabloda.": "All of BIST in one table.",
    "Düzeltmesiz çeyrek hesabının hatası, parasal kazancın kârdaki payı, temel marj, çarpanlar ve piyasa riski. Bir koda tıklayın, şirketin notu açılır.":
        "The unadjusted-quarter error, the monetary gain's share of profit, core margin, multiples and market risk. Click a ticker to open the company note.",
    "Sütun başlığına tıklayarak sıralayın.": "Click a column header to sort.",
    "Banka ve sigorta şirketleri TMS 29 uygulamaz; nominal modda gösterilir.": "Banks and insurers do not apply IAS 29; shown in nominal mode.",
    "Yatırım tavsiyesi değildir.": "Not investment advice.", "Kod, şirket veya sektör ara": "Search ticker, company or sector",
    "Düz fark hatası: hasılat": "Unadjusted error: revenue", "Düz fark hatası: net kâr": "Unadjusted error: net income",
    "Parasal kazanç / net kâr (YB)": "Monetary gain / net income (YTD)", "Parasal kazanç / net kâr": "Monetary gain / net income",
    "Reel büyüme (yıllık)": "Real growth (YoY)", "ÖK kârlılığı (yıllık)": "ROE (annualised)",
    "Fiyatlanan faaliyet marjı": "Market-implied operating margin", "Reel getiri 1Y": "Real return 1Y", "Max düşüş": "Max drawdown",
    "Düz fark hatası": "Unadjusted error",
    "parasal kazanç olmasa yılbaşından beri zarar": "loss year-to-date without the monetary gain",
    "zararda; parasal kazanç zararı küçültüyor": "loss-making; monetary gain reduces the loss",
    "net parasal varlık: enflasyondan kayıp yazıyor": "net monetary assets: books an inflation loss",
    "TMS 29 uygulanmaz, nominal mod": "IAS 29 not applied, nominal mode",
    "parasal pozisyon satırı yok (TMS 29 uygulanmıyor olabilir), nominal mod": "no monetary position line (IAS 29 may not apply), nominal mode",
    "değerleme:": "valuation:", "son 12 ay hasılat yok ya da sıfır (satışı olmayan holding/GYO): İNA uygulanamaz":
        "no or zero trailing-12-month revenue (holding/REIT without sales): DCF not applicable",
    "son 12 ay hasılat hesaplanamadı": "trailing-12-month revenue could not be computed", "İNA uygulanamaz": "DCF not applicable",
    "raporunda revenue yok": "report has no revenue", "fiyat veya hisse sayısı yok": "no price or share count",
    "sanayi": "industrial", "banka": "bank", "sigorta": "insurance", "temel": "basic", "finansal": "financial",
    # --- sektörler
    "Sektörler · KAPSAM": "Sectors · KAPSAM", "Sektörler, yan yana.": "Sectors, side by side.", "Sektörler": "Sectors",
    "Her sektörün medyan kârlılığı, çarpanları, reel getirisi ve riski. Bir sektöre tıklayın, şirketleri açılır.":
        "Median profitability, multiples, real return and risk for every sector. Click a sector to see its companies.",
    "Sektör ara": "Search sectors", "Toplam piyasa değerine göre sıralı. Sütun başlığına tıklayarak yeniden sıralayın.":
        "Sorted by total market value. Click a column header to re-sort.",
    "Toplam piyasa değeri (mn TL)": "Total market value (TRY mn)", "Toplam piyasa değeri": "Total market value",
    "Medyan temel net marj": "Median core net margin", "Medyan net marj": "Median net margin", "Medyan F/K": "Median P/E",
    "Medyan PD/DD": "Median P/B", "Medyan reel getiri": "Median real return", "Medyan beta": "Median beta",
    "Sektör içi korelasyon": "Within-sector correlation", "Sektör": "Sector", "Şirketler": "Companies", "Şirket": "Company",
    "Medyanlar son çeyrek (TMS 29 düzeltmeli) ve son 1 yıl fiyat verisinden.": "Medians from the latest quarter (IAS 29-adjusted) and last-year price data.",
    "parasal etki hariç": "excluding monetary effect", "raporlanan (TMS 29 uygulanmaz)": "reported (IAS 29 not applied)",
    "son 1 yıl, TÜFE'ye göre": "last year, vs CPI", "ortalama, son 1 yıl": "average, last year", "Kod veya şirket ara": "Search ticker or company",
    "Sütun başlığına tıklayarak sıralayın. Düz fark hatası: kümülatif rakamları TÜFE düzeltmesi yapmadan çıkarmanın son çeyrek hasılatındaki sapması.":
        "Click a column header to sort. Unadjusted error: the last-quarter revenue deviation from subtracting cumulative figures without CPI restatement.",
    "Piyasa değeri (mn TL)": "Market value (TRY mn)", "Net marj": "Net margin", "Oynaklık": "Volatility",
    # --- risk
    "KAPSAM · Risk ve korelasyon": "KAPSAM · Risk and correlation", "Riski ölçün. Birlikte hareketi görün.": "Measure risk. See co-movement.",
    "Her hisse için oynaklık, beta, VaR ve en büyük düşüş; tüm piyasa için korelasyon, kovaryans ve Ledoit–Wolf matrisleri.":
        "Volatility, beta, VaR and maximum drawdown for every stock; correlation, covariance and Ledoit–Wolf matrices for the whole market.",
    "pencere: son 252 işlem günü": "window: last 252 trading days",
    "Günlük log getiri; yıllıklaştırma 252 gün. Beta ve korelasyon BIST 100'e göre. Reel getiri TÜFE, USD getiri TCMB kuru ile.":
        "Daily log returns; annualised with 252 days. Beta and correlation vs BIST 100. Real return via CPI, USD return via the CBRT rate.",
    "Tüm matrisler her gün güncellenir": "All matrices are updated daily", "Ledoit–Wolf küçültme katsayısı": "Ledoit–Wolf shrinkage intensity",
    "işlem gününden az verisi olan": "stocks with fewer than", "hisse (yeni halka arzlar) dahildir; 'Güvenilirlik' sütununa bakın.":
        "trading days of data (recent IPOs) are included; see the 'Reliability' column.",
    "İndir:": "Download:", "Risk tablosu (tüm hisseler)": "Risk table (all stocks)", "Takip listesi korelasyon": "Watchlist correlation",
    "Takip listesi kovaryans (yıllık)": "Watchlist covariance (annual)", "Sektör korelasyonu": "Sector correlation",
    "Tüm hisseler korelasyon matrisi": "All-stock correlation matrix", "Tüm hisseler kovaryans (yıllık, örnek)": "All-stock covariance (annual, sample)",
    "Tüm hisseler Ledoit–Wolf kovaryans (pozitif tanımlı)": "All-stock Ledoit–Wolf covariance (positive definite)",
    "Portföy aracı": "Portfolio tool",
    "Hisse ekleyin (en fazla 25). Araç, tüm piyasanın Ledoit–Wolf kovaryans matrisini tarayıcıda açar ve seçiminiz için korelasyonu,":
        "Add stocks (up to 25). The tool opens the whole-market Ledoit–Wolf covariance matrix in your browser and computes, for your selection, the correlation,",
    "portföy oynaklığını ve her hissenin riske katkısını hesaplar. Ağırlıkları değiştirebilirsiniz (toplam otomatik 100'e ölçeklenir).":
        "portfolio volatility and each stock's risk contribution. You can edit the weights (they are rescaled to 100 automatically).",
    "Hisse kodu yazın ve Enter'a basın (ör. THYAO)": "Type a ticker and press Enter (e.g. THYAO)",
    "Eşit ağırlık": "Equal weight", "Temizle": "Clear", "Örnek: BIST-30 bankaları": "Example: BIST-30 banks",
    "Matris yükleniyor…": "Loading matrix…", "Hazır: ": "Ready: ", " hisse. Başlamak için hisse ekleyin.": " stocks. Add stocks to start.",
    "Matris yüklenemedi (sayfa yerel dosyadan açılmış olabilir). Yayımlanan sitede çalışır.":
        "Could not load the matrix (the page may have been opened from a local file). It works on the published site.",
    "En az iki hisse ekleyin.": "Add at least two stocks.", "Başlamak için hisse ekleyin.": "Add stocks to start.",
    "Ağırlıkların toplamı sıfır.": "Weights sum to zero.", "Portföy yıllık oynaklık": "Portfolio annual volatility",
    "Ağırlıklı ortalama oynaklık": "Weighted average volatility", "çeşitlendirme olmasaydı": "without diversification",
    "Çeşitlendirme oranı": "Diversification ratio", "1'den büyük = fayda": "above 1 = benefit", "Riskin en büyük kaynağı": "Largest risk source",
    "katkı": "contribution", "Ağırlık": "Weight", "Riske katkı": "Risk contribution", "Çıkar": "Remove",
    "Korelasyonlar ve oynaklıklar Ledoit–Wolf küçültülmüş kovaryanstan (son 1 yıl, yıllık). Riske katkı: hissenin portföy varyansındaki payı.":
        "Correlations and volatilities from the Ledoit–Wolf shrunk covariance (last year, annual). Risk contribution: the stock's share of portfolio variance.",
    "Takip listesi korelasyon ısı haritası (kümelenmiş)": "Watchlist correlation heat map (clustered)",
    "Sektörler arası ortalama korelasyon": "Average correlation between sectors", "Risk tablosu": "Risk table",
    "Güvenilirlik": "Reliability", "Gün": "Days", "Getiri 1Y": "Return 1Y", "Reel getiri": "Real return", "USD getiri": "USD return",
    "Kor. XU100": "Corr. XU100", "Özgün oynaklık": "Idiosyncratic volatility", "VaR95 (gün)": "VaR95 (day)", "ES95 (gün)": "ES95 (day)",
    "Getiri/oynaklık": "Return/volatility", "Ort. korelasyon": "Avg. correlation", "En çok birlikte hareket eden": "Most co-moving",
    "düşük (az veri)": "low (little data)", "yüksek": "high",
    "VaR95/ES95: günlük %5 en kötü getiri eşiği ve o günlerin ortalama kaybı (tarihsel). Özgün oynaklık: piyasa (beta) etkisi çıkarıldıktan sonra kalan.":
        "VaR95/ES95: the worst-5% daily return threshold and the average loss on those days (historical). Idiosyncratic volatility: what remains after removing the market (beta) effect.",
    "Getiri/oynaklık: risksiz faiz düşülmemiş basit oran. Fiyatlar Yahoo Finance (gecikmeli, bölünme ve bedelsize göre düzeltilmiş).":
        "Return/volatility: simple ratio without subtracting a risk-free rate. Prices from Yahoo Finance (delayed, adjusted for splits and bonus issues).",
    # --- notlar
    "KAPSAM araştırma notu": "KAPSAM research note", "KAPSAM finansal sektör notu": "KAPSAM financial-sector note", "KAPSAM notu": "KAPSAM note",
    "Son veri:": "Latest data:", "Tutarlar": "Amounts in", "TL'si (reel) ya da rapor TL'si (tabloda)": "TRY (real) or reporting-date TRY (table)",
    "TL'si (reel)": "TRY (real)", "TL'sidir": "TRY", "Banka tablo biçimi": "Bank statement format", "Sigorta tablo biçimi": "Insurance statement format",
    ": Enflasyondan arındırılmış görünüm ve değerleme": ": Inflation-adjusted view and valuation",
    "Reel hasılat büyümesi (yıllık)": "Real revenue growth (YoY)", "Temel net marj / raporlanan": "Core net margin / reported",
    "raporlanan": "reported", "İNA hisse başı değer": "DCF value per share", "potansiyel": "upside",
    "Piyasanın fiyatladığı kalıcı faaliyet marjı": "Market-implied steady-state operating margin",
    "Piyasanın fiyatladığı reel büyüme": "Market-implied real growth", "bizim varsayım": "our assumption", "son 12 ay": "last 12 months",
    "1. Neden düzeltme gerekli?": "1. Why adjust?", "2. Değerleme (reel İNA)": "2. Valuation (real DCF)",
    "Raporlanan rakamlar her çeyrekte farklı bir TL ile ifade edilir. Aşağıda gri çizgi şirketin raporladığı çeyreklik hasılatı, mavi çizgi ise aynı satın alma gücüne taşınmış reel hasılatı gösterir.":
        "Reported figures are expressed in a different lira each quarter. Below, the grey line shows the company's reported quarterly revenue and the blue line shows real revenue restated to the same purchasing power.",
    "Parasal kazanç/kayıp, son çeyrekte net kârın": "The monetary gain/loss makes up", "kadarını oluşturuyor.": "of last-quarter net income.",
    "Model değeri piyasa fiyatından çok uzak": "The model value is far from the market price",
    "Bu genellikle bir girdinin şirketin ekonomisini yansıtmadığını gösterir: TMS 29 sonrası faaliyet marjı yeniden değerlenmiş amortismanla düşük görünebilir; negatif işletme sermayesinden gelen parasal kazanç ekonomik bir getiri olabilir ama faaliyet kârında yoktur. Bu durumda ters İNA (piyasanın fiyatladığı marj veya büyüme) daha anlamlı bir başlangıçtır. Yatırım görüşü değildir.":
        "This usually means an input does not reflect the company's economics: after IAS 29 the operating margin can look low because of revalued depreciation, and a monetary gain from negative working capital can be an economic return that is not in operating profit. A reverse DCF (the margin or growth the market prices in) is then a better starting point. Not an investment view.",
    "Son 12 ay reel hasılat": "Last-12-month real revenue", "Reel büyüme (ilk": "Real growth (first", "yıl → sürekli)": "years → terminal)",
    "Hedef faaliyet marjı": "Target operating margin", "Reel AOSM": "Real WACC", "Satış / yatırılan sermaye": "Sales / invested capital",
    "(nakit akışından tahmin)": "(estimated from cash flow)", "(varsayım)": "(assumption)", "Firma değeri": "Enterprise value",
    "Net borç": "Net debt", "Özkaynak değeri": "Equity value", "Sürekli değerin payı": "Terminal value share", "Hisse başı değer": "Value per share",
    "Satırlar reel AOSM, sütunlar ilk dönem reel büyüme.": "Rows: real WACC; columns: initial real growth.",
    "Çarpan (son 12 ay, reel)": "Multiple (last 12 months, real)", "FD/Satışlar": "EV/Sales", "FD/FVÖK": "EV/EBIT",
    "F/K (raporlanan)": "P/E (reported)", "F/K (temel)": "P/E (core)", "Veri kalitesi ve yöntem": "Data quality and method",
    "KAP raporu işlendi.": "KAP reports processed.", "Sayısal kontroller:": "Numerical checks:", "geçti": "passed",
    "KAP'ın kendi 3 aylık rakamlarıyla çapraz kontrol:": "cross-check against KAP's own 3-month figures:", "uyumlu": "consistent",
    "Çeyreklik akışlar, önceki kümülatif rakam TÜFE ile cari rapor tarihine taşınarak ayrıştırılmıştır.":
        "Quarterly flows were derived by restating the prior cumulative figure to the current reporting date with CPI.",
    "Reel seriler": "Real series are in", "USD çevrimi TMS 21 par. 42'ye göre rapor tarihi kuruyla yapılmıştır.":
        "USD translation uses the reporting-date rate under IAS 21 para. 42.",
    "İNA reel nakit akışları ve Fisher denklemiyle bulunan reel AOSM ile hesaplanır.":
        "The DCF uses real cash flows and a real WACC derived with the Fisher equation.",
    "Bu not bir araştırma aracının çıktısıdır; yatırım tavsiyesi değildir.": "This note is the output of a research tool; it is not investment advice.",
    "Fiyat ve sektör": "Price and sector", "Son 1 yılda hisse": "Over the last year the stock returned",
    "Fiyatlar bölünme ve bedelsize göre düzeltilmiştir.": "Prices are adjusted for splits and bonus issues.",
    "medyanı": "median", "Gösterge": "Metric", "Sektör medyanı": "Sector median",
    "Raporlanan net marj": "Reported net margin", "Temel net marj (parasal etki hariç)": "Core net margin (excl. monetary effect)",
    "F/K (son 12 ay)": "P/E (last 12 months)", "F/K (son 12 ay, reel)": "P/E (last 12 months, real)", "PD/DD": "P/B", "Reel getiri (1 yıl)": "Real return (1 year)",
    "Yıllık oynaklık (aşağı yön)": "Annual volatility (downside)", "Yıllık oynaklık": "Annual volatility",
    "Piyasa riski (son 1 yıl,": "Market risk (last year,", "işlem günü)": "trading days)",
    "Getiri (1 yıl): nominal / reel / USD": "Return (1 year): nominal / real / USD", "Beta / BIST 100 korelasyonu": "Beta / BIST 100 correlation",
    "Özgün oynaklık / sistematik risk payı": "Idiosyncratic volatility / systematic risk share", "Günlük VaR95 / ES95": "Daily VaR95 / ES95",
    "En büyük düşüş (1 yıl)": "Maximum drawdown (1 year)", "Çarpıklık / basıklık": "Skewness / kurtosis",
    "Ortalama korelasyon (tüm piyasa)": "Average correlation (whole market)", "En çok birlikte hareket ettiği hisseler": "Most co-moving stocks",
    "Günlük log getiri, BIST 100'e göre piyasa modeli. Reel getiri TÜFE, USD getiri TCMB kuru ile.":
        "Daily log returns, market model vs BIST 100. Real return via CPI, USD return via the CBRT rate.",
    "Az veri: sonuçlar güvenilir değil.": "Little data: results are not reliable.",
    "Piyasa değeri / özkaynak": "Market value / equity", "Özkaynak kârlılığı (son 12 ay)": "Return on equity (last 12 months)", "Özkaynak": "Equity",
    "Faaliyet geliri reel büyüme (yıllık)": "Operating income real growth (YoY)", "Ücret/komisyon payı": "Fee/commission share",
    "Karşılık / net faiz geliri": "Provisions / net interest income", "Kredi / mevduat": "Loans / deposits",
    "Brüt prim reel büyüme (yıllık)": "Gross premium real growth (YoY)", "Saklama oranı": "Retention ratio",
    "Net marj (kâr / brüt prim)": "Net margin (profit / gross premiums)", "Yıllık ÖK kârlılığı (çeyrek)": "Annualised ROE (quarter)",
    "Çeyreklik görünüm": "Quarterly view", "mn TL (nominal)": "TRY mn (nominal)", "mn TL (rapor TL'si)": "TRY mn (reporting-date TRY)",
    "Net faiz geliri": "Net interest income", "Net ücret ve komisyon": "Net fees and commissions", "Beklenen zarar karşılıkları": "Expected credit losses",
    "Net kâr": "Net income", "Brüt yazılan primler": "Gross written premiums", "Net primler": "Net premiums", "Teknik bölüm dengesi": "Technical result",
    "Hasılat": "Revenue", "Esas faaliyet kârı": "Operating profit", "Net parasal pozisyon kazancı": "Net monetary position gain",
    "Yöntem": "Method", "rapor işlendi.": "reports processed.",
    "şirketleri BDDK/SEDDK düzenlemesi gereği TMS 29 enflasyon düzeltmesi uygulamaz; bu yüzden çeyrekler kümülatif":
        "companies do not apply IAS 29 inflation adjustment under BRSA/IPSRA rules, so quarters are derived as plain differences of cumulative",
    "rakamların düz farkıyla bulunur (düzeltme yapılırsa hata olurdu). Grafikteki reel seri, her çeyreği TÜFE ile":
        "figures (adjusting would be an error). The real series in the chart restates every quarter with CPI to",
    "TL'sine taşır.": "TRY.",
    "Faaliyet kârı ve serbest nakit akımı bankacılıkta anlamlı olmadığından İNA yerine PD/DD, F/K ve özkaynak kârlılığı gösterilir.":
        "Since operating profit and free cash flow are not meaningful for financials, P/B, P/E and return on equity are shown instead of a DCF.",
    "Değerleme (İNA) uygulanmadı:": "Valuation (DCF) not applied:", "Not, aynı TMS 29 analizini ve piyasa riskini içerir.":
        "The note contains the same IAS 29 analysis and market risk.",
    "Son 12 ay net kâr (reel, mn)": "Last-12-month net income (real, mn)", "Parasal kazanç / net kâr (YB)": "Monetary gain / net income (YTD)",
    "Düzeltmesiz çeyrek hesabının hatası (hasılat)": "Error of the unadjusted quarter calculation (revenue)",
    "Düz fark (mn)": "Plain difference (mn)", "TMS 29 tutarlı (mn)": "IAS 29-consistent (mn)", "Hata": "Error", "Çeyrek": "Quarter",
    "KAP raporu işlendi. Çeyrekler, önceki kümülatif rakam TÜFE ile cari rapor tarihine taşınarak ayrıştırılır;":
        "KAP reports processed. Quarters are derived by restating the prior cumulative figure to the current reporting date with CPI;",
    "çeyrekler eksikse son 12 ay kümülatif raporlardan (YB + önceki yıl − önceki yıl aynı dönem) hesaplanır.":
        "if quarters are missing, the last 12 months are computed from cumulative reports (YTD + prior year − prior-year same period).",
    "Çeyreklik kalemler": "Quarterly items", "Banka": "Bank", "Sigorta": "Insurance", "ve": "and", "şirket": "companies",
    "Genel bakış": "Overview", "Risk": "Risk", "Yatırım tavsiyesi değildir": "Not investment advice", "Hisse": "Stock", "Kod": "Ticker",
    "mr TL": "bn TRY", "mn TL": "TRY mn",
}

# KAP olay başlıkları (metnin tamamı eşleşirse)
EVENTS_EN = {
    "THY: Boeing'den 225 uçak (75 B787 + 150 737 MAX, kesin+opsiyon) siparişi": "THY: order for 225 Boeing aircraft (75 B787 + 150 737 MAX, firm + options)",
    "Turkcell: 5G ihalesinde 160 MHz, 1,224 milyar USD, 2042'ye kadar lisans": "Turkcell: 160 MHz in the 5G auction, USD 1.224 bn, licence until 2042",
    "ASELSAN: 442,5 milyon USD ihracat sözleşmesi (radar, İHA karşıtı sistemler)": "ASELSAN: USD 442.5 mn export contract (radar, counter-UAV systems)",
    "ASELSAN: 1,1 milyar USD hava savunma ihracat sözleşmesi": "ASELSAN: USD 1.1 bn air-defence export contract",
    "Arçelik: Arçelik Hitachi ortak girişimindeki %60 payını ~261 milyon USD'ye satıyor": "Arçelik: sells its 60% stake in the Arçelik Hitachi JV for ~USD 261 mn",
    "Arçelik: Tayland buzdolabı fabrikasında üretimi durduruyor (411 çalışan)": "Arçelik: stops production at its Thailand refrigerator plant (411 employees)",
    "Ford Otosan: 31,4 milyar TL proje bazlı devlet desteği (Ford Trucks Avrupa)": "Ford Otosan: TRY 31.4 bn project-based state incentive (Ford Trucks Europe)",
    "Ford Otosan: IVECO ile yeni kabin programı, ~364 milyon EUR yatırım": "Ford Otosan: new cab programme with IVECO, ~EUR 364 mn capex",
    "Ford Otosan: Koç Finansman'ın %100'ünü ~137 milyon USD'ye alıyor": "Ford Otosan: buys 100% of Koç Finansman for ~USD 137 mn",
    "Ford Otosan: planlı tatil/bakım duruşu, 2026 beklentilerine etkisi yok (plasebo)": "Ford Otosan: planned holiday/maintenance stop, no impact on 2026 guidance (placebo)",
    "Tüpraş: İzmit rafinerisi tank sahasında yangın, kontrol altında, önemli etki yok": "Tüpraş: fire in the İzmit refinery tank area, under control, no material impact",
    "Koç, Tüpraş'ın %2,1'ini hızlandırılmış talep toplamayla satıyor (9,32 milyar TL)": "Koç sells 2.1% of Tüpraş in an accelerated bookbuild (TRY 9.32 bn)",
    "Koç ve Temel Ticaret Tüpraş'ın %0,83'ünü satıyor; grup payı ~%50,1": "Koç and Temel Ticaret sell 0.83% of Tüpraş; group stake ~50.1%",
    "Koç (Tek-Art): Göcek'te iki marina ve otel, 160 milyon USD": "Koç (Tek-Art): two marinas and hotels in Göcek, USD 160 mn",
    "BİM: katılım bankası kurmak için BDDK'ya başvuru": "BİM: applies to the BRSA to set up a participation bank",
    "BİM: %100 bedelsiz sermaye artırımı (600 milyon → 1,2 milyar TL)": "BİM: 100% bonus share issue (TRY 600 mn → 1.2 bn)",
    "Migros: 43 dağıtım merkezindeki 7.875 taşeron çalışanı kendi kadrosuna alıyor": "Migros: moves 7,875 subcontracted workers at 43 distribution centres onto its payroll",
    "Pegasus: Smartwings Group'un %100'ünü 154 milyon EUR'ya alıyor": "Pegasus: buys 100% of Smartwings Group for EUR 154 mn",
    "Pegasus: Smartwings alımı tamamlandı (142,3 milyon EUR)": "Pegasus: Smartwings acquisition completed (EUR 142.3 mn)",
    "Erdemir: İsdemir 1 No'lu yüksek fırın (2,8 mt/yıl) devreye alındı": "Erdemir: İsdemir blast furnace No. 1 (2.8 mt/yr) commissioned",
    "Şişecam: Rekabet Kurulu'ndan 3,155 milyar TL idari para cezası": "Şişecam: TRY 3.155 bn fine from the Competition Board",
    "Türk Telekom: imtiyaz 2050'ye uzatıldı; 2,5 milyar USD + KDV bedel, 17 milyar USD yatırım taahhüdü": "Türk Telekom: concession extended to 2050; USD 2.5 bn + VAT fee, USD 17 bn investment commitment",
    "TAV: Almatı Havalimanı'nın kalan %15'ini 133 milyon USD'ye alıyor": "TAV: buys the remaining 15% of Almaty Airport for USD 133 mn",
    "Akbank: 600 milyon USD AT1 tahvil ihracı (%7,95 kupon)": "Akbank: USD 600 mn AT1 bond issue (7.95% coupon)",
    "SASA: yıllık 52.500 ton low-melt polyester elyaf tesisi devreye alındı (~75 milyon USD yıllık gelir)": "SASA: 52,500 t/yr low-melt polyester fibre plant commissioned (~USD 75 mn annual revenue)",
}
JS_EN = {"Sonuç yok": "No results", "${n} hisse": "${n} stocks", "${pct(Math.max(...rc))} katkı": "${pct(Math.max(...rc))} contribution",
         "<th>Ağırlık</th>": "<th>Weight</th>", "<th>Oynaklık</th>": "<th>Volatility</th>", "<th>Riske katkı</th>": "<th>Risk contribution</th>",
         'class="l">Hisse</th>': 'class="l">Stock</th>', 'title="Ağırlık"': 'title="Weight"', 'title="Çıkar"': 'title="Remove"'}

# değişken cümleler (sayı dönüştürmeden ÖNCE uygulanır)
PATTERNS = [
    (r"temel %(\d+) \+ gündem eki %(\d+)", r"base %\1 + agenda add-on %\2"),
    (r"VIX (\d+) > 25: küresel risk iştahı zayıf \(\+1 puan\)", r"VIX \1 > 25: weak global risk appetite (+1 pt)"),
    (r"dolar/TL son 1 ayda (%[\d,]+) arttı \(\+1 puan\)", r"USD/TRY rose \1 in a month (+1 pt)"),
    (r"son 14 gün (\d+) olumlu / (\d+) olumsuz başlık", r"last 14 days: \1 positive / \2 negative headlines"),
    (r"^(\s*[A-Z0-9]{3,6}) ve\s*$", r"\1 vs "), (r"^\s*medyanı \((\d+) şirket\)\s*$", r" median (\1 companies)"),
    (r"değerleme: ", "valuation: "), (r"\((\d+) hisse,", r"(\1 stocks,"), (r"(\d+/\d+) geçti", r"\1 passed"),
    (r"Reel seriler (\S+) TL'sidir\.", r"Real series are in \1 TRY."),
    (r"(\d+) sektör, (\d+) şirket\.", r"\1 sectors, \2 companies."),
    (r"(\d+) şirket\. ", r"\1 companies. "),
    (r"\((\d+) şirket\)", r"(\1 companies)"),
    (r"(\d+) şirket · ", r"\1 companies · "),
    (r"(\d+) hisse · ", r"\1 stocks · "),
    (r"(\d+) hisse, son 1 yıl", r"\1 stocks, last year"),
    (r"(\d+) sektör sayfası", r"\1 sector pages"),
    (r"(\d+) şirket tarandı", r"\1 companies screened"),
    (r"(\d+) şirket notu \+ Excel", r"\1 company notes + Excel"),
    (r"İNA (\d+), finansal (\d+), temel (\d+)", r"DCF \1, financial \2, basic \3"),
    (r"(\d+) olay, (\d+) hisse-olay gözlemi; olay şirketinde yön isabeti", r"\1 events, \2 stock-event observations; direction hit rate for event companies"),
    (r"(\d+) hisse kontrol edildi, (\d+) yeni rapor kaydedildi", r"\1 stocks checked, \2 new reports stored"),
    (r"(\d+) desteklenmiyor", r"\1 unsupported"),
    (r"Yeni rapor beklenen hisse yok \(tüm kayıtlar güncel\)", "No new reports expected (all records up to date)"),
    (r"(\d+) hisse \(sanayi: (\d+), banka: (\d+), sigorta: (\d+)\)", r"\1 stocks (industrial: \2, bank: \3, insurance: \4)"),
    (r"(\d+)/(\d+) hisse \(takip listesi (\d+)/(\d+)\), son tarih", r"\1/\2 stocks (watchlist \3/\4), last date"),
    (r"TÜFE son: ", "CPI last: "), (r"resmi 2003=100 son: ", "official 2003=100 last: "),
    (r"2025=100 serisiyle zincirlendi, son: ", "chained with the 2025=100 series, last: "), (r"2025=100 kodu: ", "2025=100 code: "),
    (r"kur son: ", "FX last: "), (r"medyan yıllık oynaklık", "median annual volatility"), (r"ort\. korelasyon", "avg. correlation"),
    (r"korelasyon, kovaryans ve Ledoit–Wolf matrisleri (\d+) hisse \(az veri: (\d+)\)", r"correlation, covariance and Ledoit–Wolf matrices for \1 stocks (little data: \2)"),
    (r"config/takip\.json içinde olay yok", "no events in config/takip.json"),
    (r"(\d+) KAP raporu işlendi\.", r"\1 KAP reports processed."), (r"(\d+) rapor işlendi\.", r"\1 reports processed."),
    (r"İNA \(ilk (\d+) yıl", r"DCF (first \1 years"),
    (r"^(\s*[A-Z0-9]{3,6}) ve\s*$", r"\1 vs "), (r"^\s*medyanı \((\d+) şirket\)\s*$", r" median (\1 companies)"),
    (r"\bfiyat ([\d.,]+)", r"price \1"), (r"(\d+) hisse;", r"\1 stocks;"),
    (r"CAR: piyasa modeline \(BIST 100\) göre kümülatif anormal getiri, \[-1,\+3\] işlem günü\. \|t\| > 2 kabaca %5 düzeyinde anlamlı\.",
     "CAR: cumulative abnormal return vs the market model (BIST 100), [-1,+3] trading days. |t| > 2 is roughly significant at 5%."),
    (r"Beklenen: olay şirketinde analist varsayımı \(−1\.\.\+1\), bağlantılı şirketlerde ilişki ağının öngördüğü etki\.",
     "Expected: analyst assumption for the event company (−1..+1), network-predicted impact for linked companies."),
    (r"18:10'dan sonraki açıklamalarda 0\. gün ertesi işlem günüdür\.", "For disclosures after 18:10, day 0 is the next trading day."),
    (r"Çeyrekler, önceki kümülatif rakam TÜFE ile cari rapor tarihine taşınarak ayrıştırılır;",
     "Quarters are derived by restating the prior cumulative figure to the current reporting date with CPI;"),
]

_NUM_PCT = re.compile(r"([-−]?)%(\d[\d.,]*\d|\d)")
_NUM_TR_DEC = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})*),(\d+)(?![\d,])")
_NUM_TR_INT = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+)(?![\d,.])")


def _num_tr_to_en(s: str) -> str:
    if "," in s:
        return s.replace(".", "").replace(",", ".") if s.count(",") == 1 else s
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        return s.replace(".", ",")
    return s


def _convert_numbers(text: str) -> str:
    text = _NUM_PCT.sub(lambda m: f"{m.group(1)}{_num_tr_to_en(m.group(2))}%", text)
    text = _NUM_TR_DEC.sub(lambda m: f"{m.group(1).replace('.', ',')}.{m.group(2)}", text)
    return _NUM_TR_INT.sub(lambda m: m.group(1).replace(".", ","), text)


# Tek kelimelik ya da kısa ifadeler yalnızca metin düğümünün TAMAMI ise çevrilir (şirket/sektör adlarının içi bozulmasın)
_EXACT = {k: v for k, v in PHRASES.items() if " " not in k.strip()}
_EXACT.update(EVENTS_EN)
_PH = sorted(((k, v) for k, v in PHRASES.items() if k not in _EXACT), key=lambda kv: -len(kv[0]))


def _translate_text(t: str) -> str:
    core = t.strip()
    if core in _EXACT:
        return t.replace(core, _EXACT[core])
    for pat, rep in PATTERNS:
        t = re.sub(pat, rep, t)
    for k, v in _PH:
        if k in t:
            t = t.replace(k, v)
    return t


def to_english(page: str, depth: int, here: str) -> str:
    """Türkçe sayfayı İngilizceye çevirir. depth: sayfanın kökten derinliği (0: kök, 1: risk/ ya da sektor/)."""
    root = "../" * depth
    # gezinme ve altbilgi
    active = re.search(r"<a href='(?:\.\./)*([^']+)' class=on>", page)
    page = re.sub(r"<nav class='nav'>.*?</nav>", theme.nav_html(active.group(1) if active else "", root, "en", here), page, count=1, flags=re.S)
    page = re.sub(r"<footer>.*?</footer>", lambda m: theme.foot_html("en", root), page, count=1, flags=re.S)
    page = page.replace('<html lang="tr">', '<html lang="en">', 1)
    # metin, öznitelik ve betik içindeki sabit ifadeler; sayılar yalnızca metin düğümlerinde
    parts = re.split(r"(<style>.*?</style>|<script.*?</script>|<[^>]+>)", page, flags=re.S)
    out = []
    for x in parts:
        if x.startswith("<style>") or (x.startswith("<img") and "base64" in x):
            out.append(x)
        elif x.startswith("<script"):
            x = x.replace("replace('.',',')", "replace('','')").replace("toLocaleLowerCase('tr')", "toLowerCase()")
            for k, v in JS_EN.items():
                x = x.replace(k, v)
            for k, v in _PH:
                if len(k) > 8 and k in x:
                    x = x.replace(k, v.replace("'", "\\'"))      # betik içinde: kesme işareti dizeyi kapatmasın
            out.append(x)
        elif x.startswith("<"):
            x = re.sub(r"(placeholder|title|alt)='([^']*)'", lambda m: f"{m.group(1)}='{_translate_text(m.group(2))}'", x)
            x = re.sub(r'(placeholder|title|alt)="([^"]*)"', lambda m: f'{m.group(1)}="{_translate_text(m.group(2))}"', x)
            out.append(x)
        else:
            t = _translate_text(_html.unescape(x))
            out.append(_html.escape(_convert_numbers(t), quote=False))
    page = "".join(out)
    # arama motoru etiketleri: İngilizce başlık ve adres
    page = re.sub(r"<!--seo-->.*?<!--/seo-->", lambda m: theme.seo_head(theme._title_of(page), "en", here), page, count=1, flags=re.S)
    # dosyalar Türkçe sayfaların yanında durur
    up = "../" * (depth + 1)
    page = re.sub(r"href='([^'/:]+_model\.xlsx)'", lambda m: f"href='{'../' * (depth + 1)}{m.group(1)}'", page)
    if here.startswith("risk/"):
        page = re.sub(r"href='([^'/:]+\.(?:csv|gz))'", lambda m: f"href='{up}risk/{m.group(1)}'", page)
        page = page.replace("fetch('kovaryans_ledoit_wolf.csv.gz')", f"fetch('{up}risk/kovaryans_ledoit_wolf.csv.gz')")
    return page


def build_site(out_root: Path) -> int:
    """docs/rapor altındaki tüm Türkçe sayfaların İngilizcesini docs/rapor/en/ altına yazar."""
    en = out_root / "en"
    n = 0
    for f in out_root.rglob("*.html"):
        rel = f.relative_to(out_root)
        if rel.parts[0] == "en":
            continue
        depth = len(rel.parts) - 1
        target = en / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(to_english(f.read_text(encoding="utf-8"), depth, rel.as_posix()), encoding="utf-8")
        n += 1
    return n
