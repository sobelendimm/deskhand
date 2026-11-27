"""Görsel taban + erişilebilirlik (AT-SPI) kural denetimi ortak kodu (UX turu, G1).

Kütüphane (testler içe aktarır; Qt/deskhand İÇE AKTARMAZ):
  sabit_ortam(ev, **ek)        env -i benzeri sabit ortam (kullanıcı yazı tipi/tema/ölçek ayarı sızmaz)
  cek(cikti, varyant)          bir varyantın ekranlarını AYRI süreçte (sabit ortam, offscreen, Fusion) PNG'ye çeker
  kiyasla(a, b, fark_yol)      birebir piksel kıyası (eşik 0) → fark piksel sayısı (-1: boyut farklı); fark varsa
                               fark_yol'a kırmızı işaretli fark PNG'si yazar
  diyalog_istekleri(s)         onay diyaloğu örnek istekleri (görsel taban + tasarım kapısı ortak)
  ihlaller(ogeler)             AT-SPI öğe listesinden kural ihlalleri (adsız düğme/giriş, boş ad, hedef < 24×24,
                               odak alamayan etkileşimli öge)
  anahtar(ihlal)               ihlalin koordinatsız kimliği (bilinen listesi için)

Komut satırı (alt süreç kipleri):
  python3 -I tests/_gorsel.py cek CIKTI DIL TEMA OLCEK DURUM   panel sekmelerini çeker (DURUM: - | dur)
  python3 -I tests/_gorsel.py diyalog CIKTI DIL                onay diyaloğu 3 tür
  python3 -I tests/_gorsel.py panel                            görünmez masaüstünde paneli açar (LOG/KOMUT env)
  python3 -I tests/_gorsel.py atspi-oku BASLIK                 AT_SPI_BUS_ADDRESS'teki pencerenin ağacı → JSON

Sabit ortam değerleri ve eşik: kart-DHG/UX/deneme/rapor-GORSEL-DENEME.md ("Plan için kesin değerler")."""
import json
import os
import subprocess
import sys
import time

TESTLER = os.path.dirname(os.path.abspath(__file__))
KOK = os.path.dirname(TESTLER)
SABIT_SAAT = 1_800_000_000.0  # diyalog geri sayımı göreli değil sabit saatle çizilir (saniye kayması fark yaratmaz)
# (ad, dil, tema, ölçek, durum, yalnız_ilk_sekme)
VARYANTLAR = [
    ("tr-acik-1.0", "tr", "acik", "1.0", "-", False),
    ("tr-koyu-1.0", "tr", "koyu", "1.0", "-", False),
    ("en-acik-1.25", "en", "acik", "1.25", "-", False),
    ("tr-acik-1.0-dur", "tr", "acik", "1.0", "dur", True),
]
DIYALOGLAR = ("odeme", "tus", "devir")
TOKENS = os.path.join(KOK, "deskhand", "gui", "tema", "tokens.json")


def _token_hedef_min() -> int:
    """Tıklama hedefi alt sınırı tokens.json'dan (min_tiklama_hedefi_px; yoksa WCAG 2.5.8 = 24 px)."""
    try:
        with open(TOKENS, encoding="utf-8") as f:
            v = json.load(f).get("min_tiklama_hedefi_px", 24)
    except (OSError, ValueError):
        v = 24
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else 24


HEDEF_MIN = _token_hedef_min()
DUGME = ("push button", "button", "toggle button", "check box", "radio button", "menu item", "page tab")
GIRIS = ("text", "entry", "password text", "spin button", "combo box", "editbar")


def sabit_ortam(ev: str, **ek) -> dict:
    """env -i karşılığı: yalnız PATH + geçici HOME/XDG_* + sabit Qt değişkenleri (+ ek)."""
    for alt in ("c", "s", "ca", "d", "r"):
        os.makedirs(os.path.join(ev, alt), mode=0o700, exist_ok=True)
    e = {"PATH": "/usr/bin:/bin", "HOME": ev, "LANG": "C.UTF-8",
         "XDG_CONFIG_HOME": os.path.join(ev, "c"), "XDG_STATE_HOME": os.path.join(ev, "s"),
         "XDG_CACHE_HOME": os.path.join(ev, "ca"), "XDG_DATA_HOME": os.path.join(ev, "d"),
         "XDG_RUNTIME_DIR": os.path.join(ev, "r"), "DESKHAND_ANAHTARLIK": "kapali",
         "QT_QPA_PLATFORM": "offscreen", "QT_NO_GLIB": "1", "QT_SCALE_FACTOR": "1.0", "DESKHAND_DIL": "tr"}
    e.update({k: str(v) for k, v in ek.items()})
    return e


def cek(cikti: str, varyant: tuple, ev: str, zaman: int = 90) -> subprocess.CompletedProcess:
    """Varyantın ekranlarını ayrı süreçte çeker (her süreç kendi geçici HOME'unda)."""
    ad, dil, tema, olcek, durum, _ilk = varyant
    return subprocess.run([sys.executable, "-I", os.path.abspath(__file__), "cek", cikti, dil, tema, olcek, durum],
                          env=sabit_ortam(ev, QT_SCALE_FACTOR=olcek, DESKHAND_DIL=dil), capture_output=True,
                          text=True, timeout=zaman, cwd=ev)


def diyalog_cek(cikti: str, dil: str, ev: str, zaman: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", os.path.abspath(__file__), "diyalog", cikti, dil],
                          env=sabit_ortam(ev, DESKHAND_DIL=dil), capture_output=True, text=True, timeout=zaman, cwd=ev)


def kiyasla(a, b, fark_yol: str | None = None) -> int:
    """Birebir kıyas (herhangi bir kanal farkı > 0). → fark piksel sayısı; boyut farklıysa -1."""
    import numpy as np
    from PIL import Image
    ia = Image.open(a) if isinstance(a, str) else a
    ib = Image.open(b) if isinstance(b, str) else b
    A = np.asarray(ia.convert("RGBA"), dtype=np.int16)
    B = np.asarray(ib.convert("RGBA"), dtype=np.int16)
    if A.shape != B.shape:
        return -1
    m = np.abs(A - B).max(axis=2) > 0
    n = int(m.sum())
    if n and fark_yol:
        o = np.asarray(ib.convert("RGB")).copy()
        o[m] = (255, 0, 0)
        Image.fromarray(o).save(fark_yol)
    return n


def ihlaller(ogeler: list[dict]) -> list[dict]:
    """Görünen etkileşimli öğelerde kural ihlalleri. Öge: rol, ad (ham), w, h, gorunur, odak, etkin, yol."""
    out = []
    for o in ogeler:
        if not o.get("gorunur") or "rol" not in o:
            continue
        rol, ad = o["rol"], o.get("ad")
        dugme, giris = rol in DUGME, rol in GIRIS
        if not (dugme or giris):
            continue
        kurallar = []
        if not ad:
            kurallar.append("ADSIZ_DUGME" if dugme else "ADSIZ_GIRIS")
        elif not ad.strip():
            kurallar.append("BOS_AD")
        if o.get("w", 0) < HEDEF_MIN or o.get("h", 0) < HEDEF_MIN:
            kurallar.append("HEDEF_KUCUK")
        if o.get("etkin") and not o.get("odak"):
            kurallar.append("ODAK_YOK")
        for k in kurallar:
            out.append({"kural": k, "rol": rol, "ad": ad or "", "boyut": f"{o.get('w')}x{o.get('h')}",
                        "yol": o.get("yol", ""), "sekme": o.get("sekme", "")})
    return out


def diyalog_istekleri(s: float = SABIT_SAAT) -> dict:
    """Onay diyaloğu örnek istekleri (DIYALOGLAR sırasıyla; görsel taban + tasarım kapısı ortak). deskhand.onay
    işlev içinde içe aktarılır (modül Qt/deskhand içe aktarmaz)."""
    from deskhand import onay
    return {
        "odeme": {"id": "a1", "konu": "odeme", "eylem": "Düğmeye tıkla: “Öde”", "hedef": "Trendyol — Sepetim — Firefox",
                  "masaustu": "arka", "masa": "", "ayrinti": "HASSAS düğme ('öde' ← ['Öde', 'Siparişi tamamla'])",
                  "zaman": s, "son_zaman": s + 118, "pid": 4242},
        "tus": {"id": "a2", "konu": "tus", "eylem": "Riskli tuş: ctrl+w", "hedef": "Belge — KWrite", "masaustu": "ekran",
                "ayrinti": "pencere kapatma kısayolu\ntuş: ctrl+w", "zaman": s, "son_zaman": s + 100},
        "devir": {"id": "a3", "tur": onay.TUR_DEVIR, "eylem": "CAPTCHA", "hedef": "Giriş — Firefox",
                  "masaustu": "arka", "zaman": s, "son_zaman": s + 300},
    }


def anahtar(i: dict) -> str:
    """Koordinatsız, sekmeden bağımsız kimlik: kural | rol | ad | ata zinciri (rol:ad; sekme sayfası zincirde)."""
    return f"{i['kural']}|{i['rol']}|{i['ad']}|{i['yol']}"


# =========================================================================== alt süreç kipleri
def _app(tema: str):
    """Fusion + panel teması (tokens.json; gui.tema.tema_uygula) — panelin kendi tema_uygula("sistem") çağrısı bu
    paletin koyu/açık oluşuna göre aynı kipi seçer."""
    from PyQt6.QtWidgets import QApplication

    from deskhand.gui.tema import tema_uygula
    app = QApplication([])
    app.setStyle("Fusion")
    tema_uygula(app, tema)
    return app


def _panel_kur(app):
    """Gerçek AnaPencere; tepsi, genel kısayol, sanal masaüstü, sağlık ve onay soruları SAHTE (yan etki yok)."""
    from PyQt6.QtCore import QObject, pyqtSignal

    from deskhand import liste_koruma, yollar
    os.makedirs(yollar.gunluk_dizin(), exist_ok=True)
    with open(os.path.join(yollar.gunluk_dizin(), time.strftime("gunluk-%Y%m%d.log")), "w") as f:
        for s in ("10:01:02 tikla (856,657) sol | [GitHub | Ayarlar — Firefox] | mouseto 0.33 0.45",
                  "10:01:05 yaz 12 karakter | arka :90 [Belge — KWrite] | type 'merhaba dünya'",
                  "10:01:09 onay izin | arka sanal [Ödeme] | tıkla 'Öde'",
                  "10:01:20 DUR 4 | yaz {d7bf} | başlık değişti: 'x' (beklenen /y/)",
                  "10:02:00 ac | kcalc | kcalc", "10:02:11 bas w | bırak | keyup w"):
            f.write(s + "\n")

    class Kasa:  # anahtarlık yerine bellek içi (gerçek KDE Cüzdanı okunmaz)
        deger = None

        def oku(self):
            return self.deger

        def yaz(self, v):
            self.deger = v
    liste_koruma.isaret_anahtarlik_ayarla(Kasa())
    from deskhand.gui.panel import Panel
    Panel._degisiklik_onayla = lambda self, *a, **k: False
    Panel._kalici_onayla = lambda self, *a, **k: False

    class Kisayol(QObject):
        basildi = pyqtSignal()
        hata = pyqtSignal(str)

        def ac(self, t):
            pass

        def kapat(self, kaydi_sil=True):
            pass

    class Masaustu:
        @classmethod
        def durum(cls, dogrula=True):
            return {"ekran": ":91", "boyut": [2560, 1440, 24]}
    return Panel(app, None, tepsi=False, kisayol=Kisayol(), diyalog_kurma_ms=0, arka_f=lambda: None,
                 masaustu_m=Masaustu, cakisma_f=lambda t: [], simge_sor=lambda b, m: False, saglik_f=lambda: [])


def _bekle(app, sn):
    son = time.monotonic() + sn
    while time.monotonic() < son:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def _kip_cek(cikti, dil, tema, olcek, durum):
    sys.path.insert(0, TESTLER)
    import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler)
    os.environ["DESKHAND_DIL"] = dil
    os.makedirs(cikti, exist_ok=True)
    app = _app(tema)
    w = _panel_kur(app).pencere
    w.show()
    app.processEvents()
    ilk = durum == "dur"
    if ilk:
        from deskhand.gui.durum import Durum
        w.durum_guncelle(Durum(ad="dur", dur_kaynak="kullanici", bekleyen=2, sanal_acik=True, sanal_ekran=":91"))
    app.processEvents()
    etiket = f"{dil}-{tema}-{olcek}" + ("-dur" if ilk else "")
    for i in range(1 if ilk else w.sekmeler.count()):
        w.sekmeler.setCurrentIndex(i)
        _bekle(app, 0.15)  # sekme geçiş çizimi
        w.grab().save(os.path.join(cikti, f"{etiket}-sekme{i}.png"))
        print("CEKILDI", f"{etiket}-sekme{i}.png", w.sekmeler.tabText(i), flush=True)
    os._exit(0)


def _kip_diyalog(cikti, dil):
    sys.path.insert(0, TESTLER)
    import _yalitim  # noqa: F401
    os.environ["DESKHAND_DIL"] = dil
    os.makedirs(cikti, exist_ok=True)
    app = _app("acik")
    from deskhand.gui.onay_diyalog import OnayDiyalog
    istekler = diyalog_istekleri()
    for ad in DIYALOGLAR:
        d = OnayDiyalog(istekler[ad], yanitla=lambda k, v: True, istek_var=lambda: True, kurma_ms=0,
                        saat=lambda: SABIT_SAAT)
        d.show()
        app.processEvents()
        d.grab().save(os.path.join(cikti, f"diyalog-{dil}-{ad}.png"))
        print("CEKILDI", f"diyalog-{dil}-{ad}.png", flush=True)
    os._exit(0)


def _kip_panel():
    """Görünmez masaüstünde (bwrap: ev dizini görünmez) panel: deskhand kopyası GORSEL_KOD'dan; KOMUT dosyasındaki
    'sekme N' ile sekme değiştirir, LOG'a 'hazir' / 'sekme N' yazar."""
    sys.path.insert(0, os.environ["GORSEL_KOD"])
    sys.path.insert(0, TESTLER)
    os.environ.setdefault("QT_LINUX_ACCESSIBILITY_ALWAYS_ON", "1")
    log, komut = os.environ["LOG"], os.environ["KOMUT"]
    from PyQt6.QtCore import QTimer
    app = _app("acik")
    w = _panel_kur(app).pencere
    w.show()

    def yaz(s):
        with open(log, "a") as f:
            f.write(s + "\n")
    son = [""]

    def dinle():
        try:
            with open(komut) as f:
                k = f.read().strip()
        except OSError:
            return
        if k and k != son[0]:
            son[0] = k
            if k.startswith("sekme "):
                w.sekmeler.setCurrentIndex(int(k.split()[1]))
                QTimer.singleShot(300, lambda: yaz(k + " " + w.sekmeler.tabText(w.sekmeler.currentIndex())))
            elif k == "cik":
                app.quit()
    t = QTimer()
    t.timeout.connect(dinle)
    t.start(50)
    QTimer.singleShot(800, lambda: yaz(f"hazir {w.sekmeler.count()}"))
    app.exec()
    os._exit(0)


def _kip_atspi_oku(baslik):
    """Ayrı süreç şart: libatspi süreç başına tek veri yoluna bağlanır (AT_SPI_BUS_ADDRESS)."""
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi
    t0 = time.perf_counter()
    d = Atspi.get_desktop(0)
    pen = None
    for i in range(d.get_child_count()):
        a = d.get_child_at_index(i)
        for j in range(a.get_child_count() if a else 0):
            c = a.get_child_at_index(j)
            if c is not None and (c.get_name() or "") == baslik:
                pen = c
    if pen is None:
        print(json.dumps({"hata": "pencere yok", "uygulamalar": d.get_child_count()}))
        sys.exit(1)
    S, W = Atspi.StateType, Atspi.CoordType.WINDOW
    out = []

    def yuru(o, yol):
        try:
            ss = o.get_state_set()
            rol, ad, e = o.get_role_name(), o.get_name(), o.get_extents(W)
            out.append({"rol": rol, "ad": ad, "w": e.width, "h": e.height, "x": e.x, "y": e.y, "yol": "/".join(yol),
                        "gorunur": ss.contains(S.SHOWING), "odak": ss.contains(S.FOCUSABLE),
                        "etkin": ss.contains(S.SENSITIVE)})
            alt = yol + [f"{rol}:{(ad or '').strip()}"]
            for i in range(o.get_child_count()):
                c = o.get_child_at_index(i)
                if c is not None:
                    yuru(c, alt)
        except Exception as ex:  # noqa: BLE001 - kaybolan öge ağacı bozmasın; hata kaydı ağaçta görünür
            out.append({"hata": str(ex), "yol": "/".join(yol)})
    yuru(pen, [])
    print(json.dumps({"sure_ms": round((time.perf_counter() - t0) * 1000, 1), "n": len(out), "ogeler": out},
                     ensure_ascii=False))


if __name__ == "__main__":
    k, arg = sys.argv[1], sys.argv[2:]
    if k == "cek":
        _kip_cek(*arg)
    elif k == "diyalog":
        _kip_diyalog(*arg)
    elif k == "panel":
        _kip_panel()
    elif k == "atspi-oku":
        _kip_atspi_oku(arg[0])
    else:
        sys.exit(f"bilinmeyen kip: {k}")
