"""DENETİM 2 (ekransız, sahte arka uç): tur3'te kalan yollar. Gerçek ekrana/dosyalara dokunmaz (_yalitim; uygulama
dizini geçici klasöre yönlendirilir)."""
import os

import _yalitim

from deskhand import guvenlik, ucbirim, uygulama
from deskhand.hata import Dur

sonuc = []


def rapor(ad, acik, ek=""):
    sonuc.append(acik)
    print(f"{'AÇIK ' if acik else 'sağlam'}  {ad}" + (f"  ({ek})" if ek else ""))


def dur_mu(f, *a, **k):
    try:
        return f(*a, **k), None
    except Dur as e:
        return None, f"[{e.kod}] {e.mesaj[:140]}"


# 1) MCP open_app: gömülü uçbirimli uygulamalar serbest
for ad in ("dolphin", "kate"):
    r, h = dur_mu(uygulama.mcp_uygulama, ad)
    rapor(f"1 open_app('{ad}') MCP'den başlatılabilir (F4 / uçbirim paneli = gömülü kabuk)", h is None,
          h or r[0].get("exec"))

# 2) ajanın yazdığı .desktop girdisi: denylist dışı kod çalıştıran Exec'ler
G = _yalitim.GECICI
uyg = os.path.join(G, "applications")
os.makedirs(uyg)
betik = os.path.join(G, "betik")
open(betik, "w").write("#!/bin/sh\ntouch /tmp/x\n")
os.chmod(betik, 0o700)
EXECLER = {"gitalias": "git -c alias.x=!touch\\s/tmp/p x", "flockc": "flock /tmp/l -c 'touch /tmp/p'",
           "tmuxyeni": "tmux new-session -d 'touch /tmp/p'", "betikexec": betik,
           "setprivb": f"setpriv --reset-env {betik}"}
for ad, ex in EXECLER.items():
    open(os.path.join(uyg, f"{ad}.desktop"), "w").write(f"[Desktop Entry]\nType=Application\nName={ad}\nExec={ex}\n")
uygulama.UYGULAMA_DIZINLERI = (uyg,)
for ad, ex in EXECLER.items():
    r, h = dur_mu(uygulama.mcp_uygulama, ad)
    rapor(f"2 kullanıcı uygulama dizinine yazılmış '{ad}.desktop' (Exec={ex!r}) MCP'den başlatılabilir", h is None, h or "")


# 3) Enter kapısı / uçbirim komutu: sahte arka uç
class AU:
    ad = "kde"

    def __init__(self, sinif):
        self.s = sinif

    def sinif(self, k):
        return self.s

    def baslik(self, k):
        return "pencere"

    def pid(self, k):
        return ""

    def aktif(self):
        return "{p}"


for sinif in ("org.kde.dolphin", "org.kde.kate", "Code"):
    guvenlik.sec = ucbirim.sec = (lambda s=sinif: AU(s))
    ucbirim.satir_oku = lambda k: ["~ $ sudo reboot"]
    r, h = dur_mu(ucbirim.enter_kapisi, "{p}", False)
    r2, h2 = dur_mu(guvenlik.ucbirim_komut_engel, "{p}", False, "sudo reboot")
    rapor(f"3 gömülü uçbirim ({sinif}): satır 'sudo reboot' iken Enter kapısı ve uçbirim komut denetimi uygulanmıyor",
          r is False and r2 is False, f"enter={r if h is None else h} komut={r2 if h2 is None else h2}")

guvenlik.sec = ucbirim.sec = (lambda: AU("org.kde.konsole"))
ucbirim.satir_oku = lambda k: ["~ $ history -s 'sudo reboot'"]
r1, h1 = dur_mu(ucbirim.enter_kapisi, "{p}", False)
ucbirim.satir_oku = lambda k: ["~ $ !!"]
r2, h2 = dur_mu(ucbirim.enter_kapisi, "{p}", False)
rapor("4 konsole: `history -s 'sudo reboot'` + Enter, sonra `!!` + Enter → ikisi de kapıdan onaysız geçer",
      r1 is False and r2 is False, f"{h1} / {h2}")
for satir in ("echo c3VkbyByZWJvb3Q= | base64 -d | sh", "bash <<< 'sudo reboot'", "fc -s", "sh ~/.cache/x"):
    ucbirim.satir_oku = lambda k, s=satir: ["~ $ " + s]
    r, h = dur_mu(ucbirim.enter_kapisi, "{p}", False)
    rapor(f"5 konsole Enter kapısı: {satir!r} onaysız", r is False, h or "")
print("\nDENETİM2 birim:", sum(sonuc), "açık /", len(sonuc))
