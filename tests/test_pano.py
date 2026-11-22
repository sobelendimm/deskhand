"""Pano + yapıştırarak yazma testleri (Faz 9a).

1. Sahte arka uç (ekransız): yapıştırma kararı, `\\n`/`\\t` anlamı, uçbirim tuşu, eski panonun HER durumda (hata, DUR, başlık
   kilidi, onay reddi) geri yüklenmesi, güvenlik denetimleri (hassas sayfa onayı tam metin üzerinde, gizli yazı günlüğe
   yazılmaz), pano yoksa harf harf yola dönüş.
2. kde pano kodu: `subprocess` TAKLİDİYLE (kullanıcının gerçek panosuna dokunulmaz): wl-paste/wl-copy bağımsız
   değişkenleri, --sensitive, temizleme, DUR (13) + meşgul (15) koruması, geri yükleme denetimsiz, sahte ortam koruması.
3. MCP `clipboard` aracı ve CLI `pano`: ön planda okuma insan onayı ister (kendi yazdığımız metin hariç), arka planda serbest.
4. Sanal masaüstü (Xvfb, GÖRÜNMEZ): pano yardımcısı (X11 seçim sahibi) + gerçek yapıştırma: Qt test penceresine emoji +
   uzun + çok satırlı metin, eski panonun geri gelmesi, Qt'nin sahip olduğu büyük panonun INCR ile okunması, yardımcının
   kafeste olması ve masaüstüyle kapanması, bayat yardımcının yeniden başlaması, kde yolunun hiç çağrılmaması.

Çalıştır:  python3 tests/test_pano.py"""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

import argparse
import asyncio
import atexit
import json
import os
import signal
import statistics
import subprocess
import sys
import time
import types

from PIL import Image

from deskhand import api, arka_uc, eylem, guvenlik, hata, masaustu, onay, yollar
from deskhand.arka_uc import EKRAN, kde, sanal
from deskhand.hata import Dur

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
KOK = _yalitim.KOK
GECICI = _yalitim.GECICI
PANO_PENCERE = os.path.join(KOK, "tests", "yardimci", "pano_pencere.py")
GECEN = TOPLAM = 0
olcum = {}


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


def kod_al(f, *a, **k):
    try:
        f(*a, **k)
        return 0
    except Dur as e:
        return e.kod


def bekle(kosul, sure=5.0, aralik=0.02):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        v = kosul()
        if v:
            return v
        time.sleep(aralik)
    return kosul()


def gunluk_metni():
    d = yollar.gunluk_dizin()
    try:
        return "".join(open(os.path.join(d, f)).read() for f in os.listdir(d) if f.startswith("gunluk-"))
    except OSError:
        return ""


HARF_SN_GERCEK = eylem.HARF_SN
eylem.HARF_SN = 0  # sahte girdide harf aralığı beklenmesin
YAZILAMAZ = {"😀", "🎉", "—"}  # sahte klavye düzeninde olmayan karakterler


# ================================================================ sahte arka uç (pano uygulayan)

class SahteGirdi:
    def __init__(self, au, etiket="", gizli=False, etk=None, denetle=None):
        self.au, self.etiket, self.gizli, self.denetle = au, etiket, gizli, denetle
        self.kesildi, self.hazir, self.etk, self.son_fare = None, True, None, (5, 5)

    def gonder(self, k, desen, *satirlar):
        hata.dur_denetle()
        if self.denetle:
            self.denetle(k, desen)
        if self.au.insan:
            raise Dur(12, "kullanıcı klavye/fare kullandı (insan önceliği); girdi gönderilmedi")
        for s in satirlar:
            self.au.satirlar.append(s)
            self.au.olaylar.append(("satir", s))
            if s in ("key ctrl+v", "key ctrl+shift+v"):
                self.au.hedef += self.au.pano or ""  # hedef pencere yapıştırdı
                self.au.yapistirma += 1
                if self.au.kanca:
                    self.au.kanca(self.au.yapistirma)
            elif s == "key enter":
                self.au.hedef += "\n"
            elif s == "key tab":
                self.au.hedef += "\t"

    def ham(self, s):
        hata.dur_denetle()
        self.au.satirlar.append(s)
        if s.startswith("type "):
            self.au.hedef += s[5:]
        elif s == "key space":
            self.au.hedef += " "
        elif s == "key enter":
            self.au.hedef += "\n"
        elif s == "key tab":
            self.au.hedef += "\t"

    def zorla(self, s): self.au.satirlar.append(s)
    def izle(self, k, desen): pass
    def izle_bitir(self): pass
    def etk_denetle(self, ne=None): pass
    def insan_kontrol(self): pass
    def kapat(self): pass


class SahtePano(arka_uc.ArkaUc):
    pano_bekle = 0.0

    def __init__(self, ad="kde", baslik="Belge — KWrite", sinif="kwrite"):
        self.ad = ad
        self.pen = {"{w}": [baslik, sinif, (100, 100, 800, 600)]}
        self.pano, self.hedef, self.olaylar, self.satirlar = "eski pano", "", [], []
        self.yapistirma, self.kanca, self.yedek_hatasi, self.insan = 0, None, None, False

    def pencere_coz(self, arg): return arg
    def pencereler(self, desen=None): return []
    def geometri(self, k): return self.pen[k][2] if k != EKRAN else (0, 0, 1920, 1080)
    def baslik(self, k): return self.pen.get(k, [""])[0]
    def sinif(self, k): return self.pen.get(k, ["", ""])[1]
    def aktif(self): return "{w}"
    def one_getir(self, k): pass
    def kapat(self, k): pass
    def fare(self): return 150, 150, "{w}"
    def ekran_alani(self): return (0, 0, 1920, 1080)
    def goruntu(self): return Image.new("RGB", (1920, 1080), (200, 200, 200))
    def insan_var_mi(self): return False
    def baslat(self, argv, env=None, cikti=None): raise AssertionError("başlatılmamalı")
    def yazilabilir_mi(self, c): return c not in YAZILAMAZ and c.isprintable()
    def gecerli_tuslar(self): return {"enter", "tab", "space", "a", "esc"}
    def girdi(self, etiket="", gizli=False, etk=None, denetle=None): return SahteGirdi(self, etiket, gizli, etk, denetle)

    def pano_oku(self): return self.pano

    def pano_yaz(self, metin, hassas=True):
        hata.dur_denetle()
        self.olaylar.append(("pano_yaz", metin, hassas))
        self.pano = metin or None

    def pano_yedekle(self):
        if self.yedek_hatasi:
            raise self.yedek_hatasi
        return {"metin": self.pano}

    def pano_geri_yukle(self, yedek):  # denetimsiz (gerçek arka uçlar gibi)
        self.olaylar.append(("geri", yedek["metin"]))
        self.pano = yedek["metin"]
        return None


def ns(**k):
    a = argparse.Namespace(baslik=None, onayli=False, gizli=False, kimlik="{w}")
    for x, v in k.items():
        setattr(a, x, v)
    return a


def yaz(au, metin, **k):
    """k_yaz'ı sahte arka uçla çalıştır (ad: "kde" kaydı)."""
    arka_uc._ORNEKLER["kde"] = au
    with arka_uc.hedef_sabit("kde"):
        return kod_al(eylem.k_yaz, ns(metin=metin, **k))


ISTEKLER, YANIT = [], {"izin": False}


def sahte_iste_sonuc(eylem_, hedef, ayrinti="", masaustu="ekran", sure=120, goruntu=None, gunluge_yaz=True):
    ISTEKLER.append({"eylem": eylem_, "hedef": hedef, "ayrinti": ayrinti})
    return onay.OnaySonucu(YANIT["izin"], "izin" if YANIT["izin"] else "red")


onay.iste_sonuc = sahte_iste_sonuc

# ================================================================ 1. yapıştırma kararı + akış

au = SahtePano()
arka_uc._ORNEKLER["kde"] = au
with arka_uc.hedef_sabit("kde"):
    kontrol("karar: kısa yazılabilir yazı → harf harf (yapıştırma yok)", not eylem.yapistirarak_mi("merhaba dünya"))
    kontrol("karar: 200 karakter → harf harf, 201 → yapıştır",
            not eylem.yapistirarak_mi("a" * 200) and eylem.yapistirarak_mi("a" * 201))
    kontrol("karar: klavye düzeninde olmayan karakter (emoji) → yapıştır", eylem.yapistirarak_mi("selam 😀"))
    kontrol("karar: Türkçe harf yazılabilir → harf harf", not eylem.yapistirarak_mi("çağrı ığüşöç"))
    kontrol("karar: yalnız satır sonu/sekme olan uzun yazı → panoya konacak parça yok, harf harf yol",
            not eylem.yapistirarak_mi("\n" * 300))


class PanoYok(SahtePano):
    pano_yaz = arka_uc.ArkaUc.pano_yaz  # panoyu uygulamayan arka uç


arka_uc._ORNEKLER["kde"] = PanoYok()
with arka_uc.hedef_sabit("kde"):
    kontrol("karar: arka uç panoyu uygulamıyorsa uzun/emoji yazı da harf harf yoluna", not eylem.yapistirarak_mi("a" * 500))
arka_uc._ORNEKLER["kde"] = au

for sinif_, beklenen in (("org.kde.konsole", True), ("com.mitchellh.ghostty", True), ("kitty", True), ("Alacritty", True),
                         ("foot", True), ("org.wezfurlong.wezterm", True), ("XTerm", True), ("yakuake", True),
                         ("gnome-terminal-server", True), ("Tilix", True), ("firefox", False), ("kwrite", False),
                         ("org.kde.dolphin", False), ("", False)):
    kontrol(f"uçbirim sınıfı: {sinif_!r} → {beklenen}", guvenlik.ucbirim_mi(sinif_) == beklenen)

# --- emoji + çok satırlı + sekme: yapıştırılır, \n Enter, \t Tab, eski pano geri gelir
au = SahtePano()
metin = "ilk satır 😀\n\nüçüncü — satır\tsekmeden sonra 🎉"
kod = yaz(au, metin)
kontrol("yapıştır: emoji + boş satır + sekme → hedefe BİREBİR gitti", kod == 0 and au.hedef == metin, f"{kod} {au.hedef!r}")
kontrol("yapıştır: eski pano geri yüklendi", au.pano == "eski pano" and au.olaylar[-1] == ("geri", "eski pano"), str(au.olaylar[-2:]))
anahtarlar = [s for s in au.satirlar if s.startswith("key ")]
kontrol("yapıştır: \\n → key enter ×2, \\t → key tab, 3 yapıştırma (ctrl+v)",
        anahtarlar.count("key enter") == 2 and anahtarlar.count("key tab") == 1 and anahtarlar.count("key ctrl+v") == 3,
        str(anahtarlar))
kontrol("yapıştır: harf harf 'type' satırı YOK", not any(s.startswith("type ") for s in au.satirlar))
kontrol("yapıştır: pano yöneticisi geçmişine yazılmasın (hassas=True) her yazımda",
        all(o[2] is True for o in au.olaylar if o[0] == "pano_yaz"))
kontrol("yapıştır: sıra = yedekle → [yaz, tuş]… → geri yükle",
        au.olaylar[0][0] == "pano_yaz" and au.olaylar[-1][0] == "geri")

# --- uzun düz yazı (emojisiz): tek yapıştırma
au = SahtePano()
uzun = "Uzun satır ğüşiöç. " * 30
kod = yaz(au, uzun)
kontrol("yapıştır: 570 karakterlik tek satır → TEK yapıştırma, birebir", kod == 0 and au.hedef == uzun and
        au.yapistirma == 1, f"{kod} {au.yapistirma}")

# --- uçbirim: ctrl+shift+v
au = SahtePano(sinif="org.kde.konsole")
kod = yaz(au, "ls -la 😀")
kontrol("uçbirim penceresi → ctrl+shift+v (ctrl+v değil)", kod == 0 and "key ctrl+shift+v" in au.satirlar and
        "key ctrl+v" not in au.satirlar, str(au.satirlar))

# --- pano boştu → panoyu temizleyerek geri yükle
au = SahtePano()
au.pano = None
kod = yaz(au, "boş pano 😀")
kontrol("eski pano boştu → yapıştırma sonrası pano yine boş", kod == 0 and au.pano is None and au.hedef == "boş pano 😀")

# --- \r\n normalleşir (harf harf yoldaki gibi)
au = SahtePano()
kod = yaz(au, "a 😀\r\nb")
kontrol("\\r\\n → tek Enter", kod == 0 and au.hedef == "a 😀\nb", repr(au.hedef))

# --- kullanıcı yapıştırma sırasında panoyu kendisi değiştirdi → eski pano GERİ YÜKLENMEZ (kullanıcının yeni içeriği ezilmez)
au = SahtePano()


def kullanici_kopyaladi(n):
    au.pano = "kullanıcının yeni kopyası"


au.kanca = kullanici_kopyaladi
kod = yaz(au, "a 😀\nb 🎉")
kontrol("pano bu arada kullanıcıca değişti → geri YÜKLENMEDİ, kullanıcının içeriği duruyor",
        kod == 0 and au.pano == "kullanıcının yeni kopyası" and not any(o[0] == "geri" for o in au.olaylar),
        f"{kod} {au.pano!r} {au.olaylar[-2:]}")

# --- pano hâlâ bizim son yazdığımız metin → bugünkü gibi geri yüklenir
au = SahtePano()
kod = yaz(au, "a 😀\nb 🎉")
kontrol("pano hâlâ bizim son metnimiz → eski pano geri yüklenir", kod == 0 and au.pano == "eski pano" and
        au.olaylar[-1] == ("geri", "eski pano"))

# --- pano okuma başarısız → bugünkü davranış: geri yükle
au = SahtePano()
okuma_sayac = []


def bozuk_oku():
    okuma_sayac.append(1)
    raise Dur(9, "pano okunamadı")


au.pano_oku = bozuk_oku
kod = yaz(au, "a 😀")
kontrol("geri yükleme öncesi pano okunamadı → yine geri yüklenir", kod == 0 and okuma_sayac and
        au.olaylar[-1] == ("geri", "eski pano") and au.pano == "eski pano", f"{kod} {au.olaylar[-2:]}")

# --- kullanıcı panoyu metin dışı (okuma → None) bir şeyle değiştirdi → geri yüklenmez
au = SahtePano()
au.kanca = lambda n: setattr(au, "pano", None)
kod = yaz(au, "a 😀")
kontrol("pano metin dışı/boş oldu (None ≠ bizim metin) → geri YÜKLENMEDİ",
        kod == 0 and not any(o[0] == "geri" for o in au.olaylar), f"{kod} {au.olaylar[-2:]}")

# --- hata/kesinti: eski pano HER durumda geri gelir
au = SahtePano()


def dur_ac_kancasi(n):
    if n == 1:
        guvenlik.dur_ac("kullanici")


au.kanca = dur_ac_kancasi
kod = yaz(au, "birinci 😀\nikinci 🎉\nüçüncü")
try:
    os.remove(hata.dur_dosyasi())
except OSError:
    pass
kontrol("DUR ilk yapıştırmadan sonra açıldı → 13, devamı gönderilmedi", kod == 13 and au.hedef == "birinci 😀", f"{kod} {au.hedef!r}")
kontrol("DUR kesintisinde de eski pano geri yüklendi (geri yükleme denetimsiz)", au.pano == "eski pano", str(au.pano))

au = SahtePano()
au.kanca = lambda n: setattr(au, "insan", True)
kod = yaz(au, "birinci 😀\nikinci 🎉")
kontrol("insan önceliği (12) → durur, eski pano geri yüklendi", kod == 12 and au.pano == "eski pano" and
        au.hedef == "birinci 😀", f"{kod} {au.pano!r}")

au = SahtePano()


def baslik_degistir(n):
    au.pen["{w}"][0] = "Başka sekme"


au.kanca = baslik_degistir
arka_uc._ORNEKLER["kde"] = au
with arka_uc.hedef_sabit("kde"):
    kod = kod_al(eylem.k_yaz, ns(metin="birinci 😀\nikinci 🎉", baslik="^Belge"))
kontrol("başlık kilidi: yapıştırmalar arası başlık değişti → 4, ikinci parça gitmedi, eski pano geri",
        kod == 4 and au.hedef == "birinci 😀" and au.pano == "eski pano", f"{kod} {au.hedef!r} {au.pano!r}")

au = SahtePano()
au.pano_yaz = lambda metin, hassas=True: (_ for _ in ()).throw(Dur(9, "wl-copy yok"))
kod = yaz(au, "emoji 😀")
kontrol("pano YAZILAMAZSA (9) hata geçer, eski pano geri yüklenir", kod == 9 and au.pano == "eski pano", f"{kod} {au.pano!r}")

# --- pano hiç kullanılamıyorsa (yedekle 9): harf harf yola dön
au = SahtePano()
au.yedek_hatasi = Dur(9, "wl-paste yok")
kod = yaz(au, "a" * 210)
kontrol("pano kullanılamıyor → harf harf yazıldı, hedef birebir, pano dokunulmadı",
        kod == 0 and au.hedef == "a" * 210 and not [o for o in au.olaylar if o[0] in ("pano_yaz", "geri")] and
        au.pano == "eski pano", f"{kod} {len(au.hedef)}")
au = SahtePano()
au.yedek_hatasi = Dur(9, "wl-paste yok")
kod = yaz(au, "a 😀 b")
kontrol("pano yok + yedeksiz karakter → eski davranış (yazılamayan karakter, 1), hiçbir şey yazılmadı",
        kod == 1 and not au.satirlar and au.hedef == "", f"{kod} {au.satirlar[:3]}")

# --- hassas sayfa: tam metin üzerinde onay, yazmadan ÖNCE; pano hiç dokunulmaz
au = SahtePano(baslik="Checkout - Ödeme - Shop")
ISTEKLER.clear()
YANIT["izin"] = False
kod = yaz(au, "Ali Veli 😀\n34 Cadde")
kontrol("hassas sayfa: Enter'lı yapıştırma → yazmadan ÖNCE onay, red → 10, pano/tuş HİÇ dokunulmadı",
        kod == 10 and len(ISTEKLER) == 1 and not au.olaylar and not au.satirlar and au.pano == "eski pano",
        f"{kod} {len(ISTEKLER)} {au.olaylar}")
kontrol("hassas sayfa: onay isteği TAM metni taşır", ISTEKLER and "Ali Veli" in ISTEKLER[0]["ayrinti"] and
        "34 Cadde" in ISTEKLER[0]["ayrinti"], str(ISTEKLER[:1])[:200])
YANIT["izin"] = True
ISTEKLER.clear()
au = SahtePano(baslik="Checkout - Ödeme - Shop")
kod = yaz(au, "Ali Veli 😀\n34 Cadde")
kontrol("hassas sayfa: izinle TEK onayla yapıştırıldı", kod == 0 and len(ISTEKLER) == 1 and
        au.hedef == "Ali Veli 😀\n34 Cadde" and au.pano == "eski pano", f"{kod} {len(ISTEKLER)} {au.hedef!r}")
YANIT["izin"] = False
au = SahtePano(baslik="Checkout - Ödeme - Shop")
ISTEKLER.clear()
kod = yaz(au, "a 😀 b", onayli=True)
kontrol("hassas sayfa: --onayli → sorulmaz", kod == 0 and not ISTEKLER and au.hedef == "a 😀 b")

# --- yasak pencere: hiçbir şeye dokunulmaz
au = SahtePano(baslik="deskhand")
kod = yaz(au, "emoji 😀")
kontrol("yasak pencere (deskhand paneli): yapıştırma yolu da girdi göndermez (10), eski pano geri",
        kod == 10 and au.hedef == "" and au.pano == "eski pano", f"{kod} {au.hedef!r}")

# --- gizli yazı günlüğe yazılmaz
au = SahtePano()
SIR = "cok-gizli-parola-Xq9😀"
yaz(au, SIR, gizli=True)
yaz(au, "gorunur-metin-Zk3 😀")
g = gunluk_metni()
kontrol("gizli yazı: metin günlükte YOK, 'yapistir ***(n)' var", SIR not in g and "cok-gizli" not in g and "yapistir ***(" in g)
kontrol("gizli olmayan yazı günlüğe yazılır (kırpılmış)", "gorunur-metin-Zk3" in g)
yaz(au, "x😀" + "u" * 5000)
kontrol("günlük: uzun yapıştırma 200 karakterde kırpılır", "u" * 300 not in gunluk_metni())

# ================================================================ 2. kde pano kodu (subprocess taklidi)


class SahtePopen:
    cagrilar = []
    yanit = staticmethod(lambda argv: (1, b"", ""))
    zaman_asimi = False

    def __init__(self, argv, stdin=None, stdout=None, stderr=None, env=None):
        self.argv, self.cikti, self.hata, self.env, self.girdi, self.olu = list(argv), stdout, stderr, env, b"", False
        self.stdin = self if stdin == subprocess.PIPE else None
        SahtePopen.cagrilar.append(self)

    def write(self, b): self.girdi += b
    def close(self): pass

    def wait(self, timeout=None):
        if SahtePopen.zaman_asimi and not self.olu:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        self.returncode, out, err = SahtePopen.yanit(self.argv)
        self.cikti.write(out)
        self.hata.write(err.encode())
        return self.returncode

    def kill(self): self.olu = True


KDE_SUBPROCESS = kde.subprocess
kde.subprocess = types.SimpleNamespace(Popen=SahtePopen, PIPE=subprocess.PIPE, DEVNULL=subprocess.DEVNULL,
                                       TimeoutExpired=subprocess.TimeoutExpired, run=subprocess.run)
KORUMA = {"hata": None, "cagri": 0}


def sahte_koruma(ne):
    KORUMA["cagri"] += 1
    if KORUMA["hata"]:
        raise KORUMA["hata"]


GERCEK_KORUMA = kde.on_plan_korumasi
kde.on_plan_korumasi = sahte_koruma
env0 = {k_: os.environ.pop(k_, None) for k_ in ("WAYLAND_DISPLAY", "DESKHAND_SANAL")}


def kde_yanit(turler=("text/plain;charset=utf-8",), icerik=b"merhaba", rc_liste=0):
    def f(argv):
        if argv[:2] == ["wl-paste", "--list-types"]:
            return (rc_liste, "\n".join(turler).encode(), "")
        if argv[0] == "wl-paste":
            return (0, icerik, "")
        return (0, b"", "")
    return f


def cagri_say(ad=None):
    return [c for c in SahtePopen.cagrilar if ad is None or c.argv[0] == ad]


try:
    kb = kde.KdeArkaUc()
    # okuma
    SahtePopen.cagrilar.clear()
    SahtePopen.yanit = staticmethod(kde_yanit(("text/html", "text/plain;charset=utf-8", "UTF8_STRING"), "çağrı 😀\nikinci".encode()))
    kontrol("kde pano_oku: metin türü seçilir, --no-newline + --type, UTF-8 çözülür",
            kb.pano_oku() == "çağrı 😀\nikinci" and
            cagri_say("wl-paste")[-1].argv == ["wl-paste", "--no-newline", "--type", "text/plain;charset=utf-8"],
            str([c.argv for c in SahtePopen.cagrilar]))
    SahtePopen.cagrilar.clear()
    SahtePopen.yanit = staticmethod(kde_yanit(("image/png",), b"\x89PNG"))
    kontrol("kde pano_oku: metin dışı pano → None (ikili veri okunmaz)", kb.pano_oku() is None and len(cagri_say("wl-paste")) == 1)
    SahtePopen.yanit = staticmethod(kde_yanit((), b"", rc_liste=1))
    kontrol("kde pano_oku: boş pano → None", kb.pano_oku() is None)

    # yazma
    SahtePopen.cagrilar.clear()
    kb.pano_yaz("Merhaba 😀")
    c = cagri_say("wl-copy")[-1]
    kontrol("kde pano_yaz: wl-copy --type text/plain;charset=utf-8 --sensitive, metin stdin'den",
            c.argv == ["wl-copy", "--type", "text/plain;charset=utf-8", "--sensitive"] and c.girdi == "Merhaba 😀".encode(),
            str(c.argv))
    kb.pano_yaz("x", hassas=False)
    kontrol("kde pano_yaz(hassas=False): --sensitive yok", cagri_say("wl-copy")[-1].argv == ["wl-copy", "--type", "text/plain;charset=utf-8"])
    kb.pano_yaz("")
    kontrol("kde pano_yaz(''): wl-copy --clear", cagri_say("wl-copy")[-1].argv == ["wl-copy", "--clear"])
    kontrol("kde: wl-copy çıktıları BORU değil dosya (çatallanan çocuk boruyu açık tutmasın)",
            all(not isinstance(c.cikti, int) and hasattr(c.cikti, "seek") for c in cagri_say("wl-copy")))
    SahtePopen.yanit = staticmethod(lambda argv: (1, b"", "boom"))
    kontrol("kde pano_yaz: wl-copy hata kodu → Dur 9 (ayrıntılı)", kod_al(kb.pano_yaz, "x") == 9)
    SahtePopen.yanit = staticmethod(kde_yanit())

    # güvenlik: DUR + meşgul
    n0 = len(SahtePopen.cagrilar)
    guvenlik.dur_ac("kullanici")
    kontrol("kde pano_yaz: DUR açıkken 13, wl-copy ÇALIŞMADI", kod_al(kb.pano_yaz, "x") == 13 and len(SahtePopen.cagrilar) == n0)
    kontrol("kde pano_geri_yukle: DUR açıkken de çalışır (denetimsiz temizlik)",
            kb.pano_geri_yukle({"tur": "text/plain;charset=utf-8", "veri": b"eski", "metin": True}) is None and
            len(SahtePopen.cagrilar) == n0 + 1)
    os.remove(hata.dur_dosyasi())
    KORUMA["hata"] = Dur(15, "kullanıcı film izliyor")
    n0 = len(SahtePopen.cagrilar)
    kontrol("kde pano_yaz: oyun/film (15) → wl-copy ÇALIŞMADI", kod_al(kb.pano_yaz, "x") == 15 and len(SahtePopen.cagrilar) == n0)
    kontrol("kde pano_geri_yukle: meşgulken de çalışır",
            kb.pano_geri_yukle({"bos": True}) is None and cagri_say("wl-copy")[-1].argv == ["wl-copy", "--clear"])
    KORUMA["hata"] = None

    # yedekle / geri yükle
    SahtePopen.yanit = staticmethod(kde_yanit(("text/html", "text/plain;charset=utf-8"), "eski metin".encode()))
    y = kb.pano_yedekle()
    kontrol("kde pano_yedekle: metin varsa metin türü (zengin biçim yalnız metin)", y == {
        "tur": "text/plain;charset=utf-8", "veri": b"eski metin", "metin": True}, str(y))
    n0 = len(SahtePopen.cagrilar)
    kontrol("kde pano_geri_yukle(metin): uyarı yok, --sensitive ile (geçmişe ikinci kopya düşmesin)",
            kb.pano_geri_yukle(y) is None and cagri_say("wl-copy")[-1].argv[-1] == "--sensitive" and
            cagri_say("wl-copy")[-1].girdi == b"eski metin")
    SahtePopen.yanit = staticmethod(kde_yanit(("image/png", "TARGETS"), b"\x89PNGveri"))
    y = kb.pano_yedekle()
    kontrol("kde pano_yedekle: metin dışı → birincil MIME türü + bayt", y["tur"] == "image/png" and y["veri"] == b"\x89PNGveri"
            and y["metin"] is False, str(y))
    uyari = kb.pano_geri_yukle(y)
    c = cagri_say("wl-copy")[-1]
    kontrol("kde pano_geri_yukle(görüntü): birincil tür geri yüklendi + UYARI (diğer biçimler kaybolmuş olabilir)",
            c.argv[:3] == ["wl-copy", "--type", "image/png"] and c.girdi == b"\x89PNGveri" and uyari and "image/png" in uyari,
            f"{c.argv} {uyari}")
    SahtePopen.yanit = staticmethod(kde_yanit((), b"", rc_liste=1))
    kontrol("kde pano_yedekle: boş pano → {'bos': True}; geri yükleme panoyu temizler",
            kb.pano_yedekle() == {"bos": True} and kb.pano_geri_yukle({"bos": True}) is None and
            cagri_say("wl-copy")[-1].argv == ["wl-copy", "--clear"])
    SahtePopen.yanit = staticmethod(lambda argv: (1, b"", "yazılamadı"))
    kontrol("kde pano_geri_yukle: wl-copy başarısızsa istisna YOK, uyarı döner",
            "geri yüklenemedi" in (kb.pano_geri_yukle({"tur": "text/plain", "veri": b"x", "metin": True}) or ""))
    SahtePopen.yanit = staticmethod(kde_yanit())
    kontrol("kde pano_geri_yukle: çok büyük pano → uyarı", "çok büyük" in (kb.pano_geri_yukle({"buyuk": True, "tur": "image/png"}) or ""))

    # zaman aşımı + araç yok + sahte ortam
    SahtePopen.zaman_asimi = True
    kod = kod_al(kb.pano_yaz, "x")
    kontrol("kde: wl-copy bitmezse öldürülür, Dur 7", kod == 7 and cagri_say("wl-copy")[-1].olu, str(kod))
    SahtePopen.zaman_asimi = False
    gercek_popen = SahtePopen.__init__

    def yok(self, *a, **k):
        raise FileNotFoundError("wl-copy")
    SahtePopen.__init__ = yok
    kontrol("kde: wl-clipboard kurulu değil → Dur 9", kod_al(kb.pano_yaz, "x") == 9 and kod_al(kb.pano_oku) == 9)
    SahtePopen.__init__ = gercek_popen
    n0 = len(SahtePopen.cagrilar)
    os.environ["WAYLAND_DISPLAY"] = "/run/user/1/deskhand/sanal-90/wayland-yok"
    kontrol("kde: sahte WAYLAND_DISPLAY (görünmez masaüstü ortamı) → Dur 9, wl-* HİÇ çalışmadı",
            kod_al(kb.pano_oku) == 9 and kod_al(kb.pano_yaz, "x") == 9 and len(SahtePopen.cagrilar) == n0)
    os.environ.pop("WAYLAND_DISPLAY")
    os.environ["DESKHAND_SANAL"] = ":90"
    kontrol("kde: DESKHAND_SANAL ortamında (sanal uygulamanın içinden) ön plan panosuna gidilmez",
            kod_al(kb.pano_oku) == 9 and len(SahtePopen.cagrilar) == n0)
    os.environ.pop("DESKHAND_SANAL")
    kontrol("kde: ham alt süreç denetimi: ortam kullanıcının oturumundan (sahte değil)",
            all(c.env.get("DESKHAND_SANAL") is None for c in SahtePopen.cagrilar))
finally:
    kde.subprocess = KDE_SUBPROCESS
    kde.on_plan_korumasi = GERCEK_KORUMA
    for k_, v_ in env0.items():
        if v_ is not None:
            os.environ[k_] = v_

# ================================================================ 3. MCP clipboard aracı + CLI pano (sahte arka uç)


async def mcp_testleri():
    from mcp import Client

    from deskhand import mcp_sunucu as s
    on_, arka_ = SahtePano("kde"), SahtePano("sanal")
    on_.pano, arka_.pano = "kullanıcının parolası 123", "arka plan panosu"
    arka_uc._ORNEKLER["kde"], arka_uc._ORNEKLER["sanal"] = on_, arka_
    os.environ.pop("DESKHAND_MCP_SADECE_ARKA", None)
    onaylar = []
    asil = s._onay_iste

    def onay_sahte(eylem_, hedef, ayrinti, masaustu_ad, goruntu=None):
        onaylar.append((eylem_, hedef, ayrinti, masaustu_ad))
        return YANIT["izin"], "" if YANIT["izin"] else "red"
    s._onay_iste = onay_sahte
    try:
        def metin(r):
            return "".join(getattr(c, "text", "") for c in r.content)

        async with Client(s.mcp) as c:
            adlar = [t.name for t in (await c.list_tools()).tools]
            kontrol("MCP: clipboard aracı type_text'ten HEMEN sonra", "clipboard" in adlar and
                    adlar.index("clipboard") == adlar.index("type_text") + 1, str(adlar))
            tm = {t.name: t for t in (await c.list_tools()).tools}
            kontrol("MCP: type_text max_length 20000", tm["type_text"].input_schema["properties"]["text"].get("maxLength") == 20000)
            kontrol("MCP: clipboard eylemleri read|write, text isteğe bağlı, desktop var",
                    tm["clipboard"].input_schema["properties"]["action"].get("enum") == ["read", "write"] and
                    "text" in tm["clipboard"].input_schema["properties"] and
                    "desktop" in tm["clipboard"].input_schema["properties"] and
                    tm["clipboard"].input_schema.get("required") == ["action"])

            # ön plan okuma: insan onayı
            YANIT["izin"] = False
            r = await c.call_tool("clipboard", {"action": "read", "desktop": "foreground"})
            kontrol("MCP: ön plan read, onay RED → [10], metin DÖNMEDİ", r.is_error and "[10]" in metin(r) and
                    "parolası" not in metin(r) and len(onaylar) == 1, metin(r)[:200])
            kontrol("MCP: onay isteği içeriği taşımaz (yalnız uzunluk)", "parolası" not in str(onaylar[0]) and
                    "25 karakter" in onaylar[0][2], str(onaylar[0]))
            YANIT["izin"] = True
            r = await c.call_tool("clipboard", {"action": "read", "desktop": "foreground"})
            sy = r.structured_content or {}
            kontrol("MCP: ön plan read, onay İZİN → metin döner, approved_by_user", not r.is_error and
                    sy.get("text") == "kullanıcının parolası 123" and sy.get("approved_by_user") is True, metin(r)[:200])
            YANIT["izin"] = False
            n0 = len(onaylar)
            r = await c.call_tool("clipboard", {"action": "write", "text": "ajanın yazdığı 😀", "desktop": "foreground"})
            kontrol("MCP: ön plan write serbest (onay istemez), hassas=True ile yazıldı", not r.is_error and
                    (r.structured_content or {}).get("status") == "written" and on_.pano == "ajanın yazdığı 😀" and
                    on_.olaylar[-1] == ("pano_yaz", "ajanın yazdığı 😀", True) and len(onaylar) == n0, metin(r)[:200])
            r = await c.call_tool("clipboard", {"action": "read", "desktop": "foreground"})
            kontrol("MCP: kendi yazdığımız metni okumak onay istemez", not r.is_error and
                    (r.structured_content or {}).get("text") == "ajanın yazdığı 😀" and len(onaylar) == n0 and
                    (r.structured_content or {}).get("approved_by_user") is False, metin(r)[:200])
            kontrol("MCP: clipboard(write) özeti TEK kaynakta (guvenlik.kendi_pano_mu: CLI/yapıştırma onayı da görür)",
                    guvenlik.kendi_pano_mu("ajanın yazdığı 😀") and not hasattr(s, "_KENDI_PANO"))
            on_.pano = "kullanıcı başka şey kopyaladı"
            r = await c.call_tool("clipboard", {"action": "read", "desktop": "foreground"})
            kontrol("MCP: kullanıcı panoyu değiştirdi → yine onay gerekir (red)", r.is_error and len(onaylar) == n0 + 1)
            guvenlik.kendi_pano_ekle("CLI pano yaz ile konan metin")  # başka süreç (CLI) yazdı: özet dosyası paylaşılır
            on_.pano = "CLI pano yaz ile konan metin"
            n0 = len(onaylar)
            r = await c.call_tool("clipboard", {"action": "read", "desktop": "foreground"})
            kontrol("MCP: Deskhand'in CLI'den yazdığı metni okumak da onay istemez (ortak özet listesi)",
                    not r.is_error and (r.structured_content or {}).get("text") == "CLI pano yaz ile konan metin" and
                    len(onaylar) == n0, metin(r)[:200])
            # insan önceliği: kde'de (kullanıcının panosu) pano yazmadan önce; arka planda çağrılmaz
            asil_io = guvenlik.insan_onceligi
            io_cagri = []
            guvenlik.insan_onceligi = lambda ne, azami=8.0: io_cagri.append(ne)
            try:
                await c.call_tool("clipboard", {"action": "write", "text": "io", "desktop": "foreground"})
                await c.call_tool("clipboard", {"action": "write", "text": "io", "desktop": "background"})
                kontrol("MCP: clipboard(write) kde'de insan önceliğinden geçer, arka planda geçmez", len(io_cagri) == 1,
                        str(io_cagri))
                guvenlik.insan_onceligi = lambda ne, azami=8.0: (_ for _ in ()).throw(Dur(12, "kullanıcı kullanıyor"))
                n1 = len(on_.olaylar)
                r = await c.call_tool("clipboard", {"action": "write", "text": "y", "desktop": "foreground"})
                kontrol("MCP: kullanıcı klavye/fare kullanıyor → [12], pano yazılmadı",
                        r.is_error and "[12]" in metin(r) and len(on_.olaylar) == n1, metin(r)[:200])
            finally:
                guvenlik.insan_onceligi = asil_io
            on_.pano, arka_.pano = "kullanıcı başka şey kopyaladı", "arka plan panosu"
            # arka plan: serbest
            n0 = len(onaylar)
            r = await c.call_tool("clipboard", {"action": "read", "desktop": "background"})
            kontrol("MCP: arka plan read serbest (onay yok), kendi panosunu okur", not r.is_error and
                    (r.structured_content or {}).get("text") == "arka plan panosu" and len(onaylar) == n0, metin(r)[:200])
            r = await c.call_tool("clipboard", {"action": "write", "text": "", "desktop": "background"})
            kontrol("MCP: write '' → panoyu temizler; sonra read → empty", not r.is_error and arka_.pano is None and
                    (await c.call_tool("clipboard", {"action": "read", "desktop": "background"})).structured_content.get("status") == "empty")
            kontrol("MCP: arka plan write ön plan panosuna dokunmadı", on_.pano == "kullanıcı başka şey kopyaladı")
            r = await c.call_tool("clipboard", {"action": "write", "desktop": "background"})
            kontrol("MCP: write + text yok → [1]", r.is_error and "[1]" in metin(r))
            # DUR + meşgul
            guvenlik.dur_ac("cli")
            n0 = len(on_.olaylar)
            r = await c.call_tool("clipboard", {"action": "write", "text": "x", "desktop": "foreground"})
            kontrol("MCP: DUR → [13], pano yazılmadı", r.is_error and "[13]" in metin(r) and len(on_.olaylar) == n0)
            guvenlik.dur_kapat("cli")
            asil_yaz = on_.pano_yaz
            on_.pano_yaz = lambda t, hassas=True: (_ for _ in ()).throw(Dur(15, "kullanıcı film izliyor"))
            r = await c.call_tool("clipboard", {"action": "write", "text": "x", "desktop": "foreground"})
            kontrol("MCP: oyun/film → [15]", r.is_error and "[15]" in metin(r), metin(r)[:200])
            on_.pano_yaz = asil_yaz
            # büyük pano: kırpılır
            arka_.pano = "ü" * 30000
            r = await c.call_tool("clipboard", {"action": "read", "desktop": "background"})
            sy = r.structured_content or {}
            kontrol("MCP: 30000 karakterlik pano → 20000'e kırpıldı, truncated=true, length gerçek",
                    len(sy.get("text", "")) == 20000 and sy.get("truncated") is True and sy.get("length") == 30000)
            # type_text artık 20000 karaktere izin verir ve yapıştırır
            on_.pano, on_.hedef = "eski", ""
            r = await c.call_tool("type_text", {"window": "{w}", "text": "ö" * 5000 + "😀", "desktop": "foreground"})
            kontrol("MCP: type_text 5001 karakter → yapıştırıldı, hedef birebir, eski pano geri",
                    not r.is_error and on_.hedef == "ö" * 5000 + "😀" and on_.pano == "eski", metin(r)[:200])
            r = await c.call_tool("type_text", {"window": "{w}", "text": "x" * 20001, "desktop": "foreground"})
            kontrol("MCP: type_text 20001 karakter → şema reddi", r.is_error)
    finally:
        s._onay_iste = asil


asyncio.run(mcp_testleri())

# --- CLI k_pano (sahte arka uç)
from deskhand import cli  # noqa: E402

on_ = SahtePano("kde")
on_.pano = "gizli pano içeriği"
arka_uc._ORNEKLER["kde"] = on_
os.environ.pop("DESKHAND_HEDEF", None)
ISTEKLER.clear()
YANIT["izin"] = False
cikti = []
kd_yazdir = sys.stdout


class Tampon:
    def __init__(self): self.s = ""
    def write(self, x): self.s += x; return len(x)
    def flush(self): pass
    def isatty(self): return False


def cli_calistir(**k):
    t = Tampon()
    eski, sys.stdout = sys.stdout, t
    try:
        kod = kod_al(cli.k_pano, argparse.Namespace(**({"komut": "pano", "metin": None, "onayli": False} | k)))
    finally:
        sys.stdout = eski
    return kod, t.s


kod, out = cli_calistir(islem="oku")
kontrol("CLI pano oku (ön plan): onay yok/red → 10, içerik çıktıya düşmedi", kod == 10 and "gizli" not in out and len(ISTEKLER) == 1, f"{kod} {out!r}")
kod, out = cli_calistir(islem="oku", onayli=True)
kontrol("CLI pano oku --onayli: sorulmadan okunur", kod == 0 and out == "gizli pano içeriği" and len(ISTEKLER) == 1, f"{kod} {out!r}")
YANIT["izin"] = True
kod, out = cli_calistir(islem="oku")
kontrol("CLI pano oku: panelden izin → okunur", kod == 0 and out == "gizli pano içeriği" and len(ISTEKLER) == 2, f"{kod} {out!r}")
on_.pano = None
kod, out = cli_calistir(islem="oku", onayli=True)
kontrol("CLI pano oku: boş pano → 6", kod == 6)
kod, out = cli_calistir(islem="yaz", metin="Merhaba 😀\nikinci")
kontrol("CLI pano yaz: yazıldı (hassas), çıktı uzunluk; içerik günlükte yok", kod == 0 and on_.pano == "Merhaba 😀\nikinci" and
        on_.olaylar[-1][2] is True and "Merhaba 😀" not in gunluk_metni(), f"{kod} {out!r}")
kod, out = cli_calistir(islem="oku", metin="x", onayli=True)
kontrol("CLI pano oku metin almaz → 1", kod == 1)
arka_uc._ORNEKLER["sanal"] = SahtePano("sanal")
ISTEKLER.clear()
os.environ["DESKHAND_HEDEF"] = "arka"
kod, out = cli_calistir(islem="oku")
kontrol("CLI pano oku --arka: onay istemez", len(ISTEKLER) == 0 and kod == 0 and out == "eski pano", f"{kod} {out!r}")
os.environ.pop("DESKHAND_HEDEF")

# CLI ayrıştırma (komut adları + Türkçe takma ad; hiçbir pano/girdi işi çalışmaz)
p = cli.ayristirici(sessiz=True)
a1, a2 = p.parse_args(["clipboard", "read", "--approved"]), p.parse_args(["pano", "yaz", "merhaba", "--onayli"])
kontrol("CLI ayrıştırma: clipboard read/write + pano oku/yaz takma adı", a1.komut == "pano" and a1.islem == "oku" and a1.onayli
        and a2.komut == "pano" and a2.islem == "yaz" and a2.metin == "merhaba" and p.parse_args(["pano", "oku"]).islem == "oku")
from deskhand import komutlar  # noqa: E402
adlar = [tr for tr, _en in komutlar.KOMUTLAR]
kontrol("komutlar: ('pano','clipboard') ('bas','hold') satırından hemen sonra",
        komutlar.TR_EN["pano"] == "clipboard" and komutlar.ic_ad("clipboard") == "pano" and adlar.index("pano") == adlar.index("uyu") + 1)

# ================================================================ 4. sanal masaüstü (Xvfb, GÖRÜNMEZ)

arka_uc._ORNEKLER.clear()
# sanal pano yolu kde koduna ASLA girmemeli: wl-* çağrısı olursa test patlasın
kde_cagri = []
kde._wl = lambda *a, **k: kde_cagri.append(a) or (_ for _ in ()).throw(AssertionError("sanal testte wl-clipboard çağrıldı"))

t = time.monotonic()
d = masaustu.masaustu_baslat()
au = arka_uc.sec(arka_bayragi=True)
kontrol("sanal: masaüstü açıldı, arka uç sanal, pano uygulanıyor", au.ad == "sanal" and
        type(au).pano_yaz is not arka_uc.ArkaUc.pano_yaz)
LOG = os.path.join(GECICI, "pano.log")
LOG2 = os.path.join(GECICI, "pano2.log")
p1 = au.baslat([sys.executable, PANO_PENCERE], env={"LOG": LOG, "BASLIK": "pano-test ANA"})
k = bekle(lambda: next((w for w, b, _ in au.pencereler("pano-test ANA")), None), 20, 0.05)
kontrol("sanal: Qt pano test penceresi açıldı", k is not None)
if k is None:
    masaustu.masaustu_durdur()
    sys.exit(1)
bekle(lambda: au.aktif() == k, 3)


def kutu_metni():
    try:
        satirlar = [json.loads(l) for l in open(LOG) if l.startswith("{")]
    except OSError:
        return ""
    return satirlar[-1]["metin"] if satirlar else ""


def temizle_kutu():
    arka_uc._ORNEKLER["sanal"] = au
    with api.hedef("sanal"):
        api.tus(k, "ctrl+a")
        api.tus(k, "delete")
    bekle(lambda: kutu_metni() == "", 3)


# --- pano yardımcısı: ilk kullanım başlatır, kafeste, boş pano
kontrol("sanal pano: ilk durumda boş (None)", au.pano_oku() is None and au.pano_yedekle() == {"metin": None, "metin_disi": False})
t = time.perf_counter()
au.pano_yaz("eski içerik ğüşİ 😀")
olcum["sanal pano_yaz (yardımcıyı başlatan ilk çağrı)"] = f"{(time.perf_counter() - t) * 1000:.0f} ms"
t = time.perf_counter()
oku_metin = au.pano_oku()
olcum["sanal pano_oku"] = f"{(time.perf_counter() - t) * 1000:.1f} ms"
kontrol("sanal pano: yaz → oku (Türkçe + emoji)", oku_metin == "eski içerik ğüşİ 😀", repr(oku_metin))
sureler = []
for i in range(20):
    t = time.perf_counter()
    au.pano_yaz(f"deneme {i}")
    sureler.append((time.perf_counter() - t) * 1000)
olcum["sanal pano_yaz (yardımcı çalışırken)"] = f"{statistics.median(sureler):.1f} ms (medyan, 20)"
au.pano_yaz("eski içerik ğüşİ 😀")


def yardimci_pid():
    for pid in masaustu._kafes_surecleri(d["cgroup"]):
        if any(x.endswith("pano_sahibi.py") for x in masaustu._komut_satiri(pid)):
            return pid
    return None


yp = yardimci_pid()
kontrol("sanal pano: yardımcı süreç masaüstü kafesinde", yp is not None and masaustu._cgroup(yp) == d["cgroup"], str(yp))
yo = masaustu._ortam_oku(yp) if yp else {}
kontrol("sanal pano: yardımcı ortamı sanal (DISPLAY=:N, WAYLAND_DISPLAY sahte, XAUTHORITY masaüstünün)",
        yo.get("DISPLAY") == d["ekran"] and yo.get("XAUTHORITY") == d["xauth"] and
        os.path.basename(yo.get("WAYLAND_DISPLAY", "")) == "wayland-yok", str({a: yo.get(a) for a in ("DISPLAY", "WAYLAND_DISPLAY")}))
sock = os.path.join(d["calisma"], "pano.sock")
kontrol("sanal pano: soket 0600, masaüstü çalışma klasöründe", os.path.exists(sock) and (os.stat(sock).st_mode & 0o777) == 0o600)
au.pano_yaz("başka")
kontrol("sanal pano: ikinci yazma AYNI yardımcıyı kullanır", yardimci_pid() == yp)
au.pano_yaz("")
kontrol("sanal pano: pano_yaz('') → temizle (sahiplik bırakıldı), oku → None", au.pano_oku() is None)
au.pano_yaz("a" * 100)
au.pano_yaz("eski içerik ğüşİ 😀")

# --- büyük metin (INCR): yardımcı → Qt penceresi (yapıştırma) ve Qt → Deskhand (okuma)
buyuk = ("büyük ğüş İÇ 😀 " * 300000)[:3_000_000]
au.pano_yaz(buyuk)
oku_buyuk = au.pano_oku()
kontrol("sanal pano: yardımcının sunduğu 3 MB'ı bizim okuyucumuz INCR ile birebir okur", oku_buyuk == buyuk,
        f"{len(oku_buyuk or '')} / {len(buyuk)}")
kontrol("sanal pano: 64 MB üstü → Dur 1", kod_al(au.pano_yaz, "x" * (65 * 1024 * 1024)) == 1)
au.pano_yaz("eski içerik ğüşİ 😀")

p2 = au.baslat([sys.executable, PANO_PENCERE], env={"LOG": LOG2, "BASLIK": "pano-buyuk", "PANO_BUYUK": "600000"})
bekle(lambda: "pano hazir" in (open(LOG2).read() if os.path.exists(LOG2) else ""), 20, 0.05)
time.sleep(0.3)
beklenen = ("büyük ğüş İÇ 😀 " * (600000 // 14 + 1))[:600000]
t = time.perf_counter()
alinan = au.pano_oku()
olcum["sanal pano_oku (Qt'nin sahip olduğu 600 KB, INCR)"] = f"{(time.perf_counter() - t) * 1000:.0f} ms"
kontrol("sanal pano: BAĞIMSIZ sahip (Qt) 600 KB metni INCR ile birebir okunur", alinan == beklenen, f"{len(alinan or '')} / {len(beklenen)}")
yedek = au.pano_yedekle()
kontrol("sanal pano_yedekle: Qt sahibinden metin alınır", yedek["metin"] == beklenen and not yedek["metin_disi"])
au.pano_geri_yukle(yedek)
kontrol("sanal pano_geri_yukle: 600 KB sahip yardımcıya devredilir, birebir okunur (yardımcı INCR sunar)", au.pano_oku() == beklenen)
p2.terminate()
p2.wait(5)
time.sleep(0.2)
kontrol("sanal pano: eski sahip (Qt) öldü → pano yardımcıda kalır", au.pano_oku() == beklenen)
au.pano_yaz("eski içerik ğüşİ 😀")

# --- gerçek yapıştırma senaryoları (Qt penceresi, ctrl+v → Qt'nin kendi pano okuması)
arka_uc._ORNEKLER["sanal"] = au
temizle_kutu()
EMOJI_UZUN = "Başlık 😀🎉 — çağrı ığüşöç İĞÜŞÖÇ\n" + ("Uzun satır ğüşiöç 😀 " * 15) + "\n\nüçüncü satır\tsekme sonrası 🚀"


def api_yaz(metin, **kw):
    with api.hedef("sanal"):
        t = time.perf_counter()
        r = api.yaz(k, metin, kw.get("baslik"), kw.get("gizli", False), False)
        return r, (time.perf_counter() - t) * 1000


r, ms = api_yaz(EMOJI_UZUN)
olcum["yapıştırma yolu: 4 parça + 2 Enter + Tab (≈330 karakter)"] = f"{ms:.0f} ms"
bekle(lambda: kutu_metni() == EMOJI_UZUN, 3)
kontrol("yapıştır (sanal, GERÇEK Qt): emoji + uzun + çok satırlı + sekme BİREBİR kutuya geldi", kutu_metni() == EMOJI_UZUN,
        repr(kutu_metni())[:300])
kontrol("yapıştır (sanal): çıktı 'panodan yapıştırıldı'", "panodan yapıştırıldı" in r, r)
kontrol("yapıştır (sanal): eski pano GERİ GELDİ", au.pano_oku() == "eski içerik ğüşİ 😀", repr(au.pano_oku()))

# yalnız emoji: sanal arka uç yazılabilir sayar → harf harf (keysym) yolu aynen kalır
temizle_kutu()
t = time.perf_counter()
r, ms = api_yaz("kısa 😀")
bekle(lambda: kutu_metni() == "kısa 😀", 3)
kontrol("yazı: kısa emoji sanalda harf harf yolu (yapıştırma yok), eski pano dokunulmadı",
        kutu_metni() == "kısa 😀" and "panodan" not in r and au.pano_oku() == "eski içerik ğüşİ 😀", f"{kutu_metni()!r} {r}")

# yazilabilir_mi emojiyi reddederse (kde gibi) kısa emoji da yapıştırılır
gercek_yazilabilir = sanal.SanalArkaUc.yazilabilir_mi
sanal.SanalArkaUc.yazilabilir_mi = lambda self, c: ord(c) < 0x10000 and c.isprintable()
try:
    temizle_kutu()
    r, ms = api_yaz("tek 😀 emoji")
    olcum["yapıştırma yolu: kısa emoji (tek parça)"] = f"{ms:.0f} ms"
    bekle(lambda: kutu_metni() == "tek 😀 emoji", 3)
    kontrol("yapıştır: yazilabilir_mi emojiyi reddedince KISA emoji yapıştırılır, pano geri",
            kutu_metni() == "tek 😀 emoji" and "panodan" in r and au.pano_oku() == "eski içerik ğüşİ 😀", f"{kutu_metni()!r} {r}")
finally:
    sanal.SanalArkaUc.yazilabilir_mi = gercek_yazilabilir

# 5000 karakter
temizle_kutu()
uzun5 = "Satır içeriği ğüşiöç 😀. " * 220
r, ms = api_yaz(uzun5)
olcum["yapıştırma yolu: 5500 karakter tek parça"] = f"{ms:.0f} ms"
bekle(lambda: kutu_metni() == uzun5, 3)
kontrol("yapıştır (sanal): 5500 karakterlik tek parça birebir", kutu_metni() == uzun5 and au.pano_oku() == "eski içerik ğüşİ 😀")
# karşılaştırma: aynı uzunluk harf harf olsaydı
olcum["(karşılaştırma) harf harf yazma tahmini 5500 karakter"] = f"≈ {5500 * (HARF_SN_GERCEK + 0.004):.0f} s (harf aralığı {HARF_SN_GERCEK} s + dotool/XTEST süresi)"

# 20 satır
temizle_kutu()
yirmi = "\n".join(f"satır {i} 😀 ığüşöç" for i in range(20))
r, ms = api_yaz(yirmi)
olcum["yapıştırma yolu: 20 satır (20 yapıştırma + 19 Enter)"] = f"{ms:.0f} ms"
bekle(lambda: kutu_metni() == yirmi, 5)
kontrol("yapıştır (sanal): 20 satırlı metin birebir, eski pano geri", kutu_metni() == yirmi and au.pano_oku() == "eski içerik ğüşİ 😀")

# pano boşken yapıştırma → sonra yine boş
au.pano_yaz("")
temizle_kutu()
r, ms = api_yaz("a" * 300)
bekle(lambda: kutu_metni() == "a" * 300, 3)
kontrol("yapıştır (sanal): pano BOŞKEN → yapıştırıldı, sonra pano yine boş (None)", kutu_metni() == "a" * 300 and au.pano_oku() is None)

# eski pano metin DEĞİL (hedef listesi TARGETS ama metin yok): geri yüklenemez → UYARI, pano temizlenir
au.pano_yaz("eski içerik ğüşİ 😀")
temizle_kutu()
r, ms = api_yaz("gizli parola 😀" * 30, gizli=True)
gl = gunluk_metni()
kontrol("yapıştır (sanal): gizli yazı günlüğe yazılmadı ('yapistir ***')", "gizli parola" not in gl and "yapistir ***(" in gl)
bekle(lambda: kutu_metni() == "gizli parola 😀" * 30, 3)
kontrol("yapıştır (sanal): gizli yazı yine de hedefe birebir gitti", kutu_metni() == "gizli parola 😀" * 30)

# --- hata/kesinti (gerçek sanal): DUR yapıştırmalar arasında → eski pano geri
temizle_kutu()
au.pano_yaz("eski içerik ğüşİ 😀")
asil_yaz = au.pano_yaz
sayac = {"n": 0}


def yaz_sonra_dur(metin, hassas=True):
    asil_yaz(metin, hassas)
    sayac["n"] += 1
    if sayac["n"] == 2:
        guvenlik.dur_ac("kullanici")  # ikinci parçanın yazımından sonra, tuşundan önce


au.pano_yaz = yaz_sonra_dur
with api.hedef("sanal"):
    kod = kod_al(api.yaz, k, "parça bir 😀 " * 20 + "\nparça iki 🎉\nparça üç", None, False, False)
au.pano_yaz = asil_yaz
try:
    os.remove(hata.dur_dosyasi())
except OSError:
    pass
time.sleep(0.2)
kontrol("yapıştır (sanal): DUR iki parça sonra → 13; hedefte yalnız ilk parça + Enter",
        kod == 13 and kutu_metni() == "parça bir 😀 " * 20 + "\n", f"{kod} {kutu_metni()!r}")
kontrol("yapıştır (sanal): DUR'da da eski pano GERİ yüklendi", au.pano_oku() == "eski içerik ğüşİ 😀", repr(au.pano_oku()))

# --- CLI uçtan uca (--arka): pano yaz/oku, yaz (yapıştırma), Türkçe takma adlar
def deskhand(*a, girdi=None, sure=60):
    r = subprocess.run([sys.executable, "-m", "deskhand", "--arka", *a], capture_output=True, text=True, cwd=KOK,
                       timeout=sure, input=girdi)
    return r.returncode, r.stdout, r.stderr


kod, out, err = deskhand("clipboard", "write", "CLI'dan yazıldı 😀")
kontrol("cli --arka clipboard write", kod == 0 and "panoya yazıldı" in out and au.pano_oku() == "CLI'dan yazıldı 😀", f"{kod} {out}{err}")
kod, out, err = deskhand("pano", "oku")
kontrol("cli --arka pano oku (Türkçe takma ad): içerik, onay istemez (arka plan)", kod == 0 and out == "CLI'dan yazıldı 😀", f"{kod} {out!r} {err}")
kod, out, err = deskhand("pano", "yaz", girdi="stdin'den\nçok satır\n")
kontrol("cli --arka pano yaz: metin verilmezse stdin'den", kod == 0 and au.pano_oku() == "stdin'den\nçok satır\n", f"{kod} {err}")
temizle_kutu()
kod, out, err = deskhand("yaz", k, "CLI uzun 😀 " * 30)
bekle(lambda: kutu_metni() == "CLI uzun 😀 " * 30, 3)
kontrol("cli --arka yaz: 330 karakter → yapıştırıldı, eski pano (stdin'den…) geri", kod == 0 and "panodan yapıştırıldı" in out
        and kutu_metni() == "CLI uzun 😀 " * 30 and au.pano_oku() == "stdin'den\nçok satır\n", f"{kod} {out}{err}")
au.pano_yaz("")
kod, out, err = deskhand("pano", "oku")
kontrol("cli --arka pano oku: boş pano → 6", kod == 6, f"{kod} {err}")

# --- MCP (sanal) uçtan uca: type_text + clipboard background
async def mcp_sanal():
    from mcp import Client

    from deskhand import mcp_sunucu as s
    async with Client(s.mcp) as c:
        au.pano_yaz("eski içerik ğüşİ 😀")
        temizle_kutu()
        r = await c.call_tool("type_text", {"window": "pano-test ANA", "text": EMOJI_UZUN, "desktop": "background"})
        bekle(lambda: kutu_metni() == EMOJI_UZUN, 3)
        kontrol("MCP (sanal): type_text emoji + çok satırlı → kutuya birebir, eski pano geri",
                not r.is_error and kutu_metni() == EMOJI_UZUN and au.pano_oku() == "eski içerik ğüşİ 😀",
                "".join(getattr(x, "text", "") for x in r.content)[:300])
        r = await c.call_tool("clipboard", {"action": "write", "text": "MCP yazdı ğ😀", "desktop": "background"})
        r2 = await c.call_tool("clipboard", {"action": "read", "desktop": "background"})
        kontrol("MCP (sanal): clipboard write → read", not r.is_error and (r2.structured_content or {}).get("text") == "MCP yazdı ğ😀")
        kontrol("MCP (sanal): clipboard background → onay istenmedi (panel yok), approved_by_user=False",
                (r2.structured_content or {}).get("approved_by_user") is False)


asyncio.run(mcp_sanal())

# --- yardımcı ölürse (bayat soket) yeniden başlar
yp = yardimci_pid()
os.kill(yp, signal.SIGKILL)
bekle(lambda: not masaustu._canli(yp), 3)
au.pano_yaz("yeniden başlayan yardımcı")
yp2 = yardimci_pid()
kontrol("sanal pano: yardımcı öldürülünce (bayat soket) sonraki yazma YENİDEN başlatır", yp2 is not None and yp2 != yp and
        au.pano_oku() == "yeniden başlayan yardımcı", f"{yp} → {yp2}")

# --- kde yolu hiç çağrılmadı
kontrol("sanal testlerinde kde/wl-clipboard yolu HİÇ çağrılmadı (kullanıcının gerçek panosuna dokunulmadı)", not kde_cagri)

# --- masaüstü kapanınca yardımcı da kapanır
cg = d["cgroup"]
masaustu.masaustu_durdur()
kontrol("kapanış: yardımcı süreç öldü, kafes boş", bekle(lambda: not masaustu._canli(yp2), 5) and not masaustu._kafes_surecleri(cg))
kontrol("kapanış: soket + çalışma klasörü silindi", not os.path.exists(os.path.join(d["calisma"], "pano.sock")) and
        not os.path.exists(d["calisma"]))
kontrol("kapanış: masaüstü kapalıyken pano işlemleri Dur 14", kod_al(au.pano_oku) == 14 and kod_al(au.pano_yaz, "x") == 14)

print("\nölçümler:")
for a_, v_ in olcum.items():
    print(f"  {a_}: {v_}")
print(f"\n{GECEN}/{TOPLAM} pano testi geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
