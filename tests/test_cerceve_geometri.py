"""DH-TUR2 (2) D-1: ad takası yarışı. Aynı süreçte iki pencere varken (kardeş listesi dolu) çerçeve seçimi yalnız adlara
dayanıyordu: saldırgan A, açtığı B penceresini bankaya yönlendirip iki başlığı takas edince (erişilebilirlik adları
geride) B'nin (banka) çerçevesi seçiliyordu (SON-KAPI2 poc_takas T2 → 1). Düzeltme: okumada da seçilen çerçevenin
GetExtents sınırı hedef pencerenin pencere yöneticisi geometrisiyle eşleşmeli (web.konum_coz); eşleşme yok ya da
okunamıyor → Dur 6 (SAYFA_BELIRSIZ, kapalı-başarısız). Tek pencerede (kardeş yok) davranış değişmez.
Çalıştır:  python3 tests/test_cerceve_geometri.py"""
import _yalitim  # noqa: F401

import os
import sys

from deskhand import erisim, web  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


def sonuc(f):
    try:
        return f()
    except Dur as e:
        return f"DUR {e.kod} {e.tur}"


MF = " — Mozilla Firefox"
A_GEO = (0, 0, 1280, 800)       # saldırgan pencere A (hedef)
B_GEO = (200, 120, 640, 520)    # A'nın açtığı B açılır penceresi (banka)

print("== yardımcı: cerceve_geometri_denetle")
kontrol("işlev var", hasattr(erisim, "cerceve_geometri_denetle"))
den = erisim.cerceve_geometri_denetle
kontrol("kardeş var + çerçeve sınırı hedefin geometrisi → geçer", sonuc(lambda: den(A_GEO, A_GEO, None, ["X"])) is None)
kontrol("kardeş var + çerçeve sınırı BAŞKA pencerenin geometrisi → Dur 6",
        sonuc(lambda: den(A_GEO, B_GEO, (0, 0, 640, 520), ["X"])) == f"DUR 6 {erisim.SAYFA_BELIRSIZ}")
kontrol("kardeş var + sınır okunamadı → Dur 6 (bilinmiyor = güvensiz)",
        sonuc(lambda: den(A_GEO, None, None, ["X"])) == f"DUR 6 {erisim.SAYFA_BELIRSIZ}")
kontrol("kardeş var + pencere geometrisi bilinmiyor → Dur 6",
        sonuc(lambda: den(None, A_GEO, None, ["X"])) == f"DUR 6 {erisim.SAYFA_BELIRSIZ}")
kontrol("tek pencere (kardeş yok) → geometri şartı yok", sonuc(lambda: den(A_GEO, None, None, [])) is None)
kontrol("doğrudan çağrı (kardeş verilmedi) → şart yok",
        sonuc(lambda: den(A_GEO, None, None, erisim.KARDES_VERILMEDI)) is None)
kontrol("pencere-yerel sınır (Wayland: 0,0 + boyut) hedefle tutarlı → geçer",
        sonuc(lambda: den(A_GEO, (0, 0, 0, 0), (0, 0, 1280, 770), ["X"])) is None)
kontrol("ölçek 2: XWayland fiziksel piksel (2×) hedefle tutarlı → geçer",
        sonuc(lambda: den(A_GEO, (0, 0, 2560, 1600), (0, 0, 2560, 1600), ["X"], olcek=2)) is None)

# X11/XWayland GTK diyaloğu (ölçülen: Firefox GTK dosya seçicisi, KWin dekorlu): çerçeve dekorasyonu da kapsar
DEK_GEO = (345, 107, 1231, 902)
kontrol("dekorlu çerçeve (SCREEN istemci alanını sarar + WINDOW ters köken) hedefle tutarlı → geçer",
        sonuc(lambda: den(DEK_GEO, (344, 89, 1233, 925), (-1, -18, 1233, 925), ["X"])) is None)
kontrol("dekorlu çerçeve ama WINDOW sınırı okunamadı → Dur 6",
        sonuc(lambda: den(DEK_GEO, (344, 89, 1233, 925), None, ["X"])) == f"DUR 6 {erisim.SAYFA_BELIRSIZ}")
kontrol("dekorlu çerçeve ama WINDOW kökeni SCREEN payıyla çelişiyor → Dur 6",
        sonuc(lambda: den(DEK_GEO, (344, 89, 1233, 925), (0, 0, 1233, 925), ["X"])) == f"DUR 6 {erisim.SAYFA_BELIRSIZ}")
kontrol("sarar ama sol/sağ payı eşit değil (başka pencere) → Dur 6",
        sonuc(lambda: den(DEK_GEO, (330, 89, 1248, 925), (-15, -18, 1248, 925), ["X"])) == f"DUR 6 {erisim.SAYFA_BELIRSIZ}")
kontrol("kardeşin (B) dekorlu çerçevesi hedefe (A) karşı → Dur 6",
        sonuc(lambda: den(A_GEO, (199, 102, 642, 543), (-1, -18, 642, 543), ["X"])) == f"DUR 6 {erisim.SAYFA_BELIRSIZ}")
kontrol("hedefi saran ama üst payı başlık çubuğundan büyük (çok daha büyük pencere) → Dur 6",
        sonuc(lambda: den(DEK_GEO, (344, 0, 1233, 1014), (-1, -107, 1233, 1014), ["X"])) == f"DUR 6 {erisim.SAYFA_BELIRSIZ}")

print("== erisim yolu (AT-SPI yardımcısı): poc_takas senaryoları")


class Kutu:
    def __init__(self, g):
        self.x, self.y, self.width, self.height = g


class Cerceve:
    def __init__(self, ad, geo, kim):
        self.ad, self.geo, self.kim = ad, geo, kim

    def get_name(self):
        return self.ad

    def get_extents(self, tur):
        if self.geo is None:
            raise RuntimeError("okunamadı")
        return Kutu(self.geo if tur == "SCREEN" else (0, 0, self.geo[2], self.geo[3]))

    def get_role_name(self):
        return self.kim


class Uygulama:
    def __init__(self, cerceveler):
        self.c = cerceveler

    def get_process_id(self):
        return os.getpid()

    def get_name(self):
        return "Firefox"

    def get_child_count(self):
        return len(self.c)

    def get_child_at_index(self, i):
        return self.c[i]


class Masa:
    def __init__(self, app):
        self.app = app

    def get_child_count(self):
        return 1

    def get_child_at_index(self, i):
        return self.app


class Koord:
    SCREEN, WINDOW = "SCREEN", "WINDOW"


def atspi_icin(cerceveler):
    class SahteAtspi:
        CoordType = Koord

        @staticmethod
        def get_desktop(i):
            return Masa(Uygulama(cerceveler))
    return SahteAtspi


eski = erisim._atspi, erisim._cerceve_denetle
erisim._cerceve_denetle = lambda *a, **k: None


def kos(cerceveler, baslik, kardes, geo=A_GEO):
    erisim._atspi = lambda a: atspi_icin(cerceveler)
    istek = {"a11y": "sahte", "pid": str(os.getpid()), "baslik": baslik, "islem": "cerceve_rol", "kardes": kardes}
    if geo is not None:
        istek["geo_cerceve"] = list(geo)
    return sonuc(lambda: erisim._atspi_is(istek))


try:
    banka = "Hesap Ozeti | XBank" + MF
    # T2 tam takas: A'nın (hedef) bayat adı = B'nin güncel başlığı; B'nin bayat adı = A'nın güncel başlığı
    r = kos([Cerceve(banka, A_GEO, "A"), Cerceve("Z" + MF, B_GEO, "B")], "Z" + MF, [banka])
    kontrol("T2 tam takas → Dur 6 (B'nin banka çerçevesi seçilmez)", r == f"DUR 6 {erisim.SAYFA_BELIRSIZ}", r)
    # T1 zayıf bayat A + bayat B: değişmez (Dur)
    r = kos([Cerceve("Mozilla Firefox", A_GEO, "A"), Cerceve("Z" + MF, B_GEO, "B")], "Z" + MF, [banka])
    kontrol("T1 zayıf bayat → Dur (değişmez)", str(r).startswith("DUR 6"), r)
    # N1 güncel adlar: A'nın çerçevesi seçilir (değişmez)
    r = kos([Cerceve("Z" + MF, A_GEO, "A"), Cerceve(banka, B_GEO, "B")], "Z" + MF, [banka])
    kontrol("N1 güncel adlar → A'nın çerçevesi (değişmez)", r == "A", r)
    r = kos([Cerceve("Z" + MF, None, "A"), Cerceve(banka, B_GEO, "B")], "Z" + MF, [banka])
    kontrol("N1 ama çerçeve sınırı okunamıyor → Dur 6", r == f"DUR 6 {erisim.SAYFA_BELIRSIZ}", r)
    r = kos([Cerceve("Z" + MF, A_GEO, "A"), Cerceve(banka, B_GEO, "B")], "Z" + MF, [banka], geo=None)
    kontrol("N1 ama istekte pencere geometrisi yok → Dur 6", r == f"DUR 6 {erisim.SAYFA_BELIRSIZ}", r)
    r = kos([Cerceve("Z" + MF, B_GEO, "A")], "Z" + MF, [])
    kontrol("tek pencere: geometri tutmasa da eski davranış (seçilir)", r == "A", r)
finally:
    erisim._atspi, erisim._cerceve_denetle = eski

print("== web yolu (_baglam): okumada da geometri şartı")


class SahteAu:
    ad = "kwin"

    def pid(self, k):
        return os.getpid()

    def baslik(self, k):
        return "Z" + MF

    def geometri(self, k):
        return A_GEO


class SahteYol:
    ekran = None

    def __init__(self, adres):
        pass

    def toplu(self, cagrilar):
        return [(SahteYol.ekran,), ((0, 0, SahteYol.ekran[2], SahteYol.ekran[3]),)]

    def kapat(self):
        pass


eski_w = (web.sec, web._veri_yolu_adresi, web._Yol, web._cerceve_bul, web._m, erisim.kardes_basliklari,
          erisim._cerceve_denetle)
web.sec = lambda k=None: SahteAu()
web._veri_yolu_adresi = lambda au, sanal: "sahte"
web._Yol = SahteYol
web._cerceve_bul = lambda yol, pid, baslik, kardes: ("b", "/c", pid, "Firefox", "Z" + MF)
web._m = lambda *a, **k: a
erisim._cerceve_denetle = lambda *a, **k: None
try:
    erisim.kardes_basliklari = lambda au, k, pid: ["Hesap Ozeti | XBank" + MF]
    SahteYol.ekran = B_GEO
    r = sonuc(lambda: web._baglam("{11111111-1111-1111-1111-111111111111}"))
    kontrol("web: kardeş var + çerçeve B'nin geometrisinde → Dur 6 (okuma kestirimiyle sürmez)",
            r == f"DUR 6 {erisim.SAYFA_BELIRSIZ}", r)
    SahteYol.ekran = A_GEO
    r = sonuc(lambda: web._baglam("{11111111-1111-1111-1111-111111111111}"))
    kontrol("web: kardeş var + çerçeve hedefin geometrisinde → bağlam", isinstance(r, tuple) and r[6], r)
    erisim.kardes_basliklari = lambda au, k, pid: []
    SahteYol.ekran = B_GEO
    r = sonuc(lambda: web._baglam("{11111111-1111-1111-1111-111111111111}"))
    kontrol("web: tek pencere + eşleşme yok → eski okuma kestirimi (konum None)", isinstance(r, tuple) and r[6] is None, r)
finally:
    (web.sec, web._veri_yolu_adresi, web._Yol, web._cerceve_bul, web._m, erisim.kardes_basliklari,
     erisim._cerceve_denetle) = eski_w

print(f"\n{GECEN}/{TOPLAM} geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
