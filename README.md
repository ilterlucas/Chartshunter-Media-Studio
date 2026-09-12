# Chartshunter Media Studio

**Current stable release: v40 Stable**

[![Windows](https://img.shields.io/badge/Windows-10%2F11-blue)](https://github.com/ilterlucas/Chartshunter-Media-Studio/releases/tag/v40)
[![Release](https://img.shields.io/badge/release-v40%20Stable-brightgreen)](https://github.com/ilterlucas/Chartshunter-Media-Studio/releases/tag/v40)
[![Build](https://github.com/ilterlucas/Chartshunter-Media-Studio/actions/workflows/release.yml/badge.svg)](https://github.com/ilterlucas/Chartshunter-Media-Studio/actions/workflows/release.yml)

Windows için medya indirme, altyazı üretme, British UK TTS, MP3 birleştirme ve MP3 + kapak görselinden video üretme uygulaması.

## İndir

**Önerilen paket:** [ChartshunterMediaStudio_v40_Stable.zip](https://github.com/ilterlucas/Chartshunter-Media-Studio/releases/download/v40/ChartshunterMediaStudio_v40_Stable.zip)

Tüm v40 dosyaları ve SHA256 doğrulaması için: [v40 Stable Release](https://github.com/ilterlucas/Chartshunter-Media-Studio/releases/tag/v40)

## Hızlı kullanım

1. Stable ZIP paketini indir.
2. ZIP'i normal bir klasöre tamamen çıkar.
3. **Chartshunter Media Studio.exe** dosyasını aç.
4. Kullanacağın sekmeyi seç.

Uygulama açılışta ağır bileşenleri topluca kurmaz. İlk oturumda yalnız güncelleme verilerini kontrol eder; Whisper, Chromium ve diğer büyük bileşenler gerektiğinde seçenek olarak sunulur.

## v40 varsayılan indirme ayarları

- Motor: **Auto+**
- Kalite: **MP4 1080p**
- Hız: **Hızlı**
- Zorlayıcı mod: **Açık**
- Adult/video-host uyum modu: **Açık**

> Yalnız erişim ve kullanım hakkın olan içeriklerde kullan. DRM, ödeme duvarı veya erişim kontrolünü aşmak için tasarlanmamıştır.

## Kaynak yapısı

- `src/` — Python uygulama kaynakları
- `launcher/` — hafif Windows launcher kaynakları
- `chrome_capture_extension/` — yardımcı Chrome eklentisi
- `.github/workflows/release.yml` — Windows EXE + ZIP oluşturur ve GitHub Release yayımlar
- `docs/` — kısa kullanım ve test notları

## Gereksinim

Ana launcher, Windows üzerinde Python 3.11+ bulduğunda uygulamayı açar. Ağır Python paketleri yalnız ilgili özellik kullanıldığında hazırlanır.

Ortak cache/runtime:

`%LOCALAPPDATA%\ChartshunterMediaStudio`
