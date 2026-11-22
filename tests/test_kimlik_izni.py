"""Hesap oturumu izni (ayarlar.toml [guvenlik] hesap_oturumlari; ARCHITECTURE §4 "Hesap oturumları") testleri.

Varsayılan KAPALI: Microsoft (login.live.com, login.microsoftonline.com + .live.com alan çerezleri) ve Google
(accounts.google.com, securetoken.googleapis.com + .google.com alan çerezleri) oturumu görünmez masaüstündeki Firefox
kopyasına girmez. İzin YALNIZ panelden açılır (panel yetkili; liste_koruma deseni): elle yazılan değer geri alınır,
CLI/MCP süreçleri değeri yalnız panelin doğrulanmış kanalından alır, görev kipinde izin hiç uygulanmaz, banka/devlet
ret listesi etkilenmez.

SAHTE ev dizini + sahte Firefox profili (cookies.sqlite, recovery.jsonlz4, logins.json): kullanıcının gerçek profili
okunmaz/yazılmaz. Ekransız (Qt offscreen), girdi yok, gerçek ~/.config yazılmaz (_yalitim).
Çalıştır: python3 tests/test_kimlik_izni.py"""
import json
import os
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _yalitim  # noqa: E402,F401  (deskhand'dan ÖNCE)

from deskhand import ayarlar, doktor, gorev_kipi, liste_koruma, onay  # noqa: E402
from deskhand.oturum import firefox, politika  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


# ---------------------------------------------------------------- sahte ev + sahte Firefox profili
EV = tempfile.mkdtemp(prefix="deskhand-kimlik-ev-", dir=_yalitim.GECICI)
os.environ["HOME"] = EV
os.environ.pop("XDG_CONFIG_HOME", None)
for _a in (gorev_kipi.ORTAM, gorev_kipi.SITE_ORTAM):
    os.environ.pop(_a, None)
KOK = os.path.join(EV, ".config", "mozilla", "firefox")
PROF = os.path.join(KOK, "ab12.default-release")
os.makedirs(os.path.join(PROF, "sessionstore-backups"), exist_ok=True)
with open(os.path.join(KOK, "profiles.ini"), "w") as f:
    f.write("[Profile0]\nName=d\nIsRelative=1\nPath=ab12.default-release\nDefault=1\n\n"
            "[Install1]\nDefault=ab12.default-release\nLocked=1\n")

MS = {(".live.com", "MSPAuth"), (".live.com", "WLSSC"), ("login.live.com", "__Host-MSAAUTHP"),
      ("login.microsoftonline.com", "ESTSAUTHPERSISTENT")}
MS_OTURUM = {(".live.com", "MSPRequ")}  # oturum çerezi (yalnız recovery.jsonlz4'te)
GOOGLE = {(".google.com", "SID"), (".google.com", "__Secure-3PSID"), ("accounts.google.com", "LSID"),
          ("securetoken.googleapis.com", "tok")}
EDEVLET = {("www.turkiye.gov.tr", "t"), ("giris.turkiye.gov.tr", "TURKIYESESSIONID"), (".gib.gov.tr", "g"),
           ("www.sgk.gov.tr", "s"), ("ivd.gib.gov.tr", "i")}
# banka/ödeme: HİÇBİR izinle açılmaz (ebank.gov.tr hem *bank* hem *.gov.tr: e-Devlet izni açıkken de ret)
BANKA = {("mybank.com", "sess"), (".isbank.com.tr", "s"), (".paypal.com", "p"), ("checkout.example.com", "c"),
         ("ebank.gov.tr", "b"), ("www.iyzico.com", "y")}
NOTR = {("example.com", "a"), (".github.com", "logged_in")}

con = sqlite3.connect(os.path.join(PROF, "cookies.sqlite"))
con.execute("CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, originAttributes TEXT NOT NULL DEFAULT '', "
            "name TEXT, value TEXT, host TEXT, path TEXT, expiry INTEGER, lastAccessed INTEGER, "
            "creationTime INTEGER, isSecure INTEGER, isHttpOnly INTEGER, inBrowserElement INTEGER DEFAULT 0, "
            "sameSite INTEGER DEFAULT 0, schemeMap INTEGER DEFAULT 0, isPartitionedAttributeSet INTEGER DEFAULT 0, "
            "updateTime INTEGER, CONSTRAINT moz_uniqueid UNIQUE (name, host, path, originAttributes))")
for host, ad in MS | GOOGLE | EDEVLET | BANKA | NOTR:
    con.execute("INSERT INTO moz_cookies (originAttributes,name,value,host,path,expiry) VALUES ('',?,?,?,'/',0)",
                (ad, "GIZLI", host))
con.commit()
con.close()

try:
    import lz4.block
    _ham = json.dumps({"cookies": [{"host": h, "name": n, "value": "GIZLI", "path": "/"} for h, n in MS_OTURUM]}).encode()
    with open(os.path.join(PROF, "sessionstore-backups", "recovery.jsonlz4"), "wb") as f:
        f.write(b"mozLz40\0" + struct.pack("<I", len(_ham)) + lz4.block.compress(_ham, store_size=False))
    LZ4 = True
except ImportError:
    LZ4 = False

GIRISLER = {"https://login.live.com": "microsoft", "https://accounts.google.com": "google",
            "https://giris.turkiye.gov.tr": "edevlet", "https://www.isbank.com.tr": "banka", "https://example.com": "notr"}
with open(os.path.join(PROF, "logins.json"), "w") as f:
    json.dump({"nextId": 5, "logins": [{"id": i, "hostname": h, "formSubmitURL": h, "guid": f"{{g{i}}}",
                                        "encryptedUsername": "x", "encryptedPassword": "y"}
                                       for i, h in enumerate(GIRISLER)]}, f)


def _kaynak_ozet():
    import hashlib
    h = hashlib.sha1()
    for kok, _d, dosyalar in sorted(os.walk(PROF)):
        for ad in sorted(dosyalar):
            with open(os.path.join(kok, ad), "rb") as f:
                h.update(ad.encode() + f.read())
    return h.hexdigest()


KAYNAK_ONCE = _kaynak_ozet()


def kopya_sonucu(b):
    """→ (çerez kümesi {(host, ad)}, giriş konakları kümesi)."""
    c = sqlite3.connect(os.path.join(b["kopya_yolu"], "cookies.sqlite"))
    cerez = {(h, n) for h, n in c.execute("SELECT host, name FROM moz_cookies")}
    c.close()
    try:
        with open(os.path.join(b["kopya_yolu"], "logins.json")) as f:
            giris = {g["hostname"] for g in json.load(f)["logins"]}
    except (OSError, ValueError, KeyError):
        giris = set()
    return cerez, giris


def hazirla_burada():
    return kopya_sonucu(firefox.hazirla(politika.coz("firefox")))


ISTEMCI = ("import json, os, sqlite3, sys; sys.path.insert(0, sys.argv[1])\n"
           "from deskhand.oturum import firefox, politika\n"
           "b = firefox.hazirla(politika.coz('firefox'))\n"
           "c = sqlite3.connect(os.path.join(b['kopya_yolu'], 'cookies.sqlite'))\n"
           "cerez = sorted([h, n] for h, n in c.execute('SELECT host, name FROM moz_cookies'))\n"
           "y = os.path.join(b['kopya_yolu'], 'logins.json')\n"
           "g = json.load(open(y))['logins'] if os.path.exists(y) else []\n"
           "print(json.dumps({'cerez': cerez, 'giris': [x['hostname'] for x in g], 'izin': b.get('kimlik_izni')}))\n")


def istemci(ortam=None):
    """AYRI süreç (CLI/MCP gibi): Firefox kopyasını kendisi hazırlar; izni yalnız panelden kanalla alabilir."""
    r = subprocess.run([sys.executable, "-c", ISTEMCI, _yalitim.KOK], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, **(ortam or {})))
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
        return {tuple(x) for x in d["cerez"]}, set(d["giris"]), d
    except (ValueError, IndexError, KeyError):
        return set(), set(), {"hata": r.stdout[-500:] + r.stderr[-1500:]}


def ajan_yazar(deger, isaret=False):
    """Ajan: ayarlar.toml'a elle yazar (panelden geçmeden); isteğe bağlı sahte işaret de bırakır."""
    os.makedirs(os.path.dirname(ayarlar.dosya()), exist_ok=True)
    with open(ayarlar.dosya(), "w") as f:
        f.write(f'[guvenlik]\nhesap_oturumlari = "{deger}"\n')
    if isaret:
        liste_koruma._isaret_yaz(liste_koruma.KIMLIK, deger)


def dosyada():
    return ayarlar.al("guvenlik", "hesap_oturumlari")


# ================================================================ birim: politika + ayar doğrulama
pol = politika.coz("firefox")
ham = set(pol._reddet)
for sag in ("microsoft", "google", "edevlet"):
    yeni = pol.kimlik_izni_uygula({sag})
    cikan = ham - set(yeni._reddet)
    kontrol(f"kimlik_izni_uygula({sag}): yalnız o sağlayıcının merkezi kimlik alanları çıkar",
            cikan == set(politika.KIMLIK_ALANLARI[sag]) and set(yeni._reddet) <= ham, str(cikan))
kontrol("kimlik_izni_uygula: kaynak politika değişmez; boş/bilinmeyen izin → aynı nesne",
        set(pol._reddet) == ham and pol.kimlik_izni_uygula(set()) is pol and pol.kimlik_izni_uygula({"yahoo"}) is pol)
iki = pol.kimlik_izni_uygula({"microsoft", "google", "edevlet"})
kontrol("üç izin açıkken banka/ödeme desenleri ret listesinde kalır (ebank.gov.tr dahil)",
        all(iki.site_reddedildi(a) for a in ("www.isbank.com.tr", "mybank.com", "ebank.gov.tr", "paypal.com",
                                              "checkout.example", "www.iyzico.com", "papara.com", "odeme.example")) and
        iki.cerez_reddedildi(".isbank.com.tr") and not iki.cerez_reddedildi(".live.com") and
        not iki.cerez_reddedildi(".google.com") and not iki.site_reddedildi("www.turkiye.gov.tr") and
        not iki.site_reddedildi("ivd.gib.gov.tr"))
kontrol("hiçbir sağlayıcının girdisi banka/ödeme deseni değil",
        not any(any(x in g for x in ("bank", "odeme", "payment", "checkout", "paypal", "stripe"))
                for alanlar in politika.KIMLIK_ALANLARI.values() for g in alanlar))
kontrol("ayar doğrulama: alt küme kanonik yazılır, bilinmeyen sağlayıcı reddedilir",
        ayarlar.dogrula("guvenlik", "hesap_oturumlari", "edevlet google, microsoft") == "microsoft,google,edevlet" and
        ayarlar.dogrula("guvenlik", "hesap_oturumlari", "") == "")
try:
    ayarlar.dogrula("guvenlik", "hesap_oturumlari", "microsoft,yahoo")
    kontrol("ayar doğrulama: bilinmeyen sağlayıcı → ValueError", False)
except ValueError:
    kontrol("ayar doğrulama: bilinmeyen sağlayıcı → ValueError", True)
kontrol("varsayılan: ayar dosyası yok → hesap_oturumlari boş", dosyada() == "")

# ================================================================ varsayılan KAPALI (panel yok)
cerez, giris = hazirla_burada()
kontrol("varsayılan: kopyada MSPAuth / WLSSC / __Host-MSAAUTHP / ESTSAUTH YOK", not (cerez & MS), str(cerez & MS))
kontrol("varsayılan: kopyada Google kimlik çerezleri (.google.com SID, accounts, securetoken) YOK",
        not (cerez & GOOGLE), str(cerez & GOOGLE))
kontrol("varsayılan: banka ve e-Devlet/devlet çerezi YOK, nötr çerezler VAR",
        not (cerez & BANKA) and not (cerez & EDEVLET) and NOTR <= cerez)
kontrol("varsayılan: login.live.com / accounts.google.com / e-Devlet / banka kayıtlı girişleri YOK, nötr VAR",
        giris == {"https://example.com"}, str(giris))
if LZ4:
    kontrol("varsayılan: .live.com oturum çerezi (recovery.jsonlz4) eklenmez", not (cerez & MS_OTURUM))
b = firefox.hazirla(politika.coz("firefox"))
kontrol("varsayılan: kopya özeti 'Microsoft süzüldü (4 çerez; izin kapalı …)' + Google + e-Devlet süzüldü",
        b["kimlik_metni"].startswith("kimlik oturumları: Microsoft süzüldü (4 çerez; izin kapalı") and
        "Google süzüldü (4 çerez" in b["kimlik_metni"] and "e-Devlet süzüldü (5 çerez" in b["kimlik_metni"],
        b["kimlik_metni"])

# ================================================================ panel kapalı + ajan dosyaya yazar
ajan_yazar("microsoft,google")
c2, g2, d2 = istemci()
kontrol("panel kapalı + dosyada elle 'microsoft,google' → CLI/MCP süreci izin GÖRMEZ (kimlik çerezi yok)",
        "hata" not in d2 and not (c2 & (MS | GOOGLE)) and NOTR <= c2 and d2.get("izin") == [], str(d2)[:600])
ajan_yazar("microsoft,google", isaret=True)
c2, g2, d2 = istemci()
kontrol("panel kapalı + dosya VE işaret sahte → yine izin yok (kanal yok)", not (c2 & (MS | GOOGLE)), str(d2)[:300])
kontrol("doctor (panel kapalı, dosyada açık): uyarı satırı + 'Microsoft kapalı, Google kapalı'",
        doktor.satir_hesap_oturumlari()["durum"] == "uyari" and
        doktor.satir_hesap_oturumlari()["ayrinti"].startswith("Microsoft kapalı, Google kapalı, e-Devlet kapalı | son "
                                                              "kopya"),
        str(doktor.satir_hesap_oturumlari()))
os.remove(liste_koruma.isaret_yolu(liste_koruma.KIMLIK))

# ================================================================ panel açılışı: işaretsiz izin geri alınır
uyarilar = []
onay.panel_kaydet()
k = liste_koruma.panel_baslat(uyarilar.append)
kontrol("panel açılışı: dosyada işaretsiz 'microsoft,google' → bellek boş, dosya boşa geri yazılır, uyarı",
        k.metin(liste_koruma.KIMLIK) == "" and dosyada() == "" and
        any("Hesap oturumu" in u for u in uyarilar), f"{uyarilar} {dosyada()!r}")
c2, g2, d2 = istemci()
kontrol("panel açık (izin kapalı) → CLI/MCP kopyasında kimlik çerezi yok", not (c2 & (MS | GOOGLE)), str(d2)[:300])

# ================================================================ panel açıkken ajan dosyaya yazar
ajan_yazar("microsoft")
c2, g2, d2 = istemci()
kontrol("panel açık + dosyaya elle 'microsoft' → CLI/MCP izin görmez (panelin belleği yetkili)",
        not (c2 & MS) and d2.get("izin") == [], str(d2)[:300])
n0 = len(uyarilar)
u = k.denetle()
kontrol("panel denetimi: elle yazılan izin geri alınır (dosya boş) + uyarı", dosyada() == "" and len(u) == 1 and
        len(uyarilar) == n0 + 1, str(u))
ajan_yazar("microsoft", isaret=True)
k.denetle()
kontrol("panel açık + dosya ve işaret sahte → panel belleği boş kalır, dosya geri yazılır",
        k.metin(liste_koruma.KIMLIK) == "" and dosyada() == "")

# ================================================================ CLI/MCP: kanal salt okunur; yazma yolu yok
kayit = onay._panel_kaydi()
for satir in ("kimlik microsoft", "liste kimlik microsoft", "yaz kimlik microsoft,google"):
    try:
        s = onay._kanala_baglan(kayit)
        s.settimeout(5)
        s.sendall((satir + "\n").encode())
        try:
            s.recv(64)
        except (socket.timeout, OSError):
            pass
        s.close()
    except Exception:  # noqa: BLE001
        pass
kontrol("onay kanalına yazma denemeleri izni açmaz (kanal yalnız 'liste kimlik' okur)",
        k.metin(liste_koruma.KIMLIK) == "" and liste_koruma.kimlik_izinleri() == frozenset())
_kok = _yalitim.KOK
_kaynak = "".join(open(os.path.join(_kok, "deskhand", ad), encoding="utf-8").read()
                  for ad in ("cli.py", "mcp_sunucu.py", "komutlar.py") if os.path.exists(os.path.join(_kok, "deskhand", ad)))
kontrol("CLI/MCP kaynağında izin yazan çağrı yok (panel_kimlik_kaydet / kimlik_kaydet / hesap_oturumu_yaz)",
        not any(x in _kaynak for x in ("panel_kimlik_kaydet", "kimlik_kaydet", "hesap_oturumu_yaz",
                                       "hesap_oturumlari")))

# ================================================================ panelin Ayarlar'ı: tek yetkili yol (GUI + onay diyaloğu)
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from deskhand.gui import ayar as A  # noqa: E402
from deskhand.gui.pencere import AyarlarSekmesi  # noqa: E402

w = AyarlarSekmesi()
kontrol("Ayarlar: Hesap oturumları: ana anahtar + üç kutu var, hepsi kapalı",
        set(w.k_hesap) == {"microsoft", "google", "edevlet"} and not w.k_hesap_hepsi.isChecked() and
        not any(x.isChecked() for x in w.k_hesap.values()))
sorulan = []
w.hesap_onay_sor = lambda sag: (sorulan.append(sag), False)[1]  # kullanıcı onay diyaloğunda "Hayır"
w.k_hesap["microsoft"].setChecked(True)
kontrol("Ayarlar: kutu işaretlenince onay sorulur; 'Hayır' → kutu geri döner, izin kapalı",
        sorulan == ["microsoft"] and not w.k_hesap["microsoft"].isChecked() and
        liste_koruma.kimlik_izinleri() == frozenset() and dosyada() == "")
w.hesap_onay_sor = lambda sag: (sorulan.append(sag), True)[1]  # "Evet"
w.k_hesap["microsoft"].setChecked(True)
kontrol("Ayarlar: 'Evet' → yalnız Microsoft açık (bellek + dosya + işaret)",
        w.k_hesap["microsoft"].isChecked() and liste_koruma.kimlik_izinleri() == {"microsoft"} and
        dosyada() == "microsoft" and liste_koruma.isaret_oku(liste_koruma.KIMLIK).get("icerik") == "microsoft")

cerez, giris = hazirla_burada()
kontrol("panelden Microsoft açık → kopyada MSPAuth / WLSSC / __Host-MSAAUTHP / ESTSAUTH VAR", MS <= cerez,
        str(MS - cerez))
kontrol("…Google ve e-Devlet çerezleri hâlâ YOK, banka YOK",
        not (cerez & GOOGLE) and not (cerez & EDEVLET) and not (cerez & BANKA))
kontrol("…login.live.com kayıtlı girişi VAR; Google ve banka girişi YOK",
        giris == {"https://login.live.com", "https://example.com"}, str(giris))
if LZ4:
    kontrol("….live.com oturum çerezi (recovery.jsonlz4) eklenir", MS_OTURUM <= cerez)
c2, g2, d2 = istemci()
kontrol("panelden Microsoft açık → AYRI CLI/MCP süreci de kanaldan alır: MS çerezleri VAR, Google YOK",
        MS <= c2 and not (c2 & GOOGLE) and not (c2 & BANKA) and d2.get("izin") == ["microsoft"], str(d2)[:600])
n0 = len(uyarilar)
k.denetle()
kontrol("panelin kendi yazdığı izin geri alınmaz (uyarı yok)", dosyada() == "microsoft" and len(uyarilar) == n0)
b = firefox.hazirla(politika.coz("firefox"))
n_ms = len(MS) + (len(MS_OTURUM) if LZ4 else 0)
kontrol(f"kopya özeti: 'Microsoft aktarıldı ({n_ms} çerez, 1 kayıtlı giriş)'",
        f"Microsoft aktarıldı ({n_ms} çerez, 1 kayıtlı giriş)" in b["kimlik_metni"] and
        b["kimlik_ozet"]["microsoft"] == {"izin": True, "cerez": n_ms, "giris": 1}, b["kimlik_metni"])
satir = doktor.satir_hesap_oturumlari()
kontrol("doctor: 'Microsoft açık, Google kapalı, e-Devlet kapalı' + son kopya özeti",
        satir["ayrinti"].startswith("Microsoft açık, Google kapalı, e-Devlet kapalı | son kopya (") and
        f"Microsoft aktarıldı ({n_ms} çerez, 1 kayıtlı giriş)" in satir["ayrinti"] and satir["durum"] == "tamam",
        str(satir))
from deskhand import oturum  # noqa: E402
h = oturum.hazirla("firefox")
kontrol("oturum.hazirla açıklaması (CLI `open` çıktısı) kimlik özetini taşır",
        h.karar != "kopya" or "kimlik oturumları: Microsoft aktarıldı" in (h.aciklama or ""), str(h.aciklama))

w.k_hesap["google"].setChecked(True)
cerez, giris = hazirla_burada()
kontrol("panelden Google da açık → .google.com SID / accounts / securetoken VAR, MS VAR",
        GOOGLE <= cerez and MS <= cerez, str(GOOGLE - cerez))
kontrol("iki izin açık → banka çerezi ve banka girişi YİNE YOK (ret listesi izinden etkilenmez)",
        not (cerez & BANKA) and "https://www.isbank.com.tr" not in giris and NOTR <= cerez)
kontrol("doctor: 'Microsoft açık, Google açık, e-Devlet kapalı'",
        doktor.satir_hesap_oturumlari()["ayrinti"].startswith("Microsoft açık, Google açık, e-Devlet kapalı"))
kontrol("ana anahtar: üçü açık değilken işaretsiz", not w.k_hesap_hepsi.isChecked())

w.k_hesap["microsoft"].setChecked(False)
w.k_hesap["google"].setChecked(False)
sorulan.clear()
w.hesap_onay_sor = lambda sag: (sorulan.append(sag), False)[1]
w.k_hesap_hepsi.setChecked(True)
kontrol("ana anahtar 'Hayır' → hiçbiri açılmaz, anahtar geri döner",
        sorulan == ["hepsi"] and not w.k_hesap_hepsi.isChecked() and liste_koruma.kimlik_izinleri() == frozenset())
w.hesap_onay_sor = lambda sag: (sorulan.append(sag), True)[1]
w.k_hesap_hepsi.setChecked(True)
kontrol("ana anahtar 'Evet' (tek soru) → Microsoft + Google + e-Devlet açık, üç kutu işaretli",
        sorulan == ["hepsi", "hepsi"] and liste_koruma.kimlik_izinleri() == {"microsoft", "google", "edevlet"} and
        all(x.isChecked() for x in w.k_hesap.values()) and dosyada() == "microsoft,google,edevlet")
cerez, giris = hazirla_burada()
kontrol("ana anahtar açık → MS + Google + e-Devlet (turkiye.gov.tr, *.gov.tr alt alanı) çerezleri VAR",
        MS <= cerez and GOOGLE <= cerez and EDEVLET <= cerez, str((MS | GOOGLE | EDEVLET) - cerez))
kontrol("ana anahtar açık → banka/ödeme çerezi YİNE YOK (ebank.gov.tr, paypal, iyzico dahil)",
        not (cerez & BANKA), str(cerez & BANKA))
kontrol("ana anahtar açık → login.live.com, accounts.google.com, giris.turkiye.gov.tr girişleri VAR; banka YOK",
        giris == {"https://login.live.com", "https://accounts.google.com", "https://giris.turkiye.gov.tr",
                  "https://example.com"}, str(giris))
w.k_hesap["edevlet"].setChecked(False)
kontrol("tek kutu kapatılınca ana anahtar işaretsiz, e-Devlet kapalı",
        not w.k_hesap_hepsi.isChecked() and liste_koruma.kimlik_izinleri() == {"microsoft", "google"})
cerez, _g = hazirla_burada()
kontrol("e-Devlet izni kapalı → turkiye.gov.tr / *.gov.tr çerezleri YOK", not (cerez & EDEVLET))

# ================================================================ görev kipi: izin HİÇ uygulanmaz
w.hesap_onay_sor = lambda sag: True
w.k_hesap_hepsi.setChecked(True)  # görev kipi testi: üç izin de açık
c2, g2, d2 = istemci({gorev_kipi.ORTAM: "1", gorev_kipi.SITE_ORTAM: "live.com,microsoftonline.com,google.com,"
                                                                      "googleapis.com,turkiye.gov.tr,example.com"})
kontrol("görev kipi (üç izin açık, siteler live.com/google.com/turkiye.gov.tr izinli) → kimlik/devlet çerezleri YOK",
        "hata" not in d2 and not (c2 & (MS | GOOGLE | EDEVLET | MS_OTURUM)) and ("example.com", "a") in c2 and d2.get("izin") == [],
        str(d2)[:600])
kontrol("görev kipi → kayıtlı girişler hiç yok", "hata" not in d2 and g2 == set(), str(g2))
os.environ[gorev_kipi.ORTAM] = "1"
os.environ[gorev_kipi.SITE_ORTAM] = "live.com,google.com"
try:
    b = firefox.hazirla(politika.coz("firefox"))
    cerez, giris = kopya_sonucu(b)
    kontrol("görev kipi (panel sürecinde, izin bellekte açık) → kimlik çerezleri YOK",
            not (cerez & (MS | GOOGLE | EDEVLET)) and b.get("kimlik_izni") == [] and b.get("gorev") and
            "görev kipinde aktarılmaz" in b.get("kimlik_metni", ""), str(cerez))
finally:
    os.environ.pop(gorev_kipi.ORTAM, None)
    os.environ.pop(gorev_kipi.SITE_ORTAM, None)

# ================================================================ kapatma sorusuz; dosyadan kapatma = sıkılaştırma (kabul)
n_soru = len(sorulan)
w.k_hesap["google"].setChecked(False)
w.k_hesap["edevlet"].setChecked(False)
kontrol("Ayarlar: kapatmak soru sormaz; yalnız Microsoft kalır",
        len(sorulan) == n_soru and liste_koruma.kimlik_izinleri() == {"microsoft"} and dosyada() == "microsoft")
ajan_yazar("")
k.denetle()
kontrol("panel açık + dosyada izin elle kapatıldı → kabul (sıkı taraf), CLI/MCP izin görmez",
        k.metin(liste_koruma.KIMLIK) == "" and not (istemci()[0] & MS))
w._hesap_kutulari()
kontrol("Ayarlar kutuları panelin değerine döner", not w.k_hesap["microsoft"].isChecked())

# ================================================================ panel kapanır / yeniden açılır
w.hesap_onay_sor = lambda sag: True
w.k_hesap["microsoft"].setChecked(True)
liste_koruma.panel_durdur()
onay.panel_sil()
kontrol("panel kapandı (dosya + işaret 'microsoft') → CLI/MCP izin görmez", not (istemci()[0] & MS))
uyarilar.clear()
onay.panel_kaydet()
k = liste_koruma.panel_baslat(uyarilar.append)
kontrol("panel yeniden açıldı: kendi işaretli 'microsoft'unu kabul eder (yalnız 'izin açık' hatırlatması)",
        k.metin(liste_koruma.KIMLIK) == "microsoft" and len(uyarilar) == 1 and "izni açık: Microsoft" in uyarilar[0]
        and "geçerli sayılmadı" not in uyarilar[0] and MS <= istemci()[0], str(uyarilar))
liste_koruma.panel_durdur()
onay.panel_sil()
ajan_yazar("microsoft,google")  # işaret 'microsoft'; google elle eklendi
onay.panel_kaydet()
uyarilar.clear()
k = liste_koruma.panel_baslat(uyarilar.append)
kontrol("panel açılışı: dosyada işaretsiz 'google' eklenmiş → yalnız 'microsoft' kabul, dosya geri yazılır, uyarı",
        k.metin(liste_koruma.KIMLIK) == "microsoft" and dosyada() == "microsoft" and len(uyarilar) == 1
        and "geçerli sayılmadı" in uyarilar[0], str(uyarilar))
liste_koruma.panel_durdur()
onay.panel_sil()

kontrol("kaynak profil hiç değişmedi (yalnız okundu)", _kaynak_ozet() == KAYNAK_ONCE)

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
