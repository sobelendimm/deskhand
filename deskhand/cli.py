"""Komut satırı (argparse). Komut ve seçenek adları İngilizce, Türkçe adlar (ekran v3.2) takma ad olarak çalışır
(komutlar.py); içeride komut adı ve seçenek dest'leri Türkçedir. Çıktı biçimi ve çıkış kodları ekran v3.2 ile aynı.
Yardım metni yardim_metni()'nde (paragraf paragraf çevrilir); `deskhand help` tamamını, argümansız çağrı komut
listesini verir."""
from __future__ import annotations

import argparse
import re
import os
import sys

from . import __version__, guvenlik, yollar
from .akis import k_akis
from .arka_uc import ARKA_ONEK, hedef_ad, sec
from .erisim import k_agac, k_erisim, k_ogeye_tikla
from .eylem import (GIRDI_KOMUTLARI, KAYDIR_YON, OKUMA_KOMUTLARI, k_bas, k_dizi, k_fare, k_kapat, k_kaydir,
                    k_metne_tikla, k_renge_tikla, k_simgeye_tikla, k_surukle, k_tikla, k_tus, k_uyu, k_yaz)
from .gorsel import k_foto, k_renk_bul, k_simge_bul, k_simge_kaydet
from .gunluk import gunluk, temizle
from .guvenlik import yasak_denetle
from .hata import SANAL_KAPALI, Dur, dur_denetle, dur_dosyasi
from .i18n import N_, _, h_
from .komutlar import DUGME, ERISIM, RENK, SECENEKLER, TR_EN, YON, cevirici, ic_ad, secimler, takma_adlar
from .mesgul import k_karar, k_mesgul
from .ocr import k_bekle, k_metin
from .uygulama import k_ac

# Yardım metni: her paragraf (komut listesinde her komut) ayrı bir msgid → çeviri kısa parçalarla yapılır.
# Komut adları İngilizcedir, Türkçe ad parantezde; ikisi de çalışır (komutlar.py).
YARDIM_GIRIS = N_("Deskhand {surum}: yapay zekâ ajanları için güvenli masaüstü kontrolü (KDE Plasma Wayland) — senin ekranında\n"
                  "ya da görünmez ikinci bir masaüstünde. kdotool pencere bulur, dotool fare/klavye sürer, spectacle görüntü\n"
                  "alır, tesseract (tur+eng) metin okur (OCR). 'ekran' komutu eski adıdır, aynı şekilde çalışır.")
YARDIM_GUVENLIK = (
    N_("GÜVENLİK: her girdi (tıklama/tuş/yazı/kaydırma) hedef pencere öne gelip AKTİF olduğu doğrulanınca\n"
       "gönderilir. -b DESEN verilirse pencere BAŞLIĞI da (tarayıcıda sekme) her girdiden HEMEN önce\n"
       "denetlenir. Yazılar kelime kelime gönderilir, her parçadan önce yeniden denetlenir."),
    N_("Yasak pencerelere (~/.config/deskhand/yasak-pencereler.txt; varsayılan boş) hiç girdi gitmez. Ödeme/yetki/hesap\n"
       "silme düğmelerine (Satın al, Öde, Authorize, İzin ver…) --approved olmadan tıklanmaz: --approved YALNIZ\n"
       "kullanıcı o adımı açıkça onayladıysa verilir. Her girdi ~/.local/state/deskhand/ günlüğüne yazılır."),
    N_("İNSAN ÖNCELİĞİ: kullanıcı fareyi YA DA klavyeyi kullanıyorsa (Wayland boşta bildirimi, yetkisiz) girdi\n"
       "gönderilmez: 1,5 sn sessizlik beklenir (en çok 8 sn), olmazsa 12. Basılı tutarken insan girdisi → hemen bırakır."),
    N_("DUR ANAHTARI: 'ekran stop' sonrası hiçbir deskhand süreci girdi göndermez (13), basılı tuşlar bırakılır; "
       "'ekran resume' kaldırır."),
)
YARDIM_KOMUT_BASI = (
    N_("Komutlar (koordinatlar pencereye göre, piksel; <kimlik> yerine tek pencereye uyan ad da verilebilir;\n"
       "<kimlik> = \"ekran\" (masaüstü kipi): tüm ekran — panel, masaüstü, menüler, başlatıcı; okuma odağı çalmaz,\n"
       "klavye o an etkin pencereye gider ve ona kilitlenir, fare imlecin altındaki pencereyi denetler).\n"
       "Parantezdeki Türkçe komut adları ve Türkçe seçenekler (--baslik, --bolge, --sure …) de çalışır:"),
)
YARDIM_KOMUTLAR = (
    N_("  ekran windows (bul) <desen>             kimlik | başlık | x y genişlik yükseklik"),
    N_("  ekran screenshot (foto) <kimlik> [png] [--region x,y,g,y] [--width N] [--grid [ADIM]]"),
    N_("  ekran click (tikla) <kimlik> <x> <y> [right|double|middle] [--shot] [--approved]"),
    N_("  ekran key (tus) <kimlik> <kombinasyon> [--approved]   ör. ctrl+s, Return, alt+F4"),
    N_("  ekran type (yaz) <kimlik> <metin> [--secret]   \\n → Return, \\t → Tab; --secret günlüğe metni yazmaz;\n"
       "                                          '-' ile başlayan metin: ekran type <kimlik> -- \"-5 derece\""),
    N_("  ekran scroll (kaydir) <kimlik> [down|up|left|right] [ADIM] [--point x,y]"),
    N_("  ekran read (metin) <kimlik> [desen] [--region ..] [--precise] [--all] [--deep]   yazılar + koordinatlar"),
    N_("  ekran click-text (metne-tikla) <kimlik> <metin> [right|double] [--nth N] [--wait SN] [--offset dx,dy]\n"
       "                    [--region ..] [--scroll-search [N]] [--approved]"),
    N_("  ekran wait (bekle) <kimlik> <metin> [--timeout SN] [--gone] [--region ..]"),
    N_("  ekran -b DESEN close (kapat) <kimlik>   pencereyi kapatır (başlık kilidi zorunlu)"),
    N_("  ekran hold (bas) <kimlik> <tuş[+tuş]> <SN>   tuşu basılı tut (oyunda yürüme); kesintide hemen bırakır"),
    N_("  ekran click ... --hold SN | --repeat N   fare düğmesini basılı tut (kazma) / N kez tıkla"),
    N_("  ekran drag (surukle) <kimlik> x1 y1 x2 y2 [left|right] [--duration 0.4]   sürükle-bırak"),
    N_("  ekran move (fare) <kimlik> x y          tıklamadan gezdir (açıklama baloncuğu)"),
    N_("  ekran batch (dizi) <kimlik> [--file F] <<EOF   adımlar tek süreçte (tek dotool kurulumu, oyunlar için hız)"),
    N_("  ekran sleep (uyu) SN                    (dizi içinde) bekle"),
    N_("  ekran find-color (renk-bul) <kimlik> green|red|blue|R,G,B [--region]   renkli alanlar (yazısı okunmayan "
       "düğmeler)"),
    N_("  ekran click-color (renge-tikla) <kimlik> <renk> [--region] [--nth N]   en büyük renk alanının ortasına tıkla"),
    N_("  ekran save-icon (simge-kaydet) <kimlik> <ad> --region x,y,g,y   yazısız simgeyi kaydet "
       "(~/.local/share/deskhand/simgeler)"),
    N_("  ekran find-icon (simge-bul) <kimlik> <ad> [--threshold 0.9] [--region ..]"),
    N_("  ekran click-icon (simgeye-tikla) <kimlik> <ad> [right|double] [--nth N] [--threshold 0.9] [--region ..]\n"
       "                    [--approved]"),
    N_("  ekran open (ac) <uygulama | --command \"KOMUT\"> [-b DESEN] [-s SINIF] [--timeout 30]\n"
       "                                          başlat → YENİ penceresini bekle → kimlik | başlık | sınıf "
       "(yasak: başlatılmaz)"),
    N_("  ekran flow (akis) <kimlik> <dosya|ad> [--timeout SN]   ekran tanıma akışı "
       "(~/.local/share/deskhand/akislar/AD.akis):\n"
       "                                          ekranı oku → hangi ekran → o ekranın adımları; başarıya dek, "
       "tekrar korumalı"),
    N_("  ekran a11y (erisim) [on|off|status]     erişilebilirlik ağacını aç/kapat (Qt/GTK düğmeleri ad + konumla)"),
    N_("  ekran tree (agac) <kimlik> [desen] [--role R] [--all]   penceredeki ögeler: (merkez x,y) rol: ad"),
    N_("  ekran click-element (ogeye-tikla) <kimlik> <ad> [right|double] [--role R] [--nth N] [--approved]\n"
       "                                          ADIYLA tıkla (OCR'sız)"),
    N_("  ekran stop | resume | status (dur | devam | durum)   DUR anahtarı: aç (hiçbir girdi gönderilmez) / kaldır / "
       "göster"),
    N_("  ekran desktop (masaustu) start|stop|status [--json]   görünmez arka plan masaüstü (Xvfb); --background "
       "komutları onu kullanır"),
    N_("  ekran mcp [--desktop auto|background]  MCP sunucusu (stdio) — Claude Code vb. için 12 araç"),
    N_("  ekran sessions (oturum) status|policy|clear   arka plan oturum aktarımı (hangi uygulama girişli açılır)"),
    N_("  ekran panel [--tepsi]                   izleme paneli + tepsi simgesi (DUR, Devral, onaylar, ayarlar)"),
    N_("  ekran busy (mesgul) [--json]            kullanıcı meşgul mü (tam ekran, çalan medya, klavye/fare, oyun, "
       "kilit);\n"
       "                                          yalnız okur, girdi göndermez"),
    N_("  ekran decide (karar) \"görev özeti\" [--json]   işi nerede yapayım: on | arka | sonra (çıkış kodu 0 | 20 | 21).\n"
       "                                          Meşgulse ayara göre (~/.config/deskhand/ayarlar.toml [karar]) "
       "bildirimle\n"
       "                                          sorar: Arka planda yap / Ekranımda yap / Sonra. \"arka\" → komutlara "
       "--background"),
    N_("  ekran help (yardım)                     bu metin"),
)
YARDIM_ORTAK = (
    N_("Ortak: -b/--title (--baslik) DESEN  başlık bu deseni (regex, büyük/küçük harf duyarsız) içermezse DUR."),
    N_("       -s/--class (--sinif) DESEN   pencere sınıfı (ör. krunner, vivaldi-stable) uymazsa DUR (başlıksız "
       "pencereler için)."),
    N_("       --background (--arka)        görünmez ikinci masaüstünde çalış (sanal arka uç; ortam: "
       "DESKHAND_HEDEF=arka)."),
    N_("       --on-my-screen (--ekranimda) kullanıcı oyunda/film izlerken bile ekranında çalış (YALNIZ kullanıcı "
       "açıkça izin verdiyse)."),
    N_("screenshot/read/wait bitince önceki pencere geri öne gelir (--stay: gelmesin)."),
)
YARDIM_CIKIS = (
    N_("Çıkış kodları: 0 tamam, 1 kullanım, 2 nokta pencere/ekran dışında, 3 pencere aktif değil,\n"
       "4 başlık uymadı, 5 birden çok eşleşme (--nth ver), 6 metin bulunamadı, 7 zaman aşımı,\n"
       "8 pencere yok/taşındı, 9 dotool/tesseract çalışmadı, 10 yasak pencere / hassas düğme (onay gerekir),"),
    N_("11 akış hata ekranı / 'dur' adımı, 12 kullanıcı bilgisayarı kullanıyor (insan önceliği),\n"
       "13 kullanıcı DUR dedi (ekran resume), 14 sanal masaüstü kullanılamıyor,\n"
       "15 kullanıcı oyunda/film izliyor (ekranına müdahale yok; --background),\n"
       "16 uygulama arka planda açılamaz (kullanıcının ekranında açık ya da yalnız ön plan);\n"
       "karar: 0 on, 20 arka, 21 sonra"),
)


def komut_listesi():
    """Komutlar paragrafı (argümansız çağrının çıktısı): başlık + komut satırları + ortak seçenekler."""
    return "\n".join(_(m) for m in (*YARDIM_KOMUT_BASI, *YARDIM_KOMUTLAR, *YARDIM_ORTAK))


def yardim_metni():
    """`yardım` / -h metni (çevrilmiş). Komut satırları programın çağrıldığı adla başlar (deskhand ya da ekran)."""
    metin = "\n\n".join((_(YARDIM_GIRIS).format(surum=__version__),
                         "\n".join(_(m) for m in YARDIM_GUVENLIK),
                         komut_listesi(),
                         "\n".join(_(m) for m in YARDIM_CIKIS))) + "\n"
    return re.sub(r"(?m)^(\s+)(?:ekran|deskhand)(?=\s)", lambda m: m.group(1) + prog_adi(), metin)


KOMUTSUZ_ARKA_UC = {"dur", "devam", "durum", "yardım", "yardim", "uyu", "mesgul", "karar", "panel", "masaustu", "oturum", "mcp"}  # arka uç gerekmeyen komutlar


def prog_adi():
    ad = os.path.basename(sys.argv[0] or "")
    return "ekran" if ad == "ekran" else "deskhand"


def arka_al():
    """Bu komutun arka ucu. Sanal arka uç yüklenemezse Dur(14)."""
    try:
        return sec()
    except ImportError as e:
        if hedef_ad() != "sanal":
            raise
        raise Dur(SANAL_KAPALI, _("sanal masaüstü kullanılamıyor ({hata})").format(hata=e))


# ---------------------------------------------------------------- küçük komutlar

def k_bul(a):
    for w, b, geo in arka_al().pencereler(a.desen):
        print(f"{w} | {b} | {' '.join(map(str, geo))}")


def k_dur(a):
    yol = guvenlik.dur_ac()
    gunluk("DUR anahtarı açıldı")
    print(_("DUR: açık ({yol}); hiçbir girdi gönderilmez. Kaldırmak için: {prog} devam").format(yol=yol, prog=prog_adi()))


def k_devam(a):
    acikti = guvenlik.dur_kapat()
    if acikti:
        gunluk("DUR anahtarı kaldırıldı")
    print(_("DUR: kapalı") if acikti else _("DUR: kapalı (zaten kapalıydı)"))


def k_durum(a):
    dur = (_("AÇIK ({yol})").format(yol=dur_dosyasi()) if guvenlik.dur_acik() else _("kapalı"))
    print(_("deskhand {surum} | arka uç: {arka_uc} (DESKHAND_HEDEF={hedef}) | DUR: {dur}").format(
        surum=__version__, arka_uc=hedef_ad(), hedef=os.environ.get("DESKHAND_HEDEF", "on"), dur=dur))


def k_panel(a):
    """İzleme paneli + tepsi (PyQt6). --tepsi: yalnız tepsiyle başla."""
    from .gui.__main__ import main as panel_main
    raise SystemExit(panel_main(a.arg))


def k_oturum(a):
    """Arka plan oturum aktarımı: durum | hazirla <uygulama> | politika | sil."""
    from .oturum.cli import main as oturum_main
    raise SystemExit(oturum_main(a.arg))


def k_mcp(a):
    """MCP sunucusu (stdio): yapay zekâ ajanları araçları doğrudan görür. Kayıt: README.md (MCP)."""
    from .mcp_sunucu import main as mcp_main
    raise SystemExit(mcp_main(["--desktop", a.desktop]))


def k_masaustu(a):
    """Görünmez arka plan masaüstü: baslat | durdur | durum [--json]."""
    from .masaustu import main as masaustu_main
    raise SystemExit(masaustu_main(a.arg))


def k_yardim(a):
    print(yardim_metni())


# ---------------------------------------------------------------- ayrıştırıcı

def secenek(s, *adlar, en=None, **kw):
    """Seçenek ekle: İngilizce ad birincil (yardımda önce), Türkçe ad takma ad, dest Türkçe ad.
    adlar: kısa ad (-b) ve/veya Türkçe uzun ad (--baslik); en: İngilizce ad (verilmezse SECENEKLER'den)."""
    uzun = [x for x in adlar if x.startswith("--")]
    kisa = [x for x in adlar if not x.startswith("--")]
    en = en or SECENEKLER.get(uzun[0])
    kw.setdefault("dest", uzun[0][2:].replace("-", "_"))
    if kw.get("action") not in ("store_true", "store_false", "append_const", "count") and "metavar" not in kw:
        kw["metavar"] = (en or uzun[0])[2:].upper().replace("-", "_")
    return s.add_argument(*kisa, *([en] if en and en not in uzun else []), *uzun, **kw)


class AyristirmaHatasi(ValueError):
    """sessiz ayrıştırıcıda argparse hatası (yazdırıp çıkmak yerine)."""


class _Ayristirici(argparse.ArgumentParser):
    """Kullanım hatasında çıkış kodu 1 (argparse'ın 2'si Deskhand'de "nokta dışarıda" demek)."""
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: {_('hata')}: {message}\n")


class _SessizAyristirici(argparse.ArgumentParser):
    def error(self, message):
        raise AyristirmaHatasi(message)


def ayristirici(prog=None, sessiz=False):
    """Komut satırı ayrıştırıcısı. Seçenek KISALTMASI YOK (allow_abbrev=False, alt komutlar dahil): `--onay` ya da
    `--appr` `--onayli`/`--approved` sayılmasın (akış/dizi adımlarındaki önceden onay denetimi tam adla yapılır).
    sessiz=True: hata yazdırıp çıkmak yerine AyristirmaHatasi (dizi/akış adımları, ön tarama)."""
    sinif = _SessizAyristirici if sessiz else _Ayristirici
    ortak = sinif(add_help=False, allow_abbrev=False)
    secenek(ortak, "-b", "--baslik", default=argparse.SUPPRESS, help=h_("başlık kilidi (regex)"))
    secenek(ortak, "-s", "--sinif", default=argparse.SUPPRESS, help=h_("pencere sınıfı kilidi (regex), ör. krunner"))
    okuma = sinif(add_help=False, allow_abbrev=False)
    secenek(okuma, "--kal", action="store_true", help=h_("bitince önceki pencereyi geri getirme"))
    p = sinif(prog=prog or prog_adi(), description=yardim_metni(), formatter_class=argparse.RawDescriptionHelpFormatter,
              allow_abbrev=False)
    secenek(p, "-b", "--baslik", default=None, help=h_("başlık kilidi (regex)"))
    secenek(p, "-s", "--sinif", default=None, help=h_("pencere sınıfı kilidi (regex), ör. krunner"))
    alt = p.add_subparsers(dest="komut", required=True, metavar=_("KOMUT"))
    secenek(ortak, "--arka", action="store_true", default=argparse.SUPPRESS,
            help=h_("görünmez ikinci masaüstünde (sanal arka uç)"))
    secenek(p, "--arka", action="store_true", default=False, help=h_("görünmez ikinci masaüstünde (sanal arka uç)"))
    secenek(p, "--ekranimda", action="store_true", default=False,
            help=h_("kullanıcı oyunda/film izlerken bile ekranında çalış (YALNIZ kullanıcı açıkça izin verdiyse)"))
    secenek(ortak, "--ekranimda", action="store_true", default=argparse.SUPPRESS,  # komuttan sonra da kabul
            help=h_("kullanıcı oyunda/film izlerken bile ekranında çalış (YALNIZ kullanıcı açıkça izin verdiyse)"))
    dugmeler = ["sol", "sag", "cift", "orta"]

    def komut(tr, f, **kw):
        """Alt komut: İngilizce adla, Türkçe ad(lar) takma ad; `komut` alanı her zaman Türkçe iç ad."""
        s = alt.add_parser(TR_EN[tr], aliases=takma_adlar(tr), allow_abbrev=False, **kw)
        s.set_defaults(f=f, komut=tr)
        return s

    def dugme(s, secenekler=dugmeler):
        s.add_argument("dugme", nargs="?", default="sol", type=cevirici(DUGME), choices=secimler(DUGME, secenekler),
                       metavar="{" + ",".join(en for en, t in DUGME.items() if t in secenekler) + "}")

    s = komut("bul", k_bul, parents=[ortak]); s.add_argument("desen")
    s = komut("foto", k_foto, parents=[ortak, okuma]); s.add_argument("kimlik"); s.add_argument("cikti", nargs="?")
    secenek(s, "--bolge"); secenek(s, "--genislik", type=int)
    secenek(s, "--izgara", type=int, nargs="?", const=100)
    s = komut("tikla", k_tikla, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("x", type=float)
    s.add_argument("y", type=float); dugme(s)
    secenek(s, "--foto", action="store_true", help=h_("x,y son fotoğrafın pikseli (bölge/ölçek eşlenir)"))
    secenek(s, "--onayli", action="store_true", help=h_("kullanıcı bu hassas tıklamayı AÇIKÇA onayladı"))
    secenek(s, "--basili", type=float, default=0.0, help=h_("düğmeyi SN basılı tut (oyunda kazma)"))
    secenek(s, "--tekrar", type=int, default=1, help=h_("N kez tıkla"))
    s = komut("bas", k_bas, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("tuslar")
    s.add_argument("sure", type=float); secenek(s, "--onayli", action="store_true")
    s = komut("fare", k_fare, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("x", type=float)
    s.add_argument("y", type=float)
    s = komut("surukle", k_surukle, parents=[ortak]); s.add_argument("kimlik")
    for ad in ("x1", "y1", "x2", "y2"):
        s.add_argument(ad, type=float)
    dugme(s, ["sol", "sag", "orta"])
    secenek(s, "--sure", en="--duration", type=float, default=0.4); secenek(s, "--onayli", action="store_true")
    s = komut("uyu", k_uyu); s.add_argument("sn", type=float)
    s = komut("dizi", k_dizi, parents=[ortak]); s.add_argument("kimlik"); secenek(s, "--dosya")
    s = komut("tus", k_tus, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("kombinasyon")
    secenek(s, "--onayli", action="store_true", help=h_("ödeme sayfasında Enter/boşluk: kullanıcı AÇIKÇA onayladı"))
    s = komut("kapat", k_kapat, parents=[ortak]); s.add_argument("kimlik")
    s = komut("yaz", k_yaz, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("metin")
    secenek(s, "--gizli", action="store_true", help=h_("günlüğe metni yazma"))
    secenek(s, "--onayli", action="store_true",
            help=h_("ödeme sayfasında Enter/Tab/boşluk içeren yazı: kullanıcı AÇIKÇA onayladı"))
    s = komut("kaydir", k_kaydir, parents=[ortak]); s.add_argument("kimlik")
    s.add_argument("yon", nargs="?", default="asagi", type=cevirici(YON), choices=secimler(YON, KAYDIR_YON),
                   metavar="{" + ",".join(YON) + "}")
    s.add_argument("adim", nargs="?", type=int, default=5)
    secenek(s, "--nokta", help=h_("x,y (varsayılan: pencere ortası)"))
    s = komut("metin", k_metin, parents=[ortak, okuma]); s.add_argument("kimlik"); s.add_argument("desen", nargs="?")
    secenek(s, "--bolge"); secenek(s, "--hassas", action="store_true")
    secenek(s, "--hepsi", action="store_true", help=h_("gürültü süzgeci kapalı"))
    secenek(s, "--derin", action="store_true", help=h_("3 okuma yöntemi birlikte: renkli düğmeler de görünür"))
    s = komut("metne-tikla", k_metne_tikla, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("metin")
    dugme(s)
    secenek(s, "--sira", type=int); secenek(s, "--bekle", type=float, default=0.0)
    secenek(s, "--kay", help=h_("dx,dy: metnin merkezinden kaydırarak tıkla (ör. etiketin sağındaki kutu)"))
    secenek(s, "--kaydirarak", type=int, nargs="?", const=10, default=0,
            help=h_("bulunamazsa sayfayı aşağı kaydırıp ara (en çok N kez, varsayılan 10)"))
    secenek(s, "--onayli", action="store_true", help=h_("kullanıcı bu hassas tıklamayı AÇIKÇA onayladı"))
    secenek(s, "--bolge")
    s = komut("simge-kaydet", k_simge_kaydet, parents=[ortak, okuma]); s.add_argument("kimlik"); s.add_argument("ad")
    secenek(s, "--bolge")
    s = komut("simge-bul", k_simge_bul, parents=[ortak, okuma]); s.add_argument("kimlik"); s.add_argument("ad")
    secenek(s, "--esik", type=float, default=0.9); secenek(s, "--bolge")
    s = komut("simgeye-tikla", k_simgeye_tikla, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("ad")
    dugme(s)
    secenek(s, "--esik", type=float, default=0.9); secenek(s, "--sira", type=int); secenek(s, "--bolge")
    secenek(s, "--onayli", action="store_true", help=h_("kullanıcı bu hassas tıklamayı AÇIKÇA onayladı"))
    s = komut("renk-bul", k_renk_bul, parents=[ortak, okuma]); s.add_argument("kimlik")
    s.add_argument("renk", type=cevirici(RENK))
    secenek(s, "--bolge"); secenek(s, "--en-az", type=int, default=250)
    s = komut("renge-tikla", k_renge_tikla, parents=[ortak]); s.add_argument("kimlik")
    s.add_argument("renk", type=cevirici(RENK)); dugme(s); secenek(s, "--bolge")
    secenek(s, "--en-az", type=int, default=250); secenek(s, "--sira", type=int)
    secenek(s, "--onayli", action="store_true")
    s = komut("bekle", k_bekle, parents=[ortak, okuma]); s.add_argument("kimlik"); s.add_argument("metin")
    secenek(s, "--sure", en="--timeout", type=float, default=10.0); secenek(s, "--yok", action="store_true")
    secenek(s, "--bolge")
    s = komut("ac", k_ac, parents=[ortak]); s.add_argument("uygulama", nargs="?")
    secenek(s, "--komut", dest="komut_satiri", help=h_("uygulama adı yerine bu komutu başlat"))
    s.add_argument("--site", action="append",
                   help=h_("(--arka) oturum kopyasına bu sitenin yerel deposunu da al; tekrarlanabilir"))
    secenek(s, "--sure", en="--timeout", type=float, default=30.0)
    s = komut("akis", k_akis, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("dosya")
    secenek(s, "--sure", en="--timeout", type=float, help=h_("dosyadaki süreyi geçersiz kıl"))
    s = komut("erisim", k_erisim)
    s.add_argument("islem", nargs="?", default="durum", type=cevirici(ERISIM),
                   choices=secimler(ERISIM, ["ac", "kapat", "durum"]), metavar="{on,off,status}")
    s = komut("agac", k_agac, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("desen", nargs="?")
    secenek(s, "--rol", help=h_("yalnız bu rol (ör. 'push button', 'check box')"))
    secenek(s, "--hepsi", action="store_true", help=h_("etkileşimsiz ögeler dahil hepsi"))
    s = komut("ogeye-tikla", k_ogeye_tikla, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("ad")
    dugme(s); secenek(s, "--rol")
    secenek(s, "--sira", type=int)
    secenek(s, "--onayli", action="store_true", help=h_("kullanıcı bu hassas tıklamayı AÇIKÇA onayladı"))
    s = komut("mesgul", k_mesgul); s.add_argument("--json", action="store_true")
    s = komut("panel", k_panel, add_help=False); s.add_argument("arg", nargs=argparse.REMAINDER)
    s = komut("oturum", k_oturum, add_help=False); s.add_argument("arg", nargs=argparse.REMAINDER)
    s = komut("mcp", k_mcp); s.add_argument("--desktop", choices=["auto", "background"], default="auto")
    s = komut("masaustu", k_masaustu, add_help=False); s.add_argument("arg", nargs=argparse.REMAINDER)
    s = komut("karar", k_karar); s.add_argument("ozet", help=h_("görev özeti (bildirimde gösterilir)"))
    s.add_argument("--json", action="store_true")
    komut("dur", k_dur)
    komut("devam", k_devam)
    komut("durum", k_durum)
    komut("yardım", k_yardim)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(komut_listesi())
        sys.exit(1)
    yollar.gecis()  # eski ekran klasörleri → deskhand (yalnız ilk açılışta, kopya)
    temizle()
    # Kendi ayrıştırıcısı olan komutlar: argümanları olduğu gibi devret. argparse REMAINDER, '--tepsi' gibi
    # seçenekle başlayan argümanı alt komuta bırakmıyordu ("unrecognized arguments: --tepsi").
    gecis = {"panel": k_panel, "oturum": k_oturum, "masaustu": k_masaustu}
    ilk = ic_ad(argv[0]) if argv else ""
    if ilk in gecis:
        gecis[ilk](argparse.Namespace(arg=argv[1:]))
    a = ayristirici().parse_args(argv)
    if a.arka or str(getattr(a, "kimlik", "") or "").startswith(ARKA_ONEK):
        os.environ["DESKHAND_HEDEF"] = "arka"  # bu süreç ve başlattıkları aynı arka ucu seçsin
    if a.ekranimda:
        os.environ["DESKHAND_EKRANIMDA"] = "1"  # kullanıcı açıkça izin verdi: oyun/film sırasında da ön plan
    guvenlik.SINIF_DESEN = a.sinif
    onceki = au = None
    try:
        if a.komut in GIRDI_KOMUTLARI or a.komut == "ac":
            dur_denetle()  # DUR anahtarı açıkken hiçbir şeye başlama
        if a.komut not in KOMUTSUZ_ARKA_UC:
            au = arka_al()
        if hasattr(a, "kimlik"):
            a.kimlik_ham = a.kimlik
            a.kimlik = au.pencere_coz(a.kimlik)
        if a.komut in GIRDI_KOMUTLARI:
            yasak_denetle(a.kimlik)  # yasak pencerede hiçbir şeye başlama
        if a.komut in OKUMA_KOMUTLARI and not a.kal:
            onceki = au.aktif()
        a.f(a)
    except Dur as e:
        print(_("DURDURULDU: {mesaj}").format(mesaj=e.mesaj), file=sys.stderr)
        if a.komut in GIRDI_KOMUTLARI or a.komut == "ac":
            gunluk(f"DUR {e.kod} | {a.komut} {getattr(a, 'kimlik', '')} | {e.mesaj.splitlines()[0]}")
        sys.exit(e.kod)
    finally:
        # okuma bitti: hedef hâlâ öndeyse (kullanıcı başka yere geçmediyse) önceki pencereyi geri getir
        if au is not None and onceki and onceki != getattr(a, "kimlik", None) and \
                au.aktif() == getattr(a, "kimlik", None):
            etkinlestir = getattr(au, "etkinlestir", None)
            if etkinlestir:
                etkinlestir(onceki)
            else:
                try:
                    au.one_getir(onceki)
                except Dur:
                    pass
