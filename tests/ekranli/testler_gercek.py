#!/usr/bin/python3
"""Deskhand GERÇEK DÜNYA testleri: gerçek internet siteleri (hız/gecikme/değişen sayfa) + gerçek masaüstü.
Aile ortamına uygun siteler (Vikipedi, DuckDuckGo güvenli arama, Kitapyurdu). Hiçbir şey satın alınmaz,
sepete eklenmez, çerez onayı verilmez. Tarayıcı: her senaryo AYRI bir Firefox örneği (kendi geçici profili,
firefox_test.py); kullanıcının Firefox'una/profiline dokunulmaz, sonunda yalnız o örnek (kendi PID'i) kapatılır.
Komutlar çoğunlukla İngilizce adlarıyla; bazı adımlar Türkçe takma adlarla (ikisi de sınanır).

Çalıştır:  python3 tests/ekranli/testler_gercek.py   (~2-3 dk; bu sırada klavye/fareye dokunma —
dokunursan araç 'insan önceliği' ile durur, o test KALIR, sorun değil)"""
import re
import subprocess
import sys
import time

import ortak  # DESKHAND_* geçici klasörler + deskhand komutu (Deskhand'den ÖNCE içe aktarılır)
from deskhand import yollar  # noqa: F401
import firefox_test

SONUC = []


def e(*a):
    t = time.monotonic()
    r = subprocess.run([*ortak.EKRAN, *a], capture_output=True, text=True)
    ortak.kod12_bildir(r.returncode, a)
    return r.returncode, r.stdout + r.stderr, time.monotonic() - t


def kontrol(ad, kosul, ayrinti=""):
    SONUC.append((ad, bool(kosul)))
    print(f"{'GEÇTİ ' if kosul else 'KALDI!'} {ad}" + (f"  [{ayrinti}]" if ayrinti else ""), flush=True)


def pencere_bekle(desen, sure=20):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        out = ortak.ara(desen)
        if out:
            return out[0]
        time.sleep(0.2)
    return None


def baslik(k):
    return ortak.baslik(k)


def baslik_bekle(k, desen, sure=20):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        if re.search(desen, baslik(k), re.I):
            return True
        time.sleep(0.2)
    return False


def tarayici(url, desen):
    """Ayrı Firefox örneği (kendi profili) → (TestFirefox, kimlik | None). Pencere PID ile bizim olmalı."""
    ff = firefox_test.TestFirefox(url, desen, konum=None)
    return ff, ff.ac()


def tarayici_kapat(ff):
    print("   ", ff.kapat())
    kalan = ff.bizim_pencereler()
    kontrol("   test Firefox'u kapandı (yalnız kendi PID'i)", not kalan, f"kalan {kalan}")


def vikipedi():
    t0 = time.monotonic()
    ff, K = tarayici("https://tr.wikipedia.org/wiki/Ankara", "Ankara - Vikipedi")
    kontrol("Vikipedi: sayfa açıldı (ağ, ayrı Firefox örneği)", K, f"{time.monotonic() - t0:.1f} sn")
    try:
        if not K:
            return
        kod, out, t = e("wait", K, "vikipedi üzerinde ara", "--timeout", "15", "--stay")
        kontrol("Vikipedi: arama kutusu yüklendi (wait)", kod == 0, f"{t:.1f} sn")
        kod, out, t = e("-b", "Vikipedi", "click-text", K, "vikipedi üzerinde ara")
        e("-b", "Vikipedi", "type", K, "Kapadokya")
        e("-b", "Vikipedi", "key", K, "Return")
        ok = baslik_bekle(K, "^Kapadokya - Vikipedi")
        kontrol("Vikipedi: Türkçe arama → madde", ok, baslik(K))
        kod, out, t = e("-b", "Kapadokya - Vikipedi", "click-text", K, "Göreme")
        kontrol("Vikipedi: iki 'Göreme' → belirsiz, tıklamaz (5)", kod == 5, f"kod {kod}")
        kod, out, t = e("-b", "Kapadokya - Vikipedi", "metne-tikla", K, "Göreme", "--sira", "1")  # Türkçe ad
        ok = baslik_bekle(K, "Göreme")
        kontrol("Vikipedi: metne-tikla --sira 1 (Türkçe) → doğru bağlantı", kod == 0 and ok, baslik(K))
        kod, out, t = e("-b", "Göreme", "click-text", K, "Kaynakça", "--scroll-search", "25", "--region", "300,0,1100,1000")
        n = re.search(r"# (\d+) kez", out)
        kontrol("Vikipedi: --scroll-search 'Kaynakça' (içerik sütunu)", kod == 0, f"{t:.1f} sn, {n.group(1) if n else 0} kaydırma")
    finally:
        tarayici_kapat(ff)


def duckduckgo():
    t0 = time.monotonic()
    ff, K = tarayici("https://html.duckduckgo.com/html/?kp=1&kl=tr-tr", "DuckDuckGo")
    kontrol("DuckDuckGo: sayfa açıldı (ağ, güvenli arama kp=1)", K, f"{time.monotonic() - t0:.1f} sn")
    try:
        if not K:
            return
        e("wait", K, "DuckDuckGo", "--timeout", "15", "--stay")
        # arama kutusu sayfa açılınca odakta (autofocus): doğrudan yaz
        kod, out, t = e("-b", "DuckDuckGo", "yaz", K, "Ankara Kocatepe Camii vikipedi")  # Türkçe ad
        e("-b", "DuckDuckGo", "tus", K, "Return")  # Türkçe ad
        ok = baslik_bekle(K, "Kocatepe Camii vikipedi at DuckDuckGo")
        kontrol("DuckDuckGo: Türkçe sorgu (yaz/tus) → sonuç sayfası", ok, baslik(K))
        kod, out, t = e("bekle", K, "Kocatepe Camii", "--sure", "15", "--kal")  # Türkçe ad + seçenekler
        kontrol("DuckDuckGo: sonuç başlığı okundu (bekle --sure --kal)", kod == 0, f"{t:.1f} sn")
        kod, out, t = e("-b", "DuckDuckGo", "click-text", K, "Kocatepe Camii Vikipedi")
        ok = baslik_bekle(K, "Kocatepe Camii - Vikipedi")
        kontrol("DuckDuckGo: sonuca tıkla → Vikipedi maddesi", kod == 0 and ok, baslik(K))
    finally:
        tarayici_kapat(ff)


def kitapyurdu():
    t0 = time.monotonic()
    ff, K = tarayici("https://www.kitapyurdu.com/index.php?route=product/search&filter_name=suç ve ceza dostoyevski",
                     "Arama Sonuçları")
    kontrol("Kitapyurdu: arama sayfası açıldı (ağ)", K, f"{time.monotonic() - t0:.1f} sn")
    try:
        if not K:
            return
        kod, out, t = e("wait", K, "ürün listelendi", "--timeout", "20", "--stay")
        kontrol("Kitapyurdu: 'ürün listelendi' (wait)", kod == 0, f"{t:.1f} sn")
        # DİKKAT: aynı yazı ilk ekranda 'Arama Önerileri' bağlantısında da var (araç bir kez oraya tıkladı,
        # test gevşek başlık denetimiyle geçmişti) → önce ürün listesine kaydır, ürün sayfasını 'Fiyatı' ile doğrula
        e("-b", "Arama Sonuçları", "scroll", K, "down", "6")
        time.sleep(0.8)
        kod, out, t = e("-b", "Arama Sonuçları", "click-text", K, "Suç ve Ceza 1.Cilt")
        ok = baslik_bekle(K, "Suç ve Ceza 1.Cilt.*Fiyatı")
        kontrol("Kitapyurdu: ürün sayfası (başlıkta 'Satın Al' var, sayfa kilidi tetiklenmedi)", kod == 0 and ok, f"kod {kod}")
        kod, out, t = e("read", K, "Sepete Ekle", "--stay")
        kontrol("Kitapyurdu: turuncu 'Sepete Ekle' okundu (yedek okuma)", kod == 0, f"{t:.1f} sn")
        kod, out, t = e("metin", K, "--kal")  # Türkçe ad; fiyat değişir → biçimle ara
        fiyat = re.search(r"\b\d{2,4},\d\d\b", out)
        kontrol("Kitapyurdu: fiyat okundu (sayı,kuruş biçimi)", kod == 0 and fiyat, fiyat.group(0) if fiyat else out[-60:])
    finally:
        tarayici_kapat(ff)


def masaustu():
    kod, out, t = e("read", "ekran", "--region", "2310,1386,140,54")
    saat = re.search(r"\] (\d\d:\d\d)$", out, re.M)
    kontrol("Masaüstü: panel saati okundu, odak çalınmadı", kod == 0 and saat, saat.group(1) if saat else out[-80:])
    onceki = ortak.aktif()
    e("key", "ekran", "alt+space")
    time.sleep(0.8)
    kod, out, t = e("--class", "krunner", "type", "ekran", "Dolphin")
    kontrol("Masaüstü: KRunner'a type (--class krunner)", kod == 0, f"kod {kod}")
    if kod != 0:
        e("-s", "krunner", "tus", "ekran", "Escape")
        return
    e("-s", "krunner", "tus", "ekran", "Return")
    D = pencere_bekle("— Dolphin", 10)
    kontrol("Masaüstü: KRunner → Dolphin açıldı", D)
    if D:
        kod, out, t = e("metin", D, "Masaüstü", "--kal")
        kontrol("Masaüstü: Dolphin'de 'Masaüstü' okundu", kod == 0)
        print("   ", e("-b", "Dolphin", "kapat", D)[1].strip())
    kod, out, t = e("metne-tikla", "ekran", "\\d\\d\\.\\d\\d\\.20\\d\\d" if False else time.strftime("%d.%m.%Y"),
                    "--bolge", "2310,1386,140,54")
    time.sleep(0.8)
    kod2, out2, _ = e("metin", "ekran", time.strftime("%B") if False else "Bugün", "--bolge", "1900,700,660,686")
    kontrol("Masaüstü: panel saatine tıkla → takvim açıldı", kod == 0 and kod2 == 0, f"kod {kod}/{kod2}")
    e("-s", "plasmashell", "tus", "ekran", "Escape")
    # yazısız SİMGE: panel başlatıcısı (kayıtlı değilse kaydet) → bul → tıkla → menü açıldı mı → Escape
    import os
    if not os.path.exists(os.path.join(yollar.simge_dizin(), "panel-baslatici.png")):
        e("simge-kaydet", "ekran", "panel-baslatici", "--bolge", "20,1394,30,30")
    kod, out, t = e("find-icon", "ekran", "panel-baslatici")
    kontrol("Masaüstü: panel başlatıcı SİMGESİ bulundu", kod == 0, out.strip().splitlines()[-1][:60] if out.strip() else "")
    kod, out, t = e("click-icon", "ekran", "panel-baslatici")
    time.sleep(1.0)
    kod2, out2, _ = e("metin", "ekran", "Tüm Uygulamalar", "--bolge", "0,700,900,686")
    kontrol("Masaüstü: simgeye tıkla → başlatıcı menüsü açıldı", kod == 0 and kod2 == 0, f"kod {kod}/{kod2}")
    e("-s", "plasmashell", "tus", "ekran", "Escape")
    # terminale/önceki pencereye dön
    ortak.kd("windowactivate", onceki)


def main():
    t0 = time.monotonic()
    secili = sys.argv[1:] or ["vikipedi", "duckduckgo", "kitapyurdu", "masaustu"]
    for senaryo in (globals()[a] for a in secili):
        print(f"\n== {senaryo.__name__}")
        try:
            senaryo()
        except Exception as ex:
            kontrol(f"{senaryo.__name__}: beklenmedik hata", False, repr(ex)[:120])
    gecen = sum(1 for _, ok in SONUC if ok)
    print(f"\n{gecen}/{len(SONUC)} gerçek dünya testi geçti ({time.monotonic() - t0:.0f} sn)")
    sys.exit(0 if gecen == len(SONUC) else 1)


if __name__ == "__main__":
    main()
