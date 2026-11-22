"""Test yalıtımı: deskhand içe aktarılmadan ÖNCE tüm DESKHAND_*_DIR'leri geçici bir klasöre yönlendirir (gerçek ~/.config,
~/.local/state, ~/.cache, ~/.local/share yazılmaz), arayüz dilini Türkçeye sabitler (DESKHAND_DIL=tr) ve depo kökünü
sys.path'e ekler. Alt süreçler ortamı devralır.

GERÇEK EKRAN KİLİDİ: içe aktarılınca DESKHAND_GERCEK_EKRAN=kapali ayarlanır (deskhand/hata.py gercek_ekran_denetle):
hedef vermeyi unutan bir ölçüm/test çağrısı kullanıcının GERÇEK masaüstüne (dotool, kdotool eylemi, uygulama açma, pano,
bildirim, ekran görüntüsü) EN ALT katmanda ulaşamaz → Dur 17. Görünmez masaüstü ve sahte arka uçlar etkilenmez. Gerçek
aracı SAHTE bir ikili/subprocess ile değiştiren bir test (ör. sahte dotool) kilidi kendi başına açar:
os.environ["DESKHAND_GERCEK_EKRAN"] = "acik"  (yalnız o testin içinde, gerekçesiyle). tests/ekranli/ kilidi kaldırır.

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
# Arka plan uygulamaları bwrap ad alanında (/tmp boş tmpfs): test pencerelerinin olay günlükleri (LOG) ve teste
# okunacak çıktıları YALNIZ bu dizine yazılır (arka_ortak.test_paylasimi ad alanına bağlar; dar: yalnız bu dizin).
PAYLASIM = os.path.join(GECICI, "paylasim")
os.mkdir(PAYLASIM, 0o700)
os.environ["DESKHAND_TEST_PAYLASIM"] = PAYLASIM
os.environ.pop("DESKHAND_HEDEF", None)
os.environ["DESKHAND_GERCEK_EKRAN"] = "kapali"  # alt süreçler devralır
# ajanın kendi istemcisi ipuçları (deskhand/kendi.py): testleri çalıştıran uçbirimin türü sonuçları değiştirmesin
for _ad in ("KONSOLE_DBUS_WINDOW", "WINDOWID", "TERM_PROGRAM", "GHOSTTY_RESOURCES_DIR", "KITTY_PID",
            "ALACRITTY_WINDOW_ID", "TMUX", "STY", "ZELLIJ"):
    os.environ.pop(_ad, None)
os.environ["DESKHAND_DIL"] = "tr"  # testler Türkçe metin bekler (kaynak dil); sistem dili ne olursa olsun
os.environ["PYTHONPATH"] = KOK + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")
if KOK not in sys.path:
    sys.path.insert(0, KOK)

if os.environ.get("DESKHAND_TEST_SAKLA") != "1":
    atexit.register(shutil.rmtree, GECICI, True)
