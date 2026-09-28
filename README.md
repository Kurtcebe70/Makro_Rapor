# Makro Rapor — Kişisel Günlük Makro Pano

Her hafta içi sabah 05:30 (TSİ) kendiliğinden çalışır. ABD makro verisini çeker, kendi kurallarınla puanlar, Claude'a yorum yazdırır ve raporu web sayfası olarak yayınlar. Bu sayfaya telefondan da bakabilirsin.

**Maliyet:** GitHub ve veri kaynakları ücretsiz. Claude yorumu isteğe bağlı: Sonnet 5 ile rapor başına yaklaşık 1–2 cent, ayda 0,5 $ civarı. API anahtarı eklemezsen rapor kural tabanlı şablon metinle yine üretilir.

---

## Nasıl çalışır?

```
FRED + Yahoo Finance ──► analyze.py (tüm sayılar, sabit kurallar)
                                  │
                                  ├─► narrative.py (Claude sadece bu sayıları yorumlar)
                                  ▼
                         render.py ──► docs/index.html + docs/arsiv/
```

- **Rakamları sadece kod üretir.** Claude'a sayı uydurmaması, haber veya olay eklememesi talimatı verilir.
- **Rejim skoru (0–100):** `config.yaml` içindeki her sinyal yeşil (+1), sarı (0) veya kırmızı (−1) puan alır. Bu puanlar 4 ayakta toplanır: Faiz Baskısı, Kredi & Likidite, Risk İştahı ve Enflasyon Riski.
- **Senaryolar:** "10 yıllık faiz 5,30'u aşarsa" gibi eşikler. Rapor her senaryoya olan mesafeyi gösterir.
- **Portföy bölümü:** MODEL V7.0 adayları için şunları gösterir: 200 günlük ortalama, zirveden düşüş, RSI, SPY'ye göre performans ve geri çekilme bölgesi işareti.
- **Teknik görünüm (MarketPulse benzeri):** Bu bölüm 0–100 arası bir teknik sağlık skoru üretir. Skor altı ayaktan oluşur: Trend, Momentum, Genişlik, Bilanço, Rotasyon ve Duyarlılık. Ayrıca şunları içerir:
  - Endeks tablosu: SPY, QQQ, DIA, IWM, RSP ve SMH için 10/21/50/200 günlük ortalamalar ve Weinstein evresi
  - Hareketli ortalamalı grafikler ve otomatik "okuma" metni
  - Rotasyon radarı: sektör ve tema ETF'lerinin SPY'ye göre lider, güçlenen, zayıflayan veya geride olması
  - İşlem hacmi paneli
  - Momentum faktör stresi (MTUM/SPY oynaklık oranı)
  - VIX vade yapısı
  - Opsiyon vadesi ve FOMC takvimi
  - Bilanço sezonu paneli
  - "Bugünün izleme sırası" listesi
- **Önceki rapordan bu yana:** Her gün `data/history.json` dosyasına kayıt atılır. Sinyal renk değişimleri otomatik listelenir.

## Kurulum (bir kerelik, ~10 dakika)

### 1. GitHub deposu oluştur
1. [github.com](https://github.com) üzerinde ücretsiz hesap aç (yoksa).
2. Sağ üstte **+ → New repository** seç. Ad olarak örneğin `makro-rapor` yaz. **Public** seç (ücretsiz GitHub Pages için gerekli, aşağıdaki nota bak) ve **Create** de.
3. Açılan sayfada **uploading an existing file** bağlantısına tıkla. Bu zip'in içindeki **tüm dosya ve klasörleri** sürükle bırak ve **Commit changes** de.
   > `.github` klasörü gizli klasördür. Görünmüyorsa Mac'te Finder'da `Cmd+Shift+.` ile göster. Yüklendiğinden emin ol, otomasyon bu klasörde.

### 2. Claude API anahtarını ekle (isteğe bağlı ama önerilir)
1. [console.anthropic.com](https://console.anthropic.com) → **API Keys** → yeni anahtar oluştur. Birkaç dolar kredi yükle.
2. GitHub deposunda **Settings → Secrets and variables → Actions → New repository secret** yolunu izle.
   - Name: `ANTHROPIC_API_KEY`
   - Secret: anahtarın

### 3. Yazma iznini aç
**Settings → Actions → General → Workflow permissions** bölümünde **Read and write permissions** seç ve **Save** de.

### 4. İlk raporu üret
**Actions** sekmesi → **Günlük Makro Rapor** → **Run workflow**. Yaklaşık 1–2 dakika sürer.

### 5. Sayfayı yayına al
**Settings → Pages** bölümünde:
- Source: **Deploy from a branch**
- Branch: `main`, klasör: `/docs`

Kaydet. Bir dakika içinde raporun `https://KULLANICI-ADIN.github.io/makro-rapor/` adresinde yayında olur. Telefonda ana ekrana eklemeni öneririm.

> **Gizlilik notu:** Ücretsiz GitHub Pages yalnızca public depolarda çalışır. Adresi bilen herkes raporu görebilir. Raporda kişisel pozisyon miktarı yok, sadece izlediğin hisseler var. Tamamen gizli istersen depoyu Private yap ve raporu `docs/index.html` dosyasından indirip aç.

---

## Günlük kullanım

| Ne yapmak istiyorsun? | Nereyi düzenle |
|---|---|
| Eşikleri değiştirmek (örn. 10Y kırmızı eşiği 5,00 → 4,80) | `config.yaml` → `sinyaller` |
| Senaryo eklemek/değiştirmek | `config.yaml` → `senaryolar` |
| Hisse eklemek/çıkarmak | `config.yaml` → `portfoy.hisseler` |
| DCA kural metnini yazmak | `config.yaml` → `portfoy.dca_kurallari` |
| Yeni FRED göstergesi eklemek | `config.yaml` → `gostergeler` (FRED kodu sitede serinin adının yanında yazar) |
| FedWatch olasılıkları, haftalık takvim notu | `manuel.yaml` |
| Bilanço sezonu rakamları (FactSet, haftada bir) | `manuel.yaml` → `bilanco` |
| Rotasyon radarındaki ETF'ler, sağlık skoru ağırlıkları, momentum stres eşikleri | `config.yaml` → `teknik` |

Dosyaları GitHub'ın web arayüzünden, kalem simgesine basarak düzenleyebilirsin. Değişiklik ertesi sabahki raporda görünür. Hemen görmek istersen **Run workflow** ile raporu elle çalıştır.

## Bilgisayarında çalıştırmak (isteğe bağlı)

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # isteğe bağlı
python run.py                       # docs/index.html oluşur
```

## Bilinen sınırlar

- **Veri gecikmesi:** FRED'deki günlük faiz serileri 1–2 gün gecikmeli gelir. 10 yıllık faiz için daha güncel olan Yahoo `^TNX` kullanılır. Aylık veriler (TÜFE, istihdam vb.) yayın takvimine bağlıdır. Beklenenden eskiyse raporda **bayat** etiketi çıkar.
- **FedWatch ve takvim** ücretsiz API ile alınamıyor. `manuel.yaml` dosyasından elle girilir. Ücretli sitede de elle giriliyor.
- **Dealer gamma** ücretli veri olduğu için dahil değil.
- **Genişlik** S&P 500'ün 500 hissesi yerine 11 sektör ETF'i, RSP ve IWM üzerinden ölçülür. Bu hızlı ve ücretsiz bir yaklaşım, ama hisse bazlı ölçümden daha kaba.
- **Bilanço verisi** (FactSet) ücretsiz bir API'den alınamıyor, `manuel.yaml` dosyasından elle girilir. Boş bırakılırsa sağlık skoru bilanço ayağı olmadan hesaplanır.
- **Rotasyon radarı** JdK RS-Ratio'nun basitleştirilmiş bir versiyonudur. Göreli güç 50 günlük ortalamasıyla ve 10 günlük değişimiyle hesaplanır.
- **Zamanlama:** GitHub zamanlanmış görevleri yoğun saatlerde 10–30 dakika gecikebilir.
- Rapor kişisel kullanım içindir, yatırım tavsiyesi değildir.
