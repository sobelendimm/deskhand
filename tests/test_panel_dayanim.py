"""Panel dayanıklılığı: slottan (QTimer) yakalanmayan istisna paneli ÖLDÜRMEZ (PyQt6 varsayılanı qFatal → SIGABRT, 134).
Genel yakalayıcı (gui/panel.py istisna_yakalayici_kur) günlüğe yazar, tepsiden uyarır, süreç sürer; DUR düğmesi hâlâ
çalışır. Devral dosyası yazılamazsa (ENOSPC / yazılamayan yol) Devral açılmaz, panel yaşar. Qt GÖRÜNMEZ (offscreen);
her senaryo ayrı alt süreçte (çıkış kodu ölçülür).

Çalıştır:  python3 tests/test_panel_dayanim.py"""
import os
import subprocess
import sys
import textwrap

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
os.environ["XDG_CONFIG_HOME"] = "/nonexistent-deskhand-test"
import _yalitim  # noqa: E402,F401

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


ORTAK = textwrap.dedent('''
    import os, sys, time, threading, errno
    sys.path.insert(0, os.environ["DESKHAND_KOK"])
    from PyQt6.QtCore import QObject, QTimer, pyqtSignal
    from PyQt6.QtTest import QTest
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])

    def bekle(kosul, sure=3.0):
        son = time.monotonic() + sure
        while time.monotonic() < son:
            app.processEvents()
            if kosul():
                return True
            time.sleep(0.01)
        return kosul()

    def patla():
        raise OSError(errno.ENOSPC, "No space left on device")
''')

PANEL = ORTAK + textwrap.dedent('''
    from deskhand import guvenlik, yollar
    from deskhand.gui.panel import Panel, istisna_yakalayici_kur

    class SahteKisayol(QObject):
        basildi = pyqtSignal()
        hata = pyqtSignal(str)
        acik = False
        def ac(self, tus): self.acik = True
        def kapat(self, kaydi_sil=True): self.acik = False

    class SahteMasaustu:
        @classmethod
        def durum(cls, dogrula=True): return {"ekran": ":91", "boyut": [1920, 1080, 24]}

    class SahteIkon:
        def __init__(self): self.iletiler = []
        def showMessage(self, *a): self.iletiler.append(a[1])
        def isSystemTrayAvailable(self): return False

    class SahteTepsi:
        def __init__(self): self.ikon = SahteIkon()
        def guncelle(self, d): pass
        def tazele(self): pass
        def goster(self): pass

    p = Panel(app, None, tepsi=False, kisayol=SahteKisayol(), diyalog_kurma_ms=0, arka_f=lambda: None,
              masaustu_m=SahteMasaustu, cakisma_f=lambda t: [], simge_sor=lambda b, m: False, saglik_f=lambda: [])
    p.tepsi = SahteTepsi()
    istisna_yakalayici_kur(p)
    oldu = []
    QTimer.singleShot(0, patla)
    QTimer.singleShot(5, patla)  # ikinci hata: bildirim seyreltilir (tek bildirim)
    QTimer.singleShot(30, lambda: oldu.append(1))
    bekle(lambda: oldu)
    t = threading.Thread(target=patla, name="isci-x")
    t.start(); t.join()
    print("YASIYOR")
    print("BILDIRIM", len(p.tepsi.ikon.iletiler), p.tepsi.ikon.iletiler[:1])
    # DUR düğmesi hâlâ çalışıyor
    QTest.mouseClick(p.pencere.b_dur if hasattr(p.pencere, "b_dur") else p.pencere.serit.b_dur,
                     Qt.MouseButton.LeftButton)
    print("DUR", bekle(lambda: guvenlik.dur_acik()))
    guvenlik.dur_kapat("kullanici")
    # Devral dosyası yazılamıyor: Devral açılmaz, panel yaşar
    a = p.pencere.arka
    a.devral_yolu_f = lambda: "/proc/deskhand-yok/devral"
    a.sanal = {"ekran": ":91", "boyut": [1920, 1080, 24]}
    a.b_devral.setEnabled(True)
    a.b_devral.setChecked(True)
    app.processEvents()
    print("DEVRAL", a.b_devral.isChecked(), a.l_not.text())
    g = os.path.join(yollar.gunluk_dizin(), time.strftime("gunluk-%Y%m%d.log"))
    metin = open(g).read()
    print("GUNLUK", metin.count("PANEL HATASI (slot)"), metin.count("PANEL HATASI (iş parçacığı isci-x)"),
          "Devral açılamadı" in metin)
    p.cik()
    print("SON")
''')

KANCASIZ = ORTAK + textwrap.dedent('''
    QTimer.singleShot(0, patla)
    QTimer.singleShot(200, app.quit)
    app.exec()
    print("YASIYOR")
''')


def kos(kod):
    env = dict(os.environ, DESKHAND_KOK=_yalitim.KOK)
    return subprocess.run([sys.executable, "-c", kod], env=env, capture_output=True, text=True, timeout=60)


# Önce kanıt: yakalayıcı olmadan PyQt6 slottaki istisnada süreci SIGABRT ile öldürür (bulgunun kendisi)
r = kos(KANCASIZ)
kontrol("yakalayıcısız: slottaki OSError(28) → SIGABRT (bulgu yeniden üretildi)", r.returncode in (-6, 134) and
        "YASIYOR" not in r.stdout, f"rc={r.returncode}")

r = kos(PANEL)
c = r.stdout
kontrol("yakalayıcılı: süreç yaşadı ve düzgün bitti", r.returncode == 0 and "YASIYOR" in c and "SON" in c,
        f"rc={r.returncode} {r.stderr[-600:]}")
kontrol("tepsi uyarısı: tek bildirim (seyreltildi), metin hata özetini içeriyor",
        "BILDIRIM 1" in c and "OSError" in c, c)
kontrol("istisna stderr'e iz olarak yazıldı", "No space left on device" in r.stderr and "Traceback" in r.stderr)
kontrol("istisnadan sonra DUR düğmesi çalışıyor", "DUR True" in c, c)
kontrol("Devral dosyası yazılamadı → Devral kapalı kaldı + not gösterildi", "DEVRAL False Kontrol alınamadı" in c, c)
sat = next((s for s in c.splitlines() if s.startswith("GUNLUK")), "")
kontrol("günlük: iki slot hatası + iş parçacığı hatası + Devral hatası", sat == "GUNLUK 2 1 True", sat)

print(f"\n{gecen}/{toplam} test geçti")
sys.exit(0 if gecen == toplam else 1)
