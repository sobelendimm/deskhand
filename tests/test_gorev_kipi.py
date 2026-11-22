"""GÖREV KİPİ kanıt testi (deskhand/gorev_kipi.py; DESKHAND_GOREV=1): claude argv/ortamı, open_app tarayıcı sınırı,
onay kapsamı istisnası, Firefox oturum kopyası (parola/anahtar deposu yok, yalnız izinli sitenin çerezi), ad alanında
veri klasörü yok + görev indirme klasörü, GERÇEK Firefox (başsız) ile kurumsal ilke ölçümü: file:// ve about:logins
ENGELLİ.

GERÇEK claude ÇALIŞTIRILMAZ; kullanıcının gerçek Firefox profiline DOKUNULMAZ: SAHTE profil (sahte logins.json/key4.db/
çerezler) ve SAHTE ev (arka_ortak._EV_ZORLA) kullanılır; ad alanında gerçek ev ayrıca boş tmpfs. Gerçek ekran yok
(Firefox --headless, bwrap ad alanında).

Çalıştır:  python3 tests/test_gorev_kipi.py"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

os.environ["ANTHROPIC_API_KEY"] = "sahte-anahtar"
os.environ["ANTHROPIC_BASE_URL"] = "http://sahte"

from deskhand import api, arka_ortak as ao, gorev, gorev_kipi, guvenlik  # noqa: E402
from deskhand.oturum import firefox, politika, tespit  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


# ---------------------------------------------------------------- claude argv / ortam (ORTA-1, ORTA-2, KÜÇÜK)
a = gorev.komut_olustur("/x/claude", "/x/mcp.json", "sonnet", azami_tur=60)
i = a.index("--tools")
kontrol("argv: --tools \"\" (yerleşik araç YOK)", a[i + 1] == "", str(a[i:i + 2]))
kontrol("argv: --no-chrome", "--no-chrome" in a)
kontrol("argv: --max-turns 60", a[a.index("--max-turns") + 1] == "60")
kontrol("argv: kara liste ikinci katman kalır", "Bash" in a and "--disallowedTools" in a)
o = gorev.Gorev._claude_ortami(("github.com",))
kontrol("claude ortamında ANTHROPIC_* YOK", not any(k.startswith("ANTHROPIC_") for k in o), str([k for k in o if "ANTH" in k]))
kontrol("claude ortamı: ENABLE_CLAUDEAI_MCP_SERVERS=false, CLAUDE_MDS/AUTO_MEMORY kapalı",
        o.get("ENABLE_CLAUDEAI_MCP_SERVERS") == "false" and o.get("CLAUDE_CODE_DISABLE_CLAUDE_MDS") == "1"
        and o.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY") == "1")
kontrol("claude ortamı: görev kipi + izinli siteler", o.get("DESKHAND_GOREV") == "1" and
        o.get("DESKHAND_GOREV_SITELER") == "github.com")
kontrol("mcp.json env YALNIZ iki anahtar", gorev.mcp_ortami() == {"DESKHAND_GERCEK_EKRAN": "kapali", "DESKHAND_GOREV": "1"})
kontrol("geçici çalışma dizini XDG_RUNTIME_DIR altında (/tmp değil)",
        not gorev.calisma_koku().startswith("/tmp") or not os.environ.get("XDG_RUNTIME_DIR"), gorev.calisma_koku())
m, b = gorev_kipi.maskele("bankaya gir parola: Gizli123 kart 4111 1111 1111 1111 öde")
kontrol("görev metni maskelenir (parola + kart)", b and "Gizli123" not in m and "4111 1111" not in m and "1111]" in m, m)
kontrol("site ayrıştırma", gorev_kipi.site_ayristir("https://GitHub.com/x, *, com, ornek.com.tr") ==
        ("github.com", "ornek.com.tr"), str(gorev_kipi.site_ayristir("https://GitHub.com/x, *, com, ornek.com.tr")))
kontrol("adres_yasak: file:/about:logins RET, about:blank/https serbest",
        gorev_kipi.adres_yasak("file:///etc/passwd") and gorev_kipi.adres_yasak("about:logins") and
        not gorev_kipi.adres_yasak("about:blank") and not gorev_kipi.adres_yasak("https://github.com"))

kontrol("adres_yasak: jar:file: ve about:preferences RET", gorev_kipi.adres_yasak("jar:file:///x.zip!/a") and
        gorev_kipi.adres_yasak("about:preferences#applications"))

# ---------------------------------------------------------------- KÜÇÜK maddeler (birim)
# (6) site ayrıştırma: joker + tek başına genel son ek RET, açık ileti
g_, r_ = gorev_kipi.site_ayristir_ayrintili("*.github.com, com.tr, co.uk, gov.tr, com, github.com, isbank.com.tr")
kontrol("site: joker ve genel son ek (com.tr, co.uk, gov.tr, com) RET + neden metni",
        g_ == ("github.com", "isbank.com.tr") and len(r_) == 5 and any("joker" in x for x in r_) and
        sum("genel son ek" in x for x in r_) == 4, f"{g_} {r_}")
# (4) WebsiteFilter: yalnız MatchPattern'in kabul ettiği kalıplar (file://*/* ve jar: geçersiz → Firefox atar)
blok = gorev_kipi.FIREFOX_ILKE["WebsiteFilter"]["Block"]
kontrol("ilke WebsiteFilter: geçerli kalıplar (file:///*), geçersiz (file://*/*, jar:) yok",
        blok == ["file:///*"], str(blok))
pr_ = gorev_kipi.FIREFOX_ILKE["Preferences"]
kontrol("ilke: forbid_open_with kilitli true; DisableDeveloperTools açık",
        pr_["browser.download.forbid_open_with"] == {"Value": True, "Status": "locked"} and
        gorev_kipi.FIREFOX_ILKE.get("DisableDeveloperTools") is True)
# (3) /etc/firefox/policies varsa aynı ilke oraya da bağlanır
_etc = tempfile.mkdtemp(prefix="etc-ff-", dir=_yalitim.GECICI)
_eski_etc, gorev_kipi.FIREFOX_ETC_ILKE = gorev_kipi.FIREFOX_ETC_ILKE, _etc
_b = gorev_kipi.ilke_baglari()
gorev_kipi.FIREFOX_ETC_ILKE = _eski_etc
kontrol("ilke: /etc/firefox/policies varsa görev ilkesi oraya da bağlanır",
        not gorev_kipi.firefox_dagitim_dizinleri() or (_b[0][0], _etc) in _b, str(_b))
# (5) görev indirme klasörü görev başında boşaltılır
with open(os.path.join(gorev_kipi.indirme_dizini(), "onceki.txt"), "w") as f:
    f.write("x")
gorev_kipi.indirme_dizini_bosalt()
kontrol("indirme klasörü görev başında boş", gorev_kipi.indirilenler() == [], str(gorev_kipi.indirilenler()))
# (7) uyarı metni
from deskhand.gui import metinler as T  # noqa: E402
kontrol("arayüz: sitelerde ajan adınıza işlem yapabilir uyarısı (açıklama + onay)",
        "adınıza işlem" in T.G_SITELER_ACIKLAMA and "adınıza işlem" in T.G_ONAY_METIN and
        "kandırabilir" in T.G_ONAY_METIN)
# (8) kimlik değişkenleri claude/MCP/uygulamalara geçmez; claude girişi bozulmaz
os.environ.update(GITHUB_TOKEN="g", AWS_SECRET_ACCESS_KEY="a", DB_PASSWORD="p", OPENAI_API_KEY="o",
                  CLAUDE_CODE_OAUTH_TOKEN="c", SSH_AUTH_SOCK="/x")
o2 = gorev.Gorev._claude_ortami(())
kontrol("claude ortamı: TOKEN/SECRET/PASSWORD/KEY/AUTH değişkenleri YOK, CLAUDE_CODE_OAUTH_TOKEN + HOME/PATH var",
        not any(k in o2 for k in ("GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "DB_PASSWORD", "OPENAI_API_KEY",
                                  "SSH_AUTH_SOCK")) and o2.get("CLAUDE_CODE_OAUTH_TOKEN") == "c" and "HOME" in o2
        and "PATH" in o2, str(sorted(k for k in o2 if gorev_kipi.KIMLIK_ORTAM_DENEN.search(k))))
os.environ["DESKHAND_GOREV"] = "1"
u_ = ao.ortam_tabani()
kontrol("görev kipi uygulama ortamı: kimlik değişkenleri YOK (CLAUDE_CODE_OAUTH_TOKEN dahil)",
        not any(k in u_ for k in ("GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "DB_PASSWORD", "OPENAI_API_KEY",
                                  "CLAUDE_CODE_OAUTH_TOKEN")), str([k for k in u_ if "TOKEN" in k or "KEY" in k]))
os.environ["DESKHAND_GOREV"] = "0"
kontrol("görev kipi dışında ortam_tabani değişmez", "GITHUB_TOKEN" in ao.ortam_tabani())
for k in ("GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "DB_PASSWORD", "OPENAI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN",
          "SSH_AUTH_SOCK"):
    os.environ.pop(k, None)
# (9) iç içe girdi maskeleme
gk_ = gorev.girdi_kisalt({"steps": [{"tool": "type_text", "text": "Gizli-Parola-1"},
                                    {"tool": "click", "ref": "s1:3"}, {"x": {"value": "Kart-4111"}}]}, "batch")
kontrol("girdi_kisalt: batch(steps=[{text}]) iç içe maskelenir",
        "Gizli-Parola-1" not in json.dumps(gk_) and "Kart-4111" not in json.dumps(gk_) and "s1:3" in json.dumps(gk_),
        json.dumps(gk_))

# ---------------------------------------------------------------- görev kipi AÇIK
os.environ["DESKHAND_GOREV"] = "1"
os.environ["DESKHAND_GOREV_SITELER"] = "github.com"

# open_app (BÜYÜK-1a)
for ad_ in ("konsole", "org.kde.dolphin", "kate", "python3"):
    kontrol(f"open_app denetimi: {ad_} RET", gorev_kipi.open_app_denetle(ad_, []) is not None)
ff = shutil.which("firefox")
if ff:
    kontrol("open_app denetimi: firefox GEÇER (yerel paket + distribution)", gorev_kipi.open_app_denetle("firefox", [])
            is None, str(gorev_kipi.open_app_denetle("firefox", [])))
    kontrol("open_app denetimi: firefox + file:// belge RET",
            gorev_kipi.open_app_denetle("firefox", ["file:///etc/passwd"]) is not None)
from deskhand import mcp_sunucu  # noqa: E402
with api.hedef("sanal"):
    for ad_ in ("konsole", "org.kde.dolphin"):
        try:
            mcp_sunucu.open_app(ad_, desktop="background")
            kontrol(f"MCP open_app({ad_}) RET", False)
        except Exception as e:  # noqa: BLE001
            kontrol(f"MCP open_app({ad_}) RET", "[10]" in str(e), str(e)[:200])

# onay kapsamı istisnası (BÜYÜK-2)
guvenlik._KAPSAM.update(zaman=1e18, deger="kart")
kontrol("kart kipinde görevde parola alanı onayı AÇIK", not guvenlik.onaysiz_serbest("parola alanına yazma"))
kontrol("kart kipinde görevde sistem istemi onayı AÇIK", not guvenlik.onaysiz_serbest("sistem istemi girdisi"))
kontrol("kart kipinde başka sınıf serbest kalır (riskli tuş)", guvenlik.onaysiz_serbest("riskli tuş"))
os.environ["DESKHAND_GOREV"] = "0"
kontrol("görev kipi dışında kart kipi parola alanını serbest bırakır (eski davranış)",
        guvenlik.onaysiz_serbest("parola alanına yazma"))
os.environ["DESKHAND_GOREV"] = "1"
guvenlik.onay_kapsami_sifirla()

# ---------------------------------------------------------------- SAHTE profil → görev kopyası
kok = tempfile.mkdtemp(prefix="deskhand-gk-", dir=_yalitim.GECICI)
PROFIL = os.path.join(kok, "profil")
os.makedirs(PROFIL)
for ad_ in ("logins.json", "logins-backup.json"):
    with open(os.path.join(PROFIL, ad_), "w") as f:
        json.dump({"logins": [{"hostname": "https://github.com", "guid": "{1}", "encryptedPassword": "SAHTE-PAROLA"}]}, f)
for ad_ in ("key4.db", "cert9.db"):
    with open(os.path.join(PROFIL, ad_), "wb") as f:
        f.write(b"SAHTE-" + ad_.encode())
os.makedirs(os.path.join(PROFIL, "extensions"))
with open(os.path.join(PROFIL, "extensions", "parola-yoneticisi@x.xpi"), "w") as f:
    f.write("x")
con = sqlite3.connect(os.path.join(PROFIL, "cookies.sqlite"))
con.execute("CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, originAttributes TEXT DEFAULT '', name TEXT, value TEXT, "
            "host TEXT, path TEXT, expiry INTEGER, lastAccessed INTEGER, creationTime INTEGER, isSecure INTEGER, "
            "isHttpOnly INTEGER, sameSite INTEGER, schemeMap INTEGER, UNIQUE(name, host, path, originAttributes))")
for h in (".github.com", "api.github.com", ".bankam.com.tr", "mail.ornek.com"):
    con.execute("INSERT INTO moz_cookies (name,value,host,path,expiry) VALUES (?,?,?,?,?)",
                ("oturum", "DEGER-" + h, h, "/", 4102444800))
con.commit()
con.close()
tespit.firefox_profil_dizini = lambda: PROFIL  # GERÇEK profil ASLA
pol = politika.anahtar_politikasi("firefox", politika.yukle())
b = firefox.hazirla(pol)
K = b["kopya_yolu"]
kontrol("kopya: logins.json / logins-backup.json / key4.db YOK",
        not any(os.path.exists(os.path.join(K, x)) for x in ("logins.json", "logins-backup.json", "key4.db", "logins.db")),
        str(os.listdir(K)))
kontrol("kopya: uzantılar YOK, sertifika deposu var", not os.path.exists(os.path.join(K, "extensions")) and
        os.path.exists(os.path.join(K, "cert9.db")))
con = sqlite3.connect(os.path.join(K, "cookies.sqlite"))
hostlar = sorted(r[0] for r in con.execute("SELECT host FROM moz_cookies"))
con.close()
kontrol("kopya: YALNIZ izinli sitenin (github.com) çerezleri", hostlar == [".github.com", "api.github.com"], str(hostlar))
uj = open(os.path.join(K, "user.js")).read()
kontrol("kopya user.js: signon.rememberSignons=false", 'user_pref("signon.rememberSignons", false);' in uj)
os.environ["DESKHAND_GOREV_SITELER"] = ""
b2 = firefox.hazirla(pol)
con = sqlite3.connect(os.path.join(b2["kopya_yolu"], "cookies.sqlite"))
n = con.execute("SELECT COUNT(*) FROM moz_cookies").fetchone()[0]
con.close()
kontrol("site verilmezse ÇEREZSİZ temiz profil", n == 0, str(n))

# ---------------------------------------------------------------- ad alanı: veri klasörü yok, indirme klasörü var
EV = os.path.join(kok, "ev")
for d in ("Belgeler", "Indirilenler", ".config"):
    os.makedirs(os.path.join(EV, d))
with open(os.path.join(EV, ".config/user-dirs.dirs"), "w") as f:
    f.write('XDG_DOCUMENTS_DIR="$HOME/Belgeler"\nXDG_DOWNLOAD_DIR="$HOME/Indirilenler"\n')
with open(os.path.join(EV, "Belgeler", "gizli.txt"), "w") as f:
    f.write("BELGE-GIZLI")
ao._EV_ZORLA = EV
RT = os.path.join(kok, "rt")
GERCEK_EV = os.path.realpath(os.path.expanduser("~"))


def ad_alani(argv, ortam=None, sure=90):
    tam = ao.korumali_argv(argv, RT, [(K, False)], ev=EV)
    i = tam.index("--tmpfs") + 2
    tam = tam[:i] + ["--tmpfs", GERCEK_EV] + tam[i:]
    return subprocess.run(tam, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=sure,
                          env={"HOME": EV, "PATH": "/usr/bin", **(ortam or {})})


if shutil.which("bwrap"):
    r = ad_alani(["/usr/bin/sh", "-c", f"cat '{EV}/Belgeler/gizli.txt' 2>&1; ls -A '{EV}'; "
                                       f"echo indi > '{EV}/Indirilenler/dosya.txt' && echo YAZILDI"])
    kontrol("ad alanı: görevde XDG veri klasörü (Belgeler) GÖRÜNMEZ", "BELGE-GIZLI" not in r.stdout and
            "Belgeler" not in r.stdout.split(), r.stdout + r.stderr)
    kontrol("ad alanı: görev indirme klasörü İndirilenler yolunda yazılabilir (RUNTIME_DIR/gorev-indirilenler)",
            "YAZILDI" in r.stdout and gorev_kipi.indirilenler() == ["dosya.txt"] and
            not os.path.exists(os.path.join(EV, "Indirilenler", "dosya.txt")), r.stdout + r.stderr)
    r = ad_alani(["/usr/bin/sh", "-c", "for d in /usr/lib/firefox/distribution; do ls $d; done"])
    kontrol("ad alanı: Firefox distribution/ yerine görev ilkesi (policies.json)",
            "policies.json" in r.stdout or not gorev_kipi.firefox_dagitim_dizinleri(), r.stdout + r.stderr)

# ---------------------------------------------------------------- BÜYÜK-1 / ORTA-2: görev masaüstü + pencere sınırı
# Gerçek görünmez masaüstü (Xvfb ya da KWin: DESKHAND_ARKA_TUR), yalnız test ekranı; kullanıcının ekranına girdi YOK.
import atexit  # noqa: E402
import time as _t  # noqa: E402
from deskhand import hata as _hata, masaustu  # noqa: E402
from deskhand.arka_uc import EKRAN  # noqa: E402

XPENCERE = ("import sys\nfrom Xlib import display, X\nd = display.Display(); s = d.screen()\n"
            "w = s.root.create_window(10, 10, 300, 200, 0, s.root_depth, X.InputOutput, X.CopyFromParent, "
            "background_pixel=s.white_pixel)\nw.set_wm_name(sys.argv[1]); w.set_wm_class(sys.argv[2], sys.argv[2])\n"
            "w.map(); d.flush()\nimport time\nwhile True: time.sleep(1)\n")


def kipte(gorev_acik):
    os.environ["DESKHAND_GOREV"] = "1" if gorev_acik else "0"


def dur_kodu(f):
    try:
        f()
        return None
    except _hata.Dur as e:
        return e.kod
    except Exception as e:  # noqa: BLE001  (MCP ToolError: "[kod] ...")
        if os.environ.get("DBG"):
            print("DBG", str(e)[:300])
        m = __import__("re").match(r"\[(\d+)\]", str(e))
        return int(m.group(1)) if m else str(e)[:120]


def pencere_bekle(baslik, var=True, sure=8.0):
    son = _t.monotonic() + sure
    while _t.monotonic() < son:
        try:
            with api.hedef("sanal"):
                ad = [b for _k, b, _g in api.arka().pencereler()]
        except _hata.Dur:
            ad = []
        if (baslik in ad) == var:
            return True
        _t.sleep(0.1)
    return False


if shutil.which("bwrap") and os.environ.get("DESKHAND_MASAUSTU_TEST", "1") == "1":
    atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
    ao._EV_ZORLA = None
    # 1) ÖNCEDEN açık KİPSİZ masaüstü + kipsiz pencere (başka bir Claude oturumundan kalan "Dolphin")
    kipte(False)
    masaustu.masaustu_baslat()
    pk = masaustu.baslat([sys.executable, "-c", XPENCERE, "KIPSIZ-DOLPHIN", "dolphin"])
    kontrol("hazırlık: kipsiz masaüstünde kipsiz pencere açıldı", pencere_bekle("KIPSIZ-DOLPHIN"))
    kipte(True)
    with api.hedef("sanal"):
        kontrol("BÜYÜK-1: görev ajanı önceden açık kipsiz masaüstünün pencerelerini LİSTELEYEMEZ (Dur 14)",
                dur_kodu(lambda: api.pencereler()) == 14, str(dur_kodu(lambda: api.pencereler())))
        kontrol("BÜYÜK-1: görev ajanı tüm ekran screenshot alamaz (kipsiz masaüstü)",
                dur_kodu(lambda: mcp_sunucu.screenshot(desktop="background")) == 14,
                str(dur_kodu(lambda: mcp_sunucu.screenshot(desktop="background"))))
        kontrol("BÜYÜK-1: görev ajanı tüm ekran read_text yapamaz (kipsiz masaüstü)",
                dur_kodu(lambda: mcp_sunucu.read_text(desktop="background")) == 14,
                str(dur_kodu(lambda: mcp_sunucu.read_text(desktop="background"))))
    kontrol("BÜYÜK-1: görev kipi açık kipsiz masaüstünü 'başlat' ile devralamaz", dur_kodu(masaustu.masaustu_baslat) == 14)
    kontrol("BÜYÜK-1: görev kipi açık kipsiz masaüstüne uygulama açamaz",
            dur_kodu(lambda: masaustu.baslat(["/usr/bin/true"])) == 14)
    # panel: masaüstü açıkken görev BAŞLAMAZ (açık ileti), işaret geri alınır
    kipte(False)
    g_ = gorev.Gorev(claude="/usr/bin/false", kafes=False)
    try:
        g_.baslat("deneme")
        kod_ = None
    except gorev.GorevHatasi as e:
        kod_ = (e.kod, e.mesaj)
    kontrol("BÜYÜK-1: masaüstü açıkken görev başlamaz: 'başka bir iş için açık; kapatıp başlatılsın mı?'",
            kod_ is not None and kod_[0] == "masaustu_acik" and "kapatıp başlatılsın mı" in kod_[1] and
            not g_.calisiyor and not gorev_kipi.masaustu_ayrildi(), str(kod_))
    kontrol("BÜYÜK-1: reddedilen başlatma kipsiz masaüstüne dokunmadı", masaustu.durum() is not None)
    masaustu.masaustu_durdur()
    try:
        pk.kill()
    except OSError:
        pass

    # 2) GÖREV masaüstü (görev açar → "gorev": true); kipsiz istemci ERİŞEMEZ
    gorev_kipi.masaustu_ayir()
    kipte(False)
    kontrol("BÜYÜK-1: görev masaüstü ayrılmışken kipsiz istemci masaüstü AÇAMAZ",
            dur_kodu(masaustu.masaustu_baslat) == 14)
    kipte(True)
    dg = masaustu.masaustu_baslat()
    kontrol("görev masaüstü kaydı 'gorev': true", dg.get("gorev") is True and (masaustu.durum_oku() or {}).get("gorev"))
    kipte(False)
    with api.hedef("sanal"):
        kontrol("BÜYÜK-1: kipsiz istemci görev masaüstünün pencerelerini listeleyemez / görüntü alamaz (Dur 14)",
                dur_kodu(lambda: api.pencereler()) == 14 and
                dur_kodu(lambda: mcp_sunucu.screenshot(desktop="background")) == 14)
    kontrol("BÜYÜK-1: kipsiz istemci görev masaüstüne uygulama açamaz", dur_kodu(lambda: masaustu.baslat(["/usr/bin/true"]))
            == 14)
    gorev_kipi.GOZLEMCI = True
    with api.hedef("sanal"):
        kontrol("panel önizlemesi (GOZLEMCI) görev masaüstünü görebilir", dur_kodu(lambda: api.arka().pencereler()) is None)
    gorev_kipi.GOZLEMCI = False

    # 3) ORTA-2: görev masaüstünde tarayıcı dışı pencere (Firefox'un açtığı Kate) + sınıf taklidi
    kipte(True)
    with api.hedef("sanal"):
        kontrol("tüm ekran: görev tarayıcısı penceresi yokken okuma RET",
                dur_kodu(lambda: mcp_sunucu.screenshot(desktop="background")) == 10)
    pkate = masaustu.baslat([sys.executable, "-c", XPENCERE, "belge.txt - Kate", "kate"])
    psahte = masaustu.baslat([sys.executable, "-c", XPENCERE, "Mozilla Firefox (sahte)", "firefox"])
    kontrol("hazırlık: görev masaüstünde Kate + sahte firefox sınıflı pencere açıldı",
            pencere_bekle("belge.txt - Kate") and pencere_bekle("Mozilla Firefox (sahte)"))
    with api.hedef("sanal"):
        au = api.arka()
        ks = {b: k for k, b, _g in au.pencereler()}
        k_sahte = ks.get("Mozilla Firefox (sahte)")
        izin = gorev_kipi.pencere_izinli(au, k_sahte) if k_sahte else None
        kontrol("ORTA-2: sınıfı 'firefox' ama süreci tarayıcı olmayan pencere İZİNSİZ (sınıf tek başına yetmez)",
                izin is not None and izin[0] is False and izin[1] == "firefox" and izin[2] not in
                gorev_kipi.TARAYICI_IKILILERI, str(izin))
        kod_ = dur_kodu(lambda: mcp_sunucu.screenshot(desktop="background"))
        kontrol("ORTA-2: görev masaüstünde Kate belirince tüm ekran görüntüsü RET (10)", kod_ == 10, str(kod_))
    kontrol("ORTA-2: tarayıcı dışı pencereler kapatıldı (Kate + sahte)",
            pencere_bekle("belge.txt - Kate", var=False) and pencere_bekle("Mozilla Firefox (sahte)", var=False))
    son_ = _t.monotonic() + 5
    while _t.monotonic() < son_ and (pkate.poll() is None or psahte.poll() is None):
        _t.sleep(0.1)
    kontrol("ORTA-2: tarayıcı dışı pencerelerin süreçleri sonlandı", pkate.poll() is not None and psahte.poll() is not None)
    pkate2 = masaustu.baslat([sys.executable, "-c", XPENCERE, "Kate 2", "kate"])
    pencere_bekle("Kate 2")
    with api.hedef("sanal"):
        k2 = {b: k for k, b, _g in api.arka().pencereler()}.get("Kate 2")
        kod_ = dur_kodu(lambda: mcp_sunucu.press_key(window="Kate 2", keys="ctrl+s", desktop="background"))
        # pencere ilk denetimde kapatılır: ret [10] ya da (kapatıldıktan sonraki adımda) [8] — girdi GİTMEZ
        kontrol("ORTA-2: Kate penceresine girdi (press_key) RET ve pencere kapatıldı",
                k2 is not None and kod_ in (8, 10) and pencere_bekle("Kate 2", var=False), f"{k2} {kod_}")
        kontrol("ORTA-2: Kate penceresinden read_text RET (10)",
                dur_kodu(lambda: mcp_sunucu.read_text(window="Kate 2", desktop="background")) in (8, 10))
    pff = None
    if ff:  # gerçek görev Firefox'u İZİNLİ (sınıf + süreç ikilisi) ve tüm ekran okuması o varken serbest
        prof_ = tempfile.mkdtemp(prefix="ffw-", dir=_yalitim.PAYLASIM)
        pff = masaustu.baslat(["firefox", "--no-remote", "--new-instance", "--profile", prof_, "about:blank"])
        kff, son_ = None, _t.monotonic() + 25
        while _t.monotonic() < son_ and kff is None:
            with api.hedef("sanal"):
                for k_, _b, _g in api.arka().pencereler():
                    if gorev_kipi.pencere_izinli(api.arka(), k_)[1] in gorev_kipi.TARAYICI_SINIFLARI:
                        kff = k_
            _t.sleep(0.2)
        with api.hedef("sanal"):
            izin = gorev_kipi.pencere_izinli(api.arka(), kff) if kff else None
            kontrol("ORTA-2: görevin gerçek Firefox penceresi İZİNLİ (sınıf + süreç ikilisi)",
                    izin is not None and izin[0] is True, str(izin))
            kontrol("tüm ekran: yalnız görev tarayıcısı varken screenshot serbest",
                    dur_kodu(lambda: mcp_sunucu.screenshot(desktop="background")) is None)
    for p_ in (pkate, psahte, pkate2, *([pff] if pff else [])):
        try:
            p_.kill()
        except OSError:
            pass
    masaustu.masaustu_durdur()
    gorev_kipi.masaustu_birak()
    kontrol("görev bitince ayrım kalkar; kipsiz istemci yeniden masaüstü açabilir",
            not gorev_kipi.masaustu_ayrildi() and (kipte(False) or dur_kodu(lambda: masaustu.masaustu_baslat()) is None))
    masaustu.masaustu_durdur()
    kipte(True)
    ao._EV_ZORLA = EV

# ---------------------------------------------------------------- GERÇEK Firefox (başsız) ölçümü (Marionette)
# Ekran görüntüsü + zaman aşımı yerine Marionette (yerel TCP, rastgele kapı): belge adresi/metni ve kilitli tercihler
# doğrudan okunur; engelli sayfa "about:neterror?e=blockedByPolicy" olur (bekleme yok, ~2-4 sn / Firefox).
import socket  # noqa: E402
import time  # noqa: E402


class Marionette:
    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.n = 0
        self._oku()

    def _oku(self):
        b = b""
        while b":" not in b:
            b += self.s.recv(1)
        n = int(b[:-1])
        v = b""
        while len(v) < n:
            v += self.s.recv(n - len(v))
        return json.loads(v)

    def cagir(self, ad, par=None):
        self.n += 1
        m = json.dumps([0, self.n, ad, par or {}]).encode()
        self.s.sendall(str(len(m)).encode() + b":" + m)
        while True:
            r = self._oku()
            if r[1] == self.n:
                return r[2], r[3]


def firefox_olc(gorev_acik, adresler):
    """Başsız Firefox (görev ad alanında, gorev_acik=ilke bağlı) → ({adres: (documentURI, metin)}, tercihler)."""
    os.environ["DESKHAND_GOREV"] = "1" if gorev_acik else "0"
    prof = tempfile.mkdtemp(prefix="ffp-", dir=_yalitim.PAYLASIM)
    with open(os.path.join(prof, "user.js"), "w") as f:
        f.write(uj + 'user_pref("marionette.port", 0);\n')
    # ÖLÇÜM için ilkeden YALNIZ DisableDeveloperTools çıkarılır (o ilke uzaktan denetimi = Marionette'i de kapatır:
    # remote.policy.disabled); geri kalan her şey görevdeki ilkenin aynısı. DisableDeveloperTools ayrıca birim
    # testinde denetlenir.
    asil_ilke = dict(gorev_kipi.FIREFOX_ILKE)
    gorev_kipi.FIREFOX_ILKE.pop("DisableDeveloperTools", None)
    try:
        tam = ao.korumali_argv(["firefox", "--headless", "--no-remote", "--new-instance", "--marionette",
                                "--remote-allow-system-access", "--profile", prof, "about:blank"], RT, [(K, False)],
                               ev=EV)
    finally:
        gorev_kipi.FIREFOX_ILKE.clear()
        gorev_kipi.FIREFOX_ILKE.update(asil_ilke)
    i_ = tam.index("--tmpfs") + 2
    tam = tam[:i_] + ["--tmpfs", GERCEK_EV] + tam[i_:]
    pr = subprocess.Popen(tam, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          env={"HOME": EV, "PATH": "/usr/bin", "MOZ_HEADLESS": "1", "MOZ_REMOTE_ALLOW_SYSTEM_ACCESS": "1"},
                          start_new_session=True)
    os.environ["DESKHAND_GOREV"] = "1"
    sonuc, tercih = {}, None
    try:
        port_dosya = os.path.join(prof, "MarionetteActivePort")
        son = time.monotonic() + 20
        while time.monotonic() < son and not os.path.exists(port_dosya):
            time.sleep(0.1)
        m = None
        while time.monotonic() < son:
            try:
                m = Marionette(int(open(port_dosya).read().strip()))
                break
            except (OSError, ValueError):
                time.sleep(0.1)
        if m is None:
            print("  marionette: bağlanılamadı")
            return sonuc, tercih
        m.cagir("WebDriver:NewSession", {"capabilities": {"alwaysMatch": {"pageLoadStrategy": "normal"}}})
        m.cagir("WebDriver:SetTimeouts", {"pageLoad": 8000, "script": 5000})
        h_, _r = m.cagir("Marionette:SetContext", {"value": "chrome"})
        if h_:
            print("  marionette bağlam", str(h_)[:300])
        for a in adresler:  # sistem ilkesi (ChromeURLBlockPolicy/WebsiteFilter) sekme yüklemesinde uygulanır
            h_, r = m.cagir("WebDriver:ExecuteAsyncScript", {"script": """
                const [adres, bitti] = arguments;
                const b = gBrowser.addTab(adres, {triggeringPrincipal:
                    Services.scriptSecurityManager.getSystemPrincipal()}).linkedBrowser;
                let n = 0;
                const t = setInterval(() => { n++; const u = b.documentURI ? b.documentURI.spec : '';
                    if ((u && u !== 'about:blank') || n > 50) { clearInterval(t); bitti(u); } }, 100);""",
                                                            "args": [a]})
            if h_:
                print("  marionette sekme", a, str(h_)[:200])
            sonuc[a] = ((r or {}).get("value") or "", "")
        _h, r = m.cagir("WebDriver:ExecuteScript", {"script": """
            const P = Services.prefs, ad = 'browser.download.forbid_open_with';
            return {deger: P.getBoolPref(ad, false), kilitli: P.prefIsLocked(ad),
                    sor: P.getBoolPref('browser.download.always_ask_before_handling_new_types', true),
                    parola: P.getBoolPref('signon.rememberSignons', true),
                    ilke: Services.policies.status === Services.policies.ACTIVE};""", "args": []})
        if _h:
            print("  marionette chrome", str(_h)[:300])
        tercih = (r or {}).get("value")
        try:
            m.cagir("Marionette:Quit", {"flags": ["eForceQuit"]})
        except OSError:
            pass
    finally:
        try:
            pr.wait(5)
        except subprocess.TimeoutExpired:
            os.killpg(pr.pid, 9)
            pr.wait(5)
    return sonuc, tercih


if ff and shutil.which("bwrap") and os.environ.get("DESKHAND_FIREFOX_OLCUM", "1") == "1":
    pay = _yalitim.PAYLASIM
    sayfa = os.path.join(pay, "kirmizi.html")
    with open(sayfa, "w") as f:
        f.write("<html><body style='background:#ff0000;margin:0'><h1>YEREL-GIZLI</h1></body></html>")
    adresler = ["file://" + sayfa, "about:logins", "about:config"]
    t0 = time.monotonic()
    acik, tercih_acik = firefox_olc(False, adresler)
    gor, tercih = firefox_olc(True, adresler)
    print(f"ÖLÇÜM ({time.monotonic() - t0:.1f} sn) ilkesiz={acik} tercih={tercih_acik}\n       görev={gor} "
          f"tercih={tercih}")
    eng = lambda r: r is not None and "blockedByPolicy" in (r[0] or "")  # noqa: E731
    kontrol("Firefox ilkesiz: file:// sayfası açılıyor (ölçüm geçerli)",
            (acik.get(adresler[0]) or ("",))[0].startswith("file:"), str(acik))
    kontrol("Firefox GÖREV KİPİ: file:// ENGELLİ (blockedByPolicy)", eng(gor.get(adresler[0])), str(gor.get(adresler[0])))
    kontrol("Firefox ilkesiz: about:logins açılıyor (ölçüm geçerli)",
            (acik.get("about:logins") or ("",))[0].startswith("about:logins"), str(acik.get("about:logins")))
    kontrol("Firefox GÖREV KİPİ: about:logins + about:config ENGELLİ",
            eng(gor.get("about:logins")) and eng(gor.get("about:config")), str(gor))
    kontrol("Firefox ilkesiz: forbid_open_with kilitsiz (ölçüm geçerli)",
            tercih_acik is not None and not tercih_acik.get("kilitli"), str(tercih_acik))
    kontrol("Firefox GÖREV KİPİ: browser.download.forbid_open_with = true ve KİLİTLİ; yeni türde sorma yok; ilke etkin",
            tercih is not None and tercih.get("deger") is True and tercih.get("kilitli") is True and
            tercih.get("sor") is False and tercih.get("ilke") is True and tercih.get("parola") is False, str(tercih))

# ---------------------------------------------------------------- panel: açık masaüstü sorusu + site reddi (Qt offscreen)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication  # noqa: E402
_app = QApplication.instance() or QApplication([])
from deskhand.gui.gorev import GorevSekmesi  # noqa: E402
cagrilar = []


class SahteGorev:
    def __init__(self, olay_cb=None):
        self.calisiyor = False

    def baslat(self, metin, siteler="", masaustu_kapat=False):
        cagrilar.append(masaustu_kapat)
        if not masaustu_kapat:
            raise gorev.GorevHatasi(gorev._("Görünmez masaüstü başka bir iş için açık; kapatıp başlatılsın mı?"),
                                    kod="masaustu_acik")
        return "x"

    def durdur(self):
        return False


for cevap, beklenen in ((False, [False]), (True, [False, True])):
    cagrilar.clear()
    sek = GorevSekmesi(gorev_f=SahteGorev, gecmis_f=lambda: [], olaylar_f=lambda d: [])
    sek.onay_iste = False
    sek._masaustu_kapat_onayla = lambda c=cevap: c
    sek.kutu.setPlainText("bir görev")
    sek.baslat()
    kontrol(f"panel: masaüstü açık → soru; '{'Kapat ve başlat' if cevap else 'İptal'}' → baslat çağrıları {beklenen}",
            cagrilar == beklenen and (cevap or "kapatıp başlatılsın mı" in sek.sonuc.toPlainText()),
            f"{cagrilar} {sek.sonuc.toPlainText()[:120]}")
    sek.calisiyor = False
cagrilar.clear()
sek = GorevSekmesi(gorev_f=SahteGorev, gecmis_f=lambda: [], olaylar_f=lambda d: [])
sek.onay_iste = False
sek.kutu.setPlainText("bir görev")
sek.siteler.setText("github.com, com.tr, *.x.com")
sek.baslat()
kontrol("panel: site listesinde genel son ek/joker → görev başlamaz, açık ileti", cagrilar == [] and
        "genel son ek" in sek.sonuc.toPlainText() and "joker" in sek.sonuc.toPlainText(), sek.sonuc.toPlainText())

ao._EV_ZORLA = None
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
