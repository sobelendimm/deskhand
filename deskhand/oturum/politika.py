"""Uygulama başına oturum politikası (docs/SESSIONS.md §8).

Varsayılanlar paket içindeki data/oturum.toml'dan okunur; kullanıcı CONFIG_DIR/oturum.toml ile üstüne yazar
(yalnız verdiği anahtarlar birleştirilir; vermediği varsayılanda kalır). Bilinmeyen uygulama `_varsayilan`
politikasını alır (kapali_iken=paylas, acik_iken=bekle; "açık mı" BİLİNEMİYORSA açık sayılır → bekle).

Eşleme: her bölümün `adlar` (tam ad/takma ad) ve `kimlik` (fnmatch: .desktop/Flatpak kimliği) listeleri.
`eslesen_anahtarlar(ad)` bir adın uyduğu TÜM bölümleri döndürür; birden çok aday addan gelen kararlar
`en_kisitlayici` ile birleştirilir (kapali > on > bekle > kopya > paylas).

Karar değerleri: kopya | paylas | bekle | kapali | on  (anlamları data/oturum.toml başında).

Site listeleri: `reddet` (çerez/deposu/kayıtlı parolası asla kopyalanmayan alanlar: banka/ödeme/devlet/merkezi
kimlik) ve görev bazlı `izin` (yalnız bu origin'ler kopyalanır). Eşleşme fnmatch kalıbı (`*bank*` gibi), alt alan
adları dahil; alan çerezi (`.google.com`) ret listesindeki bir alt alana gönderiliyorsa o da reddedilir.
"""
from __future__ import annotations

import fnmatch
import os
import tomllib

from .. import yollar

KARARLAR = ("kopya", "paylas", "bekle", "kapali", "on")
_VARSAYILAN_AD = "_varsayilan"

# Paket içindeki varsayılan politika (yollar.PAKET_DIZIN = .../deskhand)
_PAKET_TOML = os.path.join(yollar.PAKET_DIZIN, "data", "oturum.toml")


def _oku_toml(yol: str) -> dict:
    try:
        with open(yol, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _birlestir(taban: dict, ust: dict) -> dict:
    """ust'ü taban'ın üstüne derin birleştir (sözlükler iç içe; diğer değerler ust kazanır)."""
    sonuc = dict(taban)
    for k, v in ust.items():
        if isinstance(v, dict) and isinstance(sonuc.get(k), dict):
            sonuc[k] = _birlestir(sonuc[k], v)
        else:
            sonuc[k] = v
    return sonuc


def yukle() -> dict:
    """Varsayılan + kullanıcı politikasını birleştirip döndür (her çağrıda okunur: testler yola bağlı)."""
    taban = _oku_toml(_PAKET_TOML)
    kull = _oku_toml(os.path.join(yollar.config_dir(), "oturum.toml"))
    return _birlestir(taban, kull)


# Kısıtlayıcılık sırası (büyük = daha kısıtlayıcı)
KISIT = {"paylas": 0, "kopya": 1, "bekle": 2, "on": 3, "kapali": 4}

# Ad sonundaki sürüm/kanal ekleri: google-chrome-beta → google-chrome, steam-native → steam
_EKLER = ("-beta", "-nightly", "-stable", "-unstable", "-dev", "-developer", "-canary", "-snapshot", "-browser",
          "-bin", "-native", "-git", "-desktop", "-esr", "-launcher", "-wayland", "-x11")


def en_kisitlayici(kararlar) -> str | None:
    """Kararlar içinden en kısıtlayıcısı (bilinmeyen değer en kısıtlayıcı sayılır)."""
    kararlar = [k for k in kararlar if k]
    if not kararlar:
        return None
    return max(kararlar, key=lambda k: KISIT.get(k, len(KISIT)))


def _ad_normu(uygulama: str) -> str:
    """Adı eşleme biçimine indir: küçük harf, yol ve .desktop/.exe eki atılır."""
    a = (uygulama or "").strip().lower()
    a = os.path.basename(a.rstrip("/"))
    for ek in (".desktop", ".exe", ".appimage"):
        if a.endswith(ek):
            a = a[: -len(ek)]
    return a


def _ad_varyantlari(ad: str) -> list[str]:
    """ad + sürüm/kanal ekleri atılmış hâlleri (sırayla): brave-browser-nightly → brave-browser → brave."""
    sonuc = [ad]
    degisti = True
    while degisti:
        degisti = False
        for ek in _EKLER:
            if ad.endswith(ek) and len(ad) > len(ek):
                ad = ad[: -len(ek)]
                sonuc.append(ad)
                degisti = True
    return sonuc


def eslesen_anahtarlar(uygulama: str, yapilandirma: dict | None = None) -> list[str]:
    """Adın uyduğu politika bölümleri (`_varsayilan` hariç). Ad: ham ad, .desktop kimliği, ikili adı ya da Flatpak
    kimliği olabilir. Eşleşme: bölüm adı, `adlar`, `kimlik` kalıpları; ekleri atılmış varyantlar da denenir."""
    yap = yapilandirma if yapilandirma is not None else yukle()
    uygulamalar = yap.get("uygulama", {})
    a = _ad_normu(uygulama)
    if not a:
        return []
    varyantlar = _ad_varyantlari(a)
    # ters-DNS kimliğinin son parçası da (org.kde.kmail2 → kmail2); yalnız adlarla karşılaştırılır
    if "." in a and " " not in a:
        varyantlar += [v for v in _ad_varyantlari(a.rsplit(".", 1)[-1]) if v not in varyantlar]
    bulunan = []
    for anahtar, ham in uygulamalar.items():
        if anahtar == _VARSAYILAN_AD or not isinstance(ham, dict):
            continue
        adlar = {anahtar.lower(), *(str(x).lower() for x in ham.get("adlar", ()))}
        if ham.get("flatpak"):
            adlar.add(str(ham["flatpak"]).lower())
        kaliplar = [str(x).lower() for x in ham.get("kimlik", ())]
        if any(v in adlar for v in varyantlar) or any(fnmatch.fnmatchcase(a, k) for k in kaliplar):
            bulunan.append(anahtar)
    return bulunan


class Politika:
    """Tek uygulamanın çözülmüş politikası."""

    def __init__(self, uygulama: str, ham: dict, site: dict):
        self.uygulama = uygulama
        self.kapali_iken = ham.get("kapali_iken", "bekle")
        self.acik_iken = ham.get("acik_iken", "bekle")
        self.keyring = bool(ham.get("keyring", False))
        self.senkron = bool(ham.get("senkron", False))
        self.flatpak = ham.get("flatpak") or None
        self.disla = tuple(ham.get("disla", ()))
        self.not_ = ham.get("not") or ""
        self._reddet = tuple(site.get("reddet", ()))
        self._izin = tuple(site.get("izin", ()))
        self.bilinen = True

    def karar(self, calisiyor: bool) -> str:
        return self.acik_iken if calisiyor else self.kapali_iken

    # ---- site süzme ----
    def site_reddedildi(self, alan: str) -> bool:
        """alan ret listesinde mi (kendisi ya da üst alanı)?"""
        return _alan_eslesir(alan, self._reddet)

    def cerez_reddedildi(self, host: str) -> bool:
        """Çerez/giriş kaydı konağı reddedilmeli mi? Alanın kendisi (ya da üstü) ret listesindeyse; ayrıca ALAN
        çerezi (".google.com", baştaki nokta) ret listesindeki bir alt alana (accounts.google.com) da
        gönderildiği için reddedilir. host baştaki noktayla verilmezse yalnız ilk kural."""
        h = (host or "").strip().lower()
        alan = h.lstrip(".").rstrip(".")
        if not alan:
            return False
        if self.site_reddedildi(alan):
            return True
        if not h.startswith("."):
            return False
        for k in self._reddet:
            k = str(k).strip().lower()
            if not k:
                continue
            # yalnız düz alan kalıpları ("*.gov.tr" gibi kalıpların alt alanları zaten site_reddedildi'de)
            if "*" not in k and "?" not in k and "[" not in k and (k == alan or k.endswith("." + alan)):
                return True
        return False

    def site_izinli(self, alan: str, gorev_siteleri=None) -> bool:
        """izin listesi (politika + göreve özel) boşsa her alan izinli; doluysa yalnız eşleşenler.
        Ret her zaman izni ezer."""
        if self.site_reddedildi(alan):
            return False
        izin = tuple(self._izin) + tuple(gorev_siteleri or ())
        if not izin:
            return True
        return _alan_eslesir(alan, izin)


def _alan_eslesir(alan: str, kaliplar) -> bool:
    alan = (alan or "").strip().lower().rstrip(".")
    if not alan:
        return False
    for k in kaliplar:
        k = str(k).strip().lower()
        if not k:
            continue
        if fnmatch.fnmatch(alan, k):
            return True
        # kalıp düz alan adıysa alt alanları da yakala (github.com → api.github.com)
        if "*" not in k and "?" not in k and (alan == k or alan.endswith("." + k)):
            return True
    return False


def coz(uygulama: str, yapilandirma: dict | None = None) -> Politika:
    """Tek ad için politika nesnesi. Ad birden çok bölüme uyarsa en kısıtlayıcısı (kapalıyken, sonra açıkken
    kararına göre); hiçbirine uymazsa `_varsayilan` (Politika.uygulama = normlanmış ad, bilinen=False)."""
    yap = yapilandirma if yapilandirma is not None else yukle()
    anahtarlar = eslesen_anahtarlar(uygulama, yap)
    if anahtarlar:
        return max((anahtar_politikasi(k, yap) for k in anahtarlar),
                   key=lambda p: (KISIT.get(p.kapali_iken, len(KISIT)), KISIT.get(p.acik_iken, len(KISIT))))
    return anahtar_politikasi(_VARSAYILAN_AD, yap, ad=_ad_normu(uygulama))


def anahtar_politikasi(anahtar: str, yapilandirma: dict | None = None, ad: str | None = None) -> Politika:
    """Bölüm adından Politika (anahtar yoksa `_varsayilan`)."""
    yap = yapilandirma if yapilandirma is not None else yukle()
    uygulamalar = yap.get("uygulama", {})
    bilinen = anahtar != _VARSAYILAN_AD and anahtar in uygulamalar
    ham = uygulamalar.get(anahtar) if bilinen else None
    ham = ham or uygulamalar.get(_VARSAYILAN_AD) or {"kapali_iken": "bekle", "acik_iken": "bekle", "keyring": False}
    pol = Politika(anahtar if bilinen else (ad or anahtar), ham, yap.get("site", {}))
    pol.bilinen = bilinen
    return pol


def kopya_dizini() -> str:
    """Kopyaların kök dizini (RUNTIME_DIR/oturum, 0700)."""
    return os.path.join(yollar.runtime_dir(), "oturum")


def flatpak_kayit() -> str:
    """Deskhand'nin başlattığı Flatpak örneklerinin kaydı (RUNTIME_DIR/oturum/flatpak.json)."""
    return os.path.join(kopya_dizini(), "flatpak.json")
