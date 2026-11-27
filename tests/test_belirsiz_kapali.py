"""Belirsiz sayfa = KAPALI-BAŞARISIZ (SON-FIX, rapor-SON-KAPI2 O-1; bulgu sınıfı "Dur → güvenli görünen sonuç").

Çerçeve kararı (erisim.cerceve_karari) Dur 6 / SAYFA_BELIRSIZ verince odak/alan algısı "değil" (False) DEMEZ, "bilinmiyor"
(None) der; çağıranlar bilinmeyeni PAROLA GİBİ ele alır:
1. ALGI listesindeki her işlev belirsizlikte None döner (yeni algı işlevi bu sınıfa girerse ALGI'ya eklenir: TEK yer).
2. type_text (ref'siz k_yaz) ve key (k_tus): panel onayı istenir (ileti "alan türü belirlenemedi"; başlık/belge adı YOK),
   red → 10 ve hiçbir şey gönderilmez; izin → gizli=True (günlükte metin yok, gonderim notu "gizli").
3. read_text (web.oku): belirsizlikte içerik dönmez (Dur 6), ek bekleme ≤ BELIRSIZ_SURE.
4. n4: belirsizlikte yazış başına tek yeniden deneme bütçesi (gizli_karari ≤ ~1 sn; eskiden parola + kart 2×).
5. Negatif (S0): tek pencere, odak parola değil → onay YOK, gizli değil; odak parola → eski davranış.
Senaryolar (sahte AT-SPI, masaüstü yok): S1 aynı başlıklı açılır pencere, S2 ad geride + 2. pencere, S3 kardeş bilinmiyor.

Çalıştır:  python3 tests/test_belirsiz_kapali.py"""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

import argparse
import contextlib
import glob
import io
import os
import time

from PIL import Image

from deskhand import arka_uc, erisim, eylem, gonderim, guvenlik, onay, web, yollar
from deskhand.arka_uc import EKRAN
from deskhand.hata import Dur

GECEN = TOPLAM = 0
eylem.HARF_SN = 0
MF = " — Mozilla Firefox"
SIR = "Sir-Parola-4711"


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


# ---------------------------------------------------------------- sahte AT-SPI (poc_parola.py ile aynı kurgu)
class Cr:
    def __init__(s, a): s.a = a
    def get_name(s): return s.a


class Uy:
    def __init__(s, pid, ad, c): s.pid, s.ad, s.c = pid, ad, c
    def get_process_id(s): return s.pid
    def get_name(s): return s.ad
    def get_child_count(s): return len(s.c)
    def get_child_at_index(s, i): return s.c[i]


class Ms:
    def __init__(s, u): s.u = u
    def get_child_count(s): return len(s.u)
    def get_child_at_index(s, i): return s.u[i]


class At:
    def __init__(s, u): s.m = Ms(u)
    def get_desktop(s, i): return s.m


erisim._surec_akrabasi = lambda a, b: True
erisim._exe = lambda p: "/usr/lib/firefox/firefox"
erisim.erisim_acik = lambda: True
erisim.erisim_ac_garanti = lambda: False
erisim._cerceve_denetle = lambda *a, **k: None
PAROLA = {"id": None}
erisim._odakli_parola = lambda Atspi, c: c is PAROLA["id"]
erisim._odakli_kart = lambda Atspi, c: c is PAROLA["id"]
BASLIK = {"b": ""}


def senaryo(cerceveler, baslik, kardes, parola_var=True):
    crs = [Cr(a) for a in cerceveler]
    PAROLA["id"] = crs[0] if parola_var else None
    BASLIK["b"] = baslik
    erisim._atspi = lambda a=None: At([Uy(4242, "Firefox", crs)])
    erisim._pencere_istegi = lambda k, islem, **ek: {"a11y": "", "pid": "4242", "baslik": baslik, "islem": islem,
                                                     "kardes": kardes, "_pencere": k, **ek}


SENARYOLAR = {
    "S1 aynı başlıklı açılır pencere": (["Giris" + MF, "Giris" + MF], "Giris" + MF, ["Giris" + MF]),
    "S2 ad geride + 2. pencere": (["Haber sitesi" + MF, "Posta" + MF], "Giris" + MF, ["Posta" + MF]),
    "S3 kardeş bilinmiyor + 2 çerçeve": (["Giris" + MF, "Posta" + MF], "Giris" + MF, None),
}

# Belirsizlikte None dönmesi gereken algı işlevleri (TEK liste: sınıf genişlerse buraya ekle).
ALGI = {
    "odakli_parola_mi": lambda k: erisim.odakli_parola_mi(k),
    "odakli_kart_mi": lambda k: erisim.odakli_kart_mi(k),
    "yerel_diyalog_mu": lambda k: erisim.yerel_diyalog_mu(k),
    "odak_bilgisi": lambda k: erisim.odak_bilgisi(k),
    "odakli_metin": lambda k: erisim.odakli_metin(k),
    "ucbirim_ogesi_var_mi": lambda k: erisim.ucbirim_ogesi_var_mi(k),
    "eylem._parola_alani_mi": lambda k: eylem._parola_alani_mi(k),
}


# ---------------------------------------------------------------- sahte arka uç + onay paneli
class SahteGirdi:
    def __init__(self, au, etiket="", gizli=False, etk=None, denetle=None):
        self.au, self.etiket, self.gizli = au, etiket, gizli
        self.kesildi, self.hazir, self.etk, self.son_fare = None, True, None, (5, 5)
        au.girdiler.append(self)

    def gonder(self, k, desen, *satirlar):
        self.au.satirlar.extend(satirlar)

    def ham(self, s): self.au.satirlar.append(s)
    def zorla(self, s): self.au.satirlar.append(s)
    def izle(self, k, desen): pass
    def izle_bitir(self): pass
    def etk_denetle(self, ne=None): pass
    def insan_kontrol(self): pass
    def kapat(self): pass


class SahteAU(arka_uc.ArkaUc):
    pano_bekle = 0.0

    def __init__(self):
        self.ad = "kde"
        self.pano, self.satirlar, self.girdiler = "eski pano", [], []

    def pencere_coz(self, arg): return arg
    def pencereler(self, desen=None): return []
    def geometri(self, k): return (100, 100, 800, 600) if k != EKRAN else (0, 0, 1920, 1080)
    def baslik(self, k): return BASLIK["b"]
    def sinif(self, k): return "firefox"
    def pid(self, k): return 4242
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
    def pano_oku(self): return self.pano
    def pano_yaz(self, metin, hassas=True): self.pano = metin or None
    def pano_yedekle(self): return {"metin": self.pano}
    def pano_geri_yukle(self, yedek): self.pano = yedek.get("metin")


ISTEKLER, YANIT = [], {"izin": False}


def _iste(eylem_, hedef, ayrinti, **k):
    ISTEKLER.append({"eylem": eylem_, "hedef": hedef, "ayrinti": ayrinti})
    return onay.OnaySonucu(YANIT["izin"], "izin" if YANIT["izin"] else "red")


onay.iste_sonuc = _iste


def ns(**k):
    a = argparse.Namespace(baslik=None, onayli=False, gizli=False, kimlik="{w}")
    for x, v in k.items():
        setattr(a, x, v)
    return a


def calistir(au, f, *a):
    """→ (kod, Dur iletisi, stdout+stderr)"""
    arka_uc._ORNEKLER["kde"] = au
    cikti = io.StringIO()
    kod, mesaj = 0, ""
    guvenlik._EYLEM.onaylandi = False
    with arka_uc.hedef_sabit("kde"), contextlib.redirect_stdout(cikti), contextlib.redirect_stderr(cikti):
        try:
            f(*a)
        except Dur as e:
            kod, mesaj = e.kod, e.mesaj
    return kod, mesaj, cikti.getvalue()


def gunluk_metni():
    return "".join(open(f).read() for f in glob.glob(os.path.join(yollar.gunluk_dizin(), "*.log")))


def sizinti_yok(istek):
    s = str(istek)
    return "Giris" not in s and "Haber" not in s and "Posta" not in s and SIR not in s


os.environ.pop("DESKHAND_GOREV", None)
for kapsam in ("hepsi",):
    guvenlik.onay_kapsami = (lambda d: (lambda: d))(kapsam)
    for ad, (cer, bas, kar) in SENARYOLAR.items():
        senaryo(cer, bas, kar)
        # 1. algı → None
        for algi, f in ALGI.items():
            with arka_uc.hedef_sabit("kde"):
                arka_uc._ORNEKLER["kde"] = SahteAU()
                try:
                    r = f("{w}")
                except Dur as e:
                    r = f"Dur {e.kod}"
                except Exception as e:  # noqa: BLE001 - işlev yok / beklenmedik hata: KALDI olarak görünsün
                    r = type(e).__name__
            kontrol(f"[{ad}] {algi} → None (bilinmiyor)", r is None, repr(r))
        # 4. n4: gizli_karari belirsizlikte tek yeniden deneme bütçesi
        with arka_uc.hedef_sabit("kde"):
            arka_uc._ORNEKLER["kde"] = SahteAU()
            t = time.monotonic()
            g, p, k_, s4 = eylem.gizli_karari("{w}", "abc")
            sure = time.monotonic() - t
        kontrol(f"[{ad}] gizli_karari: gizli=True, parola=None, süre ≤ 1,3 sn (n4)", g is True and p is None
                and sure <= 1.3, f"{g} {p} {sure:.2f}")
        # 2a. type_text ref'siz: red → 10, girdi yok, ileti alan türü belirlenemedi, başlık yok
        ISTEKLER.clear()
        YANIT["izin"] = False
        au = SahteAU()
        kod, mesaj, cikti = calistir(au, eylem.k_yaz, ns(metin=SIR))
        kontrol(f"[{ad}] type_text: onay istendi, red → 10, hiçbir şey gönderilmedi",
                kod == 10 and len(ISTEKLER) == 1 and not au.satirlar, f"{kod} {mesaj} {ISTEKLER} {au.satirlar[:2]}")
        kontrol(f"[{ad}] type_text onay iletisi: 'alan türü belirlenemedi', başlık/sır YOK",
                ISTEKLER and "alan türü belirlenemedi" in ISTEKLER[0]["ayrinti"] and sizinti_yok(ISTEKLER)
                and ISTEKLER[0]["hedef"] == "" and SIR not in mesaj and SIR not in cikti, str(ISTEKLER))
        # 2b. izin → yazıldı, gizli
        ISTEKLER.clear()
        YANIT["izin"] = True
        au = SahteAU()
        kod, mesaj, cikti = calistir(au, eylem.k_yaz, ns(metin=SIR))
        kontrol(f"[{ad}] type_text izin → yazıldı, gizli=True (girdi + gonderim notu), günlük/çıktıda sır YOK",
                kod == 0 and len(ISTEKLER) == 1 and au.girdiler and au.girdiler[-1].gizli is True
                and gonderim.not_al("gizli") is True and SIR not in gunluk_metni() and SIR not in cikti,
                f"{kod} {mesaj} {[g.gizli for g in au.girdiler]} {gonderim.not_al('gizli')}")
        # 2c. key (yazı tuşu): red → 10, gönderim yok; izin → gizli
        ISTEKLER.clear()
        YANIT["izin"] = False
        au = SahteAU()
        kod, mesaj, _o = calistir(au, eylem.k_tus, ns(kombinasyon="a"))
        kontrol(f"[{ad}] key 'a': onay istendi, red → 10, tuş gönderilmedi, ileti başlıksız",
                kod == 10 and len(ISTEKLER) == 1 and not au.satirlar and sizinti_yok(ISTEKLER)
                and "alan türü belirlenemedi" in ISTEKLER[0]["ayrinti"], f"{kod} {mesaj} {ISTEKLER}")
        YANIT["izin"] = True
        au = SahteAU()
        kod, mesaj, _o = calistir(au, eylem.k_tus, ns(kombinasyon="a"))
        kontrol(f"[{ad}] key 'a' izin → gönderildi, girdi gizli", kod == 0 and au.girdiler and au.girdiler[-1].gizli
                is True, f"{kod} {mesaj}")
        YANIT["izin"] = False

    # 3. read_text: belirsizlikte içerik yok, sınırlı bekleme
    _onceki = web._oku_bir

    def _belirsiz_oku(*a, **k):
        raise Dur(6, "sayfa belirsiz", tur=erisim.SAYFA_BELIRSIZ)
    web._oku_bir = _belirsiz_oku
    t = time.monotonic()
    try:
        r = web.oku("{w}")
    except Dur as e:
        r = e
    sure = time.monotonic() - t
    web._oku_bir = _onceki
    kontrol("read_text (web.oku) belirsiz → Dur 6, içerik yok, ≤ BELIRSIZ_SURE + 0,2 sn",
            isinstance(r, Dur) and r.kod == 6 and sure <= erisim.BELIRSIZ_SURE + 0.2, f"{r!r} {sure:.2f}")

    # 5. negatif S0: tek pencere, odak parola DEĞİL → onay yok, gizli değil; odak parola → eski kural (onay)
    senaryo(["Giris" + MF], "Giris" + MF, [], parola_var=False)
    ISTEKLER.clear()
    au = SahteAU()
    kod, mesaj, _o = calistir(au, eylem.k_yaz, ns(metin="merhaba"))
    kontrol("S0 negatif: tek pencere, parola alanı değil → onaysız yazıldı, gizli değil",
            kod == 0 and not ISTEKLER and au.girdiler and au.girdiler[-1].gizli is False, f"{kod} {mesaj} {ISTEKLER}")
    with arka_uc.hedef_sabit("kde"):
        kontrol("S0 negatif: odakli_parola_mi → False (bilinen)", erisim.odakli_parola_mi("{w}") is False)
    # S4: uygulamanın erişilebilirlik ağacı yok (PID bilinmiyor → Dur tur agacta_yok): algılanacak alan yok → False
    # (sayfa tetikleyemez; önceki davranış — her ağaçsız uygulamada her yazı onay istemesin)
    senaryo(["Giris" + MF], "Giris" + MF, [], parola_var=False)
    _pi = erisim._pencere_istegi
    erisim._pencere_istegi = lambda k, islem, **ek: {**_pi(k, islem, **ek), "pid": ""}  # noqa: B023
    with arka_uc.hedef_sabit("kde"):
        kontrol("S4 ağaç yok (agacta_yok): odakli_parola_mi / odakli_kart_mi → False (bilinen: alan yok)",
                erisim.odakli_parola_mi("{w}") is False and erisim.odakli_kart_mi("{w}") is False)
    ISTEKLER.clear()
    au = SahteAU()
    kod, mesaj, _o = calistir(au, eylem.k_yaz, ns(metin="merhaba"))
    kontrol("S4 ağaç yok: onaysız yazıldı, gizli değil", kod == 0 and not ISTEKLER and au.girdiler[-1].gizli is False,
            f"{kod} {mesaj}")
    erisim._pencere_istegi = _pi
    senaryo(["Giris" + MF], "Giris" + MF, [], parola_var=True)
    ISTEKLER.clear()
    au = SahteAU()
    kod, mesaj, _o = calistir(au, eylem.k_yaz, ns(metin=SIR))
    kontrol("S0 parola alanı (bilinen): onay istendi, ileti 'Parola alanına yaz' (eski davranış)",
            kod == 10 and len(ISTEKLER) == 1 and "alan türü belirlenemedi" not in ISTEKLER[0]["ayrinti"],
            f"{kod} {ISTEKLER}")

# ---------------------------------------------------------------- n4, onay kapsamı "kart" (parola + kart sorgusu)
guvenlik.onay_kapsami = lambda: "kart"
for ad, (cer, bas, kar) in SENARYOLAR.items():
    senaryo(cer, bas, kar)
    with arka_uc.hedef_sabit("kde"):
        arka_uc._ORNEKLER["kde"] = SahteAU()
        t = time.monotonic()
        g, p, k_, s4 = eylem.gizli_karari("{w}", "abc")
        sure = time.monotonic() - t
    print(f"ÖLÇÜM n4 [{ad}] kapsam=kart gizli_karari {sure:.2f} sn")
    kontrol(f"[{ad}] kapsam kart: gizli_karari gizli=True, parola=None, tek yeniden deneme bütçesi (≤ 1,3 sn, n4)",
            g is True and p is None and sure <= 1.3, f"{g} {p} {sure:.2f}")
guvenlik.onay_kapsami = lambda: "hepsi"

# ---------------------------------------------------------------- _web_sec: belirsizlik genel ağaca düşürülmez
senaryo(*SENARYOLAR["S1 aynı başlıklı açılır pencere"])
_o1, _o2, _o3 = web.tarayici_mi, web.hazirla, web.oge_ve_sayfa
web.tarayici_mi = lambda k: True
web.hazirla = lambda k: None


def _oge_belirsiz(*a, **k):
    raise Dur(6, "sayfa belirsiz", tur=erisim.SAYFA_BELIRSIZ)


web.oge_ve_sayfa = _oge_belirsiz
try:
    r = erisim._web_sec(ns(ad="Gönder", rol=None, sira=None, ref_oge=None), "klavye")
except Dur as e:
    r = e
kontrol("_web_sec: web yolu SAYFA_BELIRSIZ → Dur (genel ağaca düşmez, None DEĞİL)",
        isinstance(r, Dur) and r.tur == erisim.SAYFA_BELIRSIZ, repr(r))


def _oge_yok(*a, **k):
    raise Dur(6, "öge yok")


web.oge_ve_sayfa = _oge_yok
kontrol("_web_sec: sayfada öge yok (Dur 6, belirsiz değil) → None (genel ağaç; eski davranış)",
        erisim._web_sec(ns(ad="Gönder", rol=None, sira=None, ref_oge=None), "klavye") is None)
web.tarayici_mi, web.hazirla, web.oge_ve_sayfa = _o1, _o2, _o3

# ---------------------------------------------------------------- uçbirim algısı: bilinmiyor → uçbirim say, önbelleğe ALMA
senaryo(*SENARYOLAR["S3 kardeş bilinmiyor + 2 çerçeve"])
guvenlik._UCBIRIM_ONBELLEK.clear()
_pp = guvenlik._pencere_pid
guvenlik._pencere_pid = lambda au, k: None  # PID'siz pencere: erişilebilirlik dalı
au = SahteAU()
au.sinif = lambda k: "bilinmeyen-uygulama"
arka_uc._ORNEKLER["kde"] = au
with arka_uc.hedef_sabit("kde"):
    kontrol("ucbirim_penceresi_mi: algı belirsiz → True (Enter kapısı açık kalmaz), önbelleğe alınmaz",
            guvenlik.ucbirim_penceresi_mi("{w}") is True and not guvenlik._UCBIRIM_ONBELLEK)
guvenlik._pencere_pid = _pp

print(f"\n{GECEN}/{TOPLAM} geçti")
raise SystemExit(0 if GECEN == TOPLAM else 1)
