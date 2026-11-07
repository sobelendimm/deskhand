"""kde arka ucu: KWin ScreenShot2 (D-Bus) ile hızlı ekran görüntüsü, deskhand-goruntu C yardımcısı üzerinden.

Her görüntüde `spectacle` süreci açmak (uygulama başlatma + PNG kodla/çöz + dosya) yerine yardımcı, KWin'in
org.kde.KWin.ScreenShot2 arayüzünü çağırır ve ham pikselleri bir borudan stdout'a aktarır; burada PIL RGB'ye
çevrilir. Yardımcı yoksa, KWin reddederse ya da çıktı anlaşılmazsa kde.ekran_goruntusu() spectacle yoluna düşer.

Yetki: KWin 6.8 öncesi, ScreenShot2'yi yalnız X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2 içeren
bir .desktop dosyasına sahip uygulamaya açar; çağıran, /proc/<pid>/exe yolu o dosyanın Exec= ilk sözcüğüyle
(kanonik yol) eşleştirilerek bulunur. /usr/bin/python3 bu yüzden yetkilendirilemez; install.sh yardımcının
kendi deskhand-goruntu.desktop dosyasını kurar. KWin 6.8'den beri denetim yoktur (her istemci çağırabilir).

Yardımcı çıktısı: "DESKHAND-GORUNTU 1 format=F width=W height=H stride=S scale=K\\n" + H*S bayt (QImage belleği).
"""
from __future__ import annotations

import subprocess
import threading

from PIL import Image

from .. import yollar
from ..gunluk import gunluk
from ..i18n import _

ONEK = b"DESKHAND-GORUNTU 1 "
ZAMAN_ASIMI = 15.0

# QImage::Format → (PIL ham çözücü kipi, piksel başına bayt). Bellekteki bayt sırası: Format_RGB32/ARGB32*
# küçük sonlu 0xAARRGGBB → B,G,R,A; RGBX8888/RGBA8888* → R,G,B,A. Ön çarpımlı alfa ekran görüntüsünde 255'tir.
HAM_KIPLER = {
    4: ("BGRX", 4), 5: ("BGRX", 4), 6: ("BGRX", 4),        # RGB32, ARGB32, ARGB32_Premultiplied
    13: ("RGB", 3), 29: ("BGR", 3),                          # RGB888, BGR888
    16: ("RGBX", 4), 17: ("RGBX", 4), 18: ("RGBX", 4),     # RGBX8888, RGBA8888, RGBA8888_Premultiplied
}
KIP64 = {25, 26, 27}  # RGBX64, RGBA64, RGBA64_Premultiplied: kanal başına 16 bit (yüksek bayt alınır)

# yardımcı çıkış kodları (deskhand-goruntu.c)
YETKISIZ = 2
DBUS_HATASI = 3

_kilit = threading.Lock()
_kapali: str | None = None  # bu süreçte yardımcı bir daha denenmez (neden)


class GoruntuHatasi(Exception):
    pass


def ayristir(veri: bytes) -> tuple[Image.Image, float]:
    """Yardımcı çıktısı → (PIL RGB görüntü, ölçek). Biçim/boyut tutarsızsa GoruntuHatasi."""
    son = veri.find(b"\n", 0, 256)
    if not veri.startswith(ONEK) or son < 0:
        raise GoruntuHatasi(_("ekran görüntüsü yardımcısının çıktısı anlaşılamadı"))
    try:
        alan = dict(p.split("=", 1) for p in veri[len(ONEK):son].decode("ascii").split())
        bicim, w, h, adim = (int(alan[a]) for a in ("format", "width", "height", "stride"))
        olcek = float(alan.get("scale", "1"))
    except (ValueError, KeyError, UnicodeDecodeError) as e:
        raise GoruntuHatasi(_("ekran görüntüsü yardımcısının çıktısı anlaşılamadı")) from e
    govde = memoryview(veri)[son + 1:]
    if w <= 0 or h <= 0 or len(govde) != adim * h:
        raise GoruntuHatasi(_("ekran görüntüsü eksik geldi ({n} / {beklenen} bayt)").format(
            n=len(govde), beklenen=adim * h))
    if bicim in HAM_KIPLER:
        kip, bpp = HAM_KIPLER[bicim]
        if adim < w * bpp:
            raise GoruntuHatasi(_("ekran görüntüsü eksik geldi ({n} / {beklenen} bayt)").format(
                n=adim, beklenen=w * bpp))
        return Image.frombytes("RGB", (w, h), govde, "raw", kip, adim, 1), olcek
    if bicim in KIP64 and adim >= w * 8:
        import numpy as np
        a = np.frombuffer(govde, dtype="<u2").reshape(h, adim // 2)[:, :w * 4].reshape(h, w, 4)
        return Image.fromarray((a[:, :, :3] >> 8).astype(np.uint8), "RGB"), olcek
    raise GoruntuHatasi(_("desteklenmeyen görüntü biçimi (QImage {bicim})").format(bicim=bicim))


def al(bolge=None, bin_yolu=None) -> tuple[Image.Image, float]:
    """Yardımcıyla görüntü: bolge=None tüm masaüstü (fiziksel piksel, spectacle -f gibi), (x, y, g, y) mantıksal
    koordinatla bölge. GoruntuHatasi: yardımcı yok / KWin reddetti / çıktı bozuk; .kalici=True ise bu süreçte
    yeniden denemeye değmez."""
    yol = bin_yolu or yollar.goruntu_bin()
    if not yol:
        h = GoruntuHatasi(_("ekran görüntüsü yardımcısı yok (make -C deskhand/yardimci deskhand-goruntu)"))
        h.kalici = True
        raise h
    argv = [yol]
    if bolge:
        argv += ["-a", *(str(int(v)) for v in bolge)]
    try:
        p = subprocess.run(argv, capture_output=True, timeout=ZAMAN_ASIMI)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GoruntuHatasi(_("ekran görüntüsü yardımcısı çalışmadı: {hata}").format(hata=e)) from e
    if p.returncode:
        ayrinti = p.stderr.decode("utf-8", "replace").strip()[-300:]
        h = GoruntuHatasi(_("ekran görüntüsü yardımcısı başarısız (kod {kod}): {ayrinti}").format(
            kod=p.returncode, ayrinti=ayrinti))
        # yetkisiz ya da arayüz yok (KWin değil / eski sürüm): her çağrıda tekrar denemenin anlamı yok
        h.kalici = p.returncode == YETKISIZ or (p.returncode == DBUS_HATASI and (
            "ServiceUnknown" in ayrinti or "UnknownMethod" in ayrinti or "UnknownObject" in ayrinti))
        raise h
    return ayristir(p.stdout)


def goruntu(yedek):
    """Tüm ekran PIL RGB: önce yardımcı, olmazsa yedek() (spectacle). Kalıcı hata süreç boyunca hatırlanır ve
    günlüğe bir kez yazılır; geçici hatada yalnız bu çağrı yedeğe düşer."""
    global _kapali
    if _kapali is None:
        try:
            return al()[0]
        except GoruntuHatasi as e:
            kalici = getattr(e, "kalici", False)
            with _kilit:
                if kalici and _kapali is None:
                    _kapali = str(e)
            gunluk(f"goruntu | spectacle yedeği | {e}")
    return yedek()


def sifirla():
    """Testler için: kalıcı hata hafızasını sil."""
    global _kapali
    _kapali = None
