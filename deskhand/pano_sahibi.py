"""Pano sahibi (sanal masaüstü yardımcısı): görünmez masaüstünün CLIPBOARD seçiminin SAHİBİ olur.

Neden: X11'de pano içeriği seçimin sahibi süreçte yaşar, sahip ölünce pano boşalır. Deskhand komutları kısa
ömürlüdür (CLI süreci biter), oysa yapıştırdıktan sonra geri yüklenen eski pano içeriği ondan sonra da durmalı. Bu
yardımcı kafesin içinde yaşar (masaüstü kapanınca birlikte kapanır) ve metni sunar. xclip/xsel gerekmez.

Tek başına betik (yalnız standart kitaplık + python-xlib), `python3 -I` ile çalışır; arka_uc/sanal.py gerektiğinde ilk
kullanımda kafesin içinde başlatır:
    python3 -I pano_sahibi.py EKRAN SOKET_YOLU        (EKRAN: ':90'; ortamda masaüstünün DISPLAY/XAUTHORITY'si)
Hazır olunca stdout'a "hazir" yazar. Yalnız kullanıcının GERÇEK ekranından farklı, DESKHAND_SANAL ile eşleşen ekrana
bağlanır (aksi halde çıkar).

İstemci protokolü (Unix soketi, dizin 0700): tek istek, tek yanıt.
    "YAZ <bayt>\\n" + UTF-8 veri  → seçimi alır → "tamam\\n" | "hata <ileti>\\n"
    "TEMIZLE\\n"                  → sahipliği bırakır (pano boş) → "tamam\\n"
Sunulan hedefler: TARGETS, TIMESTAMP, UTF8_STRING, text/plain;charset=utf-8, text/plain, TEXT, STRING (latin-1).
Tek özelliğe sığmayan veri ICCCM INCR ile parça parça sunulur; AZAMI_VERI'den büyüğü ("hata cok-buyuk") reddedilir."""
from __future__ import annotations

import os
import re
import select
import socket
import sys
import time

BEKLEME = 5.0  # istemci isteği en çok bu kadar sürede tamamlanmalı
AZAMI_VERI = 64 * 1024 * 1024  # sunulacak metnin üst sınırı (büyüğü INCR ile parça parça gider)


def ekran_dogrula(ekran: str) -> None:
    if not re.fullmatch(r":\d+", ekran or ""):
        sys.exit(f"geçersiz sanal ekran adı: {ekran!r}")
    gercek = os.environ.get("DESKHAND_GERCEK_DISPLAY", "") or ""
    if os.environ.get("DESKHAND_SANAL") != ekran or ekran == gercek.split(".")[0]:
        sys.exit("bu ekran görünmez masaüstünün ekranı değil; bağlanılmadı")


class PanoSahibi:
    HEDEFLER = ("TARGETS", "TIMESTAMP", "UTF8_STRING", "text/plain;charset=utf-8", "text/plain", "TEXT", "STRING")

    def __init__(self, ekran: str):
        from Xlib import X, Xatom, display
        from Xlib.protocol import event
        self.X, self.Xatom, self.event = X, Xatom, event
        self.d = display.Display(ekran)
        self.d.set_error_handler(lambda err, istek: None)  # bir istemci pencereyi yanıt gelmeden kapatabilir
        ek = self.d.screen()
        self.w = ek.root.create_window(0, 0, 1, 1, 0, ek.root_depth, X.InputOutput, X.CopyFromParent,
                                       event_mask=X.PropertyChangeMask)
        self.a = {ad: self.d.intern_atom(ad) for ad in (*self.HEDEFLER, "CLIPBOARD", "INCR")}
        self.veri: bytes | None = None
        self.aktarimlar: dict = {}  # süren INCR aktarımları: (istemci pencere, özellik) → durum
        self.zaman = X.CurrentTime
        # tek ChangeProperty isteğine sığan en büyük veri (BIG-REQUESTS kullanılmaz)
        self.azami = max(1024, self.d.display.info.max_request_length * 4 - 128)

    def _sunucu_zamani(self) -> int:
        """Seçimi sahiplenirken kullanılacak gerçek sunucu zamanı (özellik değişikliği olayından)."""
        X = self.X
        self.w.change_property(self.a["TIMESTAMP"], self.Xatom.INTEGER, 32, [0], X.PropModeAppend)
        self.d.flush()
        bitis = time.monotonic() + BEKLEME
        while time.monotonic() < bitis:
            while self.d.pending_events():
                e = self.d.next_event()
                if e.type == X.PropertyNotify and e.window.id == self.w.id:
                    return e.time
                self._olay(e)
            select.select([self.d.fileno()], [], [], 0.2)
        return X.CurrentTime

    def sahiplen(self, veri: bytes) -> bool:
        self.zaman = self._sunucu_zamani()
        self.veri = veri
        self.w.set_selection_owner(self.a["CLIPBOARD"], self.zaman)
        self.d.sync()
        return self.d.get_selection_owner(self.a["CLIPBOARD"]) == self.w

    def birak(self) -> None:
        """Sahipliği bırak (pano boş): SetSelectionOwner(None) — pencere düzeyindeki yöntem None almaz."""
        from Xlib.protocol import request
        self.veri = None
        request.SetSelectionOwner(display=self.d.display, onerror=None, window=self.X.NONE,
                                  selection=self.a["CLIPBOARD"], time=self.X.CurrentTime)
        self.d.sync()

    # ---- seçim istekleri
    def _yanit(self, ist, ozellik) -> None:
        e = self.event.SelectionNotify(time=ist.time, requestor=ist.requestor, selection=ist.selection,
                                       target=ist.target, property=ozellik)
        ist.requestor.send_event(e, event_mask=0)
        self.d.flush()

    def _metin_ver(self, ist, ozellik, tur, veri: bytes) -> None:
        """Tek özelliğe sığıyorsa doğrudan; sığmıyorsa ICCCM INCR (istemci özelliği sildikçe parça parça)."""
        X = self.X
        if len(veri) <= self.azami:
            ist.requestor.change_property(ozellik, tur, 8, veri)
            return
        ist.requestor.change_attributes(event_mask=X.PropertyChangeMask)
        ist.requestor.change_property(ozellik, self.a["INCR"], 32, [len(veri)])
        self.aktarimlar[(ist.requestor.id, ozellik)] = {"istek": ist, "tur": tur, "veri": veri, "konum": 0,
                                                        "son": time.monotonic()}

    def _parca_gonder(self, anahtar) -> None:
        t = self.aktarimlar[anahtar]
        parca = t["veri"][t["konum"]:t["konum"] + self.azami]
        t["istek"].requestor.change_property(anahtar[1], t["tur"], 8, parca)  # boş parça = bitti
        t["konum"] += len(parca)
        t["son"] = time.monotonic()
        self.d.flush()
        if not parca:
            del self.aktarimlar[anahtar]

    def istek(self, ist) -> None:
        X, Xatom, a = self.X, self.Xatom, self.a
        ozellik = ist.property if ist.property != X.NONE else ist.target
        hedef = ist.target
        if ist.selection != a["CLIPBOARD"] or self.veri is None:
            return self._yanit(ist, X.NONE)
        if hedef == a["TARGETS"]:
            ist.requestor.change_property(ozellik, Xatom.ATOM, 32, [a[h] for h in self.HEDEFLER])
        elif hedef == a["TIMESTAMP"]:
            ist.requestor.change_property(ozellik, Xatom.INTEGER, 32, [self.zaman])
        elif hedef in (a["UTF8_STRING"], a["text/plain;charset=utf-8"], a["text/plain"], a["TEXT"]):
            tur = a["UTF8_STRING"] if hedef in (a["TEXT"], a["text/plain"]) else hedef
            self._metin_ver(ist, ozellik, tur, self.veri)
        elif hedef == a["STRING"]:
            self._metin_ver(ist, ozellik, Xatom.STRING,
                            self.veri.decode("utf-8", "replace").encode("latin-1", "replace"))
        else:
            return self._yanit(ist, X.NONE)
        self._yanit(ist, ozellik)

    def _olay(self, e) -> None:
        X = self.X
        if e.type == X.SelectionRequest:
            self.istek(e)
        elif e.type == X.SelectionClear and e.selection == self.a["CLIPBOARD"]:
            self.veri = None  # başkası sahip oldu: sunacak bir şey kalmadı
        elif e.type == X.PropertyNotify and e.state == X.PropertyDelete:
            anahtar = (e.window.id, e.atom)
            if anahtar in self.aktarimlar:  # INCR: istemci parçayı okudu → sıradaki
                self._parca_gonder(anahtar)

    def olay_isle(self) -> None:
        while self.d.pending_events():
            self._olay(self.d.next_event())
        simdi = time.monotonic()
        for anahtar in [k for k, t in self.aktarimlar.items() if simdi - t["son"] > 10]:
            del self.aktarimlar[anahtar]  # istemci yanıt vermeyi bıraktı (öldü)


def istek_oku(c: socket.socket) -> tuple[str, bytes]:
    c.settimeout(BEKLEME)
    tampon = b""
    while b"\n" not in tampon:
        parca = c.recv(4096)
        if not parca:
            break
        tampon += parca
    baslik, _ayrac, kalan = tampon.partition(b"\n")
    komut = baslik.decode(errors="replace").split()
    if not komut:
        return "", b""
    if komut[0] == "YAZ" and len(komut) == 2 and komut[1].isdigit():
        n = int(komut[1])
        while len(kalan) < n:
            parca = c.recv(min(65536, n - len(kalan)))
            if not parca:
                break
            kalan += parca
        return "YAZ", kalan[:n]
    return komut[0], b""


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("kullanım: pano_sahibi.py EKRAN SOKET_YOLU", file=sys.stderr)
        return 2
    ekran, yol = argv
    ekran_dogrula(ekran)
    ps = PanoSahibi(ekran)
    try:
        os.unlink(yol)
    except FileNotFoundError:
        pass
    sunucu = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    eski = os.umask(0o177)
    try:
        sunucu.bind(yol)
    finally:
        os.umask(eski)
    sunucu.listen(8)
    print("hazir", flush=True)
    try:
        while True:
            hazir, _w, _x = select.select([ps.d.fileno(), sunucu], [], [], 1.0 if ps.aktarimlar else None)
            try:
                ps.olay_isle()
            except Exception as e:  # noqa: BLE001 - X bağlantısı koptu (masaüstü kapandı): çık
                print(f"X bağlantısı: {e}", file=sys.stderr)
                return 0
            if sunucu in hazir:
                c, _a = sunucu.accept()
                with c:
                    try:
                        komut, veri = istek_oku(c)
                        if komut == "YAZ":
                            if len(veri) > AZAMI_VERI:
                                c.sendall(b"hata cok-buyuk\n")
                            elif ps.sahiplen(veri):
                                c.sendall(b"tamam\n")
                            else:
                                c.sendall(b"hata sahiplenilemedi\n")
                        elif komut == "TEMIZLE":
                            ps.birak()
                            c.sendall(b"tamam\n")
                        else:
                            c.sendall(b"hata bilinmeyen-komut\n")
                    except (OSError, socket.timeout):
                        pass
    finally:
        try:
            os.unlink(yol)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
