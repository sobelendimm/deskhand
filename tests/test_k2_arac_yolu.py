"""K2 bağımsız inceleme bulguları 1, 3, 4, 5 (anahtar deposu / girişte cüzdan açma) testleri.

1 (YÜKSEK): systemd-creds / busctl / ksecretd / systemctl PATH ile aranıyordu; PATH'in başı kullanıcının yazılabilir
  ~/.local/bin'i: oraya konan sahte systemd-creds her parolayı stdin'de, sahte ksecretd cüzdan anahtarını alıyordu (K2
  PoC). Burada PATH'in başına sahteler konur, test kancası BOŞ bırakılır: sahte HİÇ çağrılmamalı, her alt süreç
  /usr/bin ya da /bin'den, temiz ortamla (PATH=/usr/bin:/bin, LD_PRELOAD/PYTHONPATH yok) başlatılmalı.
  Hiçbir gerçek araç ÇALIŞTIRILMAZ: subprocess.run/Popen kaydedici ile değiştirilir.
3: XDG_RUNTIME_DIR yoksa /tmp'ye düşülmez, ret. 4: sokete oturum ortamının tamamı değil yalnız gerekenler.
5: birim ExecStart mutlak ve tırnaklı.

Çalıştır:  python3 tests/test_k2_arac_yolu.py"""
import os
import subprocess
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


# ---------------------------------------------------------------- saldırgan: PATH'in başında sahte araçlar
SALDIRGAN = tempfile.mkdtemp(prefix="k2-saldirgan-bin-", dir=_yalitim.GECICI)
IZ = os.path.join(SALDIRGAN, "yakalanan.txt")
SAHTELER = ("systemd-creds", "busctl", "ksecretd", "systemctl", "kcmshell6", "kwalletmanager6", "deskhand")
for ad in SAHTELER:
    yol = os.path.join(SALDIRGAN, ad)
    with open(yol, "w") as f:
        f.write(f"#!/bin/sh\necho \"{ad} $*\" >> {IZ}\ncat >> {IZ}\nexit 0\n")
    os.chmod(yol, 0o755)
os.environ["PATH"] = SALDIRGAN + os.pathsep + os.environ.get("PATH", "")
os.environ["LD_PRELOAD"] = "/nonexistent/k2-kotu.so"
os.environ["PYTHONPATH"] = "/nonexistent/k2-kotu"
os.environ["K2_GIZLI_DEGISKEN"] = "sizmamali"
os.environ.pop("DESKHAND_ANAHTARLIK", None)
getattr(AD, "SINAMA_ARACLARI", {}).clear()
AD.SINAMA_ORTAM_ADLARI = ()
AD._TPM = None

cagrilar: list[tuple[list, dict | None]] = []
gercek_run, gercek_popen = subprocess.run, subprocess.Popen


def sahte_run(argv, *a, **k):
    cagrilar.append((list(argv), k.get("env")))
    return subprocess.CompletedProcess(argv, 1, b"" if not k.get("text") else "", b"" if not k.get("text") else "")


class SahtePopen:
    def __init__(self, argv, *a, **k):
        cagrilar.append((list(argv), k.get("env")))


subprocess.run, subprocess.Popen = sahte_run, SahtePopen
try:
    AD.tpm_var()
    try:
        AD.KasaDepo().yaz("banka", b"COK-GIZLI-PAROLA")
    except AD.DepoHatasi:
        pass  # kaydedici returncode 1 verir: önemli olan hangi ikilinin çağrıldığı
    try:
        AD.KasaDepo().oku("banka")
    except AD.DepoHatasi:
        pass
    AD.KasaDepo().servis_yok_kesin()
    CA.servis_var()
    CA.kilitli()
    CA._systemctl("daemon-reload")
finally:
    subprocess.run, subprocess.Popen = gercek_run, gercek_popen

kontrol("K2-1: en az bir alt süreç denendi (test boş geçmiyor)", len(cagrilar) >= 4, cagrilar)
kontrol("K2-1: PATH'teki sahte araçların HİÇBİRİ çağrılmadı", not os.path.exists(IZ) and
        not any(c[0][0].startswith(SALDIRGAN) for c in cagrilar), [c[0][0] for c in cagrilar])
kontrol("K2-1: her alt süreç /usr/bin ya da /bin'den (mutlak, root'a ait)",
        all(c[0][0].startswith(("/usr/bin/", "/bin/")) for c in cagrilar), [c[0][0] for c in cagrilar])
kontrol("K2-1: her alt süreç TEMİZ ortamla (PATH=/usr/bin:/bin)",
        all(c[1] is not None and c[1].get("PATH") == "/usr/bin:/bin" for c in cagrilar))
kontrol("K2-1: LD_PRELOAD / PYTHONPATH / başka değişken alt sürece geçmez",
        all(not ({"LD_PRELOAD", "PYTHONPATH", "K2_GIZLI_DEGISKEN"} & set(c[1] or {})) for c in cagrilar))
kontrol("K2-1: değer hiçbir argv'de yok", not any("COK-GIZLI" in " ".join(c[0]) for c in cagrilar))
for ad in ("systemd-creds", "busctl", "ksecretd", "systemctl", "kcmshell6", "kwalletmanager6"):
    y = AD.yardimci_arac(ad, zorunlu=False)
    kontrol(f"K2-1: yardimci_arac({ad}) PATH'teki sahteyi seçmez", y is None or y.startswith(("/usr/bin/", "/bin/")), y)
try:
    AD.yardimci_arac("k2-boyle-arac-yok")
    kontrol("K2-1: zorunlu araç yok → DepoHatasi(yok_kesin)", False)
except AD.DepoHatasi as e:
    kontrol("K2-1: zorunlu araç yok → DepoHatasi(yok_kesin)", e.yok_kesin)
kontrol("K2-1: mutlak olmayan yol / ../ kaçışı reddedilir",
        AD.yardimci_arac("../bin/sh", zorunlu=False) is None)
y = CA._ksecretd() if AD.yardimci_arac("ksecretd", zorunlu=False) else None
kontrol("K2-1: ksecretd (cüzdan anahtarını alan) yalnız /usr/bin ya da /bin'den", y is None or
        y.startswith(("/usr/bin/", "/bin/")), y)
for kaynak in ("deskhand/anahtar_deposu.py", "deskhand/cuzdan_ac.py"):
    with open(os.path.join(_yalitim.KOK, kaynak)) as f:
        metin = f.read()
    kontrol(f"K2-1 sınıf taraması: {kaynak} içinde shutil.which / PATH araması yok", "shutil.which" not in metin)
o = AD.temiz_ortam()
kontrol("temiz_ortam: PATH güvenli, gizli değişken yok",
        o["PATH"] == "/usr/bin:/bin" and "K2_GIZLI_DEGISKEN" not in o and "LD_PRELOAD" not in o)

# ---------------------------------------------------------------- K2-3: XDG_RUNTIME_DIR yoksa ret (/tmp'ye düşülmez)
cagrilar.clear()
subprocess.Popen = SahtePopen
eski_rt = os.environ.pop("XDG_RUNTIME_DIR", None)
try:
    try:
        CA._baslat(b"k" * 56)
        kontrol("K2-3: XDG_RUNTIME_DIR yok → CuzdanHatasi", False)
    except CA.CuzdanHatasi:
        kontrol("K2-3: XDG_RUNTIME_DIR yok → CuzdanHatasi, ksecretd başlatılmaz", not cagrilar)
    gevsek = tempfile.mkdtemp(prefix="k2-rt-", dir=_yalitim.GECICI)
    os.chmod(gevsek, 0o755)
    os.environ["XDG_RUNTIME_DIR"] = gevsek
    try:
        CA._baslat(b"k" * 56)
        kontrol("K2-3: başkasının okuyabildiği çalışma dizini → ret", False)
    except CA.CuzdanHatasi:
        kontrol("K2-3: başkasının okuyabildiği çalışma dizini → ret", not cagrilar)
    os.environ["XDG_RUNTIME_DIR"] = "goreli/yol"
    try:
        CA._calisma_dizini()
        kontrol("K2-3: göreli XDG_RUNTIME_DIR → ret", False)
    except CA.CuzdanHatasi:
        kontrol("K2-3: göreli XDG_RUNTIME_DIR → ret", True)
    os.chmod(gevsek, 0o700)
    os.environ["XDG_RUNTIME_DIR"] = gevsek
    kontrol("K2-3: kendi 0700 dizini kabul", CA._calisma_dizini() == gevsek)
finally:
    subprocess.Popen = gercek_popen
    if eski_rt is not None:
        os.environ["XDG_RUNTIME_DIR"] = eski_rt

# ---------------------------------------------------------------- K2-4: sokete yalnız gerekenler
os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
os.environ["GITHUB_TOKEN"] = "ghp_k2sizmamali"
so = CA.soket_ortami()
kontrol("K2-4: soket ortamında D-Bus + XDG_RUNTIME_DIR var",
        "DBUS_SESSION_BUS_ADDRESS" in so and "XDG_RUNTIME_DIR" in so, sorted(so))
kontrol("K2-4: soket ortamında belirteç / LD_PRELOAD / PYTHONPATH / başka değişken yok",
        not ({"GITHUB_TOKEN", "LD_PRELOAD", "PYTHONPATH", "K2_GIZLI_DEGISKEN"} & set(so)), sorted(so))
kontrol("K2-4: soket ortamında PATH güvenli", so.get("PATH") == "/usr/bin:/bin")

# ---------------------------------------------------------------- K2-5: birim ExecStart mutlak + tırnaklı
m = CA.birim_metni()
exec_satiri = next(s for s in m.splitlines() if s.startswith("ExecStart="))
kontrol("K2-5: ExecStart mutlak yorumlayıcı, tırnaklı, PATH araması yok",
        exec_satiri.startswith('ExecStart="/') and exec_satiri.endswith('" -m deskhand wallet open') and
        SALDIRGAN not in m, exec_satiri)
kontrol("K2-5: paket dizini Environment=PYTHONPATH ile (tırnaklı)", 'Environment="PYTHONPATH=/' in m)
kontrol("K2-5: tırnaklama \\ \" % $ kaçışları",
        CA._birim_tirnak('a"b%c$d\\e') == '"a\\"b%%c$$d\\\\e"', CA._birim_tirnak('a"b%c$d\\e'))
try:
    CA._birim_tirnak("a\nExecStartPre=/tmp/kotu")
    kontrol("K2-5: yeni satır içeren yol reddedilir", False)
except CA.CuzdanHatasi:
    kontrol("K2-5: yeni satır içeren yol reddedilir", True)

os.environ["DESKHAND_ANAHTARLIK"] = "kapali"
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
