"""`deskhand doctor`: kurulum ve oturum sağlığı. SALT OKUNUR: hiçbir şey başlatmaz, açmaz, yazmaz (yalnız `which`,
`--version`, dosya/soket varlığı, D-Bus'ta ad sahibi sorgusu, durum dosyaları). Bağımlılık denetimleri panelin Sağlık
sekmesiyle ortaktır (gui/saglik.py, Qt'siz); buradaki satırlar onların üstüne oturum/kurulum durumunu ekler.

Her satır: {ad, durum: "tamam" | "uyari" | "eksik", zorunlu: bool, ayrinti, oneri}. Çıkış kodu: zorunlu bir bağımlılık
eksikse 9 (hata.ARAC_EKSIK), yoksa 0. Uyarılar çıkış kodunu etkilemez."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess

from . import __version__, hata, yollar
from .gui import saglik
from .i18n import _

# install.sh'de "rec": eksikse çalışır (yedek yol / küçük kayıp). Tek dizeden: ham araç taraması (tests/test_mantik.py)
OPSIYONEL = set("spectacle xdotool scipy kwin_wayland".split())
IMGE = {"tamam": "✓", "uyari": "!", "eksik": "✗"}


def _satir(ad, durum, ayrinti, oneri="", zorunlu=False):
    return {"ad": ad, "durum": durum, "zorunlu": bool(zorunlu), "ayrinti": ayrinti, "oneri": oneri}


def _komut_ciktisi(*argv, sure=3.0):
    """Salt okunur sürüm sorgusu: ilk satır, yoksa ""."""
    if not shutil.which(argv[0]):
        return ""
    try:
        r = subprocess.run(list(argv), capture_output=True, text=True, timeout=sure)
    except (OSError, subprocess.SubprocessError):
        return ""
    satirlar = (r.stdout or "").strip().splitlines()
    return satirlar[0].strip() if r.returncode == 0 and satirlar else ""


# ---------------------------------------------------------------- bağımlılıklar (Sağlık sekmesiyle ortak)

def _paket(notu: str) -> tuple[str, bool]:
    """Sağlık notundaki "(AUR: kdotool-bin)" / "(tesseract)" → (paket, AUR mu)."""
    m = re.search(r"\((AUR: )?([\w.+-]+)\)", notu or "")
    return (m.group(2), bool(m.group(1))) if m else ("", False)


def bagimlilik_satirlari() -> list[dict]:
    sonuc = []
    for d in saglik.denetle():
        ad = d["ad"]
        zorunlu = ad not in OPSIYONEL
        paket, aur = _paket(_(d["not"]))
        ayrinti = _(d["not"])
        if d["ok"]:
            sonuc.append(_satir(ad, "tamam", ayrinti, zorunlu=zorunlu))
            continue
        oneri = (_("AUR paketini kur: {paket}") if aur else _("paketi kur: {paket}")).format(paket=paket) if paket \
            else _("./install.sh eksikleri listeler")
        sonuc.append(_satir(ad, "eksik" if zorunlu else "uyari",
                            (_("eksik") if zorunlu else _("eksik (isteğe bağlı)")) + f": {ayrinti}", oneri, zorunlu))
    return sonuc


# ---------------------------------------------------------------- oturum ve kurulum

def satir_surum():
    return _satir(_("Deskhand sürümü"), "tamam", __version__)


def satir_oturum():
    tur = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    masaustu_adi = os.environ.get("XDG_CURRENT_DESKTOP") or "?"
    ayrinti = f"{tur.capitalize() if tur else '?'} ({masaustu_adi})"
    if tur == "wayland" and "KDE" in masaustu_adi.upper():
        return _satir(_("Masaüstü oturumu"), "tamam", ayrinti)
    return _satir(_("Masaüstü oturumu"), "uyari", ayrinti + " — " + _("ön plan (kendi ekranın) yalnız KDE Plasma 6 "
                                                                   "Wayland'de desteklenir; görünmez masaüstü çalışır"),
                  _("Plasma (Wayland) oturumu aç"))


def satir_kwin():
    kwin = _komut_ciktisi("kwin_wayland", "--version") or _komut_ciktisi("kwin_x11", "--version")
    plasma = _komut_ciktisi("plasmashell", "--version")
    parcalar = [p for p in (kwin, plasma) if p]
    if parcalar:
        return _satir(_("KWin / Plasma sürümü"), "tamam", ", ".join(parcalar))
    return _satir(_("KWin / Plasma sürümü"), "uyari", _("sürüm okunamadı (kwin/plasmashell bulunamadı)"))


def satir_panel():
    from . import onay
    pid = onay.panel_pid()
    if pid:
        return _satir(_("Panel"), "tamam", _("çalışıyor (pid {pid})").format(pid=pid))
    return _satir(_("Panel"), "uyari", _("çalışmıyor: hassas eylem onayı ve DUR/Devral düğmeleri yok"),
                  "deskhand panel --tepsi")


def satir_onay_kapsami():
    from . import guvenlik
    kap = guvenlik.onay_kapsami(taze=True)
    if kap == "kart":
        return _satir(_("Onay kapsamı"), "tamam",
                      _("kart: yalnız kartla ödeme (para düğmesi/ödeme sayfası, kart bilgisi yazma) onay ister; "
                        "diğer onaylar kapalı"))
    from . import ayarlar
    try:
        dosyada = ayarlar.al("guvenlik", "onaylar")
    except Exception:  # noqa: BLE001
        dosyada = None
    if dosyada == "kart":  # dosyada kart ama panel teyit etmiyor (kapalı / panel dışında yazılmış)
        return _satir(_("Onay kapsamı"), "uyari",
                      _("hepsi: ayar dosyasında 'kart' var ama panel teyit etmiyor (panel kapalı ya da panel dışında "
                        "yazılmış); tüm onaylar açık"), "deskhand panel")
    return _satir(_("Onay kapsamı"), "tamam", _("hepsi: tüm onaylar açık (varsayılan)"))


def satir_girdi_merkezi():
    from . import girdi_merkezi
    yol = girdi_merkezi.soket_yolu()
    try:
        soket_mu = stat.S_ISSOCK(os.stat(yol).st_mode)
    except OSError:
        soket_mu = False
    if soket_mu:
        return _satir(_("Girdi merkezi soketi"), "tamam", _("var (panel hazır girdi sunuyor)"))
    return _satir(_("Girdi merkezi soketi"), "uyari",
                  _("yok: panel kapalıyken her komut kendi girdi sürecini açar (ilk girdi ~0,7 sn gecikir)"),
                  "deskhand panel --tepsi")


def _calistirilabilir(yol):
    return bool(yol) and os.path.isfile(yol) and os.access(yol, os.X_OK)


def satir_yardimcilar():
    """Üç C yardımcısı (deskhand-etkinlik, deskhand-goruntu, deskhand-eis): eksik her biri SONUCUYLA anılır."""
    etkinlik, goruntu, eis = yollar.etkinlik_bin(), yollar.goruntu_bin(), yollar.eis_bin()
    eksik = []
    if not _calistirilabilir(etkinlik):
        eksik.append(_("deskhand-etkinlik yok: insan önceliği yalnız fareye bakar"))
    if not _calistirilabilir(goruntu):
        eksik.append(_("deskhand-goruntu yok: ekran görüntüsü yavaş yedek yolla alınır; KWin arka planı kullanılamaz, "
                       "Xvfb kullanılacak"))
    if not _calistirilabilir(eis):
        eksik.append(_("deskhand-eis yok (libei + libxkbcommon + libsystemd geliştirme dosyaları gerekir): KWin arka "
                       "planı kullanılamaz, Xvfb kullanılacak"))
    if not eksik:
        return _satir(_("C yardımcıları"), "tamam", _("derli (etkinlik, ekran görüntüsü, girdi/EIS)"))
    return _satir(_("C yardımcıları"), "uyari", _("derli değil: {liste}").format(liste="; ".join(eksik)),
                  _("./install.sh derler (make -C deskhand/yardimci; kitaplıklar kurulunca yeniden çalıştır)"))


def satir_erisim():
    """AT-SPI: önce D-Bus'ta org.a11y.Bus'ın sahibi var mı (NameHasOwner etkinleştirmez); sahibi yoksa özellik
    sorgusu hizmeti BAŞLATIRDI, o yüzden sorulmaz."""
    ad = _("Erişilebilirlik (AT-SPI)")
    sahip = _komut_ciktisi("busctl", "--user", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                           "org.freedesktop.DBus", "NameHasOwner", "s", "org.a11y.Bus")
    if sahip != "b true":
        return _satir(ad, "uyari", _("erişilebilirlik veri yolu çalışmıyor (oturumda at-spi yok)"),
                      _("at-spi2-core kur, oturumu yeniden aç"))
    durum = _komut_ciktisi("busctl", "--user", "get-property", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status",
                           "IsEnabled")
    if durum == "b true":
        if os.path.exists(yollar.erisim_isareti()):
            return _satir(ad, "tamam", _("açık (Deskhand açtı; agac / ogeye-tikla çalışır; kapatmak: deskhand a11y off)"))
        return _satir(ad, "tamam", _("açık (agac / ogeye-tikla çalışır)"))
    return _satir(ad, "uyari", _("kapalı: uygulama düğmeleri ad ile bulunamaz (OCR yedekte)"), "deskhand a11y on")


def satir_arka_plan():
    from . import masaustu
    ad = _("Arka plan masaüstü")
    d = masaustu.durum()
    if d is None:
        return _satir(ad, "tamam", _("kapalı (gerektiğinde açılır: deskhand desktop start)"))
    b = "x".join(str(v) for v in (d.get("boyut") or [])[:2])
    saglik_ = d.get("saglik") or {}
    bozuk = sorted(a for a, ok in saglik_.items() if not ok)
    if bozuk:
        return _satir(ad, "uyari", _("çalışıyor ({ekran}, {boyut}) ama bileşen yanıt vermiyor: {liste}").format(
            ekran=d.get("ekran", "?"), boyut=b, liste=", ".join(bozuk)),
            _("deskhand desktop stop; deskhand desktop start"))
    return _satir(ad, "tamam", _("çalışıyor ({ekran}, {boyut})").format(ekran=d.get("ekran", "?"), boyut=b))


def satir_calisma_dizini():
    """Deskhand'in çalışma dizini (RUNTIME_DIR): kullanıcıya ait, sembolik bağ olmayan, 0700 olmalı. Gevşek izinli dizin
    sessizce düzeltilmez (arka plan masaüstü Dur 14 verir); burada nedeni ve çaresi görünür. Salt okunur."""
    from . import arka_ortak
    ad = _("Çalışma dizini")
    yol = yollar.runtime_dir()
    neden = arka_ortak.runtime_durumu(yol)
    if neden:
        return _satir(ad, "uyari", neden, _("chmod 700 {yol} (sahibi siz değilseniz dizini silin)").format(yol=yol))
    return _satir(ad, "tamam", _("{yol} (0700)").format(yol=yol) if os.path.isdir(yol) else
                  _("{yol} (henüz yok)").format(yol=yol))


def satir_arka_tur():
    """Arka plan masaüstü hangi türle açılır (KWin oturumu / Xvfb) ve KWin türünün ön koşulları: ScreenShot2 sanal
    arka uçta /dev/udmabuf okuma-yazma ister (yoksa görüntü alınamaz). Salt okunur; süreç başlatmaz."""
    from . import kwin_oturum
    ad = _("Arka plan masaüstü türü")
    ok, neden = kwin_oturum.kullanilabilir()
    if not ok:
        return _satir(ad, "tamam", _("Xvfb + openbox (KWin oturumu kullanılamıyor: {neden})").format(neden=neden))
    gpu = kwin_oturum.render_sec()
    ayrinti = _("yalıtık KWin oturumu (GPU: {gpu})").format(
        gpu=_("tümleşik {dugum}").format(dugum=gpu["dugum"]) if gpu else _("varsayılan"))
    if not os.access("/dev/udmabuf", os.R_OK | os.W_OK):
        return _satir(ad, "uyari", ayrinti + " — " + _("/dev/udmabuf okunamıyor/yazılamıyor: KWin ekran görüntüsü "
                                                       "alamaz, Xvfb'ye düşülür"),
                      _("kullanıcıya /dev/udmabuf rw izni (ör. kvm grubu ya da udev ACL)"))
    return _satir(ad, "tamam", ayrinti + " · udmabuf rw")


def satir_gpu_ocr():
    from . import ocr_gpu
    ad = _("GPU metin okuma (OCR)")
    eksik = ocr_gpu.eksikler()
    if not eksik:
        return _satir(ad, "tamam", _("kurulu (EasyOCR ekran kartında; tesseract tabanı korunur)"))
    if "gpu" in eksik:  # kart yoksa diğer eksikler anlamsız
        return _satir(ad, "tamam", _("ekran kartı yok: yalnız tesseract kullanılır"))
    neden = {"python": _("EasyOCR/torch yok"), "model": _("modeller indirilmemiş"),
             "hata": _("son açılış başarısız")}
    return _satir(ad, "uyari", _("kurulu değil: {liste}").format(liste=", ".join(neden.get(e, e) for e in eksik
                                                                             if e != "gpu")),
                  _("./install.sh eksikleri ve kurulum komutlarını listeler"))


SATIRLAR = (satir_surum, satir_oturum, satir_kwin, satir_panel, satir_onay_kapsami, satir_girdi_merkezi, satir_yardimcilar,
            satir_erisim, satir_arka_plan, satir_calisma_dizini, satir_arka_tur, satir_gpu_ocr)


def topla() -> list[dict]:
    """Tüm denetimler (bağımlılıklar + ek satırlar). Bir denetim çökerse satırı uyarı olur, doktor çökmez."""
    sonuc = []
    try:
        sonuc += bagimlilik_satirlari()
    except Exception as e:  # noqa: BLE001
        sonuc.append(_satir(_("Bağımlılıklar"), "uyari", _("denetlenemedi: {hata}").format(hata=e)))
    for f in SATIRLAR:
        try:
            sonuc.append(f())
        except Exception as e:  # noqa: BLE001
            sonuc.append(_satir(f.__name__.removeprefix("satir_"), "uyari", _("denetlenemedi: {hata}").format(hata=e)))
    return sonuc


def ozet(satirlar: list[dict]) -> dict:
    """{"tamam": n, "uyari": n, "eksik": n}; "eksik" yalnız zorunlu bağımlılıklar."""
    return {d: sum(1 for s in satirlar if s["durum"] == d) for d in ("tamam", "uyari", "eksik")}


def metin(satirlar: list[dict]) -> str:
    genislik = max(len(s["ad"]) for s in satirlar)
    cikti = []
    for s in satirlar:
        l = f"{IMGE[s['durum']]} {s['ad']:<{genislik}}  {s['ayrinti']}"
        if s["oneri"] and s["durum"] != "tamam":
            l += f"  → {s['oneri']}"
        cikti.append(l)
    o = ozet(satirlar)
    cikti.append(_("Özet: {tamam} tamam, {uyari} uyarı, {eksik} eksik zorunlu bağımlılık").format(**o))
    return "\n".join(cikti)


def k_doktor(a):
    """Salt okunur sağlık denetimi. Çıkış: zorunlu bağımlılık eksikse 9, yoksa 0 (uyarılar etkilemez)."""
    satirlar = topla()
    o = ozet(satirlar)
    if a.json:
        print(json.dumps({"surum": __version__, "tamam": o["eksik"] == 0, "ozet": o, "denetimler": satirlar},
                         ensure_ascii=False))
    else:
        print(metin(satirlar))
    if o["eksik"]:
        raise SystemExit(hata.ARAC_EKSIK)
