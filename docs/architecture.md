# KAPSAM Mimarisi

```mermaid
flowchart LR
  subgraph Girdi
    KAP[KAP bildirimleri<br/>ve finansal tablolar]
    EVDS[TCMB EVDS<br/>TÜFE, USD/TRY]
    TEZ[Analist tezi<br/>ve takip listesi]
  end
  subgraph Islem[İşlem]
    ING[Veri içe aktarma<br/>ve kalem eşleme]
    T29[TMS 29 motoru<br/>çeyrek, reel, USD, temel kâr]
    VAL[Sayısal doğrulama]
    CLS[Bildirim sınıflandırıcı<br/>ve önem skoru]
    KG[Bilgi grafiği<br/>ilişki çıkarımı, etki yayılımı]
    LLM[LLM özet<br/>kaynak zorunlu]
    THS[Tez motoru]
  end
  subgraph Cikti[Çıktı]
    UI[Pano ve uyarılar]
    XL[Excel/CSV/API]
  end
  KAP --> ING --> T29 --> VAL --> THS
  EVDS --> T29
  KAP --> CLS --> LLM --> VAL
  TEZ --> THS --> UI
  T29 --> XL
  CLS --> UI
  KAP --> KG --> THS
  CLS --> KG
  KG --> UI
```

## TMS 29 matematiği

- Raporlama tarihi R, TÜFE endeksi CPI olsun.
- Çeyreklik akış: `Q_R = YTD_R − YTD_{R−1} × CPI_R / CPI_{R−1}` (aynı mali yıl içinde).
- Reel seri (baz tarih B): `X_B = X_R × CPI_B / CPI_R`
- USD (TMS 21 par. 42, kapanış kuru): `X_USD = X_R / USDTRY_R`
- Temel net kâr: `NI − NMG × (1 − t)`. Burada NMG net parasal pozisyon kazancı, t ise vergi varsayımıdır.

## Yol haritası (prototip → MVP)

- [x] TMS 29 motoru ve birim testleri
- [x] Kural tabanlı bildirim sınıflandırıcı
- [x] Kaynak doğrulamalı LLM arayüzü
- [x] Streamlit panosu
- [x] Reel İNA, ters İNA, duyarlılık ve çarpanlar (v0.2)
- [x] HTML araştırma notu ve formüllü Excel modeli (v0.2)
- [x] Şirketler arası karşılaştırma (v0.2)
- [x] Bilgi grafiği: ilişki çıkarımı, etki yayılımı, benzer şirket, araştırma önceliği, sıralama metrikleri, olay çalışması (v0.3)
- [x] KG modelleri: kişiselleştirilmiş PageRank, TransE, CAR'dan katsayı kalibrasyonu, bootstrap ile model karşılaştırma (v0.4)
- [x] Otomatik gerçek veri hattı: EVDS, piyasa fiyatları, KAP dosyaları, zamanlanmış GitHub Actions, durum sayfası (v0.5)
- [x] Gerçek KAP Excel düzeni, 3 aylık çapraz kontrol, nakit akışından satış/sermaye, `kap-ekle` (v0.6)
- [x] İlk gerçek veri: BİM 2025/09–2026/09, gerçek TÜFE ve TCMB kurları; ters İNA ile fiyatlanan marj (v0.7)
- [x] Herhangi bir hisse için tablo kaynağı, birikimli geçmiş, `analiz` ve `tarama`; 8 şirketle gerçek tarama (v0.8)
- [x] Tüm BIST: otomatik evren, banka/sigorta tablo biçimleri (nominal mod), akıllı rapor takvimi, günlük limit, aranabilir tarama sayfası, finansal sektör notu (v0.9)
- [ ] Tüm BIST'te ilk tam tur sonrası doğrulama (ilk hafta)
- [ ] Gerçek ilişki ağı: faaliyet raporları ve KAP "yeni iş ilişkisi" bildirimlerinden
- [ ] KAP bildirimlerinin otomatik toplanması (zamanlanmış görev)
- [ ] XBRL doğrudan okuma
- [ ] 1.000 etiketli bildirimle sınıflandırıcı ince ayarı
- [ ] Sektör medyanlarıyla göreli değerleme
