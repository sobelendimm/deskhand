"""Döngü kesici: aynı eylemi ardışık olarak sonuçsuz tekrarlayan ajanı yakalar (MCP sunucusu, oturum başına bellek).

Son eylemlerin halkası: (araç, pencere, hedef, eylem öncesi ekran, değişti mi). Aynı (araç, pencere, hedef)
eylemi ARDIŞIK olarak `degisti == False` ile:
  - UYARI_ESIK (3). sonuçsuz denemede çağıran uyarı üretir (`sayac()` ≥ UYARI_ESIK),
  - RED_ESIK (5) sonuçsuz denemeden sonra 6. özdeş çağrı yürütülmeden `DonguReddi` fırlar; farklı bir eylem yapılınca
    ya da ekran (son sonuçsuz denemedeki ekrana göre) değişince sayaç sıfırlanır.
Ekranı değiştiren meşru tekrarlar (aşağı ok ×10, kaydırma) `degisti=True` olduğundan sayacı sıfırlar. Ölçümsüz
eylem (`degisti=None`, ör. verify=False): sayacı ARTIRMAZ ve bozmaz; farklı hedefli herhangi bir eylem ise bozar.
Saf modül: MCP/ekran/arka uç bilmez; ekran karşılaştırması ve mesajlar çağırandadır."""
from __future__ import annotations

import threading
from collections import deque

UYARI_ESIK = 3
RED_ESIK = 5
HALKA = 24
NOKTA_TOLERANS = 6  # px: bu kadar yakın koordinatlar 'aynı hedef'


class Nokta:
    """Koordinat hedefi: `==` toleranslıdır (3 px kayık tekrar tıklama aynı hedef sayılır). Hash'lenemez."""
    __slots__ = ("x", "y")
    __hash__ = None

    def __init__(self, x, y):
        self.x, self.y = float(x), float(y)

    def __eq__(self, o):
        return isinstance(o, Nokta) and abs(self.x - o.x) <= NOKTA_TOLERANS and abs(self.y - o.y) <= NOKTA_TOLERANS

    def __repr__(self):
        return f"Nokta({self.x:.0f},{self.y:.0f})"


def metin_norm(s: str) -> str:
    """Hedef metni karşılaştırma için: küçük harf (Türkçe İ/I farkı gözetmeden), boşluklar tek."""
    return " ".join(str(s).replace("İ", "i").replace("I", "ı").lower().split())


class DonguReddi(Exception):
    """Aynı eylem RED_ESIK kez sonuçsuz kaldı; yenisi yürütülmedi. `sayi`: ardışık sonuçsuz deneme sayısı."""

    def __init__(self, sayi: int):
        super().__init__(sayi)
        self.sayi = sayi


class _Kayit:
    __slots__ = ("arac", "pencere", "hedef", "once", "degisti")

    def __init__(self, arac, pencere, hedef, once, degisti):
        self.arac, self.pencere, self.hedef, self.once, self.degisti = arac, pencere, hedef, once, degisti

    def ayni(self, arac, pencere, hedef) -> bool:
        return self.arac == arac and self.pencere == pencere and self.hedef == hedef


class DonguKesici:
    def __init__(self, uyari: int = UYARI_ESIK, red: int = RED_ESIK, halka: int = HALKA, ayni_ekran=None):
        """ayni_ekran(a, b) → bool: iki ekran özeti (kaydedilen `once` değerleri) aynı mı; verilmezse `==`."""
        self.uyari, self.red = uyari, red
        self._halka = deque(maxlen=max(halka, red + 2))
        self._kilit = threading.Lock()
        self._ayni_ekran = ayni_ekran or (lambda a, b: a == b)

    # -------- iç
    def _seri(self, arac, pencere, hedef) -> tuple[int, _Kayit | None]:
        """Sondan geriye: aynı eylemin ardışık sonuçsuz sayısı (+ o serinin ekranı bilinen son kaydı)."""
        n, son = 0, None
        for e in reversed(self._halka):
            if not e.ayni(arac, pencere, hedef):
                break
            if e.degisti is None:  # ölçümsüz: ne artırır ne bozar
                continue
            if e.degisti:
                break
            n += 1
            if son is None and e.once is not None:
                son = e
        return n, son

    # -------- dış
    def sayac(self, arac, pencere, hedef) -> int:
        with self._kilit:
            return self._seri(arac, pencere, hedef)[0]

    def kontrol(self, arac, pencere, hedef, simdiki_ekran=None) -> None:
        """Eylemden ÖNCE. Seri RED_ESIK'e ulaştıysa: ekran son sonuçsuz denemedekinden farklıysa seri silinir
        (devam), aynıysa (ya da ölçülemiyorsa) DonguReddi. simdiki_ekran: çağrılabilir (yalnız gerektiğinde ölçülür)
        ya da hazır değer."""
        with self._kilit:
            n, son = self._seri(arac, pencere, hedef)
            if n < self.red:
                return
            if son is not None and simdiki_ekran is not None:
                simdi = simdiki_ekran() if callable(simdiki_ekran) else simdiki_ekran
                if simdi is not None and not self._ayni_ekran(son.once, simdi):
                    self._halka.clear()  # ekran değişti: yeni durum, sayaç sıfır
                    return
            raise DonguReddi(n)

    def kaydet(self, arac, pencere, hedef, once, degisti) -> int:
        """Eylemden SONRA. degisti: True/False/None (ölçüm yok). → bu eylemin ardışık sonuçsuz sayısı (0 = yok)."""
        with self._kilit:
            if once is not None:  # yer tasarrufu: yalnız ekranı bilinen EN SON kaydın görüntüsü gerekir
                for e in self._halka:
                    e.once = None
            self._halka.append(_Kayit(arac, pencere, hedef, once, degisti))
            return self._seri(arac, pencere, hedef)[0] if degisti is False else 0

    def temizle(self) -> None:
        with self._kilit:
            self._halka.clear()
