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
  gunluk.py        günlük (0600; STATE/CACHE dizinleri 0700, açılışta düzeltilir) + temizlik
  guvenlik.py      yasak pencereler, hassas düğme, ödeme sayfası, riskli tuş/uçbirim komutu onayı, uygulama erişim
                   seviyeleri, başlık/sınıf kilidi, denetle(), DUR anahtarı
  insan.py         Wayland etkinlik izleyici (ekran-etkinlik C yardımcısı) + insan_bekle
  kendi.py         ajanın kendi istemcisi: ata süreç kümesi (/proc), tmux istemcileri, ön plan süreci (§4)
  ucbirim.py       uçbirim Enter kapısı: giriş satırı okuma (AT-SPI/OCR) + yazı tamponu (§4)
  ocr.py           oku, satirla, ara, derin_oku, önbellek, ön işleme
  gorsel.py        simge (NCC), renk alanları, ızgara
  eylem.py         tikla/yaz/tus/kaydir/bas/surukle/dizi: arka uçtan BAĞIMSIZ üst katman
  akis.py, erisim.py (AT-SPI), uygulama.py (ac)
  web.py           web sayfası ögeleri: tarayıcının erişilebilirlik ağacından okuma (§9); MCP read_text(source="web"),
                   CLI `web`, click-element'in web yolu
  cli.py           argparse; komut adları İngilizce + Türkçe takma adlar. `deskhand --help` alt komut tablosu
                   (`KISA_ACIKLAMA`); `screenshot` kimliksiz (`varsayilan_foto_hedefi`: görünmez masaüstünde tüm
                   masaüstü, ön planda etkin pencere + gerçek ekran kilidi 17), `windows` desensiz (yasak pencere
                   başlığı maskeli)
  gezin.py         `goto KİMLİK ADRES`: adres çubuğu yolu (ctrl+l → adres → Return) `api.tus`/`api.yaz` üzerinden; yeni
                   güvenlik yolu YOK (başlık kilidi, hassas sayfa, CAPTCHA kapısı, DUR, insan önceliği aynen); yalnız http(s)
  dosya_sec.py     `choose-file KİMLİK YOL`: ctrl+l → AT-SPI odaklı girdi (erisim.odakli_metin) → yol → değer GERİ
                   okunur (≠ yol → Dur 8, Enter yok) → Return → diyalog kapandı mı; arka planda yalnız XDG/test paylaşımı
  surum.py         diskteki kurulum sürümü ↔ çalışan kod: get_status `stale_server`, doctor `deskhand mcp` süreçleri
  ipucu.py         ipuçlarında çalıştırılabilir tam komut (`deskhand --desktop-name AD --background tree K`)
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
  masaustu.py      arka plan masaüstü yaşam döngüsü (TEK giriş noktası, iki tür): tür seçimi, başlat/durdur/durum/
                   liste, uygulama başlatma; durum masalar.durum_yolu() ("tur": "kwin" | "xvfb"; varsayılan masaüstü
                   RUNTIME_DIR/sanal.json); `ad` parametresi (None = bağlam), oto masaüstü temizliği
  masalar.py       çoklu görünmez masaüstü: ad doğrulama (`[a-z0-9][a-z0-9-]{0,15}`, "" = varsayılan, `gorev`
                   ayrılmış), bağlam (`secili()`: masa_sabit > DESKHAND_MASAUSTU > ""), masaüstü başına yollar
                   ("" → eski yollar AYNEN; adlı → RUNTIME_DIR/masa/<ad>/{sanal.json, sanal.lock, devral, girdi.lock,
                   sahip, oturum/}), sahiplik + erişim kapısı, `[masaustu] azami`. Tekil yol sabitleri ("sanal.json",
                   "sanal.lock", "devral") YALNIZ masaustu.py/masalar.py'de (tests/test_masalar.py denetler)
  kwin_oturum.py   KWin türünün yapı taşları: kwin_wayland --virtual + özel D-Bus + özel Wayland soketi + XWayland,
                   güvenlik kapıları (guvenlik_kapilari, baglanti_denetle), GPU seçimi, hazır olma denetimi, Eis sınıfı
  arka_ortak.py    iki türün ORTAK iç yapı taşları: bellek kafesi, öncelik, boş ses çıkışı, uygulama ortamı tabanı
                   (ortam_tabani), özel D-Bus yapılandırması, Xauthority, öncelik bekçisi başlatma
  oncelik_bekcisi.py  kafesteki her iş parçacığını nice >= 10 / gerçek zamanlı olmayan / idle G/Ç'de tutan bekçi;
                   ekran sunucusu (KWin/Xvfb) SIGKILL/OOM ile ölürse oturumu kapatır (kafes, X soket/kilit, dizin)
  ses_bekcisi.py   (artık başlatılmıyor: arka plan uygulamaları kullanıcının ses sunucusuna hiç erişmez)
  ses.py           oturuma ÖZEL ses sunucusu (pipewire + wireplumber `policy` + pipewire-pulse; donanımsız, yalnız
                   `deskhand-sessiz` boş çıkışı + monitörü): kurma/kapatma/sağlık, istemci ortamı
  dinleme.py       `listen` çekirdeği: özel çıkışın monitöründen bellekte kayıt (parec) → whisper-cli → metin
  pano_sahibi.py   sanal masaüstünün CLIPBOARD seçimini sunan yardımcı süreç (kafeste, ilk pano yazımında başlar)
  oturum/          oturum köprüsü (bkz. docs/SESSIONS.md)
  mesgul.py        kullanıcı meşgul mü (oyun / film) koruması
  onay.py          insan onayı protokolü (§8): istek dosyası + panelin doğrulanmış onay kanalı (Unix soketi)
  onay_hedef.py    onay verilen hedefin özeti (kimlik, başlık, geometri, bölge görüntüsü) + onay sonrası doğrulama (§8)
  liste_koruma.py  yasak/seviye listeleri, onay kapsamı, hesap oturumları: panel yetkili kaynak (bellek, geri yazma,
                   işaret, kanaldan okuma; §4)
  girdi_merkezi.py panelin içinde hazır bekleyen tek dotool + RUNTIME_DIR/girdi.sock (Qt'siz; §2, §4)
  gui/             panel, tepsi, onay diyaloğu; gui/gorev.py = "Görev" sekmesi (görev kutusu, canlı adımlar, görünmez
                   masaüstünün canlı görüntüsü, geçmiş). Panel girişinde genel istisna yakalayıcı
                   (panel.istisna_yakalayici_kur: sys/threading excepthook → günlük + tepsi uyarısı; PyQt6'nın SIGABRT'i yok)
  gorev.py         görev yürütücü (Qt'siz): kullanıcının yazdığı görevi `claude -p --output-format stream-json` ile
                   YALNIZ `deskhand mcp --desktop background` araçlarıyla yaptırır. Ayrıcalık sınırı argv'de:
                   geçici --mcp-config (tek sunucu deskhand-gorev, env DESKHAND_GERCEK_EKRAN=kapali) + --strict-mcp-config +
                   --allowedTools mcp__deskhand-gorev__* + yerleşik araçlar --disallowedTools + --permission-mode dontAsk +
                   --setting-sources project; boş geçici çalışma dizini; istem stdin'den; olaylar {tur, zaman, ozet};
                   geçmiş STATE_DIR/gorevler/*.jsonl (0600, son 50); aynı anda tek görev (flock RUNTIME_DIR/gorev.lock);
                   ayarlar [gorev] model / azami_dakika / azami_tur; MCP sunucusu GÖREV KİPİNDE (§11)
  gorev_kipi.py    görev kipi kuralları (DESKHAND_GOREV=1): tarayıcı ilkesi, site izni, open_app süzgeci, maskeleme,
                   görev masaüstü kapısı, pencere sınırı, kimlik değişkeni süzgeci (§11)
  fark.py          eylem öncesi/sonrası ekran farkı (changed, changed_region, changed_ratio; NumPy, imleç dayanıklı)
  dongu.py         döngü kesici: aynı eylem 3. sonuçsuzda uyarı, 5'ten sonra ret (MCP, oturum başına bellek)
  gozlem.py        MCP observe: ögeleri tek biçime getirme, sorgu/atalar, OCR ayıklama, anlık görüntü önbelleği
                   (snapshot_id, ref), fark (since), numaralı görüntü (§10)
  gonderim.py      eylem sırasında gerçekten gönderilen girdinin sayacı (iş parçacığına özgü; MCP `sent`, §10)
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
INCR; çalışma klasöründe 0600 `pano.sock`; bağlantı başına TOPLAM 5 sn süre, başlık ≤ 64 bayt, `YAZ n` n > AZAMI_VERI
ise veri okunmadan "hata cok-buyuk"); okuma süreç içinde. KWin türü: `wl-copy`/`wl-paste` oturumun MUTLAK
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
koruması, insan önceliği, gözcü, ajanın kendi istemcisi, oturum kilidi) aynen istemcide kalır; `mesgul` gelince istemci tüm
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
`DESKHAND_ARKA_TUR=kwin|xvfb` (zorlanan kwin kullanılamıyorsa Dur 9, sessiz düşme yok).

**Çoklu görünmez masaüstü (Aşama 1 çekirdeği).** İLKE: bir süreç (MCP oturumu ya da CLI çağrısı) TEK görünmez
masaüstüne bağlıdır; aynı anda en çok `[masaustu] azami` (1..6, varsayılan 3) masaüstü, aşılırsa Dur 7. Her masaüstünün
kendi durum kaydı + kilidi + girdi kilidi + Devral bayrağı + oturum kopyası kökü vardır (`masalar`); alt katman
(KWin oturumu `RUNTIME_DIR/kwin-<kimlik>`, kafes, Wayland soketi, D-Bus, özel PipeWire) zaten masaüstü başınadır.
Adlı masaüstü YALNIZ KWin türünde (Xvfb türü yalnız varsayılan adla; ortak null sink adı). `arka_uc.sec()` önbelleği
`(masa, tür)` anahtarlıdır. Bağlam: CLI `--desktop-name AD` (komuttan önce) / `desktop … --name AD` / ortam
`DESKHAND_MASAUSTU`; MCP OTOMATİK bağlanır (ilk `desktop=background` çözümünde): `--desktop-name`/ortam sabitse o;
yoksa varsayılanın canlı sahibi yoksa varsayılan; yoksa en küçük boş `oturum-N` (oto). Bağlanınca
`os.environ["DESKHAND_MASAUSTU"]` yazılır (alt süreçler devralır; `erisim` yardımcı süreci isteğinde `masa` taşır);
`get_status`/`manage_desktop` yanıtında `name`. Görev kipindeki MCP HEP varsayılan masaüstüne bağlanır (sahipliğe
dokunmaz). MCP ilk ebeveynini saklar; ebeveyn ölüp systemd'ye geçtiyse bağlanmaz (Dur 14). SAHİPLİK: `sahip` dosyası
(varsayılan için `RUNTIME_DIR/sanal-sahip`) = `mcp <pid> <başlangıç> <ilk_ebeveyn_pid> <ebeveyn_başlangıç> <oto>
<pid ad alanı>`; KAPI `masalar.erisim_kapisi` (gorev_kipi kapılarından çağrılır, okuma dahil): varsayılan masaüstü
göreve ayrılmışsa (görev işareti canlı) ÖNCE görev işareti: görev kipi → izin, panel → izin, diğer herkes (sahibi dahil)
→ Dur 14 (görev masaüstü); görev bitince sahiplik aynen geri gelir. Sonra: sahibi ölü/bozuk/PID yeniden kullanılmış →
serbest; sahip başka PID ad alanında (denetlenemez) → Dur 14; çağıran sahip → izin; çağıranın ata zincirinde sahibin
ebeveyni (başlangıç zamanıyla) → izin (aynı Claude oturumunun Bash'i); ata zincirinde HİÇ `claude` süreci yok (insan:
kendi terminali, KDE kısayolu) → izin; panel (GOZLEMCI) → izin; diğer → Dur 14. Bu bir KOORDİNASYON kuralıdır (ajan
oturumları birbirinin masaüstünü bozmasın); aynı kullanıcının kabuk koduna karşı GÜVENLİK SINIRI DEĞİLDİR (aynı uid
dosyayı silebilir, ata zincirini taklit edebilir). Panel onay devrinde (CAPTCHA) "Devral", Arka plan sekmesini
isteğin masaüstüne çevirir (panel sürecinin bağlamı), karar verilince varsayılana döner; onay diyaloğu masaüstü adını
gösterir. Flatpak örneği yalnız çocuk PID eşleşmesiyle kaydedilir (uygulama adıyla eşleşme yok: başka masaüstünün
örneği kaydedilip öldürülmesin). ÖMÜR: MCP kapanışında yalnız sahiplik bırakılır; `oto` masaüstü için ayrık temizleyici
(start_new_session, `DESKHAND_OTO_BEKLE` ya da 120 sn) sahipsizse durdurur; her başlatma ve `desktop list` sahipsiz
otoları durdurur. Varsayılan ve sabit adlılar kendiliğinden kapanmaz. Durdurma (`masaustu_durdur(ad)`) YALNIZ o
masaüstünün süreçlerini, oturum kopyalarını ve Flatpak örneklerini kapatır (`oturum.kapanis(ad)`,
`politika.kopya_dizini(ad)`). Onay isteği `masa` alanı taşır; `onay.bekleyen_var(..., masa)` ve MCP
`_BEKLEYEN[(arka uç, masa)]`: bir masaüstündeki bekleyen onay başkasını kilitlemez. Görev kipi işareti
(`gorev-masaustu`) yalnız varsayılan masaüstünü ayırır (Aşama 2'de `gorev` adına taşınacak). Panel yalnız varsayılan
masaüstünü gösterir (devir sırasındaki geçiş dışında; Aşama 2). GPU: birden çok render aygıtı varsa boot_vga=0 + tümleşik aygıt ("bağlı çıkış"
bilgisine güvenilmez) (`KWIN_RENDER_NODES`); o aygıtla açılamazsa bir kez varsayılanla. Oturum "hazır" sayılmadan önce: Wayland soketi,
`org.kde.KWin` adı, ScreenShot2 arayüzü, oturum boyutunda (ölçek 1) bir kare, aynı boyutta EIS aygıtları; KWin
beklerken ölürse hemen hata.
ÖLÇEK 2 (HiDPI, `desktop start --scale 2` / `manage_desktop(scale=2)`, yalnız KWin; kayıtta `olcek`, eski kayıt = 1):
`kwin_wayland --virtual --width G --height Y --scale 2` çerçeve tamponunu 2G×2Y açar ama KWin'in çıkış deposu yeni
sanal çıkışa ölçek 1 verir (ölçüldü: EIS bölgesi 2G×2Y, düzen büyür) → hazır denetiminden önce `kscreen-doctor
output.<ad>.scale.2` oturumun KENDİ Wayland soketiyle (`_ekran_ortami`: mutlak WAYLAND_DISPLAY, özel veri yolu,
KSCREEN_BACKEND_INPROCESS; kullanıcının ekranına ulaşamaz). Hazır: kare 2G×2Y, EIS bölgesi G×Y. SÖZLEŞME: pencere
geometrisi, tıklama/EIS koordinatı, AT-SPI kutuları, OCR kutuları MANTIKSAL piksel (ölçek 1 ile aynı düzen);
`ArkaUc.goruntu()` fiziksel kare. `gorsel.pencere_goruntusu(tam=False)` (varsayılan; OCR, observe, fark, onay)
fiziksel kareyi mantıksala LANCZOS ile küçültür; `tam=True` küçültmez, `im.info["deskhand_olcek"]`
(`gorsel.piksel_olcegi`) = görüntü pikseli / pencere pikseli. Tam çözünürlüğü kullananlar: CLI `screenshot`
(`--out` dosyası 2×, `--width` küçültür; `son_foto.olcek` = toplam ölçek, `--foto` eşler) ve MCP `screenshot`
(tam kare `max_edge`'e küçültülür; `shot_id` ölçeği = küçültme × piksel ölçeği → `cekim_noktasi` mantıksal koordinat
verir; küçük bölgeler 2× ayrıntıyla döner). XWayland: KWin `[Xwayland] Scale=2` (istemciler kendileri ölçekler, X11
koordinatı fiziksel) → oturum uygulamalarına `GDK_SCALE=2` (Firefox dpr 2), Chromium/Electron'a
`--force-device-scale-factor=2`; AT-SPI kutuları YALNIZ ölçek > 1 masaüstünde (istekte `olcek`,
`ArkaUc.masaustu_olcegi()`) ve çerçeve pencere geometrisinin ~ölçek katıysa (iki boyutta da |oran − ölçek| < 0,35;
`erisim.xwayland_orani`) ölçeğe bölünür; ölçek 1'de hiç bölünmez (çerçevesini büyük bildiren uygulamada yanlış tık
olmasın). Xvfb türünde ölçek 2 Dur(9) ile reddedilir (çıkış ölçeği yok; uygulama başına bayraklar Qt/GTK/X11
karışımında tutarsız). Bellek: 2× kare ~4 kat çerçeve tamponu (1280x800'de Firefox'lu kafes ~500 MiB; 4 GB kafes
yeter).
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
- **UÇBİRİMDE KOMUT ÇALIŞTIRMAK HER ZAMAN İNSAN ONAYI İSTER; kara liste (`riskli_komut`) yalnız UYARI içindir.**
  Uçbirim (ya da gömülü uçbirim) barındıran pencereye giden HER Enter — enter, kpenter, linefeed, `x:Return`, `k:28`,
  ctrl+j/ctrl+m/ctrl+o, yazının içindeki `\n`, AT-SPI değer yazmadaki satır sonları — satır içeriğinden BAĞIMSIZ panel
  onayı ister (`ucbirim.enter_kapisi`): bir Enter = bir onay (aynı eylemdeki önceki onay taşınmaz; `yaz "a\nb\n"` iki onay,
  `tus "l s enter p w d enter"` iki onay); gözetimsiz kipte ret (10); CLI'de `--onayli` (kullanıcı sohbette onayladı) geçer.
  İstisna YOK: ön planda vim/less/REPL olsa da sorulur (tpgid ile bulunan ön plan süreci yalnız onay metnine "ön planda
  kabuk değil: …" notu olarak girer). Onay isteği: "Uçbirimde komut çalıştırılacak (Enter)", o anki satır (okunabiliyorsa;
  `--gizli`/parola ise yalnız uzunluk; okunamıyorsa "satır okunamadı"), `riskli_komut` ya da geçmiş açılımı (`!!`, `!n`,
  `^a^b`, `fc`, `r`, `history -s`) eşleşirse "YIKICI OLABİLİR: <neden>", uçbirim türü (gömülü mü). Satır okuma: erişilebilirlik
  ZATEN açıksa AT-SPI (rolü `terminal` olan ögenin imleç satırı + önceki iki satır; erişilebilirlik bunun için açılmaz),
  yoksa pencerenin OCR'ı (en alttaki dört yazılı satır; istem işaretinden sonrası, sarılmış satırların birleşimi ve tek tek
  satırlar aday); Deskhand'in yazdıklarının TAMPONU (`RUNTIME_DIR/ucbirim/<sha1(arka uç:pencere:pid)>.json`, 0600, dizin
  0700, flock; yazdırılabilir tuş/`type` eklenir, BackSpace siler, Enter/ctrl+c/ctrl+u/Esc temizler; ok tuşları, ctrl+a/e/r/w,
  Tab, tık, yapıştırma, başka uçbirime geçiş ve 120 sn hareketsizlik "kirli" yapar) uyarı adayına eklenir. Zamanlama:
  `tus`/`bas` dizisi Enter'larda bölünerek gönderilir ve HER Enter'dan HEMEN önce pencere yeniden hesaplanır (dizinin
  ortasında da); yazının içindeki Enter'lar yazmadan önce sırayla onaylanır, önceden onaylanmamış bir Enter gönderimden
  hemen önce yeniden hesaplanıp gerekiyorsa o an sorulur. Kapsanan yollar: `tus`/`bas`, `yaz` (harf harf + yapıştırarak),
  `dizi`/akış adımları, AT-SPI değer yazma. Uçbirim barındırmayan pencerede Enter'a dokunulmaz (onay sayısı değişmez).
- **Uçbirime yıkıcı komut YAZMA** (Enter'sız): hedef uçbirim barındırıyorsa ve metin `riskli_komut` uyarısı üretiyorsa onay
  istenir (`guvenlik.ucbirim_komut_engel`, `eylem._yazi_hassas`); yazıda Enter varsa bu ayrı sorulmaz (Enter onayı aynı
  uyarıyı taşır: iki diyalog açılmaz). `riskli_komut` (uyarı) metni kabuk kurallarıyla sözcüklere ayırır (tırnak/ters bölü
  kaldırılır, `$'…'` açılır, `$(…)`/`` `…` ``/`<(…)` içi ayrıca denetlenir; kabuk anahtar sözcükleri, atamalar atlanır;
  aynı metindeki atama çözülür; küme açılımı; `busybox X` → X; sarmalayıcı seçenekleri; `env -S`); uyarı kalıpları: yıkım
  (rm -r, find -delete/-exec, mkfs, dd, shred, truncate -s 0, git clean -f, rsync --delete ~, mv ~), yetki (sudo/doas/
  pkexec/run0), güç/oturum (shutdown/reboot…, systemctl/loginctl, D-Bus `login1 … Reboot/PowerOff/Suspend`,
  `org.kde.Shutdown`, ksmserver), masaüstünü/Deskhand'i sonlandırma (`killall`/`pkill`/`kquitapp*` plasmashell/kwin/
  deskhand, `systemctl stop plasma-*`), Deskhand'in ayar/durum dosyalarına dokunma, dolaylı yürütme (`… | sh`, `base64 -d |
  …`, kabuğa `<`/`<<`/`<<<`, `source`/`.`, `eval`, `alias`/`trap`, `PROMPT_COMMAND`/`PS0`/`BASH_ENV`/`LD_PRELOAD`, geçmiş,
  komut adında `${…}`/`$(…)`), içeriği denetlenemeyen betik/program (`./x.sh`, `~/x.sh`, `bash x.sh`, `python3 x.py`, geçici
  dizinden program), GTFOBins seçenekleri (`--checkpoint-action`, `ProxyCommand`, `rsync -e`, sed `e`, `man -P`, `zip -TT`,
  vim `:!`), kalıcılık (başlangıç dosyaları, autostart, `~/.ssh`, `~/.local/bin`, crontab), ayrık başlatıcılar
  (`systemd-run`, `at`, `tmux new`, `screen -dm`, `flock -c`, `watch`), indirileni kabuğa verme, çatal bombası, zorla git
  push, `:w !sudo`. Uyarı listesi eksik olabilir: güvenlik sınırı yukarıdaki Enter onayıdır.
- **Uçbirim tanıma** (`guvenlik.ucbirim_penceresi_mi`): pencere sınıfı uçbirim öykünücüsüyse; YA DA pencerenin sahibi
  sürecin TORUNLARINDA denetim uçbirimi (tty) olan bir kabuk varsa (GÖMÜLÜ uçbirim: Dolphin F4, Kate uçbirim paneli,
  VS Code/IDE — pencerenin tamamı uçbirim sayılır); PID bilinmiyorsa ve sınıf uçbirim gömebilen bir uygulamaysa
  (`GOMULU_UCBIRIM_SINIFLARI`) güvenli tarafta; erişilebilirlik zaten açıksa pencerede rolü `terminal` olan öge varsa.
  Yalnız "uçbirim" sonucu 2 sn önbellekte tutulur; "uçbirim DEĞİL" sonucu önbelleğe alınmaz (her Enter'dan önce yeniden
  hesap). Gömebilen sınıftaki pencereye uçbirim açabilen bir tuş (F4, shift+F4, ctrl+`, ctrl+shift+`, ctrl+alt+t,
  ctrl+shift+t, alt+F12) gönderildikten sonra pencere 30 sn "uçbirim olabilir" sayılır (`RUNTIME_DIR/ucbirim/ucbirim-<sha1>`;
  o sürede her Enter onaylı); aynı çağrıda uçbirim açma tuşu Enter'dan önce geliyorsa o Enter da onay ister.
- **Ajanın kendi istemcisi** (`deskhand/kendi.py`): Deskhand süreci (CLI ve MCP sunucusu) `/proc/<pid>/stat` ppid ile
  1'e kadar yürür (oturum altyapısı — systemd, kwin, plasmashell, krunner… — hariç); MCP sunucusunda küme 15 sn'de bir
  tazelenir. Penceresinin sahibi PID'i (kde: `kdotool getwindowpid`; sanal: `_NET_WM_PID`) bu kümedeyse o pencereye HER
  girdi 10 ("ajanın kendi istemcisi"; ajan kendi izin istemini onaylayamasın); okuma/ekran görüntüsü serbest. Uçbirimler çoğu
  zaman TEK süreçte çok pencere tutar (Ghostty, Konsole): o sürecin TÜM pencereleri kapsanır. Zincirde tmux varsa `$TMUX`
  soketiyle salt okunur `tmux list-clients -F '#{client_pid}'` → istemcilerin ataları (öykünücü) eklenir; çözülemezse
  (screen, zellij, dtach, tmux sorgusu başarısız) TÜM uçbirim sınıflı pencereler (kde). PID'i bilinmeyen pencereler (kde):
  ortam ipuçları (`KONSOLE_DBUS_WINDOW`, `WINDOWID`, `TERM_PROGRAM`, `GHOSTTY_RESOURCES_DIR`, `KITTY_PID`,
  `ALACRITTY_WINDOW_ID`) ve zincirdeki öykünücünün adı → o sınıftaki PID'siz uçbirim pencereleri de. PID ad alanında
  çalışıyorsak (flatpak/bwrap: `/.flatpak-info`, zincirde bwrap ya da `/proc/<pid>/status` NSpid birden çok): ataların
  dış PID'i (NSpid ilk alanı) kümeye eklenir ve PID'i eşleşmeyen aynı sınıftaki uçbirim pencereleri de kapsanır (pencere
  yöneticisi dış PID'i görür). ssh üzerinden bağlanan
  uzak istemci kapsam dışıdır. Görünmez masaüstündeki pencereler ajanın istemcisi olamaz: orada yalnız PID kuralı vardır
  (doğal olarak boşa çıkar). Denetim yerleri: `denetle`, `pencere_denetle` (AT-SPI), `imlec_alti_denetle` (tıklamanın/
  sürüklemenin düştüğü pencere), masaüstü kipinde klavye girdisinin gittiği etkin pencere (`girdi_seviye_denetle`),
  `pencere_yonet`, `k_kapat`, AT-SPI çerçevesinin süreci; yapıştırarak yazma her parçada `denetle`'den geçer.
- **Sistem yetki/parola/izin istemleri → insan onayı** (yasak değil): polkit kimlik doğrulama aracısı, KWallet
  (`kwalletd5/6`, `ksecretd`), parola sorucuları (`ksshaskpass`, `pinentry-*`, `ssh-askpass`), `xdg-desktop-portal-*` izin
  diyalogları (`org.freedesktop.impl.portal…`), `kdesu`/`sudo`/`pkexec` istemleri (`guvenlik.SISTEM_ISTEMLERI`, tek sabit
  liste; pencere sınıfında ve sahibi sürecin adında). Bu pencerelere her tür girdi (fare, klavye, yapıştırma, AT-SPI
  eylemi/değer yazma, sürükleme, pencere yönetimi, kapatma) eylem başında onay ister (`sistem_istemi_engel`; CLI
  `--onayli`, MCP'de her zaman panel, gözetimsiz kipte ret); onay o eylem boyunca o pencere için geçerlidir. Her gönderimden
  hemen önce `sistem_istemi_denetle` onaysız istemde 10 verir — girdinin DÜŞTÜĞÜ ekran noktasındaki pencere için de
  (`imlec_alti_denetle`: başka pencere hedeflenip noktada istem açıksa izin olsa bile ret; masaüstü kipindeki tıkta noktadaki
  isteme onay sorulur).
- **Yapıştırma = pano okuma** (kde): `ctrl+v`, `ctrl+shift+v`, `shift+insert`/`shift+kpinsert`, Paste tuşu (`XF86Paste`, `k:207`),
  klavye menüsüyle yapıştırma (`shift+F10` / `menu` / `alt+e` ardından `p`/`y` ya da menüde gezinip Enter — aynı çağrıda
  ya da 3 sn içinde ayrı çağrıda), orta tık (birincil seçim), AT-SPI ögesinin adı/eylem adı "paste/yapıştır" İÇERİYORSA
  (simgeli düğmenin erişilebilir adı) ve MENÜDEN
  yapıştırma (tıklanan yazı ya da AT-SPI öge adı Yapıştır/Paste/Einfügen/Coller/Pegar…, "Panodan ekle", "Insert from
  clipboard", "Paste as…", "Özel yapıştır", 📋 ya da "Ctrl+V" ipucu; kısa metin;
  `guvenlik.hassas_engel` içinde — fare, AT-SPI eylemi ve aynı işlevi çağıran web yolları) kullanıcının
  panosunu ajanın görebileceği yere taşır: pano boş değilse ve Deskhand'in bu oturumda yazdığı metin değilse
  (`guvenlik.kendi_pano_ekle/kendi_pano_mu`: süreç belleği + `RUNTIME_DIR/pano-ozetleri`, 0600, yalnız sha256) onay ister
  (okunamıyorsa da). Deskhand'in kendi yapıştırarak yazma yolu (`eylem._yapistirarak_yaz`) muaftır. Sanal masaüstünün
  panosu ayrıdır: denetim yok. BİLİNEN SINIR: yazısı OCR'la okunamayan VE erişilebilir adı olmayan simgeli bir "yapıştır"
  düğmesine fareyle tıklama tanınamaz (koordinatla tık; onay sorulmaz).
- **Parola alanı** (AT-SPI rolü `password text`, değer yazmada hedef öge, klavyeyle yazmada odaklı öge — erişilebilirlik
  açıksa): yazı / yapıştırma / değer yazma onay ister (CLI `--onayli`); değeri ASLA okunmaz (doğrulama için bile); metin
  günlüğe, hata iletisine, onay isteğine yazılmaz (yalnız uzunluk), `--gizli` verilmemiş olsa bile kendiliğinden gizlidir.
- **Oturum kilidi** (kde): `org.freedesktop.ScreenSaver.GetActive` (yoksa logind `LockedHint`) kilitli ya da okunamıyorsa
  kullanıcının ekranına hiçbir girdi gitmez (15, "oturum kilitli"; kapalı-başarısız; `--ekranimda` aşmaz): kilit ekranına
  yanlışlıkla giden yazı parola denemesi sayılır ve hesabı kilitleyebilir. Durum 0,5 sn önbellekte; sanal masaüstünde yok.
- **Onay verilen hedef değişmesin**: hassas tık panelden onaylandıysa tıklamadan HEMEN önce noktadaki yazı yeniden OCR'lanıp
  onay isteğindeki yazıyla bulanık karşılaştırılır (benzerlik < 0,85 → tık yapılmaz, 10 "onay verilen hedef değişti").
  Ağaç ögesine tıkta (`click-element`, web ögesi dahil) öge ayrıca ağaçtan yeniden bulunur (`erisim._onay_sonrasi_oge`):
  adı, rolü, merkezi (±3 px; web'de veri yolu adı + nesne yolu) aynı değilse ya da yoksa 10. Onay anında noktada OCR
  yazısı yoksa (yazısız simge / `aria-label` düğmesi: öge adı OCR'da görünmez) nokta karşılaştırması "şimdi de yazı yok"
  olur; kimlik ağaçtan doğrulanmıştır. Web erişilebilirlik eyleminde (`via="action"`) aynı öge denetimi eylemden önce.
- **Sürükleme bitişi** başlangıç gibi denetlenir: tek onay iki noktanın yazısını taşır; ara hareketlerde gözcü (etkin
  pencere + başlık kilidi); bırakmadan hemen önce bitiş noktasının altındaki pencere (yasak / kendi istemci / onaysız
  sistem istemi / başka uygulama) — uymazsa imleç başlangıca götürülüp bırakılır (sürükleme iptal).
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
- **Riskli komut başlatma.** `ac --komut` ham komut satırı `guvenlik.riskli_komut`'tan geçer: yıkıcı kalıpta insan
  onayı (CLI'de `--onayli`, gözetimsiz kipte geçmez), red → 10 ve hiçbir şey başlatılmaz. `ac --komut` kabuğu olan
  kullanıcı/ajan içindir; MCP yüzeyi bu yola HİÇ ulaşmaz.
- **MCP uygulama başlatma (`open_app`).** Kabuğu OLMAYAN bir MCP ajanı kod çalıştıramamalı (`uygulama.mcp_uygulama`,
  tek giriş noktası; `api.uygulama_komutu` → `gio launch GIRDI.desktop [belgeler…]`): `app` yalnız kurulu bir
  masaüstü girdisi (`uygulama_bul`); `/` içeren ad (yol/komut) → 10. Girdi reddedilir (10): Exec'in program konumunda
  (geçirgen sarmalayıcılar nice/prime-run/gamemoderun… atlanarak) ya da herhangi bir öğesinde yol/yalın ad olarak
  yorumlayıcı, kabuk, sarmalayıcı (`env setsid nohup systemd-run flatpak-spawn xargs`…), yetki yükseltici, başlatıcı
  (`xdg-open gio kioclient`…), `deskhand`/`ekran`, uçbirim öykünücüsü (`guvenlik.ucbirim_mi` + ek liste) varsa;
  `Terminal=true`, `Categories=…TerminalEmulator`; Flatpak'ta `run` dışı alt komut, uçbirim kimliği ya da yasak
  `--command`; alt komut/seçenekle başka program çalıştıranlar (`git -c`, `flock -c`, `tmux`, `screen`, `setpriv`,
  `script`, `expect`…); Exec öğesinde kabuk metakarakteri (`; | & $ \` < >`), `!`/`=!` ile başlayan ya da boşluklu
  komut metni (var olan yol değilse) ve `--` sonrasında bir program. **İzin listesi:** kara listeden geçen girdi
  ONAYSIZ yalnız şu koşulda başlar: dosya `SISTEM_UYGULAMA_DIZINLERI`'nde (`/usr/share/applications`,
  `/usr/local/share/applications`, `/var/lib/flatpak/exports/share/applications`) ve kendisi + tüm üst dizinleri
  (sembolik bağlar çözülerek) root sahipli, grup/diğerleri yazamaz; Exec'teki her program (geçirgen sarmalayıcılar
  dahil, PATH ile çözülüp `os.stat`) root sahipli, yazılamaz, çalıştırılabilir bir ELF ikilisi ya da aynı koşuldaki
  bir `#!` betik (sistemin kurduğu sarmalayıcılar: libreoffice, steam, vivaldi…) — betiğin yorumlayıcısı (mutlak yol)
  ve `#!/usr/bin/env PROG` ise PROG da root sahipli, yazılamaz ELF olmalı; env'e seçenek (`-S`) ya da atama verilemez.
  Kara liste aynen geçerlidir (Exec'in kendisi `bash`/`ldd`/… ise 10). Aksi halde (kullanıcı dizini
  `~/.local/share/applications`, kullanıcı Flatpak'ı, kullanıcıya ait program ya da yorumlayıcı, PATH'te önce gelen
  kullanıcı dosyası) panelden insan onayı istenir (`guvenlik._panelden_onay`; bir
  eylem = bir onay; gözetimsiz kipte/panel kapalıyken/redde 10, tur "hassas"); onay isteği girdi yolunu ve Exec'i
  gösterir; izinde girdi bir kez okunup onaylanan Exec ile aynı olduğu doğrulanır ve `RUNTIME_DIR/uygulama/` altındaki
  0600 kopyasından başlatılır (onaydan sonra dosyayı değiştirmek işe yaramaz). Argümanlar yalnız belge: http/https URL'si (sorgudaki `=` serbest), yerel `file://` URL'si ya da var
  olan dosya/klasörün MUTLAK yolu; `-` ile başlayan, `=` içeren (URL dışı), başka şemalı, denetim karakterli,
  çalıştırılabilir dosya ya da `.desktop` gösteren argüman → 10 (en çok 16). Başlatılan sürecin ortamına ajan
  değişken veremez (yalnız oturum politikasının `env_ek`'i). Görünmez masaüstünde oturum köprüsü yoksa hiçbir
  uygulama başlatılmaz (10). **Kod barındıran uygulamalar** (`uygulama.KOD_BARINDIRAN`, tek sabit liste; .desktop
  kimliğinin parçaları, Exec programları ve Flatpak kimliği sürüm ekleri atılarak karşılaştırılır: lutris,
  protontricks, winetricks, wine, steam, heroic, gameconqueror/scanmem, libreoffice, gimp, blender, krita, inkscape,
  godot, IDE'ler (code/codium/kdevelop/qtcreator/JetBrains…), jupyter, IDLE, obs, darktable…) sistem girdisi olsalar
  da insan onayı ister (belgeyi kod olarak işler ya da arayüzünden kod çalıştırır). Belge argümanında yürütülebilir
  türler (`YURUTULEBILIR_TURLER`: .bat .cmd .exe .msi .ps1 .py .sh .bash .lua .pl .rb .js .jar .AppImage .desktop
  .yml/.yaml .docm .xlsm .pptm …; yol ve file:// URL'si) her uygulama için 10. Onaylı kullanıcı girdisinde Exec
  programı kullanıcıya aitse içeriğinin sha256'sı onay anında alınır ve başlatmadan hemen önce (`api.uygulama_ac` →
  `uygulama.onayli_program_denetle`) karşılaştırılır; değiştiyse 10. **Sınır:** MCP-yalnız ajan kod çalıştıramaz;
  GUI betik konsolları (makro düzenleyici, Python konsolu, IDE uçbirimi) yalnız insanın onayladığı uygulamaların
  içindedir. Gömülü uçbirimli uygulamalar (dosya yöneticisi, kate) onaysız açılır; uçbirim panellerine yazı Enter
  kuralıyla korunur.
- **Ayar dosyaları: panel yetkili kaynak** (`liste_koruma.py`). Yasak listesi ve seviye dosyası ajanın kendi
  araçlarıyla (uçbirimde `rm`, dosya yöneticisinde silme, düzenleyicide boşaltma) kaldırılamaz: panel açılışta iki
  dosyayı okuyup BELLEKTE tutar; dosyayı yalnız kendi Kaydet'i yazar; dosya dışarıdan değişir ya da silinirse
  (QFileSystemWatcher + 2 sn yoklama) panel kendi içeriğini korur, dosyayı geri yazar ve uyarır (günlük satırı +
  tepsi bildirimi). Panel her yazışta `STATE_DIR/liste-<tur>.isaret` {sha256, icerik} bırakır; açılırken dosya
  işaretle uyuşmuyorsa işaretteki kayıt geri yüklenir. CLI ve MCP listeleri onay kanalından alır (`liste
  yasak|seviye` → `icerik <n>` + metin | `yok`; kanal doğrulaması §8 ile aynı; istemci 0,3 sn önbellek). Panel
  kapalıysa dosyadan okunur; işaret VAR ama dosya yok ya da işaretle uyuşmuyorsa Dur 10 ("Deskhand ayar dosyası kayıp
  ya da panel dışında değişti; … paneli açın"), hiçbir girdi gönderilmez. İşaret yoksa (ilk kurulum) eski davranış.
  Dosyayı elle düzenlemek desteklenmez: değişiklikler panelin Ayarlar'ından yapılır. Aynı panel yetkili desen
  `ayarlar.toml`'daki iki gevşetici ayara da uygulanır: onay kapsamı (`liste onaylar`) ve hesap oturumları
  (`liste kimlik`; aşağıda "Onay kapsamı" ve "Hesap oturumları").
- **Bekleyen onay = girdi yok (MCP).** Bir masaüstünde (kde/sanal) insan onayı beklenirken O masaüstüne giden her
  girdi aracı (click, type_text, press_key, scroll, drag, manage_window, clipboard write, run_flow, open_app) kilidi
  alır almaz beklemeden `[7] onay bekleniyor` ile reddedilir (`mcp_sunucu.kilitli(girdi=True)`); kayıt kilit
  bırakılmadan önce açılır, onaydan sonra kilit yeniden alındıktan sonra kapanır. Başka canlı Deskhand süreçlerinin
  aynı masaüstündeki istekleri de sayılır (`onay.bekleyen_var`; ömrü olağandışı uzun sahte istek sayılmaz). Okuma
  araçları ve DUR her zaman serbest. Aynı kapı CLI/akış girdisinde de vardır: `eylem.girdi_al` (her fare/klavye yolu)
  ve erişilebilirlik eylem yolunun korumaları (`erisim._atspi_korumalari`, web eylemi dahil) BAŞKA bir canlı Deskhand
  sürecinin o masaüstü için bekleyen onayında 7 verir (sürecin kendi istekleri sayılmaz). `bekleyen_var` masaüstünü
  "ekran"/"arka" ya da arka uç adıyla ("kde"/"sanal") alır.
- **Gözetimsiz kip.** `DESKHAND_GOZETIMSIZ=1` ya da genel bayrak `--unattended` (`--gozetimsiz`): onay gerektiren her
  eylem panel diyaloğu açılmadan ve beklemeden reddedilir (10, "gözetimsiz çalışmada hassas eylem yapılmaz"). Tek nokta
  `onay.iste_sonuc` (CLI, MCP, akış hepsi oradan geçer). Sohbet/insan olmadığından `--onayli` de geçersiz sayılır
  (`guvenlik.onayli_gecerli`). Zamanlanmış akışlar için.
- Başlık (`-b`) ve sınıf (`-s`) kilidi her girdiden hemen önce (4).
- DUR anahtarı: `DESKHAND_RUNTIME_DIR/dur` varsa her girdi çağrısından önce Dur(13); basılı her şey bırakılır.
  DUR AÇMAK serbesttir (`deskhand dur`, arayüz/tepsi/kısayol). Kaldırmak yalnız kullanıcının kararıdır: `deskhand devam`
  (`guvenlik.dur_kaldir_iste`) panele sorar ("DUR kaldırılsın mı?", varsayılan Hayır); panel kapalı / gözetimsiz kip /
  Hayır → Dur 13; komut satırı `--approved` yanıt sayılmaz. İletiler ajana kaldırma yolunu tarif etmez. Kullanıcının panelde
  koyduğu DUR panelin Devam'ı olmadan kaybolursa (bir süreç dosyayı sildi) görünür uyarıyla geri konur
  (`gui/panel._dur_koru`). Kapsam dışı: panel kapalıyken dosyayı silen süreç.
  `guvenlik.dur_ac(kaynak)` / `dur_kapat(kaynak)` / `dur_kaynagi()`: dur dosyasının ilk sözcüğü `kullanici` ya da `cli`'dir.
- Girdi merkezi (§2) istemci denetimlerine EK güvenceler verir: soket 0600 / dizin 0700 ve SO_PEERCRED ile yalnız
  aynı kullanıcı (istemci de sunucunun kullanıcısını ve soket iznini denetler); her partiden hemen önce DUR anahtarı
  (açıksa basma satırları 13 ile reddedilir, `keyup`/`buttonup` ve gecikme ayarları geçer); yalnız dotool dilinin
  bilinen fiilleri. Bağlantı başına basılı tuş/düğme izlenir: bağlantı kopunca (istemci öldü, SIGKILL) basılı kalanlar
  bırakılır (başka bağlantının da tuttuğu tuş hariç); kopan bağlantının girdisi kuyrukta sürüyorsa dotool yeniden
  başlatılır (denetimsiz girdi sürmez). DUR açılınca tüm bağlantıların basılıları bırakılır, kuyrukta girdi varsa
  dotool yeniden başlatılır (kuyruk düşer). Panel ölürse dotool'un girişi kapanır, dotool çıkar, aygıt yok olur.
- İnsan önceliği (12): kde arka ucunda kullanıcı klavye/fareyi kullanıyorsa; sanalda (iki tür) yalnız "Devral" açıkken.
  Paneldeki Devral iki türde de çalışır (önizleme `goruntu()`, girdi `Girdi.insan_ham`; KWin türünde EIS üzerinden).
- Pencere yönetimi, pencere kapatma ve (kde) pano yazma da insan önceliğine (12) uyar (`guvenlik.insan_onceligi`;
  pano: CLI `pano yaz` ve MCP `clipboard(write)` → `api.pano_yaz`); kapatma DUR'a (13) bakar. Deskhand'in panoya yazdığı
  metinlerin özeti TEK kaynaktadır (`guvenlik.kendi_pano_ekle/kendi_pano_mu`): CLI, MCP `clipboard(read)` ve yapıştırma
  onayı aynı listeye bakar.
- Kullanıcı meşgulken ön plan yok (15): kde arka ucu girdi, pencere öne getirme ve uygulama açmadan önce
  `mesgul.ekran_korumasi()` çağırır. Etkin pencere tam ekran / oyun biçimli ya da MPRIS'te video çalıyorsa
  Dur(15). İstisna yalnız kullanıcının açık izni (`--ekranimda`, `DESKHAND_EKRANIMDA=1` ya da bildirimdeki
  "Ekranımda yap" düğmesi → 10 dk). Sanal masaüstü etkilenmez.
- **AT-SPI çerçevesi yalnız hedef pencerenin PID'inden** seçilir; tam PID eşleşmesi yoksa YALNIZ pencere sürecinin
  TORUNLARINDAN, aynı çalıştırılabilir dosyaya sahip ve başlığı ≥ 0,9 benzeyen çerçeve (çok süreçli uygulama). ATALAR asla
  (pencerenin sahibini başlatan başka uygulamanın çerçevesine eylem gitmesin);
  bulunamazsa ya da PID bilinmiyorsa Dur 6 — başka uygulamanın çerçevesine başlık benzerliğiyle düşülmez. Seçilen
  çerçevenin kendi kimliği de denetlenir: Deskhand paneli/onay diyaloğu sürecine ait çerçeve her zaman 10 (okuma dahil),
  yasak desen (uygulama adı/çerçeve adı) 10; eylem/değer yazmada ajanın kendi istemcisi ve uygulama erişim seviyesi.
  Ağaç taramasında çerçevenin kimliği (veri yolu adı + nesne yolu, BİRLİKTE) saklanır; eylemde başka nesneyse Dur 8.
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
- **Durum kaydı güvenilmez (iki tür).** Kayıttan YALNIZ tür + kimlik/ekran numarası alınır; bütün yollar ve
  adresler çalışma dizininden KURULUR (`kwin_oturum.guvenli_kayit`, `masaustu.guvenli_kayit`; `masaustu.durum()` bunu
  uygular): KWin `RUNTIME_DIR/kwin-<8 hex>` (sembolik bağ değil, kullanıcının, 0700) → `unix:path=<dizin>/bus`,
  `<dizin>/deskhand-<kimlik>`, Xauthority, XWayland `:120+`; Xvfb `RUNTIME_DIR/sanal-<no>`. Veri yolu adresinin katı
  biçimi `unix:path=/yol[,guid=<32 hex>]` (Python `arka_ortak.bus_yolu_kati`, C `adres_coz`): `;` ile çoklu adres
  (sd-bus/libdbus ilki olmazsa SONRAKİNE geçer) reddedilir. RUNTIME_DIR var olan dizinse sahibi kullanıcı, sembolik bağ
  değil ve 0700 olmalı; gevşek izinli dizin sessizce sıkılaştırılMAZ (arada başkası dosya/soket bırakmış olabilir):
  Dur 14, `deskhand doctor` "Çalışma dizini" satırında nedeni ve `chmod 700` önerisini gösterir.
- **Karşı taraf doğrulaması (sert bağ / yer değiştirme).** Bağlanmadan önce (`kwin_oturum.baglanti_denetle`,
  `masaustu.xvfb_karsi_denetle`): oturum soketlerinin SO_PEERCRED PID'i kayıttaki süreç (başlangıç zamanı aynı) —
  veri yolu için dbus-daemon (komut satırında `--config-file=<dizin>/bus.conf`), Wayland için KWin, X için Xvfb;
  soketin (st_dev, st_ino)'su kullanıcının gerçek soketlerinden biriyse ret. `deskhand-eis` bağlandıktan sonra aynısını
  kendisi yapar (`--dbus-pid` + bus.conf; yoksa `hata bus-karsi`, çıkış 2).
- **KWin türü kapıları.** `kwin_oturum.guvenlik_kapilari` (süreç başlamadan): veri yolu adresi kullanıcının gerçek
  adresi (aynı inode dahil), Wayland soket adı kullanıcınınki, yapılandırma dizini gerçek `~/.config`, HOME/çalışma
  dizini gerçek, XWayland ekranı gerçek `DISPLAY` ise Dur 14. `arka_uc/kwin.py` HER bağlantıdan önce
  `baglanti_denetle`'nin döndürdüğü GÜVENLİ kaydı kullanır; `deskhand-eis` yalnız `--bus <özel adres>` ile bağlanır,
  ortamdan devralmaz. KWin `env -i` eşdeğeri asgari ortamla, geçici HOME/XDG_*_HOME ile açılır (KWin kendi kwinrc /
  kwinoutputconfig.json / kglobalshortcutsrc / kxkbrc dosyalarını buraya yazar); KDE_FULL_SESSION/KDE_SESSION_VERSION
  KWin'e verilmez.
- **Uygulama ad alanı (iki tür, TEK başlatma yolu: `arka_ortak.korumali_baslat` → `korumali_argv`).** Arka plan
  uygulaması (KWin/Xvfb, dbus-daemon ve Deskhand'in kendi yardımcıları DIŞINDAKİ her şey: `ac --arka`, `open_app`, oturum
  köprüsü komutları) `bwrap` ile başlar (denetim 12c sonrası model):
  - **Ayrı kullanıcı + PID ad alanı** (`--unshare-user --unshare-pid`, kendi `/proc`): kullanıcının başka süreçleri
    (gerçek KWin, oyun, terminal) görünmez; onlara sinyal, ptrace, `/proc/<pid>/root|environ|mem` erişimi yok (ESRCH).
  - **Kök salt okunur** (`--ro-bind / /`); `/dev` bwrap'in asgari /dev'i (`null`, `zero`, `random`, `tty`, `pts`, `shm`…)
    + yalnız `/dev/dri` (GPU; WebGL/GL donanımda). `/dev/uinput` (sanal klavye/fare), `/dev/input/event*` (tuş kaydı),
    `/dev/snd` (doğrudan ALSA mikrofon/hoparlör), `hidraw`, `/dev/bus/usb`, kamera düğümleri YOK. `/dev/udmabuf`
    verilmez (KWin kafes dışında zaten).
  - **Boş tmpfs:** `/tmp` (kullanıcının /tmp'deki Steam/Chromium SingletonSocket'ları, `.ICE-unix` ksmserver, Kulak Kesil
    soketleri, başka X soketleri görünmez), `/run/user/<UID>` (Wayland, D-Bus, pipewire/pulse, kwallet, gnupg, ssh,
    xauth, at-spi, portal, systemd soketleri) ve (başka yerdeyse) Deskhand'in RUNTIME_DIR'i (girdi.sock, sanal.json,
    diğer oturumlar).
  - **Ev dizini BOŞ tmpfs + BEYAZ LİSTE** (`arka_ortak.ev_baglari`, `EV_BEYAZ_LISTE`; 0700, `--size` = min(2 GiB, kafes belleği/4), kafes varsayılanı 6G → 1,5 GiB; ad alanındaki `/tmp` de aynı sınırla): gerçek
    ev dizininden YALNIZ masaüstü/araç takımı görünümü SALT OKUNUR görünür — `~/.config/kdeglobals`, `kdedefaults/`,
    `kcminputrc`, `kcmfonts`, `Trolltech.conf`, `plasma-localerc`, `breezerc`, `Kvantum`, `qt5ct`/`qt6ct`, `gtk-3.0`,
    `gtk-4.0`, `gtkrc`, `gtkrc-2.0`, `~/.gtkrc-2.0`, `xsettingsd`, `fontconfig`, `~/.local/share/fonts`, `~/.fonts`,
    `~/.cache/fontconfig`, `~/.icons`, `~/.local/share/icons`, `~/.themes`, `~/.local/share/themes`,
    `~/.local/share/color-schemes`, `user-dirs.dirs`, `user-dirs.locale`, `mimeapps.list`, `~/.local/share/mime`,
    `~/.local/share/applications` ve `~/.local/share/flatpak` (kullanıcı .desktop girdileri ve Flatpak kurulumu). Hiçbir
    uygulamanın KENDİ ayarı/verisi (jeton, oturum, geçmiş) görünmez: listede olmayan HER gizli dosya ve ev kökündeki
    veri klasörü olmayan her dizin/dosya ad alanında YOKTUR (ölçüldü: `.config/<rastgele>/token`, `.netrc`,
    `.git-credentials`, `gh/hosts.yml`, `.docker`, `.kube`, `.pypirc`, `.local/share/<bilinmeyen>`, `.cache/<uyg>`,
    `~/projeler/.env`, `~/notlar.txt` okunamıyor; `tests/test_ev_beyaz_liste.py`). Sembolik bağ olan beyaz liste
    girdisi HEDEFİNDEN bağlanır; hedefi ev dizininin kendisi/üstü ya da bir SIR_YOLLARI yolu olan girdi reddedilir.
    Sembolik bağ kuralları (`_beyaz_ham`): kaynak (realpath) bir XDG veri klasörünün içinde/kendisi/üstü ise RET (veri
    klasörü yazılabilir bağlanır: ad alanındaki uygulama orada `-> ~/.config` bağı kurup sonraki başlatmalarda tüm
    yapılandırmayı açtırabilirdi); kaynak ev DIŞINDA ve `/tmp`, `/run/user/UID` ya da RUNTIME_DIR altındaysa RET; beyaz
    liste girdisinin kaynağı ev içinde ve sözcüksel yoldan farklıysa YALNIZ kaynak beyaz listedeki (bağ olmayan) bir
    girdinin altındaysa kabul (dotfiles yöneticisi bağları `~/dotfiles/...` reddedilir; gerekirse politika `ev`); politika
    `ev` girdisi için yalnız ilk iki kural. İkinci hat (SIR_YOLLARI) kaynak→hedef eşlemesiyle de örter (kaynağın içindeki
    sır `hedef + göreli yol`'da). Politika `ev` girdisi ayrıca `gecerli_politika_ev_girdisi` ile süzülür: glob karakteri,
    derinliği 2'den az gizli girdi (`.ssh`, `.netrc`…) ve merkezlerin kendisi (`.config`, `.local`, `.local/share`,
    `.local/state`, `.cache`, `.var`) RET. İnce örtüler (SIR_YOLLARI): `.local/share/flatpak/overrides` (boş dizin),
    `.config/gtk-3.0/bookmarks` ve `servers` (/dev/null); `flatpak/repo/config` BİLEREK örtülmez (ölçüldü: /dev/null örtüsü
    `flatpak --user` kurulumunu bozar). TOCTOU: kaynaklar `O_PATH|O_NOFOLLOW` fd'si olarak açılır, `(dev,ino)` ve
    `/proc/self/fd` yolu denetlenir, bwrap `--ro-bind-fd` ile bağlar (fd'ler `pass_fds` ile geçer, uygulamaya sızmaz); bwrap
    bunu bilmiyorsa çözülmüş gerçek yol `--ro-bind` edilir ve denetim-bağlama arasındaki yarış kalır (yalnız ev sahibinin
    kendi hesabının yazabildiği yollarda). Paket/`sys.prefix` bağları veri klasörlerinden SONRA eklenir, bir `.git`
    deposunun KÖKÜ olan yol reddedilir. Teşhis: çözülmüş exec (`gio launch` için .desktop Exec'i) ev altında ama ad
    alanında görünmüyorsa `korumali_baslat` HEMEN `Dur(9)` verir (iletide `oturum.toml` `[uygulama.<ad>] ev = [...]`
    ipucu; MCP `open_app` ve CLI `ac` aynı kapıdan geçer).
    CLI `ac --background` MCP `open_app` gibi görünmez masaüstü kapalıysa onu kendiliğinden başlatır (`masaustu_baslat`:
    aynı kafes, kilit ve görev kipi kapısı) ve oturum kopyası hazırlanmadan ÖNCE denetler (boşa kopya yok).
    `ac APP [ADRES]` / `--url`: adres `uygulama.web_adresi_denetle`'den geçer (yalnız http/https, boşluk/denetim
    karakteri/`-` yok; `file:`, `about:`, `javascript:`, `data:` → 10), politikanın komutunun SONUNA tek argüman olarak
    eklenir (http(s):// ile başladığından seçenek konumunda olamaz; Chromium'da erişilebilirlik bayrağı adresten önce
    gelir); `--komut` ile birlikte verilemez; görev kipinde `open_app_denetle` ve ham komut yasağı CLI'de de geçerlidir.
    Uygulamanın yazdıkları (`~/.config/autostart`, `~/.bashrc`, `~/.config/systemd/user`, `~/.local/bin`, kendi
    ayarı, önbelleği…) oturumla ATILIR → kalıcılık kaçışı yok. Bir uygulamanın kendi ayarı gerekiyorsa oturum
    politikasında uygulama başına `ev = [...]` (ev dizinine göreli; salt okunur; VARSAYILAN hiçbir uygulamada YOK;
    `_varsayilan`daki `ev` bilinmeyen uygulamalara verilmez; `..`/mutlak yol atılır; SIR_YOLLARI'nı açamaz):
    `Hazirlik.ev` → `baslat(..., ev=)` → `korumali_argv(ev_ek=)`. Seçim ölçümü (0.6.1 sonrası; sahte ev, KWin
    türü; 0 = boş ev, A = beyaz liste, B = katman + genişletilmiş kara liste, C = katman + bilinmeyen gizli dizinleri
    örtme): KWrite, Dolphin, Konsole, Gwenview, Firefox, Chromium, zenity, Meld, Electron A'da açılıyor; KDE
    uygulamaları kullanıcının teması/yazı tipiyle (koyu temada ortalama parlaklık A = B = C, beyaz listesiz 0'da açık
    tema), OCR doğruluğu B/C ile aynı; B ve C listelenmemiş sırları sızdırdı, A sızdırmadı. Yazılabilir GERÇEK bağlar
    yalnız: kullanıcının XDG veri klasörleri
    (`~/.config/user-dirs.dirs`; yalnız ev dizininin İÇİNDE, ev kökü değil, yolunda nokta ile başlayan bileşen yok — ev
    kökünü, gizli dizini, `/`'ı ya da dışarıyı gösteren girdi yok sayılır) ve uygulamanın kendi oturum kopyası. Veri
    klasörlerinin İÇİNDEKİ var olan gizli dizin/dosyalar (`.git` — hooks/config, `.vscode`, `.envrc`, `.venv`…;
    derinlik 6, en dıştakiler) salt okunur örtülür; bu sayı 3000'i aşan klasör bütünüyle salt okunur bağlanır. Ev
    dizinindeki (derinlik 4) ve veri klasörlerindeki soket/FIFO'lar + bilinenler (`~/.steam/steam.pipe`) `/dev/null` ile
    maskelenir (ölçüldü: katman üstünden gerçek sokete/FIFO'ya zaten bağlanılamıyor; maske ikinci hat).
  - **Sır yolları OKUNAMAZ** (`arka_ortak.SIR_YOLLARI`, tek sabit liste; glob olabilir): `~/.ssh`, `~/.gnupg`,
    `~/.local/share/keyrings`, `~/.local/share/kwalletd`, `~/.password-store`, gerçek Firefox profilleri
    (`~/.config/mozilla`, `~/.mozilla`), Chromium ailesi profil kökleri (`~/.config/chromium`, `google-chrome*`,
    `vivaldi*`, `BraveSoftware`, `microsoft-edge*`), ajan/bulut/depo kimlik bilgileri (`~/.claude`, `~/.claude.json`,
    `~/.config/gh`, `~/.git-credentials`, `~/.netrc`, `~/.aws`, `~/.docker/config.json`, `~/.config/rclone`, `~/.kube`),
    Deskhand'in kendi ayar/günlüğü (`~/.config/deskhand`, `~/.local/state/deskhand`), Flatpak uygulama verileri
    (`~/.var/app`), mesajlaşma oturumları (`~/.local/share/TelegramDesktop`, `~/.config/discord*`, `Signal`,
    `Element*`, `Slack`, `WhatsApp*`, `teams*`, `Mattermost`), oyun platformu jetonları (`~/.steam/steam/config`,
    `~/.local/share/Steam/config`, `ssfn*`, `~/.config/heroic`, `~/.config/lutris`), KDE Connect eşleşme anahtarları,
    qBittorrent (WebUI parolası; Flatpak'i de), Syncthing anahtarları, OBS yayın anahtarı
    (`~/.config/obs-studio/basic/profiles`), RustDesk, Thunderbird, FileZilla, Remmina, paket deposu jetonları
    (`~/.npmrc`, `~/.pypirc`, `~/.cargo/credentials*`) ve kabuk geçmişleri. Örtülen bir dizinin içindeki ayrıca
    listelenmiş yol tekrar bağlanmaz. Dizin → boş tmpfs (uygulama yazabilir, atılır), dosya → `/dev/null`; sembolik bağsa (ör.
    profile-sync-daemon) HEDEFİ örtülür (hedef ad alanında zaten boş olan /run/user ya da /tmp'deyse gerek yok). Örtü
    veri klasörü bağlarından SONRA, oturum kopyası ondan da SONRA bağlanır: arka plan Firefox'u kendi kopyasıyla
    (`--profile <kopya>`, `XDG_CONFIG_HOME=<kopya>/.xdg-config`), Flatpak Electron kopyası `--filesystem=<kopya>` + XDG_*
    ile çalışır (ölçüldü: Firefox iki türde açılıyor/indiriyor; Flatpak çalışma zamanı ad alanında açılıyor).
  - **Geri bağlananlar** yalnız oturumun kendi yolları (`uygulama_baglari`: kendi runtime dizini, özel veri yolu ve
    Wayland soketi, erişilebilirlik veri yolu, kendi X soketi + Xauthority salt okunur) ve oturum kopyalarından YALNIZ
    politikanın bu uygulamaya verdiği kopya (`Hazirlik.kopya_yolu` → `baslat(..., kopya=)` → `arka_ortak.kopya_bagi`:
    kopya kökünün doğrudan alt dizini olmalı, değilse Dur 14). Kopya komut satırından/ortamdan ÇIKARILMAZ: komutta
    başka kopyanın yolu geçse de o kopya görünmez. MCP `open_app`'in onaylı kullanıcı girdisi (izin listesi dışı .desktop)
    `gio launch <RUNTIME_DIR/uygulama/özel kopya>` ile başlar: o TEK dosya salt okunur bağlanır (`baslat(...,
    girdi=)` → `arka_ortak.girdi_kopyasi_bagi`: o dizinin doğrudan çocuğu, kullanıcıya ait düz `.desktop`, değilse
    Dur 14); aynı dizindeki başka kopyalar görünmez. Sıra: `open_app` izin listesi + KOD_BARINDIRAN onayı + belge
    argümanı kuralları (`uygulama.mcp_uygulama`) → onaylı programın özet denetimi (`onayli_program_denetle`) → bu
    yalıtımlı başlatma (TEK yol: `masaustu.baslat` → `korumali_baslat`).
  - Uygulamanın `PATH`'i ve `LD_PRELOAD/LD_LIBRARY_PATH/LD_AUDIT`'i yalnız son komuta (`--setenv`) gider; yardımcı zincir
    (sh, nice, ionice, bwrap) güvenli PATH ile ve mutlak yollarla çalışır (aşağıda "Güvenli yardımcı ikililer").
  - `--new-session` (TIOCSTI yok). `--die-with-parent` YOK (masaüstü CLI'den uzun yaşar); kafes ve PID temizliği aynen;
    ad alanının ilk süreci ölünce çekirdek içindekilerin hepsini öldürür. bwrap yoksa ya da güvenli yolda değilse
    uygulama başlatılmaz (Dur 9).
  - **Flatpak:** `flatpak run` ad alanında çalışır (iç içe bwrap; ölçüldü) ama kullanıcının systemd kullanıcı
    yöneticisine giden veri yolu olmadığından kendi scope'una GEÇEMEZ: örnek masaüstünün bellek kafesinde ve PID ad
    alanında kalır, masaüstü kapanınca kapanır (ölçüldü). Sarmalayıcı (`oturum/flatpak_ornek.py`) ad alanında bunu
    doğrular ve ana makine kaydını yazmaz (`DESKHAND_AD_ALANI=1`); örnek kafesten çıkmışsa kapatır. Flatpak'in yazdıkları
    (`~/.var/app`) boş ev tmpfs'inde kalır (atılır); kullanıcı kurulumu (`~/.local/share/flatpak`) salt okunur.
  - **Ölçüldü:** Firefox (boş geçici profil + oturum kopyası benzeri kopya) iki türde açılıyor, sayfa yüklüyor, WebGL
    KWin türünde donanımda (tümleşik GPU), erişilebilirlik ağacı sunuyor; Qt test penceresi; tık/yazı süreleri
    değişmedi. Ayrıntı `tests/test_denetim12c.py`. İndirme: oturum KOPYASI Firefox'u kendi `XDG_CONFIG_HOME`'uyla
    (`<kopya>/.xdg-config`) çalışır; oraya kullanıcının `user-dirs.dirs`/`user-dirs.locale`/`mimeapps.list` ve
    GTK/fontconfig görünümü (0600) kopyalanır ve user.js `browser.download.dir` = XDG İndirilenler (görev kipinde görev
    klasörü) yazar. 0.9.0'dan önce bu dosyalar yoktu ve indirmeler ad alanının geçici `~/Downloads`'ına gidip tarayıcı
    kapanınca kayboluyordu (gerçek olay; ad alanında GLib sınaması `tests/test_oturum_tamir.py`).
  - **Arka planda görünmeyenler:** `/tmp` (boş tmpfs: `/tmp/claude-*`, scratchpad dahil), XDG dışı ev klasörleri ve
    kullanıcı `~/Downloads` (XDG adı başkaysa) uygulamaya GÖRÜNMEZ. Dosya seçiciye/yüklemeye verilecek dosyayı
    `~/İndirilenler` gibi bir XDG klasörüne koyun ve tam yolu dosya iletişim kutusunda Ctrl+L ile yazın.
  - **Önbellek:** kopyalar RUNTIME_DIR'da (bellek) durur; Firefox disk önbelleği 64 MB (user.js
    `browser.cache.disk.capacity`), Chromium `--disk-cache-size`. Canlı kopyalar sayı/boyut sınırını aşınca silinmez,
    açıklamaya uyarı eklenir.

  **Neyi korumaz (bilerek / kalan riskler):**
  - **Okuma:** uygulama XDG veri klasörlerini (belgeler, indirilenler, masaüstü…) ve beyaz listedeki görünüm
    ayarlarını OKUYABİLİR; veri klasörlerine konmuş sırlar (ör. `~/Masaüstü/parolalar.txt`) açıktır. Ev dizininin geri
    kalanı (her uygulamanın ayar/oturum dosyası, ev kökündeki diğer dizinler) görünmez. Bedeli: ev dizinindeki
    programlar (`~/.local/bin` betikleri, `~/Games`, `~/Applications` AppImage'ları) ve uygulamanın kendi ayarları
    (Dolphin yer imleri, Kate oturumları, Konsole profilleri) arka planda YOK — gerekiyorsa politikada uygulama başına
    `ev`. Hangi uygulamanın arka planda açılacağı oturum politikasının (kopya/bekle/kapali/on) işidir.
  - **Veri klasörleri yazılabilir:** uygulama `~/İndirilenler`, `~/Belgeler`, `~/Projeler`… içindeki NORMAL dosyaları
    değiştirebilir/silebilir; YENİ gizli girdi oluşturabilir (ör. `.git`'i olmayan bir alt dizinde yeni `.git/` ya da
    `.envrc`: kullanıcı o dizinde git/direnv çalıştırırsa yalıtım dışında kod çalışabilir) ve `Makefile`, `*.desktop`
    (Masaüstü klasöründe kullanıcının masaüstünde görünür) gibi kullanıcının sonradan çalıştırabileceği dosyalar
    yazabilir. Var olan gizli girdiler salt okunurdur; açılıştan sonra oluşan yeni gizli girdiler ve derinlik 6'dan
    aşağısı örtülmez.
  - **Ağ:** ağ ad alanı paylaşılır (tarayıcı ağa çıkabilsin; `--unshare-net` yok): uygulama yerel ağ hizmetlerine
    (127.0.0.1'deki portlar: ör. qBittorrent WebUI, geliştirme sunucuları) ve SOYUT (abstract) unix soketlerine
    bağlanabilir. Bu makinede soyut soketler yalnız ICE ve X (`:0`, anahtarlı: Xauthority görünmediğinden bağlantı
    REDDEDİLİR, ölçüldü) olarak bulundu; ICE (ksmserver) soyut soketi ICE kimlik doğrulaması ister.
  - **IPC ad alanı paylaşılır** (X MIT-SHM için): SysV paylaşımlı bellek/semafor/ileti kuyrukları aynı kullanıcının
    diğer süreçleriyle ortak.
  - `/dev/dri` (GPU) açık: GPU sürücüsü saldırı yüzeyi.
  - Açılıştan SONRA veri klasörlerinde ya da beyaz listedeki dizinlerde oluşan soket/FIFO'lar maskelenmez (gerçek dizin
    olduğundan bağlanılabilir); ev dizininin geri kalanı ad alanında hiç yoktur.
- **Ses (iki tür).** Arka plan uygulamaları kullanıcının ses sunucusuna (pipewire/pulse) HİÇ erişmez: çalma da kayıt
  (mikrofon) da yok. Soketler ad alanında görünmez (`/run/user/UID` boş tmpfs). İki durum (`ses_ortami_uygula`):
  (1) varsayılan: ortam var olmayan bir sokete yönlendirilir, uygulamalar sessiz çalışır; (2) DİNLEME (Tur 3): oturumun
  özel ses sunucusu kurulmuşsa (`ses.kur`; `manage_desktop(start, audio=true)`, ilk `listen` çağrısı ya da ayar
  `[dinleme] ozel_ses = true` ile) ortam YALNIZ onun PULSE soketini gösterir. Özel örnek: oturum dizininde `ses/` (0700;
  PipeWire soketleri `pipewire-0`/`-manager`, yapılandırma, günlükler) ve `ses/pulse/` (0700; yalnız `native`), kendi
  yapılandırması (ALSA/Bluetooth/kamera eklentisi ve aygıt fabrikaları YÜKLENMEZ, WirePlumber yalnız `policy` profili,
  XDG/HOME oturum dizininde: kullanıcının ayarları/filtre zincirleri okunmaz). pipewire-pulse'ta modül yükleme KAPALI
  (`pulse.allow-module-loading = false`, `pulse.cmd` boş): `load-module` (tünel, LADSPA, pipe, TCP…) reddedilir. İçinde
  yalnız `deskhand-sessiz` çıkışı + monitörü vardır: mikrofon yok, ses kullanıcının hoparlörüne/kulaklığına ASLA gitmez,
  kullanıcının varsayılan çıkışı/düzeyi/modülleri değişmez. Uygulamanın ad alanına YALNIZ `ses/pulse/` SALT OKUNUR
  bağlanır (`ses_bagi`); PipeWire'ın tam yetkili soketleri, yapılandırma ve günlükler bağlanmaz, PIPEWIRE_REMOTE var
  olmayan yoldur. Soket yolu kayıttan değil çalışma dizininden kurulur ve gerçek dosya sisteminden denetlenir
  (`ses.soket_hazir`); Deskhand'in `parec`'i bağlanmadan önce `ses.soket_denetle` (dizin/soket türü, sahip, sert bağ, karşı
  uç = kayıtlı `ses_pulse`). Derinlemesine savunma: üç ses süreci TEK bwrap ad alanında (`ses.sunucu_argv`: ayrı
  kullanıcı/PID/ağ/IPC/UTS — ağ yok; kök salt okunur; /run, /tmp, /var/tmp, /home ve ev, /mnt, /media, /srv, RUNTIME_DIR
  boş tmpfs; asgari /dev: snd/dri/video/hidraw yok; yazılabilir tek yol `ses/`; RLIMIT_NICE/RTPRIO 0), 1 numaralı süreç
  küçük yönetici kabuk (`ses_pw`; ölünce çekirdek hepsini öldürür), masaüstünün bellek kafesinde nice 10 + ionice idle.
  Üç süreç aynı PID ad alanındadır: ayrı PID ad alanlarında PipeWire veri akışı kurulamıyor (ölçüldü). Kurulamazsa (araç yok, açılmadı, beklenmeyen aygıt) özellik
  kapalı kalır, uyarı döner. Flatpak uygulamaları `--nosocket=pulseaudio` ile kalır (kendi soketlerini ezerdi): sesleri
  dinlenemez. Eski boş çıkış (null sink) düzeneği ve ses bekçisi artık kurulmaz.
- **Dinleme (`listen`).** `dinleme.dinle`: özel çıkışın monitöründen `parec` ile 16 kHz mono s16 BELLEKTE kayıt (en çok 120 sn;
  `until_silence`: ses duyulduktan sonra sessizlikte erken biter) → ses hiç duyulmadıysa motor çalışmaz → `whisper-cli`
  (`-mc 0`, silero VAD varsa, model `[dinleme] model`; yoksa açık hata + kurulum ipucu, HİÇBİR ŞEY indirilmez) → `{text,
  segments[{t0,t1,text}], language, duration}`. Geçici WAV/JSON yalnız `<oturum>/dinleme/` (0700, dosyalar 0600; uygulamalar
  görmez) ve iş bitince silinir; çökmeden kalan eski kayıtlar sonraki tanımada silinir. whisper-cli masaüstünün bellek
  kafesinde nice 10 + ionice idle ile çalışır; motor mutlak yolu yalnız root'a ait zincirden (`arka_ortak.arac`);
  `HSA_OVERRIDE_GFX_VERSION` yalnız kullanıcı ortamında tanımlıysa aktarılır. Kullanıcı oyundaysa/tam ekrandaysa GPU
  kullanılmaz (`-ng`, CPU, en çok 4 iş parçacığı). Tanınan metin günlüğe
  YAZILMAZ (yalnız süre/dil/parça sayısı). Sonuç `warning` alanıyla "güvenilmeyen veri" etiketlidir (ses içinden komut
  enjeksiyonu). Kullanıcının GERÇEK ekran sesi bu sürümde yoktur: `desktop="foreground"` reddedilir.
- **Uygulama ortamı (iki tür).** `arka_ortak.ortam_tabani`: kullanıcının oturumuna ait değişkenler (gerçek veri yolu,
  WAYLAND_DISPLAY/DISPLAY/XAUTHORITY, AT_SPI_BUS_ADDRESS, SSH_AUTH_SOCK/SSH_AGENT_PID, GNOME_KEYRING_CONTROL,
  LIBEI_SOCKET/EIS_SOCKET, SESSION_MANAGER, KDE_FULL_SESSION, PULSE_*/PIPEWIRE_*/IBUS_*) birleştirmeden ÖNCE ve SONRA
  silinir; `GSETTINGS_BACKEND=memory` (gerçek dconf'a yazılmaz), `ATSPI_DBUS_IMPLEMENTATION=dbus-daemon` (erişilebilirlik
  başlatıcısı `dbus-broker --scope user` ile kullanıcının gerçek a11y veri yolunu yeniden kullanamasın).
  `XDG_RUNTIME_DIR` masaüstünün kendi klasörüdür (`<çalışma>/run`, 0700). HOME değişkeni kullanıcınındır; dizinin
  kendisi ad alanında boş tmpfs + beyaz listedir (yukarıda).
- **Güvenli yardımcı ikililer (iki tür).** Deskhand'in çalıştırdığı her yardımcı (bwrap, nice, ionice, sh,
  systemd-run, busctl, env, dbus-daemon, Xvfb, openbox, kwin_wayland, Xwayland, prlimit, setpriv, kdotool, wl-copy/
  wl-paste, find, pactl, at-spi2-registryd, bekçileri/pano sahibini/bildirim yakalayıcıyı çalıştıran python3)
  `arka_ortak.arac()` ile PATH'ten DEĞİL yalnız `/usr/bin`, `/bin`'den mutlak yolla bulunur; yol bileşen bileşen
  çözülür ve her bileşen (zincirdeki her sembolik bağ dahil) root'a ait, dizinler grup/diğerleri tarafından yazılamaz,
  son dosya root'a ait, başkası yazamaz, çalıştırılabilir olmalı; değilse Dur 9. Kafes kapısı `/usr/bin/sh` ile;
  uygulamanın PATH'i yalnız son komuta. (Denetim 12c Y2: PATH'in başı yazılabilir `~/.local/bin` idi; oraya bırakılan
  sahte `bwrap` sonraki bütün başlatmaları yalıtımsız yapıyordu.) Python yorumlayıcısı çalışan yorumlayıcı güvenliyse o,
  değilse `/usr/bin/python3`. Flatpak sarmalayıcısı `flatpak`/`systemctl`'i yalnız `/usr/bin`, `/bin`'de arar.
- **Test paylaşımı (yalnız test takımı).** `DESKHAND_TEST_PAYLASIM` (tests/_yalitim.py kurar) ad alanına yazılabilir
  bağlanır — test pencerelerinin olay günlükleri teste ulaşsın (ad alanında /tmp boş). Yalnız geçici dizindeki
  `deskhand-test-*/paylasim` adlı, kullanıcıya ait, 0700, sembolik bağ olmayan dizin kabul edilir; başka değer yok
  sayılır (ev dizini, soketler bu yolla açılamaz).
- **Bayat / oynanmış kayıtla kapatma (iki tür).** Bir PID'e yalnız başlangıç zamanı kayıttakiyle aynıysa
  (`arka_ortak.pid_kaydet` / `pid_dogru`) ve kafes varsa kafesteyse sinyal gider; kafes yalnız
  `deskhand-kwin-<kimlik>-N.scope` / `deskhand-sanal-<no>-N.scope` biçimindeyse boşaltılır; silinen dizin kayıttaki yol
  değil `RUNTIME_DIR/kwin-<kimlik>` / `sanal-<no>`; X kilit/soketi yalnız :120+ (Xvfb :90+) ve kilit ölü ya da kayıttaki
  sunucuya aitse.
- **Ölü sunucu.** Öncelik bekçisi ekran sunucusunu (KWin/Xvfb; PID + başlangıç zamanı) izler: SIGKILL/OOM ile ölürse
  kafesi boşaltır (SIGTERM, 2 sn, SIGKILL), kendi X soket/kilitlerini ve çalışma dizinini siler, çıkar. Yalnız "kesin
  ölü"de (`oncelik_bekcisi.kesin_olu`: süreç yok/ESRCH, zombi, ya da başlangıç zamanı farklı); `/proc/<pid>/stat`
  GEÇİCİ okunamıyorsa (EACCES, bellek baskısı…) canlı oturum kapatılmaz.
- **Karşı taraf doğrulaması önbelleği (KWin).** `_karsi_denetle`'nin başarılı sonucu (soket inode'ları, PID'ler,
  başlangıç zamanları) anahtarıyla ~1 sn geçerli: sık komutlarda her bağlantıda yeniden soket açılmaz; soket değişirse
  ya da süreç yeniden doğarsa anahtar değişir, yeniden doğrulanır.
- **Özel D-Bus sertleştirmesi (iki tür).** `UpdateActivationEnvironment` ve `ReloadConfig` reddedilir; standart
  servis dizinleri yoktur, yalnız org.a11y.Bus etkinleştirilebilir.
- **Düşük öncelik (iki tür).** Kafes nice 10 + ionice idle ile başlar; KWin `no_new_privs` (dosya yeteneği
  cap_sys_nice VERİLMEZ), RLIMIT_RTPRIO=0 ve RLIMIT_NICE (en düşük nice 10) ile açılır; ad tabanlı sistem kurallarına
  (ananicy: `kwin_wayland` → nice -12) karşı kafesin öncelik bekçisi (`oncelik_bekcisi.py`) her iş parçacığını ~0,5 sn
  içinde nice >= 10, gerçek zamanlı olmayan zamanlama ve idle G/Ç'ye geri düşürür. XWayland takma adla
  (`deskhand-xwayland`) çalışır.
- **Onay kapsamı** (`ayarlar.toml` `[guvenlik] onaylar`; panel Ayarlar → "Onay soruları"; `guvenlik.onay_kapsami()` kipi
  okuyan TEK yer, ~1 sn önbellek; okunamayan/geçersiz değer = `hepsi`). PANEL YETKİLİDİR (`liste_koruma.kapsam`): CLI/MCP
  değeri dosyadan değil, panelin doğrulanmış onay kanalından alır (`liste onaylar`); panel kapalı / kanal doğrulanamıyor /
  eski panel → `hepsi`. Panel açılışta dosyadaki `kart`'ı yalnız kendi işareti (`liste-onaylar.isaret`) da `kart` ise
  kabul eder; işaretsiz `kart` → `hepsi` + dosya geri yazılır + uyarı. Panel açıkken dosya elle değişirse panelin değeri
  korunur. Tek değiştirme yolu panelin Ayarlar'ı (ajan girdisi panel penceresine gidemez). Varsayılan **`hepsi`**: yukarıdaki TÜM onaylar
  aynen (bugünkü davranış). **`kart`** (kullanıcının kendi bilgisayarı için bilinçli tercih: "yalnız kartla ödeme")
  yalnız şu iki sınıfta onay sorar: (1) para düğmeleri (`guvenlik.PARA_DUGMESI`: satın al, hemen al, öde, ödemeyi
  tamamla, siparişi onayla/tamamla, buy now, pay, place order, complete purchase, confirm payment… — HASSAS'ın para alt
  kümesi + son sipariş/abonelik/bağış düğmeleri: place/submit/complete order, confirm (and) pay, siparişi ver/gönder/
  onayla/tamamla, onayla ve öde, bağış yap/donate, ödemeyi yap/tamamla; "Devam Et"/"Continue", "Abone ol"/"Subscribe"/"Subscriptions",
  "Onayla ve Bitir", durum yazısı "Siparişiniz onaylandı/gönderildi" para düğmesi SAYILMAZ (kullanıcı: yalnız kart
  kullanırken sor); ödeme sayfası dışında da) ve ödeme/sipariş sayfasında HER tıklama ile Enter/boşluk — sayfa kalıbı
  `kart` kipinde DAR (`guvenlik.HASSAS_SAYFA_KART`: checkout, ödeme [ödeme geçmişi/yöntemlerim hariç], sipariş özeti,
  siparişi onayla/tamamla, order review/summary, place order, payment details/information/page/step, billing
  details/information, 3D Secure/Doğrulama; `kasa`, tek başına `billing`/`payment` YOK: "PC Kasa Modelleri", "Payment
  Request API", "Google Cloud Billing" sormaz), `hepsi` kipinde geniş `HASSAS_SAYFA` aynen (`hassas_sayfa_kalibi()`) — düğme yazısı
  okunabilse de, ajanın verdiği ad ya da noktanın yanındaki yazı ("Toplam 249,90 TL") karara girmez, muafiyet YOKTUR
  (kayıtlı kartta kart yazma kapısı hiç tetiklenmez; son sipariş tıklamasını bu kapı yakalar) (`hassas_engel`,
  `hassas_sayfa_engel`, `hassas_nokta`, AT-SPI/web hassas öge); (2) kart bilgisi yazma
  (`guvenlik.kart_bilgisi_engel`: yazı, yapıştırarak yazma, AT-SPI değer yazma; hedef alan kart alanıysa — AT-SPI/web ad,
  etiket, açıklama ya da autocomplete/id/placeholder: kart numarası, card number, cc-number, cvc/cvv, güvenlik kodu, son
  kullanma, expiry — ya da metinde 13–19 haneli, Luhn'dan geçen numara varsa: boşluk/nokta/tire/bölü ayırıcılı, çift
  boşluklu, ek rakam/SKT/CVV bitişik). YANLIŞ ALARM kuralları (`guvenlik.kart_numarasi`): ayırıcı yalnız boşluk/nokta/tire/
  bölü (en çok 3; satır sonu/Tab diziyi BİTİRİR, tampon da öyle); dizi ≤23 hane; pencere kart ailesi ön eki + uzunluğuna
  (Visa/MC/Amex/Troy/Diners/JCB/Discover/UnionPay/Maestro) VE Luhn'a uymalı, yalnız GRUP BAŞINDA başlar, SON hariç her
  grubu 4–6 haneli olmalı; tarih (`22.11.2026`) ve geçerli IBAN (mod-97, `TR33…`) aday değildir. Ölçüm (4000'er örnek):
  rastgele 30/50 hane, TR/DE IBAN, iki tarih, 20 sayılık tablo, TC+telefon, boşluklu küçük sayılar %0; 10–14 haneli
  sipariş no %0,03 (eskiden %69/94, %48, %10, %100, %38, %30, %4). Bilinen sınır: bitişik 16 haneli, kart ön ekli
  (4/5/34/37/6…) bir sipariş numarası Luhn şansıyla (~%10 × önek olasılığı) hâlâ alarm verebilir.) Panoya YAZILAN metin de aynı denetimden geçer (`guvenlik.pano_yazma_engel`: API
  `pano_yaz`, MCP `clipboard write`, CLI `pano yaz`); aynı pencereye 60 sn içinde yazılan parçalar ve rakam tuşları
  (`tus`/`bas`) süreç içi küçük bir tamponda (yalnız metnin SONUNDAKİ ≤48 karakterlik rakam dizisi, yalnız bellek)
  birleştirilip denenir (`guvenlik.kart_tampon_denetle`; CLI'de her çağrı ayrı süreç: tampon yalnız MCP/Python API
  sürecinde işler; tıklama o pencerenin tamponunu boşaltır, süresi dolan kayıt okunurken silinir; metin uzunluğu
  kesilmez). Onay isteğinde yalnız son 4 hane görünür; `kart` kipinde tampona rakam giren HER `yaz`/`tus` girdisi (ve ≥8
  rakamlı yazı) `gizli` sayılır: günlükte `type ***(n)`, `key/keydown/keyup ***`, etiket `tus ***` (`guvenlik.gizli_satir`/
  `gizli_etiket`; kde/kwin/sanal arka uçlar) — günlüğe tam numara ya da kart rakamı yazılmaz. Bu iki sınıfta CLI `--onayli`/`--approved`
  YOK SAYILIR (`guvenlik.onayli_gecerli_kati`): onay her zaman panelden gelir (terminali serbest ajan CLI'yi `--onayli`
  ile çağırıp atlatamasın); panel kapalıyken ya da gözetimsiz kipte ret (10). Onaysız serbest kalanlar
  (`guvenlik.onaysiz_serbest`: tek koşul, tek satır günlük `onay kapsamı kart: onaysız geçti | …`): hesap silme ve OAuth
  "Yetkilendir/İzin ver/Authorize" düğmeleri, sistem yetki/parola istemleri (`sistem_istemi_engel`/`_denetle`: polkit,
  KWallet, askpass, portal), parola alanına yazma (`parola_alani_engel`), uçbirime/gömülü uçbirime Enter
  (`ucbirim.enter_kapisi`; satır uyarısı yalnız günlüğe, OCR yapılmaz), uçbirime yıkıcı komut yazma, riskli tuş akorları,
  yapıştırma tuşları/menü yapıştırma ve pano okuma (MCP `clipboard read`, CLI `pano oku`), MCP `open_app` doğrulanmamış
  girdi onayı (`uygulama.mcp_uygulama`: özel kopya + YN5 içerik özeti denetimi aynen), CLI `ac --komut` yıkıcı komut
  onayı. DEĞİŞMEYENLER (onay değil, ret/koruma): ajanın kendi istemcisi, `open_app` kara listesi, panel/onay penceresi
  yasağı, liste koruma, yasak pencere listesi ve erişim seviyeleri, DUR, insan önceliği, oyun/film koruması (15), oturum
  kilidi, parola alanı DEĞERİNİ okuma reddi, bekleyen onay kapısı, onay sonrası hedef doğrulaması, arka plan yalıtımı.
  Sınırlar: `kart` kipinde kart onayı SERT SINIR DEĞİLDİR: uçbirim serbest olduğundan ham girdi araçlarıyla (dotool,
  xdotool, wtype…) atlatılabilir; `alt+sysrq`, `ctrl+alt+backspace` gibi akorlar da serbesttir; gözetimsiz kipte kart dışı
  her şey onaysız çalışır. Liste korumasındaki gibi, panel KAPALIYKEN hem ayar dosyasını hem işareti tutarlı biçimde
  sahteleyen (sha256 hesaplayıp STATE_DIR'e yazan) bir süreç panelin bir sonraki açılışında `kart`'ı geçirebilir; ayrı
  çağrılarda (CLI'de ayrı süreçlerde) parça parça yazılan numara, tampon süresi (60 sn) dışına yayılan ya da kart alanı
  olarak işaretlenmemiş alana başka biçimde (kodlanmış, harflerle) yazılan numara yakalanamaz; `run_flow` önceden onaylı
  (`--onayli`) adım onayı bu ayardan etkilenmez.
- **Hesap oturumları** (`ayarlar.toml` `[guvenlik] hesap_oturumlari` = virgüllü `microsoft`/`google`/`edevlet` alt
  kümesi; panel Ayarlar → "Hesap oturumları"; varsayılan **boş = hepsi kapalı**). Oturum politikasının site ret
  listesi (`data/oturum.toml` `[site] reddet`) görünmez masaüstündeki Firefox kopyasında kimlik sağlayıcı oturumlarını
  da süzer: `login.live.com` / `login.microsoftonline.com` (alan çerezi kuralıyla `.live.com` MSPAuth/WLSSC da),
  `accounts.google.com` / `securetoken.googleapis.com` (`.google.com` SID…), devlet girdileri. Kullanıcı bir sağlayıcıya
  izin verirse `firefox.hazirla` politikayı `Politika.kimlik_izni_uygula` ile kopyalar: YALNIZ o sağlayıcının tam
  girdileri (`politika.KIMLIK_ALANLARI`: microsoft → 2 giriş alanı; google → 2; edevlet → `*e-devlet*`, `*edevlet*`,
  `turkiye.gov.tr`, `gib.gov.tr`, `sgk.gov.tr`, `*.gov.tr`; ABD `*.gov` DEĞİL) ret listesinden çıkar → o alanların çerezi (oturum
  çerezleri dahil), kayıtlı girişleri (`logins.json`/`logins.db`; parolayı Firefox doldurur, ajan okumaz; `key4.db`
  zaten kopyalanır) ve `--site` verilmişse deposu kopyaya girer. Banka/ödeme desenleri (`*bank*`, `*odeme*`,
  `*payment*`, `*checkout*`, `*paypal*`, `*stripe*`, bankalar, iyzico, PayTR…) hiçbir sağlayıcıda yoktur: bir alan
  kalan herhangi bir girdiye uyarsa yine reddedilir (`ebank.gov.tr` e-Devlet izniyle de ret). **Görev kipinde
  (`DESKHAND_GOREV=1`) izin HİÇ uygulanmaz**: `hazirla` izni sormaz, kimlik çerezleri her zaman süzülür. Kopya
  açıklaması (`open` çıktısı, `oturum hazirla`) ve `doctor` satırı özet verir ("kimlik oturumları: Microsoft aktarıldı
  (5 çerez, 1 kayıtlı giriş); Google süzüldü (… izin kapalı)"); son özet `RUNTIME_DIR/oturum/kimlik-son.json`'da (yalnız
  bilgi, karar için okunmaz). İzin GEVŞETME yönünde olduğundan onay kapsamıyla aynı PANEL YETKİLİ model
  (`liste_koruma` KIMLIK): CLI/MCP değeri dosyadan değil panelin doğrulanmış kanalından alır (`liste kimlik`; kanal
  salt okunur, yazma komutu yok); panel kapalı / doğrulanamıyor / eski panel → izin YOK. Panel açılışta dosyadaki
  sağlayıcılardan yalnız kendi işaretinde (`liste-kimlik.isaret`) de olanları kabul eder; işaretsiz sağlayıcı →
  dosya geri yazılır + uyarı. Panel açıkken dosyaya elle eklenen sağlayıcı geri alınır (`denetle`); dosyadan çıkarmak
  ya da dosyayı silmek kabul (sıkılaştırma). Tek açma yolu panelin Ayarlar'ı: ana anahtar ("Giriş yaptığım hesaplar …
  banka ve ödeme siteleri hariç") üçünü birlikte, kutular tek tek açar; açarken onay diyaloğu (varsayılan Hayır),
  kapatmak sorusuz. Sınır (onay kapsamıyla aynı): panel KAPALIYKEN hem ayar dosyasını hem işareti tutarlı biçimde
  sahteleyen bir süreç panelin bir sonraki açılışında izni geçirebilir. İzin açıkken arka plandaki tarayıcı o hesabın
  e-postasına/dosyalarına erişebilir; güvenilmeyen sayfa ajanı kandırabilir (panel uyarı metni bunu söyler).

### 4.z Girdi ve gizlilik ayrıntıları (0.9.0)

- **deskhand-eis karakter eşlemi**: önce X11'de var olan tuş (evdev ≤ 247; xkb kodu ≤ 255), sonra en az değiştirici;
  yazdırılabilir karakter yalnız X11 dışı tuştaysa `yazilamaz` (pano yolu). Tanılama: `plan METİN`, `--harita-sina`.
- **Güç/kilit tuşları** (`guvenlik._GUC_TUSLARI`): power, sleep, wakeup, screenlock (coffee/XF86ScreenSaver), suspend,
  hibernate, logoff — kanonik adlar `_TUS_ESANLAM`/`_EVDEV_AD`/`_KEYSYM_AD`'dan; değiştiricisiz tek tuş da `riskli_tus`
  (onay). `ctrl+alt+shift+delete/pageup/pagedown` da.
- **Denetim karakterleri**: `eylem.denetim_karakteri_denetle` (k_yaz, yaz_ic, yazima_hazirla, erisim.k_ogeye_yaz);
  arka uçların `yazilabilir_mi`'si Cc için False.
- **Gizli yazı**: `yazima_hazirla(gizli=True)` karakter değiştirmez; dizi/akış adımı `eylem.adim_metni` ile maskelenir;
  `girdi_merkezi.uyari_maskele` dotool karakter uyarılarını merkez günlüğünde her zaman, istemcide gizli gönderimde
  maskeler; günlükte gizli parça uzunluğu yok (`gizli_satir` → `type ***`); `_gizli_pano_temizle` geri yüklenemeyen
  panoda gizli parçayı siler.
- **Okunamayan tarayıcı sayfası (R1)**: `dogrulama_sinamasi.okunamayan_klavye_engeli(k=…)`: Tab sonrası girdi her zaman
  ret; dizide Enter/Boşluk varsa `erisim.odak_bilgisi(k)` (tek sınırlı DFS, değer okunmaz: `rol`, `belge_ici`,
  `duzenlenebilir`) → belge dışı ya da düzenlenebilir: izin; aksi/bilinmiyor: ret.
- **Gerçek ekran kilidi ve onay**: `onay.iste_sonuc` kilidi yalnız hedef kullanıcının ekranıyken uygular;
  `guvenlik.sayfadan_cikis` (yalnız `gezin.adrese_git`): adres + Enter, odak belge dışındaysa ödeme sayfası onayından muaf.
- **Web değer maskesi** (§9): `web._ayrinti_ekle` giriş değerini `erisim._deger_temizle` ile süzer; Firefox ilk sorguda
  boş nitelik verebildiği için bir kez daha sorulur. `web.tarayici_mi` sınıfı `. - _` ve boşlukla parçalar.
- **CLI okuma komutları** `gorsel.korumali_goruntu` → `api.goruntu_al` (yasak hedef 10, diğer yasaklar siyah).
- **Maskeli görüntü yolu kuralı (0.9.1, SINIF-MASKE)**: pikseli ya da ondan türeyen metni (OCR, renk alanı koordinatı,
  `noktadaki yazı`, eşleşme listesi, Dur iletisi) süreç DIŞINA (ajana, MCP sonucuna) giden her kare
  `gorsel.korumali_goruntu` / `api.goruntu_al` yolundan alınır. Bu yol yasak pencere listesini karenin ÖNÜNDE ve
  ARKASINDA okur (`maske_kare.iki_okumali_kare`). İki konumun birleşimi karartılır; kareden sonra yasaklanan pencerenin
  kareden önceki konumu da birleşime girer (`Geometriler.tum`). Kare sırasında kapanan ya da yasaktan çıkan pencere ve
  okunamayan liste `Dur(8, tur=maske-yarisi|maske-okunamadi)` verir; kare gönderilmez. `korumali_goruntu` bu durumda
  kısa beklemeyle en çok 3 kare dener; yeniden deneme yalnız 2 sn son tarihinden önce başlar ve kararlılık beklemesi
  (`son_tarih`) o tarihte biter (toplam ≈ 2 sn + bir kare/liste okuması); uzun akış ve `bekle` tek yarışta düşmez.
  Uçbirim Enter kapısında ajana dönen Dur iletileri (10 ve gerçek ekran kilidi 17) genel eylem metni taşır, okunan
  satır yalnız panelde kalır. Ham kare
  (`gorsel.pencere_goruntusu`, `_pencere_goruntusu`, arka uç `.goruntu`) yalnız pikseli süreçten çıkmayan iç işlerde
  kullanılır. Bunlar: onay hedefi parmak izi (`onay_hedef._goruntu`), insan onay panelinin görüntüsü
  (`guvenlik.hedef_goruntusu`), uçbirim Enter kapısının satır okuması (`ucbirim._ocr_satirlar`; ajana giden Dur iletisi
  OCR'dan türeyen sözcük taşımaz, ayrıntı yalnız panelde), masaüstü kipinde tıklama öncesi yeniden denetim
  (`eylem.k_metne_tikla`, yalnız bool; kabul edilen 1 bitlik sınır) ve panel önizlemesi. İzin listesi, gerekçesi ve
  her işlevdeki başvuru sayısı `tests/test_guv_sinif_maske.py` (`IZINLI`) içinde tutulur. Ad hangi biçimde geçerse
  geçsin test kırmızı verir: ad, öznitelik, içe aktarma takma adı, dizge sabiti ya da getattr/vars/`__dict__`
  (yeni çağıran ve izinli işleve eklenen yeni kare dahil). Bilinen sınırlar: bu kapı bir tetik teli, kum havuzu
  değildir (çalışma anında kurulan ad görülmez); iki okuma arasında SÜRÜKLENEN yasak pencerenin ara konumu
  karartılmaz; iki liste okumasının maliyeti ölçülmedi.
- **CLI otomatik başlık kilidi**: `cli.otomatik_baslik_kilidi` (kimlikle verilen yaz/tus/tikla/dizi/kaydir, `-b` yok →
  `^…$`; `--no-title-lock`).
- **MCP sonuç sözleşmesi** (§10): `arac` ve `okuma_araci` sarmalayıcıları beklenmeyen istisnayı da `hata_sonucu`'na
  çevirir (`[9]`); `mcp_adlari` CLI seçeneklerini MCP parametre adlarına çevirir.
- **İnsan önceliği**: pencere sonrası tek kısa 'aktif' (`YANSIMA_PAY` 0,5 sn, `YANSIMA_SURE` 0,04 sn) için yerleşme
  beklenir; etkinlik yardımcısı v1 bildirirse izleyici yok sayılır.
### Masaüstü sahipliği (CLI) ve masaüstü seçimi (0.9.0)
- `desktop start` ve `open --background`'ın kendiliğinden açtığı masaüstü, çağıranın ata zincirindeki en yakın
  `claude` sürecine yazılır (`masalar.cli_sahiplen`; sahip dosyası türü `cli`; insan/görev kipi/panel hariç). Başka
  Claude oturumu → 14; sahibi ölen adlı `cli` masaüstü `oto` gibi süpürülür (`masaustu.oto_temizle`). `desktop stop`
  adlı masaüstünün `masa/<ad>` dizinini siler (canlı MCP sahibi yoksa).
- MCP otomatik bağlanma: varsayılan masaüstü sahipsiz ama canlı ve kafesinde uygulama (en üst `bwrap` süreci,
  `masaustu.uygulama_pidleri`) varsa DOLU sayılır → `oturum-N` (masaüstünü aynı Claude oturumu açtıysa — durum
  kaydındaki `baslatan_ajan` ata zincirinde — paylaşılır).
- CLI: `--desktop-name AD` komut adına kadar her konumda ve komuttan sonra kabul; verilmişse (ya da
  `DESKHAND_MASAUSTU`) hedef kendiliğinden arka plandır. zsh notu: boşluklu değişken bölünmez —
  `export DESKHAND_HEDEF=arka DESKHAND_MASAUSTU=ad` ya da dizi kullanın (`ENV="A=1 B=2"; $ENV komut` çalışmaz).
- Kimlik oturumu kopyasında Microsoft/Google ÇIKIŞ adreslerine gitme henüz onay istemiyor (açık iş; kopyadan çıkış
  sağlayıcıda asıl oturumu da kapatabilir — kimlik izni açıkken kopyada çıkış yapmayın).

## 5. Çıkış kodları
0 tamam · 1 kullanım hatası · 2 nokta pencere/ekran dışında · 3 aktif değil/başka pencere · 4 başlık/sınıf kilidi
uymadı · 5 belirsiz (birden çok eşleşme) · 6 bulunamadı · 7 zaman aşımı · 8 pencere yok/taşındı ·
9 araç eksik (dotool/tesseract/Xvfb…) · 10 yasak/hassas · 11 akış hata ekranı · 12 insan kullanıyor ·
**13 kullanıcı DUR dedi** · **14 sanal masaüstü kapalı** · **15 kullanıcı oyunda/film izliyor, ekranına müdahale yok** ·
**16 uygulama arka planda açılamaz** (kullanıcının ekranında açık ya da yalnız ön plan) ·
**17 gerçek ekran bu süreçte kapalı** (`DESKHAND_GERCEK_EKRAN`, bkz. §6) ·
**18 insan doğrulaması (CAPTCHA) bekliyor: ajan girdisi reddedildi, kullanıcıya devret (`request_human`)** ·
20 / 21 `decide` karar kodları: 0 = kullanıcının ekranı, 20 = arka plan, 21 = sonra.

Çağıran otomasyon 10, 12, 13, 15, 16, 17 ve 18'de durmalı ve kullanıcıya haber vermelidir. MCP yüzeyinde aynı kodlar
`[kod] ad: ayrıntı` hatası olarak görünür. Bu tablo README'deki "Exit codes" tablosuyla tutarlı tutulur.

## 6. Çalışma kuralları
- Testler `DESKHAND_*_DIR`'leri geçici klasöre yönlendirir; gerçek `~/.config`, `~/.local/state` vb. yazılmaz.
  Uzun koşudan önce/sonra `~/.config/deskhand` (ve varsa eski `~/.config/ekran`) için sha1 karşılaştırın.
  Yeni bir yazma yolu eklerken testlerin onu gerçekten taklit ettiğini doğrulayın.
- Gerçek ekran testleri: GERÇEK ekrana girdi gönderen hiçbir test/komut (kde arka ucu ile tikla/yaz/tus,
  `tests/ekranli/`) kullanıcı bilgisayarı kullanırken (film, oyun…) çalıştırılmaz; yalnız elle, makine boştayken
  koşulur. Sanal masaüstü (Xvfb) testleri serbesttir.
- **Gerçek ekran kilidi (yapısal):** `DESKHAND_GERCEK_EKRAN=kapali` ayarlıysa kullanıcının GERÇEK oturumuna etki eden her
  yol, gerçek aracı çalıştırmadan HEMEN önce `hata.gercek_ekran_denetle()` ile reddedilir (Dur 17, açık ileti): girdi
  (`kde.Girdi` kurulumu, `kde.dotool_ac`, girdi merkezi bağlantısı), yan etkili `kdotool` sözleri (etkinleştir/taşı/
  boyutlandır/küçült/kapat… `kde.calis`), uygulama başlatma (`kde.baslat`), pano yazma (`kde._wl`), bildirim
  (`mesgul.sor`), kullanıcının oturum veri yolunda erişilebilirlik ayarı ve AT-SPI eylem/yazma (`erisim`).
  Kullanıcının ekran/pano İÇERİĞİNİ okuyan yollar (ekran görüntüsü, `wl-paste`) da kapanır; `salt-okuma` değeri bunları
  (yalnız okumayı) serbest bırakır. Pencere listesi/başlık/geometri, kilit/boşta durumu ve AT-SPI okuma açık kalır.
  Tanınmayan değer `kapali` sayılır. Ayarsızken davranış birebir aynıdır; `doctor` ayarlıysa "Gerçek ekran" satırını
  gösterir. Görünmez masaüstü (`sanal`, `kwin`) ve test sahte arka uçları etkilenmez. KURAL: ölçüm/test betikleri
  `tests/_yalitim`'i içe aktarır (kilidi koyar) ya da değişkeni kendileri ayarlar; yalnız bilerek gerçek ekrana
  dokunan `tests/ekranli/` kaldırır. Gerçek aracı sahte ikiliyle değiştiren testler kilidi kendi içinde `acik` yapar.
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
- **Gözlem + ref + toplu adım (Faz 10).** MCP ajanı `observe` ile numaralı ögeler ve `ref` alır; `ref` ile eylemde öge
  güncel ağaçta KİMLİĞİYLE yeniden doğrulanır, sonra MEVCUT güvenli yoldan gider. `batch` aynı araç çekirdeklerini
  sırayla çağırır; paralel kapı yazılmaz. Her girdi sonucu `effect` taşır, her hata `sent` + `next` (§10).

## 8. Onay protokolü (arayüz + MCP + CLI ortak)
Hassas eylem (hassas düğme, ödeme sayfası, yasak dışı ama riskli `ac`, oturum aktarımı) için onay YALNIZ insandan:
- `deskhand/onay.py`: `iste(eylem, hedef, ayrinti, masaustu, sure=120) -> bool`.
  Panel kaydı: `RUNTIME_DIR/panel.pid` {pid, baslangic (/proc/<pid>/stat 22. alan), exe (/proc/<pid>/exe),
  cmdline (/proc/<pid>/cmdline argv'si: exe Python yorumlayıcısı olduğundan panelin modül yolu/giriş noktası), zaman}.
  **Onay kanalı:** panel `RUNTIME_DIR/onay/kanal.sock` Unix soketini dinler (0600, dizin 0700; `panel_kaydet` açar,
  `panel_sil` kapatır; Qt'siz iş parçacıklı sunucu). İsteyen ÖNCE kanala bağlanır ve karşı tarafı doğrular: soket
  dosyası ve dizin kendisinin ve başkalarına kapalı; SO_PEERCRED uid = kendi uid, pid = panel.pid'deki pid, aynı
  başlangıç zamanı, aynı exe, kayıttakiyle BİREBİR aynı cmdline ve cwd, panelin yüklediği deskhand paket dizini
  (kayıtta `paket`) isteyeninkiyle aynı. Doğrulanamazsa red ("onay kanalı doğrulanamadı", günlüğe neden).
  İstek: `RUNTIME_DIR/onay/istek-<uuid>.json` {id, eylem, hedef, ayrinti, masaustu, zaman, son_zaman, pid, goruntu};
  ardından kanala `bekle <uuid>`. Panel bağlananın SO_PEERCRED pid'ini isteğin `pid` alanıyla karşılaştırır (başka
  süreç başkasının kararını alamaz). Panel (QFileSystemWatcher) diyalog açar: **Bir kez izin ver / Reddet** (+ hedefin
  küçük ekran görüntüsü). Karar AYNI bağlantıdan döner: `karar izin|red <uuid>` (isteyen henüz bağlanmadıysa panel
  saklar). **İzin yalnız kanaldan gelir;** `yanit-<uuid>.json` {id, karar: "red", kaynak: "arayuz", zaman} yalnız red
  için yazılır ve isteyen her yanıt dosyasını (içeriği ne olursa olsun) RED sayar: aynı kullanıcıdaki, yalnız dosya
  yazabilen bir süreç sahte izin üretemez. Süre dolarsa, panel kapalıysa/kapanırsa (bağlantı kopar) ya da DUR
  açılırsa → red (mesaj: "Deskhand paneli kapalı, onay alınamadı"). Tek kullanımlık; istek/yanıt dosyaları kullanılınca
  silinir. Panel izni göndermeden önce diyaloğu gizler (onay sonrası doğrulamada hedefi örtmesin).
- **Onay sonrası yeniden doğrulama (MCP, `onay_hedef.py`).** Onay isteğinden hemen önce (kilit tutulurken)
  `yakala(k, bolge)` → `OnayHedefi` {k, masaustu, baslik, geometri, bolge (pencere pikseli), ozet (fark.Once), zaman};
  izinden sonra kilit altında, eylemden önce `dogrula_dur(h)`: pencere yok, başlık/geometri farklı ya da bölgenin
  görüntüsü değiştiyse (fark.py eşiği; geçici örtü için 0/0,15/0,3 sn yeniden bakılır) → Dur 10 "onay verilen hedef
  değişti; yeniden onay gerekir", eylem yapılmaz. Bölge: koordinatlı tıklamada noktanın çevresi (480×200, onay
  görüntüsüyle aynı), çekirdeğin görüntüsü `info["deskhand_bolge"]` taşıyorsa o, yoksa tüm pencere. kde'de görüntü
  yalnız çekirdek zaten hedef görüntüsünü aldıysa alınır (odak çalınmaz; yoksa yalnız kimlik/başlık/geometri);
  bölgesiz tüm ekran görüntüyle karşılaştırılmaz.
- CLI `--onayli` kalır (kullanıcı sohbette açıkça onayladıysa), MCP yüzeyinde YOK. Riskli tuş ve uçbirim komutu da bu
  protokolü kullanır (eylem metni "Riskli tuş: …" / "Uçbirime komut yaz: …"); gözetimsiz kipte `iste_sonuc` hiç panele
  yazmadan `gozetimsiz` nedeniyle red döner.
- Onay diyaloğu penceresi yasak listesine (sınıf/başlık) otomatik eklenir: hiçbir otomasyon girdisi ona gitmez.
- Tehdit modeli: onay, ajanın (yanlışlıkla ya da istem enjeksiyonuyla) kendi kendine izin vermesini ve yalnız dosya
  yazabilen bir sürecin sahte izin üretmesini engeller. Kabuğu olan ajan için sandbox değildir: aynı kullanıcıyla
  keyfi kod çalıştırabilen süreç paneli öldürüp yerine geçebilir ya da ptrace ile bağlanabilir.

## 9. Web sayfası ögeleri (tarayıcı erişilebilirlik ağacı)
**Yol.** `deskhand/web.py` tarayıcı penceresindeki sayfanın etkileşimli ögelerini (bağlantı, düğme, alan, onay/radyo/seçim
kutusu, sekme, menü ögesi; ad, rol, durum, PENCERE koordinatlı kutu, bağlantı adresi, alan değeri) AT-SPI ağacından okur.
Araçlar: MCP `read_text(source="web")` (+ `role`, `offset`/`next`, `hidden`; sayfa başlığı, adres, `sensitive_page`),
CLI `web <kimlik> [sorgu] [--rol R] [--hepsi] [--sayfa N]`, MCP `click(element=…, role=…)` ve CLI `click-element`.
**Tık yolu (`erisim._web_sec/_web_tikla`).** Hedef pencere sınıfı tarayıcı/Electron ise `element` önce sayfada aranır
(önce görünürler, yoksa görünmeyenler; bulunamazsa genel ağaç yolu = tarayıcı arayüzü). Bulunan ögenin `merkez`i
MEVCUT `tikla_ic` yoluna verilir: gerçek fare tıklaması, bu yüzden DUR 13, yasak 10, başlık/sınıf kilidi 4, erişim seviyesi
10, kde'de oyun/film 15, insan önceliği 12, imleç altı denetimi (`tikla_ic` → `Girdi.gonder`, `imlec_alti_denetle`)
aynen çalışır; döngü kesici ve fark özeti MCP `click` sarmalayıcısındadır. Hassas denetim `eylem.hassas_nokta`'da: ögenin ADI
hedef metne eklenir (yazısız `aria-label` düğmesinde OCR yazıyı okumasa da onay istenir), belge başlığı ağaçtan gelir ve
pencere başlığına EK denetlenir (`hassas_sayfa_engel(ek_basliklar=…)`). Devre dışı öge 6 (genel `ogeye-tikla` iletisiyle
aynı); görüş alanı dışındaki öge mevcut kaydırma yoluyla (`kaydir_ic`, tüm girdi denetimleriyle, en çok 8 tur, ilerleme
yoksa hata) görüş alanına getirilip tıklanır. `via="action"`: Action arayüzü (NActions + GetName) üzerinden, fare/odak yok;
denetimler `_ogeye_eylem` ile aynı (öge kimliği veri yolu adı + nesne yolu BİRLİKTE tutulur; sistem istemi onayı da).
**Çerçeve (B2 kuralı web'de de).** `web._cerceve_bul` çerçeveyi YALNIZ pencerenin süreç ağacındaki bağlantılardan seçer
(pencerenin süreci ya da torunları; atalar — pencereyi başlatan uçbirim/başlatıcı — ve Deskhand'in kendi bağlantısı
sayılmaz); PID bilinmiyor ya da ağaçta uygulama yoksa 6, başlık benzerliğiyle başka uygulamaya düşülmez. Seçilen çerçeve
`erisim._cerceve_denetle` ile denetlenir: okumada (`read_text(source="web")`, CLI `web`, tık öncesi arama) panel süreci /
yasak desen 10; eylemde (`web.eylem_yap`, çerçeve DoAction'dan hemen önce yeniden seçilir, öge o çerçevenin bağlantısında
olmalı, yoksa 8) ek olarak ajanın kendi istemcisi ve uygulama erişim seviyesi 10. Parola alanının (`password text`)
değeri okunmaz. Fare yolunda pencere düzeyi denetimler `tikla_ic`'te (kendi istemci, sistem istemi, seviye, B3).
**Konum doğrulama (fail-closed).** Wayland'de ögeler uygulamaya göre pencere-yerel, küresel istemci alanı ya da küresel
dekorlu çerçeve koordinatında gelebilir. `web.konum_coz`, üst düzey çerçevenin sınırını (GetExtents SCREEN ve WINDOW)
pencerenin bilinen geometrisiyle ±1 px karşılaştırıp çerçeveyi belirler; hiçbirine uymuyorsa okuma `konum_dogrulandi=false`
bildirir ve tık REDDEDİLİR (kod 2: "öge konumu doğrulanamadı; OCR ile metne tıklamayı dene"). Sanal masaüstünde (X11, tek
çerçeve) denetim otomatik uyar.
**Neden erişilebilirlik ağacı.** Uzaktan denetim protokolü (Marionette/BiDi) kimliksiz yerel kapı açar ve sayfa otomasyon
görür (`navigator.webdriver`); AT-SPI yeni kapı açmaz, sayfaya görünmez, Chromium/Electron'da da aynıdır. Ölçüm
(tests/web_olcum.py): kapsama %100, kutu farkı ≤ 1 px, 1.000 öge ~0,25 sn. Marionette istemcisi YALNIZ ölçüm betiğindedir.
**Arka plan Firefox.** Sanal masaüstü uygulamalardan önce kendi erişilebilirlik kayıt defterini başlatıp `IsEnabled=true`
yazdığı için `ac --arka` ile açılan Firefox ek ortam değişkeni (GNOME_ACCESSIBILITY) olmadan ağacı sunar (test_web_bag.py).
**Sınırlar.** Başka bir ögenin ÜSTÜNÜ örten öge (modal, yapışkan başlık) ağaçtan ayırt edilemez; imleç altı denetimi yalnız
pencere düzeyindedir. Gerçek (kde, Wayland) ekranda koordinat çerçevesi henüz gerçek ekranda doğrulanmadı: `konum_coz`
varsayımları (üç çerçeve, ±1 px, dekorasyon payı sınırları) elle denenmelidir. Pencere sınıfı bilinen tarayıcı listesinde
değilse `click-element` sayfaya bakmaz (`web` okuması ve koordinatlı tık yine çalışır). `ogeye-yaz` web alanlarında yoktur.

## 10. MCP gözlem yüzeyi: observe, ref, batch, wait_for, sonuç sözleşmesi
**`observe` (salt okunur, `deskhand/gozlem.py` + `mcp_sunucu.observe`).** Tek çağrıda pencerenin ögeleri: tarayıcıda
sayfa (`web.oku`, `yol_ver=True`), değilse genel ağaç (`erisim.erisim_ogeleri(ayrinti=True)`: durumlar, eylem adları,
değer), ağaç yoksa/çok küçükse (adı olan < 3 öge) ya da `include_ocr=true` ise OCR satırları (`api.metin_oku`; ağaçtaki
ögenin kutusunda aynı yazı atılır). Yeni okuma yolu YOKTUR: çerçeve seçimi ve denetimi (§4, §9: süreç ağacı, panel/yasak
10) aynen; yasak pencere 10; parola alanının (`password text`) değeri hiçbir yolda okunmaz. Pencere verilmezse tüm ekranın
OCR'ı. Çıktı: başlık satırı (`snapshot <id> | window … | sources tree+ocr | N items`), web'de sayfa satırı (ödeme sayfası
uyarısı, konum doğrulanmadıysa "element clicks are refused"), her öge `[N] rol "ad" durum = "değer" !sensitive (ocr)`;
yapılandırılmış alanlar `ref`, `role`, `name`, `value`, `states`, `frame` (pencere pikseli), `actions`, `sensitive`,
`href`, `source`; boş/varsayılan alanlar atılır, U+FFFC ve yalnız boşluk metinler atılır. `query="a|b"`: adı/değeri/rolü
eşleşen ögeler + ADI OLAN ataları (çocuk-sıra yolu öneki). `max_elements` (150, ≤1000) + `offset` → `next_offset`.
`since=<snapshot_id>` (aynı pencere): yalnız `+` eklenen, `~` değişen (ad, değer, durum, kutu > 3 px), `-` kaybolan.
`include_screenshot`: maskeli pencere görüntüsüne öge kutuları + numaraları çizilir (Set-of-Marks) ve `shot_id` kaydedilir.
**Anlık görüntü önbelleği.** `snapshot_id` = sunucu (süreç) başına rastgele 4 hex önek + sayaç; pencere başına en çok 4,
toplam 16 FARKLI içerik, ömür 120 sn (içeriği bir öncekiyle aynı gözlem, ör. sayfalı `observe(offset=…)`, aynı gruba
katılır: ilk sayfanın ref'leri düşmez). Öge kimliği: erişilebilirlik ögesinde veri yolu adı + nesne yolu (BİRLİKTE; `_tara` libatspi
nesnesinin alanlarından okur, okunamazsa çocuk-sıra yolu) + pencere; OCR satırında metin + kutu.
**`ref` ile eylem.** `click(ref)`, `type_text(ref)` (önce alan tıklanır, sonra klavye yolu), `scroll(ref)`,
`drag(from_ref, to_ref)`. Bayatlık üç ayrı nedenle, HİÇBİR girdi gönderilmeden reddedilir (`[8]`, `error.reason`):
`snapshot` (bilinmiyor / süresi doldu / önbellekten düştü), `window` (başka masaüstü ya da pencere, pencere kapandı,
boyutu değişti), `element` (öge yok, adı/rolü değişti, kutusu ±3 px'ten fazla oynadı, numara yok). Öge düzeyi doğrulama
ÇEKİRDEKTE ve güncel ağaçtan yapılır (TOCTOU): `erisim.ref_oge_sec` ögeyi ADLA ARAMAZ, kimliğiyle bulur ve ad/rol/kutuyu
karşılaştırır (aynı adlı başka düğmeye düşülmez); `k_ogeye_tikla` / `_ogeye_eylem` / `_web_sec` (`a.ref_oge`) bu
seçimle MEVCUT yoldan devam eder: fare → `hassas_nokta` (öğe adı hedef metinde) + `_onay_sonrasi_oge` + `tikla_ic`
(`Girdi.gonder`: DUR, `denetle`, seviye, kendi istemci, sistem istemi, imleç altı, insan önceliği, kde oyun/film);
`via="action"` → `_atspi_korumalari` + `_hassas_oge` + sistem istemi onayı; web → `_web_tikla` / `_web_eylem` (onay sonrası
kimlikle yeniden bulma `_web_yeniden`). OCR satırı ref'i → `k_metne_tikla` (yazı ref kutusunun ±12 px çevresinde yeniden
okunur; yoksa `[8] element`). `scroll`/`drag` ref'in GÜNCEL merkezini kilit altında yeniden doğrular (`_ref_nokta`), sonra
`kaydir_ic` / `k_surukle`. `ref` yolunda onay parametresi YOKTUR; bekleyen onay kapısı (`kilitli(girdi=True)`), döngü
kesici (hedef = öge kimliği) ve onay sonrası hedef doğrulaması (§8) aynen.
**`batch` (en çok 20 adım).** Araçlar yalnız `click`, `type_text`, `press_key`, `scroll`, `drag`, `wait` (`{"seconds":
0-10}`, DUR'u 0,1 sn'de denetler). Tüm adımlar HİÇBİR şey gönderilmeden doğrulanır (aracın kendi argüman modeli, desktop
batch'inkiyle aynı, wait süresi). Her adım modüldeki ÇEKİRDEK araç işlevini çağırır (`arac()` MCP'ye yalnız sarmalayıcıyı
kaydeder; çekirdek aynı kilit/kapı/onay/döngü kesicidir). İkinci adımdan itibaren her adımdan önce DUR, bekleyen onay ve
insan önceliği (`guvenlik.insan_onceligi`, en çok 8 sn) yeniden denetlenir. İlk hatada durulur: `failed_step`,
`not_sent`, adımın ve batch'in `sent` değeri. Bir adım onay isterse batch o adımda bekler; red = dur. `observe_after`
son adımın penceresini gözler.
**`wait_for` (salt okunur).** `text` (ağaçta ad/değer, yoksa OCR), `gone`, `element` (ad + isteğe bağlı rol), `window`
(başlık deseni, yasak pencere sayılmaz), `stable` (pencere görüntüsü `stable_ms` boyunca aynı, fark.py). Kilit her
yoklamada alınıp bırakılır; zaman aşımı hata değil `satisfied:false`.
Ön planda (kde) `text`/`gone`/`stable` pencereyi ÖNE GETİRMEZ: hedef etkinse görüntü/OCR; değilse yalnız AT-SPI ağacı
(ağaç yoksa `satisfied:false` + bir kez `note`); kullanıcı etkinken (`insan_var_mi`) yoklama atlanır, süre sayılır.
Arka planda davranış aynıdır. `batch` `desktop=auto`'yu başta BİR kez çözer; `click`/`type_text`/`scroll`/`drag` ref'i
anlık görüntüdeki pencere başlığı değiştiyse reddeder ([8]) ve başlık kilidini o başlıktan kurar.
**Sonuç sözleşmesi.** Girdi araçlarının sonucu `effect`: `confirmed` (beklenen değişim görüldü: tıklanan ref ögesinin
checked/selected/expanded durumu değişti, yazılan metin değişen bölgenin OCR'ında görüldü ya da değer geri okundu,
kaydırmada görünüm değişti, pencere geometrisi değişti), `changed`, `no_change` (döngü kesiciyle uyumlu), `unverifiable`
(ölçülemedi: kde'de `via=action`, `verify=false`), `refused` (hata ve hiçbir şey gönderilmedi). Hata sonucu (`isError`)
metni: `[kod] ne oldu` + `sent: nothing_sent | maybe_partial` + `next: ne yapmalı (araç adıyla)`; aynısı
`structuredContent.error` {code, message, reason, next}, `sent`, `effect` alanlarında. `sent` sayacı (`gonderim.py`)
`api.arka()` girdi nesnesinin `gonder()`/`ham()` dönüşünde ve erişilebilirlik eylemi/değer yazma çağrısından hemen önce
artar; bırakma (`zorla`) sayılmaz. outputSchema: `wait_for`, `click` için alanlı TypedDict, diğer girdi araçlarında
genel nesne; `observe` ve `batch`'te outputSchema YOK ve başarılı sonuç YALNIZ kısa metindir (structuredContent
gönderilmez: yapılandırılmış kopya metnin ~5 katı token'dı). observe satırı `[N] rol "ad" @x,y,w,h durumlar = "değer"
!sensitive (ocr) (offscreen) href="…"`; başlıkta snapshot_id, pencere kimliği, kaynaklar; include_screenshot'ta
`shot_id` satırı. batch metni adım başına etki/changed_region/approved_by_user/warning ve durma satırını taşır. Hata
sonuçları (her araçta) küçük structuredContent'i korur. Şemalardaki otomatik `title` metinleri silinir.
**Sınırlar.** Tarayıcı penceresinde observe yalnız sayfayı (belge) listeler: adres çubuğu/sekmeler için `press_key`
(ctrl+l) ya da `read_text(source="tree")`. Web ögeleri yalnız görünenler (kaydırma alanı dışındakiler `read_text(source=
"web", hidden=true)`). Sistem istemi penceresinde (polkit, KWallet, parola sorucusu) her tıklama türü — ref, text,
element, simge, renk, koordinat, `via=action` — hedef aranmadan önce insan onayı ister (`eylem.sistem_istemi_on`;
gözetimsiz kipte ret → 10). `type_text(ref=…)` iki çekirdek eylemdir (alan tıklaması + yazı): sistem isteminde iki
onay sorulur.

## 11. Görev kipi (panel "Görev" sekmesi; `deskhand/gorev_kipi.py`)

Görev ajanı (`claude -p`) GÜVENİLMEZ web içeriği okur (istem enjeksiyonu): kip yerel dosya ve kayıtlı parola/oturum
sızıntısını sınırlar. `gorev.mcp_ortami()` → mcp.json `env` YALNIZ `{"DESKHAND_GERCEK_EKRAN": "kapali",
"DESKHAND_GOREV": "1"}`; görevde izin verilen siteler `DESKHAND_GOREV_SITELER` ile claude'un ortamından gelir.
- **open_app** yalnız tarayıcı: yerel paket Firefox; Chromium ailesi yalnız ilke kökü (/etc/chromium vb.) varsa (oturum
  politikası zaten `on`); Flatpak/Snap tarayıcı, uçbirim, dosya yöneticisi, düzenleyici, yorumlayıcı → 10. Belge
  argümanı yalnız http(s).
- **Ev dizini**: arka plan uygulamasına XDG veri klasörleri (Masaüstü, Belgeler, İndirilenler…) BAĞLANMAZ; yalnız görünüm
  beyaz listesi + `RUNTIME_DIR/gorev-indirilenler` (kullanıcının XDG_DOWNLOAD_DIR yolunda, yazılabilir). Görev bitince
  indirilenler kullanıcıya bildirilir (`bitti` olayı: `indirilenler`, `indirme_dizini`).
- **Tarayıcı ilkesi** ad alanında salt okunur bağlanır: Firefox `<kurulum>/distribution/` yerine `policies.json` (+ özgün
  distribution.ini): BlockAboutConfig/Profiles/Addons/Support, PasswordManagerEnabled=false (about:logins engelli),
  DisableDeveloperTools (about:debugging), WebsiteFilter `file:///*`, uzantı kurulumu kapalı, indirme dizini sabit.
  Chromium ailesi: `/etc/chromium` vb. yerine `policies/managed/deskhand-gorev.json` (URLBlocklist `file://*`,
  `chrome://*`, parola yöneticisi ve geliştirici araçları kapalı).
- **Oturum kopyası** (Firefox): logins.json, logins-backup.json, logins.db, key4.db, uzantılar ve verileri KOPYALANMAZ;
  çerez/oturum çerezi/depo YALNIZ izinli sitelerin (boşsa ÇEREZSİZ temiz profil); user.js `signon.rememberSignons=false`.
- **Onay**: kapsam `kart` olsa bile parola alanı + sistem istemi onayları AÇIK (`guvenlik.onaysiz_serbest` istisnası).
- **Savunma derinliği**: observe/read_text/screenshot, tarayıcı belgesi `file:`/`about:`/`chrome:`… ise reddeder (10).
- **claude argv**: `--tools ""` (yerleşik araç yok; kara liste ikinci katman), `--no-chrome`, `--max-turns`
  (`[gorev] azami_tur`, varsayılan 60). Ortam: `ANTHROPIC_*` silinir; `ENABLE_CLAUDEAI_MCP_SERVERS=false`,
  `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`. Geçici çalışma dizini `XDG_RUNTIME_DIR` altında.
- **Geçmiş**: `type_text` metni `[N karakter]`; görev metnindeki parola/kart kalıpları maskelenir; görev kutusunda "parola
  yazmayın" ipucu, Başlat'tan önce kısa onay (görev + izinli siteler + "yalnız tarayıcı").
- **Görev masaüstü (tek masaüstü mimarisinde ayrım)**: durum tek dosyada (`sanal.json`, `sanal.lock`, tek ses çıkışı,
  panel izleyicisi/Devral aynı kayda bakar) olduğundan görev AYRI bir masaüstü açmaz; bunun yerine (1) görünmez masaüstü
  AÇIKSA görev BAŞLAMAZ: `GorevHatasi(kod="masaustu_acik")` → panel "Görünmez masaüstü başka bir iş için açık; kapatıp
  başlatılsın mı?" sorar, onayla `masaustu_durdur()` ve görev temiz masaüstüyle başlar (önceki oturumların kipsiz
  Firefox/Dolphin pencereleri görevde YOK); (2) görev başlarken `RUNTIME_DIR/gorev-masaustu` işareti (sahip PID +
  başlangıç zamanı) yazılır, ÖNCE işaret sonra açık-masaüstü denetimi (yarış yok); görev kipinde açılan masaüstünün
  kaydı `"gorev": true`; (3) `gorev_kipi.masaustu_kapisi` her bağlantıda (arka_uc sanal/kwin, erişilebilirlik,
  `masaustu.baslat`, `masaustu_baslat`): görev kipi `gorev` işaretsiz masaüstünü KULLANAMAZ (14); kipsiz istemci
  (başka Claude oturumu, CLI `--background`) işaretli masaüstüne ya da işaret varken bağlanamaz/uygulama açamaz/masaüstü
  açamaz (14, "görev bitince yeniden deneyin"). Panel önizlemesi `gorev_kipi.GOZLEMCI=True` ile serbest. Görev bitince
  yalnız `gorev` işaretli masaüstü kapatılır, işaret kaldırılır.
- **Pencere sınırı** (`gorev_kipi.pencere_denetle`, `guvenlik.yasak_denetle` + okuma araçlarından): görev kipinde her
  girdi/okuma hedefi yalnız tarayıcı penceresi — sınıf beyaz listesi (firefox, navigator, chromium…) VE pencerenin
  süreç ikilisi (`/proc/PID/exe`; PID X-Resource/KWin'den, istemci yazamaz) tarayıcı. Sınıf tek başına yetmez (taklit
  edilebilir). Başka pencere (indirme panelinden "Aç" → Kate, Konsole…) → pencere kapatılır, süreci masaüstü kafesindeyse
  SIGKILL, günlüğe olay, Dur 10. Tüm ekran (pencere verilmeyen) okuma/girdi: yalnız ekranda tarayıcı dışı pencere yokken
  ve en az bir görev tarayıcı penceresi varken. Tarayıcı belgesi yasak adreste (`file:`, `jar:`, `about:preferences`
  dahil `about:*`) okuma da girdi de reddedilir.
- **Firefox ilkesi ek**: `browser.download.forbid_open_with` (kilitli true: indirilen dosya dış uygulamayla açılamaz),
  `always_ask_before_handling_new_types` false, `open_pdf_attachments_inline` false, `alwaysOpenPanel` false; Linux
  Firefox önce `/etc/firefox/policies`'e baktığından o dizin varsa aynı ilke oraya da bağlanır. WebsiteFilter
  MatchPattern sözdizimindedir (Firefox 160 WebsiteFilter.sys.mjs): `file:///*` geçerli; `file://*/*`, `jar:`,
  `about:` kalıpları GEÇERSİZ (Firefox atar) → `jar:file:` ve `about:preferences` için ilke yolu yok; adres denetimi
  (yukarıda) kapatır. Ölçüm: `tests/test_gorev_kipi.py` başsız Firefox + Marionette (ölçümde yalnız
  DisableDeveloperTools çıkarılır, çünkü o ilke uzaktan denetimi de kapatır).
- **Ad alanı**: görev kipinde `xdotool`, `kdotool`, `ydotool`, `wtype`, `xauth`, `xdg-open`, `gio`, `kioclient`,
  `kde-open` boş dosyayla örtülür (çalıştırılamaz); PATH `/usr/bin:/bin`.
- **Kimlik değişkenleri**: `gorev_kipi.KIMLIK_ORTAM_DENEN` (TOKEN, SECRET, PASSWORD, KEY, AUTH, COOKIE…) claude'un
  ortamından (yalnız `CLAUDE_CODE_OAUTH_TOKEN` kalır; claude girişini `~/.claude/.credentials.json`'dan okur), MCP
  sunucusunun ortamından (açılışta) ve uygulama ortamından (`ortam_tabani`) silinir.
- **Site listesi**: joker (`*`), tek başına genel son ek (`com`, `com.tr`, `co.uk`, `gov.tr`…; küçük liste
  `GENEL_SON_EKLER`) ve geçersiz ad RET; panel açık iletiyle görevi başlatmaz. Arayüz uyarısı: "Bu sitelerde ajan
  sizin adınıza işlem yapabilir (ayar değiştirme, gönderi, silme); güvenilmeyen sayfa içeriği ajanı kandırabilir."
- **İndirme klasörü** her görev başında boşaltılır. **Geçmiş**: `batch(steps=[{"text": …}])` gibi iç içe girdilerde
  gizli anahtarlar yinelemeli maskelenir.
- Kalan risk: görev sürerken kullanıcı CLI ile `deskhand masaustu durdur` diyebilir (yalnız kapatma; erişim yok).
  Pencere sınırı denetim anında uygulanır: Firefox'un açtığı yabancı pencere bir sonraki araç çağrısına kadar
  (milisaniye–saniye) ekranda yaşar; o arada kendi başına çalışabilir (ör. Kate) ama ad alanı (boş ev, XDG yok, girdi
  araçları örtülü) ve ilke (`forbid_open_with`) bu yolu zaten kapatır. `about:preferences` sayfası açılabilir ama
  okunamaz/girdi alamaz.

## 12. İnsan doğrulaması (CAPTCHA) devri: algıla, reddet, devret, devam et

**Politika (değişmez):** CAPTCHA / "insan olduğunuzu doğrulayın" sınamaları ÇÖZÜLMEZ ve atlatılmaz (görsel, sesli ya da
başka yolla). Deskhand yalnız algılar, ajan girdisini reddeder, kullanıcıya devreder, çözülünce devam eder.

- **Algı** (`deskhand/dogrulama_sinamasi.py`; `incele` saf; yalnız metin geçmesi YETMEZ). Kaynaklar: (1) gömülü belge
  (iframe) adresi: `google.com/recaptcha`, `hcaptcha.com`, `challenges.cloudflare.com`, `arkoselabs`/`funcaptcha`,
  `geetest` (görünmez reCAPTCHA v3 rozeti `size=invisible` ve hCaptcha `#frame=checkbox-invisible` muaf). `web.oku` her
  ÖGEYE ait belgenin adresini (`_belge_adres`) taşır: yalnız sınama belgesinin ögeleri işaretlenir (YouTube gömmesi,
  Stripe kart alanı, sohbet kutusu etkilenmez) ve o iframe'in TÜM kutusu sınama alanıdır (onay kutusunun yanındaki etikete
  tıklamak da kutuyu işaretler); (2) öge adı + rol: "I'm not a robot", "Ben robot değilim", "Verify you are human",
  "Slide to verify"… (çerçeve DIŞINDA en çok 6 sözcüklü etiket; "Require human verification" / "Move the slider to set the
  price" / "Enable CAPTCHA" ayarları sayılmaz), satıcı adı (reCAPTCHA, hCaptcha, Turnstile…) yalnız gömülü belgede;
  (3) klasik resimli metin CAPTCHA'sı: "Güvenlik kodu / Doğrulama kodu / captcha" adlı giriş alanı + yakında resim (ya da
  "resimdeki karakterler" ifadesi); SMS/e-posta/uygulama (2FA) bağlamındaki resimsiz kod alanı sayılmaz; (4) başlık
  "Just a moment…", "Attention Required"… TEK BAŞINA yetmez: sınama çerçevesi/ögesi ya da Cloudflare adresi (`/cdn-cgi/`,
  `__cf_chl`) ile birlikte sayfanın tamamı sınama olur (`cloudflare_interstitial`); (5) OCR: yalnız kısa satır, kalıp
  satırın ≥%60'ı (düşük güven). ÇÖZÜLMÜŞ sınama (işaretli onay kutusu, Turnstile "Success!") sayılmaz.
  Sonuç `human_verification: {detected, kind, window, hint}`; `observe`, `read_text`, `wait_for`, `click`, `type_text`,
  `press_key`, `drag` sonuçlarında. `read_text` iframe'lerin TAM adresini vermez (yalnız tür + alan adı); kritik
  bildirimde sayfa başlığı değil alan adı yazılır.
- **Durum**: pencere kimliği + başlık/adres anahtarıyla `RUNTIME_DIR/insan-dogrulama.json` (0600, flock) — CLI ve MCP
  süreçleri aynı kutuları görür. Dosya YALNIZ ENGEL EKLER: algılanmış sınama kutuları (`sinama`), uyarı bastırma
  (`bastir`) ve pencerenin son girdi zamanı (`girdi`; yalnız YENİDEN TARAMA zorlar). "Sınama yok" ve "okunamadı" kararları
  YALNIZ süreç belleğindedir (dosyaya yazılmaz, dosyadan OKUNMAZ; ~3 sn / ~10 sn): "engel yok" kararı için sürecin KENDİ
  taraması gerekir. Dosya her okunuşta doğrulanır (tip, 0 ≤ yaş ≤ TTL, önyükleme kimliği), ama kapıyı kalıcı açık tutmaya
  karşı güvence dosyanın doğruluğuna değil bu kurala dayanır: dosyaya sahte "yok" yazmak ya da sınama kaydını silmek kapıyı
  AÇMAZ (süreç yeniden tarar); en kötü ihtimal fazladan ret ya da tarama. Başlık/adres değişince ya da 300 sn sonra silinir.
  **Bayat kutu yok:** her girdi (tık, tuş, yazı, kaydırma, pencere taşıma/boyutlandırma/büyütme, erişilebilirlik eylemi) o
  pencerenin sınama kaydını "kirli" işaretler (son girdi zamanı, süreçler arası; masaüstü kipinde pencere bilinmediği için
  tüm pencereler); sonraki girdiden önce kayıt son girdiden eskiyse (ya da 15 sn'den eskiyse) sayfa YENİDEN taranır
  (kaydırma animasyonu için ~0,25 sn yerleşme beklenir). Kirli kayıt yeniden OKUNAMAZSA o pencerede TÜM fare girdisi
  reddedilir (`page_wide` gibi) ve klavyede Tab sonrası girdi + tek başına Boşluk/Enter reddedilir.
- **Reddetme (ÇEKİRDEK kapı)**: fare yollarının TEK ortak noktası `eylem.hassas_nokta` (koordinat, metin, öge, simge,
  renk, web, sürükleme başlangıcı; sürükleme bitişi ve `erisim._hassas_oge` ile `ogeye-yaz` de) `nokta_engeli`'ni çağırır:
  tıklanan NOKTA sınama kutusundaysa (ya da kısa metin sınama cümlesiyse) **Dur(18)** — gözlemsiz çağrı, CLI (`ekran
  click`), MCP ve akış adımları hep aynı kapıdan geçer. Klavye (`k_tus`/`k_yaz`/`k_bas`): sayfanın tamamı sınamaysa ya da
  ODAK sınama kutusundaysa (Tab+Boşluk ile işaretleme dahil) 18. Durum yoksa ve pencere tarayıcıysa girdiden ÖNCE bir kez
  taranır (tarama ~`hazir`; "yok" 10 sn önbellek). MCP'de ek olarak ref bayrağı (`!human-verification`) ve metin hedefi;
  `batch` adım hatasında `human_verification`. **kod 18**, `sent: nothing_sent`.
- **Devir** (`request_human(reason, window, timeout_s=600)`): KDE bildirimi (`mesgul.bildir`, kritik) + onay
  kanalında `tur="devir"` isteği (panel diyaloğu: **Devral** [yalnız arka plan masaüstü; panelin mevcut Devral'ı:
  önizleme + girdi aktarımı], **Bitti**, **Vazgeç**). Bekleme boyunca o masaüstüne ajan girdisi kapalıdır ([7]);
  istek yalnız panelden (SO_PEERCRED ile doğrulanmış kanal, §8: Bitti = izin) ya da sayfanın kendisinden (başta var
  olan sınama işareti sayfa OKUNURKEN ve ADRES değişmeden art arda 2 yoklamada yok → `resolved_by=challenge_cleared`;
  okunamayan sayfa ya da değişen adres "kayboldu" sayılmaz) kapanır; ajan kendi isteğini kapatamaz. Sonuç: `resolved |
  timeout | declined | unavailable`. `resolved` sonrası işaret hâlâ varsa `still_detected: true`; kullanıcı Bitti dedikten
  sonra AYNI sınama (adres + çerçeve kümesi) için uyarı ve yeniden çağrı bastırılır (`suppressed`; girdi kapısı AÇIK kalır).
  Kendiliğinden geçen sınamalar (Cloudflare ara sayfası, yönetilen Turnstile) için bildirimden önce ~10 sn yalnız
  yoklanır; bildirim panel canlı/gözetimli/DUR yoksa gönderilir, kullanıcı oyunda/tam ekrandaysa sessizdir. Atomik devir
  kaydı (eşzamanlı ikinci istek [7]); ret/zaman aşımından sonra aynı pencere için 60 sn içinde yeni istek ret
  (`retry_after_s`). `bekleyen_var` devir isteklerini 3600 sn'ye kadar canlı sayar (bekleme boyunca BAŞKA süreçlerin
  girdisi de kapalı). Günlük/geçmişte etiket `devir-tamam` ("onay izin" değil); "Bitti/Vazgeç/süre" ile diyaloğun açtığı
  Devral kapanır.
- **Okunamayan sayfa (fail-open yok):** erişilebilirlik ağacı okunamayan TARAYICI penceresinde (kapalı/yanıtsız, belge yok)
  Tab'dan sonra gelen girdi ve tek başına Boşluk/Enter ya da boşluk içeren yazı reddedilir (odak sınama kutusunda olabilir);
  sınama durumu VARKEN odak bilinemiyorsa (sorgu hata verdi, odakta kutulu öge yok) Boşluk/Enter/yazı içeren dizi reddedilir.
  Kapı taraması erişilebilirlik kapalıyken tarayıcı penceresi için süreç başına BİR kez `erisim_ac_garanti` çağırır. **kde'de
  yan etki:** bu, kullanıcının oturumunda erişilebilirliği (AT-SPI veri yolu `IsEnabled` + `toolkit-accessibility`) OTURUM
  GENELİNDE açar ve açık kalır (tüm uygulamalar erişilebilirlik ağacı üretir; küçük performans maliyeti); günlükte ve durum
  dizinindeki işaretle görünür, `deskhand a11y off` geri alır. Sanal (arka plan) masaüstünde yalnız o masaüstünün özel veri
  yolu etkilenir. Ham tuş kodları (`k:N`) yalnız 1-255 (0x100+ BTN_* fare düğmeleridir). Masaüstü kipinde (EKRAN) kapının
  sınadığı pencere kapıdan hemen sonra ve HER tık/basmadan önce yeniden denetlenir (imlecin altındaki pencere ve imleç aynı
  değilse Dur 3); çift/üçlü tık ve `tekrar>1` tek tek gönderilir, sürüklemede `buttondown` öncesi de denetlenir.
- **Tehdit modeli:** kapı, kazara ya da sayfa metniyle kandırılmış (prompt injection) bir ajanın CAPTCHA etkileşimini
  durdurmak için EN-İYİ-ÇABA bir ikinci hattır; asıl güvence ajanın kuralıdır (CAPTCHA çözülmez, `request_human` ile
  devredilir). Kabuğu olan bir ajan `girdi.sock`'a doğrudan yazarak bu kapıları (ve diğer araç düzeyi kapıları) zaten
  atlayabilir; bu, belgedeki mevcut genel sınırdır (§2, §8) ve bu kapıların kapsamı dışındadır.
- **Sınırlar:** yeni CAPTCHA türleri algıdan kaçabilir; ağaç okunamazsa (erişilebilirlik kapalı/yanıtsız) algı yoktur — bu
  durumda tarayıcı yolları konumu doğrulanamayan ögeye tıklamaz (fail-closed) ve yukarıdaki klavye kuralları devreye girer.
  Klavye odak sorgusu tarayıcı sayfaları içindir.
