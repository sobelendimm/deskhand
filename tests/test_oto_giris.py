"""Otomatik giriş algılama + cüzdan kartı kararı (deskhand/oto_giris.py) testleri. Gerçek /etc, /proc, /sys OKUNMAZ:
her test tmp altında sahte bir kök (kok=) kurar. Gerçek cüzdan, busctl, TPM kullanılmaz: cuzdan_ac işlevleri süreç
içinde sahteyle değiştirilir; durum dosyaları _yalitim'in geçici DESKHAND_STATE_DIR'ünde.

Çalıştır:  python3 tests/test_oto_giris.py"""
import os
import pwd
import shutil
import stat
import sys
import tempfile

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import cuzdan_ac as CA
from deskhand import oto_giris as OG
from deskhand import yollar

gecen = toplam = 0
BEN = pwd.getpwuid(os.getuid()).pw_name
BASKA = "baska-kullanici"


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def yeni_kok(dm="plasmalogin.service"):
    kok = tempfile.mkdtemp(prefix="sahte-kok-", dir=_yalitim.GECICI)
    if dm:
        os.makedirs(os.path.join(kok, "etc/systemd/system"))
        os.symlink(f"/usr/lib/systemd/system/{dm}", os.path.join(kok, "etc/systemd/system/display-manager.service"))
    return kok


def yaz(kok, goreli, metin, kip=None):
    yol = os.path.join(kok, goreli)
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    with open(yol, "wb" if isinstance(metin, bytes) else "w") as f:
        f.write(metin)
    if kip is not None:
        os.chmod(yol, kip)
    return yol


def oto(user=None, oturum="plasma"):
    s = "[Autologin]\n"
    if user is not None:
        s += f"User={user}\n"
    return s + f"Session={oturum}\n"


# ---------------------------------------------------------------- algılama

def test_ana_dosya_confd_ezer():
    kok = yeni_kok()
    yaz(kok, "etc/plasmalogin.conf.d/oto.conf", oto(BEN))
    yaz(kok, "etc/plasmalogin.conf", oto())  # bu makinedeki gibi: ana dosyada User yok → conf.d geçerli
    kontrol("ana dosyada User anahtarı yok → conf.d'deki kullanıcı", OG.otomatik_giris_kullanicisi(kok) ==
            (BEN, "plasmalogin"), OG.otomatik_giris_kullanicisi(kok))
    kontrol("…ve otomatik_giris_acik True", OG.otomatik_giris_acik(kok) is True)
    yaz(kok, "etc/plasmalogin.conf", oto(BASKA))
    kontrol("ana dosya conf.d'yi EZER (User=başka)", OG.otomatik_giris_kullanicisi(kok) == (BASKA, "plasmalogin"),
            OG.otomatik_giris_kullanicisi(kok))
    kontrol("…ve otomatik_giris_acik False", OG.otomatik_giris_acik(kok) is False)
    # conf.d sırası: /usr/lib önce, /etc sonra; aynı klasörde ada göre
    kok = yeni_kok()
    yaz(kok, "usr/lib/plasmalogin/plasmalogin.conf.d/00.conf", oto(BASKA))
    yaz(kok, "etc/plasmalogin.conf.d/10.conf", oto(BEN))
    kontrol("/etc/…conf.d /usr/lib/…conf.d'yi ezer", OG.otomatik_giris_kullanicisi(kok)[0] == BEN)
    yaz(kok, "etc/plasmalogin.conf.d/20.conf", oto(BASKA))
    kontrol("aynı klasörde sonraki ad kazanır", OG.otomatik_giris_kullanicisi(kok)[0] == BASKA)
    yaz(kok, "etc/plasmalogin.conf.d/notlar.txt", oto(BEN))
    kontrol(".conf olmayan dosya okunmaz", OG.otomatik_giris_kullanicisi(kok)[0] == BASKA)
    # KConfig anahtarları büyük/küçük harf duyarlı; ':' ayırıcı değil
    kok = yeni_kok()
    yaz(kok, "etc/plasmalogin.conf", f"[Autologin]\nuser={BEN}\nUser:{BEN}\n")
    kontrol("'user=' ve 'User:' User sayılmaz", OG.otomatik_giris_kullanicisi(kok) == (None, None),
            OG.otomatik_giris_kullanicisi(kok))
    kok = yeni_kok()
    yaz(kok, "etc/plasmalogin.conf", f"User={BEN}\n[General]\nUser={BEN}\n")
    kontrol("[Autologin] dışındaki User sayılmaz", OG.otomatik_giris_kullanicisi(kok) == (None, None))


def test_bos_user_siler():
    kok = yeni_kok()
    yaz(kok, "etc/plasmalogin.conf.d/oto.conf", oto(BEN))
    yaz(kok, "etc/plasmalogin.conf", oto(""))
    kontrol("ana dosyada boş User= conf.d'deki kullanıcıyı siler", OG.otomatik_giris_kullanicisi(kok) == (None, None),
            OG.otomatik_giris_kullanicisi(kok))
    kontrol("…otomatik_giris_acik False", OG.otomatik_giris_acik(kok) is False)
    kok = yeni_kok()
    yaz(kok, "usr/lib/plasmalogin/plasmalogin.conf.d/a.conf", oto(BEN))
    yaz(kok, "etc/plasmalogin.conf.d/b.conf", "[Autologin]\nUser=   \n")
    kontrol("yalnız boşluklu User= de siler", OG.otomatik_giris_kullanicisi(kok) == (None, None))


def test_baska_kullanici_kart_yok():
    kok = yeni_kok()
    yaz(kok, "etc/plasmalogin.conf.d/oto.conf", oto(BASKA))
    kontrol("başka kullanıcı için otomatik giriş → otomatik_giris_acik False", OG.otomatik_giris_acik(kok) is False)
    with sahte_cuzdan(var=True, kurulu=False):
        d = OG.kart_durumu(kok=kok)
    kontrol("başka kullanıcı → kart yok (giris_parolali)", d["goster"] is False and d["neden"] == "giris_parolali" and
            d["oto_giris"] is False, d)
    kok = yeni_kok()
    with sahte_cuzdan(var=True, kurulu=False):
        d = OG.kart_durumu(kok=kok)
    kontrol("hiç yapılandırma yok → kart yok", d["goster"] is False and d["neden"] == "giris_parolali", d)


def test_sddm_etkin_plasmalogin_yok_sayilir():
    kok = yeni_kok("sddm.service")
    yaz(kok, "etc/plasmalogin.conf.d/oto.conf", oto(BEN))
    kontrol("sddm etkin → plasmalogin dosyaları yok sayılır", OG.otomatik_giris_kullanicisi(kok) == (None, None),
            OG.otomatik_giris_kullanicisi(kok))
    yaz(kok, "usr/lib/sddm/sddm.conf.d/00.conf", oto(BASKA))
    yaz(kok, "etc/sddm.conf.d/10.conf", oto(BEN))
    kontrol("sddm: /etc/sddm.conf.d okunur", OG.otomatik_giris_kullanicisi(kok) == (BEN, "sddm"))
    yaz(kok, "etc/sddm.conf", oto(""))
    kontrol("sddm: ana dosyada boş User= siler", OG.otomatik_giris_kullanicisi(kok) == (None, None))
    # plasmalogin etkin → sddm dosyaları yok sayılır
    kok = yeni_kok("plasmalogin.service")
    yaz(kok, "etc/sddm.conf", oto(BEN))
    kontrol("plasmalogin etkin → sddm dosyaları yok sayılır", OG.otomatik_giris_kullanicisi(kok) == (None, None))
    # başka bir giriş yöneticisi (gdm) → ikisi de yok sayılır
    kok = yeni_kok("gdm.service")
    yaz(kok, "etc/plasmalogin.conf", oto(BEN))
    yaz(kok, "etc/sddm.conf", oto(BEN))
    kontrol("gdm etkin → hiçbiri", OG.otomatik_giris_kullanicisi(kok) == (None, None))
    # bağ yok (bilinmiyor) → ikisine de bakılır, plasmalogin önce
    kok = yeni_kok(dm=None)
    yaz(kok, "etc/sddm.conf", oto(BASKA))
    kontrol("bağ yok → sddm okunur", OG.otomatik_giris_kullanicisi(kok) == (BASKA, "sddm"))
    yaz(kok, "etc/plasmalogin.conf", oto(BEN))
    kontrol("bağ yok → plasmalogin önce", OG.otomatik_giris_kullanicisi(kok) == (BEN, "plasmalogin"))


def test_okunamaz_dosya_atlanir():
    kok = yeni_kok()
    yaz(kok, "etc/plasmalogin.conf.d/10.conf", oto(BEN))
    yaz(kok, "etc/plasmalogin.conf.d/20.conf", oto(BASKA), kip=0)
    yaz(kok, "etc/plasmalogin.conf.d/30.conf", oto(BASKA) + "#" * (64 * 1024 + 1) + "\n")
    yaz(kok, "etc/plasmalogin.conf.d/40.conf", b"[Autologin]\nUser=" + BASKA.encode() + b"\xff\xfe\n")
    yaz(kok, "etc/plasmalogin.conf.d/50.conf", f"[Autologin\nUser={BASKA}\n")
    os.makedirs(os.path.join(kok, "etc/plasmalogin.conf.d/60.conf"))
    okunabilir = os.access(os.path.join(kok, "etc/plasmalogin.conf.d/20.conf"), os.R_OK)  # root ise okunur
    sonuc = OG.otomatik_giris_kullanicisi(kok)
    kontrol("okunamaz / >64 KiB / UTF-8 değil / bozuk / klasör → atlanır, kalan dosyalar geçerli",
            sonuc == (BEN, "plasmalogin") or okunabilir, sonuc)


def test_ana_dosya_okunamaz_bilinmiyor():
    """A3 D2: conf.d'de okunamayan dosya atlanır (KConfig), ama ana dosya var ve okunamıyorsa sonuç BİLİNMİYOR: ne
    "otomatik giriş var" ne "yok"; kart gizli, neden giris_bilinmiyor (kapalı-başarısızlık)."""
    if os.geteuid() == 0:
        kontrol("ana dosya okunamaz (root: izin sınanamaz, atlandı)", True)
        return
    kok = yeni_kok()
    yaz(kok, "etc/plasmalogin.conf.d/oto.conf", oto(BEN))
    yaz(kok, "etc/plasmalogin.conf", oto(""), kip=0)  # okunsa conf.d'yi silerdi
    kontrol("ana dosya okunamaz → otomatik_giris_kullanicisi (None, None)",
            OG.otomatik_giris_kullanicisi(kok) == (None, None), OG.otomatik_giris_kullanicisi(kok))
    kontrol("…otomatik_giris_acik False (conf.d'deki User=ben ile kart açılmaz)", OG.otomatik_giris_acik(kok) is False)
    _isaret_sil()
    with sahte_cuzdan():
        d = OG.kart_durumu(kok=kok)
    kontrol("…kart gizli, neden giris_bilinmiyor (giris_parolali değil)", d["goster"] is False and
            d["neden"] == "giris_bilinmiyor" and d["oto_giris"] is False, d)
    # ana dosya UTF-8 değil / >64 KiB / klasör → aynı (bilinmiyor)
    for ad, icerik in (("UTF-8 değil", b"[Autologin]\nUser=\xff\n"), (">64 KiB", oto("") + "#" * (64 * 1024 + 1))):
        kok = yeni_kok()
        yaz(kok, "etc/plasmalogin.conf.d/oto.conf", oto(BEN))
        yaz(kok, "etc/plasmalogin.conf", icerik)
        with sahte_cuzdan():
            d = OG.kart_durumu(kok=kok)
        kontrol(f"ana dosya {ad} → giris_bilinmiyor", d["neden"] == "giris_bilinmiyor", d)
    # ana dosya YOK → bilinmiyor değil: conf.d geçerli
    kok = yeni_kok()
    yaz(kok, "etc/plasmalogin.conf.d/oto.conf", oto(BEN))
    with sahte_cuzdan():
        d = OG.kart_durumu(kok=kok)
    kontrol("ana dosya yok → conf.d geçerli, kart gösterilir", d["goster"] is True and d["oto_giris"] is True, d)
    # sddm etkin: sddm'nin ana dosyası okunamaz → bilinmiyor; plasmalogin'inki önemsiz
    kok = yeni_kok("sddm.service")
    yaz(kok, "etc/sddm.conf.d/oto.conf", oto(BEN))
    yaz(kok, "etc/plasmalogin.conf", oto(""), kip=0)
    kontrol("sddm etkin: plasmalogin ana dosyası okunamaz → yok sayılır", OG.otomatik_giris_acik(kok) is True)
    yaz(kok, "etc/sddm.conf", oto(""), kip=0)
    with sahte_cuzdan():
        d = OG.kart_durumu(kok=kok)
    kontrol("sddm etkin: sddm ana dosyası okunamaz → giris_bilinmiyor", d["neden"] == "giris_bilinmiyor", d)


def test_bozuk_satir_atlanir_dosya_okunur():
    """A3 B3: KConfig gibi hoşgörülü — bozuk satır atlanır, dosyanın geri kalanı okunur."""
    kok = yeni_kok()
    yaz(kok, "etc/plasmalogin.conf.d/oto.conf", f"[General]\nbu satır bozuk\n[Eksik grup\n[Autologin]\n"
        f"çöp satır yine\nUser={BEN}\nSession=plasma\n")
    kontrol("bozuk satırlar + User= içeren dosya okunur", OG.otomatik_giris_kullanicisi(kok) == (BEN, "plasmalogin"),
            OG.otomatik_giris_kullanicisi(kok))
    yaz(kok, "etc/plasmalogin.conf", "[Autologin]\nbozuk satır\n[Kapanmayan\nUser=\n")
    kontrol("ana dosyadaki boş User= bozuk satırlara rağmen conf.d'yi ezer",
            OG.otomatik_giris_kullanicisi(kok) == (None, None), OG.otomatik_giris_kullanicisi(kok))
    yaz(kok, "etc/plasmalogin.conf", f"[Autologin]\n[Autologin][Alt]\nUser={BASKA}\n")
    kontrol("iç içe grup [Autologin][Alt] User'ı [Autologin] sayılmaz",
            OG.otomatik_giris_kullanicisi(kok) == (BEN, "plasmalogin"), OG.otomatik_giris_kullanicisi(kok))
    yaz(kok, "etc/plasmalogin.conf", f"[Autologin]\nUser={BASKA}\n  User = {BEN}  \n")
    kontrol("aynı dosyada son User= kazanır, boşluklar kırpılır",
            OG.otomatik_giris_kullanicisi(kok) == (BEN, "plasmalogin"), OG.otomatik_giris_kullanicisi(kok))


# ---------------------------------------------------------------- disk şifreleme

def _sys_blok(kok, ad, majmin, uuid=None, alt=()):
    """sys/devices/virtual/block/<ad> (+ dm/uuid, slaves/<alt> → ../../<alt>), sys/dev/block/<majmin> ve
    sys/class/block/<ad> bağları (gerçek sysfs gibi göreli)."""
    d = os.path.join(kok, "sys/devices/virtual/block", ad)
    os.makedirs(os.path.join(d, "slaves"), exist_ok=True)
    if uuid is not None:
        yaz(kok, f"sys/devices/virtual/block/{ad}/dm/uuid", uuid + "\n")
    for a in alt:
        os.symlink(f"../../{a}", os.path.join(d, "slaves", a))
    for klasor, bag in (("sys/dev/block", majmin), ("sys/class/block", ad)):
        os.makedirs(os.path.join(kok, klasor), exist_ok=True)
        os.symlink(f"../../devices/virtual/block/{ad}", os.path.join(kok, klasor, bag))


def _mountinfo(kok, satirlar):
    yaz(kok, "proc/self/mountinfo", "".join(satirlar))


def test_disk_crypt_zinciri():
    kok = yeni_kok(dm=None)
    _sys_blok(kok, "dm-0", "253:0", "CRYPT-LUKS2-0123456789abcdef-luks-root")
    _sys_blok(kok, "dm-1", "253:1", "LVM-abcdef", alt=("dm-0",))
    _sys_blok(kok, "nvme0n1p2", "259:2")
    _mountinfo(kok, ["22 1 259:2 / / rw,noatime shared:1 - ext4 /dev/nvme0n1p2 rw\n",
                     "40 22 253:1 / /home rw,relatime shared:2 - ext4 /dev/mapper/vg-home rw\n"])
    kontrol("LVM ← LUKS zinciri (slaves) → True", OG.disk_sifreli("/home/u", kok=kok) is True)
    kontrol("şifresiz kök bölüm → False", OG.disk_sifreli("/var/x", kok=kok) is False)
    kontrol("bağlama noktası bileşen bazlı: /homeless kök bölümdedir", OG.disk_sifreli("/homeless", kok=kok) is False)
    # doğrudan CRYPT aygıtı
    _mountinfo(kok, ["22 1 253:0 / / rw - ext4 /dev/mapper/luks-root rw\n"])
    kontrol("doğrudan dm-crypt → True", OG.disk_sifreli("/home/u", kok=kok) is True)
    # btrfs: 0:N → kaynak alanındaki /dev yolu (bağ) üzerinden
    os.makedirs(os.path.join(kok, "dev/mapper"))
    yaz(kok, "dev/dm-1", "")
    os.symlink("../dm-1", os.path.join(kok, "dev/mapper/luks-home"))
    _mountinfo(kok, ["22 1 259:2 / / rw - ext4 /dev/nvme0n1p2 rw\n",
                     "41 22 0:44 /@home /home rw - btrfs /dev/mapper/luks-home rw,subvol=/@home\n"])
    kontrol("btrfs alt birimi (0:N) → /dev yolu çözülür → True", OG.disk_sifreli("/home/u", kok=kok) is True)
    _mountinfo(kok, ["41 1 0:44 / / rw - overlay overlay rw\n"])
    kontrol("çözülemeyen 0:N (overlay) → None", OG.disk_sifreli("/home/u", kok=kok) is None)
    _mountinfo(kok, ["41 1 0:44 / / rw - btrfs /dev/yok rw\n"])
    kontrol("var olmayan /dev yolu → None", OG.disk_sifreli("/home/u", kok=kok) is None)
    # bağlama noktasında boşluk (\040) çözülür
    _mountinfo(kok, ["22 1 259:2 / / rw - ext4 /dev/nvme0n1p2 rw\n",
                     "40 22 253:0 / /mnt/benim\\040disk rw - ext4 /dev/mapper/luks-root rw\n"])
    kontrol("\\040 kaçışlı bağlama noktası", OG.disk_sifreli("/mnt/benim disk/a", kok=kok) is True)
    # döngülü slaves zinciri sonsuza gitmez
    kok2 = yeni_kok(dm=None)
    _sys_blok(kok2, "dm-5", "253:5", "LVM-x", alt=("dm-6",))
    _sys_blok(kok2, "dm-6", "253:6", "LVM-y", alt=("dm-5",))
    _mountinfo(kok2, ["22 1 253:5 / / rw - ext4 /dev/dm-5 rw\n"])
    kontrol("döngülü slaves → False (sonlanır)", OG.disk_sifreli("/", kok=kok2) is False)
    kontrol("mountinfo yok → None", OG.disk_sifreli("/", kok=yeni_kok(dm=None)) is None)
    kontrol("sys bağı yok → None", OG.disk_sifreli("/", kok=_mountinfo_kok("22 1 8:1 / / rw - ext4 /dev/sda1 rw\n"))
            is None)



def test_mountinfo_buyuk():
    """A3 D8: mountinfo 64 KiB'ı geçse de okunur (1 MiB'a kadar); 1 MiB'ı geçerse okunan tam satırlarla karar verilir
    (None değil)."""
    kok = yeni_kok(dm=None)
    _sys_blok(kok, "dm-0", "253:0", "CRYPT-LUKS2-0123456789abcdef-luks-root")
    _sys_blok(kok, "nvme0n1p2", "259:2")
    dolgu = "".join(f"{100 + i} 22 0:{100 + i} / /run/kap/{i:06d} rw - tmpfs tmpfs rw\n" for i in range(3000))
    kok_satir = "22 1 259:2 / / rw - ext4 /dev/nvme0n1p2 rw\n"
    ev_satir = "40 22 253:0 / /home rw - ext4 /dev/mapper/luks-root rw\n"
    _mountinfo(kok, [kok_satir, dolgu, ev_satir])
    boy = os.path.getsize(os.path.join(kok, "proc/self/mountinfo"))
    kontrol(f"mountinfo {boy // 1024} KiB (>64 KiB) → /home şifreli True", boy > 64 * 1024 and
            OG.disk_sifreli("/home/u", kok=kok) is True)
    kontrol("…kök bölüm False", OG.disk_sifreli("/var/x", kok=kok) is False)
    # >1 MiB: sondaki /home satırı okunmaz; kök satırı okunur → /home kök bölümde sayılır (False), None DEĞİL
    dolgu = "".join(f"{100 + i} 22 0:{100 + i} / /run/kap/{i:06d} rw - tmpfs tmpfs rw\n" for i in range(20000))
    _mountinfo(kok, [kok_satir, dolgu, ev_satir])
    boy = os.path.getsize(os.path.join(kok, "proc/self/mountinfo"))
    kontrol(f"mountinfo {boy // 1024} KiB (>1 MiB) → okunan kısımla karar (False), None değil",
            boy > 1024 * 1024 and OG.disk_sifreli("/home/u", kok=kok) is False)
    # yarım kalan son satır kullanılmaz: sınır tam bir satırın ortasına düşse de bozuk alan okunmaz
    metin = OG._oku(os.path.join(kok, "proc/self/mountinfo"), OG._AZAMI_MOUNTINFO, kesik=True)
    kontrol("…sınırda yarım satır kullanılmaz (≤1 MiB, tam satırla biter)", metin is not None and
            len(metin.encode()) <= 1024 * 1024 and metin.endswith("\n") and
            all(len(x.split()) == 10 for x in metin.splitlines()), None if metin is None else metin[-120:])


def _mountinfo_kok(satir):
    kok = yeni_kok(dm=None)
    _mountinfo(kok, [satir])
    return kok


# ---------------------------------------------------------------- kart kararı

class sahte_cuzdan:
    """cuzdan_ac'ın kart_durumu'nun çağırdığı işlevlerini süreç içinde değiştirir (busctl / kasa / ksecretd yok)."""

    def __init__(self, var=True, kurulu=False, son=None, servis=True, durum_hatasi=False, bilgi_hatasi=False,
                 kilitli=None):
        self.d = dict(var=var, kurulu=kurulu, son=son, servis=servis, durum_hatasi=durum_hatasi,
                      bilgi_hatasi=bilgi_hatasi, kilitli=kilitli)
        self.eski = {}

    def __enter__(self):
        d = self.d

        def durum():
            if d["durum_hatasi"]:
                raise RuntimeError("arka uç")
            if d["kurulu"] is None:  # cuzdan_ac.durum(): kasa okunamadı (DepoHatasi) → kurulu False + neden
                return {"kurulu": False, "acik": None, "neden": "kasa okunamadı"}
            return {"kurulu": d["kurulu"], "acik": None, "neden": None}

        def cuzdan_durumu():
            if d["bilgi_hatasi"]:
                raise RuntimeError("arka uç")
            return {"var": d["var"], "kilitli": d["kilitli"], "giris_parolasi_olasi": True}

        def son_sonuc():
            return None if d["son"] is None else {"zaman": "2026-11-28T08:00:00+03:00", "sonuc": d["son"]}

        for ad, f in (("durum", durum), ("cuzdan_durumu", cuzdan_durumu), ("son_sonuc", son_sonuc),
                      ("servis_var", lambda: d["servis"])):
            self.eski[ad] = getattr(CA, ad)
            setattr(CA, ad, f)
        return self

    def __exit__(self, *a):
        for ad, f in self.eski.items():
            setattr(CA, ad, f)


def _oto_kok():
    kok = yeni_kok()
    yaz(kok, "etc/plasmalogin.conf.d/oto.conf", oto(BEN))
    return kok


def _isaret_sil():
    try:
        os.unlink(os.path.join(yollar.state_dir(), "cuzdan-karti-kapali"))
    except FileNotFoundError:
        pass


def test_kart_karar_tablosu():
    oto_kok, parolali_kok = _oto_kok(), yeni_kok()
    _isaret_sil()
    # (ad, kok, sahte_cuzdan argümanları, kapalı işareti, beklenen goster, varyant, neden)
    dallar = [
        ("giriş parolalı → gizle", parolali_kok, {}, False, False, None, "giris_parolali"),
        ("cüzdan yok → gizle", oto_kok, {"var": False}, False, False, None, "cuzdan_yok"),
        ("cüzdan bilinmiyor (hata) → gizle", oto_kok, {"bilgi_hatasi": True}, False, False, None, "cuzdan_yok"),
        ("kapatıldı işareti → gizle", oto_kok, {}, True, False, None, "kapatildi"),
        ("kurulu + son acildi → gizle", oto_kok, {"kurulu": True, "son": "acildi"}, False, False, None, "kurulu"),
        ("kurulu + son yok → gizle", oto_kok, {"kurulu": True}, False, False, None, "kurulu"),
        ("kurulu + anahtar_acmadi → göster yeniden", oto_kok, {"kurulu": True, "son": "anahtar_acmadi"}, False,
         True, "yeniden", "anahtar_acmadi"),
        ("kurulu bilinmiyor (kasa hatası) → gizle", oto_kok, {"kurulu": None}, False, False, None,
         "durum_bilinmiyor"),
        ("durum() istisnası → gizle", oto_kok, {"durum_hatasi": True}, False, False, None, "durum_bilinmiyor"),
        ("oturum veri yolu yok → gizle", oto_kok, {"servis": None}, False, False, None, "veri_yolu_yok"),
        ("kurulu değil → göster ilk", oto_kok, {}, False, True, "ilk", "kurulu_degil"),
        ("kurulu değil + eski anahtar_acmadi kaydı → ilk", oto_kok, {"son": "anahtar_acmadi"}, False, True, "ilk",
         "kurulu_degil"),
    ]
    anahtarlar = {"goster", "varyant", "neden", "oto_giris", "cuzdan_var", "kurulu", "son_sonuc", "disk_sifreli",
                  "tpm", "depo", "cuzdan_kilitli"}
    for ad, kok, sc, kapali, goster, varyant, neden in dallar:
        if kapali:
            OG.kart_kapat()
        with sahte_cuzdan(**sc):
            d = OG.kart_durumu(kok=kok)
        _isaret_sil()
        kontrol(f"karar: {ad}", set(d) == anahtarlar and d["goster"] is goster and d["varyant"] == varyant and
                d["neden"] == neden, d)
    with sahte_cuzdan(kurulu=True, son="anahtar_acmadi"):
        d = OG.kart_durumu(kok=oto_kok)
    kontrol("gösterilen kartta alanlar dolu (oto_giris, cuzdan_var, kurulu, son_sonuc; tpm bool; depo None/kasa/cuzdan)",
            d["oto_giris"] is True and d["cuzdan_var"] is True and d["kurulu"] is True and
            d["son_sonuc"] == "anahtar_acmadi" and isinstance(d["tpm"], bool) and d["depo"] in (None, "kasa", "cuzdan"),
            d)
    # DESKHAND_ANAHTARLIK=kapali (_yalitim): depo okunamaz → None, tpm False (gerçek TPM'e dokunulmaz)
    kontrol("anahtarlık kapalı → depo None, tpm False", d["depo"] is None and d["tpm"] is False, d)
    for kilit in (True, False, None):
        with sahte_cuzdan(kilitli=kilit):
            d = OG.kart_durumu(kok=oto_kok)
        kontrol(f"cuzdan_kilitli cuzdan_durumu()'ndan gelir ({kilit})", d["goster"] and d["cuzdan_kilitli"] is kilit, d)
    with sahte_cuzdan(kilitli="evet"):
        d = OG.kart_durumu(kok=oto_kok)
    kontrol("cuzdan_kilitli bool değilse None", d["cuzdan_kilitli"] is None, d)


class _Yasak:
    """Dokunulursa kaydeden + patlayan nesne (secretstorage / jeepney / cüzdan deposu yerine)."""

    def __init__(self, ad, kayit):
        object.__setattr__(self, "_ad", ad)
        object.__setattr__(self, "_kayit", kayit)

    def __getattr__(self, ad):
        if ad.startswith("__"):  # sys.modules taraması (__spec__, __file__ …) çağrı değildir
            raise AttributeError(ad)
        self._kayit.append(f"{self._ad}.{ad}")
        raise AssertionError(f"yasak çağrı: {self._ad}.{ad}")

    def __call__(self, *a, **k):
        self._kayit.append(f"{self._ad}()")
        raise AssertionError(f"yasak çağrı: {self._ad}()")


def test_depo_cuzdan_secret_service_baslatmaz():
    """A3 B1: depo "cuzdan" iken kart_durumu Secret Service'i başlatabilecek hiçbir çağrı yapmaz (secretstorage,
    jeepney, CuzdanDepo, secili_depo().durum()); yalnız seçim (secili_tur) ve TPM varlığı okunur."""
    from deskhand import anahtar_deposu as AD
    _isaret_sil()
    kayit: list = []
    eski_mod = {m: sys.modules.get(m) for m in ("secretstorage", "jeepney")}
    eski_ad = {a: getattr(AD, a) for a in ("secili_tur", "tpm_var", "secili_depo", "ornek")}
    eski_durum = AD.CuzdanDepo.durum
    eski_env = os.environ.pop("DESKHAND_ANAHTARLIK", None)
    try:
        for m in eski_mod:
            sys.modules[m] = _Yasak(m, kayit)
        AD.secili_tur = lambda: "cuzdan"
        AD.tpm_var = lambda: True
        AD.secili_depo = _Yasak("secili_depo", kayit)
        AD.ornek = _Yasak("ornek", kayit)
        AD.CuzdanDepo.durum = _Yasak("CuzdanDepo.durum", kayit)
        with sahte_cuzdan(kilitli=True):
            d = OG.kart_durumu(kok=_oto_kok())
    finally:
        for m, v in eski_mod.items():
            if v is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = v
        for a, v in eski_ad.items():
            setattr(AD, a, v)
        AD.CuzdanDepo.durum = eski_durum
        if eski_env is not None:
            os.environ["DESKHAND_ANAHTARLIK"] = eski_env
    kontrol("depo cuzdan: kart gösterilir, depo/tpm/kilitli dolu", d["goster"] is True and d["depo"] == "cuzdan" and
            d["tpm"] is True and d["cuzdan_kilitli"] is True, d)
    kontrol("depo cuzdan: secretstorage / jeepney / CuzdanDepo / secili_depo çağrısı YOK", not kayit, kayit)
    # seçim doğrulanamazsa (SecimHatasi) depo None, kart yine kapalı-başarısız değil (yalnız gösterge)
    eski_ad = {a: getattr(AD, a) for a in ("secili_tur", "tpm_var")}
    eski_env = os.environ.pop("DESKHAND_ANAHTARLIK", None)
    try:
        def bozuk():
            raise AD.SecimHatasi("bozuk")
        AD.secili_tur, AD.tpm_var = bozuk, lambda: False
        with sahte_cuzdan():
            d = OG.kart_durumu(kok=_oto_kok())
    finally:
        for a, v in eski_ad.items():
            setattr(AD, a, v)
        if eski_env is not None:
            os.environ["DESKHAND_ANAHTARLIK"] = eski_env
    kontrol("seçim doğrulanamadı → depo None", d["goster"] is True and d["depo"] is None and d["tpm"] is False, d)


def test_kapat_isareti_kalici():
    _isaret_sil()
    yol = os.path.join(yollar.state_dir(), "cuzdan-karti-kapali")
    kontrol("başta işaret yok", OG.kart_kapali() is False)
    OG.kart_kapat()
    kontrol("kart_kapat → kart_kapali True", OG.kart_kapali() is True)
    kontrol("işaret 0600 düzenli dosya", stat.S_ISREG(os.lstat(yol).st_mode) and
            stat.S_IMODE(os.lstat(yol).st_mode) == 0o600, oct(os.lstat(yol).st_mode))
    OG.kart_kapat()
    kontrol("ikinci kart_kapat hata vermez", OG.kart_kapali() is True)
    kalan = [a for a in os.listdir(yollar.state_dir()) if a.startswith(".") and "cuzdan-karti" in a]
    kontrol("geçici dosya kalmadı", not kalan, kalan)
    # ayrı süreç (yeni panel çalışması) da görür
    import subprocess
    r = subprocess.run([sys.executable, "-c", "from deskhand import oto_giris as o; import sys; "
                        "sys.exit(0 if o.kart_kapali() else 1)"], cwd=_yalitim.KOK, capture_output=True, timeout=30)
    kontrol("işaret kalıcı: yeni süreç kart_kapali True", r.returncode == 0, r.stderr[-300:])
    # sembolik bağ işaret sayılmaz; kart_kapat bağın hedefine yazmaz
    os.unlink(yol)
    hedef = os.path.join(_yalitim.GECICI, "bag-hedefi")
    os.symlink(hedef, yol)
    kontrol("sembolik bağ → kart_kapali False", OG.kart_kapali() is False)
    OG.kart_kapat()
    kontrol("kart_kapat bağı izlemez (hedef yazılmadı, yerine düzenli dosya)", not os.path.exists(hedef) and
            stat.S_ISREG(os.lstat(yol).st_mode))
    _isaret_sil()
    # state_dir yoksa oluşturulur
    eski = os.environ["DESKHAND_STATE_DIR"]
    os.environ["DESKHAND_STATE_DIR"] = os.path.join(_yalitim.GECICI, "yeni-state", "deskhand")
    try:
        OG.kart_kapat()
        kontrol("state_dir yoksa oluşturulur", OG.kart_kapali() is True)
    finally:
        shutil.rmtree(os.path.join(_yalitim.GECICI, "yeni-state"), True)
        os.environ["DESKHAND_STATE_DIR"] = eski


for _t in (test_ana_dosya_confd_ezer, test_bos_user_siler, test_baska_kullanici_kart_yok,
           test_sddm_etkin_plasmalogin_yok_sayilir, test_okunamaz_dosya_atlanir, test_ana_dosya_okunamaz_bilinmiyor,
           test_bozuk_satir_atlanir_dosya_okunur, test_disk_crypt_zinciri, test_mountinfo_buyuk, test_kart_karar_tablosu, test_depo_cuzdan_secret_service_baslatmaz,
           test_kapat_isareti_kalici):
    print(f"--- {_t.__name__}", flush=True)
    try:
        _t()
    except Exception as e:  # noqa: BLE001 - bir testin istisnası KALDI sayılır, kalanlar koşar
        import traceback
        traceback.print_exc()
        kontrol(f"{_t.__name__}: istisna yok", False, f"{type(e).__name__}: {e}")

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
