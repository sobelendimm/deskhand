"""Onaylar sekmesi. Boşken bekleyen tablosu gizli, tek satır "Bekleyen onay yok" (UX-F O4); sütunlar içeriğe göre,
başlıklar içerikle aynı (sola) hizada (D4); Geçmiş'in Eylem sütunu insan dilinde, ham satır ipucunda (insan_metni)."""
from __future__ import annotations

import time

from PyQt6.QtCore import (Qt, QTimer,
                          pyqtSignal)
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout,
                             QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ... import guvenlik
from ...i18n import _
from .. import metinler as T
from ..dil import Metinler
from ..gunluk_okur import onay_gecmisi
from ..insan_metni import ayrinti, islem_adi, komut_parcasi, pencere_metni
from ..ortak import (YESIL, KIRMIZI, nokta, baslik_etiketi, _masaustu_adi, _karar_adi)


# =========================================================================== Onaylar

class OnaylarSekmesi(QWidget):
    ac_istendi = pyqtSignal(str)

    def __init__(self, parent=None, saat=time.time):
        super().__init__(parent)
        self.saat = saat
        self.bekleyen: list[dict] = []
        self.gecmis: list[dict] = []  # en yeni başta (t_gecmis satırlarıyla aynı sıra)
        self.mt = Metinler()
        kok = QVBoxLayout(self)
        e = baslik_etiketi("")
        self.mt(e.setText, T.O_BEKLEYEN)
        kok.addWidget(e)
        self.t_bekleyen = self._tablo(T.O_BEKLEYEN_SUTUNLAR)
        self.t_bekleyen.itemDoubleClicked.connect(lambda it: self._ac(it.row()))
        kok.addWidget(self.t_bekleyen, 2)
        alt = QHBoxLayout()
        self.l_bos = QLabel("")  # normal renk, tek satır (soluk + kırılan iki satır değil)
        self.l_bos.setWordWrap(False)
        self.mt(self.l_bos.setText, T.O_BOS)
        alt.addWidget(self.l_bos)
        alt.addStretch(1)
        self.b_ac = QPushButton()
        self.mt(self.b_ac.setText, T.O_AC)
        self.b_ac.clicked.connect(lambda: self._ac(self.t_bekleyen.currentRow()))
        alt.addWidget(self.b_ac)
        kok.addLayout(alt)
        e = baslik_etiketi("")
        self.mt(e.setText, T.O_GECMIS)
        kok.addWidget(e)
        self.t_gecmis = self._tablo(T.O_SUTUNLAR)
        kok.addWidget(self.t_gecmis, 3)
        for t, sutunlar in ((self.t_bekleyen, T.O_BEKLEYEN_SUTUNLAR), (self.t_gecmis, T.O_SUTUNLAR)):
            self.mt.fn(lambda t=t, sutunlar=sutunlar: t.setHorizontalHeaderLabels([_(x) for x in sutunlar]))
        self.zaman = QTimer(self)
        self.zaman.setInterval(1000)
        self.zaman.timeout.connect(self._kalanlari_yaz)
        self.guncelle([])

    @staticmethod
    def _tablo(sutunlar) -> QTableWidget:
        t = QTableWidget(0, len(sutunlar))
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setShowGrid(False)
        t.setAlternatingRowColors(True)
        b = t.horizontalHeader()
        b.setStretchLastSection(False)
        b.setHighlightSections(False)
        b.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)  # içerikle aynı hiza (D4)
        # kısa ve sabit biçimli sütunlar (Zaman, Masaüstü, Kalan/Durum) içerik kadar; Eylem ve Hedef kalan yeri paylaşır
        for i in range(len(sutunlar)):
            b.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch if i in (1, 2) else
                                   QHeaderView.ResizeMode.ResizeToContents)
        return t

    def _ac(self, satir: int):
        if 0 <= satir < len(self.bekleyen):
            self.ac_istendi.emit(self.bekleyen[satir]["id"])

    def guncelle(self, bekleyen: list[dict]) -> None:
        self.bekleyen = list(bekleyen)
        t = self.t_bekleyen
        t.setRowCount(len(self.bekleyen))
        for i, d in enumerate(self.bekleyen):
            hedef = guvenlik.onay_iletisi(d)["hedef"]  # yasak/gizli pencere başlığı diyalogdaki gibi gizli
            vals = (time.strftime("%H:%M:%S", time.localtime(d["zaman"])), d["eylem"], hedef,
                    _masaustu_adi(d["masaustu"]), "")
            for j, v in enumerate(vals):
                # yalnız görüntü (izin yalnız diyalogdan): metin tam ama temiz (yön/sıfır genişlik yok, tek satır);
                # Qt dar sütunda "…" ile kısaltırsa tamamı ipucunda ve diyalogda (UX-C-R1c)
                v = guvenlik.onay_tek_satir(v, None) if j in (1, 2) else v
                it = QTableWidgetItem(v)
                if j in (1, 2):
                    it.setToolTip(v)
                t.setItem(i, j, it)
        self._kalanlari_yaz()
        self.l_bos.setVisible(not self.bekleyen)
        t.setVisible(bool(self.bekleyen))
        self.b_ac.setVisible(bool(self.bekleyen))
        self.b_ac.setEnabled(bool(self.bekleyen))
        if self.bekleyen and self.isVisible():
            self.zaman.start()
        elif not self.bekleyen:
            self.zaman.stop()

    def _kalanlari_yaz(self):
        from ..onay_diyalog import sure_metni
        simdi = self.saat()
        for i, d in enumerate(self.bekleyen):
            it = self.t_bekleyen.item(i, 4)
            if it is not None:
                it.setText(sure_metni(d["son_zaman"] - simdi))

    def gecmis_ekle(self, satirlar: list[dict]) -> None:
        onay_satirlari = [d for d in satirlar if d.get("tur") == "onay"]  # onay_gecmisi ile aynı süzgeç ve sıra
        for g, d in zip(onay_gecmisi(satirlar), onay_satirlari, strict=True):
            g = {**g, "satir": d}
            t = self.t_gecmis
            t.insertRow(0)
            self.gecmis.insert(0, g)
            self._gecmis_yaz(0, g)
            while t.rowCount() > 200:
                t.removeRow(t.rowCount() - 1)
            del self.gecmis[200:]

    @staticmethod
    def _eylem_metni(g: dict) -> str:
        """Ham eylem ("tikla (5,5) sol") → insan dili ("Tıklandı"); bilinmeyen → işlem adı ("Pencereyi kapatma").
        Karar yalnız Durum sütununda (Eylem'de "onay sorusu: izin verildi" yinelenmez, UX-L). Gizlilik
        insan_metni'nindir: gizli yazının içeriği/uzunluğu, yasak pencere başlığı çıkmaz."""
        d = g.get("satir") or {}
        parca = komut_parcasi(g["eylem"], gizli=bool(d.get("gizli")) or "***" in g["eylem"])
        if parca:
            return parca[:1].upper() + parca[1:]
        return islem_adi(g["eylem"])

    def _gecmis_yaz(self, satir: int, g: dict) -> None:
        d = g.get("satir")
        hedef = pencere_metni(d) if d else g["hedef"]
        vals = (g["zaman"], self._eylem_metni(g), hedef, _masaustu_adi(g["masaustu"]), _karar_adi(g["sonuc"]))
        ham = ayrinti(d) if d else ""
        for j, v in enumerate(vals):
            it = QTableWidgetItem(v)
            if ham:
                it.setToolTip(ham)  # ham satır (yasak başlık / URL sorgusu maskeli)
            if j == 4:
                it.setIcon(nokta(YESIL if g["sonuc"] in ("izin", "devir-tamam", "devir-kosul") else KIRMIZI, 6))
            self.t_gecmis.setItem(satir, j, it)

    def tazele(self) -> None:
        self.mt.tazele()
        self.guncelle(self.bekleyen)
        for i, g in enumerate(self.gecmis):
            self._gecmis_yaz(i, g)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        if self.bekleyen:
            self.zaman.start()

    def hideEvent(self, e):  # noqa: N802
        super().hideEvent(e)
        self.zaman.stop()
