"""Chromium ailesi + Electron + Flatpak Electron oturum kopyası (docs/SESSIONS.md §2, §4).

İKİ YOL:
  (A) Yerel Chromium ailesi (chromium/vivaldi/chrome/brave) ve VS Code: çerez/parola şifresi anahtarlıkta (v11).
      Köprü (şifre deposu rölesi) BU SÜRÜMDE YOK ve yazılmayacak. Köprüsüz arka planda açmak kullanıcının gerçek
      `… Safe Storage` kaydını ezme riski taşır (§2.3) → bu uygulamalar arka planda AÇILMAZ (api kararı "on").
      Yine de kopya + argv üreticisi burada (test ve ileride köprü eklenirse hazır); argv oluşturmak başlatmaz.
  (B) Flatpak Electron, şifre deposu izni OLMAYAN (Discord, Spotify): köprü gerekmez. Kopya tmpfs'te tutulur ve
      SANDBOX İÇİNDE ortam değişkenleriyle verilir (flatpak --env XDG_CONFIG_HOME'u EZDİĞİ için --command=sh ile
      içeride export edilir — bu yöntem denenerek doğrulandı). Discord/Spotify kullanıcının örneğine devretmez
      (farklı kopya dizini → ayrı tek-örnek kilidi).
"""
from __future__ import annotations

import os
import shlex

from . import kopya as kopya_mod
from ..i18n import _
from .politika import Politika

# Kopyadan HARİÇ (önbellek/kilit/günlük): §2 listesi
_HARIC = {"Singleton", "SingletonLock", "SingletonSocket", "SingletonCookie", "Cache", "Code Cache",
          "GPUCache", "GPUPersistentCache", "DawnGraphiteCache", "DawnWebGPUCache", "DawnCache",
          "Crash Reports", "Crashpad", "Safe Browsing", "component_crx_cache", "extensions_crx_cache",
          "OptimizationHints", "OptimizationGuideModelsManifest", "WidevineCdm", "logs", "blob_storage",
          "Dictionaries", "discord_asset_cache", "Service Worker", "CacheStorage", "LOCK",
          "GraphiteDawnCache", "ShaderCache"}

# Flatpak Electron: kimlik → (userData alt dizini [XDG_CONFIG_HOME altında], sandbox içi komut)
_FLATPAK_ELECTRON = {
    "com.discordapp.Discord": ("discord", "com.discordapp.Discord"),
    "com.spotify.Client": ("spotify", "spotify"),
    "org.ferdium.Ferdium": ("Ferdium", "ferdium"),
}


# ------------------------------------------------------------------ (A) yerel Chromium ailesi

def anahtar_deposu(uygulama: str) -> str:
    """--password-store değeri (KDE6 → kwallet6). Bu sürümde köprü yok; yalnızca argv tamlığı için."""
    return "kwallet6"


def veri_dizini_kopyala(kaynak: str, hedef: str, profil: str = "Default") -> dict:
    """Chromium kullanıcı veri dizinini kopyala: Local State + <profil>/ (önbellek/kilit hariç). Kaynak yazılmaz.
    Döner: {kopyalanan}. Çerez/parola DEĞERİ okunmaz; yalnız dosyalar kopyalanır (v11 şifreli kalır)."""
    sayac = 0
    sayac += int(kopya_mod.dosya_kopyala(os.path.join(kaynak, "Local State"),
                                         os.path.join(hedef, "Local State")))
    kp = os.path.join(kaynak, profil)
    if os.path.isdir(kp):
        sayac += kopya_mod.dizin_kopyala(kp, os.path.join(hedef, profil), disla=_HARIC)
    return {"kopyalanan": sayac}


def chromium_argv(uygulama: str, hedef: str, ek=None) -> list[str]:
    """Yerel Chromium ailesi başlatma argümanları (köprü eklendiğinde kullanılmak üzere). Başlatmaz."""
    exe = {"chromium": "chromium", "vivaldi": "vivaldi", "chrome": "google-chrome-stable",
           "brave": "brave"}.get(uygulama, uygulama)
    return [exe, f"--user-data-dir={hedef}", f"--password-store={anahtar_deposu(uygulama)}",
            "--disable-sync", "--no-first-run", "--no-default-browser-check", *(ek or [])]


# ------------------------------------------------------------------ (B) Flatpak Electron (köprüsüz)

def flatpak_electron_hazirla(politika: Politika, uygulama: str, ek_argv=None) -> dict:
    """Flatpak Electron (Discord/Spotify) userData'sını tmpfs kopyaya al ve sandbox içi ortamla argv üret.
    Döner: {kopya_yolu, argv, env_ek, kopyalanan, durum}. Kaynak yazılmaz. Başlatmaz."""
    fk = politika.flatpak
    if not fk or fk not in _FLATPAK_ELECTRON:
        return {"durum": _("{uygulama}: Flatpak Electron eşlemesi yok").format(uygulama=uygulama), "kopya_yolu": None,
                "argv": []}
    alt, komut = _FLATPAK_ELECTRON[fk]
    kaynak = os.path.join(os.path.expanduser("~"), ".var", "app", fk, "config", alt)
    hedef = kopya_mod.yeni_kopya_dizini(uygulama)
    # Kopya iç düzeni: <hedef>/config/<alt>, <hedef>/cache, <hedef>/data (sandbox içinde XDG_* bunlara bakar)
    config_hedef = os.path.join(hedef, "config", alt)
    kopyalanan = 0
    if os.path.isdir(kaynak):
        kopyalanan = kopya_mod.dizin_kopyala(kaynak, config_hedef, disla=_HARIC)
    for d in ("cache", "data", "config"):
        os.makedirs(os.path.join(hedef, d), mode=0o700, exist_ok=True)
    argv = flatpak_argv(fk, komut, hedef, ek_argv)
    return {"kopya_yolu": hedef, "argv": argv, "env_ek": {}, "kopyalanan": kopyalanan,
            "durum": None if kopyalanan or os.path.isdir(kaynak) else _("{uygulama} userData yok (hiç açılmamış)").format(
                uygulama=uygulama)}


def flatpak_argv(flatpak_kimlik: str, komut: str, kopya_yolu: str, ek_argv=None) -> list[str]:
    """Doğrulanmış devretmesiz başlatma: flatpak run --command=sh ile sandbox İÇİNDE XDG_* export edilir
    (flatpak dışarıdan verilen XDG_CONFIG_HOME'u ezdiği için). exec ile asıl Electron komutuna geçilir.

    flatpak run --die-with-parent --filesystem=<K> --command=sh <id> -c '<script>' deskhand <K> [ek...]
    """
    betik = ('K=$1; shift; '
             'export XDG_CONFIG_HOME="$K/config" XDG_CACHE_HOME="$K/cache" XDG_DATA_HOME="$K/data"; '
             'mkdir -p "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME"; '
             f'exec {shlex.quote(komut)} "$@"')
    return ["flatpak", "run", "--die-with-parent", f"--filesystem={kopya_yolu}",
            "--command=sh", flatpak_kimlik, "-c", betik, "deskhand", kopya_yolu, *(ek_argv or [])]
