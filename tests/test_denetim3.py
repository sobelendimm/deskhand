"""Üçüncü denetim (tur4) bulgularının regresyon testi — ekransız; Qt görünmez (offscreen). Gerçek ~/.config yazılmaz.

 D1  yasak listesi / seviye dosyası ajan araçlarıyla silinip değiştirilemez: panel yetkili kaynak (bellek + kanal),
     dışarıdan değişen dosya geri yazılır; panel kapalıyken işaretli kayıpta girdi yok (Dur 10).
 YN2 kod barındıran uygulamalar (sistem girdisi olsa da) onay ister; yürütülebilir belge türleri her uygulamada 10.
 YN5 onaylı kullanıcı girdisinin kullanıcıya ait programı onaydan sonra değişirse başlatılmaz (10).
 YK1 panel doğrulaması: /proc/<pid>/cwd ve panelin deskhand paket yolu.

Çalıştır: python3 tests/test_denetim3.py"""
import json
import os
import shutil
import subprocess
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
os.environ["XDG_CONFIG_HOME"] = "/nonexistent-deskhand-test"
import _yalitim  # noqa: E402

from deskhand import guvenlik, liste_koruma, onay, uygulama, yollar  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

class SahteKasa:
    """Fake Secret Service item of the panel (liste_koruma: key, counters, last approved values); file-backed so a
    client process reads the same one (KASA_ISTEMCI). The real wallet is never touched."""
    yol = os.path.join(os.environ["DESKHAND_STATE_DIR"], "sahte-kasa.json")

    def oku(self):
        try:
            with open(self.yol, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def yaz(self, veri):
        with open(self.yol, "wb") as f:
            f.write(veri)


liste_koruma.isaret_anahtarlik_ayarla(SahteKasa())
KASA_ISTEMCI = ("class _K:\n"
                "    def oku(self):\n"
                "        import os\n"
                "        try:\n"
                "            return open(os.path.join(os.environ['DESKHAND_STATE_DIR'], 'sahte-kasa.json'), 'rb').read()\n"
                "        except FileNotFoundError:\n"
                "            return None\n"
                "    def yaz(self, v):\n"
                "        raise OSError('client')\n"
                "from deskhand import liste_koruma as _lk\n"
                "_lk.isaret_anahtarlik_ayarla(_K())\n")


def sahte_isaret(tur, metin):
    """The agent's forged mark (plain sha256 of the content, no panel signature)."""
    import hashlib
    os.makedirs(os.path.dirname(liste_koruma.isaret_yolu(tur)), exist_ok=True)
    with open(liste_koruma.isaret_yolu(tur), "w") as f:
        json.dump({"sha256": hashlib.sha256(metin.encode()).hexdigest(), "icerik": metin, "var": True}, f)

G = _yalitim.GECICI
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


def kod_al(f, *a, **k):
    try:
        f(*a, **k)
        return 0
    except Dur as e:
        return e.kod


def oku(yol):
    try:
        return open(yol).read()
    except OSError:
        return None


ISTEMCI = ("import json, sys; sys.path.insert(0, sys.argv[1]); from deskhand import guvenlik; from deskhand.hata import Dur\n"
           "try:\n"
           "    print(json.dumps({'yasak': guvenlik._kullanici_yasaklari(), 'seviye': guvenlik.seviye_kurallari()}))\n"
           "except Dur as e:\n"
           "    print(json.dumps({'dur': e.kod, 'mesaj': e.mesaj}))\n")


def istemci():
    """AYRI süreç (CLI/MCP gibi): listeleri nereden alıyor?"""
    r = subprocess.run([sys.executable, "-c", ISTEMCI.replace("\n", "\n" + KASA_ISTEMCI, 1), _yalitim.KOK],
                       capture_output=True, text=True, timeout=30)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"hata": r.stdout + r.stderr}


YASAK, SEVIYE = yollar.yasak_dosya(), yollar.seviye_dosya()
os.makedirs(os.path.dirname(YASAK), exist_ok=True)
open(YASAK, "w").write("# kullanıcı\nGizliKasa\n")
open(SEVIYE, "w").write("KeePassXC = goruntule\n")

# ================================================================ D1: panel açık (bellek + kanal + geri yazma)
uyarilar = []
onay.panel_kaydet()
k = liste_koruma.panel_baslat(uyarilar.append)
kontrol("D1: panel açılışta iki listeyi belleğe aldı ve işaret yazdı",
        k.metin("yasak") == "# kullanıcı\nGizliKasa\n" and k.metin("seviye") == "KeePassXC = goruntule\n" and
        os.path.exists(liste_koruma.isaret_yolu("yasak")) and os.path.exists(liste_koruma.isaret_yolu("seviye")))
os.remove(YASAK)  # ajan: rm ~/.config/deskhand/yasak-pencereler.txt
open(SEVIYE, "w").write("")  # ajan: dosyayı boşaltır
r = istemci()
kontrol("D1: dosyalar silinip boşaltıldı ama ayrı süreç listeleri PANELDEN alıyor (kısıt sürüyor)",
        r.get("yasak") == ["GizliKasa"] and r.get("seviye") == [["KeePassXC", 0]], str(r))
u = k.denetle()
kontrol("D1: panel dosyaları geri yazdı ve iki uyarı üretti",
        oku(YASAK) == "# kullanıcı\nGizliKasa\n" and oku(SEVIYE) == "KeePassXC = goruntule\n" and len(u) == 2 and
        len(uyarilar) == 2, f"{u} {oku(YASAK)!r}")
open(YASAK, "w").write("# boş\n")
k.denetle()
kontrol("D1: dışarıdan değiştirilen dosya panelin kaydına döner", oku(YASAK) == "# kullanıcı\nGizliKasa\n")
liste_koruma.panel_kaydet("yasak", "GizliKasa\nBanka\n")  # panelin kendi Kaydet'i
n0 = len(uyarilar)
k.denetle()
liste_koruma.onbellek_sil()
r = istemci()
kontrol("D1: panelin Kaydet'i geri alınmaz (uyarı yok) ve istemciye yansır",
        oku(YASAK) == "GizliKasa\nBanka\n" and len(uyarilar) == n0 and r.get("yasak") == ["GizliKasa", "Banka"], str(r))

# Qt panel: QFileSystemWatcher + yoklama gerçekten geri yazıyor mu (gerçek Panel sınıfı, sahte bağımlılıklar)
liste_koruma.panel_durdur()
onay.panel_sil()
from PyQt6.QtCore import QObject, pyqtSignal  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])


class SahteKisayol(QObject):
    basildi = pyqtSignal()
    hata = pyqtSignal(str)
    acik = False

    def ac(self, tus):
        pass

    def kapat(self, kaydi_sil=True):
        pass


class SahteMasaustu:
    @classmethod
    def durum(cls, dogrula=True):
        return None


from deskhand.gui.panel import Panel  # noqa: E402

p = Panel(app, None, tepsi=False, kisayol=SahteKisayol(), diyalog_kurma_ms=0, arka_f=lambda: None,
          masaustu_m=SahteMasaustu, cakisma_f=lambda t: [], simge_sor=lambda b, m: False, saglik_f=lambda: [])


def olay_bekle(kosul, sure=5.0):
    t = time.monotonic() + sure
    while time.monotonic() < t:
        app.processEvents()
        if kosul():
            return True
        time.sleep(0.05)
    return False


kontrol("D1/Qt: panel koruyucusu etkin, liste bellekte", liste_koruma.AKTIF is not None and
        liste_koruma.AKTIF.metin("yasak") == "GizliKasa\nBanka\n")
os.remove(YASAK)
kontrol("D1/Qt: panel açıkken silinen yasak dosyası kendiliğinden geri geliyor", olay_bekle(
    lambda: oku(YASAK) == "GizliKasa\nBanka\n"))
open(SEVIYE, "w").write("# ajan boşalttı\n")
kontrol("D1/Qt: değiştirilen seviye dosyası geri geliyor + kullanıcıya uyarı", olay_bekle(
    lambda: oku(SEVIYE) == "KeePassXC = goruntule\n") and len(p.liste_uyarilari) >= 2, str(p.liste_uyarilari))
from deskhand.gui import ayar as A  # noqa: E402

A.seviye_kaydet("KeePassXC = goruntule\nBanka = tikla\n")
olay_bekle(lambda: False, 0.6)
kontrol("D1/Qt: Ayarlar'dan Kaydet bellek + dosyayı günceller, izleyici geri ALMAZ",
        oku(SEVIYE) == "KeePassXC = goruntule\nBanka = tikla\n" and
        liste_koruma.AKTIF.metin("seviye") == "KeePassXC = goruntule\nBanka = tikla\n" and
        A.seviye_metni() == "KeePassXC = goruntule\nBanka = tikla\n")
p.kapanis()
kontrol("D1/Qt: kapanışta koruyucu ve kanal kapandı", liste_koruma.AKTIF is None and not onay.panel_canli())

# ================================================================ D1: panel kapalı
liste_koruma.onbellek_sil()
kontrol("D1: panel kapalı + dosyalar panelin kaydıyla aynı → dosyadan okunur",
        guvenlik._kullanici_yasaklari() == ["GizliKasa", "Banka"] and len(guvenlik.seviye_kurallari()) == 2)
os.remove(YASAK)


class AU:
    ad = "kde"

    def baslik(self, k):
        return "Herhangi"

    def sinif(self, k):
        return "herhangi"


eski_sec = guvenlik.sec
guvenlik.sec = lambda: AU()
try:
    try:
        guvenlik.yasak_denetle("{w}")
        e_ = None
    except Dur as e:
        e_ = e
    kontrol("D1: panel kapalı + işaretli yasak dosyası KAYIP → girdi yok (Dur 10, 'paneli açın')",
            e_ is not None and e_.kod == 10 and "paneli açın" in e_.mesaj, str(e_))
    r = istemci()
    kontrol("D1: ayrı süreç de (CLI/MCP) 10 alır", r.get("dur") == 10, str(r))
    kontrol("D1: işaretli kayıpta yasak dosyası sessizce varsayılanla YENİDEN OLUŞTURULMAZ", not os.path.exists(YASAK))
    open(SEVIYE, "w").write("")
    kontrol("D1: panel kapalı + işaretli seviye dosyası değişti → seviye denetimi 10",
            kod_al(guvenlik.seviye_kurallari) == 10)
finally:
    guvenlik.sec = eski_sec
# panel yeniden açılır: işaretteki son kayıt geri gelir
uyarilar.clear()
onay.panel_kaydet()
k = liste_koruma.panel_baslat(uyarilar.append)
kontrol("D1: panel yeniden açılınca kapalıyken silinen/değişen dosyalar işaretten geri yüklendi + uyarı",
        oku(YASAK) == "GizliKasa\nBanka\n" and oku(SEVIYE) == "KeePassXC = goruntule\nBanka = tikla\n" and
        len(uyarilar) == 2, str(uyarilar))
liste_koruma.panel_durdur()
onay.panel_sil()
# ilk kurulum: hiç işaret yok, panelin imzalı kaydı yok → bugünkü davranış
for t in getattr(liste_koruma, "TUM", liste_koruma.TURLER):
    if os.path.exists(liste_koruma.isaret_yolu(t)):
        os.remove(liste_koruma.isaret_yolu(t))
os.remove(SahteKasa.yol)
liste_koruma._anahtar_unut()
os.remove(YASAK)
os.remove(SEVIYE)
kontrol("D1: ilk kurulum (işaret yok): yasak dosyası varsayılanla oluşur, seviye yok = kısıt yok",
        guvenlik._kullanici_yasaklari() == [] and os.path.exists(YASAK) and guvenlik.seviye_kurallari() == [])

# ================================================================ YN2: kod barındıran uygulamalar + yürütülebilir belgeler
sistem = {x["kimlik"]: x for x in uygulama.masaustu_girdileri()
          if x["yol"].startswith(uygulama.SISTEM_UYGULAMA_DIZINLERI)}
for kimlik in ("libreoffice-writer", "steam", "gimp", "blender", "org.inkscape.Inkscape", "net.lutris.Lutris",
               "winetricks", "protontricks", "GameConqueror", "com.visualstudio.code"):
    x = sistem.get(kimlik)
    if x is not None:
        n = uygulama.girdi_guvenilir(x)
        kontrol(f"YN2: sistem girdisi '{kimlik}' kod barındırır → onay ister", n is not None and "kod" in n, str(n))
for g_ in ({"kimlik": "org.godotengine.Godot", "exec": "godot4 %f"}, {"kimlik": "idle3.12", "exec": "/usr/bin/idle3.12"},
           {"kimlik": "jupyter-lab", "exec": "jupyter-lab"}, {"kimlik": "x", "exec": "/usr/bin/flatpak run org.gimp.GIMP"},
           {"kimlik": "pycharm", "exec": "/opt/pycharm/bin/pycharm.sh"}):
    kontrol(f"YN2: {g_['kimlik']} / {g_['exec']} kod barındıran sayılır", uygulama.kod_barindiran_mi(g_) is not None)
for kimlik in ("firefox", "org.kde.kate", "org.kde.dolphin", "org.kde.gwenview", "mpv"):
    x = sistem.get(kimlik)
    if x is not None and not uygulama._root_yazilamaz(x["yol"]):  # dosya güveni ayrı denetim; kod sınıfı yine sınanır
        kontrol(f"YN2: '{kimlik}' kod barındıran DEĞİL", uygulama.kod_barindiran_mi(x) is None)
        print(f"ATLANDI  YN2: '{kimlik}' onaysız kalır (girdi dosyası root sahipli/yazılamaz değil: {x['yol']})")
    elif x is not None:
        kontrol(f"YN2: '{kimlik}' kod barındıran DEĞİL (onaysız kalır)", uygulama.girdi_guvenilir(x) is None,
                str(uygulama.girdi_guvenilir(x)))
for uzanti in (".bat", ".exe", ".msi", ".ps1", ".py", ".sh", ".lua", ".pl", ".rb", ".js", ".jar", ".AppImage",
               ".desktop", ".yml", ".yaml", ".docm", ".xlsm", ".pptm", ".cmd", ".bash"):
    yol = os.path.join(G, "belge" + uzanti)
    open(yol, "w").write("x\n")
    kontrol(f"YN2: belge '{uzanti}' her uygulama için → 10 (yol ve file://)",
            kod_al(uygulama.belge_argumanlari, [yol]) == 10 and kod_al(uygulama.belge_argumanlari, [f"file://{yol}"]) == 10)
for uzanti in (".txt", ".pdf", ".png", ".odt", ".html"):
    yol = os.path.join(G, "belge" + uzanti)
    open(yol, "w").write("x\n")
    kontrol(f"YN2: sıradan belge '{uzanti}' kabul", uygulama.belge_argumanlari([yol]) == [yol])

# ================================================================ YN5: onaylı kullanıcı programı değişirse başlatılmaz
UYG = os.path.join(G, "uygulamalar")
os.makedirs(UYG, exist_ok=True)
prog = os.path.join(G, "benim-uygulamam")
shutil.copy("/usr/bin/true", prog)
open(os.path.join(UYG, "benim.desktop"), "w").write(f"[Desktop Entry]\nType=Application\nName=Benim\nExec={prog}\n")
eski_dizin, eski_iste = uygulama.UYGULAMA_DIZINLERI, onay.iste_sonuc
uygulama.UYGULAMA_DIZINLERI = (UYG,)
onay.iste_sonuc = lambda *a, **k_: onay.OnaySonucu(True, "izin")
try:
    uygulama.mcp_uygulama("benim")
    kontrol("YN5: değişmeyen onaylı program → başlatmadan önceki denetim geçer",
            kod_al(uygulama.onayli_program_denetle) == 0)
    uygulama.mcp_uygulama("benim")
    with open(prog, "ab") as f:
        f.write(b"\0degisti")  # onaydan sonra, başlatmadan önce programın içeriği değişir
    kontrol("YN5: onaydan sonra kullanıcı programı değişti → 10, başlatılmaz", kod_al(uygulama.onayli_program_denetle) == 10)
    kontrol("YN5: kayıt tek kullanımlık (sonraki onaysız başlatmayı etkilemez)", kod_al(uygulama.onayli_program_denetle) == 0)
finally:
    uygulama.UYGULAMA_DIZINLERI, onay.iste_sonuc = eski_dizin, eski_iste

# ================================================================ YK1: cwd + paket yolu
onay.panel_kaydet()
d = json.load(open(onay.panel_pid_yolu()))
kontrol("YK1: panel kaydı cwd ve paket yolunu taşır", d.get("cwd") == os.getcwd() and d.get("paket") == onay.paket_yolu())
json.dump(dict(d, cwd="/baska/dizin"), open(onay.panel_pid_yolu(), "w"))
s = onay.iste_sonuc("x", "y", sure=3)
kontrol("YK1: panel çalışma dizini kayıttakiyle aynı değil → red (kanal)", not s.izin and s.neden == "kanal", str(s))
json.dump(dict(d, paket="/tmp/ajanin-kopyasi/deskhand"), open(onay.panel_pid_yolu(), "w"))
s = onay.iste_sonuc("x", "y", sure=3)
kontrol("YK1: panelin paket yolu bu kurulumunki değil → red (kanal)", not s.izin and s.neden == "kanal", str(s))
onay.panel_sil()

print(f"\n{gecen}/{toplam} denetim-3 testi geçti")
sys.exit(0 if gecen == toplam else 1)
