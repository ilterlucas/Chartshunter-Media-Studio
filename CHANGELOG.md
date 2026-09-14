# v43

- Tarayıcı çerezleri sistemi yeniden düzenlendi; varsayılan artık **Akıllı (önerilen - gerektiğinde çerez)**.
- Normal/public videolarda tarayıcı cookie veritabanı artık her linkte okunmuyor. İlk deneme çerezsiz yapılıyor; bu özellikle çoklu indirmede gereksiz gecikmeyi azaltır.
- Yalnız 403, giriş/oturum, yaş doğrulama, private/member/cookie uyarısı gibi durumlarda bir kez tarayıcı çereziyle tekrar deneme yapılıyor.
- Akıllı retry gerektiğinde tarayıcı sırası: **Brave → Chrome → Edge → Firefox**.
- İsteyen kullanıcı Brave/Chrome/Edge/Firefox'u **her linkte zorla kullan** şeklinde manuel seçebiliyor.
- Tarayıcı çerezi seçimi artık link kutusunun hemen altında, her ekran boyutunda daha görünür konumda.
- v42'nin yeşil başarılı / kırmızı üstü çizili başarısız link gösterimi korunuyor.
- v41'in VK fail-fast, Video X/Y, parça birleştirme kurtarma ve fallback motorları korunuyor.

# v42

- Çoklu link kutusunda indirme durumu doğrudan satır üzerinde gösteriliyor.
- Başarıyla indirilen linkler yeşil; indirilemeyen linkler kırmızı ve üstü çizili.
- O anda işlenen link sarı, iptal edilen/yarım kalan link gri gösteriliyor.
- Link kutusunun altında canlı durum özeti eklendi.

# v41

- VK/VK Video erişilemeyen veya private linklerde uzun tekrar döngüsü azaltıldı.
- Ayrı video/ses parçaları için FFmpeg kurtarma/birleştirme eklendi.
- Brave çerez desteği ve Video X/Y göstergesi eklendi.

# v40 Stable

- Açılış warm-up kurulumu kaldırıldı; ilk oturumda yalnız update metadata kontrolü yapılıyor.
- Hızlı + Zorlayıcı Açık + Adult/video-host Açık varsayılanları korundu.
