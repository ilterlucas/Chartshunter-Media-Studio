# v41

- VK/VK Video erişilemeyen veya private linklerde uzun tekrar döngüsü azaltıldı; net erişim hatasında link atlanıp sıradaki videoya geçiliyor.
- CLI tabanlı fallback motorlarına gerçek zaman aşımı eklendi; çıktı üretmeyen süreç artık indirme kuyruğunu kilitlemiyor.
- yt-dlp tek link modunda hatayı gizlemek yerine erişim hatasını yakalıyor; playlist modunda hatalı öğe atlama davranışı korunuyor.
- MP4 seçiminde AVC/H.264 + AAC/M4A kombinasyonları önceliklendirildi.
- Video ve ses ayrı indirilip normal birleşim başarısız olursa FFmpeg ile üç aşamalı parça kurtarma/birleştirme eklendi.
- FFmpeg, parçalı MP4/MP3 akışında gerçekten gerektiği anda hazırlanıyor.
- Tarayıcı çerezleri alanı ayrı ve görünür bir karta taşındı.
- Brave çerez desteği eklendi. Varsayılan seçim **Otomatik (Brave öncelikli)**; profil yoksa Chrome → Edge → Firefox sırası kullanılıyor.
- Çoklu indirmede ilerleme panelinde **Video X/Y** ayrı ve kalın gösteriliyor; dosya yüzdesi toplam kuyruk yüzdesine doğru yansıtılıyor.
- v40 açılış/lazy-install davranışı, Hızlı + Zorlayıcı Açık + Adult/video-host Açık varsayımları korunuyor.

# v40 Stable

- Açılış warm-up kurulumu kaldırıldı; ilk oturumda yalnızca update metadata kontrolü yapılıyor.
- Eksik paket/model/sistem aracı artık kullanım anında kullanıcı onayıyla hazırlanıyor.
- Update varsa kullanım anında “güncelle veya mevcut sürümle devam et” seçeneği sunuluyor.
- Whisper cached model update seçimi de kullanım anına taşındı.
- Kontrol sekmesine manuel “Güncelleme Verilerini Yenile” eklendi.
- Arayüz modernleştirildi: yeni kart/header görünümü, sekmeler, butonlar, progress bar ve koyu işlem geçmişi paneli.
- Hızlı + Zorlayıcı Açık + Adult/video-host Açık varsayılanları korundu.
