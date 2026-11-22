"""Tarayıcı penceresinde bir adrese gitme: `goto KİMLİK ADRES`. Adres çubuğu yolu (ctrl+l → adres → Return) mevcut
girdi komutlarının (tus / yaz) üzerinden yürür: başlık kilidi (-b), yasak pencere, DUR, insan önceliği, hassas
sayfa onayı (ödeme sayfasında Enter) ve insan doğrulaması (CAPTCHA) kapısı aynen çalışır; yeni bir güvenlik yolu
YOKTUR. Yalnız http/https adresi (uygulama.web_adresi_denetle)."""
from __future__ import annotations

from . import api, gorev_kipi, web
from .arka_uc import EKRAN
from .gunluk import gunluk
from .hata import Dur
from .i18n import _
from .uygulama import web_adresi_denetle


def adrese_git(k: str, adres: str, baslik: str | None = None, onayli: bool = False) -> str:
    """Tarayıcı penceresi `k`'de adres çubuğundan `adres`e git → gidilen adres. Pencere tarayıcı değilse Dur(1);
    adres http(s) değilse Dur(10). Yazdığı iki adım (ctrl+l, adres+Enter) ayrı ayrı tüm girdi denetimlerinden geçer."""
    adres = web_adresi_denetle(adres)  # hiçbir girdi gönderilmeden ÖNCE
    if not k or k == EKRAN:
        raise Dur(1, _("goto bir tarayıcı penceresi ister (tüm ekran değil)"))
    if not web.tarayici_mi(k):
        raise Dur(1, _("goto yalnız tarayıcı pencerelerinde çalışır (bu pencere bir tarayıcı değil)"))
    if gorev_kipi.etkin():  # GÖREV KİPİ: yalnız görev tarayıcısının penceresi (MCP araçlarıyla aynı denetim)
        gorev_kipi.pencere_denetle(api.arka(), k)
    api.tus(k, "ctrl+l", baslik=baslik, onayli=onayli)   # adres çubuğuna odaklan + seç
    # adres + Enter TEK yazı eylemi: CAPTCHA kapısı ve (ödeme sayfasında) onay Enter'ı adresle birlikte BİR kez görür;
    # okunamayan sayfada odak sorgusu adres çubuğunu (belge dışı) görür → izin
    api.yaz(k, adres + "\n", baslik=baslik, onayli=onayli)
    gunluk(f"goto | {k} | {adres[:200]}")
    return adres


def k_git(a):
    adres = adrese_git(a.kimlik, a.adres, baslik=a.baslik, onayli=getattr(a, "onayli", False))
    print(_("gidildi: {adres}").format(adres=adres))
