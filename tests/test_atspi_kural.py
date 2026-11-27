"""Erişilebilirlik kural testi (UX turu G1): panel GÖRÜNMEZ (yalıtık KWin) masaüstünde açılır, her sekmenin AT-SPI
ağacı AYRI bir süreçte (AT_SPI_BUS_ADDRESS = masaüstünün özel a11y veri yolu) okunur ve kurallar denetlenir:
adsız düğme/giriş, boş (yalnız boşluk) ad, tıklama hedefi < 24×24, odak alamayan etkin etkileşimli öge.

Bugünkü ihlaller tests/atspi_bilinen.json "bilinen" listesindedir (UX görevleri listeyi boşaltır): listede olmayan
YENİ ihlal → KALDI; düzelen bilinen ihlal bilgi olarak yazılır (listeden silinmesi görev raporunda). Liste yoksa
(ya da ATSPI_BILINEN_YAZ=1) bugünkü ihlallerle yazılır ve "BİLİNEN YAZILDI" denir. Kullanıcının gerçek oturumuna,
gerçek ekranına, gerçek a11y veri yoluna dokunulmaz (masaüstü + veri yolu takıma özel; gerçek ekran kilidi açık).

Çalıştır:  python3 tests/test_atspi_kural.py   (ya da tools/test_kos.py test_atspi_kural)"""
import collections
import json
import os
import shutil
import subprocess
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
import _gorsel as G

KOK = _yalitim.KOK
BILINEN = os.path.join(KOK, "tests", "atspi_bilinen.json")
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


# =========================================================================== 1) kurallar (sahte ağaç)
def oge(rol, ad, w=80, h=30, odak=True, etkin=True, gorunur=True, yol="frame:X"):
    return {"rol": rol, "ad": ad, "w": w, "h": h, "odak": odak, "etkin": etkin, "gorunur": gorunur, "yol": yol}


sahte = [
    oge("push button", "Tamam"),                         # temiz
    oge("text", "Ad"),                                   # temiz
    oge("label", ""),                                    # etkileşimsiz: kural dışı
    oge("push button", "", gorunur=False),               # görünmüyor: kural dışı
    oge("push button", ""),                              # ADSIZ_DUGME
    oge("text", None),                                   # ADSIZ_GIRIS
    oge("push button", "   "),                           # BOS_AD
    oge("push button", "x", w=16, h=16),                 # HEDEF_KUCUK
    oge("push button", "Odak almaz", odak=False),        # ODAK_YOK
    oge("push button", "Pasif", odak=False, etkin=False),  # devre dışı: odak kuralı dışı
]
bulunan = collections.Counter(i["kural"] for i in G.ihlaller(sahte))
for k in ("ADSIZ_DUGME", "ADSIZ_GIRIS", "BOS_AD", "HEDEF_KUCUK", "ODAK_YOK"):
    kontrol(f"kural: sahte ağaçta {k} tam 1 ihlal", bulunan[k] == 1, str(dict(bulunan)))
kontrol("kural: temiz/etkileşimsiz/görünmez/devre dışı öğelerde yanlış alarm yok", sum(bulunan.values()) == 5,
        str(dict(bulunan)))
kontrol("kural: anahtar koordinat içermez (kayma yeni ihlal sayılmaz)",
        G.anahtar(G.ihlaller([oge("push button", "", w=90)])[0]) == G.anahtar(G.ihlaller([oge("push button", "")])[0]))

# =========================================================================== 2) gerçek panel (yalıtık KWin)
# Görünmez masaüstü Xvfb'yi kullanıcı bellek kafesinde ister (ürün kuralı). Kafes kurulamayan CI'da bölüm atlanır;
# yerelde yoklama hep None döner, bölüm tam koşar.
_kafes_eksik = _yalitim.bellek_kafesi_eksigi()
if _kafes_eksik:
    _yalitim.atla("gerçek panel AT-SPI denetimi (görünmez masaüstü)", _kafes_eksik)
    print(f"\n{gecen}/{toplam} AT-SPI kural testi geçti")
    sys.exit(0 if gecen == toplam else 1)

from deskhand import masaustu, yollar  # noqa: E402

PAY = _yalitim.PAYLASIM
LOG, KOMUT = os.path.join(PAY, "panel.log"), os.path.join(PAY, "komut")
KOD = os.path.join(PAY, "kod")


def log():
    try:
        with open(LOG) as f:
            return f.read().splitlines()
    except OSError:
        return []


def bekle_satir(onek, sure=20.0):
    son = time.monotonic() + sure
    while time.monotonic() < son:
        s = [x for x in log() if x.startswith(onek)]
        if s:
            return s[-1]
        time.sleep(0.05)
    return None


def komut(k):
    with open(KOMUT + ".y", "w") as f:
        f.write(k)
    os.replace(KOMUT + ".y", KOMUT)


# bwrap ad alanında ev dizini görünmez: deskhand paketi paylaşıma kopyalanır (tests/ salt okunur görünür)
shutil.copytree(os.path.join(KOK, "deskhand"), os.path.join(KOD, "deskhand"),
                ignore=shutil.ignore_patterns("__pycache__"))
panel_env = {"LOG": LOG, "KOMUT": KOMUT, "GORSEL_KOD": KOD, "QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1",
             "DESKHAND_ANAHTARLIK": "kapali", "DESKHAND_DIL": "tr", "QT_SCALE_FACTOR": "1.0"}
for ad in ("CONFIG", "STATE", "CACHE", "DATA", "RUNTIME"):
    y = os.path.join(PAY, "d", ad.lower())
    os.makedirs(y, mode=0o700)
    panel_env[f"DESKHAND_{ad}_DIR"] = y

os.makedirs(yollar.runtime_dir(), mode=0o700, exist_ok=True)
os.chmod(yollar.runtime_dir(), 0o700)
t0 = time.monotonic()
d = masaustu.masaustu_baslat()
ihlal_say = collections.Counter()
ornek = {}
okunan = []
try:
    adres = (masaustu.durum(saglik=False) or {}).get("a11y_adres") or d.get("a11y_adres")
    kontrol("masaüstü: özel a11y veri yolu adresi var", bool(adres), str(d.get("uyarilar")))
    masaustu.baslat([sys.executable, "-I", os.path.join(KOK, "tests", "_gorsel.py"), "panel"], panel_env)
    hazir = bekle_satir("hazir")
    kontrol("panel: görünmez masaüstünde açıldı", hazir is not None, "\n".join(log()[-5:]))
    n_sekme = int(hazir.split()[1]) if hazir else 0
    env = {**os.environ, "AT_SPI_BUS_ADDRESS": adres or ""}
    for i in range(n_sekme):
        komut(f"sekme {i}")
        s = bekle_satir(f"sekme {i} ", 10)
        r = subprocess.run([sys.executable, "-I", os.path.join(KOK, "tests", "_gorsel.py"), "atspi-oku", "Deskhand"],
                           env=env, capture_output=True, text=True, timeout=30)
        try:
            agac = json.loads(r.stdout)
        except ValueError:
            agac = {"hata": (r.stdout + r.stderr)[-300:]}
        ad = s.split(" ", 2)[2] if s else f"sekme{i}"
        if not kontrol(f"AT-SPI: '{ad}' ağacı okundu", "ogeler" in agac and agac["n"] > 5, str(agac.get("hata"))):
            continue
        okunan.append((ad, agac["n"], agac["sure_ms"]))
        sekme_say = collections.Counter()
        for ih in G.ihlaller(agac["ogeler"]):
            k = G.anahtar(ih)
            sekme_say[k] += 1
            ornek.setdefault(k, {**ih, "sekme": ad})
        for k, n in sekme_say.items():  # sekme dışı öğeler (durum şeridi) her okumada görünür: en büyük sayı
            ihlal_say[k] = max(ihlal_say[k], n)
finally:
    komut("cik")
    masaustu.masaustu_durdur()
print("OKUNAN: " + ", ".join(f"{a} {n} öge {ms} ms" for a, n, ms in okunan) +
      f" — toplam {time.monotonic() - t0:.1f} sn", flush=True)

if not okunan:
    print("ENGEL: panelin AT-SPI ağacı okunamadı (yukarıdaki KALDI satırları)", flush=True)
else:
    guncel = {k: ihlal_say[k] for k in sorted(ihlal_say)}
    if os.environ.get("ATSPI_BILINEN_YAZ") == "1" or not os.path.exists(BILINEN):
        with open(BILINEN, "w", encoding="utf-8") as f:
            json.dump({"aciklama": "Bugünkü AT-SPI ihlalleri (G1, 27 Kas). UX görevleri listeyi boşaltır; yeni ihlal "
                                   "test_atspi_kural'da KALDI. Biçim: 'kural|rol|ad|ata zinciri' → adet.",
                       "ihlaller": guncel}, f, ensure_ascii=False, indent=1)
            f.write("\n")
        print(f"BİLİNEN YAZILDI: {sum(guncel.values())} ihlal → {BILINEN}", flush=True)
    with open(BILINEN, encoding="utf-8") as f:
        bilinen = json.load(f)["ihlaller"]
    yeni = {k: n - bilinen.get(k, 0) for k, n in guncel.items() if n > bilinen.get(k, 0)}
    duzelen = {k: n - guncel.get(k, 0) for k, n in bilinen.items() if guncel.get(k, 0) < n}
    for k, n in yeni.items():
        o = ornek[k]
        print(f"  YENİ İHLAL ×{n}: {o['kural']} rol={o['rol']!r} ad={o['ad']!r} {o['boyut']} sekme={o['sekme']} "
              f"yol={o['yol']}", flush=True)
    for k, n in duzelen.items():
        print(f"  DÜZELDİ ×{n} (atspi_bilinen.json'dan silin): {k}", flush=True)
    _ortam_farki = _yalitim.yazi_ortami_farki()  # hedef boyutu (HEDEF_KUCUK) yazı tipinin ölçüsüne bağlı
    if _ortam_farki and yeni:
        _yalitim.atla(f"AT-SPI: bilinen dışında yeni ihlal yok ({sum(yeni.values())} yeni)", _ortam_farki)
    else:
        kontrol(f"AT-SPI: bilinen dışında yeni ihlal yok (bugün {sum(guncel.values())}, bilinen {sum(bilinen.values())})",
                not yeni, f"{sum(yeni.values())} yeni")

print(f"\n{gecen}/{toplam} AT-SPI kural testi geçti")
sys.exit(0 if gecen == toplam else 1)
