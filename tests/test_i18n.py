"""i18n + İngilizce komut adları testleri (EKRANSIZ: hiçbir komut ÇALIŞTIRILMAZ, girdi gönderilmez, pencere açılmaz).

- i18n: sistem_dili kuralları, DESKHAND_DIL önceliği, katalog geri düşmesi (eksik/bozuk/boş), h_() yüzde kaçışı,
  sahte bir İngilizce katalogla Dur mesajı ve yardım metni İngilizce.
- Komutlar: her İngilizce komut adı ve Türkçe takma adı ayrıştırıcıda AYNI işleve ve AYNI iç ada gider; İngilizce
  seçenekler Türkçe dest'e; konumsal değerler (left/up/green/off/start/status …) Türkçeye normalize edilir.
- dizi adımları (sahte girdi nesnesiyle yalnız `sleep`/`uyu`) ve .akis dosyaları İngilizce adları anlar; dizide
  yasak adımlar İngilizce adla da yasak.
- Katalog araçları: kaynak.json güncel (çıkarıcı yeniden çalışınca fark yok), en.json denetimden geçer, denetleyici
  bozuk yer tutucuyu/kaybolan komut adını yakalar; `_` hem atanıp hem _() olarak çağrılan işlev yok.

Çalıştır:  python3 tests/test_i18n.py"""
import argparse
import ast
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler + DESKHAND_DIL=tr; Deskhand'den ÖNCE)
from deskhand import akis, api, cli, eylem, hata, i18n, komutlar, masaustu, onay
from deskhand.oturum import cli as oturum_cli

KOK = _yalitim.KOK
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(("  ✓ " if kosul else "  ✗ ") + ad + ("" if kosul or not ek else f"  [{ek}]"))


# ---------------------------------------------------------------- 1) dil seçimi
print("1) sistem_dili / DESKHAND_DIL")
sd = i18n.sistem_dili
kontrol("locale yok → en", sd({}) == "en")
kontrol("C / POSIX / C.UTF-8 → en", sd({"LANG": "C"}) == sd({"LC_ALL": "POSIX"}) == sd({"LANG": "C.UTF-8"}) == "en")
kontrol("tr_TR.UTF-8 → tr", sd({"LANG": "tr_TR.UTF-8"}) == "tr")
kontrol("en_US.UTF-8 → en", sd({"LANG": "en_US.UTF-8"}) == "en")
kontrol("desteklenmeyen dil (de_DE) → en", sd({"LANG": "de_DE.UTF-8"}) == "en")
kontrol("LC_ALL, LANG'ı geçer", sd({"LC_ALL": "tr_TR.UTF-8", "LANG": "en_US.UTF-8"}) == "tr")
kontrol("LC_MESSAGES, LANG'ı geçer", sd({"LC_MESSAGES": "en_GB.UTF-8", "LANG": "tr_TR.UTF-8"}) == "en")
kontrol("LANGUAGE listesinde ilk DESTEKLENEN kazanır (de:tr)", sd({"LANG": "en_US.UTF-8", "LANGUAGE": "de:tr"}) == "tr")
kontrol("LANGUAGE, locale C iken yok sayılır", sd({"LANG": "C", "LANGUAGE": "tr"}) == "en")
kontrol("tr@euro / tr_TR biçimleri", sd({"LANG": "tr@euro"}) == sd({"LANG": "tr_TR"}) == "tr")
kontrol("DESKHAND_DIL=en sistemi geçer", i18n.secilen_dil({"DESKHAND_DIL": "en", "LANG": "tr_TR.UTF-8"}) == "en")
kontrol("DESKHAND_DIL=TR (büyük harf) → tr", i18n.secilen_dil({"DESKHAND_DIL": "TR", "LANG": "en_US.UTF-8"}) == "tr")
kontrol("geçersiz DESKHAND_DIL → sistem dili", i18n.secilen_dil({"DESKHAND_DIL": "xx", "LANG": "en_US.UTF-8"}) == "en")
kontrol("testlerde DESKHAND_DIL=tr (yalıtım)", os.environ.get("DESKHAND_DIL") == "tr" and i18n.dil() == "tr")
i18n.ayar_yaz("en")
kontrol("arayuz.json 'en' (DESKHAND_DIL yokken) → en", i18n.secilen_dil({"LANG": "tr_TR.UTF-8"}) == "en")
kontrol("DESKHAND_DIL arayuz.json'u da geçer", i18n.secilen_dil({"DESKHAND_DIL": "tr"}) == "tr")
i18n.ayar_yaz("otomatik")
kontrol("arayuz.json 'otomatik' → sistem dili", i18n.secilen_dil({"LANG": "tr_TR.UTF-8"}) == "tr")

# ---------------------------------------------------------------- 2) katalog geri düşmesi
print("2) katalog")
with tempfile.TemporaryDirectory() as d:
    kontrol("katalog dosyası yok → {}", i18n.katalog_oku("en", d) == {})
    with open(os.path.join(d, "en.json"), "w") as f:
        f.write("{bozuk")
    kontrol("bozuk JSON → {}", i18n.katalog_oku("en", d) == {})
    with open(os.path.join(d, "en.json"), "w") as f:
        json.dump({"a": "A", "b": "", "c": 3, "d": None}, f)
    kontrol("boş/metin olmayan çeviriler atılır", i18n.katalog_oku("en", d) == {"a": "A"})
    kontrol("Türkçe için katalog okunmaz", i18n.katalog_oku("tr", d) == {})
    with open(os.path.join(d, "kaynak.json"), "w") as f:
        json.dump({"a": ["x:1"], "b": ["x:2"]}, f)
    kontrol("kapsama = çevrilen / kaynak", i18n.kapsama("en", d) == 0.5 and i18n.kapsama("tr", d) is None)
kontrol("paketteki en.json okunur (boş olabilir)", isinstance(i18n.katalog_oku("en"), dict))
i18n.sifirla("en", {"merhaba": "hello", "%{n} tamam": "{n}% done"})
kontrol("_(): çeviri var → çeviri", i18n._("merhaba") == "hello")
kontrol("_(): çeviri yok → Türkçe msgid (geri düşme)", i18n._("çevrilmemiş metin") == "çevrilmemiş metin")
kontrol("h_(): argparse için % kaçışı", i18n.h_("%{n} tamam") == "{n}%% done")
kontrol("N_(): çevirmez", i18n.N_("merhaba") == "merhaba")
i18n.sifirla()
kontrol("sifirla() sonrası Türkçe (DESKHAND_DIL=tr)", i18n._("merhaba") == "merhaba" and i18n.dil() == "tr")

# ---------------------------------------------------------------- 3) sahte İngilizce katalog: Dur mesajı + yardım
print("3) sahte en kataloğu")
DUR_TR = "kullanıcı DUR dedi (deskhand devam ile kaldırılır); girdi gönderilmedi"
DUR_EN = "the user said STOP (lift it with deskhand resume); no input was sent"
os.makedirs(os.path.dirname(hata.dur_dosyasi()), exist_ok=True)
open(hata.dur_dosyasi(), "w").close()
try:
    i18n.sifirla("en", {DUR_TR: DUR_EN})
    try:
        hata.dur_denetle()
        mesaj = None
    except hata.Dur as e:
        mesaj, kod = e.mesaj, e.kod
    kontrol("Dur(13) mesajı İngilizce", mesaj == DUR_EN and kod == 13, repr(mesaj))
    i18n.sifirla("tr")
    try:
        hata.dur_denetle()
    except hata.Dur as e:
        mesaj = e.mesaj
    kontrol("aynı Dur Türkçe dilde Türkçe", mesaj == DUR_TR, repr(mesaj))
finally:
    os.remove(hata.dur_dosyasi())
    i18n.sifirla()
i18n.sifirla("en", {cli.YARDIM_KOMUTLAR[-1]: "  ekran help (yardım)                     this text",
                    cli.YARDIM_CIKIS[0]: "Exit codes: 0 ok"})
metin = cli.yardim_metni()
kontrol("yardım: çevrilen paragraflar İngilizce, çevrilmeyenler Türkçe",
        "this text" in metin and "Exit codes: 0 ok" in metin and "GÜVENLİK" in metin, metin[-300:])
i18n.sifirla("en", {onay.MESAJLAR["red"]: "the user refused"})
kontrol("onay.MESAJLAR gösterimde çevrilir (OnaySonucu.mesaj)", onay.OnaySonucu(False, "red").mesaj == "the user refused")
kontrol("onay: bilinmeyen neden aynen", onay.OnaySonucu(False, "baska").mesaj == "baska")
i18n.sifirla()
kontrol("onay penceresi başlığı çevrilmez (yasak desenler sabit adlara bakar)",
        onay.ONAY_BASLIK == "Deskhand — Onay" and any(__import__("re").search(d, onay.ONAY_BASLIK) for d in onay.YASAK_DESENLER))
yardim_tr = cli.yardim_metni()
kontrol("yardım (tr): İngilizce komut + parantezde Türkçe ad",
        f"{cli.prog_adi()} windows (bul) <desen>" in yardim_tr and f"{cli.prog_adi()} click-text (metne-tikla)" in yardim_tr
        and f"{cli.prog_adi()} stop | resume | status (dur | devam | durum)" in yardim_tr)
kontrol("yardım: her komutun İngilizce adı geçer", all(f" {en}" in yardim_tr for _tr, en in komutlar.KOMUTLAR),
        [en for _tr, en in komutlar.KOMUTLAR if f" {en}" not in yardim_tr])
kontrol("argümansız çıktı = komut paragrafı (ilk satır 'Komutlar')", cli.komut_listesi().startswith("Komutlar"))

# ---------------------------------------------------------------- 4) komut adları: İngilizce ≡ Türkçe (yalnız ayrıştırma)
print("4) komut adları (ayrıştırıcı düzeyi, hiçbir şey çalışmaz)")
p = cli.ayristirici("deskhand")
K = "{00000000-0000-0000-0000-000000000000}"
ORNEK = {  # komut → kimliksiz argümanlar
    "bul": ["x"], "foto": [K], "tikla": [K, "1", "2"], "tus": [K, "Return"], "yaz": [K, "a"], "kaydir": [K],
    "metin": [K], "metne-tikla": [K, "a"], "bekle": [K, "a"], "kapat": [K], "bas": [K, "w", "1"],
    "surukle": [K, "1", "2", "3", "4"], "fare": [K, "1", "2"], "dizi": [K], "uyu": ["0"], "renk-bul": [K, "yesil"],
    "renge-tikla": [K, "yesil"], "simge-kaydet": [K, "ad"], "simge-bul": [K, "ad"], "simgeye-tikla": [K, "ad"],
    "ac": ["x"], "akis": [K, "ad"], "erisim": [], "agac": [K], "ogeye-tikla": [K, "ad"], "dur": [], "devam": [],
    "durum": [], "mesgul": [], "karar": ["görev"], "panel": [], "masaustu": ["durum"], "oturum": ["durum"],
    "mcp": [], "yardım": [],
}
kontrol("örnek tablosu tüm komutları kapsıyor", set(ORNEK) == set(komutlar.TR_EN), set(komutlar.TR_EN) ^ set(ORNEK))
hatalar = []
for tr, en in komutlar.KOMUTLAR:
    adlar = {en, tr} | {k for k, v in komutlar.EK_TAKMA.items() if v == tr}
    sonuclar = {}
    for ad in adlar:
        try:
            a = p.parse_args([ad, *ORNEK[tr]])
        except SystemExit:
            hatalar.append(f"{ad}: ayrıştırılamadı")
            continue
        sonuclar[ad] = (a.f, a.komut)
    if len(set(sonuclar.values())) != 1 or next(iter(sonuclar.values()))[1] != tr:
        hatalar.append(f"{tr}/{en}: {sonuclar}")
kontrol(f"{len(komutlar.KOMUTLAR)} komutun İngilizce ve Türkçe adı aynı işlev + iç ad ({len(komutlar.KOMUTLAR)} çift)",
        not hatalar, hatalar)
kontrol("İngilizce adlar benzersiz", len(set(komutlar.EN_TR)) == len(komutlar.KOMUTLAR))
kontrol("ic_ad: İngilizce/Türkçe/ASCII takma → Türkçe; bilinmeyen aynen",
        komutlar.ic_ad("click-text") == "metne-tikla" and komutlar.ic_ad("tikla") == "tikla"
        and komutlar.ic_ad("yardim") == "yardım" and komutlar.ic_ad("xyz") == "xyz")


def ayr(*argv):
    return vars(p.parse_args(list(argv)))


# seçenekler: İngilizce ≡ Türkçe ≡ kısa (aynı dest)
s1 = ayr("--title", "T", "--class", "C", "--background", "--on-my-screen", "click", K, "1", "2")
s2 = ayr("--baslik", "T", "--sinif", "C", "--arka", "--ekranimda", "tikla", K, "1", "2")
s3 = ayr("-b", "T", "-s", "C", "--arka", "--ekranimda", "tikla", K, "1", "2")
kontrol("ortak seçenekler (komuttan önce): --title/--baslik/-b …", s1 == s2 == s3 and s1["baslik"] == "T"
        and s1["sinif"] == "C" and s1["arka"] and s1["ekranimda"])
s1 = ayr("click", K, "1", "2", "--title", "T", "--background")
s2 = ayr("tikla", K, "1", "2", "-b", "T", "--arka")
kontrol("ortak seçenekler (komuttan sonra)", s1 == s2 and s1["baslik"] == "T" and s1["arka"] is True)
CIFTLER = [
    (("click", K, "1", "2", "--approved", "--hold", "1.5", "--repeat", "3", "--shot"),
     ("tikla", K, "1", "2", "--onayli", "--basili", "1.5", "--tekrar", "3", "--foto")),
    (("click-text", K, "a", "--nth", "2", "--wait", "1", "--offset", "3,4", "--scroll-search", "5", "--region",
      "1,2,3,4", "--approved"),
     ("metne-tikla", K, "a", "--sira", "2", "--bekle", "1", "--kay", "3,4", "--kaydirarak", "5", "--bolge",
      "1,2,3,4", "--onayli")),
    (("read", K, "--precise", "--all", "--deep", "--stay", "--region", "1,2,3,4"),
     ("metin", K, "--hassas", "--hepsi", "--derin", "--kal", "--bolge", "1,2,3,4")),
    (("screenshot", K, "--width", "800", "--grid", "50"), ("foto", K, "--genislik", "800", "--izgara", "50")),
    (("wait", K, "a", "--timeout", "3", "--gone"), ("bekle", K, "a", "--sure", "3", "--yok")),
    (("open", "--command", "true", "--timeout", "5"), ("ac", "--komut", "true", "--sure", "5")),
    (("flow", K, "ad", "--timeout", "9"), ("akis", K, "ad", "--sure", "9")),
    (("drag", K, "1", "2", "3", "4", "--duration", "0.2"), ("surukle", K, "1", "2", "3", "4", "--sure", "0.2")),
    (("type", K, "a", "--secret"), ("yaz", K, "a", "--gizli")),
    (("batch", K, "--file", "f"), ("dizi", K, "--dosya", "f")),
    (("find-icon", K, "ad", "--threshold", "0.8"), ("simge-bul", K, "ad", "--esik", "0.8")),
    (("scroll", K, "--point", "1,2"), ("kaydir", K, "--nokta", "1,2")),
    (("tree", K, "--role", "push button", "--all"), ("agac", K, "--rol", "push button", "--hepsi")),
    (("find-color", K, "green", "--min-pixels", "9"), ("renk-bul", K, "yesil", "--en-az", "9")),
]
farkli = [(e[0], ayr(*e), ayr(*t)) for e, t in CIFTLER if ayr(*e) != ayr(*t)]
kontrol(f"İngilizce seçenekler Türkçe dest'e gider ({len(CIFTLER)} komut)", not farkli, farkli[:1])
kontrol("--timeout (wait) ve --duration (drag) ikisi de 'sure'",
        ayr("wait", K, "a", "--timeout", "3")["sure"] == 3.0 and ayr("drag", K, "1", "2", "3", "4", "--duration",
                                                                       "0.2")["sure"] == 0.2)

# ---------------------------------------------------------------- 5) değer normalizasyonu
print("5) değerler")
kontrol("düğme left/right/double/middle → sol/sag/cift/orta",
        [ayr("click", K, "1", "2", b)["dugme"] for b in ("left", "right", "double", "middle")] == ["sol", "sag", "cift", "orta"])
kontrol("düğme Türkçe aynen", [ayr("tikla", K, "1", "2", b)["dugme"] for b in ("sol", "sag", "cift", "orta")]
        == ["sol", "sag", "cift", "orta"])
kontrol("click-text/click-icon/click-element/click-color düğmesi", all(
    ayr(c, K, "a", "double")["dugme"] == "cift" for c in ("click-text", "click-icon", "click-element", "click-color")))
kontrol("drag: double yok (Türkçede de yok)", ayr("drag", K, "1", "2", "3", "4", "right")["dugme"] == "sag")
try:
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        p.parse_args(["drag", K, "1", "2", "3", "4", "double"])
    kontrol("drag double → kullanım hatası", False)
except SystemExit as e:
    kontrol("drag double → kullanım hatası (1; 2 = nokta dışarıda)", e.code == 1)
kontrol("yön down/up/left/right → asagi/yukari/sol/sag",
        [ayr("scroll", K, y)["yon"] for y in ("down", "up", "left", "right")] == ["asagi", "yukari", "sol", "sag"])
kontrol("kaydır varsayılanı asagi", ayr("scroll", K)["yon"] == "asagi")
kontrol("renk green/red/blue → yesil/kirmizi/mavi; R,G,B aynen",
        [ayr("find-color", K, r)["renk"] for r in ("green", "red", "blue", "10,20,30")] == ["yesil", "kirmizi", "mavi",
                                                                                         "10,20,30"])
kontrol("erişim on/off/status → ac/kapat/durum; varsayılan durum",
        [ayr("a11y", x)["islem"] for x in ("on", "off", "status", "ac")] == ["ac", "kapat", "durum", "ac"]
        and ayr("a11y")["islem"] == "durum")
kontrol("çevirici: bilinmeyen değer aynen (choices denetimi sonra)", komutlar.cevirici(komutlar.DUGME)("zzz") == "zzz")
# masaustu / oturum alt ayrıştırıcıları: yalnız OKUYAN işlemler (sanal masaüstü kapalı → 14)
with redirect_stdout(io.StringIO()) as o1:
    r1 = masaustu.main(["status"])
with redirect_stdout(io.StringIO()) as o2:
    r2 = masaustu.main(["durum"])
kontrol("desktop status ≡ masaustu durum (kapalı → 14, aynı çıktı)", r1 == r2 == hata.SANAL_KAPALI
        and o1.getvalue() == o2.getvalue() and "KAPALI" in o1.getvalue(), o1.getvalue())
kontrol("masaustu: start/stop/status → baslat/durdur/durum",
        [komutlar.MASAUSTU[x] for x in ("start", "stop", "status")] == ["baslat", "durdur", "durum"])
with redirect_stdout(io.StringIO()) as o1:
    r1 = oturum_cli.main(["policy", "firefox", "--json"])
with redirect_stdout(io.StringIO()) as o2:
    r2 = oturum_cli.main(["politika", "firefox", "--json"])
kontrol("sessions policy ≡ oturum politika", r1 == r2 == 0 and o1.getvalue() == o2.getvalue())
with redirect_stdout(io.StringIO()) as o1:
    r1 = oturum_cli.main(["status", "telegram", "--json"])
with redirect_stdout(io.StringIO()) as o2:
    r2 = oturum_cli.main(["durum", "telegram", "--json"])
kontrol("sessions status ≡ oturum durum", r1 == r2 == 0 and o1.getvalue() == o2.getvalue())
with redirect_stdout(io.StringIO()):
    kontrol("sessions clear ≡ oturum sil (0)", oturum_cli.main(["clear"]) == 0 and oturum_cli.main(["sil"]) == 0)

# ---------------------------------------------------------------- 6) dizi + akış dosyaları
print("6) dizi / akış")


class SahteGirdi:
    hazir = False

    def insan_kontrol(self):
        pass

    def kapat(self):
        self.kapandi = True


class SahteAU:
    def girdi(self, *a, **k):
        return SahteGirdi()


eski_au = eylem._au
eylem._au = lambda: SahteAU()
try:
    a = argparse.Namespace(kimlik=K, kimlik_ham=K, baslik=None)
    with redirect_stdout(io.StringIO()) as o:
        eylem.adimlari_calistir(a, ["sleep 0", "uyu 0"])
    kontrol("dizi: 'sleep' ve 'uyu' adımları çalışır", o.getvalue().count("beklendi: 0.0 sn") == 2, o.getvalue())
    yasak_tamam = []
    for adim in ("batch", "dizi", "flow ad", "akis ad", "close", "kapat", "a11y", "erisim", "open x", "ac x"):
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                eylem.adimlari_calistir(a, [adim])
            yasak_tamam.append((adim, "çalıştı"))
        except hata.Dur as e:
            if e.kod != 1:  # "… kullanılamaz" ya da (kimliksiz komutlar: ac/erisim) "… satır hatalı"; Türkçede de böyle
                yasak_tamam.append((adim, e.kod, e.mesaj))
    kontrol("dizi: yasak adımlar İngilizce adla da yasak (Dur 1)", not yasak_tamam, yasak_tamam)
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            eylem.adimlari_calistir(a, ["nonsense 1"])
        kontrol("dizi: bilinmeyen adım → Dur 1", False)
    except hata.Dur as e:
        kontrol("dizi: bilinmeyen adım → Dur 1", e.kod == 1)
finally:
    eylem._au = eski_au

with tempfile.TemporaryDirectory() as d:
    yol = os.path.join(d, "ing.akis")
    with open(yol, "w") as f:
        f.write('# İngilizce adlarla akış\ntimeout 30\nrepeat 2\nregion %10,10,90,90\nsuccess text "Main menu"\n'
                'success gone "Connecting"\nerror "Version mismatch"\nscreen "Update" | "Güncelle"\n'
                '  click-text "Later" --nth 2\n  click-color green --below=200\n  wait 2\n  key ctrl+a\n'
                '  type "x" --secret\n  sleep 0.5\n  done\nscreen "Broken"\n  stop "kırık ekran"\n')
    ayar, ekranlar = akis.akis_oku(yol)
    kontrol("akış: İngilizce yönergeler (timeout/repeat/region/success/error)",
            ayar == {"sure": 30.0, "tekrar": 2, "bolge": "%10,10,90,90",
                     "basari": [("metin", "Main menu"), ("yok", "Connecting")], "hata": ["Version mismatch"]}, ayar)
    adim = ekranlar[0]["adimlar"]
    kontrol("akış: adım komutları Türkçe iç ada çevrildi",
            [x.split()[0] for x in adim] == ["metne-tikla", "renge-tikla", "bekle", "tus", "yaz", "uyu", "bitti"], adim)
    kontrol("akış: --below → --altinda, seçenekler/tırnaklar korunur",
            adim[1] == "renge-tikla green --altinda=200" and adim[0] == "metne-tikla Later --nth 2", adim[:2])
    kontrol("akış: ekran anahtarları + stop → dur", ekranlar[0]["anahtarlar"] == ["Update", "Güncelle"]
            and ekranlar[1]["adimlar"] == ["dur 'kırık ekran'"], ekranlar[1])
    b = cli.ayristirici("deskhand").parse_args([adim[0].split()[0], K, "Later", "--nth", "2"])
    kontrol("akış adımı ayrıştırıcıda İngilizce seçenekle çözülür", b.komut == "metne-tikla" and b.sira == 2)
    with open(os.path.join(d, "eski.akis"), "w") as f:
        f.write('sure 10\nekran "A"\n  metne-tikla "B"\n  bekle 1\n  bitti\n')
    ayar2, ek2 = akis.akis_oku(os.path.join(d, "eski.akis"))
    kontrol("akış: Türkçe dosya aynen", ayar2["sure"] == 10.0 and ek2[0]["adimlar"] == ["metne-tikla B", "bekle 1", "bitti"])

eski_dizin = os.environ.get("DESKHAND_DATA_DIR")
akis_d = os.path.join(eski_dizin, "akislar")
os.makedirs(akis_d, exist_ok=True)
with open(os.path.join(akis_d, "onayli-en.akis"), "w") as f:
    f.write('ekran "X"\n  click-text "Pay" --approved\n')
with open(os.path.join(akis_d, "onaysiz.akis"), "w") as f:
    f.write('ekran "X"\n  click-text "Next"\n')
gerek = {x["name"]: x["needs_approval"] for x in api.akislar()}
kontrol("akış listesi: --approved (İngilizce) da 'onay gerekir' sayılır", gerek.get("onayli-en") is True
        and gerek.get("onaysiz") is False, gerek)
src = open(os.path.join(KOK, "deskhand", "mcp_sunucu.py"), encoding="utf-8").read()
kontrol("MCP run_flow: --approved da onay ister (adım ayrıştırılarak, alt dize değil)",
        "api.akis_onayli_adimlar(yol)" in src and bool(api.akis_onayli_adimlar(os.path.join(akis_d, "onayli-en.akis"))))

# hassas engel işareti: mesaj çevrilse de MCP hassas engeli tanır
from deskhand import mcp_sunucu  # noqa: E402
kontrol("MCP _hassas_mi: Dur.tur='hassas' (çevrilmiş mesajla)",
        mcp_sunucu._hassas_mi(hata.Dur(10, "SENSITIVE button", tur="hassas"))
        and not mcp_sunucu._hassas_mi(hata.Dur(10, "FORBIDDEN window")))
kontrol("MCP _hassas_mi: eski Türkçe önek hâlâ tanınır", mcp_sunucu._hassas_mi(hata.Dur(10, "HASSAS düğme (...)")))

# ---------------------------------------------------------------- 7) katalog araçları
print("7) katalog araçları")
sys.path.insert(0, os.path.join(KOK, "tools"))
import i18n_cikar  # noqa: E402
import i18n_denetle  # noqa: E402

kontrol("araçların DILLER'i i18n.DILLER ile aynı", set(i18n_cikar.DILLER) == set(i18n.DILLER) - {i18n.KAYNAK})
msgs, uyarilar = i18n_cikar.tara()
ciddi = [str(u) for u in uyarilar if u.ciddi]
kontrol("çıkarıcı: f-string / birleştirme / bozuk yer tutucu yok", not ciddi, ciddi[:5])
try:
    mevcut = i18n_cikar.kaynak_oku()
except (OSError, ValueError):
    mevcut = None
kontrol("kaynak.json güncel (çıkarıcı yeniden çalışınca fark yok; değilse: python3 tools/i18n_cikar.py)",
        mevcut == msgs, "" if mevcut is None else
        f"+{len(set(msgs) - set(mevcut))} -{len(set(mevcut) - set(msgs))} msgid; yer farkı "
        f"{sum(1 for m in msgs if m in mevcut and mevcut[m] != msgs[m])}")
gunluk_cevrili = []
for kok_, _d, dosyalar in os.walk(os.path.join(KOK, "deskhand")):
    for ad in dosyalar:
        if ad.endswith(".py"):
            yol = os.path.join(kok_, ad)
            for n in ast.walk(ast.parse(open(yol, encoding="utf-8").read())):
                if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "gunluk" and any(
                        isinstance(c, ast.Call) and getattr(c.func, "id", "") in ("_", "h_") for c in ast.walk(n)):
                    gunluk_cevrili.append(f"{os.path.relpath(yol, KOK)}:{n.lineno}")
kontrol("günlük satırları çevrilmez (gunluk() içinde _() yok; panel ayrıştırıyor)", not gunluk_cevrili, gunluk_cevrili)
r = subprocess.run([sys.executable, os.path.join(KOK, "tools", "i18n_denetle.py")], capture_output=True, text=True,
                   timeout=60)
kontrol("i18n_denetle: paketteki en.json temiz (0)", r.returncode == 0, r.stdout[-400:] + r.stderr[-400:])
with tempfile.TemporaryDirectory() as d:
    kaynak = {"tuş: {kombinasyon}": ["x:1"], "kullanıcı DUR dedi (deskhand devam ile kaldırılır)": ["x:2"],
              "--sira 1..{en_cok} olmalı": ["x:3"], "ayar: DESKHAND_HEDEF=arka": ["x:4"], "dosya ~/.config/deskhand/a.txt": ["x:5"]}
    iyi = {"tuş: {kombinasyon}": "key: {kombinasyon}",
           "kullanıcı DUR dedi (deskhand devam ile kaldırılır)": "the user said STOP (lift it with deskhand resume)",
           "--sira 1..{en_cok} olmalı": "--nth must be 1..{en_cok}",
           "ayar: DESKHAND_HEDEF=arka": "setting: DESKHAND_HEDEF=arka",
           "dosya ~/.config/deskhand/a.txt": "file ~/.config/deskhand/a.txt"}
    with open(os.path.join(d, "en.json"), "w") as f:
        json.dump(iyi, f)
    r = i18n_denetle.dil_denetle("en", kaynak, d)
    kontrol("denetleyici: doğru çeviri (resume ≡ devam, --nth ≡ --sira) temiz",
            not (r.yer_tutucu or r.bicim or r.korunan or r.yerlesim) and r.kapsama == 100.0,
            (r.yer_tutucu, r.bicim, r.korunan, r.yerlesim))
    kotu = {"tuş: {kombinasyon}": "key: {combination}",
            "kullanıcı DUR dedi (deskhand devam ile kaldırılır)": "the user said STOP (lift it with deskhand continue)",
            "--sira 1..{en_cok} olmalı": "--index must be 1..{en_cok",
            "ayar: DESKHAND_HEDEF=arka": "setting: DESKHAND_TARGET=back",
            "dosya ~/.config/deskhand/a.txt": "file ~/.config/handdesk/a.txt"}
    with open(os.path.join(d, "en.json"), "w") as f:
        json.dump(kotu, f)
    r = i18n_denetle.dil_denetle("en", kaynak, d)
    kontrol("denetleyici: yer tutucu adı değişti → hata", any(m == "tuş: {kombinasyon}" for m, _n in r.yer_tutucu))
    kontrol("denetleyici: bozuk biçim ('{en_cok') → hata", any(m.startswith("--sira") for m, _n in r.bicim))
    kontrol("denetleyici: komut/seçenek/ortam/yol adı kayboldu → hata",
            {m for m, _n in r.korunan} >= {"kullanıcı DUR dedi (deskhand devam ile kaldırılır)", "--sira 1..{en_cok} olmalı",
                                           "ayar: DESKHAND_HEDEF=arka", "dosya ~/.config/deskhand/a.txt"},
            r.korunan)
    with open(os.path.join(d, "en.json"), "w") as f:
        json.dump({"eski metin": "old text"}, f)
    r = i18n_denetle.dil_denetle("en", kaynak, d)
    kontrol("denetleyici: kaynakta olmayan girdi = eski; eksikler kapsamada", r.eski == ["eski metin"] and r.kapsama == 0.0)

# `_` hem yerel değişken hem çeviri işlevi olursa UnboundLocalError: hiçbir işlevde ikisi birden olmasın
cakisan = []
for kok_, _d, dosyalar in os.walk(os.path.join(KOK, "deskhand")):
    for ad in dosyalar:
        if not ad.endswith(".py"):
            continue
        yol = os.path.join(kok_, ad)
        agac = ast.parse(open(yol, encoding="utf-8").read())

        def kendi(n):
            for c in ast.iter_child_nodes(n):
                if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef, ast.ListComp,
                                  ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                    continue
                yield c
                yield from kendi(c)
        for fn in [agac, *[n for n in ast.walk(agac) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]]:
            atar = any(isinstance(n, ast.Name) and n.id == "_" and isinstance(n.ctx, (ast.Store, ast.Del))
                       for n in kendi(fn))
            cagirir = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_"
                          for n in (kendi(fn) if fn is agac else ast.walk(fn)))
            if atar and (cagirir or fn is agac):
                cakisan.append(f"{os.path.relpath(yol, KOK)}:{getattr(fn, 'lineno', 0)}")
kontrol("hiçbir işlev (ya da modül) `_`'yi hem atayıp hem _() çağırmıyor", not cakisan, cakisan)

print(f"\n{gecen}/{toplam} i18n testi geçti")
sys.exit(0 if gecen == toplam else 1)
