"""kde arka ucu: kullanıcının gerçek KDE Plasma (Wayland) masaüstü.

kdotool pencere bulur/öne getirir, dotool fare/klavye sürer (uinput), spectacle görüntü alır,
kscreen-doctor ekran düzenini verir. kdotool/dotool/spectacle/kscreen-doctor'a dokunan HER ŞEY bu dosyadadır;
üst katman yalnız KdeArkaUc yöntemlerini kullanır (docs/ARCHITECTURE.md §2).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time

from PIL import Image

from .. import yollar
from ..gunluk import gunluk
from ..hata import INSAN, KULLANICI_MESGUL, Dur, dur_denetle
from ..i18n import _
from ..insan import INSAN_TAKLIDI, Etkinlik, girdi_suresi, insan_bekle, klavye_bekle
from . import EKRAN, ArkaUc

EKRAN_ADLARI = {"ekran", "masaustu", "masaüstü", "tum-ekran", "tüm-ekran"}

# dotool kurulumu (ölçüm): klavye 0 sn, mutlak imleç 0,2, göreli imleç 0,4 sn'de oluşur, sonra 0,2 sn
# bekleyip girdiyi okur. Hazır anı = "dotool relative pointer" aygıtının görünmesi + DOTOOL_SON_UYKU.
# Güvenlik denetimi bu andan SONRA yapılır: kurulum sırasında odak değişirse, kurulumdan önce yapılmış bir
# denetim geçersiz kalır ve girdi yanlış pencereye (ör. kullanıcının terminaline) gider. Bu sıra o yüzden şart.
DOTOOL_SON_UYKU = 0.25
DOTOOL_AZAMI = 3.0  # aygıt bu sürede görünmezse güvenli varsayılan: t0 + 1 sn


def calis(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout.strip()


_KD_OKUMA = {"getactivewindow", "getwindowgeometry", "getwindowname", "getwindowclassname", "getmouselocation"}


def kd(*a):
    """kdotool. OKUMA sorguları boş dönerse 3 kez kısa yeniden dener: kdotool her çağrıda KWin betiği yükler,
    eşzamanlı çağrılarda bazen boş döner (ör. bir sürecin yazı gözcüsü başka süreçte 'pencere bulunamadı'
    yaptırıyordu). Eylemler (windowactivate/close…) yeniden denenmez."""
    out = calis("kdotool", *a)
    if not out and a and a[0] in _KD_OKUMA:
        for _ in range(3):
            time.sleep(0.005)
            out = calis("kdotool", *a)
            if out:
                break
    return out


# ---------------------------------------------------------------- klavye düzeni

_duzen = None


def klavye_duzeni():
    """Etkin KDE klavye düzeni (layout, variant). Sabit "tr" yerine: kullanıcı düzen değiştirirse dotool
    yanlış tuş kodu göndermesin. Tek düzen → kxkbrc; çok düzen → DBus getLayout (~2 ms)."""
    global _duzen
    if _duzen is None:
        duzenler, varyantlar = ["tr"], [""]
        try:
            with open(os.path.expanduser("~/.config/kxkbrc")) as f:
                ic = f.read()
            m = re.search(r"^LayoutList=(.+)$", ic, re.M)
            if m and m.group(1).strip():
                duzenler = [d.strip() for d in m.group(1).split(",")]
            v = re.search(r"^VariantList=(.*)$", ic, re.M)
            varyantlar = [x.strip() for x in v.group(1).split(",")] if v else []
        except OSError:
            pass
        i = 0
        if len(duzenler) > 1:
            try:
                i = int(calis("qdbus6", "org.kde.keyboard", "/Layouts", "org.kde.KeyboardLayouts.getLayout") or 0)
            except ValueError:
                i = 0
        i = min(i, len(duzenler) - 1)
        _duzen = (duzenler[i], varyantlar[i] if i < len(varyantlar) else "")
    return _duzen


def girdi_ortami():
    duzen, varyant = klavye_duzeni()
    env = dict(os.environ, DOTOOL_XKB_LAYOUT=duzen)
    if varyant:
        env["DOTOOL_XKB_VARIANT"] = varyant
    return env


_yazilabilir = {}


def yazilabilir_mi(c):
    """Karakter etkin klavye düzeninde yazılabilir mi (xkbcli how-to-type)?"""
    if c not in _yazilabilir:
        try:
            duzen, varyant = klavye_duzeni()
            out = subprocess.run(["xkbcli", "how-to-type", "--layout", duzen, *(["--variant", varyant] if varyant else []), c],
                                 capture_output=True, text=True).stdout
            # doğrudan tuş YA DA ölü tuş dizisi (ä = ¨ + a; dotool ikisini de yazar, ölçüldü)
            yollar_ = out.split("=== Direct access ===")[1]
            _yazilabilir[c] = any(re.match(r"\s*\d+\s+\S+", l) for l in yollar_.splitlines())
        except (OSError, IndexError):
            _yazilabilir[c] = True  # xkbcli yoksa denetleyemeyiz; dotool uyarısı yine raporlanır
    return _yazilabilir[c]


_gecerli_tuslar = None


def gecerli_tuslar():
    """dotool'un tanıdığı tuş adları (dotool --list-keys)."""
    global _gecerli_tuslar
    if _gecerli_tuslar is None:
        _gecerli_tuslar = {l.split()[0] for l in calis("dotool", "--list-keys").splitlines() if l.strip()}
    return _gecerli_tuslar


# ---------------------------------------------------------------- pencere

def ekran_alani():
    """Tüm çıkışları kapsayan dikdörtgen (x0, y0, x1, y1)."""
    out = re.sub(r"\x1b\[[0-9;]*m", "", calis("kscreen-doctor", "-o"))
    kutular = [tuple(map(int, m.groups())) for m in re.finditer(r"Geometry:\s*(-?\d+),(-?\d+)\s+(\d+)x(\d+)", out)]
    if not kutular:
        raise Dur(8, _("ekran boyutu okunamadı (kscreen-doctor)"))
    return (min(b[0] for b in kutular), min(b[1] for b in kutular),
            max(b[0] + b[2] for b in kutular), max(b[1] + b[3] for b in kutular))


def geometri(k):
    if k == EKRAN:
        x0, y0, x1, y1 = ekran_alani()
        return (x0, y0, x1 - x0, y1 - y0)
    out = kd("getwindowgeometry", k)
    p = re.search(r"Position:\s*(-?[\d.]+),(-?[\d.]+)", out)
    g = re.search(r"Geometry:\s*([\d.]+)x([\d.]+)", out)
    if not (p and g):
        raise Dur(8, _("pencere bulunamadı: {kimlik}").format(kimlik=k))
    return tuple(round(float(v)) for v in (*p.groups(), *g.groups()))


def aktif():
    """Etkin pencere kimliği; boşsa doğrulanamadı → çağıran durur (güvenli taraf). kd() kısa yeniden dener."""
    return kd("getactivewindow")


def baslik(k):
    if k == EKRAN:
        return f"EKRAN (aktif: {kd('getwindowname', aktif())})"
    return kd("getwindowname", k) if k else ""


def sinif(k):
    if k == EKRAN or not k:
        return ""
    return kd("getwindowclassname", k)


def pencere_coz(arg):
    """Kimlik ({uuid}) ya da ad deseni → tek pencere kimliği. Desen birden çok pencereye uyarsa DUR."""
    if (arg or "").lower() in EKRAN_ADLARI:
        return EKRAN
    if re.fullmatch(r"\{[0-9a-fA-F-]{36}\}", arg or ""):
        geometri(arg)  # yoksa Dur(8)
        return arg
    if not arg:
        raise Dur(8, _("pencere kimliği boş"))
    adaylar = kd("search", "--name", arg).split()
    if not adaylar:
        raise Dur(8, _("'{ad}' adlı pencere yok (ekran bul …)").format(ad=arg))
    if len(adaylar) > 1:
        liste = "\n".join(f"  {w} | {baslik(w)}" for w in adaylar)
        raise Dur(5, _("'{ad}' {sayi} pencereye uyuyor; kimlik ver:\n{liste}").format(ad=arg, sayi=len(adaylar), liste=liste))
    return adaylar[0]


def fare_coz(metin):
    m = re.search(r"x:(-?\d+)\s+y:(-?\d+).*?window:(\S+)", metin or "")
    return (int(m.group(1)), int(m.group(2)), m.group(3)) if m else (None, None, "")


def fare():
    """→ (x, y, imlecin altındaki pencere kimliği). ~1,5 ms (kd boşsa kısa yeniden dener)."""
    return fare_coz(kd("getmouselocation"))


def baslik_ve_fare(k):
    """TEK kdotool çağrısında pencere başlığı + fare (zincir): gözcünün KWin yükünü yarıya indirir."""
    out = calis("kdotool", "getwindowname", k, "getmouselocation")
    satirlar = out.splitlines()
    if satirlar and satirlar[-1].startswith("x:"):
        return "\n".join(satirlar[:-1]), fare_coz(satirlar[-1])
    return kd("getwindowname", k), fare()


def one_getir(k):
    """Pencereyi aktif et ve doğrula. Zaten aktifse beklemeden döner. Masaüstü kipinde hiçbir şeyi öne getirmez."""
    if k == EKRAN or aktif() == k:
        return
    kd("windowactivate", k)
    for _i in range(20):
        if aktif() == k:
            time.sleep(0.15)  # öne gelen pencerenin yeniden çizilmesi için
            return
        time.sleep(0.05)
    raise Dur(3, _("hedef pencere aktif olmadı (aktif: {baslik})").format(baslik=repr(baslik(aktif()))))


def ekran_goruntusu():
    d = yollar.cikti()
    os.makedirs(d, exist_ok=True)
    yol = os.path.join(d, f"tam-{os.getpid()}.png")
    if os.path.exists(yol):
        os.remove(yol)
    subprocess.run(["spectacle", "-b", "-n", "-f", "-o", yol], capture_output=True)
    im = None
    for _i in range(150):
        if os.path.exists(yol) and os.path.getsize(yol) > 0:
            try:
                im = Image.open(yol)
                im.load()
                break
            except OSError:
                pass  # dosya henüz yazılıyor
        time.sleep(0.02)
    if os.path.exists(yol):
        os.remove(yol)
    if im is None:
        raise Dur(8, _("ekran görüntüsü alınamadı (spectacle)"))
    return im.convert("RGB")


# ---------------------------------------------------------------- ön plan koruması

KORUMA_ARALIK = 0.25  # harf harf yazı/sürüklemede (ham) ekran koruması en çok bu aralıkla yeniden denetlenir


def on_plan_korumasi(ne):
    """Kullanıcının ekranına müdahaleden HEMEN önce (her gönderimde; ~2-10 ms):
    - kullanıcıya bildirimle "nerede yapılsın?" soruluyorsa (RUNTIME_DIR/karar-bekliyor) ön plan girdisi YOK (12):
      ajan "Ekranımda yap" düğmesine kendisi basamasın. --ekranimda bunu AŞMAZ.
    - kullanıcı oyunda/film izliyorsa ekranına müdahale YOK (15; --ekranimda ya da bildirimde "Ekranımda yap" ile
      serbest). Görünmez masaüstü (--arka) etkilenmez."""
    from .. import mesgul
    if mesgul.karar_bekliyor():
        raise Dur(INSAN, _("kullanıcıya nerede yapılacağı soruluyor (bildirim açık): yanıtlayana dek ekranına girdi "
                           "gönderilmez ({ne})").format(ne=ne))
    neden = mesgul.ekran_korumasi()
    if neden:
        raise Dur(KULLANICI_MESGUL, _("kullanıcı {neden}: ekranına müdahale edilmez ({ne}). Görünmez masaüstünde "
                                      "yap (--arka) ya da sonra dene; kullanıcı açıkça izin verdiyse --ekranimda"
                                      ).format(neden=neden, ne=ne))


# ---------------------------------------------------------------- girdi (dotool)

def _goreli_imlec_sayisi():
    try:
        with open("/proc/bus/input/devices") as f:
            return f.read().count('Name="dotool relative pointer"')
    except OSError:
        return 0


class Girdi:
    """dotool'u en başta arka planda açar. ~0,66 sn'lik kurulum süresi görüntü alma/OCR ile örtüşür.

    gonder(): her gönderimden HEMEN önce hata.dur_denetle() + denetle(k, desen) (üst katmanın güvenlik denetimi)
    + insan önceliği. zorla(): bırakma satırları, hiçbir denetim yok. ham(): yalnız DUR anahtarı + gözcü bayrağı
    (harf harf yazı ve sürükleme için; pencere/başlık denetimini gözcü yapar)."""

    def __init__(self, au, etiket="", gizli=False, etk=None, denetle=None):
        if denetle is None:  # güvenlik denetimi ASLA atlanmasın: verilmediyse üst katmanınki
            from ..guvenlik import denetle
        self.au = au
        self.denetle = denetle
        self.etk_sahibi = etk is None and not INSAN_TAKLIDI
        self.etk = None if INSAN_TAKLIDI else (etk or Etkinlik())
        self.taban = _goreli_imlec_sayisi()
        self.t0 = time.monotonic()
        self.p = subprocess.Popen(["dotool"], stdin=subprocess.PIPE, stderr=subprocess.PIPE, env=girdi_ortami(),
                                  text=True)
        self.hazir = False
        self.hazir_an = None
        self.uyarilar = []
        self.etiket, self.gizli = etiket, gizli
        self.kesildi = None
        self.son_etk = self.t0
        self.fare0 = au.fare()[:2]  # dotool kurulurken kullanıcı fareyi oynatırsa anlarız
        self.son_fare = self.fare0  # fareyi en son NEREYE biz bıraktık (dizi adımları arası insan denetimi)
        threading.Thread(target=self._izle, daemon=True).start()

    def _izle(self):  # OCR sürerken aygıtın görünme anını yakalar
        while time.monotonic() - self.t0 < DOTOOL_AZAMI and self.p.poll() is None:
            if _goreli_imlec_sayisi() > self.taban:
                self.hazir_an = time.monotonic() + DOTOOL_SON_UYKU
                return
            time.sleep(0.01)

    def _hazirla(self):
        if self.hazir:
            return
        while self.hazir_an is None and self.p.poll() is None and time.monotonic() - self.t0 < DOTOOL_AZAMI:
            time.sleep(0.01)
        kalan = (self.hazir_an or self.t0 + 1.0) - time.monotonic()
        if kalan > 0:
            time.sleep(kalan)
        if self.p.poll() is not None:
            hata = self.p.stderr.read().strip()
            raise Dur(9, _("dotool çalışmadı: {hata} (uinput yüklü mü? `sudo modprobe uinput`)").format(hata=hata))
        insan_bekle(self.fare0, self.au.fare)
        klavye_bekle(self.etk, self.t0)  # kurulum süresince (≈0,65 sn) klavye/fare kullanıldıysa sessizliği bekle
        self.son_etk = time.monotonic()
        self.hazir = True

    def etk_denetle(self, ne=None):
        """Son denetimden bu yana insan klavye/fare kullandıysa DUR 12 (komut ortası: beklemeden durur).
        ne: çevrilmiş ek (varsayılan "girdi gönderilmedi")."""
        if self.etk is not None and self.etk.insan(self.son_etk):
            raise Dur(12, _("kullanıcı klavye/fare kullandı (insan önceliği); {ne}").format(
                ne=ne or _("girdi gönderilmedi")))
        self.son_etk = time.monotonic()

    def _kaydet(self, bas, satirlar):
        if self.etk is not None:
            self.etk.kendi_girdi(bas, time.monotonic() + girdi_suresi(satirlar))
            self.son_etk = time.monotonic()

    def izle(self, k, desen):
        """Yazı GÖZCÜSÜ (~10 ms): etkin pencere, başlık (sekme) ve FARE. Değişince bayrak kalkar, yazı bir
        sonraki HARFTEN önce durur. dotool ÖLDÜRÜLMEZ (yarım kalan tuş basılı kalabilir). Neden (ölçüm):
        kelime ortasında sekme değişince kalanı yeni sekmeye sızıyordu (8'de 3, 2-5 harf); harf harf + gözcü →
        10'da 1, 1 harf. Fare kıpırdarsa = insan bilgisayarı kullanıyor → dur (insan önceliği)."""
        self.kesildi = None
        self._izle_dur = threading.Event()
        f0 = fare()[:2]

        def dongu():
            # döngü başına en çok 2 kdotool çağrısı, ~10 ms aralık (3 çağrı/4 ms KWin'i aşırı yüklüyor,
            # başka süreçlerin sorguları boş dönüyordu)
            while not self._izle_dur.is_set():
                a = aktif()
                neden = None
                if desen:
                    b, f = baslik_ve_fare(k)
                else:
                    b, f = None, fare()
                f = f[:2]
                if a != k:
                    neden = (3, _("aktif pencere değişti → {baslik}").format(baslik=repr(baslik(a))))
                elif desen and not re.search(desen, b or kd("getwindowname", k), re.I):
                    neden = (4, _("başlık değişti: {baslik} (beklenen /{desen}/)").format(baslik=repr(baslik(k)), desen=desen))
                elif f[0] is not None and f0[0] is not None and f != f0:
                    neden = (12, _("kullanıcı fareyi oynattı (insan önceliği)"))
                if neden:
                    self.kesildi = Dur(*neden)
                    return
                time.sleep(0.008)

        self._izleyici = threading.Thread(target=dongu, daemon=True)
        self._izleyici.start()

    def izle_bitir(self):
        if getattr(self, "_izleyici", None):
            self._izle_dur.set()
            self._izleyici.join()

    def zorla(self, satir):
        """BIRAKMA (keyup/buttonup) için: hiçbir denetim yok, kesinti (DUR dahil) olsa bile gönderilir
        (takılı tuş kalmasın)."""
        try:
            t = time.monotonic()
            self.p.stdin.write(satir + "\n")
            self.p.stdin.flush()
            self._kaydet(t, [satir])
            gunluk(f"{self.etiket} | bırak | {satir}")
        except (BrokenPipeError, OSError):
            pass

    def insan_kontrol(self):
        """dizi adımları arası: fare en son bizim bıraktığımız yerde değilse ya da arada klavye/fare kullanıldıysa
        insan kullanıyor → durgunluğu bekle (en çok 8 sn) / DUR."""
        f = self.au.fare()[:2]
        if f[0] is not None and self.son_fare[0] is not None and \
                (abs(f[0] - self.son_fare[0]) > 2 or abs(f[1] - self.son_fare[1]) > 2):
            insan_bekle(self.son_fare, self.au.fare)
            self.son_fare = self.au.fare()[:2]
        if self.hazir:
            klavye_bekle(self.etk, self.son_etk)
            self.son_etk = time.monotonic()

    def koruma_denetle(self, her_zaman=True):
        """Ön plan koruması (on_plan_korumasi): gonder'de her seferinde, ham'da KORUMA_ARALIK'ta bir (dizi/akış
        ortasında kullanıcı film açarsa ya da karar bildirimi gelirse durur)."""
        simdi = time.monotonic()
        if her_zaman or simdi - getattr(self, "_son_koruma", 0.0) >= KORUMA_ARALIK:
            on_plan_korumasi(_("girdi"))
            self._son_koruma = time.monotonic()

    def ham(self, satir):
        """Pencere denetimsiz tek satır (harf harf yazı, sürükleme; denetimi gözcü yapar). DUR anahtarı yine
        denetlenir (~2 µs); ön plan koruması KORUMA_ARALIK'ta bir."""
        if self.kesildi:
            raise self.kesildi
        dur_denetle()
        self.koruma_denetle(her_zaman=False)
        try:
            t = time.monotonic()
            self.p.stdin.write(satir + "\n")
            self.p.stdin.flush()
            self._kaydet(t, [satir])
        except (BrokenPipeError, OSError):
            raise Dur(9, _("dotool beklenmedik şekilde kapandı"))

    def gonder(self, k, desen, *satirlar):
        self._hazirla()
        if getattr(self, "kesildi", None):
            raise self.kesildi
        dur_denetle()
        self.denetle(k, desen)
        self.koruma_denetle()  # her gönderimde: dizi/akış ortasında kullanıcı film/oyun açtıysa dur (15)
        self.etk_denetle()
        try:
            t = time.monotonic()
            self.p.stdin.write("".join(s + "\n" for s in satirlar))
            self.p.stdin.flush()
            self._kaydet(t, satirlar)
        except (BrokenPipeError, OSError):
            raise getattr(self, "kesildi", None) or Dur(9, _("dotool beklenmedik şekilde kapandı"))
        kayit = [f"type ***({len(s) - 5})" if self.gizli and s.startswith("type ") else s for s in satirlar]
        gunluk(f"{self.etiket} | [{self.au.baslik(k)}] | {' ; '.join(kayit)}")

    def kapat(self):
        if self.etk_sahibi and self.etk is not None:
            self.etk.kapat()
        if not self.hazir:  # hiç girdi gönderilmedi (hata/DUR): kurulumu bekleme
            self.p.kill()
            self.p.wait()
            return
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.p.kill()
        self.uyarilar = [l for l in self.p.stderr.read().splitlines() if l.strip()]
        for l in self.uyarilar:
            print(f"UYARI {l}", file=sys.stderr)


# ---------------------------------------------------------------- arka uç

class KdeArkaUc(ArkaUc):
    ad = "kde"

    # -------- pencere
    def pencere_coz(self, arg):
        return pencere_coz(arg)

    def kimlikler(self):
        """Tüm pencere kimlikleri (ucuz: 2 kdotool çağrısı; başlık/geometri sorgulanmaz)."""
        return set(kd("search", "--name", ".").split()) | set(kd("search", "--class", ".").split())

    def pencereler(self, desen=None):
        kimlikler = kd("search", "--name", desen).split() if desen is not None else sorted(self.kimlikler())
        sonuc = []
        for w in kimlikler:
            try:
                b = baslik(w)
                sonuc.append((w, b, geometri(w)))
            except Dur:
                pass  # listelenirken kapanan pencere
        return sonuc

    def geometri(self, k):
        return geometri(k)

    def baslik(self, k):
        return baslik(k)

    def sinif(self, k):
        return sinif(k)

    def pid(self, k):
        return kd("getwindowpid", k) if k and k != EKRAN else ""

    def aktif(self):
        return aktif()

    def _ekran_korumasi(self, ne):
        """Kullanıcı oyunda/film izliyorsa (15) ya da karar bildirimi açıksa (12) ekranına müdahale YOK."""
        on_plan_korumasi(ne)

    def one_getir(self, k):
        if k != EKRAN and aktif() != k:
            self._ekran_korumasi(_("pencere öne getirme"))
        one_getir(k)

    def etkinlestir(self, k):
        """Doğrulamasız öne getirme (okuma bitince önceki pencereyi geri vermek için)."""
        if k and k != EKRAN:
            kd("windowactivate", k)

    def kapat(self, k):
        self._ekran_korumasi(_("pencere kapatma"))  # film izlerken oynatıcı penceresi kapatılmasın
        kd("windowclose", k)

    # -------- fare / ekran
    def fare(self):
        return fare()

    def baslik_ve_fare(self, k):
        return baslik_ve_fare(k)

    def ekran_alani(self):
        return ekran_alani()

    def goruntu(self):
        return ekran_goruntusu()

    # -------- klavye
    def klavye_duzeni(self):
        return klavye_duzeni()

    def yazilabilir_mi(self, c):
        return yazilabilir_mi(c)

    def gecerli_tuslar(self):
        return gecerli_tuslar()

    # -------- girdi
    def girdi(self, etiket="", gizli=False, etk=None, denetle=None):
        self._ekran_korumasi(_("girdi"))
        return Girdi(self, etiket, gizli, etk, denetle)

    def etkinlik(self):
        """İnsan önceliği izleyicisi (Wayland boşta bildirimi); testlerde insan taklidinde None."""
        return None if INSAN_TAKLIDI else Etkinlik()

    def insan_var_mi(self):
        """Şu an klavye/fare kullanılıyor mu? (~0,3 sn: yardımcı açılır, kısa süre dinlenir)"""
        e = Etkinlik()
        try:
            if not e.calisiyor():
                return False
            beri = time.monotonic()
            time.sleep(0.2)
            return e.insan(beri)
        finally:
            e.kapat()

    # -------- uygulama
    def baslat(self, argv, env=None, cikti=None):
        """Kullanıcının oturumunda, ayrı oturum grubunda (araç kapanınca uygulama yaşar). cikti: açık dosya
        (stdout+stderr), yoksa /dev/null. env: os.environ'a EKLENECEK/değişecek değişkenler (CHANGE 4)."""
        self._ekran_korumasi(_("uygulama açma"))
        hedef = cikti if cikti is not None else subprocess.DEVNULL
        tam = dict(os.environ, **env) if env else None
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=hedef, stderr=hedef, env=tam,
                                start_new_session=True)
