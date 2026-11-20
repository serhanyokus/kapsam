# KAP finansal tabloları

KAP'ta şirketin finansal rapor bildiriminden tabloları Excel olarak indirip bu klasöre koyun.

- Dosya adını değiştirmek gerekmez. Yerelde `python -m kapsam.cli kap-ekle indirilen.xlsx --hisse THYAO` komutu dönemi dosyadan bulur ve `THYAO_2025_9.xlsx` adıyla buraya kopyalar.
- GitHub üzerinden doğrudan yüklüyorsanız adı `HISSE_YIL_AY.xlsx` yapın (ör. `THYAO_2025_9.xlsx` = 2025 9 aylık).
- Bilanço, gelir tablosu ve nakit akış aynı dosyada ayrı sayfalarda olabilir; başlık satırları ve dipnot sütunu sorun değildir.
- Çeyreklik ayrıştırma için aynı yılın önceki raporu da gerekir (ör. 2025_6 ve 2025_9).
- Dosyada "3 Aylık" sütunları varsa KAPSAM kendi hesabını bunlarla karşılaştırır ve sonucu notta gösterir.
