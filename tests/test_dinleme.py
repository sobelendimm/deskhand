"""Dinleme (Tur 3) testleri: oturuma özel ses sunucusu (ses.py) + listen aracı (dinleme.py, mcp_sunucu.listen).

Bölümler: 1) sözleşme (sahte kayıt + sahte motor: şekil, sessizlikte motor çalışmaz, geçici dosya silinir, günlükte metin
yok, motor/model yoksa açık hata + ipucu, whisper JSON çözümü) 2) görünmez masaüstü + özel ses sunucusu: güvenlik sınırı
ÖLÇÜLÜR (ad alanında kullanıcının gerçek soketi yok; özel örnekte yalnız boş çıkış + monitörü, mikrofon yok; uygulama yalnız
özel sokete bağlanır) 3) gerçek uçtan uca (motor varsa): uygulama bir ses dosyası çalar → `listen` metni içerir; kullanıcının
GERÇEK ses sunucusunda yeni akış yok, varsayılan çıkış değişmedi 4) kapanış: süreçler gitti, soketler silindi.

Çalıştır:  DESKHAND_ARKA_TUR=kwin python3 tests/test_dinleme.py     (ya da =xvfb; DESKHAND_TEST_SAKLA=1: klasör silinmesin)
Ağır (large-v3): `agir-is python3 tests/test_dinleme.py`."""
import atexit
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

os.environ.setdefault("DESKHAND_ARKA_TUR", "kwin")
from deskhand import arka_ortak as ao, dinleme, hata, masaustu, mcp_sunucu, ses  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
GECICI = _yalitim.GECICI
gecen = toplam = 0
olcum = {}


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


# ---------------------------------------------------------------- 1) sözleşme (masaüstü yok)

SESSIZ = bytes(dinleme.BAYT_SN * 2)  # 2 sn sıfır
SESLI = (b"\x00\x10\x00\xf0" * (dinleme.BAYT_SN // 4)) * 2  # 2 sn "ses" (RMS ~4096)
cdir_sahte = os.path.join(GECICI, "sahte-oturum")
os.makedirs(cdir_sahte, mode=0o700)
cagri = []


def sahte_tanici(cdir, pcm, dil):
    cagri.append((cdir, len(pcm), dil))
    return {"text": "gizli konuşma metni", "segments": [{"t0": 0.0, "t1": 1.5, "text": "gizli konuşma metni"}],
            "language": "tr", "gpu": False}


class Yakala(logging.Handler):
    def __init__(self):
        super().__init__()
        self.satirlar = []

    def emit(self, kayit):
        self.satirlar.append(kayit.getMessage())


yk = Yakala()
logging.getLogger("deskhand.dinleme").addHandler(yk)
logging.getLogger("deskhand.dinleme").setLevel(logging.DEBUG)

r = dinleme.dinle(cdir_sahte, 5, None, "auto", kaydedici=lambda c, s, sl: (SESSIZ, False), tanicisi=sahte_tanici)
kontrol("sözleşme: ses yoksa motor ÇALIŞMAZ, boş metin + heard=false", r["text"] == "" and r["heard"] is False
        and r["segments"] == [] and not cagri and r["duration"] == 2.0, str(r))
r = dinleme.dinle(cdir_sahte, 5, 1.0, "tr", kaydedici=lambda c, s, sl: (SESLI, True), tanicisi=sahte_tanici)
kontrol("sözleşme: {text, segments[{t0,t1,text}], language, duration}",
        set(r) >= {"text", "segments", "language", "duration"} and r["language"] == "tr" and r["duration"] == 2.0
        and r["segments"][0].keys() == {"t0", "t1", "text"} and cagri == [(cdir_sahte, len(SESLI), "tr")], str(r))
kontrol("günlük: yalnız süre/dil/parça sayısı, TANINAN METİN YOK",
        yk.satirlar and not any("gizli" in s for s in yk.satirlar) and any("dil=tr" in s for s in yk.satirlar),
        str(yk.satirlar))
kontrol("sözleşme: seconds sınırı (0 ve 121) → Dur 1",
        dur_kodu(dinleme.dinle, cdir_sahte, 0) == 1 and dur_kodu(dinleme.dinle, cdir_sahte, 121) == 1)
kontrol("sessizlik ölçümü: sıfır < eşik, yüksek ses > eşik",
        dinleme.rms(SESSIZ[:3200]) < dinleme.SESSIZLIK_ESIK < dinleme.rms(SESLI[:3200]))

ornek = {"result": {"language": "tr"}, "transcription": [
    {"timestamps": {"from": "00:00:00,000", "to": "00:00:02,340"}, "offsets": {"from": 0, "to": 2340}, "text": " Merhaba dünya."},
    {"timestamps": {"from": "00:00:02,340", "to": "00:00:03,000"}, "offsets": {"from": 2340, "to": 3000}, "text": "  "},
    {"timestamps": {"from": "00:01:03,500", "to": "00:01:05,000"}, "offsets": {"from": 63500, "to": 65000}, "text": "Nasılsın?"}]}
m, parcalar, dil = dinleme.json_coz(ornek)
kontrol("whisper JSON: metin birleşir, boş parça atılır, zaman damgaları sn", m == "Merhaba dünya. Nasılsın?" and dil == "tr"
        and parcalar == [{"t0": 0.0, "t1": 2.34, "text": "Merhaba dünya."}, {"t0": 63.5, "t1": 65.0, "text": "Nasılsın?"}],
        str((m, parcalar, dil)))

# motor/model yok → açık hata + kurulum ipucu; HİÇBİR ŞEY indirilmez/kurulmaz
os.makedirs(os.path.join(_yalitim.DIZINLER["DESKHAND_CONFIG_DIR"]), exist_ok=True)
from deskhand import ayarlar  # noqa: E402
ayarlar.ayarla("dinleme", "model", os.path.join(GECICI, "yok-model.bin"))
ayarlar.ayarla("dinleme", "motor", "/yok/whisper-cli")
e = dinleme.eksikler()
kontrol("motor/model yok: eksikler() = [motor, model]", e == ["motor", "model"], str(e))
try:
    dinleme.cozumle(cdir_sahte, SESLI)
    kod, msg = None, ""
except Dur as ex:
    kod, msg = ex.kod, str(ex)
kontrol("motor/model yok: Dur 9 (araç eksik) + kurulum ipucu (whisper-cli, model yolu)",
        kod == hata.ARAC_EKSIK and "whisper-cli" in msg and "yok-model.bin" in msg and "indirmez" in msg, msg)
from deskhand import doktor  # noqa: E402
sat = doktor.satir_dinleme()
kontrol("doctor: 'Dinleme' satırı motor yoksa uyarı + 'motor yok'", sat["ad"] == "Dinleme" and sat["durum"] == "uyari"
        and "motor yok" in sat["ayrinti"], str(sat))
ayarlar.ayarla("dinleme", "model", "")
ayarlar.ayarla("dinleme", "motor", "whisper-cli")
MOTOR_VAR = not dinleme.eksikler()
sat = doktor.satir_dinleme()
kontrol("doctor: motor + model varken 'Dinleme: hazır'", (sat["durum"] == "tamam" and "hazır" in sat["ayrinti"]) if MOTOR_VAR
        else sat["durum"] == "uyari", str(sat))

# listen aracı: kullanıcının kendi ekran sesi dinlenmez; kapalı masaüstü açık hata
try:
    mcp_sunucu.listen(desktop="foreground")
    h1 = ""
except Exception as ex:  # noqa: BLE001  (ToolError)
    h1 = str(ex)
kontrol("listen(desktop='foreground'): reddedilir ([10], gerçek ekran sesi YOK)", "[10]" in h1 and "ekran sesi" in h1, h1)

# ---------------------------------------------------------------- 2) görünmez masaüstü + özel ses sunucusu

for a in ("pactl", "parec", "paplay", "pipewire", "wireplumber", "pipewire-pulse"):
    if not shutil.which(a):
        print(f"atlandı: {a} yok")
        print(f"\n{gecen}/{toplam} geçti")
        sys.exit(0 if gecen == toplam else 1)


def gercek(*a):
    """Kullanıcının GERÇEK ses sunucusuna SALT OKUMA sorgusu (ortam: kullanıcınınki)."""
    return subprocess.run(["pactl", *a], capture_output=True, text=True, timeout=10, env=dict(os.environ)).stdout


def akis_idleri():
    return {l.split("\t")[0] for l in gercek("list", "short", "sink-inputs").splitlines() if l.strip()}


def gercek_ozet():
    """(f) kullanıcının GERÇEK sunucusunun özeti (YALNIZ salt okunur list sorguları)."""
    return {t: gercek("list", "short", t) for t in ("modules", "sinks", "sources", "sink-inputs", "source-outputs")}


once_akis = akis_idleri()
once_varsayilan = gercek("get-default-sink").strip()
once_cikislar = gercek("list", "short", "sinks")
once_modul = gercek("list", "short", "modules")
once_ozet = gercek_ozet()

# ZORUNLU: bu testteki her api çağrısı görünmez masaüstüne gider; arka uç "sanal" değilse ÇIK
from deskhand import api  # noqa: E402
with api.hedef("sanal"):
    if api.sec().ad != "sanal":
        print("DUR: arka uç 'sanal' değil; kullanıcının ekranına istek gitmemesi için test durduruldu")
        sys.exit(2)

d = masaustu.masaustu_baslat()
TUR = masaustu.tur(d)
print(f"arka plan masaüstü türü: {TUR}")
kontrol("masaüstü: istenen tür açıldı", TUR == os.environ["DESKHAND_ARKA_TUR"] or os.environ["DESKHAND_ARKA_TUR"] not in ("kwin", "xvfb"))
kontrol("ses: sunucu açılışta KURULMADI (varsayılan ayar ozel_ses=false; uygulamalar eskisi gibi ses görmez)",
        not masaustu.ses_var() and (d.get("ses") is None))
cdir = masaustu.baglanti_denetle(masaustu.gerekli())["calisma"]
t = time.monotonic()
cdir2, uyari = masaustu.ses_hazirla()
olcum["özel ses sunucusu kurulum"] = f"{(time.monotonic() - t) * 1000:.0f} ms"
kontrol("ses: özel sunucu kuruldu (uyarı yok)", cdir2 == cdir and uyari is None and masaustu.ses_var(), str(uyari))
kontrol("ses: ikinci ses_hazirla yeni süreç açmaz", masaustu.ses_hazirla() == (cdir, None))
dz = ses.dizin(cdir)
sk = os.lstat(ses.pulse_soketi(cdir))
kontrol("ses: dizin 0700, yalnız oturum dizininde; yol 108 bayt sınırının altında",
        (os.stat(dz).st_mode & 0o777) == 0o700 and dz.startswith(GECICI) and len(os.path.join(dz, "pipewire-0-manager")) < 108)
sinks, sources = ses.kaynaklar_ve_cikislar(cdir)
kontrol("GÜVENLİK: özel örnekte tek çıkış deskhand-sessiz, kaynak yalnız onun monitörü (MİKROFON YOK)",
        sinks == [ses.SINK] and sources == [f"{ses.SINK}.monitor"], str((sinks, sources)))
dd = masaustu.durum()
kontrol("ses: süreçler masaüstünün bellek kafesinde (cgroup) + durum kaydında",
        all(ad in dd["pid"] for ad in ses.SURECLER) and (not dd.get("cgroup") or all(
            dd["cgroup"] in open(f"/proc/{dd['pid'][ad]}/cgroup").read() for ad in ses.SURECLER)),
        str(dd.get("pid")))
sureclerin_ortami = open(f"/proc/{dd['pid']['ses_pw']}/environ", "rb").read().decode(errors="replace")
kontrol("GÜVENLİK: sunucu süreçlerinin ortamında kullanıcının gerçek runtime/soketi yok",
        f"/run/user/{os.getuid()}/pulse" not in sureclerin_ortami and f"/run/user/{os.getuid()}/pipewire" not in sureclerin_ortami
        and "DBUS_SESSION_BUS_ADDRESS" not in sureclerin_ortami and "WAYLAND_DISPLAY" not in sureclerin_ortami)
# özel örneğin donanım dosyası açmadığı: pipewire süreci /dev/snd açmamış
acik = []
for ad in ses.SURECLER:
    for fd in os.listdir(f"/proc/{dd['pid'][ad]}/fd"):
        try:
            acik.append(os.readlink(f"/proc/{dd['pid'][ad]}/fd/{fd}"))
        except OSError:
            pass
kontrol("GÜVENLİK: özel sunucu süreçleri hiçbir ses donanımı (/dev/snd), hidraw, bluetooth açmamış",
        not any(a.startswith(("/dev/snd", "/dev/hidraw", "/dev/video")) for a in acik),
        str([a for a in acik if a.startswith("/dev/")]))

# (c) ses süreçlerinin KENDİ ad alanı: gerçek ev, gerçek /run/user/UID, /dev/snd YOK, ağ YOK, nice 10
EV = os.path.expanduser("~")


def ns_bak(pid):
    kok = f"/proc/{pid}/root"
    try:
        ev_ls = os.listdir(kok + EV)
    except OSError:
        ev_ls = []
    try:
        ag = [s.split(":")[0].strip() for s in open(f"/proc/{pid}/net/dev").read().splitlines()[2:]]
    except OSError:
        ag = None
    return {"ev": ev_ls, "run_user": os.path.exists(f"{kok}/run/user/{os.getuid()}"),
            "pulse_gercek": os.path.exists(f"{kok}/run/user/{os.getuid()}/pulse"),
            "snd": os.path.exists(f"{kok}/dev/snd"), "dri": os.path.exists(f"{kok}/dev/dri"),
            "ag_ns_ayri": os.stat(f"/proc/{pid}/ns/net").st_ino != os.stat("/proc/self/ns/net").st_ino,
            "pid_ns_ayri": os.stat(f"/proc/{pid}/ns/pid").st_ino != os.stat("/proc/self/ns/pid").st_ino,
            "ag": ag, "nice": os.getpriority(os.PRIO_PROCESS, pid),
            "ses_yazilabilir": os.access(f"{kok}{dz}", os.W_OK)}


nsler = {ad: ns_bak(dd["pid"][ad]) for ad in ses.SURECLER}
kontrol("(c) GÜVENLİK: ses süreçleri bwrap'te: ayrı PID + AĞ ad alanı, ağda yalnız lo",
        all(n["ag_ns_ayri"] and n["pid_ns_ayri"] and n["ag"] == ["lo"] for n in nsler.values()), str(nsler))
kontrol("(c) GÜVENLİK: ses süreçlerinin ad alanında gerçek ev BOŞ, gerçek /run/user/UID YOK",
        all(n["ev"] == [] and not n["run_user"] and not n["pulse_gercek"] for n in nsler.values()), str(nsler))
kontrol("(c) GÜVENLİK: ses süreçlerinin ad alanında /dev/snd ve /dev/dri YOK",
        all(not n["snd"] and not n["dri"] for n in nsler.values()), str(nsler))
kontrol("(c) ses süreçleri nice 10 (düşük öncelik)", all(n["nice"] >= 10 for n in nsler.values()), str(nsler))
kontrol("ses: PipeWire soketleri yalnız `ses/`, pulse soketi `ses/` DIŞINDA kardeş `ses-pulse/` dizininde; yapılandırma + "
        "günlük `ses-conf/`te (ses/ içinde pw.conf/pulse.conf/ses.log YOK)",
        os.path.exists(os.path.join(dz, ses.PW_SOKET)) and sorted(os.listdir(ses.pulse_dizini(cdir)))[:1] == ["native"]
        and os.path.dirname(ses.pulse_dizini(cdir)) == cdir and not ses.pulse_dizini(cdir).startswith(dz + "/")
        and sorted(os.listdir(ses.conf_dizini(cdir))) == ["pulse.conf", "pw.conf", "ses.log"]
        and not any(f in os.listdir(dz) for f in ("pw.conf", "pulse.conf", "ses.log"))
        and all((os.lstat(y).st_mode & 0o777) == 0o700 for y in (dz, ses.conf_dizini(cdir), ses.pulse_dizini(cdir),
                                                                  ses.istemci_dizini(cdir)))
        and not any(f.startswith("pipewire") for f in os.listdir(ses.pulse_dizini(cdir))),
        str(os.listdir(ses.pulse_dizini(cdir))))
kontrol("parec soket denetimi: kayıtlı ses_pulse süreci → geçer",
        dur_kodu(ses.soket_denetle, cdir, dinleme.oturum_kaydi(cdir)) is None)
kontrol("parec soket denetimi: kayıtta başka PID → Dur 14",
        dur_kodu(ses.soket_denetle, cdir, {**dinleme.oturum_kaydi(cdir), "pid": {"ses_pulse": os.getpid()}}) == 14)

# ---- uygulama ad alanından ölçüm
OLCUM_DOSYA = os.path.join(_yalitim.PAYLASIM, "ses-olcum.json")
kod_ = f"""
import json, os, subprocess
uid = os.getuid()
def calistir(*a, env=None):
    try:
        r = subprocess.run(list(a), capture_output=True, text=True, timeout=15, env=env or os.environ)
        return r.returncode, r.stdout
    except Exception as e:
        return 99, str(e)
s = {{}}
s["env"] = {{k: v for k, v in os.environ.items() if k.startswith(("PULSE", "PIPEWIRE"))}}
s["gercek_pulse"] = os.path.exists(f"/run/user/{{uid}}/pulse/native")
s["gercek_pw"] = os.path.exists(f"/run/user/{{uid}}/pipewire-0")
s["runtime_ls"] = sorted(os.listdir(f"/run/user/{{uid}}")) if os.path.isdir(f"/run/user/{{uid}}") else None
s["sinks"] = calistir("pactl", "list", "short", "sinks")
s["sources"] = calistir("pactl", "list", "short", "sources")
s["info"] = calistir("pactl", "info")
s["gercek_yolla"] = calistir("pactl", "info", env={{**os.environ, "PULSE_SERVER": f"unix:/run/user/{{uid}}/pulse/native"}})[0]
try:
    open(os.environ["PULSE_RUNTIME_PATH"] + "/yaz.txt", "w").write("x")
    s["ses_dizini_yazilabilir"] = True
except OSError:
    s["ses_dizini_yazilabilir"] = False
# (a) SALDIRI (yalnız ÖZEL sunucuya: PULSE_SERVER = oturumun soketi): modül yükleme reddedilmeli
PAY = {_yalitim.PAYLASIM!r}
s["mod_null"] = calistir("pactl", "load-module", "module-null-sink", "sink_name=saldiri")
s["mod_tunnel"] = calistir("pactl", "load-module", "module-tunnel-source", "server=unix:" + PAY + "/yok-soket")
s["mod_pipe"] = calistir("pactl", "load-module", "module-pipe-sink", "file=" + PAY + "/saldiri-pipe", "sink_name=saldiri2")
s["mod_tcp"] = calistir("pactl", "load-module", "module-native-protocol-tcp", "port=46713", "listen=127.0.0.1")
s["pipe_dosyasi"] = os.path.exists(PAY + "/saldiri-pipe")
s["sinks_sonra"] = calistir("pactl", "list", "short", "sinks")
s["mods_sonra"] = calistir("pactl", "list", "short", "modules")
# (b) PipeWire soketi: görünmemeli, bağlanma başarısız
s["ses_dizini_ls"] = sorted(os.listdir({dz!r})) if os.path.isdir({dz!r}) else []
s["pw_soketi_gorunur"] = os.path.exists({os.path.join(dz, ses.PW_SOKET)!r})
s["pulse_dizini_ls"] = sorted(os.listdir(os.path.dirname(os.environ["PULSE_SERVER"][5:])))
s["pw_cli"] = calistir("pw-cli", "info", "0")
s["pw_cli_acik"] = calistir("pw-cli", "-r", {os.path.join(dz, ses.PW_SOKET)!r}, "info", "0")
s["pw_cli_yonetici"] = calistir("pw-cli", "-r", {os.path.join(dz, ses.PW_SOKET + "-manager")!r}, "info", "0")
s["pw_dump"] = calistir("pw-dump")
json.dump(s, open({OLCUM_DOSYA!r}, "w"))
"""
from deskhand import api  # noqa: E402
p = masaustu.baslat([sys.executable, "-c", kod_])
p.wait(60)
try:
    o = json.load(open(OLCUM_DOSYA))
except (OSError, ValueError):
    o = {}
env_o = o.get("env", {})
kontrol("GÜVENLİK: uygulama ortamı YALNIZ özel pulse soketine yönlendirilmiş; PIPEWIRE_REMOTE var olmayan yol",
        env_o.get("PULSE_SERVER") == f"unix:{ses.pulse_soketi(cdir)}" and env_o.get("PIPEWIRE_REMOTE")
        and not env_o["PIPEWIRE_REMOTE"].startswith(dz + "/") and not os.path.exists(env_o["PIPEWIRE_REMOTE"]), str(env_o))
ok_ = lambda k: (o.get(k) or [0, ""])[0] != 0  # noqa: E731  komut BAŞARISIZ
kontrol("(a) GÜVENLİK: load-module (null-sink, tunnel-source, pipe-sink, native-protocol-tcp) REDDEDİLDİ",
        all(ok_(k) for k in ("mod_null", "mod_tunnel", "mod_pipe", "mod_tcp")),
        str({k: o.get(k) for k in ("mod_null", "mod_tunnel", "mod_pipe", "mod_tcp")}))
kontrol("(a) GÜVENLİK: pipe-sink dosyası oluşmadı, yeni çıkış/modül yok",
        o.get("pipe_dosyasi") is False and "saldiri" not in (o.get("sinks_sonra") or [1, ""])[1]
        and "module-pipe-sink" not in (o.get("mods_sonra") or [1, ""])[1]
        and "tunnel" not in (o.get("mods_sonra") or [1, ""])[1], str((o.get("sinks_sonra"), o.get("mods_sonra"))))
kontrol("(b) GÜVENLİK: ad alanında `ses/` ve `ses-conf/` YOK (PipeWire soketi, yapılandırma, günlük GÖRÜNMEZ); pulse dizininde yalnız native",
        o.get("ses_dizini_ls") == [] and o.get("pw_soketi_gorunur") is False
        and o.get("pulse_dizini_ls", [""])[:1] == ["native"] and not any("pipewire" in f for f in o.get("pulse_dizini_ls", [])),
        str((o.get("ses_dizini_ls"), o.get("pw_soketi_gorunur"), o.get("pulse_dizini_ls"))))
kontrol("(b) GÜVENLİK: pw-cli / pw-dump PipeWire'a bağlanamaz (varsayılan, açık yol, -manager)",
        all(ok_(k) for k in ("pw_cli", "pw_cli_acik", "pw_cli_yonetici", "pw_dump")),
        str({k: o.get(k) for k in ("pw_cli", "pw_cli_acik", "pw_cli_yonetici", "pw_dump")})[:600])
kontrol("GÜVENLİK: ad alanında kullanıcının GERÇEK pulse/pipewire soketi yok (/run/user/UID boş)",
        o.get("gercek_pulse") is False and o.get("gercek_pw") is False and o.get("runtime_ls") == [], str(o.get("runtime_ls")))
kontrol("GÜVENLİK: açık gerçek yolla bağlanma BAŞARISIZ", o.get("gercek_yolla") not in (0, None), str(o.get("gercek_yolla")))
s_cik = (o.get("sinks") or [1, ""])[1].splitlines()
s_kay = (o.get("sources") or [1, ""])[1].splitlines()
kontrol("GÜVENLİK: uygulama özel sunucuda yalnız deskhand-sessiz çıkışı + monitörünü görür (mikrofon/gerçek aygıt yok)",
        len(s_cik) == 1 and ses.SINK in s_cik[0] and len(s_kay) == 1 and f"{ses.SINK}.monitor" in s_kay[0]
        and not any(x in "".join(s_cik + s_kay) for x in ("alsa_", "bluez", "oto_eq", "hdmi", "usb-")), str((s_cik, s_kay)))
kontrol("GÜVENLİK: ses dizini uygulamaya SALT OKUNUR", o.get("ses_dizini_yazilabilir") is False, str(o.get("ses_dizini_yazilabilir")))
kontrol("ölçüm: kullanıcının gerçek ses sunucusunda yeni çıkış/modül yok (uygulama başladıktan sonra)",
        gercek("list", "short", "sinks") == once_cikislar and gercek("list", "short", "modules") == once_modul)

# ---------------------------------------------------------------- 3) gerçek uçtan uca

ESPEAK = shutil.which("espeak-ng")
if not MOTOR_VAR or not ESPEAK:
    print(f"atlandı: gerçek uçtan uca ({'motor/model yok' if not MOTOR_VAR else 'espeak-ng yok'})")
else:
    ornekler = [("en", "The quick brown fox jumps over the lazy dog. Please open the second window.", ("fox", "dog")),
                ("tr", "Merhaba dünya. Bu bir deneme kaydıdır.", ("merhaba", "deneme"))]
    for dil_k, metin_k, anahtarlar in ornekler:
        wav = os.path.join(_yalitim.PAYLASIM, f"konusma-{dil_k}.wav")
        subprocess.run([ESPEAK, "-v", dil_k, "-s", "130", "-w", wav, metin_k], check=True, timeout=30)
        sonuc = {}

        def dinle_is(dil_k=dil_k, sonuc=sonuc):
            try:
                sonuc["r"] = mcp_sunucu.listen(seconds=25, until_silence=2.0, desktop="background", language=dil_k)
            except Exception as ex:  # noqa: BLE001
                sonuc["h"] = str(ex)

        th = threading.Thread(target=dinle_is)
        t0 = time.monotonic()
        th.start()
        time.sleep(1.5)  # kayıt başlasın
        pp = masaustu.baslat(["paplay", wav])  # uygulama: ad alanında, özel sunucuya
        ortada_akis = akis_idleri()
        th.join(120)
        olcum[f"listen ({dil_k}) toplam"] = f"{time.monotonic() - t0:.1f} sn"
        pp.wait(10)
        r = sonuc.get("r")
        kontrol(f"uçtan uca ({dil_k}): listen başarılı", r is not None and r.get("status") == "ok", str(sonuc))
        if r:
            metin = r["text"].lower()
            kontrol(f"uçtan uca ({dil_k}): metin beklenen sözcükleri içeriyor {anahtarlar}",
                    all(a in metin for a in anahtarlar), repr(r["text"]))
            kontrol(f"uçtan uca ({dil_k}): sözleşme alanları + untrusted uyarısı",
                    set(r) >= {"text", "segments", "language", "duration", "warning", "status"} and r["segments"]
                    and r["duration"] > 1 and "UNTRUSTED" in r["warning"] and r["language"] == dil_k, str(r)[:300])
            olcum[f"motor ({dil_k})"] = "GPU (ROCm)" if r.get("gpu") else "CPU"
            print("   metin:", r["text"], "| süre:", r["duration"], "| dil:", r["language"])
        kontrol(f"ölçüm ({dil_k}): oynatma sırasında kullanıcının gerçek sunucusunda 'paplay' akışı YOK",
                "paplay" not in gercek("list", "sink-inputs") and "parec" not in gercek("list", "source-outputs")
                and "Deskhand-sessiz" not in gercek("list", "sink-inputs"))
        kontrol(f"ölçüm ({dil_k}): kullanıcının gerçek sunucusunda yeni akış yok (önce/sonra aynı)",
                akis_idleri() == once_akis, f"{once_akis} -> {akis_idleri()} (ortada {ortada_akis})")
    # sessiz kayıt: ses çalınmıyorsa motor çalışmaz, hızlı döner
    t0 = time.monotonic()
    r = mcp_sunucu.listen(seconds=2, desktop="background", language="auto")
    kontrol("sessizlik: ses yoksa boş metin, motor çalışmaz (hızlı)", r["text"] == "" and time.monotonic() - t0 < 5, str(r))
    kontrol("geçici dosya: oturum dizininde kayıt/JSON kalmadı",
            not [f for f in os.listdir(os.path.join(cdir, "dinleme")) if f.startswith("kayit-")])

kontrol("ölçüm: varsayılan çıkış değişmedi", gercek("get-default-sink").strip() == once_varsayilan)
kontrol("ölçüm: kullanıcının gerçek çıkış listesi/modülleri değişmedi",
        gercek("list", "short", "sinks") == once_cikislar and gercek("list", "short", "modules") == once_modul)
sonra_ozet = gercek_ozet()
kontrol("(f) kullanıcının GERÇEK sunucusunda yeni modül/çıkış/kaynak/akış YOK (önce/sonra, salt okunur sorgu)",
        sonra_ozet == once_ozet, str({k: (once_ozet[k], sonra_ozet[k]) for k in once_ozet if once_ozet[k] != sonra_ozet[k]}))
# eski kayıt temizliği (çökmeden kalan WAV): eski dosya silinir, yenisine dokunulmaz
gd = os.path.join(cdir, "dinleme")
os.makedirs(gd, mode=0o700, exist_ok=True)
for ad_, yas_ in (("kayit-eski.wav", 3600), ("kayit-yeni.wav", 0)):
    open(os.path.join(gd, ad_), "wb").close()
    os.utime(os.path.join(gd, ad_), (time.time() - yas_, time.time() - yas_))
kontrol("çökme sonrası kalan WAV: eski silinir, eşzamanlı (yeni) dosyaya dokunulmaz",
        dinleme.eski_kayitlari_sil(gd) == 1 and os.listdir(gd) == ["kayit-yeni.wav"], str(os.listdir(gd)))
os.remove(os.path.join(gd, "kayit-yeni.wav"))
# kur yeniden çalışınca eski süreçler kapanır (yeni PID'ler, eskiler ölü)
eski_pidler = [masaustu.durum()["pid"][ad] for ad in ses.SURECLER]
os.unlink(ses.pulse_soketi(cdir))  # soket "kaybolmuş": ses_hazirla yeniden kurar
cdir3, uyari3 = masaustu.ses_hazirla()
yeni_pidler = [masaustu.durum()["pid"][ad] for ad in ses.SURECLER]
kontrol("kur yeniden: eski ses süreçleri öldürüldü, yenileri çalışıyor, uyarı yok",
        uyari3 is None and bekle(lambda: not any(ao._canli(p) for p in eski_pidler), 6)
        and all(ao._canli(p) for p in yeni_pidler) and set(eski_pidler).isdisjoint(yeni_pidler),
        f"{uyari3} {eski_pidler} -> {yeni_pidler}")
dd = masaustu.durum()

# ---------------------------------------------------------------- 3b) Tur 8: ses sunucusuna GÜVENME
# Ele geçirilmiş sunucu (bwrap içinde `ses/` ve `ses-pulse/` yazabilir) simülasyonu: tuzak dosyalar YALNIZ scratchpad altında
# (kullanıcının gerçek ~/.bashrc, ~/.ssh dosyalarına hiçbir yerde dokunulmaz, bağ hedefi bile değil).
import hashlib  # noqa: E402
import signal  # noqa: E402
import socket as _sock  # noqa: E402
import stat as _stat  # noqa: E402
import tempfile  # noqa: E402

TUZAK_KOK = "/tmp/claude-1000/-home-mustafa/10082ba7-82ea-4b36-ae15-9f61ff9d0931/scratchpad/olgunlastirma-ses"
os.makedirs(TUZAK_KOK, mode=0o700, exist_ok=True)
TZ = tempfile.mkdtemp(prefix="tuzak-", dir=TUZAK_KOK)
atexit.register(shutil.rmtree, TZ, True)


class Dinleyici:
    """Tuzak unix soketi (scratchpad): gelen bağlantıları sayar. Yol AF_UNIX sınırından uzun: göreli bind (bağlantı sembolik
    bağ üzerinden gelir; sun_path'e giden yol kısa)."""

    def __init__(self, yol):
        self.yol, self.sayac, self.dur = yol, 0, False
        eski = os.getcwd()
        os.chdir(os.path.dirname(yol))
        try:
            self.s = _sock.socket(_sock.AF_UNIX)
            self.s.bind(os.path.basename(yol))
            self.s.listen(8)
        finally:
            os.chdir(eski)
        self.s.settimeout(0.1)
        self.th = threading.Thread(target=self._dongu, daemon=True)
        self.th.start()

    def _dongu(self):
        while not self.dur:
            try:
                c, _a = self.s.accept()
                self.sayac += 1
                c.close()
            except _sock.timeout:
                continue
            except OSError:
                break

    def kapat(self):
        self.dur = True
        self.th.join(1)
        self.s.close()


def tuzak_dosya(ad, icerik="KORUNAN-ICERIK\n"):
    y = os.path.join(TZ, ad)
    with open(y, "w") as f:
        f.write(icerik)
    return y


def dosya_izi(y):
    st = os.stat(y)
    return (hashlib.sha1(open(y, "rb").read()).hexdigest(), st.st_mtime_ns, st.st_ino, st.st_size)


NSENTER, SETPRIV = shutil.which("nsenter"), shutil.which("setpriv")


def sunucu_icinden(kod, sure=15):
    """KOD'u ses sunucusunun GERÇEK ad alanında (kullanıcı+mount+PID) çalıştır: --preserve-credentials ile süreç ad alanında
    uid 1000 kalır (kök değil) ve execve ile ad alanı yetkilerini yitirir → sunucuyla aynı yetkisizlik. → (çıkış kodu, stdout,
    stderr) | None (nsenter/izin yok)."""
    if not NSENTER:
        return None
    pid = masaustu.durum()["pid"]["ses_pw"]
    try:
        r = subprocess.run([NSENTER, "-t", str(pid), "--preserve-credentials", "-U", "-m", "-p", "--", sys.executable, "-c", kod],
                           capture_output=True, text=True, timeout=sure)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def sunucu_ici_var():
    r = sunucu_icinden("import os; print(os.getuid())")
    if not (r and r[0] == 0 and r[1] == str(os.getuid())):
        print("   nsenter yoklaması:", r)
        return False
    return True


def sunucuyu_yeniden_kur():
    c, u = masaustu.ses_hazirla()
    return c, u, dinleme.oturum_kaydi(cdir)


cdir = masaustu.baglanti_denetle(masaustu.gerekli())["calisma"]
dz = ses.dizin(cdir)
cf = ses.conf_dizini(cdir)
kd = dinleme.oturum_kaydi(cdir)
SUNUCU_ICI = sunucu_ici_var()
print("sunucu ad alanından saldırı simülasyonu:", "GERÇEK ad alanı (nsenter)" if SUNUCU_ICI else "ana makineden (nsenter yok)")
kontrol("tur8: sunucu hazir() (güvenli soket + doğrulanmış süreçler + bağlanılabilir)", ses.hazir(kd, cdir))

# -- (b) dizin düzeni ad alanında: yapılandırma/günlük sunucuya SALT OKUNUR, istemci dizini görünmez, ses-pulse yazılabilir
kok_ = f"/proc/{kd['pid']['ses_pw']}/root"
kontrol("tur8 (b): sunucu ad alanında `ses-conf` SALT OKUNUR, `ses-istemci` GÖRÜNMEZ, `ses/` ve `ses-pulse/` yazılabilir",
        not os.access(kok_ + cf, os.W_OK) and os.path.isdir(kok_ + cf) and not os.path.exists(kok_ + ses.istemci_dizini(cdir))
        and os.access(kok_ + dz, os.W_OK) and os.access(kok_ + ses.pulse_dizini(cdir), os.W_OK),
        str((os.access(kok_ + cf, os.W_OK), os.path.exists(kok_ + ses.istemci_dizini(cdir)))))
if SUNUCU_ICI:
    r_ = sunucu_icinden(f"""
import json, os
s = {{}}
for ad, f in (("conf_yaz", {cf + '/pw.conf'!r}), ("log_ac", {cf + '/ses.log'!r}), ("conf_yeni", {cf + '/yeni'!r})):
    try:
        open(f, "a").write("x"); s[ad] = "YAZILDI"
    except OSError as e:
        s[ad] = type(e).__name__
try:
    os.rename({ses.pulse_dizini(cdir)!r}, {cdir + '/x-tasi'!r}); s["pulse_dizin_tasi"] = "TASINDI"
except OSError as e:
    s["pulse_dizin_tasi"] = type(e).__name__
try:
    os.symlink("/yok/hedef", {dz + '/deneme-baglanti'!r}); s["ses_symlink"] = "yaratildi"; os.unlink({dz + '/deneme-baglanti'!r})
except OSError as e:
    s["ses_symlink"] = type(e).__name__
print(json.dumps(s))
""")
    try:
        sd = json.loads(r_[1])
    except (TypeError, ValueError, IndexError):
        sd = {}
    kontrol("tur8 (b): SUNUCU İÇİNDEN: ses-conf/pw.conf/ses.log'a yazamaz, ses-pulse dizinini taşıyamaz; `ses/`te sembolik bağ "
            "yaratabilir (saldırı ilkeli gerçek)",
            all(sd.get(k) not in (None, "YAZILDI") for k in ("conf_yaz", "log_ac", "conf_yeni"))
            and sd.get("pulse_dizin_tasi") not in (None, "TASINDI") and sd.get("ses_symlink") == "yaratildi", str((sd, r_)))
    kontrol("tur8 (b): sunucu içinden yazma denemeleri ses-conf içeriğini değiştirmedi (pw.conf ve ses.log aynı, yeni dosya yok)",
            sorted(os.listdir(cf)) == ["pulse.conf", "pw.conf", "ses.log"] and os.path.exists(ses.pulse_soketi(cdir)))

# -- (c) Deskhand'in kendi istemci ortamı sunucunun yazabildiği hiçbir yolu göstermez
ie = ses.istemci_ortami(cdir)
yazilabilir = (dz + "/", ses.pulse_dizini(cdir) + "/")
kontrol("tur8 (c): istemci ortamı (HOME, XDG_CONFIG_HOME, PULSE_RUNTIME_PATH, PULSE_COOKIE, PULSE_CLIENTCONFIG) `ses-istemci` "
        "altında, sunucuya yazılabilir yol YOK; PULSE_CLIENTCONFIG boş dosya",
        all(ie[k].startswith(ses.istemci_dizini(cdir)) for k in ("HOME", "XDG_CONFIG_HOME", "PULSE_RUNTIME_PATH", "PULSE_COOKIE",
                                                                  "PULSE_CLIENTCONFIG"))
        and not any(v.startswith(yazilabilir) or v.startswith("unix:" + dz) for k, v in ie.items() if k != "PULSE_SERVER")
        and os.path.getsize(ie["PULSE_CLIENTCONFIG"]) == 0 and (os.lstat(ses.istemci_dizini(cdir)).st_mode & 0o777) == 0o700, str(ie))

# sunucunun yazdığı client.conf (cookie-file=...) OKUNMAZ (FIFO tuzağı: okuyan olursa takılır, yazma ucu açılabilir olur)
fifo = os.path.join(TZ, "cookie-fifo")
os.mkfifo(fifo)
for yol_ in (os.path.join(dz, "cfg", "pulse"), os.path.join(dz, ".config", "pulse")):  # libpulse: $HOME/.config/pulse (ölçüldü)
    os.makedirs(yol_, exist_ok=True)
    with open(os.path.join(yol_, "client.conf"), "w") as f_:
        f_.write(f"cookie-file = {fifo}\n")


def fifo_okuyan_sayisi(is_):
    """is_'i bir iş parçacığında çalıştır; boyunca FIFO'nun yazma ucunu açmayı dene: açılırsa biri OKUYOR demektir."""
    n, sonuc = 0, {}
    th = threading.Thread(target=lambda: sonuc.update(r=is_()))
    th.start()
    while th.is_alive():
        try:
            fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            time.sleep(0.01)
            continue
        n += 1
        try:
            os.write(fd, bytes(256))
        except OSError:
            pass
        finally:
            os.close(fd)
    th.join()
    return n, sonuc.get("r")


def eski_gibi_pactl():
    """KONTROL DENEYİ: eski ortam (HOME=ses/, XDG_CONFIG_HOME=ses/cfg, istemci yapılandırması/cookie yok)."""
    e = ses.istemci_ortami(cdir)
    for k in ("PULSE_CLIENTCONFIG", "PULSE_COOKIE"):
        e.pop(k)
    e.update(HOME=dz, XDG_CONFIG_HOME=os.path.join(dz, "cfg"))
    return subprocess.run(["pactl", "info"], capture_output=True, text=True, timeout=12, env=e).returncode


n_eski, _r = fifo_okuyan_sayisi(eski_gibi_pactl)
kontrol("tur8 (c): KONTROL DENEYİ: eski ortamla (HOME=ses/) pactl sunucunun client.conf'unu okurdu (cookie-file tuzağı açıldı)",
        n_eski >= 1, f"okuma sayısı {n_eski}")
n_yeni, r_ = fifo_okuyan_sayisi(lambda: ses.kaynaklar_ve_cikislar(cdir, dinleme.oturum_kaydi(cdir)))
kontrol("tur8 (c): yeni istemci (pactl) sunucunun client.conf/cookie-file'ını OKUMAZ, yine de sunucuya bağlanır",
        n_yeni == 0 and r_ and r_[0] == [ses.SINK], f"okuma {n_yeni}, {r_}")
n_kayit, r_ = fifo_okuyan_sayisi(lambda: dinleme.kayit(cdir, 0.6))
kontrol("tur8 (c): yeni istemci (parec/dinleme.kayit) client.conf'u OKUMAZ, kayıt çalışır",
        n_kayit == 0 and r_ is not None and isinstance(r_[0], bytes), f"okuma {n_kayit}")

# -- ses.log boyut sınırı (5 MB): ses-conf/ses.log; hazir() keser; ses/ içinde günlük dosyası yok
log_ = os.path.join(cf, "ses.log")
os.truncate(log_, ses.LOG_SINIRI + 4096)
ses.hazir(kd, cdir)
kontrol("tur8: ses.log LOG_SINIRI'nı aşınca hazir() keser (5 MB sınırı); günlük `ses/` DIŞINDA",
        os.path.getsize(log_) == 0 and not os.path.exists(os.path.join(dz, "ses.log")), str(os.path.getsize(log_)))

# -- (d) denetle-bağlan TOCTOU: soket_denetle'nin döndürdüğü yol denetlenen soketin SERT BAĞI; sunucu `native`'i sonradan
# sembolik bağla değiştirse bile bağlantı denetlenen (gerçek) sunucuya gider, tuzağa değil
dinleyici = Dinleyici(os.path.join(TZ, "native"))
ozel = ses.soket_denetle(cdir, kd)
kontrol("tur8 (d): soket_denetle Deskhand'in KENDİ dizinindeki (ses-istemci) sert bağı döndürür (aynı inode)",
        os.path.dirname(ozel) == ses.istemci_dizini(cdir) and _stat.S_ISSOCK(os.lstat(ozel).st_mode)
        and os.lstat(ozel).st_ino == os.lstat(ses.pulse_soketi(cdir)).st_ino, ozel)
nat = ses.pulse_soketi(cdir)
if SUNUCU_ICI:
    sunucu_icinden(f"import os; os.unlink({nat!r}); os.symlink({os.path.join(TZ, 'native')!r}, {nat!r})")
else:
    os.unlink(nat)
    os.symlink(os.path.join(TZ, "native"), nat)
kontrol("tur8 (d): `native` sembolik bağla değiştirildi (denetim sonrası saldırısı) ama denetlenen bağ HÂLÂ gerçek ses_pulse "
        "sürecine bağlanır; tuzak soketine bağlantı yok",
        os.path.islink(nat) and ao.soket_karsi_pid(ozel) == kd["pid"]["ses_pulse"] and dinleyici.sayac == 0,
        f"{os.path.islink(nat)} {ao.soket_karsi_pid(ozel)} {dinleyici.sayac}")
kontrol("tur8: `native` sembolik bağ → soket_hazir False, soket_denetle Dur 14, dinleme.kayit reddeder, uygulama bağı yok; "
        "tuzağa bağlantı YOK",
        not ses.soket_hazir(cdir) and dur_kodu(ses.soket_denetle, cdir, kd) == 14
        and dur_kodu(dinleme.kayit, cdir, 0.5) in (9, 14) and ao.ses_bagi(cdir) == [] and dinleyici.sayac == 0
        and ses.kaynaklar_ve_cikislar(cdir, kd) == ([], []), f"{dinleyici.sayac}")
env_t = {}
ao.ses_ortami_uygula(env_t, None, os.path.join(cdir, "run", "ses-yok"))
kontrol("tur8: bu durumda uygulama ortamı var olmayan yola gider (tuzak/sembolik bağ gösterilmez)",
        env_t["PULSE_SERVER"] == "unix:" + os.path.join(cdir, "run", "ses-yok"), str(env_t))
c_, u_, kd = sunucuyu_yeniden_kur()
kontrol("tur8: bozulan soketten sonra ses_hazirla sunucuyu yeniden kurar (hazir, uyarı yok); tuzak sayacı hâlâ 0",
        u_ is None and ses.hazir(kd, cdir) and dinleyici.sayac == 0 and not os.path.islink(ses.pulse_soketi(cdir)), str(u_))

# -- (iii) `ses-pulse` DİZİNİ sembolik bağla değiştirilirse (Deskhand tarafı sağlamlık; sunucu bunu yapamaz) uygulama gerçek
# soketleri/tuzağı görmez: bağ listesi boş, ortam var olmayan yol, dinleme reddeder
pd = ses.pulse_dizini(cdir)
os.rename(pd, pd + ".yedek")
os.symlink(TZ, pd)
kontrol("tur8 (iii): ses-pulse dizini sembolik bağ → soket_hazir False, ses_bagi boş, soket_denetle Dur 14, tuzağa bağlantı yok",
        not ses.soket_hazir(cdir) and ao.ses_bagi(cdir) == [] and dur_kodu(ses.soket_denetle, cdir, kd) == 14
        and dur_kodu(dinleme.kayit, cdir, 0.5) in (9, 14) and dinleyici.sayac == 0)
env_t = {}
ao.ses_ortami_uygula(env_t, None, os.path.join(cdir, "run", "ses-yok"))
kontrol("tur8 (iii): ses-pulse sembolik bağken uygulama ortamı tuzağı göstermez",
        env_t["PULSE_SERVER"] == "unix:" + os.path.join(cdir, "run", "ses-yok") and TZ not in str(env_t), str(env_t))
os.unlink(pd)
os.rename(pd + ".yedek", pd)
kontrol("tur8 (iii): dizin geri konunca sunucu yine hazır (bağlantı sürdü)", ses.hazir(kd, cdir))

# -- (iii) bağ listesi kurulduktan sonra dizin kimliği değişirse uygulama BAŞLAMAZ (bwrap bağından önce/sonra (dev,ino))
gercek_kimlik = ses.pulse_kimlik
sayac_ = [0]


def sahte_kimlik(esik):
    def f(c):
        sayac_[0] += 1
        return gercek_kimlik(c) if sayac_[0] <= esik else (0, 0)
    return f


ses.pulse_kimlik = sahte_kimlik(1)  # kimlik_kaydet gerçek; bağdan önceki denetimde "değişmiş"
try:
    k_once = dur_kodu(masaustu.baslat, ["true"])
finally:
    ses.pulse_kimlik = gercek_kimlik
kontrol("tur8 (iii): bağdan ÖNCE pulse dizini kimliği değişmişse uygulama başlamaz (Dur 14)", k_once == 14, str(k_once))
sayac_[0] = 0
ses.pulse_kimlik = sahte_kimlik(2)  # kaydet + önce gerçek; bağdan SONRA "değişmiş"
try:
    k_sonra = dur_kodu(masaustu.baslat, ["sleep", "30"])
finally:
    ses.pulse_kimlik = gercek_kimlik
kontrol("tur8 (iii): bağdan SONRA kimlik değişmişse uygulama öldürülür, Dur 14", k_sonra == 14, str(k_sonra))
p_ok = masaustu.baslat(["true"])
kontrol("tur8 (iii): kimlik aynıyken uygulama normal başlar", p_ok.wait(30) == 0)

# -- (a) `kur` yeniden: saldırgan sunucunun `ses/` içine koyduğu sembolik bağlar İZLENMEZ (rmtree + sıfırdan)
tuz = {ad: tuzak_dosya(ad) for ad in ("pw.conf", "pulse.conf", "ses.log", "bashrc-taklit")}
iz0 = {y: dosya_izi(y) for y in tuz.values()}
liste0 = sorted(os.listdir(TZ))
saldiri = {"pw.conf": tuz["pw.conf"], "pulse.conf": tuz["pulse.conf"], "ses.log": tuz["ses.log"],
           "ses_pw.log": tuz["bashrc-taklit"], "cfg/x-baglanti": tuz["bashrc-taklit"], "pulse": TZ,
           "pipewire-0.lock": tuz["bashrc-taklit"]}
kod_saldiri = "import os, shutil\n" + "".join(
    f"(shutil.rmtree if os.path.isdir({dz + '/' + ad!r}) and not os.path.islink({dz + '/' + ad!r}) else os.unlink)"
    f"({dz + '/' + ad!r}) if os.path.lexists({dz + '/' + ad!r}) else None\nos.symlink({hedef!r}, {dz + '/' + ad!r})\n"
    for ad, hedef in saldiri.items()) + \
    f"os.mkdir({dz + '/kilitli'!r}); open({dz + '/kilitli/dosya'!r}, 'w').write('x'); os.chmod({dz + '/kilitli'!r}, 0)\n"
if SUNUCU_ICI:
    r_ = sunucu_icinden(kod_saldiri)
    saldiri_ok = bool(r_ and r_[0] == 0)
else:
    for ad, hedef in saldiri.items():
        y = os.path.join(dz, ad)
        if os.path.isdir(y) and not os.path.islink(y):
            shutil.rmtree(y)
        elif os.path.lexists(y):
            os.unlink(y)
        os.symlink(hedef, y)
    os.mkdir(os.path.join(dz, "kilitli"))
    open(os.path.join(dz, "kilitli", "dosya"), "w").write("x")
    os.chmod(os.path.join(dz, "kilitli"), 0)
    saldiri_ok = True
kontrol("tur8 (a): saldırı hazır: ses/ içinde pw.conf/pulse.conf/ses.log/pulse sembolik bağları + 0000 izinli dizin",
        saldiri_ok and os.path.islink(os.path.join(dz, "pw.conf")) and os.path.islink(os.path.join(dz, "pulse")), str(saldiri_ok))
# sunucuyu öldür → ses_hazirla `kur`'u çalıştırır
eski_p = {a: kd["pid"][a] for a in ses.SURECLER}
os.kill(eski_p["ses_pw"], signal.SIGKILL)
bekle(lambda: not any(ao._canli(p) for p in eski_p.values()), 8)
c_, u_, kd = sunucuyu_yeniden_kur()
iz1 = {y: dosya_izi(y) for y in tuz.values()}
kontrol("tur8 (a): `kur` sembolik bağları İZLEMEDİ: tuzak dosyalar (scratchpad) bayt/mtime/inode aynı, tuzak dizinine dosya eklenmedi",
        iz0 == iz1 and sorted(os.listdir(TZ)) == liste0 and all(open(y).read() == "KORUNAN-ICERIK\n" for y in tuz.values()),
        str((iz0 == iz1, sorted(os.listdir(TZ)), liste0)))
kontrol("tur8 (a): yeni `ses/` sıfırdan: eski sembolik bağlar ve 0000 dizin silindi, sunucu yeniden kuruldu",
        u_ is None and ses.hazir(kd, cdir) and not any(os.path.lexists(os.path.join(dz, a)) for a in (
            "pw.conf", "pulse.conf", "ses.log", "kilitli", "pipewire-0.lock.eski"))
        and not os.path.islink(os.path.join(dz, "pulse")) and not os.path.islink(os.path.join(dz, "ses_pw.log"))
        and not os.path.lexists(os.path.join(dz, "cfg", "x-baglanti")), str(u_))
kontrol("tur8 (a)/(b): yapılandırma + günlük `ses-conf/`te, O_EXCL ile yeni gerçek dosyalar (sembolik bağ değil), 0600",
        all(_stat.S_ISREG(os.lstat(os.path.join(cf, a)).st_mode) and (os.lstat(os.path.join(cf, a)).st_mode & 0o777) == 0o600
            for a in ("pw.conf", "pulse.conf", "ses.log")))

# -- 2) yönetici kabuk: bir ses süreci ölünce hepsi ölür; bayat soket kalır ama hazir False; sonraki kurulum yeniden kurar
for olen in ("ses_pulse", "ses_wp"):
    p_ = {a: kd["pid"][a] for a in ses.SURECLER}
    os.kill(p_[olen], signal.SIGKILL)
    hepsi = bekle(lambda: not any(ao._canli(p) for p in p_.values()), 10)
    kontrol(f"tur8 (2): {olen} öldürülünce yönetici kabuk kalanları da kapatır (üç ses süreci de gitti)", hepsi,
            str({a: ao._canli(p) for a, p in p_.items()}))
    kontrol(f"tur8 (2): {olen} ölünce: hazir() False, masaustu.ses_var() False",
            not ses.hazir(masaustu.durum(), cdir) and not masaustu.ses_var())
    t = time.monotonic()
    c_, u_, kd = sunucuyu_yeniden_kur()
    olcum[f"ses sunucusu yeniden kurulum ({olen} ölünce)"] = f"{(time.monotonic() - t) * 1000:.0f} ms"
    yeni_p = {a: kd["pid"][a] for a in ses.SURECLER}
    kayit_ok = True
    try:
        dinleme.kayit(cdir, 0.6)
    except Dur:
        kayit_ok = False
    kontrol("tur8 (2): sonraki ses_hazirla/listen yolu sunucuyu yeniden kurdu (yeni PID'ler), kayıt çalışır",
            u_ is None and ses.hazir(kd, cdir) and set(p_.values()).isdisjoint(yeni_p.values()) and kayit_ok
            and masaustu.ses_var(), f"{u_} {p_} -> {yeni_p}")
if MOTOR_VAR:
    r = mcp_sunucu.listen(seconds=2, desktop="background", language="auto")
    kontrol("tur8 (2): listen (MCP) yeniden kurulmuş sunucuda çalışır (sessiz kayıt, boş metin)",
            r["status"] == "ok" and r["text"] == "", str(r))
dinleyici.kapat()
kontrol("tur8: tüm saldırı turlarında tuzak soketine HİÇ bağlantı gelmedi", dinleyici.sayac == 0, str(dinleyici.sayac))
dd = masaustu.durum()

# ---------------------------------------------------------------- 4) kapanış
pidler = [dd["pid"][ad] for ad in ses.SURECLER]
ok, notlar = masaustu.masaustu_durdur()
kontrol("kapanış: masaüstü kapandı", ok)
kontrol("kapanış: özel ses sunucusu süreçleri gitti", bekle(lambda: not any(ao._canli(p) for p in pidler), 8),
        str(pidler))
kontrol("kapanış: oturum dizini (soketler dahil) silindi", not os.path.exists(cdir))
kontrol("kapanış: ölçüm sonu, kullanıcının sunucusu değişmedi", gercek("list", "short", "modules") == once_modul)

print("\nÖLÇÜMLER:")
for k_, v_ in olcum.items():
    print(f"  {k_}: {v_}")
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
