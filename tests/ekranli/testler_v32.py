#!/usr/bin/python3
"""Deskhand v3.2 GUI testleri: klavye insan önceliği, open/ac, flow/akis, erişilebilirlik ağacı (tree/agac,
click-element/ogeye-tikla). Komutlar karışık İngilizce/Türkçe adlarla.
Pencere açar ve girdi gönderir → çalışırken klavye/fareye DOKUNMA (dokunursan testler 12 ile durur: doğru davranış).
İnsanı taklit eden süreçler DESKHAND_INSAN_TAKLIDI=1 ile çalışır. Ham dotool YOK.
Çalıştır: python3 tests/ekranli/testler_v32.py [klavye ac akis erisim]"""
import os
import re
import subprocess
import sys
import time

import ortak  # DESKHAND_* geçici klasörler + deskhand komutu (Deskhand'den ÖNCE içe aktarılır)
from deskhand import yollar  # noqa: F401

DIZIN = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(ortak.IS, "test_v32.log")
AKIS_LOG = os.path.join(ortak.IS, "akis.log")
SONUC = []
TAKLIT = dict(os.environ, DESKHAND_INSAN_TAKLIDI="1")


def ekran(*a, env=None, sure=120, bek12=False):
    """bek12: bu çağrının 12 (insan önceliği) dönmesi testin beklediği şey (hepsi.sh'ye bildirilmez)."""
    t = time.monotonic()
    r = subprocess.run([*ortak.EKRAN, *a], capture_output=True, text=True, env=env, timeout=sure)
    ortak.kod12_bildir(r.returncode, a, beklenen=bek12 or env is TAKLIT)
    return r.returncode, r.stdout + r.stderr, time.monotonic() - t


def kontrol(ad, kosul, ayrinti=""):
    SONUC.append((ad, bool(kosul)))
    print(f"{'GEÇTİ ' if kosul else 'KALDI!'} {ad}" + (f"  [{ayrinti}]" if ayrinti else ""), flush=True)


def olaylar(yol=LOG):
    try:
        return open(yol).read().splitlines()
    except OSError:
        return []


def pencere_ac(betik, baslik, **ek):
    """Pencereyi `ekran ac --komut` ile açar (ac komutunun kendisi de böylece sınanır) → kimlik."""
    env = dict(os.environ, BASLIK=baslik, LOG=ek.pop("log", LOG), HAZIR_MS="300", **ek)
    kod, out, t = ekran("open", "--command", f"{sys.executable} {os.path.join(DIZIN, betik)}", "-b",
                        f"^{re.escape(baslik)}$", "--timeout", "20", env=env)
    m = re.search(r"^(\{[0-9a-f-]{36}\}) \| ", out, re.M)
    return (m.group(1) if m else None), kod, out, t


def kapat(K, baslik):
    if K:
        ekran("-b", f"^{re.escape(baslik)}$", "close", K)


def koordinat(K, metin):
    out = ekran("read", K, metin)[1]
    m = re.search(r"#1 \((\d+),(\d+)\)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def t_ac():
    K, kod, out, t = pencere_ac("test_pencere.py", "ekran-test AC")
    kontrol("open --command: yeni pencere bekleniyor, kimlik döner", kod == 0 and K, f"kod {kod}, {t:.1f} sn: {out.strip()[-160:]}")
    kapat(K, "ekran-test AC")
    ortak.yasak_yaz("ekran-test YASAK")  # varsayılan liste boş: geçici listeye test deseni
    try:
        kod, out, t = ekran("ac", "--komut", "true ekran-test YASAK")  # Türkçe ad; zararsız komut, yasak desene uyar
        kontrol("ac (Türkçe): yasak uygulama başlatılmaz (10)", kod == 10, f"kod {kod}: {out.strip()[-120:]}")
    finally:
        ortak.yasak_yaz()
    kod, out, t = ekran("ac", "--komut", "true", "-b", "^hic-acilmayacak$", "--sure", "2")
    kontrol("ac --sure (Türkçe): pencere açılmazsa zaman aşımı (7)", kod == 7, f"kod {kod}")


def t_klavye():
    B = "ekran-test KLAVYE"
    K, kod, out, _ = pencere_ac("test_pencere.py", B)
    if not K:
        return kontrol("klavye: test penceresi açıldı", False, out)
    try:
        time.sleep(0.8)
        # kendi girdilerimiz insan sayılmamalı (yanlış alarm yok)
        k = koordinat(K, "Kaydet")
        r = [ekran("click", K, str(k[0]), str(k[1]))[0] for _ in range(3)]
        kontrol("kendi girdimiz: art arda 3 tıklama, yanlış 12 yok", r == [0, 0, 0], str(r))
        p = subprocess.run([*ortak.EKRAN, "dizi", K], input=f"tikla {k[0]} {k[1]}\nuyu 0.3\ntus shift\ntikla {k[0]} {k[1]}\n",
                           capture_output=True, text=True)
        kontrol("kendi girdimiz: dizi (tık+tuş+tık) yanlış 12 yok", p.returncode == 0, p.stderr.strip()[-120:])
        # tuş basılıyken otomatik tekrar (~0,57 sn sonra başlar) yanlış alarm vermemeli
        kod, out, t = ekran("hold", K, "w", "2.5")
        kontrol("bas 2,5 sn tek başına → 0 (tuş tekrarı insan sayılmaz)", kod == 0, f"kod {kod}, {out.strip()[-100:]}")
        # FARE DÜĞMESİ basılıyken insan KLAVYEYE dokunur → hemen bırak (12)
        oa = koordinat(K, "OYUN ALANI")
        yp = subprocess.Popen([*ortak.EKRAN, "tikla", K, str(oa[0]), str(oa[1] + 30), "--basili", "5"], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
        time.sleep(2.2)
        n0 = len(olaylar())
        ekran("tus", K, "shift", env=TAKLIT)  # tek başına shift (düzeltme: eskiden hiç basılmıyordu)
        t_insan = time.monotonic()
        o, e = yp.communicate(timeout=10)
        bas_ = [x for x in olaylar()[n0:] if x.startswith(("tus_bas", "fare_birak"))]
        kontrol("fare basılıyken insan klavyeye dokununca → 12, bırakır", yp.returncode == 12 and "klavye" in e,
                f"kod {yp.returncode}, {e.strip()[-110:]}")
        kontrol("tek başına 'shift' gerçekten basıldı", any(x.startswith("tus_bas") for x in bas_), str(bas_))
        # insan klavyeyi kullanırken BAŞLAMA: durmasını bekle (≥1,5 sn sessizlik), sonra tıkla
        insan = subprocess.Popen([*ortak.EKRAN, "dizi", K], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, env=TAKLIT)
        insan.stdin.write("".join("tus shift\nuyu 0.15\n" for _ in range(14)))
        insan.stdin.close()
        time.sleep(0.5)
        t0 = time.monotonic()
        kod, out, t = ekran("tikla", K, str(k[0]), str(k[1]))
        insan.wait(timeout=30)
        kontrol("insan klavyedeyken başlamaz: bekler, sonra tıklar (0)", kod == 0 and "bekleniyor" in out and t >= 2.5,
                f"kod {kod}, {t:.1f} sn, {out.strip()[-120:]}")
        # insan 8 sn'den uzun klavye kullanırsa → 12, hiç girdi gitmez
        insan = subprocess.Popen([*ortak.EKRAN, "dizi", K], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, env=TAKLIT)
        insan.stdin.write("".join("tus shift\nuyu 0.15\n" for _ in range(60)))
        insan.stdin.close()
        time.sleep(0.5)
        once = len(olaylar())
        kod, out, t = ekran("tikla", K, str(k[0]), str(k[1]), bek12=True)
        tik = [o for o in olaylar()[once:] if o.startswith("tık:")]
        kontrol("insan 8 sn+ klavyede → 12, tıklama gitmez", kod == 12 and not tik, f"kod {kod}, {t:.1f} sn, tık {tik}")
        insan.kill()
    finally:
        kapat(K, B)


def t_akis():
    for mod, baslik, bek_kod, ad in (("", "akis-test", 0, "başarı"), ("takil", "akis-test TAKIL", 7, "tekrar koruması"),
                                       ("hata", "akis-test HATA", 11, "hata ekranı")):
        K, kod, out, _ = pencere_ac("akis_pencere.py", baslik, log=AKIS_LOG, MOD=mod)
        if not K:
            kontrol(f"akış {ad}: pencere açıldı", False, out)
            continue
        try:
            time.sleep(0.8)
            kod, out, t = ekran("-b", f"^{baslik}$", "flow" if mod == "" else "akis", K, os.path.join(DIZIN, "test.akis"))
            gecis = [o for o in olaylar(AKIS_LOG) if o.startswith("ekran:")]
            if mod == "":
                ok = kod == 0 and "Kurulum tamamlandı" in out and gecis == ["ekran: hosgeldin", "ekran: lisans", "ekran: kuruluyor",
                                                                            "ekran: tamam"]
            elif mod == "takil":
                ok = kod == 7 and "üst üste" in out
            else:
                ok = kod == 11 and "başarısız" in out
            kontrol(f"akış {ad} → {bek_kod}", ok, f"kod {kod}, {t:.1f} sn, geçiş {gecis}, {out.strip().splitlines()[-1][:170]}")
        finally:
            kapat(K, baslik)


def t_erisim():
    once = subprocess.run(["busctl", "--user", "get-property", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status",
                           "IsEnabled"], capture_output=True, text=True).stdout.strip()
    kod, out, _ = ekran("a11y", "on")
    kontrol("erisim ac", kod == 0 and "AÇIK" in out, out.strip()[:100])
    B = "ekran-test ERISIM"
    K, kod, out, _ = pencere_ac("test_pencere.py", B)
    try:
        time.sleep(1.0)
        kod, out, t = ekran("tree", K)
        kontrol("agac: düğmeler adlarıyla listelenir", kod == 0 and re.search(r"button: Kaydet", out) and re.search(r"button: Onayla", out),
                f"kod {kod}, {t:.1f} sn, {out.strip()[:200]}")
        m = re.search(r"\((\d+),(\d+)\) (?:push )?button: Kaydet", out)
        o = koordinat(K, "Kaydet")
        if m and o:
            dx, dy = int(m.group(1)) - o[0], int(m.group(2)) - o[1]
            kontrol("agac konumu = OCR konumu (±10 px)", abs(dx) <= 10 and abs(dy) <= 10, f"fark ({dx},{dy})")
        else:
            kontrol("agac konumu = OCR konumu", False, f"agac {m and m.groups()}, ocr {o}")
        n = len(olaylar())
        kod, out, t = ekran("click-element", K, "Onayla")
        kontrol("click-element: OCR'ın okuyamadığı yeşil 'Onayla'", kod == 0 and "tık: Onayla" in olaylar()[n:],
                f"kod {kod}, {t:.1f} sn, {out.strip()[-120:]}")
        n = len(olaylar())
        kod, out, _ = ekran("ogeye-tikla", K, "Satın al")
        kontrol("ogeye-tikla: hassas 'Satın al' → 10, tıklanmaz", kod == 10 and not [x for x in olaylar()[n:] if "Satın" in x],
                f"kod {kod}")
        kod, out, _ = ekran("ogeye-tikla", K, "Tamam")
        kontrol("ogeye-tikla: iki 'Tamam' → 5", kod == 5, f"kod {kod}")
        n = len(olaylar())
        kod, out, _ = ekran("click-element", K, "Tamam", "--nth", "2")
        kontrol("click-element --nth 2 → Tamam2", kod == 0 and "tık: Tamam2" in olaylar()[n:], f"kod {kod}")
        kod, out, _ = ekran("ogeye-tikla", K, "Böyle bir düğme yok")
        kontrol("ogeye-tikla: olmayan öge → 6", kod == 6, f"kod {kod}")
    finally:
        kapat(K, B)
        if once != "b true":
            ekran("erisim", "kapat")
    son = subprocess.run(["busctl", "--user", "get-property", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status",
                          "IsEnabled"], capture_output=True, text=True).stdout.strip()
    kontrol("erişilebilirlik eski durumuna döndü", son == once, f"önce {once}, sonra {son}")


def main():
    secim = sys.argv[1:] or ["ac", "klavye", "akis", "erisim"]
    t0 = time.monotonic()
    for ad in secim:
        print(f"--- {ad}", flush=True)
        {"ac": t_ac, "klavye": t_klavye, "akis": t_akis, "erisim": t_erisim}[ad]()
    g = sum(1 for _, ok in SONUC if ok)
    print(f"\n{g}/{len(SONUC)} v3.2 testi geçti ({time.monotonic() - t0:.0f} sn)")
    sys.exit(0 if g == len(SONUC) else 1)


if __name__ == "__main__":
    main()
