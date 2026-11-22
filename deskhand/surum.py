"""Çalışan kod ↔ diskteki kurulum sürümü. Uzun yaşayan süreçler (MCP sunucusu, panel) güncellemeden SONRA da eski kodu
çalıştırır: kullanıcı oturumunda MCP 0.7.1 bildirirken kurulu sürüm 0.8.x idi. İki yüzey:

  * get_status (MCP): diskteki `deskhand/__init__.py` sürümü ≠ çalışan `__version__` → "stale_server" alanı + "/mcp ile
    yeniden bağla" notu (eski_sunucu()).
  * doctor: bu kullanıcının çalışan `deskhand mcp` süreçleri (/proc; başka kullanıcının süreçlerine BAKILMAZ). Başka bir
    sürecin bellekteki sürümü okunamaz: süreç, paketin kaynak dosyaları (en yeni .py değişikliği) güncellenmeden ÖNCE
    başladıysa eski kodu çalıştırıyordur → "eski" (mcp_surecleri()).

SALT OKUNUR: hiçbir şey yazmaz, hiçbir süreci durdurmaz."""
from __future__ import annotations

import os
import re

from . import __version__

PAKET = os.path.dirname(os.path.abspath(__file__))
_SURUM = re.compile(r'''^__version__\s*=\s*["']([^"']+)["']''', re.M)


def kurulu_surum(paket: str = PAKET) -> str | None:
    """Diskteki `paket/__init__.py` içindeki __version__ (içe aktarmadan, metinden). Okunamazsa None."""
    try:
        with open(os.path.join(paket, "__init__.py"), encoding="utf-8") as f:
            m = _SURUM.search(f.read(8192))
    except OSError:
        return None
    return m.group(1) if m else None


def eski_sunucu(calisan: str = __version__, kurulu: str | None = None) -> dict | None:
    """Çalışan sürüm diskteki kurulumdan farklıysa {"running", "installed", "note"}; aynıysa (ya da okunamazsa) None."""
    from .i18n import _
    kurulu = kurulu_surum() if kurulu is None else kurulu
    if not kurulu or kurulu == calisan:
        return None
    return {"running": calisan, "installed": kurulu,
            "note": _("Bu MCP sunucusu eski kodu çalıştırıyor ({calisan}); kurulu sürüm {kurulu}. MCP'yi yeniden "
                      "bağla (/mcp).").format(calisan=calisan, kurulu=kurulu)}


def kaynak_mtime(paket: str = PAKET) -> float:
    """Paketin .py dosyalarının en yeni değişiklik zamanı (kurulum/güncelleme anı yaklaşığı)."""
    en = 0.0
    for d, alt, dosyalar in os.walk(paket):
        alt[:] = [a for a in alt if a != "__pycache__"]
        for f in dosyalar:
            if f.endswith(".py"):
                try:
                    en = max(en, os.stat(os.path.join(d, f)).st_mtime)
                except OSError:
                    pass
    return en


def _acilis_zamani() -> float:
    with open("/proc/stat") as f:
        for s in f:
            if s.startswith("btime "):
                return float(s.split()[1])
    return 0.0


def _baslangic(pid: str, btime: float) -> float | None:
    """Sürecin başlangıç zamanı (epoch sn): /proc/PID/stat 22. alan (açılıştan bu yana saat tıkı)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            veri = f.read()
    except OSError:
        return None
    alanlar = veri[veri.rfind(")") + 2:].split()  # comm boşluk/parantez içerebilir: son ')' sonrası 3. alandan başlar
    try:
        return btime + int(alanlar[19]) / os.sysconf("SC_CLK_TCK")
    except (IndexError, ValueError):
        return None


def _mcp_argv(argv: list[str]) -> list[str] | None:
    """`… deskhand mcp [seçenekler]` / `python -m deskhand mcp …` → deskhand'den sonraki argümanlar; değilse None.
    (bwrap komut satırındaki `deskhand-mcp-…desktop` gibi dosya adları EŞLEŞMEZ: öge tam `deskhand` olmalı.)"""
    for i, a in enumerate(argv):
        if os.path.basename(a) == "deskhand" or (a == "deskhand" and i and argv[i - 1] == "-m"):
            kalan = argv[i + 1:]
            ilk = next((k for k in kalan if not k.startswith("-")), None)
            return kalan if ilk == "mcp" else None
    return None


def mcp_surecleri(proc: str = "/proc", uid: int | None = None) -> list[dict]:
    """Bu kullanıcının çalışan `deskhand mcp` süreçleri: {pid, args, started, package, version, stale}.
    version: süreç güncellemeden sonra başladıysa diskteki sürüm; önce başladıysa None (bellekteki sürüm okunamaz,
    stale=True)."""
    uid = os.getuid() if uid is None else uid
    try:
        btime = _acilis_zamani()
    except OSError:
        btime = 0.0
    sonuc, mtimeler = [], {}
    for pid in os.listdir(proc):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            if os.stat(os.path.join(proc, pid)).st_uid != uid:
                continue  # başka kullanıcının süreci: bakılmaz
            with open(os.path.join(proc, pid, "cmdline"), "rb") as f:
                argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        kalan = _mcp_argv(argv)
        if kalan is None:
            continue
        paket = None
        for a in argv:
            if os.path.basename(a) == "deskhand" and os.sep in a:
                try:
                    if not os.path.isabs(a):
                        a = os.path.join(os.readlink(os.path.join(proc, pid, "cwd")), a)
                    aday = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(a))), "deskhand")
                except OSError:
                    continue
                paket = aday if os.path.isfile(os.path.join(aday, "__init__.py")) else None
                break
        paket = paket or PAKET
        bas = _baslangic(pid, btime)
        if paket not in mtimeler:
            mtimeler[paket] = kaynak_mtime(paket)
        eski = bas is not None and mtimeler[paket] > 0 and bas < mtimeler[paket]
        sonuc.append({"pid": int(pid), "args": " ".join(kalan), "started": bas, "package": paket,
                      "version": None if eski else kurulu_surum(paket), "installed": kurulu_surum(paket),
                      "stale": eski})
    return sorted(sonuc, key=lambda s: s["pid"])
