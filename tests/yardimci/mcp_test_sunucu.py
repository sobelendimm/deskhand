"""MCP sunucusu, test için sahte meşgul/onay ile (YALNIZ testler: tests/test_mcp.py stdio alt süreci olarak başlatır).

- mesgul: gerçek D-Bus/KWin sorgusu ve bildirim YOK. durum() hep "meşgul (tam ekran)"; karar() =
  $DESKHAND_RUNTIME_DIR/sahte-karar dosyasındaki değer (on|arka|sonra; yoksa "arka").
- onay: $DESKHAND_RUNTIME_DIR/sahte-onay dosyası  yok → GERÇEK onay modülü (panel kapalı → red),
  "izin"/"red" → sahte yanıt, "modul-yok" → onay modülü yokmuş gibi.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from deskhand import mcp_sunucu, mesgul, onay, yollar  # noqa: E402


def _oku(ad):
    try:
        with open(os.path.join(yollar.runtime_dir(), ad)) as f:
            return f.read().strip()
    except OSError:
        return None


def sahte_durum(esik=None):
    return {"mesgul": True, "nedenler": ["tam_ekran", "medya"], "ayrinti": {}}


def sahte_karar(ozet):
    return _oku("sahte-karar") or "arka"


def sahte_karar_ayrintili(ozet, *a, **k):
    return {"karar": sahte_karar(ozet), "neden": "test: sahte karar", "soruldu": False, "durum": sahte_durum()}


mesgul.durum = sahte_durum
mesgul.karar = sahte_karar
mesgul.karar_ayrintili = sahte_karar_ayrintili

_gercek_iste_sonuc = onay.iste_sonuc


def sahte_iste_sonuc(eylem, hedef, ayrinti="", masaustu="ekran", sure=120, goruntu=None, gunluge_yaz=True):
    v = _oku("sahte-onay")
    with open(os.path.join(yollar.runtime_dir(), "onay-istekleri.log"), "a") as f:
        f.write(f"{eylem} | {hedef} | {masaustu} | {ayrinti[:200]}\n")
    if v in ("izin", "red"):
        return onay.OnaySonucu(v == "izin", v)
    return _gercek_iste_sonuc(eylem, hedef, ayrinti, masaustu, sure, goruntu, gunluge_yaz)


onay.iste_sonuc = sahte_iste_sonuc


# testte GERÇEK oturum köprüsü HİÇ kullanılmaz (gerçek uygulama verisine dokunmasın): sahte köprü her uygulamaya
# "paylas" der (komut değişmez, ortam eklenmez). $DESKHAND_RUNTIME_DIR/sahte-oturum = "yok" → köprü yokmuş gibi.
class _SahteOturum:
    @staticmethod
    def hazirla(uygulama, gorev_siteleri=None, ham_komut=False):
        from types import SimpleNamespace
        return SimpleNamespace(karar="paylas", argv=[], env_ek={}, aciklama="test: sahte oturum", kopya_yolu=None)


mcp_sunucu._oturum = lambda: None if _oku("sahte-oturum") == "yok" else _SahteOturum
# open_app yalnız .desktop girdisi başlatır: test girdileri geçici dizinde (gerçek uygulamalar listelenmez)
if os.environ.get("DESKHAND_TEST_UYGULAMA_DIZINI"):
    from deskhand import uygulama  # noqa: E402
    uygulama.UYGULAMA_DIZINLERI = (os.environ["DESKHAND_TEST_UYGULAMA_DIZINI"],)
_gercek_onay = mcp_sunucu._onay
mcp_sunucu._onay = lambda: None if _oku("sahte-onay") == "modul-yok" else _gercek_onay()

if __name__ == "__main__":
    mcp_sunucu.main()
