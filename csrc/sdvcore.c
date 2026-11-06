/* sdvcore.c — 星露谷 Mod 管理器的 C 核心（阶段一）
 *
 * 提供三件事（均导出 C ABI，可被 Python ctypes / 其它语言调用）：
 *   1. sdv_scan_mods    递归扫描 Mods 目录，解析 manifest.json，返回 JSON 数组
 *   2. sdv_decode_utf16 把 UTF-16LE/BE 的控制台输出转成 UTF-8
 *   3. sdv_classifier_* 逐行判断控制台输出级别（error/warn/info/trace）
 *
 * 编译（MinGW-w64）：
 *   gcc -shared -O2 -s -o sdvcore.dll csrc/sdvcore.c
 * 测试：
 *   gcc -O2 -o test_core.exe csrc/test_core.c csrc/sdvcore.c
 */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#define SDV_EXPORT __declspec(dllexport)

/* ------------------------------------------------------------------ 字符串缓冲 */
typedef struct {
    char *data;
    size_t len;
    size_t cap;
} Buf;

static void buf_init(Buf *b) { b->data = NULL; b->len = 0; b->cap = 0; }

static int buf_reserve(Buf *b, size_t extra) {
    if (b->len + extra + 1 <= b->cap) return 1;
    size_t cap = b->cap ? b->cap * 2 : 256;
    while (cap < b->len + extra + 1) cap *= 2;
    char *p = (char *)realloc(b->data, cap);
    if (!p) return 0;
    b->data = p;
    b->cap = cap;
    return 1;
}

static void buf_put(Buf *b, const char *s, size_t n) {
    if (!buf_reserve(b, n)) return;
    memcpy(b->data + b->len, s, n);
    b->len += n;
    b->data[b->len] = 0;
}

static void buf_puts(Buf *b, const char *s) { buf_put(b, s, strlen(s)); }

static void buf_putc(Buf *b, char c) {
    if (!buf_reserve(b, 1)) return;
    b->data[b->len++] = c;
    b->data[b->len] = 0;
}

/* JSON 字符串转义 */
static void buf_json_string(Buf *b, const char *s) {
    buf_putc(b, '"');
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        switch (*p) {
        case '"': buf_puts(b, "\\\""); break;
        case '\\': buf_puts(b, "\\\\"); break;
        case '\n': buf_puts(b, "\\n"); break;
        case '\r': buf_puts(b, "\\r"); break;
        case '\t': buf_puts(b, "\\t"); break;
        default:
            if (*p < 0x20) {
                char tmp[8];
                sprintf(tmp, "\\u%04x", *p);
                buf_puts(b, tmp);
            } else {
                buf_putc(b, (char)*p);
            }
        }
    }
    buf_putc(b, '"');
}

/* ------------------------------------------------------------------ 简易 JSON 解析 */
typedef enum { JNULL, JBOOL, JNUM, JSTR, JARR, JOBJ } JType;

typedef struct JVal {
    JType type;
    double num;
    int boolean;
    char *str;
    struct JVal **items;   /* 数组元素 / 对象值 */
    char **keys;           /* 对象键 */
    size_t n;
} JVal;

static const char *skip_ws(const char *p) {
    for (;;) {
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
        if (p[0] == '/' && p[1] == '/') {
            while (*p && *p != '\n') p++;
            continue;
        }
        if (p[0] == '/' && p[1] == '*') {
            p += 2;
            while (*p && !(p[0] == '*' && p[1] == '/')) p++;
            if (*p) p += 2;
            continue;
        }
        return p;
    }
}

static char *parse_string(const char **pp) {
    const char *p = *pp;
    if (*p != '"') return NULL;
    p++;
    Buf b;
    buf_init(&b);
    buf_putc(&b, 0);
    b.len = 0;
    while (*p && *p != '"') {
        if (*p == '\\' && p[1]) {
            p++;
            switch (*p) {
            case 'n': buf_putc(&b, '\n'); break;
            case 'r': buf_putc(&b, '\r'); break;
            case 't': buf_putc(&b, '\t'); break;
            case 'b': buf_putc(&b, '\b'); break;
            case 'f': buf_putc(&b, '\f'); break;
            case '"': buf_putc(&b, '"'); break;
            case '\\': buf_putc(&b, '\\'); break;
            case '/': buf_putc(&b, '/'); break;
            case 'u': {
                unsigned code = 0;
                for (int i = 0; i < 4 && p[1]; i++) {
                    p++;
                    char c = *p;
                    code <<= 4;
                    if (c >= '0' && c <= '9') code |= (unsigned)(c - '0');
                    else if (c >= 'a' && c <= 'f') code |= (unsigned)(c - 'a' + 10);
                    else if (c >= 'A' && c <= 'F') code |= (unsigned)(c - 'A' + 10);
                }
                char out[8];
                int n = 0;
                if (code < 0x80) {
                    out[n++] = (char)code;
                } else if (code < 0x800) {
                    out[n++] = (char)(0xC0 | (code >> 6));
                    out[n++] = (char)(0x80 | (code & 0x3F));
                } else {
                    out[n++] = (char)(0xE0 | (code >> 12));
                    out[n++] = (char)(0x80 | ((code >> 6) & 0x3F));
                    out[n++] = (char)(0x80 | (code & 0x3F));
                }
                buf_put(&b, out, (size_t)n);
                break;
            }
            default: buf_putc(&b, *p);
            }
            p++;
            continue;
        }
        buf_putc(&b, *p);
        p++;
    }
    if (*p == '"') p++;
    *pp = p;
    return b.data;
}

static JVal *parse_value(const char **pp);

static JVal *new_val(JType type) {
    JVal *v = (JVal *)calloc(1, sizeof(JVal));
    if (v) v->type = type;
    return v;
}

static JVal *parse_object(const char **pp) {
    const char *p = *pp + 1; /* { */
    JVal *obj = new_val(JOBJ);
    if (!obj) return NULL;
    for (;;) {
        p = skip_ws(p);
        if (*p == '}') { p++; break; }
        if (*p == ',') { p++; continue; }   /* 容忍尾随逗号 */
        if (*p != '"') break;
        char *key = parse_string(&p);
        p = skip_ws(p);
        if (*p != ':') { free(key); break; }
        p++;
        JVal *val = parse_value(&p);
        char **keys = (char **)realloc(obj->keys, sizeof(char *) * (obj->n + 1));
        JVal **vals = (JVal **)realloc(obj->items, sizeof(JVal *) * (obj->n + 1));
        if (!keys || !vals) { free(key); break; }
        obj->keys = keys;
        obj->items = vals;
        obj->keys[obj->n] = key;
        obj->items[obj->n] = val;
        obj->n++;
    }
    *pp = p;
    return obj;
}

static JVal *parse_array(const char **pp) {
    const char *p = *pp + 1; /* [ */
    JVal *arr = new_val(JARR);
    if (!arr) return NULL;
    for (;;) {
        p = skip_ws(p);
        if (*p == ']') { p++; break; }
        if (*p == ',') { p++; continue; }
        if (!*p) break;
        JVal *val = parse_value(&p);
        JVal **vals = (JVal **)realloc(arr->items, sizeof(JVal *) * (arr->n + 1));
        if (!vals) break;
        arr->items = vals;
        arr->items[arr->n++] = val;
    }
    *pp = p;
    return arr;
}

static JVal *parse_value(const char **pp) {
    const char *p = skip_ws(*pp);
    JVal *v = NULL;
    if (*p == '{') {
        v = parse_object(&p);
    } else if (*p == '[') {
        v = parse_array(&p);
    } else if (*p == '"') {
        v = new_val(JSTR);
        if (v) v->str = parse_string(&p);
    } else if (!strncmp(p, "true", 4)) {
        v = new_val(JBOOL);
        if (v) v->boolean = 1;
        p += 4;
    } else if (!strncmp(p, "false", 5)) {
        v = new_val(JBOOL);
        p += 5;
    } else if (!strncmp(p, "null", 4)) {
        v = new_val(JNULL);
        p += 4;
    } else {
        char *end = NULL;
        double num = strtod(p, &end);
        if (end != p) {
            v = new_val(JNUM);
            if (v) v->num = num;
            p = end;
        }
    }
    *pp = p;
    return v;
}

static void val_free(JVal *v) {
    if (!v) return;
    if (v->type == JSTR) free(v->str);
    for (size_t i = 0; i < v->n; i++) {
        if (v->items) val_free(v->items[i]);
        if (v->keys) free(v->keys[i]);
    }
    free(v->items);
    free(v->keys);
    free(v);
}

static JVal *obj_get(const JVal *obj, const char *key) {
    if (!obj || obj->type != JOBJ) return NULL;
    for (size_t i = 0; i < obj->n; i++) {
        if (obj->keys[i] && !strcmp(obj->keys[i], key)) return obj->items[i];
    }
    return NULL;
}

static const char *obj_str(const JVal *obj, const char *key) {
    JVal *v = obj_get(obj, key);
    if (!v) return NULL;
    if (v->type == JSTR) return v->str;
    if (v->type == JNUM) {
        static char tmp[64];
        sprintf(tmp, "%.10g", v->num);
        return tmp;
    }
    return NULL;
}

/* ------------------------------------------------------------------ 文件与宽字符 */
static char *wcs_to_utf8(const wchar_t *w) {
    if (!w) return NULL;
    int n = WideCharToMultiByte(CP_UTF8, 0, w, -1, NULL, 0, NULL, NULL);
    if (n <= 0) return NULL;
    char *out = (char *)malloc((size_t)n);
    if (!out) return NULL;
    WideCharToMultiByte(CP_UTF8, 0, w, -1, out, n, NULL, NULL);
    return out;
}

static unsigned char *read_file_w(const wchar_t *path, size_t *out_len) {
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return NULL;
    LARGE_INTEGER size;
    if (!GetFileSizeEx(h, &size) || size.QuadPart <= 0 || size.QuadPart > (64 << 20)) {
        CloseHandle(h);
        return NULL;
    }
    unsigned char *buf = (unsigned char *)malloc((size_t)size.QuadPart + 1);
    if (!buf) { CloseHandle(h); return NULL; }
    DWORD got = 0;
    BOOL ok = ReadFile(h, buf, (DWORD)size.QuadPart, &got, NULL);
    CloseHandle(h);
    if (!ok) { free(buf); return NULL; }
    buf[got] = 0;
    /* 去 BOM */
    if (got >= 3 && buf[0] == 0xEF && buf[1] == 0xBB && buf[2] == 0xBF) {
        memmove(buf, buf + 3, got - 3);
        got -= 3;
        buf[got] = 0;
    }
    *out_len = got;
    return buf;
}

/* ------------------------------------------------------------------ 扫描 */
typedef struct {
    Buf json;
    size_t count;
    char **seen_uids;
    size_t seen_n;
    int first;
} ScanCtx;

static int uid_seen(ScanCtx *ctx, const char *uid) {
    if (!uid || !*uid) return 0;
    for (size_t i = 0; i < ctx->seen_n; i++) {
        if (!_stricmp(ctx->seen_uids[i], uid)) return 1;
    }
    char **p = (char **)realloc(ctx->seen_uids, sizeof(char *) * (ctx->seen_n + 1));
    if (!p) return 0;
    ctx->seen_uids = p;
    ctx->seen_uids[ctx->seen_n] = _strdup(uid);
    ctx->seen_n++;
    return 0;
}

static void json_begin(ScanCtx *ctx) {
    if (!ctx->first) buf_puts(&ctx->json, ",");
    ctx->first = 0;
}

static void put_field_str(Buf *b, const char *key, const char *val) {
    buf_puts(b, ",\"");
    buf_puts(b, key);
    buf_puts(b, "\":");
    buf_json_string(b, val ? val : "");
}

static void scan_one(ScanCtx *ctx, const wchar_t *folder, const wchar_t *folder_name,
                     const wchar_t *rel) {
    wchar_t manifest[MAX_PATH * 2];
    _snwprintf(manifest, MAX_PATH * 2 - 1, L"%ls\\manifest.json", folder);
    size_t len = 0;
    unsigned char *raw = read_file_w(manifest, &len);
    char *rel_utf8 = wcs_to_utf8(rel);
    char *fn_utf8 = wcs_to_utf8(folder_name);

    json_begin(ctx);
    buf_puts(&ctx->json, "{\"rel\":");
    buf_json_string(&ctx->json, rel_utf8 ? rel_utf8 : "");
    buf_puts(&ctx->json, ",\"folder\":");
    buf_json_string(&ctx->json, fn_utf8 ? fn_utf8 : "");

    if (!raw) {
        put_field_str(&ctx->json, "error", "unreadable");
        buf_puts(&ctx->json, "}");
        free(rel_utf8);
        free(fn_utf8);
        ctx->count++;
        return;
    }
    const char *p = (const char *)raw;
    JVal *root = parse_value(&p);
    free(raw);

    if (!root || root->type != JOBJ) {
        put_field_str(&ctx->json, "error", "parse");
        buf_puts(&ctx->json, "}");
        val_free(root);
        free(rel_utf8);
        free(fn_utf8);
        ctx->count++;
        return;
    }

    const char *name = obj_str(root, "Name");
    const char *author = obj_str(root, "Author");
    const char *version = obj_str(root, "Version");
    const char *uid = obj_str(root, "UniqueID");
    const char *min_api = obj_str(root, "MinimumApiVersion");
    const char *desc = obj_str(root, "Description");
    const char *entry = obj_str(root, "EntryDll");
    const char *cp = NULL;
    JVal *cpv = obj_get(root, "ContentPackFor");
    if (cpv) {
        if (cpv->type == JSTR) cp = cpv->str;
        else if (cpv->type == JOBJ) cp = obj_str(cpv, "UniqueID");
    }

    put_field_str(&ctx->json, "name", name);
    put_field_str(&ctx->json, "author", author);
    put_field_str(&ctx->json, "version", version);
    put_field_str(&ctx->json, "unique_id", uid);
    put_field_str(&ctx->json, "min_api", min_api);
    put_field_str(&ctx->json, "entry_dll", entry);
    put_field_str(&ctx->json, "content_pack_for", cp);
    put_field_str(&ctx->json, "description", desc);
    put_field_str(&ctx->json, "error", "");

    /* UpdateKeys：字符串数组或单个字符串 */
    buf_puts(&ctx->json, ",\"update_keys\":[");
    JVal *uk = obj_get(root, "UpdateKeys");
    int first = 1;
    if (uk && uk->type == JARR) {
        for (size_t i = 0; i < uk->n; i++) {
            if (uk->items[i] && uk->items[i]->type == JSTR && uk->items[i]->str) {
                if (!first) buf_puts(&ctx->json, ",");
                buf_json_string(&ctx->json, uk->items[i]->str);
                first = 0;
            }
        }
    } else if (uk && uk->type == JSTR && uk->str) {
        buf_json_string(&ctx->json, uk->str);
    }
    buf_puts(&ctx->json, "]");

    /* Dependencies：[{id, required, min}] */
    buf_puts(&ctx->json, ",\"dependencies\":[");
    JVal *deps = obj_get(root, "Dependencies");
    int dfirst = 1;
    if (deps && deps->type == JOBJ) {
        const char *did = obj_str(deps, "UniqueID");
        if (did && *did) {
            buf_puts(&ctx->json, "{\"id\":");
            buf_json_string(&ctx->json, did);
            buf_puts(&ctx->json, ",\"required\":");
            JVal *req = obj_get(deps, "IsRequired");
            int required = 1;
            if (req && req->type == JBOOL) required = req->boolean;
            buf_puts(&ctx->json, required ? "true" : "false");
            buf_puts(&ctx->json, ",\"min\":");
            const char *mv = obj_str(deps, "MinimumVersion");
            buf_json_string(&ctx->json, mv ? mv : "");
            buf_puts(&ctx->json, "}");
            dfirst = 0;
        }
    } else if (deps && deps->type == JARR) {
        for (size_t i = 0; i < deps->n; i++) {
            JVal *d = deps->items[i];
            if (!d || d->type != JOBJ) continue;
            const char *did = obj_str(d, "UniqueID");
            if (!did || !*did) continue;
            if (!dfirst) buf_puts(&ctx->json, ",");
            dfirst = 0;
            buf_puts(&ctx->json, "{\"id\":");
            buf_json_string(&ctx->json, did);
            buf_puts(&ctx->json, ",\"required\":");
            JVal *req = obj_get(d, "IsRequired");
            int required = 1;
            if (req && req->type == JBOOL) required = req->boolean;
            buf_puts(&ctx->json, required ? "true" : "false");
            buf_puts(&ctx->json, ",\"min\":");
            buf_json_string(&ctx->json, obj_str(d, "MinimumVersion") ? obj_str(d, "MinimumVersion") : "");
            buf_puts(&ctx->json, "}");
        }
    }
    buf_puts(&ctx->json, "]");

    /* 缺失字段 + 重复 UniqueID */
    buf_puts(&ctx->json, ",\"missing\":[");
    int mfirst = 1;
    const char *keys[] = {"Name", "Author", "Version", "UniqueID"};
    const char *vals[] = {name, author, version, uid};
    for (int i = 0; i < 4; i++) {
        if (!vals[i] || !*vals[i]) {
            if (!mfirst) buf_puts(&ctx->json, ",");
            buf_json_string(&ctx->json, keys[i]);
            mfirst = 0;
        }
    }
    buf_puts(&ctx->json, "]");
    buf_puts(&ctx->json, ",\"duplicate_uid\":");
    buf_puts(&ctx->json, uid_seen(ctx, uid) ? "true" : "false");
    buf_puts(&ctx->json, "}");

    ctx->count++;
    val_free(root);
    free(rel_utf8);
    free(fn_utf8);
}

/* depth 0：Mods/ 下每个目录；没有 manifest 的目录再看一层（Mods/分组/Mod），
   与 Python 的 _iter_mod_dirs 行为一致，不无限递归。 */
static void scan_dir(ScanCtx *ctx, const wchar_t *root, const wchar_t *dir,
                     const wchar_t *prefix, int depth) {
    wchar_t pattern[MAX_PATH * 2];
    _snwprintf(pattern, MAX_PATH * 2 - 1, L"%ls\\*", dir);
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
        if (!wcscmp(fd.cFileName, L".") || !wcscmp(fd.cFileName, L"..")) continue;
        if (fd.cFileName[0] == L'.') continue;
        wchar_t sub[MAX_PATH * 2];
        _snwprintf(sub, MAX_PATH * 2 - 1, L"%ls\\%ls", dir, fd.cFileName);
        wchar_t rel[MAX_PATH * 2];
        if (prefix[0])
            _snwprintf(rel, MAX_PATH * 2 - 1, L"%ls\\%ls", prefix, fd.cFileName);
        else
            _snwprintf(rel, MAX_PATH * 2 - 1, L"%ls", fd.cFileName);
        wchar_t manifest[MAX_PATH * 2];
        _snwprintf(manifest, MAX_PATH * 2 - 1, L"%ls\\manifest.json", sub);
        if (GetFileAttributesW(manifest) != INVALID_FILE_ATTRIBUTES) {
            scan_one(ctx, sub, fd.cFileName, rel);
        } else if (depth == 0) {
            scan_dir(ctx, root, sub, rel, 1);
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
}

/* 对外：扫描一个目录（Mods 或 Mods.disabled），返回 JSON 数组（sdv_free 释放） */
SDV_EXPORT char *sdv_scan_dir(const wchar_t *root) {
    if (!root) return NULL;
    ScanCtx ctx;
    memset(&ctx, 0, sizeof(ctx));
    buf_init(&ctx.json);
    buf_putc(&ctx.json, '[');
    ctx.first = 1;
    scan_dir(&ctx, root, root, L"", 0);
    buf_puts(&ctx.json, "]");
    for (size_t i = 0; i < ctx.seen_n; i++) free(ctx.seen_uids[i]);
    free(ctx.seen_uids);
    return ctx.json.data;
}

/* 兼容旧接口：返回完整 JSON 数组 */
SDV_EXPORT char *sdv_scan_mods(const wchar_t *mods_dir) { return sdv_scan_dir(mods_dir); }

/* 只数数量：按 JSON 深度数顶层对象，避免把 description 里的括号算进去 */
SDV_EXPORT int sdv_count_mods(const wchar_t *mods_dir) {
    char *json = sdv_scan_dir(mods_dir);
    if (!json) return 0;
    int depth = 0;
    int in_str = 0;
    int esc = 0;
    int n = 0;
    for (const char *q = json; *q; q++) {
        char c = *q;
        if (in_str) {
            if (esc) esc = 0;
            else if (c == '\\') esc = 1;
            else if (c == '"') in_str = 0;
            continue;
        }
        if (c == '"') in_str = 1;
        else if (c == '[') depth++;
        else if (c == ']') depth--;
        else if (c == '{' && depth == 1) n++;
    }
    free(json);
    return n;
}

/* ------------------------------------------------------------------ UTF-16 解码 */
SDV_EXPORT char *sdv_decode_utf16(const unsigned char *buf, size_t len) {
    if (!buf || len < 2) return NULL;
    int be = 0;
    const unsigned char *p = buf;
    size_t n = len;
    if (p[0] == 0xFF && p[1] == 0xFE) { p += 2; n -= 2; }
    else if (p[0] == 0xFE && p[1] == 0xFF) { p += 2; n -= 2; be = 1; }
    else {
        /* 没有 BOM：统计奇偶位 NUL 判断字节序 */
        size_t nul_even = 0, nul_odd = 0;
        for (size_t i = 0; i + 1 < n; i += 2) {
            if (p[i] == 0) nul_even++;
            if (p[i + 1] == 0) nul_odd++;
        }
        if (nul_even > nul_odd * 2 + 4) be = 1;      /* 0x00 'X' → 大端 */
        else if (nul_odd < nul_even / 2) be = 0;
    }
    size_t wlen = n / 2;
    wchar_t *w = (wchar_t *)malloc((wlen + 1) * sizeof(wchar_t));
    if (!w) return NULL;
    for (size_t i = 0; i < wlen; i++) {
        unsigned char lo = p[i * 2], hi = p[i * 2 + 1];
        unsigned int unit = be ? ((unsigned)lo << 8 | hi) : ((unsigned)hi << 8 | lo);
        w[i] = (wchar_t)unit;
    }
    w[wlen] = 0;
    char *out = wcs_to_utf8(w);
    free(w);
    return out;
}

/* ------------------------------------------------------------------ 分级判断 */
typedef struct {
    int context;   /* 0 none, 1 warn, 2 error */
    int remain;
} SdvClassifier;

SDV_EXPORT SdvClassifier *sdv_classifier_new(void) {
    return (SdvClassifier *)calloc(1, sizeof(SdvClassifier));
}

SDV_EXPORT void sdv_classifier_free(SdvClassifier *c) { free(c); }

static int contains_ci(const char *hay, const char *needle) {
    if (!hay || !needle) return 0;
    size_t hn = strlen(hay), nn = strlen(needle);
    if (nn > hn) return 0;
    for (size_t i = 0; i + nn <= hn; i++) {
        if (!_strnicmp(hay + i, needle, nn)) return 1;
    }
    return 0;
}

static int has_level_token(const char *line, int *level) {
    static const char *tokens[] = {"ERROR", "ALERT", "CRITICAL", "FATAL", "WARN", "WARNING", "TRACE", "DEBUG"};
    for (int i = 0; i < 8; i++) {
        if (contains_ci(line, tokens[i])) {
            if (i <= 3) *level = 2;
            else if (i <= 5) *level = 1;
            else *level = 3;
            return 1;
        }
    }
    return 0;
}

static int is_indented(const char *line) {
    if (line[0] == ' ' || line[0] == '\t') return 1;
    const char *s = line;
    while (*s == ' ') s++;
    if (*s == '-' || *s == '*') return 1;
    /* [SMAPI]   - 条目 */
    const char *br = strchr(line, ']');
    if (br && br[1] == ' ') {
        const char *q = br + 1;
        while (*q == ' ') q++;
        if (*q == '-' || *q == '*') return 1;
    }
    return 0;
}

/* 返回 0=info 1=warn 2=error 3=trace */
SDV_EXPORT int sdv_classifier_level(SdvClassifier *c, const char *line) {
    if (!c || !line) return 0;
    int lv = 0;
    if (has_level_token(line, &lv)) return lv;
    int indented = is_indented(line);
    if (!indented) { c->context = 0; c->remain = 0; }
    static const char *blocks[] = {
        "could not be added", "skipped mods", "these mods",
        "no longer compatible", "consider updating", "error log",
    };
    for (int i = 0; i < 6; i++) {
        if (contains_ci(line, blocks[i])) {
            c->context = (i == 1 || i == 4) ? 1 : 2;
            c->remain = 60;
            break;
        }
    }
    if (c->remain > 0 && indented) {
        c->remain--;
        if (c->context) return c->context;
    }
    static const char *errs[] = {
        "error", "failed", "failure", "exception", "crash", "could not", "cannot ",
        "can't ", "unable to", "not found", "missing", "invalid", "conflict",
        "denied", "aborted", "fatal", "no longer", "incompatible", "unexpected", "not loaded",
    };
    for (int i = 0; i < 20; i++) if (contains_ci(line, errs[i])) return 2;
    static const char *warns[] = {
        "warn", "deprecat", "ignored", "skipped", "unsupported", "outdated",
        "out-of-date", "requires smapi", "not compatible", "may not work",
        "recommend", "but you have", "out of date",
    };
    for (int i = 0; i < 13; i++) if (contains_ci(line, warns[i])) return 1;
    return 0;
}

/* 简单判断（无状态）：给不关心上下文的地方用 */
SDV_EXPORT int sdv_classify(const char *line) {
    SdvClassifier c;
    memset(&c, 0, sizeof(c));
    return sdv_classifier_level(&c, line);
}

/* ------------------------------------------------------------------ 内存释放 */
SDV_EXPORT void sdv_free(void *p) { free(p); }

SDV_EXPORT const char *sdv_version(void) { return "1.0"; }
