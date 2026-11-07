"""Deskhand'nin başlattığı Flatpak örnekleri: kayıt, bellek sınırı, kapatma.

Sorun: `flatpak run` kendini systemd'nin özel soketiyle `app-flatpak-<kimlik>-<pid>.scope`'a taşır → Deskhand'nin
bellek kafesinden çıkar (sınır yok), `masaustu durdur` onu görmez, kopya uygulama yaşarken silinirdi.

Çözüm: arka planda başlatılan her Flatpak komutu bu dosyanın SARMALAYICISIYLA çalışır (`sarmala(argv)` → argv):
  1. başlatmadan önce `flatpak ps --columns=instance,pid,application` anlık görüntüsü,
  2. komutu ÇOCUK olarak başlat (`--die-with-parent` varsa sarmalayıcı ölünce uygulama da ölür),
  3. yeni örneği bul (PID eşleşmesi ya da kimlik + yeni örnek no), RUNTIME_DIR/oturum/flatpak.json'a kaydet,
  4. örneğin scope'una `systemctl --user --runtime set-property <scope> MemoryMax=<sınır> MemorySwapMax=0`
     (yapılamazsa günlüğe uyarı),
  5. çocuğu bekle; SIGTERM gelirse (masaustu durdur) önce kendi örneğini `flatpak kill` ile kapat.
`kapat_hepsi()` (oturum.kapanis) kayıtlı örnekleri `flatpak kill <örnek>` ile kapatır ve bitmelerini bekler
(en çok ~5 sn); kopyalar ANCAK bundan sonra silinir.

Bu dosya sarmalayıcı olarak `python3 -I <bu dosya> …` ile ÇALIŞTIRILIR: üst düzeyde yalnız standart kitaplık.
Kullanıcının kendi Flatpak örneklerine DOKUNULMAZ: yalnız kayıttaki (örnek no + PID + kimlik üçü birden uyan)
örnekler kapatılır.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

KAYIT_AD = "flatpak.json"
_KILIT_AD = "flatpak.lock"


def _gercek_ortam() -> dict:
    """flatpak/systemctl kullanıcı yöneticisine GERÇEK oturum veri yolundan gitsin (sanal masaüstü içinden
    çağrılsa bile; özel veri yolunda systemd yok)."""
    e = dict(os.environ)
    rt = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    e["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={rt}/bus"
    return e


def _uyar(metin: str) -> None:
    """Günlüğe (Deskhand günlüğü içe aktarılabiliyorsa) ve stderr'e (uygulama çıktı dosyası) yaz."""
    print(f"deskhand flatpak: {metin}", file=sys.stderr, flush=True)
    try:
        from deskhand.gunluk import gunluk
    except Exception:  # noqa: BLE001
        try:
            from ..gunluk import gunluk  # paket içinden içe aktarıldıysa
        except Exception:  # noqa: BLE001
            return
    gunluk(f"oturum flatpak | {metin}")


# ------------------------------------------------------------------ flatpak ps

def ornekler(timeout: float = 5) -> list[dict] | None:
    """Çalışan Flatpak örnekleri [{instance, pid, application}]; flatpak yok → []; sorgu başarısız → None."""
    if not shutil.which("flatpak"):
        return []
    try:
        r = subprocess.run(["flatpak", "ps", "--columns=instance,pid,application"], capture_output=True,
                           text=True, timeout=timeout, env=_gercek_ortam(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    sonuc = []
    for satir in r.stdout.splitlines():
        p = satir.split()
        if len(p) < 3 or not p[1].isdigit():
            continue  # başlık / bozuk satır
        sonuc.append({"instance": p[0], "pid": int(p[1]), "application": p[2]})
    return sonuc


# ------------------------------------------------------------------ kayıt dosyası

class _Kilit:
    def __init__(self, kayit: str):
        self.yol = os.path.join(os.path.dirname(kayit), _KILIT_AD)

    def __enter__(self):
        os.makedirs(os.path.dirname(self.yol), mode=0o700, exist_ok=True)
        self.f = open(self.yol, "a")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def oku(kayit: str) -> list[dict]:
    try:
        with open(kayit) as f:
            veri = json.load(f)
        return [g for g in veri if isinstance(g, dict) and g.get("instance")] if isinstance(veri, list) else []
    except (OSError, ValueError):
        return []


def _yaz(kayit: str, girdiler: list[dict]) -> None:
    os.makedirs(os.path.dirname(kayit), mode=0o700, exist_ok=True)
    gecici = f"{kayit}.{os.getpid()}.tmp"
    with open(gecici, "w") as f:
        json.dump(girdiler, f, indent=1)
    os.chmod(gecici, 0o600)
    os.replace(gecici, kayit)


def kaydet(kayit: str, girdi: dict) -> None:
    with _Kilit(kayit):
        girdiler = [g for g in oku(kayit) if g.get("instance") != girdi.get("instance")]
        girdiler.append(girdi)
        _yaz(kayit, girdiler)


def kayitli_ornekler(kayit: str) -> set[str]:
    return {g["instance"] for g in oku(kayit)}


# ------------------------------------------------------------------ scope + bellek

def scope_bul(pid: int, uygulama: str, proc_koku: str = "/proc") -> str | None:
    """Örneğin systemd scope birimi: /proc/<pid>/cgroup'tan `app-flatpak-<kimlik>-*.scope`. cgroup okunamazsa
    flatpak'ın adlandırması (`app-flatpak-<kimlik>-<pid>.scope`). Okunur ama Flatpak scope'u DEĞİLSE None (başka
    bir birime — örn. kullanıcının terminaline — sınır uygulanmasın)."""
    try:
        with open(os.path.join(proc_koku, str(pid), "cgroup")) as f:
            satirlar = f.read().splitlines()
    except OSError:
        return f"app-flatpak-{uygulama}-{pid}.scope"
    desen = re.compile(r"^app-flatpak-" + re.escape(uygulama) + r"-\d+\.scope$")
    for satir in satirlar:
        for parca in reversed(satir.split(":", 2)[-1].split("/")):
            if desen.match(parca):
                return parca
    return None


def bellek_uygula(scope: str, bellek: str) -> str | None:
    """Scope'a MemoryMax + takassız sınır (geçici: --runtime, ~/.config'e yazmaz). → uyarı metni ya da None."""
    if not shutil.which("systemctl"):
        return f"systemctl yok: {scope} bellek sınırı uygulanamadı"
    try:
        r = subprocess.run(["systemctl", "--user", "--runtime", "set-property", scope, f"MemoryMax={bellek}",
                            "MemorySwapMax=0"], capture_output=True, text=True, timeout=10, env=_gercek_ortam(),
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return f"{scope} bellek sınırı uygulanamadı: {e}"
    if r.returncode != 0:
        return f"{scope} bellek sınırı uygulanamadı: {(r.stderr or r.stdout).strip()[:200]}"
    return None


# ------------------------------------------------------------------ kapatma

def _canli(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _flatpak_kill(ornek: str) -> str | None:
    try:
        r = subprocess.run(["flatpak", "kill", ornek], capture_output=True, text=True, timeout=10,
                           env=_gercek_ortam(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)
    return None if r.returncode == 0 else (r.stderr or r.stdout).strip()[:200]


def kapat_hepsi(kayit: str, sure: float = 5.0) -> tuple[list[dict], list[dict], list[str]]:
    """Kayıttaki örnekleri kapat ve bitmelerini bekle. → (kapanan, kalan, uyarılar). Kalanlar kayıtta kalır.
    Yalnız örnek no + PID + kimlik ÜÇÜ BİRDEN `flatpak ps` ile uyan örneğe dokunulur."""
    with _Kilit(kayit):
        girdiler = oku(kayit)
        if not girdiler:
            return [], [], []
        uyarilar: list[str] = []
        simdiki = ornekler()
        if simdiki is None:
            uyarilar.append("flatpak ps sorgulanamadı; kayıtlı örnekler doğrulanamadı, kapatılmadı")
            return [], girdiler, uyarilar
        canli = {(o["instance"], o["pid"], o["application"]) for o in simdiki}
        hedef = [g for g in girdiler if (g["instance"], g.get("pid"), g.get("application")) in canli]
        for g in hedef:
            hata = _flatpak_kill(g["instance"])
            if hata:
                uyarilar.append(f"flatpak kill {g['instance']} ({g.get('application')}): {hata}")
        bitis = time.monotonic() + sure
        kalan = list(hedef)
        while kalan:
            simdiki = ornekler()
            if simdiki is None:  # sorgu başarısız: PID canlılığına bak
                kalan = [g for g in kalan if g.get("pid") and _canli(g["pid"])]
            else:
                hala = {o["instance"] for o in simdiki}
                kalan = [g for g in kalan if g["instance"] in hala]
            if not kalan or time.monotonic() >= bitis:
                break
            time.sleep(0.1)
        for g in kalan:
            uyarilar.append(f"{g.get('application')} örneği {g['instance']} {sure:.0f} sn içinde kapanmadı")
        kapanan = [g for g in girdiler if g not in kalan]
        _yaz(kayit, kalan)
        return kapanan, kalan, uyarilar


# ------------------------------------------------------------------ sarmalayıcı

def sarmala(argv: list[str], uygulama: str, kayit: str, bellek: str | None, kopya_yolu: str | None = None,
            sure: float = 20.0) -> list[str]:
    """Flatpak komutunu kayıt sarmalayıcısıyla çalıştıracak argv (BAŞLATMAZ)."""
    ek = ["--kayit", kayit, "--uygulama", uygulama, "--sure", f"{sure:g}"]
    if bellek:
        ek += ["--bellek", bellek]
    if kopya_yolu:
        ek += ["--kopya", kopya_yolu]
    return [sys.executable, "-I", os.path.abspath(__file__), *ek, "--", *argv]


def _yeni_ornek(once: set[str], cocuk_pid: int, uygulama: str) -> dict | None:
    simdiki = ornekler() or []
    for o in simdiki:  # 1) flatpak run exec ile bwrap'e geçer: örneğin PID'i = çocuğun PID'i
        if o["pid"] == cocuk_pid and o["instance"] not in once:
            return o
    for o in simdiki:  # 2) gio launch gibi aracılar: aynı kimlikle yeni örnek
        if o["application"] == uygulama and o["instance"] not in once:
            return o
    return None


def ana(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="deskhand-flatpak", allow_abbrev=False)
    p.add_argument("--kayit", required=True)
    p.add_argument("--uygulama", required=True)
    p.add_argument("--bellek")
    p.add_argument("--kopya")
    p.add_argument("--sure", type=float, default=20.0)
    p.add_argument("komut", nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    komut = a.komut[1:] if a.komut[:1] == ["--"] else a.komut
    if not komut:
        print("deskhand flatpak: komut yok", file=sys.stderr)
        return 2
    once = {o["instance"] for o in (ornekler() or [])}
    cocuk = subprocess.Popen(komut)
    bulunan: dict = {}

    def dur(signum, _frame):
        if bulunan.get("instance"):
            # kafes kapatılırken: örneği kapat ve (en çok 2 sn) bitmesini bekle — masaustu kafes boşalana dek
            # bekleyip ses çıkışını ondan sonra kaldırır; uygulama sarmalayıcıdan önce ölmüş olsun
            _flatpak_kill(bulunan["instance"])
            son = time.monotonic() + 2
            while time.monotonic() < son:
                simdiki = ornekler(timeout=2)
                if simdiki is not None and bulunan["instance"] not in {o["instance"] for o in simdiki}:
                    break
                time.sleep(0.1)
        try:
            cocuk.terminate()
        except OSError:
            pass
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, dur)
    signal.signal(signal.SIGHUP, dur)
    bitis = time.monotonic() + a.sure
    while time.monotonic() < bitis:
        o = _yeni_ornek(once, cocuk.pid, a.uygulama)
        if o:
            bulunan.update(o)
            break
        kod = cocuk.poll()
        if kod is not None and kod != 0:
            break  # komut hata verdi; örnek gelmeyecek
        time.sleep(0.2)
    if bulunan:
        scope = scope_bul(bulunan["pid"], bulunan["application"])
        girdi = {**bulunan, "scope": scope, "kopya": a.kopya, "sarmalayici": os.getpid(), "zaman": int(time.time())}
        kaydet(a.kayit, girdi)
        if a.bellek and scope:
            u = bellek_uygula(scope, a.bellek)
            if u:
                _uyar(u)
        elif a.bellek:
            _uyar(f"{bulunan['application']} örneğinin Flatpak scope'u bulunamadı; bellek sınırı uygulanmadı")
    else:
        _uyar(f"{a.uygulama}: {a.sure:g} sn içinde Flatpak örneği bulunamadı; kayıt/bellek sınırı yok")
    try:
        return cocuk.wait()
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    # Sarmalayıcı olarak: paket kökünü (yalnız bu dosyanın deposu) günlük için yola ekle (-I ile PYTHONPATH yok)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    raise SystemExit(ana(sys.argv[1:]))
