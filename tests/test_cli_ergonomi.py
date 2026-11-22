"""CLI ergonomi testleri (altı sürtünme düzeltmesi):
 1. `open --background` görünmez masaüstü kapalıyken kendiliğinden başlatır (kopya hazırlanmadan ÖNCE);
 2. `open APP [ADRES] / --url ADRES`: yalnız http/https, adres politikanın komutunun sonuna tek argüman;
 3. `screenshot` kimliksiz (--background: tüm masaüstü, değilse etkin pencere; gerçek ekran kilidi → 17), `--out`, `--width`;
 4. `windows` desensiz = tüm pencereler;
 5. `goto KİMLİK ADRES`: adres çubuğu yolu mevcut tus/yaz denetimleriyle, yalnız http(s);
 6. `--help` alt komut tablosu.
Birim kısımları sahte arka uç/api ile (ekransız); uçtan uca kısım GÖRÜNMEZ masaüstünde (kullanıcının ekranına girdi yok).

Çalıştır:  python3 tests/test_cli_ergonomi.py"""
import atexit
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from PIL import Image

from deskhand import api, cli, eylem, gezin, gorev_kipi, hata, komutlar, masaustu, uygulama, yollar
from deskhand.arka_uc import EKRAN
from deskhand.hata import Dur

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
KOK = _yalitim.KOK
TEST_PENCERE = os.path.join(KOK, "tests", "yardimci", "test_pencere.py")
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def dur_kodu(f, *a, **k):
    try:
        f(*a, **k)
    except Dur as e:
        return e.kod
    return None


# ================================================================= 2) adres doğrulama (saf işlev)
for iyi in ("https://example.com/a?b=1#c", "http://localhost:8080/x", "HTTPS://Example.com"):
    kontrol(f"adres kabul: {iyi}", dur_kodu(uygulama.web_adresi_denetle, iyi) is None)
for kotu in ("file:///etc/passwd", "about:config", "javascript:alert(1)", "data:text/html,x", "-evil", "--new-window",
             "//example.com", "example.com", "https://", "https://exa mple.com", "https://a.com\n--flag", "", "   ",
             "ftp://example.com", "chrome://settings", "view-source:https://a.com", "https://" + "a" * 3000):
    kontrol(f"adres RET (10): {kotu[:40]!r}", dur_kodu(uygulama.web_adresi_denetle, kotu) == 10)

# ================================================================= 2) open: komut satırı ve adres
GIRDI = {"ad": "Firefox", "ad_en": "Firefox", "exec": "firefox %u", "kimlik": "firefox.desktop",
         "yol": "/usr/share/applications/firefox.desktop"}


class Bitti(Exception):
    """sahte _baslat: başlatılacak komutu yakalayıp k_ac'ı durdurur."""


class SahteAu:
    def __init__(self, ad):
        self.ad = ad

    def aktif(self):
        return ""

    def baslik(self, k):
        return ""

    def sinif(self, k):
        return ""


class Sahne:
    """k_ac'ın dış bağımlılıklarını sahtele: olaylar sırayla kaydedilir."""

    def __init__(self, hedef="sanal", acik=False, kopya_argv=None):
        self.olay, self.komut, self.hedef, self.acik = [], None, hedef, acik
        self.kopya_argv = kopya_argv
        self.au = SahteAu(hedef)

    def __enter__(self):
        self.eski = (uygulama.sec, uygulama.uygulama_bul, uygulama._baslat, uygulama.oturum_hazirla,
                     uygulama.tum_pencereler, masaustu.durum, masaustu.masaustu_baslat)
        uygulama.sec = lambda *a, **k: self.au
        uygulama.uygulama_bul = lambda ad: dict(GIRDI)
        uygulama.tum_pencereler = lambda: set()

        def baslat(au, komut, fp, env=None, kopya=None, girdi=None, ev=()):
            self.olay.append("baslat")
            self.komut = list(komut)
            raise Bitti

        def hazirla(ad, siteler=None, ham_komut=False):
            self.olay.append("kopya")
            return (list(self.kopya_argv) if self.kopya_argv else None), {}, "oturum: sahte", "/kopya", ()

        def baslat_masaustu(*a, **k):
            self.olay.append("masaustu")
            self.acik = True
            return {"zaten": False}
        uygulama._baslat, uygulama.oturum_hazirla = baslat, hazirla
        masaustu.durum = lambda *a, **k: {"ekran": ":0"} if self.acik else None
        masaustu.masaustu_baslat = baslat_masaustu
        return self

    def __exit__(self, *e):
        (uygulama.sec, uygulama.uygulama_bul, uygulama._baslat, uygulama.oturum_hazirla,
         uygulama.tum_pencereler, masaustu.durum, masaustu.masaustu_baslat) = self.eski

    def calistir(self, *argv):
        """→ (çıkış: 0 | Dur kodu | 'bitti', stderr metni)."""
        a = cli.ayristirici().parse_args(list(argv))
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            try:
                uygulama.k_ac(a)
            except Bitti:
                return "bitti", err.getvalue()
            except Dur as e:
                return e.kod, err.getvalue()
        return 0, err.getvalue()


with Sahne("sanal", acik=False) as s:
    kod, err = s.calistir("--background", "open", "firefox")
    kontrol("open --background: masaüstü kapalıyken kendiliğinden başlatıldı", kod == "bitti" and s.olay[0] == "masaustu",
            f"{kod} {s.olay}")
    kontrol("open --background: masaüstü KOPYADAN önce başlatıldı (boşa kopya yok)",
            s.olay == ["masaustu", "kopya", "baslat"], str(s.olay))
    kontrol("open --background: çıktıda 'görünmez masaüstü başlatıldı' satırı", "görünmez masaüstü başlatıldı" in err, err)
with Sahne("sanal", acik=True) as s:
    kod, err = s.calistir("--background", "open", "firefox")
    kontrol("open --background: masaüstü zaten açıksa yeniden başlatılmaz",
            s.olay == ["kopya", "baslat"] and "başlatıldı" not in err.replace("başlatıldı:", ""), str(s.olay))
with Sahne("kde", acik=False) as s:
    kod, err = s.calistir("open", "firefox")
    kontrol("open (ön plan): masaüstü hiç başlatılmaz", "masaustu" not in s.olay and kod == "bitti", str(s.olay))
with Sahne("sanal", acik=False) as s:
    kod, err = s.calistir("--background", "open", "firefox", "file:///etc/passwd")
    kontrol("open --background + kötü adres: RET 10, masaüstü açılmadı, kopya yapılmadı", kod == 10 and s.olay == [],
            f"{kod} {s.olay}")

# adres: ön plan (gio launch) ve politika komutu (kopya) sonuna tek argüman
URL = "https://excel.cloud.microsoft/?x=1&y=2"
with Sahne("kde") as s:
    kod, _e = s.calistir("open", "firefox", URL)
    kontrol("open firefox ADRES: gio launch komutunun sonunda tek argüman",
            s.komut == ["gio", "launch", GIRDI["yol"], URL], str(s.komut))
    kod, _e = s.calistir("open", "firefox", "--url", URL)
    kontrol("open firefox --url ADRES: aynı", s.komut == ["gio", "launch", GIRDI["yol"], URL], str(s.komut))
    kod, _e = s.calistir("open", "firefox", URL, "--url", URL)
    kontrol("open: aynı adres hem konumsal hem --url → kabul", kod == "bitti")
    kod, _e = s.calistir("open", "firefox", URL, "--url", "https://baska.example")
    kontrol("open: iki farklı adres → 1", kod == 1, str(kod))
    kod, _e = s.calistir("open", "--command", "firefox", "--url", URL)
    kontrol("open --command + adres → 1 (uygulama adıyla aç)", kod == 1, str(kod))
    s.komut = None
    for kotu in ("file:///etc/shadow", "about:config", "javascript:alert(1)", "data:text/html,<b>x</b>", "-new-window"):
        kod, _e = s.calistir("open", "firefox", "--url", kotu) if not kotu.startswith("-") else \
            s.calistir("open", "firefox", "--url=" + kotu)
        kontrol(f"open: {kotu[:22]!r} adresi RET (10), hiçbir şey başlatılmadı", kod == 10 and s.komut is None,
                f"{kod} {s.komut}")
with Sahne("sanal", acik=True, kopya_argv=["firefox", "--profile", "/kopya", "--no-remote", "--new-instance"]) as s:
    kod, _e = s.calistir("--background", "open", "firefox", URL)
    kontrol("open --background firefox ADRES: oturum kopyası komutunun SONUNA tek argüman",
            s.komut == ["firefox", "--profile", "/kopya", "--no-remote", "--new-instance", URL], str(s.komut))

# Chromium ailesi: adres, erişilebilirlik bayrağından sonra da tek argüman olarak kalır
with tempfile.TemporaryDirectory() as td:
    dt = os.path.join(td, "chromium.desktop")
    with open(dt, "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=Chromium\nExec=chromium %U\n")
    argv = uygulama.erisim_bayragi_ekle(["gio", "launch", dt, URL])
    kontrol("chromium ailesi: gio launch + adres → bayrak adresten ÖNCE, adres son argüman",
            argv == ["chromium", uygulama.ERISIM_BAYRAGI, URL], str(argv))

# görev kipi: mevcut open_app_denetle kuralları CLI'de de geçerli
eski_etkin, eski_den = gorev_kipi.etkin, gorev_kipi.open_app_denetle
gorev_kipi.etkin = lambda: True
cagri = []


def den_ret(kimlik, belgeler):
    cagri.append((kimlik, list(belgeler)))
    return "görev kipinde yalnız web tarayıcısı açılabilir"


try:
    gorev_kipi.open_app_denetle = den_ret
    with Sahne("kde") as s:
        kod, _e = s.calistir("open", "firefox", URL)
        kontrol("görev kipi: open_app_denetle reddederse CLI de reddeder (10), başlatılmaz",
                kod == 10 and s.komut is None and cagri == [("firefox.desktop", [URL])], f"{kod} {cagri}")
    gorev_kipi.open_app_denetle = lambda kimlik, belgeler: None
    with Sahne("kde") as s:
        kod, _e = s.calistir("open", "firefox", URL)
        kontrol("görev kipi: denetim izin verirse (http adres) açılır", kod == "bitti", str(kod))
        kod, _e = s.calistir("open", "--command", "firefox")
        kontrol("görev kipi: ham komut (--command) açılmaz (10)", kod == 10, str(kod))
finally:
    gorev_kipi.etkin, gorev_kipi.open_app_denetle = eski_etkin, eski_den

# ================================================================= 3) screenshot: kimliksiz, --out
p = cli.ayristirici()
a = p.parse_args(["screenshot"])
kontrol("screenshot: kimlik isteğe bağlı (kimliksiz ayrıştırılır)", a.kimlik is None and a.cikti is None)
a = p.parse_args(["screenshot", "--out", "/tmp/x.png", "--width", "640"])
kontrol("screenshot: --out ve --width ayrıştırılır", a.cikti_dosya == "/tmp/x.png" and a.genislik == 640)
a = p.parse_args(["foto", "--cikti", "/tmp/y.png", "--genislik", "320"])
kontrol("foto: Türkçe --cikti / --genislik takma adları", a.cikti_dosya == "/tmp/y.png" and a.genislik == 320)
kontrol("varsayılan hedef: görünmez masaüstü → tüm masaüstü ('ekran')", cli.varsayilan_foto_hedefi(SahteAu("sanal")) == "ekran")


class AktifAu(SahteAu):
    def __init__(self, ak):
        super().__init__("kde")
        self.ak = ak

    def aktif(self):
        return self.ak


kontrol("varsayılan hedef: gerçek ekran kilidi (kapali) → 17 (etkin pencere sorulmaz bile)",
        dur_kodu(cli.varsayilan_foto_hedefi, AktifAu("{abc}")) == 17)
os.environ["DESKHAND_GERCEK_EKRAN"] = "salt-okuma"  # yalnız bu birim denetimi: ekran okuma serbest, au sahte
try:
    kontrol("varsayılan hedef: ön planda etkin pencere", cli.varsayilan_foto_hedefi(AktifAu("{abc}")) == "{abc}")
    kontrol("varsayılan hedef: etkin pencere yoksa → 8", dur_kodu(cli.varsayilan_foto_hedefi, AktifAu("")) == 8)
finally:
    os.environ["DESKHAND_GERCEK_EKRAN"] = "kapali"


def deskhand(*a, sure=90, env=None):
    r = subprocess.run([sys.executable, "-m", "deskhand", *a], capture_output=True, text=True, cwd=KOK, timeout=sure,
                       env={**os.environ, **(env or {})})
    return r.returncode, r.stdout + r.stderr


kod, out = deskhand("screenshot")
kontrol("CLI: kimliksiz screenshot, gerçek ekran kilitliyken (DESKHAND_GERCEK_EKRAN=kapali) → 17", kod == 17, f"{kod} {out[-200:]}")
kod, out = deskhand("screenshot", "{00000000-0000-0000-0000-000000000000}", "/tmp/a.png", "--out", "/tmp/b.png")
kontrol("CLI: konumsal yol + --out birlikte → 1", kod == 1 and "iki kez" in out, f"{kod} {out[-200:]}")

# ================================================================= 4) windows desensiz
a = p.parse_args(["windows"])
kontrol("windows: desen isteğe bağlı (desensiz ayrıştırılır)", a.desen is None)
a = p.parse_args(["bul", "firefox"])
kontrol("windows: desenli çağrı aynen çalışır", a.desen == "firefox")


class ListeAu(SahteAu):
    def __init__(self):
        super().__init__("kde")
        self.sorgu = []

    def pencereler(self, desen=None):
        self.sorgu.append(desen)
        return [("{a}", "Firefox", (0, 0, 10, 10)), ("{b}", "Parola Kasası", (1, 2, 3, 4))]


liste_au = ListeAu()
eski_arka, eski_yasak = cli.arka_al, api.yasak_mi
cli.arka_al = lambda: liste_au
api.yasak_mi = lambda w: "yasak" if w == "{b}" else None
try:
    cikti = io.StringIO()
    with contextlib.redirect_stdout(cikti):
        cli.k_bul(p.parse_args(["windows"]))
    kontrol("windows desensiz: TÜM pencereler (desen=None geçti)", liste_au.sorgu == [None] and
            "{a} | Firefox | 0 0 10 10" in cikti.getvalue() and "{b}" in cikti.getvalue(), cikti.getvalue())
    kontrol("windows: yasak pencerenin başlığı gösterilmez", "Parola" not in cikti.getvalue(), cikti.getvalue())
finally:
    cli.arka_al, api.yasak_mi = eski_arka, eski_yasak

# ================================================================= 5) goto
a = p.parse_args(["goto", "{abc}", "https://example.com"])
kontrol("goto: ayrıştırılır; komut iç adı 'git', girdi komutu (DUR + yasak ön denetimi)",
        a.komut == "git" and a.f is gezin.k_git and "git" in eylem.GIRDI_KOMUTLARI and komutlar.ic_ad("goto") == "git")
a = p.parse_args(["git", "{abc}", "https://example.com", "--approved"])
kontrol("goto: Türkçe 'git' + --approved", a.komut == "git" and a.onayli is True)

adimlar = []
eski = (api.tus, api.yaz, gezin.web.tarayici_mi, api.arka)


def sahte_tus(k, kombinasyon, baslik=None, onayli=False):
    adimlar.append(("tus", k, kombinasyon, baslik, onayli))
    return ""


def sahte_yaz(k, metin, baslik=None, gizli=False, onayli=False):
    adimlar.append(("yaz", k, metin, baslik, onayli))
    return ""


try:
    api.tus, api.yaz = sahte_tus, sahte_yaz
    gezin.web.tarayici_mi = lambda k: k != "{kate}"
    r = gezin.adrese_git("{ff}", "https://example.com/a b".replace(" ", "%20"), baslik="Excel", onayli=False)
    kontrol("goto: adım sırası ctrl+l → adres + Enter (TEK yazı eylemi: kapı Enter'ı adresle birlikte görür)",
            [(x[0], x[2]) for x in adimlar] == [("tus", "ctrl+l"), ("yaz", "https://example.com/a%20b\n")],
            str(adimlar))
    kontrol("goto: başlık kilidi (-b) her adıma iletilir", all(x[3] == "Excel" for x in adimlar), str(adimlar))
    adimlar.clear()
    gezin.adrese_git("{ff}", "https://example.com", onayli=True)
    kontrol("goto: --approved her adıma iletilir", all(x[4] is True for x in adimlar), str(adimlar))
    adimlar.clear()
    for kotu in ("file:///etc/passwd", "about:config", "javascript:alert(1)", "data:text/html,x", "example.com"):
        kontrol(f"goto: {kotu[:22]!r} RET (10), hiçbir girdi gitmedi",
                dur_kodu(gezin.adrese_git, "{ff}", kotu) == 10 and not adimlar, str(adimlar))
    kontrol("goto: tarayıcı olmayan pencere → 1, girdi yok",
            dur_kodu(gezin.adrese_git, "{kate}", "https://example.com") == 1 and not adimlar)
    kontrol("goto: tüm ekran (EKRAN) → 1, girdi yok",
            dur_kodu(gezin.adrese_git, EKRAN, "https://example.com") == 1 and not adimlar)

    def yaz_engel(k, metin, baslik=None, gizli=False, onayli=False):
        adimlar.append(("yaz", k, metin))
        raise Dur(4, "başlık uymadı")
    api.yaz = yaz_engel
    kod = dur_kodu(gezin.adrese_git, "{ff}", "https://example.com", baslik="X")
    kontrol("goto: yazı adımında denetim reddederse (4) başka adım YOK",
            kod == 4 and [x[0] for x in adimlar] == ["tus", "yaz"], f"{kod} {adimlar}")
    # görev kipi: yabancı pencere → pencere_denetle Dur(10), girdi yok
    adimlar.clear()
    api.yaz = sahte_yaz
    api.arka = lambda: SahteAu("sanal")
    eski_g = (gorev_kipi.etkin, gorev_kipi.pencere_denetle)
    gorev_kipi.etkin = lambda: True

    def pd(au, k, adres=None):
        raise Dur(10, "görev kipi: yabancı pencere")
    gorev_kipi.pencere_denetle = pd
    kontrol("goto: görev kipinde pencere denetimi uygulanır (10), girdi yok",
            dur_kodu(gezin.adrese_git, "{ff}", "https://example.com") == 10 and not adimlar)
    gorev_kipi.etkin, gorev_kipi.pencere_denetle = eski_g
finally:
    api.tus, api.yaz, gezin.web.tarayici_mi, api.arka = eski

# ================================================================= 6) --help tablosu
os.environ["COLUMNS"] = "120"
yardim = cli.ayristirici().format_help()
eksik = [f"{en} ({tr})" if en != tr else en for tr, en in komutlar.KOMUTLAR
         if (f"{en} ({tr})" if en != tr else en) not in yardim.replace("(yardım, yardim)", "(yardım)")]
kontrol("--help: her alt komut tabloda (İngilizce ad + Türkçe takma ad)", not eksik, str(eksik))
kontrol("--help: komut satırında kısa açıklama (windows)", any(l.strip().startswith("windows (bul)") and "pencere" in l
                                                              for l in yardim.splitlines()))
kontrol("--help: goto ve open açıklamaları", "goto (git)" in yardim and "--url ADRES" in yardim)
kod, out = deskhand("--help")
kontrol("CLI: deskhand --help çıktısında komut tablosu (grep ile bulunur)",
        kod == 0 and any(l.strip().startswith("screenshot (foto)") for l in out.splitlines()), out[-300:])
kontrol("yardım metni: ekran/deskhand komut listesinde goto ve kimliksiz screenshot",
        "goto (git)" in cli.yardim_metni() and "[kimlik] [png] [--out DOSYA]" in cli.yardim_metni())

# ================================================================= uçtan uca: GÖRÜNMEZ masaüstü (kapalıyken başla)
LOG = os.path.join(_yalitim.PAYLASIM, "ergo.log")
kontrol("uçtan uca: başlangıçta görünmez masaüstü kapalı", masaustu.durum() is None)
komut = f"env LOG={LOG} BASLIK=ergonomi-pencere HAZIR_MS=100 {sys.executable} {TEST_PENCERE}"
kod, out = deskhand("--background", "open", "--command", komut, "--approved", "--timeout", "40", sure=120)
kontrol("e2e: open --background (masaüstü kapalıydı) → 0 + 'görünmez masaüstü başlatıldı'",
        kod == 0 and "görünmez masaüstü başlatıldı" in out, f"{kod} {out[-400:]}")
kontrol("e2e: masaüstü şimdi açık", masaustu.durum() is not None)
kimlik = next((l.split(" | ")[0] for l in out.splitlines() if l.startswith("arka:")), None)
kontrol("e2e: yeni pencerenin arka: kimliği çıktıda", bool(kimlik), out[-300:])

kod, out = deskhand("--background", "windows")
kontrol("e2e: windows (desensiz) → pencere listelenir", kod == 0 and kimlik and kimlik in out, f"{kod} {out[-300:]}")
kod, out2 = deskhand("--background", "windows", "ergonomi-pencere")
kontrol("e2e: windows DESEN hâlâ çalışır", kod == 0 and kimlik and kimlik in out2, f"{kod} {out2[-300:]}")

kod, out = deskhand("--background", "screenshot")
varsayilan = os.path.join(yollar.cikti(), "pencere.png")
kontrol("e2e: screenshot kimliksiz (--background) → tüm masaüstü, varsayılan dosya",
        kod == 0 and os.path.exists(varsayilan), f"{kod} {out[-300:]}")
tam = Image.open(varsayilan).size if os.path.exists(varsayilan) else (0, 0)
hedef_dosya = os.path.join(_yalitim.GECICI, "alt", "kucuk.png")
kod, out = deskhand("--background", "screenshot", "--out", hedef_dosya, "--width", "320")
kucuk = Image.open(hedef_dosya).size if os.path.exists(hedef_dosya) else (0, 0)
kontrol("e2e: --out DOSYA + --width 320 → küçültülmüş görüntü (en-boy oranı korunur), yol çıktıda",
        kod == 0 and kucuk[0] == 320 and abs(kucuk[1] - round(tam[1] * 320 / max(tam[0], 1))) <= 1 and hedef_dosya in out,
        f"{kod} {tam} {kucuk} {out[-300:]}")
kod, out = deskhand("--background", "screenshot", kimlik, os.path.join(_yalitim.GECICI, "konumsal.png"))
kontrol("e2e: eski biçim (kimlik + konumsal yol) hâlâ çalışır",
        kod == 0 and os.path.exists(os.path.join(_yalitim.GECICI, "konumsal.png")), f"{kod} {out[-300:]}")
kod, out = deskhand("--background", "goto", kimlik, "https://example.com")
kontrol("e2e: goto tarayıcı olmayan pencerede → 1, girdi gitmedi", kod == 1 and "tarayıcı" in out, f"{kod} {out[-300:]}")
kod, out = deskhand("--background", "goto", kimlik, "file:///etc/passwd")
kontrol("e2e: goto file: adresi → 10", kod == 10, f"{kod} {out[-300:]}")

masaustu.masaustu_durdur()
print(f"\n{gecen}/{toplam} CLI ergonomi testi geçti")
sys.exit(0 if gecen == toplam else 1)
