"""Dosya seçici yardımcısı: `choose-file KİMLİK /tam/yol` (Türkçe: `dosya-sec`).

GTK dosya seçicide elle yürütülen yol (ctrl+l → yol → Enter) kırılgandı: konum girdisi zaten açıkken/kapalıyken
ikinci ctrl+l girdiyi açmayabiliyor; yazılan yol listedeki "yazarak ara"ya gidiyor ve Enter YANLIŞ dosyayı seçiyordu
(gerçek olay: yanlış PDF yüklendi). Burada her adım DOĞRULANIR, doğrulanamayan adımda Enter'a basılmaz:

  1. Yol var olan bir dosya olmalı; görünmez masaüstünde dosya arka plan uygulamasının görebildiği bir klasörde olmalı
     (XDG veri klasörleri: ~/İndirilenler, ~/Belgeler…; /tmp ve XDG dışı ev klasörleri ad alanında görünmez).
  2. ctrl+l (tus komutunun tüm denetimleriyle) → AT-SPI ile ODAKLI yazma alanı aranır (konum girdisi); yoksa yeniden
     denenir, olmazsa Dur 6 (hiçbir şey yazılmadı).
  3. Girdi doluysa ctrl+a, yol yazılır (yaz komutunun tüm denetimleriyle).
  4. Girdinin değeri AT-SPI ile geri okunur: yolla TAM aynı değilse (otomatik tamamlama ekledi, arama kutusuna gitti)
     Dur 8 — Enter'a BASILMAZ, başarı denmez.
  5. Enter → diyalog penceresi kapandı mı beklenir; kapanmadıysa Dur 8.
Yeni güvenlik yolu YOKTUR: tuş/yazı mevcut girdi komutlarından geçer (DUR, yasak pencere, başlık kilidi, insan önceliği)."""
from __future__ import annotations

import os
import time

from . import api, arka_ortak, erisim
from .arka_uc import EKRAN
from .gunluk import gunluk
from .hata import Dur
from .i18n import _

ODAK_BEKLE_SN = 1.5
KAPANIS_BEKLE_SN = 5.0
DENEME = 3


def gorunur_klasorler() -> list[str]:
    """Görünmez masaüstündeki uygulamanın gördüğü gerçek klasörler (XDG veri klasörleri + test paylaşımı)."""
    k = list(arka_ortak.veri_klasorleri())
    t = arka_ortak.test_paylasimi()
    if t:
        k.append(t)
    return k


def arka_planda_gorunur(yol: str, klasorler: list[str] | None = None) -> bool:
    g = os.path.realpath(yol)
    return any(g == k or g.startswith(k.rstrip("/") + "/") for k in (klasorler if klasorler is not None
                                                                       else gorunur_klasorler()))


def yol_denetle(yol: str, arka: bool) -> str:
    """→ mutlak yol. Dosya yoksa ya da (arka planda) görünmeyen bir klasördeyse Dur 1 — hiçbir girdi gönderilmeden."""
    if not yol:
        raise Dur(1, _("dosya yolu boş"))
    yol = os.path.abspath(os.path.expanduser(yol))
    if not os.path.isfile(yol):
        raise Dur(1, _("dosya yok ya da normal bir dosya değil: {yol}").format(yol=yol))
    if "\n" in yol or "\t" in yol:
        raise Dur(1, _("yolda satır sonu/sekme var: dosya seçiciye yazılamaz"))
    if arka and not arka_planda_gorunur(yol):
        raise Dur(1, _("bu dosya görünmez masaüstündeki uygulamaya görünmez ({yol}): arka planda yalnız XDG veri "
                       "klasörleri görünür (/tmp ve diğer ev klasörleri görünmez). Dosyayı İndirilenler (Downloads) gibi bir XDG "
                       "klasörüne kopyalayın ve o yolu verin").format(yol=yol))
    return yol


def _odak_bekle(k: str, sure: float, kosul=lambda o: True) -> dict | None:
    son = time.monotonic() + sure
    while True:
        o = erisim.odakli_metin(k)
        if o is not None and o.get("metin") is not None and kosul(o):
            return o
        if time.monotonic() >= son:
            return o if o is not None and kosul(o) else None
        time.sleep(0.1)


def _pencere_var(k: str) -> bool:
    try:
        return any(str(p.get("id")) == str(k) for p in api.pencereler())
    except Dur:
        return True  # bilinmiyor: kapandı deme


def dosya_sec(k: str, yol: str, baslik: str | None = None) -> str:
    """Dosya seçici diyaloğu `k`'de `yol`u seç → seçilen mutlak yol. Her adım doğrulanır (modül belgesi)."""
    if not k or k == EKRAN:
        raise Dur(1, _("choose-file dosya seçici diyaloğunun pencere kimliğini ister (tüm ekran değil)"))
    au = api.arka()
    yol = yol_denetle(yol, au.ad == "sanal")
    odak = None
    for _i in range(DENEME):
        api.tus(k, "ctrl+l", baslik=baslik)  # diyaloğa odak + konum girdisi
        odak = _odak_bekle(k, ODAK_BEKLE_SN)
        if odak is not None and odak.get("metin") is not None:
            break
        time.sleep(0.3)
    else:
        raise Dur(6, _("dosya seçicinin konum girdisi açılamadı ya da odakta değil ({n} deneme); hiçbir yol yazılmadı. "
                       "Pencerenin bir dosya seçici olduğunu `tree` ile denetleyin").format(n=DENEME))
    if odak["metin"]:
        api.tus(k, "ctrl+a", baslik=baslik)  # girdide eski metin var: üzerine yazılsın
    api.yaz(k, yol, baslik=baslik)
    okunan = _odak_bekle(k, ODAK_BEKLE_SN, lambda o: o.get("metin") == yol)
    if okunan is None or okunan.get("metin") != yol:
        deger = None if okunan is None else okunan.get("metin")
        raise Dur(8, _("konum girdisinin değeri yazılan yolla aynı değil (okunan: {okunan}); Enter'a basılmadı, dosya "
                       "seçilmedi. Diyaloğu `tree` ile denetleyip yeniden deneyin").format(
                           okunan=repr(deger)[:300] if deger is not None else _("okunamadı")))
    api.tus(k, "Return", baslik=baslik)
    son = time.monotonic() + KAPANIS_BEKLE_SN
    while _pencere_var(k):
        if time.monotonic() >= son:
            raise Dur(8, _("Enter'a basıldı ama dosya seçici kapanmadı (yol bir klasör olabilir ya da uygulama dosyayı "
                           "reddetti); seçimin sonucunu doğrulayın"))
        time.sleep(0.1)
    gunluk(f"choose-file | {k} | {yol[:300]}")
    return yol


def k_dosya_sec(a):
    yol = dosya_sec(a.kimlik, a.yol, baslik=a.baslik)
    print(_("seçildi: {yol}").format(yol=yol))
