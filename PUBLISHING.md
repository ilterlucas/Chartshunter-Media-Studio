# Publishing

Chartshunter Media Studio Stable sürümleri GitHub Actions ile otomatik paketlenir.

## Stable yayın akışı

`.github/workflows/release.yml`:

1. Python kaynaklarını compile kontrolünden geçirir.
2. `src/self_test.py` regresyon testlerini çalıştırır.
3. Go tabanlı Windows GUI launcher'larını derler.
4. Windows dağıtım klasörünü hazırlar.
5. SHA256 doğrulama dosyasını üretir.
6. ZIP paketini oluşturur.
7. Workflow artifact'ını yükler.
8. Stable GitHub Release'ını oluşturur veya günceller.

v41 release asset'leri:

- `ChartshunterMediaStudio_v41_Stable.zip`
- `Chartshunter.Media.Studio.exe`
- `Repair.Update.exe`
- `SHA256SUMS.txt`

Yeni stable sürümde APP_VERSION, BUILD_INFO, CHANGELOG, test raporu ve workflow içindeki tag/release adları birlikte güncellenmelidir.
