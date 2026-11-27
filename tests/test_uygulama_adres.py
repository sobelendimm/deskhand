"""DH-TUR2 (5): SON-KAPI D-a/b/c (uygulama.py).
  D-a  _adres_norm: geçersiz port (host:abc, :99999) ValueError fırlatıyordu (adres yazılıp Return gönderildikten SONRA
       iz dökümü, pencere raporsuz) → karşılaştırma için güvenli değer.
  D-b  _adres_dogrula (→ (doğrulandı, kaynak, sayfa); ux tarafından): AT-SPI sayfa adresi okunup BAŞKA sunucu dese bile başlık alt dizgesi True yapıyordu (açık
       yönlendirme + sahte başlık; a.com ⊂ visa.com) → adres okunduysa yalnız ona bakılır; başlık yalnız adres
       okunamazken yedek ve sunucu SINIRIYLA karşılaştırılır.
  D-c  k_ac: aynı süreçte 2. pencere (IkinciPencere) için başlık/sınıf bekleme bütçesi _baslat'tan ÖNCE başlıyordu
       (ayni_surecte_ac kilit beklemesi bütçeyi yiyip açılmış + doğrulanmış pencereye Dur 7 veriyordu).
Çalıştır:  python3 tests/test_uygulama_adres.py"""
import _yalitim  # noqa: F401

import sys
import time
import types

from deskhand import uygulama, web  # noqa: E402

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


def dene(f):
    try:
        return f()
    except Exception as e:  # noqa: BLE001
        return f"HATA {type(e).__name__}"


print("== D-a _adres_norm")
for s in ("example.com:abc", "http://h:99999"):
    r = dene(lambda s=s: uygulama._adres_norm(s))
    kontrol(f"D-a: geçersiz port ({s}) → iz dökümü yok", isinstance(r, tuple), r)
kontrol("D-a: geçerli port korunur", uygulama._adres_norm("example.com:8080") == ("example.com", "https://example.com:8080"))

print("== D-b _adres_dogrula")
uygulama.ADRES_DOGRULA_SN = 0.3


class Au:
    def __init__(self, baslik):
        self.b = baslik

    def baslik(self, w):
        return self.b


eski_sayfa = web.sayfa_bilgisi
try:
    web.sayfa_bilgisi = lambda w: {"adres": "https://evil.example/login"}
    kontrol("D-b: AT-SPI başka sunucu + başlıkta hedef sunucu (açık yönlendirme) → doğrulanmadı",
            uygulama._adres_dogrula(Au("bank.com - giris"), "w", "https://bank.com")[0] is False)
    web.sayfa_bilgisi = lambda w: {"adres": "https://bank.com/hesap"}
    kontrol("D-b: AT-SPI aynı sunucu → doğrulandı (negatif örnek değişmez)",
            uygulama._adres_dogrula(Au("x"), "w", "https://bank.com")[0] is True)

    def okunamaz(w):
        raise RuntimeError("a11y yok")
    web.sayfa_bilgisi = okunamaz
    kontrol("D-b: adres okunamaz + başlıkta sunucu sınırlı geçiyor → doğrulandı (yedek)",
            uygulama._adres_dogrula(Au("Giriş — bank.com — Mozilla Firefox"), "w", "https://bank.com")[0] is True)
    kontrol("D-b: adres okunamaz + sunucu yalnız alt dizge (a.com ⊂ visa.com) → doğrulanmadı",
            uygulama._adres_dogrula(Au("visa.com - Mozilla Firefox"), "w", "https://a.com")[0] is False)
    kontrol("D-b: adres okunamaz + başlık bank.com.evil.net → doğrulanmadı",
            uygulama._adres_dogrula(Au("bank.com.evil.net"), "w", "https://bank.com")[0] is False)
    kontrol("D-b: adres okunamaz + ilgisiz başlık → doğrulanmadı",
            uygulama._adres_dogrula(Au("Yeni Sekme"), "w", "https://bank.com")[0] is False)
finally:
    web.sayfa_bilgisi = eski_sayfa

print("== D-c ikinci pencere bekleme bütçesi")
butce = []


class AuK:
    ad = "kde"

    def aktif(self):
        return "{a}"


def yavas_baslat(au, komut, fp, env, kopya, ev=()):
    time.sleep(1.2)  # ayni_surecte_ac kilit beklemesi + Ctrl+N + doğrulama (taklit)
    return uygulama.IkinciPencere(kimlik="{yeni}", tur="firefox")


def bekle(au, ip, uyar, sure):
    butce.append(sure)
    return ("Başlık", "firefox")


eski = (uygulama.sec, uygulama.tum_pencereler, uygulama.erisim_hazirla, uygulama._baslat, uygulama.ikinci_pencere_bekle,
        uygulama.uygulama_bul, uygulama.baslatma_yasak_denetle)
uygulama.sec = lambda *a, **k: AuK()
uygulama.tum_pencereler = lambda: set()
uygulama.erisim_hazirla = lambda komut, env: (komut, env)
uygulama._baslat = yavas_baslat
uygulama.ikinci_pencere_bekle = bekle
uygulama.uygulama_bul = lambda ad: {"ad": "Firefox", "ad_en": "Firefox", "exec": "firefox", "kimlik": "firefox",
                                    "yol": "/usr/share/applications/firefox.desktop"}
uygulama.baslatma_yasak_denetle = lambda *a, **k: None
try:
    a = types.SimpleNamespace(uygulama="firefox", komut_satiri=None, url=None, adres=None, sure=1.0, baslik="Başlık",
                              sinif=None, site=None, onayli=False)
    r = dene(lambda: uygulama.k_ac(a))
    kontrol("D-c: _baslat bütçeden uzun sürse de başlık beklemesine bütçe kalır (> 0,8 sn)",
            butce and butce[0] > 0.8, (r, butce))
finally:
    (uygulama.sec, uygulama.tum_pencereler, uygulama.erisim_hazirla, uygulama._baslat, uygulama.ikinci_pencere_bekle,
     uygulama.uygulama_bul, uygulama.baslatma_yasak_denetle) = eski

print(f"\n{GECEN}/{TOPLAM} geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
