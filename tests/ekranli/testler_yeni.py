#!/usr/bin/python3
"""Deskhand YENİ ekranlı senaryolar (Qt test pencereleri; tarayıcı yok):

  koruma   Ekran koruması (kod 15, CONTRACT CHANGE 7): kendi TAM EKRAN test penceresi etkinken girdi / başka
           pencereyi öne getirme / uygulama açma → 15; okuma serbest; --on-my-screen (--ekranimda) ve
           DESKHAND_EKRANIMDA=1 ile çalışır; pencere normal boyuta dönünce koruma kalkar.
  mpris    Kendi küçük MPRIS oynatıcısı (jeepney, PlaybackStatus=Playing) + aynı uygulamanın (app_id) penceresi
           etkin → 15; başka uygulama etkinken (arka planda müzik) engel yok; Paused → çalışır.
  onay     Onay diyaloğu (CONTRACT §8): `deskhand panel --tepsi` (geçici klasörlerle) + "Satın al"a click-text →
           "Deskhand — Onay" GERÇEKTEN açılıyor mu, ajan girdisi diyaloğa gidemiyor mu (10), kapatma (= Reddet) →
           tıklama yok, süre dolunca red, panel kapalı → hemen red. İNSAN ADIMI: "Reddet" ve "Bir kez izin ver"e
           kullanıcı basar (ekranda sarı şerit + terminal; 30 sn). --insansiz ile atlanır.
  tepsi    Tepsi simgesi StatusNotifierItem olarak kayıtlı mı (org.kde.StatusNotifierWatcher, panelin PID'i);
           DUR menüsü (panel API'si doğrudan, D-Bus menüsü değil) → girdi 13; CLI 'resume' kullanıcının DUR'unu
           kaldıramaz (13); menüden Devam → girdi çalışır.
  arkaon   Görünmez masaüstünde (Xvfb) test penceresi + ön planda başka test penceresi: eşzamanlı tıklama ve
           yazma; iki pencerenin olay günlükleri ayrı, ön plandaki odak değişmez.

Komutlar İngilizce adlarla, birçok adımda Türkçe takma adlarla (ikisi de sınanır).
DESKHAND_* geçici klasörler (ortak/_yalitim): gerçek ayarlara yazılmaz.

Çalıştır:  python3 tests/ekranli/testler_yeni.py [koruma mpris onay tepsi arkaon] [--insansiz]
Süre ~4 dk (+ insan adımları ≤ 1 dk). Bu sırada klavye/fareye dokunma (insan adımı hariç)."""
import os
import re
import signal
import subprocess
import sys
import threading
import time

import ortak  # DESKHAND_* geçici klasörler + deskhand komutu (Deskhand'den ÖNCE içe aktarılır)
from deskhand import guvenlik, onay, yollar  # noqa: F401

DIZIN = os.path.dirname(os.path.abspath(__file__))
PENCERE = os.path.join(DIZIN, "test_pencere.py")
SONUC = []
INSANSIZ = False
MPRIS_AD = "deskhandmpristest"  # oynatıcı adı = test penceresinin Wayland app_id'si
KORUMA_KODU = 15
DUR_KODU = 13
YASAK_KODU = 10


# ---------------------------------------------------------------- ortak yardımcılar

def ekran(*a, env=None, girdi=None, sure=180):
    t = time.monotonic()
    r = subprocess.run([*ortak.EKRAN, *a], capture_output=True, text=True, env=env, input=girdi, timeout=sure)
    ortak.kod12_bildir(r.returncode, a)
    return r.returncode, r.stdout + r.stderr, time.monotonic() - t


def kontrol(ad, kosul, ayrinti=""):
    SONUC.append((ad, bool(kosul)))
    print(f"{'GEÇTİ ' if kosul else 'KALDI!'} {ad}" + (f"  [{ayrinti}]" if ayrinti else ""), flush=True)


def son_satir(out, n=140):
    s = (out or "").strip().splitlines()
    return s[-1][:n] if s else ""


def bekle_kosul(f, sure, aralik=0.2):
    """f() doğru dönene dek bekle → son değer (zaman aşımında da son değer)."""
    bitis = time.monotonic() + sure
    while True:
        v = f()
        if v or time.monotonic() >= bitis:
            return v
        time.sleep(aralik)


def eposta_son(olaylar):
    d = [o[len("eposta="):] for o in olaylar if o.startswith("eposta=")]
    return d[-1] if d else None


def olay_dosyasi_oku(yol):
    try:
        with open(yol) as f:
            return [s for s in f.read().splitlines() if not s.startswith("pencere:")]
    except OSError:
        return []


class TestPenceresi:
    """Kendi Qt test penceremiz (test_pencere.py). Pencere PID ile bulunur; denetim dosyasıyla (girdi
    göndermeden) tam ekran / normal / talimat şeridi yönetilir."""

    def __init__(self, baslik, ad, tam_ekran=False, uygulama_kimligi=None, hazir_ms=300):
        self.baslik, self.tam_ekran, self.uygulama_kimligi, self.hazir_ms = baslik, tam_ekran, uygulama_kimligi, hazir_ms
        self.log = os.path.join(ortak.IS, f"{ad}.log")
        self.komut_yolu = os.path.join(ortak.IS, f"{ad}.komut")
        self.sira = 0
        self.p = None
        self.K = None
        self.okunan = 0

    def ac(self, sure=15):
        env = dict(os.environ, BASLIK=self.baslik, LOG=self.log, HAZIR_MS=str(self.hazir_ms), KOMUT=self.komut_yolu)
        if self.tam_ekran:
            env["TAM_EKRAN"] = "1"
        if self.uygulama_kimligi:
            env["UYGULAMA_KIMLIGI"] = self.uygulama_kimligi
        self.p = subprocess.Popen([sys.executable, PENCERE], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.K = ortak.pencere_bekle(f"^{re.escape(self.baslik)}$", sure=sure, kok_pid=self.p.pid)
        time.sleep(0.6)
        self.yeni_olaylar()
        return self.K

    def komut(self, *satirlar):
        self.sira += 1
        gecici = self.komut_yolu + ".yeni"
        with open(gecici, "w") as f:
            f.write("\n".join([str(self.sira), *satirlar]) + "\n")
        os.replace(gecici, self.komut_yolu)
        time.sleep(0.4)

    def yeni_olaylar(self):
        ol = olay_dosyasi_oku(self.log)
        yeni, self.okunan = ol[self.okunan:], len(ol)
        return yeni

    def koordinat(self, metin, *ek):
        kod, out, _ = ekran("read", self.K, metin, "--stay", *ek)
        self.son = f"kod {kod}: {out.strip()[-300:]}"  # başarısızlıkta ayrıntı
        m = re.search(r"#1 \((\d+),(\d+)\)", out)
        return (m.group(1), m.group(2)) if kod == 0 and m else None

    def kapat(self):
        if self.p is not None and self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait()


# ---------------------------------------------------------------- a) ekran koruması (tam ekran)

def t_koruma():
    from deskhand import mesgul
    N = TestPenceresi("ekran-test KORUMA-N", "koruma-n")
    F = TestPenceresi("ekran-test KORUMA-F", "koruma-f", tam_ekran=True)
    try:
        kN = N.ac()
        kF = F.ac()  # en son açılan: etkin ve tam ekran
        kontrol("koruma: test pencereleri açıldı (PID ile bulundu)", kN and kF, f"{kN} / {kF}")
        if not (kN and kF):
            return
        if ortak.aktif() != kF:
            ortak.kd("windowactivate", kF)  # test kurulumu
        neden = bekle_kosul(mesgul.ekran_korumasi, 6)
        kontrol("ön koşul: tam ekran algılandı (mesgul.ekran_korumasi)", neden and "tam ekran" in neden, neden)
        kontrol("ön koşul: tam ekran pencere etkin", ortak.aktif() == kF)
        xy = F.koordinat("Kaydet")
        kontrol("tam ekranda read (okuma, öne getirme gerekmez) serbest", xy, str(xy) if xy else F.son)
        if not xy:
            return
        F.yeni_olaylar()
        for ad, argv in [
            ("click", ["click", kF, *xy]),
            ("tikla (Türkçe)", ["tikla", kF, *xy]),
            ("click-text", ["click-text", kF, "Kaydet"]),
            ("metne-tikla (Türkçe)", ["metne-tikla", kF, "Kaydet"]),
            ("type", ["type", kF, "x"]),
            ("key", ["key", kF, "Return"]),
            ("hold", ["hold", kF, "w", "0.2"]),
            ("scroll", ["scroll", kF, "down", "1"]),
        ]:
            kod, out, t = ekran(*argv)
            o = F.yeni_olaylar()
            kontrol(f"tam ekran: {ad} → 15, girdi gitmedi", kod == KORUMA_KODU and not o,
                    f"kod {kod}, {t:.2f} sn, olay {o}, {son_satir(out)}")
        kod, out, t = ekran("open", "--command", "true", "-b", "^hic-acilmayacak$", "--timeout", "2")
        kontrol("tam ekran: open (uygulama açma) → 15 (7 değil)", kod == KORUMA_KODU, f"kod {kod}, {son_satir(out)}")
        kod, out, t = ekran("click", kN, "60", "60")
        kontrol("tam ekran: BAŞKA pencereye click (öne getirme) → 15, odak çalınmadı",
                kod == KORUMA_KODU and ortak.aktif() == kF and not N.yeni_olaylar(), f"kod {kod}, {son_satir(out)}")
        kod, out, t = ekran("metin", kN)  # Türkçe ad; okumak için öne getirmek gerekir
        kontrol("tam ekran: başka pencereyi metin/read (öne getirme gerekir) → 15", kod == KORUMA_KODU and ortak.aktif() == kF,
                f"kod {kod}, {son_satir(out)}")

        # kullanıcının açık izni
        kod, out, t = ekran("--on-my-screen", "click", kF, *xy)
        o = F.yeni_olaylar()
        kontrol("--on-my-screen click → 0, tıklandı", kod == 0 and o == ["tık: Kaydet"], f"kod {kod}, olay {o}")
        kod, out, t = ekran("--ekranimda", "tikla", kF, *xy)
        o = F.yeni_olaylar()
        kontrol("--ekranimda tikla (Türkçe) → 0, tıklandı", kod == 0 and o == ["tık: Kaydet"], f"kod {kod}, olay {o}")
        kod, out, t = ekran("click-text", kF, "Kaydet", env=dict(os.environ, DESKHAND_EKRANIMDA="1"))
        o = F.yeni_olaylar()
        kontrol("DESKHAND_EKRANIMDA=1 click-text → 0", kod == 0 and o == ["tık: Kaydet"], f"kod {kod}, olay {o}")

        # pencere normal boyuta dönünce koruma kalkar
        F.komut("normal")
        neden2 = bekle_kosul(lambda: mesgul.ekran_korumasi() is None, 6)
        kontrol("normal boyut: koruma kalktı", neden2, str(mesgul.ekran_korumasi()))
        xy2 = F.koordinat("Kaydet")
        F.yeni_olaylar()
        kod, out, t = ekran("click", kF, *(xy2 or ("0", "0")))
        o = F.yeni_olaylar()
        kontrol("normal boyut: click → 0, tıklandı", kod == 0 and o == ["tık: Kaydet"], f"kod {kod}, olay {o}")
        # tekrar tam ekran → yine 15
        F.komut("tam")
        bekle_kosul(mesgul.ekran_korumasi, 6)
        kod, out, t = ekran("click-text", kF, "Kaydet")
        kontrol("yeniden tam ekran → yine 15", kod == KORUMA_KODU and not F.yeni_olaylar(), f"kod {kod}")
    finally:
        F.kapat()
        N.kapat()


# ---------------------------------------------------------------- a2) ekran koruması (MPRIS)

def t_mpris():
    from deskhand import mesgul
    from mpris_test import MprisSunucu
    N = TestPenceresi("ekran-test MPRIS-N", "mpris-n")
    M = TestPenceresi("ekran-test MPRIS", "mpris", uygulama_kimligi=MPRIS_AD)
    m = MprisSunucu(MPRIS_AD)
    try:
        try:
            m.baslat()
            kontrol("MPRIS: test oynatıcısı veri yolunda (Playing)", True, m.bus_adi)
        except Exception as ex:  # noqa: BLE001
            kontrol("MPRIS: test oynatıcısı veri yolunda (Playing)", False, repr(ex)[:120])
            return
        kN = N.ac()
        kM = M.ac()
        kontrol("MPRIS: test pencereleri açıldı", kN and kM)
        if not (kN and kM):
            return
        sinif = (ortak.sinif(kM) or "").lower()
        kontrol("MPRIS: pencere sınıfı (app_id) = oynatıcı adı", sinif == MPRIS_AD, sinif)
        if ortak.aktif() != kM:
            ortak.kd("windowactivate", kM)
        neden = bekle_kosul(mesgul.ekran_korumasi, 6)
        kontrol("ön koşul: 'video/film izliyor' algılandı", neden and MPRIS_AD in neden, neden)
        xy = M.koordinat("Kaydet")
        kontrol("MPRIS: read (okuma) serbest", xy)
        if not xy:
            return
        M.yeni_olaylar()
        kod, out, t = ekran("click", kM, *xy)
        kontrol("MPRIS çalarken aynı uygulamanın penceresi etkin: click → 15", kod == KORUMA_KODU and not M.yeni_olaylar(),
                f"kod {kod}, {son_satir(out)}")
        kod, out, t = ekran("metne-tikla", kM, "Kaydet")
        kontrol("MPRIS: metne-tikla (Türkçe) → 15", kod == KORUMA_KODU and not M.yeni_olaylar(), f"kod {kod}")

        ortak.kd("windowactivate", kN)
        bekle_kosul(lambda: ortak.aktif() == kN, 3)
        xyN = N.koordinat("Kaydet")
        N.yeni_olaylar()
        kod, out, t = ekran("click", kN, *(xyN or ("0", "0")))
        o = N.yeni_olaylar()
        kontrol("arka planda çalan medya (başka uygulama etkin) engel DEĞİL: click → 0", kod == 0 and o == ["tık: Kaydet"],
                f"kod {kod}, olay {o}, {son_satir(out)}")

        m.durum = "Paused"
        kod, out, t = ekran("click", kM, *xy)  # öne getirme + girdi; duraklatılmış oynatıcı engel değil
        o = M.yeni_olaylar()
        kontrol("MPRIS Paused: aynı pencereye click → 0", kod == 0 and o == ["tık: Kaydet"], f"kod {kod}, olay {o}")
        m.durum = "Playing"
        kod, out, t = ekran("click", kM, *xy)
        kontrol("MPRIS yeniden Playing → 15", kod == KORUMA_KODU and not M.yeni_olaylar(), f"kod {kod}")
        kod, out, t = ekran("--on-my-screen", "click", kM, *xy)
        o = M.yeni_olaylar()
        kontrol("MPRIS Playing + --on-my-screen → 0", kod == 0 and o == ["tık: Kaydet"], f"kod {kod}, olay {o}")
    finally:
        m.durdur()
        M.kapat()
        N.kapat()


# ---------------------------------------------------------------- b) onay diyaloğu

def diyaloglar(panel_pid):
    """Panelimizin (PID) açık onay diyalogları. Kullanıcının kendi Deskhand paneli varsa onunkiler sayılmaz."""
    return [k for k in ortak.ara(f"^{re.escape(onay.ONAY_BASLIK)}") if ortak.pid(k) == panel_pid]


def panel_baslat():
    log = open(os.path.join(ortak.IS, "panel.log"), "a")
    P = subprocess.Popen([*ortak.EKRAN, "panel", "--tepsi"], stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    log.close()
    ok = bekle_kosul(lambda: onay.panel_pid() == P.pid, 15)
    return P, ok


def panel_durdur(P):
    if P is None or P.poll() is not None:
        return
    P.send_signal(signal.SIGTERM)
    try:
        P.wait(timeout=10)
    except subprocess.TimeoutExpired:
        P.kill()
        P.wait()


def satin_al_istegi(kW):
    """Ajanın hassas tıklaması: onay bekler (en çok 120 sn) → Popen."""
    return subprocess.Popen([*ortak.EKRAN, "click-text", kW, "Satın al"], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def bitir(cp, sure):
    try:
        out, err = cp.communicate(timeout=sure)
    except subprocess.TimeoutExpired:
        cp.kill()
        out, err = cp.communicate()
        return None, (out or "") + (err or "")
    return cp.returncode, (out or "") + (err or "")


def insan_adimi(W, kW, P, dugme, sure=30):
    """Kullanıcıdan diyalogda `dugme`ye basmasını iste. → (kod, çıktı) | (None, neden)."""
    cp = satin_al_istegi(kW)
    D = bekle_kosul(lambda: diyaloglar(P.pid), 25)
    if not D:
        cp.kill()
        cp.communicate()
        return None, "diyalog açılmadı"
    mesaj = (f"ŞİMDİ: ekrandaki 'Deskhand — Onay' penceresinde '{dugme}' düğmesine FAREYLE basın, "
             f"sonra fareyi bırakın ({sure} sn)")
    W.komut(f"yazi:{mesaj}")
    print("\a\n" + "=" * 78 + f"\n>>> {mesaj}\n" + "=" * 78, flush=True)
    t0 = time.monotonic()
    while cp.poll() is None and time.monotonic() - t0 < sure:
        time.sleep(0.2)
    W.komut("yazi:")
    if cp.poll() is None and diyaloglar(P.pid):
        cp.kill()  # insan basmadı: istek geri çekilir (isteyen öldü), diyalog kapanır
        cp.communicate()
        return None, f"{sure} sn içinde basılmadı"
    return bitir(cp, 20)  # izin sonrası tıklama insan önceliği beklemesine girebilir


def t_onay():
    P = cp = None
    W = TestPenceresi("ekran-test ONAY", "onay")
    try:
        P, ok = panel_baslat()
        kontrol("panel --tepsi başladı (panel.pid geçici çalışma dizininde)", ok, f"pid {P.pid}")
        if not ok:
            return
        kW = W.ac()
        kontrol("onay: test penceresi açıldı", kW)
        if not kW:
            return

        # 1) diyalog açılır, ajan girdisi ona gidemez, kapatma = Reddet
        cp = satin_al_istegi(kW)
        D = bekle_kosul(lambda: diyaloglar(P.pid), 25)
        D = D[0] if D else None
        kontrol("onay diyaloğu ekranda açıldı ('Deskhand — Onay', panelimizin PID'i)", D)
        if D:
            kontrol("istek bekliyor (RUNTIME_DIR/onay, 1 istek)", len(onay.bekleyenler()) == 1, str(len(onay.bekleyenler())))
            # KDE Wayland yeni pencereyi etkinleştiriyor (WA_ShowWithoutActivating X11'de çalışır). Güvenli olan:
            # odak diyaloğa geçse bile Enter/Esc = Reddet (varsayılan düğme). Odağı aldıysa bilgi olarak yaz.
            if ortak.aktif() == D:
                print("BİLGİ  diyalog klavye odağını aldı (KDE Wayland); Enter/Esc = Reddet olduğu için güvenli")
            for ad, argv in [
                ("click --approved", ["click", D, "40", "40", "--approved"]),
                ("tikla --onayli (Türkçe)", ["tikla", D, "40", "40", "--onayli"]),
                ("click-text 'Bir kez izin ver'", ["click-text", D, "Bir kez izin ver"]),
                ("key Return", ["key", D, "Return"]),
                ("tus space (Türkçe)", ["tus", D, "space"]),
                ("click-element 'Bir kez izin ver'", ["click-element", D, "Bir kez izin ver"]),
                ("close", ["-b", "Deskhand", "close", D]),
                ("--on-my-screen click --approved", ["--on-my-screen", "click", D, "40", "40", "--approved"]),
            ]:
                kod, out, t = ekran(*argv)
                kontrol(f"diyaloğa ajan girdisi: {ad} → 10", kod == YASAK_KODU, f"kod {kod}, {son_satir(out)}")
            try:
                gx, gy, gg, gy2 = ortak.sec().geometri(D)
                # masaüstü kipi: imlecin altındaki pencere denetlenir. --approved: hassas yazı OCR'ı yeni bir onay
                # istemesin (beklemede asılı kalmasın); sınanan şey yasak denetimi
                kod, out, t = ekran("click", "ekran", str(gx + 40), str(gy + 40), "--approved")
                kontrol("masaüstü kipinde ('ekran') diyaloğun üstüne click --approved → 10", kod == YASAK_KODU, f"kod {kod}, {son_satir(out)}")
            except Exception as ex:  # noqa: BLE001
                kontrol("masaüstü kipinde diyaloğun üstüne click → 10", False, repr(ex)[:120])
            kontrol("ajan denemelerinden sonra: istek hâlâ bekliyor, tıklama yok",
                    cp.poll() is None and len(onay.bekleyenler()) == 1 and not [o for o in W.yeni_olaylar() if "Satın" in o])
            ortak.kd("windowclose", D)  # insan taklidi: pencereyi kapatmak = Reddet (onay_diyalog.closeEvent)
            kod, out = bitir(cp, 15)
            kontrol("diyalog kapatıldı (= Reddet) → click-text 10, 'reddetti'", kod == YASAK_KODU and "reddetti" in out,
                    f"kod {kod}, {son_satir(out, 200)}")
            kontrol("red sonrası tıklama YOK (test log)", not [o for o in W.yeni_olaylar() if "Satın" in o])
            kontrol("diyalog penceresi kapandı", bekle_kosul(lambda: not diyaloglar(P.pid), 5))
            kalan = [a for a in (os.listdir(onay.dizin()) if os.path.isdir(onay.dizin()) else [])
                     if a.startswith(("istek-", "yanit-"))]
            kontrol("istek/yanıt dosyaları silindi (tek kullanımlık)", not kalan, str(kalan))
        else:
            cp.kill()
            cp.communicate()

        # 2) süre dolunca red (API, kısa süre; CLI'nin varsayılanı 120 sn)
        sonuc = {}
        th = threading.Thread(target=lambda: sonuc.setdefault("s", onay.iste_sonuc(
            "ekranlı test: süre dolumu", "ekran-test ONAY", "Bu istek yanıtsız kalacak (süre testi)", sure=6)))
        t0 = time.monotonic()
        th.start()
        D2 = bekle_kosul(lambda: diyaloglar(P.pid), 5)
        kontrol("süre testi: diyalog açıldı", D2)
        th.join(20)
        s = sonuc.get("s")
        kontrol("süre dolunca red (neden 'sure', izin yok)", s is not None and not s.izin and s.neden == "sure",
                f"{s and s.neden}, {time.monotonic() - t0:.1f} sn")
        kontrol("süre dolunca diyalog kendiliğinden kapandı", bekle_kosul(lambda: not diyaloglar(P.pid), 5))

        # 3) İNSAN: Reddet, sonra Bir kez izin ver
        if INSANSIZ:
            print("ATLANDI (--insansiz): insan adımları ('Reddet', 'Bir kez izin ver')", flush=True)
        else:
            W.yeni_olaylar()
            kod, out = insan_adimi(W, kW, P, "Reddet")
            o = [x for x in W.yeni_olaylar() if "Satın" in x]
            kontrol("İNSAN 'Reddet' → 10, tıklama yok", kod == YASAK_KODU and "reddetti" in out and not o,
                    f"kod {kod}, olay {o}, {son_satir(out, 160)}")
            kod, out = insan_adimi(W, kW, P, "Bir kez izin ver")
            o = [x for x in W.yeni_olaylar() if "Satın" in x]
            kontrol("İNSAN 'Bir kez izin ver' → 0, tam bir tıklama", kod == 0 and o == ["tık: Satın al"],
                    f"kod {kod}, olay {o}, {son_satir(out, 160)}")
            # tek kullanımlık: aynı eylem yine sorar
            cp = satin_al_istegi(kW)
            D3 = bekle_kosul(lambda: diyaloglar(P.pid), 25)
            kontrol("izin tek kullanımlık: ikinci tıklama yine onay ister", D3)
            if D3:
                ortak.kd("windowclose", D3[0])
            kod, out = bitir(cp, 15)
            kontrol("ikinci istek kapatıldı → 10, tıklama yok", kod == YASAK_KODU and not [x for x in W.yeni_olaylar() if "Satın" in x],
                    f"kod {kod}")

        # 4) panel kapalı → hemen red
        panel_durdur(P)
        kontrol("panel SIGTERM ile kapandı, panel.pid silindi", P.poll() is not None and onay.panel_pid() is None)
        kod, out, t = ekran("click-text", kW, "Satın al")
        kontrol("panel kapalı: hassas click-text → 10, hemen ('panel kapalı')", kod == YASAK_KODU and "panel" in out.lower()
                and t < 10 and not [x for x in W.yeni_olaylar() if "Satın" in x], f"kod {kod}, {t:.1f} sn, {son_satir(out)}")
    finally:
        if cp is not None and cp.poll() is None:
            cp.kill()
            cp.communicate()
        panel_durdur(P)
        W.kapat()


# ---------------------------------------------------------------- c) tepsi

SNI_IZLEYICI = ("/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher")
SNI_ARAYUZ = "org.kde.StatusNotifierItem"


def sni_ayir(oge):
    """RegisteredStatusNotifierItems ögesi → (servis, nesne yolu). Biçimler: 'servis/yol' (Qt/KDE:
    'org.kde.StatusNotifierItem-PID-N/StatusNotifierItem', ':1.42/org/ayatana/…') ya da yalnız servis."""
    i = oge.find("/")
    if i <= 0:
        return oge, "/StatusNotifierItem"
    return oge[:i], oge[i:]


def sni_ogeleri():
    """Kayıtlı tepsi ögeleri: [{oge, servis, yol, pid, id}] (oturum veri yolu, SALT OKUMA)."""
    from jeepney import DBusAddress, MessageType, Properties
    from jeepney.bus_messages import message_bus
    from jeepney.io.blocking import open_dbus_connection

    def cagir(conn, msg):
        try:
            r = conn.send_and_get_reply(msg, timeout=2)
        except Exception:  # noqa: BLE001
            return None
        return None if r.header.message_type == MessageType.error else r.body

    conn = open_dbus_connection(bus="SESSION")
    try:
        izleyici = DBusAddress(SNI_IZLEYICI[0], bus_name=SNI_IZLEYICI[1], interface=SNI_IZLEYICI[1])
        g = cagir(conn, Properties(izleyici).get("RegisteredStatusNotifierItems"))
        sonuc = []
        for oge in (g[0][1] if g else []):
            servis, yol = sni_ayir(oge)
            p = cagir(conn, message_bus.GetConnectionUnixProcessID(servis))
            i = cagir(conn, Properties(DBusAddress(yol, bus_name=servis, interface=SNI_ARAYUZ)).get("Id"))
            sonuc.append({"oge": oge, "servis": servis, "yol": yol, "pid": p[0] if p else None,
                          "id": i[0][1] if i else None})
        return sonuc
    finally:
        conn.close()


def bizim_sni(pid):
    try:
        return [o for o in sni_ogeleri() if o["pid"] == pid]
    except Exception:  # noqa: BLE001
        return []


def satir_oku(p, sure):
    import select
    r, _, _ = select.select([p.stdout], [], [], sure)
    return p.stdout.readline().strip() if r else ""


def yardimci_komut(H, komut, sure=5):
    H.stdin.write(komut + "\n")
    H.stdin.flush()
    return satir_oku(H, sure)


def t_tepsi():
    # c1) gerçek komut: deskhand panel --tepsi → SNI kaydı
    P = H = None
    W = TestPenceresi("ekran-test TEPSI", "tepsi")
    try:
        P, ok = panel_baslat()
        kontrol("tepsi: panel --tepsi başladı", ok)
        if ok:
            ogeler = bekle_kosul(lambda: bizim_sni(P.pid), 10)
            kontrol("tepsi simgesi StatusNotifierItem olarak kayıtlı (RegisteredStatusNotifierItems, panelin PID'i)",
                    ogeler, str([o["oge"] for o in ogeler]))
            kontrol("tepsi ögesinin kimliği (Id) 'deskhand'", any("deskhand" in (o["id"] or "").lower() for o in ogeler),
                    str([o["id"] for o in ogeler]))
            pid = P.pid
            panel_durdur(P)
            kontrol("panel kapanınca tepsi kaydı silindi", bekle_kosul(lambda: not bizim_sni(pid), 6))
        else:
            panel_durdur(P)  # yarım kalan panel yardımcının tek örnek soketini tutmasın

        # c2) DUR menüsü: panel API'si doğrudan (tepsi menüsünün QAction'ı)
        H = subprocess.Popen([sys.executable, os.path.join(DIZIN, "panel_yardimci.py")], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=open(os.path.join(ortak.IS, "panel_yardimci.log"), "a"),
                             text=True)
        hazir = satir_oku(H, 20)
        kontrol("tepsi yardımcısı (Panel + Tepsi bu süreçte) hazır", hazir.startswith("hazir"), hazir)
        if not hazir.startswith("hazir"):
            return
        kW = W.ac()
        xy = W.koordinat("Kaydet") if kW else None
        kontrol("tepsi: test penceresi açıldı, Kaydet okundu", kW and xy)
        if not xy:
            return
        W.yeni_olaylar()
        m = yardimci_komut(H, "menu")
        kontrol("menü başlangıçta: DUR görünür, Devam gizli", m == "menu dur=1 devam=0", m)
        yanit = yardimci_komut(H, "dur")
        kontrol("tepsi menüsü DUR tetiklendi", yanit == "tamam dur", yanit)
        kontrol("DUR açık, kaynağı 'kullanici'", bekle_kosul(lambda: guvenlik.dur_kaynagi() == "kullanici", 3),
                str(guvenlik.dur_kaynagi()))
        for ad, argv in [("click", ["click", W.K, *xy]), ("tikla (Türkçe)", ["tikla", W.K, *xy]),
                         ("type", ["type", W.K, "x"]), ("open", ["open", "--command", "true", "--timeout", "2"])]:
            kod, out, t = ekran(*argv)
            kontrol(f"DUR açıkken {ad} → 13, girdi yok", kod == DUR_KODU and not W.yeni_olaylar(), f"kod {kod}, {son_satir(out)}")
        kod, out, t = ekran("resume")
        kontrol("CLI 'resume' kullanıcının DUR'unu KALDIRAMAZ → 13", kod == DUR_KODU and guvenlik.dur_acik(), f"kod {kod}")
        kod, out, t = ekran("devam")
        kontrol("CLI 'devam' (Türkçe) da kaldıramaz → 13", kod == DUR_KODU and guvenlik.dur_acik(), f"kod {kod}")
        kod, out, t = ekran("status")
        kontrol("status: DUR açık gösterilir", kod == 0 and "AÇIK" in out, son_satir(out))
        m = bekle_kosul(lambda: (lambda x: x if x == "menu dur=0 devam=1" else "")(yardimci_komut(H, "menu")), 5)
        kontrol("menü DUR'dayken: DUR gizli, Devam görünür", m == "menu dur=0 devam=1", m)
        yanit = yardimci_komut(H, "devam")
        kutu = bekle_kosul(lambda: (lambda x: x if x == "kutu 1" else "")(yardimci_komut(H, "devam-kutusu")), 5)
        kontrol("tepsi menüsü Devam → DUR hemen KALKMAZ, panelde onay sorulur", yanit == "tamam devam" and
                kutu == "kutu 1" and guvenlik.dur_acik(), f"{yanit} {kutu}")
        kod, out, t = ekran("click", W.K, *xy)
        kontrol("onay kutusu açıkken click hâlâ 13", kod == DUR_KODU, f"kod {kod}")
        yardimci_komut(H, "devam-vazgec")
        kontrol("'DUR açık kalsın' → DUR açık kalır", guvenlik.dur_acik())
        yardimci_komut(H, "devam")
        bekle_kosul(lambda: (lambda x: x if x == "kutu 1" else "")(yardimci_komut(H, "devam-kutusu")), 5)
        yanit = yardimci_komut(H, "devam-onayla")
        kontrol("tepsi menüsü Devam → panelde 'Devam et' → DUR kalktı", yanit == "tamam devam-onayla" and
                bekle_kosul(lambda: not guvenlik.dur_acik(), 3))
        kod, out, t = ekran("click", W.K, *xy)
        o = W.yeni_olaylar()
        kontrol("Devam sonrası click → 0, tıklandı", kod == 0 and o == ["tık: Kaydet"], f"kod {kod}, olay {o}")
        yardimci_komut(H, "cik")
    finally:
        if H is not None:
            try:
                H.wait(timeout=5)
            except subprocess.TimeoutExpired:
                H.terminate()
                H.wait()
        panel_durdur(P)
        W.kapat()
        if guvenlik.dur_acik():  # geçici çalışma dizini; yine de temiz bırak
            guvenlik.dur_kapat("kullanici")


# ---------------------------------------------------------------- d) arka plan + ön plan birlikte

def t_arkaon():
    kod, out, t = ekran("desktop", "start")
    kontrol("görünmez masaüstü başladı (desktop start)", kod == 0, f"kod {kod}, {t:.1f} sn, {son_satir(out)}")
    if kod != 0:
        return
    A = None
    a_log = os.path.join(ortak.IS, "arka.log")
    O = TestPenceresi("ekran-test ON", "on")
    try:
        env = dict(os.environ, BASLIK="ekran-test ARKA", LOG=a_log, HAZIR_MS="300")
        kod, out, t = ekran("--background", "open", "--command", f"{sys.executable} {PENCERE}", "-b", "^ekran-test ARKA$",
                            "--timeout", "30", env=env)
        m = re.search(r"^(arka:\S+) \| ", out, re.M)
        A = m.group(1) if m else None
        kontrol("arka planda test penceresi açıldı (arka: kimliği)", kod == 0 and A, f"kod {kod}, {son_satir(out)}")
        if not A:
            return
        kontrol("arka pencere kullanıcının ekranında YOK (KWin'de görünmez)", not ortak.ara("ekran-test ARKA"))
        kO = O.ac()
        kontrol("ön planda test penceresi açıldı", kO)
        if not kO:
            return
        time.sleep(0.5)
        a_once = len(olay_dosyasi_oku(a_log))
        xyO = O.koordinat("İptal")
        O.yeni_olaylar()
        # eşzamanlı tıklama: arka 'Kaydet', ön 'İptal'
        pa = subprocess.Popen([*ortak.EKRAN, "--background", "click-text", A, "Kaydet"], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
        po = subprocess.Popen([*ortak.EKRAN, "click", kO, *(xyO or ("0", "0"))], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
        ka, oa = bitir(pa, 60)
        ko, oo = bitir(po, 60)
        a_yeni = olay_dosyasi_oku(a_log)[a_once:]
        o_yeni = O.yeni_olaylar()
        kontrol("eşzamanlı: arka click-text → 0, ön click → 0", ka == 0 and ko == 0, f"arka {ka} {son_satir(oa)}, ön {ko} {son_satir(oo)}")
        kontrol("günlükler ayrı: arka yalnız 'tık: Kaydet', ön yalnız 'tık: İptal'",
                a_yeni == ["tık: Kaydet"] and o_yeni == ["tık: İptal"], f"arka {a_yeni}, ön {o_yeni}")
        kontrol("arka plan işi ön plandaki odağı değiştirmedi", ortak.aktif() == kO)

        # eşzamanlı yazma (Türkçe takma adlar arka planda)
        ekran("--arka", "metne-tikla", A, "E-posta", "--kay", "300,0")
        ekran("click-text", kO, "E-posta", "--offset", "300,0")
        a_once = len(olay_dosyasi_oku(a_log))
        O.yeni_olaylar()
        arka_metin, on_metin = "arka plan çğış 123", "ön plan ÖĞÜ 456"
        pa = subprocess.Popen([*ortak.EKRAN, "--arka", "yaz", A, arka_metin], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
        po = subprocess.Popen([*ortak.EKRAN, "type", kO, on_metin], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        ka, oa = bitir(pa, 60)
        ko, oo = bitir(po, 60)
        a_yeni = olay_dosyasi_oku(a_log)[a_once:]
        o_yeni = O.yeni_olaylar()
        ae, oe = eposta_son(a_yeni), eposta_son(o_yeni)
        kontrol("eşzamanlı yazma: arka kutu = arka metni, ön kutu = ön metni", ka == 0 and ko == 0 and ae == arka_metin
                and oe == on_metin, f"arka {ae!r} (kod {ka}), ön {oe!r} (kod {ko})")
        kontrol("yazılar karışmadı (her günlükte yalnız kendi metninin önekleri)",
                all(arka_metin.startswith(x[len("eposta="):]) for x in a_yeni if x.startswith("eposta="))
                and all(on_metin.startswith(x[len("eposta="):]) for x in o_yeni if x.startswith("eposta=")),
                f"arka {len(a_yeni)} olay, ön {len(o_yeni)} olay")
        kod, out, t = ekran("--background", "read", A)
        kontrol("arka read: 'Kaydet' okundu, ön plandaki odak değişmedi", kod == 0 and "Kaydet" in out and ortak.aktif() == kO,
                f"kod {kod}, {t:.1f} sn")
    finally:
        if A:
            ekran("--background", "-b", "^ekran-test ARKA$", "close", A)
        O.kapat()
        kod, out, t = ekran("desktop", "stop")
        kontrol("görünmez masaüstü kapatıldı (desktop stop)", kod == 0, son_satir(out))


SENARYOLAR = {"koruma": t_koruma, "mpris": t_mpris, "onay": t_onay, "tepsi": t_tepsi, "arkaon": t_arkaon}


def main(argv=None):
    global INSANSIZ
    argv = list(sys.argv[1:] if argv is None else argv)
    INSANSIZ = "--insansiz" in argv
    secim = [a for a in argv if not a.startswith("--")] or list(SENARYOLAR)
    bilinmeyen = [a for a in secim if a not in SENARYOLAR]
    if bilinmeyen:
        print(f"bilinmeyen senaryo: {bilinmeyen}; seçenekler: {' '.join(SENARYOLAR)} [--insansiz]")
        return 2
    t0 = time.monotonic()
    for ad in secim:
        print(f"\n== {ad}", flush=True)
        try:
            SENARYOLAR[ad]()
        except Exception as ex:  # noqa: BLE001
            import traceback
            kontrol(f"{ad}: beklenmedik hata", False, repr(ex)[:160])
            traceback.print_exc()
    g = sum(1 for _, ok in SONUC if ok)
    print(f"\n{g}/{len(SONUC)} yeni senaryo testi geçti ({time.monotonic() - t0:.0f} sn)")
    return 0 if g == len(SONUC) else 1


if __name__ == "__main__":
    sys.exit(main())
