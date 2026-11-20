# Gerçek veri: kaynaklar ve notlar (16 Kasım 2026)

Bu klasördeki veriler yayımlanmış kaynaklardan elle aktarılmıştır. Otomatik güncelleme (EVDS anahtarı ve KAP dosyaları eklendiğinde) bunların yerini alır.

## TÜFE (`tufe_aylik.csv`)
- 2022-12 – 2025-12: TÜİK TÜFE (2003=100) endeks değerleri, hakedis.org tablosundan. Kontrol: Aralık 2024 yıllık %44,38, Ocak 2025 yıllık %42,12 resmi açıklamalarla aynı.
- 2026-01 – 2026-10: TÜİK 2026'dan itibaren 2025=100 endeksine geçti. Seri, TÜİK'in açıkladığı aylık değişimlerle (BTSO tablosu: Ocak %4,84, Şubat %2,96, Mart %1,94, Nisan %4,18, Mayıs %1,71, Haziran %0,99, Temmuz %1,78, Ağustos %1,84, Eylül %1,84, Ekim %2,58) zincirlenmiştir. Ocak–Mayıs 2026 için hakedis.org'daki zincirlenmiş değerlerle %0,05 içinde uyumlu. TMS 29 düzeltmesinde yalnızca endeks oranları kullanıldığından taban değişikliği sonucu etkilemez.

## USD/TRY (`makro_ceyrek.csv`)
TCMB gösterge niteliğindeki döviz alış kuru, çeyreğin son iş günü (TCMB kurlar arşivi XML). 31.03.2025 tatil olduğu için 28.03.2025 kullanıldı.

## BİM Birleşik Mağazalar (`kap/BIMAS_*.csv`)
- Gelir tablosu, nakit akış ve bilanço kalemleri ekofin.net BIMAS sayfalarından (kümülatif, her rapor kendi tarihinin TL'siyle, TL cinsinden) aktarıldı.
- "Esas Faaliyet Karı" satırına kaynaktaki "Faaliyet Karı (Zararı)" yazıldı.
- "Kısa / Uzun Vadeli Borçlanmalar" satırlarına kaynaktaki "Finansal Borçlar" (kiralama yükümlülükleri dahil) yazıldı.
- 2026-09 bilançosu kaynakta yoktu; değerlemede net borç için en son bilanço (2026-06) TÜFE ile 2026-09 TL'sine taşındı.
- Doğrulama: 9 aylık 2026 ana ortaklık net kârı (26.151.834 bin TL) ve hasılat (720.477.782 bin TL) CNBC-e haberindeki rakamlarla aynı.
- Hisse sayısı 1,2 milyar (ödenmiş sermaye 1,2 milyar TL); fiyat 402,50 TL (16.11.2026 12:54, en az 15 dk gecikmeli, uzmanpara).

## Ana bulgu
Basında BİM'in 2026 3. çeyrek net kârı olarak verilen 10.385.559 bin TL, 9 aylık (26.151.834) ile 6 aylık (15.766.411) kârın düz farkıyla birebir aynıdır. TMS 29 ile tutarlı hesap (6 aylık rakamın Eylül TL'sine taşınması) yaklaşık 9,51 milyar TL verir; düz fark %9,2 yüksektir. Şirketin KAP'taki kendi "3 aylık" sütunuyla teyit edilmelidir.

## Diğer şirketler (TCELL, FROTO, TUPRS, ASELS, MGROS, ARCLK, ULKER)
- Gelir tablosu satırları ekofin.net şirket sayfalarından (18.11.2026) aktarıldı: Satış Gelirleri, Satışların Maliyeti, Ticari Faaliyetlerden Brüt Kar (yoksa Brüt Kar), Faaliyet Karı, Net Parasal Pozisyon, Vergi Öncesi Kar, Dönem Karı, Ana Ortaklık Payları. Kümülatif, her rapor kendi tarihinin TL'siyle.
- TUPRS ve ULKER için kaynakta 2026/09 henüz yoktu; son dönem 2026/06.
- TCELL'de bazı dönemlerde Satışların Maliyeti satırı boş; brüt kâr kaynaktaki değerdir.
- Bu şirketlerde bilanço ve nakit akış satırları aktarılmadı (yalnızca tarama için gelir tablosu). Otomatik güncelleme çalıştığında tüm sayfalar okunur.

## Otomatik kaynak
`kapsam/data/sources.py` aynı sayfaları herhangi bir hisse için okur (`python -m kapsam.cli analiz HISSE`) ve her iş günü takip listesindeki hisseler için yeni dönemleri kaydeder. Kaynak yalnızca son 5 dönemi gösterir; KAPSAM eski dönem dosyalarının üzerine yazmadığı için geçmiş zamanla birikir. Kaynağın kullanım koşullarına uyun; ticari kullanımda lisanslı veri sağlayıcıya geçin.

## Hisse evreni (v0.9)
`config/bist_evren.csv`: İş Yatırım "Temel Değerler ve Oranlar" sayfası (https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/Temel-Degerler-Ve-Oranlar.aspx). Kod, ad, sektör, kapanış (TL), piyasa değeri (mn TL), sermaye. İlk otomatik çalıştırmada oluşur, her gün yenilenir. Sektör adından tablo türü çıkarılır: "banka" → banka, "sigorta/emeklilik" → sigorta, diğerleri → sanayi.

## Banka ve sigorta tabloları (v0.9)
Banka (BDDK) ve sigorta (SEDDK) tablo biçimleri aynı kaynaktan okunur (ör. https://www.ekofin.net/sirket/detay/AKBNK/gelir-tablosu, https://www.ekofin.net/sirket/detay/AKBNK/bilancolar, https://www.ekofin.net/sirket/detay/AKGRT/gelir-tablosu). Bu şirketler TMS 29 uygulamadığı için çeyrekler düz farkla bulunur; testler gerçek sayfa düzeniyle yazılmıştır (`tests/test_sources.py`).

## Takip listesi, olaylar ve ilişki ağı (v0.9)
- BIST-30 bileşimi (Ekim–Aralık 2026): https://borsapusula.com/blog/bist30-hisseleri-2026, https://www.paraanaliz.com/haberler/borsa-istanbul-2026-4-ceyrek-endeks-degisikliklerini-acikladi-bist-30-bist-50-ve
- Olaylar: her birinin KAP bildirimi (kap.org.tr/…/BildirimPdf/…) ya da haber kaynağı `config/takip.json` içinde `kaynak` alanındadır.
- Ortaklık oranları: KAP ortaklık tablolarını aktaran endeks24.com yazıları, Anadolu Efes ortaklık yapısı belgesi, CNBC-e (Petkim/SOCAR). Her ilişkinin kaynağı `data/gercek/ag.json` içindedir. Tofaş (2024) ve THY (2020) tabloları eski tarihlidir; değişirse güncelleyin.
- Doğrulanamadığı için eklenmeyenler: Ülker–BİM tedarik ilişkisi, Tüpraş–Petkim nafta tedariki (Petkim'in hammaddesini STAR rafinerisi sağlıyor), TRMET–TRALT ortaklık oranı. Yıldız Holding Ülker paylarının tamamını Aralık 2024'te satmıştır.
