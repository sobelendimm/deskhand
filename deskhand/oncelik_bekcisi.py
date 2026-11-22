"""Öncelik bekçisi (arka plan masaüstü çekirdek bileşeni, iki türde de): bellek kafesindeki HER iş parçacığını düşük
öncelikte tutar: nice >= 10, gerçek zamanlı zamanlama yok (SCHED_FIFO/RR/DEADLINE → SCHED_OTHER), G/Ç sınıfı idle.

Birinci savunma kafesin kendisidir (nice 10 + ionice idle ile başlatma; KWin'e cap_sys_nice verilmez, RLIMIT_RTPRIO=0,
RLIMIT_NICE en düşük 10). Ama sistemdeki AD tabanlı öncelik kuralları (ör. ananicy-cpp: `kwin_wayland`, `Xwayland`,
tarayıcılar) kök olarak süreçleri yeniden yükseltebiliyor (ölçüldü: arka plandaki KWin nice -12'ye çekildi) ve KWin
yalnız `kwin_wayland` dosya adıyla çalıştığı için ad değiştirilemiyor. Bu bekçi onları kısa sürede geri düşürür:
arka plan masaüstü, oyun oynayan kullanıcıdan işlemci/disk çalmaz.

İkinci görev (ölü oturum temizliği): --izle PID BAŞLANGIÇ ile ekran sunucusu (KWin / Xvfb) izlenir; SIGKILL/OOM ile
ölürse kafes boşaltılır (SIGTERM, 2 sn, SIGKILL), oturumun X soket/kilitleri (--x N: kilit içeriği ölen PID ise) ve
çalışma dizini (--dizin) silinir, bekçi çıkar. Böylece dbus-daemon / bekçiler / at-spi süresiz kalmaz.

Tek başına betik (yalnız standart kitaplık), `python3 -I` ile çalışır; masaüstü kafesin içinde başlatır:
    python3 -I oncelik_bekcisi.py CGROUP_YOLU [--aralik SN] [--izle PID BAŞLANGIÇ] [--x N] [--dizin YOL]
Hazır olunca stdout'a "hazir" yazar; düzelttiği her iş parçacığını stderr'e (masaüstü günlüğü) bir kez yazar.
Yalnız kafesin cgroup.procs listesindeki süreçlere dokunur (kendi kullanıcının süreçleri; yükseltme YOK, yalnız düşürme).
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

EN_AZ_NICE = 10
GERCEK_ZAMANLI = (1, 2, 6)  # SCHED_FIFO, SCHED_RR, SCHED_DEADLINE
IOPRIO_CLASS_IDLE = 3
IOPRIO_WHO_PROCESS = 1
SYS_IOPRIO_SET, SYS_IOPRIO_GET = 251, 252  # x86_64
_libc = ctypes.CDLL(None, use_errno=True)


def _ioprio_al(tid: int) -> int:
    return _libc.syscall(SYS_IOPRIO_GET, IOPRIO_WHO_PROCESS, tid)


def _ioprio_idle(tid: int) -> None:
    _libc.syscall(SYS_IOPRIO_SET, IOPRIO_WHO_PROCESS, tid, IOPRIO_CLASS_IDLE << 13)


OKUMA_HATASI_AZAMI = 60  # art arda bu kadar okuma hatası (aralık 0,5 sn → ~30 sn) sonra bekçi çıkar


def surecler_oku(cg: str) -> list[int] | None:
    """Kafesteki süreçler. [] = kafes boş ya da kaldırılmış (cgroup.procs yok); None = GEÇİCİ okuma hatası (EMFILE,
    EINTR, ENOMEM, bozuk içerik…): bilinmiyor. Önceden ikisi de [] dönüyordu ve tek bir geçici hata bekçiyi
    'kafes boş' sanıp çıkarıyordu (arka plan masaüstü öncelik korumasız kalıyordu)."""
    try:
        with open(os.path.join("/sys/fs/cgroup", cg.lstrip("/"), "cgroup.procs")) as f:
            return [int(x) for x in f.read().split()]
    except (FileNotFoundError, NotADirectoryError):
        return []
    except (OSError, ValueError):
        return None


def surecler(cg: str) -> list[int]:
    return surecler_oku(cg) or []


def is_parcaciklari(pid: int):
    try:
        for t in os.listdir(f"/proc/{pid}/task"):
            try:
                with open(f"/proc/{pid}/task/{t}/stat") as f:
                    a = f.read().rsplit(")", 1)[1].split()
                yield int(t), int(a[16]), int(a[38])
            except (OSError, ValueError, IndexError):
                continue
    except OSError:
        return


def tur(cg: str, gorulen: set) -> int:
    """Bir tarama: kafesteki yükseltilmiş iş parçacıklarını düşür. → düzeltilen sayısı."""
    n = 0
    for pid in surecler(cg):
        for tid, nice, politika in is_parcaciklari(pid):
            duzeldi = False
            try:
                if politika in GERCEK_ZAMANLI:
                    os.sched_setscheduler(tid, os.SCHED_OTHER | getattr(os, "SCHED_RESET_ON_FORK", 0x40000000),
                                          os.sched_param(0))
                    duzeldi = True
                if nice < EN_AZ_NICE:
                    os.setpriority(os.PRIO_PROCESS, tid, EN_AZ_NICE)
                    duzeldi = True
                io = _ioprio_al(tid)
                if io >= 0 and (io >> 13) != IOPRIO_CLASS_IDLE:
                    _ioprio_idle(tid)
                    duzeldi = True
            except OSError:
                continue
            if duzeldi:
                n += 1
                if tid not in gorulen:
                    gorulen.add(tid)
                    try:
                        with open(f"/proc/{pid}/comm") as f:
                            ad = f.read().strip()
                    except OSError:
                        ad = "?"
                    print(f"oncelik-bekcisi: {ad} ({pid}/{tid}) düşürüldü (nice {nice}, politika {politika})",
                          file=sys.stderr, flush=True)
    return n


def _baslangic(pid: int) -> str | None:
    try:
        with open(f"/proc/{pid}/stat") as f:
            v = f.read()
        return v[v.rindex(")") + 2:].split()[19]
    except (OSError, ValueError, IndexError):
        return None


def kesin_olu(pid: int, bas: str | None) -> bool:
    """İzlenen sunucu KESİN ölü mü: süreç yok (/proc/<pid> yok, ESRCH), zombi/ölü, ya da başlangıç zamanı farklı (PID
    başka sürece geçmiş). /proc/<pid>/stat GEÇİCİ okunamıyorsa (EACCES, EAGAIN, bellek baskısı…) ölü SAYILMAZ: canlı
    oturum kapatılmaz (denetim 12c O3)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            v = f.read()
    except (FileNotFoundError, ProcessLookupError):
        return True
    except OSError:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            pass
        return False
    try:
        alanlar = v[v.rindex(")") + 2:].split()
        durum, baslangic = alanlar[0], alanlar[19]
    except (ValueError, IndexError):
        return False  # yarım okuma: bir sonraki turda yeniden bakılır
    return durum in ("X", "Z") or (bas is not None and baslangic != bas)


def _durum(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return "X"


def oturumu_kapat(cg: str, pid: int, xno: int | None, dizin: str | None) -> None:
    """Ekran sunucusu öldü: kafesteki her şeyi (bu bekçi hariç) kapat, X soket/kilitlerini ve çalışma dizinini sil."""
    import signal
    import shutil
    ben = os.getpid()
    hedef = [p for p in surecler(cg) if p != ben]
    for p in hedef:
        try:
            os.kill(p, signal.SIGTERM)
        except OSError:
            pass
    bitis = time.monotonic() + 2.0
    while time.monotonic() < bitis and any(_durum(p) not in ("X", "Z") for p in surecler(cg) if p != ben):
        time.sleep(0.05)
    for p in surecler(cg):
        if p != ben:
            try:
                os.kill(p, signal.SIGKILL)
            except OSError:
                pass
    if xno is not None:
        for n in (xno, xno + 1):
            kilit = f"/tmp/.X{n}-lock"
            try:
                with open(kilit) as f:
                    sahip = int(f.read().strip() or 0)
            except (OSError, ValueError):
                continue
            if sahip == pid:  # yalnız ÖLEN sunucunun kilidi: başkasınınkine dokunulmaz
                for y in (kilit, f"/tmp/.X11-unix/X{n}"):
                    try:
                        os.unlink(y)
                    except OSError:
                        pass
    if dizin and os.path.basename(dizin.rstrip("/")).startswith(("kwin-", "sanal-")) and os.path.isdir(dizin):
        shutil.rmtree(dizin, ignore_errors=True)
    print(f"oncelik-bekcisi: ekran sunucusu ({pid}) öldü; oturum kapatıldı", file=sys.stderr, flush=True)


def main(argv: list[str]) -> int:
    if not argv:
        print("kullanım: oncelik_bekcisi.py CGROUP_YOLU [--aralik SN] [--izle PID BAŞLANGIÇ] [--x N] [--dizin YOL]",
              file=sys.stderr)
        return 2
    cg = argv[0]
    aralik, izle, bas, xno, dizin = 0.5, None, None, None, None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--aralik":
            aralik, i = float(argv[i + 1]), i + 2
        elif a == "--izle":
            izle, bas, i = int(argv[i + 1]), argv[i + 2], i + 3
        elif a == "--x":
            xno, i = int(argv[i + 1]), i + 2
        elif a == "--dizin":
            dizin, i = argv[i + 1], i + 2
        else:
            print(f"bilinmeyen argüman: {a}", file=sys.stderr)
            return 2
    gorulen: set = set()
    tur(cg, gorulen)
    print("hazir", flush=True)
    hata = 0
    while True:
        time.sleep(aralik)
        if izle is not None and kesin_olu(izle, bas):
            oturumu_kapat(cg, izle, xno, dizin)
            return 0
        liste = surecler_oku(cg)
        if liste is None:  # geçici okuma hatası: kafes boş SAYILMAZ (bekçi sürer)
            hata += 1
            if hata >= OKUMA_HATASI_AZAMI:
                print(f"oncelik-bekcisi: kafes {hata} kez okunamadı; çıkılıyor", file=sys.stderr, flush=True)
                return 1
            continue
        hata = 0
        if not liste:
            return 0
        tur(cg, gorulen)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
