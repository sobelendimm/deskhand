"""Sağlık sekmesi (UX-F O6): üstte tek özet kartı ("Her şey hazır ✓" / "2 sorun var"), sorunlu bileşenler önde ve
insan adıyla, yanında "Kopyala" ile kurulum komutu; tam liste (paket/araç adlarıyla) katlı "Tüm bileşenler" altında."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                             QPushButton, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from ...i18n import _
from .. import metinler as T
from ..dil import Metinler
from .. import saglik as S
from ..ortak import (YESIL, KIRMIZI, SARI, Isci, nokta)

_BOSLUK, _HEDEF = 8, 28
KISA_SINIR = 70  # sorun satırındaki doctor ayrıntısının en çok uzunluğu (karakter)


def _pano_yaz(metin: str) -> None:
    QApplication.clipboard().setText(metin)


# =========================================================================== Sağlık

class SaglikSekmesi(QWidget):
    def __init__(self, parent=None, denetle=S.tam_denetim, pano=None):
        super().__init__(parent)
        self.denetle_f = denetle
        self.pano = pano or _pano_yaz  # testler sahte pano verir
        self._isci: Isci | None = None
        self.sonuc: list[dict] = []
        self.sorun_satirlari: list[dict] = []
        self.mt = Metinler()
        kok = QVBoxLayout(self)
        kok.setSpacing(_BOSLUK)

        # ---- özet kartı
        self.kart = QFrame()
        self.kart.setObjectName("saglikKart")
        self.kart.setFrameShape(QFrame.Shape.StyledPanel)
        kl = QVBoxLayout(self.kart)
        kl.setContentsMargins(12, 12, 12, 12)
        kl.setSpacing(_BOSLUK)
        ust = QHBoxLayout()
        ust.setSpacing(_BOSLUK)
        self.l_kart = QLabel("")
        f = self.l_kart.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.08)
        self.l_kart.setFont(f)
        ust.addWidget(self.l_kart, 1)
        self.b_yenile = QPushButton()
        self.b_yenile.setMinimumHeight(_HEDEF)
        self.mt(self.b_yenile.setText, T.H_YENILE)
        self.b_yenile.clicked.connect(self.yenile)
        ust.addWidget(self.b_yenile)
        kl.addLayout(ust)
        self.l_ozet = QLabel("")  # "{ok}/{n} bileşen hazır"
        kl.addWidget(self.l_ozet)
        self.l_sorun_not = QLabel()
        self.l_sorun_not.setWordWrap(True)
        self.mt(self.l_sorun_not.setText, T.H_SORUN_NOT)
        kl.addWidget(self.l_sorun_not)
        self.sorunlar = QGridLayout()  # bileşen · ne eksik · Kopyala
        self.sorunlar.setHorizontalSpacing(_BOSLUK * 2)
        self.sorunlar.setVerticalSpacing(_BOSLUK)
        self.sorunlar.setColumnStretch(1, 1)
        kl.addLayout(self.sorunlar)
        self.l_kopyalandi = QLabel("")
        self.l_kopyalandi.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.l_kopyalandi.setVisible(False)
        kl.addWidget(self.l_kopyalandi)
        kok.addWidget(self.kart)

        # ---- tam liste (katlı): paket/araç adları burada
        self.b_tumu = QToolButton()
        self.b_tumu.setCheckable(True)
        self.b_tumu.setMinimumHeight(_HEDEF)
        self.b_tumu.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.b_tumu.setArrowType(Qt.ArrowType.RightArrow)
        self.mt(self.b_tumu.setText, T.H_TUMU)
        self.b_tumu.toggled.connect(self._tumu)
        kok.addWidget(self.b_tumu, 0, Qt.AlignmentFlag.AlignLeft)
        self.tablo = QTableWidget(0, 3)
        self.mt.fn(lambda: self.tablo.setHorizontalHeaderLabels([_(x) for x in T.H_SUTUNLAR]))
        self.tablo.verticalHeader().setVisible(False)
        self.tablo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tablo.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tablo.setShowGrid(False)
        b = self.tablo.horizontalHeader()
        b.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)  # içerikle aynı hiza (D4)
        b.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        b.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        b.setStretchLastSection(True)
        b.setHighlightSections(False)
        self.tablo.setVisible(False)
        kok.addWidget(self.tablo, 1)
        self.bosluk = QWidget()  # tablo katlıyken kart üstte kalsın
        kok.addWidget(self.bosluk, 1)
        self._ilk = True
        self._denetleniyor_yaz()

    def _denetleniyor_yaz(self) -> None:
        """İlk denetim dönmeden "Her şey hazır ✓ 0/0" değil "Denetleniyor…" (UX-L D-B)."""
        self.l_kart.setText(_(T.H_DENETLENIYOR))
        self.l_ozet.setText("")
        self.l_ozet.setToolTip("")
        self.l_sorun_not.setVisible(False)

    def _tumu(self, acik: bool) -> None:
        self.b_tumu.setArrowType(Qt.ArrowType.DownArrow if acik else Qt.ArrowType.RightArrow)
        self.tablo.setVisible(acik)
        self.bosluk.setVisible(not acik)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        if self._ilk:
            self._ilk = False
            self.yenile()

    def yenile(self):
        if self._isci is not None:
            return
        self.b_yenile.setEnabled(False)
        if not self.sonuc:  # önceki sonuç varsa denetim sürerken o kalır
            self._denetleniyor_yaz()
        self._isci = Isci(self.denetle_f, self)
        self._isci.bitti.connect(self._bitti)
        self._isci.start()

    def _bitti(self, sonuc, hata):
        self._isci = None
        self.b_yenile.setEnabled(True)
        self.goster(sonuc or [])
        if hata is not None:  # denetim düştü: sade cümle üstte, ham metin ipucunda
            self.l_ozet.setText(T.hata_ozeti(hata))
            self.l_ozet.setToolTip(T.hata_ayrinti(hata))

    @staticmethod
    def _durum(d: dict) -> str:
        return d.get("durum", "tamam" if d["ok"] else "eksik")

    def _kopyala(self, komut: str, ayrinti: bool = False) -> None:
        self.pano(komut)
        self.l_kopyalandi.setText(_(T.H_KOPYALANDI_AYRINTI) if ayrinti else _(T.H_KOPYALANDI).format(komut=komut))
        self.l_kopyalandi.setVisible(True)

    @staticmethod
    def kisa(metin: str, sinir: int = KISA_SINIR) -> str:
        """Uzun ham doctor ayrıntısı → ilk satır/ilk cümle, en çok `sinir` karakter (UX-L D-C); tamamı ipucunda ve
        Kopyala ile panoda."""
        m = " ".join(str(metin or "").split("\n", 1)[0].split())
        for ayrac in ("; ", ". "):
            if ayrac in m:
                m = m.split(ayrac, 1)[0]
        return m if len(m) <= sinir else m[:sinir - 1].rstrip() + "…"

    def _sorunlari_temizle(self) -> None:
        while self.sorunlar.count():
            it = self.sorunlar.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        self.sorun_satirlari = []

    def goster(self, sonuc: list[dict]):
        # sorunlular önde (eksik → uyarı → tamam); aynı grupta özgün sıra
        sira = {"eksik": 0, "uyari": 1}
        sonuc = sorted(sonuc, key=lambda d: 2 if d["ok"] else sira.get(self._durum(d), 0))
        self.sonuc = sonuc
        self.tablo.setRowCount(len(sonuc))
        for i, d in enumerate(sonuc):
            ad = QTableWidgetItem(d["ad"])
            ad.setToolTip(_(S.insan_adi(d)))
            d_ = self._durum(d)
            durum = QTableWidgetItem(_(T.H_VAR if d["ok"] else T.H_UYARI if d_ == "uyari" else T.H_YOK))
            durum.setIcon(nokta(YESIL if d["ok"] else SARI if d_ == "uyari" else KIRMIZI, 6))
            self.tablo.setItem(i, 0, ad)
            self.tablo.setItem(i, 1, durum)
            tam = _(d["not"]) if d["not"] else ""  # saglik.py notları msgid; doctor ("ek") ayrıntısı uzun olabilir
            not_ = QTableWidgetItem(self.kisa(tam) if d.get("tur") == "ek" else tam)
            not_.setToolTip(tam)
            self.tablo.setItem(i, 2, not_)
        self._sorunlari_temizle()
        sorunlu = [d for d in sonuc if not d["ok"]]
        for r, d in enumerate(sorunlu):
            ad = QLabel(_(S.insan_adi(d)))
            ad.setToolTip(f"{d['ad']} — {_(d['not'])}")
            ad.setAccessibleName(ad.text())
            f = ad.font()
            f.setBold(True)
            ad.setFont(f)
            d_ = self._durum(d)
            # doctor satırı ("ek"): ayrıntısı insan dilinde ama uzun olabilir → kısa özet, tamamı ipucunda ve Kopyala
            # ile panoda (UX-L D-C); paketli satır: yalnız durum
            ek_not = str(d.get("not") or "") if d.get("tur") == "ek" else ""
            ne = QLabel(self.kisa(ek_not) if ek_not else _(T.H_UYARI if d_ == "uyari" else T.H_YOK))
            ne.setWordWrap(True)
            ne.setToolTip(ek_not)
            komut = S.cozum_komutu(d)
            satir = {"veri": d, "ad": ad, "ne": ne, "komut": komut, "kopyala": None}
            self.sorunlar.addWidget(ad, r, 0)
            self.sorunlar.addWidget(ne, r, 1)
            if komut or ek_not:
                b = QPushButton(_(T.H_KOPYALA))
                b.setMinimumHeight(_HEDEF)
                b.setToolTip(_(T.H_KOPYALA_IPUCU).format(komut=komut) if komut else _(T.H_KOPYALA_AYRINTI_IPUCU))
                b.setAccessibleName(f"{_(T.H_KOPYALA)}: {ad.text()}")
                if komut:
                    b.clicked.connect(lambda _c=False, k=komut: self._kopyala(k))
                else:
                    b.clicked.connect(lambda _c=False, k=ek_not: self._kopyala(k, ayrinti=True))
                self.sorunlar.addWidget(b, r, 2)
                satir["kopyala"] = b
            self.sorun_satirlari.append(satir)
        n = len(sorunlu)
        if not sonuc:  # boş sonuç "Her şey hazır ✓ 0/0" değildir (UX-L D-B)
            self.l_kart.setText(_(T.H_SONUC_YOK))
            self.l_sorun_not.setVisible(False)
            self.l_kopyalandi.setVisible(False)
            self.l_ozet.setText("")
            self.l_ozet.setToolTip("")
            return
        self.l_kart.setText(_(T.H_HEPSI_TAMAM) if not n else _(T.H_SORUN_TEK) if n == 1
                            else _(T.H_SORUN_VAR).format(n=n))
        self.l_sorun_not.setVisible(bool(n))
        self.l_kopyalandi.setVisible(False)
        ok = len(sonuc) - n
        self.l_ozet.setText(_(T.H_OZET).format(ok=ok, n=len(sonuc)))
        self.l_ozet.setToolTip("")

    def tazele(self) -> None:
        self.mt.tazele()
        if self.sonuc:
            self.goster(self.sonuc)
        elif self._isci is not None or self._ilk:
            self._denetleniyor_yaz()
        else:
            self.goster([])
