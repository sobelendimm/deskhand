/* deskhand-eis: KWin EIS (libei) ile girdi gönderen KALICI yardımcı. Arka plan KWin oturumunun (kwin_wayland
 * --virtual) girdi yolu: stdin'den dotool satır dilini (docs/ARCHITECTURE.md §2) okur, her satıra stdout'ta TEK satır
 * yanıt verir. Gerçek oturuma girdi göndermez: bağlandığı veri yolu --bus ile AÇIKÇA verilen özel adrestir.
 *
 * Kullanım:   deskhand-eis --bus unix:path=/özel/veri/yolu/bus
 *   --bus zorunlu; ortamdaki DBUS_SESSION_BUS_ADDRESS DEVRALINMAZ (argüman yoksa çıkış 2). Adres kullanıcının gerçek
 *   oturum veri yolu (/run/user/UID/bus) ise ya da "unix:path=" biçiminde değilse reddedilir (çıkış 2).
 *
 * Açılışta: sd-bus ile adrese bağlan → org.kde.KWin.EIS.RemoteDesktop.connectToEIS(yetenekler=3) → fd → libei
 * gönderici bağlamı → seat'e pointer + pointer-absolute + keyboard + button + scroll → aygıtlar RESUMED olunca
 * start_emulating. Hazır olunca stdout'a  "hazir GENİŞLİK YÜKSEKLİK"  (mutlak aygıtın bölgelerinin sınır kutusu).
 * Başarısızsa "hata <neden>" yazıp çıkış koduyla çıkar.
 *
 * Komutlar (her biri bir satır; yanıt: "tamam" ya da "hata <neden>"):
 *   mouseto FX FY            mutlak konum; FX/FY [0..1] kesir, TÜM ekran (bölgelerin sınır kutusu)
 *   mousemove DX DY          göreli (son konum + piksel)
 *   click left|right|middle  bas + bırak          buttondown B / buttonup B   basılı tut / bırak
 *   key K [K2 ...]           akor: ctrl+s, enter, ctrl+shift+a; K: dotool/evdev adı (enter, leftshift, pageup, f5...),
 *                            k:KOD (evdev kodu), x:Keysym, ya da tek karakter (A, @, ı: klavye düzeninden)
 *   keydown K / keyup K      basılı tut / bırak
 *   type METİN               metni yaz (satırın geri kalanı, birebir; kaçış yok): karakter → tuş (+Shift/AltGr)
 *                            eşlemesi aygıtın verdiği xkb tuş haritasından (libxkbcommon) ters aramayla. Haritada
 *                            olmayan karakter varsa HİÇBİR ŞEY yazılmaz: "hata yazilamaz <karakterler>" (çağıran
 *                            pano yoluna düşebilsin). Satır sonu dilde yok: Python tarafı "\n"yi `key enter`e böler.
 *   yazilabilir METİN        girdi göndermez; "tamam" (hepsi yazılabilir) | "yazilamaz <karakterler>"
 *   wheel N / hwheel N       kaydır; N artı = yukarı / sağ (dotool gibi), N çentik
 *   typedelay MS typehold MS keydelay MS keyhold MS    (varsayılan 2 8 2 8, dotool gibi)
 *   hareketbekle MS          hareketten sonraki ilk düğme/kaydırma öncesi bekleme (varsayılan 0)
 *   birak                    basılı tutulan HER ŞEYİ hemen bırak
 *   basili                   (tanılama) "tamam tus=KOD,… dugme=KOD,…": bu bağlantının basılı tuttukları
 *   bilgi                    "tamam GENİŞLİK YÜKSEKLİK DÜZEN"
 *   cik                      hepsini bırak, çık
 *
 * BIRAKMA GÜVENCESİ: basılı tuş/düğmeleri izler; stdin EOF, SIGTERM/SIGINT/SIGHUP, EIS kopması ve her hata çıkışında
 * hepsi bırakılır (EIS kopmuşsa gönderilemez; basılı kalanı o hâlde KWin'in kendisi bırakır, bkz. tests).
 * AYGIT DEĞİŞİMİ: KWin düzen değişince klavye aygıtını kaldırıp yenisini verir: kaldırılan aygıtla basılı kalanlar yeni
 * aygıt RESUMED olunca ondan bas+bırak ile temizlenir; aygıt yokken olay gönderilmez (en çok AYGIT_YEDEK_MS beklenir);
 * tuş haritası her zaman yeni aygıtın EIS keymap'inden okunur.
 * İŞARETÇİ: hareketten sonraki ilk düğme/kaydırma olayı `hareketbekle` kadar bekler (varsayılan 0: KWin 6.8.3'te
 * gereksiz ölçüldü); imleç zaten hedefteyse önce 1 px komşuya gidilir ("park edilmiş imleç": altına yeni pencere geldiyse aynı
 * konuma hareket olay üretmezdi). Kaydırma: ayrık 120'lik birim + sonda scroll_stop.
 * KAPANIŞ: bırakmalar → ei_ping/PONG eşitlemesi → ei_unref → RemoteDesktop.disconnect(çerez).
 * Çıkış kodları: 0 normal (EOF / cik / sinyal) · 1 kullanım · 2 --bus yok/yasak · 3 D-Bus/EIS bağlantı hatası ·
 *   4 aygıtlar hazır olmadı · 5 EIS koptu.
 * Derleme: make -C deskhand/yardimci deskhand-eis  (libei-1.0, xkbcommon, libsystemd). */
#define _GNU_SOURCE
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <libei.h>
#include <limits.h>
#include <linux/input-event-codes.h>
#include <math.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <systemd/sd-bus.h>
#include <time.h>
#include <unistd.h>
#include <xkbcommon/xkbcommon.h>

#define HIZMET "org.kde.KWin"
#define NESNE "/org/kde/KWin/EIS/RemoteDesktop"
#define ARAYUZ "org.kde.KWin.EIS.RemoteDesktop"
#define YETENEK_KLAVYE_FARE 3
#define SATIR_AZAMI 65536
#define HAZIR_BEKLEME_MS 8000
#define AYGIT_AZAMI 16
#define BASILI_AZAMI 64
#define EVDEV_SHIFT KEY_LEFTSHIFT
#define EVDEV_ALTGR KEY_RIGHTALT
/* hareketten sonraki ilk düğme/kaydırma öncesi bekleme (ms; `hareketbekle MS` ile değişir). Bir rakip KWin'in işaretçi
 * odağını eşzamansız uyguladığını bildiriyor; KWin 6.8.3'te ölçüldü: 50 hızlı iki-pencere tıkında 0 yanlış yüzey,
 * bekleme her tıka +20 ms ekliyordu → varsayılan 0 (gerekirse açılır) */
static int hareket_dugme_ms = 0;
#define AYGIT_YEDEK_MS 600   /* aygıt değişiminde (kaldırıldı → yenisi RESUMED) olay göndermeden önce en çok bekleme */

struct tus_ad { const char *ad; int kod; };
static const struct tus_ad TUS_ADLARI[] = {
#include "deskhand-eis-tuslar.h"
};
/* dotool/xdotool takma adları (Python tarafı bunları zaten çevirir; yine de kabul et) */
static const struct tus_ad TAKMA[] = {
    {"return", KEY_ENTER}, {"escape", KEY_ESC}, {"page_up", KEY_PAGEUP}, {"prior", KEY_PAGEUP},
    {"page_down", KEY_PAGEDOWN}, {"next", KEY_PAGEDOWN}, {"del", KEY_DELETE}, {"ins", KEY_INSERT},
    {"bksp", KEY_BACKSPACE}, {"print", KEY_SYSRQ}, {"control", KEY_LEFTCTRL}, {"ctrl", KEY_LEFTCTRL},
    {"shift", KEY_LEFTSHIFT}, {"alt", KEY_LEFTALT}, {"super", KEY_LEFTMETA}, {"meta", KEY_LEFTMETA},
    {"win", KEY_LEFTMETA}, {"altgr", KEY_RIGHTALT},
};

/* ------------------------------------------------------------------ durum */

struct aygit { struct ei_device *d; bool aktif; };
static struct ei *ei;
static struct aygit aygitlar[AYGIT_AZAMI];
static int aygit_n;
static unsigned emulasyon_no;
static volatile sig_atomic_t sinyal_geldi;
static int sinyal_boru[2] = {-1, -1};
static bool koptu, cikis_istendi;
static int typedelay = 2, typehold = 8, keydelay = 2, keyhold = 8;

static int basili_tus[BASILI_AZAMI], basili_tus_n;
static int basili_dugme[8], basili_dugme_n;
static double son_x = -1, son_y = -1; /* son mutlak konum (mousemove için) */
static long son_hareket_ms = -1000000;  /* son işaretçi hareketinin zamanı (hareket→düğme beklemesi) */
/* klavye/işaretçi aygıtı KALDIRILDIĞINDA (KWin düzen değişince klavyeyi değiştirir) o aygıtla basılı olanlar: yeni aygıt
 * RESUMED olunca yeni aygıttan bas+bırak ile temizlenir (KWin kaldırılan aygıtın basılı düğmesini bırakmayabilir) */
static int artik_tus[BASILI_AZAMI], artik_tus_n;
static int artik_dugme[8], artik_dugme_n;
static sd_bus *veri_yolu;  /* connectToEIS çağrısının veri yolu: kapanışta disconnect(çerez) */
static int eis_cerez;
static bool pong_geldi;
static struct ei_device *son_klavye, *son_dugme; /* tuş/düğme olaylarının en son gönderildiği aygıtlar */

static void izle_ekle(int *dizi, int *n, int azami, int kod);
static int tus_gonder(int kod, bool bas);
static int dugme_gonder(int kod, bool bas);
static void artik_temizle(struct ei_device *d);

/* klavye haritası: karakter/keysym → (evdev kodu, gereken değiştirici) */
struct eslem { uint32_t cp; xkb_keysym_t sym; int kod; int mod; }; /* mod: bit0 Shift, bit1 AltGr */
#define MOD_SHIFT 1
#define MOD_ALTGR 2
static struct eslem *eslemler;
static size_t eslem_n, eslem_kap;
static struct xkb_context *xkb_baglam;
static char duzen_adi[64] = "?";

/* ------------------------------------------------------------------ yardımcılar */

static void yanit(const char *bicim, ...) __attribute__((format(printf, 1, 2)));
static void yanit(const char *bicim, ...) {
    va_list a;
    va_start(a, bicim);
    vprintf(bicim, a);
    va_end(a);
    putchar('\n');
    if (fflush(stdout) != 0) cikis_istendi = true; /* okuyan kapandı: bırak ve çık */
}

static void sinyal_isle(int s) {
    (void)s;
    sinyal_geldi = 1;
    int e = errno;
    if (sinyal_boru[1] >= 0) (void)!write(sinyal_boru[1], "x", 1);
    errno = e;
}

static long simdi_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1000L + t.tv_nsec / 1000000L;
}

static int popcount_mod(int m) { return (m & 1) + ((m >> 1) & 1); }

/* ------------------------------------------------------------------ aygıtlar ve olaylar */

static struct aygit *aygit_bul(struct ei_device *d) {
    for (int i = 0; i < aygit_n; i++)
        if (aygitlar[i].d == d) return &aygitlar[i];
    return NULL;
}

/* yeteneği olan, RESUMED bir aygıt (tercih: verilmişse o, yoksa ilk) */
static struct ei_device *rol(enum ei_device_capability c, struct ei_device *tercih) {
    if (tercih) {
        struct aygit *a = aygit_bul(tercih);
        if (a && a->aktif && ei_device_has_capability(tercih, c)) return tercih;
    }
    for (int i = 0; i < aygit_n; i++)
        if (aygitlar[i].aktif && ei_device_has_capability(aygitlar[i].d, c)) return aygitlar[i].d;
    return NULL;
}
static struct ei_device *mutlak_aygit(void) { return rol(EI_DEVICE_CAP_POINTER_ABSOLUTE, NULL); }
static struct ei_device *dugme_aygit(void) { return rol(EI_DEVICE_CAP_BUTTON, mutlak_aygit()); }
static struct ei_device *kaydirma_aygit(void) { return rol(EI_DEVICE_CAP_SCROLL, mutlak_aygit()); }
static struct ei_device *klavye_aygit(void) { return rol(EI_DEVICE_CAP_KEYBOARD, NULL); }

static void eslem_ekle(uint32_t cp, xkb_keysym_t sym, int kod, int mod) {
    if (eslem_n == eslem_kap) {
        eslem_kap = eslem_kap ? eslem_kap * 2 : 512;
        struct eslem *y = realloc(eslemler, eslem_kap * sizeof *y);
        if (!y) return;
        eslemler = y;
    }
    eslemler[eslem_n++] = (struct eslem){cp, sym, kod, mod};
}

/* aygıtın xkb haritasından (düzen 0) tüm (tuş, seviye) → (karakter, keysym, Shift/AltGr) eşlemlerini çıkar */
static void harita_kur(struct ei_device *kbd) {
    struct ei_keymap *km = ei_device_keyboard_get_keymap(kbd);
    eslem_n = 0;
    snprintf(duzen_adi, sizeof duzen_adi, "?");
    if (!km || ei_keymap_get_type(km) != EI_KEYMAP_TYPE_XKB) return;
    size_t boy = ei_keymap_get_size(km);
    int fd = ei_keymap_get_fd(km);
    void *m = mmap(NULL, boy, PROT_READ, MAP_PRIVATE, fd, 0);
    if (m == MAP_FAILED) return;
    char *metin = malloc(boy + 1);
    if (!metin) { munmap(m, boy); return; }
    memcpy(metin, m, boy);
    metin[boy] = 0;
    munmap(m, boy);
    if (!xkb_baglam) xkb_baglam = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
    struct xkb_keymap *xk = xkb_baglam ? xkb_keymap_new_from_string(xkb_baglam, metin, XKB_KEYMAP_FORMAT_TEXT_V1,
                                                                    XKB_KEYMAP_COMPILE_NO_FLAGS) : NULL;
    free(metin);
    if (!xk) return;
    const char *ad = xkb_keymap_layout_get_name(xk, 0);
    snprintf(duzen_adi, sizeof duzen_adi, "%s", ad ? ad : "?");
    for (char *c = duzen_adi; *c; c++) if (*c == ' ') *c = '_';

    xkb_mod_index_t i_shift = xkb_keymap_mod_get_index(xk, XKB_MOD_NAME_SHIFT);
    xkb_mod_index_t i_l3 = xkb_keymap_mod_get_index(xk, "Mod5");
    xkb_mod_mask_t m_shift = i_shift == XKB_MOD_INVALID ? 0 : 1u << i_shift;
    xkb_mod_mask_t m_l3 = i_l3 == XKB_MOD_INVALID ? 0 : 1u << i_l3;
    /* değiştirici tuşların fiziksel yeri: sol Shift ve sağ Alt (AltGr = ISO_Level3_Shift) gerçekten o işi yapıyor mu */
    const xkb_keysym_t *s;
    bool shift_ok = xkb_keymap_key_get_syms_by_level(xk, EVDEV_SHIFT + 8, 0, 0, &s) == 1 && s[0] == XKB_KEY_Shift_L;
    bool altgr_ok = xkb_keymap_key_get_syms_by_level(xk, EVDEV_ALTGR + 8, 0, 0, &s) == 1 &&
                    (s[0] == XKB_KEY_ISO_Level3_Shift || s[0] == XKB_KEY_Mode_switch);

    for (xkb_keycode_t kc = xkb_keymap_min_keycode(xk); kc <= xkb_keymap_max_keycode(xk); kc++) {
        xkb_level_index_t seviye = xkb_keymap_num_levels_for_key(xk, kc, 0);
        for (xkb_level_index_t lv = 0; lv < seviye; lv++) {
            const xkb_keysym_t *syms;
            if (xkb_keymap_key_get_syms_by_level(xk, kc, 0, lv, &syms) != 1) continue;
            xkb_mod_mask_t maskeler[8];
            size_t mn = xkb_keymap_key_get_mods_for_level(xk, kc, 0, lv, maskeler, 8);
            int mod = -1;
            for (size_t j = 0; j < mn && mod < 0; j++) { /* yalnız Shift/AltGr'dan oluşan ilk maske (Lock/NumLock/Ctrl dışlanır) */
                xkb_mod_mask_t mk = maskeler[j];
                if (mk & ~(m_shift | m_l3)) continue;
                int mm = ((mk & m_shift) ? MOD_SHIFT : 0) | ((mk & m_l3) ? MOD_ALTGR : 0);
                if (((mm & MOD_SHIFT) && !shift_ok) || ((mm & MOD_ALTGR) && !altgr_ok)) continue;
                mod = mm;
            }
            if (mod < 0) continue;
            uint32_t cp = xkb_keysym_to_utf32(syms[0]);
            if (cp < 0x20 || cp == 0x7f) cp = 0; /* denetim karakterleri type ile yazılmaz (\n, \t özel) */
            eslem_ekle(cp, syms[0], (int)kc - 8, mod);
        }
    }
    xkb_keymap_unref(xk);
}

/* karakter (cp > 0) ya da keysym (cp == 0) için en az değiştiricili eşlem; yoksa NULL */
static const struct eslem *eslem_ara(uint32_t cp, xkb_keysym_t sym) {
    const struct eslem *iyi = NULL;
    for (size_t i = 0; i < eslem_n; i++) {
        const struct eslem *e = &eslemler[i];
        if (cp ? e->cp != cp : e->sym != sym) continue;
        if (!iyi || popcount_mod(e->mod) < popcount_mod(iyi->mod)) iyi = e;
    }
    return iyi;
}

/* kaldırılan aygıtla basılı kalanları YENİ (RESUMED) aygıttan bas+bırak ile temizle */
static void artik_temizle(struct ei_device *d) {
    if (artik_tus_n && ei_device_has_capability(d, EI_DEVICE_CAP_KEYBOARD)) {
        for (int i = 0; i < artik_tus_n; i++) {
            if (tus_gonder(artik_tus[i], true) == 0) tus_gonder(artik_tus[i], false);
        }
        artik_tus_n = 0;
    }
    if (artik_dugme_n && ei_device_has_capability(d, EI_DEVICE_CAP_BUTTON)) {
        for (int i = 0; i < artik_dugme_n; i++) {
            if (dugme_gonder(artik_dugme[i], true) == 0) dugme_gonder(artik_dugme[i], false);
        }
        artik_dugme_n = 0;
    }
}

static void olaylari_isle(void) {
    ei_dispatch(ei); /* kopma EI_EVENT_DISCONNECT olarak gelir */
    struct ei_event *e;
    while ((e = ei_get_event(ei))) {
        struct ei_device *d = ei_event_get_device(e);
        switch (ei_event_get_type(e)) {
        case EI_EVENT_SEAT_ADDED:
            ei_seat_bind_capabilities(ei_event_get_seat(e), EI_DEVICE_CAP_POINTER, EI_DEVICE_CAP_POINTER_ABSOLUTE,
                                      EI_DEVICE_CAP_KEYBOARD, EI_DEVICE_CAP_BUTTON, EI_DEVICE_CAP_SCROLL, NULL);
            break;
        case EI_EVENT_DEVICE_ADDED:
            if (aygit_n < AYGIT_AZAMI && !aygit_bul(d)) {
                aygitlar[aygit_n++] = (struct aygit){ei_device_ref(d), false};
                if (ei_device_has_capability(d, EI_DEVICE_CAP_KEYBOARD)) harita_kur(d);
            }
            break;
        case EI_EVENT_DEVICE_RESUMED: {
            struct aygit *a = aygit_bul(d);
            if (a) {
                a->aktif = true;
                ei_device_start_emulating(d, ++emulasyon_no);
                artik_temizle(d);
            }
            break; }
        case EI_EVENT_DEVICE_PAUSED: {
            struct aygit *a = aygit_bul(d);
            if (a) a->aktif = false;
            break; }
        case EI_EVENT_DEVICE_REMOVED: {
            struct aygit *a = aygit_bul(d);
            if (a) {
                /* bu aygıtla basılı olanlar "artık": yeni aygıt gelince ondan bas+bırak ile temizlenecek */
                if (d == son_klavye)
                    for (; basili_tus_n > 0; basili_tus_n--)
                        izle_ekle(artik_tus, &artik_tus_n, BASILI_AZAMI, basili_tus[basili_tus_n - 1]);
                if (d == son_dugme)
                    for (; basili_dugme_n > 0; basili_dugme_n--)
                        izle_ekle(artik_dugme, &artik_dugme_n, 8, basili_dugme[basili_dugme_n - 1]);
                if (d == son_klavye) son_klavye = NULL;
                if (d == son_dugme) son_dugme = NULL;
                ei_device_unref(a->d);
                *a = aygitlar[--aygit_n];
            }
            break; }
        case EI_EVENT_PONG:
            pong_geldi = true;
            break;
        case EI_EVENT_DISCONNECT:
            koptu = true;
            break;
        default:
            break;
        }
        ei_event_unref(e);
    }
}

static void sinyal_boru_bosalt(void) {
    char b[64];
    while (read(sinyal_boru[0], b, sizeof b) > 0) {}
}

/* ms boyunca bekle; bu sırada EIS olaylarını işle. 0 = süre doldu; -1 = EIS koptu ya da sonlandırma istendi */
static int bekle_ms(int ms) {
    long son = simdi_ms() + ms;
    for (;;) {
        long kalan = son - simdi_ms();
        if (kalan < 0) kalan = 0;
        struct pollfd p[2] = {{.fd = ei_get_fd(ei), .events = POLLIN}, {.fd = sinyal_boru[0], .events = POLLIN}};
        int r = poll(p, 2, (int)kalan);
        if (r < 0 && errno != EINTR) return -1;
        if (r > 0) {
            if (p[1].revents) sinyal_boru_bosalt();
            if (p[0].revents) olaylari_isle();
        }
        if (sinyal_geldi || koptu || cikis_istendi) return -1;
        if (kalan == 0 || simdi_ms() >= son) return 0;
    }
}

/* ------------------------------------------------------------------ düşük düzey girdi */

static void izle_ekle(int *dizi, int *n, int azami, int kod) {
    for (int i = 0; i < *n; i++)
        if (dizi[i] == kod) return;
    if (*n < azami) dizi[(*n)++] = kod;
}
static void izle_sil(int *dizi, int *n, int kod) {
    for (int i = 0; i < *n; i++)
        if (dizi[i] == kod) {
            memmove(&dizi[i], &dizi[i + 1], (size_t)(*n - i - 1) * sizeof *dizi);
            (*n)--;
            return;
        }
}

/* aygıt yoksa (değişim sürüyor: eski kaldırıldı, yenisi henüz RESUMED değil) kısa süre bekle; RESUMED olmayan aygıta
 * gönderilen olay sessizce düşerdi */
static struct ei_device *aygit_bekle(struct ei_device *(*bul)(void)) {
    struct ei_device *a = bul();
    long son = simdi_ms() + AYGIT_YEDEK_MS;
    while (!a && !koptu && simdi_ms() < son) {
        if (bekle_ms(10) < 0) break;
        a = bul();
    }
    return a;
}

/* hareketten hemen sonraki ilk düğme/kaydırma olayı: KWin işaretçi odağını eşzamansız günceller; beklenmezse olay
 * ESKİ yüzeye gidebilir */
static void hareket_sonrasi_bekle(void) {
    long gecen = simdi_ms() - son_hareket_ms;
    if (gecen >= 0 && gecen < hareket_dugme_ms) bekle_ms((int)(hareket_dugme_ms - gecen));
    son_hareket_ms = -1000000; /* yalnız ilk olay bekler */
}

static int tus_gonder(int kod, bool bas) {
    struct ei_device *k = aygit_bekle(klavye_aygit);
    if (!k) return -1;
    ei_device_keyboard_key(k, (uint32_t)kod, bas);
    ei_device_frame(k, ei_now(ei));
    son_klavye = k;
    if (bas) izle_ekle(basili_tus, &basili_tus_n, BASILI_AZAMI, kod);
    else izle_sil(basili_tus, &basili_tus_n, kod);
    return 0;
}

static int dugme_gonder(int kod, bool bas) {
    struct ei_device *p = aygit_bekle(dugme_aygit);
    if (!p) return -1;
    if (bas) hareket_sonrasi_bekle();
    ei_device_button_button(p, (uint32_t)kod, bas);
    ei_device_frame(p, ei_now(ei));
    son_dugme = p;
    if (bas) izle_ekle(basili_dugme, &basili_dugme_n, 8, kod);
    else izle_sil(basili_dugme, &basili_dugme_n, kod);
    return 0;
}

static void hepsini_birak(void) {
    if (!koptu && ei) {
        while (basili_tus_n > 0) {
            int k = basili_tus[basili_tus_n - 1];
            if (tus_gonder(k, false) < 0) break;
        }
        while (basili_dugme_n > 0) {
            int b = basili_dugme[basili_dugme_n - 1];
            if (dugme_gonder(b, false) < 0) break;
        }
        ei_dispatch(ei); /* kuyruktaki iletileri yaz */
    }
    basili_tus_n = basili_dugme_n = 0;
}

static void sinirlar(double *bx, double *by, double *bw, double *bh) {
    double x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    struct ei_device *p = mutlak_aygit();
    struct ei_region *r;
    for (size_t i = 0; p && (r = ei_device_get_region(p, i)); i++) {
        double x = ei_region_get_x(r), y = ei_region_get_y(r);
        double w = ei_region_get_width(r), h = ei_region_get_height(r);
        if (x < x0) x0 = x;
        if (y < y0) y0 = y;
        if (x + w > x1) x1 = x + w;
        if (y + h > y1) y1 = y + h;
    }
    if (x1 <= x0 || y1 <= y0) { x0 = y0 = 0; x1 = y1 = 0; }
    *bx = x0; *by = y0; *bw = x1 - x0; *bh = y1 - y0;
}

static int konuma_git(double x, double y) {
    struct ei_device *p = aygit_bekle(mutlak_aygit);
    if (!p) return -1;
    if (x == son_x && y == son_y && basili_dugme_n == 0) {
        /* "park edilmiş imleç": imleç zaten oradayken altına yeni pencere geldiyse aynı konuma mutlak hareket olay
         * üretmez, tık eski yüzeye gider → önce 1 px komşuya, sonra hedefe (düğme basılıyken yapılmaz: sürükleme) */
        double bx, by, bw, bh;
        sinirlar(&bx, &by, &bw, &bh);
        double kx = x + 1 <= bx + bw - 1 ? x + 1 : x - 1;
        ei_device_pointer_motion_absolute(p, kx, y);
        ei_device_frame(p, ei_now(ei));
    }
    ei_device_pointer_motion_absolute(p, x, y);
    ei_device_frame(p, ei_now(ei));
    son_x = x;
    son_y = y;
    son_hareket_ms = simdi_ms();
    return 0;
}

/* ------------------------------------------------------------------ komut ayrıştırma */

static int dugme_kodu(const char *ad) {
    if (!strcmp(ad, "left")) return BTN_LEFT;
    if (!strcmp(ad, "right")) return BTN_RIGHT;
    if (!strcmp(ad, "middle")) return BTN_MIDDLE;
    return -1;
}

static int utf8_coz(const char **sp, uint32_t *cp) {
    const unsigned char *s = (const unsigned char *)*sp;
    int n;
    uint32_t c;
    if (s[0] < 0x80) { c = s[0]; n = 1; }
    else if ((s[0] & 0xE0) == 0xC0) { c = s[0] & 0x1F; n = 2; }
    else if ((s[0] & 0xF0) == 0xE0) { c = s[0] & 0x0F; n = 3; }
    else if ((s[0] & 0xF8) == 0xF0) { c = s[0] & 0x07; n = 4; }
    else return -1;
    for (int i = 1; i < n; i++) {
        if ((s[i] & 0xC0) != 0x80) return -1;
        c = (c << 6) | (s[i] & 0x3F);
    }
    *cp = c;
    *sp += n;
    return 0;
}

static void kucult(char *s) {
    for (; *s; s++) *s = (char)tolower((unsigned char)*s);
}

/* tek tuş belirteci → (evdev kodu, gereken Shift/AltGr). 0 tamam, -1 bilinmeyen */
static int tus_coz(const char *t, int *kod, int *mod) {
    *mod = 0;
    if (!strncmp(t, "k:", 2)) {
        char *son;
        long v = strtol(t + 2, &son, 10);
        if (son == t + 2 || *son || v < 1 || v > 0x2ff) return -1;
        *kod = (int)v;
        return 0;
    }
    if (!strncmp(t, "x:", 2)) {
        xkb_keysym_t ks = xkb_keysym_from_name(t + 2, XKB_KEYSYM_NO_FLAGS);
        if (ks == XKB_KEY_NoSymbol) return -1;
        const struct eslem *e = eslem_ara(0, ks);
        if (!e) return -1;
        *kod = e->kod;
        *mod = e->mod;
        return 0;
    }
    char alt[64];
    snprintf(alt, sizeof alt, "%s", t);
    kucult(alt);
    const char *p = t;
    uint32_t cp = 0;
    bool tek_karakter = utf8_coz(&p, &cp) == 0 && !*p;
    if (!(tek_karakter && strcmp(alt, t))) { /* büyük tek harf (A) ad değil karakter sayılır (sanal arka uçla aynı) */
        for (size_t i = 0; i < sizeof TUS_ADLARI / sizeof *TUS_ADLARI; i++)
            if (!strcmp(TUS_ADLARI[i].ad, alt) && TUS_ADLARI[i].kod > 0) { *kod = TUS_ADLARI[i].kod; return 0; }
        for (size_t i = 0; i < sizeof TAKMA / sizeof *TAKMA; i++)
            if (!strcmp(TAKMA[i].ad, alt)) { *kod = TAKMA[i].kod; return 0; }
    }
    if (tek_karakter) {
        const struct eslem *e = eslem_ara(cp, 0);
        if (e) { *kod = e->kod; *mod = e->mod; return 0; }
    }
    return -1;
}

#define AKOR_AZAMI 8
#define AKOR_UZUNLUK 8
struct akor { int kod[AKOR_UZUNLUK]; int n; };

/* "ctrl+shift+a enter" → akorlar. Hepsi çözülmeden hiçbir şey basılmaz. Dönüş: akor sayısı ya da -1 */
static int akorlari_coz(char *arg, struct akor *akorlar, char *bilinmeyen, size_t bn) {
    int an = 0;
    char *kayit1;
    for (char *tok = strtok_r(arg, " \t", &kayit1); tok; tok = strtok_r(NULL, " \t", &kayit1)) {
        if (an == AKOR_AZAMI) { snprintf(bilinmeyen, bn, "cok-akor"); return -1; }
        struct akor *a = &akorlar[an];
        a->n = 0;
        char *kayit2;
        for (char *t = strtok_r(tok, "+", &kayit2); t; t = strtok_r(NULL, "+", &kayit2)) {
            int kod, mod;
            if (tus_coz(t, &kod, &mod) < 0) { snprintf(bilinmeyen, bn, "%s", t); return -1; }
            if ((mod & MOD_ALTGR) && a->n < AKOR_UZUNLUK) a->kod[a->n++] = EVDEV_ALTGR;
            if ((mod & MOD_SHIFT) && a->n < AKOR_UZUNLUK) a->kod[a->n++] = EVDEV_SHIFT;
            if (a->n >= AKOR_UZUNLUK) { snprintf(bilinmeyen, bn, "akor-uzun"); return -1; }
            a->kod[a->n++] = kod;
        }
        if (a->n) an++;
    }
    return an ? an : -1;
}

/* ------------------------------------------------------------------ komutlar (yanıt metni: NULL = tamam) */

static const char *kes_hatasi(void) { return koptu ? "eis-koptu" : "kesildi"; }

static const char *komut_key(char *arg, int mod) /* mod: 0 key (bas+bırak), 1 keydown, 2 keyup */
{
    struct akor akorlar[AKOR_AZAMI];
    static char hata[96];
    char bil[64];
    int an = akorlari_coz(arg, akorlar, bil, sizeof bil);
    if (an < 0) {
        if (!strcmp(bil, "cok-akor") || !strcmp(bil, "akor-uzun")) snprintf(hata, sizeof hata, "%s", bil);
        else snprintf(hata, sizeof hata, "bilinmeyen-tus %s", bil);
        return hata;
    }
    if (!klavye_aygit()) return "klavye-yok";
    if (mod == 1) {
        for (int i = 0; i < an; i++)
            for (int j = 0; j < akorlar[i].n; j++)
                if (tus_gonder(akorlar[i].kod[j], true) < 0) return "klavye-yok";
        return NULL;
    }
    if (mod == 2) {
        for (int i = an - 1; i >= 0; i--)
            for (int j = akorlar[i].n - 1; j >= 0; j--)
                if (tus_gonder(akorlar[i].kod[j], false) < 0) return "klavye-yok";
        return NULL;
    }
    for (int i = 0; i < an; i++) {
        for (int j = 0; j < akorlar[i].n; j++)
            if (tus_gonder(akorlar[i].kod[j], true) < 0) return "klavye-yok";
        int r = bekle_ms(keyhold);
        for (int j = akorlar[i].n - 1; j >= 0; j--) tus_gonder(akorlar[i].kod[j], false);
        if (r < 0) return kes_hatasi();
        if (bekle_ms(keydelay) < 0) return kes_hatasi();
    }
    return NULL;
}

struct plan { int kod; int mod; };

/* metni (kod, mod) planına çevir. Yazılamayanlar `yok`a eklenir (benzersiz). Dönüş: plan uzunluğu, -1 hatalı UTF-8 */
static long plan_kur(const char *metin, struct plan **plan_out, char *yok, size_t yok_boy) {
    size_t n = strlen(metin), say = 0;
    struct plan *plan = malloc((n + 1) * sizeof *plan);
    if (!plan) return -1;
    size_t yn = 0;
    yok[0] = 0;
    const char *p = metin;
    while (*p) {
        const char *basla = p;
        uint32_t cp;
        if (utf8_coz(&p, &cp) < 0) { free(plan); return -1; }
        if (cp == '\n') { plan[say++] = (struct plan){KEY_ENTER, 0}; continue; }
        if (cp == '\t') { plan[say++] = (struct plan){KEY_TAB, 0}; continue; }
        const struct eslem *e = cp >= 0x20 && cp != 0x7f ? eslem_ara(cp, 0) : NULL;
        if (e) { plan[say++] = (struct plan){e->kod, e->mod}; continue; }
        size_t len = (size_t)(p - basla);
        bool var = false;
        for (size_t i = 0; i + len <= yn; i += 1) /* benzersiz: aynı bayt dizisi zaten listede mi (karakter sınırında) */
            if (!memcmp(yok + i, basla, len)) { var = true; break; }
        if (!var && yn + len < yok_boy) { memcpy(yok + yn, basla, len); yn += len; yok[yn] = 0; }
    }
    *plan_out = plan;
    return (long)say;
}

static const char *komut_type(const char *metin) {
    static char hata[160];
    char yok[128];
    struct plan *plan;
    long n = plan_kur(metin, &plan, yok, sizeof yok);
    if (n < 0) return "gecersiz-utf8";
    if (yok[0]) {
        free(plan);
        snprintf(hata, sizeof hata, "yazilamaz %s", yok);
        return hata;
    }
    if (!klavye_aygit()) { free(plan); return "klavye-yok"; }
    const char *sonuc = NULL;
    for (long i = 0; i < n && !sonuc; i++) {
        int bas[3], bn = 0;
        if (plan[i].mod & MOD_ALTGR) bas[bn++] = EVDEV_ALTGR;
        if (plan[i].mod & MOD_SHIFT) bas[bn++] = EVDEV_SHIFT;
        bas[bn++] = plan[i].kod;
        for (int j = 0; j < bn; j++) tus_gonder(bas[j], true);
        int r = bekle_ms(typehold);
        for (int j = bn - 1; j >= 0; j--) tus_gonder(bas[j], false);
        if (r < 0 || bekle_ms(typedelay) < 0) sonuc = kes_hatasi();
    }
    free(plan);
    return sonuc;
}

static const char *komut_yazilabilir(const char *metin) {
    static char hata[160];
    char yok[128];
    struct plan *plan;
    long n = plan_kur(metin, &plan, yok, sizeof yok);
    if (n < 0) return "gecersiz-utf8";
    free(plan);
    if (!yok[0]) return NULL;
    snprintf(hata, sizeof hata, "!yazilamaz %s", yok); /* '!' = hata değil, sorgu sonucu */
    return hata;
}

static const char *komut_kaydir(const char *arg, bool yatay) {
    char *son;
    double v = strtod(arg, &son);
    while (*son == ' ') son++;
    if (son == arg || *son || !isfinite(v) || fabs(v) > 10000) return "sayi-gecersiz";
    int n = (int)fabs(v), yon = v > 0 ? 1 : -1;
    struct ei_device *k = aygit_bekle(kaydirma_aygit);
    if (!k) return "kaydirma-yok";
    if (n) hareket_sonrasi_bekle();
    for (int i = 0; i < n; i++) {
        /* libei: artı y = aşağı, artı x = sağ; dotool wheel artı = yukarı. Ayrık birim 120 = bir çentik */
        ei_device_scroll_discrete(k, yatay ? yon * 120 : 0, yatay ? 0 : -yon * 120);
        ei_device_frame(k, ei_now(ei));
        if (bekle_ms(5) < 0) return kes_hatasi();
    }
    if (n) { /* kaydırma dizisinin sonu (wl_pointer.axis_stop) */
        ei_device_scroll_stop(k, yatay, !yatay);
        ei_device_frame(k, ei_now(ei));
    }
    return NULL;
}

static const char *komut_mouseto(const char *arg) {
    char *s1, *s2;
    double fx = strtod(arg, &s1), fy = strtod(s1, &s2);
    while (*s2 == ' ') s2++;
    if (s1 == arg || s2 == s1 || *s2 || !isfinite(fx) || !isfinite(fy)) return "mouseto-FX-FY-olmali";
    if (fx < 0) fx = 0;
    if (fx > 1) fx = 1;
    if (fy < 0) fy = 0;
    if (fy > 1) fy = 1;
    double bx, by, bw, bh;
    sinirlar(&bx, &by, &bw, &bh);
    if (bw < 1 || bh < 1) return "ekran-yok";
    double x = bx + fx * bw, y = by + fy * bh;
    if (x > bx + bw - 1) x = bx + bw - 1;
    if (y > by + bh - 1) y = by + bh - 1;
    return konuma_git(floor(x), floor(y)) < 0 ? "fare-yok" : NULL;
}

static const char *komut_mousemove(const char *arg) {
    char *s1, *s2;
    double dx = strtod(arg, &s1), dy = strtod(s1, &s2);
    while (*s2 == ' ') s2++;
    if (s1 == arg || s2 == s1 || *s2 || !isfinite(dx) || !isfinite(dy)) return "mousemove-DX-DY-olmali";
    double bx, by, bw, bh;
    sinirlar(&bx, &by, &bw, &bh);
    if (bw < 1 || bh < 1) return "ekran-yok";
    double x = (son_x < 0 ? bx + bw / 2 : son_x) + dx, y = (son_y < 0 ? by + bh / 2 : son_y) + dy;
    x = fmin(fmax(x, bx), bx + bw - 1);
    y = fmin(fmax(y, by), by + bh - 1);
    return konuma_git(floor(x), floor(y)) < 0 ? "fare-yok" : NULL;
}

static const char *komut_dugme(char *arg, const char *komut) {
    char *g = arg;
    while (*g == ' ') g++;
    kucult(g);
    for (char *e = g + strlen(g); e > g && e[-1] == ' '; ) *--e = 0;
    int kod = dugme_kodu(g);
    if (kod < 0) return "bilinmeyen-dugme (left|right|middle)";
    if (!dugme_aygit()) return "fare-yok";
    if (strcmp(komut, "buttonup")) dugme_gonder(kod, true);
    if (!strcmp(komut, "click")) {
        if (bekle_ms(keyhold) < 0) { dugme_gonder(kod, false); return kes_hatasi(); }
    }
    if (strcmp(komut, "buttondown")) dugme_gonder(kod, false);
    return NULL;
}

static const char *komut_ms(const char *arg, int *hedef) {
    char *son;
    double v = strtod(arg, &son);
    while (*son == ' ') son++;
    if (son == arg || *son || !isfinite(v) || v < 0 || v > 60000) return "MS-olmali";
    *hedef = (int)v;
    return NULL;
}

/* bir satırı işle; yanıt yazar */
static void satir_isle(char *satir) {
    size_t n = strlen(satir);
    while (n && (satir[n - 1] == '\r')) satir[--n] = 0;
    char *c = satir;
    while (*c == ' ' || *c == '\t') c++;
    if (!*c) return;
    char *arg = c;
    while (*arg && *arg != ' ') arg++;
    if (*arg) *arg++ = 0; /* ilk boşluk ayraçtır; arg satırın geri kalanı BİREBİR (type için) */
    kucult(c);
    const char *h = NULL;
    bool sorgu = false;
    if (!strcmp(c, "type")) h = komut_type(arg);
    else if (!strcmp(c, "yazilabilir")) { h = komut_yazilabilir(arg); sorgu = true; }
    else if (!strcmp(c, "mouseto")) h = komut_mouseto(arg);
    else if (!strcmp(c, "mousemove")) h = komut_mousemove(arg);
    else if (!strcmp(c, "click") || !strcmp(c, "buttondown") || !strcmp(c, "buttonup")) h = komut_dugme(arg, c);
    else if (!strcmp(c, "key")) h = komut_key(arg, 0);
    else if (!strcmp(c, "keydown")) h = komut_key(arg, 1);
    else if (!strcmp(c, "keyup")) h = komut_key(arg, 2);
    else if (!strcmp(c, "wheel")) h = komut_kaydir(arg, false);
    else if (!strcmp(c, "hwheel")) h = komut_kaydir(arg, true);
    else if (!strcmp(c, "typedelay")) h = komut_ms(arg, &typedelay);
    else if (!strcmp(c, "typehold")) h = komut_ms(arg, &typehold);
    else if (!strcmp(c, "keydelay")) h = komut_ms(arg, &keydelay);
    else if (!strcmp(c, "keyhold")) h = komut_ms(arg, &keyhold);
    else if (!strcmp(c, "hareketbekle")) h = komut_ms(arg, &hareket_dugme_ms);
    else if (!strcmp(c, "birak")) hepsini_birak();
    else if (!strcmp(c, "basili")) { /* tanılama: bu bağlantının basılı tuttuğu evdev tuş / düğme kodları */
        char t[BASILI_AZAMI * 8 + 16] = "", b[8 * 8 + 16] = "";
        for (int i = 0; i < basili_tus_n; i++) snprintf(t + strlen(t), sizeof t - strlen(t), "%s%d", i ? "," : "", basili_tus[i]);
        for (int i = 0; i < basili_dugme_n; i++) snprintf(b + strlen(b), sizeof b - strlen(b), "%s%d", i ? "," : "", basili_dugme[i]);
        yanit("tamam tus=%s dugme=%s", t, b);
        return;
    }
    else if (!strcmp(c, "bilgi")) {
        double bx, by, bw, bh;
        sinirlar(&bx, &by, &bw, &bh);
        yanit("tamam %d %d %s", (int)bw, (int)bh, duzen_adi);
        return;
    } else if (!strcmp(c, "cik")) {
        cikis_istendi = true;
    } else h = "bilinmeyen-komut";
    if (koptu) h = "eis-koptu";
    if (!h) yanit("tamam");
    else if (sorgu && h[0] == '!') yanit("%s", h + 1);
    else yanit("hata %s", h);
    if (!koptu) ei_dispatch(ei); /* iletiler hemen gitsin */
}

/* ------------------------------------------------------------------ açılış / kapanış */

/* kapanış sırası: son bırakmalar → ei_ping/PONG ile eşitle (KWin hepsini işledi) → ei_unref → disconnect(çerez)
 * D-Bus çağrısı (aksi hâlde KWin "Broken pipe" uyarıları yazar) */
static void cik(int kod) {
    hepsini_birak();
    if (ei && !koptu) {
        struct ei_ping *p = ei_new_ping(ei);
        if (p) {
            pong_geldi = false;
            ei_ping(p);
            ei_dispatch(ei);
            long son = simdi_ms() + 300;
            while (!pong_geldi && !koptu && simdi_ms() < son) {
                struct pollfd pf = {.fd = ei_get_fd(ei), .events = POLLIN};
                if (poll(&pf, 1, 20) > 0) olaylari_isle();
            }
            ei_ping_unref(p);
        }
    }
    if (ei) ei_unref(ei);
    ei = NULL;
    if (veri_yolu) {
        if (!koptu) sd_bus_call_method(veri_yolu, HIZMET, NESNE, ARAYUZ, "disconnect", NULL, NULL, "i", eis_cerez);
        sd_bus_flush_close_unref(veri_yolu);
        veri_yolu = NULL;
    }
    exit(kod);
}

static int adres_denetle(const char *adres) {
    if (strncmp(adres, "unix:path=", 10)) {
        fprintf(stderr, "deskhand-eis: --bus yalnız unix:path=... biçiminde olabilir\n");
        return -1;
    }
    char yol[PATH_MAX];
    size_t n = strcspn(adres + 10, ",");
    if (!n || n >= sizeof yol) return -1;
    memcpy(yol, adres + 10, n);
    yol[n] = 0;
    char gercek[PATH_MAX];
    snprintf(gercek, sizeof gercek, "/run/user/%u/bus", (unsigned)getuid());
    char a[PATH_MAX], b[PATH_MAX];
    const char *ya = realpath(yol, a) ? a : yol, *yb = realpath(gercek, b) ? b : gercek;
    if (!strcmp(yol, gercek) || !strcmp(ya, yb)) {
        fprintf(stderr, "deskhand-eis: --bus kullanıcının GERÇEK oturum veri yolu (%s); reddedildi\n", gercek);
        return -1;
    }
    return 0;
}

int main(int argc, char **argv) {
    const char *adres = NULL;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--bus") && i + 1 < argc) adres = argv[++i];
        else { fprintf(stderr, "kullanım: deskhand-eis --bus unix:path=/özel/veri/yolu/bus\n"); return 1; }
    }
    if (!adres || !*adres) {
        fprintf(stderr, "deskhand-eis: --bus ADRES zorunlu (ortamdan devralınmaz)\n");
        yanit("hata bus-yok");
        return 2;
    }
    if (adres_denetle(adres) < 0) {
        yanit("hata bus-yasak");
        return 2;
    }
    signal(SIGPIPE, SIG_IGN);
    if (pipe2(sinyal_boru, O_CLOEXEC | O_NONBLOCK) < 0) return 3;
    struct sigaction sa = {.sa_handler = sinyal_isle};
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGHUP, &sa, NULL);

    sd_bus *bus = NULL;
    sd_bus_message *yan = NULL;
    sd_bus_error hata = SD_BUS_ERROR_NULL;
    int r = sd_bus_new(&bus);
    if (r >= 0) r = sd_bus_set_address(bus, adres);
    if (r >= 0) r = sd_bus_set_bus_client(bus, 1);
    if (r >= 0) r = sd_bus_start(bus);
    if (r < 0) {
        fprintf(stderr, "deskhand-eis: veri yoluna bağlanılamadı (%s): %s\n", adres, strerror(-r));
        yanit("hata bus-baglanti");
        return 3;
    }
    r = sd_bus_call_method(bus, HIZMET, NESNE, ARAYUZ, "connectToEIS", &hata, &yan, "i", YETENEK_KLAVYE_FARE);
    if (r < 0) {
        fprintf(stderr, "deskhand-eis: connectToEIS: %s\n", hata.message ? hata.message : strerror(-r));
        yanit("hata connectToEIS");
        return 3;
    }
    int fd = -1, cerez = 0;
    if (sd_bus_message_read(yan, "hi", &fd, &cerez) < 0 || fd < 0 || (fd = fcntl(fd, F_DUPFD_CLOEXEC, 3)) < 0) {
        yanit("hata connectToEIS-yanit");
        return 3;
    }
    sd_bus_message_unref(yan);
    veri_yolu = bus;
    eis_cerez = cerez;
    ei = ei_new_sender(NULL);
    if (!ei) return 3;
    ei_configure_name(ei, "deskhand-eis");
    if (ei_setup_backend_fd(ei, fd) < 0) {
        yanit("hata ei-kurulamadi");
        return 3;
    }
    /* aygıtlar hazır olana dek bekle: mutlak fare + klavye (+ düğme) */
    long son = simdi_ms() + HAZIR_BEKLEME_MS;
    bool hazir = false;
    while (simdi_ms() < son && !koptu && !sinyal_geldi) {
        bekle_ms(20);
        if (mutlak_aygit() && klavye_aygit() && dugme_aygit()) {
            bekle_ms(150); /* kalan aygıtlar (kaydırma) da gelsin */
            hazir = true;
            break;
        }
    }
    if (!hazir) {
        fprintf(stderr, "deskhand-eis: aygıtlar hazır olmadı (mutlak=%d klavye=%d düğme=%d)\n", mutlak_aygit() != NULL,
                klavye_aygit() != NULL, dugme_aygit() != NULL);
        yanit("hata aygit-yok");
        cik(koptu ? 5 : 4);
    }
    double bx, by, bw, bh;
    sinirlar(&bx, &by, &bw, &bh);
    yanit("hazir %d %d", (int)bw, (int)bh);

    static char tampon[SATIR_AZAMI + 1];
    size_t tn = 0;
    bool tasti = false; /* satır çok uzun: sonraki satır sonuna dek at */
    while (!sinyal_geldi && !koptu && !cikis_istendi) {
        char *nl;
        while (!tasti && (nl = memchr(tampon, '\n', tn))) {
            *nl = 0;
            satir_isle(tampon);
            size_t kalan = tn - (size_t)(nl - tampon) - 1;
            memmove(tampon, nl + 1, kalan);
            tn = kalan;
            if (sinyal_geldi || koptu || cikis_istendi) break;
        }
        if (sinyal_geldi || koptu || cikis_istendi) break;
        if (tn >= SATIR_AZAMI) { /* satır sınırı aşıldı */
            yanit("hata satir-cok-uzun");
            tn = 0;
            tasti = true;
        }
        struct pollfd p[3] = {{.fd = STDIN_FILENO, .events = POLLIN}, {.fd = ei_get_fd(ei), .events = POLLIN},
                              {.fd = sinyal_boru[0], .events = POLLIN}};
        int pr = poll(p, 3, -1);
        if (pr < 0 && errno != EINTR) break;
        if (pr > 0 && p[2].revents) sinyal_boru_bosalt();
        if (pr > 0 && p[1].revents) olaylari_isle();
        if (pr > 0 && (p[0].revents & (POLLIN | POLLHUP))) {
            ssize_t o = read(STDIN_FILENO, tampon + tn, SATIR_AZAMI - tn);
            if (o == 0) break; /* EOF */
            if (o < 0) {
                if (errno == EINTR || errno == EAGAIN) continue;
                break;
            }
            if (tasti) { /* satır sonuna dek at */
                char *e = memchr(tampon + tn, '\n', (size_t)o);
                if (e) {
                    tasti = false;
                    size_t kalan = (size_t)o - (size_t)(e + 1 - (tampon + tn));
                    memmove(tampon, e + 1, kalan);
                    tn = kalan;
                }
            } else tn += (size_t)o;
        }
    }
    if (koptu) {
        fprintf(stderr, "deskhand-eis: EIS bağlantısı koptu\n");
        yanit("hata eis-koptu");
        cik(5);
    }
    cik(0);
    return 0;
}
