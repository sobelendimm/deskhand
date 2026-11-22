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
  guvenlik.py      yasak pencereler, hassas düğme, ödeme sayfası, riskli tuş/uçbirim komutu onayı, uygulama erişim
                   seviyeleri, başlık/sınıf kilidi, denetle(), DUR anahtarı
  insan.py         Wayland etkinlik izleyici (ekran-etkinlik C yardımcısı) + insan_bekle
  ocr.py           oku, satirla, ara, derin_oku, önbellek, ön işleme
  gorsel.py        simge (NCC), renk alanları, ızgara
  eylem.py         tikla/yaz/tus/kaydir/bas/surukle/dizi: arka uçtan BAĞIMSIZ üst katman
  akis.py, erisim.py (AT-SPI), uygulama.py (ac)
  cli.py           argparse; komut adları İngilizce + Türkçe takma adlar
  arka_uc/__init__.py   ArkaUc arayüzü + sec(hedef)
  arka_uc/kde.py        kdotool + dotool + kscreen-doctor (+ spectacle yalnız görüntü kurtarması)
  arka_uc/kde_goruntu.py  ekran görüntüsü: yardimci/deskhand-goruntu (C, sd-bus) → KWin ScreenShot2
                        (org.kde.KWin.ScreenShot2, ham piksel borudan; ~8 ms). Yetki: KWin < 6.8 çağıranın
                        /proc/<pid>/exe yolunu Exec= ilk sözcüğü aynı .desktop dosyasıyla eşleştirir ve
                        X-KDE-DBUS-Restricted-Interfaces'te arayüzü arar → install.sh
                        ~/.local/share/applications/deskhand-goruntu.desktop kurar (KWin 6.8 denetimi kaldırdı).
                        Yardımcı derlenmemiş/yetkisizse iç kurtarma: spectacle (günlüğe yazılır).
  arka_uc/sanal.py      arka plan masaüstünün Xvfb türü: Xvfb + python-xlib
  arka_uc/kwin.py       arka plan masaüstünün KWin türü: kdotool (+ KWin betikleri) + yardimci/deskhand-eis (EIS girdi)
                        + deskhand-goruntu + wl-copy/wl-paste, hepsi oturumun özel veri yolu / Wayland soketiyle
  masaustu.py      arka plan masaüstü yaşam döngüsü (TEK giriş noktası, iki tür): tür seçimi, başlat/durdur/durum,
                   uygulama başlatma; durum RUNTIME_DIR/sanal.json ("tur": "kwin" | "xvfb")
  kwin_oturum.py   KWin türünün yapı taşları: kwin_wayland --virtual + özel D-Bus + özel Wayland soketi + XWayland,
                   güvenlik kapıları (guvenlik_kapilari, baglanti_denetle), GPU seçimi, hazır olma denetimi, Eis sınıfı
  arka_ortak.py    iki türün ORTAK iç yapı taşları: bellek kafesi, öncelik, boş ses çıkışı, uygulama ortamı tabanı
                   (ortam_tabani), özel D-Bus yapılandırması, Xauthority, öncelik bekçisi başlatma
  oncelik_bekcisi.py  kafesteki her iş parçacığını nice >= 10 / gerçek zamanlı olmayan / idle G/Ç'de tutan bekçi
  ses_bekcisi.py   arka plan sesi boş çıkıştan başka çıkışa düşerse susturur ve kapatır
  pano_sahibi.py   sanal masaüstünün CLIPBOARD seçimini sunan yardımcı süreç (kafeste, ilk pano yazımında başlar)
  oturum/          oturum köprüsü (bkz. docs/SESSIONS.md)
  mesgul.py        kullanıcı meşgul mü (oyun / film) koruması
  onay.py          insan onayı protokolü (§8)
  girdi_merkezi.py panelin içinde hazır bekleyen tek dotool + RUNTIME_DIR/girdi.sock (Qt'siz; §2, §4)
  gui/             panel, tepsi, onay diyaloğu
  fark.py          eylem öncesi/sonrası ekran farkı (changed, changed_region, changed_ratio; NumPy, imleç dayanıklı)
  dongu.py         döngü kesici: aynı eylem 3. sonuçsuzda uyarı, 5'ten sonra ret (MCP, oturum başına bellek)
  mcp_sunucu.py    MCP yüzeyi
bin/ekran          uyumluluk: `python3 -m deskhand "$@"` (Türkçe komutlar aynen)
tests/             ekransız testler: test_ocr.py, test_mantik.py ...; ekranlı: tests/ekranli/ (yalnız elle)
```

## 2. ArkaUc arayüzü (deskhand/arka_uc/__init__.py)

Koordinatlar: `geometri()` ve `goruntu()` EKRAN pikseli (arka ucun kendi ekranı). Üst katman pencere
koordinatını `geometri()` ile ekrana çevirir.

Pencere kimliği: arka uca özgü dize. kde: `{uuid}`; sanal: Xvfb türünde `arka:0x1a00007`, KWin türünde
`arka:{uuid}` (her zaman `arka:` önekli, böylece bir kimlik yanlış arka uca gidemez). Özel kimlik `EKRAN` = masaüstü
kipi (tüm ekran).

**Arka plan masaüstünün iki türü.** `sanal` hedefinin arkasında iki arka uç vardır: yalıtık KWin oturumu
(`arka_uc/kwin.py`, `KwinArkaUc`) ve Xvfb + openbox (`arka_uc/sanal.py`, `SanalArkaUc`). İkisinin de `ad`ı `"sanal"`dır;
tür `tur` özniteliğindedir ("kwin" | "xvfb"). Üst katman (eylem, guvenlik, erisim, MCP, CLI) türü bilmez; komutlar, MCP
araçları, kimlik öneki ve çıkış kodları aynıdır. Geometri iki türde de İSTEMCİ alanıdır (başlık çubuğu/çerçeve hariç;
KWin türünde KWin betiğiyle `clientGeometry`); `tasi`/`boyutlandir` istemci alanının köşesini/boyutunu verir.

| Yöntem | Döner | Not |
|---|---|---|
| `ad` | "kde" \| "sanal" | `sanal` arka uçlarında ayrıca `tur`: "kwin" \| "xvfb" |
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
`pid(k)`, `etkinlestir(k)`, `etkinlik()`, `oturum_veri_yolu()` (org.a11y.Bus'ın oturum veri yolu; None = kullanıcının
oturumu), `ekran_korumasi(ne)` (kde: oyun/film → 15; girdi göndermeyen ama uygulamayı etkileyen yollar çağırır).

Pencere yönetimi (isteğe bağlı; varsayılan = desteklenmiyor → Dur 9): `tasi(k, x, y)`, `boyutlandir(k, g, y)`,
`kucult(k)`, `buyut(k)` (çalışma alanını kapla), `geri_yukle(k)` (küçültülmüş/büyütülmüşten normale); dönüş None.
KWin türü: KWin betikleri (`kdotool kwinscript`, özel veri yolu) — istemci alanı ölçüsünde taşı/boyutlandır, durum
(`pencere_durumu`: hidden/maximized) doğrulanır (Xvfb türü gibi en çok ~1 sn, olmazsa Dur 9).
Koordinatlar ekran pikseli. Denetimler üst katmanda (`eylem.pencere_yonet`: DUR 13, yasak 10, -s/-b kilidi 4, hedef
konum/boyut ekran alanı dışında 2); kde arka ucu ayrıca `one_getir` ile aynı ekran korumasını (15/12) uygular.
kde: kdotool `windowmove`/`windowsize`/`windowminimize`/`windowstate`; sanal: EWMH (`_NET_MOVERESIZE_WINDOW`,
`_NET_WM_STATE`, `WM_CHANGE_STATE`).

**Pano (isteğe bağlı; varsayılan Dur 9 "desteklenmiyor"):** `pano_oku() -> str | None` (metin; boş/metin dışı = None),
`pano_yaz(metin, hassas=True)` ("" = temizle; `hassas` pano yöneticisi geçmişine yazılmasın; DUR ve ön plan koruması
BURADA), `pano_yedekle()` → opak anlık görüntü (yapıştırarak yazmadan önce; okunamıyorsa Dur 9 → üst katman harf harf
yazar) ve `pano_geri_yukle(yedek) -> uyarı | None` (DENETİMSİZ: DUR/kesintide de eski pano geri gelmeli). kde:
`wl-paste`/`wl-copy` (`--sensitive`; metin dışı pano birincil MIME türüyle geri yüklenir). sanal: X11 seçimi sahibinde
yaşar → masaüstünün kafesinde ilk kullanımda başlatılan `deskhand/pano_sahibi.py` yardımcısı (python-xlib, ICCCM +
INCR; çalışma klasöründe 0600 `pano.sock`); okuma süreç içinde. KWin türü: `wl-copy`/`wl-paste` oturumun MUTLAK
Wayland soketiyle ve asgari ortamla (kullanıcının değişkenleri yok); `wl-copy`'nin sunucu çocuğu masaüstünün kafesinde
yaşar; okuma en çok 32 MB, yazma en çok 64 MB. Üç arka uç birbirinin panosuna dokunmaz.

`baslat(argv, env, cikti)`: `env`, her iki arka uçta da `os.environ`'a EKLENECEK/değişecek değişkenlerdir (tam ortam
değil). Sanalda masaüstü değerleri (DISPLAY, özel D-Bus, ses...) her zaman üstün gelir.

**Girdi nesnesi:** `gonder(k, desen, *satirlar)` (her çağrıdan önce `guvenlik.denetle`, hemen ardından
`guvenlik.girdi_seviye_denetle(k, satirlar)`: uygulama erişim seviyesi, §4), `zorla(satir)` (bırakma;
denetimsiz, kesintide bile), `ham(satir)`, `izle(k, desen)` / `izle_bitir()` (gözcü), `etk_denetle()`,
`insan_kontrol()`, `kapat()`.

**Girdi dili = dotool satır dili** (her iki arka uç da aynı satırları anlar):
`mouseto FX FY` (0..1 kesir, tüm ekran), `buttondown|buttonup|click left|right|middle`, `key K`,
`keydown K`, `keyup K` (K: `ctrl+s`, `enter`, `leftshift`…), `type METİN`, `wheel N` (artı=yukarı),
`hwheel N` (artı=sağ), `typedelay MS`, `typehold MS`. Xvfb türü bunları XTEST'e çevirir (Türkçe karakterler
dahil: xkb düzeni `tr` ya da keysym eşleme). KWin türü kalıcı `deskhand-eis` yardımcısına (libei, KWin EIS) verir:
süreç başına TEK bağlantı (kilitli paylaşılır), `type` HEP YA DA HİÇ (oturumun klavye haritasında olmayan karakter →
`hata yazilamaz` → Dur 1; `yazilabilir_mi` aynı haritadan, girdi göndermeden yanıtlar, üst katman bu karakterlerde
pano yoluna düşer). Yardımcı: hareketten sonraki ilk düğme/kaydırma öncesi bekleme `hareketbekle MS` ile açılabilir
(varsayılan 0: KWin 6.8.3'te 50 hızlı iki-pencere tıkında yanlış yüzey yok, bekleme tık başına +20 ms ekliyordu), imleç
zaten hedefteyse önce 1 px komşuya gider ("park edilmiş imleç"; ucuz önlem), kaydırma ayrık 120'lik
birim + `scroll_stop`, klavye aygıtı değişince (düzen değişimi) eskisiyle basılı kalanları yeni aygıttan bas+bırak ile
temizler, kapanışta ei_ping eşitlemesi + `disconnect(çerez)`.

**Atomiklik.** DUR denetimi satır başına değil `gonder()` çağrısı başına yapılır: bir çağrıdaki satırlar
ATOMİKTİR (çift tıklamanın iki click'i bölünmez). Harf harf yazıda (`ham`) her harften önce denetlenir.
Gözcü kesintisi (`kesildi` bayrağı) bir sonraki `izle()`ye dek kalır (iki arka uçta aynı).

**Girdi merkezi.** Panel açıkken içinde tek bir dotool HAZIR bekler (`deskhand/girdi_merkezi.py`); kde `Girdi`
satırlarını `RUNTIME_DIR/girdi.sock` üzerinden ona gönderir, kendi dotool'unu açmaz (her komutta ~0,66 sn aygıt
kurulumu yok). Protokol: `merhaba 1 <düzen> <varyant|->` → `tamam 1 <pid>`; `parti <n>` + n satır → `tamam` |
`mesgul <sn>` | `hata <kod> <mesaj>`; `bekle` → girdi bitince `tamam <n>` + n dotool uyarısı. Bir `gonder()` çağrısı
TEK partidir (atomik, başka bağlantının satırlarıyla karışmaz). İstemcideki denetimlerin HEPSİ (DUR, `denetle`, ön plan
koruması, insan önceliği, gözcü, kendi-girdi penceresi) aynen istemcide kalır; `mesgul` gelince istemci tüm
denetimleri yeniden yapıp tekrar dener. Merkez yoksa ya da el sıkışma başarısızsa `Girdi` kendi dotool'unu açar
(iç geri düşme: panel kapalıyken). Klavye düzeni farklıysa merkez boştayken dotool'u yeni düzenle yeniden açar.

**Devral.** `RUNTIME_DIR/devral`: bir Girdi nesnesinin İLK `gonder()`'inde Devral açıksa en çok 8 sn beklenir,
sonra 12 ile durulur; sonraki çağrılar beklemeden 12. Bildirimler `STATE_DIR/bildirimler.jsonl` dosyasına yazılır
(2 MB'ı aşınca son 1 MB tutulur, `gunluk.temizle`).

## 3. Hedef seçimi
`--arka` genel bayrağı / `DESKHAND_HEDEF=arka|on|oto` / kimlik `arka:` öneki → `arka_uc.sec()`. `sanal` hedefinde
`sec()` durum kaydının türüne bakar (`arka_tur()`): KWin → `KwinArkaUc`, Xvfb (ya da kayıt yok) → `SanalArkaUc`.

**Tür seçimi (tek yol, seçenek sunulmaz).** `masaustu.secilen_tur()`: `kwin_oturum.kullanilabilir()` (KWin >= 6.8,
erişilebilir render aygıtı, `deskhand-eis` + `deskhand-goruntu` derli, kdotool, dbus-daemon…) ise KWin; değilse Xvfb.
Kendiliğinden seçilen KWin AÇILAMAZSA Xvfb'ye düşülür (uyarı + günlük). Yalnız test/tanılama için
`DESKHAND_ARKA_TUR=kwin|xvfb` (zorlanan kwin kullanılamıyorsa Dur 9, sessiz düşme yok). Aynı anda TEK arka plan
masaüstü (durum kaydı + kilit). GPU: birden çok render aygıtı varsa ekrana bağlı çıkışı olmayan, boot_vga=0, tümleşik
aygıt (`KWIN_RENDER_NODES`); o aygıtla açılamazsa bir kez varsayılanla. Oturum "hazır" sayılmadan önce: Wayland soketi,
`org.kde.KWin` adı, ScreenShot2 arayüzü, oturum boyutunda (ölçek 1) bir kare, aynı boyutta EIS aygıtları; KWin
beklerken ölürse hemen hata.
Varsayılan `on` (kullanıcının gerçek masaüstü). `oto`, `deskhand decide` (karar) komutuna bağlanır: kullanıcı
ekranı meşgulse işi arka planda, olmazsa ön planda yapmayı önerir.

## 4. Güvenlik (iki arka uçta da AYNEN)
- Yasak pencereler (`yasak-pencereler.txt`): hiçbir girdi + başlatma yok (10). **Liste varsayılan olarak boştur**
  (yalnız yerleşik panel/onay penceresi yasağı vardır); kullanıcı kendi yasaklarını ekler.
- Hassas düğme / ödeme sayfası başlığı → `--onayli` yoksa 10. `--onayli` YALNIZ kullanıcı sohbette açıkça onayladıysa.
- **Riskli tuş kombinasyonları → insan onayı** (yasak DEĞİL). `guvenlik.riskli_tus(kombinasyon) -> neden | None`:
  ctrl+alt+delete, ctrl+alt+backspace, ctrl+alt+f1…f12 (sanal uçbirim), meta+l ve ctrl+alt+l (ekran kilidi),
  alt+sysrq+tuş. `k_tus` / `k_bas` hassas-eylem yolunu kullanır (`riskli_tus_engel`): `--onayli` yoksa panelden onay,
  panel kapalıysa 10; `dizi`/akış adımları aynı işlevlerden geçtiği için aynen kapsanır. Pencere sınıfından bağımsız.
  `k_bas` tuşları aynı anda basılı tuttuğundan boşlukla ayrılmış tuşlar tek küme sayılır (`birlikte=True`).
- **Uçbirime yıkıcı komut yazma → insan onayı.** Hedef pencerenin sınıfı uçbirim öykünücüsüyse (`UCBIRIM_SINIFLARI`,
  tek sabit liste) ve yazılacak metin dar bir yıkıcı kalıba uyuyorsa (`riskli_komut`: rm -r, sudo/doas/pkexec/run0,
  curl|wget … | sh, mkfs, dd of=/dev/…, > /dev/disk, çatal bombası, kökte chmod/chown -R, shutdown/reboot/poweroff/halt,
  systemctl/loginctl poweroff/reboot/suspend, git push --force/-f, :w !sudo) onay istenir. Denetim `eylem._yazi_hassas`
  (imza değişmez) ve `guvenlik.yazi_onay_ister_mi` üzerinden akar: yazmadan ÖNCE yapılır (Enter ayrı gönderilse bile
  komut metni yakalanır), parça parça/yapıştırarak yazan her yol aynı işlevi kullanmalıdır. Onay isteği komutu
  (kısaltılmış; `--gizli` ise yalnız uzunluğu), nedeni ve sınıfı taşır. Uçbirim olmayan pencerede metin sıradan yazıdır.
- **Uygulama erişim seviyeleri** (varsayılan YOK): `CONFIG_DIR/uygulama-seviyeleri.txt`, satır `DESEN = goruntule | tikla |
  tam` (DESEN yasak listesindeki gibi başlık/sınıf regex'i; İngilizce eş adlar view/click/full). goruntule = hiçbir
  girdi yok (10; okuma/ekran görüntüsü serbest), tikla = fare serbest, klavye (yaz/tuş/bas) ve pencere kapatma yok (10),
  tam = kısıt yok. Dosya yoksa/boşsa hiçbir kısıt yoktur (araç kendiliğinden uygulama kısıtlamaz); dosya okunurken
  oluşturulmaz, yalnız panelden Kaydet yazar. Birden çok desen uyarsa EN KISITLAYICI geçerlidir; biçimi bozuk satır
  (= yok, bilinmeyen seviye) güvenli tarafta goruntule sayılır (panel bozuk satırı kaydetmez). Denetim iki arka uçta
  aynıdır: `Girdi.gonder`, `denetle(k, desen)`'ten hemen sonra `guvenlik.girdi_seviye_denetle(k, satirlar)` çağırır
  (key/keydown/type = klavye; mouseto/click/button/wheel = fare; typedelay/typehold ayar satırı denetlenmez); masaüstü
  kipinde klavye etkin pencereye, fare `imlec_alti_denetle` ile imlecin altındaki pencereye bakar. `ac` ile başlatma
  etkilenmez. Seviye reddi onaydan ÖNCE verilir (boş diyalog açılmaz). Pencere yönetimi (`eylem.pencere_yonet`: taşı/
  boyutlandır/küçült/büyüt/geri) "fare" girdisi sayılır (goruntule'de 10, tikla'da serbest); değiştirici tuşlu tık
  ("keydown") ve yapıştırarak yazma klavye sayılır (tikla'da 10). Panonun kendisi (`clipboard`) pencereye bağlı olmadığından
  seviye denetimi dışındadır.
- **Riskli komut başlatma.** `ac --komut` ve MCP `open_app` (args) ham komut satırı `guvenlik.riskli_komut`'tan geçer:
  yıkıcı kalıpta insan onayı (CLI'de `--onayli`, gözetimsiz kipte geçmez), red → 10 ve hiçbir şey başlatılmaz.
- **Gözetimsiz kip.** `DESKHAND_GOZETIMSIZ=1` ya da genel bayrak `--unattended` (`--gozetimsiz`): onay gerektiren her
  eylem panel diyaloğu açılmadan ve beklemeden reddedilir (10, "gözetimsiz çalışmada hassas eylem yapılmaz"). Tek nokta
  `onay.iste_sonuc` (CLI, MCP, akış hepsi oradan geçer). Sohbet/insan olmadığından `--onayli` de geçersiz sayılır
  (`guvenlik.onayli_gecerli`). Zamanlanmış akışlar için.
- Başlık (`-b`) ve sınıf (`-s`) kilidi her girdiden hemen önce (4).
- DUR anahtarı: `DESKHAND_RUNTIME_DIR/dur` varsa her girdi çağrısından önce Dur(13); basılı her şey bırakılır.
  `deskhand dur` oluşturur, `deskhand devam` siler. Arayüz/tepsi/kısayol bunu kullanır.
  `guvenlik.dur_ac(kaynak)` / `dur_kapat(kaynak)` / `dur_kaynagi()`: dur dosyasının ilk sözcüğü `kullanici` ya da
  `cli`'dir. Kullanıcının koyduğu DUR'u CLI ezemez ve kaldıramaz (Dur 13); yalnızca arayüz kaldırır.
- Girdi merkezi (§2) istemci denetimlerine EK güvenceler verir: soket 0600 / dizin 0700 ve SO_PEERCRED ile yalnız
  aynı kullanıcı (istemci de sunucunun kullanıcısını ve soket iznini denetler); her partiden hemen önce DUR anahtarı
  (açıksa basma satırları 13 ile reddedilir, `keyup`/`buttonup` ve gecikme ayarları geçer); yalnız dotool dilinin
  bilinen fiilleri. Bağlantı başına basılı tuş/düğme izlenir: bağlantı kopunca (istemci öldü, SIGKILL) basılı kalanlar
  bırakılır (başka bağlantının da tuttuğu tuş hariç); kopan bağlantının girdisi kuyrukta sürüyorsa dotool yeniden
  başlatılır (denetimsiz girdi sürmez). DUR açılınca tüm bağlantıların basılıları bırakılır, kuyrukta girdi varsa
  dotool yeniden başlatılır (kuyruk düşer). Panel ölürse dotool'un girişi kapanır, dotool çıkar, aygıt yok olur.
- İnsan önceliği (12): kde arka ucunda kullanıcı klavye/fareyi kullanıyorsa; sanalda (iki tür) yalnız "Devral" açıkken.
  Paneldeki Devral iki türde de çalışır (önizleme `goruntu()`, girdi `Girdi.insan_ham`; KWin türünde EIS üzerinden).
- Kullanıcı meşgulken ön plan yok (15): kde arka ucu girdi, pencere öne getirme ve uygulama açmadan önce
  `mesgul.ekran_korumasi()` çağırır. Etkin pencere tam ekran / oyun biçimli ya da MPRIS'te video çalıyorsa
  Dur(15). İstisna yalnız kullanıcının açık izni (`--ekranimda`, `DESKHAND_EKRANIMDA=1` ya da bildirimdeki
  "Ekranımda yap" düğmesi → 10 dk). Sanal masaüstü etkilenmez.
- Erişilebilirlik eylem yolu (`ogeye-tikla --eylem`, `ogeye-yaz`; `erisim.py`): gerçek fare/klavye girdisi ve odak yoktur,
  bu yüzden fare yolundaki denetimler (imleç altı hariç) AÇIKÇA uygulanır: DUR (13), yasak pencere (10), başlık/sınıf
  kilidi (4), hassas düğme adı / ödeme sayfası (10 ya da panelden onay; onay isteği görüntüsüzdür), kde'de oyun/film
  koruması (15), uygulama erişim seviyesi (eylem/tık = "fare" sınıfı: goruntule'de 10; değer yazma = "klavye": tikla'da da
  10; onaydan ÖNCE), insan önceliği (12: kde'de kullanıcı klavye/fare kullanıyorsa en çok 8 sn durgunluk beklenir, sonra 12;
  sanalda yalnız Devral açıkken), günlük. Değer yazmada uçbirime yıkıcı komut denetimi de aynen (`_yazi_hassas`). Eylemden
  hemen önce (onay beklenmiş olabilir) bu denetimler yeniden yapılır. libatspi süreçte tek veri yoluna bağlanır; başka masaüstü için iş
  yardımcı süreçte yürür. Sanal masaüstü açılırken `masaustu._erisim_hazirla_ic` özel veri yolunda IsEnabled=true yapar ve
  kayıt defterini (at-spi2-registryd) kendi kafesinde başlatır.
- Erişilebilirliğin kendiliğinden açılması (kde): kullanıcının oturum veri yolunda IsEnabled=true yazılır; bu kalıcı bir
  masaüstü ayarını (`toolkit-accessibility`) değiştirebilir. Deskhand açtıysa `STATE_DIR/erisim-deskhand-acti` işareti
  yazılır ve günlüğe BİR kez not düşülür; `deskhand doctor` "açık (Deskhand açtı)" / "açık" / "kapalı" ayrımını gösterir;
  `deskhand a11y off` işareti de siler. Testler `_erisim_yaz`'ı taklit eder (gerçek oturum ayarına dokunulmaz).
- Ham `dotool`/`xdotool` çağrısı YALNIZ arka uç içinde. Testler dahil başka yerde ASLA.
- Sanal X bağlantısı yalnız `masaustu.guvenli_ekran()` ile açılır: boş ad Xlib'de `$DISPLAY`'e (kullanıcının gerçek
  XWayland'i) düşer ve XTEST girdisi gerçek masaüstüne gidebilirdi. Yalnız `:N` biçiminde ve gerçek `DISPLAY`'den
  farklı ekran kabul edilir.
- **KWin türü kapıları.** `kwin_oturum.guvenlik_kapilari` (süreç başlamadan): veri yolu adresi kullanıcının gerçek
  adresi, Wayland soket adı kullanıcınınki, yapılandırma dizini gerçek `~/.config`, HOME/çalışma dizini gerçek, XWayland
  ekranı gerçek `DISPLAY` ise Dur 14. `kwin_oturum.baglanti_denetle` aynı kapıları + soketlerin oturum dizininde, oturum
  dizininin `RUNTIME_DIR/kwin-*` olduğunu `arka_uc/kwin.py`'nin HER bağlantısından önce yeniden sınar (oynanmış/bayat
  durum dosyası gerçek oturuma bağlatamaz). `deskhand-eis` yalnız `--bus <özel adres>` ile bağlanır, ortamdan devralmaz,
  gerçek adresi reddeder. KWin `env -i` eşdeğeri asgari ortamla, geçici HOME/XDG_*_HOME ile açılır (KWin kendi kwinrc /
  kwinoutputconfig.json / kglobalshortcutsrc / kxkbrc dosyalarını buraya yazar); KDE_FULL_SESSION/KDE_SESSION_VERSION
  KWin'e verilmez.
- **Uygulama ortamı (iki tür).** `arka_ortak.ortam_tabani`: kullanıcının oturumuna ait değişkenler (gerçek veri yolu,
  WAYLAND_DISPLAY/DISPLAY/XAUTHORITY, AT_SPI_BUS_ADDRESS, SSH_AUTH_SOCK/SSH_AGENT_PID, GNOME_KEYRING_CONTROL,
  LIBEI_SOCKET/EIS_SOCKET, SESSION_MANAGER, KDE_FULL_SESSION, PULSE_*/PIPEWIRE_*/IBUS_*) birleştirmeden ÖNCE ve SONRA
  silinir; `GSETTINGS_BACKEND=memory` (gerçek dconf'a yazılmaz), `ATSPI_DBUS_IMPLEMENTATION=dbus-daemon` (erişilebilirlik
  başlatıcısı `dbus-broker --scope user` ile kullanıcının gerçek a11y veri yolunu yeniden kullanamasın).
  `XDG_RUNTIME_DIR` masaüstünün kendi klasörüdür (`<çalışma>/run`, 0700); ses sunucusuna yalnız AÇIK yolla
  (PULSE_SERVER + PIPEWIRE_RUNTIME_DIR) ve yalnız boş çıkışa gidilir. HOME bilerek kullanıcınındır (uygulamalar
  kullanıcının dosyalarıyla çalışır; profil/ayar yazımı oturum politikasıyla sınırlanır).
- **Özel D-Bus sertleştirmesi (iki tür).** `UpdateActivationEnvironment` ve `ReloadConfig` reddedilir; standart
  servis dizinleri yoktur, yalnız org.a11y.Bus etkinleştirilebilir.
- **Düşük öncelik (iki tür).** Kafes nice 10 + ionice idle ile başlar; KWin `no_new_privs` (dosya yeteneği
  cap_sys_nice VERİLMEZ), RLIMIT_RTPRIO=0 ve RLIMIT_NICE (en düşük nice 10) ile açılır; ad tabanlı sistem kurallarına
  (ananicy: `kwin_wayland` → nice -12) karşı kafesin öncelik bekçisi (`oncelik_bekcisi.py`) her iş parçacığını ~0,5 sn
  içinde nice >= 10, gerçek zamanlı olmayan zamanlama ve idle G/Ç'ye geri düşürür. XWayland takma adla
  (`deskhand-xwayland`) çalışır.

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
- **Pano + yapıştırarak yazma (Faz 9a).** `eylem.yaz_ic`: klavye düzeninde olmayan karakter (emoji…) ya da 200
  karakterden uzun yazı panoya konup yapıştırılır (uçbirimde ctrl+shift+v, yoksa ctrl+v); `\n` Enter, `\t` Tab tuşu
  olarak aynen kalır (parçalar arasında). Eski pano önce alınır, hata/DUR/kesintide de geri yüklenir; tüm güvenlik
  denetimleri (hassas sayfa onayı tam metinde, başlık/sınıf kilidi, DUR, gözcü, insan önceliği, ön plan koruması) her
  `gonder()`'de çalışır; yapıştır tuşu `Girdi` üzerinden gider. MCP `clipboard`, CLI `pano`: ön planda okuma insan
  onayı ister (Deskhand'in bu oturumda yazdığı metin hariç), arka planda serbest (§2, §4).
- **Oyun/film sırasında ön plan yok.** Kullanıcı oyun oynarken ya da video izlerken Deskhand gerçek ekrana
  müdahale etmez (kod 15); yalnız açık kullanıcı izniyle istisna vardır. Sanal masaüstü bundan etkilenmez (§4).
- **Yasak listesi varsayılan boş.** Deskhand bir "tıklama aracıdır"; kullanıcı neyi yasaklayacağına kendisi karar
  verir. Yalnız Deskhand'in kendi panel/onay penceresi daima yasaktır (§4).
- **Riskli eylem = onay, yasak değil.** Yasak listeleri varsayılan boş kalır; oturumu sonlandıran tuşlar ve uçbirime
  yazılan yıkıcı komutlar insan onayı ister (dolaylı komut enjeksiyonuna karşı), uygulama erişim seviyeleri de varsayılan
  olarak yoktur (§4). Gözetimsiz kipte onay asla sorulmaz, red olur.
- **Sanal ekran güvenliği.** Sanal X bağlantısı yalnız doğrulanmış `:N` ekranına açılır; boş `DISPLAY` asla
  gerçek masaüstüne düşmez (§4).
- **Devral ve bildirimler.** Sanal masaüstünde kullanıcı "Devral" ile denetimi alabilir; bu durum ve bildirimler
  durum dizininde tutulur (§2).
- **Girdi merkezi.** kde arka ucu girdiyi panelin hazır dotool'u üzerinden gönderir (kurulum beklemesi yok); güvenlik
  denetimleri istemcide aynen kalır, merkez DUR'u ayrıca denetler ve kopan bağlantının basılılarını bırakır (§2, §4).
- **Arka plan masaüstü KWin türü (Faz 12b).** Koşullar uygunsa arka plan masaüstü yalıtık KWin oturumudur (Wayland
  yerel uygulamalar, GPU hızlandırma, X11 isteyenler oturumun XWayland'ine); değilse Xvfb. Dış yüzey değişmez (§2, §3,
  §4). Bilinen sınırlar: Wayland açılır menü/açılır liste (xdg_popup) yalnız gerçek girdi olayıyla açılır → AT-SPI
  "Show Menu" eylemi menü açamaz (fare yolu çalışır), açılır listenin ögeleri ağaçta görünmez; Wayland istemcisi panoyu
  yalnız bir girdi olayından sonra ayarlayabilir; kök zemin KWin'in (gri değil).
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
- CLI `--onayli` kalır (kullanıcı sohbette açıkça onayladıysa), MCP yüzeyinde YOK. Riskli tuş ve uçbirim komutu da bu
  protokolü kullanır (eylem metni "Riskli tuş: …" / "Uçbirime komut yaz: …"); gözetimsiz kipte `iste_sonuc` hiç panele
  yazmadan `gozetimsiz` nedeniyle red döner.
- Onay diyaloğu penceresi yasak listesine (sınıf/başlık) otomatik eklenir: hiçbir otomasyon girdisi ona gitmez.
