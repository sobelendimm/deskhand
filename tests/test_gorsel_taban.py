"""Görsel taban (UX turu G1): panelin her sekmesi (TR açık 1.0, TR koyu 1.0, EN açık 1.25), DUR durumu ve onay
diyaloğunun 3 türü SABİT ortamda (env -i karşılığı, offscreen, Fusion, sabit ölçek/dil/saat) çekilir ve
tests/gorsel_taban/ altındaki referansla BİREBİR (eşik 0) kıyaslanır.

  - taban yoksa yazılır ve "TABAN YAZILDI" denir (ilk koşu); varsa kıyaslanır, fark → KALDI + fark PNG'si
    (GORSEL_FARK dizinine; verilmezse geçici dizine, yolu yazılır)
  - bilinçli görünüm değişikliğinde: GORSEL_GUNCELLE=1 python3 tests/test_gorsel_taban.py (taban yeniden yazılır;
    görev raporu "taban güncellendi: <dosyalar> + neden" yazar)

Çalıştır:  python3 tests/test_gorsel_taban.py   (ya da tools/test_kos.py test_gorsel_taban)"""
import concurrent.futures as cf
import os
import shutil
import sys
import tempfile

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
import _gorsel as G

TABAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gorsel_taban")
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


# =========================================================================== 1) karşılaştırıcı (birim)
from PIL import Image  # noqa: E402

g = os.path.join(_yalitim.GECICI, "birim")
os.makedirs(g)
a = Image.new("RGB", (40, 30), (200, 200, 200))
a.save(os.path.join(g, "a.png"))
a.save(os.path.join(g, "a2.png"), compress_level=0)
b = a.copy()
b.putpixel((7, 9), (200, 200, 201))
b.save(os.path.join(g, "b.png"))
fy = os.path.join(g, "fark.png")
kontrol("kıyas: aynı görüntü → 0 fark, fark PNG'si yazılmaz",
        G.kiyasla(os.path.join(g, "a.png"), os.path.join(g, "a2.png"), fy) == 0 and not os.path.exists(fy))
n = G.kiyasla(os.path.join(g, "a.png"), os.path.join(g, "b.png"), fy)
kontrol("kıyas: tek pikselde 1 birimlik değişiklik → 1 fark + fark PNG'si (değişen piksel kırmızı)",
        n == 1 and os.path.exists(fy) and Image.open(fy).convert("RGB").getpixel((7, 9)) == (255, 0, 0), str(n))
kontrol("kıyas: boyut farkı → -1", G.kiyasla(a, Image.new("RGB", (41, 30)), None) == -1)

# =========================================================================== 2) çekim + taban kıyası
guncelle = os.environ.get("GORSEL_GUNCELLE") == "1"
cikti = os.path.join(_yalitim.GECICI, "cekim")
fark_dizin = os.environ.get("GORSEL_FARK") or tempfile.mkdtemp(prefix="gorsel-fark-")
os.makedirs(cikti)


def _is(i, varyant):
    ev = os.path.join(_yalitim.GECICI, f"ev{i}")
    return G.cek(cikti, varyant, ev) if varyant != "diyalog" else G.diyalog_cek(cikti, "tr", ev)


with cf.ThreadPoolExecutor(3) as h:
    sonuclar = list(h.map(lambda iv: _is(*iv), enumerate([*G.VARYANTLAR, "diyalog"])))
for v, r in zip([*G.VARYANTLAR, "diyalog"], sonuclar, strict=True):
    ad = v if isinstance(v, str) else v[0]
    kontrol(f"çekim: {ad} süreci başarılı", r.returncode == 0 and "CEKILDI" in r.stdout,
            f"rc {r.returncode}: {(r.stdout + r.stderr)[-400:]}")

beklenen = sum(1 if v[5] else 6 for v in G.VARYANTLAR) + len(G.DIYALOGLAR)
pngler = sorted(f for f in os.listdir(cikti) if f.endswith(".png"))
kontrol(f"çekim: {beklenen} ekran (6 sekme × 3 varyant + DUR + 3 diyalog)", len(pngler) == beklenen, str(len(pngler)))

os.makedirs(TABAN, exist_ok=True)
yazilan, farkli = [], []
ortam_farki = None if guncelle else _yalitim.yazi_ortami_farki()
if ortam_farki:  # aynı kod başka yazı tipiyle başka pikseller verir: birebir kıyas bu makinede anlamsız
    _yalitim.atla(f"taban: {len(pngler)} ekran birebir kıyası", ortam_farki)
elif guncelle or not os.path.exists(_yalitim.REFERANS_ORTAM):
    with open(_yalitim.REFERANS_ORTAM, "w", encoding="utf-8") as f_:
        f_.write(_yalitim.yazi_ortami() + "\n")
for f in ([] if ortam_farki else pngler):
    t, y = os.path.join(TABAN, f), os.path.join(cikti, f)
    if guncelle or not os.path.exists(t):
        shutil.copyfile(y, t)
        yazilan.append(f)
        continue
    fp = os.path.join(fark_dizin, f.replace(".png", ".fark.png"))
    n = G.kiyasla(t, y, fp)
    if n:
        shutil.copyfile(y, os.path.join(fark_dizin, f.replace(".png", ".yeni.png")))
        farkli.append(f"{f}: {'boyut farklı' if n < 0 else f'{n} piksel'}")
    kontrol(f"taban: {f} birebir", n == 0, f"{'boyut farklı' if n < 0 else f'{n} piksel'} → {fp}")
if yazilan:
    print(f"TABAN YAZILDI: {len(yazilan)} dosya → {TABAN}", flush=True)
fazla = sorted(set(f for f in os.listdir(TABAN) if f.endswith(".png")) - set(pngler))
kontrol("taban: çekilmeyen eski taban dosyası yok", not fazla, ", ".join(fazla))
if farkli:
    print(f"FARK: {len(farkli)} ekran — fark PNG'leri {fark_dizin}", flush=True)
elif not os.environ.get("GORSEL_FARK"):
    shutil.rmtree(fark_dizin, True)

print(f"\n{gecen}/{toplam} görsel taban testi geçti")
sys.exit(0 if gecen == toplam else 1)
