"""Onay kapsamı (`ayarlar.toml` [guvenlik] onaylar = hepsi | kart) testleri.

  hepsi (varsayılan): bugünkü davranış (her serbest bırakılan noktada onay ister).
  kart: YALNIZ para düğmesi/ödeme sayfası ve kart bilgisi yazma onay ister (CLI --onayli yok sayılır, gözetimsiz → ret);
        uçbirim Enter, yıkıcı komut, riskli tuş, parola alanı, pano/yapıştırma, open_app, sistem istemi, hesap silme/OAuth
        düğmeleri onaysız geçer; kendi istemci, open_app kara listesi vb. korumalar aynen sürer.

Ekransız (sahte arka uç) + bir uçtan uca (görünmez sanal masaüstü, Xvfb, mini uçbirim penceresi). Gerçek ekrana/panoya
girdi yok; gerçek ~/.config yazılmaz (_yalitim). Çalıştır:  python3 tests/test_onay_kapsami.py"""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

import argparse
import atexit
import contextlib
import io
import os
import sys
import time

from PIL import Image

from deskhand import arka_uc, ayarlar, cli, doktor, eylem, guvenlik, hata, masaustu, onay, uygulama, yollar
from deskhand.arka_uc import EKRAN
from deskhand.hata import Dur

GECEN = TOPLAM = 0
KOK = _yalitim.KOK
TEST_PENCERE = os.path.join(KOK, "tests", "yardimci", "test_pencere.py")
atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
os.environ.pop("DESKHAND_GOZETIMSIZ", None)


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


def kapsam(deger):
    ayarlar.ayarla("guvenlik", "onaylar", deger)
    guvenlik.onay_kapsami_sifirla()
    return guvenlik.onay_kapsami() == deger


# ---------------------------------------------------------------- sahte arka uç (test_riskli kalıbı)
class SahteGirdi:
    def __init__(self, au, etiket="", gizli=False, etk=None, denetle=None):
        self.au, self.etiket, self.gizli, self.denetle = au, etiket, gizli, denetle
        self.etk, self.kesildi, self.hazir, self.son_fare = None, None, True, au.fare()[:2]
        self.son_etk = time.monotonic()

    def gonder(self, k, desen, *satirlar):
        hata.dur_denetle()
        if self.denetle:
            self.denetle(k, desen)
        guvenlik.girdi_seviye_denetle(k, satirlar)
        for s in satirlar:
            self.au.satirlar.append(s)

    def ham(self, s): self.au.satirlar.append(s)
    def zorla(self, s): self.au.satirlar.append(s)
    def izle(self, k, desen): pass
    def izle_bitir(self): pass
    def etk_denetle(self, ne=None): pass
    def insan_kontrol(self): pass
    def kapat(self): pass


class SahteAU(arka_uc.ArkaUc):
    def __init__(self, ad="kde"):
        self.ad = ad
        self.pen = {"{t}": ["Terminal", "org.kde.konsole", (100, 100, 800, 600)],
                    "{n}": ["Notlar", "org.kde.kate", (100, 100, 800, 600)],
                    "{o}": ["Ödeme - Mağaza", "firefox", (100, 100, 800, 600)],
                    "{p}": ["Kimlik doğrulama", "polkit-kde-authentication-agent-1", (100, 100, 800, 600)]}
        self.imlec, self.satirlar, self.pano, self.on = (5, 5), [], "kullanicinin-panosu", "{n}"

    def pencere_coz(self, arg): return arg
    def pencereler(self, desen=None): return []
    def geometri(self, k): return self.pen[k][2] if k != EKRAN else (0, 0, 1920, 1080)
    def baslik(self, k): return self.pen.get(k, [""])[0]
    def sinif(self, k): return self.pen.get(k, ["", ""])[1]
    def aktif(self): return self.on
    def one_getir(self, k): self.on = k
    def kapat(self, k): pass
    def ekran_alani(self): return (0, 0, 1920, 1080)
    def goruntu(self): return Image.new("RGB", (1920, 1080), (200, 200, 200))
    def insan_var_mi(self): return False
    def baslat(self, argv, env=None, cikti=None): raise AssertionError("başlatılmamalı")
    def gecerli_tuslar(self): return None
    def pano_oku(self): return self.pano
    def fare(self): return (5, 5, "{masaustu}")
    def girdi(self, etiket="", gizli=False, etk=None, denetle=None): return SahteGirdi(self, etiket, gizli, etk, denetle)


def ns(**k):
    a = argparse.Namespace(baslik=None, onayli=False, gizli=False, kimlik="{n}")
    for x, v in k.items():
        setattr(a, x, v)
    return a


ISTEKLER = []
YANIT = {"izin": False}


def sahte_iste_sonuc(eylem_, hedef, ayrinti="", masaustu="ekran", sure=120, goruntu=None, gunluge_yaz=True):
    ISTEKLER.append({"eylem": eylem_, "hedef": hedef, "ayrinti": ayrinti})
    return onay.OnaySonucu(YANIT["izin"], "izin" if YANIT["izin"] else "red")


gercek_iste_sonuc = onay.iste_sonuc
onay.iste_sonuc = sahte_iste_sonuc
au = SahteAU("kde")
arka_uc._ORNEKLER["kde"] = au


def temiz():
    ISTEKLER.clear()
    YANIT["izin"] = False
    del au.satirlar[:]


def sorar(f, *a, **k):
    """→ (kod, sorulan onay sayısı, gönderilen girdi sayısı)"""
    temiz()
    kod = kod_al(f, *a, **k)
    return kod, len(ISTEKLER), len(au.satirlar)


def hepsi_ve_kart(ad, f, *a, **k):
    """Bir serbest bırakılan nokta: hepsi → onay ister (red → 10, girdi yok); kart → sormadan geçer."""
    assert kapsam("hepsi")
    kod, n, g = sorar(f, *a, **k)
    kontrol(f"{ad}: hepsi → onay ister (red → 10)", kod == 10 and n == 1 and g == 0, f"{kod} {n} {g}")
    assert kapsam("kart")
    kod, n, g = sorar(f, *a, **k)
    kontrol(f"{ad}: kart → onaysız geçer", kod == 0 and n == 0, f"{kod} {n} {g}")
    return g


kontrol("varsayılan onay kapsamı = hepsi (ayar dosyası yok)", guvenlik.onay_kapsami(taze=True) == "hepsi" and
        ayarlar.VARSAYILAN["guvenlik"]["onaylar"] == "hepsi")
for kotu in ("para-parola", "kart ", 3):
    try:
        ayarlar.dogrula("guvenlik", "onaylar", kotu)
        kontrol(f"ayar doğrulama: {kotu!r} reddedilir", False)
    except ValueError:
        kontrol(f"ayar doğrulama: {kotu!r} reddedilir", True)
kontrol("ayar yazıldı geçici CONFIG'e", kapsam("kart") and ayarlar.dosya().startswith(_yalitim.GECICI))
kapsam("hepsi")

with arka_uc.hedef_sabit("kde"):
    # ================================================================ SERBEST BIRAKILANLAR
    hepsi_ve_kart("uçbirim Enter (eylem.k_tus)", eylem.k_tus, ns(kimlik="{t}", kombinasyon="enter"))
    kontrol("uçbirim Enter: kart → tuş gerçekten gönderildi", any("enter" in s.lower() or "return" in s.lower()
                                                                  for s in au.satirlar), str(au.satirlar))
    hepsi_ve_kart("uçbirime yıkıcı komut yazma", eylem.k_yaz, ns(kimlik="{t}", metin="rm -rf build"))
    hepsi_ve_kart("riskli tuş ctrl+alt+f3", eylem.k_tus, ns(kimlik="{n}", kombinasyon="ctrl+alt+f3"))
    hepsi_ve_kart("parola alanına yazma (parola_alani_engel)", guvenlik.parola_alani_engel, "{n}", False, 5, "yazı")
    hepsi_ve_kart("yapıştırma ctrl+v (pano okuma)", eylem.k_tus, ns(kimlik="{n}", kombinasyon="ctrl+v"))
    hepsi_ve_kart("ac --komut yıkıcı komut", guvenlik.baslatma_komut_engel, "rm -rf build")
    hepsi_ve_kart("menüden yapıştırma (hassas_engel → yapistirma_engel)", guvenlik.hassas_engel, False, "Yapıştır",
                  k="{n}")

    def cli_pano_oku(**k):
        with contextlib.redirect_stdout(io.StringIO()):
            cli.k_pano(ns(islem="oku", metin=None, **k))
    hepsi_ve_kart("CLI pano oku", cli_pano_oku)

    # sistem istemi (polkit penceresi): kart kipinde de onaysız
    hepsi_ve_kart("sistem istemi (polkit) tuş", eylem.k_tus, ns(kimlik="{p}", kombinasyon="a"))
    # hesap silme / OAuth düğmeleri: kart kipinde onaysız
    for dugme in ("Hesabı sil", "İzin ver", "Authorize", "Yetkilendir", "Allow", "Delete my account"):
        hepsi_ve_kart(f"hassas düğme {dugme!r} (para değil)", guvenlik.hassas_engel, False, dugme, k=None)

    # ================================================================ MCP clipboard read
    try:
        from deskhand import mcp_sunucu
        f_ = getattr(mcp_sunucu.clipboard, "fn", mcp_sunucu.clipboard)
        sonuc = {}

        def mcp_pano(ad):
            assert kapsam(ad)
            temiz()
            try:
                f_(action="read", desktop="foreground")
                return "ok"
            except Exception as e:  # noqa: BLE001
                return str(e)
        sonuc["hepsi"], n1 = mcp_pano("hepsi"), len(ISTEKLER)
        sonuc["kart"], n2 = mcp_pano("kart"), len(ISTEKLER)
        if n1 == 1:
            kontrol("MCP clipboard read: hepsi → onay ister", sonuc["hepsi"] != "ok", str(sonuc))
            kontrol("MCP clipboard read: kart → onaysız okur", n2 == 0 and sonuc["kart"] == "ok", str(sonuc))
        else:
            print(f"ATLANDI  MCP clipboard read (sahte kde arka ucu MCP bağlamında kullanılamadı: {sonuc})")
    except ImportError as e:
        print(f"ATLANDI  MCP testleri (mcp paketi yok: {e})")

# ---------------------------------------------------------------- open_app (kullanıcı dizini girdisi)
UYG = os.path.join(_yalitim.GECICI, "uygulamalar")
os.makedirs(UYG, exist_ok=True)
BETIK = os.path.join(_yalitim.GECICI, "betik.sh")
open(BETIK, "w").write("#!/bin/sh\necho x\n")
os.chmod(BETIK, 0o755)
for kimlik, ex in {"kullanici-betik": BETIK, "python3": "python3", "konsole": "konsole"}.items():
    with open(os.path.join(UYG, kimlik + ".desktop"), "w") as f:
        f.write(f"[Desktop Entry]\nType=Application\nName={kimlik}\nExec={ex}\n")
uygulama.UYGULAMA_DIZINLERI = (UYG,)
assert kapsam("hepsi")
temiz()
kod = kod_al(uygulama.mcp_uygulama, "kullanici-betik")
kontrol("open_app (kullanıcı dizini girdisi): hepsi → onay ister (red → 10)", kod == 10 and len(ISTEKLER) == 1, f"{kod}")
assert kapsam("kart")
temiz()
try:
    g_, _b = uygulama.mcp_uygulama("kullanici-betik")
    kontrol("open_app (kullanıcı dizini girdisi): kart → onaysız; özel kopyadan (YN5) başlar",
            not ISTEKLER and g_["yol"].startswith(os.path.join(yollar.runtime_dir(), "uygulama") + "/") and
            bool(uygulama._ONAYLI.ozetler), str(g_.get("yol")))
except Dur as e:
    kontrol("open_app (kullanıcı dizini girdisi): kart → onaysız", False, str(e))
kontrol("open_app kara listesi kart kipinde de reddeder (python3 → 10, onay sorulmaz)",
        kod_al(uygulama.mcp_uygulama, "python3") == 10 and not ISTEKLER)
kontrol("open_app kara listesi kart kipinde de reddeder (uçbirim → 10)", kod_al(uygulama.mcp_uygulama, "konsole") == 10)

# ================================================================ KALANLAR: para düğmesi / ödeme sayfası / kart bilgisi
with arka_uc.hedef_sabit("kde"):
    for mod in ("hepsi", "kart"):
        assert kapsam(mod)
        for dugme in ("Satın al", "Hemen al", "Öde", "Ödemeyi tamamla", "Siparişi onayla", "Buy now", "Pay", "Place order",
                      "Complete purchase", "Confirm payment"):
            kod, n, _g = sorar(guvenlik.hassas_engel, False, dugme, k=None)
            kontrol(f"[{mod}] para düğmesi {dugme!r} (ödeme sayfası DIŞINDA) → onay ister", kod == 10 and n == 1, f"{kod} {n}")
        kod, n, _g = sorar(guvenlik.hassas_engel, True, "Satın al", k=None)
        if mod == "hepsi":
            kontrol("[hepsi] para düğmesi + --onayli → sorulmaz (bugünkü davranış)", kod == 0 and n == 0, f"{kod} {n}")
        else:
            kontrol("[kart] para düğmesi + --onayli → YOK SAYILIR: panelden sorulur, panel red → 10",
                    kod == 10 and n == 1, f"{kod} {n}")
        # ödeme sayfasında Enter
        kod, n, g = sorar(eylem.k_tus, ns(kimlik="{o}", kombinasyon="enter"))
        kontrol(f"[{mod}] ödeme sayfasında Enter → onay ister, tuş gitmez", kod == 10 and n == 1 and g == 0, f"{kod} {n} {g}")
        kod, n, g = sorar(eylem.k_tus, ns(kimlik="{o}", kombinasyon="enter", onayli=True))
        if mod == "kart":
            kontrol("[kart] ödeme sayfasında Enter + --onayli → yok sayılır (panel red → 10)",
                    kod == 10 and n == 1 and g == 0, f"{kod} {n} {g}")
        else:
            kontrol("[hepsi] ödeme sayfasında Enter + --onayli → sorulmaz", kod == 0 and n == 0 and g == 1, f"{kod} {n} {g}")
        # ödeme sayfasında tıklama
        for yakin, ad in ((["Ödemeyi tamamla"], "para düğmesi"), ([], "okunamayan hedef")):
            kod, n, _g = sorar(guvenlik.hassas_sayfa_engel, "{o}", False, "tıklama", yakin=yakin, nokta=(5, 5),
                               goruntu_al=False)
            kontrol(f"[{mod}] ödeme sayfasında tıklama ({ad}) → onay ister", kod == 10 and n == 1, f"{kod} {n}")
        kod, n, _g = sorar(guvenlik.hassas_sayfa_engel, "{o}", False, "tıklama", yakin=["Kuponu uygula"], nokta=(5, 5),
                           goruntu_al=False)
        if mod == "kart":
            kontrol("[kart] ödeme sayfasında para OLMAYAN okunur öge ('Kuponu uygula') → sorulmaz", kod == 0 and n == 0)
        else:
            kontrol("[hepsi] ödeme sayfasında 'Kuponu uygula' → sorar (eski davranış)", kod == 10 and n == 1)
        # gözetimsiz: ret (gerçek onay modülü; panel yok)
        onay.iste_sonuc = gercek_iste_sonuc
        os.environ["DESKHAND_GOZETIMSIZ"] = "1"
        temiz()
        try:
            guvenlik.hassas_engel(True, "Öde", k=None)
            m = ""
        except Dur as e:
            m = f"{e.kod} {e.mesaj}"
        kontrol(f"[{mod}] gözetimsiz kipte para düğmesi (+ --onayli) → 10", m.startswith("10"), m[:160])
        os.environ.pop("DESKHAND_GOZETIMSIZ")
        onay.iste_sonuc = sahte_iste_sonuc

    # ---- kart bilgisi yazma
    TAM = ("4111111111111111", "4111 1111 1111 1111")
    GECERLI = ["4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111", "kartim 5500 0000 0000 0004 tamam",
               "3782 822463 10005", "6011111111111117"]
    GECERSIZ = ["4111 1111 1111 1112", "05321234567", "1234567890", "12345", "4111 1111 1111", "tarih 2026-11-22 x"]
    for m_ in GECERLI:
        kontrol(f"Luhn: {m_!r} → kart numarası (son 4 hane döner)", guvenlik.kart_numarasi(m_) == "".join(
            c for c in m_ if c.isdigit())[-4:], str(guvenlik.kart_numarasi(m_)))
    for m_ in GECERSIZ:
        kontrol(f"Luhn: {m_!r} → kart numarası DEĞİL", guvenlik.kart_numarasi(m_) is None)
    for ad_ in ("Kart numarası", "Card number", "cc-number", "CVV", "cvc", "Güvenlik kodu", "Son kullanma tarihi",
                "Expiry date", "cc-exp"):
        kontrol(f"kart alanı adı: {ad_!r}", guvenlik.kart_alani_mi(ad_))
    for ad_ in ("Ad Soyad", "Adres", "Posta kodu", "Arama", ""):
        kontrol(f"kart alanı DEĞİL: {ad_!r}", not guvenlik.kart_alani_mi(ad_))
    kontrol("kart alanı: web niteliği (autocomplete=cc-number)", guvenlik.kart_alani_mi("", None, "cc-number x"))

    assert kapsam("hepsi")
    for m_ in GECERLI[:3]:
        kod, n, g = sorar(eylem.k_yaz, ns(kimlik="{n}", metin=m_))
        kontrol(f"[hepsi] kart numarası yazma {m_!r} → ekstra onay YOK (bugünkü davranış)", kod == 0 and n == 0 and g > 0,
                f"{kod} {n} {g}")
    assert kapsam("kart")
    for m_ in GECERLI:
        kod, n, g = sorar(eylem.k_yaz, ns(kimlik="{n}", metin=m_))
        rakam = "".join(c for c in m_ if c.isdigit())
        son4 = rakam[-4:]
        iletiler = " ".join(i["eylem"] + i["ayrinti"] + i["hedef"] for i in ISTEKLER)
        kontrol(f"[kart] kart numarası yazma {m_!r} → onay ister, girdi gitmez", kod == 10 and n == 1 and g == 0,
                f"{kod} {n} {g}")
        kontrol(f"[kart] onay isteğinde yalnız son 4 hane ({son4}) görünür, tam numara YOK",
                bool(ISTEKLER) and son4 in iletiler and rakam not in iletiler.replace(" ", "").replace("-", "") and
                m_ not in iletiler, iletiler[:200])
    for m_ in GECERSIZ[:3]:
        kod, n, g = sorar(eylem.k_yaz, ns(kimlik="{n}", metin=m_))
        kontrol(f"[kart] kart olmayan sayı {m_!r} → sorulmaz", kod == 0 and n == 0 and g > 0, f"{kod} {n} {g}")
    kod, n, g = sorar(eylem.k_yaz, ns(kimlik="{n}", metin=TAM[0], onayli=True))
    kontrol("[kart] kart numarası + --onayli → YOK SAYILIR (panel red → 10)", kod == 10 and n == 1 and g == 0,
            f"{kod} {n} {g}")
    temiz()
    YANIT["izin"] = True
    kod = kod_al(eylem.k_yaz, ns(kimlik="{n}", metin=TAM[1]))
    kontrol("[kart] panelden izin → numara yazılır (bir onay)", kod == 0 and len(ISTEKLER) == 1 and len(au.satirlar) > 0,
            f"{kod} {len(ISTEKLER)}")
    # CVV alanı (odaktaki alan kart alanı): numara olmasa da
    eski_kart_alani = eylem._kart_alani_mi
    eylem._kart_alani_mi = lambda k: True
    try:
        kod, n, g = sorar(eylem.k_yaz, ns(kimlik="{n}", metin="123"))
        kontrol("[kart] CVV alanına '123' yazma → onay ister", kod == 10 and n == 1 and g == 0, f"{kod} {n} {g}")
        kontrol("[kart] CVV onayında değer yok, yalnız uzunluk",
                "123" not in ISTEKLER[0]["ayrinti"].replace("kart bilgisi alanı, 3", ""), ISTEKLER[0]["ayrinti"])
        kod, n, g = sorar(eylem.k_yaz, ns(kimlik="{n}", metin="123", onayli=True))
        kontrol("[kart] CVV + --onayli → yok sayılır", kod == 10 and n == 1)
        assert kapsam("hepsi")
        kod, n, g = sorar(eylem.k_yaz, ns(kimlik="{n}", metin="123"))
        kontrol("[hepsi] CVV alanına yazma → ekstra onay yok", kod == 0 and n == 0 and g > 0)
        assert kapsam("kart")
    finally:
        eylem._kart_alani_mi = eski_kart_alani
    # günlük: tam numara asla
    icerik = ""
    gd = yollar.gunluk_dizin()
    for ad_ in (os.listdir(gd) if os.path.isdir(gd) else []):
        with open(os.path.join(gd, ad_), errors="replace") as f:
            icerik += f.read()
    kontrol("günlükte tam kart numarası YOK (kart kipi)",
            not any(t in icerik for t in TAM + ("4111-1111-1111-1111", "5500 0000 0000 0004", "6011111111111117")),
            icerik[-300:])
    onay.iste_sonuc = gercek_iste_sonuc
    os.environ["DESKHAND_GOZETIMSIZ"] = "1"
    kod = kod_al(eylem.k_yaz, ns(kimlik="{n}", metin=TAM[0], onayli=True))
    kontrol("[kart] gözetimsiz kipte kart numarası yazma (+ --onayli) → 10", kod == 10, str(kod))
    os.environ.pop("DESKHAND_GOZETIMSIZ")
    onay.iste_sonuc = sahte_iste_sonuc

    # ================================================================ DEĞİŞMEYEN korumalar (kart kipinde de)
    assert kapsam("kart")
    au.pid = lambda k: os.getppid()  # ajanın kendi istemcisi: bu sürecin atası
    kod = kod_al(guvenlik.kendi_istemci_denetle, "{n}")
    kontrol("kart kipinde de: ajanın kendi istemcisi → 10", kod == 10, str(kod))
    del au.pid
    from deskhand import gozlem
    kontrol("kart kipinde de: parola alanı değeri okunmaz (gözlem)",
            "deger" not in gozlem.agac_ogesi(
                {"rol": "password text", "ad": "Parola", "deger": "sir", "x": 0, "y": 0, "w": 1, "h": 1}, set()))
    guvenlik.dur_ac("kullanici")
    kontrol("kart kipinde de: DUR açıkken girdi → 13", kod_al(eylem.k_tus, ns(kimlik="{n}", kombinasyon="a")) == 13)
    guvenlik.dur_kapat("kullanici")

# ---------------------------------------------------------------- doktor + panel
assert kapsam("kart")
satir = doktor.satir_onay_kapsami()
kontrol("doctor: 'Onay kapsamı: kart …' satırı", satir["ad"] == "Onay kapsamı" and satir["ayrinti"].startswith("kart"))
assert kapsam("hepsi")
kontrol("doctor: 'Onay kapsamı: hepsi …' satırı", doktor.satir_onay_kapsami()["ayrinti"].startswith("hepsi"))
try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    qapp = QApplication.instance() or QApplication([])
    from deskhand.gui import pencere as P
    y = P.AyarlarSekmesi()
    kontrol("panel: 'Onay soruları' seçici Hepsi / Yalnız kartla ödeme, başlangıçta Hepsi",
            [y.c_onay.itemData(i) for i in range(y.c_onay.count())] == ["hepsi", "kart"] and
            y.c_onay.itemText(1) == "Yalnız kartla ödeme" and y.c_onay.currentData() == "hepsi")
    y.c_onay.setCurrentIndex(1)
    y.c_onay.activated.emit(1)
    kontrol("panel: seçim ayarlara yazıldı + kip hemen geçerli", ayarlar.al("guvenlik", "onaylar") == "kart" and
            guvenlik.onay_kapsami() == "kart")
    kapsam("hepsi")
except ImportError as e:
    print(f"ATLANDI  panel testi (PyQt6 yok: {e})")

# ================================================================ uçtan uca: sanal masaüstü + mini uçbirim penceresi
onay.iste_sonuc = gercek_iste_sonuc  # panel yok → gerçek onay yolu red verir
arka_uc._ORNEKLER.clear()
LOG = os.path.join(_yalitim.PAYLASIM, "onay_kapsami.log")


def tus_hamlari():
    try:
        with open(LOG) as f:
            return [l for l in f if l.startswith("tus_ham ")]
    except OSError:
        return []


def bekle(kosul, sure=5.0):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        v = kosul()
        if v:
            return v
        time.sleep(0.05)
    return kosul()


p1 = None
try:
    d = masaustu.masaustu_baslat()
    kontrol("e2e: sanal masaüstü açıldı", bool(d))
    os.environ["DESKHAND_HEDEF"] = "arka"
    sa = arka_uc.sec(arka_bayragi=True)
    p1 = sa.baslat([sys.executable, TEST_PENCERE], env={"LOG": LOG, "BASLIK": "deskhand-onay TERM", "HAZIR_MS": "300",
                                                         "SINIF": "xterm", "TUS_LOG": "1"})
    k1 = bekle(lambda: next((w for w, b, _ in sa.pencereler("deskhand-onay TERM")), None), 20)
    kontrol("e2e: mini uçbirim penceresi (sınıf xterm) açıldı", k1 is not None)
    if k1:
        bekle(lambda: sa.aktif() == k1, 3)
        time.sleep(0.5)
        with arka_uc.hedef_sabit("sanal"):
            assert kapsam("hepsi")
            n0 = len(tus_hamlari())
            kod = kod_al(eylem.k_tus, ns(kimlik=k1, kombinasyon="enter"))
            time.sleep(0.4)
            kontrol("e2e [hepsi]: uçbirimde Enter → onay ister (panel kapalı → 10), tuş basılmadı",
                    kod == 10 and len(tus_hamlari()) == n0, str(kod))
            assert kapsam("kart")
            kod = kod_al(eylem.k_tus, ns(kimlik=k1, kombinasyon="enter"))
            kontrol("e2e [kart]: uçbirimde Enter onaysız → gerçekten basıldı", kod == 0 and bekle(
                lambda: len(tus_hamlari()) > n0), f"{kod} {tus_hamlari()[n0:]}")
            n1 = len(tus_hamlari())
            kod = kod_al(eylem.k_yaz, ns(kimlik=k1, metin="ls\n"))
            kontrol("e2e [kart]: 'ls⏎' yazısı (içinde Enter) onaysız yazıldı", kod == 0 and bekle(
                lambda: len(tus_hamlari()) >= n1 + 3), f"{kod} {tus_hamlari()[n1:]}")
            n2 = len(tus_hamlari())
            kod = kod_al(eylem.k_yaz, ns(kimlik=k1, metin="rm -rf /tmp/deskhand-yok"))
            kontrol("e2e [kart]: uçbirime yıkıcı komut yazma onaysız", kod == 0 and bekle(
                lambda: len(tus_hamlari()) > n2 + 10), f"{kod}")
            n3 = len(tus_hamlari())
            kod = kod_al(eylem.k_yaz, ns(kimlik=k1, metin="4111 1111 1111 1111", onayli=True))
            time.sleep(0.4)
            kontrol("e2e [kart]: kart numarası (+ --onayli) → panel kapalı → 10, hiç harf yazılmadı",
                    kod == 10 and len(tus_hamlari()) == n3, f"{kod}")
            assert kapsam("hepsi")
finally:
    os.environ.pop("DESKHAND_HEDEF", None)
    if p1 is not None:
        p1.kill()
        p1.wait()
    if masaustu.durum_oku() is not None:
        masaustu.masaustu_durdur()

print(f"\n{GECEN}/{TOPLAM} onay-kapsamı testi geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
