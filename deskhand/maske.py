"""Alan değeri maskesinin ortak çekirdeği (masaüstü erisim._deger_temizle ve web._ayrinti_ekle AYNI kuralı kullanır).

İçerik kuralları ipucundan bağımsızdır: Luhn'lu kart numarası (tam genişlikli/ayırıcılı/görünmez karakterli dahil), kısa
rakam kodu (PIN/OTP/CVC), harf+rakam karışık kısa kod, birden çok alana bölünmüş kart numarası. Değerin kendisi hiçbir
yere döndürülmez; işlevler yalnız evet/hayır (ya da gizlenecek alan anahtarları) döner."""
from __future__ import annotations

import itertools
import re
import unicodedata

# Alanı tanıtan nitelikler (web: son anlık görüntüde hiçbiri yoksa değer doğrulanamaz). text-input-type TANITICI DEĞİL:
# Firefox her giriş alanına koyar, kısmi önbellekte yalnız o gelir (INCELEME-maske-R2-A bulgu 4, poc2 M).
TANITICI_NITELIK = ("id", "autocomplete", "placeholder", "placeholder-text")
# Zararsız alan ipucu: 4–9 haneli / harf+rakam karışık kod katmanı bu alanlarda uygulanmaz (ipucusuz 3–9 katmanında DEĞİL)
ZARARSIZ = re.compile(r"posta ?kodu|\bzip|postal|\badet|miktar|quantity|\bqty\b|\byil\b|\byili\b|\byear|telefon|phone|"
                      r"\btel\b|\bgsm\b")
_AYIRICI = re.compile(r"[\s\-./_]")
_RAKAM = re.compile(r"[0-9]+")
_KARISIK = re.compile(r"(?=[^\W_]*[0-9])(?=[^\W_]*[^\W\d_])[^\W_]+")
KISA_IPUCUSUZ = (3, 9)  # ipucusuz alanda rakam kodu boyu (eski 3–8 kuralı korunur, 9 eklenir)
KISA_RAKAM = (4, 9)  # her alanda (zararsız ipucu yoksa) rakam kodu boyu
KISA_KARISIK = (6, 8)  # her alanda (zararsız ipucu yoksa) harf+rakam karışık kod boyu
KART_HANE = (13, 19)
PENCERE_AZAMI = 6  # bölünmüş kart: ardışık en çok alan
PERMUTASYON_AZAMI = 4  # bölünmüş kart: karışık sıralı denetimde en çok alan


def normal(v: str) -> str:
    """NFKC + her Unicode ondalık rakam → ASCII + biçim (Cf) karakterleri silinir; boşluk kalır."""
    v = unicodedata.normalize("NFKC", v or "")
    cikti = []
    for c in v:
        if unicodedata.category(c) == "Cf":
            continue
        d = unicodedata.decimal(c, None)
        cikti.append(str(d) if d is not None and not c.isascii() else c)
    return "".join(cikti)


def kod_bicimi(v: str) -> str:
    """normal(v) + boşluk/tire/nokta/bölü/alt çizgi silinir."""
    return _AYIRICI.sub("", normal(v))


def kart_var(v: str) -> bool:
    """Değerde Luhn'lu kart numarası var mı (normalleştirilmiş metinde ya da ayırıcısız kod biçiminde)?"""
    from .guvenlik import kart_numarasi
    n = normal(v)
    if kart_numarasi(n):
        return True
    kb = _AYIRICI.sub("", n)
    return bool(_RAKAM.fullmatch(kb)) and KART_HANE[0] <= len(kb) <= KART_HANE[1] and bool(kart_numarasi(kb))


def zararsiz(ipuclari) -> bool:
    from .ocr import katla
    return any(ZARARSIZ.search(katla(str(i))) for i in ipuclari if i)


def kisa_kod(v: str, ipuclari=(), ipucusuz: bool = False) -> bool:
    """Değer PIN/OTP/CVC biçiminde kısa kod mu? ipucusuz (tanıtıcı nitelik yok) alanda 3–9 rakam her zaman; her alanda
    4–9 rakam ya da 6–8 karakter harf+rakam karışık, ipuçlarında zararsız desen (posta kodu, adet, yıl, telefon…) yoksa."""
    kb = kod_bicimi(v)
    rakam = bool(_RAKAM.fullmatch(kb))
    if ipucusuz and rakam and KISA_IPUCUSUZ[0] <= len(kb) <= KISA_IPUCUSUZ[1]:
        return True
    if not ((rakam and KISA_RAKAM[0] <= len(kb) <= KISA_RAKAM[1])
            or (KISA_KARISIK[0] <= len(kb) <= KISA_KARISIK[1] and _KARISIK.fullmatch(kb))):
        return False
    return not zararsiz(ipuclari)


def tanitici_var(nit) -> bool:
    """Nitelik sözlüğünde alanı tanıtan (boş olmayan) nitelik var mı?"""
    return isinstance(nit, dict) and any(nit.get(a) for a in TANITICI_NITELIK)


def _pencere_kart(parcalar: list[str]) -> bool:
    from .guvenlik import kart_numarasi
    return KART_HANE[0] <= sum(map(len, parcalar)) <= KART_HANE[1] and bool(kart_numarasi("".join(parcalar)))


def _ardisik(sira: list[tuple], gizli: set) -> None:
    for i in range(len(sira)):
        for j in range(i + 2, min(i + PENCERE_AZAMI, len(sira)) + 1):
            if _pencere_kart([r for _, r in sira[i:j]]):
                gizli.update(a for a, _ in sira[i:j])


def bolunmus_kart(alanlar: list[tuple]) -> list:
    """Birden çok alana bölünmüş kart numarası. alanlar: [(anahtar, ham değer, kutu (x, y, w, h) | None)].
    Kod biçimi yalnız rakam olan alanlar alınır (rakamsız/boş alan atlanır); 2–6 alanlık ardışık pencere toplam 13–19
    hane ve Luhn'lu ise pencerenin anahtarları. Sıralar: verilen (belge) sırası, kutu (y, x) sırası, ardışık 2–4
    alanlık pencere içi permütasyonlar (görsel sırası bilinmeyen karışık düzen). Parça boyu sınırı yok. → gizlenecek anahtarlar."""
    rakamli = []
    for anahtar, ham, kutu in alanlar:
        if not isinstance(ham, str):
            continue
        kb = kod_bicimi(ham)
        if _RAKAM.fullmatch(kb) and len(kb) < KART_HANE[1]:
            rakamli.append((anahtar, kb, kutu))
    gizli: set = set()
    if len(rakamli) < 2:
        return []
    _ardisik([(a, r) for a, r, _ in rakamli], gizli)
    kutulu = [t for t in rakamli if t[2]]
    if len(kutulu) >= 2:
        _ardisik([(a, r) for a, r, _ in sorted(kutulu, key=lambda t: (t[2][1], t[2][0]))], gizli)
    # karışık sıra: yalnız (belge sırasında) ardışık 2–4 alanlık pencerenin içinde permütasyon — bütün alanlar
    # üzerinde permütasyon ilgisiz sayı alanlarını (Luhn 1/10) birleştirip yanlış pozitif üretir
    for i in range(len(rakamli)):
        for j in range(i + 2, min(i + PERMUTASYON_AZAMI, len(rakamli)) + 1):
            for grup in itertools.permutations(rakamli[i:j]):
                if _pencere_kart([r for _, r, _ in grup]):
                    gizli.update(a for a, _, _ in grup)
    return [a for a, _, _ in rakamli if a in gizli]
