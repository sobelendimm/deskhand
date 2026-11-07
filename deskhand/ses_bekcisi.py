"""Ses bekçisi (sanal masaüstü çekirdek bileşeni): arka plan uygulamalarının ses akışı boş çıkıştan
(deskhand-sessiz-*) BAŞKA bir çıkışa düşerse (çıkış dışarıdan kaldırıldı, bir yönlendirici taşıdı…) akışı
hemen susturur ve kapatır: kullanıcının kulaklığına arka plandan ses SIZMAZ.

Birinci savunma ortam değişkenleridir (masaustu.uygulama_ortami: PULSE_PROP node.dont-fallback/dont-reconnect →
çıkış kalkınca akış öldürülür). Bu bekçi, bunları yok sayan istemciler için ikinci hattır.

Tek başına betik (yalnız standart kitaplık + pactl), `python3 -I` ile çalışır; masaustu.py kafesin içinde başlatır:
    python3 -I ses_bekcisi.py KAFES        (KAFES: systemd kapsam adı, boş olabilir)
Hazır olunca stdout'a "hazir" yazar. Akış "bizim" sayılır: özelliklerinde deskhand.sanal=1 VAR ya da isteyen
sürecin cgroup'u kafesin içinde. `pactl subscribe` olaylarıyla çalışır (yoklama yok); pactl ölürse yeniden başlatır.
"""
from __future__ import annotations

import json
import select
import signal
import subprocess
import sys
import time

ONEK = "deskhand-sessiz"


def _pactl_json(*a) -> list:
    try:
        r = subprocess.run(["pactl", "-f", "json", *a], capture_output=True, text=True, timeout=5)
        v = json.loads(r.stdout or "[]")
        return v if isinstance(v, list) else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def _komut(*a) -> bool:
    try:
        return subprocess.run(list(a), capture_output=True, timeout=3).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _pactl(*a) -> bool:
    return _komut("pactl", *a)


def _kafeste(pid, kafes: str) -> bool:
    if not kafes:
        return False
    try:
        with open(f"/proc/{int(pid)}/cgroup") as f:
            return any(s.startswith("0::") and s.strip().endswith("/" + kafes) for s in f)
    except (OSError, ValueError, TypeError):
        return False


def bizim_mi(girdi: dict, kafes: str) -> bool:
    p = girdi.get("properties") or {}
    return str(p.get("deskhand.sanal", "")) == "1" or _kafeste(p.get("application.process.id"), kafes)


def kacaklar(girdiler: list, cikislar: dict, kafes: str) -> list[dict]:
    """Bizim olup boş çıkışta OLMAYAN akışlar (cikislar: index → ad)."""
    return [g for g in girdiler if bizim_mi(g, kafes) and not str(cikislar.get(g.get("sink"), "")).startswith(ONEK)]


_YOK_EDILEN: set[str] = set()


def denetle(kafes: str) -> int:
    """Kaçak akışları sustur (pactl, anında) ve yok et (pw-cli destroy <object.id>: istemci "Entity killed" alır;
    pactl'de kill-sink-input yok). Susturulmuş + yok edilmeye çalışılmış akışa yeniden dokunulmaz (olay döngüsü
    kendini beslemesin); uygulama sesini yeniden açarsa yine susturulur."""
    cikislar = {s.get("index"): s.get("name", "") for s in _pactl_json("list", "sinks", "short")}
    n = 0
    for g in kacaklar(_pactl_json("list", "sink-inputs"), cikislar, kafes):
        i = str(g.get("index"))
        oid = str((g.get("properties") or {}).get("object.id") or "")
        ad = f"#{i} ({(g.get('properties') or {}).get('application.name', '?')})"
        if not g.get("mute") and _pactl("set-sink-input-mute", i, "1"):
            n += 1
            _yaz(f"akış {ad} boş çıkışta değildi ({cikislar.get(g.get('sink'), g.get('sink'))}): susturuldu")
        if oid and oid not in _YOK_EDILEN:
            _YOK_EDILEN.add(oid)
            n += 1
            _yaz(f"akış {ad}: " + ("kapatıldı" if _komut("pw-cli", "destroy", oid) else "kapatılamadı (susturulmuş kalır)"))
    return n


def _yaz(m: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {m}", file=sys.stderr, flush=True)


def _ilgili(satir: str) -> bool:
    return ("sink-input" in satir and ("'new'" in satir or "'change'" in satir)) or \
        ("on sink #" in satir and "'remove'" in satir)


def main(argv: list[str]) -> int:
    kafes = argv[1] if len(argv) > 1 else ""
    alt: list[subprocess.Popen] = []

    def cik(*_a):
        for p in alt:
            try:
                p.kill()
            except OSError:
                pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, cik)
    signal.signal(signal.SIGINT, cik)
    hazir = False
    while True:
        try:
            p = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError as e:
            print(f"pactl başlatılamadı: {e}", file=sys.stderr, flush=True)
            if not hazir:
                print("pactl-yok", flush=True)
            return 1
        alt[:] = [p]
        denetle(kafes)  # abonelikten ÖNCE kaçan olmasın: abonelik açıldıktan sonra bir tur
        if not hazir:
            print("hazir", flush=True)
            sys.stdout.close()
            hazir = True
        assert p.stdout is not None
        while True:
            satir = p.stdout.readline()
            if not satir:
                break
            if not _ilgili(satir):
                continue
            # aynı anda gelen olayları birleştir (taşınan her akış bir 'change' üretir)
            while select.select([p.stdout], [], [], 0.01)[0]:
                if not p.stdout.readline():
                    break
            denetle(kafes)
        p.wait()
        time.sleep(1.0)  # ses sunucusu yeniden başlıyor olabilir


if __name__ == "__main__":
    sys.exit(main(sys.argv))
