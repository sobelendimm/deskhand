"""Anahtar deposu (deskhand/anahtar_deposu.py) testleri: kasa (systemd-creds), seçim, depo değişimi, kapalı-başarısızlık,
CLI `secret` ve `type --secret-ref`.

Gerçek TPM ve gerçek KDE Cüzdanı KULLANILMAZ: PATH'in başına konan SAHTE bir systemd-creds (geçici dizinde) mühürler;
cüzdan yerine sahte bir depo nesnesi verilir (anahtar_deposu.ornek_ayarla). DESKHAND_*_DIR'ler geçici (tests/_yalitim.py).

Çalıştır:  python3 tests/test_anahtar_deposu.py"""
import json
import os
import stat
import subprocess
import sys
import tempfile

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import anahtar_deposu as AD
from deskhand import cli, liste_koruma, yollar
from deskhand.hata import Dur

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


# ---------------------------------------------------------------- sahte systemd-creds
SAHTE_DIZIN = tempfile.mkdtemp(prefix="sahte-creds-", dir=_yalitim.GECICI)
ARGV_GUNLUK = os.path.join(SAHTE_DIZIN, "argv.log")
SAHTE = os.path.join(SAHTE_DIZIN, "systemd-creds")
with open(SAHTE, "w") as f:
    f.write(f"""#!{sys.executable}
import base64, os, sys
kip = os.environ.get("SAHTE_CREDS_KIP", "tamam")
with open({ARGV_GUNLUK!r}, "a") as g:
    g.write(" ".join(sys.argv[1:]) + "\\n")
arg = sys.argv[1:]
if arg[:1] == ["has-tpm2"]:
    sys.exit(1 if kip == "tpm-yok" else 0)
if "--user" not in arg:
    sys.stderr.write("--user yok\\n"); sys.exit(2)
ad = next((a.split("=", 1)[1] for a in arg if a.startswith("--name=")), "")
if "encrypt" in arg:
    if kip == "enc-hata":
        sys.stderr.write("Failed to encrypt\\n"); sys.exit(1)
    veri = sys.stdin.buffer.read()
    sys.stdout.buffer.write(b"SAHTE1:" + ad.encode() + b":" + base64.b64encode(veri[::-1]))
    sys.exit(0)
if "decrypt" in arg:
    m = sys.stdin.buffer.read()
    p = m.split(b":", 2)
    if kip == "bozuk" or len(p) != 3 or p[0] != b"SAHTE1":
        sys.stderr.write("Failed to decrypt credential\\n"); sys.exit(1)
    if p[1].decode() != ad:
        sys.stderr.write("Name in credential doesn't match expectations.\\n"); sys.exit(1)
    sys.stdout.buffer.write(base64.b64decode(p[2])[::-1]); sys.exit(0)
sys.exit(3)
""")
os.chmod(SAHTE, 0o755)
os.environ["PATH"] = SAHTE_DIZIN + os.pathsep + os.environ.get("PATH", "")
os.environ["SAHTE_CREDS_KIP"] = "tamam"


def argv_metni() -> str:
    try:
        with open(ARGV_GUNLUK) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def cagri_sayisi(sozcuk: str) -> int:
    return sum(1 for s in argv_metni().splitlines() if sozcuk in s.split())


DEGER = b"gizli-Deger-\xc3\xa7\xc4\x9f-123"

# ---------------------------------------------------------------- 1. kasa: yaz / oku / izinler / atomik
kasa = AD.KasaDepo()
kontrol("kasa: yok → None (öğe yok, hata değil)", kasa.oku("hesap1") is None)
kasa.yaz("hesap1", DEGER)
kontrol("kasa: yaz → oku aynı değer", kasa.oku("hesap1") == DEGER)
yol = os.path.join(yollar.data_dir(), "kasa", "hesap1.cred")
kontrol("kasa: öğe dosyası 0600", stat.S_IMODE(os.stat(yol).st_mode) == 0o600, oct(os.stat(yol).st_mode))
kontrol("kasa: dizin 0700", stat.S_IMODE(os.stat(os.path.dirname(yol)).st_mode) == 0o700)
with open(yol, "rb") as f:
    ham = f.read()
kontrol("kasa: dosyada düz değer yok", DEGER not in ham)
kontrol("kasa: değer argv'de yok (stdin/stdout)", DEGER.decode() not in argv_metni() and "gizli-Deger" not in argv_metni())
kontrol("kasa: --user + --with-key=auto + --name ile mühürlenir",
        "--user --name=hesap1 --with-key=auto encrypt - -" in argv_metni(), argv_metni())
kontrol("kasa: geçici dosya artığı yok", sorted(os.listdir(os.path.dirname(yol))) == ["hesap1.cred"])

# önbellek: aynı dosya ikinci okumada systemd-creds çağırmaz; dosya değişince yeniden çözer
k2 = AD.KasaDepo()
once = cagri_sayisi("decrypt")
k2.oku("hesap1"); k2.oku("hesap1"); k2.oku("hesap1")
kontrol("kasa: aynı mühür yoklamada bir kez çözülür (önbellek)", cagri_sayisi("decrypt") - once == 1)
kasa.yaz("hesap1", b"yeni")
kontrol("kasa: dosya değişince önbellek geçersiz", k2.oku("hesap1") == b"yeni")
kasa.yaz("hesap1", DEGER)

# atomik: şifreleme başarısızsa eski dosya yerinde, artık yok
os.environ["SAHTE_CREDS_KIP"] = "enc-hata"
try:
    kasa.yaz("hesap1", b"bozulmamali")
    kontrol("kasa: şifreleme hatası DepoHatasi", False)
except AD.DepoHatasi as e:
    kontrol("kasa: şifreleme hatası DepoHatasi (değersiz neden)", "bozulmamali" not in e.neden, e.neden)
os.environ["SAHTE_CREDS_KIP"] = "tamam"
kontrol("kasa: şifreleme hatasında eski değer korunur", AD.KasaDepo().oku("hesap1") == DEGER)
kontrol("kasa: şifreleme hatasında artık yok", sorted(os.listdir(os.path.dirname(yol))) == ["hesap1.cred"])

# ---------------------------------------------------------------- 2. bozuk mühür / başka ad / symlink / araç yok / TPM yok
os.environ["SAHTE_CREDS_KIP"] = "bozuk"
try:
    AD.KasaDepo().oku("hesap1")
    kontrol("bozuk mühür → DepoHatasi", False)
except AD.DepoHatasi as e:
    kontrol("bozuk mühür → DepoHatasi + anlaşılır neden + cüzdan önerisi",
            "mühür bozuk" in e.neden and "KDE Cüzdanı" in e.neden and not e.yok_kesin, e.neden)
os.environ["SAHTE_CREDS_KIP"] = "tamam"

kasa_dizin = os.path.dirname(yol)
os.link(yol, os.path.join(kasa_dizin, "baska.cred"))  # mühür başka bir ada kopyalandı
try:
    AD.KasaDepo().oku("baska")
    kontrol("başka ada kopyalanan mühür açılmaz", False)
except AD.DepoHatasi:
    kontrol("başka ada kopyalanan mühür açılmaz", True)
os.unlink(os.path.join(kasa_dizin, "baska.cred"))

hedef = os.path.join(_yalitim.GECICI, "baska-dosya")
with open(hedef, "wb") as f:
    f.write(ham)
os.symlink(hedef, os.path.join(kasa_dizin, "bag.cred"))
try:
    AD.KasaDepo().oku("bag")
    kontrol("sembolik bağ öğe reddedilir", False)
except AD.DepoHatasi:
    kontrol("sembolik bağ öğe reddedilir", True)
os.unlink(os.path.join(kasa_dizin, "bag.cred"))

eski_path = os.environ["PATH"]
os.environ["PATH"] = os.path.join(_yalitim.GECICI, "bos-path")
try:
    try:
        AD.KasaDepo().oku("hesap1")
        kontrol("systemd-creds yok → DepoHatasi(yok_kesin)", False)
    except AD.DepoHatasi as e:
        kontrol("systemd-creds yok → DepoHatasi(yok_kesin) + cüzdan önerisi", e.yok_kesin and "KDE Cüzdanı" in e.neden,
                e.neden)
    d = AD.KasaDepo().durum()
    kontrol("systemd-creds yok → durum hazir=False, neden dolu", d["tur"] == "kasa" and not d["hazir"] and d["neden"])
    kontrol("systemd-creds yok → servis_yok_kesin", AD.KasaDepo().servis_yok_kesin())
finally:
    os.environ["PATH"] = eski_path

AD._TPM = None
os.environ["SAHTE_CREDS_KIP"] = "tpm-yok"
d = AD.KasaDepo().durum()
kontrol("TPM yok → durum tpm=False, kasa yine hazır (makine anahtarı)", d["tpm"] is False and d["hazir"], d)
os.environ["SAHTE_CREDS_KIP"] = "tamam"
AD._TPM = None
kontrol("TPM var → durum tpm=True", AD.KasaDepo().durum()["tpm"] is True)
kontrol("durum biçimi", set(AD.KasaDepo().durum()) == {"tur", "hazir", "neden", "tpm"})

# ---------------------------------------------------------------- 3. adlar
kasa.yaz("panel-isaret", b"{}")
kontrol("listele: iç adlar görünmez", kasa.listele() == ["hesap1"], kasa.listele())
kontrol("tum_adlar: iç adlar dahil", "panel-isaret" in kasa.tum_adlar())
for kotu in ("../x", "a/b", "", ".gizli", "x" * 65, "a b"):
    try:
        kasa.yaz(kotu, b"v")
        kontrol(f"geçersiz ad reddedilir: {kotu!r}", False)
    except ValueError:
        kontrol(f"geçersiz ad reddedilir: {kotu!r}", True)
kontrol("kullanici_adi_mi: iç ad değil", not AD.kullanici_adi_mi("panel-isaret") and AD.kullanici_adi_mi("banka.1"))
kasa.sil("panel-isaret")

# ---------------------------------------------------------------- 4. seçim
kontrol("kapalı (testler): secili_depo reddeder", isinstance(AD.secili_depo(), AD.KapaliDepo))
os.environ.pop("DESKHAND_ANAHTARLIK")
try:
    kontrol("seçim: kasada öğe var → kasa", AD.secili_tur() == "kasa")
    kasa.sil("hesap1")
    isaret = liste_koruma.isaret_yolu("yasak")
    os.makedirs(os.path.dirname(isaret), exist_ok=True)
    with open(isaret, "w") as f:
        f.write("{}")
    kontrol("seçim: ayar yok + panel işareti (cüzdan kullanılmış) → cuzdan", AD.secili_tur() == "cuzdan")
    os.unlink(isaret)
    kontrol("seçim: yeni kurulum → kasa", AD.secili_tur() == "kasa")
    AD._ayar_yaz("cuzdan")
    kontrol("seçim: [anahtar] depo ayarı uygulanır", AD.secili_tur() == "cuzdan")
    from deskhand import ayarlar
    kontrol("seçim: diğer ayarlar bilinmeyen bölüm uyarısı vermez", ayarlar.oku()["guvenlik"]["onaylar"] == "hepsi")
    AD._ayar_yaz("kasa")
finally:
    os.environ["DESKHAND_ANAHTARLIK"] = "kapali"


# ---------------------------------------------------------------- 5. kapalı-başarısızlık (İnceleme odağı 2) + depo değişimi
class SahteCuzdan(AD.Depo):
    tur = "cuzdan"

    def __init__(self):
        self.d, self.kilitli = {}, False

    def _k(self):
        if self.kilitli:
            raise AD.DepoHatasi("cüzdan kilitli")

    def oku(self, ad):
        self._k()
        return self.d.get(ad)

    def yaz(self, ad, veri):
        self._k()
        self.d[ad] = bytes(veri)

    def sil(self, ad):
        self._k()
        return self.d.pop(ad, None) is not None

    def listele(self):
        self._k()
        return sorted(a for a in self.d if a not in AD.IC_ADLAR)

    def tum_adlar(self):
        self._k()
        return sorted(self.d)

    def durum(self):
        return {"tur": "cuzdan", "hazir": not self.kilitli, "neden": None, "tpm": False}


cuzdan = SahteCuzdan()
AD.ornek_ayarla("cuzdan", cuzdan)
AD.ornek_ayarla("kasa", None)
liste_koruma.isaret_anahtarlik_ayarla(None)
os.environ.pop("DESKHAND_ANAHTARLIK")
try:
    AD._ayar_yaz("kasa")
    liste_koruma._anahtar_unut()
    kontrol("kasa: boş kasa + işaret yok + dosya yok → ilk kurulum", liste_koruma.ilk_kurulum())
    with open(liste_koruma.dosya("seviye"), "w") as f:
        f.write("firefox = izle\n")
    liste_koruma._anahtar_unut()
    kontrol("kasa: öğe yok + işaret yok ama seviye dosyası dolu → ilk kurulum DEĞİL (sorulur)",
            not liste_koruma.ilk_kurulum())
    os.unlink(liste_koruma.dosya("seviye"))
    # panel imzalar (kasada öğe + işaret oluşur)
    liste_koruma._anahtar_unut()
    kontrol("kasa: panel imzası kasaya yazılır", liste_koruma._isaret_yaz(liste_koruma.KAPSAM, "hepsi"))
    kontrol("kasa: imzalı öğe kasada", "panel-isaret" in AD.ornek("kasa").tum_adlar())
    liste_koruma._anahtar_unut()
    kontrol("kasa: imzalı değer okunur", liste_koruma.onayli_deger(liste_koruma.KAPSAM) == (True, "hepsi"))
    liste_koruma.panel_dur_sakla(True)
    liste_koruma._anahtar_unut()
    kontrol("kasa: kullanıcının DUR kaydı okunur", liste_koruma.panel_dur_ayrinti() == (True, None))
    # depo değişimi: kasa → cüzdan taşır; imza geçerli kalır
    AD.ornek("kasa").yaz("banka", b"parola-1")
    sonuc = AD.depo_degistir("cuzdan")
    kontrol("depo_degistir: iç + kullanıcı öğeleri taşınır",
            {"panel-isaret", "banka"} <= set(sonuc["tasinan"]) and AD.secili_tur() == "cuzdan", sonuc)
    kontrol("depo_degistir: imzalı değer yeni depoda geçerli",
            liste_koruma.onayli_deger(liste_koruma.KAPSAM) == (True, "hepsi") and
            liste_koruma.isaret_dogrula(liste_koruma.KAPSAM)[0] == "gecerli")
    kontrol("depo_degistir: DUR kaydı taşınır", liste_koruma.panel_dur_ayrinti() == (True, None))
    # eski depo okunamıyor → hiçbir şey değişmez
    cuzdan.kilitli = True
    try:
        AD.depo_degistir("kasa")
        kontrol("depo_degistir: eski depo kilitli → DepoHatasi", False)
    except AD.DepoHatasi:
        kontrol("depo_degistir: eski depo kilitli → DepoHatasi, ayar değişmez", AD.secili_tur() == "cuzdan")
    liste_koruma._anahtar_unut()
    kontrol("cüzdan kilitli → imzalı durum yok, ilk kurulum DEĞİL", not liste_koruma.ilk_kurulum())
    kontrol("cüzdan kilitli → DUR kapalı-başarısız",
            liste_koruma.panel_dur_ayrinti() == (None, liste_koruma.DUR_NEDEN_OKUNAMADI))
    cuzdan.kilitli = False
    # ayar elle kasa'ya çevrildi (taşıma yok): kasada öğe var ama ... önce kasa öğesini sil (dosya silindi)
    AD.ornek("kasa").sil("panel-isaret")
    AD._ayar_yaz("kasa")
    liste_koruma._anahtar_unut()
    kontrol("kasa dosyası silindi + işaret var → ilk kurulum DEĞİL", not liste_koruma.ilk_kurulum())
    kontrol("kasa dosyası silindi + işaret var → onaylı değer yok (gevşetme sorulur)",
            liste_koruma.onayli_deger(liste_koruma.KAPSAM) == (False, None))
    kontrol("kasa dosyası silindi + işaret var → kullanıcının DUR'u kapalı-başarısız (kalkmaz)",
            liste_koruma.panel_dur_ayrinti() == (None, liste_koruma.DUR_NEDEN_OKUNAMADI))
    cuzdan.d.pop("panel-isaret")
    AD._ayar_yaz("cuzdan")
    liste_koruma._anahtar_unut()
    kontrol("ayar elle cüzdana çevrildi (cüzdanda öğe yok) + işaret var → DUR kapalı-başarısız",
            liste_koruma.panel_dur_ayrinti() == (None, liste_koruma.DUR_NEDEN_OKUNAMADI) and
            not liste_koruma.ilk_kurulum())
    # bozuk mühür: kapalı-başarısız, öğe yok sayılmaz
    AD._ayar_yaz("kasa")
    AD.ornek("kasa").yaz("panel-isaret", b"x")
    os.environ["SAHTE_CREDS_KIP"] = "bozuk"
    AD.ornek_ayarla("kasa", None)
    liste_koruma._anahtar_unut()
    kontrol("bozuk mühür → imzalı durum yok, ilk kurulum DEĞİL, neden görünür",
            not liste_koruma.ilk_kurulum() and "mühür bozuk" in (liste_koruma.kasa_nedeni() or ""),
            liste_koruma.kasa_nedeni())
    os.environ["SAHTE_CREDS_KIP"] = "tamam"
finally:
    os.environ["DESKHAND_ANAHTARLIK"] = "kapali"
    AD.ornek_ayarla("cuzdan", None)
    AD.ornek_ayarla("kasa", None)
    liste_koruma.isaret_anahtarlik_ayarla(None)

# ---------------------------------------------------------------- 6. kasa kipinde Secret Service HİÇ çağrılmaz (odak 1)
ALT = os.path.join(_yalitim.GECICI, "alt")
alt_ortam = {k: v for k, v in os.environ.items() if k != "DESKHAND_ANAHTARLIK"}
for ad_ in ("CONFIG", "STATE", "DATA", "CACHE", "RUNTIME"):
    alt_ortam[f"DESKHAND_{ad_}_DIR"] = os.path.join(ALT, ad_.lower())
PROBE = r"""
import sys
class Engel:
    def find_spec(self, ad, yol=None, hedef=None):
        if ad.split(".")[0] in ("secretstorage", "jeepney"):
            raise ImportError("YASAK: " + ad)
        return None
sys.meta_path.insert(0, Engel())
from deskhand import anahtar_deposu, doktor, liste_koruma
from deskhand.oturum import kalici
print("tur", anahtar_deposu.secili_tur())
liste_koruma._durum(True)
liste_koruma.panel_dur_ayrinti()
liste_koruma.ilk_kurulum()
liste_koruma._kasa_nesnesi().servis_yok_kesin()
k = kalici._anahtar(True)
print("anahtar", len(k or b""))
doktor.satir_anahtar_deposu(); doktor.satir_kalici_oturum()
print("moduller", [m for m in sys.modules if m.split(".")[0] in ("secretstorage", "jeepney")])
"""
r = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=60, env=alt_ortam,
                   cwd=_yalitim.KOK)
kontrol("kasa kipi: panel/kalıcı oturum/doctor açılışı secretstorage/jeepney yüklemez",
        r.returncode == 0 and "tur kasa" in r.stdout and "anahtar 32" in r.stdout and "moduller []" in r.stdout
        and "YASAK" not in r.stdout + r.stderr, (r.stdout + r.stderr)[-800:])

# ---------------------------------------------------------------- 7. CLI secret + type --secret-ref
cli_ortam = dict(alt_ortam)
for ad_ in ("CONFIG", "STATE", "DATA", "CACHE", "RUNTIME"):
    cli_ortam[f"DESKHAND_{ad_}_DIR"] = os.path.join(_yalitim.GECICI, "cli", ad_.lower())


def dh(*arg, girdi=None):
    return subprocess.run([sys.executable, "-m", "deskhand", *arg], input=girdi, capture_output=True, text=True,
                          timeout=60, env=cli_ortam, cwd=_yalitim.KOK)


r = dh("secret", "set", "banka", girdi="Cok-Gizli-9\n")
kontrol("CLI secret set: stdin'den kaydeder", r.returncode == 0 and "banka" in r.stdout, r.stdout + r.stderr)
kontrol("CLI secret set: değer çıktıda yok", "Cok-Gizli-9" not in r.stdout + r.stderr)
r = dh("secret", "list")
kontrol("CLI secret list: yalnız ad", r.stdout.split() == ["banka"], r.stdout + r.stderr)
r = dh("secret", "set", "panel-isaret", girdi="x")
kontrol("CLI secret set: iç ad reddedilir", r.returncode == 1)
r = dh("secret", "status", "--json")
kontrol("CLI secret status --json", r.returncode == 0 and json.loads(r.stdout)["tur"] == "kasa", r.stdout + r.stderr)
r = dh("secret", "rm", "banka")
kontrol("CLI secret rm", r.returncode == 0 and dh("secret", "list").stdout.strip() == "")
kontrol("CLI: değer hiçbir systemd-creds argv'sinde yok", "Cok-Gizli-9" not in argv_metni())

# type --secret-ref (girdi katmanı sahte: k_yaz yakalanır)
yakalanan = {}
eski_k_yaz = cli.k_yaz
cli.k_yaz = lambda a: yakalanan.update(metin=a.metin, gizli=a.gizli)
from deskhand import eylem  # noqa: E402
eski_parola = eylem._parola_alani_mi
os.environ.pop("DESKHAND_ANAHTARLIK")
try:
    AD.ornek_ayarla("kasa", None)
    AD._ayar_yaz("kasa")
    AD.ornek("kasa").yaz("site", b"P@rola!")
    ns = cli.ayristirici().parse_args(["type", "pencere-1", "--secret-ref", "site"])
    eylem._parola_alani_mi = lambda k: False
    try:
        ns.f(ns)
        kontrol("type --secret-ref: parola alanı değilse reddedilir (10)", False)
    except Dur as e:
        kontrol("type --secret-ref: parola alanı değilse reddedilir (10), değer iletide yok",
                e.kod == 10 and "P@rola" not in e.mesaj and not yakalanan)
    eylem._parola_alani_mi = lambda k: None
    try:
        ns.f(ns)
        kontrol("type --secret-ref: alan türü bilinmiyorsa reddedilir", False)
    except Dur as e:
        kontrol("type --secret-ref: alan türü bilinmiyorsa reddedilir", e.kod == 10 and not yakalanan)
    eylem._parola_alani_mi = lambda k: True
    ns.f(ns)
    kontrol("type --secret-ref: parola alanına depodaki değer gizli yazılır",
            yakalanan == {"metin": "P@rola!", "gizli": True} and ns.metin is None, yakalanan)
    ns2 = cli.ayristirici().parse_args(["type", "pencere-1", "metin", "--secret-ref", "site"])
    try:
        ns2.f(ns2)
        kontrol("type: metin + --secret-ref birlikte reddedilir", False)
    except Dur as e:
        kontrol("type: metin + --secret-ref birlikte reddedilir", e.kod == 1)
    ns3 = cli.ayristirici().parse_args(["type", "pencere-1", "--secret-ref", "yok-boyle"])
    try:
        ns3.f(ns3)
        kontrol("type --secret-ref: kayıtsız ad → Dur 1", False)
    except Dur as e:
        kontrol("type --secret-ref: kayıtsız ad → Dur 1", e.kod == 1)
    ns4 = cli.ayristirici().parse_args(["type", "pencere-1"])
    try:
        ns4.f(ns4)
        kontrol("type: ne metin ne --secret-ref → Dur 1", False)
    except Dur as e:
        kontrol("type: ne metin ne --secret-ref → Dur 1", e.kod == 1)
    yakalanan.clear()
    ns5 = cli.ayristirici().parse_args(["type", "pencere-1", "merhaba"])
    ns5.f(ns5)
    kontrol("type: düz metin eskisi gibi", yakalanan.get("metin") == "merhaba")
finally:
    os.environ["DESKHAND_ANAHTARLIK"] = "kapali"
    cli.k_yaz = eski_k_yaz
    eylem._parola_alani_mi = eski_parola
    AD.ornek_ayarla("kasa", None)

# MCP type_text: secret_ref parametresi var, text ile birlikte reddedilir (masaüstüne dokunmadan)
import inspect  # noqa: E402
from deskhand import mcp_sunucu  # noqa: E402
fn = getattr(mcp_sunucu.type_text, "__wrapped__", mcp_sunucu.type_text)
kontrol("MCP type_text: secret_ref parametresi", "secret_ref" in inspect.signature(fn).parameters)
try:
    fn(text="x", window="w", secret_ref="site")
    kontrol("MCP type_text: text + secret_ref reddedilir", False)
except Exception as e:  # noqa: BLE001 - ToolError
    kontrol("MCP type_text: text + secret_ref reddedilir", "[1]" in str(e), str(e))

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
