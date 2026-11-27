"""Bug class SINIF-MASKE (Z3 O2 follow-up, kart DHG): a window frame taken WITHOUT reading the forbidden-window list
before and after it, whose pixels or derived text (OCR) leave the process (agent output, Dur message).

Z3D closed the class in api.goruntu_al (maske_kare.iki_okumali_kare). Other callers of the raw grab
gorsel.pencere_goruntusu OCR'd an unmasked frame and printed the text to the agent ("noktadaki yazı: …",
"bulundu: '…'", match lists, Dur messages): a password manager under the click point (desktop mode) or over the
target window was read. The fix routes them through gorsel.korumali_goruntu (= api.goruntu_al: target forbidden → 10,
other forbidden windows blacked out, list before AND after the frame, race / unreadable list → no frame, no text).

Headless: fake backend (tests/test_guv_z3d.SahteAu), OCR replaced by a recorder; no real screen, no tesseract.
Covers:
  M1 ocr.nokta_metni (click-point text, printed by tikla/renge-tikla/surukle, MCP click): list-frame-list, masked
  M2 nokta_metni: forbidden window closes while the frame is taken → Dur, nothing reaches OCR
  M3 nokta_metni: list unreadable → Dur, no frame, nothing reaches OCR
  M4 ocr.tara default (metne-tikla text search; matches are printed): masked, list-frame-list
  M5 ocr.bul_dongu default: race → Dur, nothing reaches OCR
  M6 eylem.kaydirarak_ara (metne-tikla --scroll): the scrolled frame given to OCR is masked
  S1 static: no code references the raw grab (pencere_goruntusu / _pencere_goruntusu / backend .goruntu) outside
     the reasoned allowlist IZINLI (internal checks whose pixels never leave the process)
  S2 the allowlist has no stale entry; S3 every entry has a reason; S4 the scanner flags a new caller (self-test)

Run:  python3 tests/test_guv_sinif_maske.py
"""
import argparse
import ast
import contextlib
import os
import sys

import _yalitim  # noqa: F401  (DESKHAND_* temp dirs; before Deskhand)

from PIL import Image  # noqa: E402

from deskhand import akis, api, eylem, gorsel, ocr  # noqa: E402
from deskhand.arka_uc import EKRAN  # noqa: E402
from deskhand.hata import Dur  # noqa: E402
from test_guv_z3d import ACIK, KASA, SahteAu, _kirmizi  # noqa: E402  (same fake desktop and race pattern)

gecen = toplam = 0
KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


# ------------------------------------------------------------------ behaviour (fake desktop + OCR recorder)

@contextlib.contextmanager
def _sahte(au, okunan, yasak=None):
    """Real Deskhand code on the fake desktop: the RAW grab (wherever a module imported it by name) returns the fake
    frame; OCR (ocr.oku and the name imported into eylem) only records the image it was given."""
    def ham(k_, bolge=None, kararli=False, tam=False):
        return au.kare(), (0, 0, 200, 100), (0, 0)

    def oku(im, *a, **kw):
        okunan.append(im.copy())
        return []
    yamalar = [(m, "pencere_goruntusu", ham) for m in (gorsel, ocr, eylem, akis) if hasattr(m, "pencere_goruntusu")]
    yamalar = yamalar + [(api, "arka", lambda: au), (api, "yasak_mi", yasak or (lambda w: "test" if w == KASA else None)),
                (ocr, "oku", oku), (eylem, "oku", oku), (eylem, "kaydir_ic", lambda *a, **kw: None)]
    eski = [(m, ad, getattr(m, ad)) for m, ad, _y in yamalar]
    for m, ad, y in yamalar:
        setattr(m, ad, y)
    try:
        yield
    finally:
        for m, ad, d in eski:
            setattr(m, ad, d)


def _kos(au, f, yasak=None):
    okunan = []
    with _sahte(au, okunan, yasak):
        try:
            sonuc = f()
        except Exception as e:  # noqa: BLE001 - Dur expected in race cases; anything else fails the checks
            sonuc = e
    return sonuc, au.olaylar, okunan


def _maskeli(okunan) -> bool:
    return bool(okunan) and not any(_kirmizi(im, 20, 80) for im in okunan if im.size == (200, 100))


def test_davranis():
    nokta = lambda: ocr.nokta_metni(EKRAN, 50, 30)  # noqa: E731 - the point lies on the forbidden window
    sonuc, olay, okunan = _kos(SahteAu([ACIK, ACIK]), nokta)
    kontrol("M1 nokta_metni: liste karenin önünde ve arkasında okunur", olay == ["liste", "kare", "liste"],
            f"{olay} {sonuc!r}")
    kontrol("M1 nokta_metni: OCR'a giden karede yasak pencere karartılmış", _maskeli(okunan),
            f"{len(okunan)} görüntü, {sonuc!r}")

    sonuc, olay, okunan = _kos(SahteAu([ACIK, []]), nokta)
    kontrol("M2 nokta_metni: kare sırasında kapanan yasak pencere → Dur (yeniden denenebilir)",
            isinstance(sonuc, Dur) and sonuc.tur == "maske-yarisi", repr(sonuc))
    kontrol("M2 nokta_metni: yarışta OCR'a hiçbir kare gitmez", not okunan, f"{len(okunan)} görüntü")

    sonuc, olay, okunan = _kos(SahteAu([RuntimeError("liste yok")]), nokta)
    kontrol("M3 nokta_metni: liste okunamazsa Dur ve kare HİÇ alınmaz",
            isinstance(sonuc, Dur) and sonuc.tur == "maske-okunamadi" and "kare" not in olay, f"{sonuc!r} {olay}")
    kontrol("M3 nokta_metni: liste okunamazsa OCR'a hiçbir şey gitmez", not okunan, f"{len(okunan)} görüntü")

    sonuc, olay, okunan = _kos(SahteAu([ACIK, ACIK]), lambda: ocr.tara(EKRAN, "gizli", None))
    kontrol("M4 ocr.tara (metne-tikla): liste önünde ve arkasında, OCR'a giden kare maskeli",
            olay == ["liste", "kare", "liste"] and _maskeli(okunan), f"{olay} {len(okunan)} {sonuc!r}")

    sonuc, olay, okunan = _kos(SahteAu([ACIK, []]), lambda: ocr.bul_dongu(EKRAN, "gizli", None, 0))
    kontrol("M5 ocr.bul_dongu: yarışta Dur, OCR'a hiçbir kare gitmez",
            isinstance(sonuc, Dur) and not okunan, f"{sonuc!r} {len(okunan)}")

    a = argparse.Namespace(kimlik=EKRAN, metin="gizli", kaydirarak=1, baslik=None)
    beyaz = Image.new("RGB", (200, 100), (255, 255, 255))
    sonuc, olay, okunan = _kos(SahteAu([ACIK, ACIK]),
                               lambda: eylem.kaydirarak_ara(None, a, None, (0, 0, 200, 100), beyaz))
    kontrol("M6 kaydirarak_ara: kaydırılan kare maskeli okunur (liste önünde/arkasında)",
            olay[:3] == ["liste", "kare", "liste"] and _maskeli(okunan), f"{olay} {len(okunan)} {sonuc!r}")

    # Z3D review (low): a window NOT forbidden before the frame (title "Loading…"), forbidden after it and moved
    # meanwhile: the frame shows it at the OLD place, which must be masked too (the list before the frame knows it)
    gec = "gec"
    au = SahteAu([[(gec, "Yükleniyor", (20, 10, 60, 50))], [(gec, "Kasa", (120, 10, 60, 50))]])
    sonuc, olay, okunan = _kos(au, lambda: api.goruntu_al(EKRAN),
                               yasak=lambda w: "test" if w == gec and "kare" in au.olaylar else None)
    kontrol("M7 kareden sonra yasaklanan + taşınan pencere: kare anındaki ESKİ konumu da karartılır (ya da kare "
            "gönderilmez)", isinstance(sonuc, Dur) or not _kirmizi(sonuc[0], 20, 80),
            repr(sonuc if isinstance(sonuc, Dur) else sonuc[3]))
    kontrol("M7 yeni konum da maskede", isinstance(sonuc, Dur) or any(m["box"][0] >= 120 for m in sonuc[3]),
            repr(sonuc))
    # Z3D review (nit): a forbidden window that is still open but no longer forbidden after the frame (title
    # changed): the frame is still dropped (safe side), and the message must not claim it was closed
    au = SahteAu([[(gec, "Kasa", (20, 10, 60, 50))], [(gec, "Belge", (20, 10, 60, 50))]])
    sonuc, olay, okunan = _kos(au, lambda: api.goruntu_al(EKRAN),
                               yasak=lambda w: "test" if w == gec and "kare" not in au.olaylar else None)
    kontrol("M8 kare sırasında yasaktan çıkan (açık kalan) pencere: kare gönderilmez, ileti 'değişti' der",
            isinstance(sonuc, Dur) and sonuc.tur == "maske-yarisi" and "değişti" in sonuc.mesaj, repr(sonuc))


# ------------------------------------------------------------------ static guard (the class must not come back)

HAM_ADLAR = {"pencere_goruntusu", "_pencere_goruntusu"}  # raw grab (no forbidden-window list, no mask)
# backend layer: defines/wraps the raw screen grab itself (not a consumer)
ARKA_KATMAN = ("deskhand/arka_uc/", "deskhand/kwin_oturum.py", "deskhand/kde_goruntu.py")

IZINLI = {  # "file:function[.inner]": why the raw frame (and anything derived from it) never leaves the process
    "deskhand/gorsel.py:pencere_goruntusu": "the raw grab itself (stability loop over _pencere_goruntusu)",
    "deskhand/gorsel.py:_pencere_goruntusu": "the raw grab implementation (backend .goruntu + crop)",
    "deskhand/api.py:goruntu_al": "THE masked path: grab inside maske_kare.iki_okumali_kare, union blacked out",
    "deskhand/gui/onizleme.py:maskeli_goruntu": "panel preview for the human: iki_okumali_kare; the list-less "
                                                "fallback is for backends without a window list",
    "deskhand/onay_hedef.py:_goruntu": "approval-target fingerprint: compared in-process (fark.py), never sent",
    "deskhand/guvenlik.py:hedef_goruntusu": "approval image for the HUMAN panel (onay request), never to the agent",
    "deskhand/ucbirim.py:_ocr_satirlar": "terminal Enter gate: the line goes to the human approval panel only; the "
                                         "agent sees the generic risk reason (guvenlik.riskli_komut)",
    "deskhand/eylem.py:k_metne_tikla": "desktop-mode re-check before the click: dogrula → bool only, the Dur "
                                       "message carries the agent's own search text",
}


def _taramalar(yol, kaynak):
    """→ [(qualname, name, line)] for every reference to a raw grab (Name/Attribute, call or value)."""
    agac = ast.parse(kaynak, yol)
    bulunan = []

    def gez(dugum, yigin):
        for cocuk in ast.iter_child_nodes(dugum):
            if isinstance(cocuk, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                gez(cocuk, yigin + [cocuk.name])
                continue
            ad = None
            if isinstance(cocuk, ast.Name) and cocuk.id in HAM_ADLAR:
                ad = cocuk.id
            elif isinstance(cocuk, ast.Attribute) and (cocuk.attr in HAM_ADLAR or cocuk.attr == "goruntu"):
                ad = cocuk.attr
            if ad:
                bulunan.append((".".join(yigin) or "<modül>", ad, getattr(cocuk, "lineno", 0)))
            gez(cocuk, yigin)
    gez(agac, [])
    return bulunan


def _izinsizler(kok):
    izinsiz, kullanilan = [], set()
    for dizin, _alt, dosyalar in os.walk(os.path.join(kok, "deskhand")):
        for d in sorted(dosyalar):
            if not d.endswith(".py"):
                continue
            yol = os.path.relpath(os.path.join(dizin, d), kok).replace(os.sep, "/")
            if yol.startswith(ARKA_KATMAN):
                continue
            with open(os.path.join(kok, yol), encoding="utf-8") as f:
                for qual, ad, satir in _taramalar(yol, f.read()):
                    # qualname prefix match: an inner helper (kaydir_al) counts as its function unless listed itself
                    anahtar = next((f"{yol}:{q}" for q in _onekler(qual) if f"{yol}:{q}" in IZINLI), None)
                    if anahtar:
                        kullanilan.add(anahtar)
                    else:
                        izinsiz.append(f"{yol}:{satir} {qual} → {ad}")
    return izinsiz, kullanilan


def _onekler(qual):
    p = qual.split(".")
    return [".".join(p[:i]) for i in range(len(p), 0, -1)]


def test_statik():
    izinsiz, kullanilan = _izinsizler(KOK)
    kontrol("S1 ham kare (pencere_goruntusu / _pencere_goruntusu / .goruntu) izin listesi dışında kullanılmıyor "
            "(ajana giden yol gorsel.korumali_goruntu / api.goruntu_al)", not izinsiz, "; ".join(izinsiz))
    eskimis = sorted(set(IZINLI) - kullanilan)
    kontrol("S2 izin listesinde eskimiş satır yok (artık ham kare almayan işlev listeden çıkarılır)", not eskimis,
            ", ".join(eskimis))
    kontrol("S3 her izinli satırın gerekçesi var", all(len(v.strip()) >= 20 for v in IZINLI.values()))
    yeni = "from .gorsel import pencere_goruntusu\n\ndef yeni_okuma(k):\n    return pencere_goruntusu(k)\n\n" \
           "def yeni_deger(au):\n    return iki(au.goruntu)\n"
    bulunan = _taramalar("deskhand/yeni.py", yeni)
    kontrol("S4 tarayıcı yeni çağıranı ve değer olarak geçirilen ham kareyi yakalar (öz sınama)",
            [(q, a) for q, a, _s in bulunan] == [("yeni_okuma", "pencere_goruntusu"), ("yeni_deger", "goruntu")],
            str(bulunan))


def main():
    print("deskhand:", os.path.dirname(api.__file__))
    for f in (test_davranis, test_statik):
        try:
            f()
        except Exception as e:  # noqa: BLE001 - a crashing case is a failure, the others still run
            kontrol(f"{f.__name__} çöktü", False, f"{type(e).__name__}: {e}")
    print(f"\n{gecen}/{toplam} geçti")
    return 0 if gecen == toplam else 1


if __name__ == "__main__":
    sys.exit(main())
