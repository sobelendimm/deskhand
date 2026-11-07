"""Ekran koruması testi için küçük MPRIS oynatıcısı (jeepney, oturum veri yolu). Ses/görüntü yok: yalnız
org.mpris.MediaPlayer2.<ad>.instance<pid> adını alır ve PlaybackStatus/Metadata özelliklerini yanıtlar.
Deskhand (mesgul.medya) oynatıcı adını etkin pencerenin sınıfıyla eşler: test penceresi aynı adla
(UYGULAMA_KIMLIGI → Wayland app_id) açılır.

Not: çalıştığı sürece Plasma'nın medya denetimi bu "oynatıcıyı" gösterir; test bitince ad bırakılır.
Yanıt mantığı (yanit) veri yolundan bağımsızdır: birim testinde özel bir dbus-daemon ile sınanır."""
import os
import threading

MPRIS_YOL = "/org/mpris/MediaPlayer2"
KOK_ARAYUZ = "org.mpris.MediaPlayer2"
OYNATICI_ARAYUZ = "org.mpris.MediaPlayer2.Player"
OZELLIK_ARAYUZ = "org.freedesktop.DBus.Properties"
INTROSPECT = """<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node><interface name="org.freedesktop.DBus.Properties">
<method name="Get"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
<method name="GetAll"><arg type="s" direction="in"/><arg type="a{sv}" direction="out"/></method></interface>
<interface name="org.mpris.MediaPlayer2"><property name="Identity" type="s" access="read"/></interface>
<interface name="org.mpris.MediaPlayer2.Player"><property name="PlaybackStatus" type="s" access="read"/>
<property name="Metadata" type="a{sv}" access="read"/></interface></node>"""


def ozellikler(ad, durum, baslik="deskhand ekran koruması testi"):
    """{arayüz: {özellik: (imza, değer)}}"""
    return {
        KOK_ARAYUZ: {"Identity": ("s", f"{ad} (test)"), "DesktopEntry": ("s", ad), "CanQuit": ("b", False),
                     "CanRaise": ("b", False), "HasTrackList": ("b", False)},
        OYNATICI_ARAYUZ: {
            "PlaybackStatus": ("s", durum),
            "Metadata": ("a{sv}", {"mpris:trackid": ("o", "/org/deskhand/test/1"), "xesam:title": ("s", baslik)}),
            "CanPlay": ("b", True), "CanPause": ("b", True), "CanControl": ("b", False),
        },
    }


def yanit(arayuz, uye, govde, ozellik_tablosu):
    """Bir yöntem çağrısının yanıtı → ("tamam", imza, gövde) | ("hata", hata_adı, ileti)."""
    if arayuz in (OZELLIK_ARAYUZ, None) and uye == "Get":
        a, o = govde
        if a in ozellik_tablosu and o in ozellik_tablosu[a]:
            return ("tamam", "v", (ozellik_tablosu[a][o],))
        return ("hata", "org.freedesktop.DBus.Error.UnknownProperty", f"{a}.{o}")
    if arayuz in (OZELLIK_ARAYUZ, None) and uye == "GetAll":
        return ("tamam", "a{sv}", (dict(ozellik_tablosu.get(govde[0], {})),))
    if uye == "Introspect":
        return ("tamam", "s", (INTROSPECT,))
    if uye == "Ping":
        return ("tamam", "", ())
    return ("hata", "org.freedesktop.DBus.Error.UnknownMethod", f"{arayuz}.{uye}")


class MprisSunucu:
    """with MprisSunucu("deskhandmpristest") as m: ...; m.durum = "Paused" (anında geçerli)."""

    def __init__(self, ad, durum="Playing", adres="SESSION"):
        self.ad, self.durum, self.adres = ad, durum, adres
        self.bus_adi = f"org.mpris.MediaPlayer2.{ad}.instance{os.getpid()}"
        self._dur = threading.Event()
        self._is = None
        self.conn = None

    def baslat(self):
        from jeepney.bus_messages import message_bus
        from jeepney.io.blocking import open_dbus_connection
        self.conn = open_dbus_connection(bus=self.adres)
        r = self.conn.send_and_get_reply(message_bus.RequestName(self.bus_adi, 4), timeout=3)  # DO_NOT_QUEUE
        if r.body[0] not in (1, 4):  # PRIMARY_OWNER | ALREADY_OWNER
            self.conn.close()
            raise RuntimeError(f"MPRIS adı alınamadı: {self.bus_adi} ({r.body[0]})")
        self._is = threading.Thread(target=self._dongu, daemon=True)
        self._is.start()
        return self

    def _dongu(self):
        from jeepney import MessageType, new_error, new_method_return
        while not self._dur.is_set():
            try:
                msg = self.conn.receive(timeout=0.2)
            except TimeoutError:
                continue
            except Exception:  # noqa: BLE001 - bağlantı kapandı
                return
            if msg.header.message_type != MessageType.method_call:
                continue
            from jeepney import HeaderFields
            arayuz = msg.header.fields.get(HeaderFields.interface)
            uye = msg.header.fields.get(HeaderFields.member)
            sonuc = yanit(arayuz, uye, msg.body, ozellikler(self.ad, self.durum))
            try:
                if sonuc[0] == "tamam":
                    self.conn.send(new_method_return(msg, sonuc[1], sonuc[2]))
                else:
                    self.conn.send(new_error(msg, sonuc[1], "s", (sonuc[2],)))
            except Exception:  # noqa: BLE001
                return

    def durdur(self):
        self._dur.set()
        if self._is is not None:
            self._is.join(timeout=2)
        if self.conn is not None:
            try:
                self.conn.close()  # bağlantı kapanınca ad veri yolundan düşer
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self):
        return self.baslat()

    def __exit__(self, *a):
        self.durdur()
