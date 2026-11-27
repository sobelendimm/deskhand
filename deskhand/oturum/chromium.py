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

# Kopya RUNTIME_DIR'da (tmpfs, bellek): disk önbelleği 64 MB ile sınırlı (Firefox: browser.cache.disk.capacity)
DISK_CACHE_BAYT = 64 * 1024 * 1024

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
    kopya_mod.izinleri_daralt(hedef)
    return {"kopyalanan": sayac}


def chromium_argv(uygulama: str, hedef: str, ek=None, parola_deposu: str | None = None) -> list[str]:
    """Yerel Chromium ailesi başlatma argümanları. parola_deposu verilmezse anahtar_deposu (köprü için). Başlatmaz."""
    exe = {"chromium": "chromium", "vivaldi": "vivaldi", "chrome": "google-chrome-stable",
           "brave": "brave"}.get(uygulama, uygulama)
    return [exe, f"--user-data-dir={hedef}", f"--password-store={parola_deposu or anahtar_deposu(uygulama)}",
            "--disable-sync", "--no-first-run", "--no-default-browser-check",
            f"--disk-cache-size={DISK_CACHE_BAYT}", *(ek or [])]


# ------------------------------------------------------------------ (A2) yerli Chromium: BOŞ profil (ABM-F3)
# Kullanıcının profili kopyalanmaz (çerez/parola anahtarlıkta şifreli; röle yazılmaz: N1b). Boş --user-data-dir +
# --password-store=basic: Chromium anahtarlığa HİÇ gitmez → kullanıcının "Chromium Safe Storage" kaydı ezilemez.
# Yalnız Flatpak OLMAYAN `chromium` politikası (ölçüldü: rapor-ABM-OLC S5). Chrome/Brave/Vivaldi değişmez ("on").
YERLI_DESTEKLI = ("chromium",)

# Flatpak tarayıcıları görünmez masaüstünde AÇILMAZ (rapor-ABM-OLC: com.google.Chrome ölçüldü; aynı başlatıcı düzeni)
FLATPAK_TARAYICILARI = ("com.google.Chrome", "org.chromium.Chromium", "com.brave.Browser", "com.vivaldi.Vivaldi",
                        "com.microsoft.Edge", "com.opera.Opera", "io.github.ungoogled_software.ungoogled_chromium",
                        "com.github.Eloston.UngoogledChromium")


def _bos_profil_yolu(uygulama: str) -> str:
    """Yeni boş profil kopyasının YOLU (dizin OLUŞTURULMAZ): kopya kökünde, kopya bekçisinin ad deseninde."""
    import time
    from . import politika
    return os.path.join(politika.kopya_dizini(),
                        f"{uygulama}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{os.urandom(3).hex()}")


def bos_profil_olustur(yol: str | None) -> bool:
    """Karar anında yalnız YOLU verilen yerli Chromium boş profil kopyasını oluştur (gerçek açılışta, başlatmadan hemen
    önce: uygulama._baslat). Yalnız kopya kökünün doğrudan altındaki, YERLI_DESTEKLI adlı, ad desenine uyan ve henüz
    VAR OLMAYAN yol (0700, sahip kaydı yeni_kopya_dizini ile aynı); başka her yol için hiçbir şey yapmaz. → oluşturuldu
    mu."""
    import time
    from . import kopya_bekcisi as _bekci
    if not yol or os.path.lexists(yol):
        return False
    ad = os.path.basename(yol)
    if not _bekci.KOPYA_DESENI.fullmatch(ad) or not any(ad.startswith(u + "-") for u in YERLI_DESTEKLI):
        return False
    kok = kopya_mod.kopya_kok()
    if os.path.realpath(os.path.dirname(yol)) != os.path.realpath(kok):
        return False
    kopya_mod.sinir_uygula()
    kopya_mod.bos_alan_denetle(kok)
    os.mkdir(yol, 0o700)  # var olursa FileExistsError (yarış): üzerine kurulmaz
    os.chmod(yol, 0o700)
    _bekci.sahip_yaz(yol, {"hazirlayan": os.getpid(), "hazirlayan_bas": _bekci.baslangic(os.getpid()),
                           "zaman": time.time()})
    return True


def yerli_hazirla(uygulama: str = "chromium", ek=None, olustur: bool = True) -> dict:
    """Yerli Chromium için BOŞ profil kopyası (tmpfs, kopya kökünde; kopya bekçisi ve kapanış onu siler) + argv
    (erişilebilirlik bayrağıyla). olustur=False: yalnız yol (karar/tanı yan etkisiz; dizin gerçek açılışta
    bos_profil_olustur ile). → {kopya_yolu, argv, not}. Başlatmaz."""
    from ..uygulama import ERISIM_BAYRAGI
    if olustur:
        hedef = kopya_mod.yeni_kopya_dizini(uygulama)
        kopya_mod.izinleri_daralt(hedef)
    else:
        hedef = _bos_profil_yolu(uygulama)
    return {"kopya_yolu": hedef, "argv": chromium_argv(uygulama, hedef, [ERISIM_BAYRAGI, *(ek or [])], "basic"),
            "not": _("{ad} boş profille açıldı: kayıtlı girişler yok (şifre deposu rölesi yok, anahtarlığa "
                     "dokunulmaz)").format(ad=uygulama.capitalize())}


def flatpak_tarayici_nedeni(kimlik: str) -> str:
    """Flatpak tarayıcısının görünmez masaüstünde açılmama kök nedeni + öneri (kod 16 iletisi)."""
    return _("{kimlik} (Flatpak) görünmez masaüstünde açılmaz: kök neden, ad alanındaki boş ev dizininde "
             "~/.var/app/{kimlik} yok ve Flatpak başlatıcısının X yetkisi yok; başlatıcı iç içe bwrap'ten önce çıkıyor "
             "(ölçüldü). Öneri: yerli chromium kullanın (open chromium; boş profil, kayıtlı girişler yok) ya da "
             "Ekranımda yap.").format(kimlik=kimlik)


def flatpak_tarayici_mi(kimlik: str | None) -> bool:
    return bool(kimlik) and kimlik in FLATPAK_TARAYICILARI


def on_karari(h):
    """oturum.hazirla'nın "on" kararı (şifre deposu gerektiren tarayıcı) için ABM-F3 kuralı:
      - çözüm bir Flatpak tarayıcısıysa → Dur(16) + kök neden + "yerli chromium" önerisi (hemen; başlatma denenmez);
      - YALNIZ yerli `chromium` politikasına uyuyorsa → Hazirlik(kopya): boş profil, a11y bayrağı, "kayıtlı girişler yok";
      - başka her durumda None (karar aynen kalır). h "on" değilse None."""
    from ..hata import OTURUM_POLITIKASI, Dur
    if getattr(h, "karar", None) != "on":
        return None
    ayr = getattr(h, "ayrinti", None) or {}
    flatpaklar = list((ayr.get("cozum") or {}).get("flatpak") or [])
    for fk in flatpaklar:
        if flatpak_tarayici_mi(fk):
            raise Dur(OTURUM_POLITIKASI, flatpak_tarayici_nedeni(fk))
    politikalar = list(ayr.get("politikalar") or [])
    if flatpaklar or not politikalar or any(p not in YERLI_DESTEKLI for p in politikalar):
        return None
    b = yerli_hazirla(politikalar[0], olustur=False)  # kopya dizini gerçek açılışta (tanı komutu yan etkisiz)
    from . import Hazirlik
    return Hazirlik(karar="kopya", argv=b["argv"], kopya_yolu=b["kopya_yolu"], aciklama=b["not"],
                    gerekli_keyring=False, ayrinti={**ayr, "yerli_bos_profil": True})


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
    # sandbox içinde XDG_CONFIG_HOME = <hedef>/config: kullanıcının XDG klasör adları + GTK görünümü orada olmalı
    # (yoksa indirilenler sandbox'ın geçici ~/Downloads'ına gider; Firefox kopyasıyla aynı sorun)
    from .firefox import xdg_yapilandirma_kur
    xdg_yapilandirma_kur(os.path.join(hedef, "config"))
    kopya_mod.izinleri_daralt(hedef)
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
