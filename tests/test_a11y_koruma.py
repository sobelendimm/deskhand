"""Erişilebilirlik (a11y) soketi koruması (denetim 6 ORTA-1) + deskhand-eis kayıt denetimi (K3). Süreç/oturum açmaz:
geçici dizinde kendi soketimizle çalışır; kullanıcının gerçek oturumuna dokunmaz.

1) arka_ortak.a11y_soket_denetle: geçerli soket geçer; sembolik bağ, düz dosya, dizin dışı adres, çoklu adres,
   'gerçek soketin sert bağı' (kimlik kümesi), başka PID ad alanındaki (bwrap) sahte soket, yanlış kafes → Dur(14)
2) uygulama_baglari: iki türde a11y dizini SALT OKUNUR bağ (bwrap içinden bağ koyulamaz, soket'e connect çalışır)
3) kwin_oturum.Eis: kayıtta dbus PID'i yoksa Dur(14), süreç başlatılmaz
4) fail-closed bağ (a11y_bagi) + açılışta Deskhand'in kendi yarattığı dizin + (st_dev, st_ino) kimliği
5) GERÇEK masaüstü regresyonu (iki tür): erişilebilirlik hazırlığı başarısız olsa da uygulama at-spi dizinini
   yaratamaz/yazamaz; dizin kaybolur/değişirse uygulama başlatılmaz"""
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
    # signal.alarm: p.kill() yalnız dış süreci öldürür, ad alanındaki sunucu sahipsiz kalırdı (sızıntı) → 20 sn'de kendini bitirir
    sunucu = ("import os,signal,socket,sys;signal.alarm(20);os.chdir(sys.argv[1]);s=socket.socket(socket.AF_UNIX);"
              "s.bind('bus_0');s.listen(4);print('hazir',flush=True);[s.accept() for _ in range(8)]")
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
    os.makedirs(os.path.join(kok, "run", "at-spi"), mode=0o700, exist_ok=True)
    for tur, g in (("kwin", {"tur": "kwin", "calisma": kok, "wayland_yol": os.path.join(kok, "wl"), "x_ana": None}),
                   ("xvfb", {"tur": "xvfb", "calisma": kok, "no": 77})):
        hedef = dizin if tur == "kwin" else os.path.join(kok, "run", "at-spi")
        st_ = os.lstat(hedef)  # masaüstü açılışında kaydedilen dizin kimliği (kimliksiz + var olan dizin artık reddedilir)
        g["a11y_dizin_kimlik"] = [st_.st_dev, st_.st_ino]
        ro = {y: r for y, r in (ko.uygulama_baglari(g) if tur == "kwin" else masaustu.uygulama_baglari(g))}
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

# ---- 4) FAIL-CLOSED a11y bağı + dizin kimliği (süreçsiz)
print("\n4) a11y_bagi / a11y_dizini_hazirla / dizin kimliği")
k4 = os.path.realpath(os.path.join(GECICI, "a11y4"))
os.makedirs(k4, mode=0o700)
d4 = os.path.join(k4, "at-spi")
kim = ao.a11y_dizini_hazirla(d4)
st4 = os.lstat(d4)
kontrol("a11y_dizini_hazirla: 0700 dizin, kimlik = (st_dev, st_ino)",
        (st4.st_mode & 0o777) == 0o700 and kim == [st4.st_dev, st4.st_ino])
kontrol("a11y_dizini_hazirla: dizin zaten varsa (başkası koymuş) → Dur(14)", dur14(ao.a11y_dizini_hazirla, d4) == 14)
kontrol("a11y_bagi: kayıtlı kimlikle geçer, SALT OKUNUR bağ", ao.a11y_bagi(d4, kim) == (d4, True))
kontrol("a11y_bagi: kimlik kayıtlı ama dizin YOK → Dur(14), uygulama başlatılmaz",
        dur14(ao.a11y_bagi, os.path.join(k4, "yok-at-spi"), kim) == 14)
d4b = os.path.join(k4, "eski-at-spi")
kontrol("a11y_bagi: kimlik yok (eski masaüstü) + dizin yok → uygulamadan ÖNCE 0700 yaratılır",
        ao.a11y_bagi(d4b, None) == (d4b, True) and (os.lstat(d4b).st_mode & 0o777) == 0o700)
kontrol("a11y_bagi: kimlik yok (eski masaüstü) + dizin ZATEN var (0700, kendi yarattığı) → Dur(14), yeniden açın",
        dur14(ao.a11y_bagi, d4b, None) == 14)
os.rmdir(d4)
os.mkdir(d4, 0o700)  # aynı yol, yeni dizin (uygulama ya da başkası yeniden yaratmış)
kontrol("a11y_bagi: aynı yolda başka dizin (kimlik değişti) → Dur(14)", dur14(ao.a11y_bagi, d4, kim) == 14)
kontrol("a11y_soket_denetle: dizin kimliği değişmişse → Dur(14)", (lambda: (
    soket_ac(d4, "bus_0"), dur14(ao.a11y_soket_denetle, f"unix:path={d4}/bus_0", d4, "", kim))[1] == 14)())
kontrol("a11y_soket_denetle: kimlik uyuşuyorsa geçer", ao.a11y_soket_denetle(
    f"unix:path={d4}/bus_0", d4, "", [os.lstat(d4).st_dev, os.lstat(d4).st_ino]) == f"{d4}/bus_0")
os.chmod(d4, 0o755)
kontrol("a11y_bagi: gevşek izinli (0755) dizin → Dur(14)", dur14(ao.a11y_bagi, d4, None) == 14)
os.chmod(d4, 0o700)
os.rename(d4, d4 + ".tasindi")
os.symlink(d4 + ".tasindi", d4)
kontrol("a11y_bagi: dizin sembolik bağ → Dur(14)", dur14(ao.a11y_bagi, d4, None) == 14)
kontrol("a11y_kimlik_temizle: yalnız iki tamsayı", ao.a11y_kimlik_temizle({"a11y_dizin_kimlik": [1, 2]}) == [1, 2] and
        ao.a11y_kimlik_temizle({"a11y_dizin_kimlik": ["1", 2]}) is None and
        ao.a11y_kimlik_temizle({"a11y_dizin_kimlik": [1, 2, 3]}) is None and
        ao.a11y_kimlik_temizle({"a11y_dizin_kimlik": [True, 2]}) is None and ao.a11y_kimlik_temizle({}) is None)
for t_, g_ in (("kwin", {"tur": "kwin", "calisma": k4, "wayland_yol": os.path.join(k4, "wl"), "x_ana": None,
                         "a11y_dizin_kimlik": kim}),
               ("xvfb", {"tur": "xvfb", "calisma": k4, "no": 77, "a11y_dizin_kimlik": kim})):
    kontrol(f"{t_}: uygulama_baglari a11y dizini yoksa/değiştiyse Dur(14) (fail-closed)",
            dur14(ko.uygulama_baglari if t_ == "kwin" else masaustu.uygulama_baglari, g_) == 14)

# ---- 5) GERÇEK masaüstü: erişilebilirlik hazırlığı BAŞARISIZ → uygulama a11y dizinini yaratıp/yazıp sahte soket koyamaz
print("\n5) regresyon: erişilebilirlik hazırlığı başarısız + uygulama at-spi dizinine yazmaya çalışır")
if ao.bwrap_var():
    import atexit
    from deskhand import masaustu as m5
    atexit.register(lambda: m5.durum_oku() is not None and m5.masaustu_durdur())
    asil_ei, asil_ab = m5._erisim_hazirla_ic, ko.atspi_baslat
    m5._erisim_hazirla_ic = lambda d: ""  # xvfb: açılışta hazırlık başarısız (yalnız uyarı)
    ko.atspi_baslat = lambda d: None      # kwin: aynısı
    try:
        d5 = m5.masaustu_baslat()
    finally:
        m5._erisim_hazirla_ic, ko.atspi_baslat = asil_ei, asil_ab
    g5 = m5.guvenli_kayit(d5)
    t5 = m5.tur(g5)
    dz5 = os.path.join(g5["calisma"], "at-spi" if t5 == "kwin" else os.path.join("run", "at-spi"))
    kontrol(f"[{t5}] hazırlık başarısız olsa da a11y dizinini Deskhand açılışta 0700 yarattı, kimlik kayıtlı",
            os.path.isdir(dz5) and not os.path.islink(dz5) and (os.stat(dz5).st_mode & 0o777) == 0o700 and
            g5.get("a11y_dizin_kimlik") == [os.stat(dz5).st_dev, os.stat(dz5).st_ino], str(g5.get("a11y_dizin_kimlik")))
    betik = (f"cd '{dz5}' || echo CD_YOK; mkdir '{dz5}/x' 2>&1 | head -1; touch '{dz5}/y' 2>&1 | head -1; "
             f"ln -s /etc/passwd '{dz5}/bus_0' 2>&1 | head -1; rmdir '{dz5}' 2>&1 | head -1; "
             f"mv '{dz5}' '{dz5}.x' 2>&1 | head -1; echo BITTI")
    p5 = m5.baslat(["/bin/sh", "-c", betik], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    cikti5 = p5.communicate(timeout=30)[0]
    kontrol(f"[{t5}] uygulama at-spi dizininde mkdir/dosya/bağ/rmdir/mv YAPAMAZ (salt okunur bağ)",
            "BITTI" in cikti5 and not os.listdir(dz5) and os.path.isdir(dz5) and not os.path.lexists(dz5 + ".x"),
            cikti5 + str(os.listdir(dz5)))
    kontrol(f"[{t5}] beş girişimin beşi de hata verdi (çıktıda beş hata satırı; dile bağlı değil)",
            len([x for x in cikti5.splitlines() if x.strip() and x.strip() != "BITTI"]) == 5, cikti5)
    # dizin kaybolur/değişirse: uygulama BAŞLATILMAZ (fail-closed), a11y soketi denetimi de reddeder
    eski_kim = os.stat(dz5)
    bas5 = []
    asil_pop = subprocess.Popen
    subprocess.Popen = lambda *a, **k: bas5.append(a) or asil_pop(*a, **k)
    try:
        os.rmdir(dz5)
        kontrol(f"[{t5}] a11y dizini yok → baslat Dur(14), süreç başlatılmadı",
                dur14(m5.baslat, ["/bin/true"]) == 14 and not bas5, str(bas5))
        os.mkdir(dz5, 0o700)  # aynı yol, YENİ dizin: kimlik uyuşmaz
        kontrol(f"[{t5}] a11y dizini yeniden yaratılmış (başka kimlik) → baslat Dur(14), süreç başlatılmadı",
                dur14(m5.baslat, ["/bin/true"]) == 14 and not bas5, str(bas5))
        kontrol(f"[{t5}] aynı durumda a11y_denetle (bağlantı öncesi) Dur(14)",
                dur14(m5.a11y_denetle, f"unix:path={dz5}/bus_0", d5) == 14)
        os.rmdir(dz5)
        os.symlink("/tmp", dz5)
        kontrol(f"[{t5}] a11y dizini sembolik bağ → baslat Dur(14), süreç başlatılmadı",
                dur14(m5.baslat, ["/bin/true"]) == 14 and not bas5, str(bas5))
    finally:
        subprocess.Popen = asil_pop
        if os.path.islink(dz5):
            os.unlink(dz5)
    m5.masaustu_durdur()
else:
    print("ATLANDI: bwrap yok (gerçek masaüstü bölümü)")

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
