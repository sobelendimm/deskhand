"""Arka uç (backend) arayüzü: pencere bulma, görüntü alma ve girdi gönderme burada soyutlanır.

Üst katman (guvenlik, eylem, ocr, akis...) yalnız bu arayüzü kullanır. Arka uçlar:
  kde   — kullanıcının gerçek KDE Plasma (Wayland) masaüstü: kdotool + dotool + spectacle
  sanal — görünmez ikinci masaüstü; iki türü var (dışarıdan aynı: ad "sanal", "arka:" önekli kimlikler):
          kwin.py  yalıtık KWin oturumu (kdotool + deskhand-eis + deskhand-goruntu, özel veri yolu) — koşullar
                   uygunsa varsayılan; sanal.py  Xvfb + openbox (python-xlib: XTEST girdi, XGetImage görüntü)
Ayrıntılı sözleşme: docs/ARCHITECTURE.md §2.
"""
from __future__ import annotations

import os
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager

from .. import hata
from ..hata import ARAC_EKSIK, Dur
from ..i18n import _

EKRAN = "EKRAN"  # masaüstü kipi: tüm ekran
ARKA_ONEK = "arka:"  # sanal arka ucun pencere kimlikleri her zaman bu önekle başlar


class ArkaUc(ABC):
    ad: str = ""

    # -------- pencere
    @abstractmethod
    def pencere_coz(self, arg: str) -> str: ...

    @abstractmethod
    def pencereler(self, desen: str | None = None) -> list[tuple[str, str, tuple[int, int, int, int]]]: ...

    @abstractmethod
    def geometri(self, k: str) -> tuple[int, int, int, int]: ...

    @abstractmethod
    def baslik(self, k: str) -> str: ...

    @abstractmethod
    def sinif(self, k: str) -> str: ...

    @abstractmethod
    def aktif(self) -> str: ...

    @abstractmethod
    def one_getir(self, k: str) -> None: ...

    @abstractmethod
    def kapat(self, k: str) -> None: ...

    # -------- fare / ekran
    @abstractmethod
    def fare(self) -> tuple[int | None, int | None, str]: ...

    def baslik_ve_fare(self, k: str):
        return self.baslik(k), self.fare()

    @abstractmethod
    def ekran_alani(self) -> tuple[int, int, int, int]: ...

    def masaustu_olcegi(self) -> int:
        """Masaüstü ölçeği (HiDPI): KWin arka plan masaüstünde kayıttaki `olcek` (1/2); diğerlerinde 1."""
        return 1

    @abstractmethod
    def goruntu(self):
        """Tüm ekranın görüntüsü: PIL.Image (RGB), ekran pikseli."""

    # -------- girdi
    @abstractmethod
    def girdi(self, etiket: str = "", gizli: bool = False, etk=None, denetle=None):
        """Girdi nesnesi (docs/ARCHITECTURE.md §2): gonder/zorla/ham/izle/izle_bitir/etk_denetle/insan_kontrol/kapat.
        Girdi dili dotool satır dilidir; her arka uç aynı satırları anlar.
        denetle(k, desen): üst katmanın güvenlik denetimi (guvenlik.denetle'nin bu arka uca bağlanmış hâli);
        gonder() her satırdan HEMEN önce önce hata.dur_denetle() sonra denetle(k, desen) çağırır (Dur fırlatır).
        zorla() (bırakma) hiçbir denetim yapmaz."""

    @abstractmethod
    def insan_var_mi(self) -> bool: ...

    # -------- uygulama
    @abstractmethod
    def baslat(self, argv: list[str], env: dict | None = None):
        """Uygulamayı BU arka ucun oturumunda başlatır → subprocess.Popen."""

    def atspi_adresi(self) -> str | None:
        return None

    def oturum_veri_yolu(self) -> str | None:
        """org.a11y.Bus'ın yaşadığı OTURUM veri yolunun adresi (sanal: özel veri yolu); None = kullanıcının oturumu."""
        return None

    def ekran_korumasi(self, ne: str) -> None:
        """Kullanıcının ekranına müdahaleden önce koruma (kde: oyun/film → Dur 15, karar bildirimi → 12). Girdi
        göndermeyen ama kullanıcının uygulamasını etkileyen yollar (erişilebilirlik eylemi) çağırır; varsayılan: yok."""

    # -------- CHANGE 1 (Faz 1): isteğe bağlı yöntemler. Üst katman bunları yedekli çağırır; arka uç uygularsa
    # davranış zenginleşir. Varsayılanlar güvenli tarafta.
    def kimlikler(self) -> list[str]:
        """Ucuz pencere kimliği listesi (ac'in yeni pencere döngüsü)."""
        return [k for k, _, _ in self.pencereler()]

    def klavye_duzeni(self) -> tuple[str, str]:
        """(düzen, varyant), ör. ("tr", "")."""
        return ("us", "")

    def yazilabilir_mi(self, c: str) -> bool:
        """Bu karakter doğrudan yazılabilir mi (değilse üst katman yedeğe çevirir: — → -)."""
        return True

    def gecerli_tuslar(self) -> set[str] | None:
        """Geçerli tuş adları (dotool adları); None = doğrulama yok."""
        return None

    def pid(self, k: str) -> int | None:
        """Pencerenin süreç kimliği (erişilebilirlik ağacı eşlemesi)."""
        return None

    def etkinlestir(self, k: str) -> None:
        """Doğrulamasız öne getirme (okuma bitince önceki pencereyi geri vermek için)."""
        try:
            self.one_getir(k)
        except Exception:
            pass

    def etkinlik(self):
        """İnsan etkinliği izleyicisi (akis için) ya da None."""
        return None

    # -------- Faz 9e: pencere yönetimi (isteğe bağlı; varsayılan = desteklenmiyor → Dur 9). Koordinatlar EKRAN
    # pikseli; sınır denetimi (kod 2), yasak (10), DUR (13) üst katmanda (eylem.pencere_yonet). Dönüş: None.
    def _pencere_islemi_yok(self, ne: str):
        raise hata.Dur(hata.ARAC_EKSIK, _("'{arka_uc}' arka ucu pencere işlemini desteklemiyor: {ne}").format(
            arka_uc=self.ad, ne=ne))

    def tasi(self, k: str, x: int, y: int) -> None:
        """Pencerenin sol üst köşesini (x, y) ekran pikseline taşı (geometri() ile aynı başlangıç noktası)."""
        self._pencere_islemi_yok(_("taşıma"))

    def boyutlandir(self, k: str, g: int, y: int) -> None:
        """Pencere boyutunu g x y piksel yap (geometri() ile aynı ölçü: kde çerçeveli, sanal istemci alanı)."""
        self._pencere_islemi_yok(_("boyutlandırma"))

    def kucult(self, k: str) -> None:
        """Pencereyi görev çubuğuna küçült."""
        self._pencere_islemi_yok(_("küçültme"))

    def buyut(self, k: str) -> None:
        """Pencereyi çalışma alanını kaplayacak biçimde büyüt (tam ekran DEĞİL)."""
        self._pencere_islemi_yok(_("büyütme"))

    def geri_yukle(self, k: str) -> None:
        """Küçültülmüş ya da büyütülmüş pencereyi normal boyuta/konuma döndür."""
        self._pencere_islemi_yok(_("geri yükleme"))

    # -------- Faz 9a: pano (isteğe bağlı; varsayılan "desteklenmiyor"). Üst katman (eylem.yaz_ic, MCP/CLI pano)
    # yalnız bu yöntemleri kullanır; ham wl-copy/wl-paste/X seçimi YALNIZ arka uç içinde.
    def pano_oku(self) -> str | None:
        """Panonun METİN içeriği; boşsa ya da metin dışıysa None."""
        raise Dur(ARAC_EKSIK, _("bu arka uç panoyu desteklemiyor"))

    def pano_yaz(self, metin: str, hassas: bool = True) -> None:
        """Panoyu `metin` yapar ("" = panoyu temizle). hassas: pano yöneticisi geçmişine yazılmasın.
        Güvenlik denetimleri (DUR, ön plan koruması) burada yapılır."""
        raise Dur(ARAC_EKSIK, _("bu arka uç panoyu desteklemiyor"))

    def pano_yedekle(self):
        """Yapıştırarak yazmadan ÖNCE panonun geri yüklenebilir anlık görüntüsü (üst katman için opak nesne).
        Varsayılan: yalnız metin. Pano okunamıyorsa Dur(9) (üst katman harf harf yazmaya döner)."""
        return {"metin": self.pano_oku()}

    def pano_geri_yukle(self, yedek) -> str | None:
        """pano_yedekle() görüntüsünü geri yükle. Denetimsizdir (temizlik: DUR ya da kesintide de çalışmalı).
        → tam geri yüklenemediyse kullanıcıya gösterilecek uyarı metni, yoksa None."""
        self.pano_yaz((yedek or {}).get("metin") or "", hassas=True)
        return None


_YEREL = threading.local()  # iş parçacığına özgü hedef (MCP sunucusu: çağrı başına masaüstü; CLI kullanmaz)


@contextmanager
def hedef_sabit(ad: str):
    """Bu iş parçacığında sec() hep `ad` ("kde" | "sanal") arka ucunu seçsin (DESKHAND_HEDEF'ten önce gelir).
    Süreç içinde eşzamanlı çağrılar (MCP) ortam değişkenini paylaşmasın diye; çıkışta önceki değer geri gelir."""
    if ad not in ("kde", "sanal"):
        raise ValueError(f"bilinmeyen arka uç: {ad!r}")
    onceki = getattr(_YEREL, "hedef", None)
    _YEREL.hedef = ad
    try:
        yield
    finally:
        _YEREL.hedef = onceki


def hedef_ad(kimlik: str | None = None, arka_bayragi: bool = False) -> str:
    """Hangi arka uç? Öncelik: kimlik öneki > --arka bayrağı > hedef_sabit() > DESKHAND_HEDEF ortam değişkeni > 'on'."""
    if kimlik and kimlik.startswith(ARKA_ONEK):
        return "sanal"
    if arka_bayragi:
        return "sanal"
    yerel = getattr(_YEREL, "hedef", None)
    if yerel:
        return yerel
    h = os.environ.get("DESKHAND_HEDEF", "on").strip().lower()
    return "sanal" if h in {"arka", "sanal", "background"} else "kde"


_ORNEKLER: dict[str, ArkaUc] = {}
# (masaüstü adı, tür) → örnek (KWin örneği kalıcı EIS bağlantısını tutar: masaüstü BAŞINA ayrı örnek)
_TUR_ORNEKLERI: dict[tuple[str, str], ArkaUc] = {}


def arka_tur() -> str:
    """Arka plan masaüstünün türü: çalışan (ya da en son kaydı duran) masaüstünün durum kaydından ("kwin" | "xvfb").
    Kayıt yoksa "xvfb" (kapalı masaüstünde her iki arka uç da aynı Dur 14'ü verir). ~0,1 ms (yalnız JSON okuma)."""
    from .. import masaustu
    return masaustu.tur(masaustu.durum_oku())


def _yeni_sanal(tur: str) -> ArkaUc:
    if tur == "kwin":
        from .kwin import KwinArkaUc
        return KwinArkaUc()
    from .sanal import SanalArkaUc
    return SanalArkaUc()


def sec(kimlik: str | None = None, arka_bayragi: bool = False) -> ArkaUc:
    """Hedefin arka ucu. "sanal" hedefi (görünmez masaüstü) türüne göre: KWin oturumu → KwinArkaUc, Xvfb →
    SanalArkaUc. İkisinin de `ad`ı "sanal"dır (üst katman kuralları, kimlik öneki, çıkış kodları aynı)."""
    ad = hedef_ad(kimlik, arka_bayragi)
    if ad == "sanal":
        from .. import masalar
        masa = masalar.secili()
        tur = arka_tur()
        if masa != "":  # adlı masaüstü: önbellek (ad, tür) anahtarlı; _ORNEKLER["sanal"] varsayılanındır
            anahtar = (masa, tur)
            au = _TUR_ORNEKLERI.get(anahtar)
            if au is None:
                au = _yeni_sanal(tur)
                _TUR_ORNEKLERI[anahtar] = au
            return au
        au = _ORNEKLER.get("sanal")
        # _ORNEKLER["sanal"] = geçerli türün örneği (testlerin koyduğu `tur`suz sahte arka uç olduğu gibi kalır)
        if au is None or getattr(au, "tur", tur) != tur:
            au = _TUR_ORNEKLERI.get(("", tur))
            if au is None:
                au = _yeni_sanal(tur)
                _TUR_ORNEKLERI[("", tur)] = au
            _ORNEKLER["sanal"] = au
        return au
    if ad not in _ORNEKLER:
        from .kde import KdeArkaUc
        _ORNEKLER[ad] = KdeArkaUc()
    return _ORNEKLER[ad]
