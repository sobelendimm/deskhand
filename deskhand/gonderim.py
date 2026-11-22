"""Bir eylem sırasında GERÇEKTEN gönderilen girdinin sayacı (iş parçacığına özgü): MCP sonuç sözleşmesinin `sent` alanı.

Hata olduğunda ajan "bir şey gönderildi mi" bilmeli: `nothing_sent` (hiçbir girdi satırı/erişilebilirlik eylemi
gitmedi; tekrar denemek güvenli) ya da `maybe_partial` (en az biri gitti: yazının bir kısmı yazılmış, imleç taşınmış
olabilir). Sayaç girdinin GÖNDERİLDİĞİ tek yerlerde artar:
- `api.arka()` girdi nesnesinin `gonder()`/`ham()` çağrısı başarıyla döndüğünde (iki arka uç, girdi merkezi dahil),
- erişilebilirlik eylemi / değer yazma çağrılmadan HEMEN önce (erisim.py: çağrı yarıda kalsa da "belki gitti").
Bırakma satırları (`zorla`: keyup/buttonup) sayılmaz: basılı olanı geri alır, yeni etki üretmez.
Saf modül: ekran/arka uç bilmez."""
from __future__ import annotations

import threading

_YEREL = threading.local()


def sifirla() -> None:
    """Yeni eylem başlıyor: sayaç ve notlar sıfır."""
    _YEREL.sayi = 0
    _YEREL.notlar = {}


def artir(n: int = 1) -> None:
    _YEREL.sayi = getattr(_YEREL, "sayi", 0) + n


def sayi() -> int:
    return getattr(_YEREL, "sayi", 0)


def durum() -> str:
    """→ "nothing_sent" | "maybe_partial" (son sifirla()'dan beri)."""
    return "maybe_partial" if sayi() else "nothing_sent"


def not_yaz(ad: str, deger) -> None:
    """Çekirdeğin üst katmana bıraktığı küçük ölçüm notu (ör. değer yazma geri okundu mu: "dogrulandi")."""
    if not hasattr(_YEREL, "notlar"):
        _YEREL.notlar = {}
    _YEREL.notlar[ad] = deger


def not_al(ad: str, varsayilan=None):
    return getattr(_YEREL, "notlar", {}).get(ad, varsayilan)
