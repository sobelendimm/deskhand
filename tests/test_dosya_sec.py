"""`choose-file` (dosya-sec): dosya seçici diyaloğunda doğrulanmış dosya seçimi (deskhand/dosya_sec.py).

A) Birim (sahte api/erisim): dosya yok / arka planda görünmeyen klasör → Dur 1 ve HİÇBİR girdi yok; konum girdisi
   odağa gelmezse Dur 6 ve yol YAZILMAZ; geri okunan değer yolla aynı değilse Dur 8 ve Enter'a BASILMAZ; diyalog
   kapanmazsa Dur 8; mutlu yol sırası (ctrl+l → yol → Return).
B) Uçtan uca: GÖRÜNMEZ masaüstünde (yalıtılmış kwin/xvfb) geçici profilli gerçek Firefox, yerel 127.0.0.1 sunucusundaki
   `<input type=file>` sayfası; GTK dosya seçici açılır, `choose-file` dosyayı seçer, sayfanın change olayı başlığa
   dosya adını yazar. Kullanıcının ekranına girdi gitmez; Firefox yoksa B atlanır.

Çalıştır:  python3 tests/test_dosya_sec.py"""
import os
import shutil
import sys
import tempfile
import time

import _yalitim  # noqa: F401

sys.path.insert(0, os.path.join(_yalitim.KOK, "tests", "yardimci"))

from deskhand import api, dosya_sec as DS, erisim  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def dur_kodu(f, *a, **k):
    try:
        f(*a, **k)
    except Dur as e:
        return e.kod, e.mesaj
    return None, ""


# ======================================================================= A) birim
pay = _yalitim.PAYLASIM
dosya = os.path.join(pay, "yukle-ornek.txt")
with open(dosya, "w") as f:
    f.write("deskhand\n")
tmp_dosya = tempfile.NamedTemporaryFile(prefix="deskhand-dosya-", delete=False)
tmp_dosya.close()


class SahteAu:
    ad = "sanal"


olaylar = []
durum = {"odak": [], "pencere_acik": True, "okunan": None}
eski = (api.arka, api.tus, api.yaz, api.pencereler, erisim.odakli_metin, DS.ODAK_BEKLE_SN, DS.KAPANIS_BEKLE_SN)


def s_tus(k, komb, baslik=None, onayli=False):
    olaylar.append(("tus", komb))
    if komb == "Return":
        durum["pencere_acik"] = False


def s_yaz(k, metin, baslik=None, gizli=False, onayli=False):
    olaylar.append(("yaz", metin))
    durum["okunan"] = metin if durum.get("okunan_ayni", True) else metin + ".bak"


def s_odak(k):
    if not durum["odak_var"]:
        return None
    return {"rol": "text", "ad": "", "metin": durum["okunan"] if durum["okunan"] is not None else ""}


api.arka, api.tus, api.yaz = (lambda: SahteAu()), s_tus, s_yaz
api.pencereler = lambda desen=None: [{"id": "arka:0x1"}] if durum["pencere_acik"] else []
erisim.odakli_metin = s_odak
DS.ODAK_BEKLE_SN = 0.2
DS.KAPANIS_BEKLE_SN = 0.3
try:
    def sifirla(**k):
        olaylar.clear()
        durum.update({"pencere_acik": True, "okunan": None, "odak_var": True, "okunan_ayni": True}, **k)

    sifirla()
    kod, m = dur_kodu(DS.dosya_sec, "arka:0x1", os.path.join(pay, "yok.txt"))
    kontrol("dosya yok → Dur 1, hiçbir girdi yok", kod == 1 and not olaylar, m)
    kod, m = dur_kodu(DS.dosya_sec, "arka:0x1", tmp_dosya.name)
    kontrol("arka planda /tmp dosyası → Dur 1 + 'XDG klasörüne kopyalayın' iletisi, girdi yok",
            kod == 1 and "İndirilenler" in m and "XDG" in m and not olaylar, m)
    kontrol("arka_planda_gorunur: XDG/paylaşım içi evet, dışı hayır",
            DS.arka_planda_gorunur(dosya) and not DS.arka_planda_gorunur(tmp_dosya.name) and
            DS.arka_planda_gorunur("/home/u/İndirilenler/a.pdf", ["/home/u/İndirilenler"]) and
            not DS.arka_planda_gorunur("/home/u/İndirilenler2/a.pdf", ["/home/u/İndirilenler"]))
    kod, m = dur_kodu(DS.dosya_sec, "EKRAN", dosya)
    kontrol("tüm ekran kimliği → Dur 1", kod == 1 and not olaylar, m)

    sifirla(odak_var=False)
    kod, m = dur_kodu(DS.dosya_sec, "arka:0x1", dosya)
    kontrol("konum girdisi odağa gelmedi → Dur 6, ctrl+l yeniden denendi, yol YAZILMADI, Enter yok",
            kod == 6 and olaylar == [("tus", "ctrl+l")] * DS.DENEME, f"{kod} {olaylar}")

    sifirla(okunan_ayni=False)
    kod, m = dur_kodu(DS.dosya_sec, "arka:0x1", dosya)
    kontrol("geri okunan değer farklı (otomatik tamamlama) → Dur 8, Enter'a BASILMADI",
            kod == 8 and ("tus", "Return") not in olaylar and ("yaz", dosya) in olaylar, f"{kod} {olaylar}")

    sifirla()
    durum["okunan"] = "/eski/metin"
    r = DS.dosya_sec("arka:0x1", dosya)
    kontrol("mutlu yol: ctrl+l → (dolu girdi) ctrl+a → yol → Return; diyalog kapandı",
            r == dosya and olaylar == [("tus", "ctrl+l"), ("tus", "ctrl+a"), ("yaz", dosya), ("tus", "Return")],
            str(olaylar))

    sifirla()
    _eski_tus = api.tus
    api.tus = lambda k, komb, baslik=None, onayli=False: olaylar.append(("tus", komb))  # Return diyaloğu kapatmaz
    kod, m = dur_kodu(DS.dosya_sec, "arka:0x1", dosya)
    api.tus = _eski_tus
    kontrol("Enter sonrası diyalog kapanmadı → Dur 8 (başarı denmez)", kod == 8, m)
finally:
    (api.arka, api.tus, api.yaz, api.pencereler, erisim.odakli_metin, DS.ODAK_BEKLE_SN, DS.KAPANIS_BEKLE_SN) = eski
    os.unlink(tmp_dosya.name)

from deskhand import cli  # noqa: E402
from deskhand.komutlar import EN_TR  # noqa: E402

kontrol("CLI: choose-file / dosya-sec kayıtlı", EN_TR.get("choose-file") == "dosya-sec" and
        "choose-file" in cli.komut_listesi())


# ======================================================================= B) uçtan uca (gerçek Firefox + GTK seçici)
def uctan_uca():
    if not (shutil.which("firefox") and (shutil.which("kwin_wayland") or shutil.which("Xvfb"))):
        print("ATLANDI (B): firefox ya da kwin_wayland/Xvfb yok")
        return
    import web_tarayici as wt

    from deskhand import masaustu
    from deskhand.arka_uc import sec
    os.environ["DESKHAND_HEDEF"] = "arka"
    bekci = wt.ProfilBekcisi()
    masaustu.masaustu_baslat()
    au = sec(arka_bayragi=True)
    srv = wt.Sunucu()
    ff = None
    try:
        ff = wt.Firefox(au, pay, srv.url("dosya.html"))
        k = ff.k
        son = time.monotonic() + 20
        while time.monotonic() < son and "Dosya Testi" not in ff.baslik():
            time.sleep(0.1)
        kontrol("firefox: test sayfası yüklendi", "Dosya Testi" in ff.baslik(), ff.baslik())
        time.sleep(1.0)
        once = {w for w, _b, _g in au.pencereler(None)}
        t = wt.Tiklayici(au, k)
        t.tikla(400, 150, sure=0.5)  # <input type=file> (üstte 300 px yüksek): dosya seçiciyi açar
        t.kapat()
        dk = None
        son = time.monotonic() + 20
        while time.monotonic() < son and dk is None:
            for w, b, _g in au.pencereler(None):
                if w not in once and w != k and ff.p.pid in wt.ata_pidler(au.pid(w)):
                    dk = w
            time.sleep(0.2)
        if not kontrol("GTK dosya seçici penceresi açıldı", dk is not None):
            return
        time.sleep(1.0)  # seçici ilk klasörünü yüklesin (yazarak arama tuzağı tam bu anda)
        t0 = time.monotonic()
        r = DS.dosya_sec(dk, dosya)
        sure = time.monotonic() - t0
        kontrol(f"choose-file: dosya seçildi, diyalog kapandı ({sure:.1f} sn)", r == dosya)
        son = time.monotonic() + 10
        while time.monotonic() < son and not ff.baslik().startswith("SECILDI"):
            time.sleep(0.1)
        kontrol("sayfa DOĞRU dosyayı aldı (change olayı: dosya adı)",
                ff.baslik().startswith("SECILDI yukle-ornek.txt"), ff.baslik())
        kontrol("kullanıcının Firefox profil kökü değişmedi", not bekci.fark(), str(bekci.fark()))
    finally:
        if ff is not None:
            ff.kapat()
        srv.kapat()
        masaustu.masaustu_durdur()


try:
    uctan_uca()
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    kontrol("uçtan uca bölüm hatasız", False, repr(e))

print(f"\n{gecen}/{toplam} test geçti")
sys.exit(0 if gecen == toplam else 1)
