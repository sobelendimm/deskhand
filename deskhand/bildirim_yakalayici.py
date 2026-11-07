"""Sanal masaüstünün bildirim yakalayıcısı: ÖZEL D-Bus'ta org.freedesktop.Notifications adını sahiplenir,
Notify çağrılarını JSONL günlüğüne yazar (kullanıcının ekranına bildirim düşmez).

Tek başına çalışır (paket içe aktarması yok; masaustu.py `python3 -I bu_dosya ADRES GUNLUK` ile başlatır):
  - Notify(susssasa{sv}i) → u        günlüğe bir satır; replaces_id verilirse aynı kimlik
  - CloseNotification(u)            NotificationClosed(id, 3) sinyali
  - GetCapabilities → as, GetServerInformation → ssss, Introspect, Peer.Ping
Ad alınınca stdout'a "hazir" yazar.
"""
from __future__ import annotations

import json
import os
import sys
import time

AD = "org.freedesktop.Notifications"
YOL = "/org/freedesktop/Notifications"
YETENEKLER = ["body", "actions", "persistence"]
BASIT = set("sbyniqxtud")
GOVDE_SINIRI = 4000
INTROSPECT = """<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
 <interface name="org.freedesktop.Notifications">
  <method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
   <arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
   <arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
  <method name="CloseNotification"><arg type="u" direction="in"/></method>
  <method name="GetCapabilities"><arg type="as" direction="out"/></method>
  <method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/>
   <arg type="s" direction="out"/><arg type="s" direction="out"/></method>
  <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
  <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
 </interface>
 <interface name="org.freedesktop.DBus.Introspectable">
  <method name="Introspect"><arg type="s" direction="out"/></method>
 </interface>
 <interface name="org.freedesktop.DBus.Peer"><method name="Ping"/></interface>
</node>
"""


def ipuclari(h: dict) -> dict:
    """a{sv} ipuçlarından JSON'a uyan basit olanlar (resim verisi gibi büyükler yalnız türüyle)."""
    out = {}
    for k, v in (h or {}).items():
        try:
            imza, deger = v
        except (TypeError, ValueError):
            continue
        if imza in BASIT:
            out[k] = deger if not isinstance(deger, bytes) else deger.decode(errors="replace")
        else:
            out[k] = f"<{imza}>"
    return out


def kayit(govde: tuple, kimlik: int) -> dict:
    uyg, yerine, simge, baslik, metin, eylemler, h, sure = govde
    return {"zaman": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "id": kimlik, "uygulama": uyg, "baslik": baslik,
            "govde": metin[:GOVDE_SINIRI], "simge": simge, "yerine": yerine,
            "eylemler": dict(zip(eylemler[0::2], eylemler[1::2])), "zaman_asimi": sure, "ipuclari": ipuclari(h)}


def yaz(gunluk: str, satir: dict) -> None:
    try:
        os.makedirs(os.path.dirname(gunluk) or ".", exist_ok=True)
        with open(gunluk, "a") as f:
            f.write(json.dumps(satir, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"bildirim günlüğü yazılamadı: {e}", file=sys.stderr)


def calistir(adres: str, gunluk: str) -> int:
    from jeepney import DBusAddress, HeaderFields, MessageType, message_bus, new_error, new_method_return, new_signal
    from jeepney.io.blocking import open_dbus_connection

    c = open_dbus_connection(bus=adres)
    yanit = c.send_and_get_reply(message_bus.RequestName(AD, 4), timeout=5)  # 4 = DO_NOT_QUEUE
    if yanit.body[0] not in (1, 4):  # 1 birincil sahip, 4 zaten bizim
        print(f"ad alınamadı: {yanit.body}", flush=True)
        return 1
    print("hazir", flush=True)
    sinyal_adr = DBusAddress(YOL, interface=AD)
    sayac = 0
    while True:
        try:
            m = c.receive()
        except (ConnectionError, OSError):
            return 0  # veri yolu kapandı (masaüstü durduruldu)
        if m.header.message_type != MessageType.method_call:
            continue
        f = m.header.fields
        uye, arayuz = f.get(HeaderFields.member), f.get(HeaderFields.interface)
        try:
            if uye == "Notify" and arayuz in (None, AD):
                yerine = int(m.body[1])
                if yerine:
                    kimlik = yerine
                else:
                    sayac += 1
                    kimlik = sayac
                yaz(gunluk, kayit(m.body, kimlik))
                c.send(new_method_return(m, "u", (kimlik,)))
            elif uye == "CloseNotification":
                c.send(new_method_return(m))
                c.send(new_signal(sinyal_adr, "NotificationClosed", "uu", (int(m.body[0]), 3)))
            elif uye == "GetCapabilities":
                c.send(new_method_return(m, "as", (YETENEKLER,)))
            elif uye == "GetServerInformation":
                c.send(new_method_return(m, "ssss", ("deskhand", "deskhand", "0.4.0", "1.2")))
            elif uye == "Introspect":
                c.send(new_method_return(m, "s", (INTROSPECT,)))
            elif uye == "Ping":
                c.send(new_method_return(m))
            else:
                c.send(new_error(m, "org.freedesktop.DBus.Error.UnknownMethod", "s", (f"bilinmeyen: {uye}",)))
        except Exception as e:  # noqa: BLE001 - tek bozuk çağrı yakalayıcıyı düşürmesin
            try:
                c.send(new_error(m, "org.freedesktop.DBus.Error.Failed", "s", (str(e),)))
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("kullanım: bildirim_yakalayici.py D-BUS-ADRESİ GÜNLÜK.jsonl", file=sys.stderr)
        sys.exit(2)
    sys.exit(calistir(sys.argv[1], sys.argv[2]))
