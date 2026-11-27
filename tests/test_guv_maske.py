"""0.9.1 security fixes (branch guv-091-maske): preview masking of forbidden windows and Firefox session-cookie copy.

Headless: Qt offscreen, fake backends, fake Firefox profile in a temp folder (test data uses *.test / example.com only).
Covers:
  1. a class read that fails once is NOT cached; the frame is dropped instead of shown unmasked
  2. window list is taken before AND after the frame: a window that closes/moves in between is still masked
  3. KWin: the mask uses the FRAME geometry (title bar included), in the preview and in api.goruntu_al
  4. expired session cookies in recovery.jsonlz4 are skipped; the new lifetime never exceeds the source expiry
  5. a wildcard reject rule (`*bank*`) that matches a known subdomain rejects the parent domain cookie too
  6. the copied cookies.sqlite holds no bytes of a removed cookie value (rebuilt, not just DELETE)

Run:  python3 tests/test_guv_maske.py
"""
import json
import os
import sqlite3
import struct
import sys
import tempfile
import time
import types

import _yalitim  # noqa: F401  (DESKHAND_* temp dirs; before Deskhand)

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PIL import Image  # noqa: E402
from PyQt6.QtCore import QSize  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from deskhand.gui import onizleme  # noqa: E402
from deskhand.gui.gorev import GorevSekmesi  # noqa: E402
from deskhand.gui.pencere import ArkaPlanSekmesi  # noqa: E402
from deskhand.oturum import firefox, politika  # noqa: E402

app = QApplication([])
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


# ------------------------------------------------------------------ preview fakes

class SahteAu:
    """Fake background desktop: 200x100 white screen; one window drawn red. Forbidden only by CLASS 'deskhand'."""

    def __init__(self, pencereler, sinif=None):
        self._p = pencereler          # callable(call_no) -> list[(k, title, geo)]
        self._sinif = sinif or (lambda k, n: "deskhand")
        self.liste_cagri = 0
        self.sinif_cagri = 0
        self.olaylar = []

    def ekran_alani(self):
        return (0, 0, 200, 100)

    def pencereler(self, desen=None):
        self.liste_cagri += 1
        self.olaylar.append("liste")
        return self._p(self.liste_cagri)

    def sinif(self, k):
        self.sinif_cagri += 1
        return self._sinif(k, self.sinif_cagri)

    def goruntu(self):
        self.olaylar.append("kare")
        im = Image.new("RGB", (200, 100), (255, 255, 255))
        im.paste((255, 0, 0), (20, 10, 80, 60))   # the secret window's pixels
        return im


class SahteOnizleme:
    def __init__(self):
        self.kaynak = QSize(0, 0)
        self.bos_metin = ""
        self.son = "yok"

    def hedef_boyut(self):
        return QSize(200, 100)

    def goster(self, q, kaynak=None):
        self.son = q


def _ozne(cls_ad, au):
    o = types.SimpleNamespace(sanal=object(), calisiyor=True, _sinif_onb={}, onizleme=SahteOnizleme(),
                              arka_f=lambda: au, _gorunur=lambda: True,
                              zaman=types.SimpleNamespace(stop=lambda: None),
                              l_eylem=types.SimpleNamespace(isVisible=lambda: False))
    return o


def _kare(cls, au, o=None):
    o = o or _ozne(cls.__name__, au)
    cls.kare(o)
    return o


def _kirmizi_var(q) -> bool:
    if q is None or q == "yok":
        return False
    return any(q.pixelColor(x, y).red() > 200 and q.pixelColor(x, y).green() < 50
               for x in range(20, 80, 5) for y in range(10, 60, 5))


def test_sinif_onbellek():
    for cls in (ArkaPlanSekmesi, GorevSekmesi):
        ad = cls.__name__

        def sinif(k, n):
            if n == 1:
                raise RuntimeError("class read failed")
            return "deskhand"
        au = SahteAu(lambda n: [("w1", "Ayarlar", (20, 10, 60, 50))], sinif)
        o = _kare(cls, au)
        kontrol(f"1 {ad}: sınıf okunamayınca kare GÖSTERİLMEZ", o.onizleme.son is None, repr(o.onizleme.son))
        kontrol(f"1 {ad}: başarısız okuma önbelleğe yazılmadı", "w1" not in o._sinif_onb, str(o._sinif_onb))
        o = _kare(cls, au, o)
        kontrol(f"1 {ad}: sonraki karede sınıf yeniden okunur ve pencere karartılır",
                o.onizleme.son not in (None, "yok") and not _kirmizi_var(o.onizleme.son))


def test_yaris():
    for cls in (ArkaPlanSekmesi, GorevSekmesi):
        ad = cls.__name__
        # the forbidden window is listed only BEFORE the frame (it closes/moves right after the grab)
        au = SahteAu(lambda n: [("w1", "Ayarlar", (20, 10, 60, 50))] if n == 1 else [])
        o = _kare(cls, au)
        kontrol(f"2 {ad}: kare ile liste arasında kapanan yasak pencere yine karartılır",
                o.onizleme.son not in (None, "yok") and not _kirmizi_var(o.onizleme.son), str(au.olaylar))
        # the window appears only AFTER the frame was taken (list after the grab)
        au = SahteAu(lambda n: [] if n == 1 else [("w1", "Ayarlar", (20, 10, 60, 50))])
        o = _kare(cls, au)
        kontrol(f"2 {ad}: kareden sonra listeye düşen yasak pencere de karartılır",
                o.onizleme.son not in (None, "yok") and not _kirmizi_var(o.onizleme.son), str(au.olaylar))


def test_kwin_cerceve():
    from deskhand import api
    from deskhand.arka_uc import ARKA_ONEK
    from deskhand.arka_uc.kwin import KwinArkaUc
    au = KwinArkaUc()
    uuid = "{12345678-1234-1234-1234-123456789abc}"
    # client area starts at y=40; the title bar (frame) starts at y=10 and shows the secret document name
    au._liste = lambda d=None: [{"i": uuid, "t": "gizli-belge.kdbx - Ayarlar", "c": "deskhand", "p": 1, "m": False,
                                 "x": 0, "g": [20, 40, 60, 20], "f": [20, 10, 60, 50]}]
    au.ekran_alani = lambda: (0, 0, 200, 100)
    au.goruntu = lambda: SahteAu(None).goruntu()
    au.sinif = lambda k: "deskhand"
    kutular = onizleme.yasak_kutulari(au, (200, 100), {})
    kontrol("3 önizleme (KWin): maske başlık çubuğunu da kapsar (çerçeve geometrisi)",
            kutular and min(k[1] for k in kutular) <= 10, str(kutular))
    eski_arka, eski_yasak = api.arka, api.yasak_mi
    api.arka = lambda: au
    api.yasak_mi = lambda k: "test" if k == ARKA_ONEK + uuid else None
    try:
        m = api._yasak_dikdortgenler("ekran", (0, 0), (200, 100))
    finally:
        api.arka, api.yasak_mi = eski_arka, eski_yasak
    kontrol("3 api.goruntu_al (KWin): ajanın görüntüsünde de maske çerçeveden",
            m and m[0]["box"][1] <= 10 and m[0]["box"][3] >= 50, str(m))


# ------------------------------------------------------------------ cookie fakes

_SEMA = ("CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, originAttributes TEXT NOT NULL DEFAULT '', "
         "name TEXT, value TEXT, host TEXT, path TEXT, expiry INTEGER, lastAccessed INTEGER, "
         "creationTime INTEGER, isSecure INTEGER, isHttpOnly INTEGER, inBrowserElement INTEGER DEFAULT 0, "
         "sameSite INTEGER DEFAULT 0, schemeMap INTEGER DEFAULT 0, isPartitionedAttributeSet INTEGER DEFAULT 0, "
         "updateTime INTEGER, CONSTRAINT moz_uniqueid UNIQUE (name, host, path, originAttributes))")


def _mozlz4(yol, obj):
    import lz4.block
    ham = json.dumps(obj).encode()
    with open(yol, "wb") as f:
        f.write(b"mozLz40\0" + struct.pack("<I", len(ham)) + lz4.block.compress(ham, store_size=False))


def _db(yol, satirlar):
    con = sqlite3.connect(yol)
    con.execute(_SEMA)
    con.execute("PRAGMA user_version=16")
    for host, ad, deger, bitis in satirlar:
        con.execute("INSERT INTO moz_cookies (originAttributes,name,value,host,path,expiry) VALUES ('',?,?,?,'/',?)",
                    (ad, deger, host, bitis))
    con.commit()
    con.close()


def _pol(reddet):
    return politika.Politika("firefox", {"kapali_iken": "kopya"}, {"reddet": list(reddet)})


def test_suresi_dolmus():
    t = tempfile.mkdtemp(prefix="dh-guv-")
    simdi_ms = int(time.time() * 1000)
    db = os.path.join(t, "cookies.sqlite")
    _db(db, [("app.example.com", "sid", "ESKIKALICI", simdi_ms - 3_600_000),   # expired persistent row
             ("diger.example.com", "x", "1", simdi_ms + 86_400_000 * 30)])
    rec = os.path.join(t, "recovery.jsonlz4")
    _mozlz4(rec, {"cookies": [
        {"host": "app.example.com", "name": "sid", "value": "BAYATOTURUM", "path": "/",
         "expiry": int(time.time()) - 600},                                   # expired in the source (seconds)
        {"host": "kisa.example.com", "name": "k", "value": "v", "path": "/",
         "expiry": int(time.time()) + 120},                                   # valid for 2 more minutes
        {"host": "uzun.example.com", "name": "u", "value": "v", "path": "/"}]})
    firefox._oturum_cerezleri_ekle(rec, db, _pol([]), None)
    con = sqlite3.connect(db)
    sat = {r[0]: r[1] for r in con.execute("SELECT host, expiry FROM moz_cookies")}
    deger = [r[0] for r in con.execute("SELECT value FROM moz_cookies WHERE host='app.example.com'")]
    con.close()
    kontrol("4 kaynakta süresi dolmuş oturum çerezi yeniden geçerli yazılmaz", "BAYATOTURUM" not in deger, str(deger))
    kontrol("4 kısa ömürlü çerezin yeni bitişi kaynak bitişini aşmaz",
            "kisa.example.com" in sat and sat["kisa.example.com"] <= (int(time.time()) + 121) * 1000,
            str(sat.get("kisa.example.com")))
    kontrol("4 bitişsiz oturum çerezi yine eklenir (1 gün)", "uzun.example.com" in sat)


def test_joker_ust_alan():
    pol = _pol(["*bank*"])
    t = tempfile.mkdtemp(prefix="dh-guv-")
    db = os.path.join(t, "cookies.sqlite")
    ileri = int(time.time() * 1000) + 86_400_000
    _db(db, [("bank.example.com", "s", "GIZLIBANKA", ileri),
             (".example.com", "ust", "GIZLIUST", ileri),
             (".magaza.test", "oturum", "MAGAZA", ileri),
             ("www.magaza.test", "w", "1", ileri)])
    kalan, silinen, _iz = firefox._cookies_suz(db, pol, None)
    con = sqlite3.connect(db)
    hostlar = {r[0] for r in con.execute("SELECT host FROM moz_cookies")}
    con.close()
    kontrol("5 `*bank*`: bank.example.com konak çerezi silinir", "bank.example.com" not in hostlar, str(hostlar))
    kontrol("5 `*bank*`: .example.com alan çerezi de taşınmaz (reddedilen alt alana gider)",
            ".example.com" not in hostlar, str(hostlar))
    kontrol("5 izinli sitenin alan çerezi kalır (.magaza.test)", ".magaza.test" in hostlar, str(hostlar))
    kontrol("5 politika: bilinen konak yokken .magaza.test reddedilmez",
            not pol.cerez_reddedildi(".magaza.test", bilinen_konaklar={"www.magaza.test"}))
    # hosts known only from history (places.sqlite) and site storage also count; the profile is not written
    kaynak = os.path.join(t, "profil")
    os.makedirs(os.path.join(kaynak, "storage", "default", "https+++mybank.ornek.test"))
    con = sqlite3.connect(os.path.join(kaynak, "places.sqlite"))
    con.execute("CREATE TABLE moz_origins (id INTEGER PRIMARY KEY, prefix TEXT, host TEXT)")
    con.execute("INSERT INTO moz_origins (prefix, host) VALUES ('https://', 'bank.gecmis.test')")
    con.commit()
    con.close()
    once = sorted(os.listdir(kaynak))
    bilinen = firefox._bilinen_konaklar(kaynak, db, {})
    kontrol("5 geçmiş + site deposu konakları bilinir (profilde yeni dosya yok)",
            {"bank.gecmis.test", "mybank.ornek.test"} <= bilinen and sorted(os.listdir(kaynak)) == once,
            str(sorted(bilinen)))
    kontrol("5 geçmişte görülen reddedilen alt alan: .gecmis.test alan çerezi taşınmaz",
            pol.cerez_reddedildi(".gecmis.test", bilinen) and pol.cerez_reddedildi(".ornek.test", bilinen))


def test_ham_bayt():
    pol = _pol(["*bank*", "yasak.test"])
    t = tempfile.mkdtemp(prefix="dh-guv-")
    db = os.path.join(t, "cookies.sqlite")
    ileri = int(time.time() * 1000) + 86_400_000
    gizli = "YASAKDEGER" + "Q" * 40
    # like a real profile: the source is in WAL mode and is copied with the backup API (kopya.sqlite_yedek)
    kaynak = os.path.join(t, "kaynak.sqlite")
    _db(kaynak, [("yasak.test", "s", gizli, ileri)] + [(f"h{i}.example.com", "a", "B" * 50, ileri) for i in range(30)])
    con = sqlite3.connect(kaynak)
    con.execute("PRAGMA journal_mode=WAL")
    con.close()
    from deskhand.oturum import kopya
    t = os.path.join(t, "kopya")
    os.makedirs(t)
    db = os.path.join(t, "cookies.sqlite")
    kopya.sqlite_yedek(kaynak, db)
    firefox._cookies_suz(db, pol, None)
    firefox._cookies_yeniden_kur(db)
    ham = b""
    for ad in os.listdir(t):
        with open(os.path.join(t, ad), "rb") as f:
            ham += f.read()
    kontrol("6 kopya klasörünün ham baytlarında silinen çerez değeri YOK", b"YASAKDEGER" not in ham)
    con = sqlite3.connect(db)
    n = con.execute("SELECT COUNT(*) FROM moz_cookies").fetchone()[0]
    uv = con.execute("PRAGMA user_version").fetchone()[0]
    con.close()
    kontrol("6 izinli satırlar ve şema sürümü korunur", n == 30 and uv == 16, f"{n} {uv}")


def main():
    for f in (test_sinif_onbellek, test_yaris, test_kwin_cerceve, test_suresi_dolmus, test_joker_ust_alan,
              test_ham_bayt):
        try:
            f()
        except Exception as e:  # noqa: BLE001 - a crashing case is a failure, the others still run
            kontrol(f"{f.__name__} çöktü", False, f"{type(e).__name__}: {e}")
    print(f"\n{gecen}/{toplam} geçti")
    return 0 if gecen == toplam else 1


if __name__ == "__main__":
    sys.exit(main())
