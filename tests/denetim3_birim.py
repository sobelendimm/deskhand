"""DENETİM 3 (ekransız, sahte arka uç): tur4 Enter kapısına yeni atlatma denemeleri (YO2) ve yapıştırma (YO3)."""
import _yalitim  # noqa: F401

from deskhand import guvenlik, ucbirim
from deskhand.hata import Dur


class AU:
    ad = "kde"

    def sinif(self, k):
        return "org.kde.konsole"

    def baslik(self, k):
        return "~ : bash — Konsole"

    def pid(self, k):
        return ""

    def aktif(self):
        return "{p}"


guvenlik.sec = ucbirim.sec = lambda: AU()

ORNEKLER = [
    # geçmiş / yeniden çalıştırma
    "!?reboot?", "!#", "!$", "!:0 reboot", "\\!!", "history | tail -1 | sh", "$(history -p !!)", "fc -e - ",
    "$(fc -ln -1)", "eval \"$(history | tail -n1 | cut -c8-)\"",
    # dolaylı yürütme
    "xargs -I{} sh -c {} < /tmp/k", "cat /tmp/k | bash -s", "bash /dev/stdin < /tmp/k", "sh -s < k.txt",
    "bash k.sh", "./k.sh", "~/k.sh", "zsh -i", "exec bash", "env -S 'sudo reboot'", "nohup ./k &",
    "python3 -", "python3 k.py", "node k.js", "perl k.pl", "make -f /tmp/m", "ninja -f /tmp/n",
    "vim -c ':!reboot' -c q", "less /tmp/k", "man -P 'sh -c reboot' ls", "git -c core.pager='sh -c reboot' log",
    "find . -maxdepth 0 -execdir reboot \\;", "tar -cf /dev/null x --checkpoint-action=exec=reboot --checkpoint=1",
    "rsync -e 'sh -c reboot' a b:", "ssh -o ProxyCommand='reboot' x", "awk 'BEGIN{while((\"reboot\"|getline l)>0)}'",
    "sed -n '1e reboot' /etc/hostname", "zip /tmp/z /etc/hostname -T -TT 'reboot #'", "watch -n1 reboot",
    "timeout 1 reboot", "busybox sh -c reboot", "dbus-send --system --print-reply --dest=org.freedesktop.login1 "
    "/org/freedesktop/login1 org.freedesktop.login1.Manager.Reboot boolean:true",
    "qdbus org.kde.Shutdown /Shutdown logout", "gdbus call --system -d org.freedesktop.login1 -o "
    "/org/freedesktop/login1 -m org.freedesktop.login1.Manager.PowerOff true",
    "systemctl --user stop plasma-plasmashell", "kquitapp6 plasmashell", "killall plasmashell", "pkill -f deskhand",
    "kill -9 $(pgrep -f 'deskhand panel')", "rm -f $XDG_RUNTIME_DIR/deskhand/dur",
    "printf '%s' x > ~/.config/deskhand/yasak-pencereler.txt", "cp /dev/null ~/.config/deskhand/yasak-pencereler.txt",
    "ln -sf /dev/null ~/.config/deskhand/yasak-pencereler.txt", "chmod 000 ~/.config/deskhand",
    "mv ~/.config/deskhand ~/.config/x", "echo 'sudo reboot' | at now + 1 min", "(sleep 99; reboot) &",
    "reb\\\noot", "'re''boot'", "r\\eboot", "$'\\x72eboot'", "${0:0:0}reboot", "\\reboot",
]
acik = 0
for s in ORNEKLER:
    ucbirim.satir_oku = lambda k, s=s: ["~ $ " + s]
    try:
        r = ucbirim.enter_kapisi("{p}", False)
        durum = "AÇIK " if r is False else f"? {r}"
        acik += r is False
    except Dur as e:
        durum = "yakalandı"
        _ = e
    print(f"{durum}  {s!r}")
print(f"\nYO2 Enter kapısı: {acik} / {len(ORNEKLER)} örnek onaysız geçti\n")

print("YO3 yapıştırma tanıma:")
for kom in ("ctrl+v", "shift+insert", "shift+kpinsert", "ctrl+shift+v", "shift+f10 p", "alt+e p", "menu p",
            "compose p", "shift+F10 Down Down Return", "x:XF86Paste", "k:207"):
    print(f"  yapistir_tusu_mu({kom!r}) = {guvenlik.yapistir_tusu_mu(kom)}")
for t in ("Yapıştır", "", "Paste", "📋", "Pa&ste", "Yapıştır ve Git", "Panodan ekle", "Insert from clipboard"):
    print(f"  yapistirma_metni_mi({t!r}) = {guvenlik.yapistirma_metni_mi(t)}")
