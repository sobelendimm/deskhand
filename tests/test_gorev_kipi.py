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

# ---------------------------------------------------------------- GERÇEK Firefox (başsız) ölçümü
if ff and shutil.which("bwrap") and os.environ.get("DESKHAND_FIREFOX_OLCUM", "1") == "1":
    from PIL import Image
    pay = _yalitim.PAYLASIM
    sayfa = os.path.join(pay, "kirmizi.html")
    with open(sayfa, "w") as f:
        f.write("<html><body style='background:#ff0000;margin:0'><h1>YEREL-GIZLI</h1></body></html>")

    def ekran(url, gorev_acik=True):
        os.environ["DESKHAND_GOREV"] = "1" if gorev_acik else "0"
        cikti = os.path.join(pay, f"ss-{abs(hash((url, gorev_acik)))}.png")
        prof = tempfile.mkdtemp(prefix="ffp-", dir=pay)
        with open(os.path.join(prof, "user.js"), "w") as f:
            f.write(uj)
        try:  # ilke engel sayfasında başsız --screenshot yüklenmeyi bitirmez: zaman aşımı = sayfa GÖRÜNTÜLENMEDİ
            ad_alani(["firefox", "--headless", "--no-remote", "--new-instance", "--profile", prof,
                      "--screenshot", cikti, "--window-size=400,300", url], {"MOZ_HEADLESS": "1"}, 45)
        except subprocess.TimeoutExpired:
            pass
        os.environ["DESKHAND_GOREV"] = "1"
        if not os.path.exists(cikti):
            return 0.0, None
        im = Image.open(cikti).convert("RGB")
        px = list(im.get_flattened_data())
        return sum(1 for p in px if p[0] > 200 and p[1] < 40 and p[2] < 40) / len(px), im

    kirmizi_acik, _x = ekran("file://" + sayfa, gorev_acik=False)
    kirmizi_gorev, _y = ekran("file://" + sayfa, gorev_acik=True)
    print(f"ÖLÇÜM file:// kırmızı piksel oranı: ilkesiz={kirmizi_acik} görev={kirmizi_gorev}")
    kontrol("Firefox ilkesiz: file:// sayfası açılıyor (ölçüm geçerli)", kirmizi_acik is not None and kirmizi_acik > 0.5,
            str(_x))
    kontrol("Firefox GÖREV KİPİ: file:// ENGELLİ (sayfa görüntülenmiyor)", kirmizi_gorev is not None and
            kirmizi_gorev < 0.01, str(_y))
    _a, im_logins_acik = ekran("about:logins", gorev_acik=False)
    _b, im_logins_gorev = ekran("about:logins", gorev_acik=True)
    print(f"ÖLÇÜM about:logins: ilkesiz görüntü={'var' if im_logins_acik else 'yok'}, "
          f"görev={'var' if im_logins_gorev else 'yok (engel)'}")
    kontrol("Firefox ilkesiz: about:logins açılıyor (ölçüm geçerli)", im_logins_acik is not None)
    kontrol("Firefox GÖREV KİPİ: about:logins ENGELLİ (sayfa görüntülenmiyor)", im_logins_gorev is None)

ao._EV_ZORLA = None
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
