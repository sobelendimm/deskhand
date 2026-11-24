"""0.9.1 Faz A (güvenilirlik) testleri: gerçek kullanımda görülen dört sorun.

  1. request_human / onay isteği: iptal edilen çağrı beklemeyi hemen bitirir (istek silinir, günlüğe yazılır); panel
     kapanınca/ölünce bekleme biter; sahibi ölmüş (PID yeniden kullanılmış dahil) ya da nabzı durmuş istek kilit
     tutmaz; Bitti / Vazgeç kapatır; panelin tepsi bildirimi tıklanınca YALNIZ diyaloğu öne getirme sinyali verir.
  2. Panel kimlik kaydı eskiyince (Python güncellendi → exe "(deleted)") panel kendisi tazeler; doktor nedeni söyler;
     başka canlı panelin kaydına dokunulmaz.
  3. Boştaki görünmez masaüstü [masaustu] bosta_kapat_dk sonra kapanır (Devral / bekleyen onay varken kapanmaz).
  4. Test yalıtımı: takım süreci SIGKILL ile ölse de GECICI'ye bağlı ayrık süreçler süpürülür.

Test süreci panel gibi davranır (kendi onay kanalı; gerçek panele DOKUNULMAZ); masaüstü sahte (durum/durdurma yerine
geçen işlevler); Qt görünmez (offscreen). Çalıştır:  python3 tests/test_faz_a_guvenilirlik.py"""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

import os
import signal
import subprocess
import sys
import threading
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("DESKHAND_GOZETIMSIZ", None)

from deskhand import doktor, masaustu, onay, yollar  # noqa: E402

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


def gunluk_metni() -> str:
    try:
        with open(os.path.join(yollar.gunluk_dizin(), time.strftime("gunluk-%Y%m%d.log"))) as f:
            return f.read()
    except OSError:
        return ""


def arka_plan(f, *a, **k):
    sonuc = {}

    def calis():
        sonuc["r"] = f(*a, **k)
    t = threading.Thread(target=calis, daemon=True)
    t.start()
    return t, sonuc


def istek_bekle(sure=5.0):
    son = time.monotonic() + sure
    while time.monotonic() < son:
        b = onay.bekleyenler()
        if b:
            return b[0]
        time.sleep(0.05)
    return None


def istek_yaz(pid, pid_bas=None, yas=0.0, tur="devir"):
    """Elle istek dosyası (sahibi/nabzı denetlenecek)."""
    import uuid
    k = uuid.uuid4().hex
    onay._dizin_hazirla()
    d = {"id": k, "eylem": "human_verification", "hedef": "t", "ayrinti": "", "masaustu": "arka", "zaman": time.time(),
         "son_zaman": time.time() + 600, "pid": pid, "goruntu": None, "masa": "", "tur": tur}
    if pid_bas is not None:
        d["pid_bas"] = pid_bas
    onay._yaz_atomik(onay.istek_yolu(k), d)
    if yas:
        t = time.time() - yas
        os.utime(onay.istek_yolu(k), (t, t))
    return k


# ============================================================ 1) onay / insan devri isteği
print("== 1) insan devri isteği")
onay.panel_kaydet()  # bu süreç panel gibi (kanal + kayıt)

# 1a: iptal edilen çağrı
iptal = threading.Event()
t, s = arka_plan(onay.iste_sonuc, "human_verification", "Sayfa", "doğrula", "arka", 60, tur="devir", iptal=iptal.is_set)
d = istek_bekle()
kontrol("1a: devir isteği bekleyenlerde (panelde görünür), tur=devir", d is not None and d["tur"] == "devir", str(d))
kontrol("1a: istek sahibin başlangıç zamanını taşır (PID yeniden kullanımına karşı)",
        d is not None and d.get("pid_bas") == onay._baslangic(os.getpid()), str(d))
kontrol("1a: beklerken başka süreçlerin girdisi kilitli (bekleyen_var)", onay.bekleyen_var("arka"))
t0 = time.monotonic()
iptal.set()
t.join(3)
r = s.get("r")
kontrol("1a: iptal → bekleme ≤1 sn'de biter, neden=iptal, izin YOK",
        r is not None and r.neden == "iptal" and not r.izin and time.monotonic() - t0 < 1.0, str(r))
kontrol("1a: iptal sonrası istek dosyası silindi ve kilit kalktı",
        d is not None and not os.path.exists(onay.istek_yolu(d["id"])) and not onay.bekleyen_var("arka"))
kontrol("1a: iptal günlüğe yazıldı (onay devir-iptal)", "onay devir-iptal" in gunluk_metni(), gunluk_metni()[-300:])

# 1b: Bitti (izin kanaldan) ve Vazgeç
for karar, beklenen, etiket in (("izin", "izin", "devir-tamam"), ("red", "red", "devir-red")):
    t, s = arka_plan(onay.iste_sonuc, "human_verification", "Sayfa", "doğrula", "arka", 60, tur="devir")
    d = istek_bekle()
    ok = d is not None and onay.yanitla(d["id"], karar)
    t.join(3)
    r = s.get("r")
    kontrol(f"1b: {'Bitti' if karar == 'izin' else 'Vazgeç'} → isteği kapatır ({beklenen}), günlükte {etiket}",
            ok and r is not None and r.neden == beklenen and f"onay {etiket}" in gunluk_metni()
            and not os.path.exists(onay.istek_yolu(d["id"])), str(r))

# 1c: panel kapanınca bekleme hemen biter
t, s = arka_plan(onay.iste_sonuc, "human_verification", "Sayfa", "doğrula", "arka", 60, tur="devir")
d = istek_bekle()
t0 = time.monotonic()
onay.panel_sil()
t.join(4)
r = s.get("r")
kontrol("1c: panel kapanınca bekleme ≤2 sn'de biter (panel-kapandi), istek silinir, günlükte",
        r is not None and r.neden == "panel-kapandi" and time.monotonic() - t0 < 2.0 and d is not None
        and not os.path.exists(onay.istek_yolu(d["id"])) and "onay devir-panel-kapandi" in gunluk_metni(), str(r))
onay.panel_kaydet()

# 1d: sahibi ölmüş / PID yeniden kullanılmış / nabzı durmuş istek kilit tutmaz
p = subprocess.Popen([sys.executable, "-c", "pass"])
p.wait()
k_olu = istek_yaz(p.pid)
k_reuse = istek_yaz(os.getpid(), pid_bas="1")  # canlı PID ama başka başlangıç zamanı
k_nabizsiz = istek_yaz(os.getpid(), pid_bas=onay._baslangic(os.getpid()), yas=onay.NABIZ_SINIR + 30)
kontrol("1d: sahibi ölmüş / PID yeniden kullanılmış / nabzı durmuş istekler bekleyen sayılmaz, kilit yok",
        onay.bekleyenler() == [] and not onay.bekleyen_var("arka"), str(onay.bekleyenler()))
silinen = onay.temizle()
kontrol("1d: temizle üçünü de siler", all(f"istek-{k}.json" in silinen for k in (k_olu, k_reuse, k_nabizsiz)),
        str(silinen))
k_taze = istek_yaz(os.getpid(), pid_bas=onay._baslangic(os.getpid()))
kontrol("1d: canlı sahip + taze nabız → bekleyen (kilit sürer)", onay.bekleyen_var("arka"))
onay._sil(onay.istek_yolu(k_taze))

# 1e: bekleme sürerken nabız (dosya dokunulur) isteği canlı tutar
eski_sinir = onay.NABIZ_SINIR
onay.NABIZ_SINIR = 2.0
try:
    iptal = threading.Event()
    t, s = arka_plan(onay.iste_sonuc, "human_verification", "Sayfa", "doğrula", "arka", 60, tur="devir",
                     iptal=iptal.is_set)
    istek_bekle()
    time.sleep(3.2)
    kontrol("1e: bekleyen isteğin nabzı atar (NABIZ_SINIR'dan uzun beklemede de görünür)", len(onay.bekleyenler()) == 1)
    iptal.set()
    t.join(3)
finally:
    onay.NABIZ_SINIR = eski_sinir

# 1f: MCP iptal edilebilir sarmalayıcı: istemci iptali iş parçacığındaki beklemeye ulaşır
from deskhand import mcp_sunucu  # noqa: E402

gordu = threading.Event()


def uzun_bekleyen():
    son = time.monotonic() + 10
    while time.monotonic() < son:
        if mcp_sunucu.cagri_iptal_edildi():
            gordu.set()
            return "iptal"
        time.sleep(0.02)
    return "sure"


import inspect  # noqa: E402

import anyio  # noqa: E402

sar = mcp_sunucu._iptalli_sarmala(uzun_bekleyen, inspect.signature(uzun_bekleyen))


async def iptal_et():
    with anyio.move_on_after(0.3):
        await sar()


t0 = time.monotonic()
anyio.run(iptal_et)
kontrol("1f: request_human sarmalayıcısı async (SDK iptal edebilir)", inspect.iscoroutinefunction(
    mcp_sunucu.request_human.mcp_sarili))
kontrol("1f: istemci iptali çekirdeğe ulaşır (cagri_iptal_edildi), ≤1,5 sn",
        gordu.wait(1.5) and time.monotonic() - t0 < 1.5)
kontrol("1f: doğrudan çağrıda (test/batch) iptal yok", not mcp_sunucu.cagri_iptal_edildi())
kontrol("1f: devir sonucu 'cancelled' durumu sözleşmede",
        "cancelled" in str(mcp_sunucu.DevirSonuc.__annotations__["status"]) and "iptal" in mcp_sunucu.DEVIR_NEDEN)

# 1g: panelin tepsi bildirimi (Qt görünmez): tıklama YALNIZ "diyaloğu öne getir" sinyali; karar üretmez
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from deskhand.gui.tepsi import Tepsi  # noqa: E402

tp = Tepsi()
gelen = []
tp.onay_istendi.connect(gelen.append)
kimlik = "a" * 32
tp.onay_bildir({"id": kimlik, "tur": "devir", "ayrinti": "Cloudflare doğrulaması"})
tp.ikon.messageClicked.emit()
kontrol("1g: tepsi bildirimine tıklama → onay_istendi(id) (panel diyaloğu öne getirir)", gelen == [kimlik], str(gelen))
kontrol("1g: tepsi bildirimi karar vermez (yanıt dosyası yok)", not os.path.exists(onay.yanit_yolu(kimlik)))
onay.panel_sil()

# ============================================================ 2) panel kimlik kaydı eskiyince
print("== 2) panel kimlik kaydı")
onay.panel_kaydet()
onay.liste_saglayici = lambda tur: "icerik-" + tur
kontrol("2a: taze kayıt → liste kanaldan gelir, tanı yok",
        onay.liste_iste("kimlik") == "icerik-kimlik" and onay.panel_kanal_tanisi() is None)
kayit = onay._json_oku(onay.panel_pid_yolu())
kayit["exe"] = kayit["exe"] + " (deleted)"  # Python güncellendi: kayıt (ya da süreç) artık eşleşmiyor
onay._yaz_atomik(onay.panel_pid_yolu(), kayit)
try:
    onay.liste_iste("kimlik")
    hata_ = ""
except onay._ListeYok as e:
    hata_ = str(e)
kontrol("2b: eski kayıt → liste reddedilir (doğrulama ZAYIFLAMADI)", "kimliği" in hata_, hata_)
tani = onay.panel_kanal_tanisi() or ""
kontrol("2b: tanı nedeni açıkça söyler ('panel kaydı eski', exe)", "panel kaydı eski" in tani and "exe" in tani, tani)
sp = doktor.satir_panel()
kontrol("2b: doktor Panel satırı uyarı + neden + yeniden başlatma önerisi",
        sp["durum"] == "uyari" and "panel kaydı eski" in sp["ayrinti"] and sp["oneri"], str(sp))
kontrol("2c: panel kendi kaydını tazeler", onay.panel_kaydi_tazele() == "tazelendi")
yeni = onay._json_oku(onay.panel_pid_yolu())
kontrol("2c: tazelenen kayıt YALNIZ bu sürecin canlı değerleri",
        yeni["pid"] == os.getpid() and yeni["exe"] == onay._exe(os.getpid())
        and yeni["baslangic"] == onay._baslangic(os.getpid()) and yeni["cmdline"] == onay._komut_satiri(os.getpid()))
kontrol("2c: tazelemeden sonra liste yeniden gelir, tanı temiz",
        onay.liste_iste("kimlik") == "icerik-kimlik" and onay.panel_kanal_tanisi() is None)
sp = doktor.satir_panel()
kontrol("2c: doktor 'kendiliğinden tazelendi' der", sp["durum"] == "tamam" and "tazelendi" in sp["ayrinti"], str(sp))
kontrol("2c: tazeleme günlüğe yazıldı", "panel kimlik kaydı tazelendi (exe)" in gunluk_metni())
kontrol("2d: güncel kayıtta tazeleme bir şey yapmaz", onay.panel_kaydi_tazele() == "ayni")
kontrol("2d: panel_kaydet periyodik tazeleyiciyi başlatır", onay._TAZELEYICI is not None)
# başka CANLI bir panelin kaydına dokunulmaz (ebeveyn süreç: canlı, başlangıç zamanı doğru)
pp = os.getppid()
baska = {"pid": pp, "baslangic": onay._baslangic(pp), "exe": onay._exe(pp), "cmdline": onay._komut_satiri(pp),
         "cwd": onay._cwd(pp), "paket": onay.paket_yolu(), "zaman": time.time()}
onay._yaz_atomik(onay.panel_pid_yolu(), baska)
kontrol("2e: başka canlı sürecin kaydı → 'baskasi', dosya değişmez",
        onay.panel_kaydi_tazele() == "baskasi" and onay._json_oku(onay.panel_pid_yolu()) == baska)
onay._sil(onay.panel_pid_yolu())
kontrol("2f: kayıt silinmişse panel yeniden kaydolur",
        onay.panel_kaydi_tazele() == "tazelendi" and onay.panel_pid() == os.getpid())
onay.panel_sil()
kontrol("2g: panel_sil tazeleyiciyi durdurur", onay._TAZELEYICI is None)
onay.liste_saglayici = None

# ============================================================ 3) boştaki görünmez masaüstü
print("== 3) boştaki görünmez masaüstü")
from deskhand import ayarlar, masalar  # noqa: E402

masalar.kok_hazirla("")
sahte_durum = {"tur": "kwin", "ad": ""}
durdurulan = []
gercek = (masaustu.durum, masaustu.masaustu_durdur, masaustu.devral_var)
devral = [False]
masaustu.durum = lambda dogrula=True, saglik=True, ad=None: dict(sahte_durum) if sahte_durum is not None else None
masaustu.masaustu_durdur = lambda ad=None: (durdurulan.append(ad), (True, []))[1]
masaustu.devral_var = lambda yol=None: devral[0]
try:
    with open(masalar.durum_yolu(""), "w") as f:
        f.write("{}")
    masaustu.kullanim_isaretle("", zorla=True)
    kontrol("3a: varsayılan 30 dk", masaustu.bosta_kapat_dk() == 30)
    kontrol("3a: yeni kullanılmış masaüstü kapanmaz", masaustu.bosta_neden("") == "kullaniliyor" and
            not masaustu.bosta_kapat("") and durdurulan == [])
    gelecek = time.time() + 31 * 60
    kontrol("3b: 31 dk kullanılmadı → kapanır", masaustu.bosta_kapat("", simdi=gelecek) and durdurulan == [""])
    kontrol("3b: kapanış günlüğe yazıldı", "boşta kaldı: kapatıldı" in gunluk_metni())
    durdurulan.clear()
    devral[0] = True
    kontrol("3c: Devral açıkken (insan çalışıyor) kapanmaz",
            masaustu.bosta_neden("", simdi=gelecek) == "devral" and not masaustu.bosta_kapat("", simdi=gelecek))
    devral[0] = False
    onay.panel_kaydet()
    iptal = threading.Event()
    t, s = arka_plan(onay.iste_sonuc, "human_verification", "Sayfa", "doğrula", "arka", 60, tur="devir",
                     iptal=iptal.is_set)
    istek_bekle()
    kontrol("3d: bekleyen devir isteği varken kapanmaz", masaustu.bosta_neden("", simdi=gelecek) == "onay")
    iptal.set()
    t.join(3)
    onay.panel_sil()
    sahte_durum["gorev"] = True
    kontrol("3e: görev kipindeki masaüstü kapanmaz", masaustu.bosta_neden("", simdi=gelecek) == "gorev")
    sahte_durum.pop("gorev")
    os.makedirs(yollar.config_dir(), exist_ok=True)
    with open(ayarlar.dosya(), "w") as f:
        f.write("[masaustu]\nbosta_kapat_dk = 0\n")
    kontrol("3f: bosta_kapat_dk = 0 → kapatma kapalı", masaustu.bosta_kapat_dk() == 0 and
            masaustu.bosta_neden("", simdi=gelecek) == "kapali")
    with open(ayarlar.dosya(), "w") as f:
        f.write("[masaustu]\nbosta_kapat_dk = 5\n")
    kontrol("3f: ayar dakikası uygulanır (5 dk)", masaustu.bosta_neden("", simdi=time.time() + 6 * 60) is None)
    os.remove(ayarlar.dosya())
    # kullanım işareti: sıklık sınırı ve panel süreci istisnası
    yol = masaustu.kullanim_yolu("")
    os.utime(yol, (1, 1))
    masaustu._SON_ISARET.clear()
    onay.panel_kaydet()  # bu süreç artık panel: önizleme yoklaması masaüstünü açık tutmasın
    masaustu.kullanim_isaretle()
    kontrol("3g: panel sürecinin bağlantıları kullanım sayılmaz", os.stat(yol).st_mtime < 10)
    masaustu.kullanim_isaretle(zorla=True)
    kontrol("3g: açık kullanıcı kullanımı (zorla) sayılır", time.time() - os.stat(yol).st_mtime < 5)
    onay.panel_sil()
    os.utime(yol, (1, 1))
    masaustu._SON_ISARET.clear()
    masaustu.kullanim_isaretle()
    ilk = os.stat(yol).st_mtime
    os.utime(yol, (1, 1))
    masaustu.kullanim_isaretle()
    kontrol("3g: ajan kullanımı sayılır, sık çağrıda seyrek yazılır", ilk > 10 and os.stat(yol).st_mtime < 10)
    # MCP bekçisi: yalnız sahibi olduğu masaüstü, araç çalışırken atlar
    mcp_sunucu._MASA.update(bagli=True, ad="", sahip=True)
    os.utime(yol, (1, 1))
    os.utime(masalar.durum_yolu(""), (1, 1))
    durdurulan.clear()
    with mcp_sunucu.kilitli():
        atla = mcp_sunucu.bosta_denetle()
    kontrol("3h: MCP bekçisi araç sürerken (KILIT) atlar", atla is False and durdurulan == [])
    kontrol("3h: MCP bekçisi boştaki kendi masaüstünü kapatır", mcp_sunucu.bosta_denetle() and durdurulan == [""])
    mcp_sunucu._MASA.update(sahip=False)
    durdurulan.clear()
    kontrol("3h: sahibi olmadığı (paylaşılan) masaüstüne dokunmaz", not mcp_sunucu.bosta_denetle() and durdurulan == [])
    mcp_sunucu._MASA.update(bagli=False)
finally:
    masaustu.durum, masaustu.masaustu_durdur, masaustu.devral_var = gercek

# ============================================================ 4) test yalıtımı: süreç sızıntısı
print("== 4) test yalıtımı süreç süpürme")
COCUK = r"""
import os, subprocess, sys
sys.path.insert(0, sys.argv[1])
import _yalitim
p = subprocess.Popen(["sleep", "300"], start_new_session=True, stdin=subprocess.DEVNULL)  # ayrık 'masaüstü süreci'
print(p.pid, _yalitim.GECICI, flush=True)
if sys.argv[2] == "kill":
    os.kill(os.getpid(), 9)
"""
for kip in ("kill", "normal"):
    c = subprocess.run([sys.executable, "-c", COCUK, os.path.join(_yalitim.KOK, "tests"), kip], capture_output=True,
                       text=True, timeout=30)
    try:
        pid_s, gecici = c.stdout.split()
        pid = int(pid_s)
    except ValueError:
        kontrol(f"4: çocuk takım çıktı verdi ({kip})", False, c.stdout + c.stderr)
        continue
    son = time.monotonic() + 10
    while time.monotonic() < son and (os.path.exists(f"/proc/{pid}") or os.path.exists(gecici)):
        time.sleep(0.1)
    canli = os.path.exists(f"/proc/{pid}")
    if canli:  # yalnız bu testin kendi sleep'i
        os.kill(pid, signal.SIGKILL)
    kontrol(f"4: takım {'SIGKILL ile öldü' if kip == 'kill' else 'normal bitti'} → ayrık süreci süpürüldü, "
            f"geçici dizini silindi", not canli and not os.path.exists(gecici), f"canlı={canli}")
kontrol("4: bu takımın GECICI'sine bağlı başka süreç yok (bekçi hariç)", _yalitim.gecici_surecleri() == [],
        str(_yalitim.gecici_surecleri()))

print(f"\n{GECEN}/{TOPLAM} Faz A güvenilirlik testi geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
