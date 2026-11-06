/* test_core.c — C 核心自测：扫描真实 Mods 目录、解码 UTF-16、分级判断 */
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

extern char *sdv_scan_mods(const wchar_t *mods_dir);
extern int sdv_count_mods(const wchar_t *mods_dir);
extern char *sdv_decode_utf16(const unsigned char *buf, size_t len);
extern int sdv_classify(const char *line);
extern void sdv_free(void *p);
typedef struct SdvClassifier SdvClassifier;
extern SdvClassifier *sdv_classifier_new(void);
extern int sdv_classifier_level(SdvClassifier *c, const char *line);
extern void sdv_classifier_free(SdvClassifier *c);

static double now_ms(void) {
    static LARGE_INTEGER freq;
    static int init = 0;
    if (!init) { QueryPerformanceFrequency(&freq); init = 1; }
    LARGE_INTEGER c;
    QueryPerformanceCounter(&c);
    return (double)c.QuadPart * 1000.0 / (double)freq.QuadPart;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        printf("usage: test_core.exe <mods_dir>\n");
        return 2;
    }
    wchar_t dir[MAX_PATH * 2];
    MultiByteToWideChar(CP_ACP, 0, argv[1], -1, dir, MAX_PATH * 2);

    /* 1) 只数数量 */
    double t0 = now_ms();
    int n = sdv_count_mods(dir);
    double t1 = now_ms();
    printf("[count]  %d 个 Mod，耗时 %.2f ms\n", n, t1 - t0);

    /* 2) 完整扫描并输出 JSON */
    t0 = now_ms();
    char *json = sdv_scan_mods(dir);
    t1 = now_ms();
    if (!json) {
        printf("[scan]  失败\n");
        return 1;
    }
    size_t len = strlen(json);
    printf("[scan]   耗时 %.2f ms，JSON %zu 字节\n", t1 - t0, len);
    printf("[scan]   前 400 字节：%.400s\n", json);
    sdv_free(json);

    /* 3) UTF-16 解码 */
    const char *text = "[SMAPI] Skipped mods";
    size_t tn = strlen(text);
    unsigned char *u16 = (unsigned char *)malloc(tn * 2 + 2);
    for (size_t i = 0; i < tn; i++) { u16[i * 2] = (unsigned char)text[i]; u16[i * 2 + 1] = 0; }
    char *decoded = sdv_decode_utf16(u16, tn * 2);
    printf("[decode] %s\n", decoded ? decoded : "(null)");
    sdv_free(decoded);
    free(u16);

    /* 4) 分级 */
    const char *lines[] = {
        "[SMAPI] SMAPI 4.5.2 loaded",
        "[SMAPI]    Skipped mods",
        "[SMAPI]       These mods could not be added to your game.",
        "[SMAPI]       - BrokenMod because it needs SMAPI 5.0",
        "[18:00:00 ERROR SMAPI] boom",
        "[SMAPI] You can update 1 mod:",
    };
    printf("-- 无状态 --\n");
    for (int i = 0; i < 6; i++) {
        printf("[level]  %d  %s\n", sdv_classify(lines[i]), lines[i]);
    }
    printf("-- 有状态（上下文继承）--\n");
    SdvClassifier *st = sdv_classifier_new();
    for (int i = 0; i < 6; i++) {
        printf("[level]  %d  %s\n", sdv_classifier_level(st, lines[i]), lines[i]);
    }
    sdv_classifier_free(st);
    return 0;
}
