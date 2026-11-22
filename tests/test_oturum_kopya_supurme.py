"""Oturum kopyası süpürme testleri (EKRANSIZ; geçici RUNTIME_DIR, tests/_yalitim.py — gerçek /run/user'a DOKUNMAZ).

22 Kas 2026: kapanan arka plan Firefox'larının kopyaları silinmediği için /run/user/<uid> (tmpfs) doldu, durum dosyası
yazımı OSError 28 ile key/type'ı düşürdü. Doğrulananlar:
  - sahibi ölü kopya silinir; sahibi CANLI kopya (gerçek `sleep` alt süreci) ASLA silinmez; başka masaüstünün canlı
    kopyası silinmez, ölüsü süpürülür; pid yeniden kullanımı (başlangıç zamanı farklı) ölü sayılır; zombi ölüdür
  - sahip kaydı olmayan eski kopya: kullanan süreç yoksa silinir; cwd / komut satırıyla kullanılıyorsa kalır; çok yeniyse kalır
  - hazırlayan süreç canlıysa korunur; kalıp dışı dizin, sembolik bağ, flatpak.json asla silinmez
  - sınır (sayı/boyut) aşımında en eski sahipsiz (takılmış hazırlık) silinir, canlı sahipli asla
  - bekçi: sahip süreç bitince kopya HEMEN silinir, yaşarken silinmez
  - yeni_kopya_dizini: hazırlayan kaydı + önce süpürme; boş alan yetmezse Dur 9
  - ENOSPC: dogrulama_sinamasi durum yazımı → anlaşılır Dur 9 (çökme yok, yarım .tmp kalmaz)
  - doctor satırı: "Oturum kopyaları: N adet, X MB"

Çalıştır:  python3 tests/test_oturum_kopya_supurme.py
"""
import errno
import json
import os
import re
import subprocess
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici; Deskhand'den ÖNCE)

from deskhand import doktor, dogrulama_sinamasi, hata, masalar, yollar
from deskhand.hata import Dur
from deskhand.oturum import kopya, kopya_bekcisi

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


assert yollar.runtime_dir().startswith(_yalitim.GECICI), "RUNTIME_DIR yalıtılmamış"
os.makedirs(yollar.runtime_dir(), mode=0o700, exist_ok=True)
KOK = masalar.oturum_koku("")
KOK_B = masalar.oturum_koku("deneme")
for k in (KOK, KOK_B):
    os.makedirs(k, mode=0o700, exist_ok=True)
SURECLER = []
_sayac = [0]


def sahte_kopya(kok, uyg="firefox", bayt=4096, sahip=None, yas=0.0):
    _sayac[0] += 1
    ad = f"{uyg}-20261122-1{_sayac[0]:05d}-4242-{os.urandom(3).hex()}"
    yol = os.path.join(kok, ad)
    os.makedirs(yol, mode=0o700)
    with open(os.path.join(yol, "prefs.js"), "wb") as f:
        f.write(b"x" * bayt)
    if sahip is not None:
        kopya_bekcisi.sahip_yaz(yol, sahip)
    if yas:
        t = time.time() - yas
        os.utime(yol, (t, t))
    return yol


def canli_surec(*argv, **kw):
    p = subprocess.Popen(list(argv) or ["sleep", "60"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **kw)
    SURECLER.append(p)
    for _ in range(100):  # exec bitsin (cmdline/cwd görünür olsun)
        if kopya_bekcisi.surec_durumu(p.pid):
            break
        time.sleep(0.01)
    time.sleep(0.05)
    return p


def olu_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


var = os.path.isdir


# ------------------------------------------------------------------ süreç canlılığı

canli_p = canli_surec("sleep", "60")
bas = kopya_bekcisi.baslangic(canli_p.pid)
kontrol("canlı süreç + doğru başlangıç → canlı", kopya_bekcisi.canli(canli_p.pid, bas))
kontrol("pid yeniden kullanımı (başlangıç farklı) → ölü", not kopya_bekcisi.canli(canli_p.pid, str(int(bas) + 1)))
kontrol("bitmiş süreç → ölü", not kopya_bekcisi.canli(olu_pid()))
z = subprocess.Popen(["true"])
for _ in range(200):
    d = kopya_bekcisi.surec_durumu(z.pid)
    if d and d[0] == "Z":
        break
    time.sleep(0.01)
kontrol("zombi (toplanmamış) süreç → ölü", not kopya_bekcisi.canli(z.pid))
z.wait()

# ------------------------------------------------------------------ süpürme

olu = sahte_kopya(KOK, sahip={"pid": olu_pid(), "bas": "1", "zaman": time.time() - 50})
canli_k = sahte_kopya(KOK, sahip={"pid": canli_p.pid, "bas": bas, "zaman": time.time() - 50})
pid_tekrar = sahte_kopya(KOK, sahip={"pid": canli_p.pid, "bas": str(int(bas) + 7), "zaman": time.time() - 50})
b_canli = sahte_kopya(KOK_B, sahip={"pid": canli_p.pid, "bas": bas, "zaman": time.time() - 50})
b_olu = sahte_kopya(KOK_B, sahip={"pid": olu_pid(), "bas": "1", "zaman": time.time() - 50})
eski_sahipsiz = sahte_kopya(KOK, yas=3600)
eski_cwd = sahte_kopya(KOK, yas=3600)
cwd_p = canli_surec("sleep", "60", cwd=eski_cwd)
eski_cmd = sahte_kopya(KOK, yas=3600)
cmd_p = canli_surec(sys.executable, "-c", "import time; time.sleep(60)", "--profile", eski_cmd)
eski_fd = sahte_kopya(KOK, yas=3600)
fd_p = canli_surec(sys.executable, "-c", f"import time; f=open({os.path.join(eski_fd, 'prefs.js')!r}); time.sleep(60)")
time.sleep(0.2)
yeni_sahipsiz = sahte_kopya(KOK)
hazir_canli = sahte_kopya(KOK, sahip={"hazirlayan": os.getpid(), "hazirlayan_bas": kopya_bekcisi.baslangic(os.getpid()),
                                      "zaman": time.time() - 30})
hazir_olu = sahte_kopya(KOK, sahip={"hazirlayan": olu_pid(), "hazirlayan_bas": "1", "zaman": time.time() - 30})
hazir_cok_eski = sahte_kopya(KOK, sahip={"hazirlayan": os.getpid(), "zaman": time.time() - 5000,
                                         "hazirlayan_bas": kopya_bekcisi.baslangic(os.getpid())})
kalip_disi = os.path.join(KOK, "baska-dizin")
os.makedirs(kalip_disi)
os.utime(kalip_disi, (1, 1))
bag_hedef = sahte_kopya(KOK_B, sahip={"pid": canli_p.pid, "bas": bas})
bag = os.path.join(KOK, "firefox-20261122-000000-1-abcdef")
os.symlink(bag_hedef, bag)
with open(os.path.join(KOK, "flatpak.json"), "w") as f:
    json.dump([], f)

silinen = set(kopya.supur())
kontrol("ölü sahipli kopya silindi", not var(olu) and olu in silinen)
kontrol("CANLI sahipli kopya silinmedi", var(canli_k))
kontrol("pid yeniden kullanımı: kopya silindi", not var(pid_tekrar))
kontrol("başka masaüstünün canlı kopyası silinmedi", var(b_canli))
kontrol("başka masaüstünün ölü kopyası süpürüldü", not var(b_olu))
kontrol("sahip kaydı olmayan eski + kullanılmayan kopya silindi", not var(eski_sahipsiz))
kontrol("sahipsiz ama cwd ile kullanılan kopya kaldı", var(eski_cwd))
kontrol("sahipsiz ama komut satırında geçen kopya kaldı", var(eski_cmd))
kontrol("sahipsiz ama açık dosyayla kullanılan kopya kaldı", var(eski_fd))
kontrol("sahip kaydı olmayan çok yeni kopya kaldı (hazırlanıyor olabilir)", var(yeni_sahipsiz))
kontrol("hazırlayanı canlı kopya kaldı", var(hazir_canli))
kontrol("hazırlayanı ölü kopya silindi", not var(hazir_olu))
kontrol("hazırlık süresi (HAZIRLIK_AZAMI) aşılmış kopya silindi", not var(hazir_cok_eski))
kontrol("kalıp dışı dizin, sembolik bağ ve flatpak.json silinmedi",
        var(kalip_disi) and os.path.islink(bag) and var(bag_hedef) and os.path.isfile(os.path.join(KOK, "flatpak.json")))
for p in (cwd_p, cmd_p, fd_p):
    p.kill()
    p.wait()
kopya.supur()
kontrol("kullanan süreçler bitince sonraki süpürmede silindiler",
        not var(eski_cwd) and not var(eski_cmd) and not var(eski_fd) and var(canli_k))
kontrol("güvenli_sil kök dışını reddeder", not kopya_bekcisi.guvenli_sil(b_canli, KOK) and var(b_canli))
os.unlink(bag)

# ------------------------------------------------------------------ sınır (sayı / boyut)

for y in (yeni_sahipsiz, hazir_canli, b_canli):
    kopya_bekcisi.guvenli_sil(y, os.path.dirname(y))
takili1 = sahte_kopya(KOK, sahip={"hazirlayan": os.getpid(), "hazirlayan_bas": kopya_bekcisi.baslangic(os.getpid()),
                                  "zaman": time.time() - 600})
takili2 = sahte_kopya(KOK, sahip={"hazirlayan": os.getpid(), "hazirlayan_bas": kopya_bekcisi.baslangic(os.getpid()),
                                  "zaman": time.time() - 300})
taze = sahte_kopya(KOK, sahip={"hazirlayan": os.getpid(), "hazirlayan_bas": kopya_bekcisi.baslangic(os.getpid()),
                               "zaman": time.time() - 5})
# şimdi: canli_k (canlı sahip) + takili1 + takili2 + taze = 4 kopya; yeni kopyayla 5 > 3
s = kopya.sinir_uygula(azami_sayi=3)
kontrol("sayı sınırı: en eski takılmış hazırlıklar silindi", not var(takili1) and not var(takili2), str(s))
kontrol("sayı sınırı: canlı sahipli ve taze hazırlık kaldı", var(canli_k) and var(taze))
s = kopya.sinir_uygula(azami_sayi=1, azami_bayt=1)
kontrol("sınır hâlâ aşılıyor ama yalnız canlılar: hiçbiri silinmez", s == [] and var(canli_k) and var(taze))
buyuk = sahte_kopya(KOK, bayt=300_000, sahip={"hazirlayan": olu_pid(), "hazirlayan_bas": "1", "zaman": time.time() - 900})
s = kopya.sinir_uygula(azami_sayi=99, azami_bayt=10_000)
kontrol("boyut sınırı: ölü (sahipsiz) büyük kopya silindi, canlı kaldı", not var(buyuk) and var(canli_k))
kopya_bekcisi.guvenli_sil(taze, KOK)

# ------------------------------------------------------------------ yeni_kopya_dizini + boş alan

olu2 = sahte_kopya(KOK, sahip={"pid": olu_pid(), "bas": "1"})
yeni = kopya.yeni_kopya_dizini("firefox")
s = kopya_bekcisi.sahip_oku(yeni)
kontrol("yeni_kopya_dizini: önce ölü kopya süpürüldü", not var(olu2))
kontrol("yeni_kopya_dizini: hazırlayan kaydı (pid + başlangıç), 0700, kalıba uyar",
        s.get("hazirlayan") == os.getpid() and s.get("hazirlayan_bas") == kopya_bekcisi.baslangic(os.getpid())
        and (os.stat(yeni).st_mode & 0o777) == 0o700 and kopya_bekcisi.KOPYA_DESENI.fullmatch(os.path.basename(yeni)))
kontrol("yeni kopya (hazırlanıyor) süpürmede kalır", var(yeni) and yeni not in kopya.supur())
try:
    kopya.bos_alan_denetle(KOK, en_az=1 << 62)
    kontrol("boş alan yetmezse Dur 9", False)
except Dur as e:
    kontrol("boş alan yetmezse Dur 9 (geçici alan dolu, deskhand doctor)",
            e.kod == 9 and "geçici alan dolu" in e.mesaj and "deskhand doctor" in e.mesaj, e.mesaj)

# ------------------------------------------------------------------ bekçi: sahip bitince HEMEN silinir

kisa = canli_surec("sleep", "1.2")
bekci = kopya.sahip_kaydet(yeni, kisa.pid, son_pay=1.0)
s = kopya_bekcisi.sahip_oku(yeni)
kontrol("sahip_kaydet: pid + başlangıç yazıldı, hazırlayan korundu",
        s.get("pid") == kisa.pid and s.get("bas") == kopya_bekcisi.baslangic(kisa.pid) and s.get("hazirlayan") == os.getpid())
time.sleep(0.5)
kontrol("bekçi: sahip yaşarken kopya silinmez", var(yeni) and bekci is not None and bekci.poll() is None)
kisa.wait()
time.sleep(0.3)
kontrol("bekçi: sahip bittikten hemen sonra son pay boyunca bekler (masaüstü kapanışı önce davranır)", var(yeni))
bitis = time.monotonic() + 10
while var(yeni) and time.monotonic() < bitis:
    time.sleep(0.05)
kontrol("bekçi: sahip bitince kopya silindi", not var(yeni))
try:
    bekci.wait(timeout=5)
except subprocess.TimeoutExpired:
    bekci.kill()
kontrol("bekçi çıktı", bekci.returncode == 0, str(bekci.returncode))
dis = sahte_kopya(KOK_B, sahip={"pid": canli_p.pid, "bas": bas})
r = subprocess.run([sys.executable, "-I", kopya_bekcisi.__file__, "--kok", KOK, "--kopya", dis, "--pid", "1"],
                   capture_output=True, timeout=10)
kontrol("bekçi: kök dışı / başka masaüstünün kopyasını reddeder", r.returncode == 3 and var(dis))

# ------------------------------------------------------------------ ENOSPC: anlaşılır Dur

kontrol("alan_dolu_mu: ENOSPC/EDQUOT evet, EACCES hayır",
        hata.alan_dolu_mu(OSError(errno.ENOSPC, "x")) and hata.alan_dolu_mu(OSError(errno.EDQUOT, "x"))
        and not hata.alan_dolu_mu(OSError(errno.EACCES, "x")))
hata.alan_dolu_denetle(OSError(errno.EACCES, "x"))  # Dur fırlatmamalı
kontrol("alan_dolu_denetle: başka OSError'da Dur yok", True)


class _DoluJson:
    dumps = staticmethod(json.dumps)
    load = staticmethod(json.load)

    @staticmethod
    def dump(*a, **k):
        raise OSError(errno.ENOSPC, "No space left on device")


gercek_json = dogrulama_sinamasi.json
dogrulama_sinamasi.json = _DoluJson
try:
    with dogrulama_sinamasi._depo() as d:
        d["boot"] = "deneme-" + os.urandom(2).hex()
    kontrol("ENOSPC → Dur 9", False)
except Dur as e:
    kontrol("dogrulama_sinamasi ENOSPC → Dur 9 'geçici alan dolu … deskhand doctor' (çökme yok)",
            e.kod == 9 and "geçici alan dolu" in e.mesaj and "deskhand doctor" in e.mesaj and e.tur == "alan-dolu", e.mesaj)
except OSError as e:
    kontrol("ENOSPC → Dur 9", False, repr(e))
finally:
    dogrulama_sinamasi.json = gercek_json
kalan_tmp = [f for f in os.listdir(os.path.dirname(dogrulama_sinamasi._yol())) if f.endswith(".tmp")]
kontrol("ENOSPC: yarım .tmp dosyası kalmadı", not kalan_tmp, str(kalan_tmp))
with dogrulama_sinamasi._depo() as d:
    d["boot"] = "sonra"
kontrol("ENOSPC sonrası normal yazım çalışır", True)

# ------------------------------------------------------------------ doctor satırı

olu3 = sahte_kopya(KOK, bayt=2 * 1024 * 1024, sahip={"pid": olu_pid(), "bas": "1"})
satir = doktor.satir_oturum_kopyalari()
kontrol("doctor: 'Oturum kopyaları: N adet, X MB' + sahipsiz süpürüldü",
        satir["ad"] == "Oturum kopyaları" and re.match(r"\d+ adet, \d+ MB", satir["ayrinti"])
        and "sahipsiz kopya silindi" in satir["ayrinti"] and not var(olu3), str(satir))
kontrol("doctor: canlı kopyalar (iki masaüstü) sayıldı, silinmedi",
        var(canli_k) and var(dis) and var(bag_hedef) and satir["ayrinti"].startswith("3 adet"),
        str(satir))
kontrol("doctor satırı SATIRLAR listesinde", doktor.satir_oturum_kopyalari in doktor.SATIRLAR)

for p in SURECLER:
    if p.poll() is None:
        p.kill()
        p.wait()
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
