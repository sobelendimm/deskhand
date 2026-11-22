"""Tanı ve kurulum tutarlılığı (ekransız):
 1. Eski MCP sunucusu: diskteki deskhand/__init__.py sürümü ≠ çalışan __version__ → get_status "stale_server" alanı;
    doctor çalışan `deskhand mcp` süreçlerini listeler (yalnız bu kullanıcının; güncellemeden önce başlamış = eski).
 2. Günlük/önbellek izinleri: günlük 0600, STATE_DIR / CACHE_DIR 0700; eski gevşek izinler açılışta düzelir.
 3. server.json sürümü == paket __version__.

Çalıştır:  python3 tests/test_tani_surum.py"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import time

import _yalitim  # noqa: F401

from deskhand import __version__, doktor, gunluk, mcp_sunucu, surum, yollar

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


# ======================================================================= 1) eski sunucu
kontrol("kurulu_surum diskten okunur == __version__", surum.kurulu_surum() == __version__)
kontrol("eski_sunucu: aynı sürüm → None", surum.eski_sunucu(__version__) is None)
st = mcp_sunucu.get_status(desktop="foreground")
kontrol("get_status: güncel sunucuda stale_server yok", "stale_server" not in st and st["version"] == __version__)
eski_v = mcp_sunucu.__version__
mcp_sunucu.__version__ = "0.7.1"  # bellekte eski kod çalışıyormuş gibi
try:
    st = mcp_sunucu.get_status(desktop="foreground")
finally:
    mcp_sunucu.__version__ = eski_v
ss = st.get("stale_server") or {}
kontrol("get_status: sürüm yamalanınca stale_server {running, installed} + /mcp notu",
        ss.get("running") == "0.7.1" and ss.get("installed") == __version__ and "/mcp" in ss.get("note", ""), st)

with tempfile.TemporaryDirectory() as td:  # okunamayan / sürümsüz paket → None (yanlış alarm yok)
    kontrol("kurulu_surum: __init__.py yok → None", surum.kurulu_surum(td) is None)
    kontrol("eski_sunucu: kurulu okunamadı → None", surum.eski_sunucu("0.1", kurulu="") is None)

kontrol("_mcp_argv: `python3 /x/bin/deskhand mcp --desktop background` eşleşir",
        surum._mcp_argv(["/usr/bin/python3", "/x/bin/deskhand", "mcp", "--desktop", "background"]) ==
        ["mcp", "--desktop", "background"])
kontrol("_mcp_argv: `python3 -m deskhand mcp` eşleşir", surum._mcp_argv(["python3", "-m", "deskhand", "mcp"]) == ["mcp"])
kontrol("_mcp_argv: başka alt komut / benzer ad eşleşmez",
        surum._mcp_argv(["python3", "/x/bin/deskhand", "panel"]) is None and
        surum._mcp_argv(["gio", "launch", "/tmp/deskhand-mcp-ana.desktop"]) is None)

# Sahte bir `deskhand mcp` süreci: sahte paket (sürüm 9.9.9) + bin/deskhand; süreç başladıktan SONRA paket güncellenir
with tempfile.TemporaryDirectory() as td:
    paket = os.path.join(td, "deskhand")
    os.makedirs(paket)
    os.makedirs(os.path.join(td, "bin"))
    with open(os.path.join(paket, "__init__.py"), "w") as f:
        f.write('__version__ = "9.9.9"\n')
    os.utime(os.path.join(paket, "__init__.py"), (time.time() - 3600, time.time() - 3600))
    betik = os.path.join(td, "bin", "deskhand")
    with open(betik, "w") as f:
        f.write("import time\ntime.sleep(30)\n")
    p = subprocess.Popen([sys.executable, betik, "mcp", "--desktop", "background"])
    try:
        bulundu = []
        son = time.monotonic() + 5
        while time.monotonic() < son and not bulundu:
            bulundu = [s for s in surum.mcp_surecleri() if s["pid"] == p.pid]
            time.sleep(0.05)
        s = bulundu[0] if bulundu else {}
        kontrol("mcp_surecleri: sahte süreç bulundu, paketi + sürümü (güncel)",
                s.get("package") == paket and s.get("version") == "9.9.9" and not s.get("stale") and
                s.get("args") == "mcp --desktop background", s)
        with open(os.path.join(paket, "__init__.py"), "w") as f:  # güncelleme: süreç eski kodu çalıştırıyor
            f.write('__version__ = "10.0.0"\n')
        s = next((x for x in surum.mcp_surecleri() if x["pid"] == p.pid), {})
        kontrol("mcp_surecleri: süreç güncellemeden önce başlamış → stale, sürüm bilinmiyor",
                s.get("stale") is True and s.get("version") is None and s.get("installed") == "10.0.0", s)
        kontrol("mcp_surecleri: başka kullanıcının süreçlerine bakılmaz (uid süzgeci)",
                all(x["pid"] != p.pid for x in surum.mcp_surecleri(uid=os.getuid() + 12345)))
        satir = doktor.satir_mcp_surecleri()
        kontrol("doctor satırı: pid + eski kod uyarısı + /mcp önerisi",
                f"pid {p.pid}" in satir["ayrinti"] and satir["durum"] == "uyari" and "/mcp" in satir["oneri"], satir)
    finally:
        p.kill()
        p.wait()

# ======================================================================= 2) izinler
sd, cd = yollar.state_dir(), yollar.cache_dir()
os.makedirs(sd, mode=0o755, exist_ok=True)
os.chmod(sd, 0o755)
os.makedirs(cd, mode=0o755, exist_ok=True)
os.chmod(cd, 0o755)
eski_gunluk = os.path.join(sd, "gunluk-20000101.log")
with open(eski_gunluk, "w") as f:
    f.write("eski\n")
os.chmod(eski_gunluk, 0o644)
os.utime(eski_gunluk, None)
gunluk._IZIN_TAMAM = False
gunluk.gunluk("izin denemesi")
bugun = os.path.join(yollar.gunluk_dizin(), time.strftime("gunluk-%Y%m%d.log"))


def kip(y):
    return stat.S_IMODE(os.stat(y).st_mode)


kontrol("günlük dosyası 0600", kip(bugun) == 0o600, oct(kip(bugun)))
kontrol("STATE_DIR 0700 (0755'ten düzeltildi)", kip(sd) == 0o700, oct(kip(sd)))
kontrol("CACHE_DIR 0700 (0755'ten düzeltildi)", kip(cd) == 0o700, oct(kip(cd)))
kontrol("mevcut eski günlük 0644 → 0600", kip(eski_gunluk) == 0o600, oct(kip(eski_gunluk)))
os.chmod(cd, 0o755)
gunluk.temizle()
kontrol("açılış temizliği (temizle) CACHE_DIR iznini yine düzeltir", kip(cd) == 0o700)
import shutil  # noqa: E402
shutil.rmtree(cd)
gunluk.izinleri_duzelt()
kontrol("CACHE_DIR yoksa 0700 oluşturulur", kip(cd) == 0o700)

# ======================================================================= 3) server.json
with open(os.path.join(_yalitim.KOK, "server.json")) as f:
    sj = json.load(f)
kontrol("server.json version == __version__", sj["version"] == __version__, sj["version"])
kontrol("server.json packages[].version + indirme adresi == __version__",
        all(p["version"] == __version__ and f"/v{__version__}/" in p["identifier"] for p in sj["packages"]))

print(f"\n{gecen}/{toplam} test geçti")
sys.exit(0 if gecen == toplam else 1)
