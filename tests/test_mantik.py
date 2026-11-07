"""deskhand mantık testleri (EKRANSIZ: girdi göndermez, pencere açmaz, uygulama başlatmaz).
Klavye etkinliği kuralları (sentetik olaylarla), akış dosyası ayrıştırma, bulanık eşleşme, uygulama bulma,
başlatma yasağı (ekran v3.2'den, 28 test) + paket yapısı: yollar/geçiş, DUR anahtarı, arka uç seçimi,
güvenlik denetiminin sahte arka uçla sınanması, Girdi bağlantısı (sahte dotool borusu), ham araç çağrısı taraması.

Çalıştır:  python3 tests/test_mantik.py"""
import os, sys, tempfile, time, types

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from deskhand import akis, guvenlik, hata, insan, ocr, uygulama, yollar

# Ekran koruması (kod 15) gerçek masaüstünü OKUR: bu takım kullanıcının o anki ekranına (film/masaüstü) bağlı
# kalmasın; koruma ayrı testlerde (test_entegrasyon, test_guvenlik) sınanıyor.
from deskhand import mesgul as _mesgul  # noqa: E402
_mesgul.ekran_korumasi = lambda *a, **k: None
_mesgul.karar_bekliyor = lambda: False


class _E:  # eski tek dosyalık modülün adları → paket modülleri (testler aynen kalsın)
    Etkinlik, ETKINLIK_MS, KENDI_PAY = insan.Etkinlik, insan.ETKINLIK_MS, insan.KENDI_PAY
    kaba, norm = staticmethod(ocr.kaba), staticmethod(ocr.norm)
    bulanik_icerir, akis_oku, akis_bolge = staticmethod(akis.bulanik_icerir), staticmethod(akis.akis_oku), \
        staticmethod(akis.akis_bolge)
    Dur = hata.Dur
    masaustu_girdileri, uygulama_bul = staticmethod(uygulama.masaustu_girdileri), staticmethod(uygulama.uygulama_bul)
    baslatma_yasak_denetle = staticmethod(guvenlik.baslatma_yasak_denetle)


E = _E
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


def sahte_etk(olaylar, kendi=(), hazir_once=1.0):
    e = E.Etkinlik.__new__(E.Etkinlik)
    e.olaylar, e.kendi, e.hata, e.p = list(olaylar), [list(x) for x in kendi], None, None
    e.hazir_an = time.monotonic() - hazir_once
    e._hazir = types.SimpleNamespace(wait=lambda t: True)
    return e


t = time.monotonic()
ms = E.ETKINLIK_MS / 1000
# 1) sessiz kullanıcı: yalnız açılış 'bosta'
kontrol("etkinlik: sessiz → insan yok", not sahte_etk([("bosta", t - 0.9)]).insan(t - 1))
# 2) bizim girdimiz (pencere içinde) → insan değil
e = sahte_etk([("bosta", t - 0.9), ("aktif", t - 0.5), ("bosta", t - 0.4)], kendi=[(t - 0.51, t - 0.45 + E.KENDI_PAY)])
kontrol("etkinlik: kendi girdimiz → insan değil", not e.insan(t - 1))
# 3) pencere dışında 'aktif' → insan
e = sahte_etk([("bosta", t - 0.9), ("aktif", t - 0.3), ("bosta", t - 0.2)], kendi=[(t - 0.8, t - 0.7)])
kontrol("etkinlik: pencere dışı aktif → İNSAN", e.insan(t - 1))
# 4) 'beri'den önceki insan olayı sayılmaz (bitmiş)
kontrol("etkinlik: eski (beri öncesi) insan olayı sayılmaz", not e.insan(t - 0.1))
# 5) hiç bosta gelmedi (yardımcı açıldığından beri kesintisiz girdi) → insan
kontrol("etkinlik: açılıştan beri hiç boşta yok → İNSAN", sahte_etk([], hazir_once=0.5).insan(t - 1))
kontrol("etkinlik: yardımcı yeni açıldı, olay yok → henüz insan sayılmaz", not sahte_etk([], hazir_once=0.05).insan(t - 1))
# 6) bizim aktifimiz ama girdimiz bittiği halde etkinlik sürüyor → insan
e = sahte_etk([("bosta", t - 2), ("aktif", t - 1.0)], kendi=[(t - 1.01, t - 0.9)])
kontrol("etkinlik: bizim girdimiz bitti, etkinlik sürüyor → İNSAN", e.insan(t - 0.5))
e = sahte_etk([("bosta", t - 2), ("aktif", t - 0.05)], kendi=[(t - 0.06, t + 0.1)])
kontrol("etkinlik: bizim girdimiz sürüyor → insan değil", not e.insan(t - 0.5))
# 7) sessizlik ölçümü
kontrol("sessiz_mi: son girdi 2 sn önce → sessiz", sahte_etk([("bosta", t - 3), ("aktif", t - 2.1), ("bosta", t - 2.0)]).sessiz_mi(1.5))
kontrol("sessiz_mi: son girdi 0,5 sn önce → değil", not sahte_etk([("bosta", t - 3), ("aktif", t - 0.6), ("bosta", t - 0.5)]).sessiz_mi(1.5))
kontrol("sessiz_mi: şu an etkin → değil", not sahte_etk([("bosta", t - 3), ("aktif", t - 0.1)]).sessiz_mi(1.5))
e = sahte_etk([("bosta", t - 0.2)], hazir_once=0.25)
kontrol("sessiz_mi: yalnız açılış boşta, yardımcı 0,25 sn önce açıldı → henüz değil", not e.sessiz_mi(1.5))
# 8) kendi pencere birleştirme
e = sahte_etk([])
e.kendi_girdi(t, t + 0.01); e.kendi_girdi(t + 0.02, t + 0.03)
kontrol("kendi_girdi: çakışan pencereler birleşir", len(e.kendi) == 1, str(e.kendi))
# 9) gerçek yardımcı süreç çalışıyor mu (yalnız dinler; girdi göndermez)
r = E.Etkinlik()
kontrol("yardımcı: Wayland boşta bildirimi v2 bağlandı", r.calisiyor() and r.hazir_an is not None, r.hata or "")
r.kapat()

# 10) bulanık eşleşme
n = lambda s: E.kaba(E.norm(s))
kontrol("bulanik: Türkçe harf/boşluk duyarsız", E.bulanik_icerir(n("SUNUCU İLE İLETİŞİM KURULAMADI lütfen"), "iletişim kurulamadı"))
kontrol("bulanik: OCR harf düşmesi ('kuruladı')", E.bulanik_icerir(n("sunucu ile iletisim kuruladi"), "iletişim kurulamadı"))
kontrol("bulanik: alakasız metin eşleşmez", not E.bulanik_icerir(n("Tek oyunculu oyun başlat"), "iletişim kurulamadı"))
kontrol("bulanik: kısa anahtar yalnız tam", not E.bulanik_icerir(n("Tamam"), "Tamm") and E.bulanik_icerir(n("Tamam"), "Tamam"))

# 11) akış dosyası
d = tempfile.mkdtemp()
yol = os.path.join(d, "t.akis")
open(yol, "w").write('''# deneme
sure 40
tekrar 3
bolge %10,10,90,90
basari metin "Kurulum tamamlandı"
hata "Kurulum başarısız"
ekran "Lisans sözleşmesi" | "lisans"
  renge-tikla yesil --altinda=300
ekran "Hoş geldiniz"
  metne-tikla "İleri"   # yorum
  bekle 0.5
''')
ayar, ekr = E.akis_oku(yol)
kontrol("akış: ayarlar", ayar["sure"] == 40 and ayar["tekrar"] == 3 and ayar["basari"] == [("metin", "Kurulum tamamlandı")]
        and ayar["hata"] == ["Kurulum başarısız"], str(ayar))
kontrol("akış: ekran blokları + anahtarlar + adımlar", len(ekr) == 2 and ekr[0]["anahtarlar"] == ["Lisans sözleşmesi", "lisans"]
        and ekr[1]["adimlar"] == ["metne-tikla 'İleri'", "bekle 0.5"], str(ekr))
kontrol("akış: oransal bölge", E.akis_bolge("%10,10,90,90", (0, 0, 1000, 500, )) == [100, 50, 800, 400])
open(yol, "w").write("sure 10\n  tus a\n")
try:
    E.akis_oku(yol); ok = False
except E.Dur as x:
    ok = x.kod == 1
kontrol("akış: bloksuz girintili adım → hata 1", ok)

# 12) uygulama bulma + başlatma yasağı (HİÇBİR ŞEY BAŞLATILMAZ)
gir = E.masaustu_girdileri()
kontrol("uygulama: .desktop girdileri okundu", len(gir) > 20, str(len(gir)))
try:
    g = E.uygulama_bul("Dolphin"); ok = "dolphin" in g["kimlik"].lower()
except E.Dur as x:
    ok, g = False, x.mesaj
kontrol("uygulama: 'Dolphin' bulundu", ok, str(g))
os.makedirs(os.path.dirname(yollar.yasak_dosya()), exist_ok=True)
with open(yollar.yasak_dosya(), "w") as f:  # testin kendi listesi (varsayılan liste boş)
    f.write("Ornek Oyun\nsteam_app_123456\n")
for ornek in ("steam steam://rungameid/123456", "steam -applaunch 123456", "Ornek Oyun 2"):
    try:
        E.baslatma_yasak_denetle(ornek); ok = False
    except E.Dur as x:
        ok = x.kod == 10
    kontrol(f"yasak: '{ornek}' başlatılmaz (10)", ok)
try:
    E.baslatma_yasak_denetle("steam steam://rungameid/427520", "Örnek Oyun"); ok = True
except E.Dur:
    ok = False
kontrol("yasak: başka oyun serbest", ok)

# ================================================================ paket (deskhand) testleri
import io, re, subprocess
from deskhand import arka_uc, eylem, yollar
from deskhand.arka_uc import EKRAN, kde

KOK = _yalitim.KOK

# 13) yollar: ortamla yönlendirme + eski ekran klasörlerinden KOPYA (taşıma değil)
kontrol("yollar: DESKHAND_CONFIG_DIR geçici klasörde", yollar.yasak_dosya().startswith(_yalitim.GECICI))
ev = tempfile.mkdtemp(dir=_yalitim.GECICI)
os.makedirs(os.path.join(ev, ".config/ekran"))
open(os.path.join(ev, ".config/ekran/yasak-pencereler.txt"), "w").write("OzelYasak\n")
os.makedirs(os.path.join(ev, ".local/share/ekran/simgeler"))
open(os.path.join(ev, ".local/share/ekran/simgeler/s.png"), "wb").write(b"x")
yedek = {k: os.environ.pop(k) for k in ("HOME", "DESKHAND_CONFIG_DIR", "DESKHAND_DATA_DIR", "DESKHAND_STATE_DIR")}
os.environ["HOME"] = ev
try:
    yapilan = yollar.gecis()
    ok = (os.path.exists(os.path.join(ev, ".config/deskhand/yasak-pencereler.txt"))
          and os.path.exists(os.path.join(ev, ".config/ekran/yasak-pencereler.txt"))
          and os.path.exists(os.path.join(ev, ".local/share/deskhand/simgeler/s.png")))
    kontrol("geçiş: eski klasörler KOPYALANDI, eskiler yerinde", ok and len(yapilan) == 2, str(yapilan))
    open(os.path.join(ev, ".config/deskhand/yasak-pencereler.txt"), "w").write("Yeni\n")
    kontrol("geçiş: yeni klasör varsa dokunulmaz", not yollar.gecis()
            and open(os.path.join(ev, ".config/deskhand/yasak-pencereler.txt")).read() == "Yeni\n")
finally:
    os.environ.update(yedek)
os.environ["HOME"] = yedek["HOME"]
kontrol("geçiş: DESKHAND_* verilmişse hiç geçiş yok", yollar.gecis() == [])

# 14) varsayılan yasak listesi BOŞ (yalnız yorum satırları); yerleşik panel yasağı her zaman var
os.remove(yollar.yasak_dosya())
try:
    guvenlik.baslatma_yasak_denetle("Ornek Oyun 2"); ok = True
except hata.Dur:
    ok = False
kontrol("yasak: varsayılan liste boş yazıldı, hiçbir uygulama yasak değil",
        ok and guvenlik._kullanici_yasaklari() == [] and os.path.exists(yollar.yasak_dosya()))
with open(yollar.yasak_dosya(), "w") as f:  # sonraki denetim testleri için örnek yasak
    f.write("Ornek Oyun\nsteam_app_123456\n")

# 15) DUR anahtarı
guvenlik.dur_ac()
try:
    hata.dur_denetle(); ok = False
except hata.Dur as x:
    ok = x.kod == 13
kontrol("DUR: açıkken dur_denetle → 13", ok)
kontrol("DUR: dosya DESKHAND_RUNTIME_DIR altında", hata.dur_dosyasi().startswith(_yalitim.GECICI))
guvenlik.dur_kapat()
try:
    hata.dur_denetle(); ok = True
except hata.Dur:
    ok = False
kontrol("DUR: devam sonrası serbest", ok)

# 16) arka uç seçimi
kontrol("hedef: varsayılan kde", arka_uc.hedef_ad() == "kde")
kontrol("hedef: arka: öneki → sanal", arka_uc.hedef_ad("arka:0x1a00007") == "sanal")
kontrol("hedef: --arka → sanal", arka_uc.hedef_ad(None, True) == "sanal")


# 17) üst katman yalnız ArkaUc ile: sahte arka uçla güvenlik denetimi (hiçbir gerçek araç çağrılmaz)
class SahteAU(arka_uc.ArkaUc):
    ad = "kde"

    def __init__(self):
        self.akt, self.basliklar, self.siniflar = "{a}", {"{a}": "Not defteri", "{y}": "Ornek Oyun 2"}, {}
        self.imlec = (110, 120, "{a}")

    def pencere_coz(self, arg): return arg
    def pencereler(self, desen=None): return []
    def geometri(self, k): return (100, 100, 400, 300) if k != EKRAN else (0, 0, 1000, 800)
    def baslik(self, k): return self.basliklar.get(k, "")
    def sinif(self, k): return self.siniflar.get(k, "uyg")
    def aktif(self): return self.akt
    def one_getir(self, k): pass
    def kapat(self, k): pass
    def fare(self): return self.imlec
    def ekran_alani(self): return (0, 0, 1000, 800)
    def goruntu(self): raise AssertionError("görüntü alınmamalı")
    def girdi(self, etiket="", gizli=False, etk=None, denetle=None): raise AssertionError("girdi açılmamalı")
    def insan_var_mi(self): return False
    def baslat(self, argv, env=None): raise AssertionError("başlatılmamalı")
    def gecerli_tuslar(self): return {"enter", "w", "d", "s", "a", "leftshift", "backspace", "esc"}


def kod_al(f, *a):
    try:
        f(*a)
        return 0
    except hata.Dur as x:
        return x.kod


sahte = SahteAU()
eski_kde = arka_uc._ORNEKLER.get("kde")
arka_uc._ORNEKLER["kde"] = sahte
try:
    kontrol("denetle: aktif + başlık uyuyor → geçer", kod_al(guvenlik.denetle, "{a}", "defter") == 0)
    kontrol("denetle: başlık kilidi uymadı → 4", kod_al(guvenlik.denetle, "{a}", "Tarayıcı") == 4)
    sahte.akt = "{b}"
    kontrol("denetle: aktif pencere değişti → 3", kod_al(guvenlik.denetle, "{a}", None) == 3)
    sahte.akt = "{y}"
    kontrol("denetle: yasak pencere → 10", kod_al(guvenlik.denetle, "{y}", None) == 10)
    kontrol("denetle: masaüstü kipinde etkin pencere yasak → 10", kod_al(guvenlik.denetle, EKRAN, None) == 10)
    sahte.akt = ""
    kontrol("denetle: etkin pencere belirlenemedi → 3", kod_al(guvenlik.denetle, EKRAN, None) == 3)
    sahte.akt = "{a}"
    guvenlik.SINIF_DESEN = "krunner"
    kontrol("denetle: sınıf kilidi → 4", kod_al(guvenlik.denetle, "{a}", None) == 4)
    guvenlik.SINIF_DESEN = None
    sahte.imlec = (300, 300, "{a}")
    kontrol("imleç hedefte değil → 12", kod_al(guvenlik.imlec_alti_denetle, "{a}", 110, 120) == 12)
    sahte.imlec = (110, 120, "{y}")
    kontrol("imlecin altında yasak pencere → 10", kod_al(guvenlik.imlec_alti_denetle, "{a}", 110, 120) == 10)
    sahte.basliklar["{o}"] = "Ödeme — Mağaza"
    kontrol("ödeme sayfası başlığı → 10 (onaysız)", kod_al(guvenlik.hassas_sayfa_engel, "{o}", False, "tıklama") == 10)
    kontrol("hassas düğme 'Satın al' → 10", kod_al(guvenlik.hassas_engel, False, "Satın al") == 10)
    fx, fy, px, py = eylem.ekran_noktasi("{a}", 10, 20)
    kontrol("ekran_noktasi: pencere → ekran (+ kesir)", (px, py) == (110, 120) and abs(fx - 110.5 / 1000) < 1e-9
            and abs(fy - 120.5 / 800) < 1e-9, str((fx, fy, px, py)))
    kontrol("ekran_noktasi: pencere dışı → 2", kod_al(eylem.ekran_noktasi, "{a}", 500, 20) == 2)
    kontrol("tus_coz: X adı Return → enter", eylem.tus_coz("Return") == "enter")
    kontrol("tus_coz: tek başına shift → leftshift", eylem.tus_coz("shift") == "leftshift")
    kontrol("tus_coz: w+d → 1, bas için w d", kod_al(eylem.tus_coz, "w+d") == 1 and eylem.tus_coz("w+d", True) == "w d")
    kontrol("tus_coz: bilinmeyen tuş → 1", kod_al(eylem.tus_coz, "ctrl+Bogus") == 1)
finally:
    guvenlik.SINIF_DESEN = None
    if eski_kde is None:
        arka_uc._ORNEKLER.pop("kde", None)
    else:
        arka_uc._ORNEKLER["kde"] = eski_kde


# 18) kde Girdi bağlantısı: SAHTE dotool borusu (gerçek dotool AÇILMAZ). gonder: DUR → denetle → yaz; zorla denetimsiz
class SahteBoru:
    def __init__(self): self.stdin = io.StringIO()
    def poll(self): return None


def sahte_girdi(denetimler):
    g = kde.Girdi.__new__(kde.Girdi)
    g.au, g.denetle = sahte, (lambda k, d: denetimler.append((k, d)))
    g.etk, g.etk_sahibi, g.p, g.hazir = None, False, SahteBoru(), True
    g.etiket, g.gizli, g.kesildi, g.son_etk = "test", False, None, time.monotonic()
    return g


arka_uc._ORNEKLER["kde"] = sahte
try:
    den = []
    g = sahte_girdi(den)
    g.gonder("{a}", "defter", "key enter")
    kontrol("Girdi.gonder: denetle(k, desen) çağrıldı, satır yazıldı",
            den == [("{a}", "defter")] and g.p.stdin.getvalue() == "key enter\n", f"{den} {g.p.stdin.getvalue()!r}")
    guvenlik.dur_ac()
    den.clear()
    g2 = sahte_girdi(den)
    kontrol("Girdi.gonder: DUR açık → 13, denetim/yazı yok",
            kod_al(g2.gonder, "{a}", None, "click left") == 13 and not den and g2.p.stdin.getvalue() == "")
    kontrol("Girdi.ham: DUR açık → 13", kod_al(g2.ham, "type a") == 13 and g2.p.stdin.getvalue() == "")
    g2.zorla("keyup w")
    kontrol("Girdi.zorla: DUR açıkken bile bırakır", g2.p.stdin.getvalue() == "keyup w\n")
    guvenlik.dur_kapat()
finally:
    guvenlik.dur_kapat()
    if eski_kde is None:
        arka_uc._ORNEKLER.pop("kde", None)
    else:
        arka_uc._ORNEKLER["kde"] = eski_kde

# 19) ham araç çağrısı YALNIZ arka uçta (docs/ARCHITECTURE.md §4)
ham = []
for kok_, _, dosyalar in os.walk(os.path.join(KOK, "deskhand")):
    if os.path.basename(kok_) == "arka_uc":
        continue
    for f in dosyalar:
        if f.endswith(".py"):
            for no, satir in enumerate(open(os.path.join(kok_, f)), 1):
                if re.search(r"[\"'](kdotool|dotool|xdotool|spectacle|kscreen-doctor)[\"']", satir):
                    ham.append(f"{f}:{no}")
kontrol("ham kdotool/dotool/spectacle çağrısı yalnız arka_uc/ içinde", not ham, str(ham))

# 20) komut satırı (salt: yardım/durum/dur/devam; girdi komutu DUR açıkken ve var olmayan pencereye)
def deskhand(*a):
    r = subprocess.run([sys.executable, "-m", "deskhand", *a], capture_output=True, text=True, cwd=KOK, timeout=60)
    return r.returncode, r.stdout + r.stderr


kod, out = deskhand()
kontrol("cli: argümansız → komut listesi, 1", kod == 1 and "ekran windows (bul) <desen>" in out
        and "ekran stop | resume | status (dur | devam | durum)" in out)
kod, out = deskhand("yardım")
kontrol("cli: yardım → tam metin + yeni komutlar + --arka + 13/14, 0",
        kod == 0 and "GÜVENLİK" in out and "--arka" in out and "13 kullanıcı DUR dedi" in out and "14 sanal" in out)
kod, out = deskhand("--arka", "durum")
kontrol("cli: --arka durum → sanal", kod == 0 and "arka uç: sanal" in out, out)
deskhand("dur")
kod, out = deskhand("tikla", "{00000000-0000-0000-0000-000000000000}", "1", "1")
kontrol("cli: DUR açıkken girdi komutu → 13 (hiçbir şey açılmadan)", kod == 13 and "DUR" in out, f"{kod} {out}")
kod, out = deskhand("durum")
kontrol("cli: durum DUR'u gösterir", "DUR: AÇIK" in out)
deskhand("devam")
kontrol("cli: devam → DUR kalktı", not os.path.exists(hata.dur_dosyasi()))
kod, out = deskhand("bas", "{00000000-0000-0000-0000-000000000000}", "w", "99")
kontrol("cli: yok pencere → 8 (girdi açılmadan)", kod == 8, f"{kod} {out}")

print(f"\n{gecen}/{toplam} mantık testi geçti")
sys.exit(0 if gecen == toplam else 1)
