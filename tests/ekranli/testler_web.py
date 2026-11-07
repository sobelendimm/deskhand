#!/usr/bin/python3
"""Deskhand GERÇEK TARAYICI testi (Firefox, açık tema web sayfası, kaydırma).
Yerel sunucu (127.0.0.1) test sayfasını verir; sayfadaki olaylar POST /olay ile web.log'a yazılır.
Sayfa AYRI bir Firefox örneğinde açılır (kendi geçici profili: firefox_test.py); kullanıcının Firefox'u ve profili
hiç kullanılmaz. Pencere sayfa başlığındaki benzersiz belirteç + bu örneğin PID'i ile bulunur; sonunda yalnız bu
örnek (kendi PID'i, SIGTERM) kapatılır. Komutlar İngilizce adlarıyla; birkaç senaryo Türkçe takma adlarla.

Çalıştır:  python3 tests/ekranli/testler_web.py   (~60 sn; bu sırada klavye/fareye dokunma)"""
import http.server
import os
import re
import secrets
import subprocess
import sys
import threading
import time

import ortak  # DESKHAND_* geçici klasörler + deskhand komutu (Deskhand'den ÖNCE içe aktarılır)
from deskhand import yollar  # noqa: F401
import firefox_test

DIZIN = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(ortak.IS, "web.log")
SONUC = []
BELIRTEC = secrets.token_hex(4)  # sayfa başlığında: kullanıcının pencereleriyle karışmasın
DESEN = "ekran-test web"

SAYFA = """<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>ekran-test web @@BELIRTEC@@</title>
<style>body{font-family:'Noto Sans',sans-serif;font-size:15px;background:#fff;color:#222;margin:30px}
button{font-size:15px;padding:6px 14px;margin:4px} input{font-size:15px;width:360px;padding:4px}
label{display:inline-block;width:110px}</style></head><body>
<h2>ekran web testi</h2>
<p id="durum">Durum: Yükleniyor</p>
<div><button onclick="olay('tık: Kaydet')" oncontextmenu="olay('sağ: Kaydet');return false">Kaydet</button>
<button onclick="olay('tık: İptal')">İptal</button>
<button onclick="olay('tık: Şifreyi sıfırla')">Şifreyi sıfırla</button></div>
<div><button onclick="olay('tık: Tamam1')">Tamam</button><button onclick="olay('tık: Tamam2')">Tamam</button>
<span ondblclick="olay('çift: Çift tıkla beni')" style="margin-left:20px">Çift tıkla beni</span></div>
<div><button onclick="olay('tık: Satın al')">Satın al</button></div>
<p><label>E-posta:</label><input id="eposta" oninput="olay('eposta='+this.value)"></p>
<p><label>Not alanı:</label><input id="not" oninput="notDegisti(this.value)"></p>
<div style="height:3200px;background:linear-gradient(#fff,#eef)"></div>
<button onclick="olay('tık: Alttaki düğme')">Alttaki düğme</button>
<div style="height:400px"></div>
<script>
function olay(s){fetch('/olay',{method:'POST',body:s,keepalive:true});}
function notDegisti(v){olay('not='+v); if(v.length>=10 && !document.title.includes('SEKME')) document.title='ekran-test BAŞKA SEKME';}
setTimeout(()=>{document.getElementById('durum').textContent='Durum: Hazır';},3500);
window.addEventListener('scrollend',()=>olay('scroll='+Math.round(scrollY)));
</script></body></html>""".replace("@@BELIRTEC@@", BELIRTEC)



class Sunucu(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        b = SAYFA.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        veri = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        with open(LOG, "a") as f:
            f.write(veri + "\n")
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


def ekran(*a):
    t = time.monotonic()
    r = subprocess.run([*ortak.EKRAN, *a], capture_output=True, text=True)
    ortak.kod12_bildir(r.returncode, a)
    return r.returncode, r.stdout + r.stderr, time.monotonic() - t


okunan = 0


def yeni_olaylar(bekle=0.35):
    global okunan
    time.sleep(bekle)  # fetch POST'u gelsin
    with open(LOG) as f:
        satirlar = f.read().splitlines()
    yeni, okunan = satirlar[okunan:], len(satirlar)
    return yeni


def son(onek, olaylar):
    d = [o[len(onek):] for o in olaylar if o.startswith(onek)]
    return d[-1] if d else None


def kontrol(ad, kosul, ayrinti=""):
    SONUC.append((ad, bool(kosul)))
    print(f"{'GEÇTİ ' if kosul else 'KALDI!'} {ad}" + (f"  [{ayrinti}]" if ayrinti else ""), flush=True)


def testler(K):
    B = ["-b", DESEN]  # başlık (sekme) kilidi: her girdiden hemen önce
    print("pencere:", ekran("windows", DESEN)[1].strip())
    kod, out, t = ekran("wait", K, "Durum: Hazır", "--timeout", "12", "--stay")
    kontrol("wait: web sayfasında yazı belirince", kod == 0, f"kod {kod}, {t:.1f} sn")
    kod, out, t = ekran("read", K, "--stay")
    bek = ["Kaydet", "İptal", "Şifreyi sıfırla", "Çift tıkla beni", "Satın al", "E-posta:", "Not alanı:"]
    eksik = [b for b in bek if b not in out]
    # Tam listede tek başına duran web düğmesi görünmeyebilir (bilinen OCR sınırı, README); ARAMA yedek okumalarla bulur
    aranan = [b for b in eksik if ekran("read", K, b, "--stay")[0] != 0]
    kontrol("read: açık tema Türkçe OCR (liste + aramayla)", not aranan,
            f"{t:.2f} sn" + (f", listede yok ama aramayla bulundu {eksik}" if eksik and not aranan else "")
            + (f", aramayla da yok {aranan}" if aranan else ""))
    yeni_olaylar()

    # İngilizce komut + seçenek adları; son ikisi Türkçe takma adlarla (metne-tikla / --sira)
    for ad, komut, argv, olay in [
        ("click-text Kaydet", "click-text", ["Kaydet"], "tık: Kaydet"),
        ("click-text 'iptal'", "click-text", ["iptal"], "tık: İptal"),
        ("click-text 'sifreyi sifirla'", "click-text", ["sifreyi sifirla"], "tık: Şifreyi sıfırla"),
        ("click-text Tamam --nth 2", "click-text", ["Tamam", "--nth", "2"], "tık: Tamam2"),
        ("metne-tikla çift (Türkçe ad)", "metne-tikla", ["Çift tıkla beni", "cift"], "çift: Çift tıkla beni"),
        ("metne-tikla sağ (Türkçe; tarayıcı menüsü açılmaz)", "metne-tikla", ["Kaydet", "sag"], "sağ: Kaydet"),
        ("click-text Tamam --sira 1 (Türkçe seçenek)", "click-text", ["Tamam", "--sira", "1"], "tık: Tamam1"),
    ]:
        kod, out, t = ekran(*B, komut, K, *argv)
        o = [x for x in yeni_olaylar() if not x.startswith("scroll=")]
        kontrol(ad, kod == 0 and o == [olay], f"{t:.2f} sn, olay {o}")

    kod, out, t = ekran(*B, "click-text", K, "Satın al")
    o = yeni_olaylar()
    kontrol("hassas: 'Satın al' onaysız → 10 (panel kapalı: onay alınamaz)", kod == 10 and not o, f"kod {kod}")
    out = ekran("read", K, "Satın al", "--stay")[1]
    mm = re.search(r"#1 \((\d+),(\d+)\)", out)
    kod, out, t = ekran(*B, "click", K, mm.group(1), mm.group(2)) if mm else (-1, "", 0)
    o = yeni_olaylar()
    kontrol("hassas: KOORDİNATLA click 'Satın al' → 10", kod == 10 and not o, f"kod {kod}, {t:.2f} sn, olay {o}")
    kod, out, t = ekran(*B, "click-text", K, "Satın al", "--approved")
    o = yeni_olaylar()
    kontrol("hassas: --approved → tıklar", kod == 0 and o == ["tık: Satın al"], f"olay {o}")

    ekran(*B, "click-text", K, "E-posta", "--offset", "200,0")
    yeni_olaylar()
    metin = "Örnek Mahallesi, çağrı.ışık@örnek.com — ÖĞÜŞİ 12345 {x}"
    kod, out, t = ekran(*B, "type", K, metin)
    o = yeni_olaylar()
    bekl = metin.replace("—", "-")
    kontrol("type: web kutusuna Türkçe (— → -)", kod == 0 and son("eposta=", o) == bekl, f"{t:.2f} sn, {son('eposta=', o)!r}")
    ekran(*B, "key", K, "ctrl+a")
    kod, out, t = ekran(*B, "tus", K, "BackSpace")  # Türkçe ad
    o = yeni_olaylar()
    kontrol("key ctrl+a + tus BackSpace (Türkçe ad) → kutu boş", kod == 0 and son("eposta=", o) == "", f"{t:.2f} sn")
    kod, out, t = ekran(*B, "yaz", K, "kısa")  # Türkçe ad
    o = yeni_olaylar()
    kontrol("yaz (Türkçe ad): 'kısa'", kod == 0 and son("eposta=", o) == "kısa", f"{son('eposta=', o)!r}")

    # --- kaydırma: yön ve miktar (scrollend olayı scrollY verir)
    kod, out, t = ekran(*B, "scroll", K, "down", "5")
    o = yeni_olaylar(0.8)
    y1 = int(son("scroll=", o) or -1)
    kontrol("scroll down 5 → sayfa aşağı iner", kod == 0 and y1 > 100, f"scrollY {y1}")
    kod, out, t = ekran(*B, "kaydir", K, "yukari", "5")  # Türkçe ad + Türkçe yön
    o = yeni_olaylar(0.8)
    y2 = int(son("scroll=", o) or -1)
    kontrol("kaydir yukari 5 (Türkçe) → başa döner", kod == 0 and 0 <= y2 < y1, f"scrollY {y2}")

    kod, out, t = ekran(*B, "click-text", K, "Alttaki düğme", "--scroll-search")
    o = [x for x in yeni_olaylar() if not x.startswith("scroll=")]
    n = re.search(r"# (\d+) kez kaydırıldı", out)
    if kod != 0:
        print("AYRINTI scroll-search:", out.strip()[-1500:])
    kontrol("click-text --scroll-search: 3200 px aşağıdaki düğme", kod == 0 and o == ["tık: Alttaki düğme"],
            f"{t:.1f} sn, {n.group(1) if n else '?'} kaydırma")
    kod, out, t = ekran(*B, "click-text", K, "Böyle bir düğme yok", "--scroll-search", "40")
    kontrol("--scroll-search: sayfa sonunu anlar, durur → 6", kod == 6 and "sayfa sonu" in out, f"{t:.1f} sn")
    ekran(*B, "key", K, "ctrl+Home")
    time.sleep(0.5)

    # --- sekme/başlık kilidi: sayfa başlığı yazarken değişir
    ekran(*B, "click-text", K, "Not alanı", "--offset", "200,0")
    yeni_olaylar()
    kod, out, t = ekran(*B, "type", K, "Birinci kelime sonra ikinci kelime ve üçüncü")
    o = yeni_olaylar()
    n = son("not=", o) or ""
    if kod != 4:
        print("AYRINTI yazma:", kod, out.strip()[-800:], o)
    kontrol("yazarken sekme başlığı değişti → 4, kalan yazılmadı", kod == 4 and n.startswith("Birinci") and len(n) <= 16,
            f"yazılan {n!r}")


def main():
    open(LOG, "w").close()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Sunucu)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    kullanici_once = firefox_test.kullanici_firefox_pencereleri()
    ff = firefox_test.TestFirefox(url, f"{DESEN} {BELIRTEC}")
    try:
        K = ff.ac()
        kontrol("Firefox: ayrı örnek, kendi profiliyle açıldı (pencere PID'i bizim)", K, f"profil {ff.profil}")
        if K:
            kontrol("Firefox: pencere kullanıcının pencerelerinden değil", K not in kullanici_once)
            testler(K)
    except Exception as ex:  # noqa: BLE001 - kapanış yine çalışsın
        kontrol("web: beklenmedik hata", False, repr(ex)[:160])
    finally:
        print("test Firefox'u:", ff.kapat())
        time.sleep(0.8)
        kalan = ff.bizim_pencereler()
        kontrol("test Firefox penceresi kapandı", not kalan, f"kalan {kalan}")
        kullanici_sonra = firefox_test.kullanici_firefox_pencereleri(ff.pidler)
        kontrol("kullanıcının Firefox pencereleri dokunulmadı (önce = sonra)", kullanici_sonra == kullanici_once,
                f"önce {len(kullanici_once)}, sonra {len(kullanici_sonra)}")
        srv.shutdown()

    gecen = sum(1 for _, ok in SONUC if ok)
    print(f"\n{gecen}/{len(SONUC)} web testi geçti")
    sys.exit(0 if gecen == len(SONUC) else 1)


if __name__ == "__main__":
    main()
