"""KDE arka ucu küçük düzeltmeler (0.9.0), EKRANSIZ:
- ekran_alani yalnız ETKİN çıkışları kapsar (kapalı çıkışın eski Geometry satırı alanı büyütüyordu);
- klavye düzeni önbelleği kxkbrc mtime'ı ile imzalı (uzun yaşayan süreç düzen değişikliğini görür);
- deskhand-etkinlik ext-idle-notify v1'e düşerse (engelleyicilerden etkilenir) izleyici yok sayılır.

Gerçek ~/.config okunmaz (HOME geçici klasöre), gerçek yardımcı çalışmaz (sahte betik).
Çalıştır:  python3 tests/test_kde_ekran_duzen.py"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _yalitim  # noqa: F401,E402

os.environ["HOME"] = os.path.join(_yalitim.GECICI, "ev")
os.makedirs(os.path.join(os.environ["HOME"], ".config"))

from deskhand import insan, yollar  # noqa: E402
from deskhand.arka_uc import kde  # noqa: E402

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ek=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


print("1) ekran_alani: yalnız etkin çıkışlar")
CIKTI = """\x1b[01;32mOutput: \x1b[0;0m1 DP-2 aaaa
\tenabled
\tconnected
\tGeometry: 0,0 2560x1440
\tScale: 1
Output: 2 HDMI-A-1 bbbb
\tdisabled
\tconnected
\tGeometry: 2560,0 1920x1080
Output: 3 DP-3 cccc
\tenabled
\tconnected
\tGeometry: -1920,200 1920x1080
"""
kontrol("kapalı çıkış atlanır", kde.etkin_cikis_kutulari(CIKTI) == [(0, 0, 2560, 1440), (-1920, 200, 1920, 1080)],
        str(kde.etkin_cikis_kutulari(CIKTI)))
eski = kde.calis
kde.calis = lambda *a, **k: CIKTI
try:
    kontrol("ekran_alani kapalı çıkışı kapsamaz", kde.ekran_alani() == (-1920, 0, 2560, 1440), str(kde.ekran_alani()))
finally:
    kde.calis = eski
ESKI_BICIM = "Output: 1 DP-2 x\n\tGeometry: 0,0 800x600\nOutput: 2 DP-3 y\n\tGeometry: 800,0 800x600\n"
kontrol("enabled/disabled satırı olmayan (eski) çıktı: tüm kutular", len(kde.etkin_cikis_kutulari(ESKI_BICIM)) == 2)

print("2) klavye düzeni önbelleği kxkbrc değişince yenilenir")
kxkb = os.path.join(os.environ["HOME"], ".config", "kxkbrc")
with open(kxkb, "w") as f:
    f.write("[Layout]\nLayoutList=tr\nVariantList=\n")
kde._duzen = None
kontrol("ilk okuma: tr", kde.klavye_duzeni() == ("tr", ""), str(kde.klavye_duzeni()))
kde._yazilabilir["ğ"] = True
with open(kxkb, "w") as f:
    f.write("[Layout]\nLayoutList=us\nVariantList=intl\n")
os.utime(kxkb, ns=(time.time_ns() + 2_000_000_000,) * 2)
kontrol("kxkbrc değişti → us/intl (eski süreç yeni düzeni görür)", kde.klavye_duzeni() == ("us", "intl"),
        str(kde.klavye_duzeni()))
kontrol("düzen değişince yazılabilirlik önbelleği boşaldı", "ğ" not in kde._yazilabilir)
kontrol("değişmeyen dosya: önbellek (aynı sonuç)", kde.klavye_duzeni() == ("us", "intl"))

print("3) deskhand-etkinlik v1 → izleyici yok sayılır")
betik = os.path.join(_yalitim.GECICI, "sahte-etkinlik")
eski_bin = yollar.etkinlik_bin


def sahte(surum_satiri):
    with open(betik, "w") as f:
        f.write(f"#!/bin/sh\necho '{surum_satiri}'\nexec sleep 30\n")
    os.chmod(betik, 0o700)
    yollar.etkinlik_bin = lambda: betik
    try:
        return insan.Etkinlik()
    finally:
        yollar.etkinlik_bin = eski_bin


insan.Etkinlik._uyarildi = True  # uyarı satırı test çıktısını kirletmesin
e = sahte("hazir 50 v1 12.5")
calisiyor = e.calisiyor()
kontrol("v1 → calisiyor() False (yalnız fare)", not calisiyor and "v1" in (e.hata or ""), str(e.hata))
e.p.wait(2)
kontrol("v1 → yardımcı sonlandırıldı", e.p.poll() is not None)
e.kapat()
e = sahte("hazir 50 v2 12.5")
kontrol("v2 → calisiyor() True, hazir_an okunur", e.calisiyor() and e.hazir_an == 12.5, f"{e.hata} {e.hazir_an}")
e.kapat()
e = sahte("hazir 12.5")
kontrol("sürümsüz (eski yardımcı) → çalışır", e.calisiyor() and e.hazir_an == 12.5, str(e.hata))
e.kapat()
kontrol("hazir_surumu ayrıştırma", insan.hazir_surumu("hazir 50 v2 1.0".split()) == 2
        and insan.hazir_surumu("hazir 1.0".split()) is None)

print(f"\n{GECEN}/{TOPLAM} geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
