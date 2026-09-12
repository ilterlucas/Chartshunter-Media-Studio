# Publishing

Stable release workflow iki şekilde çalışır:

1. GitHub Actions > Build Windows Stable Release > Run workflow: EXE + ZIP artifact üretir.
2. `v40` gibi bir tag push edildiğinde aynı paketleri GitHub Release olarak yayımlar.

Yeni stable sürüm için `BUILD_INFO.json`, `CHANGELOG.md` ve uygulama sürümünü güncelle; ardından tag oluştur.
