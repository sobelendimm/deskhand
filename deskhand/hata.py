"""Ortak durma istisnası ve çıkış kodları (docs/ARCHITECTURE.md §5)."""
from __future__ import annotations

import os

from .i18n import _

DISARIDA = 2
AKTIF_DEGIL = 3
BASLIK_SINIF = 4
BELIRSIZ = 5
BULUNAMADI = 6
ZAMAN_ASIMI = 7
PENCERE_YOK = 8
ARAC_EKSIK = 9
YASAK_HASSAS = 10
AKIS_HATA = 11
INSAN = 12
KULLANICI_DUR = 13
SANAL_KAPALI = 14
KULLANICI_MESGUL = 15  # kullanıcı oyunda / film izliyor: ekranına müdahale yok
OTURUM_POLITIKASI = 16  # uygulama arka planda açılamaz (kullanıcının ekranında açık / yalnız ön plan)
GERCEK_EKRAN_KAPALI = 17  # bu süreçte kullanıcının GERÇEK ekranı kilitli (DESKHAND_GERCEK_EKRAN): görünmez masaüstü kullan


class Dur(Exception):
    """kod: çıkış kodu; mesaj: kullanıcıya görünen (çevrilmiş) metin; tur: makinece denetlenen ayrıntı
    (ör. "hassas": hassas düğme/sayfa engeli; mesaj çevrilebildiği için mesaja bakılmaz)."""

    def __init__(self, kod, mesaj, tur=None):
        super().__init__(mesaj)
        self.kod, self.mesaj, self.tur = kod, mesaj, tur


# ---------------------------------------------------------------- gerçek ekran kilidi (yapısal, fail-closed)
# Ölçüm/test betikleri hedef vermeyi unutunca çağrı varsayılan `kde` arka ucuna, yani kullanıcının GERÇEK masaüstüne
# gider (dotool girdisi, pencere etkinleştirme, uygulama açma, pano, bildirim). DESKHAND_GERCEK_EKRAN bunu EN ALT
# katmanda keser: gerçek oturuma dokunan her yol, gerçek aracı çalıştırmadan HEMEN önce gercek_ekran_denetle()'yi çağırır.
#   (ayarsız) / acik  → davranış değişmez
#   salt-okuma        → yan etkiler reddedilir; ekran görüntüsü / pano OKUMA serbest
#   kapali            → yan etkiler VE kullanıcının ekran/pano içeriğini okuyan yollar reddedilir (tanınmayan her değer
#                       de "kapali" sayılır: yazım hatası kilidi açmasın)
# Pencere listesi/başlıkları/geometri, kilit/boşta durumu ve AT-SPI okuma kapatılmaz (içerik taşımaz ya da yan
# etkisizdir). tests/_yalitim.py bunu "kapali" yapar; tests/ekranli/ (bilerek gerçek ekran) kaldırır.
GERCEK_EKRAN_DEGISKENI = "DESKHAND_GERCEK_EKRAN"


def gercek_ekran_kipi() -> str:
    """"acik" | "salt-okuma" | "kapali" (ortam değişkeninden; tanınmayan değer = "kapali")."""
    if GERCEK_EKRAN_DEGISKENI not in os.environ:
        return "acik"
    d = os.environ[GERCEK_EKRAN_DEGISKENI].strip().lower()
    if d == "acik":  # ayarlı ama boş (VAR=$AYARSIZ) ya da tanınmayan değer → kapali
        return "acik"
    return "salt-okuma" if d == "salt-okuma" else "kapali"


def gercek_ekran_denetle(ne: str, okuma: bool = False) -> None:
    """Kullanıcının GERÇEK oturumuna dokunan bir aracı çalıştırmadan HEMEN önce çağrılır; kilit kapalıysa Dur(17).
    okuma=True: yan etkisiz ama kullanıcının ekran/pano İÇERİĞİNİ okuyan yol (ekran görüntüsü, pano) — yalnız
    "kapali"da reddedilir ("salt-okuma" serbest bırakır). ~1 µs."""
    kip = gercek_ekran_kipi()
    if kip == "acik" or (okuma and kip == "salt-okuma"):
        return
    raise Dur(GERCEK_EKRAN_KAPALI,
              _("gerçek ekran bu süreçte kapalı (DESKHAND_GERCEK_EKRAN={deger}): hedefi görünmez masaüstü yap ({ne})"
                ).format(deger=os.environ.get(GERCEK_EKRAN_DEGISKENI, "").strip() or "kapali", ne=ne),
              tur="gercek-ekran-kapali")


def calisma_dizini() -> str:
    """DESKHAND_RUNTIME_DIR ya da $XDG_RUNTIME_DIR/deskhand (DUR anahtarı, sanal masaüstü durumu)."""
    d = os.environ.get("DESKHAND_RUNTIME_DIR")
    if not d:
        d = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "deskhand")
    if not os.path.isdir(d):
        # Dizini HER ZAMAN 0700 ile kendimiz kurarız: yoksa bir alt yolun os.makedirs'i onu varsayılan izinle (0755)
        # ara dizin olarak yaratır ve arka_ortak.runtime_denetle "gevşek izinli" diye her işi durdurur (yeniden
        # başlatmadan sonra /run/user boşken ilk çağrıda; süreç ömründe silinirse de). Var olan dizine dokunulmaz
        # (izin/symlink denetimi runtime_denetle'de). Maliyet: tek stat.
        try:
            os.mkdir(d, 0o700)
        except OSError:
            pass
    return d


def dur_dosyasi() -> str:
    return os.path.join(calisma_dizini(), "dur")


def gozetimsiz() -> bool:
    """Gözetimsiz kip (DESKHAND_GOZETIMSIZ=1 ya da --unattended/--gozetimsiz): başında insan yok (zamanlanmış akış);
    onay gerektiren her eylem panel diyaloğu açılmadan reddedilir (onay.iste_sonuc: tek nokta)."""
    return os.environ.get("DESKHAND_GOZETIMSIZ", "").strip().lower() in ("1", "true", "yes", "evet", "on")


def dur_denetle() -> None:
    """DUR anahtarı açıksa Dur(13). Her girdi satırından önce çağrılır (iki arka uçta da). ~2 µs."""
    if os.path.exists(dur_dosyasi()):
        raise Dur(KULLANICI_DUR, _("kullanıcı DUR dedi (deskhand devam ile kaldırılır); girdi gönderilmedi"))
