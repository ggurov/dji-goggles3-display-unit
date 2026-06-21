/*
 * LOGH decrypt via liblog_util.so on donor goggles.
 * Run from /blackbox/stage/logutil_decrypt
 */
#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef int (*recognize_fn)(const char *path);
typedef int (*read_ctx_fn)(void *ctx, int enc_type, const void *hdr, int hdr_len);
typedef int (*decrypt_fn)(void *ctx, const void *in, int in_len, void *out,
                          uint32_t *out_avail, int tail_flag);
typedef void (*delete_ctx_fn)(void *ctx);

#define CTX_SIZE 512
#define BODY_OFF 0xb0
#define CHUNK 8192
#define MARKER0 0x2a
#define MARKER1 0x04
#define MARKER_LEN 12

static void *load_sym(void *lib, const char *name) {
    void *p = dlsym(lib, name);
    if (!p) {
        fprintf(stderr, "dlsym(%s): %s\n", name, dlerror());
    }
    return p;
}

static int read_file(const char *path, uint8_t **out, long *out_len) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        return -1;
    }
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return -1;
    }
    long sz = ftell(f);
    if (sz <= 0) {
        fclose(f);
        return -1;
    }
    if (fseek(f, 0, SEEK_SET) != 0) {
        fclose(f);
        return -1;
    }
    uint8_t *buf = (uint8_t *)malloc((size_t)sz);
    if (!buf) {
        fclose(f);
        return -1;
    }
    if (fread(buf, 1, (size_t)sz, f) != (size_t)sz) {
        free(buf);
        fclose(f);
        return -1;
    }
    fclose(f);
    *out = buf;
    *out_len = sz;
    return 0;
}

static int write_file(const char *path, const uint8_t *data, size_t n) {
    FILE *f = fopen(path, "wb");
    if (!f) {
        return -1;
    }
    size_t w = fwrite(data, 1, n, f);
    fclose(f);
    return (w == n) ? 0 : -1;
}

static int is_bulk_seam(const uint8_t *body, int body_len, int marker_off) {
    const int trim = 12;
    if (marker_off < trim || marker_off + 2 > body_len) {
        return 0;
    }
    const uint8_t *pre = body + marker_off - trim;
    if (pre[10] == 0x00 && pre[11] == 0x00) {
        for (int k = 0; k + 1 < trim; k++) {
            if (pre[k] == 0x55 && pre[k + 1] == 0xe2) {
                return 1;
            }
        }
    }
    return 0;
}

static int clean_logh_body(uint8_t *body, int body_len, int verbose) {
    uint8_t *out = body;
    int o = 0;
    int i = 0;
    const int trim = 12;
    while (i < body_len) {
        int j = i;
        while (j + 2 <= body_len && !(body[j] == MARKER0 && body[j + 1] == MARKER1)) {
            j++;
        }
        if (j >= body_len) {
            memcpy(out + o, body + i, (size_t)(body_len - i));
            return o + (body_len - i);
        }
        if (!is_bulk_seam(body, body_len, j)) {
            if (j + 2 <= body_len) {
                memmove(out + o, body + i, (size_t)(j + 2 - i));
                o += j + 2 - i;
            }
            i = j + 2;
            continue;
        }
        int seg_end = j - trim;
        if (seg_end < i) {
            seg_end = j;
        }
        int seg_len = seg_end - i;
        if (seg_len > 0) {
            memmove(out + o, body + i, (size_t)seg_len);
            o += seg_len;
        }
        i = j + MARKER_LEN;
    }
    if (verbose && o != body_len) {
        printf("cleaned body %d -> %d bytes\n", body_len, o);
    }
    return o;
}

static int decrypt_body(decrypt_fn decrypt, void *ctx, const uint8_t *cipher, int cipher_len,
                        uint8_t *plain, size_t plain_cap, uint32_t *out_written) {
    uint32_t avail = (uint32_t)plain_cap;
    int dr = decrypt(ctx, cipher, cipher_len, plain, &avail, 0);
    if (dr < 0) {
        *out_written = 0;
        return dr;
    }
    *out_written = avail;
    return 0;
}

static int decrypt_logh(void *lib, const char *in_path, const char *out_path, int verbose) {
    recognize_fn recognize = (recognize_fn)load_sym(lib, "log_recognize_file_enc_type");
    read_ctx_fn read_ctx = (read_ctx_fn)load_sym(lib, "log_read_decrypt_ctx");
    decrypt_fn decrypt = (decrypt_fn)load_sym(lib, "log_decrypt_fragment");
    delete_ctx_fn delete_ctx = (delete_ctx_fn)load_sym(lib, "log_delete_encrypt_ctx");
    if (!recognize || !read_ctx || !decrypt) {
        return 1;
    }

    int enc_type = recognize(in_path);
    if (enc_type < 0) {
        fprintf(stderr, "recognize failed: %d\n", enc_type);
        return 2;
    }

    uint8_t *file = NULL;
    long file_len = 0;
    if (read_file(in_path, &file, &file_len) != 0) {
        return 3;
    }
    if (file_len < BODY_OFF || memcmp(file, "LOGH", 4) != 0) {
        free(file);
        return 4;
    }

    uint32_t plain_size = 0;
    memcpy(&plain_size, file + 16, 4);
    int body_len = (int)file_len - BODY_OFF;
    int has_markers = 0;
    for (int k = 0; k + 2 <= body_len; k++) {
        if (file[BODY_OFF + k] == MARKER0 && file[BODY_OFF + k + 1] == MARKER1) {
            if (is_bulk_seam(file + BODY_OFF, body_len, k)) {
                has_markers = 1;
                break;
            }
        }
    }
    if (has_markers) {
        body_len = clean_logh_body(file + BODY_OFF, body_len, verbose);
        long new_len = BODY_OFF + body_len;
        if (new_len < file_len) {
            memset(file + new_len, 0, (size_t)(file_len - new_len));
            file_len = new_len;
        }
    }
    int cipher_len = body_len - (body_len % 16);
    if (cipher_len <= 0) {
        free(file);
        return 4;
    }
    if (plain_size > 0) {
        int aligned = (int)((plain_size + 15U) & ~15U);
        if (aligned > 0 && aligned < cipher_len) {
            cipher_len = aligned;
        }
    }

    uint8_t ctx[CTX_SIZE];
    memset(ctx, 0, sizeof(ctx));
    if (read_ctx(ctx, enc_type, file, (int)file_len) != 0) {
        free(file);
        return 5;
    }

    size_t plain_cap = plain_size > 0 ? plain_size + 64 : (size_t)cipher_len + 64;
    uint8_t *plain = (uint8_t *)calloc(1, plain_cap);
    if (!plain) {
        if (delete_ctx) {
            delete_ctx(ctx);
        }
        free(file);
        return 6;
    }

    uint32_t out_n = 0;
    int rc = decrypt_body(decrypt, ctx, file + BODY_OFF, cipher_len, plain, plain_cap, &out_n);
    if (delete_ctx) {
        delete_ctx(ctx);
    }
    free(file);

    if (verbose) {
        printf("%s: enc=%d cipher=%d rc=%d out=%u\n", in_path, enc_type, cipher_len, rc, out_n);
        if (out_n > 0) {
            printf("head: %.*s\n", out_n > 80 ? 80 : (int)out_n, (char *)plain);
        }
    }

    if (rc != 0 || out_n == 0) {
        free(plain);
        return 7;
    }

    if (out_path && write_file(out_path, plain, out_n) != 0) {
        free(plain);
        return 8;
    }
    if (verbose && out_path) {
        printf("wrote %s (%u bytes)\n", out_path, out_n);
    }

    free(plain);
    return 0;
}

int main(int argc, char **argv) {
    int verbose = 0;
    int argi = 1;
    while (argi < argc && argv[argi][0] == '-') {
        if (strcmp(argv[argi], "-v") == 0) {
            verbose = 1;
        }
        argi++;
    }
    if (argi >= argc) {
        fprintf(stderr, "usage: %s [-v] <logh-file> [out-file]\n", argv[0]);
        return 1;
    }

    void *lib = dlopen("/system/lib64/liblog_util.so", RTLD_NOW);
    if (!lib) {
        lib = dlopen("liblog_util.so", RTLD_NOW);
    }
    if (!lib) {
        fprintf(stderr, "dlopen: %s\n", dlerror());
        return 1;
    }

    const char *in_path = argv[argi];
    const char *out_path = (argi + 1 < argc) ? argv[argi + 1] : NULL;
    int rc = decrypt_logh(lib, in_path, out_path, verbose || out_path == NULL);
    dlclose(lib);
    return rc;
}
