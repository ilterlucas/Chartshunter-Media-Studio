# Chartshunter Media Studio

**Current stable release: v40 Stable**

Windows için medya indirme, altyazı üretme, British UK TTS, MP3 birleştirme ve MP3 + kapak görselinden video üretme uygulaması.

## Hızlı kullanım

1. **Releases** bölümünden en son Windows Stable paketini indir.
2. ZIP'i normal bir klasöre çıkar.
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

`%LOCALAPPDATA%\\ChartshunterMediaStudio`
