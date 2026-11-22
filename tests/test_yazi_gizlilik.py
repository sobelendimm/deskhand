"""Yazı girdisi: denetim karakterleri + gizli (--secret) yazı sızıntıları (sahte arka uç, ekransız).

1. Denetim karakterleri (\\x08, \\x1b, \\x7f, \\x0f, \\x85 …): k_yaz / yaz_ic / yapıştırma yolu / harf harf yol / dizi
   adımı → HİÇBİR ŞEY gönderilmeden Dur(1); \\n ve \\t serbest; arka uçların yazilabilir_mi'si (kde, kwin, sanal) False.
2. Gizli yazı: karakter DEĞİŞTİRİLMEZ (Café → Cafe yok), ileti karakter değil konum/uzunluk verir.
3. Dizi/akış: gizli adım satırı stdout'a, günlüğe ve Dur iletisine yazılmaz.
4. dotool uyarıları (impossible character…): merkez günlüğüne ve gizli gönderimin iletisine karakter taşınmaz.
5. Gizli yapıştırma: eski pano geri yüklenemezse (çok büyük) pano temizlenir.

Çalıştır:  python3 tests/test_yazi_gizlilik.py"""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

import argparse
import contextlib
import io
import os

from PIL import Image

from deskhand import arka_uc, eylem, girdi_merkezi, hata, onay, yollar
from deskhand.arka_uc import EKRAN, kde, kwin, sanal
from deskhand.hata import Dur

GECEN = TOPLAM = 0
eylem.HARF_SN = 0
YAZILAMAZ = {"😀", "é", "—"}


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


def gunluk_metni():
    d = yollar.gunluk_dizin()
    try:
        return "".join(open(os.path.join(d, f)).read() for f in os.listdir(d) if f.startswith("gunluk-"))
    except OSError:
        return ""


class SahteGirdi:
    def __init__(self, au, etiket="", gizli=False, etk=None, denetle=None):
        self.au, self.etiket, self.gizli = au, etiket, gizli
        self.kesildi, self.hazir, self.etk, self.son_fare = None, True, None, (5, 5)

    def gonder(self, k, desen, *satirlar):
        hata.dur_denetle()
        for s in satirlar:
            self.au.satirlar.append(s)
            if s in ("key ctrl+v", "key ctrl+shift+v"):
                self.au.hedef += self.au.pano or ""

    def ham(self, s):
        self.au.satirlar.append(s)
        if s.startswith("type "):
            self.au.hedef += s[5:]

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
        self.pano, self.hedef, self.satirlar, self.olaylar = "eski pano", "", [], []

    def pencere_coz(self, arg): return arg
    def pencereler(self, desen=None): return []
    def geometri(self, k): return (100, 100, 800, 600) if k != EKRAN else (0, 0, 1920, 1080)
    def baslik(self, k): return "Belge — KWrite"
    def sinif(self, k): return "kwrite"
    def aktif(self): return "{w}"
    def one_getir(self, k): pass
    def kapat(self, k): pass
    def fare(self): return 150, 150, "{w}"
    def ekran_alani(self): return (0, 0, 1920, 1080)
    def goruntu(self): return Image.new("RGB", (1920, 1080), (200, 200, 200))
    def insan_var_mi(self): return False
    def baslat(self, argv, env=None, cikti=None): raise AssertionError("başlatılmamalı")
    def yazilabilir_mi(self, c): return c not in YAZILAMAZ and c.isprintable()
    def gecerli_tuslar(self): return None
    def girdi(self, etiket="", gizli=False, etk=None, denetle=None): return SahteGirdi(self, etiket, gizli, etk, denetle)
    def pano_oku(self): return self.pano

    def pano_yaz(self, metin, hassas=True):
        self.olaylar.append(("pano_yaz", metin))
        self.pano = metin or None

    def pano_yedekle(self): return {"metin": self.pano}

    def pano_geri_yukle(self, yedek):
        self.olaylar.append(("geri", yedek))
        if yedek.get("bos"):
            self.pano = None
            return None
        if yedek.get("buyuk"):
            return "eski pano içeriği çok büyük olduğu için geri yüklenemedi"
        self.pano = yedek["metin"]
        return None


class PanoYok(SahteAU):
    pano_yaz = arka_uc.ArkaUc.pano_yaz


class BuyukPano(SahteAU):
    def pano_yedekle(self): return {"buyuk": True, "tur": "image/png"}


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
    with arka_uc.hedef_sabit("kde"), contextlib.redirect_stdout(cikti), contextlib.redirect_stderr(cikti):
        try:
            f(*a)
        except Dur as e:
            kod, mesaj = e.kod, e.mesaj
    return kod, mesaj, cikti.getvalue()


onay.iste_sonuc = lambda *a, **k: onay.OnaySonucu(False, "red")

# ================================================================ 1. denetim karakterleri
for c in ("\x08", "\x1b", "\x7f", "\x0f", "\x00", "\x85", "\x9b"):
    for sinif_, ad_ in ((SahteAU, "pano"), (PanoYok, "harf harf")):
        for metin in (f"ab{c}cd", "x" * 300 + c, f"selam 😀{c}"):
            au = sinif_()
            kod, mesaj, _o = calistir(au, eylem.k_yaz, ns(metin=metin))
            kontrol(f"denetim karakteri U+{ord(c):04X} ({ad_}, {len(metin)} kr) → Dur 1, nothing_sent",
                    kod == 1 and not au.satirlar and au.pano == "eski pano" and not au.olaylar and "denetim" in mesaj,
                    f"{kod} {mesaj!r} {au.satirlar[:3]} {au.olaylar[:2]}")
    au = SahteAU()
    g = SahteGirdi(au)
    kod, mesaj, _o = calistir(au, eylem.yaz_ic, g, "{w}", None, f"a{c}b")
    kontrol(f"yaz_ic doğrudan (MCP/akış yolu) U+{ord(c):04X} → Dur 1, gönderim yok", kod == 1 and not au.satirlar)
    kontrol(f"yazima_hazirla U+{ord(c):04X} → Dur 1", calistir(au, eylem.yazima_hazirla, f"a{c}")[0] == 1)
    kontrol(f"kde.yazilabilir_mi(U+{ord(c):04X}) False (xkbcli çağrılmadan)", kde.yazilabilir_mi(c) is False)
    kontrol(f"kwin.yazilabilir_mi(U+{ord(c):04X}) False (EIS'e sorulmadan)",
            kwin.KwinArkaUc.yazilabilir_mi(None, c) is False)
    kontrol(f"sanal.yazilabilir_mi(U+{ord(c):04X}) False", sanal.SanalArkaUc.yazilabilir_mi(None, c) is False
            if hasattr(sanal, "SanalArkaUc") else True)
au = PanoYok()
kod, mesaj, _o = calistir(au, eylem.k_yaz, ns(metin="satır1\n\tsatır2\r\nson"))
kontrol("\\n, \\t, \\r\\n serbest (denetim karakteri sayılmaz)", kod == 0 and au.hedef.startswith("satır1"), f"{kod} {mesaj}")
au = SahteAU()
a_ = argparse.Namespace(kimlik="{w}", kimlik_ham="{w}", baslik=None, onayli_izin=True)
kod, mesaj, _o = calistir(au, eylem.adimlari_calistir, a_, ["yaz 'ab\x1bcd'"])
kontrol("dizi adımı yaz 'ab<ESC>cd' → Dur 1, gönderim yok", kod == 1 and not au.satirlar, f"{kod} {au.satirlar}")

# ================================================================ 2. gizli yazıda karakter değiştirme yok
au = PanoYok()
kod, mesaj, cikti = calistir(au, eylem.k_yaz, ns(metin="Café—Gizli7", gizli=True))
kontrol("gizli + düzende olmayan karakter (pano yok) → Dur 1, HİÇBİR şey yazılmadı (Cafe yazılmadı)",
        kod == 1 and not au.satirlar and au.hedef == "", f"{kod} {au.satirlar}")
kontrol("gizli: ileti karakteri/metni taşımaz, konum + uzunluk verir",
        "é" not in mesaj and "Caf" not in mesaj and "Gizli7" not in mesaj and "4." in mesaj and "11" in mesaj, mesaj)
kontrol("gizli: stdout/stderr'de karakter yok", "é" not in cikti and "Caf" not in cikti, cikti)
au = PanoYok()
kod, mesaj, cikti = calistir(au, eylem.k_yaz, ns(metin="Café"))
kontrol("gizli DEĞİL: eski davranış (é → e yedeği, uyarı)", kod == 0 and au.hedef == "Cafe", f"{kod} {au.hedef!r}")

# ================================================================ 3. dizi/akış: gizli adım görünmez
au = SahteAU()
a_ = argparse.Namespace(kimlik="{w}", kimlik_ham="{w}", baslik=None, onayli_izin=True)
g0 = gunluk_metni()
kod, mesaj, cikti = calistir(au, eylem.adimlari_calistir, a_, ["yaz 'Parola-Sir9' --secret"])
kontrol("dizi: gizli adım çalıştı", kod == 0 and au.hedef == "Parola-Sir9", f"{kod} {mesaj}")
kontrol("dizi: gizli adım satırı stdout'ta YOK (yalnız komut adı + ***)",
        "Parola-Sir9" not in cikti and "***" in cikti, cikti)
kontrol("dizi: gizli adım günlükte YOK", "Parola-Sir9" not in gunluk_metni()[len(g0):])
kontrol("gizli yazı: günlükte parça uzunlukları YOK (yalnız toplam, etikette)",
        "***(" not in gunluk_metni()[len(g0):], gunluk_metni()[len(g0):][-300:])
kod, mesaj, cikti = calistir(SahteAU(), eylem.adimlari_calistir, a_, ["yaz 'Parola-Sir9' --gizli --bilinmeyen"])
kontrol("dizi: hatalı gizli satır → Dur 1, iletide gizli metin YOK", kod == 1 and "Parola-Sir9" not in mesaj
        and "Parola-Sir9" not in cikti, mesaj)
kod, mesaj, cikti = calistir(SahteAU(), eylem.adimlari_calistir, a_, ["yaz 'acik metin' --bilinmeyen"])
kontrol("dizi: gizli OLMAYAN hatalı satır iletisi aynen (tanılama kaybolmaz)", kod == 1 and "acik metin" in mesaj, mesaj)
kontrol("adim_metni: --secret / --gizli / tırnaklı; 'secret' sözcüğü gizli sayılmaz",
        eylem.gizli_adim_mi("type 'x' --secret") and eylem.gizli_adim_mi("yaz x --gizli")
        and not eylem.gizli_adim_mi("yaz 'my secret'") and not eylem.gizli_adim_mi("yaz --secretive"))

# ================================================================ 4. dotool uyarıları
m = girdi_merkezi.uyari_maskele("impossible character for layout: é")
kontrol("merkez: 'impossible character' uyarısında karakter maskelenir", "é" not in m and m.endswith("***"), m)
kontrol("merkez: karakter içermeyen uyarı aynen", girdi_merkezi.uyari_maskele("impossible key for layout: shift")
        == "impossible key for layout: shift")
gk = kde.Girdi.__new__(kde.Girdi)
gk.gizli = True
kontrol("kde.Girdi gizli: istemciye dönen uyarıda karakter yok",
        gk._uyari_suz(["impossible character for layout: ş"]) == ["impossible character for layout: ***"])
gk.gizli = False
kontrol("kde.Girdi gizli değil: uyarı aynen (tanılama)",
        gk._uyari_suz(["impossible character for layout: ş"]) == ["impossible character for layout: ş"])

# ================================================================ 5. gizli yapıştırma + büyük pano
au = BuyukPano()
gizli_metin = "S" * 250 + "-çok-gizli"
kod, mesaj, cikti = calistir(au, eylem.k_yaz, ns(metin=gizli_metin, gizli=True))
kontrol("gizli + büyük (geri yüklenemeyen) pano → yazıldı ve SONRA pano boş", kod == 0 and au.hedef == gizli_metin
        and au.pano is None, f"{kod} {mesaj} pano={str(au.pano)[:20]!r}")
kontrol("gizli + büyük pano: uyarı panonun temizlendiğini söyler, metni taşımaz",
        "çok-gizli" not in cikti and "pano" in cikti, cikti)
au = BuyukPano()
kod, mesaj, cikti = calistir(au, eylem.k_yaz, ns(metin="A" * 250))
kontrol("gizli DEĞİL + büyük pano: davranış aynı (pano temizlenmez)", kod == 0 and au.pano == "A" * 250)
au = SahteAU()
kod, mesaj, cikti = calistir(au, eylem.k_yaz, ns(metin="B" * 250, gizli=True))
kontrol("gizli + normal pano: eski pano geri yüklendi (temizlenmedi)", kod == 0 and au.pano == "eski pano")

print(f"\n{GECEN}/{TOPLAM} yazı gizlilik testi geçti")
raise SystemExit(0 if GECEN == TOPLAM else 1)
