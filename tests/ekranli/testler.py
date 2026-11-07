#!/usr/bin/python3
"""Deskhand (eski adı ekran) uçtan uca test takımı (Qt test penceresi). Test penceresini açar, her komutu çalıştırır,
pencerenin olay günlüğünü (test.log) beklenenle karşılaştırır, sonunda pencereyi kapatır.

Çalıştır:  python3 tests/ekranli/testler.py
Süre ~45 sn; bu sırada klavye/fareye dokunma (odak test penceresinde olmalı).
Ham dotool KULLANMAZ: her girdi Deskhand'in güvenlik denetiminden geçer. Komutlar karışık: bir kısmı İngilizce
adlarıyla (click-text, click, read, wait…), bir kısmı Türkçe takma adlarıyla (metne-tikla, tikla, metin…)."""
import json
import os
import re
import subprocess
import sys
import time

import ortak  # DESKHAND_* geçici klasörler + deskhand komutu (Deskhand'den ÖNCE içe aktarılır)
from deskhand import yollar  # noqa: F401

DIZIN = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(ortak.IS, "test.log")
SONUC = []


def ekran(*a):
    t = time.monotonic()
    r = subprocess.run([*ortak.EKRAN, *a], capture_output=True, text=True)
    ortak.kod12_bildir(r.returncode, a)
    return r.returncode, r.stdout + r.stderr, time.monotonic() - t


okunan = 0


def yeni_olaylar():
    global okunan
    with open(LOG) as f:
        satirlar = f.read().splitlines()
    yeni, okunan = satirlar[okunan:], len(satirlar)
    return yeni


def son(onek, olaylar):
    d = [o[len(onek):] for o in olaylar if o.startswith(onek)]
    return d[-1] if d else None


def koordinat(K, metin):
    out = ekran("metin", K, metin)[1]
    m = re.search(r"#1 \((\d+),(\d+)\)", out)
    return int(m.group(1)), int(m.group(2))


def kontrol(ad, kosul, ayrinti=""):
    SONUC.append((ad, bool(kosul), ayrinti))
    print(f"{'GEÇTİ ' if kosul else 'KALDI!'} {ad}" + (f"  [{ayrinti}]" if ayrinti else ""), flush=True)


def main():
    env = dict(os.environ, HAZIR_MS="4000", LOG=LOG)
    pen = subprocess.Popen([sys.executable, os.path.join(DIZIN, "test_pencere.py")], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        K = None
        for _ in range(100):
            out = ortak.ara("ekran-test ANA")
            if out:
                K = out[0]
                break
            time.sleep(0.05)
        assert K, "test penceresi açılmadı"
        time.sleep(0.3)
        yeni_olaylar()

        # --- bekle (İngilizce: wait --timeout --gone; Türkçe: bekle --sure)
        kod, out, t = ekran("wait", K, "Durum: Hazır", "--timeout", "10")
        kontrol("wait: yazı belirince döner", kod == 0 and 2.0 < t < 6.5, f"kod {kod}, {t:.1f} sn")
        kod, out, t = ekran("wait", K, "Yükleniyor", "--gone", "--timeout", "2")
        kontrol("wait --gone: kaybolan yazı", kod == 0, f"kod {kod}, {t:.1f} sn")
        kod, out, t = ekran("bekle", K, "Ödeme tamamlandı", "--sure", "1")
        kontrol("bekle (Türkçe): zaman aşımı kodu 7", kod == 7, f"kod {kod}, {t:.1f} sn")

        # --- OCR kalitesi
        kod, out, t = ekran("metin", K)
        bek = ["Durum: Hazır", "Kaydet", "İptal", "Şifreyi sıfırla", "Tamam", "Çift tıkla beni", "E-posta:", "Not alanı:"]
        # boşluk duyarsız: düzen değişince OCR 'Çift tıkla' → 'Çifttıkla' okuyabiliyor (arama zaten boşluğa duyarsız)
        satirlar_ = [re.sub(r"\s+", "", l.split("] ", 1)[1]) for l in out.splitlines() if "] " in l]
        eksik = [b for b in bek if re.sub(r"\s+", "", b) not in satirlar_]
        kontrol("metin: Türkçe OCR birebir", not eksik, f"{t:.2f} sn" + (f", eksik: {eksik}" if eksik else ""))
        import shutil
        shutil.rmtree(yollar.ocr_onbellek(), ignore_errors=True)
        kod, out, t = ekran("metin", K, "--kal")  # soğuk: tesseract çalışır (--kal: odak geri verilip yeniden
        kod, out2, t2 = ekran("metin", K, "--kal")  # öne getirilince pencere animasyonu görüntüyü değiştiriyordu)
        kontrol("OCR önbelleği: aynı ekran yeniden okunmaz", kod == 0 and out2.split("\n", 1)[1] == out.split("\n", 1)[1]
                and t2 < t - 0.15, f"{t:.2f} → {t2:.2f} sn")

        # --- tıklamalar
        for ad, komut, argv, olay in [
            ("click-text Kaydet", "click-text", ["Kaydet"], "tık: Kaydet"),
            ("metne-tikla küçük/noktasız 'iptal'", "metne-tikla", ["iptal"], "tık: İptal"),
            ("click-text ASCII 'sifreyi sifirla'", "click-text", ["sifreyi sifirla"], "tık: Şifreyi sıfırla"),
            ("click-text --nth 2", "click-text", ["Tamam", "--nth", "2"], "tık: Tamam2"),
            ("metne-tikla --sira 1", "metne-tikla", ["Tamam", "--sira", "1"], "tık: Tamam1"),
            ("click-text double", "click-text", ["Çift tıkla beni", "double"], "çift: Çift tıkla beni"),
            ("metne-tikla çift", "metne-tikla", ["Çift tıkla beni", "cift"], "çift: Çift tıkla beni"),
            ("click-text right", "click-text", ["Kaydet", "right"], "sağ: Kaydet"),
            ("metne-tikla sağ", "metne-tikla", ["Kaydet", "sag"], "sağ: Kaydet"),
        ]:
            kod, out, t = ekran(komut, K, *argv)
            o = yeni_olaylar()
            kontrol(ad, kod == 0 and o == [olay], f"{t:.2f} sn, olay {o}")

        # --- durması gerekenler (hiç olay olmamalı)
        for ad, argv, bek_kod, azami in [
            ("belirsiz eşleşme → 5", ["click-text", K, "Tamam"], 5, 2.0),
            ("olmayan metin → 6", ["metne-tikla", K, "Gönder"], 6, 2.5),
            ("yanlış başlık kilidi → 4 (OCR'sız, hızlı)", ["--title", "TENGA", "click-text", K, "Kaydet"], 4, 0.6),
            ("yanlış başlık kilidi (Türkçe --baslik) → 4", ["--baslik", "TENGA", "metne-tikla", K, "Kaydet"], 4, 0.6),
            ("pencere dışı → 2", ["click", K, "5000", "50"], 2, 0.6),
            ("bilinmeyen tuş → 1", ["key", K, "ctrl+Bogus"], 1, 0.6),
            ("emoji yazma → 1, hiçbir şey yazılmaz", ["type", K, "selam 😀"], 1, 0.6),
            ("emoji yazma (Türkçe yaz) → 1", ["yaz", K, "selam 😀"], 1, 0.6),
        ]:
            kod, out, t = ekran(*argv)
            o = yeni_olaylar()
            kontrol(ad, kod == bek_kod and not o and t < azami, f"kod {kod}, {t:.2f} sn, olay {o}")

        # --- foto + ızgara + --foto eşleme
        kod, out, t = ekran("foto", K, os.path.join(ortak.IS, "izgara.png"), "--genislik", "400", "--izgara", "50")
        s = json.load(open(yollar.son_foto()))
        kx, ky = koordinat(K, "Kaydet")
        ix = s["kenar"][0] + kx * s["olcek"]
        iy = s["kenar"][1] + ky * s["olcek"]
        kod2, out2, t2 = ekran("tikla", K, f"{ix:.0f}", f"{iy:.0f}", "--foto")
        o = yeni_olaylar()
        kontrol("foto --genislik --izgara + tikla --foto", kod == 0 and kod2 == 0 and o == ["tık: Kaydet"], f"olay {o}")

        # --- simgeler (yazısız düğmeler): kaydet → bul → tıkla; iki eş simgede belirsizlik
        kx, ky = koordinat(K, "Kaydet")
        e1 = ekran("simge-kaydet", K, "test-kaydet", "--bolge", f"{kx - 60},{ky - 12},120,24")
        kod, out, t = ekran("simge-bul", K, "test-kaydet", "--kal")
        m_ = re.search(r"#1 \((\d+),(\d+)\) benzerlik ([\d.]+)", out)
        kontrol("simge-bul: kaydedilen simge doğru yerde (≥0.99)", kod == 0 and m_ and abs(int(m_.group(1)) - kx) <= 3
                and abs(int(m_.group(2)) - ky) <= 3 and float(m_.group(3)) >= 0.99, f"{t:.2f} sn, {out.splitlines()[1:2]}")
        yeni_olaylar()
        kod, out, t = ekran("simgeye-tikla", K, "test-kaydet")
        o = yeni_olaylar()
        kontrol("simgeye-tikla: Kaydet", kod == 0 and o == ["tık: Kaydet"], f"{t:.2f} sn, olay {o}")
        tx, ty = koordinat(K, "Tamam")
        ekran("simge-kaydet", K, "test-tamam", "--bolge", f"{tx - 50},{ty - 12},100,24")
        kod, out, t = ekran("simgeye-tikla", K, "test-tamam")
        o = yeni_olaylar()
        kontrol("simgeye-tikla: iki eş 'Tamam' → belirsiz (5), tıklamaz", kod == 5 and not o, f"kod {kod}")
        kod, out, t = ekran("simgeye-tikla", K, "test-tamam", "--sira", "2")
        o = yeni_olaylar()
        kontrol("simgeye-tikla --sira 2 → Tamam2", kod == 0 and o == ["tık: Tamam2"], f"olay {o}")
        kod, out, t = ekran("simgeye-tikla", K, "boyle-simge-yok")
        kontrol("simgeye-tikla: kayıtsız simge → 1", kod == 1 and not yeni_olaylar())
        for ad in ("test-kaydet", "test-tamam"):
            try:
                os.remove(os.path.join(yollar.simge_dizin(), f"{ad}.png"))
            except OSError:
                pass

        # --- renkli düğmeler (yazısı okunamayabilir): renk-bul / renge-tikla
        kod, out, t = ekran("renk-bul", K, "yesil", "--kal")
        kontrol("renk-bul yesil: tek yeşil düğme bulundu", kod == 0 and "1 alan" in out, out.splitlines()[0] if out else "")
        yeni_olaylar()
        kod, out, t = ekran("renge-tikla", K, "yesil")
        o = yeni_olaylar()
        kontrol("renge-tikla yesil → Onayla", kod == 0 and o == ["tık: Onayla"], f"{t:.2f} sn, olay {o}")
        kod, out, t = ekran("renge-tikla", K, "kirmizi")
        o = yeni_olaylar()
        kontrol("renge-tikla kirmizi → Vazgeç", kod == 0 and o == ["tık: Vazgeç"], f"{t:.2f} sn, olay {o}")
        # Not: kalın beyaz yazılı renkli düğmeler satır içinde OCR ile okunmuyor ('Onayla' → 'onara', ölçüm);
        # bu yüzden renkli düğmeler RENGİYLE bulunur
        kod, out, t = ekran("renk-bul", K, "kirmizi", "--kal")
        kontrol("renk-bul kirmizi: kırmızı düğme bulundu", kod == 0 and "1 alan" in out, out.splitlines()[0] if out else "")
        yeni_olaylar()

        # --- hassas düğme (ödeme/yetki): onaysız tıklanmaz
        kod, out, t = ekran("metne-tikla", K, "Satın al")
        o = yeni_olaylar()
        kontrol("hassas: metne-tikla 'Satın al' → 10", kod == 10 and not o, f"kod {kod}, olay {o}")
        sx, sy = koordinat(K, "Satın al")
        yeni_olaylar()
        kod, out, t = ekran("tikla", K, str(sx), str(sy))
        o = yeni_olaylar()
        kontrol("hassas: koordinatla tikla da → 10 (noktadaki yazı OCR)", kod == 10 and not o and t < 1.2,
                f"kod {kod}, {t:.2f} sn, olay {o}")
        kx, ky = koordinat(K, "Kaydet")
        yeni_olaylar()
        kod, out, t = ekran("tikla", K, str(kx), str(ky))
        o = yeni_olaylar()
        kontrol("normal tikla: noktadaki yazıyı söyler, gecikme yok", kod == 0 and o == ["tık: Kaydet"]
                and "noktadaki yazı: Kaydet" in out and t < 1.1, f"{t:.2f} sn, olay {o}")
        kod, out, t = ekran("metne-tikla", K, "Satın al", "--onayli")
        o = yeni_olaylar()
        kontrol("hassas + --onayli → tıklar", kod == 0 and o == ["tık: Satın al"], f"olay {o}")

        # --- yasak pencere: okuma serbest, girdi YOK. Varsayılan yasak listesi BOŞ → test geçici listeye kendi
        # desenini yazar (gerçek ayarlara dokunmaz)
        ortak.yasak_yaz("ekran-test YASAK")
        env2 = dict(os.environ, BASLIK="ekran-test YASAK (pencere)", LOG=os.path.join(ortak.IS, "yasak.log"))
        open(env2["LOG"], "w").close()
        yp = subprocess.Popen([sys.executable, os.path.join(DIZIN, "test_pencere.py")], env=env2,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            Y = None
            for _ in range(100):
                out = ortak.ara("ekran-test YASAK")
                if out:
                    Y = out[0]
                    break
                time.sleep(0.05)
            time.sleep(0.4)
            sonuc = [ekran("metne-tikla", Y, "Kaydet")[0], ekran("click", Y, "100", "100")[0],
                     ekran("yaz", Y, "x")[0], ekran("key", Y, "Return")[0], ekran("scroll", Y)[0],
                     ekran("--on-my-screen", "click", Y, "100", "100")[0]]
            kod_m, out_m, _ = ekran("metin", Y, "--kal")
            kontrol("yasak pencere: tüm girdiler (--on-my-screen dahil) → 10, hiç olay yok",
                    sonuc == [10] * 6 and not open(env2["LOG"]).read(),
                    f"kodlar {sonuc}")
            kontrol("yasak pencere: okuma (metin) serbest", kod_m == 0 and "Kaydet" in out_m)
            # odağı geri verme: yasak pencere öndeyken ana pencereyi oku → yasak pencere geri öne gelmeli
            onde = ortak.aktif()
            ekran("metin", K)
            sonra = ortak.aktif()
            kontrol("okuma bitince önceki pencere geri gelir", onde == Y and sonra == Y, f"önce {onde == Y}, sonra {sonra == Y}")
            ekran("metin", K, "--kal")
            sonra = ortak.aktif()
            kontrol("--kal: hedef önde kalır", sonra == K)
        finally:
            yp.terminate()
            yp.wait()
            ortak.yasak_yaz()  # geçici liste yine boş

        # --- günlük: her girdi ve her DUR kaydı
        gl = open(os.path.join(yollar.gunluk_dizin(), time.strftime("gunluk-%Y%m%d.log"))).read()
        kontrol("günlük: tıklama + başlık + DUR 10 kayıtlı", "[ekran-test ANA]" in gl and "metne-tikla 'Satın al'" in gl
                and "DUR 10" in gl and "--onayli" in gl)

        # --- temizlik: 5 günden eski önbellek dosyası silinir, yenisi kalır
        eski, yeni = (os.path.join(yollar.cikti(), f"test-{a}.png") for a in ("eski", "yeni"))
        for yol, gun in ((eski, 6), (yeni, 4)):
            open(yol, "w").close()
            os.utime(yol, (time.time() - gun * 86400,) * 2)
        ekran("bul", "yok-boyle-pencere")
        kontrol("temizlik: 6 günlük silindi, 4 günlük kaldı", not os.path.exists(eski) and os.path.exists(yeni))
        os.remove(yeni)

        # --- yazma
        kod, out, t = ekran("-b", "ekran-test ANA", "metne-tikla", K, "E-posta", "--kay", "300,0")
        yeni_olaylar()
        metin = "çağrı.ışık@örnek.com ÖĞÜŞİ  iki boşluk 123 !?#{}[]|~\\<>"
        kod, out, t = ekran("-b", "ekran-test ANA", "yaz", K, metin)
        o = yeni_olaylar()
        kontrol("yaz: Türkçe + özel karakter birebir", kod == 0 and son("eposta=", o) == metin, f"{t:.2f} sn, sonuç {son('eposta=', o)!r}")
        ekran("tus", K, "ctrl+a")
        kod, out, t = ekran("tus", K, "BackSpace")
        o = yeni_olaylar()
        kontrol("tus ctrl+a + BackSpace (X adı)", kod == 0 and son("eposta=", o) == "", f"{t:.2f} sn")
        kod, out, t = ekran("yaz", K, "A—B…C€ äé ő")
        o = yeni_olaylar()
        kontrol("yaz: tr'de olmayan → yedek + uyarı", kod == 0 and son("eposta=", o) == "A-B...C€ äé o"
                and "değiştirildi" in out and "impossible" not in out, f"sonuç {son('eposta=', o)!r}")

        # --- insan önceliği: yazarken fare kıpırdarsa (insan bilgisayara dokundu) yazma durmalı
        ekran("metne-tikla", K, "E-posta", "--kay", "300,0")
        ekran("tus", K, "ctrl+a"); ekran("tus", K, "BackSpace")
        yeni_olaylar()
        uzun = "insan dokununca bu uzun metin yarıda kesilmeli ve kalan harfler hiç yazılmamalı " * 2
        yp2 = subprocess.Popen([*ortak.EKRAN, "yaz", K, uzun], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.3)
        subprocess.run([*ortak.EKRAN, "kaydir", K, "asagi", "1", "--nokta", "200,150"], capture_output=True,
                       env=dict(os.environ, DESKHAND_INSAN_TAKLIDI="1"))  # "insan" fareyi oynatır
        out, err = yp2.communicate(timeout=30)
        o = yeni_olaylar()
        e_ = son("eposta=", o) or ""
        kontrol("insan önceliği: yazarken fare oynayınca → 12, yarıda kesilir", yp2.returncode == 12 and 0 < len(e_) < len(uzun),
                f"kod {yp2.returncode}, {len(e_)}/{len(uzun)} harf")

        # --- yazarken sekme/başlık değişirse durmalı (pencere 10. harfte başlığını değiştirir)
        ekran("metne-tikla", K, "Not alanı", "--kay", "300,0")
        yeni_olaylar()
        tam = "Birinci kelime sonra ikinci kelime ve üçüncü"
        kod, out, t = ekran("-b", "ANA", "yaz", K, tam)
        o = yeni_olaylar()
        n = son("not=", o) or ""
        kontrol("yazarken başlık değişti → 4, kalan yazılmadı", kod == 4 and n.startswith("Birinci") and len(n) <= 16,
                f"yazılan {n!r}")
    finally:
        pen.terminate()
        pen.wait()

    gecen = sum(1 for _, ok, _ in SONUC if ok)
    print(f"\n{gecen}/{len(SONUC)} test geçti")
    sys.exit(0 if gecen == len(SONUC) else 1)


if __name__ == "__main__":
    main()
