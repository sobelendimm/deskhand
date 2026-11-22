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
  kendi.py         ajanın kendi istemcisi: ata süreç kümesi (/proc), tmux istemcileri, ön plan süreci (§4)
  ucbirim.py       uçbirim Enter kapısı: giriş satırı okuma (AT-SPI/OCR) + yazı tamponu (§4)
  ocr.py           oku, satirla, ara, derin_oku, önbellek, ön işleme
  gorsel.py        simge (NCC), renk alanları, ızgara
  eylem.py         tikla/yaz/tus/kaydir/bas/surukle/dizi: arka uçtan BAĞIMSIZ üst katman
  akis.py, erisim.py (AT-SPI), uygulama.py (ac)
  web.py           web sayfası ögeleri: tarayıcının erişilebilirlik ağacından okuma (§9); MCP read_text(source="web"),
                   CLI `web`, click-element'in web yolu
  cli.py           argparse; komut adları İngilizce + Türkçe takma adlar
  arka_uc/__init__.py   ArkaUc arayüzü + sec(hedef)
  arka_uc/kde.py        kdotool + dotool + kscreen-doctor (+ spectacle yalnız görüntü kurtarması)
  arka_uc/kde_goruntu.py  ekran görüntüsü: yardimci/deskhand-goruntu (C, sd-bus) → KWin ScreenShot2
                        (org.kde.KWin.ScreenShot2, ham piksel borudan; ~8 ms). Yetki: KWin < 6.8 çağıranın
                        /proc/<pid>/exe yolunu Exec= ilk sözcüğü aynı .desktop dosyasıyla eşleştirir ve
                        X-KDE-DBUS-Restricted-Interfaces'te arayüzü arar → install.sh
                        ~/.local/share/applications/deskhand-goruntu.desktop kurar (KWin 6.8 denetimi kaldırdı).
                        Yardımcı derlenmemiş/yetkisizse iç kurtarma: spectacle (günlüğe yazılır).
  arka_uc/sanal.py      Xvfb + python-xlib
  masaustu.py      sanal masaüstü yaşam döngüsü
  pano_sahibi.py   sanal masaüstünün CLIPBOARD seçimini sunan yardımcı süreç (kafeste, ilk pano yazımında başlar)
  oturum/          oturum köprüsü (bkz. docs/SESSIONS.md)
  mesgul.py        kullanıcı meşgul mü (oyun / film) koruması
  onay.py          insan onayı protokolü (§8): istek dosyası + panelin doğrulanmış onay kanalı (Unix soketi)
  onay_hedef.py    onay verilen hedefin özeti (kimlik, başlık, geometri, bölge görüntüsü) + onay sonrası doğrulama (§8)
  girdi_merkezi.py panelin içinde hazır bekleyen tek dotool + RUNTIME_DIR/girdi.sock (Qt'siz; §2, §4)
  gui/             panel, tepsi, onay diyaloğu
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
`pid(k)`, `etkinlestir(k)`, `etkinlik()`, `oturum_veri_yolu()` (org.a11y.Bus'ın oturum veri yolu; None = kullanıcının
oturumu), `ekran_korumasi(ne)` (kde: oyun/film → 15; girdi göndermeyen ama uygulamayı etkileyen yollar çağırır).

Pencere yönetimi (isteğe bağlı; varsayılan = desteklenmiyor → Dur 9): `tasi(k, x, y)`, `boyutlandir(k, g, y)`,
`kucult(k)`, `buyut(k)` (çalışma alanını kapla), `geri_yukle(k)` (küçültülmüş/büyütülmüşten normale); dönüş None.
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
INCR; çalışma klasöründe 0600 `pano.sock`); okuma süreç içinde. İki arka uç birbirinin panosuna dokunmaz.

`baslat(argv, env, cikti)`: `env`, her iki arka uçta da `os.environ`'a EKLENECEK/değişecek değişkenlerdir (tam ortam
değil). Sanalda masaüstü değerleri (DISPLAY, özel D-Bus, ses...) her zaman üstün gelir.

**Girdi nesnesi:** `gonder(k, desen, *satirlar)` (her çağrıdan önce `guvenlik.denetle`, hemen ardından
`guvenlik.girdi_seviye_denetle(k, satirlar)`: uygulama erişim seviyesi, §4), `zorla(satir)` (bırakma;
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
`--arka` genel bayrağı / `DESKHAND_HEDEF=arka|on|oto` / kimlik `arka:` öneki → `arka_uc.sec()`.
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
  `riskli_komut` metni kabuk kurallarıyla sözcüklere ayırır (tırnak/ters bölü kaldırılır, `$'…'` açılır, `$(…)`/`` `…` ``/
  `<(…)` içi ayrıca denetlenir); kabuk anahtar sözcükleri (`{ } ! if then do else elif while until time`), atamalar ve
  bilinmeyen `$DEĞİŞKEN` komut adı atlanır, aynı metindeki atama çözülür (`S=sudo; $S reboot`), küme açılımı
  (`{sudo,reboot}`), `busybox`/`toybox X` → X, sarmalayıcıların argümanlı seçenekleri (`env -u AD`, `nice -n 5`,
  `timeout -s 9 5`), `env -S`, `find … -delete` / `-exec rm`, `sh/bash -c` (ve `-lc` gibi kümeler), `eval`, `python -c` /
  `perl -e` / `ruby -e` / `node -e` kodunda dosya silme, komut çalıştırma ya da dinamik kod (`__import__`, `eval`…).
- **Uçbirim ENTER KAPISI** (`deskhand/ucbirim.py`; parça parça yazılmış komut: `sud` + `o reboot` + Enter). Uçbirim
  sınıflı pencereye satırı çalıştıran bir tuş (enter, kpenter, linefeed, `x:Return`, `k:28`, ctrl+j/ctrl+m/ctrl+o; yazının
  içindeki `\n`) gitmeden HEMEN önce o anki giriş satırı okunur — erişilebilirlik ZATEN açıksa AT-SPI (rolü `terminal` olan
  ögenin imleç satırı + önceki iki satır; erişilebilirlik bunun için açılmaz), yoksa pencerenin OCR'ı (en alttaki üç yazılı
  satır; istem işaretinden sonrası ve sarılmış satırların birleşimi aday) — ve `riskli_komut`'tan geçer; yıkıcıysa onay
  (yoksa 10). Yazının içindeki Enter'lar için kapı yazmadan ÖNCE sorulur (satır = okunan/tampon + ilk satır). Yedek TAMPON:
  `RUNTIME_DIR/ucbirim/<sha1(arka uç:pencere:pid)>.json` (0600, dizin 0700, flock): yazdırılabilir tuşlar ve `type`
  eklenir, BackSpace siler; Enter/ctrl+c/ctrl+u/Esc temizler; ok tuşları, ctrl+a/e/r/w, Tab, tık, orta tık, yapıştırma
  "kirli" yapar. Yeni pencere, başka uçbirim penceresine geçiş ve 120 sn hareketsizlik de "kirli" yapar (bilinçli: temiz
  saymak aradaki insan düzenlemesini ve parçalı yazmayı gözden kaçırırdı). Kirliyken satır okunamıyorsa Enter onay ister.
  Yazılırken onaylanmış komut (`--onayli` ya da panel) aynı satırda Enter'da yeniden sorulmaz. Ön plandaki süreç kabuk
  değilse (pencere PID → uçbirimin çocukları → `/proc/<kabuk>/stat` tpgid; vim, less, REPL) kapı uygulanmaz; ssh, tmux,
  kapsayıcı kabuğu (docker/podman/distrobox…) ise uygulanır; PID bilinmiyorsa uygulanır. Kapsanan yollar: `tus`/`bas`,
  `yaz` (harf harf + yapıştırarak), `dizi`/akış adımları, AT-SPI değer yazma.
- **Ajanın kendi istemcisi** (`deskhand/kendi.py`): Deskhand süreci (CLI ve MCP sunucusu) `/proc/<pid>/stat` ppid ile
  1'e kadar yürür (oturum altyapısı — systemd, kwin, plasmashell, krunner… — hariç); MCP sunucusunda küme 15 sn'de bir
  tazelenir. Penceresinin sahibi PID'i (kde: `kdotool getwindowpid`; sanal: `_NET_WM_PID`) bu kümedeyse o pencereye HER
  girdi 10 ("ajanın kendi istemcisi"; ajan kendi izin istemini onaylayamasın); okuma/ekran görüntüsü serbest. Uçbirimler çoğu
  zaman TEK süreçte çok pencere tutar (Ghostty, Konsole): o sürecin TÜM pencereleri kapsanır. Zincirde tmux varsa `$TMUX`
  soketiyle salt okunur `tmux list-clients -F '#{client_pid}'` → istemcilerin ataları (öykünücü) eklenir; çözülemezse
  (screen, zellij, dtach, tmux sorgusu başarısız) TÜM uçbirim sınıflı pencereler (kde). PID'i bilinmeyen pencereler (kde):
  ortam ipuçları (`KONSOLE_DBUS_WINDOW`, `WINDOWID`, `TERM_PROGRAM`, `GHOSTTY_RESOURCES_DIR`, `KITTY_PID`,
  `ALACRITTY_WINDOW_ID`) ve zincirdeki öykünücünün adı → o sınıftaki PID'siz uçbirim pencereleri de. ssh üzerinden bağlanan
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
- **Yapıştırma = pano okuma** (kde): `ctrl+v`, `ctrl+shift+v`, `shift+insert` ve orta tık (birincil seçim) kullanıcının
  panosunu ajanın görebileceği yere taşır: pano boş değilse ve Deskhand'in bu oturumda yazdığı metin değilse
  (`guvenlik.kendi_pano_ekle/kendi_pano_mu`: süreç belleği + `RUNTIME_DIR/pano-ozetleri`, 0600, yalnız sha256) onay ister
  (okunamıyorsa da). Deskhand'in kendi yapıştırarak yazma yolu (`eylem._yapistirarak_yaz`) muaftır. Sanal masaüstünün
  panosu ayrıdır: denetim yok.
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
  `--command`. Argümanlar yalnız belge: http/https URL'si (sorgudaki `=` serbest), yerel `file://` URL'si ya da var
  olan dosya/klasörün MUTLAK yolu; `-` ile başlayan, `=` içeren (URL dışı), başka şemalı, denetim karakterli,
  çalıştırılabilir dosya ya da `.desktop` gösteren argüman → 10 (en çok 16). Başlatılan sürecin ortamına ajan
  değişken veremez (yalnız oturum politikasının `env_ek`'i). Görünmez masaüstünde oturum köprüsü yoksa hiçbir
  uygulama başlatılmaz (10). Shebang'li betik uygulamalar (Exec = betiğin yolu) meşru sayılır; GUI içinden kabuk
  açan uygulamalar (dosya yöneticisinin gömülü uçbirimi, IDE konsolu) bu denetimin kapsamı dışındadır.
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
- İnsan önceliği (12): kde arka ucunda kullanıcı klavye/fareyi kullanıyorsa; sanalda yalnız "Devral" açıkken.
- Pencere yönetimi, pencere kapatma ve (kde) pano yazma da insan önceliğine (12) uyar (`guvenlik.insan_onceligi`;
  pano: CLI `pano yaz` ve MCP `clipboard(write)` → `api.pano_yaz`); kapatma DUR'a (13) bakar. Deskhand'in panoya yazdığı
  metinlerin özeti TEK kaynaktadır (`guvenlik.kendi_pano_ekle/kendi_pano_mu`): CLI, MCP `clipboard(read)` ve yapıştırma
  onayı aynı listeye bakar.
- Kullanıcı meşgulken ön plan yok (15): kde arka ucu girdi, pencere öne getirme ve uygulama açmadan önce
  `mesgul.ekran_korumasi()` çağırır. Etkin pencere tam ekran / oyun biçimli ya da MPRIS'te video çalıyorsa
  Dur(15). İstisna yalnız kullanıcının açık izni (`--ekranimda`, `DESKHAND_EKRANIMDA=1` ya da bildirimdeki
  "Ekranımda yap" düğmesi → 10 dk). Sanal masaüstü etkilenmez.
- **AT-SPI çerçevesi yalnız hedef pencerenin PID'inden** seçilir (çok süreçli uygulamada aynı süreç ağacından: ata/torun);
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
- **Oturum köprüsü.** Arka plandaki uygulamaların kullanıcının hesap oturumlarını kullanabilmesi, uygulama başına
  bir politikayla (kopya / paylas / bekle / on / kapali) yönetilir; uygulama kullanıcı oturumunda açık ve
  arka planda açılamıyorsa kod 16 döner (bkz. docs/SESSIONS.md).
- **Gözlem + ref + toplu adım (Faz 10).** MCP ajanı `observe` ile numaralı ögeler ve `ref` alır; `ref` ile eylemde öge
  güncel ağaçta KİMLİĞİYLE yeniden doğrulanır, sonra MEVCUT güvenli yoldan gider. `batch` aynı araç çekirdeklerini
  sırayla çağırır; paralel kapı yazılmaz. Her girdi sonucu `effect` taşır, her hata `sent` + `next` (§10).

## 8. Onay protokolü (arayüz + MCP + CLI ortak)
Hassas eylem (hassas düğme, ödeme sayfası, yasak dışı ama riskli `ac`, oturum aktarımı) için onay YALNIZ insandan:
- `deskhand/onay.py`: `iste(eylem, hedef, ayrinti, masaustu, sure=120) -> bool`.
  Panel kaydı: `RUNTIME_DIR/panel.pid` {pid, baslangic (/proc/<pid>/stat 22. alan), exe (/proc/<pid>/exe), zaman}.
  **Onay kanalı:** panel `RUNTIME_DIR/onay/kanal.sock` Unix soketini dinler (0600, dizin 0700; `panel_kaydet` açar,
  `panel_sil` kapatır; Qt'siz iş parçacıklı sunucu). İsteyen ÖNCE kanala bağlanır ve karşı tarafı doğrular: soket
  dosyası ve dizin kendisinin ve başkalarına kapalı; SO_PEERCRED uid = kendi uid, pid = panel.pid'deki pid, aynı
  başlangıç zamanı ve aynı exe. Doğrulanamazsa red ("onay kanalı doğrulanamadı", günlüğe neden).
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
toplam 16, ömür 120 sn. Öge kimliği: erişilebilirlik ögesinde veri yolu adı + nesne yolu (BİRLİKTE; `_tara` libatspi
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
**Sonuç sözleşmesi.** Girdi araçlarının sonucu `effect`: `confirmed` (beklenen değişim görüldü: tıklanan ref ögesinin
checked/selected/expanded durumu değişti, yazılan metin değişen bölgenin OCR'ında görüldü ya da değer geri okundu,
kaydırmada görünüm değişti, pencere geometrisi değişti), `changed`, `no_change` (döngü kesiciyle uyumlu), `unverifiable`
(ölçülemedi: kde'de `via=action`, `verify=false`), `refused` (hata ve hiçbir şey gönderilmedi). Hata sonucu (`isError`)
metni: `[kod] ne oldu` + `sent: nothing_sent | maybe_partial` + `next: ne yapmalı (araç adıyla)`; aynısı
`structuredContent.error` {code, message, reason, next}, `sent`, `effect` alanlarında. `sent` sayacı (`gonderim.py`)
`api.arka()` girdi nesnesinin `gonder()`/`ham()` dönüşünde ve erişilebilirlik eylemi/değer yazma çağrısından hemen önce
artar; bırakma (`zorla`) sayılmaz. outputSchema: `observe`, `batch`, `wait_for`, `click` için alanlı TypedDict, diğer girdi
araçlarında genel nesne; şemalardaki otomatik `title` metinleri tools/list'i küçültmek için silinir.
**Sınırlar.** Tarayıcı penceresinde observe yalnız sayfayı (belge) listeler: adres çubuğu/sekmeler için `press_key`
(ctrl+l) ya da `read_text(source="tree")`. Web ögeleri yalnız görünenler (kaydırma alanı dışındakiler `read_text(source=
"web", hidden=true)`). Sistem istemi penceresinde ref/text/element tıklaması pencere denetiminde onaysız istem olarak
reddedilir (10; koordinatlı tık onay sorar). `structuredContent` metinden büyüktür (href, eylem adları): istemci ikisini
de modele veriyorsa token maliyeti artar.
