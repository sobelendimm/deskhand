"""Girişte KDE Cüzdanı'nı açma (deskhand/cuzdan_ac.py) testleri. Gerçek cüzdan, gerçek ksecretd, gerçek TPM ve gerçek
systemctl KULLANILMAZ: PATH'in başında sahte systemd-creds / busctl / ksecretd / systemctl; tuz dosyası geçici
XDG_DATA_HOME'da; birim dosyası geçici XDG_CONFIG_HOME'da.

Çalıştır:  python3 tests/test_cuzdan_ac.py"""
import hashlib
import os
import stat
import sys
import tempfile

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import anahtar_deposu as AD
from deskhand import cuzdan_ac as CA

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


S = tempfile.mkdtemp(prefix="sahte-cuzdan-", dir=_yalitim.GECICI)
DURUM = os.path.join(S, "durum")      # "sahip=0|1 kilit=0|1"
ARGV = os.path.join(S, "argv.log")
ALINAN = os.path.join(S, "alinan")    # sahte ksecretd: aldığı anahtar (hex) + ortam
PY = sys.executable


def betik(ad, govde):
    yol = os.path.join(S, ad)
    with open(yol, "w") as f:
        f.write(f"#!{PY}\nimport os, sys\nARGV={ARGV!r}\nDURUM={DURUM!r}\nALINAN={ALINAN!r}\n"
                f"open(ARGV, 'a').write({ad!r} + ' ' + ' '.join(sys.argv[1:]) + '\\n')\n" + govde)
    os.chmod(yol, 0o755)


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
if "--auto-start=no" not in a: sys.exit(9)
if "NameHasOwner" in a: print("b true" if d["sahip"] == "1" else "b false"); sys.exit(0)
if "get-property" in a:
    if d["sahip"] != "1": sys.exit(1)
    print("b true" if d["kilit"] == "1" else "b false"); sys.exit(0)
sys.exit(2)
""")
betik("ksecretd", """
import socket
a = sys.argv[1:]
assert a[0] == "--pam-login"
boru, soket = int(a[1]), int(a[2])
k = b""
while len(k) < 56:
    p = os.read(boru, 56 - len(k))
    if not p: break
    k += p
s = socket.socket(fileno=soket)
c, _ = s.accept()
ortam = b""
while True:
    p = c.recv(65536)
    if not p: break
    ortam += p
open(ALINAN, "w").write(k.hex() + "\\n" + ortam.decode())
ok = k.hex() == os.environ.get("SAHTE_BEKLENEN", "")
open(DURUM, "w").write("sahip=1 kilit=" + ("0" if ok else "1"))
""")
betik("systemctl", "sys.exit(0)\n")
os.environ["PATH"] = S + os.pathsep + os.environ.get("PATH", "")
os.environ["XDG_DATA_HOME"] = os.path.join(S, "data")
os.environ["XDG_CONFIG_HOME"] = os.path.join(S, "config")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(S, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.environ.pop("DESKHAND_ANAHTARLIK")
CA._BEKLE_SN = 3.0


def durum_yaz(sahip, kilit):
    with open(DURUM, "w") as f:
        f.write(f"sahip={sahip} kilit={kilit}")


def argv_satirlari(arac):
    try:
        return [s for s in open(ARGV).read().splitlines() if s.startswith(arac + " ")]
    except FileNotFoundError:
        return []


PAROLA = "Cuzdan-Parolasi-42"
durum_yaz(0, 1)

# 1. tuz yok → kurulum reddedilir
try:
    CA.cuzdan_otomatik_kur(PAROLA)
    kontrol("tuz yok → CuzdanHatasi", False)
except CA.CuzdanHatasi as e:
    kontrol("tuz yok → CuzdanHatasi (parola iletide yok)", PAROLA not in e.neden, e.neden)

tuz = os.urandom(56)
os.makedirs(os.path.join(os.environ["XDG_DATA_HOME"], "kwalletd"))
with open(CA.tuz_yolu(), "wb") as f:
    f.write(tuz)
beklenen = hashlib.pbkdf2_hmac("sha512", PAROLA.encode(), tuz, 50000, 56)
os.environ["SAHTE_BEKLENEN"] = beklenen.hex()

# 2. kurulum: yalnız KARMA mühürlenir, birim etkinleşir
CA.cuzdan_otomatik_kur(PAROLA)
kasa = AD.ornek("kasa")
kontrol("kurulum: kasada karma (56 bayt, PBKDF2-SHA512 50000 tur)", kasa.oku(CA.AD) == beklenen)
cred = os.path.join(AD.KasaDepo().dizin, "kde-cuzdan.cred")
kontrol("kurulum: kasa öğesi 0600", stat.S_IMODE(os.stat(cred).st_mode) == 0o600)
kontrol("kurulum: kde-cuzdan kullanıcı listesinde görünmez", CA.AD not in kasa.listele())
kontrol("kurulum: birim yazıldı", os.path.exists(CA.birim_yolu()) and "wallet open" in open(CA.birim_yolu()).read())
kontrol("kurulum: systemctl --user enable", any("--user enable " + CA.BIRIM in s for s in argv_satirlari("systemctl")))
hepsi = open(ARGV).read()
kontrol("kurulum: parola ve karma hiçbir argv'de yok", PAROLA not in hepsi and beklenen.hex() not in hepsi)
d = CA.durum()
kontrol("durum: kurulu, servis yok → acik None", d == {"kurulu": True, "acik": None, "neden": None}, d)

# 3. servis yok → ksecretd --pam-login ile açılır
n0 = len(argv_satirlari("ksecretd"))
kontrol("cuzdan_ac: doğru anahtar → 0", CA.cuzdan_ac() == 0)
alinan = open(ALINAN).read().splitlines()
kontrol("cuzdan_ac: ksecretd anahtarı borudan aldı", alinan[0] == beklenen.hex())
kontrol("cuzdan_ac: ortam soketten gönderildi", any(s.startswith("XDG_RUNTIME_DIR=") for s in alinan[1:]))
kontrol("cuzdan_ac: tek ksecretd başlatıldı, argv'de anahtar yok",
        len(argv_satirlari("ksecretd")) - n0 == 1 and beklenen.hex() not in open(ARGV).read())
kontrol("cuzdan_ac: soket dosyası kalmadı", not [a for a in os.listdir(os.environ["XDG_RUNTIME_DIR"])
                                                  if a.startswith("deskhand-kwallet")])
kontrol("durum: açık", CA.durum()["acik"] is True)
kontrol("busctl her çağrıda --auto-start=no", all("--auto-start=no" in s for s in argv_satirlari("busctl")))

# 4. zaten açık → hiçbir şey başlatılmaz
n0 = len(argv_satirlari("ksecretd"))
kontrol("zaten açık → 0, ksecretd başlatılmaz", CA.cuzdan_ac() == 0 and len(argv_satirlari("ksecretd")) == n0)

# 5. başka biri başlatmış ve kilitli → 1, yeniden başlatma yok
durum_yaz(1, 1)
kontrol("kilitli + çalışıyor → 1, ksecretd başlatılmaz", CA.cuzdan_ac() == 1 and len(argv_satirlari("ksecretd")) == n0)
d = CA.durum()
kontrol("durum: kilitli → acik False + neden", d["acik"] is False and d["neden"], d)

# 6. yanlış anahtar → tek deneme, 1
durum_yaz(0, 1)
os.environ["SAHTE_BEKLENEN"] = "00" * 56
kontrol("yanlış anahtar → 1", CA.cuzdan_ac() == 1)
kontrol("yanlış anahtar → yalnız BİR ksecretd (döngü yok)", len(argv_satirlari("ksecretd")) - n0 == 1)

# 7. kasa okunamıyor → 1, ksecretd yok
durum_yaz(0, 1)
n0 = len(argv_satirlari("ksecretd"))
os.environ["DESKHAND_ANAHTARLIK"] = "kapali"
kontrol("kasa okunamıyor → 1, ksecretd başlatılmaz", CA.cuzdan_ac() == 1 and len(argv_satirlari("ksecretd")) == n0)
os.environ.pop("DESKHAND_ANAHTARLIK")

# 8. kaldır
CA.kaldir()
kontrol("kaldır: birim ve anahtar silindi", not os.path.exists(CA.birim_yolu()) and kasa.oku(CA.AD) is None)
kontrol("kaldır: systemctl disable", any("--user disable " + CA.BIRIM in s for s in argv_satirlari("systemctl")))
kontrol("kaldır sonrası durum", CA.durum()["kurulu"] is False)

os.environ["DESKHAND_ANAHTARLIK"] = "kapali"
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
