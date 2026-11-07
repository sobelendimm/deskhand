"""Girdi güvenliği testleri (ekransız; sahte arka uç, gerçek ekrana/panele/dotool'a HİÇBİR şey gitmez):

1. Ödeme sayfasında Enter/boşluk: çözülmüş tuşa göre (x:Return, k:28, kpenter…) ve Enter/Tab/boşluklu yazı → onay
   (kde ve sanal arka uç aynı üst katmandan geçer).
2. Onay isteği NE onaylandığını taşır: noktadaki yazı, hassas düğme metni, küçük görüntü; bir eylem = bir onay.
3. İmleç altı bilinemezse tıklanmaz (3).
4. Kısaltmasız ayrıştırıcı; akışta önceden onaylı adım ayrıştırılarak sayılır; onaysız akışta --onayli adım reddedilir.
5. DUR anahtarı atomik ve yarışsız (kullanıcının DUR'u ajan tarafından kaldırılamaz/ezilemez).
6. kde: ekran koruması her gönderimde / ham'da aralıkla; pencere kapatma korumalı; karar bildirimi açıkken ön plan
   girdisi yok (--ekranimda aşmaz), sahibi ölmüş karar dosyası yok sayılır.
7. MCP: çekirdek onay beklenirken tek kilit bırakılır; onaydan sonra başlık yeniden doğrulanır."""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

import argparse
import io
import os
import sys
import threading
import time

from PIL import Image

from deskhand import akis, api, arka_uc, eylem, guvenlik, hata, mesgul, onay
from deskhand.arka_uc import EKRAN
from deskhand.hata import Dur

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)


def kod_al(f, *a, **k):
    try:
        f(*a, **k)
        return 0
    except Dur as e:
        return e.kod


# ---------------------------------------------------------------- sahte arka uç + girdi

class SahteGirdi:
    def __init__(self, au, etiket="", gizli=False, etk=None, denetle=None):
        self.au, self.etiket, self.gizli, self.denetle = au, etiket, gizli, denetle
        self.etk, self.kesildi, self.hazir, self.son_fare = None, None, True, au.fare()[:2]
        self.son_etk = time.monotonic()

    def _satir(self, s):
        if s.startswith("mouseto "):
            fx, fy = map(float, s.split()[1:3])
            x0, y0, x1, y1 = self.au.ekran_alani()
            self.au.imlec = (int(x0 + fx * (x1 - x0)), int(y0 + fy * (y1 - y0)))
        self.au.satirlar.append(s)

    def gonder(self, k, desen, *satirlar):
        hata.dur_denetle()
        if self.denetle:
            self.denetle(k, desen)
        for s in satirlar:
            self._satir(s)

    def ham(self, s):
        hata.dur_denetle()
        self._satir(s)

    def zorla(self, s):
        self._satir(s)

    def izle(self, k, desen): pass
    def izle_bitir(self): pass
    def etk_denetle(self, ne=None): pass
    def insan_kontrol(self): pass
    def kapat(self): pass


class SahteAU(arka_uc.ArkaUc):
    ad = "kde"

    def __init__(self, ad="kde", baslik="Checkout - Ödeme - Shop"):
        self.ad = ad
        self.pen = {"{w}": [baslik, "firefox", (100, 100, 800, 600)]}
        self.imlec, self.satirlar, self.alt_bilinmez = (5, 5), [], False

    def pencere_coz(self, arg): return arg
    def pencereler(self, desen=None): return []
    def geometri(self, k): return self.pen[k][2] if k != EKRAN else (0, 0, 1920, 1080)
    def baslik(self, k): return self.pen.get(k, [""])[0]
    def sinif(self, k): return self.pen.get(k, ["", ""])[1]
    def aktif(self): return "{w}"
    def one_getir(self, k): pass
    def kapat(self, k): pass
    def ekran_alani(self): return (0, 0, 1920, 1080)
    def goruntu(self): return Image.new("RGB", (1920, 1080), (200, 200, 200))
    def insan_var_mi(self): return False
    def baslat(self, argv, env=None, cikti=None): raise AssertionError("başlatılmamalı")
    def gecerli_tuslar(self): return {"enter", "kpenter", "space", "linefeed", "tab", "a", "s", "w", "esc"}

    def fare(self):
        x, y = self.imlec
        if self.alt_bilinmez:
            return x, y, ""
        X, Y, W, H = self.pen["{w}"][2]
        return x, y, ("{w}" if X <= x < X + W and Y <= y < Y + H else "{masaustu}")

    def girdi(self, etiket="", gizli=False, etk=None, denetle=None):
        return SahteGirdi(self, etiket, gizli, etk, denetle)


def ns(**k):
    a = argparse.Namespace(baslik=None, onayli=False, gizli=False, kimlik="{w}")
    for x, v in k.items():
        setattr(a, x, v)
    return a


ISTEKLER = []
YANIT = {"izin": False}
gercek_iste_sonuc = onay.iste_sonuc


def sahte_iste_sonuc(eylem_, hedef, ayrinti="", masaustu="ekran", sure=120, goruntu=None, gunluge_yaz=True):
    ISTEKLER.append({"eylem": eylem_, "hedef": hedef, "ayrinti": ayrinti, "goruntu": goruntu})
    return onay.OnaySonucu(YANIT["izin"], "izin" if YANIT["izin"] else "red")


onay.iste_sonuc = sahte_iste_sonuc
gercek_nokta_metni = eylem.nokta_metni
eylem.nokta_metni = lambda k, x, y: ["Siparişi onayla"]  # OCR yok: noktadaki yazı sabit

# ================================================================ 1. Enter/boşluk eşdeğerleri (K1)
for ad_ in ("kde", "sanal"):
    au = SahteAU(ad_)
    arka_uc._ORNEKLER[ad_] = au
    with arka_uc.hedef_sabit(ad_):
        for tus in ("enter", "Return", "x:Return", "x:KP_Enter", "x:ISO_Enter", "x:space", "x:KP_Space", "x:0xff0d",
                    "x:U000D", "x:U0020", "k:28", "k:96", "k:57", "k:101", "kpenter", "linefeed", "ctrl+enter",
                    "x:Bogus_Yok", "k:abc", "esc space"):
            ISTEKLER.clear()
            n0 = len(au.satirlar)
            kod = kod_al(eylem.k_tus, ns(kombinasyon=tus))
            kontrol(f"[{ad_}] ödeme sayfası: tus {tus!r} → onay istendi, red → 10, girdi yok",
                    kod == 10 and len(ISTEKLER) == 1 and len(au.satirlar) == n0, f"{kod} {len(ISTEKLER)}")
        for tus in ("tab", "x:a", "k:30", "ctrl+s", "x:Escape"):
            ISTEKLER.clear()
            n0 = len(au.satirlar)
            kod = kod_al(eylem.k_tus, ns(kombinasyon=tus))
            kontrol(f"[{ad_}] ödeme sayfası: tus {tus!r} (Enter/boşluk değil) → sorulmaz, gönderilir",
                    kod == 0 and not ISTEKLER and len(au.satirlar) == n0 + 1, f"{kod} {au.satirlar[n0:]}")
        kontrol(f"[{ad_}] bas x:Return → 10", kod_al(eylem.k_bas, ns(tuslar="x:Return", sure=0.1)) == 10)
        n0 = len(au.satirlar)
        kontrol(f"[{ad_}] tus x:U+000D ('+' akor ayırıcı) → 1, girdi yok",
                kod_al(eylem.k_tus, ns(kombinasyon="x:U+000D")) == 1 and len(au.satirlar) == n0)
        for metin in ("4111\n", "a\tb", "\t ", "ad soyad", "x\r", " "):
            ISTEKLER.clear()
            n0 = len(au.satirlar)
            kod = kod_al(eylem.k_yaz, ns(metin=metin))
            kontrol(f"[{ad_}] ödeme sayfası: yaz {metin!r} → yazmadan ÖNCE onay, red → 10, HİÇ girdi yok",
                    kod == 10 and len(ISTEKLER) == 1 and len(au.satirlar) == n0, f"{kod} {au.satirlar[n0:]}")
        ISTEKLER.clear()
        n0 = len(au.satirlar)
        kontrol(f"[{ad_}] ödeme sayfası: boşluksuz yazı (kart no) serbest",
                kod_al(eylem.k_yaz, ns(metin="4111111111111111")) == 0 and not ISTEKLER and len(au.satirlar) > n0)
        kontrol(f"[{ad_}] yaz --onayli (sohbette onay) → sorulmaz",
                kod_al(eylem.k_yaz, ns(metin="a b\n", onayli=True)) == 0 and not ISTEKLER)
        au.pen["{w}"][0] = "Belge — KWrite"
        n0 = len(au.satirlar)
        kontrol(f"[{ad_}] sıradan sayfa: 'a b\\n' sorulmadan yazılır",
                kod_al(eylem.k_yaz, ns(metin="a b\n")) == 0 and not ISTEKLER and "key enter" in au.satirlar[n0:])
        kontrol(f"[{ad_}] sıradan sayfa: tus x:Return sorulmaz", kod_al(eylem.k_tus, ns(kombinasyon="x:Return")) == 0
                and not ISTEKLER)

# izinle: bir eylem = bir onay, istek yazıyı ve görüntüyü taşır
au = SahteAU("kde")
arka_uc._ORNEKLER["kde"] = au
with arka_uc.hedef_sabit("kde"):
    YANIT["izin"] = True
    ISTEKLER.clear()
    n0 = len(au.satirlar)
    kod = kod_al(eylem.k_yaz, ns(metin="Ali Veli\n34 Cadde\n"))
    kontrol("izin: Enter'lı çok satırlı yazı TEK onayla yazıldı", kod == 0 and len(ISTEKLER) == 1 and
            au.satirlar[n0:].count("key enter") == 2, f"{kod} {len(ISTEKLER)}")
    kontrol("izin: istek yazılacak metni ve küçük görüntüyü taşır", ISTEKLER and "Ali Veli" in ISTEKLER[0]["ayrinti"]
            and isinstance(ISTEKLER[0]["goruntu"], Image.Image), str(ISTEKLER[:1])[:300])
    ISTEKLER.clear()
    kod_al(eylem.k_yaz, ns(metin="gizli parola\n", gizli=True))
    kontrol("izin: --gizli yazının içeriği onay isteğinde görünmez", ISTEKLER and "parola" not in ISTEKLER[0]["ayrinti"]
            and "***(13)" in ISTEKLER[0]["ayrinti"], str(ISTEKLER[:1])[:200])
    YANIT["izin"] = False

    # ============================================================ 2. tıklama onayı NE onaylandığını gösterir (O3)
    ISTEKLER.clear()
    n0 = len(au.satirlar)
    kod = kod_al(eylem.k_tikla, ns(x=300, y=200, dugme="sol", foto=False, basili=0.0, tekrar=1))
    kontrol("tıklama: ödeme sayfası + 'Siparişi onayla' → TEK onay isteği, red → 10, girdi yok",
            kod == 10 and len(ISTEKLER) == 1 and len(au.satirlar) == n0, f"{kod} {len(ISTEKLER)}")
    a0 = ISTEKLER[0]["ayrinti"] if ISTEKLER else ""
    kontrol("tıklama: ayrıntıda 'x,y noktasındaki yazı' ve hassas düğme metni",
            "300,200 noktasındaki yazı: Siparişi onayla" in a0 and "Hassas düğme: “Siparişi onayla”" in a0, a0)
    g0 = ISTEKLER[0]["goruntu"] if ISTEKLER else None
    kontrol("tıklama: hedef çevresinin küçük görüntüsü (≤ 480x200)", isinstance(g0, Image.Image) and
            g0.size[0] <= 480 and g0.size[1] <= 200, str(getattr(g0, "size", None)))
    YANIT["izin"] = True
    ISTEKLER.clear()
    n0 = len(au.satirlar)
    kod = kod_al(eylem.k_tikla, ns(x=300, y=200, dugme="sol", foto=False, basili=0.0, tekrar=1))
    kontrol("tıklama: izin → tek onayla (sayfa + düğme) tıklandı", kod == 0 and len(ISTEKLER) == 1 and
            "click left" in au.satirlar[n0:], f"{kod} {len(ISTEKLER)} {au.satirlar[n0:]}")
    YANIT["izin"] = False

    # sayfa hassas değil ama düğme hassas: düğme onayı da görüntü + nokta taşır
    au.pen["{w}"][0] = "Mağaza — Ürün"
    ISTEKLER.clear()
    kod = kod_al(eylem.k_tikla, ns(x=300, y=200, dugme="sol", foto=False, basili=0.0, tekrar=1))
    kontrol("hassas düğme (sıradan sayfa): onay isteği noktadaki yazı + görüntü", kod == 10 and len(ISTEKLER) == 1 and
            "noktasındaki yazı" in ISTEKLER[0]["ayrinti"] and isinstance(ISTEKLER[0]["goruntu"], Image.Image))
    au.pen["{w}"][0] = "Checkout - Ödeme - Shop"

    # ============================================================ 3. imleç altı bilinemezse tıklanmaz (O8)
    eylem.nokta_metni = lambda k, x, y: ["Kaydet"]
    au.pen["{w}"][0] = "Belge — KWrite"
    au.alt_bilinmez = True
    n0 = len(au.satirlar)
    kod = kod_al(eylem.k_tikla, ns(x=300, y=200, dugme="sol", foto=False, basili=0.0, tekrar=1))
    kontrol("imleç altı bilinemedi → 3, tıklanmadı", kod == 3 and "click left" not in au.satirlar[n0:], str(kod))
    au.alt_bilinmez = False
    kontrol("imleç altı hedef → tıklanır",
            kod_al(eylem.k_tikla, ns(x=300, y=200, dugme="sol", foto=False, basili=0.0, tekrar=1)) == 0)
    au.pen["{w}"][0] = "Checkout - Ödeme - Shop"

# ================================================================ 4. kısaltmasız ayrıştırıcı + akış ön onayı (O2)
from deskhand import cli  # noqa: E402

p = cli.ayristirici("deskhand", sessiz=True)
for sec_ in ("--onay", "--appr", "--ona", "--onayl"):
    try:
        p.parse_args(["tikla", "w", "1", "2", sec_])
        kontrol(f"ayrıştırıcı: kısaltma {sec_} reddedilir", False, "kabul edildi")
    except cli.AyristirmaHatasi:
        kontrol(f"ayrıştırıcı: kısaltma {sec_} reddedilir", True)
kontrol("ayrıştırıcı: tam ad --approved geçer", p.parse_args(["click", "w", "1", "2", "--approved"]).onayli is True)
kontrol("ayrıştırıcı: normal ayrıştırıcıda da kısaltma yok", cli.ayristirici("x")._subparsers is not None and
        all(not s.allow_abbrev for s in cli.ayristirici("x")._subparsers._group_actions[0].choices.values()))

d = os.path.join(_yalitim.GECICI, "akis-test")
os.makedirs(d, exist_ok=True)
ornek = {
    "kisaltma": ('ekran "X"\n  tikla 1 1 --onay\n', []),
    "tirnak": ('ekran "X"\n  tikla 1 1 --onay\'\'li\n', ["tikla 1 1 --onayli"]),
    "ingilizce": ('ekran "X"\n  click-text "Pay" --approved\n', ["metne-tikla Pay --approved"]),
    "metin-icinde": ('ekran "X"\n  metne-tikla "--onayli değil"\n  yaz "not --approved here"\n', []),
    "altinda": ('ekran "X"\n  renge-tikla yesil --altinda=120 --onayli\n', ["renge-tikla yesil --altinda=120 --onayli"]),
}
for ad_, (icerik, beklenen) in ornek.items():
    yol = os.path.join(d, ad_ + ".akis")
    with open(yol, "w") as f:
        f.write(icerik)
    r = akis.onayli_adimlar(yol)
    kontrol(f"akış ön taraması ({ad_}): ayrıştırılmış --onayli", r == beklenen, f"{r} ≠ {beklenen}")

# onay alınmadan çalışan akışta --onayli adım reddedilir (dosya taramadan sonra değişse bile)
au = SahteAU("kde", baslik="Belge — KWrite")
arka_uc._ORNEKLER["kde"] = au
with arka_uc.hedef_sabit("kde"):
    a = argparse.Namespace(kimlik="{w}", kimlik_ham="{w}", baslik=None, onayli_izin=False)
    n0 = len(au.satirlar)
    kod = kod_al(eylem.adimlari_calistir, a, ["tikla 10 10 --onayli"])
    kontrol("akış: onaysız çalıştırmada --onayli adım → 10, girdi yok", kod == 10 and len(au.satirlar) == n0, str(kod))
    kod = kod_al(eylem.adimlari_calistir, a, ["tikla 10 10 --onay"])
    kontrol("akış: kısaltma adımı → 1 (hatalı satır)", kod == 1, str(kod))
    a.onayli_izin = True
    kontrol("akış: onaylı çalıştırmada --onayli adım çalışır", kod_al(eylem.adimlari_calistir, a, ["tikla 10 10 --onayli"]) == 0)

# ================================================================ 5. DUR anahtarı atomik / yarışsız (D1)
guvenlik.dur_kapat("kullanici")
guvenlik.dur_ac("cli")
kontrol("DUR: ajan açtı → cli", guvenlik.dur_kaynagi() == "cli")
guvenlik.dur_ac("kullanici")
kontrol("DUR: kullanıcı ajanınkinin üstüne yazar", guvenlik.dur_kaynagi() == "kullanici")
guvenlik.dur_ac("cli")
kontrol("DUR: ajan kullanıcınınkini ezemez", guvenlik.dur_kaynagi() == "kullanici")
guvenlik.dur_kapat("kullanici")

# yarış: ajan 'devam' derken (okuma ile taşıma arasında) kullanıcı DUR koyar → kullanıcınınki kalmalı
guvenlik.dur_ac("cli")
gercek_rename = guvenlik.os.rename
tetik = {"n": 0}


def yarisan_rename(kaynak, hedef):
    if tetik["n"] == 0:
        tetik["n"] = 1
        guvenlik.dur_ac("kullanici")  # tam bu anda panel DUR'u
    return gercek_rename(kaynak, hedef)


guvenlik.os.rename = yarisan_rename
try:
    kod = kod_al(guvenlik.dur_kapat, "cli")
finally:
    guvenlik.os.rename = gercek_rename
kontrol("DUR yarışı: ajanın 'devam'ı kullanıcının yeni DUR'unu kaldırmaz (13, DUR açık, sahibi kullanıcı)",
        kod == 13 and guvenlik.dur_kaynagi() == "kullanici", f"{kod} {guvenlik.dur_kaynagi()}")
kontrol("DUR yarışı: geride geçici dosya kalmadı",
        not [f for f in os.listdir(os.path.dirname(hata.dur_dosyasi())) if f.startswith(("dur.", ".dur-"))],
        str(os.listdir(os.path.dirname(hata.dur_dosyasi()))))
guvenlik.dur_kapat("kullanici")

# eşzamanlı okuyucu hiçbir an boş/yarım dosya görmez (eskiden open("w") önce boşaltıyordu → "cli" sanılıyordu)
dur_bayrak = threading.Event()
gorulen = set()


def okuyucu():
    while not dur_bayrak.is_set():
        k_ = guvenlik.dur_kaynagi()
        if k_:
            gorulen.add(k_)


th = threading.Thread(target=okuyucu, daemon=True)
th.start()
for _i in range(300):
    guvenlik.dur_ac("kullanici")
dur_bayrak.set()
th.join(5)
kontrol("DUR: kullanıcı yazarken okuyan hiç 'cli' (boş dosya) görmedi", gorulen == {"kullanici"}, str(gorulen))
guvenlik.dur_kapat("kullanici")
kontrol("DUR: kapalı", guvenlik.dur_kaynagi() is None and guvenlik.dur_kapat("cli") is False)

# ================================================================ 6. kde: ekran koruması + karar bildirimi (O4, D8, EK)
from deskhand.arka_uc import kde  # noqa: E402


class SahteBoru:
    def __init__(self): self.stdin = io.StringIO()
    def poll(self): return None


def sahte_kde_girdi():
    g = kde.Girdi.__new__(kde.Girdi)
    g.au, g.denetle = au, (lambda k, d: None)
    g.etk, g.etk_sahibi, g.p, g.hazir = None, False, SahteBoru(), True
    g.etiket, g.gizli, g.kesildi, g.son_etk = "test", False, None, time.monotonic()
    return g


koruma = {"neden": None}
gercek_koruma = mesgul.ekran_korumasi
mesgul.ekran_korumasi = lambda *a, **k: koruma["neden"]
try:
    g = sahte_kde_girdi()
    g.gonder("{w}", None, "key a")
    koruma["neden"] = "tam ekranda (test)"
    kontrol("kde: dizi ortasında film açıldı → sonraki gonder 15, satır yok",
            kod_al(g.gonder, "{w}", None, "key b") == 15 and g.p.stdin.getvalue() == "key a\n", g.p.stdin.getvalue())
    koruma["neden"] = None
    g.gonder("{w}", None, "typedelay 4")
    koruma["neden"] = "tam ekranda (test)"
    kontrol("kde: ham harf başına denetlemez (aralık içinde)", kod_al(g.ham, "type x") == 0)
    time.sleep(kde.KORUMA_ARALIK + 0.05)
    kontrol("kde: ham aralık dolunca yeniden denetler → 15", kod_al(g.ham, "type y") == 15)
    koruma["neden"] = None

    # pencere kapatma da korumalı (D8): gerçek kdotool çağrılmaz
    cagrilar = []
    gercek_kd = kde.kd
    kde.kd = lambda *a: cagrilar.append(a) or ""
    try:
        koruma["neden"] = "video/film izliyor (test)"
        kontrol("kde: film izlerken pencere kapatma → 15, windowclose yok",
                kod_al(kde.KdeArkaUc().kapat, "{w}") == 15 and not cagrilar, str(cagrilar))
        koruma["neden"] = None
        kde.KdeArkaUc().kapat("{w}")
        kontrol("kde: koruma yokken kapatma gider", cagrilar == [("windowclose", "{w}")], str(cagrilar))
    finally:
        kde.kd = gercek_kd

    # karar bildirimi açıkken ön plan girdisi yok; --ekranimda aşmaz; sahibi ölmüş dosya yok sayılır
    kontrol("karar: dosya yokken beklemiyor", mesgul.karar_bekliyor() is False)
    icerik = mesgul._karar_bekliyor_yaz()
    os.environ["DESKHAND_EKRANIMDA"] = "1"
    try:
        g = sahte_kde_girdi()
        kontrol("karar: bildirim açıkken kde gonder → 12 (--ekranimda aşmaz)",
                mesgul.karar_bekliyor() and kod_al(g.gonder, "{w}", None, "click left") == 12 and
                g.p.stdin.getvalue() == "")
        gercek_girdi_sinifi = kde.Girdi
        kde.Girdi = lambda *a, **k: (_ for _ in ()).throw(AssertionError("dotool açılmamalı"))
        kontrol("karar: kde girdi() açılmaz → 12", kod_al(kde.KdeArkaUc().girdi, "t") == 12)
    finally:
        kde.Girdi = gercek_girdi_sinifi
        del os.environ["DESKHAND_EKRANIMDA"]
    mesgul._karar_bekliyor_sil(icerik)
    kontrol("karar: kendi dosyasını siler", not os.path.exists(mesgul.karar_bekliyor_yolu()))
    with open(mesgul.karar_bekliyor_yolu(), "w") as f:
        f.write(f"{os.getpid()} 1\n")  # PID canlı ama başlangıç zamanı uymuyor (PID başka sürece geçmiş)
    kontrol("karar: PID yeniden kullanılmış → yok sayılır", mesgul.karar_bekliyor() is False)
    with open(mesgul.karar_bekliyor_yolu(), "w") as f:
        f.write("999999999 123\n")
    kontrol("karar: süreç ölmüş → yok sayılır", mesgul.karar_bekliyor() is False)
    g = sahte_kde_girdi()
    kontrol("karar: bayat dosyada kde gonder serbest", kod_al(g.gonder, "{w}", None, "key a") == 0)
    kontrol("karar: ölü sürecin dosyası temizlendi", not os.path.exists(mesgul.karar_bekliyor_yolu()))
    # iki soru aynı anda: biri biterken diğerinin koruması kalır (dosyalar ayrı)
    baska = os.path.join(os.path.dirname(mesgul.karar_bekliyor_yolu()), "karar-bekliyor-1-1")
    with open(baska, "w") as f:
        f.write(f"1 {mesgul.surec_baslangici(1)}\n")  # PID 1 (systemd) canlı: başka bir "soran" süreç gibi
    benim = mesgul._karar_bekliyor_yaz()
    mesgul._karar_bekliyor_sil(benim)
    kontrol("karar: kendi sorum bitince başka sürecin sorusu korumayı sürdürür", mesgul.karar_bekliyor() is True)
    os.remove(baska)
    kontrol("karar: hepsi bitince koruma yok", mesgul.karar_bekliyor() is False)

    # sor() bildirim süresince dosyayı tutar, bitince siler (D-Bus sahte; gerçek bildirim yok)
    class SahteBag:
        def close(self): pass

    gozlem = []
    gercek_dbus, gercek_cagir = mesgul._dbus_ac, mesgul._cagir
    mesgul._dbus_ac = lambda: SahteBag()
    mesgul._cagir = lambda *a, **k: gozlem.append(mesgul.karar_bekliyor()) or None
    try:
        sonuc = mesgul.sor("test", 1)
    finally:
        mesgul._dbus_ac, mesgul._cagir = gercek_dbus, gercek_cagir
    kontrol("karar: sor() sırasında karar-bekliyor var, sonra yok",
            gozlem == [True] and not os.path.exists(mesgul.karar_bekliyor_yolu()), f"{gozlem} {sonuc}")
finally:
    mesgul.ekran_korumasi = gercek_koruma

# ================================================================ 7. MCP: onay beklerken kilit bırakılır (D12)
from deskhand import mcp_sunucu as s  # noqa: E402

au = SahteAU("kde")
arka_uc._ORNEKLER["kde"] = au
bekle = threading.Event()
istendi = threading.Event()


def bekleyen_iste_sonuc(eylem_, hedef, ayrinti="", masaustu="ekran", sure=120, goruntu=None, gunluge_yaz=True):
    ISTEKLER.append({"eylem": eylem_, "ayrinti": ayrinti})
    istendi.set()
    bekle.wait(20)
    return onay.OnaySonucu(YANIT["izin"], "izin" if YANIT["izin"] else "red")


onay.iste_sonuc = bekleyen_iste_sonuc


def mcp_eylem(sonuc):
    try:
        with api.hedef("kde"):
            desen = s.baslik_kilidi("{w}", "{w}")
            sonuc["r"] = s.onayla_ve_yap("press_key", "{w}", lambda onayli: api.tus("{w}", "enter", desen, onayli))
    except Exception as e:  # noqa: BLE001
        sonuc["hata"] = e


for senaryo in ("izin", "baslik-degisti"):
    ISTEKLER.clear()
    bekle.clear()
    istendi.clear()
    YANIT["izin"] = True
    au.pen["{w}"][0] = "Checkout - Ödeme - Shop"
    n0 = len(au.satirlar)
    sonuc = {}
    th = threading.Thread(target=mcp_eylem, args=(sonuc,), daemon=True)
    th.start()
    istendi.wait(10)
    t0 = time.monotonic()
    alindi = s.KILIT.acquire(timeout=2)
    if alindi:
        s.KILIT.release()
    kontrol(f"MCP [{senaryo}]: onay beklenirken kilit serbest (başka araç beklemez)",
            alindi and time.monotonic() - t0 < 1.0, f"{time.monotonic() - t0:.2f} sn")
    if senaryo == "baslik-degisti":
        au.pen["{w}"][0] = "Başka sekme — Ödeme"
    bekle.set()
    th.join(15)
    if senaryo == "izin":
        kontrol("MCP [izin]: onaydan sonra kilit yeniden alındı, Enter gönderildi, approved_by_user",
                "r" in sonuc and sonuc["r"][1] is True and au.satirlar[n0:] == ["key enter"],
                f"{sonuc} {au.satirlar[n0:]}")
    else:
        e = sonuc.get("hata")
        kontrol("MCP [başlık değişti]: onay geçersiz → 4, girdi yok",
                isinstance(e, Dur) and e.kod == 4 and au.satirlar[n0:] == [], f"{sonuc} {au.satirlar[n0:]}")
    kontrol(f"MCP [{senaryo}]: eylem bitince kilit serbest", not s.KILIT.locked())

onay.iste_sonuc = gercek_iste_sonuc
eylem.nokta_metni = gercek_nokta_metni
print(f"\n{GECEN}/{TOPLAM} güvenlik testi geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
