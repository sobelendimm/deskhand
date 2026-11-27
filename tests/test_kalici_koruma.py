"""`[oturum] kalici` (persistent background session sites) is PANEL-AUTHORITATIVE (security review item 6): a site an
agent writes into ayarlar.toml is not used until the user approves it in the panel.

This process acts as the panel (onay.panel_kaydet + liste_koruma.panel_baslat with a fake approval callback); the
client is a SEPARATE process (CLI/MCP/copy watchdog) that gets the list only through the panel's verified channel.
Ekransız, girdi yok, gerçek ~/.config yazılmaz (_yalitim). Çalıştır: python3 tests/test_kalici_koruma.py"""
import json
import os
import subprocess
import sys

import _yalitim  # noqa: F401  (deskhand'dan ÖNCE)

from deskhand import ayarlar, doktor, liste_koruma, onay  # noqa: E402

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


ISTEMCI = ("import json, sys; sys.path.insert(0, sys.argv[1]); from deskhand.oturum import kalici\n"
           "print(json.dumps(sorted(kalici.ayar_siteleri())))\n")


def istemci():
    """AYRI süreç: kalıcı oturum siteleri nereden geliyor?"""
    r = subprocess.run([sys.executable, "-c", ISTEMCI, _yalitim.KOK], capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"hata": r.stdout + r.stderr}


def ajan_yazar(deger):
    """Ajan: uçbirimle ayarlar.toml'a yazar (panelden geçmeden)."""
    os.makedirs(os.path.dirname(ayarlar.dosya()), exist_ok=True)
    with open(ayarlar.dosya(), "w") as f:
        f.write(f'[oturum]\nkalici = "{deger}"\n')


def baslat(cevap, sorulan, uyarilar):
    """Panel koruyucusu; the approval callback answers `cevap` and records what was asked."""
    def onayla(siteler):
        sorulan.append(list(siteler))
        return cevap
    try:
        return liste_koruma.panel_baslat(uyarilar.append, onayla=onayla)
    except TypeError:  # old code: no approval callback
        return liste_koruma.panel_baslat(uyarilar.append)


def dene(ad, fn, ek=""):
    try:
        kontrol(ad, fn(), ek() if callable(ek) else ek)
    except Exception as e:  # noqa: BLE001
        kontrol(ad, False, f"{type(e).__name__}: {e}")


# ================================================================ panel kapalı
ajan_yazar("ajan.test")
dene("6a: panel kapalı + dosyada elle site → istemci boş liste", lambda: istemci() == [], istemci)

# ================================================================ panel açık, kullanıcı REDDEDER
uyarilar, sorulan = [], []
onay.panel_kaydet()
k = baslat(False, sorulan, uyarilar)
dene("6b: panel açılışı: onaysız site sorulur, reddedilince kabul edilmez, dosyadan geri alınır",
     lambda: sorulan == [["ajan.test"]] and istemci() == [] and ayarlar.al("oturum", "kalici") == "",
     lambda: f"{sorulan} {istemci()} {ayarlar.al('oturum', 'kalici')!r}")
ajan_yazar("ajan.test, ikinci.test")
k.denetle()
dene("6c: panel açıkken ajan dosyaya yazar → sorulur, red → liste değişmez, dosya geri yazılır",
     lambda: sorulan[-1] == ["ajan.test", "ikinci.test"] and istemci() == [] and ayarlar.al("oturum", "kalici") == "",
     lambda: f"{sorulan} {istemci()}")
sahte_isaret("kalici", "ajan.test")  # sahte işaret: panelin BELLEĞİ yetkili
ajan_yazar("ajan.test")
n_sorulan = len(sorulan)
k.denetle()
dene("6d: sahte işaret + dosya → reddedilir; aynı içerik bu panel oturumunda zaten reddedildiği için yeniden "
     "sorulmaz (C6)", lambda: istemci() == [] and len(sorulan) == n_sorulan and ayarlar.al("oturum", "kalici") == "",
     lambda: f"{sorulan} {istemci()}")
liste_koruma.panel_durdur()
onay.panel_sil()

# ================================================================ kullanıcı ONAYLAR
uyarilar, sorulan = [], []
ajan_yazar("shopier.test")
onay.panel_kaydet()
k = baslat(True, sorulan, uyarilar)
dene("6e: kullanıcı panelde onaylar → istemci siteyi görür", lambda: istemci() == ["shopier.test"], istemci)
ajan_yazar("")
k.denetle()
dene("6f: dosyadan çıkarmak (sıkılaştırma) sorulmadan kabul", lambda: istemci() == [] and len(sorulan) == 1,
     lambda: f"{istemci()} {sorulan}")
dene("6g: doctor kalıcı listeyi panelden gösterir",
     lambda: doktor.satir_kalici_oturum()["ayrinti"].startswith("kapalı"), lambda: str(doktor.satir_kalici_oturum()))
ajan_yazar("shopier.test")
k.denetle()
dene("6h: doctor onaylı siteyi listeler", lambda: "shopier.test" in doktor.satir_kalici_oturum()["ayrinti"],
     lambda: str(doktor.satir_kalici_oturum()))
liste_koruma.panel_durdur()
onay.panel_sil()
dene("6i: panel kapandı → istemci boş (dosyada onaylı olsa bile)", lambda: istemci() == [], istemci)

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
