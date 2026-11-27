"""Masaüstü (AT-SPI, tarayıcı dışı) değer maskesi — web yoluyla aynı düzey (M3; RAPOR-MASKE-M3.md).
Sahte AT-SPI ögeleriyle erisim._ayrinti: Luhn'lu kart numarası, ipucusuz kısa rakam kodu (PIN/OTP), parola rolü
(niteliksiz), sıradan değer korunur. Kullanıcının ekranına dokunulmaz (D-Bus yok).

Çalıştır:  python3 tests/test_masaustu_maske.py"""
import sys
import types

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import erisim  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


class SahteDurum:
    def contains(self, _s):
        return False


S = types.SimpleNamespace()  # durum sabiti yok → GOZLEM_DURUMLARI atlanır
Atspi = types.SimpleNamespace(Text=types.SimpleNamespace(get_text=lambda ti, a, b: ti))


class Oge:
    """Qt/GTK giriş alanı: ad, açıklama, nitelikler (Qt'de çoğu zaman {}), metin."""

    def __init__(self, ad, metin, nit=None, aciklama=""):
        self.ad, self.metin, self.nit, self.aciklama = ad, metin, {} if nit is None else nit, aciklama

    def get_name(self):
        return self.ad

    def get_description(self):
        return self.aciklama

    def get_attributes(self):
        return self.nit

    def get_text_iface(self):
        return self.metin

    def get_value_iface(self):
        return None

    def get_action_iface(self):
        return None


def deger(ad, metin, nit=None, rol="text"):
    return erisim._ayrinti(Atspi, Oge(ad, metin, nit), rol, SahteDurum(), S).get("deger")


kontrol("masaüstü: Luhn'lu kart numarası (adı sade) → ***", deger("Not", "4111 1111 1111 1111") == "***",
        str(deger("Not", "4111 1111 1111 1111")))
kontrol("masaüstü: ipucusuz 4 haneli PIN → ***", deger("Giriş", "4829") == "***", str(deger("Giriş", "4829")))
kontrol("masaüstü: ipucusuz 6 haneli OTP → ***", deger("Kod", "482913") == "***", str(deger("Kod", "482913")))
kontrol("masaüstü: tam genişlikli rakam OTP → ***", deger("A1", "４８２９１３") == "***")
kontrol("masaüstü: sıradan metin korunur", deger("Şehir", "Çınarlı") == "Çınarlı", str(deger("Şehir", "Çınarlı")))
kontrol("masaüstü: parola rolü (niteliksiz) değeri okunmaz", deger("", "gizli-1", rol="password text") is None)

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
