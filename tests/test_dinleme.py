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
sinks, sources = ses.kaynaklar_ve_cikislar(dz)
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
kontrol("ses: PipeWire soketleri yalnız `ses/`, pulse soketi ayrı `ses/pulse/` dizininde",
        os.path.exists(os.path.join(dz, ses.PW_SOKET)) and sorted(os.listdir(ses.pulse_dizini(cdir)))[:1] == ["native"]
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
kontrol("(b) GÜVENLİK: ad alanında `ses/` içinde yalnız `pulse/` (PipeWire soketi, yapılandırma, günlük GÖRÜNMEZ); pulse dizininde yalnız native",
        o.get("ses_dizini_ls") in ([], ["pulse"]) and o.get("pw_soketi_gorunur") is False
        and o.get("pulse_dizini_ls", [""])[:1] == ["native"] and not any("pipewire" in f for f in o.get("pulse_dizini_ls", [])),
        str((o.get("ses_dizini_ls"), o.get("pw_soketi_gorunur"), o.get("pulse_dizini_ls"))))
kontrol("(b) GÜVENLİK: pw-cli / pw-dump PipeWire'a bağlanamaz (varsayılan, açık yol, -manager)",
        all(ok_(k) for k in ("pw_cli", "pw_cli_acik", "pw_cli_yonetici", "pw_dump")),
        str({k: o.get(k) for k in ("pw_cli", "pw_cli_acik", "pw_cli_yonetici", "pw_dump")})[:600])
# /run/user/UID ad alanında boş tmpfs; yalnız arka_ortak.sir_bos_hedefler'in açtığı BOŞ özel dizinler (ör. psd: tarayıcı
# profil bağlarının hedefi) bulunabilir — gerçek oturum soketi/dizini değil
_izinli = {os.path.relpath(h, f"/run/user/{os.getuid()}").split("/")[0]
           for h in ao.sir_bos_hedefler() if h.startswith(f"/run/user/{os.getuid()}/")}
kontrol("GÜVENLİK: ad alanında kullanıcının GERÇEK pulse/pipewire soketi yok (/run/user/UID yalnız boş özel dizinler)",
        o.get("gercek_pulse") is False and o.get("gercek_pw") is False
        and set(o.get("runtime_ls") or []) <= _izinli, str((o.get("runtime_ls"), sorted(_izinli))))
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
