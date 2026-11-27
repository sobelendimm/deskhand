"""Masaüstü (AT-SPI, tarayıcı dışı) değer maskesi — web yoluyla aynı düzey (M3; RAPOR-MASKE-M3.md).
Sahte AT-SPI ögeleriyle erisim._ayrinti: Luhn'lu kart numarası, ipucusuz kısa rakam kodu (PIN/OTP), parola rolü
(niteliksiz), sıradan değer korunur. Kullanıcının ekranına dokunulmaz (D-Bus yok).

Çalıştır:  python3 tests/test_masaustu_maske.py"""
import sys
import types

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import erisim, maske  # noqa: E402

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
kontrol("masaüstü: parola rolü (niteliksiz) değeri okunmaz, uzunluk vermez → ***",
        deger("", "gizli-1", rol="password text") == "***" and deger("", "uzun-gizli-12", rol="password text") == "***")
kontrol("masaüstü: zararsız ad (Adet/Yıl/Posta kodu) kısa sayıyı açar", deger("Adet", "250") == "250"
        and deger("Yıl", "2026") == "2026" and deger("Posta kodu", "34000") == "34000")
kontrol("masaüstü: zararsız ad Luhn'lu kartı açmaz",
        deger("Adet", "4111111111111111") == "***" and deger("Posta kodu", "4111 1111 1111 1111") == "***")
kontrol("masaüstü: GTK nitelikleri (toolkit, keyshortcuts) kısa kodu açmaz",
        deger("Kod", "482913", {"toolkit": "gtk", "keyshortcuts": "Alt+K"}) == "***")

# Ortak çekirdek (maske.py): poc2 A–P karşılıkları (INCELEME-maske-R2-A; id'li "nötr" alan: ipucusuz değil)
for ad, v in (("A 9 hane OTP", "123456789"), ("B 6 hane", "482913"), ("C harf+rakam kod", "A7K9Q2"),
              ("D boşluklu kod", "482 913"), ("P tam genişlikli", "４８２９１３"), ("sıfır genişlikli", "48\u200b2913")):
    kontrol(f"çekirdek: id'li nötr alanda {ad} → kısa kod", maske.kisa_kod(v, ("A1", "f1"), ipucusuz=False))
kontrol("çekirdek: ipucusuz 3 hane kısa kod; id'li 3 hane değil",
        maske.kisa_kod("737", ("A1",), ipucusuz=True) and not maske.kisa_kod("737", ("A1", "f1"), ipucusuz=False))
kontrol("çekirdek: zararsız ipucu (adet/yıl/posta kodu) 4–9 katmanını atlar, ipucusuz 3–9 katmanını atlamaz",
        not maske.kisa_kod("2500", ("Adet", "adet"), ipucusuz=False) and not maske.kisa_kod("2026", ("Yıl",))
        and not maske.kisa_kod("34000", ("Posta kodu",)) and maske.kisa_kod("250", ("Adet",), ipucusuz=True))
kontrol("çekirdek: sıradan metin, 10 hane, 2 hane kısa kod değil",
        not any(maske.kisa_kod(v, ("Not", "not")) for v in ("Çınarlı 12", "1234567890", "12", "Ankara")))
kontrol("çekirdek: text-input-type tanıtıcı değil", not maske.tanitici_var({"text-input-type": "text", "tag": "input"})
        and maske.tanitici_var({"id": "f1"}))
kontrol("çekirdek: kart (ayırıcılı, tam genişlikli, sıfır genişlikli) var; Luhn'suz yok",
        maske.kart_var("4111-1111-1111-1111") and maske.kart_var("４１１１１１１１１１１１１１１１")
        and maske.kart_var("4111\u200b1111\u200b1111\u200b1111") and not maske.kart_var("4111 1111 1111 1112"))


def bol(parcalar, kutular=None):
    return maske.bolunmus_kart([(i, p, (kutular[i] if kutular else None)) for i, p in enumerate(parcalar)])


k = ["4111", "1111", "1111", "1111"]
for ad, parca, beklenen in (
        ("F 4+4+4+4", k, {0, 1, 2, 3}),
        ("G2 3+3+3+3+4", ["411", "111", "111", "111", "1111"], {0, 1, 2, 3, 4}),
        ("H 8+8", ["41111111", "11111111"], {0, 1}),
        ("I karışık sıra", [k[2], k[0], k[3], k[1]], {0, 1, 2, 3}),
        ("J araya x", [k[0], k[1], "x", k[2], k[3]], {0, 1, 3, 4}),
        ("K sıfır genişlikli parça", [p + "\u200b" for p in k], {0, 1, 2, 3}),
        ("N Amex 4+6+5", ["3782", "822463", "10005"], {0, 1, 2}),
        ("O 6+10", ["411111", "1111111111"], {0, 1})):
    sonuc = set(bol(parca))
    kontrol(f"bölünmüş kart: {ad} → hepsi gizli", beklenen <= sonuc, str(sorted(sonuc)))
kontrol("bölünmüş kart: Luhn'suz birleşim korunur", not bol(["4111", "1111", "1111", "1112"]))
kontrol("bölünmüş kart: kutu (y, x) sırası", set(bol([k[1], k[3], k[0], k[2]],
                                                    [(60, 0, 50, 20), (180, 0, 50, 20), (0, 0, 50, 20), (120, 0, 50, 20)]))
        == {0, 1, 2, 3})

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
