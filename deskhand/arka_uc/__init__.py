"""Arka uç (backend) arayüzü: pencere bulma, görüntü alma ve girdi gönderme burada soyutlanır.

Üst katman (guvenlik, eylem, ocr, akis...) yalnız bu arayüzü kullanır. İki arka uç vardır:
  kde   — kullanıcının gerçek KDE Plasma (Wayland) masaüstü: kdotool + dotool + spectacle
  sanal — görünmez ikinci masaüstü (Xvfb + openbox): python-xlib (XTEST girdi, XGetImage görüntü)
Ayrıntılı sözleşme: docs/ARCHITECTURE.md §2.
"""
from __future__ import annotations

import os
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager

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


def sec(kimlik: str | None = None, arka_bayragi: bool = False) -> ArkaUc:
    ad = hedef_ad(kimlik, arka_bayragi)
    if ad not in _ORNEKLER:
        if ad == "sanal":
            from .sanal import SanalArkaUc
            _ORNEKLER[ad] = SanalArkaUc()
        else:
            from .kde import KdeArkaUc
            _ORNEKLER[ad] = KdeArkaUc()
    return _ORNEKLER[ad]
