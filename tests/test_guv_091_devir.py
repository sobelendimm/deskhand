"""0.9.1 security fixes, branch X: human handoff (request_human) and the approval channel.

Each section reproduces one audit finding with a test that failed before the fix:
  1. Heartbeat / cross-process input lock: a live request whose owner is alive is never treated as dead (heartbeat from
     a separate thread, liveness from pid + start time, not only the file mtime); the requester stops waiting when its
     request file is removed.
  2. Cancel vs. resolved: a cancelled call never returns `resolved` and never suppresses the challenge guard.
  3. Pre-wait: the handoff input lock is set before the first poll; a "cleared" candidate is bound to the same document
     (query/fragment change = different document: not counted).
  4. Panel record refresh vs. shutdown: a refresh that already started cannot reopen the socket / rewrite panel.pid
     after panel_sil.

The test process acts as the panel (own approval channel; the real panel is NOT touched); no input, no screen.
Run:  python3 tests/test_guv_091_devir.py"""
import _yalitim  # noqa: F401  (DESKHAND_* temp dirs; before deskhand)

import os
import subprocess
import sys
import threading
import time

os.environ.pop("DESKHAND_GOZETIMSIZ", None)

from deskhand import dogrulama_sinamasi as ds  # noqa: E402
from deskhand import mcp_sunucu, onay  # noqa: E402

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


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


onay.panel_kaydet()

# ============================================================ 1) heartbeat / liveness
print("== 1) nabız ve süreçler arası girdi kilidi")
eski_sinir = onay.NABIZ_SINIR
onay.NABIZ_SINIR = 1.5
try:
    # 1a: the `kontrol` callback blocks (in-process lock wait) longer than NABIZ_SINIR: the request must stay pending
    birak = threading.Event()

    def yavas_kontrol():
        birak.wait(6)
        return False
    iptal1 = threading.Event()
    t, s = arka_plan(onay.iste_sonuc, "human_verification", "Sayfa", "doğrula", "arka", 60, tur="devir",
                     kontrol=yavas_kontrol, iptal=iptal1.is_set)
    d = istek_bekle()
    time.sleep(onay.KONTROL_ARALIK + onay.NABIZ_SINIR + 1.0)  # kontrol is now blocked past the heartbeat limit
    gorunur = len(onay.bekleyenler()) == 1 and onay.bekleyen_var("arka")
    silinen = onay.temizle()
    kontrol("1a: kontrol takılı kalsa da canlı istek bekleyen sayılır (kilit düşmez)", gorunur)
    kontrol("1a: temizle canlı isteği silmez", d is not None and f"istek-{d['id']}.json" not in silinen, str(silinen))
    birak.set()
    iptal1.set()
    t.join(5)

    # 1b: mtime pushed into the past by another process: owner alive → still pending
    iptal2 = threading.Event()
    t, s = arka_plan(onay.iste_sonuc, "human_verification", "Sayfa", "doğrula", "arka", 60, tur="devir",
                     iptal=iptal2.is_set)
    d = istek_bekle()
    os.utime(onay.istek_yolu(d["id"]), (1, 1))
    kontrol("1b: başka süreç nabzı eskitse de (mtime=1) sahibi canlı istek bekleyen kalır",
            len(onay.bekleyenler()) == 1 and onay.bekleyen_var("arka"))
    kontrol("1b: temizle onu silmez", f"istek-{d['id']}.json" not in onay.temizle())

    # 1c: request file removed (e.g. by another process' cleanup): requester stops waiting
    t0 = time.monotonic()
    onay._sil(onay.istek_yolu(d["id"]))
    t.join(3)
    r = s.get("r")
    kontrol("1c: istek dosyası silinince isteyen ≤2 sn'de beklemeyi bırakır, izin YOK",
            r is not None and not r.izin and time.monotonic() - t0 < 2.0, str(r))
    iptal2.set()

    # 1d: owner stopped (SIGSTOP) and no heartbeat: not pending (frozen process does not hold the lock forever)
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        time.sleep(0.2)
        os.kill(p.pid, 19)  # SIGSTOP
        time.sleep(0.2)
        import uuid
        k = uuid.uuid4().hex
        onay._yaz_atomik(onay.istek_yolu(k), {
            "id": k, "eylem": "x", "hedef": "t", "ayrinti": "", "masaustu": "arka", "zaman": time.time(),
            "son_zaman": time.time() + 600, "pid": p.pid, "pid_bas": onay._baslangic(p.pid), "goruntu": None,
            "masa": "", "tur": "devir"})
        os.utime(onay.istek_yolu(k), (1, 1))
        kontrol("1d: durdurulmuş (SIGSTOP) sahip + nabız yok → bekleyen değil", onay.bekleyenler() == [])
        onay._sil(onay.istek_yolu(k))
    finally:
        p.kill()
        p.wait()
finally:
    onay.NABIZ_SINIR = eski_sinir

# ============================================================ 2) cancel vs. resolved (onay core)
print("== 2) iptal ile karar yarışı")
durum = {"iptal": False, "gonderildi": False}


def iptal_yaris():
    # the client cancels right AFTER this check; the panel's "Done" is already on the channel at the next poll
    if not durum["gonderildi"]:
        b = onay.bekleyenler()
        if b and onay.yanitla(b[0]["id"], "izin", gosterilen=b[0]["_iz"]):
            durum["gonderildi"] = True
            durum["iptal"] = True
            return False
    return durum["iptal"]


t, s = arka_plan(onay.iste_sonuc, "human_verification", "Sayfa", "doğrula", "arka", 30, tur="devir",
                 iptal=iptal_yaris)
t.join(8)
r = s.get("r")
kontrol("2a: iptal edilmiş çağrı, kanalda hazır 'izin' olsa da iptal döner (izin YOK)",
        durum["gonderildi"] and r is not None and not r.izin and r.neden == "iptal", str(r))

# ============================================================ 2/3) request_human core (_devir_yurut, stubs)
print("== 2/3) request_human: iptal, ön bekleme kilidi, aynı belge")


class _Arka:
    ad = "sanal"


class _SahteOnay:
    def __init__(self, f):
        self.f = f

    def iste_sonuc(self, *a, **k):
        return self.f(*a, **k)

    def panel_canli(self):
        return False


K = "arka:guv1"
_eski = {n: getattr(mcp_sunucu, n) for n in ("_sinama_oku", "_baslik_simdi", "_onay")}
_eski_arka, _eski_son_adres, _eski_bastir = mcp_sunucu.api.arka, ds.son_adres, ds.bastir
_eski_on_bekle = mcp_sunucu.ON_BEKLE_SN
SINAMA = {"kind": "turnstile", "imza": "imza1", "site": "s.test", "window": "w", "hint": "h"}
olay = {"adres": [], "sinama": [], "kilit": [], "bastir": []}


def sahne(adresler, sinamalar):
    """adresler/sinamalar: one value per _sinama_oku call (last value repeats)."""
    olay.update(adres=list(adresler), sinama=list(sinamalar), kilit=[], bastir=[], son="")
    mcp_sunucu._SON_DEVIR_RED.clear()  # a previous scene's timeout must not trigger the 60 s re-request block

    def oku(k):
        olay["kilit"].append(mcp_sunucu.onay_bekliyor_mu("sanal"))
        a = olay["adres"].pop(0) if len(olay["adres"]) > 1 else olay["adres"][0]
        sn = olay["sinama"].pop(0) if len(olay["sinama"]) > 1 else olay["sinama"][0]
        olay["son"] = a
        return (dict(sn) if sn else None), True
    mcp_sunucu._sinama_oku = oku
    ds.son_adres = lambda k: olay["son"]


mcp_sunucu.api.arka = lambda: _Arka()
mcp_sunucu._baslik_simdi = lambda k: "Sayfa"
ds.bastir = lambda k, imza, simdi=None: olay["bastir"].append(imza)
mcp_sunucu.ON_BEKLE_SN = 1.0
SURE = onay.OnaySonucu(False, "sure", "x")
try:
    # 3a: pre-wait — agent changes only the query of the same path; the challenge marker vanishes
    sahne(["https://s.test/p?a=1", "https://s.test/p?a=2"], [SINAMA, None])
    mcp_sunucu._onay = lambda: _SahteOnay(lambda *a, **k: SURE)
    s3 = mcp_sunucu._devir_yurut(K, "doğrula", 10, {})
    kontrol("3a: ön beklemede sorgu değişip işaret kaybolursa resolved SAYILMAZ",
            s3.get("status") != "resolved", str(s3))
    kontrol("3a: devir girdi kilidi İLK yoklamadan önce kurulu", bool(olay["kilit"]) and all(olay["kilit"]),
            str(olay["kilit"]))
    kontrol("3a: devir bitince kilit kalkar", not mcp_sunucu.onay_bekliyor_mu("sanal"))
    # 3b: same document, challenge gone by itself → still resolved/challenge_cleared (no regression)
    sahne(["https://s.test/p?a=1"], [SINAMA, None])
    s3 = mcp_sunucu._devir_yurut(K, "doğrula", 10, {})
    kontrol("3b: aynı belgede işaret kaybolursa challenge_cleared",
            s3.get("status") == "resolved" and s3.get("resolved_by") == "challenge_cleared", str(s3))
    # 3c: Cloudflare challenge token in the query is not part of the document identity
    sahne(["https://s.test/p?__cf_chl_rt_tk=abc", "https://s.test/p"], [SINAMA, None])
    s3 = mcp_sunucu._devir_yurut(K, "doğrula", 10, {})
    kontrol("3c: yalnız Cloudflare sınama belirteci kalkınca aynı belge (challenge_cleared)",
            s3.get("status") == "resolved" and s3.get("resolved_by") == "challenge_cleared", str(s3))
    # 3d: fragment change during the wait (iste_sonuc kontrol path) is not counted either
    def kontrollu(*a, **k):
        for _i in range(4):
            if k["kontrol"]():
                return onay.OnaySonucu(False, "kosul", "x")
        return SURE
    sahne(["https://s.test/p#a", "https://s.test/p#a", "https://s.test/p#b"], [{**SINAMA, "kind": "recaptcha"}, None])
    mcp_sunucu._onay = lambda: _SahteOnay(kontrollu)
    s3 = mcp_sunucu._devir_yurut(K, "doğrula", 10, {})
    kontrol("3d: beklemede parça (#) değişip işaret kaybolursa resolved SAYILMAZ", s3.get("status") != "resolved",
            str(s3))

    # 2b: cancel set while the panel's Done arrives → cancelled, no suppression
    olay_iptal = threading.Event()
    mcp_sunucu._IPTAL_YEREL.olay = olay_iptal

    def bitti_ve_iptal(*a, **k):
        olay_iptal.set()
        return onay.OnaySonucu(True, "izin", "x")
    sahne(["https://s.test/p"], [{**SINAMA, "kind": "recaptcha"}])
    mcp_sunucu._onay = lambda: _SahteOnay(bitti_ve_iptal)
    s2 = mcp_sunucu._devir_yurut(K, "doğrula", 10, {})
    kontrol("2b: iptal edilmiş çağrı resolved dönmez (cancelled)", s2.get("status") == "cancelled", str(s2))
    kontrol("2b: iptal edilmiş çağrı sınama korumasını bastırmaz", olay["bastir"] == [], str(olay["bastir"]))
    # 2c: pre-wait — challenge cleared on the same document but the call is already cancelled
    olay_iptal.set()
    sahne(["https://s.test/p"], [SINAMA, None])
    mcp_sunucu._onay = lambda: _SahteOnay(lambda *a, **k: SURE)
    s2 = mcp_sunucu._devir_yurut(K, "doğrula", 10, {})
    kontrol("2c: ön beklemede iptal edilmiş çağrı resolved dönmez", s2.get("status") == "cancelled", str(s2))
    mcp_sunucu._IPTAL_YEREL.olay = None
finally:
    for n, v in _eski.items():
        setattr(mcp_sunucu, n, v)
    mcp_sunucu.api.arka, ds.son_adres, ds.bastir = _eski_arka, _eski_son_adres, _eski_bastir
    mcp_sunucu.ON_BEKLE_SN = _eski_on_bekle
    mcp_sunucu._IPTAL_YEREL.olay = None

# ============================================================ 4) panel record refresh vs. shutdown
print("== 4) panel kaydı tazeleme ile kapanış yarışı")
onay.panel_kaydet()
kayit = onay._json_oku(onay.panel_pid_yolu())
onay._yaz_atomik(onay.panel_pid_yolu(), {**kayit, "exe": "/eski/python (deleted)"})  # stale → refresh rewrites
icerde, devam = threading.Event(), threading.Event()
_eski_fark = onay.kayit_farki


def yavas_fark(d):
    icerde.set()
    devam.wait(5)
    return _eski_fark(d)


onay.kayit_farki = yavas_fark
try:
    t_taz, _s = arka_plan(onay.panel_kaydi_tazele)
    icerde.wait(3)
    t_sil, _s2 = arka_plan(onay.panel_sil)
    time.sleep(0.3)
    devam.set()
    t_taz.join(5)
    t_sil.join(5)
finally:
    onay.kayit_farki = _eski_fark
kontrol("4a: kapanıştan sonra panel.pid yok (başlamış tazeleme yeniden yazmadı)",
        not os.path.exists(onay.panel_pid_yolu()))
kontrol("4a: kapanıştan sonra onay kanalı soketi yok/kapalı",
        onay._KANAL is None and not os.path.exists(onay.kanal_yolu()))
kontrol("4b: kapanıştan sonra tazeleme yeniden kaydolmaz", onay.panel_kaydi_tazele() != "tazelendi"
        and not os.path.exists(onay.panel_pid_yolu()))
kontrol("4c: kapanışta tazeleyici iş parçacığı beklendi (durdu)",
        not any(t.name == "panel-kayit-tazele" and t.is_alive() for t in threading.enumerate()))

print(f"\n{GECEN}/{TOPLAM} geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
