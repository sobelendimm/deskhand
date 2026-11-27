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
  M9 korumali_goruntu retries a mask race (bounded: 3 grabs, short waits); still racing → Dur(tur=maske-yarisi),
     nothing reaches OCR
  R1 eylem.k_renge_tikla: a red forbidden window is masked → no colour area, no click, no coordinates
  A1 akis.k_akis: every frame the flow OCRs is masked (list before and after)
  U1 ucbirim Enter gate: a file/command name read by OCR from the terminal reaches only the human panel; the Dur(10)
     the agent gets carries a generic reason (U2: a reason from the agent's own text is still shown)
  S1 static: the raw-grab NAMES (pencere_goruntusu / _pencere_goruntusu, backend .goruntu) appear nowhere outside
     the reasoned allowlist IZINLI in ANY form (name, attribute, import alias, string constant, getattr/vars/__dict__
     with "goruntu"), and an allowed function holds exactly the listed number of references (a new raw grab inside
     an allowed function fails too)
  S2 no stale allowlist entry; S3 every entry has a reason; S4/S5 scanner self-test incl. the review's bypass forms
     (alias, getattr, vars, __dict__, attrgetter: missed by the 6f96402 scanner); S6 count check self-test
  Known limit: the static guard is a tripwire, not a sandbox (a name built at run time, e.g. "pencere_" + "goruntusu",
  is not seen); review keeps the rest.

Run:  python3 tests/test_guv_sinif_maske.py
"""
import argparse
import ast
import contextlib
import os
import sys
import tempfile

import _yalitim  # noqa: F401  (DESKHAND_* temp dirs; before Deskhand)

from PIL import Image  # noqa: E402

from deskhand import akis, api, eylem, gorsel, guvenlik, ocr, ucbirim  # noqa: E402
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
    def ham(k_, bolge=None, kararli=False, tam=False, son_tarih=None):
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


@contextlib.contextmanager
def _yamali(yamalar):
    eski = [(m, ad, getattr(m, ad)) for m, ad, _y in yamalar]
    for m, ad, y in yamalar:
        setattr(m, ad, y)
    try:
        yield
    finally:
        for m, ad, d in eski:
            setattr(m, ad, d)


def _yamali_cagir(yamalar, f):
    """f() with extra patches applied INSIDE _kos (after _sahte's own raw-grab patch)."""
    with _yamali(yamalar):
        return f()


class SiraliAu(SahteAu):
    """Like SahteAu, but every list READ takes the next state of `sira` (the last one repeats): races that come and
    go between retries."""

    def __init__(self, sira, kare_geo=(20, 10, 60, 50)):
        super().__init__([], kare_geo)
        self.sira = sira

    def pencereler(self, desen=None):
        self.olaylar.append("liste")
        sonuc = self.sira[min(self.n, len(self.sira) - 1)]
        self.n += 1
        if isinstance(sonuc, Exception):
            raise sonuc
        return sonuc


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

    # every retry races again (a single race is retried: M9)
    sonuc, olay, okunan = _kos(SiraliAu([ACIK, []] * 10), nokta)
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

    sonuc, olay, okunan = _kos(SiraliAu([ACIK, []] * 10), lambda: ocr.bul_dongu(EKRAN, "gizli", None, 0))
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

    # review ORTA-2: a mask race must not kill a long flow / wait at once: bounded retry in korumali_goruntu
    kare_sayisi = lambda au: au.olaylar.count("kare")  # noqa: E731
    au = SiraliAu([ACIK, [], ACIK, ACIK])
    sonuc, olay, okunan = _kos(au, nokta)
    kontrol("M9 bir yarıştan sonra yeniden denenir ve maskeli kare okunur (2 kare)",
            not isinstance(sonuc, Exception) and kare_sayisi(au) == 2 and _maskeli(okunan), f"{olay} {sonuc!r}")
    au = SiraliAu([ACIK, [], ACIK, [], ACIK, ACIK])
    sonuc, olay, okunan = _kos(au, nokta)
    kontrol("M9 iki yarıştan sonra da başarı (3 kare)", not isinstance(sonuc, Exception) and kare_sayisi(au) == 3
            and _maskeli(okunan), f"{olay} {sonuc!r}")
    au = SiraliAu([ACIK, []] * 10)
    sonuc, olay, okunan = _kos(au, nokta)
    kontrol("M9 sürekli yarış: Dur(tur=maske-yarisi), OCR'a hiçbir kare gitmez",
            isinstance(sonuc, Dur) and sonuc.tur == "maske-yarisi" and not okunan, f"{sonuc!r} {len(okunan)}")
    kontrol("M9 sürekli yarış: deneme sınırlı ve yeniden denendi (tam 3 kare)", kare_sayisi(au) == 3, str(olay))

    # review round 2 (low): a REAL total time limit, also with kararli=True (each stability wait up to 1.5 s; here
    # scaled: 0.5 s per frame, limit 0.6 s). Old: the limit was only checked before sleeping (≈ 3 × wait).
    import time
    au = SiraliAu([ACIK, []] * 10)

    def yavas(k_, bolge=None, kararli=False, tam=False, son_tarih=None):
        bitis = time.monotonic() + 0.5
        if son_tarih is not None:
            bitis = min(bitis, son_tarih)
        time.sleep(max(0.0, bitis - time.monotonic()))  # the stability wait of the real raw grab
        return au.kare(), (0, 0, 200, 100), (0, 0)
    with _yamali([(gorsel, "MASKE_SURE", 0.6)]):
        t0 = time.monotonic()
        sonuc, olay, okunan = _kos(au, lambda: _yamali_cagir([(gorsel, "pencere_goruntusu", yavas)], nokta))
        gecen_sn = time.monotonic() - t0
    kontrol("M10 sürekli yarış + kararlılık beklemesi: toplam süre son tarihte kalır (≤ sınır + 0,15 sn)",
            isinstance(sonuc, Dur) and sonuc.tur == "maske-yarisi" and gecen_sn <= 0.75 and not okunan,
            f"{gecen_sn:.2f} sn, {kare_sayisi(au)} kare, {sonuc!r}")

    # review DÜŞÜK: behaviour tests for renge-tikla and akis
    tiklanan = []
    a = argparse.Namespace(kimlik=EKRAN, renk="kirmizi", en_az=50, sira=None, bolge=None, onayli=False, baslik=None,
                           dugme="sol", mod=None)

    class AuYok:
        def one_getir(self, k):
            pass
    with _yamali([(eylem, "girdi_al", lambda *a_, **k_: object()), (eylem, "girdi_birak", lambda *a_, **k_: None),
                  (eylem, "_au", AuYok), (eylem, "sistem_istemi_on", lambda *a_, **k_: None),
                  (eylem, "denetle", lambda *a_, **k_: None), (eylem, "nokta_metni", lambda *a_, **k_: []),
                  (eylem, "hassas_nokta", lambda *a_, **k_: None),
                  (eylem, "tikla_ic", lambda *a_, **k_: tiklanan.append(a_[3:5]))]):
        sonuc, olay, okunan = _kos(SahteAu([ACIK, ACIK]), lambda: eylem.k_renge_tikla(a))
    kontrol("R1 renge-tikla: yasak penceredeki kırmızı alan bulunmaz (maskeli), tıklanmaz",
            isinstance(sonuc, Dur) and sonuc.kod == 6 and not tiklanan, f"{sonuc!r} {tiklanan}")
    kontrol("R1 renge-tikla: liste karenin önünde ve arkasında okunur", olay[:3] == ["liste", "kare", "liste"],
            str(olay))

    d = tempfile.mkdtemp(prefix="dh-sinif-maske-")
    yol = os.path.join(d, "deneme.akis")
    with open(yol, "w", encoding="utf-8") as f:
        f.write('ekran "zzz-yok"\n    bekle 1\n')

    class AkisAu:
        def geometri(self, k):
            return (0, 0, 200, 100)
    akis_okunan = []

    def akis_oku_(im, *a_, **k_):
        akis_okunan.append(im.copy())
        return []
    with _yamali([(akis, "sec", AkisAu), (akis, "dur_denetle", lambda: None), (akis, "oku", akis_oku_),
                  (akis, "derin_oku", akis_oku_)]):
        sonuc, olay, _o = _kos(SahteAu([ACIK, ACIK]),
                               lambda: akis.k_akis(argparse.Namespace(dosya=yol, sure=0.3, kimlik=EKRAN)))
    kontrol("A1 akış: okunan her kare maskeli, liste önünde ve arkasında",
            olay[:3] == ["liste", "kare", "liste"] and _maskeli(akis_okunan), f"{olay} {len(akis_okunan)} {sonuc!r}")

    # review DÜŞÜK: terminal Enter gate — OCR-derived names stay in the human panel
    panel = []

    class UcAu:
        ad = "sanal"

        def baslik(self, k):
            return "Konsole"

        def sinif(self, k):
            return "org.kde.konsole"

    def kapi(okunan_satir, ek="", panel_yamasi=None):
        panel.clear()
        panel_yamasi = panel_yamasi or [
            (guvenlik, "_panelden_onay", lambda *a_, **k_: (panel.append(a_), (False, "ret"))[1])]
        with _yamali([(ucbirim, "sec", UcAu), (ucbirim, "ucbirim_hedefi", lambda au_, k_: True),
                      (ucbirim, "satir_oku", lambda k_: okunan_satir),
                      (ucbirim, "tampon_oku", lambda au_, k_: {"metin": "", "kirli": True}),
                      (ucbirim, "_on_plan_notu", lambda au_, k_: ""),
                      (guvenlik, "onay_kapsami", lambda *a_, **k_: "hepsi"),
                      (guvenlik, "onayli_gecerli", lambda o: False), *panel_yamasi]):
            try:
                ucbirim.enter_kapisi("w1", False, ek=ek, goruntu_al=False)
            except Dur as e:
                return e
        return None
    e = kapi(["$ ./kasa_gizli_betik.sh"])
    kontrol("U1 uçbirim kapısı: OCR'dan okunan dosya adı ajana dönen Dur(10) iletisinde YOK",
            isinstance(e, Dur) and e.kod == 10 and "kasa_gizli_betik" not in e.mesaj, repr(e))
    kontrol("U1 uçbirim kapısı: ayrıntı insan panelinde (okunan satır + uyarı)",
            any("kasa_gizli_betik" in str(x) for x in panel), str(panel)[:200])
    e = kapi([], ek="./ajan_betigi.sh")
    kontrol("U2 uçbirim kapısı: ajanın kendi yazdığı metnin uyarısı iletide kalır",
            isinstance(e, Dur) and "ajan_betigi" in e.mesaj, repr(e))

    # review round 2 (low): the REAL _panelden_onay; the approval module refuses with the real-screen lock (17).
    # Its Dur went to the agent with the whole OCR'd line ("onay gerekçesi: Uçbirimde komut çalıştır: '<line>'")
    from deskhand import onay
    istenen = []

    def kilit(eylem_, hedef_, ayrinti_, **k_):
        istenen.append(eylem_)
        raise Dur(17, "gerçek ekran kilitli (sınama)")
    e = kapi(["$ echo s3cr3t-parola-satiri"], panel_yamasi=[(onay, "iste_sonuc", kilit), (guvenlik, "sec", UcAu)])
    kontrol("U3 ekran kilidi Dur(17): ajana dönen iletide okunan satır YOK, genel eylem metni var",
            isinstance(e, Dur) and e.kod == 17 and "s3cr3t" not in e.mesaj and "Enter" in e.mesaj, repr(e))
    kontrol("U3 okunan satır onay isteğine (insan paneli) gider", any("s3cr3t" in x for x in istenen), str(istenen))


# ------------------------------------------------------------------ static guard (the class must not come back)

HAM_ADLAR = {"pencere_goruntusu", "_pencere_goruntusu"}  # raw grab (no forbidden-window list, no mask)
ARKA_AD = "goruntu"  # backend screen grab (au.goruntu): only as attribute / getattr / vars / __dict__ / attrgetter
DINAMIK = {"getattr", "hasattr", "setattr", "delattr", "attrgetter", "methodcaller", "__getattribute__"}
# backend layer: defines/wraps the raw screen grab itself (not a consumer)
ARKA_KATMAN = ("deskhand/arka_uc/", "deskhand/kwin_oturum.py", "deskhand/kde_goruntu.py")

IZINLI = {  # "file:function[.inner]": (references, why the raw frame and anything derived from it never leaves)
    "deskhand/gorsel.py:pencere_goruntusu": (2, "the raw grab itself (stability loop over _pencere_goruntusu)"),
    "deskhand/gorsel.py:_pencere_goruntusu": (1, "the raw grab implementation (backend .goruntu + crop)"),
    "deskhand/api.py:goruntu_al": (2, "THE masked path: grab inside maske_kare.iki_okumali_kare, union blacked out"),
    "deskhand/gui/onizleme.py:maskeli_goruntu": (2, "panel preview for the human: iki_okumali_kare; the list-less "
                                                    "fallback is for backends without a window list"),
    "deskhand/onay_hedef.py:_goruntu": (2, "approval-target fingerprint: compared in-process (fark.py), never sent"),
    "deskhand/guvenlik.py:hedef_goruntusu": (3, "approval image for the HUMAN panel (onay request), never to the "
                                                "agent"),
    "deskhand/ucbirim.py:_ocr_satirlar": (2, "terminal Enter gate: the OCR'd line goes to the human approval panel "
                                             "only; the agent's Dur carries a generic reason (enter_kapisi, U1)"),
    "deskhand/eylem.py:k_metne_tikla": (2, "desktop-mode re-check before the click: dogrula → bool only (accepted "
                                           "1-bit limit; the click itself is refused on a forbidden window)"),
}


def _dizge(d):
    return d.value if isinstance(d, ast.Constant) and isinstance(d.value, str) else None


def _dinamik_mi(cagri):
    f = cagri.func
    return (isinstance(f, ast.Name) and f.id in DINAMIK) or (isinstance(f, ast.Attribute) and f.attr in DINAMIK)


def _sozluk_mu(d):
    """vars(x) / globals() / locals() / x.__dict__ → a namespace read by key."""
    if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id in ("vars", "globals", "locals"):
        return True
    return isinstance(d, ast.Attribute) and d.attr == "__dict__"


def _taramalar(yol, kaynak):
    """→ [(qualname, name, line)] for every reference to a raw grab in ANY form: Name, Attribute, import (alias),
    a string constant equal to a raw name, and "goruntu" through getattr/attrgetter/vars()/__dict__."""
    agac = ast.parse(kaynak, yol)
    bulunan = []

    def gez(dugum, yigin):
        for cocuk in ast.iter_child_nodes(dugum):
            if isinstance(cocuk, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                gez(cocuk, yigin + [cocuk.name])
                continue
            adlar = []
            if isinstance(cocuk, ast.Name) and cocuk.id in HAM_ADLAR:
                adlar.append(cocuk.id)
            elif isinstance(cocuk, ast.Attribute) and (cocuk.attr in HAM_ADLAR or cocuk.attr == ARKA_AD):
                adlar.append(cocuk.attr)
            elif isinstance(cocuk, ast.alias):
                adlar += [x for x in (cocuk.name.rsplit(".", 1)[-1], cocuk.asname) if x in HAM_ADLAR]
            elif _dizge(cocuk) in HAM_ADLAR:
                adlar.append(_dizge(cocuk))
            elif isinstance(cocuk, ast.Call) and _dinamik_mi(cocuk):
                adlar += [ARKA_AD for x in cocuk.args if _dizge(x) == ARKA_AD]
            elif isinstance(cocuk, ast.Subscript) and _sozluk_mu(cocuk.value) and _dizge(cocuk.slice) == ARKA_AD:
                adlar.append(ARKA_AD)
            for ad in adlar:
                bulunan.append((".".join(yigin) or "<modül>", ad, getattr(cocuk, "lineno", 0)))
            gez(cocuk, yigin)
    gez(agac, [])
    return bulunan


def _onekler(qual):
    p = qual.split(".")
    return [".".join(p[:i]) for i in range(len(p), 0, -1)]


def _denetle(dosyalar, izinli):
    """dosyalar: {relative path: source} → (unlisted references, stale keys, count mismatches)."""
    izinsiz, sayac = [], {}
    for yol, kaynak in dosyalar.items():
        for qual, ad, satir in _taramalar(yol, kaynak):
            # qualname prefix match: an inner helper (kaydir_al) counts as its function unless listed itself
            anahtar = next((f"{yol}:{q}" for q in _onekler(qual) if f"{yol}:{q}" in izinli), None)
            if anahtar:
                sayac[anahtar] = sayac.get(anahtar, 0) + 1
            else:
                izinsiz.append(f"{yol}:{satir} {qual} → {ad}")
    eskimis = sorted(set(izinli) - set(sayac))
    fazla = sorted(f"{k}: {sayac[k]} başvuru, listede {izinli[k][0]}" for k in sayac if sayac[k] != izinli[k][0])
    return izinsiz, eskimis, fazla


def _kaynaklar(kok):
    sonuc = {}
    for dizin, _alt, dosyalar in os.walk(os.path.join(kok, "deskhand")):
        for d in sorted(dosyalar):
            if not d.endswith(".py"):
                continue
            yol = os.path.relpath(os.path.join(dizin, d), kok).replace(os.sep, "/")
            if yol.startswith(ARKA_KATMAN):
                continue
            with open(os.path.join(kok, yol), encoding="utf-8") as f:
                sonuc[yol] = f.read()
    return sonuc


# the independent review's bypass forms (all missed by the 6f96402 scanner) + the plain ones
ATLATMALAR = {
    "duz_cagri": "from .gorsel import pencere_goruntusu\ndef f(k):\n    return pencere_goruntusu(k)\n",
    "takma_ad": "def f(k):\n    from .gorsel import pencere_goruntusu as pg\n    return pg(k)\n",
    "getattr": "def f(k):\n    from . import gorsel\n    return getattr(gorsel, 'pencere_goruntusu')(k)\n",
    "getattr_arka": "def f(au):\n    return getattr(au, 'goruntu')()\n",
    "vars": "def f(k):\n    from . import gorsel\n    return vars(gorsel)['pencere_goruntusu'](k)\n",
    "vars_arka": "def f(au):\n    return vars(au)['goruntu']()\n",
    "dict_arka": "def f(au):\n    return au.__dict__['goruntu']()\n",
    "attrgetter": "import operator\ndef f(au):\n    return operator.attrgetter('goruntu')(au)()\n",
    "modul_takma": "def f(k):\n    import deskhand.gorsel as g\n    return g._pencere_goruntusu(k)\n",
    "deger": "def f(au):\n    return iki(au.goruntu)\n",
}


def test_statik():
    izinsiz, eskimis, fazla = _denetle(_kaynaklar(KOK), IZINLI)
    kontrol("S1 ham kare adı (pencere_goruntusu / _pencere_goruntusu / .goruntu, her biçimde) izin listesi dışında "
            "geçmiyor (ajana giden yol gorsel.korumali_goruntu / api.goruntu_al)", not izinsiz, "; ".join(izinsiz))
    kontrol("S1 izinli işlevlerde başvuru sayısı listedeki kadar (izinli işleve eklenen yeni ham kare de kırmızı)",
            not fazla, "; ".join(fazla))
    kontrol("S2 izin listesinde eskimiş satır yok (artık ham kare almayan işlev listeden çıkarılır)", not eskimis,
            ", ".join(eskimis))
    kontrol("S3 her izinli satırın gerekçesi var", all(len(v[1].strip()) >= 20 for v in IZINLI.values()))
    for ad, kod in ATLATMALAR.items():
        bulunan = _taramalar("deskhand/yeni.py", kod)
        kontrol(f"S5 atlatma biçimi yakalanır: {ad}", any(q == "f" for q, _a, _s in bulunan), str(bulunan))
    izinsiz, eskimis, fazla = _denetle({"deskhand/yeni.py": "def izinli(au):\n    a = au.goruntu()\n"
                                                            "    return a, au.goruntu()\n"},
                                       {"deskhand/yeni.py:izinli": (1, "öz sınama: bir başvuru izinli")})
    kontrol("S6 izinli işleve eklenen ikinci ham kare sayı denetimine takılır (öz sınama)",
            not izinsiz and not eskimis and fazla, str(fazla))


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
