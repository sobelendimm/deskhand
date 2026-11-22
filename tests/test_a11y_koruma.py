"""Erişilebilirlik (a11y) soketi koruması (denetim 6 ORTA-1) + deskhand-eis kayıt denetimi (K3). Süreç/oturum açmaz:
geçici dizinde kendi soketimizle çalışır; kullanıcının gerçek oturumuna dokunmaz.

1) arka_ortak.a11y_soket_denetle: geçerli soket geçer; sembolik bağ, düz dosya, dizin dışı adres, çoklu adres,
   'gerçek soketin sert bağı' (kimlik kümesi), başka PID ad alanındaki (bwrap) sahte soket, yanlış kafes → Dur(14)
2) uygulama_baglari: iki türde a11y dizini SALT OKUNUR bağ (bwrap içinden bağ koyulamaz, soket'e connect çalışır)
3) kwin_oturum.Eis: kayıtta dbus PID'i yoksa Dur(14), süreç başlatılmaz"""
import os
import socket
import subprocess
import sys
import threading

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from deskhand import arka_ortak as ao, kwin_oturum as ko, masaustu
from deskhand.hata import Dur

GECICI = _yalitim.GECICI
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def dur14(f, *a):
    try:
        f(*a)
    except Dur as e:
        return e.kod if hasattr(e, "kod") else getattr(e, "code", None)
    return None


def soket_ac(dizin, ad):
    """dizin/ad soketi (yol uzunluk sınırı için dizine geçerek bağlanır) → dinleyen soket (kabul döngüsü arka planda)."""
    onceki = os.getcwd()
    os.chdir(dizin)
    try:
        s = socket.socket(socket.AF_UNIX)
        s.bind(ad)
        s.listen(8)
    finally:
        os.chdir(onceki)
    threading.Thread(target=lambda: [s.accept() for _ in range(64)], daemon=True).start()
    return s


kok = os.path.realpath(os.path.join(GECICI, "a11y"))
dizin = os.path.join(kok, "at-spi")
os.makedirs(dizin, mode=0o700)
os.makedirs(os.path.join(kok, "baska"), mode=0o700)
yol = os.path.join(dizin, "bus_0")
srv = soket_ac(dizin, "bus_0")
adres = f"unix:path={yol},guid={'a' * 32}"

# ---- 1) denetim
kontrol("geçerli soket (kendi sürecimiz, aynı PID ad alanı) geçer", ao.a11y_soket_denetle(adres, dizin) == yol)
kontrol("yolu guid'siz da geçer", ao.a11y_soket_denetle(f"unix:path={yol}", dizin) == yol)

baska = soket_ac(os.path.join(kok, "baska"), "bus_0")
bg = os.path.join(dizin, "bus_1")
os.symlink(os.path.join(kok, "baska", "bus_0"), bg)
kontrol("sembolik bağ (gerçek yola yönlendirme) → Dur(14), connect denenmez",
        dur14(ao.a11y_soket_denetle, f"unix:path={bg}", dizin) == 14)
os.remove(bg)

dz = os.path.join(dizin, "bus_2")
open(dz, "w").close()
kontrol("düz dosya → Dur(14)", dur14(ao.a11y_soket_denetle, f"unix:path={dz}", dizin) == 14)
os.remove(dz)
kontrol("dizin dışı soket adresi → Dur(14)",
        dur14(ao.a11y_soket_denetle, f"unix:path={kok}/baska/bus_0", dizin) == 14)
kontrol("çoklu adres (`;`) → Dur(14)", dur14(ao.a11y_soket_denetle, f"unix:path={yol};unix:path=/run/x/bus", dizin) == 14)
kontrol("beklenmeyen ad (bus_x) → Dur(14)", dur14(ao.a11y_soket_denetle, f"unix:path={dizin}/baska_ad", dizin) == 14)
kontrol("dizin sembolik bağ → Dur(14)", (lambda: (os.symlink(dizin, os.path.join(kok, "at-bag")),
                                                  dur14(ao.a11y_soket_denetle, f"unix:path={kok}/at-bag/bus_0",
                                                        os.path.join(kok, "at-bag")))[1] == 14)())

asil = ao.gercek_soket_kimlikleri
st = os.stat(yol)
ao.gercek_soket_kimlikleri = lambda: {(st.st_dev, st.st_ino)}
kontrol("(st_dev, st_ino) gerçek soketlerden biri (sert bağ) → Dur(14)", dur14(ao.a11y_soket_denetle, adres, dizin) == 14)
ao.gercek_soket_kimlikleri = asil

kontrol("kafes (cgroup) uyuşmuyorsa → Dur(14)", dur14(ao.a11y_soket_denetle, adres, dizin, "/yok/baska.scope") == 14)
kontrol("kafes (cgroup) uyuşuyorsa geçer", ao.a11y_soket_denetle(adres, dizin, ao._cgroup(os.getpid())) == yol)

# bwrap içindeki uygulamanın kendi açtığı sahte soket: başka PID ad alanı → reddedilir
if ao.bwrap_var():
    kok2 = os.path.realpath(os.path.join(GECICI, "a11y2"))
    dizin2 = os.path.join(kok2, "at-spi")
    os.makedirs(dizin2, mode=0o700)
    sunucu = ("import os,socket,sys;os.chdir(sys.argv[1]);s=socket.socket(socket.AF_UNIX);s.bind('bus_0');s.listen(4);"
              "print('hazir',flush=True);[s.accept() for _ in range(8)]")
    argv = ao.korumali_argv([sys.executable, "-c", sunucu, dizin2], os.path.join(kok2, "rt"), [(dizin2, False)])
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={"PATH": ao.GUVENLI_PATH},
                         text=True)
    try:
        hazir = p.stdout.readline().strip() == "hazir"
        kontrol("(ölçüm) bwrap içinde sahte soket açıldı", hazir)
        kontrol("bwrap içindeki (başka PID ad alanı) sahte soket → Dur(14)",
                hazir and dur14(ao.a11y_soket_denetle, f"unix:path={dizin2}/bus_0", dizin2) == 14)
    finally:
        p.kill()
        p.wait()

    # ---- 2) uygulama_baglari: a11y dizini salt okunur; bwrap içinden bağ/dosya konamaz, connect çalışır
    for tur, g in (("kwin", {"tur": "kwin", "calisma": kok, "wayland_yol": os.path.join(kok, "wl"), "x_ana": None}),
                   ("xvfb", {"tur": "xvfb", "calisma": kok, "no": 77})):
        ro = {y: r for y, r in (ko.uygulama_baglari(g) if tur == "kwin" else masaustu.uygulama_baglari(g))}
        hedef = dizin if tur == "kwin" else os.path.join(kok, "run", "at-spi")
        kontrol(f"{tur}: a11y dizini uygulamaya SALT OKUNUR bağlanır", ro.get(hedef) is True, str(ro))
    # xvfb düzeni: <çalışma>/run yazılabilir + <çalışma>/run/at-spi salt okunur (bwrap'te ölç)
    kok3 = os.path.realpath(os.path.join(GECICI, "a11y3"))
    rt3 = os.path.join(kok3, "run")
    os.makedirs(os.path.join(rt3, "at-spi"), mode=0o700)
    soket_ac(os.path.join(rt3, "at-spi"), "bus_0")
    betik = (f"cd {rt3}/at-spi && python3 -c \"import socket;s=socket.socket(socket.AF_UNIX);s.connect('bus_0');"
             f"print('BAGLANDI')\"; ln -s /run/user/{os.getuid()}/at-spi/bus_0 {rt3}/at-spi/bus_9 2>&1 | head -1; "
             f"rm -f {rt3}/at-spi/bus_0 2>&1 | head -1; touch {rt3}/serbest && echo RUN_YAZILABILIR")
    argv = ao.korumali_argv(["/bin/sh", "-c", betik], os.path.join(kok3, "rt"),
                            [(rt3, False), (os.path.join(rt3, "at-spi"), True)])
    r = subprocess.run(argv, capture_output=True, text=True, env={"PATH": ao.GUVENLI_PATH})
    kontrol("salt okunur at-spi bağında soketa connect ÇALIŞIR (ölçüm)", "BAGLANDI" in r.stdout, r.stdout + r.stderr)
    kontrol("salt okunur at-spi bağında sembolik bağ/silme olmaz", not os.path.lexists(os.path.join(rt3, "at-spi", "bus_9"))
            and os.path.exists(os.path.join(rt3, "at-spi", "bus_0")), r.stdout + r.stderr)
    kontrol("runtime'ın geri kalanı yazılabilir kaldı", "RUN_YAZILABILIR" in r.stdout, r.stdout + r.stderr)
else:
    print("ATLANDI: bwrap yok (bwrap'li bölümler)")

# ---- 3) K3: kayıtta dbus PID'i yoksa deskhand-eis başlatılmaz
asil_gk = ko.guvenli_kayit
ko.guvenli_kayit = lambda d: d
asil_pop = subprocess.Popen
basladi = []
subprocess.Popen = lambda *a, **k: basladi.append(a) or asil_pop(*a, **k)
try:
    from deskhand import yollar
    asil_eis = yollar.eis_bin
    yollar.eis_bin = lambda: sys.executable  # var say; başlatılmamalı
    kod = dur14(ko.Eis, {"calisma": kok, "dbus_adres": f"unix:path={kok}/bus", "pid": {}})
    kontrol("Eis: kayıtta dbus PID'i yok → Dur(14), süreç başlatılmadı", kod == 14 and not basladi, f"{kod} {basladi}")
    kod = dur14(ko.Eis, {"calisma": kok, "dbus_adres": f"unix:path={kok}/bus"})
    kontrol("Eis: kayıtta pid bölümü hiç yok → Dur(14)", kod == 14 and not basladi, f"{kod} {basladi}")
finally:
    subprocess.Popen = asil_pop
    ko.guvenli_kayit = asil_gk
    yollar.eis_bin = asil_eis

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
