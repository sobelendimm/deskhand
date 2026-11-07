"""deskhand meşgul algılama + karar testleri (Faz 4). EKRANSIZ: girdi göndermez, GERÇEK bildirim göndermez.

D-Bus sinyalleri (MPRIS, bildirim sunucusu) ÖZEL bir dbus-daemon üzerinde sahte hizmetle sınanır: etkinleştirme
(servicedir) olmayan kendi yapılandırmasıyla başlatılır, DBUS_SESSION_BUS_ADDRESS ona yönlendirilir; gerçek oturum
veri yoluna hiçbir şey gitmez. kdotool/loginctl/etkinlik yardımcısı sahte (süreç içi işlevler; CLI testinde PATH
öne eklenen sahte programlar).

Çalıştır:  python3 tests/test_mesgul.py"""
import json, os, subprocess, sys, tempfile, textwrap, time, types

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from deskhand import ayarlar, mesgul, yollar

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


GECICI = tempfile.mkdtemp(prefix="deskhand-mesgul-", dir=_yalitim.GECICI)

# ---------------------------------------------------------------- özel veri yolu + sahte hizmet

BUS_CONF = f"""<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:dir={GECICI}</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow user="*"/>
    <allow own="*"/>
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
  </policy>
</busconfig>
"""

# Sahte hizmet: MPRIS oynatıcıları + org.freedesktop.Notifications. Senaryo argv[1]:
#   arka | on | sonra : Notify'dan sonra ActionInvoked(id, senaryo)
#   kapat              : NotificationClosed(id, 2) (kullanıcı kapattı)
#   sessiz             : yanıt yok (süre dolar → CloseNotification beklenir)
#   sahte_once         : önce BAŞKA bir bağlantıdan ActionInvoked(id, "on") (taklit), sonra gerçek "arka"
# argv[2]: kayıt dosyası (JSON satırları), argv[3]: Inhibited (0/1), argv[4]: oynatıcılar JSON
SAHTE = textwrap.dedent('''
    import json, sys
    from jeepney import DBusAddress, new_method_return, new_signal, new_error, message_bus, MessageType
    from jeepney.low_level import HeaderFields
    from jeepney.io.blocking import open_dbus_connection
    senaryo, kayit, inhibited, oynaticilar = sys.argv[1], sys.argv[2], sys.argv[3] == "1", json.loads(sys.argv[4])
    c = open_dbus_connection(bus="SESSION")
    adlar = ["org.freedesktop.Notifications"] + ["org.mpris.MediaPlayer2." + o["ad"] for o in oynaticilar]
    for ad in adlar:
        c.send_and_get_reply(message_bus.RequestName(ad))
    def yaz(**k):
        with open(kayit, "a") as f:
            f.write(json.dumps(k) + "\\n")
    BLD = DBusAddress("/org/freedesktop/Notifications", interface="org.freedesktop.Notifications")
    print("hazir", flush=True)
    while True:
        m = c.receive()
        if m.header.message_type != MessageType.method_call:
            continue
        h = m.header.fields
        uye, hedef, arayuz = h.get(HeaderFields.member), h.get(HeaderFields.destination), h.get(HeaderFields.interface)
        if uye == "Get" and arayuz == "org.freedesktop.DBus.Properties":
            ia, oz = m.body
            if hedef == "org.freedesktop.Notifications" and oz == "Inhibited":
                c.send(new_method_return(m, "v", (("b", inhibited),)))
                continue
            o = next((o for o in oynaticilar if hedef == "org.mpris.MediaPlayer2." + o["ad"]), None)
            if o and oz == "PlaybackStatus":
                c.send(new_method_return(m, "v", (("s", o["durum"]),)))
            elif o and oz == "Metadata":
                c.send(new_method_return(m, "v", (("a{sv}", {"xesam:title": ("s", o["baslik"])}),)))
            else:
                c.send(new_error(m, "org.freedesktop.DBus.Error.UnknownProperty"))
        elif uye == "Notify":
            yaz(olay="Notify", govde=list(m.body[:6]), ipucu={k: v[1] for k, v in m.body[6].items()}, sure=m.body[7])
            c.send(new_method_return(m, "u", (7,)))
            if senaryo in ("arka", "on", "sonra"):
                c.send(new_signal(BLD, "ActionInvoked", "us", (7, senaryo)))
            elif senaryo == "kapat":
                c.send(new_signal(BLD, "NotificationClosed", "uu", (7, 2)))
            elif senaryo == "sahte_once":
                c2 = open_dbus_connection(bus="SESSION")
                c2.send(new_signal(BLD, "ActionInvoked", "us", (7, "on")))
                c2.close()
                import time; time.sleep(0.2)
                c.send(new_signal(BLD, "ActionInvoked", "us", (7, "arka")))
        elif uye == "CloseNotification":
            yaz(olay="CloseNotification", id=m.body[0])
            c.send(new_method_return(m))
        else:
            c.send(new_error(m, "org.freedesktop.DBus.Error.UnknownMethod"))
''')
SAHTE_YOL = os.path.join(GECICI, "sahte_hizmet.py")
with open(SAHTE_YOL, "w") as f:
    f.write(SAHTE)
with open(os.path.join(GECICI, "bus.conf"), "w") as f:
    f.write(BUS_CONF)

GERCEK_BUS = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
bus = subprocess.Popen(["dbus-daemon", "--config-file", os.path.join(GECICI, "bus.conf"), "--nofork", "--print-address=1"],
                       stdout=subprocess.PIPE, text=True)
ADRES = bus.stdout.readline().strip()
os.environ["DBUS_SESSION_BUS_ADDRESS"] = ADRES
kontrol("özel dbus-daemon başladı (gerçek oturum veri yolundan ayrı)", ADRES.startswith("unix:") and ADRES != GERCEK_BUS, ADRES)
sahte_surecler = []


def sahte_baslat(senaryo="arka", inhibited=False, oynaticilar=()):
    kayit = os.path.join(GECICI, f"kayit-{len(sahte_surecler)}.jsonl")
    p = subprocess.Popen([sys.executable, SAHTE_YOL, senaryo, kayit, "1" if inhibited else "0", json.dumps(list(oynaticilar))],
                         stdout=subprocess.PIPE, text=True, env=dict(os.environ, DBUS_SESSION_BUS_ADDRESS=ADRES))
    sahte_surecler.append(p)
    assert p.stdout.readline().strip() == "hazir"
    return p, kayit


def sahte_durdur(p):
    p.terminate()
    p.wait(5)


def kayit_oku(yol):
    try:
        return [json.loads(l) for l in open(yol)]
    except OSError:
        return []


try:
    # ---------------------------------------------------------------- 1) ayarlar
    kontrol("ayarlar: dosya CONFIG_DIR altında", ayarlar.dosya() == os.path.join(_yalitim.DIZINLER["DESKHAND_CONFIG_DIR"], "ayarlar.toml"))
    a = ayarlar.oku()
    kontrol("ayarlar: dosya yokken varsayılanlar", a["karar"] == {"mesgulken": "sor", "sor_sure": 45, "cevapsiz": "arka",
                                                                   "girdi_esik_sn": 20, "tam_ekranda_sor": False}, str(a))
    kontrol("ayarlar: okuma dosya oluşturmaz", not os.path.exists(ayarlar.dosya()))
    ayarlar.ayarla("karar", "mesgulken", "hep-arka")
    ayarlar.ayarla("karar", "sor_sure", "30")
    kontrol("ayarlar: ayarla → yazıldı, takma ad hep-arka → arka, sayı dönüştürüldü",
            ayarlar.oku()["karar"]["mesgulken"] == "arka" and ayarlar.al("karar", "sor_sure") == 30)
    try:
        ayarlar.ayarla("karar", "cevapsiz", "on")
        kontrol("ayarlar: cevapsiz=on reddedilir (sessizce ekrana girilmez)", False)
    except ValueError:
        kontrol("ayarlar: cevapsiz=on reddedilir (sessizce ekrana girilmez)", True)
    with open(ayarlar.dosya(), "w") as f:
        f.write('[karar]\nmesgulken = "uc"\nsor_sure = true\ntam_ekranda_sor = true\nbilinmeyen = 1\n[baska]\nx = 1\n')
    a = ayarlar.oku()["karar"]
    kontrol("ayarlar: geçersiz değerler varsayılana düşer, geçerliler kalır",
            a["mesgulken"] == "sor" and a["sor_sure"] == 45 and a["tam_ekranda_sor"] is True, str(a))
    with open(ayarlar.dosya(), "w") as f:
        f.write("[karar\nbozuk")
    kontrol("ayarlar: bozuk dosya → varsayılanlar", ayarlar.oku()["karar"]["mesgulken"] == "sor")
    import tomllib
    metin = ayarlar.toml_uret({"karar": {"s": 'a"b\\c\nd', "b": True, "n": 2.5, "l": ["x", "y"]}, "bölüm": {"k": 1}})
    geri = tomllib.loads(metin)
    kontrol("ayarlar: üretilen TOML geri okunur (kaçış, bool, float, liste, ASCII dışı ad)",
            geri == {"karar": {"s": 'a"b\\c\nd', "b": True, "n": 2.5, "l": ["x", "y"]}, "bölüm": {"k": 1}}, metin)
    os.remove(ayarlar.dosya())

    # ---------------------------------------------------------------- 2) pencere / tam ekran
    kontrol("kwin_coz: JSON satırı", mesgul.kwin_coz('kdotool-x ERROR deneme\n{"fs":true,"sinif":"mpv"}') == {"fs": True, "sinif": "mpv"})
    kontrol("kwin_coz: null → etkin pencere yok", mesgul.kwin_coz("null") is None)
    kontrol("kwin_coz: boş/bozuk → False (yedek yol)", mesgul.kwin_coz("") is False and mesgul.kwin_coz("{bozuk") is False)
    cg = [0, 0, 2560, 1440]
    kontrol("tam_ekran: KWin fullScreen bayrağı", mesgul.tam_ekran_mi({"fs": True, "g": [10, 10, 100, 100], "cg": cg}))
    kontrol("tam_ekran: kenarlıksız pencere çıkışı kaplıyor", mesgul.tam_ekran_mi({"fs": False, "g": [0, 0, 2560, 1440], "cg": cg}))
    kontrol("tam_ekran: büyütülmüş pencere (panel payı) → hayır", not mesgul.tam_ekran_mi({"fs": False, "g": [0, 0, 2560, 1396], "cg": cg}))
    kontrol("tam_ekran: ikinci ekranda tam ekran (yedek yol, çıkış listesi)",
            mesgul.tam_ekran_mi({"fs": False, "g": [2560, 0, 1920, 1080], "cg": None}, [(0, 0, 2560, 1440), (2560, 0, 1920, 1080)]))
    kontrol("tam_ekran: pencere yok → hayır", not mesgul.tam_ekran_mi(None))

    # ---------------------------------------------------------------- 3) oyun / yasak
    kontrol("yasak_desenleri: dosya yokken varsayılan (boş) liste, dosya OLUŞTURULMAZ",
            not [d for d in mesgul.yasak_desenleri() if "deskhand" not in d.lower()] and not os.path.exists(yollar.yasak_dosya()))
    kontrol("oyun: yasak listesi (başlık)", (mesgul.oyun_mu({"sinif": "x", "baslik": "Ornek Oyun 2"}, ["Ornek Oyun"]) or "").startswith("yasak"))
    kontrol("oyun: steam_app_N sınıfı", "oyun" in (mesgul.oyun_mu({"sinif": "steam_app_1234", "baslik": "Oyun"}, []) or ""))
    kontrol("oyun: .exe sınıfı (wine)", mesgul.oyun_mu({"sinif": "game.exe", "baslik": ""}, []) is not None)
    kontrol("oyun: gamescope", mesgul.oyun_mu({"sinif": "gamescope", "baslik": ""}, []) is not None)
    kontrol("oyun: sıradan pencere → değil", mesgul.oyun_mu({"sinif": "org.kde.dolphin", "baslik": "Ev"}, []) is None)
    kontrol("oyun: bozuk regex satırı atlanır", mesgul.oyun_mu({"sinif": "x", "baslik": "y"}, ["(bozuk"]) is None)

    # ---------------------------------------------------------------- 4) oturum / girdi
    kontrol("loginctl_coz: kilitli + boşta", mesgul.loginctl_coz("LockedHint=yes\nIdleHint=yes") ==
            {"kilitli": True, "bosta": True, "okundu": True})
    kontrol("loginctl_coz: boş çıktı → bilinmiyor (kilitli değil)", mesgul.loginctl_coz("")["okundu"] is False)
    simdi = time.time()
    g = mesgul.girdi_birlestir(False, {"pid": 1, "basla": simdi - 100, "son_insan": simdi - 5}, 20, simdi)
    kontrol("girdi: kayıt 5 sn önce insan girdisi, eşik 20 → var", g["var"] and g["son_sn"] == 5.0 and g["kaynak"] == "anlik+kayit", str(g))
    g = mesgul.girdi_birlestir(False, {"pid": 1, "basla": simdi - 100, "son_insan": simdi - 50}, 20, simdi)
    kontrol("girdi: kayıt 50 sn önce → yok", not g["var"])
    kontrol("girdi: anlık insan → var", mesgul.girdi_birlestir(True, None, 20)["var"])
    kontrol("girdi: izlenemedi → yok, kaynak 'yok'", mesgul.girdi_birlestir(None, None, 20) == {
        "var": False, "anlik": None, "son_sn": None, "esik_sn": 20, "kaynak": "yok"})
    os.makedirs(yollar.runtime_dir(), exist_ok=True)
    with open(mesgul.etkinlik_kaydi_yolu(), "w") as f:
        json.dump({"pid": os.getpid(), "basla": simdi, "son_insan": None}, f)
    kontrol("etkinlik_kaydi: izleyici yaşıyor → okunur", mesgul.etkinlik_kaydi() is not None)
    olu = subprocess.Popen(["true"]); olu.wait()
    with open(mesgul.etkinlik_kaydi_yolu(), "w") as f:
        json.dump({"pid": olu.pid, "basla": simdi, "son_insan": simdi}, f)
    kontrol("etkinlik_kaydi: izleyici ölü → yok sayılır", mesgul.etkinlik_kaydi() is None)
    os.remove(mesgul.etkinlik_kaydi_yolu())

    class SahteEtk:
        def __init__(self, insan=False, calisir=True):
            self.hazir_an, self._insan, self._c, self.kapandi = time.monotonic(), insan, calisir, False
        def calisiyor(self): return self._c
        def insan(self, beri): return self._insan
        def kapat(self): self.kapandi = True
    eski_etk = mesgul._etkinlik_yap
    e = SahteEtk(insan=True)
    mesgul._etkinlik_yap = lambda: e
    t0 = time.monotonic(); s = mesgul.AnlikGirdi().sonuc()
    kontrol("AnlikGirdi: insan var, ~ANLIK_SN sürer, yardımcı kapatılır",
            s is True and e.kapandi and mesgul.ANLIK_SN - 0.02 <= time.monotonic() - t0 < mesgul.ANLIK_SN + 0.2)
    mesgul._etkinlik_yap = lambda: SahteEtk(calisir=False)
    kontrol("AnlikGirdi: yardımcı çalışmıyor → None", mesgul.AnlikGirdi().sonuc() is None)

    # ---------------------------------------------------------------- 5) bildirim ayarları (plasmanotifyrc)
    rc = os.path.join(GECICI, "plasmanotifyrc")
    eski_rc = mesgul.plasma_rc_yolu
    mesgul.plasma_rc_yolu = lambda: rc
    b = mesgul.bildirim_durumu(None)
    kontrol("plasmanotifyrc yok → Plasma varsayılanları (tam ekranda DND açık, kritikler açık)",
            b["dnd_tam_ekran"] and b["kritik_dnd"] and not b["bastiriliyor"] and not b["okundu"], str(b))
    with open(rc, "w") as f:
        f.write("[Applications][firefox]\nSeen=true\n\n[DoNotDisturb]\nWhenFullscreen=false\n\n[Notifications]\nCriticalInDndMode=false\n")
    b = mesgul.bildirim_durumu(None)
    kontrol("plasmanotifyrc: WhenFullscreen/CriticalInDndMode okunur", not b["dnd_tam_ekran"] and not b["kritik_dnd"], str(b))
    mesgul.plasma_rc_yolu = lambda: os.path.join(GECICI, "yok-rc")

    # ---------------------------------------------------------------- 6) MPRIS + Inhibited (özel veri yolu, sahte hizmet)
    oyn = [{"ad": "sahte.instance_1_42", "durum": "Playing", "baslik": "Deneme Filmi"},
           {"ad": "durgun", "durum": "Paused", "baslik": "Şarkı"}]
    p, _ = sahte_baslat("arka", inhibited=True, oynaticilar=oyn)
    conn = mesgul._dbus_ac()
    m = mesgul.medya(conn)
    kontrol("MPRIS: iki oynatıcı, çalanın başlığı okunur, örnek eki atılır",
            m == [{"oynatici": "durgun", "durum": "Paused", "baslik": ""},
                  {"oynatici": "sahte", "durum": "Playing", "baslik": "Deneme Filmi"}], str(m))
    kontrol("bildirim sunucusu: Inhibited (Rahatsız Etme) okunur", mesgul.bildirim_durumu(conn)["bastiriliyor"] is True)
    kontrol("ScreenSaver hizmeti yok → kilitli sayılmaz (otomatik başlatma yok)",
            mesgul._cagir(conn, "org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver", "GetActive") is None)
    conn.close()

    # durum(): tüm sinyaller sahte
    eski = (mesgul._kd, mesgul._calis, mesgul._yedek_pencere)
    kwin = {"fs": True, "sinif": "mpv", "ad": "mpv", "baslik": "film.mkv", "g": [0, 0, 2560, 1440], "cikis": "DP-1",
            "cg": [0, 0, 2560, 1440], "kimlik": "{x}"}
    mesgul._kd = lambda *a: json.dumps(kwin) if a[:1] == ("kwinscript",) else ""
    mesgul._calis = lambda argv, sure=1.5: "LockedHint=no\nIdleHint=no" if argv[0] == "loginctl" else ""
    mesgul._etkinlik_yap = lambda: SahteEtk(insan=False)
    t0 = time.monotonic()
    d = mesgul.durum()
    kontrol("durum: tam ekran + medya → meşgul", d["mesgul"] and d["nedenler"] == ["tam_ekran", "medya"], str(d["nedenler"]))
    kontrol("durum: hızlı (< 0,5 sn)", time.monotonic() - t0 < 0.5, f"{time.monotonic() - t0:.2f}")
    kontrol("durum: ayrıntıda pencere + oynatıcı + Rahatsız Etme",
            d["ayrinti"]["pencere"]["sinif"] == "mpv" and d["ayrinti"]["bildirim"]["bastiriliyor"]
            and any(o["baslik"] == "Deneme Filmi" for o in d["ayrinti"]["medya"]))
    mesgul._calis = lambda argv, sure=1.5: "LockedHint=yes\nIdleHint=no" if argv[0] == "loginctl" else ""
    d = mesgul.durum()
    kontrol("durum: kilitli → meşgul DEĞİL, neden kullanici_yok", not d["mesgul"] and d["nedenler"] == ["kullanici_yok"]
            and d["ayrinti"]["oturum"]["kilitli"])
    kwin_kilit = dict(kwin, fs=True, sinif="kscreenlocker_greet")
    mesgul._kd = lambda *a: json.dumps(kwin_kilit)
    mesgul._calis = lambda argv, sure=1.5: "LockedHint=no\nIdleHint=no"
    kontrol("durum: kilit ekranı penceresi → kilitli", mesgul.durum()["ayrinti"]["oturum"]["kilitli"])
    mesgul._kd = lambda *a: ""
    mesgul._yedek_pencere = lambda: {"fs": False, "sinif": "steam_app_99", "ad": "", "baslik": "Oyun", "g": [0, 0, 800, 600],
                                     "cikis": "", "cg": None, "kimlik": "{y}"}
    mesgul._calis = lambda argv, sure=1.5: "LockedHint=no\nIdleHint=yes"
    mesgul._etkinlik_yap = lambda: SahteEtk(insan=True)
    eski_cik = mesgul._cikislar
    mesgul._cikislar = lambda: [(0, 0, 2560, 1440)]
    d = mesgul.durum()
    kontrol("durum: kwinscript yok → yedek yol; oyun + girdi; boşta ama girdi var → kullanıcı VAR",
            d["mesgul"] and "oyun" in d["nedenler"] and "girdi" in d["nedenler"] and not d["ayrinti"]["tam_ekran"], str(d["nedenler"]))
    sahte_durdur(p)
    mesgul._etkinlik_yap = lambda: SahteEtk(insan=False)
    mesgul._yedek_pencere = lambda: None
    d = mesgul.durum()
    kontrol("durum: oturum boşta, girdi yok → kullanici_yok, meşgul değil", not d["mesgul"] and d["nedenler"] == ["kullanici_yok"])
    mesgul._calis = lambda argv, sure=1.5: "LockedHint=no\nIdleHint=no"
    d = mesgul.durum()
    kontrol("durum: hiçbir sinyal yok (hizmet de yok) → meşgul değil", not d["mesgul"] and d["nedenler"] == [], str(d["nedenler"]))
    mesgul._kd, mesgul._calis, mesgul._yedek_pencere = eski
    mesgul._cikislar, mesgul._etkinlik_yap = eski_cik, eski_etk

    # ---------------------------------------------------------------- 7) karar tablosu (sahte durum + sahte sor)
    def sahte_d(mesgul_=True, nedenler=("medya",), kilitli=False, tam=False, bastir=False, dnd_tam=True, kritik=True):
        return {"mesgul": mesgul_, "nedenler": list(nedenler), "ayrinti": {
            "tam_ekran": tam, "oturum": {"kilitli": kilitli, "bosta": False},
            "bildirim": {"bastiriliyor": bastir, "dnd_tam_ekran": dnd_tam, "kritik_dnd": kritik}}}

    def ayar(**k):
        a = {"karar": dict(ayarlar.VARSAYILAN["karar"])}
        a["karar"].update(k)
        return a

    cagri = []
    def sor_f(cevap):
        def f(ozet, sure, kritik=False):
            cagri.append((ozet, sure, kritik))
            return cevap, "sahte"
        return f

    def K(d, a=None, cevap="on"):
        cagri.clear()
        return mesgul.karar_ayrintili("Rapor indir", d, a or ayar(), sor_f(cevap))

    r = K(sahte_d(False, ["kullanici_yok"], kilitli=True))
    kontrol("karar: kilitli → arka (sorulmaz)", r["karar"] == "arka" and not cagri)
    r = K(sahte_d(False, []))
    kontrol("karar: meşgul değil → on", r["karar"] == "on" and not cagri)
    r = K(sahte_d(False, ["kullanici_yok"]))
    kontrol("karar: oturum boşta (kilitsiz) → on", r["karar"] == "on" and "boşta" in r["neden"])
    r = K(sahte_d(), ayar(mesgulken="arka"))
    kontrol("karar: meşgul + mesgulken=arka → arka", r["karar"] == "arka" and not cagri)
    r = K(sahte_d(), ayar(mesgulken="bekle"))
    kontrol("karar: meşgul + mesgulken=bekle → sonra", r["karar"] == "sonra" and not cagri)
    r = K(sahte_d(), cevap="on")
    kontrol("karar: meşgul + sor → kullanıcı 'Ekranımda yap' → on (normal öncelik, süre ayardan)",
            r["karar"] == "on" and r["soruldu"] and cagri == [("Rapor indir", 45, False)], str(cagri))
    r = K(sahte_d(), ayar(cevapsiz="sonra"), cevap=None)
    kontrol("karar: sor → yanıt yok → cevapsiz (sonra)", r["karar"] == "sonra" and r["soruldu"])
    r = K(sahte_d(nedenler=["tam_ekran", "medya"], tam=True, bastir=True))
    kontrol("karar: tam ekran (film) + varsayılan → SORMADAN cevapsiz=arka", r["karar"] == "arka" and not cagri and not r["soruldu"])
    r = K(sahte_d(nedenler=["girdi"], bastir=True))
    kontrol("karar: elle Rahatsız Etme açık → sormadan cevapsiz", r["karar"] == "arka" and not cagri)
    r = K(sahte_d(nedenler=["tam_ekran"], tam=True, bastir=True), ayar(tam_ekranda_sor=True), cevap="sonra")
    kontrol("karar: tam_ekranda_sor=true → KRİTİK bildirimle sorulur", r["karar"] == "sonra" and cagri and cagri[0][2] is True)
    r = K(sahte_d(nedenler=["tam_ekran"], tam=True, bastir=True, kritik=False), ayar(tam_ekranda_sor=True))
    kontrol("karar: DND'de kritikler kapalı → bildirim görünmez, sorulmaz → cevapsiz", r["karar"] == "arka" and not cagri)
    r = K(sahte_d(nedenler=["tam_ekran"], tam=True, bastir=False, dnd_tam=False), ayar(tam_ekranda_sor=True))
    kontrol("karar: tam ekranda DND kapalı + tam_ekranda_sor → sorulur (kritik)", cagri and cagri[0][2] is True)
    son = json.load(open(mesgul.son_karar_yolu()))
    kontrol("karar: son karar RUNTIME_DIR/karar-son.json'a yazılır (tepsi rozeti)",
            son["ozet"] == "Rapor indir" and son["karar"] == r["karar"] and son["nedenler"] == ["tam_ekran"])

    # ---------------------------------------------------------------- 8) bildirim yolu (özel veri yolu, sahte sunucu)
    kontrol("bildirim testi gerçek veri yoluna gitmiyor", os.environ["DBUS_SESSION_BUS_ADDRESS"] == ADRES)
    for senaryo, beklenen in (("arka", "arka"), ("on", "on"), ("sonra", "sonra"), ("kapat", "sonra")):
        p, kayit = sahte_baslat(senaryo)
        cevap, aciklama = mesgul.sor("Raporu <indir> & kaydet", 5, kritik=(senaryo == "on"))
        olaylar = kayit_oku(kayit)
        kontrol(f"sor: sunucu '{senaryo}' → {beklenen}", cevap == beklenen, f"{cevap} {aciklama}")
        if senaryo in ("arka", "on"):
            n = olaylar[0] if olaylar else {}
            govde = n.get("govde", [])
            kontrol(f"sor ({senaryo}): Notify içeriği (uygulama, başlık, kaçışlı gövde, 3 eylem, sessiz, süre)",
                    govde[:1] == ["Deskhand"] and govde[3] == mesgul.BILDIRIM_BASLIK and govde[4] == "Raporu &lt;indir&gt; &amp; kaydet"
                    and govde[5] == ["arka", "Arka planda yap", "on", "Ekranımda yap", "sonra", "Sonra"]
                    and n["ipucu"].get("suppress-sound") is True and n["sure"] == 5000, str(n))
            kontrol(f"sor ({senaryo}): aciliyet {'kritik (2)' if senaryo == 'on' else 'normal (1)'}",
                    n.get("ipucu", {}).get("urgency") == (2 if senaryo == "on" else 1))
        sahte_durdur(p)
    p, kayit = sahte_baslat("sessiz")
    t0 = time.monotonic()
    cevap, aciklama = mesgul.sor("x", 0.6)
    gecen_sure = time.monotonic() - t0
    time.sleep(0.1)
    kontrol("sor: yanıt yok → None, süre kadar bekler, bildirim geri çekilir (CloseNotification)",
            cevap is None and 0.55 <= gecen_sure < 2 and any(o["olay"] == "CloseNotification" and o["id"] == 7 for o in kayit_oku(kayit)),
            f"{cevap} {gecen_sure:.2f} {kayit_oku(kayit)}")
    sahte_durdur(p)
    p, _ = sahte_baslat("sahte_once")
    cevap, _a = mesgul.sor("x", 5)
    kontrol("sor: başka bağlantıdan gelen taklit ActionInvoked yok sayılır", cevap == "arka", str(cevap))
    sahte_durdur(p)
    cevap, aciklama = mesgul.sor("x", 1)
    kontrol("sor: bildirim hizmeti yok → None (kilitlenmez)", cevap is None and "yok" in aciklama, aciklama)
    p, _ = sahte_baslat("arka")
    r = mesgul.karar_ayrintili("Arka plan deneme", sahte_d(), ayar())
    kontrol("karar + gerçek sor() yolu: sahte sunucu 'arka' → arka", r["karar"] == "arka" and r["soruldu"], str(r["neden"]))
    sahte_durdur(p)
    mesgul.plasma_rc_yolu = eski_rc

    # ---------------------------------------------------------------- 9) CLI (sahte kdotool/loginctl/etkinlik, özel veri yolu)
    sbin = os.path.join(GECICI, "bin")
    os.makedirs(sbin)
    def program(ad, govde):
        yol = os.path.join(sbin, ad)
        with open(yol, "w") as f:
            f.write("#!/bin/sh\n" + govde + "\n")
        os.chmod(yol, 0o755)
        return yol
    kwin_pencere = json.dumps({"fs": False, "sinif": "org.kde.kate", "ad": "kate", "baslik": "Not", "g": [0, 0, 800, 600],
                               "cikis": "DP-1", "cg": [0, 0, 2560, 1440], "kimlik": "{z}"})
    program("kdotool", f"[ \"$1\" = kwinscript ] && echo '{kwin_pencere}'; exit 0")
    program("loginctl", 'printf "LockedHint=no\\nIdleHint=no\\n"')
    etk = os.path.join(sbin, "sahte-etkinlik")
    with open(etk, "w") as f:
        f.write(f"#!{sys.executable}\nimport time\nprint('hazir', time.monotonic(), flush=True)\ntime.sleep(0.06)\n"
                "print('bosta', time.monotonic(), flush=True)\ntime.sleep(30)\n")
    os.chmod(etk, 0o755)
    xdg = os.path.join(GECICI, "xdg"); os.makedirs(xdg)
    ortam = dict(os.environ, PATH=sbin + os.pathsep + os.environ["PATH"], DESKHAND_ETKINLIK_BIN=etk, XDG_CONFIG_HOME=xdg,
                 DBUS_SESSION_BUS_ADDRESS=ADRES)

    def deskhand(*a):
        r = subprocess.run([sys.executable, "-m", "deskhand", *a], capture_output=True, text=True, cwd=_yalitim.KOK, env=ortam, timeout=30)
        return r.returncode, r.stdout, r.stderr

    p, _ = sahte_baslat("arka", oynaticilar=[{"ad": "muzik", "durum": "Playing", "baslik": "Parça"}])
    kod, out, err = deskhand("mesgul", "--json")
    try:
        j = json.loads(out)
    except ValueError:
        j = {}
    kontrol("cli: mesgul --json → medya çalıyor → meşgul, 0", kod == 0 and j.get("mesgul") and j.get("nedenler") == ["medya"], f"{kod} {out} {err}")
    kod, out, err = deskhand("mesgul")
    kontrol("cli: mesgul insan okunur", kod == 0 and "meşgul: evet — medya" in out and "muzik çalıyor" in out, out + err)
    kod, out, err = deskhand("karar", "Yedek al")
    kontrol("cli: karar → bildirim (sahte) 'arka' → çıktı arka, kod 20", kod == 20 and out.strip() == "arka", f"{kod} {out} {err}")
    sahte_durdur(p)
    p, _ = sahte_baslat("arka")
    kod, out, err = deskhand("karar", "Yedek al", "--json")
    try:
        j = json.loads(out)
    except ValueError:
        j = {}
    kontrol("cli: karar --json, meşgul değil → on, kod 0", kod == 0 and j.get("karar") == "on" and not j.get("soruldu"), f"{kod} {out} {err}")
    os.makedirs(_yalitim.DIZINLER["DESKHAND_CONFIG_DIR"], exist_ok=True)
    with open(ayarlar.dosya(), "w") as f:
        f.write('[karar]\nmesgulken = "bekle"\n')
    sahte_durdur(p)
    p, _ = sahte_baslat("arka", oynaticilar=[{"ad": "muzik", "durum": "Playing", "baslik": "Parça"}])
    kod, out, err = deskhand("karar", "Yedek al")
    kontrol("cli: mesgulken=bekle → sonra, kod 21", kod == 21 and out.strip() == "sonra", f"{kod} {out} {err}")
    sahte_durdur(p)
    kod, out, err = deskhand("yardım")
    kontrol("cli: yardımda mesgul/karar ve 20/21", " busy (mesgul)" in out and " decide (karar)" in out and "20 arka" in out)
finally:
    for p in sahte_surecler:
        if p.poll() is None:
            p.terminate()
    bus.terminate()
    bus.wait(5)
    if GERCEK_BUS is not None:
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = GERCEK_BUS

print(f"\n{gecen}/{toplam} meşgul testi geçti")
sys.exit(0 if gecen == toplam else 1)
