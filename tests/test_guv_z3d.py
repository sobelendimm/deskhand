"""Z3 security review follow-up (surum-091): O1 domain-cookie rule and O2 agent screenshot masking race.

Headless: fake backends, temp profile folders (test data uses *.test / example.com only); no real browser profile,
no real cookie, no network, no real screen.
Covers:
  O2-1 api.goruntu_al reads the forbidden-window list BEFORE and AFTER the frame (order: list, frame, list)
  O2-2 a forbidden window that closes while the frame is taken: the frame is NOT returned (Dur, retryable code)
  O2-3 a forbidden window that moves while the frame is taken: both positions are masked
  O2-4 the list cannot be read (before / after the frame): Dur, no frame (before: nothing is grabbed)
  O2-5 the target window itself becomes forbidden while the frame is taken: Dur(10)
  O2-6 a window that appears only after the frame is masked (already covered before the fix, kept)
  O1-1 a fixed-tail reject rule (`*.bank.com`, `*.secure.example.com`) rejects a domain cookie it could reach through
       ANY subdomain, without known hosts
  O1-2 no false positive: `*.gov.tr` does not reject `.example.com`; trailing-`*` rules keep the known-host evidence
  O1-3 the decision equals a brute-force search over a small alphabet
  O1-4 places.sqlite in WAL mode: hosts still in the WAL are known; the profile folder is not changed

Run:  python3 tests/test_guv_z3d.py
"""
import itertools
import os
import random
import sqlite3
import sys
import tempfile

import _yalitim  # noqa: F401  (DESKHAND_* temp dirs; before Deskhand)

from PIL import Image  # noqa: E402

from deskhand import api, gorsel  # noqa: E402
from deskhand.arka_uc import EKRAN  # noqa: E402
from deskhand.hata import Dur  # noqa: E402
from deskhand.oturum import firefox, politika  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


# ------------------------------------------------------------------ O2: agent screenshot path

KASA = "kasa"          # the forbidden window (e.g. a password manager)
HEDEF = "hedef"        # a normal target window


class SahteAu:
    """Fake desktop 200x100. `listeler`: list per call number (1 = before the frame, 2 = after); an item that is an
    Exception is raised. The frame shows red wherever the forbidden window was at grab time (`kare_geo`)."""

    def __init__(self, listeler, kare_geo=(20, 10, 60, 50)):
        self.listeler = listeler
        self.kare_geo = kare_geo
        self.olaylar = []
        self.n = 0

    def ekran_alani(self):
        return (0, 0, 200, 100)

    def pencereler(self, desen=None):
        self.n += 1
        self.olaylar.append("liste")
        sonuc = self.listeler[min(self.n, len(self.listeler)) - 1]
        if isinstance(sonuc, Exception):
            raise sonuc
        return sonuc

    def kare(self):
        self.olaylar.append("kare")
        im = Image.new("RGB", (200, 100), (255, 255, 255))
        if self.kare_geo:
            x, y, g, h = self.kare_geo
            im.paste((255, 0, 0), (x, y, x + g, y + h))
        return im


def _kos(au, k=EKRAN, yasak=None):
    """Run the REAL api.goruntu_al with the fake backend → (result | Dur, events)."""
    eski = api.arka, api.yasak_mi, gorsel.pencere_goruntusu
    api.arka = lambda: au
    api.yasak_mi = yasak or (lambda w: "test" if w == KASA else None)
    gorsel.pencere_goruntusu = lambda k_, bolge=None, kararli=False, tam=False: (au.kare(), (0, 0, 200, 100), (0, 0))
    try:
        try:
            return api.goruntu_al(k), au.olaylar
        except Exception as e:  # noqa: BLE001 - Dur expected; anything else is reported by the checks
            return e, au.olaylar
    finally:
        api.arka, api.yasak_mi, gorsel.pencere_goruntusu = eski


def _kirmizi(im, x0, x1) -> bool:
    return any(im.getpixel((x, y))[0] > 200 and im.getpixel((x, y))[1] < 50 for x in range(x0, x1, 4) for y in range(12, 58, 4))


ACIK = [(KASA, "Kasa", (20, 10, 60, 50))]


def test_o2():
    sonuc, olay = _kos(SahteAu([ACIK, ACIK]))
    kontrol("O2-1 liste karenin önünde ve arkasında okunur", olay == ["liste", "kare", "liste"], str(olay))
    kontrol("O2-1 açık kalan yasak pencere karartılır",
            not isinstance(sonuc, Dur) and not _kirmizi(sonuc[0], 20, 80), repr(sonuc))

    sonuc, olay = _kos(SahteAu([ACIK, []]))
    kontrol("O2-2 kare sırasında kapanan yasak pencere: kare GÖNDERİLMEZ (Dur)", isinstance(sonuc, Dur), repr(sonuc))
    kontrol("O2-2 hata yeniden denenebilir (kod 8, tur maske-yarisi)",
            isinstance(sonuc, Dur) and sonuc.kod == 8 and sonuc.tur == "maske-yarisi",
            repr(getattr(sonuc, "kod", sonuc)))
    kontrol("O2-2 hata iletisinde pencere başlığı yok", isinstance(sonuc, Dur) and "Kasa" not in sonuc.mesaj)

    tasindi = [(KASA, "Kasa", (120, 10, 60, 50))]
    sonuc, olay = _kos(SahteAu([ACIK, tasindi]))
    kontrol("O2-3 kare sırasında taşınan yasak pencere: eski konum karartılır",
            not isinstance(sonuc, Dur) and not _kirmizi(sonuc[0], 20, 80), repr(sonuc))
    kontrol("O2-3 yeni konum da maskede",
            not isinstance(sonuc, Dur) and any(m["box"][0] >= 120 for m in sonuc[3]), repr(sonuc))

    sonuc, olay = _kos(SahteAu([RuntimeError("liste yok")]))
    kontrol("O2-4 liste kareden ÖNCE okunamazsa Dur ve kare HİÇ alınmaz",
            isinstance(sonuc, Dur) and "kare" not in olay and sonuc.tur == "maske-okunamadi", f"{sonuc!r} {olay}")
    sonuc, olay = _kos(SahteAu([ACIK, RuntimeError("liste yok")]))
    kontrol("O2-4 liste kareden SONRA okunamazsa Dur (kare dönmez)",
            isinstance(sonuc, Dur) and sonuc.tur == "maske-okunamadi", repr(sonuc))

    durum = {"n": 0}

    def yasak(w):
        if w == HEDEF:
            durum["n"] += 1
            return "test" if durum["n"] > 1 else None
        return None
    sonuc, olay = _kos(SahteAu([[], []], kare_geo=None), k=HEDEF, yasak=yasak)
    kontrol("O2-5 hedef kare sırasında yasaklanırsa Dur(10)", isinstance(sonuc, Dur) and sonuc.kod == 10,
            repr(sonuc))

    sonuc, olay = _kos(SahteAu([[], ACIK]))
    kontrol("O2-6 kareden sonra beliren yasak pencere karartılır",
            not isinstance(sonuc, Dur) and not _kirmizi(sonuc[0], 20, 80), repr(sonuc))


# ------------------------------------------------------------------ O1: domain-cookie rule

def _pol(reddet):
    return politika.Politika("firefox", {"kapali_iken": "kopya"}, {"reddet": list(reddet)})


def test_o1_kural():
    kontrol("O1-1 `*.bank.com`: .bank.com çerezi bilinen alt alan olmadan reddedilir",
            _pol(["*.bank.com"]).cerez_reddedildi(".bank.com", bilinen_konaklar={"bank.com"}))
    kontrol("O1-1 `*.secure.example.com`: .example.com çerezi reddedilir (alt alana gider)",
            _pol(["*.secure.example.com"]).cerez_reddedildi(".example.com"))
    kontrol("O1-1 `login?.example.com`: .example.com çerezi reddedilir",
            _pol(["login?.example.com"]).cerez_reddedildi(".example.com"))
    kontrol("O1-2 `*.gov.tr`: .example.com reddedilmez", not _pol(["*.gov.tr"]).cerez_reddedildi(".example.com"))
    kontrol("O1-2 `*.bank.com`: .notbank.com reddedilmez", not _pol(["*.bank.com"]).cerez_reddedildi(".notbank.com"))
    kontrol("O1-2 `*.bank.com`: konak çerezi example.com etkilenmez",
            not _pol(["*.bank.com"]).cerez_reddedildi("example.com"))
    kontrol("O1-2 sonu `*` olan kural yalnız bilinen konak kanıtıyla (belgelenmiş sınır)",
            not _pol(["*bank*"]).cerez_reddedildi(".magaza.test", {"www.magaza.test"})
            and _pol(["*bank*"]).cerez_reddedildi(".magaza.test", {"bank.magaza.test"}))
    varsayilan = politika.coz("firefox", politika.yukle())
    kontrol("O1-2 varsayılan liste: .github.com ve .example.com alan çerezi kalır",
            not varsayilan.cerez_reddedildi(".github.com") and not varsayilan.cerez_reddedildi(".example.com"))
    kontrol("O1-2 varsayılan liste: .gov alan çerezi reddedilir (`*.gov`)", varsayilan.cerez_reddedildi(".gov"))


def _kaba(kural: str, alan: str, alfabe: str, uzunluk: int) -> bool:
    import fnmatch
    for n in range(1, uzunluk + 1):
        for x in itertools.product(alfabe, repeat=n):
            if fnmatch.fnmatchcase("".join(x) + "." + alan, kural):
                return True
    return False


def test_o1_kaba_kuvvet():
    rnd = random.Random(91)
    parcalar = ["a", "b", ".", "*", "?", "[ab]", "[!a]"]
    alanlar = ["a", "b", "a.b", "ab", "b.a"]
    hatalar = []
    n = 0
    for _ in range(600):
        kural = "".join(rnd.choice(parcalar) for _ in range(rnd.randint(1, 5)))
        if kural.endswith("*"):
            continue
        for alan in alanlar:
            n += 1
            beklenen = _kaba(kural, alan, "ab.", 6)
            bulunan = politika._alt_alana_uyabilir(kural, alan)
            if beklenen != bulunan:
                hatalar.append((kural, alan, beklenen, bulunan))
    kontrol(f"O1-3 karar = kaba kuvvet ({n} durum)", not hatalar, str(hatalar[:5]))


def test_o1_places_wal():
    t = tempfile.mkdtemp(prefix="dh-z3d-")
    kaynak = os.path.join(t, "profil")
    os.makedirs(kaynak)
    yer = os.path.join(kaynak, "places.sqlite")
    yazar = sqlite3.connect(yer)
    yazar.execute("PRAGMA journal_mode=WAL")
    yazar.execute("PRAGMA wal_autocheckpoint=0")
    yazar.execute("CREATE TABLE moz_origins (id INTEGER PRIMARY KEY, prefix TEXT, host TEXT)")
    yazar.execute("INSERT INTO moz_origins (prefix, host) VALUES ('https://', 'eski.ornek.test')")
    yazar.commit()
    yazar.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    yazar.execute("INSERT INTO moz_origins (prefix, host) VALUES ('https://', 'bank.wal.test')")  # only in the WAL
    yazar.commit()
    try:
        def durum():
            return sorted((ad, os.stat(os.path.join(kaynak, ad)).st_size, os.stat(os.path.join(kaynak, ad)).st_mtime_ns)
                          for ad in os.listdir(kaynak))
        once = durum()
        db = os.path.join(t, "cookies.sqlite")
        sqlite3.connect(db).close()
        bilinen = firefox._bilinen_konaklar(kaynak, db, {})
        kontrol("O1-4 WAL'daki geçmiş konağı bilinir (Firefox açıkken)", "bank.wal.test" in bilinen, str(bilinen))
        kontrol("O1-4 ana dosyadaki konak da bilinir", "eski.ornek.test" in bilinen, str(bilinen))
        kontrol("O1-4 profil klasörü değişmedi (yeni dosya, boyut, zaman yok)", durum() == once,
                f"{once} → {durum()}")
        kontrol("O1-4 WAL'daki reddedilen alt alan: .wal.test alan çerezi taşınmaz",
                _pol(["*bank*"]).cerez_reddedildi(".wal.test", bilinen))
    finally:
        yazar.close()


def main():
    print("deskhand:", os.path.dirname(api.__file__))
    for f in (test_o2, test_o1_kural, test_o1_kaba_kuvvet, test_o1_places_wal):
        try:
            f()
        except Exception as e:  # noqa: BLE001 - a crashing case is a failure, the others still run
            kontrol(f"{f.__name__} çöktü", False, f"{type(e).__name__}: {e}")
    print(f"\n{gecen}/{toplam} geçti")
    return 0 if gecen == toplam else 1


if __name__ == "__main__":
    sys.exit(main())
