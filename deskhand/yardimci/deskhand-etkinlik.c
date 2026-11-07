/* deskhand-etkinlik: kullanıcının KLAVYE + FARE etkinliğini izler (Wayland ext-idle-notify-v1).
 * Yetki gerekmez (input grubu / root yok): KWin, ext_idle_notifier_v1 v2'yi her istemciye sunar.
 * v2 get_input_idle_notification kullanılır: video oynatırken etkin olan uyku engelleyicilerini
 * (idle inhibitor) YOK SAYAR, yalnız gerçek girdiye bakar.
 *
 * Kullanım: deskhand-etkinlik [ZAMAN_ASIMI_MS=50]
 * stdout (her satır anında): "hazir <ms> v<sürüm> <t>" | "bosta <t>" | "aktif <t>" | "hata <neden>"
 *   bosta: ZAMAN_ASIMI_MS boyunca hiç girdi yok;  aktif: bostadan sonraki İLK girdi.
 *   t = CLOCK_MONOTONIC saniye (Python time.monotonic() ile aynı saat).
 * Ebeveyn ölünce kendisi de ölür (PR_SET_PDEATHSIG). Not: Deskhand'in kendi gönderdiği girdiler de
 * 'aktif' üretir; kimin girdisi olduğunu deskhand zaman pencereleriyle ayırır. */
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include "ext-idle-notify-v1-client-protocol.h"

static struct wl_seat *koltuk;
static struct ext_idle_notifier_v1 *bildirici;
static uint32_t surum;

static double simdi(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

static void bosta(void *v, struct ext_idle_notification_v1 *n) { printf("bosta %.4f\n", simdi()); fflush(stdout); }
static void aktif(void *v, struct ext_idle_notification_v1 *n) { printf("aktif %.4f\n", simdi()); fflush(stdout); }
static const struct ext_idle_notification_v1_listener bildirim_dinle = {bosta, aktif};

static void kuresel(void *v, struct wl_registry *r, uint32_t ad, const char *arayuz, uint32_t s) {
    if (!strcmp(arayuz, wl_seat_interface.name) && !koltuk)
        koltuk = wl_registry_bind(r, ad, &wl_seat_interface, 1);
    else if (!strcmp(arayuz, ext_idle_notifier_v1_interface.name) && !bildirici) {
        surum = s < 2 ? s : 2;
        bildirici = wl_registry_bind(r, ad, &ext_idle_notifier_v1_interface, surum);
    }
}
static void kuresel_sil(void *v, struct wl_registry *r, uint32_t ad) {}
static const struct wl_registry_listener kayit_dinle = {kuresel, kuresel_sil};

int main(int argc, char **argv) {
    prctl(PR_SET_PDEATHSIG, SIGTERM);
    if (getppid() == 1) return 0;  /* ebeveyn çoktan öldü */
    int ms = argc > 1 ? atoi(argv[1]) : 50;
    if (ms < 10) ms = 10;
    struct wl_display *d = wl_display_connect(NULL);
    if (!d) { printf("hata wayland-baglantisi\n"); fflush(stdout); return 2; }
    struct wl_registry *r = wl_display_get_registry(d);
    wl_registry_add_listener(r, &kayit_dinle, NULL);
    wl_display_roundtrip(d);
    if (!koltuk || !bildirici) { printf("hata protokol-yok\n"); fflush(stdout); return 3; }
    struct ext_idle_notification_v1 *n = surum >= 2
        ? ext_idle_notifier_v1_get_input_idle_notification(bildirici, ms, koltuk)
        : ext_idle_notifier_v1_get_idle_notification(bildirici, ms, koltuk);  /* v1: engelleyiciler etkiler */
    ext_idle_notification_v1_add_listener(n, &bildirim_dinle, NULL);
    wl_display_roundtrip(d);
    printf("hazir %d v%u %.4f\n", ms, surum, simdi());
    fflush(stdout);
    while (wl_display_dispatch(d) != -1) {}
    return 0;
}
