"""DENETİM 3 (ekransız, sahte arka uç): YB1 gömülü uçbirim tanımada zamanlama açıkları.
 a) 2 sn önbellek: F4'ten hemen sonra (kabuk henüz doğmadan) hesaplanan "uçbirim değil" sonucu, kabuk doğduktan sonra
    da 2 sn boyunca kullanılır → uçbirim komut denetimi ve Enter kapısı uygulanmaz.
 b) tek press_key çağrısı "f4 s u d o … enter": kapı tuş dizisi GÖNDERİLMEDEN önce bakar; o an kabuk yok → kapı yok.
Gerçek ekrana/sürece dokunmaz."""
import _yalitim  # noqa: F401

from deskhand import guvenlik, kendi, ucbirim
from deskhand.hata import Dur

KABUK = {"var": False}


class AU:
    ad = "kde"

    def sinif(self, k):
        return "org.kde.dolphin"

    def baslik(self, k):
        return "Ev — Dolphin"

    def pid(self, k):
        return "4242"

    def aktif(self):
        return "{d}"


guvenlik.sec = ucbirim.sec = lambda: AU()
kendi.kabuk_torunlari = lambda pid, proc=None, tablo=None: [5151] if KABUK["var"] else []
kendi.on_plan_surecleri = lambda pid, proc=None: ["bash"] if KABUK["var"] else None
ucbirim.satir_oku = lambda k: ["~ $ sudo reboot"]


def dene(f, *a):
    try:
        return f(*a)
    except Dur as e:
        return f"Dur {e.kod}"


guvenlik._UCBIRIM_ONBELLEK.clear()
ilk = guvenlik.ucbirim_penceresi_mi("{d}")      # F4 basıldı (tampon_isle → hesap): kabuk henüz yok
KABUK["var"] = True                               # ~100 ms sonra gömülü uçbirimin kabuğu doğdu
ikinci = guvenlik.ucbirim_penceresi_mi("{d}")    # 2 sn içinde: önbellek
komut = dene(guvenlik.ucbirim_komut_engel, "{d}", False, "sudo reboot")
enter = dene(ucbirim.enter_kapisi, "{d}", False)
print(f"a) önbellek: ilk={ilk} kabuk doğduktan sonra={ikinci} | uçbirim komut denetimi={komut} | Enter kapısı={enter}"
      f"  → {'AÇIK' if komut is False and enter is False else 'sağlam'}")

guvenlik._UCBIRIM_ONBELLEK.clear()
KABUK["var"] = False
r = dene(ucbirim.tus_dizisi_kapisi, "{d}", False, "f4 s u d o space r e b o o t enter")
print(f"b) tek çağrı 'f4 … enter' (kapı tuşlar gönderilmeden bakar, kabuk yok): {r} → {'AÇIK' if r is False else 'sağlam'}")
guvenlik._UCBIRIM_ONBELLEK.clear()
KABUK["var"] = True
r2 = dene(ucbirim.tus_dizisi_kapisi, "{d}", False, "s u d o space r e b o o t enter")
print(f"   kontrol: kabuk varken aynı dizi: {r2}")
