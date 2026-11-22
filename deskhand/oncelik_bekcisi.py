"""Öncelik bekçisi (arka plan masaüstü çekirdek bileşeni, iki türde de): bellek kafesindeki HER iş parçacığını düşük
öncelikte tutar: nice >= 10, gerçek zamanlı zamanlama yok (SCHED_FIFO/RR/DEADLINE → SCHED_OTHER), G/Ç sınıfı idle.

Birinci savunma kafesin kendisidir (nice 10 + ionice idle ile başlatma; KWin'e cap_sys_nice verilmez, RLIMIT_RTPRIO=0,
RLIMIT_NICE en düşük 10). Ama sistemdeki AD tabanlı öncelik kuralları (ör. ananicy-cpp: `kwin_wayland`, `Xwayland`,
tarayıcılar) kök olarak süreçleri yeniden yükseltebiliyor (ölçüldü: arka plandaki KWin nice -12'ye çekildi) ve KWin
yalnız `kwin_wayland` dosya adıyla çalıştığı için ad değiştirilemiyor. Bu bekçi onları kısa sürede geri düşürür:
arka plan masaüstü, oyun oynayan kullanıcıdan işlemci/disk çalmaz.

Tek başına betik (yalnız standart kitaplık), `python3 -I` ile çalışır; masaüstü kafesin içinde başlatır:
    python3 -I oncelik_bekcisi.py CGROUP_YOLU [ARALIK_SN]
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


def surecler(cg: str) -> list[int]:
    try:
        with open(os.path.join("/sys/fs/cgroup", cg.lstrip("/"), "cgroup.procs")) as f:
            return [int(x) for x in f.read().split()]
    except (OSError, ValueError):
        return []


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


def main(argv: list[str]) -> int:
    if not argv:
        print("kullanım: oncelik_bekcisi.py CGROUP_YOLU [ARALIK_SN]", file=sys.stderr)
        return 2
    cg = argv[0]
    aralik = float(argv[1]) if len(argv) > 1 else 0.5
    gorulen: set = set()
    tur(cg, gorulen)
    print("hazir", flush=True)
    while True:
        time.sleep(aralik)
        if not surecler(cg):
            return 0
        tur(cg, gorulen)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
