"""Görünmez masaüstünün bellek bekçisi (ABM-F1).

Ölçüm (ABM-OLC, 27 Kas): kafesin büyümesi YALNIZ Firefox içerik süreçlerinde (gezinme başına ~22 MB, saatte GB'lar);
KWin ve yardımcılar düz. memory.reclaim 512M → −151 MB, gecikme değişmedi. Bu yüzden:

- bellek_durumu(kafes) → {"current", "max", "oran", "shmem"} (cgroup v2 dosyaları; sınırsız kafeste oran 0).
- bellek_uyarisi(durum) → oran ≥ 0,80 ise uyarı metni (i18n), değilse None. Araç sonuçlarına `memory_warning`
  alanı olarak eklenir (uyari_ekle; MCP `arac` sarmalayıcısı çağırır). Son 10 dk'da bekçi Firefox'u yeniden
  başlattıysa bu da aynı alanda bildirilir (pencere kimlikleri değişti: yeniden gözlem).
- bakim(ad) — MCP'nin 60 sn'lik boşta bekçisinden (masaustu.bosta_kapat) çağrılır; masaüstü BOŞTAYSA (son kullanım
  ≥ 120 sn; Devral açık ya da onay bekliyorsa hiçbir şey yapılmaz):
    oran ≥ 0,85 ve DESKHAND_FF_YENIDEN≠kapali → YALNIZ Firefox, oturum geri yüklemeli yeniden başlatılır (en çok
      10 dk'da bir). Masaüstü KAPANMAZ, başka uygulamaya dokunulmaz.
    oran ≥ 0,60 → memory.reclaim 512M (en çok 10 dk'da bir).
  Görev ortasında (boşta değilken) hiçbir şey yapılmaz: yalnız uyarı.

Firefox yeniden başlatma: başlatma kaydı (masaustu.baslat → tarayici_kaydet; çalışma dizininde, uygulamanın ad
alanında GÖRÜNMEZ) aynı komut/ortam/kopya/ev ile yeniden kullanılır. Ana Firefox SIGTERM ile kapanır (oturumu
sessionstore.jsonlz4'e yazar), kopyanın user.js'ine browser.sessionstore.resume_session_once eklenir ve aynı kopya
ile yeniden açılır (sekmeler geri gelir). Kapanış sırasında kopya bekçisi (oturum/kopya_bekcisi) kopyayı silmesin
diye kopya dizininde açık bir tanımlayıcı tutulur; yeni süreç kendi bekçisini alır, eski bekçi sonlandırılır.
"""
from __future__ import annotations

import json
import os
import re
import signal
import time

from .i18n import _

UYARI_ORAN = 0.80
YENIDEN_ORAN = 0.85
RECLAIM_ORAN = 0.60
BOSTA_SN = 120.0
RECLAIM_MIKTAR = "512M"
RECLAIM_ARALIK_SN = 600.0
YENIDEN_ARALIK_SN = 600.0
OLAY_BILDIR_SN = 600.0
ORTAM_FF = "DESKHAND_FF_YENIDEN"
CGROUP_KOK = "/sys/fs/cgroup"
DURUM_DOSYA = "bellek-bekcisi.json"
KAYIT_DOSYA = "tarayicilar.json"
FIREFOX_ADLARI = ("firefox", "firefox-bin", "firefox-esr")
KAPANIS_SN = 20.0
_KAFES_RX = re.compile(r"/[A-Za-z0-9_.@:/\\-]+")
_GERI_YUKLE = 'user_pref("browser.sessionstore.resume_session_once", true);  // deskhand bellek bekçisi\n'


# ---------------------------------------------------------------- ölçüm + uyarı

def _oku(yol: str) -> str | None:
    try:
        with open(yol) as f:
            return f.read().strip()
    except OSError:
        return None


def bellek_durumu(kafes: str | None, kok: str | None = None) -> dict | None:
    """Kafesin (cgroup v2 yolu, ör. /user.slice/…/deskhand-kwin-x-1.scope) bellek durumu → {"current", "max", "oran",
    "shmem"} (bayt; max 0 = sınırsız → oran 0.0). Okunamazsa None."""
    if not kafes or ".." in kafes or not _KAFES_RX.fullmatch(kafes):
        return None
    dizin = os.path.join(kok or CGROUP_KOK, kafes.lstrip("/"))
    cur = _oku(os.path.join(dizin, "memory.current"))
    if cur is None or not cur.isdigit():
        return None
    mx = _oku(os.path.join(dizin, "memory.max")) or "max"
    azami = int(mx) if mx.isdigit() else 0
    shmem = 0
    for satir in (_oku(os.path.join(dizin, "memory.stat")) or "").splitlines():
        p = satir.split()
        if len(p) == 2 and p[0] == "shmem" and p[1].isdigit():
            shmem = int(p[1])
    current = int(cur)
    return {"current": current, "max": azami, "oran": (current / azami) if azami else 0.0, "shmem": shmem}


def ff_yeniden_acik() -> bool:
    return (os.environ.get(ORTAM_FF) or "").strip().lower() not in ("kapali", "kapalı", "0", "off", "no", "hayir")


def bellek_uyarisi(durum: dict | None, firefox_var: bool = True) -> str | None:
    """oran ≥ UYARI_ORAN → uyarı metni (ne olacağını söyler), değilse None. firefox_var: yeniden başlatılabilecek
    (kayıtlı, kopyalı) Firefox var mı."""
    if not durum or durum.get("oran", 0) < UYARI_ORAN:
        return None
    mb = 1 << 20
    metin = _("görünmez masaüstü bellek sınırının %{yuzde} kadarını kullanıyor ({cur} / {max} MB)").format(
        yuzde=round(durum["oran"] * 100), cur=durum["current"] // mb, max=durum["max"] // mb)
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
    gecici = f"{yol}.{os.getpid()}.tmp"
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


def uyari_metni(ad: str | None = None, d: dict | None = None) -> str | None:
    """Masaüstünün güncel uyarısı (oran + son 10 dk'daki Firefox yeniden başlatma bildirimi) ya da None."""
    from . import masaustu
    d = d if d is not None else masaustu.durum(dogrula=False, saglik=False, ad=ad)
    if not d:
        return None
    parcalar = []
    u = bellek_uyarisi(bellek_durumu(d.get("cgroup")), bool(_kayitlar(d.get("calisma") or "")))
    if u:
        parcalar.append(u)
    olay = _durum_oku(ad).get("son_yeniden_olay")
    if isinstance(olay, dict) and time.time() - float(olay.get("zaman") or 0) < OLAY_BILDIR_SN:
        parcalar.append(_("bellek için Firefox {saat} saatinde yeniden başlatıldı ({once} → {sonra} MB, {sekme} sekme "
                          "geri yüklendi); pencere kimlikleri değişti, yeniden gözlem yapın").format(
            saat=time.strftime("%H:%M", time.localtime(float(olay["zaman"]))), once=olay.get("once_mb"),
            sonra=olay.get("sonra_mb"), sekme=olay.get("sekme", "?")))
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
    kayitlar = [g for g in _kayitlar(calisma) if os.path.realpath(g.get("kopya") or "") != os.path.realpath(kopya)]
    kayitlar.append({"argv": [str(a) for a in temel], "env": {str(k): str(v) for k, v in (env or {}).items()},
                     "kopya": kopya, "ev": [list(x) if isinstance(x, (list, tuple)) else x for x in (ev or ())],
                     "pid": int(pid), "bas": surec_baslangic(pid)})
    gecici = _kayit_yolu(calisma) + f".{os.getpid()}.tmp"
    try:
        fd = os.open(gecici, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(kayitlar, f)
        os.replace(gecici, _kayit_yolu(calisma))
    except OSError:
        pass


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


def _sekme_sayisi(kopya: str) -> int | None:
    from .oturum.firefox import mozlz4_coz
    for ad in ("sessionstore.jsonlz4", os.path.join("sessionstore-backups", "recovery.jsonlz4")):
        ham = mozlz4_coz(os.path.join(kopya, ad))
        if ham:
            try:
                return sum(len(w.get("tabs") or []) for w in json.loads(ham).get("windows") or [])
            except (ValueError, AttributeError, TypeError):
                return None
    return None


def firefox_yeniden_baslat(d: dict, g: dict) -> dict:
    """Kayıttaki Firefox'u (g) oturum geri yüklemeli yeniden başlat. → {"ok", "neden"?, "pid"?, "sekme"?}."""
    from . import masaustu
    kopya = g.get("kopya") or ""
    cg = d.get("cgroup") or ""
    if not kopya or not os.path.isdir(kopya) or os.path.islink(kopya) or not cg:
        return {"ok": False, "neden": "kopya-yok"}
    ana_pid = firefox_ana_pidleri(cg, kopya)
    if not ana_pid:
        return {"ok": False, "neden": "firefox-yok"}
    tut = os.open(kopya, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)  # kopya bekçisi silmesin (kullanımda sayar)
    try:
        t0 = time.time()
        for p in ana_pid:
            try:
                os.kill(p, signal.SIGTERM)  # Firefox SIGTERM'de düzgün kapanır: oturumu sessionstore.jsonlz4'e yazar
            except OSError:
                pass
        if not _bekle(lambda: not any(_canli(p) for p in ana_pid), KAPANIS_SN):
            for p in ana_pid:
                try:
                    os.kill(p, signal.SIGKILL)
                except OSError:
                    pass
        _bekle(lambda: not _canli(int(g.get("pid") or 0), g.get("bas")), 5)
        oturum = os.path.join(kopya, "sessionstore.jsonlz4")
        taze = os.path.isfile(oturum) and os.path.getmtime(oturum) >= t0 - 1
        argv = list(g.get("argv") or [])
        uj = os.path.join(kopya, "user.js")
        try:
            with open(uj, encoding="utf-8") as f:
                icerik = f.read()
        except OSError:
            icerik = ""
        if _GERI_YUKLE not in icerik:
            with open(uj, "a", encoding="utf-8") as f:
                f.write(("\n" if icerik and not icerik.endswith("\n") else "") + _GERI_YUKLE)
        sekme = _sekme_sayisi(kopya)
        p = masaustu.baslat(argv, g.get("env") or None, kopya=kopya, ev=tuple(tuple(x) if isinstance(x, list) else x
                                                                             for x in (g.get("ev") or ())))
        ok = _bekle(lambda: bool(firefox_ana_pidleri(cg, kopya)) or p.poll() is not None, 15) and p.poll() is None
        if ok:
            _eski_bekciyi_durdur(kopya, int(g.get("pid") or 0))
        return {"ok": ok, "pid": p.pid, "sekme": sekme, "oturum_dosyasi": taze,
                **({} if ok else {"neden": "acilmadi"})}
    finally:
        os.close(tut)


# ---------------------------------------------------------------- bakım (boşta)

def _engel(ad: str | None) -> str | None:
    from . import masaustu
    if masaustu.devral_var(masaustu.devral_yolu(ad)):
        return "devral"
    try:
        from . import onay
        if onay.bekleyen_var("arka", masa=ad):
            return "onay"
    except Exception:  # noqa: BLE001 - karar verilemedi: dokunma
        return "onay?"
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


def bakim(ad: str | None = None, simdi: float | None = None, d: dict | None = None) -> dict | None:
    """Boşta masaüstünde bellek bakımı (bkz. modül belgesi). Masaüstünü KAPATMAZ. → yapılan iş özeti ya da None."""
    from . import masaustu
    from .gunluk import gunluk
    d = d if d is not None else masaustu.durum(saglik=False, ad=ad)
    if not d or not d.get("cgroup"):
        return None
    durum = bellek_durumu(d["cgroup"])
    if not durum or not durum["max"]:
        return None
    simdi = time.time() if simdi is None else simdi
    son = masaustu.son_kullanim(ad)
    if son is None or simdi - son < BOSTA_SN or durum["oran"] < RECLAIM_ORAN or _engel(ad):
        return None
    kayit = _durum_oku(ad)
    mb = 1 << 20
    if durum["oran"] >= YENIDEN_ORAN and ff_yeniden_acik() and \
            simdi - float(kayit.get("son_yeniden") or 0) >= YENIDEN_ARALIK_SN:
        kayitlar = [g for g in _kayitlar(d.get("calisma") or "") if g.get("kopya")]
        sonuc = [firefox_yeniden_baslat(d, g) for g in kayitlar]
        if any(s.get("ok") for s in sonuc):
            time.sleep(1)
            sonra = bellek_durumu(d["cgroup"]) or durum
            olay = {"zaman": simdi, "once_mb": durum["current"] // mb, "sonra_mb": sonra["current"] // mb,
                    "sekme": sum(s.get("sekme") or 0 for s in sonuc if s.get("ok"))}
            kayit.update(son_yeniden=simdi, son_yeniden_olay=olay)
            _durum_yaz(ad, kayit)
            _ONBELLEK.clear()
            gunluk(f"bellek | {ad or 'varsayılan'} Firefox yeniden başlatıldı: {olay['once_mb']} → "
                   f"{olay['sonra_mb']} MB, {olay['sekme']} sekme")
            return {"is": "firefox_yeniden", **olay, "sonuc": sonuc}
        if sonuc:
            kayit["son_yeniden"] = simdi  # başarısız deneme de 10 dk bekler (döngü yok)
            _durum_yaz(ad, kayit)
    if simdi - float(kayit.get("son_reclaim") or 0) >= RECLAIM_ARALIK_SN:
        ok = reclaim(d["cgroup"])
        kayit["son_reclaim"] = simdi
        _durum_yaz(ad, kayit)
        sonra = bellek_durumu(d["cgroup"]) or durum
        gunluk(f"bellek | {ad or 'varsayılan'} memory.reclaim {RECLAIM_MIKTAR}: {durum['current'] // mb} → "
               f"{sonra['current'] // mb} MB")
        return {"is": "reclaim", "ok": ok, "once_mb": durum["current"] // mb, "sonra_mb": sonra["current"] // mb}
    return None
