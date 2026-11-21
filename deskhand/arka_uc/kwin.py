"""KWin arka ucu: arka plan masaüstünün KWin türü (yalıtık `kwin_wayland --virtual` oturumu, deskhand/kwin_oturum.py).

Dışarıdan sanal (Xvfb) arka uçla AYNIDIR: `ad = "sanal"`, pencere kimlikleri `arka:` önekli (`arka:{uuid}`), aynı
çıkış kodları, aynı Girdi sözleşmesi (docs/ARCHITECTURE.md §2). Hangisinin kullanılacağına arka_uc.sec() durum
kaydının türüne (masaustu.durum()["tur"]) bakarak karar verir; tür `self.tur` ile okunur.

Araçlar (hepsi YALNIZ oturumun özel veri yolu / Wayland soketiyle; kullanıcının gerçek oturumuna bağlanmaz):
  pencere   kdotool (özel veri yolu: kwin_oturum.kdotool_ortami; okuma sorguları boş dönerse kısa yeniden dener)
  görüntü   yardimci/deskhand-goruntu (KWin ScreenShot2, özel adres; ~2 ms)
  girdi     yardimci/deskhand-eis (KWin EIS / libei; KALICI bağlantı, süreç başına bir tane, kilitli paylaşılır)
  pano      wl-copy / wl-paste (oturumun Wayland soketi; wl-copy'nin sunucu çocuğu masaüstünün kafesinde yaşar)
Her bağlantıdan önce kwin_oturum.baglanti_denetle(d): veri yolu adresi kullanıcının gerçek adresi, Wayland soketi
kullanıcının soketi DEĞİL, ikisi de oturumun çalışma dizininde (yoksa Dur 14).

EIS kopması: yardımcı süreç ölürse (KWin yeniden başladı, çökme) basılı FARE DÜĞMESİ KWin'de takılı kalabilir (KWin
6.8 ölçümü: tuşları bırakıyor, düğmeyi bırakmıyor) → arka uç bunu kendiliğinden yeni bağlantıdan `click` ile kurtarır
(Eis.kurtar), sonra Dur(9) verir; sonraki çağrı yeni bağlantı açar.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import time

from .. import hata, kwin_oturum, masaustu
from ..hata import (AKTIF_DEGIL, ARAC_EKSIK, BASLIK_SINIF, BELIRSIZ, INSAN, KULLANICI_DUR, PENCERE_YOK,
                    SANAL_KAPALI, Dur)
from ..i18n import _
from . import ARKA_ONEK, EKRAN, ArkaUc

EKRAN_ADLARI = {"ekran", "masaustu", "masaüstü", "tum-ekran", "tüm-ekran"}
UUID = re.compile(r"\{[0-9a-fA-F-]{36}\}")
DEVRAL_BEKLE = 8.0  # sanal arka uçla aynı: Devral açıkken ilk girdiden önce en çok bu kadar beklenir, sonra 12
KD_ZAMAN = 10.0
_KD_OKUMA = {"search", "getactivewindow", "getwindowgeometry", "getwindowname", "getwindowclassname",
             "getmouselocation", "getwindowpid"}
PANO_ZAMAN = 5.0
PANO_AZAMI = 32 * 1024 * 1024
GOZCU_ARALIK = 0.012  # yazı gözcüsü yoklama aralığı (her yoklama tek kdotool çağrısı)


def kimlik_yap(uuid: str) -> str:
    return f"{ARKA_ONEK}{uuid}"


def kimlik_coz(k: str) -> str:
    """`arka:{uuid}` → `{uuid}` (kdotool kimliği). Başka biçim → Dur 8."""
    if not isinstance(k, str) or not k.startswith(ARKA_ONEK):
        raise Dur(PENCERE_YOK, _("bu kimlik arka plan masaüstüne ait değil: {kimlik} (kimlikler '{onek}{{…}}')").format(
            kimlik=repr(k), onek=ARKA_ONEK))
    u = k[len(ARKA_ONEK):]
    if not UUID.fullmatch(u):
        raise Dur(PENCERE_YOK, _("geçersiz arka plan pencere kimliği: {kimlik}").format(kimlik=repr(k)))
    return u


def _fare_coz(metin: str) -> tuple[int | None, int | None, str]:
    m = re.search(r"x:(-?\d+)\s+y:(-?\d+)", metin or "")
    if not m:
        return None, None, ""
    w = re.search(r"window:(\{[0-9a-fA-F-]{36}\})", metin)
    return int(m.group(1)), int(m.group(2)), (kimlik_yap(w.group(1)) if w else "")


class KwinArkaUc(ArkaUc):
    ad = "sanal"   # dış dünya için: arka plan masaüstü (Xvfb türüyle aynı ad, aynı üst katman kuralları)
    tur = "kwin"
    pano_bekle = 0.2

    def __init__(self):
        self._kilit = threading.RLock()   # paylaşılan EIS bağlantısı
        self._eis = None
        self._eis_imza = None
        self._yazilabilir: dict[str, bool] = {}
        self._yazilabilir_imza = None

    # -------- oturum + kapı
    def _d(self) -> dict:
        """Çalışan KWin oturumunun kaydı (PID + soket doğrulamalı) + bağlantı kapısı. Kapalı / başka tür → Dur 14."""
        d = masaustu.durum(saglik=False)
        if d is None or masaustu.tur(d) != "kwin":
            raise Dur(SANAL_KAPALI, _("sanal masaüstü kapalı (deskhand masaustu baslat)"))
        kwin_oturum.baglanti_denetle(d)
        return d

    def ekran_adi(self) -> str:
        return self._d()["ekran"]

    def _kd(self, *a, d: dict | None = None) -> str:
        """kdotool, oturumun özel veri yolunda. Okuma sorguları boş dönerse 3 kez kısa yeniden dener (kdotool her
        çağrıda KWin betiği yükler; eşzamanlı çağrılarda bazen boş döner). Eylemler yeniden denenmez."""
        d = d or self._d()
        env = kwin_oturum.kdotool_ortami(d)
        for deneme in range(4):
            try:
                r = subprocess.run(["kdotool", *a], capture_output=True, text=True, env=env, timeout=KD_ZAMAN,
                                   stdin=subprocess.DEVNULL)
            except FileNotFoundError:
                raise Dur(ARAC_EKSIK, _("kdotool yok"))
            except subprocess.TimeoutExpired:
                raise Dur(hata.ZAMAN_ASIMI, _("kdotool {sn} sn içinde yanıt vermedi").format(sn=f"{KD_ZAMAN:.0f}"))
            out = r.stdout.strip()
            if out or not a or a[0] not in _KD_OKUMA:
                return out
            time.sleep(0.005 * (deneme + 1))
        return ""

    # -------- pencere
    def kimlikler(self) -> list[str]:
        d = self._d()
        u = set(self._kd("search", "--name", ".", d=d).split()) | set(self._kd("search", "--class", ".", d=d).split())
        return sorted(kimlik_yap(x) for x in u if UUID.fullmatch(x))

    def _geo_coz(self, out: str) -> tuple[int, int, int, int] | None:
        p = re.search(r"Position:\s*(-?[\d.]+),(-?[\d.]+)", out)
        s = re.search(r"Geometry:\s*([\d.]+)x([\d.]+)", out)
        if not (p and s):
            return None
        return tuple(round(float(v)) for v in (*p.groups(), *s.groups()))

    def pencereler(self, desen: str | None = None):
        try:
            rx = re.compile(desen, re.I) if desen else None
        except re.error:
            rx = re.compile(re.escape(desen), re.I)
        d = self._d()
        sonuc = []
        for k in self.kimlikler():
            u = kimlik_coz(k)
            out = self._kd("getwindowname", u, "getwindowgeometry", u, d=d)
            satirlar = out.splitlines()
            geo = self._geo_coz(out)
            if geo is None:
                continue  # listelenirken kapanan pencere
            # chain çıktısı: ilk satır başlık, sonra "Window …", "Position", "Geometry"
            b = satirlar[0] if satirlar and not satirlar[0].startswith(("Window ", "  Position")) else ""
            if rx is not None and not rx.search(b):
                continue
            sonuc.append((k, b, geo))
        return sonuc

    def pencere_coz(self, arg: str) -> str:
        if (arg or "").lower() in EKRAN_ADLARI or arg == EKRAN:
            return EKRAN
        if not arg:
            raise Dur(PENCERE_YOK, _("pencere kimliği boş"))
        if arg.startswith(ARKA_ONEK) or UUID.fullmatch(arg):
            k = arg if arg.startswith(ARKA_ONEK) else ARKA_ONEK + arg
            self.geometri(k)  # yoksa Dur(8)
            return k
        adaylar = self.pencereler(arg)
        if not adaylar:
            raise Dur(PENCERE_YOK, _("'{ad}' adlı pencere yok (sanal masaüstü; deskhand --arka bul …)").format(ad=arg))
        if len(adaylar) > 1:
            liste = "\n".join(f"  {k} | {b}" for k, b, _g in adaylar)
            raise Dur(BELIRSIZ, _("'{ad}' {sayi} pencereye uyuyor; kimlik ver:\n{liste}").format(
                ad=arg, sayi=len(adaylar), liste=liste))
        return adaylar[0][0]

    def geometri(self, k: str) -> tuple[int, int, int, int]:
        if k == EKRAN:
            x0, y0, x1, y1 = self.ekran_alani()
            return (x0, y0, x1 - x0, y1 - y0)
        geo = self._geo_coz(self._kd("getwindowgeometry", kimlik_coz(k)))
        if geo is None:
            raise Dur(PENCERE_YOK, _("pencere bulunamadı: {kimlik}").format(kimlik=k))
        return geo

    def baslik(self, k: str) -> str:
        if k == EKRAN:
            a = self.aktif()
            return f"EKRAN (aktif: {self.baslik(a) if a else ''})"
        if not k:
            return ""
        return self._kd("getwindowname", kimlik_coz(k))

    def sinif(self, k: str) -> str:
        if not k or k == EKRAN:
            return ""
        return self._kd("getwindowclassname", kimlik_coz(k)).lower()

    def pid(self, k: str) -> int | None:
        if not k or k == EKRAN:
            return None
        out = self._kd("getwindowpid", kimlik_coz(k))
        return int(out) if out.isdigit() else None

    def aktif(self) -> str:
        out = self._kd("getactivewindow")
        return kimlik_yap(out) if UUID.fullmatch(out) else ""

    def one_getir(self, k: str) -> None:
        if k == EKRAN or self.aktif() == k:
            return
        u = kimlik_coz(k)
        self.geometri(k)  # yoksa Dur 8
        self._kd("windowactivate", u)
        for _i in range(40):
            if self.aktif() == k:
                time.sleep(0.05)  # öne gelen pencere yeniden çizilsin
                return
            time.sleep(0.025)
        a = self.aktif()
        raise Dur(AKTIF_DEGIL, _("hedef pencere aktif olmadı (aktif: {baslik})").format(
            baslik=repr(self.baslik(a) if a else "")))

    def etkinlestir(self, k: str) -> None:
        if k and k != EKRAN:
            try:
                self._kd("windowactivate", kimlik_coz(k))
            except Dur:
                pass

    def kapat(self, k: str) -> None:
        if k == EKRAN:
            raise Dur(PENCERE_YOK, _("masaüstü kipi kapatılamaz"))
        self.geometri(k)
        self._kd("windowclose", kimlik_coz(k))

    # -------- pencere yönetimi (kdotool; denetimler üst katmanda: eylem.pencere_yonet)
    def _pencere_eylemi(self, k: str, *kd_args) -> None:
        if k == EKRAN:
            raise Dur(PENCERE_YOK, _("masaüstü kipi taşınamaz/boyutlandırılamaz; pencere kimliği/adı ver"))
        self.geometri(k)  # yoksa Dur 8
        self._kd(*kd_args)

    def tasi(self, k: str, x: int, y: int) -> None:
        self._pencere_eylemi(k, "windowmove", kimlik_coz(k), str(int(x)), str(int(y)))

    def boyutlandir(self, k: str, g: int, y: int) -> None:
        self._pencere_eylemi(k, "windowsize", kimlik_coz(k), str(int(g)), str(int(y)))

    def kucult(self, k: str) -> None:
        self._pencere_eylemi(k, "windowminimize", kimlik_coz(k))

    def buyut(self, k: str) -> None:
        self._pencere_eylemi(k, "windowstate", "--add", "MAXIMIZED", kimlik_coz(k))

    def geri_yukle(self, k: str) -> None:
        self._pencere_eylemi(k, "windowstate", "--remove", "MINIMIZED", "--remove", "MAXIMIZED", kimlik_coz(k))

    # -------- fare / ekran
    def fare(self):
        return _fare_coz(self._kd("getmouselocation"))

    def baslik_ve_fare(self, k: str):
        if k == EKRAN or not k:
            return self.baslik(k), self.fare()
        out = self._kd("getwindowname", kimlik_coz(k), "getmouselocation")
        satirlar = out.splitlines()
        if satirlar and satirlar[-1].startswith("x:"):
            return "\n".join(satirlar[:-1]), _fare_coz(satirlar[-1])
        return self.baslik(k), self.fare()

    def ekran_alani(self) -> tuple[int, int, int, int]:
        g, y = self._d()["boyut"][:2]
        return (0, 0, int(g), int(y))

    def goruntu(self):
        return kwin_oturum.goruntu(self._d())

    # -------- girdi
    def _eis_al(self):
        """Paylaşılan kalıcı EIS bağlantısı (kilit tutularak çağrılır). Oturum değiştiyse yenisi; yardımcı öldüyse
        önce basılı düğme kurtarması (Eis.kurtar), sonra yeni bağlantı."""
        d = self._d()
        imza = (d["kimlik"], d.get("baslangic"))
        e = self._eis
        if e is not None and (self._eis_imza != imza or e.p.poll() is not None):
            if self._eis_imza == imza and e.p.poll() is not None:
                try:
                    e.kurtar()
                except Exception:  # noqa: BLE001 - kurtarma en iyi çaba
                    pass
            try:
                e.kapat()
            except Exception:  # noqa: BLE001
                pass
            self._eis = e = None
        if e is None:
            self._eis = e = kwin_oturum.Eis(d)
            self._eis_imza = imza
        return e

    def eis_satir(self, satir: str) -> str:
        """Tek satırı paylaşılan EIS bağlantısına gönder. Yardımcı bu sırada öldüyse: basılı düğmeler kendiliğinden
        kurtarılır (yeni bağlantıdan click), Dur(9)."""
        with self._kilit:
            e = self._eis_al()
            try:
                return e.satir(satir)
            except kwin_oturum.EisHatasi:
                raise
            except Dur as h:
                if e.p.poll() is None:
                    raise
                try:
                    kurtarilan = e.kurtar()
                except Exception:  # noqa: BLE001
                    kurtarilan = []
                try:
                    e.kapat()
                except Exception:  # noqa: BLE001
                    pass
                self._eis = None
                raise Dur(ARAC_EKSIK, _("girdi yardımcısı koptu ({hata}); basılı düğmeler bırakıldı: {liste}").format(
                    hata=h.mesaj, liste=", ".join(kurtarilan) or "-"))

    def girdi(self, etiket: str = "", gizli: bool = False, etk=None, denetle=None):
        return KwinGirdi(self, etiket, gizli, etk, denetle)

    def insan_var_mi(self) -> bool:
        return masaustu.devral_var()

    def etkinlik(self):
        from .sanal import _DevralEtkinlik
        return _DevralEtkinlik()

    # -------- klavye
    def klavye_duzeni(self) -> tuple[str, str]:
        dz = self._d().get("duzen") or ["tr", ""]
        return (dz[0], dz[1] if len(dz) > 1 else "")

    def yazilabilir_mi(self, c: str) -> bool:
        """Oturumun klavye haritasında (EIS'in verdiği xkb haritası) doğrudan yazılabilir mi; girdi GÖNDERMEZ."""
        if c in "\n\t":
            return True
        d = self._d()
        imza = (d["kimlik"], d.get("baslangic"))
        if imza != self._yazilabilir_imza:
            self._yazilabilir, self._yazilabilir_imza = {}, imza
        if c not in self._yazilabilir:
            with self._kilit:
                y = self._eis_al().satir("yazilabilir " + c)
            self._yazilabilir[c] = not y.startswith("yazilamaz")
        return self._yazilabilir[c]

    def gecerli_tuslar(self) -> set[str]:
        from .sanal import DEGISTIRICI, linux_tuslari
        return set(linux_tuslari()) | set(DEGISTIRICI)

    # -------- uygulama
    def baslat(self, argv: list[str], env: dict | None = None, cikti=None):
        """Arka plan masaüstünde (kafes + oturum ortamı: Wayland yerel, X11 isteyenler oturumun XWayland'ine)."""
        if cikti is not None:
            return masaustu.baslat(argv, env, stdout=cikti, stderr=cikti)
        return masaustu.baslat(argv, env)

    def oturum_veri_yolu(self) -> str | None:
        return self._d().get("dbus_adres") or None

    def atspi_adresi(self) -> str | None:
        d = self._d()
        return d.get("a11y_adres") or kwin_oturum.atspi_adresi(d)

    # -------- pano (wl-clipboard, oturumun Wayland soketiyle; docs/ARCHITECTURE.md §2). Kullanıcının GERÇEK panosuna
    # dokunmaz: WAYLAND_DISPLAY oturumun MUTLAK soket yolu, ortam asgari (kullanıcının değişkenleri yok).
    def _wl_ortami(self, d: dict) -> dict:
        return {"PATH": kwin_oturum.ASGARI_PATH, "WAYLAND_DISPLAY": d["wayland_yol"], "XDG_RUNTIME_DIR": d["calisma"],
                "HOME": os.path.join(d["calisma"], "ev"), "LANG": os.environ.get("LANG") or "C.UTF-8"}

    def _wl(self, argv: list[str], girdi: bytes | None = None, kafes: bool = False):
        """wl-copy/wl-paste → (çıkış kodu, stdout bayt, stderr metin). wl-copy çatallanıp sunmaya devam eder: çıktılar
        geçici dosyaya (boru olursa bekleme asılır); kafes=True: wl-copy masaüstünün bellek kafesinde başlar (sunucu
        çocuğu da orada yaşar, masaüstü kapanınca kapanır)."""
        d = self._d()
        env = self._wl_ortami(d)
        with tempfile.TemporaryFile() as cikti, tempfile.TemporaryFile() as hata_:
            try:
                std = dict(stdin=subprocess.PIPE if girdi is not None else subprocess.DEVNULL, stdout=cikti,
                           stderr=hata_)
                if kafes:
                    from .. import arka_ortak
                    p = arka_ortak.kafeste_baslat(d, argv, env, **std)
                else:
                    p = subprocess.Popen(argv, env=env, start_new_session=True, **std)
            except FileNotFoundError:
                raise Dur(ARAC_EKSIK, _("{arac} yok (wl-clipboard paketi)").format(arac=argv[0])) from None
            try:
                if girdi is not None:
                    try:
                        p.stdin.write(girdi)
                        p.stdin.close()
                    except (BrokenPipeError, OSError):
                        pass
                p.wait(timeout=PANO_ZAMAN)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
                raise Dur(hata.ZAMAN_ASIMI, _("{arac} {sn} sn içinde bitmedi").format(
                    arac=argv[0], sn=f"{PANO_ZAMAN:.0f}")) from None
            cikti.seek(0)
            veri = cikti.read(PANO_AZAMI + 1)
            hata_.seek(0)
            return p.returncode, veri, hata_.read(400).decode(errors="replace").strip()

    def _pano_turleri(self) -> list[str]:
        kod, veri, _e = self._wl(["wl-paste", "--list-types"])
        if kod != 0:
            return []
        return [t.strip() for t in veri.decode(errors="replace").splitlines() if t.strip()]

    def _pano_yaz_ham(self, metin, tur: str = "text/plain;charset=utf-8") -> None:
        if isinstance(metin, str) and not metin:
            argv, girdi = ["wl-copy", "--clear"], None
        else:
            argv, girdi = ["wl-copy", "--type", tur], (metin.encode() if isinstance(metin, str) else metin)
        kod, _o, hata_ = self._wl(argv, girdi, kafes=True)
        if kod != 0:
            raise Dur(ARAC_EKSIK, _("wl-copy başarısız ({kod}): {hata}").format(kod=kod, hata=hata_ or _("ayrıntı yok")))

    def pano_oku(self) -> str | None:
        from .kde import _metin_turu
        tur = _metin_turu(self._pano_turleri())
        if tur is None:
            return None
        kod, veri, _e = self._wl(["wl-paste", "--no-newline", "--type", tur])
        return veri.decode(errors="replace") if kod == 0 else None

    def pano_yaz(self, metin: str, hassas: bool = True) -> None:
        """hassas: oturumda pano yöneticisi (Klipper) yok, yok sayılır."""
        hata.dur_denetle()
        self._pano_yaz_ham(metin)

    def pano_yedekle(self):
        from .kde import PANO_SAHTE_TURLER, _metin_turu
        turler = self._pano_turleri()
        if not turler:
            return {"bos": True}
        tur = _metin_turu(turler)
        metin = tur is not None
        if tur is None:
            tur = next((t for t in turler if t not in PANO_SAHTE_TURLER), None)
            if tur is None:
                return {"bos": True}
        kod, veri, _e = self._wl(["wl-paste", "--no-newline", "--type", tur])
        if kod != 0:
            return {"bos": True}
        if len(veri) > PANO_AZAMI:
            return {"buyuk": True, "tur": tur}
        return {"tur": tur, "veri": veri, "metin": metin}

    def pano_geri_yukle(self, yedek) -> str | None:
        if yedek.get("buyuk"):
            return _("eski pano içeriği ({tur}) çok büyük olduğu için geri yüklenemedi").format(tur=yedek.get("tur"))
        try:
            if yedek.get("bos"):
                self._pano_yaz_ham("")
            else:
                self._pano_yaz_ham(yedek["veri"], yedek["tur"])
        except Dur as e:
            return _("eski pano içeriği geri yüklenemedi: {hata}").format(hata=e.mesaj)
        if not yedek.get("bos") and not yedek.get("metin"):
            return _("eski pano içeriği metin değildi; birincil türü ({tur}) geri yüklendi, diğer biçimler kaybolmuş "
                     "olabilir").format(tur=yedek["tur"])
        return None


# ---------------------------------------------------------------- girdi

class KwinGirdi:
    """Girdi sözleşmesi (gonder/zorla/ham/insan_ham/izle/izle_bitir/etk_denetle/insan_kontrol/kapat), paylaşılan kalıcı
    EIS bağlantısı üzerinden. Denetim sırası sanal (Xvfb) Girdi ile AYNI: hazırla (Devral) → DUR → denetle(k, desen) +
    uygulama erişim seviyesi → Devral, sonra satırlar. Bir gonder() çağrısının satırları ATOMİKTİR. Bu nesnenin
    bastığı tuş/düğmeler izlenir; herhangi bir Dur'da, gözcü DUR'u görünce ve kapat()'ta bırakılır."""

    devral_bekle = DEVRAL_BEKLE

    def __init__(self, arka: KwinArkaUc, etiket: str = "", gizli: bool = False, etk=None, denetle=None):
        from .sanal import _DevralEtkinlik
        self.arka = arka
        self.etiket, self.gizli = etiket, gizli
        self.denetle = denetle
        self.etk = _DevralEtkinlik()
        self.etk_sahibi = False
        self.ekran = arka.ekran_adi()  # Dur 14: masaüstü kapalı
        with arka._kilit:
            arka._eis_al()  # bağlantı hazır (ilk kez ~0,17 sn; sonra paylaşılır)
        self.t0 = time.monotonic()
        self.hazir = False
        self.hazir_an = self.t0
        self.uyarilar: list[str] = []
        self.kesildi = None
        self.son_etk = self.t0
        self.fare0 = arka.fare()[:2]
        self.son_fare = self.fare0
        self._basili_tus: list[str] = []
        self._basili_dugme: list[str] = []
        self._b_kilit = threading.Lock()
        self._izleyici = None
        self._izle_dur = threading.Event()

    # -------- satırlar
    def _izle_satir(self, satir: str) -> None:
        k, _a, arg = satir.strip().partition(" ")
        k, arg = k.lower(), arg.strip()
        with self._b_kilit:
            if k == "keydown":
                for t in re.split(r"[\s+]+", arg):
                    if t and t not in self._basili_tus:
                        self._basili_tus.append(t)
            elif k == "keyup":
                for t in re.split(r"[\s+]+", arg):
                    if t in self._basili_tus:
                        self._basili_tus.remove(t)
            elif k == "buttondown":
                if arg.lower() not in self._basili_dugme:
                    self._basili_dugme.append(arg.lower())
            elif k == "buttonup":
                if arg.lower() in self._basili_dugme:
                    self._basili_dugme.remove(arg.lower())

    def _calistir(self, satir: str) -> None:
        s = satir.rstrip("\n")
        if not s.strip():
            return
        k = s.strip().split(" ", 1)[0].lower()
        if k in ("keydown", "buttondown"):
            self._izle_satir(s)  # gönderimden ÖNCE: yarım kalsa bile bırakılsın
        self.arka.eis_satir(s)
        if k in ("keyup", "buttonup"):
            self._izle_satir(s)

    def _hepsini_birak(self) -> None:
        with self._b_kilit:
            tuslar, dugmeler = list(self._basili_tus), list(self._basili_dugme)
            self._basili_tus.clear()
            self._basili_dugme.clear()
        for t in reversed(tuslar):
            try:
                self.arka.eis_satir(f"keyup {t}")
            except Exception:  # noqa: BLE001 - bırakma en iyi çaba
                pass
        for b in reversed(dugmeler):
            try:
                self.arka.eis_satir(f"buttonup {b}")
            except Exception:  # noqa: BLE001
                pass

    # -------- insan önceliği (arka planda: Devral bayrağı)
    def _devral_bekle(self, ne: str) -> None:
        if not masaustu.devral_var():
            return
        bitis = time.monotonic() + self.devral_bekle
        while time.monotonic() < bitis:
            time.sleep(0.05)
            if not masaustu.devral_var():
                return
        raise Dur(INSAN, _("kullanıcı sanal masaüstünü {sn} sn boyunca kullandı (Devral); {ne}").format(
            sn=f"{self.devral_bekle:.0f}", ne=ne))

    def _hazirla(self) -> None:
        if self.hazir:
            return
        self._devral_bekle(_("girdi gönderilmedi"))
        self.son_etk = time.monotonic()
        self.hazir = True

    def etk_denetle(self, ne: str | None = None) -> None:
        if masaustu.devral_var():
            raise Dur(INSAN, _("kullanıcı sanal masaüstünü devraldı (Devral); {ne}").format(
                ne=ne or _("girdi gönderilmedi")))
        self.son_etk = time.monotonic()

    def insan_kontrol(self) -> None:
        self._devral_bekle(_("girdi gönderilmedi"))
        self.son_fare = self.arka.fare()[:2]
        self.son_etk = time.monotonic()

    # -------- gözcü
    def izle(self, k: str, desen: str | None) -> None:
        """Yazı GÖZCÜSÜ (~12 ms, yoklama başına 1-2 kdotool çağrısı ~1,6 ms): etkin pencere, başlık,
        DUR, Devral. DUR'u görünce bu nesnenin basılı tuttuklarını HEMEN bırakır. Değişince bayrak kalkar; ham() bir
        sonraki satırdan (harften) önce durur."""
        self.izle_bitir()
        self.kesildi = None
        self._izle_dur = threading.Event()
        u = None if k == EKRAN else kimlik_coz(k)
        d = self.arka._d()

        def dongu():
            try:
                while not self._izle_dur.is_set():
                    neden = None
                    if os.path.exists(hata.dur_dosyasi()):
                        neden = (KULLANICI_DUR, _("kullanıcı DUR dedi"))
                    elif masaustu.devral_var():
                        neden = (INSAN, _("kullanıcı sanal masaüstünü devraldı (Devral)"))
                    elif u is not None:
                        # kdotool zinciri (getactivewindow getwindowname) yalnız ADI basar, kimliği değil: iki sorgu
                        a = self.arka._kd("getactivewindow", d=d).strip()
                        if a != u:
                            b = self.arka._kd("getwindowname", a, d=d) if UUID.fullmatch(a) else ""
                            neden = (AKTIF_DEGIL, _("aktif pencere değişti → {baslik}").format(baslik=repr(b)))
                        elif desen:
                            b = self.arka._kd("getwindowname", u, d=d)
                            if not re.search(desen, b, re.I):
                                neden = (BASLIK_SINIF, _("başlık değişti: {baslik} (beklenen /{desen}/)").format(
                                    baslik=repr(b), desen=desen))
                    if neden:
                        self.kesildi = Dur(*neden)
                        if neden[0] == KULLANICI_DUR:
                            self._hepsini_birak()
                        return
                    time.sleep(GOZCU_ARALIK)
            except Exception as e:  # noqa: BLE001 - gözcü çökerse güvenli taraf: dur
                self.kesildi = Dur(PENCERE_YOK, _("gözcü hatası: {hata}").format(hata=e))

        self._izleyici = threading.Thread(target=dongu, daemon=True)
        self._izleyici.start()

    def izle_bitir(self) -> None:
        if self._izleyici is not None:
            self._izle_dur.set()
            self._izleyici.join()
            self._izleyici = None

    # -------- gönderim
    def _kayit(self, k: str, satirlar) -> None:
        from ..gunluk import gunluk
        kayit = [f"type ***({len(s) - 5})" if self.gizli and s.startswith("type ") else s for s in satirlar]
        try:
            b = self.arka.baslik(k)
        except Dur:
            b = "?"
        gunluk(f"{self.etiket} | arka {self.ekran} [{b}] | {' ; '.join(kayit)}")

    def gonder(self, k: str, desen: str | None, *satirlar: str) -> None:
        """Sanal (Xvfb) Girdi.gonder ile aynı sıra: hazırla → DUR → güvenlik denetimi (denetle + erişim seviyesi) →
        Devral, sonra satırlar (ATOMİK). Herhangi bir Dur'da bu nesnenin basılıları bırakılır."""
        try:
            self._hazirla()
            if self.kesildi:
                raise self.kesildi
            hata.dur_denetle()
            if self.denetle is not None:
                self.denetle(k, desen)
                from ..guvenlik import girdi_seviye_denetle
                girdi_seviye_denetle(k, satirlar)  # uygulama erişim seviyesi (goruntule/tikla/tam): diğerleriyle aynı
            self.etk_denetle()
            for s in satirlar:
                self._calistir(s)
        except Dur:
            self._hepsini_birak()
            raise
        except Exception as e:  # noqa: BLE001
            self._hepsini_birak()
            raise Dur(ARAC_EKSIK, _("arka plan girdisi gönderilemedi: {hata}").format(hata=e))
        self.son_etk = time.monotonic()
        self._kayit(k, satirlar)

    def ham(self, satir: str) -> None:
        """Denetimsiz tek satır (yaz döngüsü; denetimi gözcü yapar). DUR yine de her satırdan önce bakılır."""
        if self.kesildi:
            self._hepsini_birak()
            raise self.kesildi
        try:
            hata.dur_denetle()
            self._calistir(satir)
        except Dur:
            self._hepsini_birak()
            raise
        except Exception as e:  # noqa: BLE001
            self._hepsini_birak()
            raise Dur(ARAC_EKSIK, _("arka plan girdisi gönderilemedi: {hata}").format(hata=e))

    def insan_ham(self, satir: str) -> None:
        """Paneldeki "Devral": İNSANIN girdisini arka plan masaüstüne aktarır. Devral bayrağını yok sayar, yalnız
        DUR'a bakar (bırakma satırları DUR'da da geçer). Günlüğe yazılmaz (kullanıcı parola yazıyor olabilir)."""
        if satir.split(" ", 1)[0].lower() not in ("buttonup", "keyup"):
            hata.dur_denetle()
        try:
            self._calistir(satir)
        except Dur:
            raise
        except Exception as e:  # noqa: BLE001
            self._hepsini_birak()
            raise Dur(ARAC_EKSIK, _("arka plan girdisi gönderilemedi: {hata}").format(hata=e))

    def zorla(self, satir: str) -> None:
        """BIRAKMA (keyup/buttonup): hiçbir denetim yok, kesinti olsa bile gönderilir."""
        try:
            self._calistir(satir)
        except Exception:  # noqa: BLE001
            pass
        from ..gunluk import gunluk
        gunluk(f"{self.etiket} | arka bırak | {satir}")

    def kapat(self) -> None:
        self.izle_bitir()
        self._hepsini_birak()

