"""Ayarlar sayfası panelin ETKİN değerini gösterir (kullanıcı hatası 27 Kas 16:46).

Kök neden: gui/panel.py Panel.__init__ AnaPencere'yi (→ AyarlarSekmesi) liste_koruma.panel_baslat'tan ÖNCE kurar;
AyarlarSekmesi kurulurken A.onay_kapsami_oku() / A.hesap_oturumlari_oku() liste_koruma.AKTIF None iken çağrılır →
panel kendi kanalını soramaz → "hepsi" / boş küme. Arka uç (koruyucu belleği) ise kayıtlı 'kart' + üç sağlayıcıyı
uygular: arayüz ile arka uç tutarsız.

Senaryo: 1. süreç (panel) Ayarlar'dan 'kart' + Microsoft/Google/e-Devlet açar (imzalı durum sahte kasada) → panel
kapanır → 2. süreç (panel yeniden başlatma) Ayarlar'ı gösterir: kutular işaretli + 'Yalnız kartla ödeme'; pencere
gizle/göster ve sekme değişimi sonrası da aynı. Ekransız (offscreen), sahte kasa, gerçek ~/.config yazılmaz.
Çalıştır: python3 tests/test_ayar_yukleme.py"""
import os
import subprocess
import sys
import textwrap

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _yalitim  # noqa: E402,F401

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


ORTAK = textwrap.dedent('''
    import os, sys, json
    sys.path.insert(0, os.environ["DESKHAND_KOK"])
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    import faulthandler; faulthandler.dump_traceback_later(25, exit=True)
    from deskhand import liste_koruma

    class SahteKasa:  # panelin imzalı durumu (Secret Service yerine dosya); gerçek cüzdana dokunulmaz
        yol = os.path.join(os.environ["DESKHAND_STATE_DIR"], "sahte-kasa.json")
        def oku(self):
            try:
                return open(self.yol, "rb").read()
            except FileNotFoundError:
                return None
        def yaz(self, v):
            open(self.yol, "wb").write(v)
    liste_koruma.isaret_anahtarlik_ayarla(SahteKasa())

    from deskhand.gui.panel import Panel
    # yasak/seviye ilk süreçte imzalanmadı: açılıştaki "doğrulanamadı" sorusu kalıcı Hayır (modal diyalog açılmaz)
    Panel._degisiklik_onayla = lambda self, *a, **k: False
    Panel._kalici_onayla = lambda self, *a, **k: False

    class SahteKisayol(QObject):
        basildi = pyqtSignal()
        hata = pyqtSignal(str)
        acik = False
        def ac(self, tus): self.acik = True
        def kapat(self, kaydi_sil=True): self.acik = False

    class SahteMasaustu:
        @classmethod
        def durum(cls, dogrula=True): return {"ekran": ":91", "boyut": [1920, 1080, 24]}

    uyarilar = []
    p = Panel(app, None, tepsi=False, kisayol=SahteKisayol(), diyalog_kurma_ms=0, arka_f=lambda: None,
              masaustu_m=SahteMasaustu, cakisma_f=lambda t: [], simge_sor=lambda b, m: False, saglik_f=lambda: [])
    w = p.pencere.ayarlar

    def gorunen():
        return {"kapsam": w.c_onay.currentData(), "kutular": sorted(s for s, k in w.k_hesap.items() if k.isChecked()),
                "hepsi": w.k_hesap_hepsi.isChecked(),
                "etkin_kapsam": liste_koruma.kapsam(), "etkin_kimlik": sorted(liste_koruma.kimlik_izinleri())}
''')

YAZ = ORTAK + textwrap.dedent('''
    w.hesap_onay_sor = lambda sag: True  # kullanıcı onay diyaloğunda "Evet"
    i = w.c_onay.findData("kart")
    w.c_onay.setCurrentIndex(i)
    w.c_onay.activated.emit(i)
    for s in ("microsoft", "google", "edevlet"):
        w.k_hesap[s].setChecked(True)
    w.uygula()  # tek kaydetme modeli (UX-A): alanlar yalnız işaretler, Uygula yazar
    print("SONUC " + json.dumps(gorunen()), flush=True)
    liste_koruma.panel_durdur()
    os._exit(0)
''')

OKU = ORTAK + textwrap.dedent('''
    print("ILK " + json.dumps(gorunen()), flush=True)
    p.goster(); app.processEvents()
    p.pencere.hide(); app.processEvents()           # pencere kapat / aç
    p.goster(); app.processEvents()
    sekmeler = p.pencere.findChild(__import__("PyQt6.QtWidgets", fromlist=["QTabWidget"]).QTabWidget)
    if sekmeler is not None:                          # sekme değişimi
        sekmeler.setCurrentIndex(0); app.processEvents()
        sekmeler.setCurrentWidget(w); app.processEvents()
    print("SONRA " + json.dumps(gorunen()), flush=True)
    from deskhand import ayarlar as _ay
    _ay.ayarla("guvenlik", "hesap_oturumlari", "microsoft")  # dosyaya panel dışında yazılmış (doğrulanmamış) değer
    w.panel_degerleri_yukle()
    print("ETIKET " + json.dumps({"hesap": w.l_hesap.text(), "kutular": gorunen()["kutular"]}), flush=True)
    liste_koruma.panel_durdur()
    os._exit(0)
''')


def kos(kod):
    env = dict(os.environ, DESKHAND_KOK=_yalitim.KOK)
    try:
        return subprocess.run([sys.executable, "-c", kod], env=env, capture_output=True, text=True, timeout=40)
    except subprocess.TimeoutExpired as e:  # kısmi çıktı + nerede takıldığı raporda görünsün
        def _m(x):
            return x.decode(errors="replace") if isinstance(x, bytes) else (x or "")
        return subprocess.CompletedProcess(e.cmd, -9, _m(e.stdout), "ZAMAN AŞIMI " + _m(e.stderr))


def json_satir(cikti, onek):
    import json
    for s in cikti.splitlines():
        if s.startswith(onek + " "):
            return json.loads(s[len(onek) + 1:])
    return None


HEPSI = ["edevlet", "google", "microsoft"]
r = kos(YAZ)
y = json_satir(r.stdout, "SONUC")
kontrol("1. panel: Ayarlar'dan 'kart' + üç hesap açıldı (arka uç da aynı)",
        y is not None and y["etkin_kapsam"] == "kart" and y["etkin_kimlik"] == HEPSI and y["kutular"] == HEPSI,
        f"rc={r.returncode} {y} {r.stderr[-800:]}")

r = kos(OKU)
ilk, sonra = json_satir(r.stdout, "ILK"), json_satir(r.stdout, "SONRA")
kontrol("2. panel (yeniden başlatma): arka uç kayıtlı değeri uygular (kart + üç hesap)",
        ilk is not None and ilk["etkin_kapsam"] == "kart" and ilk["etkin_kimlik"] == HEPSI,
        f"rc={r.returncode} {ilk} {r.stderr[-800:]}")
kontrol("2. panel: Ayarlar 'Yalnız kartla ödeme' gösterir (arka uçla aynı)",
        ilk is not None and ilk["kapsam"] == ilk["etkin_kapsam"] == "kart", str(ilk))
kontrol("2. panel: Hesap oturumları kutuları işaretli (ana anahtar dahil)",
        ilk is not None and ilk["kutular"] == HEPSI and ilk["hepsi"], str(ilk))
kontrol("pencere kapat/aç + sekme değişimi sonrası da aynı",
        sonra is not None and sonra["kapsam"] == "kart" and sonra["kutular"] == HEPSI and sonra["hepsi"], str(sonra))

e = json_satir(r.stdout, "ETIKET")
kontrol("dosyada doğrulanmamış farklı değer: kutular ETKİN değeri gösterir + açık etiket",
        e is not None and e["kutular"] == HEPSI and "doğrulanmamış" in e["hesap"] and "Microsoft" in e["hesap"], str(e))

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
