"""Görev yürütücü (deskhand/gorev.py) + panelin Görev sekmesi testleri. GERÇEK `claude` ÇALIŞTIRILMAZ (kota): PATH'te
SAHTE bir `claude` vardır; argv'yi/istemi/MCP yapılandırmasını dosyaya yazar ve hazır stream-json satırları basar. HOME
geçici klasördür (gerçek ~/.local/bin/claude bulunamaz). Qt GÖRÜNMEZ (offscreen); gerçek ekrana girdi/pencere yok.

Çalıştır:  python3 tests/test_gorev.py"""
import json, os, stat, sys, tempfile, time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
os.environ["XDG_CONFIG_HOME"] = "/nonexistent-deskhand-test"
import _yalitim  # noqa: E402,F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

TMP = tempfile.mkdtemp(prefix="gorev-test-", dir=_yalitim.GECICI)
os.environ["HOME"] = os.path.join(TMP, "home")  # gerçek ~/.local/bin/claude (ve deskhand) bulunmasın
os.makedirs(os.environ["HOME"])
BIN = os.path.join(TMP, "bin")
os.makedirs(BIN)
KAYIT = os.path.join(TMP, "kayit.json")
COCUK = os.path.join(TMP, "cocuk.pid")
os.environ["DESKHAND_SAHTE_KAYIT"] = KAYIT
os.environ["DESKHAND_SAHTE_COCUK"] = COCUK
ESKI_PATH = os.environ["PATH"]
SAHTE = os.path.join(BIN, "claude")
SAHTE_KOD = r'''#!%s
import json, os, signal, subprocess, sys, time
mod = os.environ.get("DESKHAND_SAHTE_MOD", "tamam")
argv = sys.argv[1:]
mcp = ""
if "--mcp-config" in argv:
    try:
        mcp = open(argv[argv.index("--mcp-config") + 1]).read()
    except OSError:
        pass
stdin = sys.stdin.read()
json.dump({"argv": argv, "stdin": stdin, "mcp": mcp, "cwd": os.getcwd(), "cwd_ls": os.listdir("."),
           "gercek_ekran": os.environ.get("DESKHAND_GERCEK_EKRAN"), "claudecode": os.environ.get("CLAUDECODE"),
           "pid": os.getpid()}, open(os.environ["DESKHAND_SAHTE_KAYIT"], "w"))
def bas(o):
    print(json.dumps(o, ensure_ascii=False), flush=True)
if mod == "mcp_yok":
    bas({"type": "system", "subtype": "init", "mcp_servers": [{"name": "deskhand-gorev", "status": "failed"}]})
    bas({"type": "result", "subtype": "success", "is_error": False, "result": "bitti"})
else:
    bas({"type": "system", "subtype": "init", "mcp_servers": [{"name": "deskhand-gorev", "status": "connected"}]})
if mod == "tamam":
    bas({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "Firefox'u acmaliyim"},
         {"type": "text", "text": "Basliyorum"},
         {"type": "tool_use", "id": "t1", "name": "mcp__deskhand-gorev__open_app",
          "input": {"app": "firefox", "desktop": "background", "blob": "A" * 5000}}]}})
    bas({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": [
         {"type": "text", "text": "pencere acildi " + "x" * 2000},
         {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD" * 5000}}]}]}})
    bas({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t2",
         "name": "mcp__deskhand-gorev__click", "input": {"ref": "a1b2-3:7"}}]}})
    bas({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "is_error": True,
         "content": "[8] ref bayat"}]}})
    bas({"type": "result", "subtype": "success", "is_error": False, "result": "Sepete eklendi.\nBitti."})
elif mod in ("uyku", "inatci"):
    if mod == "inatci":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    c = subprocess.Popen(["sleep", "300"])
    open(os.environ["DESKHAND_SAHTE_COCUK"], "w").write(str(c.pid))
    while True:
        time.sleep(0.2)
elif mod == "giris":
    bas({"type": "result", "subtype": "success", "is_error": True, "result": "Not logged in · Please run /login"})
    sys.exit(1)
elif mod == "cikis":
    sys.stderr.write("claude: Invalid API key\n")
    sys.exit(1)
elif mod == "sonucsuz":
    sys.exit(0)
''' % sys.executable
with open(SAHTE, "w") as f:
    f.write(SAHTE_KOD)
os.chmod(SAHTE, 0o755)
os.environ["PATH"] = BIN + os.pathsep + ESKI_PATH

from deskhand import ayarlar, gorev, guvenlik, yollar  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


def kos(metin="görev", mod="tamam", **kw):
    """Sahte claude ile görevi çalıştır → (Gorev, olaylar)."""
    os.environ["DESKHAND_SAHTE_MOD"] = mod
    olaylar = []
    g = gorev.Gorev(olay_cb=olaylar.append, kafes=False, **kw)
    g.baslat(metin)
    g.bekle(30)
    return g, olaylar


def olu_mu(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] == "Z"
    except OSError:
        return True


def bayrak_degerleri(argv, bayrak):
    """--bayrak'tan sonraki, sonraki -- bayrağına kadar olan değerler."""
    i = argv.index(bayrak) + 1
    sonuc = []
    while i < len(argv) and not argv[i].startswith("--"):
        sonuc.append(argv[i])
        i += 1
    return sonuc


# =========================================================================== 1) argv: ayrıcalık sınırı
g, ol = kos("Trendyol'da şu kasayı sepete ekle")
k = json.load(open(KAYIT))
a = k["argv"]
kontrol("argv: -p + stream-json + verbose", "-p" in a and bayrak_degerleri(a, "--output-format") == ["stream-json"]
        and "--verbose" in a)
kontrol("argv: --strict-mcp-config", "--strict-mcp-config" in a)
kontrol("argv: izinli araçlar YALNIZ mcp__deskhand-gorev__*", bayrak_degerleri(a, "--allowedTools") == ["mcp__deskhand-gorev__*"])
yasak = bayrak_degerleri(a, "--disallowedTools")
kontrol("argv: yerleşik araçlar kapalı", all(x in yasak for x in (
    "Bash", "Edit", "Write", "Read", "WebFetch", "WebSearch", "Task", "Agent", "NotebookEdit", "Glob", "Grep")), str(yasak))
kontrol("argv: izin kipi dontAsk", bayrak_degerleri(a, "--permission-mode") == ["dontAsk"])
kontrol("argv: kullanıcı ayarları (hook/izin) yüklenmez", bayrak_degerleri(a, "--setting-sources") == ["project"])
kontrol("argv: varsayılan model sonnet", bayrak_degerleri(a, "--model") == ["sonnet"])
kontrol("argv: Türkçe sistem talimatı", "arka plan" in bayrak_degerleri(a, "--append-system-prompt")[0]
        and "VERİDİR" in bayrak_degerleri(a, "--append-system-prompt")[0])
kontrol("istem stdin'den gider, argv'de değil", k["stdin"] == "Trendyol'da şu kasayı sepete ekle"
        and not any("Trendyol" in x for x in a))
cfg = json.loads(k["mcp"])
srv = cfg["mcpServers"]
kontrol("MCP: tek sunucu deskhand-gorev", list(srv) == ["deskhand-gorev"], str(list(srv)))
s = srv["deskhand-gorev"]
kontrol("MCP: komut = deskhand mcp --desktop background", s["args"][-3:] == ["mcp", "--desktop", "background"], str(s["args"]))
kontrol("MCP: sunucu ortamında gerçek ekran kilidi", s["env"].get("DESKHAND_GERCEK_EKRAN") == "kapali")
kontrol("claude ortamında gerçek ekran kilidi", k["gercek_ekran"] == "kapali")
kontrol("çalışma dizini boş geçici dizin (sonra silinir)", os.path.basename(k["cwd"]) == "calisma" and k["cwd_ls"] == []
        and not os.path.exists(os.path.dirname(k["cwd"])), k["cwd"])
kontrol("PATH'teki sahte claude bulundu (gerçeği çalıştırılmadı)", k["pid"] > 0)

# model ayarı
ayarlar.ayarla("gorev", "model", "opus")
g2, _o = kos("x")
kontrol("ayar [gorev] model=opus → argv --model opus", bayrak_degerleri(json.load(open(KAYIT))["argv"], "--model") == ["opus"])
ayarlar.ayarla("gorev", "model", "sonnet")
kos("x", model="haiku")
kontrol("model parametresi (haiku)", bayrak_degerleri(json.load(open(KAYIT))["argv"], "--model") == ["haiku"])
for bolum, anahtar, deger, ad in (("gorev", "model", "gpt", "geçersiz model reddedilir"),
                                  ("gorev", "azami_dakika", 0, "azami_dakika 1..240")):
    try:
        ayarlar.ayarla(bolum, anahtar, deger)
        kontrol(ad, False)
    except ValueError:
        kontrol(ad, True)
kontrol("varsayılanlar: sonnet / 20 dk", ayarlar.al("gorev", "model") == "sonnet" and ayarlar.al("gorev", "azami_dakika") == 20)

# bellek kafesi öneki
kaf = gorev.komut_olustur("/x/claude", "/x/mcp.json", "sonnet", kafes=True)
kontrol("bellek kafesi: systemd-run --user --scope MemoryMax=4G", kaf[:4] == ["systemd-run", "--user", "--scope", "--quiet"]
        and "MemoryMax=4G" in kaf and "/x/claude" in kaf)
kontrol("bellek kafesi yok → doğrudan claude", gorev.komut_olustur("/x/claude", "/x/m", "sonnet")[0] == "/x/claude")
kontrol("bellek_kafesi_var bool", isinstance(gorev.bellek_kafesi_var(), bool))

# =========================================================================== 2) olay ayrıştırma
turler = [o["tur"] for o in ol]
kontrol("olay sırası", turler == ["dusunce", "metin", "arac", "arac_sonuc", "arac", "arac_sonuc", "sonuc", "bitti"], str(turler))
kontrol("olay biçimi: tur/zaman/ozet", all({"tur", "zaman", "ozet"} <= set(o) for o in ol)
        and all(len(o["zaman"]) == 8 for o in ol))
arac = [o for o in ol if o["tur"] == "arac"]
kontrol("arac: öneksiz ad + kısaltılmış girdi", arac[0]["arac"] == "open_app" and arac[0]["girdi"]["app"] == "firefox"
        and len(str(arac[0]["girdi"]["blob"])) <= 100, str(arac[0]))
sonuclar = [o for o in ol if o["tur"] == "arac_sonuc"]
kontrol("arac_sonuc: kısaltıldı, ad eşleşti", sonuclar[0]["arac"] == "open_app" and len(sonuclar[0]["ozet"]) <= 300
        and sonuclar[0]["ozet"].startswith("pencere acildi"), sonuclar[0]["ozet"][:60])
kontrol("arac_sonuc: hata bayrağı", sonuclar[0]["hata"] is False and sonuclar[1]["hata"] is True)
img = gorev.ayristir({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "q", "content": [
    {"type": "image", "source": {"type": "base64", "data": "QUJD" * 5000}}]}]}}, {})
kontrol("görüntü bloğu '[görüntü]' olur, base64 geçmez", img[0]["ozet"] == "[görüntü]", str(img))
kontrol("sonuc: ajanın özeti (satır sonu korunur)", [o for o in ol if o["tur"] == "sonuc"][0]["ozet"] == "Sepete eklendi.\nBitti.")
b = ol[-1]
kontrol("bitti: durum tamam + kayıt dosyası", b["durum"] == "tamam" and b["dosya"] == g.dosya and g.id)
gunluk_metni = open(g.dosya, encoding="utf-8").read()
kontrol("base64 olaya/günlüğe girmez", "QUJD" * 10 not in json.dumps(ol) and "QUJD" * 10 not in gunluk_metni
        and "A" * 150 not in gunluk_metni)
kontrol("günlük: kullanıcının görev metni tutulur", "Trendyol'da şu kasayı sepete ekle" in gunluk_metni)
d = gorev.ayristir({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "z",
                    "name": "mcp__deskhand-gorev__type_text", "input": {"text": "merhaba"}}]}}, {})
kontrol("ayristir: tek nesne", d and d[0]["ozet"].startswith('type_text({"text": "merhaba"'), str(d))
kontrol("ayristir: bilinmeyen/biçimsiz nesne → []", gorev.ayristir({"type": "rate_limit_event"}) == []
        and gorev.ayristir("çöp") == [] and gorev.ayristir(None) == [])

g3, ol3 = kos("x", mod="mcp_yok")
kontrol("MCP sunucusu yüklenemezse hata olayı", any(o["tur"] == "hata" and "yüklenemedi" in o["ozet"] for o in ol3))

# =========================================================================== 3) geçmiş
yol = g.dosya
st = os.stat(yol)
kontrol("geçmiş dosyası 0600", stat.S_IMODE(st.st_mode) == 0o600, oct(st.st_mode))
kontrol("geçmiş dizini 0700", stat.S_IMODE(os.stat(os.path.dirname(yol)).st_mode) == 0o700)
kontrol("geçmiş dizini STATE_DIR/gorevler", os.path.dirname(yol) == os.path.join(yollar.state_dir(), "gorevler"))
gm = gorev.gecmis()
ilk = [x for x in gm if x["dosya"] == yol]
kontrol("gecmis(): alanlar", ilk and ilk[0]["durum"] == "tamam" and ilk[0]["metin"] == "Trendyol'da şu kasayı sepete ekle"
        and ilk[0]["ozet"] == "Sepete eklendi.\nBitti." and ilk[0]["model"] == "sonnet", str(ilk))
kontrol("gecmis(): en yeni önce", [x["dosya"] for x in gm] == sorted((x["dosya"] for x in gm), reverse=True))
kontrol("olaylar(dosya) başlıksız adımlar", [o["tur"] for o in gorev.olaylar(yol)][:3] == ["dusunce", "metin", "arac"])
kontrol("olaylar(): geçmiş dizini dışındaki dosya okunmaz", gorev.olaylar(SAHTE) == [])
d = gorev.gecmis_dizini()
for i in range(60):
    p = os.path.join(d, f"20200101-0000{i:02d}-x{i:02d}.jsonl")
    with open(p, "w") as f:
        f.write(json.dumps({"tur": "gorev", "id": f"x{i}", "metin": "eski"}) + "\n")
kos("budama")
n = len([f for f in os.listdir(d) if f.endswith(".jsonl")])
kontrol("geçmiş en çok 50 görev", n == 50, str(n))
from deskhand import gunluk  # noqa: E402
eski = time.time() - 30 * 86400
for f in os.listdir(d):
    os.utime(os.path.join(d, f), (eski, eski))
gunluk.temizle()
kontrol("gunluk.temizle görev geçmişini süreyle silmez", len(os.listdir(d)) == n)


# =========================================================================== 4) durdurma
def durdurma_dene(mod):
    os.environ["DESKHAND_SAHTE_MOD"] = mod
    if os.path.exists(COCUK):
        os.remove(COCUK)
    ol = []
    g = gorev.Gorev(olay_cb=ol.append, kafes=False)
    g.baslat("uzun iş")
    bas = time.monotonic()
    while not os.path.exists(COCUK) or not open(COCUK).read():
        time.sleep(0.05)
        assert time.monotonic() - bas < 10
    cocuk = int(open(COCUK).read())
    kontrol(f"{mod}: çalışıyor", g.calisiyor and not olu_mu(cocuk))
    t0 = time.monotonic()
    ok = g.durdur()
    kontrol(f"{mod}: durdur() engellemez", ok and time.monotonic() - t0 < 0.5)
    kontrol(f"{mod}: bitti", g.bekle(20), "20 sn içinde bitmedi")
    return g, ol, cocuk, time.monotonic() - t0


gorev.OLDURME_BEKLEME = 1.0
g4, ol4, cocuk, sure = durdurma_dene("uyku")
kontrol("durdur: süreç GRUBU ölür (çocuk dahil)", olu_mu(cocuk))
kontrol("durdur: bitti.durum = durduruldu", ol4[-1]["tur"] == "bitti" and ol4[-1]["durum"] == "durduruldu", str(ol4[-1:]))
kontrol("durdur: SIGTERM'le hızlı (<2 sn)", sure < 2.0, f"{sure:.1f}")
kontrol("durdur: bitince tekrar durdur False", g4.durdur() is False)
g5, ol5, cocuk5, sure5 = durdurma_dene("inatci")
kontrol("inatçı süreç SIGKILL ile ölür", olu_mu(cocuk5) and ol5[-1]["durum"] == "durduruldu", str(ol5[-1:]))
kontrol("SIGKILL ~OLDURME_BEKLEME sonra", 0.9 < sure5 < 6, f"{sure5:.1f}")
kontrol("görev durdurma Deskhand DUR anahtarını açmaz", not guvenlik.dur_kaynagi())

# zaman aşımı
os.environ["DESKHAND_SAHTE_MOD"] = "uyku"
if os.path.exists(COCUK):
    os.remove(COCUK)
olz = []
gz = gorev.Gorev(olay_cb=olz.append, kafes=False, azami_sn=1.0)
t0 = time.monotonic()
gz.baslat("sonsuz")
gz.bekle(20)
kontrol("zaman aşımı: durdurulur", olz and olz[-1]["tur"] == "bitti" and olz[-1]["durum"] == "zaman_asimi"
        and any(o["tur"] == "hata" and o.get("kod") == "zaman_asimi" for o in olz), str(olz[-2:]))
kontrol("zaman aşımı: ~1 sn sonra", 0.8 < time.monotonic() - t0 < 8, f"{time.monotonic() - t0:.1f}")
kontrol("zaman aşımı: çocuk da öldü", olu_mu(int(open(COCUK).read())))

# aynı anda tek görev
os.environ["DESKHAND_SAHTE_MOD"] = "uyku"
ga = gorev.Gorev(kafes=False)
ga.baslat("a")
try:
    ga.baslat("b")
    kontrol("aynı nesnede ikinci görev reddedilir", False)
except gorev.GorevHatasi as e:
    kontrol("aynı nesnede ikinci görev reddedilir", "zaten çalışıyor" in e.mesaj)
try:
    gorev.Gorev(kafes=False).baslat("b")
    kontrol("başka nesne/süreç de reddedilir (flock)", False)
except gorev.GorevHatasi as e:
    kontrol("başka nesne/süreç de reddedilir (flock)", "zaten çalışıyor" in e.mesaj)
ga.durdur()
ga.bekle(20)
os.environ["DESKHAND_SAHTE_MOD"] = "tamam"
try:
    gb = gorev.Gorev(kafes=False)
    gb.baslat("c")
    gb.bekle(20)
    kontrol("önceki bitince yeni görev başlar (kilit bırakıldı)", True)
except gorev.GorevHatasi as e:
    kontrol("önceki bitince yeni görev başlar (kilit bırakıldı)", False, str(e))

# =========================================================================== 5) hatalar
for ad_, mod in (("giriş yapılmamış", "giris"), ("claude hata koduyla çıktı", "cikis")):
    g6, ol6 = kos("x", mod=mod)
    h = [o for o in ol6 if o["tur"] == "hata"]
    kontrol(f"{ad_}: hata + /login ipucu", h and "/login" in h[0].get("ipucu", "") and ol6[-1]["durum"] == "hata", str(ol6))
g7, ol7 = kos("x", mod="sonucsuz")
kontrol("sonuçsuz bitiş hata sayılır", ol7[-1]["durum"] == "hata" and any("sonuç vermeden" in o["ozet"] for o in ol7))

os.environ["PATH"] = os.path.join(TMP, "bos")
os.makedirs(os.environ["PATH"], exist_ok=True)
try:
    gorev.Gorev(kafes=False).baslat("x")
    kontrol("claude yok → açık hata", False)
except gorev.GorevHatasi as e:
    kontrol("claude yok → açık Türkçe hata + ipucu", "bulunamadı" in e.mesaj and "giriş" in e.ipucu, str(e))
os.environ["PATH"] = BIN + os.pathsep + ESKI_PATH
for kotu in ("", "   ", "x" * 5000):
    try:
        gorev.Gorev(kafes=False).baslat(kotu)
        kontrol(f"geçersiz görev metni ({len(kotu)}) reddedilir", False)
    except gorev.GorevHatasi:
        kontrol(f"geçersiz görev metni ({len(kotu)}) reddedilir", True)
kontrol("hatalı başlatmalardan sonra görev kilidi serbest", gorev.Gorev(kafes=False)._kilit_al().close() is None)

# =========================================================================== 6) arayüz
# =========================================================================== 6) arayüz (Qt offscreen)
from PIL import Image  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from deskhand.gui import durum as D  # noqa: E402
from deskhand.gui.gorev import GorevSekmesi, adim_metni  # noqa: E402
from deskhand.gui.pencere import AnaPencere  # noqa: E402
from deskhand.gui.tepsi import Tepsi  # noqa: E402

app = QApplication([])


def bekle(kosul, sure=15.0):
    son = time.monotonic() + sure
    while time.monotonic() < son:
        app.processEvents()
        if kosul():
            return True
        time.sleep(0.01)
    app.processEvents()
    return kosul()


class SahteArka:
    kareler = 0

    def goruntu(self):
        SahteArka.kareler += 1
        return Image.new("RGB", (640, 360), (30, 90, 150))


class SahteGorev:
    """Yürütücü yerine: olayları test elle yayar."""
    son = None

    def __init__(self, olay_cb=None):
        self.olay_cb, self.metin, self.durduruldu, self.calisiyor = olay_cb, None, 0, False
        SahteGorev.son = self

    def baslat(self, metin):
        if metin == "HATA":
            raise gorev.GorevHatasi("`claude` komutu bulunamadı.", "Claude Code'u kurun.")
        self.metin, self.calisiyor = metin, True
        return "abc"

    def durdur(self):
        self.durduruldu += 1
        return True

    def bekle(self, sure=None):
        return True


class SahteMasaustu:
    @staticmethod
    def durum(dogrula=True):
        return None


gec = [{"dosya": os.path.join(gorev.gecmis_dizini(), "x.jsonl"), "id": "x", "zaman": "2026-11-22 10:30:00",
        "metin": "İndirilenler'i düzenle", "model": "sonnet", "durum": "tamam", "ozet": "12 dosya taşındı."}]
w = AnaPencere([], arka_f=SahteArka, masaustu_m=SahteMasaustu, gorev_f=SahteGorev)
sek = w.gorev
kontrol("pencere: Görev sekmesi İLK sekme", w.sekmeler.widget(0) is sek and w.sekmeler.tabText(0) == "Görev"
        and w.sekmeler.count() == 7)
tp = Tepsi()
kontrol("tepsi menüsünde 'Görev ver…'", tp.a_gorev.text() == "Görev ver…")
alinan = []
tp.gorev_istendi.connect(lambda: alinan.append(1))
tp.a_gorev.trigger()
kontrol("tepsi: Görev ver… sinyali", alinan == [1])
w.sekmeler.setCurrentWidget(w.ayarlar)
w.gorev_goster()
kontrol("gorev_goster(): Görev sekmesi açılır", w.sekmeler.currentWidget() is sek)

kontrol("başta: Başlat açık, Durdur kapalı, kutu serbest", sek.b_baslat.isEnabled() and not sek.b_durdur.isEnabled()
        and not sek.kutu.isReadOnly() and sek.c_model.isEnabled())
kontrol("başta: Devral kapalı (masaüstü yok)", not sek.b_devral.isEnabled())
kontrol("başta: durum etiketi 'Hazır'", sek.l_durum.text().startswith("Hazır"))
kontrol("model seçici: 3 model, varsayılan sonnet", sek.c_model.count() == 3 and sek.c_model.currentData() == "sonnet")
sek.c_model.setCurrentIndex(sek.c_model.findData("haiku"))
kontrol("model seçici ayara yazar", ayarlar.al("gorev", "model") == "haiku")
sek.c_model.setCurrentIndex(sek.c_model.findData("sonnet"))

sek.baslat()
kontrol("boş görev başlamaz", SahteGorev.son is None and not sek.calisiyor)
sek.kutu.setPlainText("HATA")
sek.baslat()
kontrol("başlatma hatası: açık Türkçe hata + ipucu, kilitlenmez",
        not sek.calisiyor and "bulunamadı" in sek.sonuc.toPlainText() and "kurun" in sek.sonuc.toPlainText()
        and sek.b_baslat.isEnabled() and not sek.kutu.isReadOnly())

sek.kutu.setPlainText("Trendyol'da şu kasayı sepete ekle")
sek.kutu.setFocus()
QTest.keyClick(sek.kutu, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
app.processEvents()
g = SahteGorev.son
kontrol("Ctrl+Enter görevi başlatır", sek.calisiyor and g.metin == "Trendyol'da şu kasayı sepete ekle")
kontrol("çalışırken: kutu kilitli, Başlat kapalı, Durdur açık, model kilitli",
        sek.kutu.isReadOnly() and not sek.b_baslat.isEnabled() and sek.b_durdur.isEnabled() and not sek.c_model.isEnabled())
kontrol("çalışırken: durum 'Çalışıyor'", sek.l_durum.text().startswith("Çalışıyor"))
sek.baslat()
kontrol("çalışırken ikinci Başlat yok sayılır", SahteGorev.son is g)


def yay(**o):
    o.setdefault("zaman", "10:00:00")
    o.setdefault("ozet", "")
    g.olay_cb(o)
    app.processEvents()


yay(tur="dusunce", ozet="…")
yay(tur="dusunce", ozet="…")
yay(tur="arac", arac="open_app", girdi={"app": "firefox"}, kimlik="t1", ozet='open_app({"app": "firefox"})')
yay(tur="arac_sonuc", arac="open_app", kimlik="t1", hata=False)
yay(tur="arac", arac="click", girdi={"text": "Sepete ekle"}, kimlik="t2", ozet="click(…)")
yay(tur="arac_sonuc", arac="click", kimlik="t2", hata=True, ozet="[8] ref bayat")
yay(tur="metin", ozet="Sepete ekliyorum")
liste = [sek.liste.item(i).text() for i in range(sek.liste.count())]
kontrol("adımlar canlı + Türkçe açıklama", liste == ["Düşünüyor…", "Firefox açılıyor", "‘Sepete ekle’ tıklanıyor",
                                                      "Sepete ekliyorum"], str(liste))
kontrol("ardışık düşünce tek satır", liste.count("Düşünüyor…") == 1)
kontrol("ham araç adı ipucu olarak", "open_app" in sek.liste.item(1).toolTip())
kontrol("hatalı araç sonucu ipucunda", "ref bayat" in sek.liste.item(2).toolTip())
kontrol("durum: adım sayısı", "2 adım" in sek.l_durum.text(), sek.l_durum.text())
kontrol("adim_metni: bilinen/bilinmeyen araç", adim_metni({"arac": "scroll"}) == "Sayfa kaydırılıyor"
        and adim_metni({"arac": "manage_desktop", "girdi": {"action": "start"}}) == "Görünmez masaüstü açılıyor"
        and adim_metni({"arac": "zzz"}) == "Araç çalışıyor: zzz"
        and adim_metni({"arac": "press_key", "girdi": {"keys": "ctrl+t"}}) == "Tuşa basılıyor: ctrl+t")

# onay bekleniyor
w.durum_guncelle(D.Durum(bekleyen=1))
kontrol("onay isteği gelince sekmede 'onay bekleniyor'", "Onay bekleniyor (1)" in sek.l_durum.text(), sek.l_durum.text())
w.durum_guncelle(D.Durum(bekleyen=0))
kontrol("onay bitince durum geri döner", sek.l_durum.text().startswith("Çalışıyor"))

# canlı görüntü
w.show()
SahteArka.kareler = 0
sek.sanal_guncelle({"ekran": ":91", "boyut": [640, 360, 24]})
kontrol("masaüstü açılınca Devral açılır", sek.b_devral.isEnabled())
kontrol("çalışırken canlı görüntü (sahte arka uçtan) alınır", bekle(lambda: SahteArka.kareler >= 1) and sek.onizleme.resim is not None)
k0 = SahteArka.kareler
kontrol("~1 kare/sn", bekle(lambda: SahteArka.kareler >= k0 + 2, 4.5), f"{SahteArka.kareler - k0}")
kontrol("canlı görüntüde Devral girdisi kapalı (yalnız izleme)", not sek.onizleme.devral)

# Devral düğmesi: mevcut Devral akışı (Arka plan ekranı sekmesi)
sek.b_devral.click()
app.processEvents()
kontrol("Devral düğmesi: Arka plan ekranı açılır, Devral AÇIK", w.sekmeler.currentWidget() is w.arka
        and w.arka.b_devral.isChecked() and sek.b_devral.text() == "Bırak", sek.b_devral.text())
w.sekmeler.setCurrentWidget(sek)
sek.b_devral.click()
app.processEvents()
kontrol("Devral düğmesi tekrar: Devral kapanır", not w.arka.b_devral.isChecked() and sek.b_devral.text() == "Devral")

# durdur
sek.b_durdur.click()
kontrol("Durdur yürütücüye gider", g.durduruldu == 1 and "Durduruluyor" in sek.l_durum.text() and not sek.b_durdur.isEnabled())
yay(tur="sonuc", ozet="Sepete eklendi.")
yay(tur="bitti", ozet="durduruldu", durum="durduruldu", dosya="x")
kontrol("bitince: kutu açılır, düğmeler eski haline", not sek.calisiyor and sek.b_baslat.isEnabled()
        and not sek.b_durdur.isEnabled() and not sek.kutu.isReadOnly() and sek.c_model.isEnabled())
kontrol("sonuç kutusunda ajanın özeti", sek.sonuc.toPlainText() == "Sepete eklendi.")
kontrol("bitince durum 'Durduruldu'", sek.l_durum.text() == "Durduruldu.")
k1 = SahteArka.kareler
time.sleep(1.4)
app.processEvents()
kontrol("görev bitince canlı görüntü DURUR", SahteArka.kareler == k1 and not sek.zaman.isActive())

# hata olayı
sek.kutu.setPlainText("başka")
sek.baslat()
g = SahteGorev.son
yay(tur="hata", ozet="Terminalde giriş yapılmamış", ipucu="Terminalde `claude` çalıştırıp /login ile giriş yapın.")
yay(tur="bitti", ozet="hata", durum="hata")
kontrol("hata olayı: kırmızı satır + sonuç kutusu + /login ipucu", "/login" in sek.sonuc.toPlainText()
        and "giriş yapılmamış" in sek.liste.item(sek.liste.count() - 1).text() and sek.l_durum.text() == "Görev tamamlanamadı.")

# geçmiş
sek2 = GorevSekmesi(arka_f=SahteArka, gorev_f=SahteGorev, gecmis_f=lambda: gec,
                    olaylar_f=lambda d: [{"tur": "arac", "arac": "open_app", "girdi": {"app": "dolphin"}, "kimlik": "q",
                                          "ozet": "open_app(…)"}, {"tur": "arac_sonuc", "kimlik": "q", "hata": False}])
kontrol("geçmiş listesi", sek2.gecmis_liste.count() == 1 and "İndirilenler'i düzenle" in sek2.gecmis_liste.item(0).text()
        and "Bitti." in sek2.gecmis_liste.item(0).text(), sek2.gecmis_liste.item(0).text())
sek2._gecmis_sec(sek2.gecmis_liste.item(0))
kontrol("geçmişe tıklayınca adımlar + özet gösterilir", sek2.liste.count() == 1 and sek2.liste.item(0).text() == "Dolphin açılıyor"
        and sek2.sonuc.toPlainText() == "12 dosya taşındı.")
sek2._gecmis_kutuya(sek2.gecmis_liste.item(0))
kontrol("geçmişe çift tıklayınca metin kutuya gelir", sek2.kutu.toPlainText() == "İndirilenler'i düzenle")

# uçtan uca: GERÇEK yürütücü + sahte claude (araç adları, geçmiş, düğme durumları)
os.environ["DESKHAND_SAHTE_MOD"] = "tamam"
sek3 = GorevSekmesi(arka_f=SahteArka, gorev_f=lambda olay_cb: gorev.Gorev(olay_cb=olay_cb, kafes=False))
sek3.show()
sek3.kutu.setPlainText("Trendyol'da bir şey ara")
sek3.baslat()
kontrol("uçtan uca: başladı, kilitli", sek3.calisiyor and sek3.kutu.isReadOnly())
kontrol("uçtan uca: bitti", bekle(lambda: not sek3.calisiyor, 30), sek3.l_durum.text())
liste3 = [sek3.liste.item(i).text() for i in range(sek3.liste.count())]
kontrol("uçtan uca: adımlar Türkçe", "Firefox açılıyor" in liste3 and "Bir öğe tıklanıyor" in liste3, str(liste3))
kontrol("uçtan uca: sonuç + durum + geçmiş", sek3.sonuc.toPlainText() == "Sepete eklendi.\nBitti." and sek3.l_durum.text() == "Bitti."
        and sek3.gecmis_liste.count() >= 1 and sek3.b_baslat.isEnabled())
w.close()
sek3.kapat()

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
