# Chartshunter Media Studio

**Current stable release: v41 Stable**

[![Windows](https://img.shields.io/badge/Windows-10%2F11-blue)](https://github.com/ilterlucas/Chartshunter-Media-Studio/releases/tag/v41)
[![Release](https://img.shields.io/badge/release-v41%20Stable-brightgreen)](https://github.com/ilterlucas/Chartshunter-Media-Studio/releases/tag/v41)
[![Build](https://github.com/ilterlucas/Chartshunter-Media-Studio/actions/workflows/release.yml/badge.svg)](https://github.com/ilterlucas/Chartshunter-Media-Studio/actions/workflows/release.yml)

Windows için medya indirme, altyazı üretme, British UK TTS, MP3 birleştirme ve MP3 + kapak görselinden video üretme uygulaması.

## İndir

**Önerilen paket:** [ChartshunterMediaStudio_v41_Stable.zip](https://github.com/ilterlucas/Chartshunter-Media-Studio/releases/download/v41/ChartshunterMediaStudio_v41_Stable.zip)

Tüm v41 dosyaları ve SHA256 doğrulaması için: [v41 Stable Release](https://github.com/ilterlucas/Chartshunter-Media-Studio/releases/tag/v41)

## v41 öne çıkanlar

- VK/VK Video erişilemez linklerinde uzun tekrar döngüsünü kesip sıradaki videoya geçme.
- Video/ses ayrı parçaları indirildiğinde ek FFmpeg birleştirme/kurtarma akışı.
- Tarayıcı çerezleri alanı artık ayrı ve görünür; **Brave** eklendi.
- Varsayılan çerez seçimi **Otomatik (Brave öncelikli)**; sonra Chrome → Edge → Firefox.
- Çoklu indirmede alt panelde net **Video X/Y** göstergesi ve toplam kuyruk yüzdesi.
- v40'ın lazy kurulum ve ilk oturum update-metadata mantığı korunur.

## Hızlı kullanım

1. Stable ZIP paketini indir.
2. ZIP'i normal bir klasöre tamamen çıkar.
3. **Chartshunter Media Studio.exe** dosyasını aç.
4. Kullanacağın sekmeyi seç.

Uygulama açılışta ağır bileşenleri topluca kurmaz. İlk oturumda yalnız güncelleme verilerini kontrol eder; Whisper, Chromium ve diğer büyük bileşenler gerektiğinde seçenek olarak sunulur.

## Varsayılan indirme ayarları

- Motor: **Auto+**
- Kalite: **MP4 1080p**
- Hız: **Hızlı**
- Zorlayıcı mod: **Açık**
- Adult/video-host uyum modu: **Açık**
- Tarayıcı çerezleri: **Otomatik (Brave öncelikli)**

> Yalnız erişim ve kullanım hakkın olan içeriklerde kullan. DRM, ödeme duvarı veya erişim kontrolünü aşmak için tasarlanmamıştır.

## Kaynak yapısı

- `src/` — Python uygulama kaynakları
- `launcher/` — hafif Windows launcher kaynakları
- `chrome_capture_extension/` — yardımcı Chrome eklentisi
- `.github/workflows/release.yml` — Windows EXE + ZIP oluşturur ve GitHub Release yayımlar
- `docs/` — kısa kullanım ve test notları

Ortak cache/runtime:

`%LOCALAPPDATA%\ChartshunterMediaStudio`
