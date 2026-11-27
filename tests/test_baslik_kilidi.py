"""CLI otomatik başlık kilidi: kimlikle verilen girdi komutlarında (yaz, tus, tikla, kaydir; yalnız tarayıcı pencereleri) -b yoksa şimdiki TAM
başlığa kilit (^…$); --no-title-lock kapatır; komut sırasında başlık değişince Dur 4 + "-b ile esnek desen" iletisi.
Sahte arka uç (ekransız). Çalıştır:  python3 tests/test_baslik_kilidi.py"""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

import contextlib
import io
import re

from PIL import Image

from deskhand import arka_uc, cli, eylem, hata
from deskhand.arka_uc import EKRAN

GECEN = TOPLAM = 0
eylem.HARF_SN = 0


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


class SahteGirdi:
    def __init__(self, au, etiket="", gizli=False, etk=None, denetle=None):
        self.au, self.etiket, self.gizli, self.denetle = au, etiket, gizli, denetle
        self.kesildi, self.hazir, self.etk, self.son_fare = None, True, None, (5, 5)

    def gonder(self, k, desen, *satirlar):
        hata.dur_denetle()
        if self.denetle:
            self.denetle(k, desen)
        self.au.satirlar.extend(satirlar)
        self.au.gonderim += 1

    def ham(self, s):
        if self.denetle:
            self.denetle("{w}", self.au.son_desen)
        self.au.satirlar.append(s)
        self.au.gonderim += 1

    def zorla(self, s): self.au.satirlar.append(s)
    def izle(self, k, desen): self.au.son_desen = desen
    def izle_bitir(self): pass
    def etk_denetle(self, ne=None): pass
    def insan_kontrol(self): pass
    def kapat(self): pass


class SahteAU(arka_uc.ArkaUc):
    def __init__(self, degis_sonra=None):
        self.ad = "kde"
        self.satirlar, self.gonderim, self.degis_sonra, self.son_desen = [], 0, degis_sonra, None
        self.sinif_adi = "firefox"  # otomatik kilit YALNIZ tarayıcı pencerelerinde

    def pencere_coz(self, arg): return "{w}" if arg in ("{w}", "Belge") else arg
    def pencereler(self, desen=None): return []
    def geometri(self, k): return (100, 100, 800, 600) if k != EKRAN else (0, 0, 1920, 1080)

    def baslik(self, k):
        if self.degis_sonra is not None and self.gonderim >= self.degis_sonra:
            return "Başka sekme — KWrite"
        return "Belge (1) [taslak] — KWrite"

    def sinif(self, k): return self.sinif_adi
    def aktif(self): return "{w}"
    def one_getir(self, k): pass
    def kapat(self, k): pass
    def fare(self): return 150, 150, "{w}"
    def ekran_alani(self): return (0, 0, 1920, 1080)
    def goruntu(self): return Image.new("RGB", (1920, 1080), (200, 200, 200))
    def insan_var_mi(self): return False
    def baslat(self, argv, env=None, cikti=None): raise AssertionError("başlatılmamalı")
    def yazilabilir_mi(self, c): return c.isprintable()
    def gecerli_tuslar(self): return None
    def girdi(self, etiket="", gizli=False, etk=None, denetle=None): return SahteGirdi(self, etiket, gizli, etk, denetle)


def ayristir(*argv):
    a = cli.ayristirici().parse_args(list(argv))
    a.kimlik_ham = a.kimlik
    a.kimlik = SahteAU().pencere_coz(a.kimlik)
    return a


au = SahteAU()
for argv in (("yaz", "{w}", "x"), ("tus", "{w}", "enter"), ("tikla", "{w}", "5", "5"), ("kaydir", "{w}")):
    a = ayristir(*argv)
    kontrol(f"{argv[0]} KİMLİKLE, -b yok → tam başlık kilidi ^…$", cli.otomatik_baslik_kilidi(a, au) and
            a.baslik == "^" + re.escape("Belge (1) [taslak] — KWrite") + "$", str(getattr(a, "baslik", None)))
    kontrol(f"{argv[0]}: kilit kendi başlığıyla eşleşir (özel karakterler kaçışlı)",
            re.search(a.baslik, "Belge (1) [taslak] — KWrite", re.I) is not None)
a = ayristir("yaz", "{w}", "x", "-b", "Belge")
kontrol("-b verildiyse dokunulmaz", not cli.otomatik_baslik_kilidi(a, au) and a.baslik == "Belge")
a = ayristir("yaz", "{w}", "x", "--no-title-lock")
kontrol("--no-title-lock → kilit yok", not cli.otomatik_baslik_kilidi(a, au) and not getattr(a, "baslik", None))
a = ayristir("yaz", "{w}", "x", "--baslik-kilitsiz")
kontrol("Türkçe --baslik-kilitsiz → kilit yok", not cli.otomatik_baslik_kilidi(a, au))
a = ayristir("yaz", "Belge", "x")
kontrol("başlık DESENİYLE verilen pencere (kimlik değil) → otomatik kilit yok", not cli.otomatik_baslik_kilidi(a, au))
a = ayristir("dizi", "{w}")
kontrol("dizi otomatik kilit kapsamı DIŞINDA (adımlar arasında sayfa değişimi olağan)", not cli.otomatik_baslik_kilidi(a, au))
for sinif_ in ("kwrite", "org.kde.konsole", "com.mitchellh.ghostty", "zenity"):
    au_ = SahteAU(); au_.sinif_adi = sinif_
    a = ayristir("yaz", "{w}", "x")
    kontrol(f"tarayıcı olmayan pencere ({sinif_}) → otomatik kilit yok (başlık yazarken değişir)",
            not cli.otomatik_baslik_kilidi(a, au_) and not getattr(a, "baslik", None))
au_ = SahteAU()


def _sinif_okunamaz(k):
    raise hata.Dur(5, "sınıf okunamadı (taklit)")


au_.sinif = _sinif_okunamaz
a = ayristir("yaz", "{w}", "x")
kontrol("DH-TUR2: pencere sınıfı okunamadı (bilinmiyor) → kilit YİNE konur (kapalı-başarısız)",
        cli.otomatik_baslik_kilidi(a, au_) and a.baslik == "^" + re.escape("Belge (1) [taslak] — KWrite") + "$",
        str(getattr(a, "baslik", None)))
import os as _os
_eski = cli._masa_secenegi(["--no-title-lock", "yaz", "{w}", "x"])
kontrol("--no-title-lock komuttan ÖNCE: argv'den soyulur, ortam bayrağı konur",
        _eski == ["yaz", "{w}", "x"] and _os.environ.get(cli.BASLIK_KILITSIZ_ORTAM) == "1", str(_eski))
a = ayristir("yaz", "{w}", "x")
kontrol("ortam bayrağı varken otomatik kilit yok", not cli.otomatik_baslik_kilidi(a, au))
_os.environ.pop(cli.BASLIK_KILITSIZ_ORTAM, None)
a = ayristir("metne-tikla", "{w}", "Kaydet")
kontrol("listede olmayan komut (metne-tikla) → otomatik kilit yok", not cli.otomatik_baslik_kilidi(a, au))

# uçtan uca (cli.main, sahte arka uç): komut sırasında başlık değişir → Dur 4 + yönlendirme iletisi
for degis, beklenen in ((None, 0), (2, 4)):
    au = SahteAU(degis_sonra=degis)
    arka_uc._ORNEKLER["kde"] = au
    hata_ = io.StringIO()
    kod = 0
    with arka_uc.hedef_sabit("kde"), contextlib.redirect_stderr(hata_), contextlib.redirect_stdout(io.StringIO()):
        try:
            cli.main(["yaz", "{w}", "merhabadunyanasilsin"])  # boşluksuz: sahte tarayıcı sayfası okunamaz (R1)
        except SystemExit as e:
            kod = e.code or 0
    if beklenen == 0:
        kontrol("başlık değişmezse yazı tamam (otomatik kilit engel olmaz)", kod == 0, f"{kod} {hata_.getvalue()}")
    else:
        kontrol("başlık komut sırasında değişince Dur 4", kod == 4, f"{kod} {hata_.getvalue()}")
        kontrol("ileti: -b ile esnek desen / --no-title-lock yönlendirmesi",
                "-b ile esnek" in hata_.getvalue() and "--no-title-lock" in hata_.getvalue(), hata_.getvalue())
        kontrol("başlık değiştikten sonra yazı sürmedi", au.gonderim <= 3, str(au.gonderim))

print(f"\n{GECEN}/{TOPLAM} başlık kilidi testi geçti")
raise SystemExit(0 if GECEN == TOPLAM else 1)
