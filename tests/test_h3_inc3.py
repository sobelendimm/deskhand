"""H3 third security review (kart-DHG rapor-H3-inceleme-3.md): red tests from the PoCs (INC3/poc_*.py).

B1  panel start, wallet unreadable: a loosened yasak/seviye is never applied silently. One combined question with the
    file content (default No). No / no answer → the lists are "not verified": clients get Dur 10, a visible reason;
    when the wallet becomes readable the panel restores the signed value and checks again.
B2  a Yes is not cached: a site the user removed in Settings and the agent writes back is ASKED again.
B3  the requester sends the sha256 of the request bytes it wrote (`bekle <id> <sha256>`); a request swapped before the
    panel showed it (or a second, different hash for the same id) is refused, visibly.
B4  the user's DUR survives a panel restart (kept in the panel's signed state, restored at start).
B5  a refused Yes does not close the dialog as "izin".
No real wallet (fake key ring), no real ~/.config (tests/_yalitim). Run: python3 tests/test_h3_inc3.py"""
import glob
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid

import _yalitim  # noqa: F401  (before deskhand)

from deskhand import ayarlar, guvenlik, liste_koruma as lk, onay  # noqa: E402
from deskhand.hata import Dur, dur_dosyasi  # noqa: E402
from deskhand.oturum import kalici  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


class Kasa:
    """Fake Secret Service item of the panel; `kilitli` = locked wallet."""

    def __init__(self):
        self.veri = None
        self.kilitli = False

    def oku(self):
        if self.kilitli:
            raise kalici.AnahtarYok("cüzdan kilitli")
        return self.veri

    def yaz(self, v):
        if self.kilitli:
            raise kalici.AnahtarYok("cüzdan kilitli")
        self.veri = v


KASA = Kasa()
lk.isaret_anahtarlik_ayarla(KASA)
SORULAN: list = []
UYARILAR: list = []
CEVAP = {"v": False}


def sor(tur, aciklama):
    SORULAN.append((tur, aciklama))
    return CEVAP["v"]


def onayla(siteler):
    SORULAN.append(("kalici", list(siteler)))
    return CEVAP["v"]


def panel_ac(cevap=False):
    SORULAN.clear()
    UYARILAR.clear()
    CEVAP["v"] = cevap
    lk.panel_durdur()
    lk._anahtar_unut()
    onay.panel_kaydet()
    return lk.panel_baslat(UYARILAR.append, onayla, sor)


def panel_kapat():
    lk.panel_durdur()
    onay.panel_sil()


def istemci_yasak():
    """What a client process gets for `yasak` while the panel is open (the verified channel; AKTIF is the panel's
    in-process shortcut, so it is hidden for the call)."""
    aktif, lk.AKTIF = lk.AKTIF, None
    lk.onbellek_sil()
    try:
        return lk.metin("yasak")
    except Dur as e:
        return f"Dur {e.kod}"
    finally:
        lk.AKTIF = aktif


ONAYLI = "KeePassXC\n^Online Banking\n"
SAHTE = "# emptied by agent\n"
YASAK = lk.dosya("yasak")
os.makedirs(os.path.dirname(YASAK), exist_ok=True)

# setup: the user approved ONAYLI in the panel (signed in the wallet item)
k = panel_ac()
k.kaydet("yasak", ONAYLI)
panel_kapat()
kontrol("hazırlık: onaylı değer cüzdanda", lk.onayli_deger("yasak") == (True, ONAYLI), repr(lk.onayli_deger("yasak")))

# ================================================================ B1 (PoC A): marks deleted + wallet locked
open(YASAK, "w").write(SAHTE)
for y in glob.glob(os.path.join(os.path.dirname(lk.isaret_yolu("yasak")), "liste-*.isaret")):
    os.remove(y)
KASA.kilitli = True
k = panel_ac(False)
sorulan_yasak = [a for t, a in SORULAN if "yasak" in t]
v = istemci_yasak()
kontrol("B1-A: işaretler silindi + cüzdan kilitli → soru ya da Dur; istemci boş listeyi ALMAZ",
        (sorulan_yasak or v == "Dur 10") and v != SAHTE, f"sorulan={SORULAN} istemci={v!r}")
kontrol("B1-A: tek birleşik soru (yasak + seviye birlikte), dosya içeriğiyle",
        len(SORULAN) == 1 and "yasak" in SORULAN[0][0] and "seviye" in SORULAN[0][0] and "emptied" in SORULAN[0][1],
        str(SORULAN))
kontrol("B1-A: Hayır → istemci Dur 10", v == "Dur 10", repr(v))
kontrol("B1-A: Hayır → görünür neden (cüzdan okunamıyor; listeler doğrulanamadı)",
        any("listeler doğrulanamadı" in u for u in UYARILAR), str(UYARILAR))
kontrol("B1-A: 'dosyadaki değer kullanılıyor' uyarısı yok", not any("dosyadaki değer kullanılıyor" in u for u in UYARILAR),
        str(UYARILAR))
# the wallet opens: the panel restores the signed value and checks again (no question: the file is restored)
KASA.kilitli = False
k.KASA_YENIDEN_SN = 0
SORULAN.clear()
CEVAP["v"] = False
k.denetle()
v = istemci_yasak()
kontrol("B1: cüzdan açılınca imzalı değer geri yüklenir, istemci onaylı listeyi alır", v == ONAYLI, repr(v))
kontrol("B1: geri yükleme dosyaya yazıldı", open(YASAK).read() == ONAYLI, repr(open(YASAK).read()))
panel_kapat()

# ================================================================ B1 (PoC B): marks kept, forged mark == forged file
open(YASAK, "w").write(SAHTE)
with open(lk.isaret_yolu("yasak"), "w") as f:
    json.dump({"sha256": lk._ozet(SAHTE), "icerik": SAHTE, "var": True}, f)
KASA.kilitli = True
k = panel_ac(False)
v = istemci_yasak()
kontrol("B1-B: Hayır sonrası gevşek değer YÜRÜRLÜKTE DEĞİL (istemci Dur 10)", v == "Dur 10", repr(v))
kontrol("B1-B: yanıltıcı 'son kaydı geri yüklendi' uyarısı yok", not any("geri yüklendi" in u for u in UYARILAR),
        str(UYARILAR))
panel_kapat()

# B1: Yes → applied, signed once the wallet can be read
open(YASAK, "w").write("Yeni\n")
k = panel_ac(True)
v = istemci_yasak()
kontrol("B1: Evet → dosyadaki liste uygulanır", v == "Yeni\n" and len(SORULAN) == 1, f"{v!r} {SORULAN}")
KASA.kilitli = False
k.KASA_YENIDEN_SN = 0
k.denetle()
lk._anahtar_unut()
kontrol("B1: Evet'teki değer cüzdan okunur olunca imzalanır", lk.onayli_deger("yasak") == (True, "Yeni\n") and
        lk.isaret_dogrula("yasak") == ("gecerli", "Yeni\n"), repr(lk.onayli_deger("yasak")))
panel_kapat()

# B1: no question callback (no GUI) → Dur 10
KASA.kilitli = True
open(YASAK, "w").write(SAHTE)
lk._anahtar_unut()
onay.panel_kaydet()
k = lk.panel_baslat(UYARILAR.append, None, None)
kontrol("B1: yanıt yok (arayüz yok) → Dur 10", istemci_yasak() == "Dur 10")
panel_kapat()
KASA.kilitli = False
k = panel_ac(True)
k.kaydet("yasak", ONAYLI)
panel_kapat()

# ================================================================ B2: a Yes is not replayed
k = panel_ac(True)
ayarlar.ayarla("oturum", "kalici", "ajan.test")
k.denetle()
kontrol("B2: kullanıcı Evet → site eklendi", k.metin(lk.KALICI) == "ajan.test", repr(k.metin(lk.KALICI)))
k.kalici_kaydet("")  # the user removes it in the panel's Settings
CEVAP["v"] = False
SORULAN.clear()
ayarlar.ayarla("oturum", "kalici", "ajan.test")  # the agent writes it back
k.denetle()
kontrol("B2: kaldırılan site ajan yeniden yazınca SORULUR", ("kalici", ["ajan.test"]) in SORULAN and
        k.metin(lk.KALICI) == "", f"{SORULAN} {k.metin(lk.KALICI)!r}")
SORULAN.clear()
for _i in range(3):
    k.denetle()
kontrol("B2: Hayır önbellekte: aynı içerik yeniden sorulmaz (soru yağmuru yok)", SORULAN == [], str(SORULAN))
panel_kapat()

# ================================================================ B3: the approval is bound to what the requester wrote
onay.panel_kaydet()
REDLER: list = []
onay.onay_reddedildi = REDLER.append
os.makedirs(onay.dizin(), mode=0o700, exist_ok=True)


def istek_bytes(i, eylem):
    d = {"id": i, "eylem": eylem, "hedef": "Firefox", "ayrinti": "", "masaustu": "ekran", "zaman": time.time(),
         "son_zaman": time.time() + 60, "pid": os.getpid()}
    return json.dumps(d, ensure_ascii=False).encode()


def yaz(i, ham):
    with open(onay.istek_yolu(i), "wb") as f:
        f.write(ham)


def baglan(i, sha):
    c = socket.socket(socket.AF_UNIX)
    c.connect(onay.kanal_yolu())
    c.sendall(f"bekle {i} {sha}\n".encode() if sha else f"bekle {i}\n".encode())
    c.settimeout(3)
    time.sleep(0.2)  # the panel thread reads the line
    return c


def al(c):
    try:
        return c.recv(200).decode()
    except OSError as e:
        return f"hata {e}"
    finally:
        c.close()


# A) swapped BEFORE the panel read: the requester's hash does not match the file → refused at once
i = uuid.uuid4().hex
gercek = istek_bytes(i, "click 'Buy now'")
yaz(i, istek_bytes(i, "click 'Cancel'"))  # the writer swapped it before the requester's bekle reached the panel
c = baglan(i, hashlib.sha256(gercek).hexdigest())
g = onay.istek_oku(onay.istek_yolu(i))
r = onay.yanitla(i, "izin", gosterilen=g["_iz"]) if g else None
cevap = al(c)
kontrol("B3-A: gösterimden önce değişen istek → Evet reddedilir (izin gitmez)", r is False and "izin" not in cevap,
        f"{r} {cevap!r}")
kontrol("B3-A: görünür uyarı", any(i[:8] in x for x in REDLER), str(REDLER))
onay._sil(onay.istek_yolu(i))

# A2) swapped AFTER the bekle, before the dialog read
i = uuid.uuid4().hex
gercek = istek_bytes(i, "click 'Buy now'")
yaz(i, gercek)
c = baglan(i, hashlib.sha256(gercek).hexdigest())
yaz(i, istek_bytes(i, "click 'Cancel'"))
g = onay.istek_oku(onay.istek_yolu(i))
r = onay.yanitla(i, "izin", gosterilen=g["_iz"])
cevap = al(c)
kontrol("B3-A2: bekle'den sonra, gösterimden önce değişen istek → Evet reddedilir", r is False and "izin" not in cevap,
        f"{r} {cevap!r}")
onay._sil(onay.istek_yolu(i))

# second, different hash for the same id → refused
i = uuid.uuid4().hex
gercek = istek_bytes(i, "click 'Save'")
yaz(i, gercek)
c1 = baglan(i, hashlib.sha256(gercek).hexdigest())
c2 = baglan(i, "f" * 64)
g = onay.istek_oku(onay.istek_yolu(i))
r = onay.yanitla(i, "izin", gosterilen=g["_iz"])
al(c2)
cevap = al(c1)
kontrol("B3: aynı id için farklı ikinci karma → istek reddedilir", r is False and "izin" not in cevap,
        f"{r} {cevap!r}")
onay._sil(onay.istek_yolu(i))

# no hash at all (old requester) → the Yes is not given
i = uuid.uuid4().hex
yaz(i, istek_bytes(i, "click 'Save'"))
c = baglan(i, None)
g = onay.istek_oku(onay.istek_yolu(i))
onay.IZ_BEKLE_SN = 0.2
r = onay.yanitla(i, "izin", gosterilen=g["_iz"])
c.close()
kontrol("B3: karmasız bekle → Evet verilmez", r is False, str(r))
onay._sil(onay.istek_yolu(i))

# negative: the honest request (hash matches) is approved
i = uuid.uuid4().hex
gercek = istek_bytes(i, "click 'Save'")
yaz(i, gercek)
c = baglan(i, hashlib.sha256(gercek).hexdigest())
g = onay.istek_oku(onay.istek_yolu(i))
r = onay.yanitla(i, "izin", gosterilen=g["_iz"])
cevap = al(c)
kontrol("B3: dürüst istek (karma tutuyor) → izin iletilir", r is True and cevap == f"karar izin {i}\n",
        f"{r} {cevap!r}")
onay._sil(onay.istek_yolu(i))

# end to end: iste_sonuc sends the hash; a panel thread approves
import threading  # noqa: E402

sonuc = {}


def panel_yanitlayici():
    son = time.monotonic() + 5
    while time.monotonic() < son:
        b = onay.bekleyenler()
        if b:
            time.sleep(0.2)
            sonuc["r"] = onay.yanitla(b[0]["id"], "izin", gosterilen=b[0]["_iz"])
            return
        time.sleep(0.05)


t = threading.Thread(target=panel_yanitlayici)
t.start()
s = onay.iste_sonuc("x", "y", sure=8, gunluge_yaz=False)
t.join(6)
kontrol("B3: iste_sonuc karmayı gönderir, dürüst istek onaylanır", s.izin and sonuc.get("r") is True, f"{s} {sonuc}")
onay.panel_sil()

# ================================================================ B4: the user's DUR survives a panel restart
from deskhand.gui.panel import Panel  # noqa: E402


class SahtePanel:
    """Only the DUR bookkeeping of gui.panel.Panel (no Qt window)."""
    _dur_kaydet = Panel._dur_kaydet
    _dur_baslat = Panel._dur_baslat
    _dur_koru = Panel._dur_koru

    def __init__(self):
        self.uyarilar = []

    def _liste_uyari(self, m):
        self.uyarilar.append(m)


lk._anahtar_unut()
p = SahtePanel()
guvenlik.dur_ac("kullanici")
Panel._dur_kaydet(p, True)  # the panel's DUR button
os.remove(dur_dosyasi())
p2 = SahtePanel()  # the agent killed the panel, deleted DUR and started a new panel
Panel._dur_baslat(p2)
kontrol("B4: panel yeniden başlayınca kullanıcının DUR'u geri konur", guvenlik.dur_acik() and
        guvenlik.dur_kaynagi() == "kullanici" and p2._dur_kullanici, f"{guvenlik.dur_kaynagi()} {p2.uyarilar}")
kontrol("B4: geri koyma görünür", any("DUR" in u for u in p2.uyarilar), str(p2.uyarilar))
Panel._dur_kaydet(p2, False)  # the user's Devam
guvenlik.dur_kapat("kullanici")
p3 = SahtePanel()
Panel._dur_baslat(p3)
kontrol("B4: kullanıcı kaldırdıysa yeniden başlatmada DUR gelmez", not guvenlik.dur_acik() and not p3._dur_kullanici)
guvenlik.dur_ac("kullanici")  # set outside this panel (e.g. an earlier panel, file still there)
p4 = SahtePanel()
Panel._dur_baslat(p4)
kontrol("B4: açılışta var olan kullanıcı DUR'u panelin DUR'u sayılır", p4._dur_kullanici)
guvenlik.dur_kapat("kullanici")
Panel._dur_kaydet(p4, False)

# ================================================================ B5: a refused Yes is not reported as "izin"
DIYALOG = ("import os, sys; os.environ['QT_QPA_PLATFORM'] = 'offscreen'; sys.path.insert(0, sys.argv[1])\n"
           "from PyQt6.QtWidgets import QApplication\n"
           "app = QApplication([])\n"
           "from deskhand.gui.onay_diyalog import OnayDiyalog\n"
           "import time\n"
           "istek = {'id': 'd' * 32, 'eylem': 'Kaydet', 'hedef': 'Belge', 'ayrinti': '', 'masaustu': 'ekran',\n"
           "         'zaman': time.time(), 'son_zaman': time.time() + 60, 'pid': 1, 'tur': '',\n"
           "         'goruntu': None, 'masa': '', '_iz': ('', 'e' * 64)}\n"
           "dlg = OnayDiyalog(istek, yanitla=lambda k, karar: False, kurma_ms=0, hareket_px=0, istek_var=lambda: True)\n"
           "alinan = []\n"
           "dlg.karar_verildi.connect(lambda i, n: alinan.append(n))\n"
           "dlg.b_izin.setEnabled(True)\n"
           "dlg._karar('izin')\n"
           "print(repr(alinan), getattr(dlg, 'ret_nedeni', None))\n")
r = subprocess.run([sys.executable, "-c", DIYALOG, _yalitim.KOK], capture_output=True, text=True, timeout=60)
kontrol("B5: reddedilen Evet diyalogda 'red' + neden ile kapanır", "['red']" in r.stdout and "None" not in r.stdout,
        (r.stdout + r.stderr)[-400:])

# ================================================================ EK-2 (1): an unverified list is read-only in Settings
AYAR = ("import os, sys; os.environ['QT_QPA_PLATFORM'] = 'offscreen'; sys.path.insert(0, sys.argv[1])\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "from deskhand import liste_koruma as lk, onay\n"
        "from deskhand.oturum import kalici\n"
        "class K:\n"
        "    def oku(self):\n"
        "        raise kalici.AnahtarYok('cüzdan kilitli')\n"
        "    def yaz(self, v):\n"
        "        raise kalici.AnahtarYok('cüzdan kilitli')\n"
        "lk.isaret_anahtarlik_ayarla(K())\n"
        "open(lk.isaret_yolu('yasak'), 'w').write('{\"sha256\": \"yok\"}')\n"
        "open(lk.dosya('yasak'), 'w').write('# emptied by agent\\n')\n"
        "uyarilar = []\n"
        "k = lk.panel_baslat(uyarilar.append, None, None)\n"
        "from deskhand.gui.pencere import AyarlarSekmesi\n"
        "y = AyarlarSekmesi()\n"
        "print('RO', y.yasak.isReadOnly(), y.seviye.isReadOnly())\n"
        "print('BTN', y.b_yasak_kaydet.isEnabled(), y.b_seviye_kaydet.isEnabled())\n"
        "print('ETIKET', 'DOĞRULANMADI' in y.l_yasak.text())\n"
        "y.yasak.setPlainText('# still empty\\n')\n"
        "print('KAYDET', y.yasak_kaydet())\n"
        "try:\n"
        "    lk.panel_kaydet('yasak', '# via api\\n')\n"
        "    print('API kaydetti')\n"
        "except OSError:\n"
        "    print('API reddetti')\n"
        "print('HALA', 'yasak' in k._dogrulanamayan)\n"
        "print('UYARI', repr(uyarilar))\n")
os.makedirs(os.path.join(_yalitim.GECICI, "ek2"), exist_ok=True)
ortam = dict(os.environ)
for ad in ("DESKHAND_CONFIG_DIR", "DESKHAND_STATE_DIR", "DESKHAND_DATA_DIR", "DESKHAND_CACHE_DIR"):
    ortam[ad] = os.path.join(_yalitim.GECICI, "ek2", ad.split("_")[1].lower())
    os.makedirs(ortam[ad], exist_ok=True)
r = subprocess.run([sys.executable, "-c", AYAR, _yalitim.KOK], capture_output=True, text=True, timeout=60, env=ortam)
cikti = r.stdout + r.stderr[-600:]
kontrol("EK-2: doğrulanamayan tür Ayarlar'da salt okunur, kaydet kapalı, DOĞRULANMADI etiketi",
        "RO True True" in r.stdout and "BTN False False" in r.stdout and "ETIKET True" in r.stdout, cikti)
kontrol("EK-2: doğrulanamayan tür Ayarlar'dan ve API'den kaydedilemez (imzalanmaz)",
        "KAYDET False" in r.stdout and "API reddetti" in r.stdout and "HALA True" in r.stdout, cikti)
kontrol("EK-2: uyarı metni kaydet önermiyor", "UYARI" in r.stdout and "kaydedin" not in r.stdout.split("UYARI", 1)[1]
        and "Dur 10" in r.stdout.split("UYARI", 1)[1], cikti)

# ================================================================ EK-2 (2): the full content is shown; shown == applied
KASA.kilitli = True
uzun = "".join(f"^Pencere-{n:03d}$\n" for n in range(120))  # far longer than the old 200-char cut
open(YASAK, "w").write(uzun)
for y in glob.glob(os.path.join(os.path.dirname(lk.isaret_yolu("yasak")), "liste-*.isaret")):
    os.remove(y)
GOSTERILEN = []


def sor_iz(dogru):
    def f(tur, aciklama):
        GOSTERILEN.append(aciklama)
        iz = hashlib.sha256(aciklama.encode("utf-8", "surrogateescape")).hexdigest()
        return (True, iz if dogru else "0" * 64)
    return f


lk._anahtar_unut()
onay.panel_kaydet()
k = lk.panel_baslat(UYARILAR.append, onayla, sor_iz(False))
kontrol("EK-2: uzun liste diyalog metninde eksiksiz (kırpma yok)",
        GOSTERILEN and all(f"^Pencere-{n:03d}$" in GOSTERILEN[-1] for n in range(120)) and "…" not in GOSTERILEN[-1],
        GOSTERILEN[-1][-200:] if GOSTERILEN else "soru yok")
kontrol("EK-2: gösterilen ≠ uygulanacak (karma tutmuyor) → Evet uygulanmaz (Dur 10)", istemci_yasak() == "Dur 10",
        repr(istemci_yasak())[:80])
panel_kapat()
lk._anahtar_unut()
onay.panel_kaydet()
k = lk.panel_baslat(UYARILAR.append, onayla, sor_iz(True))
kontrol("EK-2: gösterilen = uygulanacak → Evet uygulanır", istemci_yasak() == uzun, repr(istemci_yasak())[:80])
panel_kapat()
KASA.kilitli = False

# the panel's own dialog shows the whole text in a scrollable read-only area and reports its hash
DLG = ("import os, sys, hashlib; os.environ['QT_QPA_PLATFORM'] = 'offscreen'; sys.path.insert(0, sys.argv[1])\n"
       "from PyQt6.QtWidgets import QApplication, QPlainTextEdit\n"
       "app = QApplication([])\n"
       "from deskhand.gui.panel import degisiklik_diyalogu\n"
       "metin = 'yasak pencereler:\\n' + ''.join(f'^P-{n:03d}$\\n' for n in range(300))\n"
       "dlg, alan = degisiklik_diyalogu(metin)\n"
       "print('TAM', alan.toPlainText() == metin, alan.isReadOnly(), isinstance(alan, QPlainTextEdit))\n"
       "print('IZ', dlg.gosterilen_iz() == hashlib.sha256(metin.encode()).hexdigest())\n")
r = subprocess.run([sys.executable, "-c", DLG, _yalitim.KOK], capture_output=True, text=True, timeout=60)
kontrol("EK-2: panel diyaloğu metni eksiksiz, kaydırılabilir salt okunur alanda gösterir ve izini verir",
        "TAM True True True" in r.stdout and "IZ True" in r.stdout, (r.stdout + r.stderr)[-500:])

print(f"\n{gecen}/{toplam} H3-INC3 testi geçti")
sys.exit(0 if gecen == toplam else 1)
