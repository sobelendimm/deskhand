"""Oturum köprüsü (Faz 3): uygulama başına politika + "kullanıcının oturumunda açık mı" + tarayıcı/Electron
profil anlık kopyaları. Görünmez arka plan masaüstünde açılan uygulamalar kullanıcının mevcut girişleriyle
açılır, kullanıcı şifre girmez, asıl oturum ASLA bozulmaz.

Dış API (masaustu/uygulama entegrasyonu):
  hazirla(uygulama, gorev_siteleri=None, ham_komut=False) -> Hazirlik   (uygulama çözümünü kendisi yapar)
  temizle(kopya_yolu) / sil_hepsi() / kapanis()   (kapanis: kayıtlı Flatpak örneklerini kapatır, sonra kopyaları siler)
  cerez_parmak(kopya_yolu) / degisim_bildir(once, sonra)   (§4 jeton döndürme — raporlama)

KESİN KURALLAR: kaynak profiller YALNIZ okunur (tek yönlü). Sır değerleri günlüğe/rapora yazılmaz.
Şifre deposu rölesi YOK → keyring gerektiren uygulamalar arka planda açılmaz (karar "on").
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass, field

from ..i18n import N_, _
from . import chromium, cozum, firefox, flatpak_ornek, kopya, politika, tespit


@dataclass
class Hazirlik:
    karar: str                       # paylas | kopya | bekle | kapali | on
    argv: list = field(default_factory=list)
    env_ek: dict = field(default_factory=dict)
    kopya_yolu: str | None = None
    aciklama: str = ""
    gerekli_keyring: bool = False
    ayrinti: dict = field(default_factory=dict)


# İnsan okunur açıklamalar
_ACIKLAMA = {  # gösterirken _()
    "bekle": N_("{ad} ekranında açık; aynı anda iki istemci oturumunu düşürür. "
                "Kapatınca arka planda yapabilirim ya da Ekranımda yap."),
    "kapali": N_("{ad} arka planda çalıştırılmaz (ikinci örnek asıl veriyi/oturumu bozar)."),
    "on": N_("{ad} şifre deposu gerektiriyor; arka planda açılamaz (kaydınızı bozma riski), Ekranınızda yapılabilir."),
    "on_obsidian": N_("{ad} kasası doğrudan gerçek dosyalara yazar; arka planda açılmaz, Ekranınızda yapılabilir."),
}


def _bellek_siniri() -> str | None:
    """Arka plan bellek sınırı (DESKHAND_SANAL_BELLEK; "0"/"yok" = kapalı) — masaustu ile aynı kural."""
    try:
        from ..masaustu import _bellek_siniri as bs
        return bs()
    except Exception:  # noqa: BLE001
        b = (os.environ.get("DESKHAND_SANAL_BELLEK") or "4G").strip()
        return None if b.lower() in ("0", "yok", "none", "off") else b


def _flatpak_sarmala(argv: list, kimlik: str, kopya_yolu: str | None) -> list:
    return flatpak_ornek.sarmala(list(argv), kimlik, politika.flatpak_kayit(), _bellek_siniri(), kopya_yolu)


def _aciklama(karar: str, ad: str) -> str:
    anahtar = "on_obsidian" if (karar == "on" and ad == "obsidian") else karar
    metin = _ACIKLAMA.get(anahtar)
    return _(metin).format(ad=ad.capitalize()) if metin else ""


def hazirla(uygulama: str, gorev_siteleri=None, ham_komut: bool = False) -> Hazirlik:
    """Uygulamayı arka planda nasıl açacağımızı çöz; gerekirse kopya üret. Kaynak profil yazılmaz.

    Politika ajanın yazdığı HAM addan değil, ÇÖZÜLMÜŞ uygulamadan hesaplanır (cozum.coz: .desktop kimliği, Exec
    ikilisi ve gerçek yolu, Flatpak kimliği, kısmi ad, mutlak yol); birden çok politikaya uyarsa EN KISITLAYICI
    karar kazanır. Bilinmeyen uygulama yalnız kullanıcının oturumunda KESİNLİKLE çalışmıyorsa paylas; açık ya da
    bilinemiyorsa bekle. ham_komut=True: ajanın verdiği komut satırı (ac --komut); bilinen bir uygulamaya
    uymuyorsa tespit yapılmadan paylas (test pencereleri vb.), uyuyorsa normal politika (kopya → bekle)."""
    yap = politika.yukle()
    c = cozum.coz(uygulama)
    anahtarlar: list[str] = []
    for ad_ in c.adlar:
        for k in politika.eslesen_anahtarlar(ad_, yap):
            if k not in anahtarlar:
                anahtarlar.append(k)
    temel = {"cozum": c.ozet(), "politikalar": list(anahtarlar)}
    if ham_komut and not anahtarlar:
        return Hazirlik(karar="paylas", aciklama=_("ham komut (bilinen bir uygulamaya uymuyor)"),
                        ayrinti={**temel, "calisiyor": None})

    adaylar = [politika.anahtar_politikasi(k, yap) for k in anahtarlar] or \
        [politika.anahtar_politikasi("_varsayilan", yap, ad=politika._ad_normu(c.girdi) or "?")]
    secim = None  # (karar, pol, ayrinti)
    for pol in adaylar:
        calisiyor, det = tespit.calisiyor_mu(pol.uygulama if pol.bilinen else "", pol.flatpak,
                                             c.ikililer, c.flatpaklar)
        belirsiz = [*c.belirsiz, *det.pop("belirsiz", [])]
        if not pol.bilinen and not c.ikililer and not c.flatpaklar and not belirsiz:
            belirsiz.append("aranacak süreç adı yok")  # hiçbir sinyal sorulamadı: "kapalı" denemez
        k = pol.karar(calisiyor or bool(belirsiz))  # bilinemiyorsa açık say
        if pol.keyring and k == "kopya":  # keyring gerektiren + kopya istense bile: röle yok → arka planda açma
            k = "on"
        if ham_komut and k == "kopya":  # ham komuta kopya enjekte edilemez
            k = "bekle"
        ayr = {"calisiyor": calisiyor, **({"belirsiz": belirsiz} if belirsiz else {}), **det}
        if secim is None or politika.KISIT.get(k, 9) > politika.KISIT.get(secim[0], 9):
            secim = (k, pol, ayr)
    karar, pol, ayr = secim
    ayrinti = {**temel, **ayr}
    ad = pol.uygulama

    if karar in ("bekle", "kapali", "on"):
        aciklama = _aciklama(karar, ad)
        if ham_komut and karar == "bekle" and pol.karar(False) == "kopya":
            aciklama = _("{ad}: ham komutla oturum kopyası kullanılamaz; uygulama adıyla açın (ac {ad})").format(ad=ad)
        elif karar == "bekle" and not pol.bilinen and ayr.get("belirsiz") and not ayr.get("calisiyor"):
            aciklama = _("{ad}: kullanıcının ekranında açık olup olmadığı bilinemiyor; tek örnek kilidi pencereyi "
                         "kullanıcının ekranına devredebilir. Kapalı olduğu kesinleşince arka planda yapabilirim ya da "
                         "Ekranımda yap.").format(ad=ad)
        return Hazirlik(karar=karar, aciklama=aciklama, gerekli_keyring=pol.keyring, ayrinti=ayrinti)

    if karar == "paylas":
        argv: list = []
        if not ham_komut and c.flatpaklar:
            # flatpak run kendi scope'una geçer: kafes dışı kalmasın diye sarmalayıcıyla kaydet + bellek sınırı
            if len(c.flatpaklar) != 1:
                return Hazirlik(karar="bekle", aciklama=_("{ad}: birden çok Flatpak uygulamasına uyuyor; tam adını "
                                                          "verin").format(ad=ad), ayrinti=ayrinti)
            fk = c.flatpaklar[0]
            komut = c.exec_argv if cozum._flatpak_kimligi(c.exec_argv)[0] == fk else ["flatpak", "run", fk]
            argv = _flatpak_sarmala(komut, fk, None)
        return Hazirlik(karar="paylas", argv=argv, aciklama=_aciklama("paylas", ad), gerekli_keyring=pol.keyring,
                        ayrinti=ayrinti)

    # karar == "kopya"
    if ad == "firefox":
        b = firefox.hazirla(pol, gorev_siteleri)
    elif pol.flatpak and pol.flatpak in chromium._FLATPAK_ELECTRON:
        b = chromium.flatpak_electron_hazirla(pol, ad)
        if b.get("argv") and not b.get("durum"):
            b["argv"] = _flatpak_sarmala(b["argv"], pol.flatpak, b.get("kopya_yolu"))
    else:
        return Hazirlik(karar="bekle", aciklama=_("{ad}: kopya yöntemi tanımlı değil").format(ad=ad), ayrinti=ayrinti)

    if b.get("durum"):
        return Hazirlik(karar="bekle", kopya_yolu=b.get("kopya_yolu"),
                        aciklama=b["durum"], gerekli_keyring=pol.keyring, ayrinti=ayrinti)
    ayrinti.update({k: v for k, v in b.items() if k not in ("argv", "env_ek", "kopya_yolu", "durum")})
    return Hazirlik(karar="kopya", argv=b.get("argv", []), env_ek=b.get("env_ek", {}),
                    kopya_yolu=b.get("kopya_yolu"), gerekli_keyring=pol.keyring,
                    aciklama=_("{ad} kopyası hazır").format(ad=ad), ayrinti=ayrinti)


def temizle(kopya_yolu: str) -> None:
    kopya.temizle(kopya_yolu)


def _canli_ornek_kopyalari() -> set[str]:
    """Kayıtta olup PID'i hâlâ yaşayan Flatpak örneklerinin kopya dizinleri (silinmemeli)."""
    korunan = set()
    for g in flatpak_ornek.oku(politika.flatpak_kayit()):
        if g.get("kopya") and g.get("pid") and flatpak_ornek._canli(int(g["pid"])):
            korunan.add(os.path.realpath(g["kopya"]))
    return korunan


def sil_hepsi() -> int:
    """Tüm oturum kopyalarını sil (çalışan kayıtlı Flatpak örneğinin kopyası hariç). Döner: silinen sayısı."""
    return kopya.sil_hepsi(haric=_canli_ornek_kopyalari())


# ------------------------------------------------------------------ §4 değişim tespiti (raporlama)

def cerez_parmak(kopya_yolu: str) -> dict:
    """Kopya cookies.sqlite'ındaki her alan için çerez DEĞERLERİNİN özetini (sha1) döndür. Değer yazdırılmaz;
    yalnız alan adı → özet. Kopya kapanınca başlangıçla karşılaştırmak için (jeton döndürme uyarısı)."""
    db = _cookies_yolu(kopya_yolu)
    sonuc: dict[str, str] = {}
    if not db or not os.path.isfile(db):
        return sonuc
    try:
        con = sqlite3.connect(f"file:{os.path.abspath(db)}?mode=ro", uri=True)
    except sqlite3.Error:
        return sonuc
    try:
        h: dict[str, hashlib._Hash] = {}
        for host, name, value in con.execute("SELECT host, name, value FROM moz_cookies ORDER BY host, name"):
            alan = (host or "").lstrip(".").lower()
            h.setdefault(alan, hashlib.sha1()).update(f"{name}={value};".encode(errors="replace"))
        sonuc = {a: d.hexdigest() for a, d in h.items()}
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return sonuc


def degisim_bildir(once: dict, sonra: dict) -> list[str]:
    """Başlangıç ve kapanış parmaklarını karşılaştır; çerezi değişen alanları döndür (jeton döndürmüş olabilir).
    Değerler yazılmaz; yalnız alan adları. Çağıran bunu günlüğe/kullanıcıya uyarı olarak yazar."""
    degisen = []
    for alan in set(once) | set(sonra):
        if once.get(alan) != sonra.get(alan):
            degisen.append(alan)
    return sorted(degisen)


def _cookies_yolu(kopya_yolu: str) -> str | None:
    if not kopya_yolu:
        return None
    dogrudan = os.path.join(kopya_yolu, "cookies.sqlite")
    return dogrudan if os.path.isfile(dogrudan) else None


# ---------------------------------------------------------------- yaşam döngüsü (ac --arka / masaustu durdur)

PARMAK_DOSYA = ".deskhand-parmak.json"


def parmak_kaydet(kopya_yolu: str) -> None:
    """Kopya açılmadan ÖNCE çerez parmak izi (alan → değer özeti; değer yazılmaz)."""
    import json
    if not kopya_yolu:
        return
    try:
        with open(os.path.join(kopya_yolu, PARMAK_DOSYA), "w") as f:
            json.dump(cerez_parmak(kopya_yolu), f)
    except OSError:
        pass


def kapanis() -> list[str]:
    """Sanal masaüstü kapanırken: önce Deskhand'nin başlattığı Flatpak örneklerini `flatpak kill` ile kapat ve
    bitmelerini bekle (en çok ~5 sn; kafes dışındaki scope'larında yaşarlar), sonra her kopyada çerezleri ilk
    hâliyle karşılaştır (jeton döndürme uyarısı) ve kopyayı sil. Kapanmayan örneğin kopyası SİLİNMEZ.
    → uyarı satırları."""
    import json
    from ..gunluk import gunluk
    kok = politika.kopya_dizini()
    uyarilar: list[str] = []
    korunan: set[str] = set()
    kayit = politika.flatpak_kayit()
    if os.path.isfile(kayit):
        try:
            _kapanan, kalan, notlar = flatpak_ornek.kapat_hepsi(kayit)
        except Exception as e:  # noqa: BLE001
            kalan, notlar = flatpak_ornek.oku(kayit), [f"Flatpak örnekleri kapatılamadı: {e}"]
        for n in notlar:
            gunluk(f"oturum: {n}")  # günlük Türkçe kalır
        korunan = {os.path.realpath(g["kopya"]) for g in kalan if g.get("kopya")}
        if kalan:
            uyarilar.append(_("oturum: {sayi} Flatpak örneği kapatılamadı ({uygulamalar}); kopyaları silinmedi").format(
                sayi=len(kalan), uygulamalar=", ".join(sorted({str(g.get("application")) for g in kalan}))))
        elif notlar:
            uyarilar.append(_("oturum: Flatpak örnekleri kapatılırken uyarı (ayrıntı günlükte)"))
    if not os.path.isdir(kok):
        return uyarilar
    for ad in sorted(os.listdir(kok)):
        yol = os.path.join(kok, ad)
        if not os.path.isdir(yol) or os.path.islink(yol) or os.path.realpath(yol) in korunan:
            continue
        try:
            with open(os.path.join(yol, PARMAK_DOSYA)) as f:
                once = json.load(f)
            degisen = degisim_bildir(once, cerez_parmak(yol))
        except (OSError, ValueError):
            degisen = []
        if degisen:
            u = N_("oturum: {ad} kopyasında şu sitelerin oturum çerezleri yenilendi; asıl tarayıcıda yeniden giriş "
                   "gerekebilir: {siteler}")
            uyarilar.append(_(u).format(ad=ad, siteler=", ".join(degisen[:10])))
            gunluk(u.format(ad=ad, siteler=", ".join(degisen[:10])))  # günlük Türkçe kalır
        temizle(yol)
    return uyarilar
