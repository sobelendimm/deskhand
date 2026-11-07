# Deskhand — Mimari ve modüller arası sözleşme

> **English summary.** This document is the internal contract of Deskhand: the package layout, the `ArkaUc`
> (backend) interface shared by the real-desktop (KDE) and virtual-desktop (Xvfb) backends, the input language,
> target selection, the safety rules, the exit codes, the working rules for contributors, and the human-approval
> protocol. Source code refers to sections by number (§2, §4, §5, §6, §8), so the numbering is stable. The text
> is in Turkish, like the project's code comments.

Arayüzü değiştiren bir ihtiyaç doğarsa kodu tek taraflı değiştirmeyin: önce §7'ye bir tasarım kararı olarak
yazın ve proje bakımcısıyla netleştirin.

## 1. Paket düzeni

```
deskhand/
  __init__.py      __version__
  __main__.py      python -m deskhand → cli.main()
  yollar.py        TÜM dosya yolları burada. Ortam değişkeniyle değiştirilebilir (testler için):
                   DESKHAND_CONFIG_DIR (vars. ~/.config/deskhand), DESKHAND_STATE_DIR (~/.local/state/deskhand),
                   DESKHAND_CACHE_DIR (~/.cache/deskhand), DESKHAND_DATA_DIR (~/.local/share/deskhand),
                   DESKHAND_RUNTIME_DIR ($XDG_RUNTIME_DIR/deskhand).
                   GEÇİŞ: selefi `ekran` aracının ~/.config/ekran, ~/.local/share/ekran/simgeler ve
                   ~/.local/state/ekran dizinleri varsa ve yenisi yoksa ilk açılışta KOPYALANIR (taşınmaz;
                   eski araç çalışmaya devam eder).
  hata.py          Dur(kod, mesaj) + çıkış kodları (§5)
  gunluk.py        günlük + temizlik
  guvenlik.py      yasak pencereler, hassas düğme, ödeme sayfası, başlık/sınıf kilidi, denetle(), DUR anahtarı
  insan.py         Wayland etkinlik izleyici (ekran-etkinlik C yardımcısı) + insan_bekle
  ocr.py           oku, satirla, ara, derin_oku, önbellek, ön işleme
  gorsel.py        simge (NCC), renk alanları, ızgara
  eylem.py         tikla/yaz/tus/kaydir/bas/surukle/dizi: arka uçtan BAĞIMSIZ üst katman
  akis.py, erisim.py (AT-SPI), uygulama.py (ac)
  cli.py           argparse; komut adları İngilizce + Türkçe takma adlar
  arka_uc/__init__.py   ArkaUc arayüzü + sec(hedef)
  arka_uc/kde.py        kdotool + dotool + spectacle + kscreen-doctor
  arka_uc/sanal.py      Xvfb + python-xlib
  masaustu.py      sanal masaüstü yaşam döngüsü
  oturum/          oturum köprüsü (bkz. docs/SESSIONS.md)
  mesgul.py        kullanıcı meşgul mü (oyun / film) koruması
  onay.py          insan onayı protokolü (§8)
  gui/             panel, tepsi, onay diyaloğu
  mcp_sunucu.py    MCP yüzeyi
bin/ekran          uyumluluk: `python3 -m deskhand "$@"` (Türkçe komutlar aynen)
tests/             ekransız testler: test_ocr.py, test_mantik.py ...; ekranlı: tests/ekranli/ (yalnız elle)
```

## 2. ArkaUc arayüzü (deskhand/arka_uc/__init__.py)

Koordinatlar: `geometri()` ve `goruntu()` EKRAN pikseli (arka ucun kendi ekranı). Üst katman pencere
koordinatını `geometri()` ile ekrana çevirir.

Pencere kimliği: arka uca özgü dize. kde: `{uuid}`; sanal: `arka:0x1a00007` (her zaman `arka:` önekli, böylece
bir kimlik yanlış arka uca gidemez). Özel kimlik `EKRAN` = masaüstü kipi (tüm ekran).

| Yöntem | Döner | Not |
|---|---|---|
| `ad` | "kde" \| "sanal" | |
| `pencere_coz(arg)` | kimlik | ad deseni tek pencereye uymalı (yoksa Dur 8, çoksa Dur 5) |
| `pencereler(desen=None)` | [(kimlik, başlık, (x,y,g,y))] | `bul` komutu |
| `geometri(k)` | (x, y, g, y) | yoksa Dur 8 |
| `baslik(k)`, `sinif(k)` | str | |
| `aktif()` | kimlik \| "" | boş = doğrulanamadı → çağıran DURUR |
| `one_getir(k)` | None | aktif olmazsa Dur 3 |
| `kapat(k)` | None | |
| `fare()` | (x, y, altındaki_kimlik) | |
| `baslik_ve_fare(k)` | (başlık, fare()) | gözcü için tek çağrı |
| `ekran_alani()` | (x0, y0, x1, y1) | |
| `goruntu()` | PIL.Image (RGB, tüm ekran) | pencere kırpımı üst katmanda |
| `girdi(etiket, gizli, etk, denetle)` | Girdi nesnesi | `denetle(k, desen)` = üst katmanın güvenlik denetimi; her satırdan önce `hata.dur_denetle()` + `denetle()` |
| `insan_var_mi()` | bool | kde: Wayland etkinliği; sanal: "Devral" açıksa True |
| `baslat(argv, env=None, cikti=None)` | Popen | uygulamayı BU arka ucun oturumunda başlatır |
| `atspi_adresi()` | str \| None | erişilebilirlik veri yolu |

İsteğe bağlı (varsayılanlı) yöntemler: `kimlikler()`, `klavye_duzeni()`, `yazilabilir_mi(c)`, `gecerli_tuslar()`,
`pid(k)`, `etkinlestir(k)`, `etkinlik()`.

`baslat(argv, env, cikti)`: `env`, her iki arka uçta da `os.environ`'a EKLENECEK/değişecek değişkenlerdir (tam ortam
değil). Sanalda masaüstü değerleri (DISPLAY, özel D-Bus, ses...) her zaman üstün gelir.

**Girdi nesnesi:** `gonder(k, desen, *satirlar)` (her çağrıdan önce `guvenlik.denetle`), `zorla(satir)` (bırakma;
denetimsiz, kesintide bile), `ham(satir)`, `izle(k, desen)` / `izle_bitir()` (gözcü), `etk_denetle()`,
`insan_kontrol()`, `kapat()`.

**Girdi dili = dotool satır dili** (her iki arka uç da aynı satırları anlar):
`mouseto FX FY` (0..1 kesir, tüm ekran), `buttondown|buttonup|click left|right|middle`, `key K`,
`keydown K`, `keyup K` (K: `ctrl+s`, `enter`, `leftshift`…), `type METİN`, `wheel N` (artı=yukarı),
`hwheel N` (artı=sağ), `typedelay MS`, `typehold MS`. Sanal arka uç bunları XTEST'e çevirir (Türkçe karakterler
dahil: xkb düzeni `tr` ya da keysym eşleme).

**Atomiklik.** DUR denetimi satır başına değil `gonder()` çağrısı başına yapılır: bir çağrıdaki satırlar
ATOMİKTİR (çift tıklamanın iki click'i bölünmez). Harf harf yazıda (`ham`) her harften önce denetlenir.
Gözcü kesintisi (`kesildi` bayrağı) bir sonraki `izle()`ye dek kalır (iki arka uçta aynı).

**Devral.** `RUNTIME_DIR/devral`: bir Girdi nesnesinin İLK `gonder()`'inde Devral açıksa en çok 8 sn beklenir,
sonra 12 ile durulur; sonraki çağrılar beklemeden 12. Bildirimler `STATE_DIR/bildirimler.jsonl` dosyasına yazılır
(2 MB'ı aşınca son 1 MB tutulur, `gunluk.temizle`).

## 3. Hedef seçimi
`--arka` genel bayrağı / `DESKHAND_HEDEF=arka|on|oto` / kimlik `arka:` öneki → `arka_uc.sec()`.
Varsayılan `on` (kullanıcının gerçek masaüstü). `oto`, `deskhand decide` (karar) komutuna bağlanır: kullanıcı
ekranı meşgulse işi arka planda, olmazsa ön planda yapmayı önerir.

## 4. Güvenlik (iki arka uçta da AYNEN)
- Yasak pencereler (`yasak-pencereler.txt`): hiçbir girdi + başlatma yok (10). **Liste varsayılan olarak boştur**
  (yalnız yerleşik panel/onay penceresi yasağı vardır); kullanıcı kendi yasaklarını ekler.
- Hassas düğme / ödeme sayfası başlığı → `--onayli` yoksa 10. `--onayli` YALNIZ kullanıcı sohbette açıkça onayladıysa.
- Başlık (`-b`) ve sınıf (`-s`) kilidi her girdiden hemen önce (4).
- DUR anahtarı: `DESKHAND_RUNTIME_DIR/dur` varsa her girdi çağrısından önce Dur(13); basılı her şey bırakılır.
  `deskhand dur` oluşturur, `deskhand devam` siler. Arayüz/tepsi/kısayol bunu kullanır.
  `guvenlik.dur_ac(kaynak)` / `dur_kapat(kaynak)` / `dur_kaynagi()`: dur dosyasının ilk sözcüğü `kullanici` ya da
  `cli`'dir. Kullanıcının koyduğu DUR'u CLI ezemez ve kaldıramaz (Dur 13); yalnızca arayüz kaldırır.
- İnsan önceliği (12): kde arka ucunda kullanıcı klavye/fareyi kullanıyorsa; sanalda yalnız "Devral" açıkken.
- Kullanıcı meşgulken ön plan yok (15): kde arka ucu girdi, pencere öne getirme ve uygulama açmadan önce
  `mesgul.ekran_korumasi()` çağırır. Etkin pencere tam ekran / oyun biçimli ya da MPRIS'te video çalıyorsa
  Dur(15). İstisna yalnız kullanıcının açık izni (`--ekranimda`, `DESKHAND_EKRANIMDA=1` ya da bildirimdeki
  "Ekranımda yap" düğmesi → 10 dk). Sanal masaüstü etkilenmez.
- Ham `dotool`/`xdotool` çağrısı YALNIZ arka uç içinde. Testler dahil başka yerde ASLA.
- Sanal X bağlantısı yalnız `masaustu.guvenli_ekran()` ile açılır: boş ad Xlib'de `$DISPLAY`'e (kullanıcının gerçek
  XWayland'i) düşer ve XTEST girdisi gerçek masaüstüne gidebilirdi. Yalnız `:N` biçiminde ve gerçek `DISPLAY`'den
  farklı ekran kabul edilir.

## 5. Çıkış kodları
0 tamam · 1 kullanım hatası · 2 nokta pencere/ekran dışında · 3 aktif değil/başka pencere · 4 başlık/sınıf kilidi
uymadı · 5 belirsiz (birden çok eşleşme) · 6 bulunamadı · 7 zaman aşımı · 8 pencere yok/taşındı ·
9 araç eksik (dotool/tesseract/Xvfb…) · 10 yasak/hassas · 11 akış hata ekranı · 12 insan kullanıyor ·
**13 kullanıcı DUR dedi** · **14 sanal masaüstü kapalı** · **15 kullanıcı oyunda/film izliyor, ekranına müdahale yok** ·
**16 uygulama arka planda açılamaz** (kullanıcının ekranında açık ya da yalnız ön plan) ·
20 / 21 `decide` karar kodları: 0 = kullanıcının ekranı, 20 = arka plan, 21 = sonra.

Çağıran otomasyon 10, 12, 13, 15 ve 16'da durmalı ve kullanıcıya haber vermelidir. MCP yüzeyinde aynı kodlar
`[kod] ad: ayrıntı` hatası olarak görünür. Bu tablo README'deki "Exit codes" tablosuyla tutarlı tutulur.

## 6. Çalışma kuralları
- Testler `DESKHAND_*_DIR`'leri geçici klasöre yönlendirir; gerçek `~/.config`, `~/.local/state` vb. yazılmaz.
  Uzun koşudan önce/sonra `~/.config/deskhand` (ve varsa eski `~/.config/ekran`) için sha1 karşılaştırın.
  Yeni bir yazma yolu eklerken testlerin onu gerçekten taklit ettiğini doğrulayın.
- Gerçek ekran testleri: GERÇEK ekrana girdi gönderen hiçbir test/komut (kde arka ucu ile tikla/yaz/tus,
  `tests/ekranli/`) kullanıcı bilgisayarı kullanırken (film, oyun…) çalıştırılmaz; yalnız elle, makine boştayken
  koşulur. Sanal masaüstü (Xvfb) testleri serbesttir.
- `pkill -f DESEN` kullanmayın (kendi kabuğunuzu öldürebilir); süreçleri PID ile durdurun.
- Kişisel veri: kodda, yorumlarda, testlerde ve belgelerde kullanıcı adı, gerçek ev dizini, hesap adı, tarihli kişisel
  olay notu olmaz. Tasarım nedeni yorumda kalabilir; tarih ve kişi olmadan.
- Ağır işleri (uzun taramalar, büyük testler) belleği sınırlı bir kafeste (ör. `systemd-run --user -p MemoryMax=…`)
  ve tek seferde çalıştırın.
- Git: değişiklikleri commit etmeden önce testleri çalıştırın; birden çok kişi/araç paralel çalışıyorsa her biri
  yalnız kendi dosyalarını commit eder.

## 7. Tasarım kararları
Arayüz sözleşmesine zamanla giren kararların özeti (ayrıntılar ilgili bölümlerde):
- **ArkaUc genişlemesi.** İsteğe bağlı yöntemler varsayılanlıdır (`kimlikler`, `klavye_duzeni`, `yazilabilir_mi`,
  `gecerli_tuslar`, `pid`, `etkinlestir`, `etkinlik`); `baslat` bir `cikti` parametresi alır ve `env` her iki arka
  uçta da mevcut ortama EKLENİR (§2).
- **DUR atomikliği.** DUR, satır başına değil `gonder()` çağrısı başına denetlenir; böylece çift tıklama gibi
  bölünmemesi gereken diziler yarım kalmaz (§2).
- **DUR sahipliği.** Kullanıcının koyduğu DUR'u CLI kaldıramaz; dur dosyası kaynağı (`kullanici`/`cli`) taşır (§4).
- **Oyun/film sırasında ön plan yok.** Kullanıcı oyun oynarken ya da video izlerken Deskhand gerçek ekrana
  müdahale etmez (kod 15); yalnız açık kullanıcı izniyle istisna vardır. Sanal masaüstü bundan etkilenmez (§4).
- **Yasak listesi varsayılan boş.** Deskhand bir "tıklama aracıdır"; kullanıcı neyi yasaklayacağına kendisi karar
  verir. Yalnız Deskhand'in kendi panel/onay penceresi daima yasaktır (§4).
- **Sanal ekran güvenliği.** Sanal X bağlantısı yalnız doğrulanmış `:N` ekranına açılır; boş `DISPLAY` asla
  gerçek masaüstüne düşmez (§4).
- **Devral ve bildirimler.** Sanal masaüstünde kullanıcı "Devral" ile denetimi alabilir; bu durum ve bildirimler
  durum dizininde tutulur (§2).
- **Oturum köprüsü.** Arka plandaki uygulamaların kullanıcının hesap oturumlarını kullanabilmesi, uygulama başına
  bir politikayla (kopya / paylas / bekle / on / kapali) yönetilir; uygulama kullanıcı oturumunda açık ve
  arka planda açılamıyorsa kod 16 döner (bkz. docs/SESSIONS.md).

## 8. Onay protokolü (arayüz + MCP + CLI ortak)
Hassas eylem (hassas düğme, ödeme sayfası, yasak dışı ama riskli `ac`, oturum aktarımı) için onay YALNIZ insandan:
- `deskhand/onay.py`: `iste(eylem, hedef, ayrinti, masaustu, sure=120) -> bool`.
  İstek: `RUNTIME_DIR/onay/istek-<uuid>.json` {id, eylem, hedef, ayrinti, masaustu, zaman, son_zaman, pid}.
  Panel (QFileSystemWatcher) diyalog açar: **Bir kez izin ver / Reddet** (+ hedefin küçük ekran görüntüsü).
  Yanıt: `yanit-<uuid>.json` {id, karar: "izin"|"red", kaynak: "arayuz", zaman}. Yalnız panel yazar.
  İsteyen yanıtı bekler; süre dolarsa ya da panel kapalıysa → red (mesaj: "Deskhand paneli kapalı, onay alınamadı").
  Tek kullanımlık; istek/yanıt dosyaları kullanılınca silinir; dizin 0700.
- CLI `--onayli` kalır (kullanıcı sohbette açıkça onayladıysa), MCP yüzeyinde YOK.
- Onay diyaloğu penceresi yasak listesine (sınıf/başlık) otomatik eklenir: hiçbir otomasyon girdisi ona gitmez.
