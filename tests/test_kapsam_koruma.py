"""Onay kapsamı ([guvenlik] onaylar = hepsi | kart) PANEL YETKİLİ: ayar dosyasına elle yazılan `kart` geçmez.

Bu süreç panel gibi davranır (onay.panel_kaydet + liste_koruma.panel_baslat); istemci AYRI süreçtir (CLI/MCP gibi) ve
kapsamı yalnız panelin doğrulanmış kanalından alır. Ekransız, girdi yok, gerçek ~/.config yazılmaz (_yalitim).
Çalıştır: python3 tests/test_kapsam_koruma.py"""
import json
import os
import subprocess
import sys
import time

import _yalitim  # noqa: F401  (deskhand'dan ÖNCE)

from deskhand import ayarlar, doktor, guvenlik, liste_koruma, onay  # noqa: E402

class SahteKasa:
    """Fake Secret Service item of the panel (liste_koruma: key, counters, last approved values); file-backed so a
    client process reads the same one (KASA_ISTEMCI). The real wallet is never touched."""
    yol = os.path.join(os.environ["DESKHAND_STATE_DIR"], "sahte-kasa.json")

    def oku(self):
        try:
            with open(self.yol, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def yaz(self, veri):
        with open(self.yol, "wb") as f:
            f.write(veri)


liste_koruma.isaret_anahtarlik_ayarla(SahteKasa())
KASA_ISTEMCI = ("class _K:\n"
                "    def oku(self):\n"
                "        import os\n"
                "        try:\n"
                "            return open(os.path.join(os.environ['DESKHAND_STATE_DIR'], 'sahte-kasa.json'), 'rb').read()\n"
                "        except FileNotFoundError:\n"
                "            return None\n"
                "    def yaz(self, v):\n"
                "        raise OSError('client')\n"
                "from deskhand import liste_koruma as _lk\n"
                "_lk.isaret_anahtarlik_ayarla(_K())\n")


def sahte_isaret(tur, metin):
    """The agent's forged mark (plain sha256 of the content, no panel signature)."""
    import hashlib
    os.makedirs(os.path.dirname(liste_koruma.isaret_yolu(tur)), exist_ok=True)
    with open(liste_koruma.isaret_yolu(tur), "w") as f:
        json.dump({"sha256": hashlib.sha256(metin.encode()).hexdigest(), "icerik": metin, "var": True}, f)

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


ISTEMCI = ("import json, sys, time; sys.path.insert(0, sys.argv[1]); from deskhand import guvenlik, liste_koruma\n"
           "k = guvenlik.onay_kapsami(taze=True)\n"
           "n = int(sys.argv[2]); t = time.perf_counter()\n"
           "for _ in range(n): liste_koruma.kapsam()\n"
           "ham = (time.perf_counter() - t) / max(n, 1) * 1e6\n"
           "t = time.perf_counter()\n"
           "for _ in range(1000): guvenlik.onay_kapsami()\n"
           "onb = (time.perf_counter() - t) / 1000 * 1e6\n"
           "print(json.dumps({'kapsam': k, 'ham_us': ham, 'onbellek_us': onb}))\n")


def istemci(n=0):
    """AYRI süreç: kapsam nereden geliyor? (+ isteğe bağlı süre ölçümü)"""
    r = subprocess.run([sys.executable, "-c", ISTEMCI, _yalitim.KOK, str(n)], capture_output=True, text=True,
                       timeout=60)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"hata": r.stdout + r.stderr}


def ajan_yazar(deger):
    """Ajan: Kate/uçbirimle ayarlar.toml'a yazar (panelden geçmeden)."""
    os.makedirs(os.path.dirname(ayarlar.dosya()), exist_ok=True)
    with open(ayarlar.dosya(), "w") as f:
        f.write(f'[guvenlik]\nonaylar = "{deger}"\n')


def dosyada():
    return ayarlar.al("guvenlik", "onaylar")


# ================================================================ panel kapalı
ajan_yazar("kart")
kontrol("panel kapalı + dosyada elle 'kart' → istemci 'hepsi'", istemci().get("kapsam") == "hepsi")
sahte_isaret(liste_koruma.KAPSAM, "kart")  # işareti de sahte (panel kapalı → yine panel yok)
kontrol("panel kapalı + dosya VE işaret 'kart' → istemci yine 'hepsi' (kanal yok)", istemci().get("kapsam") == "hepsi")
kontrol("doctor: dosyada kart ama panel teyit etmiyor → uyarı satırı, 'hepsi'",
        doktor.satir_onay_kapsami()["durum"] == "uyari" and doktor.satir_onay_kapsami()["ayrinti"].startswith("hepsi"))
os.remove(liste_koruma.isaret_yolu(liste_koruma.KAPSAM))

# ================================================================ panel açılışı: işaretsiz 'kart'
uyarilar = []
onay.panel_kaydet()
k = liste_koruma.panel_baslat(uyarilar.append)
kontrol("panel açılışı: işaretsiz 'kart' kabul edilmez → bellek 'hepsi', dosya 'hepsi'ye döner, uyarı",
        k.metin("onaylar") == "hepsi" and dosyada() == "hepsi" and len(uyarilar) == 1, f"{uyarilar} {dosyada()}")
kontrol("istemci (panel açık) → 'hepsi'", istemci().get("kapsam") == "hepsi")

# ================================================================ panel açıkken ajan dosyaya 'kart' yazar (bulgu senaryosu)
ajan_yazar("kart")
kontrol("panel açık + dosyaya elle 'kart' (işaret yok) → istemci 'hepsi'", istemci().get("kapsam") == "hepsi")
u = k.denetle()
kontrol("panel denetimi: dosya 'hepsi'ye geri yazıldı + uyarı", dosyada() == "hepsi" and len(u) == 1, str(u))
ajan_yazar("kart")
sahte_isaret(liste_koruma.KAPSAM, "kart")  # sahte işaret de işe yaramaz: panelin BELLEĞİ yetkili
kontrol("panel açık + dosya ve işaret sahte 'kart' → istemci 'hepsi'", istemci().get("kapsam") == "hepsi")
k.denetle()
kontrol("…ve panel dosyayı geri yazar", dosyada() == "hepsi")

# ================================================================ panelin Ayarlar'ı: tek yetkili yol
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from deskhand.gui import ayar as A  # noqa: E402

A.onay_kapsami_yaz("kart")
r = istemci(200)
kontrol("panel Ayarlar → 'kart' → istemci 'kart' (dosya + işaret 'kart')",
        r.get("kapsam") == "kart" and dosyada() == "kart" and
        liste_koruma.isaret_oku(liste_koruma.KAPSAM).get("icerik") == "kart", str(r))
n0 = len(uyarilar)
k.denetle()
kontrol("panelin kendi yazdığı geri alınmaz (uyarı yok)", dosyada() == "kart" and len(uyarilar) == n0)
kontrol("panel sürecinde onay_kapsami belleği okur → 'kart'", guvenlik.onay_kapsami(taze=True) == "kart")
print(f"ÖLÇÜM  istemci kanal sorgusu {r.get('ham_us', 0):.0f} µs/çağrı; önbellekli onay_kapsami "
      f"{r.get('onbellek_us', 0):.2f} µs/çağrı (1 sn önbellek)")

# ================================================================ sıkılaştırma kabul: dosyada hepsi / dosya silindi
ajan_yazar("hepsi")
k.denetle()
kontrol("panel açık + dosyada 'hepsi' → kabul (sıkı taraf), istemci 'hepsi'",
        k.metin("onaylar") == "hepsi" and istemci().get("kapsam") == "hepsi")
A.onay_kapsami_yaz("kart")
os.remove(ayarlar.dosya())
k.denetle()
kontrol("panel açık + ayar dosyası silindi → 'hepsi'", k.metin("onaylar") == "hepsi" and
        istemci().get("kapsam") == "hepsi")

# ================================================================ kanal doğrulanamıyor → hepsi
A.onay_kapsami_yaz("kart")
d = json.load(open(onay.panel_pid_yolu()))
json.dump(dict(d, exe="/usr/bin/baska"), open(onay.panel_pid_yolu(), "w"))
kontrol("panel.pid kaydı uyuşmuyor (kanal doğrulanamıyor) → istemci 'hepsi'", istemci().get("kapsam") == "hepsi")
json.dump(d, open(onay.panel_pid_yolu(), "w"))
kontrol("kayıt düzelince → 'kart'", istemci().get("kapsam") == "kart")

# ================================================================ panel kapanır / yeniden açılır
liste_koruma.panel_durdur()
onay.panel_sil()
kontrol("panel kapandı (dosya + işaret 'kart') → istemci 'hepsi'", istemci().get("kapsam") == "hepsi")
uyarilar.clear()
onay.panel_kaydet()
k = liste_koruma.panel_baslat(uyarilar.append)
kontrol("panel yeniden açıldı: kendi işaretli 'kart'ı kabul (uyarı yok) → istemci 'kart'",
        k.metin("onaylar") == "kart" and not uyarilar and istemci().get("kapsam") == "kart", str(uyarilar))
liste_koruma.panel_durdur()
onay.panel_sil()
liste_koruma._isaret_yaz(liste_koruma.KAPSAM, "hepsi")  # işaret 'hepsi' ama dosyaya elle 'kart'
ajan_yazar("kart")
onay.panel_kaydet()
k = liste_koruma.panel_baslat(uyarilar.append)
kontrol("panel açılışı: dosya 'kart' + işaret 'hepsi' → 'hepsi' + uyarı",
        k.metin("onaylar") == "hepsi" and dosyada() == "hepsi" and len(uyarilar) == 1)
liste_koruma.panel_durdur()
onay.panel_sil()
os.remove(liste_koruma.isaret_yolu(liste_koruma.KAPSAM))
ajan_yazar("hepsi")
onay.panel_kaydet()
k = liste_koruma.panel_baslat()
kontrol("panel açılışı: dosya 'hepsi' → 'hepsi' (işaret yazıldı)", k.metin("onaylar") == "hepsi" and
        liste_koruma.isaret_oku(liste_koruma.KAPSAM).get("icerik") == "hepsi")


# ================================================================ eski panel (`liste onaylar` bilmeyen) → hepsi
liste_koruma.panel_durdur()  # sağlayıcı yok: panel 'saglayici-yok' yanıtlar
onay.liste_saglayici = lambda tur: None if tur == "onaylar" else ""
kontrol("panel kapsam sunmuyor (yanıt 'yok') → 'hepsi'", istemci().get("kapsam") == "hepsi")
onay.liste_saglayici = lambda tur: "kart; rm" if tur == "onaylar" else ""
kontrol("panel tanınmayan değer yanıtlıyor → 'hepsi'", istemci().get("kapsam") == "hepsi")
onay.liste_saglayici = None
onay.panel_sil()
time.sleep(0)

print(f"\n{gecen}/{toplam} kapsam-koruma testi geçti")
sys.exit(0 if gecen == toplam else 1)
