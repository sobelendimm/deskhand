"""Test yalıtımı: deskhand içe aktarılmadan ÖNCE tüm DESKHAND_*_DIR'leri geçici bir klasöre yönlendirir (gerçek ~/.config,
~/.local/state, ~/.cache, ~/.local/share yazılmaz), arayüz dilini Türkçeye sabitler (DESKHAND_DIL=tr) ve depo kökünü
sys.path'e ekler. Alt süreçler ortamı devralır.

Kullanım (her testin EN BAŞINDA):  import _yalitim  (ya da tests/ dışından: from tests import _yalitim)"""
import atexit
import os
import shutil
import sys
import tempfile

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GECICI = tempfile.mkdtemp(prefix="deskhand-test-")
DIZINLER = {ad: os.path.join(GECICI, ad.split("_")[1].lower())
            for ad in ("DESKHAND_CONFIG_DIR", "DESKHAND_STATE_DIR", "DESKHAND_CACHE_DIR", "DESKHAND_DATA_DIR", "DESKHAND_RUNTIME_DIR")}
os.environ.update(DIZINLER)
os.environ.pop("DESKHAND_HEDEF", None)
os.environ["DESKHAND_DIL"] = "tr"  # testler Türkçe metin bekler (kaynak dil); sistem dili ne olursa olsun
os.environ["PYTHONPATH"] = KOK + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")
if KOK not in sys.path:
    sys.path.insert(0, KOK)

if os.environ.get("DESKHAND_TEST_SAKLA") != "1":
    atexit.register(shutil.rmtree, GECICI, True)
