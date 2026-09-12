# Publishing

Chartshunter Media Studio Stable sürümleri GitHub Actions ile otomatik paketlenir.

## v40 düzeni

`.github/workflows/release.yml`:

1. Python kaynaklarını syntax/compile kontrolünden geçirir.
2. Go tabanlı Windows GUI launcher'larını derler.
3. Windows dağıtım klasörünü hazırlar.
4. SHA256 doğrulama dosyasını üretir.
5. ZIP paketini oluşturur.
6. Workflow artifact'ını yükler.
7. `v40` GitHub Release'ını oluşturur veya mevcut asset'leri günceller.

Release asset'leri:

- `ChartshunterMediaStudio_v40_Stable.zip`
- `Chartshunter.Media.Studio.exe`
- `Repair.Update.exe`
- `SHA256SUMS.txt`

## Sonraki stable sürüm

Yeni stable sürümde uygulama sürümü, `BUILD_INFO.json`, `CHANGELOG.md` ve workflow içindeki release/tag adları birlikte güncellenmelidir. Kaynak değişiklikleri önce test edilmeli; stable tag/release yalnız doğrulama tamamlandıktan sonra yayınlanmalıdır.
