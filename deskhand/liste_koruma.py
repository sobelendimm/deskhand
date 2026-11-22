"""Yasak listesi ve uygulama erişim seviyeleri: PANEL YETKİLİ KAYNAKTIR (docs/ARCHITECTURE.md §4 "Ayar dosyaları").

Tehdit: ajan kendi araçlarıyla (uçbirimde rm, dosya yöneticisinde silme, düzenleyicide boşaltma) yasak-pencereler.txt
ya da uygulama-seviyeleri.txt dosyasını silip/değiştirip kısıtları kaldırabilirdi (dosya yoksa = kısıt yok).

- Panel açılışta iki dosyayı okur ve BELLEKTE tutar (`Koruyucu`). Dosyayı yalnız panelin kendi Kaydet'i yazar
  (`kaydet`). Dosya dışarıdan değişir ya da silinirse panel kendi içeriğini KORUR, dosyayı geri yazar ve uyarır
  (`denetle`; panelde QFileSystemWatcher + yoklama).
- Panel her yazışında STATE_DIR/liste-<tur>.isaret {sha256, icerik, var} bırakır. Panel açılırken dosya işaretle
  uyuşmuyorsa (kapalıyken silinmiş/değiştirilmiş) işaretteki içerik geri yüklenir ve uyarılır.
- CLI ve MCP içeriği panelden onay kanalıyla alır (`liste yasak|seviye`; onay.py kanal doğrulaması aynen).
- Panel kapalıysa dosyadan okunur; işaret VAR ama dosya yok ya da içeriği işaretle uyuşmuyorsa → Dur 10 ("Deskhand
  ayar dosyası kayıp ya da panel dışında değişti; paneli açın"): hiçbir girdi gönderilmez. İşaret yoksa (ilk kurulum,
  panel hiç açılmadı) eski davranış: yasak dosyası yoksa varsayılanla oluşturulur, seviye dosyası yoksa kısıt yok.

Qt'siz (CLI/MCP hafif kalsın); panel tarafının Qt izleyicisi deskhand/gui/panel.py'de.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time

from . import yollar
from .hata import Dur
from .i18n import N_, _

TURLER = ("yasak", "seviye")
ONBELLEK_SN = 0.3  # istemci: panelden alınan listeyi bu kadar süre yeniden sormaz (pencere listesinde her pencere
#                   için denetim); panelin Kaydet'i en geç bu kadar sonra geçerli. Dosya yolu önbelleksiz.
MESAJ_KAYIP = N_("Deskhand ayar dosyası ({dosya}) kayıp ya da panel dışında değişti; güvenli tarafta hiçbir girdi "
                 "gönderilmez; Deskhand paneli açın (panel kendi kaydını geri yükler).")


def dosya(tur: str) -> str:
    return yollar.yasak_dosya() if tur == "yasak" else yollar.seviye_dosya()


def isaret_yolu(tur: str) -> str:
    return os.path.join(yollar.state_dir(), f"liste-{tur}.isaret")


def _ozet(metin: str | None) -> str:
    return "yok" if metin is None else hashlib.sha256(metin.encode("utf-8", "surrogateescape")).hexdigest()


def _oku(yol: str) -> str | None:
    try:
        with open(yol, encoding="utf-8", errors="surrogateescape") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except OSError:
        return None


def isaret_oku(tur: str) -> dict | None:
    try:
        with open(isaret_yolu(tur)) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("sha256"), str):
        return None
    return d


def _yaz_atomik(yol: str, metin: str) -> None:
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    gecici = f"{yol}.{os.getpid()}.{threading.get_ident()}"
    with open(gecici, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(metin)
    os.replace(gecici, yol)


def _isaret_yaz(tur: str, metin: str | None) -> None:
    _yaz_atomik(isaret_yolu(tur), json.dumps({"sha256": _ozet(metin), "icerik": metin, "var": metin is not None,
                                              "zaman": time.time()}, ensure_ascii=False))
    try:
        os.chmod(isaret_yolu(tur), 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------- panel tarafı

class Koruyucu:
    """Panel sürecindeki yetkili kopya. uyari(metin) her geri yüklemede çağrılır (panel: günlük + bildirim)."""

    def __init__(self, uyari=None):
        self.uyari = uyari or (lambda m: None)
        self._kilit = threading.Lock()
        self.bellek: dict[str, str | None] = {}
        for tur in TURLER:
            self._ac(tur)

    def _ac(self, tur: str) -> None:
        mevcut = _oku(dosya(tur))
        isaret = isaret_oku(tur)
        if isaret is not None and isaret["sha256"] != _ozet(mevcut):
            # panel kapalıyken silinmiş/değiştirilmiş: panelin son kaydı geri gelir
            icerik = isaret.get("icerik") if isaret.get("var", True) else None
            if icerik is not None and not isinstance(icerik, str):
                icerik = None
            self.bellek[tur] = icerik
            self._dosyaya(tur)
            self.uyari(_("{dosya} panel kapalıyken silinmiş ya da değiştirilmiş; panelin son kaydı geri yüklendi "
                         "(değişiklikleri Ayarlar'dan yapın).").format(dosya=dosya(tur)))
            return
        if mevcut is None and tur == "yasak":
            from .guvenlik import VARSAYILAN_YASAK
            mevcut = _(VARSAYILAN_YASAK)
            _yaz_atomik(dosya(tur), mevcut)
        self.bellek[tur] = mevcut
        _isaret_yaz(tur, mevcut)

    def _dosyaya(self, tur: str) -> None:
        icerik = self.bellek.get(tur)
        if icerik is None:
            try:
                os.remove(dosya(tur))
            except FileNotFoundError:
                pass
        else:
            _yaz_atomik(dosya(tur), icerik)
        _isaret_yaz(tur, icerik)

    def metin(self, tur: str) -> str | None:
        with self._kilit:
            return self.bellek.get(tur)

    def kaydet(self, tur: str, metin: str) -> None:
        """Panelin Kaydet'i: bellek + dosya + işaret (tek yetkili yazar)."""
        with self._kilit:
            self.bellek[tur] = metin
            self._dosyaya(tur)

    def denetle(self) -> list[str]:
        """Dosyalar bellekle aynı mı? Değilse (silindi/değişti) bellekteki içerik geri yazılır. → uyarı metinleri."""
        uyarilar = []
        with self._kilit:
            for tur in TURLER:
                if _oku(dosya(tur)) != self.bellek.get(tur):
                    self._dosyaya(tur)
                    uyarilar.append(_("{dosya} panel dışında silindi ya da değiştirildi; panelin kaydı korundu ve dosya "
                                      "geri yazıldı (değişiklikleri Ayarlar'dan yapın).").format(dosya=dosya(tur)))
        for u in uyarilar:
            self.uyari(u)
        return uyarilar


AKTIF: Koruyucu | None = None  # panel sürecinde etkin koruyucu (onay kanalı `liste` isteğini buradan yanıtlar)


def panel_baslat(uyari=None) -> Koruyucu:
    global AKTIF
    AKTIF = Koruyucu(uyari)
    from . import onay
    onay.liste_saglayici = AKTIF.metin
    return AKTIF


def panel_durdur() -> None:
    global AKTIF
    AKTIF = None
    from . import onay
    onay.liste_saglayici = None


def panel_kaydet(tur: str, metin: str) -> None:
    """gui/ayar.py Kaydet: panel koruyucusu varsa onun üzerinden (yoksa dosya + işaret)."""
    if AKTIF is not None:
        AKTIF.kaydet(tur, metin)
    else:
        _yaz_atomik(dosya(tur), metin)
        _isaret_yaz(tur, metin)


# ---------------------------------------------------------------- istemci tarafı (guvenlik)

_ONBELLEK: dict[str, tuple[float, str | None]] = {}
_ONBELLEK_KILIT = threading.Lock()


def metin(tur: str) -> str | None:
    """Geçerli liste metni: panel açıksa panelden (bellekteki yetkili kopya), kapalıysa dosyadan + işaret denetimi.
    → metin | None (seviye dosyası yok = kısıt yok). Kayıp/değişmiş işaretli dosyada Dur 10."""
    if AKTIF is not None:
        return AKTIF.metin(tur)
    simdi = time.monotonic()
    with _ONBELLEK_KILIT:
        o = _ONBELLEK.get(tur)
        if o is not None and simdi - o[0] < ONBELLEK_SN:
            return o[1]
    sonuc = _panelden(tur)
    if sonuc is _YOK:
        return _dosyadan(tur)  # dosya yolu önbelleksiz (~20 µs): elle/panelden yazılan değişiklik hemen geçerli
    with _ONBELLEK_KILIT:
        _ONBELLEK[tur] = (time.monotonic(), sonuc)
    return sonuc


def onbellek_sil() -> None:
    with _ONBELLEK_KILIT:
        _ONBELLEK.clear()


_YOK = object()


def _panelden(tur: str):
    """Panel açık ve kanalı doğrulanıyorsa panelin içeriği; değilse _YOK."""
    from . import onay
    try:
        return onay.liste_iste(tur)
    except Exception:  # noqa: BLE001 - panel yok / doğrulanamadı / eski panel: dosya yolu (işaret denetimli)
        return _YOK


def _dosyadan(tur: str) -> str | None:
    yol = dosya(tur)
    mevcut = _oku(yol)
    isaret = isaret_oku(tur)
    if isaret is not None and isaret["sha256"] != _ozet(mevcut):
        raise Dur(10, _(MESAJ_KAYIP).format(dosya=yol))
    if mevcut is None and tur == "yasak" and isaret is None:  # ilk kurulum: eski davranış
        from .guvenlik import VARSAYILAN_YASAK
        mevcut = _(VARSAYILAN_YASAK)
        try:
            _yaz_atomik(yol, mevcut)
        except OSError:
            pass
    return mevcut
