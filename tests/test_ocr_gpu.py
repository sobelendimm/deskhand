#!/usr/bin/python3
"""deskhand ekran kartı OCR'ı (ocr_gpu) testleri. EKRANSIZ: girdi göndermez, ekran görüntüsü almaz.

1-6 her makinede (torch/ekran kartı GEREKMEZ): kurulum yokken tesseract'a sessiz düşme, protokol, kelime biçimi
dönüşümü, tesseract satırına yalnız EKLEME kuralı, sahte sunucuyla istemci (önbellek anahtarı, zaman aşımı, oyunda
kapatma). 7 yalnız OCR venv'i + modeli + ekran kartı olan makinede: gerçek sunucu (gerçek DATA_DIR salt okunur
kullanılır; soket/günlük geçici klasörde), kullanıcı oyundaysa atlanır.

Çalıştır:  python3 tests/test_ocr_gpu.py"""
import os
import signal
import socket
import sys
import threading
import time

GERCEK_DATA = os.path.expanduser(os.environ.get("DESKHAND_DATA_DIR") or "~/.local/share/deskhand")
import _yalitim  # noqa: E402,F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from PIL import Image  # noqa: E402

from deskhand import ocr as m, ocr_gpu as g  # noqa: E402

ORNEK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ornek")
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


WEB = Image.open(os.path.join(ORNEK, "web-test-acik.png")).convert("RGB")


# ---------------------------------------------------------------- 1. kurulum yok → tesseract
def kurulumsuz():
    kontrol("yalıtılmış ortamda kurulum eksik sayılır (model/venv geçici DATA_DIR'de yok)", "model" in g.eksikler(), g.eksikler())
    kontrol("ocr_gpu.oku → None (sessiz)", g.oku(WEB, bekle=1.0) is None)
    kontrol("ocr.oku(motor=gpu) → [] (hata yok)", m.oku(WEB, motor="gpu") == [])
    kontrol("baslat → False, sunucu açılmaz", g.baslat() is False and not g.calisiyor())
    a = m.derin_oku(WEB, m.LISTE_OKUMALARI)
    b = m.derin_oku(WEB, m.LISTE_OKUMALARI, gpu_bekle=None)
    kontrol("derin_oku: ekran kartı yokken sonuç tesseract'ınkiyle aynı", [s["t"] for s in a] == [s["t"] for s in b])
    kontrol("yedek_ara: tesseract yedekleriyle 'Satın al' bulunur", bool(m.yedek_ara(WEB, "Satın al")))
    os.makedirs(os.path.dirname(g.hata_yolu()), exist_ok=True)
    g._hata_yaz("deneme: açılamadı")
    kontrol("son açılış başarısızsa bir süre denenmez (eksikler: hata)", "hata" in g.eksikler())
    os.utime(g.hata_yolu(), (time.time() - g.HATA_SN - 5,) * 2)
    kontrol("hata süresi dolunca yeniden denenir", "hata" not in g.eksikler())
    os.unlink(g.hata_yolu())


# ---------------------------------------------------------------- 2. protokol
def protokol():
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        veri = bytes(range(256)) * 300
        g.ileti_yaz(a, {"komut": "oku", "w": 1, "h": 2, "ad": "Şanlıurfa"}, veri)
        baslik, gelen = g.ileti_oku(b)
        kontrol("ileti: başlık (Türkçe harf) + ham veri gidip gelir", baslik["ad"] == "Şanlıurfa" and gelen == veri and baslik["n"] == len(veri))
        g.ileti_yaz(a, {"x": 1}, b"0123456789")
        try:
            g.ileti_oku(b, en_cok=5)
            kontrol("ileti: sınırı aşan veri reddedilir", False)
        except ValueError:
            kontrol("ileti: sınırı aşan veri reddedilir", True)
        kontrol("SO_PEERCRED: aynı kullanıcı → karşı ucun PID'i", g._es_kullanici(b) == os.getpid())
    finally:
        a.close()
        b.close()
    kontrol("büyütme: küçük görüntü 2x, 2560x1440 1x", g.buyutme(1336, 365) == 2.0 and g.buyutme(2560, 1440) == 1.0)


# ---------------------------------------------------------------- 3. kelime biçimi
KUTULAR = [[30.0, 180.0, 114.0, 210.0, "Satın al", 0.97], [10.0, 5.0, 60.0, 20.0, "  ", 0.5],
           [200.0, 100.0, 300.0, 120.0, "Kaydet", 0.4]]


def bicim():
    k = g.kelimelere(KUTULAR)
    kontrol("kelimelere: boş metin atlanır, kelimeye bölünür", [w["t"] for w in k] == ["Satın", "al", "Kaydet"], [w["t"] for w in k])
    alanlar = {"anahtar", "x", "y", "g", "y2", "x2", "conf", "t"}
    kontrol("kelimelere: Deskhand alanları", all(set(w) == alanlar for w in k))
    s1, s2 = k[0], k[1]
    kontrol("kelimelere: x payı harf sayısıyla, kutu içinde", 30 <= s1["x"] < s1["x2"] < s2["x"] < s2["x2"] <= 114.0001
            and abs(s1["g"] - (s1["x2"] - s1["x"])) < 1e-6)
    kontrol("kelimelere: güven 0-100, kutu = satır anahtarı", s1["conf"] == 97.0 and s1["anahtar"] == s2["anahtar"] != k[2]["anahtar"])
    sat = m.satirla(k)
    ms = m.ara(sat, "satin al")
    kontrol("satirla + ara: ekran kartı kelimelerinde arama", len(ms) == 1 and abs(ms[0]["cx"] - 72) < 1 and abs(ms[0]["cy"] - 195) < 1)


# ---------------------------------------------------------------- 4. yalnız ekleme kuralı
def ekleme():
    def satir(t, x, y, w=80, conf=90):
        return {**m.kutu([{"x": x, "y": y, "x2": x + w, "y2": y + 20, "conf": conf, "t": t}]),
                "kelimeler": [{"t": t}]}
    tess = [satir("İptal", 100, 100), satir("sazmal", 30, 180), satir("Durum:", 20, 60, 50), satir("Hazır", 75, 60, 40)]
    kopya = [dict(s) for s in tess]
    gpu = [satir("Iptal", 101, 101, conf=60), satir("Satın al", 31, 181, conf=99), satir("Durum: Hazır", 20, 60, 95),
           satir("Yeni düğme", 400, 300)]
    sonuc = m.gpu_ekle(tess, gpu)
    metinler = [s["t"] for s in sonuc]
    kontrol("gpu_ekle: aynı metin (harf katlamalı) eklenmez", metinler.count("İptal") == 1 and "Iptal" not in metinler, metinler)
    kontrol("gpu_ekle: birden çok tesseract satırını kapsayan aynı metin eklenmez", "Durum: Hazır" not in metinler, metinler)
    kontrol("gpu_ekle: tesseract'ın bozuk okuduğu yerdeki doğru okuma eklenir", "Satın al" in metinler and "sazmal" in metinler)
    kontrol("gpu_ekle: yeni satır eklenir, gpu işaretli", any(s["t"] == "Yeni düğme" and s.get("gpu") for s in sonuc))
    kontrol("gpu_ekle: tesseract satırları değişmez", tess == kopya and all(s in sonuc for s in kopya) and not any(s.get("gpu") for s in tess))


# ---------------------------------------------------------------- 5-6. sahte sunucu ile istemci
class SahteSunucu:
    """Protokolü konuşan torch'suz sunucu (iş parçacığı). yanit=False: istek okunur, yanıt verilmez (zaman aşımı)."""

    def __init__(self, kutular, yanit=True):
        self.kutular, self.yanit, self.istekler = kutular, yanit, []
        os.makedirs(os.path.dirname(g.soket_yolu()), exist_ok=True)
        try:
            os.unlink(g.soket_yolu())
        except FileNotFoundError:
            pass
        self.ls = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.ls.bind(g.soket_yolu())
        os.chmod(g.soket_yolu(), 0o600)
        self.ls.listen(4)
        self.ls.settimeout(0.2)
        self.dur = False
        self.t = threading.Thread(target=self.dongu, daemon=True)
        self.t.start()

    def dongu(self):
        while not self.dur:
            try:
                c, _ = self.ls.accept()
            except OSError:
                continue
            with c:
                c.settimeout(5)
                baslik, veri = g.ileti_oku(c)
                self.istekler.append((baslik, len(veri)))
                if self.yanit:
                    g.ileti_yaz(c, {"kutular": self.kutular, "sure": 0.01})
                else:
                    time.sleep(3)

    def kapat(self):
        self.dur = True
        self.t.join()
        self.ls.close()
        os.unlink(g.soket_yolu())


def sahte():
    eski = (g.eksikler, g.oyunda, g.ISTEK_SN, g.kapat)
    kapatildi = []
    g.eksikler = lambda: []
    g.oyunda = lambda: False
    try:
        sv = SahteSunucu(KUTULAR)
        try:
            os.makedirs(os.path.dirname(g.kilit_yolu()), exist_ok=True)
            k = g.oku(WEB)
            kontrol("istemci: sahte sunucudan kelimeler", k is not None and [w["t"] for w in k] == ["Satın", "al", "Kaydet"])
            b, n = sv.istekler[-1]
            kontrol("istemci: görüntü RGB ham + boyut + büyütme gönderilir", (b["w"], b["h"], n, b["mag"]) == (1336, 365, 1336 * 365 * 3, 2.0))
            once = len(sv.istekler)
            k1 = m.oku(WEB, motor="gpu")
            k2 = m.oku(WEB, motor="gpu")
            kontrol("ocr.oku(motor=gpu): önbellekli (ikinci okuma sunucuya gitmez)", len(sv.istekler) == once + 1 and
                    [w["t"] for w in k1] == [w["t"] for w in k2] == ["Satın", "al", "Kaydet"])
            t = m.oku(WEB)
            kontrol("önbellek anahtarı okuma türünü ayırır (tesseract okuması ayrı)", len(sv.istekler) == once + 1 and
                    "Durum:" in [w["t"] for w in t])
            # büyük boş zemin: içerik kutusu kırpılır, koordinatlar geri kaydırılır
            tuval = Image.new("RGB", (2560, 1440), (20, 20, 20))
            tuval.paste(WEB, (900, 500))
            k = m.oku_gpu(tuval)
            b, n = sv.istekler[-1]
            kontrol("oku_gpu: büyük boş zemin kırpılır, koordinat kayar", b["w"] < 2560 and k and k[0]["x"] >= 900 - 24
                    and k[0]["y"] >= 500 - 24, (b["w"], k and k[0]["x"]))
        finally:
            sv.kapat()
        # zaman aşımı: yanıt yok → None, ISTEK_SN içinde
        g.ISTEK_SN = 1.0
        sv = SahteSunucu(KUTULAR, yanit=False)
        try:
            t0 = time.monotonic()
            k = g.oku(WEB.crop((0, 0, 50, 50)))
            sure = time.monotonic() - t0
            kontrol("zaman aşımı: yanıt yoksa None, süre sınırlı", k is None and sure < 2.5, f"{sure:.1f} sn")
        finally:
            sv.kapat()
        g.ISTEK_SN = eski[2]
        # sunucu yok + bekle: None, bekle süresi kadar
        t0 = time.monotonic()
        k = g.oku(WEB, bekle=0.5)
        kontrol("sunucu yok: bekle sonunda None", k is None and 0.4 < time.monotonic() - t0 < 3)
        # oyunda: okuma yok, çalışan sunucu kapatılır
        g.oyunda = lambda: True
        g.kapat = lambda: kapatildi.append(1) or True
        kontrol("oyunda: GPU okuması yok (None) ve sunucu kapatılır", g.oku(WEB) is None and kapatildi == [1])
        kontrol("oyunda: baslat → False", g.baslat() is False)
    finally:
        g.eksikler, g.oyunda, g.ISTEK_SN, g.kapat = eski


# ---------------------------------------------------------------- 7. gerçek sunucu (varsa)
def gercek():
    os.environ["DESKHAND_DATA_DIR"] = GERCEK_DATA  # yalnız okunur: venv + model
    try:
        eksik = g.eksikler()
        if eksik:
            print(f"ATLANDI gerçek ekran kartı testi (eksik: {', '.join(eksik)})")
            return
        if g.oyunda():
            print("ATLANDI gerçek ekran kartı testi (kullanıcı oyunda/tam ekranda)")
            return
        g.BOSTA_KAPAN_SN = 8
        t0 = time.monotonic()
        k = m.oku_gpu(WEB, bekle=g.SOGUK_SN + 7)
        soguk = time.monotonic() - t0
        sat = m.satirla(k or [])
        kontrol("gerçek: soğuk açılış + 'Satın al' ve 'Şifreyi sıfırla' bulunur",
                bool(m.ara(sat, "Satın al")) and bool(m.ara(sat, "Şifreyi sıfırla")), f"{soguk:.1f} sn, {[s['t'] for s in sat]}")
        pid = g._sunucu_pid()
        kontrol("gerçek: soket 0600 + PID dosyası", oct(os.stat(g.soket_yolu()).st_mode & 0o777) == "0o600" and pid)
        time.sleep(g.BOSTA_DUR_SN + 1.5)
        durum = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0]
        kontrol("gerçek: boşta kendini dondurur (işlemci 0)", durum == "T", durum)
        t0 = time.monotonic()
        k = m.oku_gpu(WEB)
        kontrol("gerçek: donmuş sunucu uyanır, sıcak istek < 1 sn", k and time.monotonic() - t0 < 1.0, f"{time.monotonic() - t0:.2f} sn")
        bitis = time.monotonic() + 8 + g.BEKCI_SN * 2 + 5
        while time.monotonic() < bitis and os.path.exists(f"/proc/{pid}"):
            time.sleep(0.5)
        kontrol("gerçek: boşta süresi dolunca bekçi kapatır (VRAM bırakılır)", not os.path.exists(f"/proc/{pid}") and not g.calisiyor())
        kontrol("gerçek: kapanınca soket ve PID dosyası silinir", not os.path.exists(g.soket_yolu()) and not os.path.exists(g.pid_yolu()))
    finally:
        if g.calisiyor():
            g.kapat()
        os.environ["DESKHAND_DATA_DIR"] = _yalitim.DIZINLER["DESKHAND_DATA_DIR"]


def main():
    t0 = time.monotonic()
    for adim in (kurulumsuz, protokol, bicim, ekleme, sahte, gercek):
        adim()
    print(f"\n{gecen}/{toplam} ekran kartı OCR testi geçti ({time.monotonic() - t0:.1f} sn)")
    sys.exit(0 if gecen == toplam else 1)


if __name__ == "__main__":
    signal.signal(signal.SIGCONT, signal.SIG_DFL)
    main()
