"""Etkinlik/durum metinlerinin insan diliyle üretimi (UX-B; UX denetimi Y3, D1, D3): her eylem türü için TR + EN tek
cümle, ham satır ayrıntıda korunur, gizli yazı ve yasak pencere başlığı ne insan metninde ne ayrıntıda görünür,
pencere kimliği ({d7bf}) gösterilmez, çoğul ekleri doğru. Qt'siz; örnek günlük satırları burada üretilir.

Çalıştır:  python3 tests/test_insan_metni.py   (ya da tools/test_kos.py test_insan_metni)"""
import sys

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import guvenlik, i18n  # noqa: E402
from deskhand.gui import gunluk_okur as G  # noqa: E402
from deskhand.gui import insan_metni as H  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def dil(kod):
    i18n.sifirla(kod, i18n.katalog_oku(kod) if kod != "tr" else None)


GIZLI_TR = "(gizli yazı: gizlendi)"
# (ad, günlük satırı, TR beklenen, EN beklenen) — beklenen tam cümle
ORNEKLER = [
    ("tık (pencere)", "10:01:02 tikla (856,657) sol | [GitHub | Ayarlar — Firefox] | mouseto 0.33 0.45",
     "Firefox penceresinde tıklandı", "Clicked in Firefox"),
    ("öğeye tık", "10:01:03 ogeye-tikla 'Kaydet' sol | [Belge — KWrite] | click left",
     "KWrite penceresinde 'Kaydet' öğesine tıklandı", "Clicked 'Kaydet' in KWrite"),
    ("sağ tık", "10:01:03 tikla (5,5) sag | [Dosyalar] | click right",
     "Dosyalar penceresinde sağ tıklandı", "Right-clicked in Dosyalar"),
    ("yazı", "10:01:05 yaz 12 karakter | arka :90 [Belge — KWrite] | type 'merhaba dünya'",
     "KWrite penceresinde 12 karakter yazıldı", "Typed 12 characters in KWrite"),
    ("yazı tekil", "10:01:05 yaz 1 karakter | [Not] | type 'a'",
     "Not penceresinde 1 karakter yazıldı", "Typed 1 character in Not"),
    ("tuş", "10:01:06 tus Return | [Not] | key Return",
     "Not penceresinde Enter tuşuna basıldı", "Pressed Enter in Not"),
    ("kısayol", "10:01:06 tus ctrl+s | [Not] | key ctrl+s",
     "Not penceresinde Ctrl+S kısayoluna basıldı", "Pressed the Ctrl+S shortcut in Not"),
    ("çok tuş", "10:01:06 tus a b c | [Not] | key a ; key b ; key c",
     "Not penceresinde 3 tuşa basıldı", "Pressed 3 keys in Not"),
    ("fare taşıma", "10:01:07 fare (10,20) | [Not] | mouseto 0.1 0.2",
     "Not penceresinde fare imleci taşındı", "Moved the mouse pointer in Not"),
    ("kaydırma", "10:01:08 kaydir asagi 3 | [Not] | wheel -3",
     "Not penceresinde aşağı kaydırıldı", "Scrolled down in Not"),
    ("sürükleme", "10:01:09 surukle (1,1)→(5,5) sol | [Not] | buttondown left",
     "Not penceresinde fareyle sürüklendi", "Dragged with the mouse in Not"),
    ("basılı tut", "10:02:10 bas w 0.5 sn | [Oyun] | keydown w",
     "Oyun penceresinde W tuşu basılı tutuldu", "Held W in Oyun"),
    ("tuşu bırak", "10:02:11 bas w | bırak | keyup w", "W tuşu bırakıldı", "Released W"),
    ("pencere aç", "10:02:00 ac | kcalc | kcalc", "kcalc açıldı", "Opened kcalc"),
    ("pencere kapat", "10:02:01 kapat | [Not] | windowclose", "Not penceresi kapatıldı", "Closed the Not window"),
    ("okuma", "10:02:02 metin | [Not] | ocr", "Not penceresindeki yazı okundu", "Read the text in Not"),
    ("DUR açıldı", "10:03:00 DUR anahtarı açıldı", "DUR anahtarı açıldı", "STOP switch turned on"),
    ("Devam", "10:03:01 DUR anahtarı kaldırıldı (panel)", "DUR anahtarı kaldırıldı (panel)",
     "STOP switch cleared (panel)"),
    ("durdurma", "10:01:20 DUR 4 | yaz {d7bf} | başlık değişti: 'x' (beklenen /y/)",
     "Yazma güvenlik denetiminde durduruldu (kod 4)", "Typing was stopped by a safety check (code 4)"),
    ("onay sorusu", "10:01:09 onay izin | arka sanal [Ödeme] | tıkla 'Öde'",
     "Onay sorusu: izin verildi ('Öde')", "Approval request: allowed ('Öde')"),
    ("bilinmeyen", "10:04:00 tuhaf-bir-sey oldu", "Deskhand bir işlem kaydetti (ayrıntı sütununda)",
     "Deskhand logged an event (see the details column)"),
]

for kod in ("tr", "en"):
    dil(kod)
    for ad, satir, tr, en in ORNEKLER:
        d = G.ayristir(satir)
        s = H.insan_metni(d)
        kontrol(f"{kod}: {ad}", s == (tr if kod == "tr" else en), repr(s))
        kontrol(f"{kod}: {ad}: ham satır ayrıntıda VAR", H.ayrinti(d) == satir, H.ayrinti(d))

# ---- bilinmeyen / bozuk girdi: asla boş, asla istisna
dil("tr")
for bozuk in ({}, {"eylem": None}, {"tur": "girdi", "eylem": "tikla"}, {"tur": "dur", "eylem": "DUR"},
              {"tur": "onay", "eylem": "onay"}, {"tur": "girdi", "etiket": "tus", "eylem": "tus: "}):
    try:
        s = H.insan_metni(bozuk)
        kontrol(f"bozuk girdi boş değil: {bozuk}", isinstance(s, str) and s.strip(), repr(s))
    except Exception as e:  # noqa: BLE001
        kontrol(f"bozuk girdi istisna vermez: {bozuk}", False, repr(e))

# ---- gizlilik: gizli yazı (iki biçim) ve gizli tuş
GIZLI = ["10:05:00 yaz 9 karakter | [(gizli yazı: gizlendi)] | type ***",
         "10:05:01 yaz 9 karakter | arka :91 [Giriş — Firefox] | type ***",
         "10:05:02 tus *** | arka :91 [Giriş] | key ***",
         "10:05:03 yaz 9 karakter | [(gizli yazı: gizlendi)] | yapistir ***",
         "10:05:04 bas *** | bırak | keyup ***"]
for kod in ("tr", "en"):
    dil(kod)
    gizli_yer = guvenlik.gizli_yer()
    for satir in GIZLI:
        d = G.ayristir(satir)
        s, a, p = H.insan_metni(d), H.ayrinti(d), H.pencere_metni(d)
        kontrol(f"{kod}: gizli satır insan metni gizli kalıbını taşır: {satir[9:30]}", gizli_yer in s, s)
        kontrol(f"{kod}: gizli satır: içerik/uzunluk/*** insan metninde yok", "***" not in s and "9" not in s, s)
        kontrol(f"{kod}: gizli satır ayrıntı içerik taşımaz (ham maskeli)", "parola" not in a and "***" in a, a)
        kontrol(f"{kod}: gizli satır pencere sütunu sızdırmaz", "***" not in p, p)

# ---- yasak pencere: başlık ne insan metninde ne ayrıntıda ne pencere sütununda
dil("tr")
H._yasak_onbellek_sifirla(["KeePassXC"])
YASAK = ["10:06:00 tikla (5,5) sol | [Veritabanı — KeePassXC] | click left",
         "10:06:01 DUR 7 | tikla {d7bf} | yasak pencere: 'Veritabanı — KeePassXC'",
         "10:06:02 onay red | [Veritabanı — KeePassXC] | tıkla 'Aç'"]
for satir in YASAK:
    d = G.ayristir(satir)
    hepsi = " ".join((H.insan_metni(d), H.ayrinti(d), H.pencere_metni(d)))
    kontrol(f"yasak pencere başlığı hiçbir sütunda yok: {satir[9:40]}", "KeePassXC" not in hepsi and
            "Veritabanı" not in hepsi, hepsi)
H._yasak_onbellek_sifirla(None)

# ---- pencere kimliği, URL sorgusu/parçası, belirteç
d = G.ayristir("10:01:20 DUR 4 | yaz {d7bf} | başlık değişti: 'x' (beklenen /y/)")
kontrol("D3: DUR satırında pencere kimliği ({d7bf}) gösterilmez", H.pencere_metni(d) == "", H.pencere_metni(d))
kontrol("D3: insan metninde kimlik yok", "{d7bf}" not in H.insan_metni(d))
d = G.ayristir("10:07:00 ac | firefox | firefox https://ornek.com/giris?token=abc123#gizli")
s = H.insan_metni(d) + " " + H.pencere_metni(d) + " " + H.ayrinti(d)
kontrol("URL sorgusu/parçası (belirteç) hiçbir yerde yok", "abc123" not in s and "#gizli" not in s, s)
d = G.ayristir("10:07:01 tikla (1,1) sol | [https://ornek.com/a?sid=XYZ — Firefox] | click left")
s = H.insan_metni(d) + " " + H.pencere_metni(d)
kontrol("pencere başlığındaki URL sorgusu gösterilmez", "XYZ" not in s, s)

# ---- çoğul (D1)
dil("en")
kontrol("EN çoğul: 1 key / 3 keys", H.cogul(1, H.TUS_TEKIL, H.TUS_COGUL) == "1 key" and
        H.cogul(3, H.TUS_TEKIL, H.TUS_COGUL) == "3 keys", H.cogul(1, H.TUS_TEKIL, H.TUS_COGUL))
kontrol("EN: 1 approval waiting (approval(s) yok)", H.onay_bekliyor(1) == "1 approval waiting" and
        H.onay_bekliyor(2) == "2 approvals waiting", H.onay_bekliyor(1))
dil("tr")
kontrol("TR çoğul: 3 tuş (Türkçe sayıdan sonra tekil)", H.cogul(3, H.TUS_TEKIL, H.TUS_COGUL) == "3 tuş" and
        H.cogul(1, H.TUS_TEKIL, H.TUS_COGUL) == "1 tuş")
kontrol("TR: 2 onay bekliyor", H.onay_bekliyor(2) == "2 onay isteği bekliyor")

# ---- durum (başlık şeridi / tepsi): son eylem insan metni, ham dizgi yok
from deskhand.gui import durum as D  # noqa: E402

d = G.ayristir("10:02:11 bas w | bırak | keyup w")
du = D.durum_turet(None, d, 100.0, 100.5)
kontrol("durum: son eylem insan metni (ham 'keyup' yok)", du.son_eylem == "W tuşu bırakıldı", du.son_eylem)
dil("en")
du = D.durum_turet(None, d, 100.0, 100.5, bekleyen=1)
kontrol("durum EN: son eylem insan metni + tekil onay ipucu", du.son_eylem == "Released W" and
        "1 approval waiting" in du.ipucu() and "(s)" not in du.ipucu(), du.ipucu())
d = G.ayristir("10:05:01 yaz 9 karakter | arka :91 [Giriş — Firefox] | type ***")
du = D.durum_turet(None, d, 100.0, 100.5)
kontrol("durum: gizli yazı başlık şeridinde de gizli", guvenlik.gizli_yer() in du.son_eylem and "***" not in du.son_eylem,
        du.son_eylem)
dil("tr")
kontrol("ajan şu an (arka plan): ham komut değil insan metni",
        D.guvenli_eylem({"etiket": "ogeye-tikla 'Kaydet' sol"}) == "'Kaydet' öğesine tıklandı",
        D.guvenli_eylem({"etiket": "ogeye-tikla 'Kaydet' sol"}))

# ---- dil.gunluk_eylemi de insan metni döndürür (eski çağıranlar için)
from deskhand.gui.dil import gunluk_eylemi  # noqa: E402

d = G.ayristir("10:02:11 bas w | bırak | keyup w")
kontrol("dil.gunluk_eylemi → insan metni", gunluk_eylemi(d) == "W tuşu bırakıldı", gunluk_eylemi(d))

print(f"\n{gecen}/{toplam} insan metni testi geçti")
sys.exit(0 if gecen == toplam else 1)
