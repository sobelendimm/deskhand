"""Gerçek ekran kilidi + ödeme sayfası (K4b): görünmez masaüstündeki hassas sayfa kilitlenmez (sahte arka uç, ekransız).

1. DESKHAND_GERCEK_EKRAN=kapali iken onay.iste_sonuc: hedef görünmez masaüstüyse (sanal/kwin = "sanal") panel onayı
   İSTENİR (17 değil); hedef kullanıcının ekranıysa (kde) yine 17. Panel kaydı SAHTE (None): gerçek panele dokunulmaz.
2. Başlığında "Ödeme" geçen görünmez masaüstü sayfasında Enter: onay istenir (red → 10, ileti tetikleyen kalıbı söyler);
   gerçek ekran hedefinde 17 iletisi de onayın gerekçesini (kalıbı) söyler.
3. goto (adres çubuğu): odak erişilebilirlik ağacında belge DIŞINDA doğrulanırsa adres + Enter onaysız gider; odak
   bilinmiyor / sayfa içindeyse ya da yazı goto'nun adresi değilse onay kuralı aynen.
4. Sayfadan çıkış: geri (alt+left) ve pencereyi kapatma ödeme sayfası kapısına takılmaz.

Çalıştır:  python3 tests/test_odeme_kilit.py"""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

import argparse
import contextlib
import io
import os

from PIL import Image

from deskhand import api, arka_uc, dogrulama_sinamasi, erisim, eylem, gezin, guvenlik, hata, onay, web
from deskhand.arka_uc import EKRAN
from deskhand.hata import Dur

GECEN = TOPLAM = 0
eylem.HARF_SN = 0
BASLIK = "Ödeme - Örnek Mağaza — Mozilla Firefox"


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


class SahteGirdi:
    def __init__(self, au, etiket="", gizli=False, etk=None, denetle=None):
        self.au, self.etiket, self.gizli = au, etiket, gizli
        self.kesildi, self.hazir, self.etk, self.son_fare = None, True, None, (5, 5)

    def gonder(self, k, desen, *satirlar):
        hata.dur_denetle()
        self.au.satirlar.extend(satirlar)

    def ham(self, s): self.au.satirlar.append(s)
    def zorla(self, s): self.au.satirlar.append(s)
    def izle(self, k, desen, **kw): pass
    def izle_bitir(self): pass
    def etk_denetle(self, ne=None): pass
    def insan_kontrol(self): pass
    def kapat(self): pass


class SahteAU(arka_uc.ArkaUc):
    def __init__(self, ad="sanal"):
        self.ad = ad
        self.satirlar, self.kapanan = [], []

    def pencere_coz(self, arg): return arg
    def pencereler(self, desen=None): return []
    def geometri(self, k): return (0, 0, 1280, 800)
    def baslik(self, k): return BASLIK
    def sinif(self, k): return "firefox"
    def aktif(self): return "{w}"
    def one_getir(self, k): pass
    def kapat(self, k): self.kapanan.append(k)
    def fare(self): return 150, 150, "{w}"
    def ekran_alani(self): return (0, 0, 1280, 800)
    def goruntu(self): return Image.new("RGB", (1280, 800), (200, 200, 200))
    def insan_var_mi(self): return False
    def baslat(self, argv, env=None, cikti=None): raise AssertionError("başlatılmamalı")
    def yazilabilir_mi(self, c): return c.isprintable()
    def gecerli_tuslar(self): return None
    def girdi(self, etiket="", gizli=False, etk=None, denetle=None): return SahteGirdi(self, etiket, gizli, etk, denetle)


def ns(**k):
    a = argparse.Namespace(baslik=None, onayli=False, gizli=False, kimlik="{w}")
    for x, v in k.items():
        setattr(a, x, v)
    return a


def calistir(au, f, *a, **kw):
    """→ (kod, ileti)"""
    arka_uc._ORNEKLER[au.ad] = au
    with arka_uc.hedef_sabit(au.ad), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            f(*a, **kw)
        except Dur as e:
            return e.kod, e.mesaj
    return 0, ""


kontrol("ön koşul: gerçek ekran kilidi KAPALI (testler)", hata.gercek_ekran_kipi() == "kapali")

ASIL_ISTE, ASIL_PANEL = onay.iste_sonuc, onay._panel_kaydi
ISTEKLER = []
onay._panel_kaydi = lambda *a, **k: None  # gerçek panel kaydı HİÇ okunmaz (panel-yok)


@contextlib.contextmanager
def gercek_calisma_dizini():
    """iste_sonuc'un 'kullanıcının gerçek paneli' dalı (DESKHAND_RUNTIME_DIR yok); panel kaydı sahte (None)."""
    rt = os.environ.pop("DESKHAND_RUNTIME_DIR")
    try:
        yield
    finally:
        os.environ["DESKHAND_RUNTIME_DIR"] = rt


# ================================================================ 1. iste_sonuc: kilit yalnız kullanıcının ekranına
with gercek_calisma_dizini():
    for md in ("sanal", "arka", "background"):
        try:
            s = ASIL_ISTE("tıkla", "deneme", masaustu=md)
            kontrol(f"kilit + hedef görünmez masaüstü ({md}) → onay İSTENİR (17 değil; sahte panel yok → panel-yok)",
                    s.izin is False and s.neden == "panel-yok", str(s))
        except Dur as e:
            kontrol(f"kilit + hedef görünmez masaüstü ({md}) → onay İSTENİR (17 değil)", False, f"{e.kod} {e.mesaj}")
    for md in ("kde", "ekran"):
        try:
            ASIL_ISTE("tıkla", "deneme", masaustu=md)
            kontrol(f"kilit + hedef kullanıcının ekranı ({md}) → 17", False)
        except Dur as e:
            kontrol(f"kilit + hedef kullanıcının ekranı ({md}) → 17", e.kod == 17, f"{e.kod} {e.mesaj}")

# ================================================================ 2. ödeme sayfasında Enter
dogrulama_sinamasi_klavye = dogrulama_sinamasi.klavye_engeli
dogrulama_sinamasi.klavye_engeli = lambda *a, **k: None  # CAPTCHA kapısı bu testin konusu değil
try:
    with gercek_calisma_dizini():
        au = SahteAU("sanal")
        kod, mesaj = calistir(au, eylem.k_tus, ns(kombinasyon="Return"))
        kontrol("kilit + görünmez masaüstü ödeme sayfası: Enter → onay istendi, red → 10 (17 DEĞİL), girdi yok",
                kod == 10 and not au.satirlar, f"{kod} {mesaj}")
        kontrol("ret iletisi tetikleyen kalıbı ve başlığı söyler ('odeme' ← başlık)",
                "odeme" in mesaj and "Ödeme" in mesaj, mesaj)
        au = SahteAU("kde")
        kod, mesaj = calistir(au, eylem.k_tus, ns(kombinasyon="Return"))
        kontrol("kilit + KULLANICININ ekranı (kde): 17, girdi yok", kod == 17 and not au.satirlar, f"{kod} {mesaj}")
        kontrol("17 iletisi onayın gerekçesini (ödeme kalıbı) söyler", "odeme" in mesaj and "gerekçesi" in mesaj, mesaj)

    def sahte_iste(eylem_, hedef, ayrinti="", masaustu="ekran", sure=120, goruntu=None, gunluge_yaz=True, **kw):
        ISTEKLER.append((eylem_, hedef, ayrinti))
        return onay.OnaySonucu(False, "red")
    onay.iste_sonuc = sahte_iste

    # ============================================================ 3. goto: adres çubuğu
    web_tm, api_arka, odak_eski = web.tarayici_mi, api.arka, erisim.odak_bilgisi
    web.tarayici_mi = lambda k: True
    au = SahteAU("sanal")
    api.arka = lambda: au
    try:
        erisim.odak_bilgisi = lambda k: {"rol": "entry", "belge_ici": False, "duzenlenebilir": True}
        ISTEKLER.clear()
        kod, mesaj = calistir(au, gezin.adrese_git, "{w}", "https://example.org/sepet#ozet")
        kontrol("goto: odak adres çubuğunda (doğrulandı) → ödeme sayfasından onaysız çıkış",
                kod == 0 and not ISTEKLER and "key ctrl+l" in au.satirlar and "key enter" in au.satirlar,
                f"{kod} {mesaj} {ISTEKLER} {au.satirlar}")
        for ad_, odak_ in (("bilinmiyor", None), ("sayfa içindeki alan", {"rol": "entry", "belge_ici": True,
                                                                           "duzenlenebilir": True})):
            erisim.odak_bilgisi = lambda k, o=odak_: o
            ISTEKLER.clear()
            au.satirlar.clear()
            kod, mesaj = calistir(au, gezin.adrese_git, "{w}", "https://example.org/")
            kontrol(f"goto: odak {ad_} → onay istendi, red → 10, Enter gitmedi",
                    kod == 10 and len(ISTEKLER) == 1 and "key enter" not in au.satirlar, f"{kod} {ISTEKLER}")
        erisim.odak_bilgisi = lambda k: {"rol": "entry", "belge_ici": False, "duzenlenebilir": True}
        ISTEKLER.clear()
        au.satirlar.clear()
        kod, mesaj = calistir(au, eylem.k_yaz, ns(metin="https://example.org/\n"))
        kontrol("goto bağlamı DIŞINDA aynı yazı (adres + Enter) → onay kuralı aynen", kod == 10 and len(ISTEKLER) == 1)
        with guvenlik.sayfadan_cikis("{w}", "https://example.org/\n"):
            ISTEKLER.clear()
            kod, mesaj = calistir(au, eylem.k_yaz, ns(metin="siparis onay\n"))
        kontrol("goto bağlamında BAŞKA yazı → onay kuralı aynen", kod == 10 and len(ISTEKLER) == 1)
        with guvenlik.sayfadan_cikis("{w}", "https://example.org/\n"):
            ISTEKLER.clear()
            kod, mesaj = calistir(au, eylem.k_yaz, ns(metin="https://example.org/\n", kimlik="{baska}"))
        kontrol("goto bağlamı başka pencere için → onay kuralı aynen", kod == 10 and len(ISTEKLER) == 1)
        kontrol("bağlam çıkınca temizlenir", getattr(guvenlik._CIKIS, "deger", None) is None)

        # ======================================================== 4. geri / kapat
        ISTEKLER.clear()
        au.satirlar.clear()
        kod, mesaj = calistir(au, eylem.k_tus, ns(kombinasyon="alt+Left"))
        kontrol("ödeme sayfasında geri (alt+left) → onaysız", kod == 0 and not ISTEKLER and au.satirlar, f"{kod} {mesaj}")
        kod, mesaj = calistir(au, eylem.k_kapat, ns())
        kontrol("ödeme sayfasında pencereyi kapat → ödeme kapısı sormaz", not ISTEKLER and (kod == 0 or "odeme" not in mesaj),
                f"{kod} {mesaj} {ISTEKLER}")
    finally:
        web.tarayici_mi, api.arka, erisim.odak_bilgisi = web_tm, api_arka, odak_eski
finally:
    dogrulama_sinamasi.klavye_engeli = dogrulama_sinamasi_klavye
    onay.iste_sonuc, onay._panel_kaydi = ASIL_ISTE, ASIL_PANEL

print(f"\n{GECEN}/{TOPLAM} ödeme/kilit testi geçti")
raise SystemExit(0 if GECEN == TOPLAM else 1)
