"""Entegrasyon testleri (ekransız): yerleşik panel yasağı, hassas eylemde panelden onay, bir eylem = bir onay,
kullanıcının DUR'u. Sahte arka uç kullanılır; gerçek ekrana/panele hiçbir şey gitmez."""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler)

import os
import sys
import threading
import time

from deskhand import arka_uc, guvenlik, onay, yollar
from deskhand.hata import Dur

GECEN, TOPLAM = 0, 0


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    if kosul:
        GECEN += 1
        print(f"GEÇTİ  {ad}")
    else:
        print(f"KALDI  {ad}  {ayrinti}")


class Sahte(arka_uc.ArkaUc):
    ad = "kde"
    pencereler_ = {"w1": ("Ödeme - Mağaza — Mozilla Firefox", "firefox"),
                   "w2": ("Deskhand", "deskhand"),
                   "w3": ("Deskhand — Onay", "python3"),
                   "w4": ("Belge — KWrite", "kwrite")}

    def pencere_coz(self, arg): return arg
    def pencereler(self, desen=None): return []
    def geometri(self, k): return (0, 0, 100, 100)
    def baslik(self, k): return self.pencereler_.get(k, ("", ""))[0]
    def sinif(self, k): return self.pencereler_.get(k, ("", ""))[1]
    def aktif(self): return "w4"
    def one_getir(self, k): pass
    def kapat(self, k): pass
    def fare(self): return (0, 0, "")
    def ekran_alani(self): return (0, 0, 100, 100)
    def goruntu(self): return None
    def girdi(self, etiket="", gizli=False, etk=None, denetle=None): return None
    def insan_var_mi(self): return False
    def baslat(self, argv, env=None, cikti=None): return None


arka_uc._ORNEKLER["kde"] = Sahte()

# ---------------------------------------------------------------- 1. yerleşik yasak
os.makedirs(os.path.dirname(yollar.yasak_dosya()), exist_ok=True)
with open(yollar.yasak_dosya(), "w") as f:
    f.write("# kullanıcı listeyi boşalttı\n")
kontrol("yasak: kullanıcı listesi boşken de panel yasağı var", set(guvenlik.YERLESIK_YASAK) <= set(guvenlik.yasak_desenler()))
for k, ad in (("w2", "panel penceresi (sınıf deskhand)"), ("w3", "onay diyaloğu (başlık)")):
    try:
        guvenlik.yasak_denetle(k)
        kontrol(f"yasak: {ad} → 10", False, "geçti")
    except Dur as d:
        kontrol(f"yasak: {ad} → 10", d.kod == 10, str(d.kod))
try:
    guvenlik.yasak_denetle("w4")
    kontrol("yasak: sıradan pencere serbest", True)
except Dur as d:
    kontrol("yasak: sıradan pencere serbest", False, d.mesaj)

try:
    guvenlik.baslatma_yasak_denetle("deskhand")
    kontrol("yasak: 'deskhand' başlatılamaz", False, "geçti")
except Dur as d:
    kontrol("yasak: 'deskhand' başlatılamaz", d.kod == 10)

# ---------------------------------------------------------------- 2. panel kapalı → red
guvenlik.eylem_basladi()
try:
    guvenlik.hassas_engel(False, "Satın al")
    kontrol("onay: panel kapalı → Dur 10", False, "geçti")
except Dur as d:
    kontrol("onay: panel kapalı → Dur 10", d.kod == 10 and onay.MESAJ_PANEL_YOK in d.mesaj, d.mesaj)
kontrol("onay: --onayli (sohbette onay) yine çalışır", guvenlik.hassas_engel(True, "Satın al") is not None)
kontrol("onay: hassas olmayan düğme sormaz", guvenlik.hassas_engel(False, "Kaydet") is None)

# ---------------------------------------------------------------- 3. sahte panel: izin / red
onay.panel_kaydet()
istekler = []
karar = {"deger": "izin"}
dur_isareti = threading.Event()


def panel_dongusu():
    gorulen = set()
    while not dur_isareti.is_set():
        for i in onay.bekleyenler():
            if i["id"] not in gorulen:
                gorulen.add(i["id"])
                istekler.append(i)
                onay.yanitla(i["id"], karar["deger"])
        time.sleep(0.05)


t = threading.Thread(target=panel_dongusu, daemon=True)
t.start()
try:
    guvenlik.eylem_basladi()
    r = guvenlik.hassas_engel(False, "Satın al", hedef="Mağaza")
    kontrol("onay: paneldeki insan izin verdi → devam", r is not None and len(istekler) == 1, f"{r} {len(istekler)}")
    kontrol("onay: istek eylem/hedef taşıyor", istekler and "Satın al" in istekler[0].get("eylem", "")
            and istekler[0].get("hedef") == "Mağaza", str(istekler[:1]))
    r2 = guvenlik.hassas_sayfa_engel("w1", False, "tıklama")
    kontrol("onay: aynı eylemde ikinci hassas denetim YENİDEN SORMAZ", r2 is True and len(istekler) == 1,
            f"{r2} {len(istekler)}")
    guvenlik.eylem_basladi()
    karar["deger"] = "red"
    try:
        guvenlik.hassas_sayfa_engel("w1", False, "tıklama")
        kontrol("onay: yeni eylem yeniden sorar; red → Dur 10", False, "geçti")
    except Dur as d:
        kontrol("onay: yeni eylem yeniden sorar; red → Dur 10", d.kod == 10 and len(istekler) == 2,
                f"{d.kod} {len(istekler)}")
    try:
        guvenlik.hassas_engel(False, "Ödemeyi onayla")
        kontrol("onay: reddedilen eylemden sonra da sorar (red taşınmaz)", False, "geçti")
    except Dur as d:
        kontrol("onay: reddedilen eylemden sonra da sorar (red taşınmaz)", d.kod == 10 and len(istekler) == 3,
                f"{len(istekler)}")
    # iş parçacığı yalıtımı: başka iş parçacığındaki onay bu eyleme sayılmaz
    karar["deger"] = "izin"
    guvenlik.eylem_basladi()
    sonuc = {}
    th = threading.Thread(target=lambda: sonuc.update(r=guvenlik.hassas_engel(False, "Satın al")))
    th.start(); th.join(15)
    karar["deger"] = "red"
    try:
        guvenlik.hassas_engel(False, "Satın al")
        kontrol("onay: başka iş parçacığının onayı bu eyleme geçmez", False, "geçti")
    except Dur:
        kontrol("onay: başka iş parçacığının onayı bu eyleme geçmez", sonuc.get("r") is not None)
finally:
    dur_isareti.set()
    t.join(2)
    onay.panel_sil()

# ---------------------------------------------------------------- 4. kullanıcının DUR'u
guvenlik.dur_ac("kullanici")
guvenlik.dur_ac("cli")
kontrol("DUR: ajan kullanıcının DUR'unu ezemez", guvenlik.dur_kaynagi() == "kullanici")
try:
    guvenlik.dur_kapat("cli")
    kontrol("DUR: ajan kullanıcının DUR'unu kaldıramaz (13)", False, "kaldırdı")
except Dur as d:
    kontrol("DUR: ajan kullanıcının DUR'unu kaldıramaz (13)", d.kod == 13)
kontrol("DUR: kullanıcı kaldırır", guvenlik.dur_kapat("kullanici") is True and guvenlik.dur_kaynagi() is None)
guvenlik.dur_ac("cli")
kontrol("DUR: ajanın kendi DUR'unu ajan kaldırır", guvenlik.dur_kapat("cli") is True)

# ---------------------------------------------------------------- 5. ekran koruması (oyun/film sırasında ön plan YOK)
from deskhand import mesgul  # noqa: E402
import json  # noqa: E402

pc = lambda sinif, fs=False, ad="": {"fs": fs, "sinif": sinif, "ad": ad, "baslik": "x", "g": [0, 0, 800, 600],
                                       "cikis": "", "cg": None, "kimlik": "{a}"}
kontrol("koruma: tam ekran → engel", (mesgul.ekran_korumasi(pc("firefox", fs=True), []) or "").startswith("tam ekran"))
kontrol("koruma: oyun penceresi → engel", (mesgul.ekran_korumasi(pc("steam_app_123456"), []) or "").startswith("oyunda"))
kontrol("koruma: etkin pencerede video çalıyor → engel",
        (mesgul.ekran_korumasi(pc("firefox"), [{"oynatici": "firefox", "durum": "Playing"}]) or "").startswith("video"))
kontrol("koruma: arka planda müzik (başka uygulama) → engel YOK",
        mesgul.ekran_korumasi(pc("org.kde.dolphin"), [{"oynatici": "spotify", "durum": "Playing"}]) is None)
kontrol("koruma: duraklatılmış video → engel YOK",
        mesgul.ekran_korumasi(pc("firefox"), [{"oynatici": "firefox", "durum": "Paused"}]) is None)
kontrol("koruma: sıradan pencere → engel YOK", mesgul.ekran_korumasi(pc("kwrite"), []) is None)
kab = dict(pc("plasmashell"), g=[0, 0, 2560, 1440], cg=[0, 0, 2560, 1440])
kontrol("koruma: masaüstü yüzeyi (plasmashell) ekranı kaplasa da oyun/film DEĞİL", mesgul.ekran_korumasi(kab, []) is None)
kontrol("koruma: ekranı kaplayan sıradan pencere (kenarlıksız oyun) → engel",
        mesgul.ekran_korumasi(dict(pc("oyun"), g=[0, 0, 2560, 1440], cg=[0, 0, 2560, 1440]), []) is not None)
os.environ["DESKHAND_EKRANIMDA"] = "1"
kontrol("koruma: --ekranimda (kullanıcı açık izni) → serbest", mesgul.ekran_korumasi(pc("firefox", fs=True), []) is None)
del os.environ["DESKHAND_EKRANIMDA"]
os.makedirs(os.path.dirname(mesgul.son_karar_yolu()), exist_ok=True)
with open(mesgul.son_karar_yolu(), "w") as f:
    json.dump({"zaman": time.time(), "karar": "on", "soruldu": True}, f)
kontrol("koruma: kullanıcı bildirimde 'Ekranımda yap' dedi → 10 dk serbest",
        mesgul.ekran_korumasi(pc("firefox", fs=True), []) is None)
with open(mesgul.son_karar_yolu(), "w") as f:
    json.dump({"zaman": time.time(), "karar": "on", "soruldu": False}, f)
kontrol("koruma: sorulmadan verilen 'on' izin sayılmaz", mesgul.ekran_korumasi(pc("firefox", fs=True), []) is not None)
with open(mesgul.son_karar_yolu(), "w") as f:
    json.dump({"zaman": time.time() - 700, "karar": "on", "soruldu": True}, f)
kontrol("koruma: 10 dk'dan eski izin geçersiz", mesgul.ekran_korumasi(pc("firefox", fs=True), []) is not None)
os.remove(mesgul.son_karar_yolu())

# kde arka ucunun girdi/öne getirme/açma yollarına bağlı mı (gerçek kde nesnesi, korumayı sahteyle)
from deskhand.arka_uc import kde as kde_mod  # noqa: E402
from deskhand import hata as hata_mod  # noqa: E402
gercek = mesgul.ekran_korumasi
mesgul.ekran_korumasi = lambda *a, **k: "tam ekranda (test)"
try:
    au = kde_mod.KdeArkaUc()
    for ad, f in (("girdi", lambda: au.girdi("t")), ("uygulama açma", lambda: au.baslat(["/bin/true"]))):
        try:
            f()
            kontrol(f"koruma: kde {ad} → 15", False, "geçti")
        except hata_mod.Dur as d:
            kontrol(f"koruma: kde {ad} → 15", d.kod == 15, str(d.kod))
finally:
    mesgul.ekran_korumasi = gercek

# ---------------------------------------------------------------- 6. kendi ayrıştırıcısı olan komutlar: argümanlar aynen
from deskhand import cli as _cli  # noqa: E402
import deskhand.gui.__main__ as _gm  # noqa: E402
import deskhand.masaustu as _ms  # noqa: E402
alinan = {}
gercek_gm, gercek_ms = _gm.main, _ms.main
_gm.main = lambda argv: alinan.setdefault("panel", list(argv)) and 0
_ms.main = lambda argv: alinan.setdefault("masaustu", list(argv)) and 0
try:
    for argv in (["panel", "--tepsi"], ["desktop", "status", "--json"], ["masaustu", "durum"]):
        try:
            _cli.main(argv)
        except SystemExit:
            pass
finally:
    _gm.main, _ms.main = gercek_gm, gercek_ms
kontrol("cli: 'panel --tepsi' argümanı panele aynen gider (otomatik başlatma bunu kullanıyor)",
        alinan.get("panel") == ["--tepsi"], str(alinan))
kontrol("cli: 'desktop status --json' masaüstüne aynen gider", alinan.get("masaustu") == ["status", "--json"], str(alinan))

print(f"\n{GECEN}/{TOPLAM} entegrasyon testi geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
