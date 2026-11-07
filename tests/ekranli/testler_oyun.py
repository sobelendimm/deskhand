#!/usr/bin/python3
"""Deskhand OYUN GİRDİSİ testleri: hold/bas (tuş basılı tut), click --hold/--repeat (tikla --basili/--tekrar),
drag/surukle, move/fare, batch/dizi (adımlar İngilizce ve Türkçe adlarla). Komutlar karışık İngilizce/Türkçe.
Qt test penceresindeki 'OYUN ALANI' tuş/fare olaylarını monotonik zamanla kaydeder; süreler, yollar,
kesintide bırakma, takılı tuş kalmaması ve dizi hızı ölçülür.

Çalıştır:  python3 tests/ekranli/testler_oyun.py   (~60 sn; klavye/fareye dokunma)"""
import os
import re
import subprocess
import sys
import time

import ortak  # DESKHAND_* geçici klasörler + deskhand komutu (Deskhand'den ÖNCE içe aktarılır)
from deskhand import yollar  # noqa: F401

DIZIN = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(ortak.IS, "oyun.log")
SONUC = []


def ekran(*a, girdi=None, insan=False):
    """insan=True: bu süreç İNSANI taklit ediyor (DESKHAND_INSAN_TAKLIDI) → kendisi insan önceliği için beklemez."""
    t = time.monotonic()
    env = dict(os.environ, DESKHAND_INSAN_TAKLIDI="1") if insan else None
    r = subprocess.run([*ortak.EKRAN, *a], capture_output=True, text=True, input=girdi, env=env)
    ortak.kod12_bildir(r.returncode, a, beklenen=insan)
    return r.returncode, r.stdout + r.stderr, time.monotonic() - t


def olaylar():
    with open(LOG) as f:
        return [l.split() for l in f.read().splitlines() if l.strip()]


def temizle():
    open(LOG, "w").close()


def kontrol(ad, kosul, ayrinti=""):
    SONUC.append((ad, bool(kosul)))
    print(f"{'GEÇTİ ' if kosul else 'KALDI!'} {ad}" + (f"  [{ayrinti}]" if ayrinti else ""), flush=True)


def bul(ol, tur, *ek):
    return [o for o in ol if o[0] == tur and all(o[1 + i] == v for i, v in enumerate(ek))]


def main():
    temizle()
    env = dict(os.environ, HAZIR_MS="500", LOG=LOG, BASLIK="ekran-test OYUN")
    pen = subprocess.Popen([sys.executable, os.path.join(DIZIN, "test_pencere.py")], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        K = None
        for _ in range(100):
            out = ortak.ara("ekran-test OYUN")
            if out:
                K = out[0]
                break
            time.sleep(0.05)
        assert K, "test penceresi açılmadı"
        time.sleep(0.8)
        kod, out, _ = ekran("read", K, "OYUN ALANI", "--stay")
        m = re.search(r"#1 \((\d+),(\d+)\)", out)
        assert m, f"oyun alanı bulunamadı: {out}"
        cx, cy = int(m.group(1)), int(m.group(2))
        ekran("tikla", K, str(cx), str(cy))  # odak oyun alanına
        time.sleep(0.2)
        temizle()

        # T1 tuş basılı tut
        kod, out, t = ekran("hold", K, "w", "1.0")
        ol = olaylar()
        b, r = bul(ol, "tus_bas", "w"), bul(ol, "tus_birak", "w")
        sure = float(r[0][2]) - float(b[0][2]) if b and r else -1
        kontrol("hold w 1.0 sn: tek basma + tek bırakma, süre ≈1,0", kod == 0 and len(b) == 1 and len(r) == 1 and 0.85 <= sure <= 1.2,
                f"basılı {sure:.3f} sn, komut {t:.2f} sn")
        temizle()

        # T2 iki tuş birden
        kod, out, t = ekran("bas", K, "w+d", "0.6")
        ol = olaylar()
        ok = all(bul(ol, "tus_bas", k) and bul(ol, "tus_birak", k) for k in ("w", "d"))
        kontrol("bas w+d 0.6: iki tuş da basıldı ve bırakıldı", kod == 0 and ok, f"{[o[0] + ' ' + o[1] for o in ol]}")
        temizle()

        # T3 basılıyken insan fareyi oynatır → hemen bırak (12), takılı tuş yok
        yp = subprocess.Popen([*ortak.EKRAN, "bas", K, "w", "4"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.5)
        ekran("fare", K, str(cx - 150), str(cy + 20), insan=True)  # "insan"
        t_insan = time.monotonic()
        out_b, err_b = yp.communicate(timeout=15)
        ol = olaylar()
        r = bul(ol, "tus_birak", "w")
        gecikme = float(r[0][2]) - t_insan if r else 99
        kontrol("bas sırasında fare oynadı → 12, tuş HEMEN bırakıldı", yp.returncode == 12 and len(r) == 1 and gecikme < 0.3,
                f"kod {yp.returncode}, bırakma insandan {gecikme:+.3f} sn sonra")
        temizle()

        # T4 fare düğmesi basılı tut (kazma)
        kod, out, t = ekran("click", K, str(cx), str(cy), "right", "--hold", "0.8")
        ol = olaylar()
        b, r = bul(ol, "fare_bas", "sag"), bul(ol, "fare_birak", "sag")
        sure = float(r[0][4]) - float(b[0][4]) if b and r else -1
        kontrol("click right --hold 0.8: basılı süre ≈0,8", kod == 0 and len(b) == 1 and len(r) == 1 and 0.65 <= sure <= 1.1,
                f"basılı {sure:.3f} sn")
        temizle()

        # T5 sürükle: başlangıç/bitiş farkı ekran farkına eşit, arada hareket olayları
        p1, p2 = (cx - 220, cy - 30), (cx + 160, cy + 40)
        kod, out, t = ekran("drag", K, *map(str, (*p1, *p2)), "left", "--duration", "0.4")
        ol = olaylar()
        b, r = bul(ol, "fare_bas", "sol"), bul(ol, "fare_birak", "sol")
        hareket = [o for o in ol if o[0] == "fare_surukle"]
        if b and r:
            dx, dy = int(r[0][2]) - int(b[0][2]), int(r[0][3]) - int(b[0][3])
            ofs = (int(b[0][2]) - p1[0], int(b[0][3]) - p1[1])  # alan koordinatı = ekran koordinatı + ofs
        else:
            dx = dy = 0
            ofs = (0, 0)
        kontrol("drag: bas→bırak farkı = hedef farkı (±2 px), ≥5 ara hareket",
                kod == 0 and abs(dx - (p2[0] - p1[0])) <= 2 and abs(dy - (p2[1] - p1[1])) <= 2 and len(hareket) >= 5,
                f"fark ({dx},{dy}) beklenen ({p2[0] - p1[0]},{p2[1] - p1[1]}), {len(hareket)} hareket, {t:.2f} sn")
        temizle()

        # T6 fare: tıklamadan gezdir
        q = (cx + 90, cy - 20)
        kod, out, t = ekran("move", K, *map(str, q))
        ol = olaylar()
        ust = [o for o in ol if o[0] == "fare_ustunde"]
        son = (int(ust[-1][1]), int(ust[-1][2])) if ust else None
        kontrol("move: noktaya gitti (±2 px), tıklama YOK",
                kod == 0 and son and abs(son[0] - (q[0] + ofs[0])) <= 2 and abs(son[1] - (q[1] + ofs[1])) <= 2 and not bul(ol, "fare_bas"),
                f"son konum {son}, beklenen {(q[0] + ofs[0], q[1] + ofs[1])}")
        temizle()

        # T7 tekrarlı tıklama
        kod, out, t = ekran("tikla", K, str(cx), str(cy), "--tekrar", "3")  # Türkçe ad + seçenek
        ol = olaylar()
        kontrol("tikla --tekrar 3 (Türkçe): 3 basma + 3 bırakma", kod == 0 and len(bul(ol, "fare_bas", "sol")) == 3 and len(bul(ol, "fare_birak", "sol")) == 3,
                f"{t:.2f} sn")
        temizle()

        # T8 batch: tek dotool kurulumu → hız; olay sırası doğru (adımlar İngilizce adlarla)
        adimlar = [f"click {cx} {cy}", "hold w 0.3", f"move {q[0]} {q[1]}", "sleep 0.2", "key e"]
        kod, out, t_dizi = ekran("batch", K, girdi="\n".join(adimlar))
        ol = olaylar()
        sira = [o[0] + (" " + o[1] if o[0].startswith("tus") or o[0] in ("fare_bas", "fare_birak") else "") for o in ol
                if o[0] in ("fare_bas", "fare_birak", "tus_bas", "tus_birak")]
        beklenen = ["fare_bas sol", "fare_birak sol", "tus_bas w", "tus_birak w", "tus_bas e", "tus_birak e"]
        temizle()
        t0 = time.monotonic()
        for a_ in adimlar:
            parca = a_.split()
            if parca[0] in ("uyu", "sleep"):
                time.sleep(float(parca[1]))
            else:
                ekran(parca[0], K, *parca[1:])
        t_ayri = time.monotonic() - t0
        kontrol("batch (İngilizce adımlar): olay sırası doğru", kod == 0 and sira == beklenen, f"{sira}")
        kontrol("batch: ayrı komutlardan ≥1,5 sn hızlı (tek dotool kurulumu)", t_dizi < t_ayri - 1.5,
                f"dizi {t_dizi:.2f} sn, ayrı ayrı {t_ayri:.2f} sn")
        temizle()

        # T9 dizi hatalı adımda durur, sonrakiler ÇALIŞMAZ
        kod, out, t = ekran("dizi", K, girdi="tus a\ntikla 5000 50\ntus b")
        ol = olaylar()
        kontrol("dizi: 2. adım pencere dışı → 2, 3. adım çalışmadı", kod == 2 and bul(ol, "tus_bas", "a") and not bul(ol, "tus_bas", "b"),
                f"kod {kod}")
        temizle()

        # T10 dizi yanlış başlık → hiçbir girdi
        kod, out, t = ekran("-b", "TENGA", "dizi", K, girdi="tus a\ntus b")
        kontrol("dizi -b yanlış başlık → 4, hiçbir olay yok", kod == 4 and not olaylar(), f"kod {kod}, {t:.2f} sn")
        temizle()

        # T11 dizi + insan önceliği: adımlar arasında insan fareyi oynatırsa durgunluğu bekleyip DEVAM eder
        yp = subprocess.Popen([*ortak.EKRAN, "dizi", K], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        yp.stdin.write("bas w 0.2\nuyu 2.0\ntus x\n")
        yp.stdin.close()
        time.sleep(1.6)
        ekran("fare", K, str(cx + 40), str(cy + 40), insan=True)  # "insan" uyu sırasında fareyi oynatır, sonra durur
        t_insan = time.monotonic()
        yp.wait(timeout=30)
        ol = olaylar()
        x = bul(ol, "tus_bas", "x")
        bekleme = float(x[0][2]) - t_insan if x else -1
        kontrol("dizi + insan önceliği: insan durduktan ≥1,4 sn sonra devam etti", yp.returncode == 0 and x and bekleme >= 1.4,
                f"kod {yp.returncode}, 'x' insandan {bekleme:.2f} sn sonra")

        # T12 bütünlük: takılı tuş/düğme yok (tüm oturum)
        ol_hepsi = olaylar()
        tb = {k: len(bul(ol_hepsi, "tus_bas", k)) - len(bul(ol_hepsi, "tus_birak", k)) for k in {o[1] for o in ol_hepsi if o[0] == "tus_bas"}}
        fb = {k: len(bul(ol_hepsi, "fare_bas", k)) - len(bul(ol_hepsi, "fare_birak", k)) for k in ("sol", "sag", "orta")}
        kontrol("takılı tuş/düğme YOK (her basmanın bırakması var)", all(v == 0 for v in tb.values()) and all(v == 0 for v in fb.values()),
                f"tuş {tb}, fare {fb}")
    finally:
        pen.terminate()
        pen.wait()

    gecen = sum(1 for _, ok in SONUC if ok)
    print(f"\n{gecen}/{len(SONUC)} oyun girdisi testi geçti")
    sys.exit(0 if gecen == len(SONUC) else 1)


if __name__ == "__main__":
    main()
