"""KWin/Xvfb test penceresinin (kwin_test_pencere.py) renkleri — tek kaynak (UX-K).

Piksel algılayan testler (test_kwin_oturum, test_arka_kwin, test_olcek, olcum_arka_tur) ögeleri bu renklerle bulur.
Palet panelin koyu temasıyla uyumlu ve sakin (Breeze mavisi düğme, yumuşak turuncu alan, ince yeşil çerçeve); algılanan
renkler birbirinden ve zeminlerden (pencere zemini, KWin siyah kök, Xvfb gri kök) CIEDE2000 ≥ tokens.json
`renk_ayrim_min_de` (test_tema denetler)."""

ZEMIN = (0x23, 0x26, 0x29)        # pencere zemini (koyu tema Base)
METIN = (0xef, 0xf0, 0xf1)        # başlık/metin
CERCEVE = (0x27, 0xae, 0x60)      # metin kutusu çerçevesi (yeşil)
DUGME = (0x3d, 0xae, 0xe9)        # "Kaydet" düğmesi (Breeze mavisi)
DUGME_METIN = (0x0b, 0x18, 0x23)  # düğme yazısı (koyu tema vurgu_metin)
ALAN = (0xd9, 0x82, 0x2b)         # tekerlek/fare alanı (yumuşak turuncu)
ALGILANAN = {"cerceve": CERCEVE, "dugme": DUGME, "alan": ALAN}


def hex_(r) -> str:
    return "#%02x%02x%02x" % r
