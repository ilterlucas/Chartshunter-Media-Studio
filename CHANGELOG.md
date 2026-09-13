# v42

- Çoklu link kutusunda indirme durumu doğrudan satır üzerinde gösteriliyor.
- Başarıyla indirilen linkler **yeşil** işaretleniyor.
- İndirilemeyen linkler **kırmızı ve üstü çizili** gösteriliyor.
- O anda işlenen link sarı tonla işaretleniyor; iptal edilen/yarım kalan link gri gösteriliyor.
- Link kutusunun altında canlı özet eklendi: indirildi / indirilemedi / işleniyor / bekliyor.
- Renklendirme yalnız link satırına uygulanıyor; grup başlıkları ve açıklama satırları değişmiyor.
- Yeni bir indirme turu başlatıldığında eski durum işaretleri sıfırlanıyor.
- v41'deki VK fail-fast, Brave öncelikli çerez seçimi, Video X/Y ilerlemesi ve parça birleştirme kurtarma akışı korunuyor.

# v41

- VK/VK Video erişilemeyen veya private linklerde uzun tekrar döngüsü azaltıldı; net erişim hatasında link atlanıp sıradaki videoya geçiliyor.
- CLI tabanlı fallback motorlarına gerçek zaman aşımı eklendi; çıktı üretmeyen süreç artık indirme kuyruğunu kilitlemiyor.
- MP4 seçiminde AVC/H.264 + AAC/M4A kombinasyonları önceliklendirildi.
- Video ve ses ayrı indirilip normal birleşim başarısız olursa FFmpeg ile üç aşamalı parça kurtarma/birleştirme eklendi.
- Tarayıcı çerezleri alanı ayrı ve görünür bir karta taşındı.
- Brave çerez desteği eklendi. Varsayılan seçim **Otomatik (Brave öncelikli)**.
- Çoklu indirmede ilerleme panelinde **Video X/Y** ayrı ve belirgin gösteriliyor.

# v40 Stable

- Açılış warm-up kurulumu kaldırıldı; ilk oturumda yalnızca update metadata kontrolü yapılıyor.
- Eksik paket/model/sistem aracı artık kullanım anında kullanıcı onayıyla hazırlanıyor.
- Hızlı + Zorlayıcı Açık + Adult/video-host Açık varsayılanları korundu.
