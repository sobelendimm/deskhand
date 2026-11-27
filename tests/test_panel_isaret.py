"""Panel-authoritative settings: the panel's mark is AUTHENTICATED (HMAC-SHA256, key in the Secret Service; H3 second
security review, Y1 class + Y5 + C6; docs/SESSIONS.md §3.8, deskhand/liste_koruma.py).

Threat: an agent (same uid) writes ayarlar.toml / the list files AND the plain sha256 mark while the panel is closed;
when the panel opens the forged value used to be accepted without any dialog (PoC kart-DHG/kanit_h3_isaret.py:
`dialog asked: [] warnings: [] client sees: ["ajan.test"]`).

Every type (yasak, seviye, onaylar, kimlik, kalici, kalici_sure) is checked:
  - a forged loosening (plain sha256 mark, or a wrong hmac) is NOT applied; the panel asks (default No);
  - a tightening in the file is accepted without asking;
  - a value the panel itself signed comes back without a question;
  - locked wallet / no key: loosening is not applied, no sha256 fallback; legacy sha256 marks are asked once;
  - C6: a refused change in an unwritable file is asked once per panel session (no dialog loop), the failure is shown.
No real wallet (fake key ring), no real ~/.config (tests/_yalitim). Run: python3 tests/test_panel_isaret.py"""
import hashlib
import json
import os
import subprocess
import sys
import time

import _yalitim  # noqa: F401  (before deskhand)

from deskhand import ayarlar, liste_koruma, onay  # noqa: E402
from deskhand.hata import Dur  # noqa: E402
from deskhand.oturum import kalici  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


class SahteAnahtarlik:
    """Fake Secret Service item of the panel (key + counters + last approved values), file-backed so that client
    processes see it too (KASA_ISTEMCI below); `kilitli` = locked wallet."""

    def __init__(self, yol):
        self.yol = yol
        self.kilitli = False

    def oku(self):
        if self.kilitli:
            raise kalici.AnahtarYok("cüzdan kilitli")
        try:
            with open(self.yol, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def yaz(self, veri):
        if self.kilitli:
            raise kalici.AnahtarYok("cüzdan kilitli")
        with open(self.yol, "wb") as f:
            f.write(veri)

    # the previous (key-only) fake interface, so this file still runs against 25c56e3 (red/green record)
    def anahtar(self, olustur):
        if self.kilitli:
            raise kalici.AnahtarYok("cüzdan kilitli")
        if not hasattr(self, "_k"):
            if not olustur:
                raise kalici.AnahtarYok("anahtar yok", yok=True)
            self._k = os.urandom(32)
        return self._k


KASA_YOLU = os.path.join(os.environ["DESKHAND_STATE_DIR"], "sahte-kasa.json")
ANAHTARLIK = SahteAnahtarlik(KASA_YOLU)
_ayarla = getattr(liste_koruma, "isaret_anahtarlik_ayarla", None)
if _ayarla is not None:
    _ayarla(ANAHTARLIK)

SORULAN: list = []
UYARILAR: list = []
CEVAP = {"evet": False}


def onayla(siteler):
    SORULAN.append(("kalici", list(siteler)))
    return CEVAP["evet"]


def sor(tur, aciklama):
    SORULAN.append((tur, aciklama))
    return CEVAP["evet"]


def panel_ac(evet=False):
    """Panel start with recording dialogs (no Qt)."""
    SORULAN.clear()
    UYARILAR.clear()
    CEVAP["evet"] = evet
    liste_koruma.panel_durdur()
    onay.panel_kaydet()
    try:
        return liste_koruma.panel_baslat(UYARILAR.append, onayla, sor)
    except TypeError:  # older liste_koruma: no generic question callback
        return liste_koruma.panel_baslat(UYARILAR.append, onayla)


def panel_kapat():
    liste_koruma.panel_durdur()
    onay.panel_sil()


def ajan_ayar(bolum, anahtar, deger):
    """The agent edits ayarlar.toml by hand (no panel API)."""
    os.makedirs(os.path.dirname(ayarlar.dosya()), exist_ok=True)
    try:
        metin = open(ayarlar.dosya()).read()
    except OSError:
        metin = ""
    import re
    satir = f"{anahtar} = {json.dumps(deger) if isinstance(deger, str) else deger}"
    if re.search(rf"^\[{bolum}\]", metin, re.M):
        if re.search(rf"^{anahtar}\s*=.*$", metin, re.M):
            metin = re.sub(rf"^{anahtar}\s*=.*$", satir, metin, flags=re.M)
        else:
            metin = re.sub(rf"^\[{bolum}\]\n", f"[{bolum}]\n{satir}\n", metin, flags=re.M)
    else:
        metin += f"\n[{bolum}]\n{satir}\n"
    open(ayarlar.dosya(), "w").write(metin)


def sahte_isaret(tur, metin, hmac_=None):
    """The agent's forged mark: plain sha256 (the old format) or a made-up hmac."""
    d = {"sha256": "yok" if metin is None else hashlib.sha256(metin.encode()).hexdigest(), "icerik": metin,
         "var": metin is not None, "zaman": time.time()}
    if hmac_ is not None:
        d["hmac"] = hmac_
        d["surum"] = 2
    with open(liste_koruma.isaret_yolu(tur), "w") as f:
        json.dump(d, f)


ISTEMCI = ("import json, sys; sys.path.insert(0, sys.argv[1]); from deskhand.oturum import kalici\n"
           "from deskhand import liste_koruma\n"
           "class K:\n"
           "    def oku(self):\n"
           "        try:\n"
           "            return open(sys.argv[2], 'rb').read()\n"
           "        except FileNotFoundError:\n"
           "            return None\n"
           "    def yaz(self, v):\n"
           "        raise kalici.AnahtarYok('istemci yazmaz')\n"
           "getattr(liste_koruma, 'isaret_anahtarlik_ayarla', lambda n: None)(K())\n"
           "print(json.dumps({'kalici': sorted(kalici.ayar_siteleri()), 'sure': kalici.sure_gun(),"
           " 'kimlik': sorted(liste_koruma.kimlik_izinleri()), 'kapsam': liste_koruma.kapsam()}))\n")


def istemci():
    r = subprocess.run([sys.executable, "-c", ISTEMCI, _yalitim.KOK, KASA_YOLU], capture_output=True, text=True,
                       timeout=60)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"hata": r.stdout + r.stderr[-400:]}


def sorulan_turler():
    return [t for t, _a in SORULAN]


YASAK = liste_koruma.dosya("yasak")
SEVIYE = liste_koruma.dosya("seviye")
os.makedirs(os.path.dirname(YASAK), exist_ok=True)
open(YASAK, "w").write("GizliKasa\n")
open(SEVIYE, "w").write("KeePassXC = goruntule\n")

# ================================================================ baseline: the panel signs its own state
k = panel_ac()
kontrol("hazırlık: ilk açılış soru sormaz", SORULAN == [], str(SORULAN))
m = liste_koruma.isaret_oku(liste_koruma.KALICI) or {}
kontrol("işaret HMAC taşır (anahtar cüzdanda, ayrı öge)", isinstance(m.get("hmac"), str) and len(m["hmac"]) == 64,
        str(m))
panel_kapat()

# ================================================================ Y1 PoC: forged kalici site + plain sha256 mark
ajan_ayar("oturum", "kalici", "ajan.test")
sahte_isaret(liste_koruma.KALICI, "ajan.test")
k = panel_ac(evet=False)
r = istemci()
kontrol("Y1 PoC: sahte işaret + ayar → panel açılışında diyalog sorulur",
        ("kalici", ["ajan.test"]) in SORULAN, str(SORULAN))
kontrol("Y1 PoC: reddedilince istemci listesi boş", r.get("kalici") == [], str(r))
kontrol("Y1 PoC: dosya panelin listesine geri yazıldı + görünür uyarı",
        liste_koruma.kalici_dosyada() == frozenset() and UYARILAR, str(UYARILAR))
panel_kapat()

# forged hmac field
ajan_ayar("oturum", "kalici", "ajan.test")
sahte_isaret(liste_koruma.KALICI, "ajan.test", hmac_="0" * 64)
k = panel_ac(evet=False)
kontrol("Y1: uydurma hmac alanı da geçmez (sorulur, kullanılmaz)",
        ("kalici", ["ajan.test"]) in SORULAN and istemci().get("kalici") == [], str(SORULAN))
panel_kapat()

# user says Yes → accepted and signed; next start: no question
ajan_ayar("oturum", "kalici", "dukkan.test")
k = panel_ac(evet=True)
kontrol("Y1: kullanıcı Evet → site kabul", istemci().get("kalici") == ["dukkan.test"])
panel_kapat()
k = panel_ac()
kontrol("Y1: panelin imzaladığı liste yeniden açılışta sorusuz", SORULAN == [] and
        istemci().get("kalici") == ["dukkan.test"], str(SORULAN))
panel_kapat()

# tightening: removing a site needs no question
ajan_ayar("oturum", "kalici", "")
k = panel_ac()
kontrol("sıkılaştırma: dosyadan site silmek sorusuz kabul", SORULAN == [] and istemci().get("kalici") == [],
        str(SORULAN))
panel_kapat()

# ================================================================ Y1 class: every other type
# yasak: emptied + forged mark
open(YASAK, "w").write("")
sahte_isaret("yasak", "")
k = panel_ac()
kontrol("Y1/yasak: boşaltılmış dosya + sahte işaret → panelin son kaydı, soru",
        k.metin("yasak") == "GizliKasa\n" and "yasak" in sorulan_turler() and open(YASAK).read() == "GizliKasa\n",
        f"{k.metin('yasak')!r} {SORULAN}")
panel_kapat()
open(YASAK, "w").write("GizliKasa\nBanka\n")
k = panel_ac()
kontrol("Y1/yasak: desen eklemek (sıkılaştırma) sorusuz kabul", k.metin("yasak") == "GizliKasa\nBanka\n" and
        "yasak" not in sorulan_turler(), str(SORULAN))
panel_kapat()

# seviye: raised level + forged mark
open(SEVIYE, "w").write("KeePassXC = tam\n")
sahte_isaret("seviye", "KeePassXC = tam\n")
k = panel_ac()
kontrol("Y1/seviye: seviye yükseltme + sahte işaret → kullanılmaz, soru",
        k.metin("seviye") == "KeePassXC = goruntule\n" and "seviye" in sorulan_turler(), f"{k.metin('seviye')!r}")
panel_kapat()

# kapsam: kart + forged mark
ajan_ayar("guvenlik", "onaylar", "kart")
sahte_isaret(liste_koruma.KAPSAM, "kart")
k = panel_ac()
kontrol("Y1/kapsam: sahte 'kart' → 'hepsi' + soru", k.metin(liste_koruma.KAPSAM) == "hepsi" and
        liste_koruma.KAPSAM in sorulan_turler(), str(SORULAN))
panel_kapat()

# kimlik: google + forged mark
ajan_ayar("guvenlik", "hesap_oturumlari", "google")
sahte_isaret(liste_koruma.KIMLIK, "google")
k = panel_ac()
kontrol("Y1/kimlik: sahte izin → yok + soru", k.metin(liste_koruma.KIMLIK) == "" and
        liste_koruma.KIMLIK in sorulan_turler() and istemci().get("kimlik") == [], str(SORULAN))
panel_kapat()

# Y5: kalici_sure_gun 365 + forged mark
SURE = getattr(liste_koruma, "SURE", "kalici_sure")
ajan_ayar("oturum", "kalici", "dukkan.test")
liste_koruma.panel_kalici_kaydet("dukkan.test")  # the panel (no koruyucu) signs the list
ajan_ayar("oturum", "kalici_sure_gun", 365)
sahte_isaret(SURE, "365")
k = panel_ac()
r = istemci()
kontrol("Y5: kalici_sure_gun 365 (sahte işaret) → istemci 30, soru", r.get("sure") == 30 and SURE in sorulan_turler(),
        f"{r} {SORULAN}")
panel_kapat()
ajan_ayar("oturum", "kalici_sure_gun", 7)
k = panel_ac()
kontrol("Y5: süre kısaltmak (7) sorusuz kabul", istemci().get("sure") == 7 and SURE not in sorulan_turler(),
        str(SORULAN))
panel_kapat()

# ================================================================ key unavailable: no sha256 fallback
liste_koruma.panel_kapsam_kaydet("kart")  # the panel signs 'kart'
k = panel_ac()
kontrol("anahtar var: panelin imzalı 'kart'ı sorusuz", k.metin(liste_koruma.KAPSAM) == "kart" and
        liste_koruma.KAPSAM not in sorulan_turler(), str(SORULAN))
panel_kapat()
ANAHTARLIK.kilitli = True
getattr(liste_koruma, "_anahtar_unut", lambda: None)()
k = panel_ac()
kontrol("cüzdan kilitli: imzalı 'kart' bile doğrulanamaz → 'hepsi' + soru (düşüş yok)",
        k.metin(liste_koruma.KAPSAM) == "hepsi" and liste_koruma.KAPSAM in sorulan_turler(), str(SORULAN))
panel_kapat()
ANAHTARLIK.kilitli = False
getattr(liste_koruma, "_anahtar_unut", lambda: None)()

# ================================================================ migration: legacy sha256 mark asked once
ajan_ayar("oturum", "kalici", "eski.test")
sahte_isaret(liste_koruma.KALICI, "eski.test")  # what the previous release wrote
k = panel_ac(evet=True)
kontrol("geçiş: eski sha256 işaretli değer bir kez sorulur", ("kalici", ["eski.test"]) in SORULAN, str(SORULAN))
panel_kapat()
k = panel_ac()
kontrol("geçiş: onaydan sonra HMAC yazıldı, yeniden sorulmaz", SORULAN == [] and
        istemci().get("kalici") == ["eski.test"], str(SORULAN))

# ================================================================ C6: unwritable file → one question per session
ajan_ayar("oturum", "kalici_sure_gun", 365)  # panel open: loosening in the file
dizin = os.path.dirname(ayarlar.dosya())
os.chmod(ayarlar.dosya(), 0o444)
os.chmod(dizin, 0o555)
try:
    SORULAN.clear()
    UYARILAR.clear()
    for _i in range(3):
        k.denetle()
    kontrol("C6: yazılamayan dosyada reddedilen değişiklik oturumda bir kez sorulur",
            sorulan_turler().count(SURE) == 1, str(SORULAN))
    kontrol("C6: yazılamama görünür uyarı", any("yazılamadı" in u for u in UYARILAR), str(UYARILAR))
    kontrol("C6: değer yine uygulanmadı", istemci().get("sure") == 7)
finally:
    os.chmod(dizin, 0o755)
    os.chmod(ayarlar.dosya(), 0o644)
panel_kapat()

# ================================================================ panel closed: the client path verifies the hmac too
k = panel_ac()
liste_koruma.panel_kaydet("yasak", "GizliKasa\n")
panel_kapat()
liste_koruma.onbellek_sil()
open(YASAK, "w").write("GizliKasa\nEk\n")
try:
    v = liste_koruma.metin("yasak")
except Dur as e:
    v = f"Dur {e.kod}"
kontrol("panel kapalı: imzalı kayda göre sıkılaştırma okunur", v == "GizliKasa\nEk\n", repr(v))
open(YASAK, "w").write("")
sahte_isaret("yasak", "")
try:
    v = liste_koruma.metin("yasak")
    e_ = None
except Dur as e:
    v, e_ = None, e
kontrol("panel kapalı: boşaltma + sahte işaret → Dur 10 (girdi yok)", e_ is not None and e_.kod == 10, repr(v))


# ================================================================ replay: an older signed mark put back
liste_koruma.onbellek_sil()
liste_koruma.panel_kalici_kaydet("replay.test")
eski_isaret = open(liste_koruma.isaret_yolu(liste_koruma.KALICI), "rb").read()
liste_koruma.panel_kalici_kaydet("")  # the user removed it in the panel
ajan_ayar("oturum", "kalici", "replay.test")
with open(liste_koruma.isaret_yolu(liste_koruma.KALICI), "wb") as f:
    f.write(eski_isaret)
getattr(liste_koruma, "_anahtar_unut", lambda: None)()
k = panel_ac()
kontrol("replay: eski imzalı işaret geri konunca gevşetme uygulanmaz", ("kalici", ["replay.test"]) in SORULAN and
        istemci().get("kalici") == [], str(SORULAN))
panel_kapat()

# ================================================================ locked wallet: a new site in the file
ANAHTARLIK.kilitli = True
getattr(liste_koruma, "_anahtar_unut", lambda: None)()
ajan_ayar("oturum", "kalici", "kilit.test")
k = panel_ac()
kontrol("cüzdan kilitli: dosyadaki yeni kalıcı site istemciye gitmez, panel sorar",
        ("kalici", ["kilit.test"]) in SORULAN and istemci().get("kalici") == [], str(SORULAN))
kontrol("cüzdan kilitli: bir kez görünür uyarı", sum("imzalı kaydı kullanılamıyor" in u for u in UYARILAR) == 1,
        str(UYARILAR))
panel_kapat()
ANAHTARLIK.kilitli = False

# ================================================================ first start (no item, no marks)
os.remove(KASA_YOLU) if os.path.exists(KASA_YOLU) else None
for t in liste_koruma.TUM if hasattr(liste_koruma, "TUM") else ():
    if os.path.exists(liste_koruma.isaret_yolu(t)):
        os.remove(liste_koruma.isaret_yolu(t))
getattr(liste_koruma, "_anahtar_unut", lambda: None)()
open(YASAK, "w").write("Ilk\n")
ajan_ayar("oturum", "kalici", "ilk.test")
ajan_ayar("oturum", "kalici_sure_gun", 5)
k = panel_ac()
kontrol("ilk kurulum: imzasız gevşetme sorulur, daraltma sorusuz",
        ("kalici", ["ilk.test"]) in SORULAN and "yasak" not in sorulan_turler() and SURE not in sorulan_turler() and
        k.metin("yasak") == "Ilk\n" and istemci().get("kalici") == [], str(SORULAN))
panel_kapat()

# ================================================================ DUR: opening is free, removing is the user's
from deskhand import guvenlik  # noqa: E402

CLI = "import sys; sys.path.insert(0, sys.argv[1]); from deskhand import cli; cli.main(sys.argv[2:])"


def cli_kos(*argv):
    r = subprocess.run([sys.executable, "-c", CLI, _yalitim.KOK, *argv], capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


onay.panel_sil()
kod, cikti_dur = cli_kos("dur")
kontrol("DUR: CLI açabilir (sıkılaştırma serbest)", guvenlik.dur_acik(), cikti_dur)
kod2, cikti2 = cli_kos("devam", "--approved")
kod, cikti = cli_kos("devam")
kontrol("DUR: CLI resume panel kapalı → ret, --approved yok sayılır", guvenlik.dur_acik() and kod != 0 and kod2 != 0,
        f"{kod} {cikti} | {kod2} {cikti2[-200:]}")
kontrol("DUR: ret iletisi kullanıcının panelden kaldıracağını söyler", "panel" in cikti.lower(), cikti)
kontrol("DUR iletisi resume komutunu tarif etmez",
        not any(s in cikti_dur + cikti for s in (" devam", " resume", "'ekran resume'")), cikti_dur + cikti)
os.environ["DESKHAND_GOZETIMSIZ"] = "1"
kod, cikti = cli_kos("resume")
os.environ.pop("DESKHAND_GOZETIMSIZ", None)
kontrol("DUR: gözetimsiz kipte de kaldırılamaz", guvenlik.dur_acik() and kod != 0, f"{kod} {cikti}")
guvenlik.dur_kapat("kullanici")  # the panel's own button
kontrol("DUR: panelin kendi düğmesi kaldırır", not guvenlik.dur_acik())

# ================================================================ TARAMA-2 (1): marks exist, no signed state → closed-fail
k = panel_ac()
liste_koruma.panel_kaydet("yasak", "Kilitli\n")
panel_kapat()
open(YASAK, "w").write("")  # the agent empties the list (marks stay)
ANAHTARLIK.kilitli = True
getattr(liste_koruma, "_anahtar_unut", lambda: None)()
k = panel_ac()
kontrol("tarama-2: işaret var + cüzdan yok → yasak gevşetmesi uygulanmaz, sorulur",
        k.metin("yasak") == "Kilitli\n" and "yasak" in sorulan_turler(), f"{k.metin('yasak')!r} {SORULAN}")
panel_kapat()
open(YASAK, "w").write("")
ISTEMCI_KAPALI = ("import json, sys; sys.path.insert(0, sys.argv[1]); from deskhand import liste_koruma\n"
                  "from deskhand.hata import Dur\n"
                  "try:\n"
                  "    print(json.dumps({'yasak': liste_koruma.metin('yasak')}))\n"
                  "except Dur as e:\n"
                  "    print(json.dumps({'dur': e.kod}))\n")
r = subprocess.run([sys.executable, "-c", ISTEMCI_KAPALI, _yalitim.KOK], capture_output=True, text=True, timeout=60,
                   env=dict(os.environ, DESKHAND_ANAHTARLIK="kapali"))
kontrol("tarama-2: DESKHAND_ANAHTARLIK=kapali istemci gevşetmeyi göremez (Dur 10)", '"dur": 10' in r.stdout,
        r.stdout + r.stderr[-300:])
ANAHTARLIK.kilitli = False
getattr(liste_koruma, "_anahtar_unut", lambda: None)()
liste_koruma.onbellek_sil()

# ================================================================ TARAMA-2 (2): DUR removal is a panel-side request
from deskhand import guvenlik as _g  # noqa: E402

TUR_DUR = getattr(onay, "TUR_DUR", "dur")


def dur_istegi(eylem="Kaydet", ayrinti="AJAN METNI: Evet deyin"):
    import uuid
    i = uuid.uuid4().hex
    os.makedirs(os.path.dirname(onay.istek_yolu(i)), exist_ok=True)
    simdi = time.time()
    with open(onay.istek_yolu(i), "w") as f:
        json.dump({"id": i, "eylem": eylem, "hedef": "DUR", "ayrinti": ayrinti, "masaustu": "ekran", "zaman": simdi,
                   "son_zaman": simdi + 60, "pid": os.getpid(), "tur": TUR_DUR}, f)
    return i


d_ = onay.istek_oku(onay.istek_yolu(dur_istegi()))
kontrol("tarama-2: DUR sorusunda istekçinin metni görünmez (panel sabit metin)",
        d_ is not None and "AJAN" not in d_["ayrinti"] and d_["eylem"] != "Kaydet", str(d_))


class SahteKanal:
    def yanitlandi(self, i):
        return False

    def gonder(self, i, karar):
        return True


eski_kanal = onay._KANAL
onay._KANAL = SahteKanal()
try:
    _g.dur_ac("kullanici")
    onay.yanitla(dur_istegi(), "izin")
    kontrol("tarama-2: kullanıcı Evet → DUR'u PANEL kaldırır", not _g.dur_acik())
finally:
    onay._KANAL = eski_kanal
kontrol("tarama-2: SON_DUR_IZNI (zamana bağlı genel onay) yok", not hasattr(onay, "SON_DUR_IZNI"))

eski_iste = onay.iste_sonuc
sayac = []
onay.iste_sonuc = lambda *a, **k: (sayac.append(1), onay.OnaySonucu(True, "izin"))[1]
try:
    _g.dur_ac("kullanici")
    for _i in range(2):
        try:
            _g.dur_kaldir_iste()
        except Dur:
            pass
    kontrol("tarama-2: istekçi 'izin' alsa da DUR'u kendisi kaldırmaz; her istek yeni soru",
            _g.dur_acik() and len(sayac) == 2, f"{_g.dur_acik()} {len(sayac)}")
finally:
    onay.iste_sonuc = eski_iste
    _g.dur_kapat("kullanici")

print(f"\n{gecen}/{toplam} panel-işaret testi geçti")
sys.exit(0 if gecen == toplam else 1)
