"""İpucu metinlerindeki komutlar: kullanıcının/ajanın OLDUĞU GİBİ çalıştırabileceği tam komut satırı (genel seçenekler
komuttan ÖNCE: `deskhand --desktop-name <ad> --background tree <kimlik>`). Eski `ekran …` adları ipuçlarında kullanılmaz."""
from __future__ import annotations

import os
import shlex


def komut(*argv: str) -> str:
    """→ "deskhand [--desktop-name AD] [--background] ALT-KOMUT ARG…" (geçerli masaüstü ve hedefe göre)."""
    parcalar = ["deskhand"]
    try:
        from . import masalar
        ad = masalar.secili()
    except Exception:  # noqa: BLE001
        ad = ""
    if ad:
        parcalar += ["--desktop-name", ad]
    arka = (os.environ.get("DESKHAND_HEDEF") or "").strip().lower() in ("arka", "sanal", "background")
    if arka or any(str(a).startswith("arka:") for a in argv):
        parcalar.append("--background")
    return " ".join(parcalar + [shlex.quote(str(a)) for a in argv])
