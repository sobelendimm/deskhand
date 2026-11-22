"""Faz 12b bağımsız denetiminin saldırıları (docs/denetim/12b/ kanıt betiklerinden) — REGRESYON testi: düzeltmeden sonra
HER saldırı BAŞARISIZ olmalı. Kullanıcının GERÇEK oturumuna bağlantı/girdi YOK: "gerçek oturum" rolünü ikinci bir
yalıtık KWin oturumu (B) ya da sahte bir dinleyen soket oynar.

B1 `;` çoklu veri yolu adresi · B2 sert bağ (hardlink) · B3 uygulama ad alanı (gerçek soketler görünmez) ·
O1 bayat/bozuk oturum.json ilgisiz süreç/dizine dokunmaz · O3 KWin SIGKILL → oturum kendiliğinden kapanır ·
XWayland anahtarsız bağlantıyı reddeder · K1/K2 (deskhand-eis) · K4 RUNTIME_DIR sahip/izin denetimi.
KWin oturumu kurulamıyorsa yalnız süreçsiz bölümler koşar.

Çalıştır:  python3 tests/test_denetim12.py"""
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

import _yalitim  # noqa: F401

from deskhand import arka_ortak as ao, kwin_oturum as ko, masaustu, yollar  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

KOK = _yalitim.KOK
G = _yalitim.GECICI
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


def bekle(kosul, sure=8.0, aralik=0.05):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        v = kosul()
        if v:
            return v
        time.sleep(aralik)
    return kosul()


RT = yollar.runtime_dir()
os.makedirs(RT, mode=0o700, exist_ok=True)
uid = os.getuid()

# ---------------------------------------------------------------- B1: ';' çoklu adres (süreçsiz)
print("B1) ';' çoklu adres")
GERCEK = f"unix:path=/run/user/{uid}/bus"
for adres in (f"unix:path={RT}/kwin-aaaaaaaa/yok;{GERCEK}", f"{GERCEK};unix:path=/yok", f"unix:path=/a/b,guid=xyz",
              "unix:abstract=/tmp/dbus-x", f"unix:path={RT}/x,foo=bar"):
    kontrol(f"katı biçim: {adres[:60]}… → reddedilir", ao.bus_yolu_kati(adres) is None and
            dur_kodu(ko.guvenlik_kapilari, adres, "deskhand-x", os.path.join(G, "ev", "config")) == 14)
kontrol("katı biçim: unix:path=/yol ve ,guid=<32 hex> kabul",
        ao.bus_yolu_kati("unix:path=/a/bus") == "/a/bus" and
        ao.bus_yolu_kati("unix:path=/a/bus,guid=" + "0" * 32) == "/a/bus")
cdir = os.path.join(RT, "kwin-aaaaaaaa")
os.makedirs(cdir, mode=0o700, exist_ok=True)
d = {"kimlik": "aaaaaaaa", "calisma": "/tmp/baska", "wayland": "wayland-1", "wayland_yol": f"/run/user/{uid}/wayland-1",
     "dbus_adres": f"unix:path={cdir}/yok;{GERCEK}", "xwayland": None}
g = ko.guvenli_kayit(d)
kontrol("güvenli kayıt: yollar kayıttan DEĞİL oturum dizininden (adres, Wayland soketi, çalışma dizini)",
        g["dbus_adres"] == f"unix:path={cdir}/bus" and g["wayland_yol"] == f"{cdir}/deskhand-aaaaaaaa" and
        g["calisma"] == cdir, str(g))
kontrol("bağlantı kapısı: oynanmış kayıt (';' + gerçek Wayland) → Dur 14", dur_kodu(ko.baglanti_denetle, d) == 14)
for k_ in ("../kwin-aaaaaaaa", "AAAAAAAA", "aaaa", ""):
    kontrol(f"güvenli kayıt: geçersiz kimlik {k_!r} → Dur 14", dur_kodu(ko.guvenli_kayit, {**d, "kimlik": k_}) == 14)
kontrol("güvenli kayıt: XWayland :0 → Dur 14", dur_kodu(ko.guvenli_kayit, {**d, "x_ana": 0}) == 14)
kontrol("güvenli kayıt: başka kafes adı → Dur 14", dur_kodu(ko.guvenli_kayit, {**d, "kafes": "app-firefox.scope"}) == 14)

# C yardımcısı: adres_denetle (denetimin sarmalayıcısı)
EIS_C = os.path.join(KOK, "deskhand", "yardimci", "deskhand-eis.c")
sarm = os.path.join(G, "adres_harness.c")
with open(sarm, "w") as f:
    f.write(f'''#define main eis_main
#include "{EIS_C}"
#undef main
int main(void) {{
    char g[128], m1[256], m2[256], m3[256];
    snprintf(g, sizeof g, "unix:path=/run/user/%u/bus", (unsigned)getuid());
    snprintf(m1, sizeof m1, "unix:path=/yok/bus;unix:path=/run/user/%u/bus", (unsigned)getuid());
    snprintf(m2, sizeof m2, "unix:path=/run/user/%u/./bus", (unsigned)getuid());
    snprintf(m3, sizeof m3, "unix:path=/tmp/x/bus,guid=zz");
    const char *t[] = {{g, m1, m2, m3}};
    for (int i = 0; i < 4; i++) printf("%d\\n", adres_denetle(t[i]));
    return 0;
}}
''')
bin_ = os.path.join(G, "adres_harness")
r = subprocess.run(["sh", "-c", f'cc -O0 -w -I{os.path.dirname(EIS_C)} -o {bin_} {sarm} '
                    f'$(pkg-config --cflags --libs libei-1.0 xkbcommon libsystemd) -lm'], capture_output=True, text=True)
if r.returncode == 0:
    out = subprocess.run([bin_], capture_output=True, text=True).stdout.split()
    kontrol("deskhand-eis adres_denetle: gerçek, ';' çoklu, './' ve bozuk guid → hepsi -1", out == ["-1"] * 4, str(out))
else:
    kontrol("deskhand-eis sarmalayıcısı derlenemedi (libei yok?)", True)

# ---------------------------------------------------------------- B2: sert bağ (süreçsiz: sahte 'gerçek' soket)
print("\nB2) sert bağ")
sahte_dizin = tempfile.mkdtemp(prefix="sahte-gercek-", dir=RT)
sahte_bus = os.path.join(sahte_dizin, "bus")
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv.bind(sahte_bus)
srv.listen(4)
gelen = []
threading.Thread(target=lambda: gelen.append(srv.accept()), daemon=True).start()
asil = ko._gercek_degerler


def sahte_gercek():
    g_ = asil()
    g_["bus"] = set(g_["bus"]) | {f"unix:path={sahte_bus}"}
    return g_


ko._gercek_degerler = sahte_gercek
os.link(sahte_bus, os.path.join(cdir, "bus"))
kontrol("sert bağ: guvenlik_kapilari aynı inode'u 'gerçek' sayar → Dur 14",
        dur_kodu(ko.guvenlik_kapilari, f"unix:path={cdir}/bus", "deskhand-x", os.path.join(cdir, "ev", "config")) == 14)
d2 = {"kimlik": "aaaaaaaa", "pid": {"dbus": os.getpid(), "kwin": os.getpid()},
      "pid_bas": {"dbus": ao.surec_baslangic(os.getpid()), "kwin": ao.surec_baslangic(os.getpid())}}
kontrol("sert bağ: baglanti_denetle karşı tarafı (SO_PEERCRED) doğrular → Dur 14", dur_kodu(ko.baglanti_denetle, d2) == 14)
ko._gercek_degerler = asil
srv.close()

# ---------------------------------------------------------------- K4: RUNTIME_DIR sahip/izin
os.chmod(RT, 0o755)
kontrol("K4: bizim RUNTIME_DIR'imiz 0755 → Dur 14, sessizce sıkılaştırılmaz (denetim 12c)",
        dur_kodu(ko.guvenli_kayit, d) == 14 and (os.stat(RT).st_mode & 0o777) == 0o755)
os.chmod(RT, 0o700)
bag = os.path.join(G, "rt-bag")
os.symlink(RT, bag)
kontrol("K4: RUNTIME_DIR sembolik bağ → Dur 14", dur_kodu(ao.runtime_denetle, bag) == 14)

# ---------------------------------------------------------------- O1: bayat/bozuk oturum.json
print("\nO1) bayat kayıt")
kurban = subprocess.Popen(["sleep", "300"])
dis = tempfile.mkdtemp(prefix="dh12-")
kurban_dizin = os.path.join(dis, "kwin-kurban")
os.makedirs(kurban_dizin)
open(os.path.join(kurban_dizin, "onemli.txt"), "w").write("veri")
bcdir = os.path.join(RT, "kwin-bayat001")
os.makedirs(bcdir, mode=0o700)
bayat = {"kimlik": "bayat001", "calisma": kurban_dizin, "wayland": "deskhand-bayat001", "wayland_yol": "/yok",
         "pid": {"kwin": 0, "dbus": kurban.pid, "a11y": os.getppid()}, "baslatan_pid": 0, "baslangic": 0,
         "cgroup": ao._cgroup(os.getpid()), "kafes": ao._cgroup(os.getpid()).rsplit("/", 1)[-1], "x_ana": 0}
with open(os.path.join(bcdir, "oturum.json"), "w") as f:
    json.dump(bayat, f)
temiz = ko.temizle_kalintilar()
time.sleep(0.5)
kontrol("O1: kalıntı taraması bayat oturumu buldu", "bayat001" in temiz, str(temiz))
kontrol("O1: kayıttaki İLGİSİZ süreç (başlangıç zamanı yok/uyuşmuyor) öldürülmedi", kurban.poll() is None)
kontrol("O1: kayıttaki RUNTIME_DIR DIŞINDAKİ 'kwin-*' dizini silinmedi", os.path.exists(os.path.join(kurban_dizin, "onemli.txt")))
kontrol("O1: kendi kalıntı dizini silindi", not os.path.exists(bcdir))
kontrol("O1: bu testin kafesi (kayıttaki sahte kafes) boşaltılmadı", ao._canli(os.getpid()))
kurban.kill()
kurban.wait()
subprocess.run(["rm", "-rf", dis])
# Xvfb türü: oynanmış sanal.json → durum() kayıttaki adresi kullanmaz
masaustu._durum_yaz({"tur": "xvfb", "no": 91, "ekran": ":0", "dbus_adres": GERCEK, "calisma": "/tmp", "pid": {}})
kontrol("Xvfb kaydı: dizini olmayan/oynanmış kayıt → durum() None (gerçek adres kullanılmaz)", masaustu.durum() is None)
os.remove(masaustu.durum_yolu())

# ---------------------------------------------------------------- oturum kopyaları: her uygulama YALNIZ kendi kopyasını görür
# (arka plan masaüstü türü DESKHAND_ARKA_TUR'a göre: iki türde de koşulur)
print("\nKopya) oturum kopyası yalıtımı")
from deskhand.oturum import politika  # noqa: E402
KOPYA = politika.kopya_dizini()
os.makedirs(KOPYA, mode=0o700, exist_ok=True)
kA, kB = os.path.join(KOPYA, "firefox-sahteA"), os.path.join(KOPYA, "chromium-sahteB")
for k_, ad_ in ((kA, "A"), (kB, "B")):
    os.makedirs(k_, mode=0o700, exist_ok=True)
    open(os.path.join(k_, "gizli-cerez.txt"), "w").write(ad_)
# Bağlanan kopya komut satırından/ortamdan ÇIKARILMAZ (denetim 12c Y6): yalnız politikanın verdiği (kopya=). Sonuç
# stdout'tan (ad alanında /tmp boş: dosyaya yazılan rapor ana makineye ulaşmaz)
GOR = ("import json, os, sys, time\nben, oteki, kok = sys.argv[1:4]\ntime.sleep(1.5)\n"
       "r = {'kendi': os.path.exists(os.path.join(ben, 'gizli-cerez.txt')), 'oteki_var': os.path.exists(oteki),\n"
       " 'oteki_dosya': os.path.exists(os.path.join(oteki, 'gizli-cerez.txt')), 'kok': sorted(os.listdir(kok)) if os.path.isdir(kok) else None,\n"
       " 'env_kopya': os.path.isdir(os.environ.get('XDG_CONFIG_HOME', '/yok'))}\n"
       "print(json.dumps(r))\n")
os.makedirs(os.path.join(kA, ".xdg-config"), exist_ok=True)


def oku(p):
    return json.loads(p.communicate(timeout=30)[0].decode().strip().splitlines()[-1])


dk_ = masaustu.masaustu_baslat("800x600")
try:
    # A: Firefox gibi --profile <kopya> + XDG_CONFIG_HOME=<kopya>/.xdg-config; B: Chromium gibi --user-data-dir=<kopya>
    pA = masaustu.baslat([sys.executable, "-c", GOR, kA, kB, KOPYA, "--profile", kA],
                         {"XDG_CONFIG_HOME": os.path.join(kA, ".xdg-config")}, kopya=kA, stdout=subprocess.PIPE)
    pB = masaustu.baslat([sys.executable, "-c", GOR, kB, kA, KOPYA, f"--user-data-dir={kB}"], kopya=kB,
                         stdout=subprocess.PIPE)
    rA, rB = oku(pA), oku(pB)
    kontrol(f"kopya ({masaustu.tur(dk_)}): A kendi kopyasını görür, B'ninkini GÖREMEZ (dizin yok)",
            rA["kendi"] and not rA["oteki_var"] and not rA["oteki_dosya"] and rA["env_kopya"], str(rA))
    kontrol(f"kopya ({masaustu.tur(dk_)}): B kendi kopyasını görür, A'nınkini GÖREMEZ", rB["kendi"] and not rB["oteki_var"]
            and not rB["oteki_dosya"], str(rB))
    kontrol(f"kopya ({masaustu.tur(dk_)}): kopya kökünde yalnız kendi kopyası listelenir",
            rA["kok"] == ["firefox-sahteA"] and rB["kok"] == ["chromium-sahteB"], f"{rA['kok']} {rB['kok']}")
    pC = masaustu.baslat([sys.executable, "-c", GOR, kA, kB, KOPYA, "--profile", kA], stdout=subprocess.PIPE)
    rC = oku(pC)
    kontrol(f"kopya ({masaustu.tur(dk_)}): kopyası verilmeyen uygulama (komut satırında kopya yolu GEÇSE de) hiçbir "
            "kopyayı görmez", not rC["kendi"] and not rC["oteki_var"] and rC["kok"] in (None, []), str(rC))
finally:
    masaustu.masaustu_durdur()

ok, neden = ko.kullanilabilir()
if not ok:
    print(f"ATLANDI (canlı bölümler): {neden}")
else:
    # ---------------------------------------------------------------- canlı: A (Deskhand) + B ('gerçek oturum' rolü)
    print("\nB1/B2 canlı: iki oturum")
    A = B = None
    try:
        A = ko.baslat((1024, 768), xwayland=True)
        B = ko.baslat((800, 600), xwayland=False)
        sahte = {**A, "dbus_adres": f"unix:path={A['calisma']}/yok;unix:path={B['calisma']}/bus",
                 "calisma": B["calisma"], "wayland_yol": B["wayland_yol"]}
        kontrol("B1 canlı: oynanmış A kaydıyla görüntü YİNE A'nın (1024x768; B'nin 800x600'ü değil)",
                ko.goruntu(sahte).size == (1024, 768))
        with ko.Eis(sahte) as e:
            kontrol("B1 canlı: oynanmış A kaydıyla EIS YİNE A'ya bağlandı (1024x768)", e.boyut == (1024, 768), str(e.boyut))
        kontrol("B1 canlı: baglanti_denetle A'nın GERÇEK değerlerini döndürür",
                ko.baglanti_denetle(sahte)["dbus_adres"] == f"unix:path={A['calisma']}/bus")
        # B2 canlı: A'nın bus soketi yerine B'ninkinin sert bağı
        abus = os.path.join(A["calisma"], "bus")
        yedek = os.path.join(A["calisma"], "bus.yedek")
        os.rename(abus, yedek)
        os.link(os.path.join(B["calisma"], "bus"), abus)
        try:
            kontrol("B2 canlı: A/bus = B/bus sert bağı → baglanti_denetle Dur 14", dur_kodu(ko.baglanti_denetle, A) == 14)
            kontrol("B2 canlı: deskhand-eis karşı tarafı (--dbus-pid + bus.conf) doğrular → bağlanmaz",
                    dur_kodu(ko.Eis, A) is not None)
            r = subprocess.run([yollar.eis_bin(), "--bus", f"unix:path={abus}"], capture_output=True, text=True,
                               timeout=20, stdin=subprocess.DEVNULL)
            kontrol("B2 canlı: deskhand-eis --dbus-pid'siz de bus.conf denetimiyle reddeder (çıkış 2, bus-karsi)",
                    r.returncode == 2 and "bus-karsi" in r.stdout, f"{r.returncode} {r.stdout!r}")
        finally:
            os.unlink(abus)
            os.rename(yedek, abus)
        kontrol("B2 canlı: geri alınınca kapı yine geçer", dur_kodu(ko.baglanti_denetle, A) is None)

        # B3: uygulama ad alanı
        print("\nB3) uygulama ad alanı")
        IC = ("import json, os, sys, glob\nuid = os.getuid()\nrt = sys.argv[2]\n"
              "g = [f'/run/user/{uid}/bus', f'/run/user/{uid}/wayland-1', f'/run/user/{uid}/wayland-0', "
              "f'/run/user/{uid}/pipewire-0', f'/run/user/{uid}/pulse/native', f'/run/user/{uid}/kwallet5.socket', "
              "f'/run/user/{uid}/gnupg', '/tmp/.X11-unix/X0', '/tmp/.X11-unix/X1']\n"
              "r = {'gercek_erisim': [p for p in g if os.path.exists(p)],\n"
              " 'xauth': glob.glob(f'/run/user/{uid}/xauth_*'),\n"
              " 'deskhand_rt': sorted(os.listdir(rt)) if os.path.isdir(rt) else None,\n"
              " 'oturum_json': os.path.exists(os.path.join(os.environ['XDG_RUNTIME_DIR'], '..', 'oturum.json')),\n"
              " 'wayland': os.path.exists(os.environ['WAYLAND_DISPLAY']),\n"
              " 'bus': os.path.exists(os.environ['DBUS_SESSION_BUS_ADDRESS'][10:]),\n"
              " 'x': sorted(os.listdir('/tmp/.X11-unix')), 'home_config': os.access(os.path.expanduser('~/.config'), os.W_OK)}\n"
              "print(json.dumps(r))\n")
        p = ko.uygulama_baslat(A, [sys.executable, "-I", "-c", IC, "-", RT], stdout=subprocess.PIPE)
        ic = json.loads(p.communicate(timeout=30)[0].decode().strip().splitlines()[-1])
        kontrol("B3: ad alanında kullanıcının gerçek soketleri (veri yolu, Wayland, pipewire/pulse, kwallet, gnupg, X0/X1) "
                "GÖRÜNMEZ", ic["gercek_erisim"] == [] and ic["xauth"] == [], str(ic))
        kontrol("B3: Deskhand'in RUNTIME_DIR'i boş (sanal.json, girdi.sock, diğer oturumlar görünmez)",
                ic["deskhand_rt"] in ([], [f"kwin-{A['kimlik']}"]), str(ic["deskhand_rt"]))
        kontrol("B3: oturumun çalışma dizininden yalnız gerekenler (oturum.json görünmez)", not ic["oturum_json"])
        kontrol("B3: oturumun kendi Wayland soketi, veri yolu ve XWayland soketi görünür",
                ic["wayland"] and ic["bus"] and ic["x"] == [f"X{A['x_ana']}"], str(ic))
        kontrol("B3: ev dizini boş tmpfs + beyaz liste (yazılabilir görünür; yazılanlar atılır — test_ev_beyaz_liste)",
                ic["home_config"])
        # XWayland: anahtarsız bağlantı reddedilir (soyut soket ad alanı paylaşılır, anahtar dosyası görünmez)
        if subprocess.run(["which", "xdpyinfo"], capture_output=True).returncode == 0:
            px = ko.uygulama_baslat(A, ["/usr/bin/xprop", "-root", "-spy"])
            time.sleep(2)
            env = {"PATH": "/usr/bin", "XAUTHORITY": "/dev/null", "HOME": "/nonexistent"}
            r = subprocess.run(["xdpyinfo", "-display", A["xwayland"]], env=env, capture_output=True, text=True, timeout=10)
            r2 = subprocess.run(["xdpyinfo", "-display", A["xwayland"]], env={**env, "XAUTHORITY": A["xauth"]},
                                capture_output=True, text=True, timeout=10)
            kontrol("XWayland: anahtarsız bağlantı REDDEDİLİR, anahtarla bağlanır", r.returncode != 0 and r2.returncode == 0,
                    f"{r.returncode} {r2.returncode}")
            px.terminate()

        # O3: KWin SIGKILL → öncelik bekçisi oturumu kapatır
        print("\nO3) KWin SIGKILL")
        kw = A["pid"]["kwin"]
        cg = A["cgroup"]
        xa = A["x_ana"]
        os.kill(kw, signal.SIGKILL)
        kontrol("O3: KWin ölünce kafes (dbus, bekçiler, at-spi, uygulamalar) kendiliğinden boşaldı",
                bekle(lambda: not ao._kafes_surecleri(cg), 8), str(ao._kafes_surecleri(cg)))
        kontrol("O3: XWayland soketleri/kilitleri ve çalışma dizini silindi",
                bekle(lambda: not any(os.path.exists(y) for n in (xa, xa + 1)
                                      for y in (f"/tmp/.X11-unix/X{n}", f"/tmp/.X{n}-lock"))
                      and not os.path.exists(A["calisma"]), 5))
        A = None
    finally:
        for o in (A, B):
            if o:
                ko.durdur(o)

print(f"\n{gecen}/{toplam} denetim regresyon testi geçti")
sys.exit(0 if gecen == toplam else 1)
