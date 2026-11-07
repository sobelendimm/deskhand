"""KWin ScreenShot2 görüntü yardımcısı testleri (ekransız): çıktı ayrıştırma sahte veriyle, sahte yardımcıyla
çağrı/hata sınıflandırması ve spectacle iç kurtarması. Gerçek ekran görüntüsü ALINMAZ (gerçek ikili yalnız
kullanım hatası için çağrılır; D-Bus'a gitmez).

Çalıştır:  python3 tests/test_goruntu.py"""
import os
import struct
import subprocess
import sys

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from PIL import Image

from deskhand import yollar
from deskhand.arka_uc import kde, kde_goruntu
from deskhand.arka_uc.kde_goruntu import GoruntuHatasi, ayristir

GECICI = _yalitim.GECICI
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def cikti(bicim, w, h, adim, govde, olcek="1"):
    return f"DESKHAND-GORUNTU 1 format={bicim} width={w} height={h} stride={adim} scale={olcek}\n".encode() + govde


def hata_mi(f, *a):
    try:
        f(*a)
    except GoruntuHatasi as e:
        return e
    return None


# ---------------------------------------------------------------- ayrıştırma (sahte veri)
# 2x2, satır sonunda 4 bayt dolgu; pikseller: kırmızı, yeşil / mavi, (10, 20, 30)
PIKSEL = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (10, 20, 30)]


def bellek(dizilim, bpp, dolgu=4):
    satirlar = []
    for y in range(2):
        s = b"".join(dizilim(*PIKSEL[y * 2 + x]) for x in range(2))
        satirlar.append(s + b"\xee" * dolgu)
    return b"".join(satirlar), 2 * bpp + dolgu


for ad, bicim, dizilim, bpp in [
    ("RGBX8888 (16)", 16, lambda r, g, b: bytes((r, g, b, 255)), 4),
    ("RGBA8888_Premultiplied (18)", 18, lambda r, g, b: bytes((r, g, b, 255)), 4),
    ("ARGB32 (5) = bellekte B,G,R,A", 5, lambda r, g, b: bytes((b, g, r, 255)), 4),
    ("RGB32 (4)", 4, lambda r, g, b: bytes((b, g, r, 0xff)), 4),
    ("RGB888 (13)", 13, lambda r, g, b: bytes((r, g, b)), 3),
    ("BGR888 (29)", 29, lambda r, g, b: bytes((b, g, r)), 3),
    ("RGBA64 (26) 16 bit", 26, lambda r, g, b: struct.pack("<4H", r * 257, g * 257, b * 257, 65535), 8),
]:
    govde, adim = bellek(dizilim, bpp)
    im, olcek = ayristir(cikti(bicim, 2, 2, adim, govde))
    kontrol(f"ayrıştırma: {ad} → RGB, dolgulu satır", im.mode == "RGB" and im.size == (2, 2) and olcek == 1.0
            and [im.getpixel((x, y)) for y in range(2) for x in range(2)] == PIKSEL,
            f"{im.mode} {[im.getpixel((x, y)) for y in range(2) for x in range(2)]}")

govde, adim = bellek(lambda r, g, b: bytes((r, g, b, 255)), 4)
im, olcek = ayristir(cikti(16, 2, 2, adim, govde, "1.5"))
kontrol("ayrıştırma: ölçek okunur", olcek == 1.5)
kontrol("ayrıştırma: sonuç belleğe bağlı değil (kopya)", isinstance(im, Image.Image) and im.copy().tobytes() == im.tobytes())
kontrol("ayrıştırma: yanlış önek → hata", hata_mi(ayristir, b"PNG\x89" + govde) is not None)
kontrol("ayrıştırma: başlık satırı yok → hata", hata_mi(ayristir, b"DESKHAND-GORUNTU 1 format=16 width=2") is not None)
kontrol("ayrıştırma: eksik gövde → hata", hata_mi(ayristir, cikti(16, 2, 2, adim, govde[:-1])) is not None)
kontrol("ayrıştırma: fazla gövde → hata", hata_mi(ayristir, cikti(16, 2, 2, adim, govde + b"x")) is not None)
kontrol("ayrıştırma: bozuk sayı → hata", hata_mi(ayristir, cikti("x", 2, 2, adim, govde)) is not None)
kontrol("ayrıştırma: eksik alan → hata",
        hata_mi(ayristir, b"DESKHAND-GORUNTU 1 format=16 width=2 height=2\n" + govde) is not None)
kontrol("ayrıştırma: desteklenmeyen biçim (Mono 1) → hata", hata_mi(ayristir, cikti(1, 2, 2, adim, govde)) is not None)
kontrol("ayrıştırma: adım < genişlik*bpp → hata", hata_mi(ayristir, cikti(16, 4, 2, adim, govde)) is not None)
kontrol("ayrıştırma: sıfır boyut → hata", hata_mi(ayristir, cikti(16, 0, 2, adim, govde)) is not None)

# ---------------------------------------------------------------- sahte yardımcı ile çağrı
SAHTE = os.path.join(GECICI, "sahte-goruntu")
KAYIT = os.path.join(GECICI, "sahte-kayit")
with open(SAHTE, "w") as f:
    f.write(f"""#!{sys.executable}
import os, sys
with open({KAYIT!r}, "a") as k:
    k.write(" ".join(sys.argv[1:]) + "\\n")
kip = open({SAHTE + ".kip"!r}).read().strip()
if kip == "tamam":
    w, h = 3, 2
    sys.stdout.buffer.write(b"DESKHAND-GORUNTU 1 format=16 width=3 height=2 stride=12 scale=1\\n" + bytes((1, 2, 3, 255)) * 6)
elif kip == "yetkisiz":
    sys.stderr.write("deskhand-goruntu: org.kde.KWin.ScreenShot2.Error.NoAuthorized: not authorized\\n"); sys.exit(2)
elif kip == "servis-yok":
    sys.stderr.write("deskhand-goruntu: org.freedesktop.DBus.Error.ServiceUnknown: yok\\n"); sys.exit(3)
elif kip == "boru":
    sys.stderr.write("deskhand-goruntu: boru zaman aşımı\\n"); sys.exit(4)
elif kip == "bozuk":
    sys.stdout.buffer.write(b"merhaba")
""")
os.chmod(SAHTE, 0o755)


def kip(k):
    with open(SAHTE + ".kip", "w") as f:
        f.write(k)
    if os.path.exists(KAYIT):
        os.remove(KAYIT)


def cagri_sayisi():
    return len(open(KAYIT).read().splitlines()) if os.path.exists(KAYIT) else 0


def son_argv():
    return open(KAYIT).read().splitlines()[-1] if os.path.exists(KAYIT) else None


kip("tamam")
im, olcek = kde_goruntu.al(bin_yolu=SAHTE)
kontrol("al: sahte yardımcı → 3x2 RGB", im.size == (3, 2) and im.getpixel((2, 1)) == (1, 2, 3))
kontrol("al: tüm ekran argümansız", son_argv() == "", repr(son_argv()))
kde_goruntu.al((10, 20, 400, 300), bin_yolu=SAHTE)
kontrol("al: bölge → -a X Y G Y (CaptureArea)", son_argv() == "-a 10 20 400 300", repr(son_argv()))

for k, kalici_mi in [("yetkisiz", True), ("servis-yok", True), ("boru", False), ("bozuk", False)]:
    kip(k)
    e = hata_mi(kde_goruntu.al, None, SAHTE)
    kontrol(f"al: {k} → GoruntuHatasi, kalıcı={kalici_mi}",
            e is not None and bool(getattr(e, "kalici", False)) == kalici_mi, repr(e))
e = hata_mi(kde_goruntu.al, None, os.path.join(GECICI, "yok"))
kontrol("al: ikili çalıştırılamıyor → GoruntuHatasi", e is not None)

# ---------------------------------------------------------------- goruntu(): yedek (spectacle) davranışı
YEDEK = Image.new("RGB", (5, 5), (9, 9, 9))
yedek_sayac = [0]


def yedek():
    yedek_sayac[0] += 1
    return YEDEK


asil_bin = yollar.goruntu_bin
yollar.goruntu_bin = lambda: SAHTE
try:
    kde_goruntu.sifirla()
    kip("tamam")
    im = kde_goruntu.goruntu(yedek)
    kontrol("goruntu: yardımcı çalışıyor → yedek çağrılmaz", im.size == (3, 2) and yedek_sayac[0] == 0)

    kip("boru")  # geçici hata: bu çağrı yedeğe düşer, sonraki yine yardımcıyı dener
    im1 = kde_goruntu.goruntu(yedek)
    im2 = kde_goruntu.goruntu(yedek)
    kontrol("goruntu: geçici hata → yedek, yardımcı her seferinde yeniden denenir",
            im1 is YEDEK and im2 is YEDEK and cagri_sayisi() == 2 and kde_goruntu._kapali is None)

    kip("yetkisiz")  # kalıcı: bir kez denenir, sonra süreç boyunca doğrudan yedek
    yedek_sayac[0] = 0
    sonuc = [kde_goruntu.goruntu(yedek) for _ in range(3)]
    kontrol("goruntu: yetkisiz → yedek; yardımcı yalnız bir kez denenir",
            all(s is YEDEK for s in sonuc) and yedek_sayac[0] == 3 and cagri_sayisi() == 1
            and kde_goruntu._kapali is not None, f"çağrı {cagri_sayisi()}")
    gunluk_dosyalari = os.listdir(yollar.gunluk_dizin()) if os.path.isdir(yollar.gunluk_dizin()) else []
    metin = "".join(open(os.path.join(yollar.gunluk_dizin(), g)).read() for g in gunluk_dosyalari)
    kontrol("goruntu: yedeğe düşüş günlüğe (geçici dizin) yazılır",
            yollar.gunluk_dizin().startswith(GECICI) and "spectacle yedeği" in metin)

    kde_goruntu.sifirla()
    yollar.goruntu_bin = lambda: None
    yedek_sayac[0] = 0
    kontrol("goruntu: yardımcı derlenmemiş → yedek", kde_goruntu.goruntu(yedek) is YEDEK and yedek_sayac[0] == 1)

    # kde.ekran_goruntusu bu yolu kullanır; spectacle yalnız kurtarma
    kde_goruntu.sifirla()
    yollar.goruntu_bin = lambda: SAHTE
    asil_spectacle = kde.spectacle_goruntusu
    kde.spectacle_goruntusu = yedek
    try:
        kip("tamam")
        yedek_sayac[0] = 0
        im = kde.ekran_goruntusu()
        kontrol("kde.ekran_goruntusu: yardımcı varsa spectacle çağrılmaz", im.size == (3, 2) and yedek_sayac[0] == 0)
        kde_goruntu.sifirla()
        kip("servis-yok")
        im = kde.ekran_goruntusu()
        kontrol("kde.ekran_goruntusu: KWin arayüzü yok → spectacle", im is YEDEK and yedek_sayac[0] == 1)
        kontrol("kde.KdeArkaUc().goruntu() aynı yoldan", kde.KdeArkaUc().goruntu() is YEDEK)
    finally:
        kde.spectacle_goruntusu = asil_spectacle
finally:
    yollar.goruntu_bin = asil_bin
    kde_goruntu.sifirla()

# ---------------------------------------------------------------- gerçek ikili: yalnız kullanım hatası (D-Bus yok)
gercek = yollar.goruntu_bin()
if gercek:
    kontrol("yol: paket içindeki derlenmiş ikili", gercek == os.path.join(yollar.PAKET_DIZIN, "yardimci", "deskhand-goruntu"))
    for argv in (["-x"], ["-a", "0", "0", "0", "5"], ["-a", "1", "2", "3"], ["-a", "1", "2", "x", "4"]):
        p = subprocess.run([gercek, *argv], capture_output=True, timeout=10)
        kontrol(f"ikili: {' '.join(argv)} → kullanım hatası (1), çıktı yok", p.returncode == 1 and not p.stdout,
                f"{p.returncode}")
else:
    print("ATLANDI  gerçek ikili derlenmemiş (make -C deskhand/yardimci deskhand-goruntu)")

print(f"\n{gecen}/{toplam} görüntü testi geçti")
sys.exit(0 if gecen == toplam else 1)
