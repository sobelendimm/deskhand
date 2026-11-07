"""Tüm dosya yolları. Her biri ortam değişkeniyle değiştirilebilir (testler geçici klasör verir):

  DESKHAND_CONFIG_DIR   ~/.config/deskhand          yasak-pencereler.txt
  DESKHAND_STATE_DIR    ~/.local/state/deskhand     girdi günlüğü (7 gün)
  DESKHAND_CACHE_DIR    ~/.cache/deskhand           ekran görüntüleri, OCR önbelleği (5 gün)
  DESKHAND_DATA_DIR     ~/.local/share/deskhand     simgeler/, akislar/, etkinlik/
  DESKHAND_RUNTIME_DIR  $XDG_RUNTIME_DIR/deskhand   DUR anahtarı (hata.calisma_dizini)

GEÇİŞ: eski `ekran` yolları (~/.config/ekran, ~/.local/share/ekran/simgeler|akislar, ~/.local/state/ekran)
varsa ve yenisi yoksa ilk açılışta KOPYALANIR (taşınmaz: eski `ekran` aracı çalışmaya devam eder).
Ortam değişkeniyle yönlendirilmiş bir yola geçiş yapılmaz (testler gerçek dosyalara dokunmasın).

Değerler her çağrıda ortamdan okunur (içe aktarma anında sabitlenmez).
"""
from __future__ import annotations

import os
import shutil

from .hata import calisma_dizini


def _yol(degisken: str, varsayilan: str) -> str:
    return os.environ.get(degisken) or os.path.expanduser(varsayilan)


def config_dir() -> str:
    return _yol("DESKHAND_CONFIG_DIR", "~/.config/deskhand")


def state_dir() -> str:
    return _yol("DESKHAND_STATE_DIR", "~/.local/state/deskhand")


def cache_dir() -> str:
    return _yol("DESKHAND_CACHE_DIR", "~/.cache/deskhand")


def data_dir() -> str:
    return _yol("DESKHAND_DATA_DIR", "~/.local/share/deskhand")


def runtime_dir() -> str:
    return calisma_dizini()


# ---------------------------------------------------------------- tek tek dosyalar

def cikti() -> str:
    """Ekran görüntüleri ve geçici çıktılar (5 gün sonra silinir)."""
    return cache_dir()


def ocr_onbellek() -> str:
    return os.path.join(cache_dir(), "ocr")


def son_foto() -> str:
    return os.path.join(cache_dir(), "son-foto.json")


def gunluk_dizin() -> str:
    return state_dir()


def yasak_dosya() -> str:
    return os.path.join(config_dir(), "yasak-pencereler.txt")


def simge_dizin() -> str:
    return os.path.join(data_dir(), "simgeler")


def akis_dizin() -> str:
    return os.path.join(data_dir(), "akislar")


PAKET_DIZIN = os.path.dirname(os.path.abspath(__file__))
ETKINLIK_AD = "deskhand-etkinlik"
ESKI_ETKINLIK = "~/.local/share/ekran/etkinlik/ekran-etkinlik"


def etkinlik_bin() -> str:
    """Wayland etkinlik yardımcısı (C). Sıra: $DESKHAND_ETKINLIK_BIN → DATA_DIR/etkinlik/deskhand-etkinlik →
    paket içinde derlenmiş (deskhand/yardimci/deskhand-etkinlik, `make -C deskhand/yardimci`) → eski ekran yolu.
    Hiçbiri yoksa eski yol döner (başlatılamazsa Etkinlik yalnız fareye düşer, bir kez uyarır)."""
    adaylar = [os.environ.get("DESKHAND_ETKINLIK_BIN") or "",
               os.path.join(data_dir(), "etkinlik", ETKINLIK_AD),
               os.path.join(PAKET_DIZIN, "yardimci", ETKINLIK_AD)]
    for a in adaylar:
        if a and os.path.isfile(a) and os.access(a, os.X_OK):
            return a
    return os.path.expanduser(ESKI_ETKINLIK)


GORUNTU_AD = "deskhand-goruntu"


def goruntu_bin() -> str | None:
    """KWin ScreenShot2 ekran görüntüsü yardımcısı (C): paket içinde derlenmiş deskhand/yardimci/deskhand-goruntu
    (install.sh derler; KWin < 6.8 yetkisi için ~/.local/share/applications/deskhand-goruntu.desktop bu yolu
    gösterir, bu yüzden yol sabittir). Çalıştırılabilir değilse None (iç kurtarma: spectacle)."""
    a = os.path.join(PAKET_DIZIN, "yardimci", GORUNTU_AD)
    return a if os.path.isfile(a) and os.access(a, os.X_OK) else None


# ---------------------------------------------------------------- geçiş (eski ekran → deskhand)

# (ortam değişkeni, eski yol, yeni yolu veren işlev)
_GECIS = (
    ("DESKHAND_CONFIG_DIR", "~/.config/ekran", config_dir),
    ("DESKHAND_DATA_DIR", "~/.local/share/ekran/simgeler", simge_dizin),
    ("DESKHAND_DATA_DIR", "~/.local/share/ekran/akislar", akis_dizin),
    ("DESKHAND_STATE_DIR", "~/.local/state/ekran", state_dir),
)


def gecis() -> list[tuple[str, str]]:
    """Eski ekran klasörlerini (varsa, yenisi yoksa) KOPYALA. → [(eski, yeni)] kopyalananlar. Hata sessiz:
    kopyalanamazsa araç boş yeni klasörle (ve varsayılan yasak listesiyle) çalışır."""
    yapilan = []
    for degisken, eski, yeni_f in _GECIS:
        if os.environ.get(degisken):
            continue
        eski, yeni = os.path.expanduser(eski), yeni_f()
        if not os.path.isdir(eski) or os.path.exists(yeni):
            continue
        try:
            os.makedirs(os.path.dirname(yeni), exist_ok=True)
            shutil.copytree(eski, yeni, symlinks=True)
            yapilan.append((eski, yeni))
        except OSError:
            pass
    return yapilan
