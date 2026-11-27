"""Görünmez masaüstünün bellek bekçisi (ABM-F1; R2 düzeltmeleri 27 Kas).

Ölçüm (ABM-OLC, 27 Kas): kafesin büyümesi YALNIZ Firefox içerik süreçlerinde (gezinme başına ~22 MB, saatte GB'lar);
KWin ve yardımcılar düz. memory.reclaim 512M → −151 MB, gecikme değişmedi. Bu yüzden:

- bellek_durumu(kafes) → {"current", "max", "oran", "shmem", "anon", "kullanim"} (cgroup v2). ORAN = (anon + shmem) /
  max: sayfa önbelleği hariç (çekirdek onu sınırda kendisi geri alır; memory.current'a girer ama bellek baskısı değildir).
  Sınırsız kafeste oran 0.
- bellek_uyarisi(durum) → oran ≥ 0,80 ise uyarı metni (i18n), değilse None. Araç sonuçlarına `memory_warning` alanı
  olarak eklenir (uyari_ekle; MCP `arac` sarmalayıcısı çağırır). Yeniden başlatma sürüyorsa / son 10 dk'da yapıldıysa /
  başarısız olduysa / etkisiz kaldıysa bu da aynı alanda bildirilir.
- bakim(ad) — MCP'nin 60 sn'lik boşta bekçisinden (masaustu.bosta_kapat, KILIT altında) çağrılır; masaüstü BOŞTAYSA
  (son kullanım ≥ 120 sn; Devral açık, onay bekliyor ya da görev masaüstüyse hiçbir şey yapılmaz):
    oran ≥ 0,85 ve DESKHAND_FF_YENIDEN açık → YALNIZ Firefox, oturum geri yüklemeli yeniden başlatılır. Sınırlar: 10 dk'da
      bir; 24 saatte en çok 3 (bosta_kapat_dk=0 olsa da); oran %10'dan az düştüyse "etkisiz" → 60 dk geri çekilme, her
      etkisiz denemede iki katı. Masaüstü KAPANMAZ, başka uygulamaya dokunulmaz.
    oran ≥ 0,60 → memory.reclaim 512M (en çok 10 dk'da bir).
  Görev ortasında (boşta değilken) hiçbir şey yapılmaz: yalnız uyarı.

Firefox yeniden başlatma: başlatma kaydı (masaustu.baslat → tarayici_kaydet; çalışma dizininde, uygulamanın ad
alanında GÖRÜNMEZ) aynı komut/ortam/kopya/ev ile yeniden kullanılır.
  1. ÖNCE oturum kurtarma dosyası (sessionstore-backups/recovery.jsonlz4) denetlenir: var, çözülüyor, en az bir pencere
     içeriyor ve ŞU ANKİ Firefox açıldıktan sonra yazılmış olmalı (Firefox onu yalnız durum değişince ~15 sn içinde
     yazar; boşta Firefox'ta dosyanın yaşı bayatlık değildir, önceki örnekten kalma olması bayatlıktır). Değilse
     Firefox'a DOKUNULMAZ, yalnız uyarı verilir.
  2. Kurtarma dosyası kopya içinde yedeklenir (YEDEK_AD) ve kopyaya koruma işareti konur (oturum.kopya_bekcisi.koru_*):
     bekleyen ya da başarısız yeniden başlatmanın kopyasını bekçi/süpürme SİLMEZ.
  3. Ana Firefox SIGTERM ile kapanır (ölçüldü 27 Kas: SIGTERM sessionstore.jsonlz4 YAZMIYOR, geri yükleme ~15 sn'de bir
     yazılan recovery.jsonlz4'ten → son ~15 sn'de açılan sekme kaybolabilir), user.js'e resume_session_once eklenir,
     aynı kopya ile yeniden açılır. KILIT yalnız bu adımlar süresince tutulur (kayıt başına ≤ KAPANIS_AZAMI_SN +
     ESKI_BEKLE_SN; en çok AZAMI_KAYIT kayıt → MCP KILIT_BEKLE'nin altında).
  4. Doğrulama (açıldı mı, DOGRULA_SN boyunca ayakta mı) KİLİT DIŞINDA bir iş parçacığında yapılır; bu sırada araç
     sonuçları "Firefox yeniden başlıyor" uyarısını taşır. Başarıda eski bekçi durdurulur ve koruma işareti kalkar;
     açılış Dur/hata, açılmama ya da açılıştan sonra çökme günlüğe + `memory_warning`'e yazılır ("Firefox yeniden
     başlatılamadı: <neden>; oturum yedeği: <yol>"), koruma işareti KALIR (KORU_AZAMI sonra süpürülebilir).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import threading
import time
from typing import TypeGuard

from .i18n import _

UYARI_ORAN = 0.80
YENIDEN_ORAN = 0.85
RECLAIM_ORAN = 0.60
BOSTA_SN = 120.0
RECLAIM_MIKTAR = "512M"
RECLAIM_ARALIK_SN = 600.0
YENIDEN_ARALIK_SN = 600.0
OLAY_BILDIR_SN = 600.0
HATA_BILDIR_SN = 3600.0
ETKISIZ_ORAN = 0.10            # yeniden başlatma oranı bundan az düşürdüyse "etkisiz"
GERI_CEKILME_ILK_SN = 3600.0   # etkisiz yeniden başlatmadan sonra bekleme; her etkisiz denemede iki katı
GERI_CEKILME_AZAMI_SN = 86400.0  # geri çekilmenin üst sınırı (daha uzunu/bozuk damga geçersiz sayılır)
GUNLUK_AZAMI = 3               # 24 saatte en çok bu kadar yeniden başlatma (bosta_kapat_dk'dan bağımsız)
GUNLUK_PENCERE_SN = 86400.0
AZAMI_KAYIT = 3                # bir bakımda en çok bu kadar Firefox (KILIT süresi sınırlı kalsın)
KAPANIS_SN = 20.0              # SIGTERM sonrası bekleme; sonra SIGKILL
KAPANIS_AZAMI_SN = KAPANIS_SN + 1.0
ESKI_BEKLE_SN = 5.0            # kayıttaki (sarmalayıcı) sürecin bitmesi için bekleme
ACILIS_SN = 15.0               # yeni ana Firefox'un görünmesi için bekleme (kilit dışında)
DOGRULA_SN = 10.0              # açıldıktan sonra bu kadar sn ayakta kalmalı (kilit dışında)
BEKLEYEN_AZAMI_SN = 180.0      # doğrulaması bitmemiş (iş parçacığı ölmüş) yeniden başlatma bu kadar sn sonra sonuçlandırılır
KAPANIS_PAYI_SN = 20.0         # doğrulama başarısızsa: masaüstü mü kapanıyor (xvfb ≤ ~8 sn; KWin çekirdek süreçleri tek tek ≤ 4 sn)? bu kadar bekle
ORTAM_FF = "DESKHAND_FF_YENIDEN"
CGROUP_KOK = "/sys/fs/cgroup"
DURUM_DOSYA = "bellek-bekcisi.json"
KAYIT_DOSYA = "tarayicilar.json"
YEDEK_AD = "deskhand-yedek.jsonlz4"  # kopyanın sessionstore-backups/ dizininde: yeniden başlatma öncesi kurtarma dosyası
FIREFOX_ADLARI = ("firefox", "firefox-bin", "firefox-esr")
_KAFES_RX = re.compile(r"/[A-Za-z0-9_.@:/\\-]+")
_GERI_YUKLE = 'user_pref("browser.sessionstore.resume_session_once", true);  // deskhand bellek bekçisi\n'
_KAPALI = frozenset(("kapali", "kapalı", "false", "0", "no", "off", "hayir", "hayır"))
_ACIK = frozenset(("", "acik", "açık", "true", "1", "yes", "on", "evet"))
_UYARILAN: set[str] = set()
_KILIT = threading.RLock()  # bekçi durum dosyasının oku-değiştir-yaz'ı (bakım ↔ doğrulama iş parçacığı)
_SON_IS: threading.Thread | None = None  # son doğrulama iş parçacığı (testler bekler)
_SON_IS_ID: str | None = None            # o iş parçacığının sonuçlandıracağı bekleyen kaydın kimliği


def _mono() -> float:
    """Süre saati: CLOCK_BOOTTIME (monoton, uykuyu sayar, süreçler arası ortak; duvar saati sıçramalarından etkilenmez).
    Açılışta sıfırlanır: durum kaydı açılış kimliğiyle (_acilis) bağlanır."""
    try:
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    except (AttributeError, OSError):
        return time.monotonic()


def _acilis() -> str:
    return _oku("/proc/sys/kernel/random/boot_id") or ""


def _taze(olay, simdi: float, sure: float) -> bool:
    """olay["mono"] (süre saati damgası) son `sure` sn içinde mi? Damgasız/bozuk → hayır."""
    try:
        return abs(simdi - float(olay["mono"])) < sure
    except (KeyError, TypeError, ValueError):
        return False


def _is_canli(b) -> bool:
    """Bu bekleyen kaydı sonuçlandıracak doğrulama iş parçacığı (bu süreçte) hâlâ çalışıyor mu?"""
    t = _SON_IS
    return t is not None and t.is_alive() and isinstance(b, dict) and b.get("id") == _SON_IS_ID


# ---------------------------------------------------------------- ölçüm + uyarı

def _oku(yol: str) -> str | None:
    try:
        with open(yol) as f:
            return f.read().strip()
    except OSError:
        return None


def bellek_durumu(kafes: str | None, kok: str | None = None) -> dict | None:
    """Kafesin (cgroup v2 yolu, ör. /user.slice/…/deskhand-kwin-x-1.scope) bellek durumu → {"current", "max", "oran",
    "shmem", "anon", "kullanim"} (bayt). kullanim = anon + shmem (sayfa önbelleği hariç; memory.stat okunamazsa
    current); oran = kullanim / max (max 0 = sınırsız → 0.0). Okunamazsa None."""
    if not kafes or ".." in kafes or not _KAFES_RX.fullmatch(kafes):
        return None
    dizin = os.path.join(kok or CGROUP_KOK, kafes.lstrip("/"))
    cur = _oku(os.path.join(dizin, "memory.current"))
    if cur is None or not cur.isdigit():
        return None
    mx = _oku(os.path.join(dizin, "memory.max")) or "max"
    azami = int(mx) if mx.isdigit() else 0
    stat: dict[str, int] = {}
    for satir in (_oku(os.path.join(dizin, "memory.stat")) or "").splitlines():
        p = satir.split()
        if len(p) == 2 and p[1].isdigit():
            stat[p[0]] = int(p[1])
    current = int(cur)
    anon, shmem = stat.get("anon"), stat.get("shmem", 0)
    kullanim = min(current, anon + shmem) if anon is not None else current
    return {"current": current, "max": azami, "oran": (kullanim / azami) if azami else 0.0, "shmem": shmem,
            "anon": anon or 0, "kullanim": kullanim}


def ff_yeniden_acik() -> bool:
    """DESKHAND_FF_YENIDEN: kapali/false/0/no/off (büyük-küçük harf duyarsız) kapatır; tanınmayan değer açık sayılır ve
    günlüğe bir kez uyarı yazılır."""
    v = (os.environ.get(ORTAM_FF) or "").strip().lower()
    if v in _KAPALI:
        return False
    if v not in _ACIK and v not in _UYARILAN:
        _UYARILAN.add(v)
        from .gunluk import gunluk
        gunluk(f"bellek | {ORTAM_FF}={v!r} tanınmıyor (kapatmak için: kapali/false/0/no/off); açık sayıldı")
    return True


def bellek_uyarisi(durum: dict | None, firefox_var: bool = True) -> str | None:
    """oran ≥ UYARI_ORAN → uyarı metni (ne olacağını söyler), değilse None. firefox_var: yeniden başlatılabilecek
    (kayıtlı, kopyalı, sınıra/geri çekilmeye takılmamış) Firefox var mı."""
    if not durum or durum.get("oran", 0) < UYARI_ORAN:
        return None
    mb = 1 << 20
    metin = _("görünmez masaüstü bellek sınırının %{yuzde} kadarını kullanıyor ({cur} / {max} MB)").format(
        yuzde=round(durum["oran"] * 100), cur=durum.get("kullanim", durum["current"]) // mb, max=durum["max"] // mb)
    if ff_yeniden_acik() and firefox_var:
        return metin + "; " + _("boşta kalınca Firefox oturumu geri yüklenerek yeniden başlatılır (sekmeler geri "
                                "gelir, pencere kimlikleri değişir)")
    return metin + "; " + _("gereksiz sekme ve pencereleri kapatın")


# ---------------------------------------------------------------- bekçi durumu (masaüstü kökünde)

def _durum_yolu(ad: str | None) -> str:
    from . import masalar
    return os.path.join(masalar.kok(ad), DURUM_DOSYA)


def _durum_oku(ad: str | None) -> dict:
    try:
        with open(_durum_yolu(ad)) as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _durum_yaz(ad: str | None, v: dict) -> None:
    yol = _durum_yolu(ad)
    if not os.path.isdir(os.path.dirname(yol)):
        return
    gecici = f"{yol}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        fd = os.open(gecici, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(v, f)
        os.replace(gecici, yol)
    except OSError:
        try:
            os.unlink(gecici)
        except OSError:
            pass


def durum_temizle(ad: str | None) -> None:
    """Masaüstü kapanışında (masaustu.masaustu_durdur): bekçi durum dosyasını sil (varsayılan masaüstünde RUNTIME_DIR'da
    kalır; yeni masaüstü eski olayları/sınırları devralmasın)."""
    with _KILIT:
        try:
            os.unlink(_durum_yolu(ad))
        except OSError:
            pass
        _ONBELLEK.clear()


def _kayit_oku(ad: str | None, d: dict) -> dict:
    """Bu masaüstünün (kimlik) ve bu açılışın (boot_id) bekçi durumu. Başka kimliğin (çökmüş/dışarıdan öldürülmüş
    masaüstünden kalan dosya) ya da önceki açılışın kaydı yok sayılır: sayaçlar, geri çekilme, olaylar sıfırdan."""
    k = _durum_oku(ad)
    acilis = _acilis()
    if k.get("kimlik") != d.get("kimlik") or k.get("acilis") != acilis:
        k = {}
    k["kimlik"], k["acilis"] = d.get("kimlik"), acilis
    return k


def bekleyen_var(ad: str | None, d: dict) -> bool:
    """Doğrulaması süren Firefox yeniden başlatması var mı? (masaustu.bosta_neden: bu sırada masaüstü kapatılmaz)"""
    b = _kayit_oku(ad, d).get("bekleyen")
    return isinstance(b, dict) and (_taze(b, _mono(), BEKLEYEN_AZAMI_SN) or _is_canli(b))


_ONBELLEK: dict = {}
ONBELLEK_SN = 5.0


def uyari_ekle(r):
    """Araç sonucu sözlüğüne `memory_warning` ekle (gerekirse). Hata ve sözlük dışı sonuç: dokunulmaz. Ucuz: masaüstü
    başına ONBELLEK_SN önbellekli. → r."""
    if not isinstance(r, dict) or "memory_warning" in r:
        return r
    try:
        from . import masalar
        ad = masalar.secili()
        simdi = time.monotonic()
        o = _ONBELLEK.get(ad)
        if o is None or simdi - o[0] > ONBELLEK_SN:
            o = (simdi, uyari_metni(ad))
            _ONBELLEK[ad] = o
        if o[1]:
            r["memory_warning"] = o[1]
    except Exception:  # noqa: BLE001 - uyarı asla aracı düşürmez
        pass
    return r


def _neden_metni(neden: str) -> str:
    kod, _ayrac, ayrinti = str(neden).partition(":")
    metin = {"acilmadi": _("Firefox yeniden açılmadı"),
             "coktu": _("Firefox açıldıktan hemen sonra kapandı"),
             "baslatilamadi": _("başlatma reddedildi"),
             "hata": _("beklenmedik hata"),
             "dogrulanamadi": _("doğrulama tamamlanamadı")}.get(kod.strip())
    if metin is None:
        return str(neden)
    return metin + (f" ({ayrinti.strip()})" if ayrinti.strip() else "")


def _bu_masaustu(olay, d: dict) -> TypeGuard[dict]:
    return isinstance(olay, dict) and olay.get("kimlik", d.get("kimlik")) == d.get("kimlik")


def uyari_metni(ad: str | None = None, d: dict | None = None) -> str | None:
    """Masaüstünün güncel uyarısı (oran + yeniden başlatma: sürüyor / yapıldı / etkisiz / başarısız) ya da None."""
    from . import masaustu
    d = d if d is not None else masaustu.durum(dogrula=False, saglik=False, ad=ad)
    if not d:
        return None
    parcalar = []
    kayit = _kayit_oku(ad, d)
    simdi = _mono()
    cg = d.get("cgroup") or ""
    olcum = bellek_durumu(cg)
    u = bellek_uyarisi(olcum, False)
    if u:  # vaat yalnız gerçekten yeniden başlatılabilecek CANLI kayıt varsa (süreç taraması: yalnız uyarı gerekince)
        if _uzun_engel(kayit, simdi) is None and any(_kayit_canli(g, cg) for g in _kayitlar(d.get("calisma") or "")):
            u = bellek_uyarisi(olcum, True) or u
        parcalar.append(u)
    b = kayit.get("bekleyen")
    if _bu_masaustu(b, d) and (_taze(b, simdi, BEKLEYEN_AZAMI_SN) or _is_canli(b)):
        parcalar.append(_("Firefox bellek için yeniden başlıyor; birkaç saniye bekleyip yeniden gözlem yapın (pencere "
                          "kimlikleri değişecek)"))
    olay = kayit.get("son_yeniden_olay")
    if _bu_masaustu(olay, d) and _taze(olay, simdi, OLAY_BILDIR_SN):
        parcalar.append(_("bellek için Firefox {saat} saatinde yeniden başlatıldı ({once} → {sonra} MB, {sekme} sekme "
                          "geri yüklendi); pencere kimlikleri değişti, yeniden gözlem yapın").format(
            saat=time.strftime("%H:%M", time.localtime(float(olay["zaman"]))), once=olay.get("once_mb"),
            sonra=olay.get("sonra_mb"), sekme=olay.get("sekme", "?")))
        if olay.get("etkisiz"):
            parcalar.append(_("Firefox yeniden başlatması belleği yeterince azaltmadı ({once} → {sonra} MB); sonraki "
                              "yeniden başlatma {dk} dk ertelendi").format(
                once=olay.get("once_mb"), sonra=olay.get("sonra_mb"), dk=int(float(olay.get("geri_cekilme_sn") or 0) // 60)))
    h = kayit.get("son_hata_olay")
    if _bu_masaustu(h, d) and _taze(h, simdi, HATA_BILDIR_SN):
        if h.get("olduruldu"):
            parcalar.append(_("Firefox yeniden başlatılamadı: {neden}; oturum yedeği: {yedek}").format(
                neden=_neden_metni(h.get("neden") or ""), yedek=h.get("yedek") or "-"))
        else:
            parcalar.append(_("Firefox bellek için yeniden başlatılmadı: oturum kurtarma dosyası yok ya da bayat ({yol}); "
                              "sekmeler kaybolmasın diye Firefox'a dokunulmadı").format(yol=h.get("yedek") or "-"))
    return "; ".join(parcalar) or None


# ---------------------------------------------------------------- tarayıcı başlatma kaydı

def _firefox_mi(argv) -> bool:
    return bool(argv) and os.path.basename(str(argv[0])) in FIREFOX_ADLARI


def _profil(argv) -> str | None:
    for i, a in enumerate(argv[:-1]):
        if a in ("--profile", "-profile"):
            return argv[i + 1]
    return None


def _kayit_yolu(calisma: str) -> str:
    return os.path.join(calisma, KAYIT_DOSYA)


def _kayitlar(calisma: str) -> list[dict]:
    if not calisma:
        return []
    try:
        with open(_kayit_yolu(calisma)) as f:
            v = json.load(f)
        return [g for g in v if isinstance(g, dict)] if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def _kayit_yaz(calisma: str, kayitlar: list[dict]) -> None:
    gecici = _kayit_yolu(calisma) + f".{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        fd = os.open(gecici, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(kayitlar, f)
        os.replace(gecici, _kayit_yolu(calisma))
    except OSError:
        try:
            os.unlink(gecici)
        except OSError:
            pass


def _kayit_canli(g: dict, cg: str) -> bool:
    """Kayıt yeniden başlatılabilir mi: kopyası duruyor ve kafeste o kopyayla çalışan ana Firefox var."""
    k = g.get("kopya") or ""
    return bool(k and cg) and os.path.isdir(k) and not os.path.islink(k) and bool(firefox_ana_pidleri(cg, k))


def _kayit_buda(calisma: str, olu: list[dict]) -> None:
    """Ölü kayıtları (kopyası silinmiş ya da Firefox'u kapanmış) tarayicilar.json'dan çıkar. Dosya yeniden okunur ve
    yalnız bu kayıtlar (kopya + pid) çıkarılır: arada eklenen kayıt kaybolmaz."""
    if not olu:
        return
    anahtar = {(os.path.realpath(g.get("kopya") or ""), g.get("pid")) for g in olu}
    with _KILIT:
        tum = _kayitlar(calisma)
        kalan = [g for g in tum if (os.path.realpath(g.get("kopya") or ""), g.get("pid")) not in anahtar]
        if len(kalan) != len(tum):
            _kayit_yaz(calisma, kalan)


def tarayici_kaydet(d: dict, argv, env, kopya, ev, pid: int) -> None:
    """masaustu.baslat: politikanın kopyasıyla açılan Firefox'un başlatma bilgisi (yeniden başlatma için). Kayıt
    çalışma dizinindedir (0700; uygulamanın ad alanına bağlanmaz). Firefox değilse / kopya yoksa hiçbir şey yapmaz."""
    if not kopya or not _firefox_mi(argv) or os.path.realpath(_profil(list(argv)) or "/") != os.path.realpath(kopya):
        return
    calisma = d.get("calisma") or ""
    if not calisma or not os.path.isdir(calisma):
        return
    from .arka_ortak import surec_baslangic
    temel = [a for a in argv if not re.match(r"^(https?|file|about):", str(a))]  # adresler oturumdan geri gelir
    with _KILIT:  # budama (_kayit_buda) ile aynı süreçte yarışmasın
        kayitlar = [g for g in _kayitlar(calisma) if os.path.realpath(g.get("kopya") or "") != os.path.realpath(kopya)]
        kayitlar.append({"argv": [str(a) for a in temel], "env": {str(k): str(v) for k, v in (env or {}).items()},
                         "kopya": kopya, "ev": [list(x) if isinstance(x, (list, tuple)) else x for x in (ev or ())],
                         "pid": int(pid), "bas": surec_baslangic(pid)})
        _kayit_yaz(calisma, kayitlar)


# ---------------------------------------------------------------- süreçler

def _kafes_pidleri(cg: str) -> list[int]:
    out: set[int] = set()
    for kok, _d, _f in os.walk(os.path.join(CGROUP_KOK, cg.lstrip("/"))):
        out.update(int(x) for x in (_oku(os.path.join(kok, "cgroup.procs")) or "").split() if x.isdigit())
    return sorted(out)


def _argv(pid: int) -> list[str]:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return [p.decode(errors="replace") for p in f.read().split(b"\0") if p]
    except OSError:
        return []


def firefox_ana_pidleri(cg: str, kopya: str) -> list[int]:
    """Kafesteki, bu kopyayla çalışan ANA Firefox süreçleri (içerik süreçleri -contentproc hariç)."""
    gercek = os.path.realpath(kopya)
    return [p for p in _kafes_pidleri(cg) if _firefox_mi(a := _argv(p)) and "-contentproc" not in a
            and os.path.realpath(_profil(a) or "/") == gercek]


def _canli(pid: int, bas=None) -> bool:
    from .arka_ortak import _canli as c, pid_dogru
    return c(pid) and (not bas or pid_dogru(pid, bas))


def _bekle(kosul, sure: float) -> bool:
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        if kosul():
            return True
        time.sleep(0.1)
    return bool(kosul())


def _baslangic_epoch(pid: int) -> float | None:
    """Sürecin başlangıç zamanı (epoch sn): /proc/<pid>/stat alan 22 (açılıştan beri tik) + /proc/stat btime."""
    from .arka_ortak import surec_baslangic
    tik = surec_baslangic(pid)
    btime = next((int(s.split()[1]) for s in (_oku("/proc/stat") or "").splitlines() if s.startswith("btime ")), None)
    if tik is None or btime is None:
        return None
    return btime + int(tik) / os.sysconf("SC_CLK_TCK")


def _eski_bekciyi_durdur(kopya: str, eski_pid: int) -> None:
    """Eski sahibin kopya bekçisini sonlandır (yeni süreç kendi bekçisini aldı)."""
    gercek = os.path.realpath(kopya)
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        a = _argv(int(d))
        if any(x.endswith("kopya_bekcisi.py") for x in a) and "--kopya" in a and "--pid" in a:
            i, j = a.index("--kopya"), a.index("--pid")
            if i + 1 < len(a) and j + 1 < len(a) and a[i + 1] == gercek and a[j + 1] == str(eski_pid):
                try:
                    os.kill(int(d), signal.SIGTERM)
                except OSError:
                    pass


def _kurtarma_yolu(kopya: str) -> str:
    return os.path.join(kopya, "sessionstore-backups", "recovery.jsonlz4")


def _kurtarma_sekme(kopya: str) -> int | None:
    """recovery.jsonlz4'teki sekme sayısı; dosya yok/çözülemiyor/penceresiz → None."""
    from .oturum.firefox import mozlz4_coz
    ham = mozlz4_coz(_kurtarma_yolu(kopya))
    if not ham:
        return None
    try:
        pencereler = json.loads(ham).get("windows") or []
        return sum(len(w.get("tabs") or []) for w in pencereler) if pencereler else None
    except (ValueError, AttributeError, TypeError):
        return None


def kurtarma_denetle(kopya: str, ana_pid: list[int]) -> tuple[bool, int | None]:
    """Öldürmeden ÖNCE: kurtarma dosyası var, çözülüyor, pencere içeriyor ve şu anki ana Firefox açıldıktan sonra
    yazılmış mı? → (taze mi, sekme sayısı)."""
    try:
        mt = os.path.getmtime(_kurtarma_yolu(kopya))
    except OSError:
        return False, None
    sekme = _kurtarma_sekme(kopya)
    if sekme is None:
        return False, None
    baslar = [b for b in (_baslangic_epoch(p) for p in ana_pid) if b is not None]
    if not baslar or mt < max(baslar) - 1:
        return False, sekme
    return True, sekme


def firefox_yeniden_baslat(d: dict, g: dict, son: float | None = None) -> dict:
    """Kayıttaki Firefox'u (g) oturum geri yüklemeli yeniden başlat; KİLİTLİ kısım (öldür + başlat). → {"ok": True |
    False | None (doğrulama bekliyor: "popen" ile), "neden"?, "olduruldu", "pid"?, "sekme"?, "yedek"?, "kopya"}.
    Doğrulama: dogrula(cg, kopya, popen) (kilit dışında)."""
    from . import masaustu
    from .oturum import kopya_bekcisi
    kopya = g.get("kopya") or ""
    cg = d.get("cgroup") or ""
    temel = {"kopya": kopya, "olduruldu": False}
    if not kopya or not os.path.isdir(kopya) or os.path.islink(kopya) or not cg:
        return {**temel, "ok": False, "neden": "kopya-yok"}
    ana_pid = firefox_ana_pidleri(cg, kopya)
    if not ana_pid:
        return {**temel, "ok": False, "neden": "firefox-yok"}
    taze, sekme = kurtarma_denetle(kopya, ana_pid)
    if not taze:
        return {**temel, "ok": False, "neden": "kurtarma-yok", "yedek": _kurtarma_yolu(kopya)}
    yedek = os.path.join(kopya, "sessionstore-backups", YEDEK_AD)
    try:
        shutil.copyfile(_kurtarma_yolu(kopya), yedek)
        os.chmod(yedek, 0o600)
    except OSError:
        return {**temel, "ok": False, "neden": "kurtarma-yok", "yedek": _kurtarma_yolu(kopya)}
    kopya_bekcisi.koru_isaretle(kopya, "bellek-yeniden")  # bekleyen/başarısız yeniden başlatmanın kopyası silinmesin
    tut = os.open(kopya, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)  # ek güvence: bekçi kopyayı kullanımda sayar
    sonuc = {**temel, "olduruldu": True, "sekme": sekme, "yedek": yedek}
    try:
        for p in ana_pid:
            try:
                os.kill(p, signal.SIGTERM)
            except OSError:
                pass
        if not _bekle(lambda: not any(_canli(p) for p in ana_pid), KAPANIS_SN):
            for p in ana_pid:
                try:
                    os.kill(p, signal.SIGKILL)
                except OSError:
                    pass
            _bekle(lambda: not any(_canli(p) for p in ana_pid), KAPANIS_AZAMI_SN - KAPANIS_SN)
        _bekle(lambda: not _canli(int(g.get("pid") or 0), g.get("bas")), ESKI_BEKLE_SN)
        uj = os.path.join(kopya, "user.js")
        try:
            with open(uj, encoding="utf-8") as f:
                icerik = f.read()
        except OSError:
            icerik = ""
        if _GERI_YUKLE not in icerik:
            with open(uj, "a", encoding="utf-8") as f:
                f.write(("\n" if icerik and not icerik.endswith("\n") else "") + _GERI_YUKLE)
        p = masaustu.baslat(list(g.get("argv") or []), g.get("env") or None, kopya=kopya,
                            ev=tuple(tuple(x) if isinstance(x, list) else x for x in (g.get("ev") or ())))
        return {**sonuc, "ok": None, "pid": p.pid, "popen": p}
    except Exception as e:  # noqa: BLE001 - Dur dahil: YUTULMAZ, çağıran günlüğe + uyarıya yazar
        from .hata import Dur
        tur = "baslatilamadi" if isinstance(e, Dur) else "hata"
        return {**sonuc, "ok": False, "neden": f"{tur}: {getattr(e, 'mesaj', None) or e}"}
    finally:
        os.close(tut)


def dogrula(cg: str, kopya: str, p, acildi=None) -> tuple[bool, str | None]:
    """Kilit dışında: yeni ana Firefox ACILIS_SN içinde göründü mü ve DOGRULA_SN boyunca ayakta kaldı mı? acildi():
    yeni ana Firefox görününce bir kez çağrılır (koruma işareti "acildi")."""
    if not _bekle(lambda: bool(firefox_ana_pidleri(cg, kopya)) or p.poll() is not None, ACILIS_SN) \
            or p.poll() is not None:
        return False, "acilmadi" if p.poll() is None else "coktu"
    if acildi is not None:
        acildi()
    bitis = time.monotonic() + DOGRULA_SN
    while time.monotonic() < bitis:
        if p.poll() is not None or not firefox_ana_pidleri(cg, kopya):
            return False, "coktu"
        time.sleep(0.1)
    return True, None


# ---------------------------------------------------------------- bakım (boşta)

def _engel(ad: str | None, d: dict | None = None) -> str | None:
    from . import masaustu
    if d is not None and d.get("gorev"):
        return "gorev"  # görev masaüstü boşta sayılmaz (masaustu.bosta_neden ile aynı)
    if masaustu.devral_var(masaustu.devral_yolu(ad)):
        return "devral-acik"  # (dosya adı sabiti "devral" burada geçmez: test_masalar yasak sabit denetimi)
    try:
        from . import onay
        if onay.bekleyen_var("arka", masa=ad):
            return "onay"
    except Exception:  # noqa: BLE001 - karar verilemedi: dokunma
        return "onay?"
    return None


def _gecmis(kayit: dict, simdi: float) -> list[float]:
    """24 sa penceresindeki yeniden başlatma damgaları (süre saati; pencereden uzak gelecek damgası bozuk sayılır)."""
    return [float(t) for t in (kayit.get("yeniden_gecmis") or []) if isinstance(t, (int, float))
            and abs(simdi - float(t)) < GUNLUK_PENCERE_SN]


def _uzun_engel(kayit: dict, simdi: float) -> str | None:
    """Uzun süreli engel: etkisizlik geri çekilmesi (en çok GERI_CEKILME_AZAMI_SN; daha uzak bitiş bozuk sayılır) ya da
    24 saat sınırı."""
    try:
        bitis = float(kayit.get("geri_cekilme_bitis") or 0)
    except (TypeError, ValueError):
        bitis = 0.0
    if 0 < bitis - simdi <= GERI_CEKILME_AZAMI_SN + 1:  # +1 sn: simdi + AZAMI kayan noktada AZAMI'yı az aşabilir
        return "geri-cekilme"
    if len(_gecmis(kayit, simdi)) >= GUNLUK_AZAMI:
        return "gunluk-sinir"
    return None


def reclaim(cg: str, miktar: str = RECLAIM_MIKTAR) -> bool:
    """memory.reclaim yaz (çekirdek istenen miktarı geri alamazsa EAGAIN: yine de bir kısmını almıştır)."""
    try:
        with open(os.path.join(CGROUP_KOK, cg.lstrip("/"), "memory.reclaim"), "w") as f:
            f.write(miktar)
        return True
    except BlockingIOError:
        return True
    except OSError:
        return False


def _ayni_masaustu(ad: str | None, d: dict) -> bool:
    """Masaüstü hâlâ aynı (kimlik) ve canlı mı? (kapanırken ekran sunucusu ölür, sonra durum kaydı silinir)"""
    from . import masaustu
    try:
        simdiki = masaustu.durum(dogrula=True, saglik=False, ad=ad)
    except Exception:  # noqa: BLE001
        return False
    return bool(simdiki) and simdiki.get("kimlik") == d.get("kimlik")


def _hata_kaydet(ad: str | None, d: dict, kayit: dict, s: dict, simdi: float) -> None:
    """Hata olayı (uyarı HATA_BILDIR_SN sürer, her denemede yenilenir). Günlüğe: öldürülmüş (gerçek) her başarısızlık;
    'kurtarma dosyası yok/bayat' yalnız durum değişince (boştaki Firefox'ta 10 dk'da bir tekrarlamasın)."""
    from .gunluk import gunluk
    onceki = kayit.get("son_hata_olay")
    yeni = {"zaman": time.time(), "mono": simdi, "neden": s.get("neden"), "yedek": s.get("yedek"),
            "olduruldu": bool(s.get("olduruldu")), "kimlik": d.get("kimlik")}
    ayni = isinstance(onceki, dict) and all(onceki.get(k) == yeni[k] for k in ("neden", "yedek", "olduruldu", "kimlik"))
    kayit["son_hata_olay"] = yeni
    if s.get("olduruldu"):
        gunluk(f"bellek | {ad or 'varsayılan'} Firefox yeniden başlatılamadı: {s.get('neden')}; oturum yedeği: "
               f"{s.get('yedek')} (kopya korunuyor)")
    elif not ayni:
        gunluk(f"bellek | {ad or 'varsayılan'} Firefox yeniden başlatılmadı: oturum kurtarma dosyası yok ya da bayat "
               f"({s.get('yedek')}); Firefox'a dokunulmadı")


def _sonuclandir(ad: str | None, d: dict, durum: dict, sonuclar: list[tuple[dict, dict]], simdi: float,
                 bekleyen_id: str | None = None) -> dict | None:
    """Doğrulanmış sonuçları (g, s: ok True/False) işle: eski bekçi + koruma işareti, olay/hata kaydı, etkisizlik geri
    çekilmesi. Başarılı yeniden başlatmanın koruma işareti HER durumda kalkar; masaüstü bu arada kapandıysa/değiştiyse
    başka bir şey yazılmaz. bekleyen_id: bu bekleyen kayıt zaten sonuçlandıysa (bayat dal ↔ iş parçacığı) hiçbir şey
    yapılmaz (tek sonuç). simdi: süre saati. → başarı olayı ya da None."""
    from .gunluk import gunluk
    from .oturum import kopya_bekcisi
    mb = 1 << 20
    with _KILIT:
        for _g, s in sonuclar:
            if s.get("ok") and s.get("kopya") and os.path.isdir(s["kopya"]):
                kopya_bekcisi.koru_kaldir(s["kopya"])
        if not _ayni_masaustu(ad, d):
            return None
        kayit = _kayit_oku(ad, d)
        b = kayit.get("bekleyen")
        if bekleyen_id is not None and not (isinstance(b, dict) and b.get("id") == bekleyen_id):
            return None
        kayit.pop("bekleyen", None)
        basarili = []
        for g, s in sonuclar:
            if s.get("ok"):
                basarili.append(s)
                if s.get("kopya") and os.path.isdir(s["kopya"]):
                    _eski_bekciyi_durdur(s["kopya"], int(g.get("pid") or 0))
            else:
                _hata_kaydet(ad, d, kayit, s, simdi)
                if s.get("olduruldu") and s.get("kopya") and os.path.isdir(s["kopya"]):
                    kopya_bekcisi.koru_isaretle(s["kopya"], "bellek-yeniden", "basarisiz")
        olay = None
        if basarili:
            if len(basarili) == len(sonuclar):
                kayit.pop("son_hata_olay", None)  # sorun çözüldü: eski hata uyarısı/günlük durumu kalmasın
            sonra = bellek_durumu(d["cgroup"]) or durum
            once_k, sonra_k = durum.get("kullanim", durum["current"]), sonra.get("kullanim", sonra["current"])
            etkisiz = once_k <= 0 or (once_k - sonra_k) / once_k < ETKISIZ_ORAN
            olay = {"zaman": time.time(), "mono": simdi, "once_mb": once_k // mb, "sonra_mb": sonra_k // mb,
                    "kimlik": d.get("kimlik"), "sekme": sum(s.get("sekme") or 0 for s in basarili), "etkisiz": etkisiz}
            gc = 0.0
            if etkisiz:
                gc = min(GERI_CEKILME_AZAMI_SN, max(GERI_CEKILME_ILK_SN, 2 * float(kayit.get("geri_cekilme_sn") or 0)))
                kayit.update(geri_cekilme_sn=gc, geri_cekilme_bitis=simdi + gc)
                olay["geri_cekilme_sn"] = gc
            else:
                kayit.pop("geri_cekilme_sn", None)
                kayit.pop("geri_cekilme_bitis", None)
            kayit["son_yeniden_olay"] = olay
            gunluk(f"bellek | {ad or 'varsayılan'} Firefox yeniden başlatıldı: {olay['once_mb']} → {olay['sonra_mb']} MB "
                   f"(anon+shmem), {olay['sekme']} sekme" + (f"; ETKİSİZ (<%{round(ETKISIZ_ORAN * 100)} düşüş), sonraki "
                                                               f"yeniden başlatma {int(gc // 60)} dk ertelendi"
                                                               if etkisiz else ""))
        _durum_yaz(ad, kayit)
        _ONBELLEK.clear()
        return olay


def _dogrula_is(ad: str | None, d: dict, durum: dict, bekleyenler: list[tuple[dict, dict]], hazir: list, simdi: float,
                bekleyen_id: str):
    """Doğrulama iş parçacığı (KILIT DIŞINDA)."""
    from .oturum import kopya_bekcisi
    sonuclar = list(hazir)
    basarisiz = False
    for g, s in bekleyenler:
        try:
            ok, neden = dogrula(d["cgroup"], s["kopya"], s["popen"],
                                acildi=lambda k=s["kopya"]: kopya_bekcisi.koru_isaretle(k, "bellek-yeniden", "acildi"))
        except Exception as e:  # noqa: BLE001
            ok, neden = False, f"dogrulanamadi: {e}"
        basarisiz = basarisiz or not ok
        s2 = {k: v for k, v in s.items() if k != "popen"}
        s2.update(ok=ok, **({"neden": neden} if neden else {}))
        sonuclar.append((g, s2))
    if basarisiz:  # masaüstü kapanıyorsa (Firefox kapanış yüzünden öldü) sahte "yeniden başlatılamadı" yazılmasın
        _bekle(lambda: not _ayni_masaustu(ad, d), KAPANIS_PAYI_SN)
    try:
        _sonuclandir(ad, d, durum, sonuclar, simdi, bekleyen_id)
    except Exception as e:  # noqa: BLE001 - iş parçacığı sessizce ölmesin
        from .gunluk import gunluk
        gunluk(f"bellek | {ad or 'varsayılan'} yeniden başlatma doğrulaması: hata: {e}")


def _bayat_bekleyen(ad: str | None, d: dict, b: dict) -> None:
    """Doğrulaması sonuçlanmamış (iş parçacığı süreçle birlikte öldü) bekleyen yeniden başlatma: şimdi değerlendir."""
    sonuclar = []
    for k in b.get("kopyalar") or []:
        ok = bool(firefox_ana_pidleri(d["cgroup"], k.get("kopya") or "")) if k.get("kopya") else False
        sonuclar.append(({"pid": k.get("pid")}, {**k, "ok": ok, **({} if ok else {"neden": "dogrulanamadi"})}))
    durum = {"current": int(b.get("once_current") or 0), "kullanim": int(b.get("once_kullanim") or 0)}
    try:
        mono = float(b.get("mono") or 0)
    except (TypeError, ValueError):
        mono = 0.0
    _sonuclandir(ad, d, durum, sonuclar, mono or _mono(), str(b.get("id") or ""))  # bekleyen kaydı da kalkar


def _yeniden(ad: str | None, d: dict, durum: dict, kayit: dict, kayitlar: list[dict], simdi: float,
             son: float | None) -> dict:
    """Kilitli kısım: kayıtları öldür + başlat; doğrulamayı iş parçacığına ver. simdi: süre saati."""
    global _SON_IS, _SON_IS_ID
    import secrets
    sonuc = []
    for g in kayitlar:
        try:
            s = firefox_yeniden_baslat(d, g, son)
        except Exception as e:  # noqa: BLE001
            s = {"kopya": g.get("kopya"), "ok": False, "olduruldu": False, "neden": f"hata: {e}"}
        sonuc.append((g, s))
    kayit["son_yeniden"] = simdi  # başarısız deneme de 10 dk bekler (döngü yok)
    if any(s.get("olduruldu") or s.get("ok") for _g, s in sonuc):
        kayit["yeniden_gecmis"] = _gecmis(kayit, simdi) + [simdi]
    bekleyen = [(g, s) for g, s in sonuc if s.get("ok") is None]
    hazir = [(g, s) for g, s in sonuc if s.get("ok") is not None and s.get("neden") not in ("kopya-yok", "firefox-yok")]
    ozet = [{k: v for k, v in s.items() if k != "popen"} for _g, s in sonuc]
    bid = secrets.token_hex(6)
    if bekleyen:
        kayit["bekleyen"] = {"mono": simdi, "id": bid, "kimlik": d.get("kimlik"), "once_current": durum["current"],
                             "once_kullanim": durum.get("kullanim", durum["current"]),
                             "kopyalar": [{k: s.get(k) for k in ("kopya", "pid", "sekme", "yedek", "olduruldu")}
                                          for _g, s in bekleyen]}
    with _KILIT:
        _durum_yaz(ad, kayit)
        _ONBELLEK.clear()
    if bekleyen:
        _SON_IS_ID = bid
        _SON_IS = threading.Thread(target=_dogrula_is, args=(ad, d, durum, bekleyen, hazir, simdi, bid),
                                   name="deskhand-bellek-dogrula", daemon=True)
        _SON_IS.start()
        return {"is": "firefox_yeniden", "bekliyor": True, "sonuc": ozet}
    olay = _sonuclandir(ad, d, durum, hazir, simdi) if hazir else None
    if olay:
        return {"is": "firefox_yeniden", **olay, "sonuc": ozet}
    return {"is": "firefox_yeniden", "ok": False, "sonuc": ozet}


def bakim(ad: str | None = None, simdi: float | None = None, d: dict | None = None,
          mono: float | None = None) -> dict | None:
    """Boşta masaüstünde bellek bakımı (bkz. modül belgesi). Masaüstünü KAPATMAZ. simdi: duvar saati (boşta denetimi:
    son_kullanim bir mtime); mono: süre saati (_mono; 10 dk / geri çekilme / 24 sa). → yapılan iş özeti ya da None."""
    from . import masaustu
    from .gunluk import gunluk
    d = d if d is not None else masaustu.durum(saglik=False, ad=ad)
    if not d or not d.get("cgroup"):
        return None
    simdi = time.time() if simdi is None else simdi
    mono = _mono() if mono is None else mono
    kayit = _kayit_oku(ad, d)
    b = kayit.get("bekleyen")
    if isinstance(b, dict):
        if _taze(b, _mono(), BEKLEYEN_AZAMI_SN) or _is_canli(b):
            return None  # doğrulama sürüyor (iş parçacığı canlıysa saat sıçrasa da): başka bakım yok
        _bayat_bekleyen(ad, d, b)
        kayit = _kayit_oku(ad, d)
        kayit.pop("bekleyen", None)
    durum = bellek_durumu(d["cgroup"])
    if not durum or not durum["max"]:
        return None
    son = masaustu.son_kullanim(ad)
    if son is None or simdi - son < BOSTA_SN or durum["oran"] < RECLAIM_ORAN or _engel(ad, d):
        return None
    calisma = d.get("calisma") or ""
    tum = _kayitlar(calisma)
    canli = [g for g in tum if _kayit_canli(g, d["cgroup"])]
    _kayit_buda(calisma, [g for g in tum if g not in canli])  # ölü kayıtlar yuvaları yemesin
    mb = 1 << 20
    if durum["oran"] >= YENIDEN_ORAN and ff_yeniden_acik() and _uzun_engel(kayit, mono) is None and \
            abs(mono - float(kayit.get("son_yeniden") or -YENIDEN_ARALIK_SN * 2)) >= YENIDEN_ARALIK_SN:
        kayitlar = canli[:AZAMI_KAYIT]
        if kayitlar:
            return _yeniden(ad, d, durum, kayit, kayitlar, mono, son)
    if abs(mono - float(kayit.get("son_reclaim") or -RECLAIM_ARALIK_SN * 2)) >= RECLAIM_ARALIK_SN:
        ok = reclaim(d["cgroup"])
        kayit["son_reclaim"] = mono
        with _KILIT:
            _durum_yaz(ad, kayit)
        sonra = bellek_durumu(d["cgroup"]) or durum
        if ok:
            gunluk(f"bellek | {ad or 'varsayılan'} memory.reclaim {RECLAIM_MIKTAR}: {durum['current'] // mb} → "
                   f"{sonra['current'] // mb} MB")
        else:
            gunluk(f"bellek | {ad or 'varsayılan'} memory.reclaim {RECLAIM_MIKTAR}: başarısız (yazılamadı); "
                   f"{durum['current'] // mb} MB")
        return {"is": "reclaim", "ok": ok, "once_mb": durum["current"] // mb, "sonra_mb": sonra["current"] // mb}
    return None
