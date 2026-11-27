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
        len(SORULAN) == 1 and "yasak" in SORULAN[0][0] and "seviye" in SORULAN[0][0] and
        "TAMAMIDIR (0 giriş)" in SORULAN[0][1] and "1 yorum satırı (1) uygulanmaz" in SORULAN[0][1],
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
    _dur_kasa_denetle = getattr(Panel, "_dur_kasa_denetle", lambda self: None)
    DUR_KASA_YENIDEN_SN = 0.0

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
        return (True, aciklama.iz if dogru else "0" * 64)  # the display token (INC4: canonical entry lists)
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

# the panel's own dialog shows every entry in a scrollable read-only area and gives back the display's token
DLG = ("import os, sys; os.environ['QT_QPA_PLATFORM'] = 'offscreen'; sys.path.insert(0, sys.argv[1])\n"
       "from PyQt6.QtWidgets import QApplication, QPlainTextEdit\n"
       "app = QApplication([])\n"
       "from deskhand import liste_koruma as lk\n"
       "from deskhand.gui.panel import degisiklik_diyalogu\n"
       "metin = ''.join(f'^P-{n:03d}$\\n' for n in range(300))\n"
       "g = lk.gosterim('soru', [('yasak', metin, None, None)])\n"
       "dlg, alanlar = degisiklik_diyalogu(g)\n"
       "t = alanlar[0].toPlainText()\n"
       "print('TAM', all(f'^P-{n:03d}$' in t for n in range(300)), alanlar[0].isReadOnly(),\n"
       "      isinstance(alanlar[0], QPlainTextEdit))\n"
       "print('IZ', dlg.gosterilen_iz() == g.iz)\n")
r = subprocess.run([sys.executable, "-c", DLG, _yalitim.KOK], capture_output=True, text=True, timeout=60)
kontrol("EK-2: panel diyaloğu girişleri eksiksiz, kaydırılabilir salt okunur alanda gösterir ve jetonu verir",
        "TAM True True True" in r.stdout and "IZ True" in r.stdout, (r.stdout + r.stderr)[-500:])

# ================================================================ INC4 (rapor-H3-inceleme-4.md)
import re  # noqa: E402

SATIR_RE = re.compile(r"^[ +\u2212~] +\d+ │ ")  # a content line: sign, number, bar
ISARET_RE = re.compile(r"^ {9}[⚠⋯] ")  # an unnumbered marker line (folded run / note)


def icerik_satirlari(g):
    return [s for b in g.bolumler for s in b.satirlar]


def yapisi_dogru(g):
    return all(SATIR_RE.match(s) or ISARET_RE.match(s) for s in icerik_satirlari(g))


# ---- Y1: the wallet locks between _kasa_yeniden's read and a second read → the refused content is NEVER served
def y1_senaryo(kilit_araya):
    KASA.kilitli = False
    k = panel_ac(True)
    k.kaydet("yasak", ONAYLI)
    panel_kapat()
    open(YASAK, "w").write(SAHTE)
    for y in glob.glob(os.path.join(os.path.dirname(lk.isaret_yolu("yasak")), "liste-*.isaret")):
        os.remove(y)
    KASA.kilitli = True
    k = panel_ac(False)  # the user says No
    KASA.kilitli = False
    eski_sn, lk._DURUM_ONBELLEK_SN = lk._DURUM_ONBELLEK_SN, 0.0
    orijinal = lk.onayli_deger
    say = [0]

    def izle(tur):
        r_ = orijinal(tur)
        if tur == "yasak":
            say[0] += 1
            if say[0] == 1:
                KASA.kilitli = True  # locked right after the first read, before any second read
        return r_
    if kilit_araya == "poc":  # INC4/poc_inc4_kasa_yaris.py: locked right after _kasa_yeniden's onayli_deger read
        lk.onayli_deger = izle
    eski_oku = Kasa.oku
    if kilit_araya == "oku":  # locked after the FIRST wallet read inside denetle, whichever function reads it
        sayac = [0]

        def oku_kilitle(self):
            v = eski_oku(self)
            sayac[0] += 1
            if sayac[0] == 1:
                self.kilitli = True
            return v
        Kasa.oku = oku_kilitle
    try:
        k.KASA_YENIDEN_SN = 0
        k.denetle()
    finally:
        lk.onayli_deger = orijinal
        Kasa.oku = eski_oku
        lk._DURUM_ONBELLEK_SN = eski_sn
    v = istemci_yasak()
    panel_kapat()
    KASA.kilitli = False
    return v


v = y1_senaryo("poc")
kontrol("INC4 Y1: iki okuma arasında kilit (PoC) → reddedilen içerik SUNULMAZ (onaylı liste ya da Dur 10)",
        v in (ONAYLI, "Dur 10") and v != SAHTE, repr(v))
v = y1_senaryo("oku")
kontrol("INC4 Y1: ilk cüzdan okumasından hemen sonra kilit → reddedilen içerik SUNULMAZ",
        v in (ONAYLI, "Dur 10") and v != SAHTE, repr(v))
v = y1_senaryo("")
kontrol("INC4 Y1 (negatif): cüzdan okunur kalınca imzalı değer geri yüklenir", v == ONAYLI, repr(v))

# ---- O3: the display
bos = "KeePassXC\n" + "\n" * 300 + "panelin kaydı «KeePassXC», dosyada «KeePassXC»\n"
g = lk.gosterim("soru", [("yasak", bos, None, None)])
st = icerik_satirlari(g)
kontrol("INC4 O3: boş satırla kaydırma → boş satırlar tek işaretli satıra katlanır, girişler numaralı",
        len(st) == 4 and "300 boş satır (2–301) katlandı" in st[1] and SATIR_RE.match(st[2]) and "  302 │ " in st[2]
        and st[3].lstrip().startswith("⚠") and "U+00AB" in st[3],
        str(st))
kontrol("INC4 O3: içerikteki sahte 'panelin kaydı … dosyada' etiketi yalnız numaralı bir içerik satırı; sabit etiket "
        "içeriği taşımaz", yapisi_dogru(g) and "KeePassXC" not in g.bolumler[0].etiket and
        g.bolumler[0].etiket.startswith("Onaylı kayıt okunamadı"), g.bolumler[0].etiket)
gizli = "KeePass\u202eCXssaP\u200b\nOnline\u00a0Banking\r\nx\u2028y\n"
g = lk.gosterim("soru", [("yasak", gizli, None, None)])
st = icerik_satirlari(g)
ham = "".join(st)
kontrol("INC4 O3: bidi / sıfır genişlik / NBSP görünür \\u{XXXX} kaçışıyla, ham karakter içerikte yok",
        "\\u{202E}" in ham and "\\u{200B}" in ham and "\\u{00A0}" in ham and
        not any(c in ham for c in "\u202e\u200b\u00a0\u2028\r") and yapisi_dogru(g), str(st))
uygulanan = [x.strip() for x in gizli.splitlines() if x.strip() and not x.lstrip().startswith("#")]  # guvenlik
kontrol("INC4 O3: U+2028 uygulamanın ayrıştırıcısı gibi satır böler (gösterilen = uygulanan)",
        lk.kanonik("yasak", gizli) == uygulanan and len(uygulanan) == 4, str(lk.kanonik("yasak", gizli)))
kiril = "KeePassXC\nKe\u0435PassXC\n"
g = lk.gosterim("soru", [("yasak", kiril, "KeePassXC\n", "onayli")])
st = icerik_satirlari(g)
kontrol("INC4 O3: Kiril е işaretlenir (satırın altında ⚠ U+0435), fark +1 / −0",
        any("U+0435 CYRILLIC SMALL LETTER IE" in s for s in st) and SATIR_RE.match(st[0]) and "Ke\\u{0435}PassXC" in st[0]
        and "0 kaldırılan, 1 eklenen" in g.bolumler[0].etiket and "Dikkat: 1 girişte" in g.bolumler[0].etiket, str(st))
g = lk.gosterim("soru", [("yasak", "Yeni\n", ONAYLI, "onayli")])
st = icerik_satirlari(g)
kontrol("INC4 O3: onaylı kayda göre giriş bazlı fark; kaldırılanlar önce (− ), sayılar sabit etikette",
        st[0].startswith("\u2212") and "KeePassXC" in st[0] and st[-1].startswith("+") and "Yeni" in st[-1] and
        "2 kaldırılan, 1 eklenen" in g.bolumler[0].etiket, str(st) + g.bolumler[0].etiket)
g = lk.gosterim("soru", [("seviye", "KeePassXC = tam\nkonsole\n", "KeePassXC = goruntule\n", "onayli")])
st = icerik_satirlari(g)
kontrol("INC4 O3: seviye değişikliği eski → yeni seviye; eşittir'siz satır uygulandığı gibi (goruntule)",
        any("KeePassXC: goruntule → tam" in s for s in st) and any("konsole = goruntule" in s for s in st), str(st))
g = lk.gosterim("soru", [("yasak", "".join(f"p{n}\n" for n in range(lk.GOSTERIM_UST_SINIR + 1)), None, None)])
kontrol("INC4 O3: giriş üst sınırı aşılınca Evet kapalı", g.evet_kapali and "Evet verilemez" in g.bolumler[0].etiket)

# cüzdan kilitliyken "TAMAMI (N giriş)" etiketi, birleşik soruda
KASA.kilitli = False
k = panel_ac(True)
k.kaydet("yasak", ONAYLI)
panel_kapat()
open(YASAK, "w").write("A\n\nB\n# yorum\n")
KASA.kilitli = True
k = panel_ac(False)
g = SORULAN[0][1] if SORULAN else None
bol = {b.tur: b for b in g.bolumler} if g is not None else {}
kontrol("INC4 O3: cüzdan kilitli → sabit etiket 'karşılaştırma yapılamıyor … TAMAMIDIR (2 giriş) … Hayır deyin'",
        "yasak" in bol and "karşılaştırma yapılamıyor" in bol["yasak"].etiket and
        "TAMAMIDIR (2 giriş)" in bol["yasak"].etiket and "Hayır deyin" in bol["yasak"].etiket,
        str(bol.get("yasak").etiket if bol.get("yasak") else g))
panel_kapat()

# Y5: CR / NBSP / U+2029 content — a legitimate Yes (the token of the display) is ACCEPTED
garip = "Online\u00a0Banking\r\nKee\u2029Pass\n"
open(YASAK, "w").write(garip)
for y in glob.glob(os.path.join(os.path.dirname(lk.isaret_yolu("yasak")), "liste-*.isaret")):
    os.remove(y)
lk._anahtar_unut()
onay.panel_kaydet()
GOSTERILEN.clear()
k = lk.panel_baslat(UYARILAR.append, onayla, sor_iz(True))
kontrol("INC4 Y5: CR/NBSP/U+2029 içeren dosyaya meşru Evet kabul edilir",
        istemci_yasak() == garip.replace("\r\n", "\n"),
        repr(istemci_yasak())[:80])
panel_kapat()
KASA.kilitli = False
DLG5 = ("import os, sys; os.environ['QT_QPA_PLATFORM'] = 'offscreen'; sys.path.insert(0, sys.argv[1])\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "from deskhand import liste_koruma as lk\n"
        "from deskhand.gui.panel import degisiklik_diyalogu\n"
        "g = lk.gosterim('soru', [('yasak', 'Online\\u00a0Banking\\r\\nKee\\u2029Pass\\nKe\\u0435PassXC\\n', None, None)])\n"
        "dlg, alanlar = degisiklik_diyalogu(g)\n"
        "from PyQt6.QtWidgets import QLabel\n"
        "etiketler = [e.text() for e in dlg.findChildren(QLabel)]\n"
        "t = alanlar[0].toPlainText()\n"
        "print('IZ', dlg.gosterilen_iz() == g.iz)\n"
        "print('KACIS', '\\\\u{00A0}' in t, 'U+0435' in t)\n"
        "print('ETIKET', g.bolumler[0].etiket in etiketler, all('Banking' not in e for e in etiketler))\n")
r = subprocess.run([sys.executable, "-c", DLG5, _yalitim.KOK], capture_output=True, text=True, timeout=60)
kontrol("INC4 Y5/O3: Qt diyaloğu jetonu kanonik listeden verir (widget metninden değil), kaçış ve işaret görünür, "
        "yapı etiketleri içerikten ayrı bileşende", "IZ True" in r.stdout and "KACIS True True" in r.stdout and
        "ETIKET True True" in r.stdout, (r.stdout + r.stderr)[-500:])

# ---- Y3: the wallet becomes readable but holds no approved value → the check is repeated without a restart
KASA.veri = None  # the item is gone (deleted earlier)
open(YASAK, "w").write("Dosyadaki\n")
for y in glob.glob(os.path.join(os.path.dirname(lk.isaret_yolu("yasak")), "liste-*.isaret")):
    os.remove(y)
open(lk.isaret_yolu("seviye"), "w").write('{"sha256": "yok"}')  # marks exist: not a first start
KASA.kilitli = True
k = panel_ac(False)
kontrol("INC4 Y3 hazırlık: kilitli + Hayır → Dur 10", istemci_yasak() == "Dur 10")
KASA.kilitli = False
k.KASA_YENIDEN_SN = 0
SORULAN.clear()
CEVAP["v"] = True
k.denetle()
kontrol("INC4 Y3: cüzdan okunur ama onaylı değer yok → yeniden sorulur (panel yeniden başlamadan); Evet → uygulanır",
        len(SORULAN) == 1 and "yasak" in SORULAN[0][0] and istemci_yasak() == "Dosyadaki\n",
        f"{[t for t, _a in SORULAN]} {istemci_yasak()!r}")
panel_kapat()
KASA.veri = None
open(lk.isaret_yolu("seviye"), "w").write('{"sha256": "yok"}')
open(YASAK, "w").write("Dosyadaki2\n")
k = panel_ac(False)  # wallet open, no item: asked at start, No; the item is then re-created without son[yasak]
SORULAN.clear()
k.KASA_YENIDEN_SN = 0
for _i in range(3):
    k.denetle()
kontrol("INC4 Y3: aynı içeriğe Hayır sonrası soru döngüsü yok, Dur 10 sürer",
        SORULAN == [] and istemci_yasak() == "Dur 10", f"{SORULAN} {istemci_yasak()!r}")
open(YASAK, "w").write("Dosyadaki3\n")
CEVAP["v"] = False
k.denetle()
kontrol("INC4 Y3: dosya değişince yeniden sorulur", len(SORULAN) == 1, str([t for t, _a in SORULAN]))
kontrol("INC4 Y3: uyarı 'cüzdan açılınca geri yükler' diye yanlış vaatte bulunmaz; yeniden sorma yolunu söyler",
        any("yeniden sorulur" in u for u in UYARILAR), str(UYARILAR)[-300:])
panel_kapat()
KASA.kilitli = False
k = panel_ac(True)
k.kaydet("yasak", ONAYLI)
panel_kapat()

# ---- B4/E4: wallet unreadable at panel start → the user's DUR counts as ON; the signed value applies later
for kayitli in (False, True):
    lk._anahtar_unut()
    Panel._dur_kaydet(SahtePanel(), kayitli)
    try:
        os.remove(dur_dosyasi())
    except FileNotFoundError:
        pass
    KASA.kilitli = True
    lk._anahtar_unut()
    p5 = SahtePanel()
    Panel._dur_baslat(p5)
    kontrol(f"INC4 B4: kilitli cüzdanda açılış → DUR açık (kapalı-başarısız, panelin kendi kaynağı; imzalı={kayitli})",
            guvenlik.dur_acik() and guvenlik.dur_kaynaklari() == {guvenlik.DUR_KAPALI_BASARISIZ} and
            p5._dur_kasa_bekliyor and not p5._dur_kullanici,
            f"{guvenlik.dur_kaynagi()} {p5.uyarilar}")
    KASA.kilitli = False
    lk._anahtar_unut()
    Panel._dur_koru(p5)
    kontrol(f"INC4 B4: cüzdan okununca imzalı değer uygulanır (imzalı={kayitli} → DUR {'açık' if kayitli else 'kalkar'})",
            guvenlik.dur_acik() == kayitli and p5._dur_kullanici == kayitli, f"{guvenlik.dur_kaynagi()} {p5.uyarilar}")
    guvenlik.dur_kapat("kullanici")
    Panel._dur_kaydet(p5, False)
# the user pressed DUR while waiting for the wallet: it stays
KASA.kilitli = True
lk._anahtar_unut()
p6 = SahtePanel()
Panel._dur_baslat(p6)
guvenlik.dur_ac("kullanici")
Panel._dur_kaydet(p6, True)  # the panel's DUR button
KASA.kilitli = False
lk._anahtar_unut()
Panel._dur_koru(p6)
kontrol("INC4 B4: bekleme sırasında kullanıcının bastığı DUR cüzdan okununca kalkmaz ve imzalanır",
        guvenlik.dur_acik() and lk.panel_dur_durumu() is True, f"{guvenlik.dur_kaynagi()} {lk.panel_dur_durumu()}")
guvenlik.dur_kapat("kullanici")
Panel._dur_kaydet(p6, False)

# ================================================================ INC5 (rapor-H3-inceleme-5.md; ANA R8 kararları)
KB = guvenlik.DUR_KAPALI_BASARISIZ


def dur_sifirla():
    guvenlik.dur_kapat("kullanici")


def kod_al(f, *a):
    try:
        f(*a)
        return 0
    except Dur as e:
        return e.kod


def kilitli_acilis(onceden=()):
    """A panel start with a locked wallet; `onceden`: DUR sources already on (set by someone else)."""
    dur_sifirla()
    for k_ in onceden:
        guvenlik.dur_ac(k_)
    KASA.kilitli = True
    lk._anahtar_unut()
    p_ = SahtePanel()
    Panel._dur_baslat(p_)
    return p_


def kasa_acilir(p_):
    KASA.kilitli = False
    lk._anahtar_unut()
    Panel._dur_koru(p_)


# DUR source set (guvenlik): parsing + ownership
kontrol("INC5 P1: _kaynak_coz panelin kapalı-başarısız etiketini 'cli' ya da 'kullanici' saymaz",
        set(guvenlik._kaynak_coz(f"{KB} 123\n")) == {KB} and set(guvenlik._kaynak_coz("")) == {"cli"} and
        set(guvenlik._kaynak_coz("kullanici 1\ncli 2\n")) == {"kullanici", "cli"})
dur_sifirla()
guvenlik.dur_ac(KB)
kod = kod_al(guvenlik.dur_kapat, "cli")
kontrol("INC5 P1 (D3): ajanın dur_kapat('cli')'si panelin kapalı-başarısız DUR'unu kaldıramaz (13, DUR açık)",
        kod == 13 and guvenlik.dur_kaynaklari() == {KB}, f"{kod} {guvenlik.dur_kaynaklari()}")
guvenlik.dur_ac("cli")
kod = kod_al(guvenlik.dur_kapat, "cli")
kontrol("INC5 P1: ajan yalnız kendi kaynağını kaldırır; başka kaynak sürerken 13",
        kod == 13 and guvenlik.dur_kaynaklari() == {KB}, f"{kod} {guvenlik.dur_kaynaklari()}")
guvenlik.dur_ac("kullanici")
kontrol("INC5: kaynaklar birbirini ezmez (kullanıcı + panel aynı anda)",
        guvenlik.dur_kaynaklari() == {KB, "kullanici"} and guvenlik.dur_kaynagi() == "kullanici")
guvenlik.dur_kapat(KB)
kontrol("INC5: panel yalnız kendi kaynağını kaldırır; kullanıcının DUR'u kalır",
        guvenlik.dur_kaynaklari() == {"kullanici"})
dur_sifirla()
kontrol("INC5: kullanıcının Devam'ı bütün kaynakları kaldırır", not guvenlik.dur_acik())

# P1(3): the last source is MOVED away, then checked: a source written meanwhile (outside the lock) is put back
guvenlik.dur_ac(KB)
gercek_rename = guvenlik.os.rename
tetik = {"n": 0}


def araya_giren_rename(kaynak, hedef):
    if tetik["n"] == 0:
        tetik["n"] = 1
        with open(kaynak, "a") as f_:  # a writer that does not take the lock (e.g. an older process)
            f_.write("cli 99999\n")
    return gercek_rename(kaynak, hedef)


guvenlik.os.rename = araya_giren_rename
try:
    sonuc_ = guvenlik.dur_kapat(KB)
finally:
    guvenlik.os.rename = gercek_rename
kontrol("INC5 P1 (3): kaldırma taşı → doğrula → geri koy; araya giren kaynak kaybolmaz",
        sonuc_ is True and guvenlik.dur_kaynaklari() == {"cli"}, f"{sonuc_} {guvenlik.dur_kaynaklari()}")
kontrol("INC5 P1 (3): geride geçici dosya kalmadı",
        not [f_ for f_ in os.listdir(os.path.dirname(dur_dosyasi())) if f_.startswith(("dur.", ".dur-"))],
        str(os.listdir(os.path.dirname(dur_dosyasi()))))
dur_sifirla()

# a same-uid process holding the DUR lock cannot block the user's DUR button
import fcntl  # noqa: E402

kfd = os.open(os.path.join(os.path.dirname(dur_dosyasi()), "dur-kilit"), os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(kfd, fcntl.LOCK_EX)
try:
    t0 = time.monotonic()
    guvenlik.dur_ac("kullanici")
    sure_ = time.monotonic() - t0
finally:
    os.close(kfd)
kontrol("INC5: DUR kilidini tutan süreç kullanıcının DUR'unu engelleyemez (sınırlı bekleme)",
        guvenlik.dur_kaynaklari() == {"kullanici"} and sure_ < 3, f"{sure_:.2f} sn {guvenlik.dur_kaynaklari()}")
dur_sifirla()

# O5: locked wallet at start, a DUR someone else set is on → the panel ADDS its own source, never overwrites
for onceden in (("cli",), ("kullanici",)):
    p7 = kilitli_acilis(onceden)
    kontrol(f"INC5 O5: kilitli açılışta panel kendi kaynağını ekler, {onceden[0]} DUR'unu ezmez",
            guvenlik.dur_kaynaklari() == {KB, onceden[0]} and p7._dur_kasa_bekliyor,
            str(guvenlik.dur_kaynaklari()))
    KASA.kilitli = False
    lk._anahtar_unut()
    lk.panel_dur_sakla(False)  # the signed record: DUR off
    Panel._dur_koru(p7)
    kontrol(f"INC5 O4: cüzdan okununca imzalı 'DUR yok' yalnız panelin kaynağını kaldırır ({onceden[0]} kalır)",
            guvenlik.dur_kaynaklari() == {onceden[0]} and not p7._dur_kasa_bekliyor,
            f"{guvenlik.dur_kaynaklari()} {p7.uyarilar[-1:]}")
    dur_sifirla()
    Panel._dur_kaydet(p7, False)

# P1(2)/D4: the agent sets its own DUR before the restart, then lifts it → the closed-fail DUR is still on
p8 = kilitli_acilis(("cli",))
kod = kod_al(guvenlik.dur_kapat, "cli")
kontrol("INC5 P1 (2)/D4: ajanın önceden koyduğu cli DUR'u kapalı-başarısız kuralını atlatamaz",
        kod == 13 and guvenlik.dur_kaynaklari() == {KB}, f"{kod} {guvenlik.dur_kaynaklari()}")

# P1(4): a deleted DUR is put back with its OWN label; P1(5): a new panel takes over the earlier panel's label
os.remove(dur_dosyasi())
Panel._dur_koru(p8)
kontrol("INC5 P1 (4): silinen kapalı-başarısız DUR kendi etiketiyle geri konur ('kullanici' değil)",
        guvenlik.dur_kaynaklari() == {KB} and any("geri konuldu" in u for u in p8.uyarilar),
        str(guvenlik.dur_kaynaklari()))
lk._anahtar_unut()
p9 = SahtePanel()
Panel._dur_baslat(p9)  # wallet still locked: the label stays, this panel waits for it
kontrol("INC5 P1 (5): yeni panel önceki panelin kapalı-başarısız kaynağını devralır (kilitli → sürer)",
        guvenlik.dur_kaynaklari() == {KB} and p9._dur_kasa_bekliyor)
KASA.kilitli = False
lk._anahtar_unut()
lk.panel_dur_sakla(False)
p10 = SahtePanel()
Panel._dur_baslat(p10)
kontrol("INC5 P1 (5): cüzdan okunurken açılan panel imzalı 'kapalı' kayda göre önceki kapalı-başarısız kaynağı kaldırır",
        not guvenlik.dur_acik() and not p10._dur_kasa_bekliyor, str(guvenlik.dur_kaynaklari()))
lk.panel_dur_sakla(True)
p11 = kilitli_acilis()
kasa_acilir(p11)
kontrol("INC5: imzalı kayıt 'açık' → kapalı-başarısız kaynak kullanıcınınkiyle değişir, DUR hiç kalkmaz",
        guvenlik.dur_kaynaklari() == {"kullanici"} and p11._dur_kullanici, str(guvenlik.dur_kaynaklari()))
os.remove(dur_dosyasi())
Panel._dur_koru(p11)
kontrol("INC5 P1 (4): silinen kullanıcı DUR'u 'kullanici' etiketiyle geri konur",
        guvenlik.dur_kaynaklari() == {"kullanici"})
dur_sifirla()
Panel._dur_kaydet(p11, False)

# N1: a corrupt / incomplete signed item is closed-fail and is NOT re-made by an automatic path
lk.panel_dur_sakla(False)
for ad_, bozuk in (("bozuk", b"{not json"),
                   ("dur alanı eksik", json.dumps({"surum": 1, "anahtar": "ab" * 32, "sayac": {}, "son": {}}).encode())):
    KASA.veri = bozuk
    KASA.kilitli = False
    lk._anahtar_unut()
    p12 = SahtePanel()
    dur_sifirla()
    Panel._dur_baslat(p12)
    lk._anahtar_unut()
    kontrol(f"INC5 N1: {ad_} kayıt → panel_dur_durumu None, DUR açık (kapalı-başarısız)",
            lk.panel_dur_durumu() is None and guvenlik.dur_kaynaklari() == {KB})
    lk._anahtar_unut()
    kontrol(f"INC5 N1: {ad_} kayıt otomatik yolda (_durum(True)) yeniden yaratılmaz",
            (lk._durum(True) is None) is (ad_ == "bozuk") and KASA.veri == bozuk and lk.panel_dur_durumu() is None)
    lk._anahtar_unut()
    Panel._dur_koru(p12)
    kontrol(f"INC5 N1: {ad_} kayıtta panel yoklaması DUR'u kaldırmaz", guvenlik.dur_kaynaklari() == {KB})
    dur_sifirla()  # the user's Devam
    Panel._dur_kaydet(p12, False)
    lk._anahtar_unut()
    kontrol(f"INC5 N1: {ad_} kayıt yalnız kullanıcı eylemiyle (Devam) yeniden yazılır",
            KASA.veri != bozuk and lk.panel_dur_durumu() is False)

# Y10: no Secret Service at all (absent, not locked) → a first start, no closed-fail DUR


class YokKasa(Kasa):
    def __init__(self, yok):
        super().__init__()
        self.yok = yok

    def oku(self):
        raise kalici.AnahtarYok("Secret Service yok")

    def servis_yok_kesin(self):
        return self.yok


for yok in (True, False):
    lk.isaret_anahtarlik_ayarla(YokKasa(yok))
    dur_sifirla()
    p13 = SahtePanel()
    Panel._dur_baslat(p13)
    kontrol(f"INC5 Y10: Secret Service {'kesin yok → DUR açılmaz' if yok else 'belirsiz/kilitli → kapalı-başarısız DUR'}",
            guvenlik.dur_acik() is (not yok) and lk.panel_dur_durumu() is (False if yok else None))
    dur_sifirla()
lk.isaret_anahtarlik_ayarla(KASA)
KASA.veri, KASA.kilitli = None, False
lk._anahtar_unut()

# Y7 / Y8 / Y9: the display
for desen, ad_ in (("KeePass\u2169\u216d", "Roma rakamı Ⅹ Ⅽ"), ("Online Banking \U0001d7d0", "matematik rakamı 𝟐"),
                   ("Banka\u2800", "U+2800"), ("example\u3002com", "U+3002"), ("Banking \uff12", "tam genişlik ２"),
                   ("\u200bKeePassXC", "sıfır genişlik (Y8)"), ("A\x00B", "NUL (Y8)")):
    g = lk.gosterim("soru", [("yasak", desen + "\n", None, None)])
    st = icerik_satirlari(g)
    ham_ = "".join(st)
    kontrol(f"INC5 Y7/Y8: {ad_} → kaçışlı, ⚠ ve sayaçta",
            not any(ord(c) > 0x7e and c not in "│−⚠×çğıİöşüÇĞÖŞÜ" or ord(c) < 0x20 for c in st[0]) and
            g.bolumler[0].isaretli == 1 and "Dikkat: 1 girişte" in g.bolumler[0].etiket and
            any(s.lstrip().startswith("⚠") for s in st) and "\\u{" in ham_, str(st))
g = lk.gosterim("soru", [("yasak", "KeePass\u2169\u216d\n", None, None)])
kontrol("INC5 Y7: 'KeePassⅩⅭ' → KeePass\\u{2169}\\u{216D}", "KeePass\\u{2169}\\u{216D}" in icerik_satirlari(g)[0])
g = lk.gosterim("soru", [("yasak", "İstanbul ığdır\nŞÜÖÇĞ şüöçğ\n", None, None)])
kontrol("INC5 Y7 (negatif): meşru Türkçe kural ⚠ almaz, olduğu gibi görünür",
        g.bolumler[0].isaretli == 0 and "Dikkat" not in g.bolumler[0].etiket and
        any("İstanbul ığdır" in s for s in icerik_satirlari(g)), str(icerik_satirlari(g)))
metin_ = "".join("\n# c\n" for _ in range(5000)) + "KeePassXC\n"
g = lk.gosterim("soru", [("yasak", metin_, None, None)])
st = icerik_satirlari(g)
kontrol("INC5 Y9: art arda boş/yorum satırları tek '⟨boş/yorum ×K⟩' satırına katlanır",
        len(st) == 2 and "⟨boş/yorum ×10000⟩" in st[0] and "KeePassXC" in st[1] and not g.evet_kapali, str(st[:3]))
eski_sinir = lk.GOSTERIM_SATIR_SINIR
lk.GOSTERIM_SATIR_SINIR = 10
try:
    g = lk.gosterim("soru", [("yasak", "".join(f"x\u0430{n}\n" for n in range(6)), None, None)])
finally:
    lk.GOSTERIM_SATIR_SINIR = eski_sinir
kontrol("INC5 Y9: gösterilen satır üst sınırı aşılınca Evet kapalı, 'Ayarlar'dan inceleyin'",
        g.evet_kapali and "Ayarlar'dan inceleyin" in g.bolumler[0].etiket, g.bolumler[0].etiket)

print(f"\n{gecen}/{toplam} H3-INC3 testi geçti")
sys.exit(0 if gecen == toplam else 1)
