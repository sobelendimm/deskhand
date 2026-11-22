"""Ajanın verdiği düzenli ifadelerin (pencere/başlık/sınıf desenleri) güvenli olup olmadığına bakar (ReDoS).

Python `re` modülünde eşleştirme zaman aşımı yoktur: `(a+)+$` gibi bir desen birkaç düzine karakterlik başlıkta
saatlerce geri izler ve gözcü/yürütücü döngüsünü kilitler (kde arka ucunda desen kdotool/KWin'e de gider). `regex`
modülü bağımlılık olarak eklenmez; bunun yerine desen SINIRLANIR ve açık kalıplar reddedilir:

* uzunluk en çok MAKS_UZUNLUK (300) karakter,
* geçersiz sözdizimi → hata (re.compile),
* tekrarlanan bir grubun İÇİNDE yine tekrar (`(a+)+`, `(a*)*`, `(.*a){5,}`, `(a{2,9})*`) ya da çakışan seçenek
  (`(a|a)+`, `(a|ab)*`) → ret,
* tek desende MAKS_SINIRSIZ (4) taneden çok sınırsız niceleyici (`.*.*.*.*.*x`: çok terimli geri izleme) → ret.

Sezgiseldir (her kötü deseni yakalamaz, iyi huylu olanı nadiren reddeder); kesin koruma değil, sınırı daraltır. YALNIZ ajanın
verdiği desenlere uygulanır: Deskhand'in kendi ürettiği kalıplar (başlık kilidi: kaçışlı tam başlık) bu sınırlara takılmaz.
Tüketici: deskhand.api (pencere, pencereler, uygulama_ac), mcp_sunucu (başlık kilidi, wait_for), cli.
"""
from __future__ import annotations

import re

from .hata import Dur
from .i18n import _

MAKS_UZUNLUK = 300
MAKS_SINIRSIZ = 4  # tek desende en çok bu kadar sınırsız niceleyici (*, +, {n,})


def _niceleyici(d: str, i: int):
    """d[i:] bir niceleyici ile başlıyorsa → (sınırsız mı, tekrarlı mı (>1 kez olabilir), uzunluk); yoksa None.
    `?` tekrarlı değildir (0/1); tembel (`?`) / sahiplenici (`+`) ekini de tüketir."""
    if i >= len(d):
        return None
    c = d[i]
    if c in "*+":
        n = 1
        sinirsiz = tekrar = True
    elif c == "?":
        n = 1
        sinirsiz = tekrar = False
    elif c == "{":
        m = re.match(r"\{(\d*)(,?)(\d*)\}", d[i:])
        if not m or (not m.group(1) and not m.group(3)):
            return None  # niceleyici değil, düz '{'
        n = m.end()
        alt, virgul, ust = m.groups()
        sinirsiz = bool(virgul) and not ust
        if virgul:
            tekrar = sinirsiz or int(ust) > 1
        else:
            tekrar = int(alt) > 1
    else:
        return None
    if d[i + n:i + n + 1] in ("?", "+"):
        n += 1
    return sinirsiz, bool(tekrar), n


def _cakisan_secenekler(govde: str) -> bool:
    """Grup gövdesi düz sözcük seçeneklerinden oluşuyorsa (a|ab): biri ötekinin öneki ya da aynıysa True."""
    if "|" not in govde or re.search(r"[\\\[\](){}*+?.^$]", govde):
        return False
    s = govde.split("|")
    return any(i != j and (a == b or b.startswith(a)) for i, a in enumerate(s) for j, b in enumerate(s))


def sorun(desen: str) -> str | None:
    """Desen güvenli değilse nedeni (çevrilmiş kısa metin), değilse None. Geçersiz sözdizimini de bildirir."""
    if len(desen) > MAKS_UZUNLUK:
        return _("desen çok uzun ({n} karakter; en çok {maks})").format(n=len(desen), maks=MAKS_UZUNLUK)
    try:
        re.compile(desen)
    except re.error as e:
        return _("geçersiz desen: {hata}").format(hata=e)
    yigin = []  # her açık grup için [gövde başlangıcı, içinde tekrar var mı, içinde '|' var mı]
    sinirsiz = 0
    i, sinif = 0, False
    while i < len(desen):
        c = desen[i]
        if c == "\\":
            i += 2
            continue
        if sinif:
            sinif = c != "]"
            i += 1
            continue
        if c == "[":
            sinif = True
            i += 1
            if desen[i:i + 1] == "^":
                i += 1
            if desen[i:i + 1] == "]":
                i += 1
            continue
        if c == "(":
            yigin.append([i + 1, False, False])
            i += 1
            continue
        if c == "|" and yigin:
            yigin[-1][2] = True
            i += 1
            continue
        if c == ")":
            if not yigin:
                i += 1
                continue
            bas, icinde, secenek = yigin.pop()
            nic = _niceleyici(desen, i + 1)
            if nic and nic[1]:  # grup tekrarlanıyor
                if icinde:
                    return _("iç içe niceleyici (ör. (a+)+): geri izleme ile kilitlenebilir")
                if secenek and _cakisan_secenekler(desen[bas:i]):
                    return _("tekrarlanan grupta çakışan seçenekler (ör. (a|ab)+): geri izleme ile kilitlenebilir")
            if yigin and (icinde or (nic and nic[1])):
                yigin[-1][1] = True
            i += 1
            continue
        nic = _niceleyici(desen, i)
        if nic and i > 0:
            if nic[0]:
                sinirsiz += 1
            if yigin and nic[1]:
                yigin[-1][1] = True
            i += nic[2]
            continue
        i += 1
    if sinirsiz > MAKS_SINIRSIZ:
        return _("çok fazla sınırsız niceleyici ({n}; en çok {maks})").format(n=sinirsiz, maks=MAKS_SINIRSIZ)
    return None


def denetle(desen: str | None) -> str | None:
    """Ajanın verdiği desen güvenli değilse Dur(1, …) (kullanım hatası); güvenliyse aynen döndürür. None/boş: dokunmaz."""
    if not desen:
        return desen
    neden = sorun(str(desen))
    if neden:
        raise Dur(1, _("desen reddedildi: {neden}; daha basit bir başlık deseni ya da pencere kimliği ver").format(neden=neden))
    return desen
