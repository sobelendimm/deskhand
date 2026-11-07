/* deskhand-goruntu: KWin ScreenShot2 D-Bus arayüzüyle ekran görüntüsü (spectacle süreci açmadan).
 *
 * Kullanım:
 *   deskhand-goruntu                  tüm masaüstü (CaptureWorkspace)
 *   deskhand-goruntu -a X Y G Y       bölge, mantıksal koordinat (CaptureArea)
 *   deskhand-goruntu -s               etkin ekran (CaptureActiveScreen)
 *   deskhand-goruntu -w {UUID}        pencere (CaptureWindow)
 *   -m: fiziksel değil mantıksal çözünürlük (native-resolution=false). -c: imleç dahil.
 *
 * stdout: tek başlık satırı, ardından height*stride bayt ham piksel (KWin'in QImage belleği, olduğu gibi):
 *   "DESKHAND-GORUNTU 1 format=<QImage::Format> width=<w> height=<h> stride=<bayt> scale=<ölçek>\n"
 * Çıkış kodu: 0 tamam · 1 kullanım · 2 yetkisiz (KWin < 6.8: X-KDE-DBUS-Restricted-Interfaces) ·
 *   3 D-Bus hatası / arayüz yok · 4 boru/okuma hatası ya da zaman aşımı. Hata ayrıntısı stderr'e.
 *
 * Yetki: KWin 6.8 öncesi, çağıranın /proc/<pid>/exe yolunu Exec= ilk sözcüğü aynı olan bir .desktop
 * dosyasıyla eşleştirir ve o dosyanın X-KDE-DBUS-Restricted-Interfaces listesinde
 * org.kde.KWin.ScreenShot2 arar (install.sh bu ikili için deskhand-goruntu.desktop kurar).
 * KWin 6.8'den beri bu denetim yoktur. Derleme: make -C deskhand/yardimci (libsystemd: sd-bus). */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <systemd/sd-bus.h>
#include <unistd.h>

#define HIZMET "org.kde.KWin.ScreenShot2"
#define NESNE "/org/kde/KWin/ScreenShot2"
#define ARAYUZ "org.kde.KWin.ScreenShot2"
#define ZAMAN_ASIMI_US (10ULL * 1000000ULL)
#define OKUMA_MS 10000

static int kullanim(void) {
    fprintf(stderr, "kullanım: deskhand-goruntu [-m] [-c] [-a X Y G Y | -s | -w UUID]\n");
    return 1;
}

static int sayi(const char *s, long *d) {
    char *son;
    errno = 0;
    *d = strtol(s, &son, 10);
    return !(errno || son == s || *son);
}

static int hepsini_yaz(int fd, const char *b, size_t n) {
    while (n) {
        ssize_t w = write(fd, b, n);
        if (w < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        b += w;
        n -= (size_t)w;
    }
    return 0;
}

/* KWin borusundan stdout'a tam n bayt: önce splice (çekirdekte kopya, iki uç da boru iken), olmazsa read/write */
static int aktar(int kaynak, size_t n) {
    static char tampon[1 << 16];
    int splice_ok = 1;
    struct pollfd p = {.fd = kaynak, .events = POLLIN};
    while (n) {
        int r = poll(&p, 1, OKUMA_MS);
        if (r < 0 && errno == EINTR) continue;
        if (r <= 0) {
            fprintf(stderr, "deskhand-goruntu: boru zaman aşımı\n");
            return -1;
        }
        if (splice_ok) {
            ssize_t s = splice(kaynak, NULL, STDOUT_FILENO, NULL, n, SPLICE_F_MOVE | SPLICE_F_MORE);
            if (s > 0) {
                n -= (size_t)s;
                continue;
            }
            if (s == 0) break;
            if (errno == EINTR || errno == EAGAIN) continue;
            splice_ok = 0; /* ör. stdout bir uçbirim: düz kopyaya geç */
        }
        ssize_t o = read(kaynak, tampon, n < sizeof tampon ? n : sizeof tampon);
        if (o < 0) {
            if (errno == EINTR || errno == EAGAIN) continue;
            perror("deskhand-goruntu: read");
            return -1;
        }
        if (o == 0) break;
        if (hepsini_yaz(STDOUT_FILENO, tampon, (size_t)o) < 0) return -1;
        n -= (size_t)o;
    }
    if (n) {
        fprintf(stderr, "deskhand-goruntu: eksik veri (%zu bayt kaldı)\n", n);
        return -1;
    }
    return 0;
}

static int secenek(sd_bus_message *m, const char *ad, int deger) {
    int r = sd_bus_message_open_container(m, 'e', "sv");
    if (r >= 0) r = sd_bus_message_append(m, "s", ad);
    if (r >= 0) r = sd_bus_message_append(m, "v", "b", deger);
    if (r >= 0) r = sd_bus_message_close_container(m);
    return r;
}

int main(int argc, char **argv) {
    const char *yontem = "CaptureWorkspace", *pencere = NULL;
    long alan[4] = {0};
    int mantiksal = 0, imlec = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-m")) mantiksal = 1;
        else if (!strcmp(argv[i], "-c")) imlec = 1;
        else if (!strcmp(argv[i], "-s")) yontem = "CaptureActiveScreen";
        else if (!strcmp(argv[i], "-w") && i + 1 < argc) {
            yontem = "CaptureWindow";
            pencere = argv[++i];
        } else if (!strcmp(argv[i], "-a") && i + 4 < argc) {
            yontem = "CaptureArea";
            for (int j = 0; j < 4; j++)
                if (!sayi(argv[++i], &alan[j])) return kullanim();
            if (alan[2] <= 0 || alan[3] <= 0 || alan[2] > 65535 || alan[3] > 65535) return kullanim();
        } else return kullanim();
    }

    int boru[2];
    if (pipe2(boru, O_CLOEXEC) < 0) {
        perror("deskhand-goruntu: pipe2");
        return 4;
    }
    fcntl(boru[0], F_SETPIPE_SZ, 1 << 20); /* daha az uyanma; başarısızsa önemsiz */
    fcntl(STDOUT_FILENO, F_SETPIPE_SZ, 1 << 20);

    sd_bus *bus = NULL;
    sd_bus_message *m = NULL, *yanit = NULL;
    sd_bus_error hata = SD_BUS_ERROR_NULL;
    int r = sd_bus_open_user(&bus);
    if (r < 0) {
        fprintf(stderr, "deskhand-goruntu: oturum veri yolu: %s\n", strerror(-r));
        return 3;
    }
    r = sd_bus_message_new_method_call(bus, &m, HIZMET, NESNE, ARAYUZ, yontem);
    if (r >= 0 && pencere) r = sd_bus_message_append(m, "s", pencere);
    if (r >= 0 && !strcmp(yontem, "CaptureArea"))
        r = sd_bus_message_append(m, "iiuu", (int32_t)alan[0], (int32_t)alan[1], (uint32_t)alan[2], (uint32_t)alan[3]);
    if (r >= 0) r = sd_bus_message_open_container(m, 'a', "{sv}");
    if (r >= 0) r = secenek(m, "native-resolution", !mantiksal);
    if (r >= 0) r = secenek(m, "include-cursor", imlec);
    if (r >= 0 && pencere) r = secenek(m, "include-decoration", 1);
    if (r >= 0) r = sd_bus_message_close_container(m);
    if (r >= 0) r = sd_bus_message_append(m, "h", boru[1]); /* sd-bus kopyasını tutar */
    close(boru[1]);
    if (r < 0) {
        fprintf(stderr, "deskhand-goruntu: ileti: %s\n", strerror(-r));
        return 3;
    }
    r = sd_bus_call(bus, m, ZAMAN_ASIMI_US, &hata, &yanit);
    sd_bus_message_unref(m); /* yazma ucunun son kopyası: KWin bitirince EOF gelsin */
    if (r < 0) {
        fprintf(stderr, "deskhand-goruntu: %s: %s\n", hata.name ? hata.name : "hata",
                hata.message ? hata.message : strerror(-r));
        int yetkisiz = hata.name && strstr(hata.name, "NoAuthorized");
        sd_bus_error_free(&hata);
        return yetkisiz ? 2 : 3;
    }

    char tur[16] = "";
    uint32_t bicim = 0, gen = 0, yuk = 0, adim = 0;
    double olcek = 1.0;
    r = sd_bus_message_enter_container(yanit, 'a', "{sv}");
    while (r > 0 && (r = sd_bus_message_enter_container(yanit, 'e', "sv")) > 0) {
        const char *ad;
        if ((r = sd_bus_message_read(yanit, "s", &ad)) < 0) break;
        uint32_t *u = !strcmp(ad, "format") ? &bicim : !strcmp(ad, "width") ? &gen
                    : !strcmp(ad, "height") ? &yuk : !strcmp(ad, "stride") ? &adim : NULL;
        if (u) r = sd_bus_message_read(yanit, "v", "u", u);
        else if (!strcmp(ad, "scale")) r = sd_bus_message_read(yanit, "v", "d", &olcek);
        else if (!strcmp(ad, "type")) {
            const char *t;
            r = sd_bus_message_read(yanit, "v", "s", &t);
            if (r >= 0) snprintf(tur, sizeof tur, "%s", t);
        } else r = sd_bus_message_skip(yanit, "v");
        if (r < 0) break;
        r = sd_bus_message_exit_container(yanit);
    }
    if (r < 0 || strcmp(tur, "raw") || !gen || !yuk || adim < gen) {
        fprintf(stderr, "deskhand-goruntu: beklenmeyen yanıt (type=%s %ux%u stride=%u)\n", tur, gen, yuk, adim);
        return 3;
    }
    char baslik[160];
    int n = snprintf(baslik, sizeof baslik, "DESKHAND-GORUNTU 1 format=%u width=%u height=%u stride=%u scale=%.6g\n",
                     bicim, gen, yuk, adim, olcek);
    if (hepsini_yaz(STDOUT_FILENO, baslik, (size_t)n) < 0 || aktar(boru[0], (size_t)adim * yuk) < 0) return 4;
    sd_bus_message_unref(yanit);
    sd_bus_unref(bus);
    return 0;
}
