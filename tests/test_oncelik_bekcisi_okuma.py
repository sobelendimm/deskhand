"""Öncelik bekçisi: cgroup.procs'un GEÇİCİ okuma hatası 'kafes boş' sayılmaz (0.9.0). Önceden surecler() her
OSError'da [] dönüyordu → tek bir EMFILE/EINTR bekçiyi çıkarıyor, arka plan masaüstü öncelik korumasız kalıyordu.

EKRANSIZ, gerçek cgroup'a dokunmaz (open / sleep / tur sahte).
Çalıştır:  python3 tests/test_oncelik_bekcisi_okuma.py"""
import errno
import io
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _yalitim  # noqa: F401,E402

from deskhand import oncelik_bekcisi as ob  # noqa: E402

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ek=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


def sahte_open(sonuc):
    def ac(yol, *a, **k):
        if isinstance(sonuc, BaseException):
            raise sonuc
        return io.StringIO(sonuc)
    return ac


print("1) surecler_oku: boş / kaldırılmış / geçici hata ayrılır")
ob.open = sahte_open("12\n34\n")
kontrol("okunan liste", ob.surecler_oku("/x") == [12, 34])
ob.open = sahte_open("")
kontrol("boş kafes → []", ob.surecler_oku("/x") == [])
ob.open = sahte_open(FileNotFoundError(errno.ENOENT, "yok"))
kontrol("kafes kaldırılmış (ENOENT) → []", ob.surecler_oku("/x") == [])
ob.open = sahte_open(OSError(errno.EMFILE, "çok fazla dosya"))
kontrol("geçici hata (EMFILE) → None (bilinmiyor)", ob.surecler_oku("/x") is None)
ob.open = sahte_open("12\nbozuk\n")
kontrol("bozuk içerik → None", ob.surecler_oku("/x") is None)
kontrol("surecler() eski sözleşme: hata → []", ob.surecler("/x") == [])
del ob.open

print("2) ana döngü: geçici hata bekçiyi çıkarmaz")
ob.time = types.SimpleNamespace(sleep=lambda s: None, monotonic=time.monotonic)  # yalnız bu modülde
turlar = []
ob.tur = lambda cg, g: turlar.append(cg) or 0
sira = iter([[1], None, None, [1], []])
ob.surecler_oku = lambda cg: next(sira)
kod = ob.main(["/x"])
kontrol("hata, hata, dolu, boş → yalnız boşta çıkar (0); ilk + 2 dolu tur", kod == 0 and len(turlar) == 3, f"kod={kod} tur={len(turlar)}")
sayac = {"n": 0}


def hep_hata(cg):
    sayac["n"] += 1
    return None


ob.surecler_oku = hep_hata
kod = ob.main(["/x"])
kontrol("süreğen okuma hatası → OKUMA_HATASI_AZAMI sonra 1 ile çıkar", kod == 1 and sayac["n"] == ob.OKUMA_HATASI_AZAMI,
        f"kod={kod} n={sayac['n']}")

print(f"\n{GECEN}/{TOPLAM} geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
