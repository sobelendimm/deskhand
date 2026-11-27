"""open_app aynı süreçte 2. pencere + adres: SON-KAPI düşük bulguları (L1-L3) birim testi (ekransız, sahte KWin arka ucu).

L1 adres doğrulaması: AT-SPI belge adresi okunduysa YALNIZ ona bakılır (başlık "bank.com" dese de başka sunucu =
   doğrulanmadı + gözlenen adres bildirilir); başlık yalnız adres hiç okunamadığında yedek, sunucu SINIRIYLA eşleşir
   (a.com ⊄ Visa.com) ve sonuçta "başlıktan" diye belirtilir.
L2 geçersiz port (host:abc, :99999): ayrıştırma/doğrulama HİÇBİR girdiden (Ctrl+N dahil) önce; Dur 10, kopya silinir.
L3 süre bütçesi: ayni_surecte_ac uzun sürdü diye doğrulanmış pencere için timeout / Dur 7 dönmez (api + CLI).

Çalıştır:  python3 tests/test_open_adres.py"""
import argparse
import os
import sys
import threading
import time

import _yalitim

from deskhand import api, erisim, masaustu, uygulama, web
from deskhand.hata import Dur
from deskhand.oturum import kopya

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


class SahteAu:
    """Sahte KWin arka ucu: pencere → [başlık, sınıf, pid]; pid os.getpid() = kayıtlı tarayıcının soyu."""
    ad = "sahte"

    def __init__(self, pen):
        self.pen = dict(pen)
        self.etkin = next(iter(self.pen), "")
        self.gec = {}  # w → başlık/sınıf daha kaç okumada boş
        self.kapatilan = []
        self.kilit = threading.Lock()

    def pencereler(self):
        with self.kilit:
            return [(w, v[0], (0, 0, 1, 1)) for w, v in sorted(self.pen.items())]

    def pid(self, w):
        return self.pen[w][2] if w in self.pen else None

    def baslik(self, w):
        if self.gec.get(w, 0) > 0:
            self.gec[w] -= 1
            return ""
        return self.pen[w][0] if w in self.pen else ""

    def sinif(self, w):
        return "" if self.gec.get(w, 0) > 0 else (self.pen[w][1] if w in self.pen else "")

    def aktif(self):
        return self.etkin

    def kapat(self, w):
        self.kapatilan.append(w)
        self.pen.pop(w, None)


FF = ["Mozilla Firefox", "firefox", os.getpid()]
GIRDI = []
CALISMA = os.path.join(_yalitim.GECICI, "calisma")
os.makedirs(CALISMA, exist_ok=True)
KAYITLI = kopya.yeni_kopya_dizini("firefox")
ESKI = (masaustu.durum, uygulama._kayitli_tarayicilar, api.tus, api.yaz, erisim.odak_bilgisi, web.sayfa_bilgisi,
        uygulama.YENI_PENCERE_BEKLE_SN, uygulama.ADRES_DOGRULA_SN, api.arka, uygulama.tum_pencereler, api.yasak_mi,
        uygulama._baslat, uygulama.sec)


def kur(au_, yeni_baslik="Yeni Sekme — Mozilla Firefox"):
    """KWin, kayıtlı tek Firefox; Ctrl+N {b}'yi (başlığı yeni_baslik) açar ve etkin yapar; girdiler GIRDI'ye."""
    GIRDI.clear()
    masaustu.durum = lambda *a, **k: {"tur": "kwin", "calisma": CALISMA, "cgroup": ""}
    uygulama._kayitli_tarayicilar = lambda d_, tur_, h_: [(os.getpid(), KAYITLI)]

    def _tus(w, t, **k):
        GIRDI.append(("tus", w, t))
        if t == "ctrl+n":
            with au_.kilit:
                au_.pen["{b}"] = [yeni_baslik, "firefox", os.getpid()]
                au_.etkin = "{b}"
    api.tus = _tus
    api.yaz = lambda w, m, **k: GIRDI.append(("yaz", w, m))
    erisim.odak_bilgisi = lambda k: {"rol": "entry", "belge_ici": False, "duzenlenebilir": True}


def dene(f):
    try:
        return f(), None
    except Dur as x:
        return None, x


def ac(au_, adres, kp=None):
    kp = kp or kopya.yeni_kopya_dizini("firefox")
    return dene(lambda: uygulama.ayni_surecte_ac(au_, ["firefox", "--profile", "/x", "--no-remote", adres], kp))


def okunamaz(k):
    raise RuntimeError("erişilebilirlik okunamadı")


try:
    uygulama.YENI_PENCERE_BEKLE_SN = 2.0
    uygulama.ADRES_DOGRULA_SN = 1.0

    # ---- L1: AT-SPI adresi başlığı ezer
    au = SahteAu({"{a}": FF})
    kur(au, "bank.com - giris — Mozilla Firefox")  # açık yönlendirme: sayfa başlığı hedef adı taşıyor
    web.sayfa_bilgisi = lambda k: {"adres": "https://evil.example/giris", "baslik": "bank.com - giris"}
    s, e = ac(au, "https://bank.com/")
    kontrol("L1a: AT-SPI başka sunucu diyor, başlıkta hedef ad var → doğrulandı SAYILMAZ, gözlenen adres bildirilir",
            e is None and s is not None and s.adres_dogrulandi is False and s.sayfa_adresi == "https://evil.example/giris"
            and "evil.example" in uygulama.ikinci_pencere_iletisi(s), f"{s} {e and e.mesaj}")

    au = SahteAu({"{a}": FF})
    kur(au, "Visa.com — Mozilla Firefox")
    web.sayfa_bilgisi = okunamaz
    s, e = ac(au, "https://a.com/")
    kontrol("L1b: AT-SPI okunamadı, başlıkta sunucu yalnız ALT DİZGE (a.com ⊂ Visa.com) → doğrulanmadı",
            e is None and s is not None and s.adres_dogrulandi is False, f"{s} {e and e.mesaj}")

    au = SahteAu({"{a}": FF})
    kur(au, "a.com - Ana Sayfa — Mozilla Firefox")
    s, e = ac(au, "https://a.com/")
    kontrol("L1c: AT-SPI hiç okunamadı, başlıkta sunucu sınırlı → doğrulandı, kaynak 'baslik' (yedek açıkça belirtilir)",
            e is None and s is not None and s.adres_dogrulandi is True and s.adres_kaynagi == "baslik",
            f"{s} {e and e.mesaj}")

    au = SahteAu({"{a}": FF})
    kur(au, "Sayfa — Mozilla Firefox")
    web.sayfa_bilgisi = lambda k: {"adres": "https://www.bank.com/giris", "baslik": "Giriş"}
    s, e = ac(au, "https://bank.com/")
    kontrol("L1d (kontrol): AT-SPI aynı sunucu → doğrulandı, kaynak 'belge'",
            e is None and s is not None and s.adres_dogrulandi is True and s.adres_kaynagi == "belge",
            f"{s} {e and e.mesaj}")

    # ---- L2: geçersiz port → hiçbir girdi yok, Dur 10, kopya silinir
    for kotu in ("example.com:abc", "http://h:99999"):
        au = SahteAu({"{a}": FF})
        kur(au)
        kp = kopya.yeni_kopya_dizini("firefox")
        s, e = ac(au, kotu, kp)
        kontrol(f"L2: geçersiz port {kotu!r} → Dur 10 (adres reddedildi), HİÇBİR girdi (Ctrl+N dahil), kopya silindi",
                e is not None and e.kod == 10 and "adres reddedildi" in e.mesaj and GIRDI == [] and
                not os.path.exists(kp) and "{b}" not in au.pen, f"{s} {e and (e.kod, e.mesaj)} {GIRDI}")
    kontrol("L2: _adres_norm geçersiz portta istisna atmaz (sayfa adresi okuması da çökmesin)",
            dene(lambda: uygulama._adres_norm("http://h:99999"))[1] is None)
    kontrol("L2: CLI --url geçersiz portu baştan reddeder (Dur 10)",
            (dene(lambda: uygulama.web_adresi_denetle("http://h:99999"))[1] or Dur(0, "")).kod == 10)
    au = SahteAu({"{a}": FF})
    kur(au)
    web.sayfa_bilgisi = lambda k: {"adres": "https://example.com:8080/", "baslik": "X"}
    s, e = ac(au, "example.com:8080")
    kontrol("L2 (kontrol): geçerli port example.com:8080 → normal akış, doğrulandı",
            e is None and s is not None and s.adres_dogrulandi is True, f"{s} {e and e.mesaj}")

    # ---- L3: süre bütçesi doğrulanan pencereden başlar
    def yavas_baslat(au_, *a, **k):
        time.sleep(1.3)  # ayni_surecte_ac (kilit + Ctrl+N + odak + adres doğrulama) bütçeden uzun sürdü
        au_.gec["{b}"] = 2  # doğrulanan pencerenin başlığı ilk okumalarda henüz boş
        return uygulama.IkinciPencere(kimlik="{b}", tur="firefox")
    au = SahteAu({"{a}": FF, "{b}": ["Hedef — Mozilla Firefox", "firefox", os.getpid()]})
    uygulama._baslat = yavas_baslat
    api.arka = lambda: au
    uygulama.tum_pencereler = lambda: set(au.pen)
    api.yasak_mi = lambda w: None
    r, e = dene(lambda: api.uygulama_ac(["firefox", "--no-remote"], "Firefox", [], None, "Hedef", 1.0))
    kontrol("L3 api: doğrulanmış 2. pencere, başlık süzgeci geç eşleşiyor → timeout değil opened",
            e is None and r.get("status") == "opened" and (r.get("window") or {}).get("id") == "{b}",
            f"{r} {e and e.mesaj}")

    def baslikla_baslat(au_, *a, **k):
        return uygulama.IkinciPencere(kimlik="{b}", tur="firefox", adres="https://a.com/", adres_dogrulandi=True,
                                      adres_kaynagi="baslik")
    uygulama._baslat = baslikla_baslat
    r, e = dene(lambda: api.uygulama_ac(["firefox", "--no-remote"], "Firefox", [], None, None, 1.0))
    kontrol("L1c api: başlıktan doğrulama sonuçta açıkça belirtilir (address_source=title + ileti)",
            e is None and r.get("status") == "opened" and r.get("address_source") == "title" and
            "başlığından" in (r.get("message") or ""), f"{r} {e and e.mesaj}")
    # ---- R1 (otomatik tarama): yasak pencerede gözlenen adres iletiye girmez; diğer durumda şema + ana makine
    def dogrulanmamis_baslat(au_, *a, **k):
        return uygulama.IkinciPencere(kimlik="{b}", tur="firefox", adres="https://example.org/x?k=gizli",
                                      adres_dogrulandi=False, sayfa_adresi="https://u:p@example.org/yol?token=abc#x")
    uygulama._baslat = dogrulanmamis_baslat
    api.yasak_mi = lambda w: "yasak" if w == "{b}" else None
    r, e = dene(lambda: api.uygulama_ac(["firefox", "--no-remote"], "Firefox", [], None, None, 1.0))
    m = (r or {}).get("message") or ""
    kontrol("R1 api: yasak pencerede address_unverified iletisinde adres YOK (genel ileti)",
            e is None and r.get("status") == "address_unverified" and m and "example.org" not in m and
            "token" not in m and "gizli" not in m and "example.org" not in str(r), f"{r} {e and e.mesaj}")
    api.yasak_mi = lambda w: None
    r, e = dene(lambda: api.uygulama_ac(["firefox", "--no-remote"], "Firefox", [], None, None, 1.0))
    m = (r or {}).get("message") or ""
    kontrol("R1 api: gözlenen https://u:p@example.org/yol?token=abc#x → iletide yalnız https://example.org",
            e is None and r.get("status") == "address_unverified" and "https://example.org" in m and
            not any(x in m for x in ("token", "abc", "u:p", "/yol", "#x", "gizli", "?")), f"{r} {e and e.mesaj}")
    kontrol("R1: adres_kisa şema + ana makine (userinfo/yol/sorgu/parça yok)",
            uygulama.adres_kisa("https://u:p@Example.org:8443/yol?token=abc#x") == "https://example.org"
            and uygulama.adres_kisa("about:newtab") == "about:newtab"
            and uygulama.adres_kisa("file:///home/u/gizli.txt") == "file:", uygulama.adres_kisa("file:///x"))
    uygulama._baslat = yavas_baslat
    au.gec.clear()

    # ---- R1: başlık yedeği sınırlı ana makine eşleşmesi + yalnız tek pencerede
    web.sayfa_bilgisi = okunamaz
    tek = lambda: True  # noqa: E731
    for sahte in ("evil-example.com.saldirgan — Mozilla Firefox", "example.com.evil — Mozilla Firefox"):
        au2 = SahteAu({"{c}": [sahte, "firefox", os.getpid()]})
        sn = uygulama._adres_dogrula(au2, "{c}", "example.com", tek)
        kontrol(f"R1: başlık {sahte!r} example.com'u DOĞRULAMAZ", sn[0] is False, str(sn))
    au2 = SahteAu({"{c}": ["Example Domain — example.com — Mozilla Firefox", "firefox", os.getpid()]})
    sn = uygulama._adres_dogrula(au2, "{c}", "example.com", tek)
    kontrol("R1 (kontrol): meşru 'Example Domain — example.com' tek pencerede, adres okunamadı → doğrular",
            sn[:2] == (True, "baslik"), str(sn))
    sn = uygulama._adres_dogrula(au2, "{c}", "example.com", lambda: False)
    kontrol("R1: aynı süreçte aynı başlıklı birden çok pencere (tek_mi False) → başlık doğrulaması YOK",
            sn[0] is False, str(sn))
    sayac = iter([True, True, False])
    sn = uygulama._adres_dogrula(au2, "{c}", "example.com", lambda: next(sayac, True))
    kontrol("R1: tek_mi döngüde bir kez bile False → başlık doğrulaması YOK", sn[0] is False, str(sn))

    uygulama.sec = lambda: au
    a = argparse.Namespace(url=None, adres=None, komut_satiri="firefox --no-remote", uygulama=None, baslik="Hedef",
                           sinif=None, sure=1.0, onayli=False, site=None)
    import contextlib
    import io
    cikti = io.StringIO()
    with contextlib.redirect_stdout(cikti), contextlib.redirect_stderr(io.StringIO()):
        _r, e = dene(lambda: uygulama.k_ac(a))
    kontrol("L3 CLI: k_ac aynı durumda Dur 7 vermez, doğrulanan pencereyi yazar",
            e is None and cikti.getvalue().startswith("{b} | Hedef"), f"{cikti.getvalue()!r} {e and e.mesaj}")
finally:
    (masaustu.durum, uygulama._kayitli_tarayicilar, api.tus, api.yaz, erisim.odak_bilgisi, web.sayfa_bilgisi,
     uygulama.YENI_PENCERE_BEKLE_SN, uygulama.ADRES_DOGRULA_SN, api.arka, uygulama.tum_pencereler, api.yasak_mi,
     uygulama._baslat, uygulama.sec) = ESKI
    kopya.temizle(KAYITLI)

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
