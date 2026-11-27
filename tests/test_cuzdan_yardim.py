"""B1: cüzdan ve parola arka ucu testleri (deskhand/cuzdan_ac.py düğme işlevleri, anahtar_deposu sir_degistir /
sir_listesi / "parola kaydet" isteği, cli type --secret-ref kayıtlı olmayan ad → Dur 19).

Gerçek KDE Cüzdanı, gerçek kwalletd6/kcmshell6, gerçek TPM KULLANILMAZ: secretstorage sys.modules'ta SAHTE bir
modül, busctl / kcmshell6 / systemd-creds anahtar_deposu.SINAMA_ARACLARI ile sahte (PATH'e bakılmaz).

Çalıştır:  python3 tests/test_cuzdan_yardim.py"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import types

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import anahtar_deposu as AD
from deskhand import cli
from deskhand import cuzdan_ac as CA
from deskhand.hata import SIR_YOK, Dur

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


S = tempfile.mkdtemp(prefix="sahte-yardim-", dir=_yalitim.GECICI)
ARGV = os.path.join(S, "argv.log")
DURUM = os.path.join(S, "durum")
PY = sys.executable


def betik(ad, govde):
    yol = os.path.join(S, ad)
    with open(yol, "w") as f:
        f.write(f"#!{PY}\nimport os, sys\nARGV={ARGV!r}\nDURUM={DURUM!r}\n"
                f"open(ARGV, 'a').write({ad!r} + ' ' + ' '.join(sys.argv[1:]) + '\\n')\n" + govde)
    os.chmod(yol, 0o755)
    AD.SINAMA_ARACLARI[ad] = yol


betik("systemd-creds", """
import base64
a = sys.argv[1:]
if a[:1] == ["has-tpm2"]: sys.exit(0)
ad = next((x.split("=", 1)[1] for x in a if x.startswith("--name=")), "")
if "encrypt" in a:
    sys.stdout.buffer.write(b"S1:" + ad.encode() + b":" + base64.b64encode(sys.stdin.buffer.read())); sys.exit(0)
p = sys.stdin.buffer.read().split(b":", 2)
if len(p) != 3 or p[1].decode() != ad: sys.exit(1)
sys.stdout.buffer.write(base64.b64decode(p[2]))
""")
betik("busctl", """
d = dict(x.split("=") for x in open(DURUM).read().split())
a = sys.argv[1:]
if "changePassword" in a: sys.exit(0 if d.get("degistir", "1") == "1" else 1)
if "NameHasOwner" in a: print("b true" if d["sahip"] == "1" else "b false"); sys.exit(0)
if "get-property" in a:
    if d["sahip"] != "1": sys.exit(1)
    print("b true" if d["kilit"] == "1" else "b false"); sys.exit(0)
sys.exit(2)
""")
betik("kcmshell6", "sys.exit(0)\n")


def durum_yaz(sahip=1, kilit=1, degistir=1):
    with open(DURUM, "w") as f:
        f.write(f"sahip={sahip} kilit={kilit} degistir={degistir}")


def argv_satirlari(arac):
    try:
        return [s for s in open(ARGV).read().splitlines() if s.startswith(arac + " ")]
    except FileNotFoundError:
        return []


os.environ["XDG_DATA_HOME"] = os.path.join(S, "data")
durum_yaz()

# ---------------------------------------------------------------- sahte secretstorage (Unlock sayacı)
SAYAC = {"unlock": 0, "baglanti": 0}
SS = {"kilitli": True, "unlock_sonucu": "ac", "bekle": 0.0}


class SahteKoleksiyon:
    def is_locked(self):
        return SS["kilitli"]

    def unlock(self):
        SAYAC["unlock"] += 1
        if SS["bekle"]:
            time.sleep(SS["bekle"])
        if SS["unlock_sonucu"] == "hata":
            raise RuntimeError("D-Bus hatası")
        if SS["unlock_sonucu"] == "ac":
            SS["kilitli"] = False
            return False
        return True  # dismissed (iptal)


class SahteBaglanti:
    def close(self):
        pass


sahte_ss = types.ModuleType("secretstorage")


def _dbus_init():
    SAYAC["baglanti"] += 1
    return SahteBaglanti()


sahte_ss.dbus_init = _dbus_init
sahte_ss.get_default_collection = lambda b: SahteKoleksiyon()
sys.modules["secretstorage"] = sahte_ss

# ---------------------------------------------------------------- 1. düğme dışı yollar Unlock ÇAĞIRMAZ
os.environ["DESKHAND_ANAHTARLIK"] = "kapali"
durum_yaz(sahip=1, kilit=1)
CA.cuzdan_ac()
CA.durum()
CA.cuzdan_durumu()
CA.main(["status"])
durum_yaz(sahip=0, kilit=1)
CA.cuzdan_ac()
kontrol("Unlock: cuzdan_ac / durum / cuzdan_durumu / CLI status → Unlock 0, secretstorage bağlantısı 0",
        SAYAC == {"unlock": 0, "baglanti": 0}, SAYAC)
r = subprocess.run([PY, "-c", "import sys; from deskhand import cuzdan_ac; sys.exit(cuzdan_ac.main(['status']))"],
                   capture_output=True, text=True, timeout=30, cwd=_yalitim.KOK,
                   env={**os.environ, "PYTHONPATH": _yalitim.KOK})
kontrol("CLI wallet status ayrı süreçte: secretstorage yüklenmeden biter", r.returncode == 0, r.stderr[-300:])

# kaynak taraması: Unlock / changePassword / kcm_users ve düğme işlevleri yalnız cuzdan_ac.py (tanım) + gui/ (çağrı)
DESEN = re.compile(r"\.unlock\(|[\"']Unlock[\"']|changePassword|kcm_users|kullanici_kilit_ac|parola_degistir_baslat|"
                   r"kullanici_ayari_ac")
disarida = []
for kok, _dizinler, dosyalar in os.walk(os.path.join(_yalitim.KOK, "deskhand")):
    for d in dosyalar:
        if not d.endswith(".py"):
            continue
        yol = os.path.join(kok, d)
        goreli = os.path.relpath(yol, _yalitim.KOK)
        if goreli == os.path.join("deskhand", "cuzdan_ac.py") or goreli.startswith(os.path.join("deskhand", "gui") + "/"):
            continue
        with open(yol, encoding="utf-8", errors="replace") as f:
            for no, satir in enumerate(f, 1):
                if DESEN.search(satir):
                    disarida.append(f"{goreli}:{no}")
kontrol("kaynak taraması: Unlock/changePassword/kcm_users yalnız cuzdan_ac.py + gui/ (MCP/CLI/arka planda yok)",
        not disarida, disarida)
# A2: panelin otomatik giriş kartı (gui/cuzdan_karti.py) ve "bir daha gösterme" işareti yalnız panelden: kart sınıfı ve
# kart_kapat yalnız oto_giris.py (tanım) + gui/ (çağrı); arka plan / MCP / CLI kartın düğmelerine ulaşmaz
KART_DESEN = re.compile(r"CuzdanGirisKarti|cuzdan_karti|kart_kapat\(")
kart_disarida = []
for kok, _dizinler, dosyalar in os.walk(os.path.join(_yalitim.KOK, "deskhand")):
    for d in dosyalar:
        if not d.endswith(".py"):
            continue
        yol = os.path.join(kok, d)
        goreli = os.path.relpath(yol, _yalitim.KOK)
        if goreli == os.path.join("deskhand", "oto_giris.py") or goreli.startswith(os.path.join("deskhand", "gui") + "/"):
            continue
        with open(yol, encoding="utf-8", errors="replace") as f:
            for no, satir in enumerate(f, 1):
                if KART_DESEN.search(satir):
                    kart_disarida.append(f"{goreli}:{no}")
kontrol("kaynak taraması: cüzdan kartı ve kart_kapat yalnız oto_giris.py + gui/ (MCP/CLI/arka planda yok)",
        not kart_disarida, kart_disarida)
kontrol("kaynak taraması: gui/cuzdan_karti.py var (tarama boşa koşmuyor)",
        os.path.isfile(os.path.join(_yalitim.KOK, "deskhand", "gui", "cuzdan_karti.py")))
with open(os.path.join(_yalitim.KOK, "deskhand", "cuzdan_ac.py"), encoding="utf-8") as f:
    kaynak = f.read()
govde_main = kaynak[kaynak.index("def main("):]
kontrol("kaynak taraması: cuzdan_ac.main (CLI) düğme işlevlerini çağırmaz", not DESEN.search(govde_main))
kontrol("kaynak taraması: .unlock( cuzdan_ac.py'de tek yerde", len(re.findall(r"\.unlock\(", kaynak)) == 1)

# ---------------------------------------------------------------- 2. kullanici_kilit_ac
SS.update(kilitli=True, unlock_sonucu="ac", bekle=0.0)
kontrol("kilit aç: kullanıcı parolayı girdi → True, tek Unlock", CA.kullanici_kilit_ac(5) is True and
        SAYAC["unlock"] == 1, SAYAC)
SAYAC["unlock"] = 0
kontrol("kilit aç: zaten açık → True, Unlock çağrılmaz", CA.kullanici_kilit_ac(5) is True and SAYAC["unlock"] == 0)
SS.update(kilitli=True, unlock_sonucu="iptal")
kontrol("kilit aç: iptal → False (Kilitli), tek Unlock, döngü yok", CA.kullanici_kilit_ac(5) is False and
        SAYAC["unlock"] == 1, SAYAC)
SAYAC["unlock"] = 0
SS.update(kilitli=True, unlock_sonucu="hata")
kontrol("kilit aç: D-Bus hatası → False", CA.kullanici_kilit_ac(5) is False and SAYAC["unlock"] == 1)
SAYAC["unlock"] = 0
SS.update(kilitli=True, unlock_sonucu="ac", bekle=2.0)
t0 = time.monotonic()
s_ = CA.kullanici_kilit_ac(0.3)
kontrol("kilit aç: zaman aşımı → False hemen (beklemez), tek Unlock", s_ is False and time.monotonic() - t0 < 1.5 and
        SAYAC["unlock"] == 1, (s_, time.monotonic() - t0))
time.sleep(2.0)
SS["bekle"] = 0.0
del sys.modules["secretstorage"]
sys.modules["secretstorage"] = None  # python-secretstorage yok
kontrol("kilit aç: secretstorage yok → False", CA.kullanici_kilit_ac(2) is False)
sys.modules["secretstorage"] = sahte_ss

# ---------------------------------------------------------------- 3. parola_degistir_baslat / cuzdan_durumu / kcm
durum_yaz(sahip=1, kilit=1, degistir=1)
kontrol("parola değiştir: KDE penceresi istendi → True", CA.parola_degistir_baslat(4242) is True)
s = argv_satirlari("busctl")[-1]
kontrol("parola değiştir: changePassword sxs kdewallet <wid> Deskhand (kwalletd6)",
        "call org.kde.kwalletd6 /modules/kwalletd6 org.kde.KWallet changePassword sxs kdewallet 4242 Deskhand" in s, s)
CA.parola_degistir_baslat("x; rm -rf ~")
kontrol("parola değiştir: geçersiz wid → 0 (argv'ye ham metin girmez)",
        argv_satirlari("busctl")[-1].endswith("kdewallet 0 Deskhand"), argv_satirlari("busctl")[-1])
durum_yaz(sahip=1, kilit=1, degistir=0)
kontrol("parola değiştir: D-Bus reddi → False", CA.parola_degistir_baslat(0) is False)
AD.SINAMA_ARACLARI["busctl"] = None
kontrol("parola değiştir: busctl yok → False", CA.parola_degistir_baslat(0) is False)
AD.SINAMA_ARACLARI["busctl"] = os.path.join(S, "busctl")
durum_yaz(sahip=1, kilit=1)
d = CA.cuzdan_durumu()
kontrol("cuzdan_durumu: cüzdan yok + tuz yok", d == {"var": False, "kilitli": True, "giris_parolasi_olasi": False}, d)
os.makedirs(os.path.join(os.environ["XDG_DATA_HOME"], "kwalletd"), exist_ok=True)
for ad_ in ("kdewallet.kwl", "kdewallet.salt"):
    with open(os.path.join(os.environ["XDG_DATA_HOME"], "kwalletd", ad_), "wb") as f:
        f.write(b"x")
durum_yaz(sahip=0, kilit=1)
d = CA.cuzdan_durumu()
kontrol("cuzdan_durumu: cüzdan var, servis yok → kilitli None, giriş parolası olası",
        d == {"var": True, "kilitli": None, "giris_parolasi_olasi": True}, d)
cagri = []
eski_popen = subprocess.Popen


class KayitPopen:
    def __init__(self, argv, *a, **k):
        cagri.append((list(argv), k.get("env"), k.get("start_new_session")))


subprocess.Popen = KayitPopen
try:
    ok = CA.kullanici_ayari_ac()
finally:
    subprocess.Popen = eski_popen
kontrol("kullanıcı ayarları: kcmshell6 kcm_users ayrık, temiz ortam",
        ok and cagri and cagri[0][0] == [os.path.join(S, "kcmshell6"), "kcm_users"] and cagri[0][2] and
        cagri[0][1].get("PATH") == "/usr/bin:/bin", cagri)
AD.SINAMA_ARACLARI["kcmshell6"] = None
kontrol("kullanıcı ayarları: kcmshell6 yok → False", CA.kullanici_ayari_ac() is False)

# ---------------------------------------------------------------- 4. sir_degistir / sir_listesi (kasa, sahte creds)
os.environ.pop("DESKHAND_ANAHTARLIK")
AD.ornek_ayarla("kasa", None)
AD._ayar_yaz("kasa")
try:
    AD.sir_yaz("banka", b"Eski-Parola-1", "firefox", "ornekbanka.com.tr")
    AD.sir_yaz("posta", b"Posta-Parola-2")
    AD.ornek("kasa").yaz("eski-bicim", b"Zarfsiz-Deger-3")  # zarfsız eski kayıt
    once = AD._sir_ac(AD.ornek("kasa").oku("banka"))[2]
    time.sleep(1.05)
    AD.sir_degistir("banka", b"Yeni-Parola-9")
    deger, hedef = AD.sir_oku("banka")
    sonra = AD._sir_ac(AD.ornek("kasa").oku("banka"))[2]
    kontrol("sir_degistir: yeni değer yazıldı", deger == b"Yeni-Parola-9")
    kontrol("sir_degistir: site ve uygulama bağı aynen korunur",
            hedef == {"uygulama": "firefox", "site": "ornekbanka.com.tr"}, hedef)
    kontrol("sir_degistir: nesil +1, değişim zamanı ilerler",
            sonra["nesil"] == once["nesil"] + 1 and sonra["degisim"] > once["degisim"], (once, sonra))
    try:
        AD.sir_degistir("yok-boyle", b"x")
        kontrol("sir_degistir: kayıtlı olmayan ad → DepoHatasi", False)
    except AD.DepoHatasi:
        kontrol("sir_degistir: kayıtlı olmayan ad → DepoHatasi", "yok-boyle" not in AD.ornek("kasa").tum_adlar())
    for kotu in ("panel-isaret", "kde-cuzdan"):
        try:
            AD.sir_degistir(kotu, b"x")
            kontrol(f"sir_degistir: iç ad ({kotu}) reddedilir", False)
        except ValueError:
            kontrol(f"sir_degistir: iç ad ({kotu}) reddedilir", True)
    try:
        AD.sir_degistir("posta", b"")
        kontrol("sir_degistir: boş değer reddedilir", False)
    except ValueError:
        kontrol("sir_degistir: boş değer reddedilir", AD.sir_oku("posta")[0] == b"Posta-Parola-2")
    liste = AD.sir_listesi()
    metin = json.dumps(liste, ensure_ascii=False)
    kontrol("sir_listesi: alanlar ad/site/uygulama/degisim, ada göre sıralı",
            [x["ad"] for x in liste] == ["banka", "eski-bicim", "posta"] and
            all(set(x) == {"ad", "site", "uygulama", "degisim"} for x in liste), liste)
    kontrol("sir_listesi: DEĞER YOK", not any(v in metin for v in ("Yeni-Parola", "Posta-Parola", "Zarfsiz", "Eski-Par")))
    kontrol("sir_listesi: bağ ve zaman doğru; zarfsız kayıt bağsız, zamanı None",
            liste[0]["site"] == "ornekbanka.com.tr" and liste[0]["uygulama"] == "firefox" and
            isinstance(liste[0]["degisim"], int) and liste[1]["site"] is None and liste[1]["degisim"] is None)
    kontrol("sir_listesi: iç öğeler görünmez", not {"panel-isaret", "kde-cuzdan"} & {x["ad"] for x in liste})

    # ------------------------------------------------------------ 5. kayıtlı olmayan parola → Dur 19 + değersiz istek
    from deskhand import eylem  # noqa: E402
    yakalanan, sorulan = [], []
    eski = (cli.k_yaz, eylem._parola_alani_mi, cli._guncel_konak, cli._pencere_bilgisi, cli.guvenlik._panelden_onay)
    cli.k_yaz = lambda a: yakalanan.append(a.metin)
    eylem._parola_alani_mi = lambda k: True
    cli._guncel_konak = lambda k: "giris.ornekbanka.com.tr"
    cli._pencere_bilgisi = lambda k: ("Giriş", "firefox")
    cli.guvenlik._panelden_onay = lambda *a, **k: (sorulan.append(a) or (False, "red"))
    try:
        ns = cli.ayristirici().parse_args(["type", "pencere-1", "--secret-ref", "kargo"])
        try:
            ns.f(ns)
            kontrol("SIR_YOK: kayıtlı olmayan ad → Dur 19", False)
        except Dur as e:
            kontrol("SIR_YOK: kayıtlı olmayan ad → Dur 19 (tur sir_yok), ileti panel kaydı der",
                    e.kod == SIR_YOK == 19 and e.tur == "sir_yok" and "panelde" in e.mesaj, (e.kod, e.mesaj))
        kontrol("SIR_YOK: hiçbir şey yazılmadı, onay sorulmadı", not yakalanan and not sorulan)
        ist = AD.sir_istekleri()
        kontrol("SIR_YOK: panele tek istek {tur: sir_kaydet, ad, site} (site = alanın sayfası)",
                len(ist) == 1 and ist[0]["tur"] == "sir_kaydet" and ist[0]["ad"] == "kargo" and
                ist[0]["site"] == "giris.ornekbanka.com.tr", ist)
        dosya = os.path.join(AD.sir_istek_dizini(), ist[0]["id"] + ".json")
        with open(dosya) as f:
            ham = json.load(f)
        kontrol("SIR_YOK: istek dosyasında DEĞER alanı yok (yalnız tur/ad/site/zaman), 0600 + dizin 0700",
                set(ham) == {"tur", "ad", "site", "zaman"} and (os.stat(dosya).st_mode & 0o777) == 0o600 and
                (os.stat(AD.sir_istek_dizini()).st_mode & 0o777) == 0o700, (ham, oct(os.stat(dosya).st_mode)))
        try:
            ns.f(ns)
        except Dur:
            pass
        kontrol("SIR_YOK: aynı ad+site için ikinci istek açılmaz", len(AD.sir_istekleri()) == 1)
        cli._guncel_konak = lambda k: (_ for _ in ()).throw(Dur(10, "kök belirlenemedi"))
        try:
            cli.ayristirici().parse_args(["type", "p", "--secret-ref", "bulut"]).f(
                cli.ayristirici().parse_args(["type", "p", "--secret-ref", "bulut"]))
        except Dur as e:
            kontrol("SIR_YOK: site belirlenemezse yine Dur 19, istek sitesiz",
                    e.kod == 19 and any(x["ad"] == "bulut" and x["site"] is None for x in AD.sir_istekleri()))
        kontrol("SIR_YOK: istek kapatılır", AD.sir_istegi_kapat(ist[0]["id"]) and
                all(x["id"] != ist[0]["id"] for x in AD.sir_istekleri()))
        kontrol("istek: iç ad / geçersiz ad için istek yazılmaz",
                AD.sir_istegi_yaz("panel-isaret") is None and AD.sir_istegi_yaz("../kotu") is None)
        kontrol("istek: geçersiz site atılır", AD.sir_istegi_yaz("ftp", "javascript:alert(1)") is not None and
                any(x["ad"] == "ftp" and x["site"] is None for x in AD.sir_istekleri()))
        with open(os.path.join(AD.sir_istek_dizini(), "0" * 32 + ".json"), "w") as f:
            json.dump({"tur": "baska", "ad": "x"}, f)
        with open(os.path.join(AD.sir_istek_dizini(), "1" * 32 + ".json"), "w") as f:
            json.dump({"tur": "sir_kaydet", "ad": "eski", "site": None, "zaman": time.time() - 2 * 86400}, f)
        kontrol("istek: yabancı tür ve süresi dolmuş istek okunmaz (dolmuş silinir)",
                not any(x["ad"] in ("x", "eski") for x in AD.sir_istekleri()) and
                not os.path.exists(os.path.join(AD.sir_istek_dizini(), "1" * 32 + ".json")))
        for i in range(25):
            AD.sir_istegi_yaz(f"toplu{i}")
        kontrol("istek: en çok 20 bekleyen istek", len(AD.sir_istekleri()) == 20)
    finally:
        cli.k_yaz, eylem._parola_alani_mi, cli._guncel_konak, cli._pencere_bilgisi, cli.guvenlik._panelden_onay = eski
    from deskhand import mcp_sunucu  # noqa: E402
    kontrol("MCP: 19 için kod adı + 'ne yapmalı' satırı (parolayı ajana yazdırmaz)",
            19 in mcp_sunucu.KOD_ADI and "never ask the user to type the password" in mcp_sunucu.IPUCU[19])
finally:
    os.environ["DESKHAND_ANAHTARLIK"] = "kapali"
    AD.ornek_ayarla("kasa", None)

kontrol("arka planda iş parçacığı birikmez (zaman aşımındaki tek Unlock dışında)",
        sum(1 for t in threading.enumerate() if t.name == "deskhand-cuzdan-kilit-ac") == 0)
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
