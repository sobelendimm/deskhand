"""Denetim testleri için düz X penceresi (yalnız görünmez sanal masaüstünde): her girdi LOG dosyasına yazılır.
Kullanım: LOG=… python3 denetim_pencere.py BAŞLIK SINIF X Y G Y PID KİP
  PID: _NET_WM_PID olarak yazılır (0 = yazılmaz); KİP: "duz" | "ucbirim" (yazılanı "$ " istemiyle çizer; Return →
  CALISTI:<satır>, BackSpace siler; ctrl+u satırı temizler) | "ustte" (her zaman üstte) | "ucbirim+kabuk" (ucbirim
  gibi çizer + denetim uçbirimi pty olan bir `sh` çocuğu başlatır: Dolphin F4 gibi GÖMÜLÜ uçbirim taklidi; sh hiçbir
  komut çalıştırmaz, yalnız bekler)."""
import os
import sys

from PIL import Image, ImageDraw, ImageFont
from Xlib import X, XK, display

LOG = os.environ["LOG"]
baslik, sinif = sys.argv[1], sys.argv[2]
x, y, w, h = map(int, sys.argv[3:7])
pid, kip = int(sys.argv[7]), sys.argv[8]
if pid == -1:
    pid = os.getpid()
if kip.endswith("+kabuk"):
    import fcntl, pty, subprocess, termios
    ana, yan = pty.openpty()
    KABUK = subprocess.Popen(["sh", "-i"], stdin=yan, stdout=yan, stderr=yan, start_new_session=True,
                             preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0),
                             env={"PATH": "/usr/bin:/bin", "HISTFILE": "/dev/null", "PS1": "$ ", "ENV": "/dev/null"})
    kip = "ucbirim"


def log(s):
    with open(LOG, "a") as f:
        f.write(s + "\n")


d = display.Display()
s = d.screen()
win = s.root.create_window(x, y, w, h, 0, s.root_depth, X.InputOutput, X.CopyFromParent,
                           background_pixel=s.white_pixel,
                           event_mask=X.ExposureMask | X.KeyPressMask | X.ButtonPressMask | X.ButtonReleaseMask)
win.set_wm_name(baslik)
win.change_property(d.intern_atom("_NET_WM_NAME"), d.intern_atom("UTF8_STRING"), 8, baslik.encode())
win.set_wm_class(sinif, sinif)
win.set_wm_hints(flags=1, input=1)
win.set_wm_normal_hints(flags=1 | 2 | 4 | 8, x=x, y=y, width=w, height=h)
if pid:
    win.change_property(d.intern_atom("_NET_WM_PID"), d.intern_atom("CARDINAL"), 32, [pid])
if kip == "ustte":
    win.change_property(d.intern_atom("_NET_WM_STATE"), d.intern_atom("ATOM"), 32, [d.intern_atom("_NET_WM_STATE_ABOVE")])
gc = win.create_gc(foreground=s.black_pixel, background=s.white_pixel)
try:
    YAZI = ImageFont.load_default(size=26)
except TypeError:  # eski Pillow
    YAZI = ImageFont.load_default()
satir = ""


def ciz():
    if kip != "ucbirim":
        return
    im = Image.new("RGB", (w, 60), (255, 255, 255))
    ImageDraw.Draw(im).text((10, 12), "$ " + satir, fill=(0, 0, 0), font=YAZI)
    win.put_pil_image(gc, 0, h - 80, im)
    d.flush()


win.map()
d.flush()
log("hazir")
while True:
    e = d.next_event()
    if e.type == X.Expose:
        ciz()
    elif e.type == X.ButtonPress:
        log(f"TIK:{e.detail}")
    elif e.type == X.KeyPress:
        ks = d.keycode_to_keysym(e.detail, 1 if e.state & X.ShiftMask else 0) or d.keycode_to_keysym(e.detail, 0)
        ctrl = bool(e.state & X.ControlMask)
        if ks in (XK.XK_Return, XK.XK_KP_Enter) or (ctrl and ks in (XK.XK_j, XK.XK_m)):
            log("CALISTI:" + satir)
            satir = ""
        elif ks == XK.XK_BackSpace:
            satir = satir[:-1]
        elif ctrl and ks == XK.XK_u:
            satir = ""
        elif 0x20 <= ks < 0x7F and not ctrl:
            satir += chr(ks)
            log("TUS:" + chr(ks))
        ciz()
