# Publishing

Chartshunter Media Studio Stable sürümleri GitHub Actions ile otomatik paketlenir.

## Stable yayın akışı

`.github/workflows/release.yml`:

1. Python kaynaklarını compile kontrolünden geçirir.
2. `src/self_test.py` regresyon testlerini çalıştırır.
3. Windows GUI launcher'larını derler.
4. Windows dağıtım klasörünü hazırlar.
5. SHA256 doğrulama dosyasını üretir.
6. ZIP paketini oluşturur.
7. Workflow artifact'ını yükler.
8. Stable GitHub Release'ını oluşturur veya günceller.

v42 release asset'leri:

- `ChartshunterMediaStudio_v42_Stable.zip`
- `Chartshunter.Media.Studio.exe`
- `Repair.Update.exe`
- `SHA256SUMS.txt`
