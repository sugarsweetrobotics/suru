/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 sugarsweetrobotics
 * (コンパイルしたプログラムに一緒に入るので、本体の GPL ではなく MIT です。runtime/LICENSE)
 */
/*
 * 「する」のコンパイラが出す LLVM IR と一緒にリンクする実行時ライブラリ。
 * インタプリタ(suru.py)の Interpreter と同じ動きをするように書いている。
 *
 * 値(V)は 64 ビットの整数で表す:
 *   下の 1 ビットが 1 … 整数(残りの 63 ビット)
 *   0               … 値なし(省略できる引数を渡さなかったとき)
 *   それ以外         … ヒープ上のオブジェクトへのポインタ(先頭が tag)
 * メモリは解放しない(プログラムが終わるまで持っておく)。
 */
#include <errno.h>
#include <math.h>
#include <pthread.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

typedef int64_t V;

enum { T_INT = 0, T_FLT = 1, T_BOOL, T_STR, T_LIST, T_REC, T_FN, T_ACT, T_PURE, T_LAZY, T_ADDR, T_BYTES };

typedef struct { int32_t tag; } Hdr;
typedef struct { int32_t tag; double d; } Flt;
typedef struct { int32_t tag; int32_t b; } Bool;
typedef struct { int32_t tag; int64_t n; int64_t ncp; char s[]; } Str;
typedef struct { int32_t tag; int64_t n; V it[]; } List;
typedef struct { int32_t tag; void *p; } Addr; /* 番地: 外部の関数とやりとりする C のポインタ */
typedef struct { int32_t tag; int64_t n; uint8_t d[]; } Bytes; /* バイト列(変更しない) */
typedef struct Ctor {
    const char *name, *type;
    int32_t n;
    const char **fields;
    V nullary;
} Ctor;
typedef struct { int32_t tag; Ctor *c; V v[]; } Rec;

typedef V (*Code)(void *up, V *args, int32_t pos);
enum { FK_CODE, FK_TRAIT, FK_PARTIAL };
struct Trait;
typedef struct Fn {
    int32_t tag, kind;
    const char *name;
    int32_t n;              /* 引数の数(FK_PARTIAL なら元の関数と同じ) */
    const int32_t *parts;   /* 助詞の番号 */
    const uint8_t *req;     /* 必須か(NULL ならすべて必須) */
    Code code;
    void *up;               /* 関数を作った場所のフレーム(または C の関数のデータ) */
    struct Fn *base;        /* FK_PARTIAL: 元の関数 */
    V *bound;               /* FK_PARTIAL: 先に渡した引数(0 は未指定) */
    struct Trait *trait;    /* FK_TRAIT */
    int32_t wo, wo_list;
} Fn;
enum { A_SHOW, A_INPUT, A_RUNALL, A_CHAIN, A_FMAP, A_LISTEN, A_ACCEPT, A_RECVLINE, A_RECV, A_SEND, A_CLOSE, A_TRY, A_CALL, A_PEEK, A_POKE, A_ERRNO, A_FAIL };
typedef struct { int32_t tag, kind; const char *name; V a, b; int32_t pos; } Act;
typedef struct { int32_t tag; V v; } Pure;
typedef struct { int32_t tag, state; Code code; void *up; V v; } Lazy;

#define IS_INT(v) (((v) & 1) != 0)
#define INT_VAL(v) ((v) >> 1)
#define OBJ(v) ((Hdr *)(intptr_t)(v))
#define TAG(v) (IS_INT(v) ? T_INT : OBJ(v)->tag)
#define AS(type, v) ((type *)(intptr_t)(v))
#define INT_MAX62 ((int64_t)((1ULL << 62) - 1))
#define INT_MIN62 (-(int64_t)(1ULL << 62))

static const char *PART_NAMES[] = {"を", "に", "で", "から", "へ", "より", "が"};
enum { P_WO = 0, P_NI, P_DE, P_KARA, P_HE, P_YORI, P_GA };

/* ------------------------------------------------------------------ */
/* メモリ                                                              */
/* ------------------------------------------------------------------ */

static char *arena_ptr;
static size_t arena_left;

void *rt_alloc(int64_t size) {
    size = (size + 15) & ~(int64_t)15;
    if ((size_t)size > arena_left) {
        size_t chunk = size > (1 << 24) ? (size_t)size : (1 << 24);
        arena_ptr = malloc(chunk);
        if (!arena_ptr) { fputs("エラー: メモリが足りません\n", stderr); exit(1); }
        arena_left = chunk;
    }
    void *p = arena_ptr;
    arena_ptr += size;
    arena_left -= size;
    return p;
}

/* ------------------------------------------------------------------ */
/* 文字列バッファ                                                      */
/* ------------------------------------------------------------------ */

typedef struct { char *s; size_t n, cap; } Buf;
static void buf_add(Buf *b, const char *s, size_t n) {
    if (b->n + n + 1 > b->cap) {
        b->cap = (b->n + n + 1) * 2;
        b->s = realloc(b->s, b->cap);
    }
    memcpy(b->s + b->n, s, n);
    b->n += n;
    b->s[b->n] = 0;
}
static void buf_cat(Buf *b, const char *s) { buf_add(b, s, strlen(s)); }
static void buf_printf(Buf *b, const char *fmt, ...) {
    char tmp[512];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(tmp, sizeof tmp, fmt, ap);
    va_end(ap);
    if (n < (int)sizeof tmp) { buf_add(b, tmp, n); return; }
    char *big = malloc(n + 1);
    va_start(ap, fmt);
    vsnprintf(big, n + 1, fmt, ap);
    va_end(ap);
    buf_add(b, big, n);
    free(big);
}

/* ------------------------------------------------------------------ */
/* エラー                                                              */
/* ------------------------------------------------------------------ */

static const char *source_text = "";

static int display_width(const char *s, size_t n) {
    int w = 0;
    for (size_t i = 0; i < n;) {
        unsigned char c = s[i];
        uint32_t cp;
        int len;
        if (c < 0x80) { cp = c; len = 1; }
        else if ((c >> 5) == 6) { cp = c & 0x1f; len = 2; }
        else if ((c >> 4) == 14) { cp = c & 0x0f; len = 3; }
        else { cp = c & 0x07; len = 4; }
        for (int k = 1; k < len && i + k < n; k++) cp = (cp << 6) | (s[i + k] & 0x3f);
        i += len;
        int wide = (cp >= 0x1100 && cp <= 0x115f) || (cp >= 0x2e80 && cp <= 0xa4cf) || (cp >= 0xac00 && cp <= 0xd7a3) ||
                   (cp >= 0xf900 && cp <= 0xfaff) || (cp >= 0xfe30 && cp <= 0xfe4f) || (cp >= 0xff00 && cp <= 0xff60) ||
                   (cp >= 0xffe0 && cp <= 0xffe6) || (cp >= 0x20000 && cp <= 0x3fffd);
        w += wide ? 2 : 1;
    }
    return w;
}

/* 「試行する」の中なら、実行時エラーで止まらずに代わりの動作へ戻る */
typedef struct TryFrame { jmp_buf jb; struct TryFrame *prev; } TryFrame;
static TryFrame *try_top;

__attribute__((noreturn)) static void fail_msg(int32_t pos, const char *msg) {
    fflush(stdout);
    int line = pos & 0xfffff, col = (pos >> 20) & 0x7ff;
    Buf b = {0};
    buf_cat(&b, "エラー: ");
    if (line) {
        if (col) buf_printf(&b, "%d行目 %d文字目: ", line, col);
        else buf_printf(&b, "%d行目: ", line);
    }
    buf_cat(&b, msg);
    if (try_top) {
        /* 試行する の中: エラーの文だけを書いて、代わりの動作へ */
        fprintf(stderr, "%s\n", b.s);
        fflush(stderr);
        free(b.s);
        TryFrame *f = try_top;
        try_top = f->prev;
        longjmp(f->jb, 1);
    }
    /* 該当する行と位置の印 */
    if (line) {
        const char *p = source_text;
        for (int k = 1; k < line && p; k++) {
            p = strchr(p, '\n');
            if (p) p++;
        }
        if (p && *p) {
            const char *e = strchr(p, '\n');
            size_t n = e ? (size_t)(e - p) : strlen(p);
            if (n && p[n - 1] == '\r') n--;
            Buf t = {0};
            for (size_t i = 0; i < n; i++) {
                if (p[i] == '\t') buf_cat(&t, "    ");
                else buf_add(&t, p + i, 1);
            }
            buf_cat(&b, "\n  ");
            if (t.s) buf_cat(&b, t.s);
            if (col) {
                /* col 文字目の手前までの表示幅 */
                size_t i = 0;
                int k = 1;
                Buf pre = {0};
                while (i < n && k < col) {
                    unsigned char c = p[i];
                    int len = c < 0x80 ? 1 : (c >> 5) == 6 ? 2 : (c >> 4) == 14 ? 3 : 4;
                    if (p[i] == '\t') buf_cat(&pre, "    ");
                    else buf_add(&pre, p + i, len);
                    i += len;
                    k++;
                }
                int w = pre.s ? display_width(pre.s, pre.n) : 0;
                buf_cat(&b, "\n  ");
                for (int j = 0; j < w; j++) buf_cat(&b, " ");
                buf_cat(&b, "^");
            }
        }
    }
    fprintf(stderr, "%s\n", b.s);
    exit(1);
}

__attribute__((noreturn)) static void fail(int32_t pos, const char *fmt, ...) {
    char tmp[2048];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(tmp, sizeof tmp, fmt, ap);
    va_end(ap);
    fail_msg(pos, tmp);
}

__attribute__((noreturn)) void rt_fail(const char *msg, int32_t pos) { fail_msg(pos, msg); }

/* ------------------------------------------------------------------ */
/* 値を作る                                                            */
/* ------------------------------------------------------------------ */

static Bool TRUE_OBJ = {T_BOOL, 1}, FALSE_OBJ = {T_BOOL, 0};
#define V_TRUE ((V)(intptr_t)&TRUE_OBJ)
#define V_FALSE ((V)(intptr_t)&FALSE_OBJ)
static List EMPTY_OBJ = {T_LIST, 0};
#define V_EMPTY ((V)(intptr_t)&EMPTY_OBJ)

V rt_bool(int32_t b) { return b ? V_TRUE : V_FALSE; }

static V mk_int(int64_t n, int32_t pos) {
    if (n > INT_MAX62 || n < INT_MIN62)
        fail(pos, "整数が大きすぎます(コンパイルしたプログラムの整数は ±%lld までです)", (long long)INT_MAX62);
    return (V)(((uint64_t)n << 1) | 1);
}

V rt_float(double d) {
    Flt *f = rt_alloc(sizeof(Flt));
    f->tag = T_FLT;
    f->d = d;
    return (V)(intptr_t)f;
}

static int64_t count_cp(const char *s, int64_t n) {
    int64_t k = 0;
    for (int64_t i = 0; i < n; i++)
        if ((s[i] & 0xc0) != 0x80) k++;
    return k;
}

static V mk_str(const char *s, int64_t n) {
    Str *o = rt_alloc(sizeof(Str) + n + 1);
    o->tag = T_STR;
    o->n = n;
    memcpy(o->s, s, n);
    o->s[n] = 0;
    o->ncp = count_cp(s, n);
    return (V)(intptr_t)o;
}
V rt_str(const char *s, int64_t n) { return mk_str(s, n); }
static V cstr(const char *s) { return mk_str(s, strlen(s)); }

static List *new_list(int64_t n) {
    List *l = rt_alloc(sizeof(List) + n * sizeof(V));
    l->tag = T_LIST;
    l->n = n;
    return l;
}
V rt_list(int64_t n, V *items) {
    if (n == 0) return V_EMPTY;
    List *l = new_list(n);
    memcpy(l->it, items, n * sizeof(V));
    return (V)(intptr_t)l;
}

static V mk_pure(V v) {
    Pure *p = rt_alloc(sizeof(Pure));
    p->tag = T_PURE;
    p->v = v;
    return (V)(intptr_t)p;
}

static V mk_act(int kind, const char *name, V a, V b) {
    Act *x = rt_alloc(sizeof(Act));
    x->tag = T_ACT;
    x->kind = kind;
    x->name = name;
    x->a = a;
    x->b = b;
    return (V)(intptr_t)x;
}

V rt_make_fn(const char *name, int32_t n, const int32_t *parts, Code code, void *up) {
    Fn *f = rt_alloc(sizeof(Fn));
    memset(f, 0, sizeof(Fn));
    f->tag = T_FN;
    f->kind = FK_CODE;
    f->name = name;
    f->n = n;
    f->parts = parts;
    f->code = code;
    f->up = up;
    return (V)(intptr_t)f;
}

static V mk_builtin(const char *name, int32_t n, const int32_t *parts, const uint8_t *req, Code code, void *data) {
    V v = rt_make_fn(name, n, parts, code, data);
    AS(Fn, v)->req = req;
    return v;
}

V rt_lazy(Code code, void *up) {
    Lazy *z = rt_alloc(sizeof(Lazy));
    z->tag = T_LAZY;
    z->state = 0;
    z->code = code;
    z->up = up;
    z->v = 0;
    return (V)(intptr_t)z;
}

V rt_force(V v) {
    if (v == 0 || IS_INT(v) || OBJ(v)->tag != T_LAZY) return v;
    Lazy *z = AS(Lazy, v);
    if (z->state == 0) {
        z->v = z->code(z->up, NULL, 0);
        z->state = 1;
    }
    return z->v;
}

/* ------------------------------------------------------------------ */
/* 型と性質の登録                                                      */
/* ------------------------------------------------------------------ */

static Ctor **ctors;
static int nctors;

static Ctor *find_ctor(const char *name) {
    for (int i = 0; i < nctors; i++)
        if (strcmp(ctors[i]->name, name) == 0) return ctors[i];
    return NULL;
}

typedef struct { const char *name; V v; } Entry;
static Entry *shared;
static int nshared, capshared;

static void shared_set(const char *name, V v) {
    for (int i = 0; i < nshared; i++)
        if (strcmp(shared[i].name, name) == 0) { shared[i].v = v; return; }
    if (nshared == capshared) {
        capshared = capshared ? capshared * 2 : 64;
        shared = realloc(shared, capshared * sizeof(Entry));
    }
    shared[nshared].name = name;
    shared[nshared].v = v;
    nshared++;
}

static V shared_get(const char *name) {
    for (int i = 0; i < nshared; i++)
        if (strcmp(shared[i].name, name) == 0) return shared[i].v;
    return 0;
}

void rt_def_ctor(const char *name, const char *type, int32_t n, const char **fields) {
    Ctor *c = malloc(sizeof(Ctor));
    c->name = name;
    c->type = type;
    c->n = n;
    c->fields = fields;
    c->nullary = 0;
    ctors = realloc(ctors, (nctors + 1) * sizeof(Ctor *));
    ctors[nctors++] = c;
    if (n == 0) {
        Rec *r = rt_alloc(sizeof(Rec));
        r->tag = T_REC;
        r->c = c;
        c->nullary = (V)(intptr_t)r;
        shared_set(name, c->nullary);
    }
}

typedef struct { const char *name; int32_t n; const int32_t *parts; V deflt; } Method;
typedef struct Trait { const char *name; int nm; Method *m; } Trait;
typedef struct { Trait *t; const char *type; int n; const char **names; V *fns; } Impl;

static Trait **traits;
static int ntraits;
static Impl *impls;
static int nimpls;

static Trait *find_trait(const char *name) {
    for (int i = 0; i < ntraits; i++)
        if (strcmp(traits[i]->name, name) == 0) return traits[i];
    return NULL;
}

void rt_trait(const char *name) {
    Trait *t = calloc(1, sizeof(Trait));
    t->name = name;
    traits = realloc(traits, (ntraits + 1) * sizeof(Trait *));
    traits[ntraits++] = t;
}

/* 性質の関数を宣言する。wo は「を」の引数の位置、wo_list はそれが「a と b」のように分解する引数か */
void rt_trait_method(const char *trait, const char *name, int32_t n, const int32_t *parts, int32_t wo,
                     int32_t wo_list, V deflt) {
    Trait *t = find_trait(trait);
    t->m = realloc(t->m, (t->nm + 1) * sizeof(Method));
    t->m[t->nm].name = name;
    t->m[t->nm].n = n;
    t->m[t->nm].parts = parts;
    t->m[t->nm].deflt = deflt;
    t->nm++;
    Fn *f = AS(Fn, rt_make_fn(name, n, parts, NULL, NULL));
    f->kind = FK_TRAIT;
    f->trait = t;
    f->wo = wo;
    f->wo_list = wo_list;
    shared_set(name, (V)(intptr_t)f);
}

static Impl *find_impl(const char *trait, const char *type) {
    for (int i = 0; i < nimpls; i++)
        if (strcmp(impls[i].t->name, trait) == 0 && strcmp(impls[i].type, type) == 0) return &impls[i];
    return NULL;
}

void rt_impl(const char *trait, const char *type, const char *name, V fn) {
    Impl *im = find_impl(trait, type);
    if (!im) {
        impls = realloc(impls, (nimpls + 1) * sizeof(Impl));
        im = &impls[nimpls++];
        im->t = find_trait(trait);
        im->type = type;
        im->n = 0;
        im->names = NULL;
        im->fns = NULL;
    }
    if (name == NULL) return; /* 関数を1つも定義しない実装(既定の実装だけを使う) */
    im->names = realloc(im->names, (im->n + 1) * sizeof(char *));
    im->fns = realloc(im->fns, (im->n + 1) * sizeof(V));
    im->names[im->n] = name;
    im->fns[im->n] = fn;
    im->n++;
}

static V impl_fn(Impl *im, const char *name) {
    for (int i = 0; i < im->n; i++)
        if (strcmp(im->names[i], name) == 0) return im->fns[i];
    return 0;
}

static const char *SHOWABLE = "表示可能", *TO_STRING = "文字列化する", *MAPPABLE = "写像可能",
                  *MONAD = "連鎖可能", *MAP = "写像する", *BIND = "連鎖する", *UNIT = "結果にする";

static const char *type_name_of(V v) {
    switch (TAG(v)) {
    case T_REC: return AS(Rec, v)->c->type;
    case T_ACT: case T_PURE: return "動作";
    case T_BOOL: return "真偽";
    case T_INT: case T_FLT: return "数";
    case T_STR: return "文字列";
    case T_LIST: return "リスト";
    case T_ADDR: return "番地";
    case T_BYTES: return "バイト列";
    default: return "関数";
    }
}

/* ------------------------------------------------------------------ */
/* 表示                                                                */
/* ------------------------------------------------------------------ */

static void fmt_into(Buf *b, V v, int nested, int use_traits);
V rt_call(V fn, int32_t n, const int32_t *parts, const V *vals, int32_t pos);

static void fmt_float(Buf *b, double d) {
    if (isnan(d)) { buf_cat(b, "nan"); return; }
    if (isinf(d)) { buf_cat(b, d > 0 ? "inf" : "-inf"); return; }
    if (d == floor(d)) {
        if (d == 0) { buf_cat(b, "0"); return; }
        buf_printf(b, "%.0f", d);
        return;
    }
    char tmp[64];
    for (int p = 1; p <= 17; p++) {
        snprintf(tmp, sizeof tmp, "%.*g", p, d);
        if (strtod(tmp, NULL) == d) break;
    }
    buf_cat(b, tmp);
}

static void fmt_value(Buf *b, V v, int nested, int use_traits) {
    switch (TAG(v)) {
    case T_INT: buf_printf(b, "%lld", (long long)INT_VAL(v)); return;
    case T_FLT: fmt_float(b, AS(Flt, v)->d); return;
    case T_BOOL: buf_cat(b, AS(Bool, v)->b ? "真" : "偽"); return;
    case T_STR:
        if (nested) buf_cat(b, "「");
        buf_add(b, AS(Str, v)->s, AS(Str, v)->n);
        if (nested) buf_cat(b, "」");
        return;
    case T_LIST: {
        List *l = AS(List, v);
        if (l->n == 0) { buf_cat(b, "空"); return; }
        buf_cat(b, "（");
        for (int64_t i = 0; i < l->n; i++) {
            if (i) buf_cat(b, " と ");
            fmt_into(b, l->it[i], 1, use_traits);
        }
        buf_cat(b, "）");
        return;
    }
    case T_REC: {
        Rec *r = AS(Rec, v);
        if (r->c->n == 0) { buf_cat(b, r->c->name); return; }
        buf_cat(b, "（");
        for (int i = 0; i < r->c->n; i++) {
            if (i) buf_cat(b, " で ");
            buf_cat(b, r->c->fields[i]);
            buf_cat(b, " は ");
            fmt_into(b, r->v[i], 1, use_traits);
        }
        buf_cat(b, " の ");
        buf_cat(b, r->c->name);
        buf_cat(b, "）");
        return;
    }
    case T_FN: {
        Fn *f = AS(Fn, v);
        buf_printf(b, "<関数 %s>", f->kind == FK_PARTIAL ? f->base->name : f->name);
        return;
    }
    case T_ACT: buf_printf(b, "<動作 %s>", AS(Act, v)->name); return;
    case T_PURE: buf_cat(b, "<動作 結果にする>"); return;
    case T_ADDR: buf_printf(b, "番地(0x%llx)", (unsigned long long)(uintptr_t)AS(Addr, v)->p); return;
    case T_BYTES: {
        Bytes *x = AS(Bytes, v);
        buf_cat(b, "バイト列（");
        for (int64_t i = 0; i < x->n; i++) buf_printf(b, i ? " %02x" : "%02x", x->d[i]);
        buf_cat(b, "）");
        return;
    }
    default: buf_cat(b, "?"); return;
    }
}

static const int32_t PARTS_WO[] = {P_WO};

/* 性質「表示可能」が実装されていれば「文字列化する」を使う */
static void fmt_into(Buf *b, V v, int nested, int use_traits) {
    if (use_traits) {
        Impl *im = find_impl(SHOWABLE, type_name_of(v));
        V fn = im ? impl_fn(im, TO_STRING) : 0;
        if (fn) {
            V s = rt_call(fn, 1, PARTS_WO, &v, 0);
            if (TAG(s) == T_STR) buf_add(b, AS(Str, s)->s, AS(Str, s)->n);
            else fmt_value(b, s, 0, 0);
            return;
        }
    }
    fmt_value(b, v, nested, use_traits);
}

static V format_v(V v) {
    Buf b = {0};
    fmt_into(&b, v, 0, 1);
    return mk_str(b.s ? b.s : "", b.n);
}

/* 性質を使わない表示(文字列の + で使う) */
static Buf plain(V v) {
    Buf b = {0};
    fmt_value(&b, v, 0, 0);
    if (!b.s) buf_add(&b, "", 0);
    return b;
}

static const char *show(V v) {
    Buf b = {0};
    fmt_into(&b, v, 0, 1);
    return b.s ? b.s : "";
}

static const char *action_hint(V v) {
    int t = TAG(v);
    if (t == T_ACT || t == T_PURE)
        return "。動作の結果を使うときは、「…してから」か、手順の中で「…した 結果」を使ってください";
    return "";
}

/* ------------------------------------------------------------------ */
/* 計算                                                                */
/* ------------------------------------------------------------------ */

static int is_num(V v) { int t = TAG(v); return t == T_INT || t == T_FLT; }
static double num_d(V v) { return IS_INT(v) ? (double)INT_VAL(v) : AS(Flt, v)->d; }

static V need_num(V v, int32_t pos) {
    int t = TAG(v);
    if (t == T_ACT || t == T_PURE) fail(pos, "動作「%s」で計算しようとしました%s", show(v), action_hint(v));
    if (!is_num(v)) fail(pos, "数ではない値「%s」で計算しようとしました", show(v));
    return v;
}

static List *need_list(V v, const char *what, int32_t pos) {
    if (TAG(v) != T_LIST) fail(pos, "%sはリストでなければなりません(「%s」が渡されました)", what, plain(v).s);
    return AS(List, v);
}

int32_t rt_eq(V a, V b) {
    if (a == b) return 1;
    int ta = TAG(a), tb = TAG(b);
    if (is_num(a) && is_num(b)) {
        if (ta == T_INT && tb == T_INT) return 0;
        return num_d(a) == num_d(b);
    }
    if (ta != tb) return 0;
    switch (ta) {
    case T_BOOL: return AS(Bool, a)->b == AS(Bool, b)->b;
    case T_STR: return AS(Str, a)->n == AS(Str, b)->n && memcmp(AS(Str, a)->s, AS(Str, b)->s, AS(Str, a)->n) == 0;
    case T_LIST: {
        List *x = AS(List, a), *y = AS(List, b);
        if (x->n != y->n) return 0;
        for (int64_t i = 0; i < x->n; i++)
            if (!rt_eq(x->it[i], y->it[i])) return 0;
        return 1;
    }
    case T_REC: {
        Rec *x = AS(Rec, a), *y = AS(Rec, b);
        if (x->c != y->c) return 0;
        for (int i = 0; i < x->c->n; i++)
            if (!rt_eq(x->v[i], y->v[i])) return 0;
        return 1;
    }
    case T_PURE: return rt_eq(AS(Pure, a)->v, AS(Pure, b)->v);
    case T_ADDR: return AS(Addr, a)->p == AS(Addr, b)->p;
    case T_BYTES: return AS(Bytes, a)->n == AS(Bytes, b)->n && memcmp(AS(Bytes, a)->d, AS(Bytes, b)->d, AS(Bytes, a)->n) == 0;
    default: return 0;
    }
}

/* 演算子の番号(コンパイラと同じ順) */
enum { OP_ADD, OP_SUB, OP_MUL, OP_DIV, OP_MOD, OP_POW, OP_LT, OP_GT, OP_LE, OP_GE, OP_EQ, OP_NE };

static V concat_lists(List *x, List *y) {
    if (x->n == 0) return (V)(intptr_t)y;
    if (y->n == 0) return (V)(intptr_t)x;
    List *l = new_list(x->n + y->n);
    memcpy(l->it, x->it, x->n * sizeof(V));
    memcpy(l->it + x->n, y->it, y->n * sizeof(V));
    return (V)(intptr_t)l;
}

static double py_fmod(double a, double b) {
    double m = fmod(a, b);
    if (m != 0 && ((m < 0) != (b < 0))) m += b;
    return m;
}

V rt_binop(int32_t op, V a, V b, int32_t pos) {
    if (op == OP_EQ) return rt_bool(rt_eq(a, b));
    if (op == OP_NE) return rt_bool(!rt_eq(a, b));
    if (op == OP_ADD && TAG(a) == T_LIST && TAG(b) == T_LIST) return concat_lists(AS(List, a), AS(List, b));
    if (op == OP_ADD && (TAG(a) == T_STR || TAG(b) == T_STR)) {
        Buf x = plain(a), y = plain(b);
        buf_add(&x, y.s, y.n);
        return mk_str(x.s, x.n);
    }
    need_num(a, pos);
    need_num(b, pos);
    if (IS_INT(a) && IS_INT(b)) {
        int64_t x = INT_VAL(a), y = INT_VAL(b), r;
        switch (op) {
        case OP_ADD: return mk_int(x + y, pos);
        case OP_SUB: return mk_int(x - y, pos);
        case OP_MUL:
            if (__builtin_mul_overflow(x, y, &r)) mk_int(INT_MAX62 + 1, pos);
            return mk_int(r, pos);
        case OP_DIV:
            if (y == 0) fail(pos, "0 で割ることはできません");
            if (x % y == 0) return mk_int(x / y, pos);
            return rt_float((double)x / (double)y);
        case OP_MOD: {
            if (y == 0) fail(pos, "0 で割ることはできません");
            int64_t m = x % y;
            if (m != 0 && ((m < 0) != (y < 0))) m += y;
            return mk_int(m, pos);
        }
        case OP_POW: {
            if (y < 0) return rt_float(pow((double)x, (double)y));
            int64_t acc = 1, base = x;
            int64_t e = y;
            while (e > 0) {
                if (e & 1) {
                    if (__builtin_mul_overflow(acc, base, &acc) || acc > INT_MAX62 || acc < INT_MIN62) mk_int(INT_MAX62 + 1, pos);
                }
                e >>= 1;
                if (e > 0 && __builtin_mul_overflow(base, base, &base)) {
                    /* 次に使うときだけ溢れが問題になる */
                    base = INT_MAX62 + 1;
                }
            }
            return mk_int(acc, pos);
        }
        case OP_LT: return rt_bool(x < y);
        case OP_GT: return rt_bool(x > y);
        case OP_LE: return rt_bool(x <= y);
        case OP_GE: return rt_bool(x >= y);
        }
    }
    double x = num_d(a), y = num_d(b);
    switch (op) {
    case OP_ADD: return rt_float(x + y);
    case OP_SUB: return rt_float(x - y);
    case OP_MUL: return rt_float(x * y);
    case OP_DIV:
        if (y == 0) fail(pos, "0 で割ることはできません");
        return rt_float(x / y);
    case OP_MOD:
        if (y == 0) fail(pos, "0 で割ることはできません");
        return rt_float(py_fmod(x, y));
    case OP_POW: return rt_float(pow(x, y));
    case OP_LT: return rt_bool(x < y);
    case OP_GT: return rt_bool(x > y);
    case OP_LE: return rt_bool(x <= y);
    case OP_GE: return rt_bool(x >= y);
    }
    fail(pos, "未知の演算子");
}

V rt_neg(V v, int32_t pos) {
    need_num(v, 0);
    if (IS_INT(v)) return mk_int(-INT_VAL(v), pos);
    return rt_float(-AS(Flt, v)->d);
}

/* Python の真偽の扱い(「もし」の条件) */
int32_t rt_truthy(V v) {
    switch (TAG(v)) {
    case T_INT: return INT_VAL(v) != 0;
    case T_FLT: return AS(Flt, v)->d != 0;
    case T_BOOL: return AS(Bool, v)->b;
    case T_STR: return AS(Str, v)->n != 0;
    case T_LIST: return AS(List, v)->n != 0;
    default: return 1;
    }
}

/* 「かつ」「または」「でない」: 真か偽でなければエラー */
int32_t rt_truth(V v, const char *what, int32_t pos) {
    if (TAG(v) != T_BOOL) fail(pos, "「%s」の条件は 真 か 偽 でなければなりません(「%s」でした)", what, show(v));
    return AS(Bool, v)->b;
}

V rt_pred_check(V v, const char *fname, int32_t pos) {
    if (TAG(v) != T_BOOL) fail(pos, "述語「%s」は 真 か 偽 を返す必要があります(「%s」が返りました)", fname, show(v));
    return v;
}

/* ------------------------------------------------------------------ */
/* 組・リストの中身                                                    */
/* ------------------------------------------------------------------ */

static int field_index(Rec *r, const char *name) {
    for (int i = 0; i < r->c->n; i++)
        if (strcmp(r->c->fields[i], name) == 0) return i;
    return -1;
}

V rt_field(V v, const char *name, int32_t pos) {
    if (TAG(v) == T_REC) {
        int i = field_index(AS(Rec, v), name);
        if (i >= 0) return AS(Rec, v)->v[i];
    }
    fail(pos, "「%s」には「%s」というフィールドがありません", plain(v).s, name);
}

static int32_t is_monadic(V v);

V rt_field_result(V v, int32_t pos) {
    if (TAG(v) != T_REC && is_monadic(v))
        fail(pos, "「の 結果」は「入力 の 結果 を 数値にする」のように呼び出しの引数に書いてください");
    return rt_field(v, "結果", pos);
}

V rt_prop(V v, const char *name, int32_t pos) {
    if (TAG(v) == T_REC) return rt_field(v, name, pos);
    if (strcmp(name, "長さ") == 0) {
        if (TAG(v) == T_STR) return mk_int(AS(Str, v)->ncp, pos);
        return mk_int(need_list(v, "「の 長さ」の前", pos)->n, pos);
    }
    char what[256];
    snprintf(what, sizeof what, "「の %s」の前", name);
    List *l = need_list(v, what, pos);
    if (strcmp(name, "残り") == 0) {
        if (l->n == 0) fail(pos, "空のリストに「残り」はありません");
        return rt_list(l->n - 1, l->it + 1);
    }
    if (l->n == 0) fail(pos, "空のリストに「%s」はありません", name);
    return strcmp(name, "先頭") == 0 ? l->it[0] : l->it[l->n - 1];
}

V rt_each_check(V v, int32_t pos) {
    need_list(v, "「の それぞれ」の前", pos);
    return v;
}

/* パターンマッチ */
int32_t rt_is_list_len(V v, int64_t n) { return TAG(v) == T_LIST && AS(List, v)->n == n; }
V rt_list_at(V v, int64_t i) { return AS(List, v)->it[i]; }
int32_t rt_is_ctor(V v, const char *ctor) { return TAG(v) == T_REC && strcmp(AS(Rec, v)->c->name, ctor) == 0; }
V rt_rec_at(V v, int64_t i) { return AS(Rec, v)->v[i]; }
int64_t rt_rec_size(V v) { return AS(Rec, v)->c->n; }

/* 「先頭 は x で 残り は 他」: フィールドの値。なければ 0 */
V rt_named_get(V v, const char *fname) {
    if (TAG(v) == T_REC) {
        int i = field_index(AS(Rec, v), fname);
        return i >= 0 ? AS(Rec, v)->v[i] : 0;
    }
    if (TAG(v) == T_LIST && AS(List, v)->n > 0) {
        List *l = AS(List, v);
        if (strcmp(fname, "先頭") == 0) return l->it[0];
        if (strcmp(fname, "残り") == 0) return rt_list(l->n - 1, l->it + 1);
    }
    return 0;
}

/* 引数「a と b を」: 決まった数の値のリスト */
V rt_bind_seq(V v, int64_t n, int32_t part, const char *fname, int32_t pos) {
    if (TAG(v) != T_LIST || AS(List, v)->n != n) {
        char got[64];
        if (TAG(v) == T_LIST) snprintf(got, sizeof got, "%lld個のリスト", (long long)AS(List, v)->n);
        else snprintf(got, sizeof got, "1個の値");
        fail(pos, "「%s」の「%s」には%lld個の値が必要です(渡されたのは%s)", fname, PART_NAMES[part], (long long)n, got);
    }
    return v;
}

__attribute__((noreturn)) void rt_no_match(V v, const char *fname, int32_t pos) {
    if (fname && *fname) fail(pos, "「%s」は「%s」のどの定義にも当てはまりません", show(v), fname);
    fail(pos, "「%s」はどの場合にも当てはまりません", show(v));
}

__attribute__((noreturn)) void rt_run_outside(int32_t pos) {
    fail(pos, "「した 結果」は手順の文の中で使ってください(関数の本体や条件分岐の枝の中では、そこを「手順（…）」で囲みます)");
}

V rt_construct(const char *ctor, int32_t n, const V *vals, int32_t pos) {
    Ctor *c = find_ctor(ctor);
    if (n == 1 && c->n >= 2 && TAG(vals[0]) == T_LIST && AS(List, vals[0])->n == c->n) {
        vals = AS(List, vals[0])->it; /* 「（3 と 4） の 点」 */
        n = c->n;
    }
    if (n != c->n) fail(pos, "「%s」には%d個の値が必要です(渡されたのは%d個)", ctor, c->n, n);
    if (n == 0) return c->nullary;
    Rec *r = rt_alloc(sizeof(Rec) + n * sizeof(V));
    r->tag = T_REC;
    r->c = c;
    memcpy(r->v, vals, n * sizeof(V));
    return (V)(intptr_t)r;
}

V rt_update(V target, int32_t n, const char **fields, const V *vals, int32_t pos) {
    for (int k = 0; k < n; k++)
        if (TAG(target) != T_REC || field_index(AS(Rec, target), fields[k]) < 0)
            fail(pos, "「%s」には「%s」というフィールドがありません", plain(target).s, fields[k]);
    Rec *old = AS(Rec, target);
    Rec *r = rt_alloc(sizeof(Rec) + old->c->n * sizeof(V));
    r->tag = T_REC;
    r->c = old->c;
    memcpy(r->v, old->v, old->c->n * sizeof(V));
    for (int k = 0; k < n; k++) r->v[field_index(r, fields[k])] = vals[k];
    return (V)(intptr_t)r;
}

/* ------------------------------------------------------------------ */
/* 呼び出し                                                            */
/* ------------------------------------------------------------------ */

static const char *fn_name(Fn *f) { return f->kind == FK_PARTIAL ? f->base->name : f->name; }

static Fn *need_fn(V v, int32_t pos) {
    if (TAG(v) != T_FN) fail(pos, "「%s」は関数ではありません", plain(v).s);
    return AS(Fn, v);
}

static int slot_of(Fn *f, int32_t part) {
    for (int i = 0; i < f->n; i++)
        if (f->parts[i] == part) return i;
    return -1;
}

static int is_req(Fn *f, int i) { return f->req ? f->req[i] : 1; }

static V dispatch(Fn *m, V *args, int32_t pos);

/* 引数を位置(助詞の順)で並べた配列で呼ぶ。足りない引数は 0 */
static V invoke(Fn *f, V *args, int32_t pos) {
    for (int i = 0; i < f->n; i++)
        if (args[i] == 0 && is_req(f, i)) fail(pos, "「%s」には「%s」の引数が必要です", f->name, PART_NAMES[f->parts[i]]);
    if (f->kind == FK_TRAIT) return dispatch(f, args, pos);
    return f->code(f->up, args, pos);
}

V rt_call(V fnv, int32_t n, const int32_t *parts, const V *vals, int32_t pos) {
    Fn *f = need_fn(fnv, pos);
    V args[16] = {0};
    Fn *base = f;
    if (f->kind == FK_PARTIAL) {
        base = f->base;
        for (int k = 0; k < n; k++) {
            int i = slot_of(base, parts[k]);
            if (i >= 0 && f->bound[i]) fail(pos, "「%s」の「%s」は既に渡されています", base->name, PART_NAMES[parts[k]]);
        }
        memcpy(args, f->bound, base->n * sizeof(V));
    }
    for (int k = 0; k < n; k++) {
        int i = slot_of(base, parts[k]);
        if (i < 0) fail(pos, "「%s」は「%s」の引数を受け取りません", base->name, PART_NAMES[parts[k]]);
        args[i] = vals[k];
    }
    return invoke(base, args, pos);
}

static V partial(Fn *f, int32_t n, const int32_t *parts, const V *vals, int32_t pos) {
    Fn *base = f->kind == FK_PARTIAL ? f->base : f;
    V *bound = rt_alloc(base->n * sizeof(V));
    memset(bound, 0, base->n * sizeof(V));
    if (f->kind == FK_PARTIAL) memcpy(bound, f->bound, base->n * sizeof(V));
    for (int k = 0; k < n; k++) {
        int i = slot_of(base, parts[k]);
        if (i < 0 || (f->kind == FK_PARTIAL && f->bound[i]))
            fail(pos, "「%s」は「%s」の引数を受け取りません", base->name, PART_NAMES[parts[k]]);
        bound[i] = vals[k];
    }
    Fn *p = rt_alloc(sizeof(Fn));
    *p = *base;
    p->kind = FK_PARTIAL;
    p->base = base;
    p->bound = bound;
    return (V)(intptr_t)p;
}

/* 「三倍すること」「1 を 加算すること」 */
V rt_ref(V fnv, int32_t n, const int32_t *parts, const V *vals, const char *name, int32_t pos) {
    if (TAG(fnv) != T_FN) fail(pos, "「%s」は関数ではありません", name);
    if (n == 0) return fnv;
    return partial(AS(Fn, fnv), n, parts, vals, pos);
}

/* まだ渡していない引数を定義の順に埋めて呼ぶ。足りなければ部分適用 */
static V apply(V fnv, int n, const V *vals, int32_t pos) {
    Fn *f = need_fn(fnv, pos);
    Fn *base = f->kind == FK_PARTIAL ? f->base : f;
    int32_t parts[16];
    int k = 0, missing = 0;
    for (int i = 0; i < base->n; i++) {
        if (f->kind == FK_PARTIAL && f->bound[i]) continue;
        if (k < n) parts[k++] = base->parts[i];
        else if (is_req(base, i)) missing = 1;
    }
    if (k < n) fail(pos, "「%s」に渡す値が多すぎます", base->name);
    if (missing) return partial(f, n, parts, vals, pos);
    return rt_call(fnv, n, parts, vals, pos);
}

static V apply1(V fnv, V x, int32_t pos) { return apply(fnv, 1, &x, pos); }

static int required_slots(V fnv, int32_t pos) {
    Fn *f = need_fn(fnv, pos);
    Fn *base = f->kind == FK_PARTIAL ? f->base : f;
    int c = 0;
    for (int i = 0; i < base->n; i++)
        if (!(f->kind == FK_PARTIAL && f->bound[i]) && is_req(base, i)) c++;
    return c;
}

/* 性質の関数: 「を」の値の型で実装を選ぶ */
static V dispatch(Fn *m, V *args, int32_t pos) {
    V v = args[m->wo];
    if (m->wo_list && TAG(v) == T_LIST && AS(List, v)->n > 0) v = AS(List, v)->it[0];
    const char *tname = type_name_of(v);
    Impl *im = find_impl(m->trait->name, tname);
    if (!im) {
        if (strcmp(m->trait->name, SHOWABLE) == 0) return format_v(args[m->wo]);
        fail(pos, "「%s」は性質「%s」を持っていません(「%s」が使えません)", tname, m->trait->name, m->name);
    }
    V fn = impl_fn(im, m->name);
    if (!fn) {
        for (int i = 0; i < m->trait->nm; i++)
            if (strcmp(m->trait->m[i].name, m->name) == 0) fn = m->trait->m[i].deflt;
    }
    return rt_call(fn, m->n, m->parts, args, pos);
}

/* ------------------------------------------------------------------ */
/* 動作と連鎖                                                          */
/* ------------------------------------------------------------------ */

static V perform(V v);
static V net_run(Act *a);
static V mem_run(Act *a);

static V act_run(Act *a) {
    switch (a->kind) {
    case A_SHOW: {
        const char *s = show(a->a);
        fputs(s, stdout);
        fputc('\n', stdout);
        return a->a;
    }
    case A_INPUT: {
        if (a->a) { fputs(AS(Str, a->a)->s, stdout); }
        fflush(stdout);
        char *line = NULL;
        size_t cap = 0;
        ssize_t n = getline(&line, &cap, stdin);
        if (n < 0) fail((int32_t)a->b, "入力がありません");
        if (n > 0 && line[n - 1] == '\n') n--;
        if (n > 0 && line[n - 1] == '\r') n--;
        return mk_str(line, n);
    }
    case A_LISTEN: case A_ACCEPT: case A_RECVLINE: case A_RECV: case A_SEND: case A_CLOSE:
        return net_run(a);
    case A_TRY: {
        TryFrame f;
        f.prev = try_top;
        try_top = &f;
        if (setjmp(f.jb) == 0) {
            V r = perform(a->a);
            try_top = f.prev;
            return r;
        }
        return perform(a->b); /* fail_msg が try_top を戻している */
    }
    case A_RUNALL: {
        List *l = AS(List, a->a);
        if (l->n == 0) return V_EMPTY;
        List *out = new_list(l->n);
        for (int64_t i = 0; i < l->n; i++) out->it[i] = perform(l->it[i]);
        return (V)(intptr_t)out;
    }
    case A_CALL: return apply1(a->a, V_EMPTY, a->pos); /* 外部の関数を呼ぶ動作 */
    case A_PEEK: case A_POKE: case A_ERRNO: case A_FAIL: return mem_run(a);
    case A_CHAIN: return apply1(a->b, perform(a->a), 0); /* 続きの動作は perform のループで行う */
    case A_FMAP: return apply1(a->b, perform(a->a), 0);
    }
    return 0;
}

static V perform(V v) {
    for (;;) {
        int t = TAG(v);
        if (t == T_ACT) {
            v = act_run(AS(Act, v));
            int t2 = TAG(v);
            if (t2 != T_ACT && t2 != T_PURE) return v;
            continue;
        }
        if (t == T_PURE) return AS(Pure, v)->v;
        return v;
    }
}

static Impl *monad_impl(V m) {
    if (TAG(m) == T_REC) return find_impl(MONAD, AS(Rec, m)->c->type);
    return NULL;
}

static int32_t is_monadic(V v) {
    int t = TAG(v);
    return t == T_ACT || t == T_PURE || t == T_LIST || monad_impl(v) != NULL;
}

static V coerce(V r, V like, int32_t pos) {
    if (TAG(r) != T_PURE) return r;
    V x = AS(Pure, r)->v;
    if (TAG(like) == T_LIST) return rt_list(1, &x);
    Impl *im = monad_impl(like);
    V u = im ? impl_fn(im, UNIT) : 0;
    if (u) return rt_call(u, 1, PARTS_WO, &x, pos);
    return r;
}

/* C で書いた関数の値(データ付き) */
typedef struct { V f, m; int32_t pos; } KData;

static V k_cont(void *up, V *args, int32_t pos) {
    KData *d = up;
    return coerce(apply1(d->f, args[0], d->pos), d->m, d->pos);
}
static V k_map(void *up, V *args, int32_t pos) {
    KData *d = up;
    return apply1(d->f, args[0], d->pos);
}
static V k_pure_map(void *up, V *args, int32_t pos) {
    KData *d = up;
    return mk_pure(apply1(d->f, args[0], d->pos));
}

static V mk_k(const char *name, Code code, V f, V m, int32_t pos) {
    KData *d = rt_alloc(sizeof(KData));
    d->f = f;
    d->m = m;
    d->pos = pos;
    return mk_builtin(name, 1, PARTS_WO, NULL, code, d);
}

static const int32_t PARTS_WO_DE[] = {P_WO, P_DE};

/* m を行い、その結果を f(1引数の関数の値)に渡す。モナドのバインド */
static V chain(V m, V f, int32_t pos) {
    int t = TAG(m);
    if (t == T_PURE) return apply1(f, AS(Pure, m)->v, pos);
    if (t == T_ACT) return mk_act(A_CHAIN, AS(Act, m)->name, m, f);
    if (t == T_LIST) {
        List *l = AS(List, m);
        V out = V_EMPTY;
        for (int64_t i = 0; i < l->n; i++) {
            V r = coerce(apply1(f, l->it[i], pos), m, pos);
            if (TAG(r) != T_LIST) fail(pos, "リストを連鎖するときは、続きもリストを返す必要があります(「%s」が返りました)", show(r));
            out = concat_lists(AS(List, out), AS(List, r));
        }
        return out;
    }
    if (!monad_impl(m)) fail(pos, "「%s」は動作ではありません(性質「%s」を持っていません)", show(m), MONAD);
    V k = mk_k("続き", k_cont, f, m, pos);
    V vals[2] = {m, k};
    return rt_call(shared_get(BIND), 2, PARTS_WO_DE, vals, pos);
}

static V fmap(V m, V f, int32_t pos) {
    int t = TAG(m);
    if (t == T_PURE) return mk_pure(apply1(f, AS(Pure, m)->v, pos));
    if (t == T_ACT) return mk_act(A_FMAP, AS(Act, m)->name, m, f);
    if (t == T_LIST) {
        List *l = AS(List, m);
        if (l->n == 0) return V_EMPTY;
        List *out = new_list(l->n);
        for (int64_t i = 0; i < l->n; i++) out->it[i] = apply1(f, l->it[i], pos);
        return (V)(intptr_t)out;
    }
    if (t == T_REC && find_impl(MAPPABLE, AS(Rec, m)->c->type)) {
        V k = mk_k("関数", k_map, f, 0, pos);
        V vals[2] = {m, k};
        return rt_call(shared_get(MAP), 2, PARTS_WO_DE, vals, pos);
    }
    if (monad_impl(m)) return chain(m, mk_k("関数", k_pure_map, f, 0, pos), pos);
    fail(pos, "「%s」は性質「%s」を持っていません(「の 結果」が使えません)", show(m), MAPPABLE);
}

/* 「…してから」 */
V rt_chain_then(V m, V k, int32_t pos) {
    if (!is_monadic(m)) fail(pos, "「してから」の前の「%s」は動作ではありません(純粋な値なら「して」を使います)", show(m));
    return chain(m, k, pos);
}

/* 手順の中の「…した 結果」 */
V rt_do_run(V m, V k, const char *name, int32_t pos) {
    if (!is_monadic(m)) fail(pos, "「%sした 結果」: 「%s」は動作ではありません", name, show(m));
    return chain(m, k, pos);
}

/* 手順の途中の文 */
V rt_do_seq(V v, V k, int32_t pos) {
    if (!is_monadic(v)) fail(pos, "手順の途中の文の値「%s」は動作ではありません", show(v));
    return chain(v, k, pos);
}

V rt_do_result(V v) { return is_monadic(v) ? v : mk_pure(v); }

/* 「の 結果」の引数: 1つなら写像、2つ以上なら前から順に連鎖して最後を写像する */
typedef struct { V fn; int32_t n; const int32_t *parts; V *vals; int32_t *lift; int32_t nlift; int32_t pos; } LiftData;

static V lift_call(LiftData *d);

static V k_lift(void *up, V *args, int32_t pos) {
    LiftData *d = up;
    LiftData *e = rt_alloc(sizeof(LiftData));
    *e = *d;
    e->vals = rt_alloc(d->n * sizeof(V));
    memcpy(e->vals, d->vals, d->n * sizeof(V));
    e->vals[d->lift[0]] = args[0];
    e->lift = d->lift + 1;
    e->nlift = d->nlift - 1;
    if (e->nlift == 0) return rt_call(e->fn, e->n, e->parts, e->vals, e->pos);
    return lift_call(e);
}

static V lift_call(LiftData *d) {
    V m = d->vals[d->lift[0]];
    V k = mk_builtin("続き", 1, PARTS_WO, NULL, k_lift, d);
    if (d->nlift == 1) return fmap(m, k, d->pos);
    return chain(m, k, d->pos);
}

/* 「の それぞれ」(flags 1)や「の 結果」(flags 2)を含む呼び出し */
V rt_call_ex(V fn, int32_t n, const int32_t *parts, const V *vals0, const int32_t *flags, int32_t pos) {
    V *vals = rt_alloc(n * sizeof(V));
    memcpy(vals, vals0, n * sizeof(V));
    int32_t *lift = rt_alloc(n * sizeof(int32_t));
    int nlift = 0, neach = 0;
    for (int k = 0; k < n; k++) {
        if (flags[k] == 2) {
            V t = vals[k];
            if (TAG(t) == T_REC && field_index(AS(Rec, t), "結果") >= 0) vals[k] = rt_field(t, "結果", pos);
            else lift[nlift++] = k;
        } else if (flags[k] == 1) {
            neach++;
        }
    }
    if (nlift) {
        if (neach) fail(pos, "「の 結果」と「の それぞれ」は1つの呼び出しに一緒に書けません");
        LiftData *d = rt_alloc(sizeof(LiftData));
        d->fn = fn;
        d->n = n;
        d->parts = parts;
        d->vals = vals;
        d->lift = lift;
        d->nlift = nlift;
        d->pos = pos;
        return lift_call(d);
    }
    if (!neach) return rt_call(fn, n, parts, vals, pos);
    int64_t len = -1;
    for (int k = 0; k < n; k++)
        if (flags[k] == 1) {
            int64_t m = AS(List, vals[k])->n;
            if (len >= 0 && m != len) fail(pos, "「それぞれ」のリストの長さがそろっていません");
            len = m;
        }
    if (len == 0) return V_EMPTY;
    List *out = new_list(len);
    V *cur = rt_alloc(n * sizeof(V));
    for (int64_t i = 0; i < len; i++) {
        for (int k = 0; k < n; k++) cur[k] = flags[k] == 1 ? AS(List, vals[k])->it[i] : vals[k];
        out->it[i] = rt_call(fn, n, parts, cur, pos);
    }
    return (V)(intptr_t)out;
}

/* ------------------------------------------------------------------ */
/* 組み込み関数                                                        */
/* ------------------------------------------------------------------ */

#define BI(name) static V name(void *up, V *a, int32_t pos)

BI(b_show) { return mk_act(A_SHOW, "表示する", a[0], 0); }
BI(b_input) { return mk_act(A_INPUT, "入力する", a[0] ? format_v(a[0]) : 0, pos); }
BI(b_runall) {
    List *l = need_list(a[0], "「実行する」の「を」", pos);
    for (int64_t i = 0; i < l->n; i++) {
        int t = TAG(l->it[i]);
        if (t != T_ACT && t != T_PURE)
            fail(pos, "「%s」は動作ではありません(「実行する」には動作のリストを渡してください)", plain(l->it[i]).s);
    }
    return mk_act(A_RUNALL, "実行する", a[0], 0);
}

static int utf8_len(unsigned char c) { return c < 0x80 ? 1 : (c >> 5) == 6 ? 2 : (c >> 4) == 14 ? 3 : 4; }
static uint32_t utf8_cp(const char *s, int len) {
    uint32_t cp = len == 1 ? (unsigned char)s[0] : len == 2 ? s[0] & 0x1f : len == 3 ? s[0] & 0x0f : s[0] & 0x07;
    for (int k = 1; k < len; k++) cp = (cp << 6) | (s[k] & 0x3f);
    return cp;
}
static int is_space_cp(uint32_t cp) {
    return cp == ' ' || (cp >= 9 && cp <= 13) || (cp >= 0x1c && cp <= 0x1f) || cp == 0x85 || cp == 0xa0 || cp == 0x1680 ||
           (cp >= 0x2000 && cp <= 0x200a) || cp == 0x2028 || cp == 0x2029 || cp == 0x202f || cp == 0x205f || cp == 0x3000;
}

BI(b_to_number) {
    V v = a[0];
    if (is_num(v)) return v;
    if (TAG(v) == T_STR) {
        /* 全角の数字と記号を半角にして、前後の空白を除く */
        Str *s = AS(Str, v);
        Buf b = {0};
        for (int64_t i = 0; i < s->n;) {
            int len = utf8_len(s->s[i]);
            uint32_t cp = utf8_cp(s->s + i, len);
            if (cp >= 0xff01 && cp <= 0xff5e) { char c = (char)(cp - 0xfee0); buf_add(&b, &c, 1); }
            else if (cp == 0x2212) buf_add(&b, "-", 1);
            else if (is_space_cp(cp)) buf_add(&b, " ", 1);
            else buf_add(&b, s->s + i, len);
            i += len;
        }
        char *t = b.s ? b.s : "";
        while (*t == ' ') t++;
        size_t n = strlen(t);
        while (n && t[n - 1] == ' ') t[--n] = 0;
        if (n) {
            char *e;
            const char *p = t;
            if (*p == '+' || *p == '-') p++;
            int digits = *p != 0;
            for (const char *q = p; *q; q++) if ((*q < '0' || *q > '9') && *q != '_') digits = 0;
            if (digits) {
                long long x = strtoll(t, &e, 10);
                if (*e == 0) return mk_int(x, pos);
            }
            double d = strtod(t, &e);
            if (*e == 0) return rt_float(d);
        }
    }
    fail(pos, "「%s」は数値にできません%s", plain(v).s, action_hint(v));
}

BI(b_abs) {
    V v = need_num(a[0], pos);
    if (IS_INT(v)) return mk_int(INT_VAL(v) < 0 ? -INT_VAL(v) : INT_VAL(v), pos);
    return rt_float(fabs(AS(Flt, v)->d));
}

static V fold_op(int op, V x, V y, V unit, int32_t pos) {
    /* x と y(なければ 0)の要素を順に演算する */
    V items[2] = {x, y};
    V acc = 0;
    for (int k = 0; k < 2; k++) {
        V v = items[k];
        if (!v) continue;
        if (TAG(v) == T_LIST) {
            List *l = AS(List, v);
            for (int64_t i = 0; i < l->n; i++) acc = acc ? rt_binop(op, acc, l->it[i], pos) : l->it[i];
        } else {
            acc = acc ? rt_binop(op, acc, v, pos) : v;
        }
    }
    return acc ? acc : unit;
}

BI(b_add) { return fold_op(OP_ADD, a[0], a[1], mk_int(0, pos), pos); }
BI(b_mul) { return fold_op(OP_MUL, a[0], a[1], mk_int(1, pos), pos); }
BI(b_sub) { return rt_binop(OP_SUB, a[0], a[1], pos); }  /* から, を */
BI(b_div) { return rt_binop(OP_DIV, a[0], a[1], pos); }  /* を, で */
BI(b_append) {
    List *l = need_list(a[1], "「追加する」の「に」", pos);
    List *o = new_list(l->n + 1);
    memcpy(o->it, l->it, l->n * sizeof(V));
    o->it[l->n] = a[0];
    return (V)(intptr_t)o;
}
BI(b_insert) {
    List *l = need_list(a[1], "「挿入する」の「に」", pos);
    List *o = new_list(l->n + 1);
    o->it[0] = a[0];
    memcpy(o->it + 1, l->it, l->n * sizeof(V));
    return (V)(intptr_t)o;
}
BI(b_apply) {
    if (a[1]) return apply(a[0], 1, &a[1], pos);
    return rt_call(a[0], 0, NULL, NULL, pos);
}
BI(b_filter) { /* から, で */
    List *l = need_list(a[0], "「選別する」の「から」", pos);
    V *tmp = rt_alloc((l->n + 1) * sizeof(V));
    int64_t k = 0;
    for (int64_t i = 0; i < l->n; i++)
        if (rt_truthy(apply1(a[1], l->it[i], pos))) tmp[k++] = l->it[i];
    return rt_list(k, tmp);
}
BI(b_fold) { /* を, から, で */
    V fn = a[2], acc = a[1];
    int two = required_slots(fn, pos) >= 2;
    List *l = need_list(a[0], "「畳み込みする」の「を」", pos);
    for (int64_t i = 0; i < l->n; i++) {
        V pair[2] = {acc, l->it[i]};
        if (two) acc = apply(fn, 2, pair, pos);
        else { V t = rt_list(2, pair); acc = apply(fn, 1, &t, pos); }
    }
    return acc;
}
BI(b_unit) { return mk_pure(a[0]); }
static V b_fmap(void *up, V *a, int32_t pos) { return fmap(a[0], a[1], pos); }
static V b_chain(void *up, V *a, int32_t pos) { return chain(a[0], a[1], pos); }

/* --- 標準ライブラリの組み込み ---------------------------------------- */

static int64_t need_int(V v, const char *what, int32_t pos) {
    need_num(v, pos);
    if (IS_INT(v)) return INT_VAL(v);
    double d = AS(Flt, v)->d;
    if (d == floor(d) && fabs(d) < 4e18) return (int64_t)d;
    fail(pos, "%sは整数でなければなりません(「%s」が渡されました)", what, plain(v).s);
}
static Str *need_str(V v, const char *what, int32_t pos) {
    if (TAG(v) != T_STR) fail(pos, "%sは文字列でなければなりません(「%s」が渡されました)", what, plain(v).s);
    return AS(Str, v);
}
static V need_seq(V v, const char *what, int32_t pos) {
    if (TAG(v) != T_STR && TAG(v) != T_LIST) fail(pos, "%sは文字列かリストでなければなりません(「%s」が渡されました)", what, plain(v).s);
    return v;
}
/* 文字列の i 文字目(0から)のバイト位置 */
static int64_t cp_offset(Str *s, int64_t i) {
    int64_t off = 0;
    while (i > 0 && off < s->n) { off += utf8_len(s->s[off]); i--; }
    return off;
}
static int64_t seq_len(V v) { return TAG(v) == T_STR ? AS(Str, v)->ncp : AS(List, v)->n; }
static V seq_slice(V v, int64_t lo, int64_t hi) {
    int64_t n = seq_len(v);
    if (lo < 0) lo = 0;
    if (hi > n) hi = n;
    if (hi < lo) hi = lo;
    if (TAG(v) == T_STR) {
        Str *s = AS(Str, v);
        int64_t a = cp_offset(s, lo), b = cp_offset(s, hi);
        return mk_str(s->s + a, b - a);
    }
    return rt_list(hi - lo, AS(List, v)->it + lo);
}

BI(s_floor) {
    V v = need_num(a[0], pos);
    if (IS_INT(v)) return v;
    double d = floor(AS(Flt, v)->d);
    if (fabs(d) > 4e18) fail(pos, "整数が大きすぎます");
    return mk_int((int64_t)d, pos);
}
BI(s_sqrt) {
    V v = need_num(a[0], pos);
    double x = num_d(v);
    if (x < 0) fail(pos, "負の数「%s」の平方根は求められません", plain(v).s);
    double r = sqrt(x);
    if (r == floor(r) && r < 4e18) return mk_int((int64_t)r, pos);
    return rt_float(r);
}
BI(s_range) { /* から, を */
    int64_t lo = need_int(a[0], "「範囲にする」の「から」", pos), hi = need_int(a[1], "「範囲にする」の「を」", pos);
    if (hi < lo) return V_EMPTY;
    List *l = new_list(hi - lo + 1);
    for (int64_t i = lo; i <= hi; i++) l->it[i - lo] = mk_int(i, pos);
    return (V)(intptr_t)l;
}
BI(s_reverse) {
    V v = need_seq(a[0], "「逆順にする」の「を」", pos);
    if (TAG(v) == T_LIST) {
        List *l = AS(List, v);
        if (l->n == 0) return v;
        List *o = new_list(l->n);
        for (int64_t i = 0; i < l->n; i++) o->it[i] = l->it[l->n - 1 - i];
        return (V)(intptr_t)o;
    }
    Str *s = AS(Str, v);
    char *t = malloc(s->n + 1);
    int64_t w = s->n;
    for (int64_t i = 0; i < s->n;) {
        int len = utf8_len(s->s[i]);
        w -= len;
        memcpy(t + w, s->s + i, len);
        i += len;
    }
    V r = mk_str(t, s->n);
    free(t);
    return r;
}
BI(s_take) {
    V xs = need_seq(a[0], "「先頭取得する」の「から」", pos);
    int64_t n = need_int(a[1], "「先頭取得する」の「を」", pos);
    return seq_slice(xs, 0, n < 0 ? 0 : n);
}
BI(s_drop) {
    V xs = need_seq(a[0], "「先頭削除する」の「から」", pos);
    int64_t n = need_int(a[1], "「先頭削除する」の「を」", pos);
    return seq_slice(xs, n < 0 ? 0 : n, seq_len(xs));
}
BI(s_nth) {
    V xs = need_seq(a[0], "「番目取得する」の「から」", pos);
    int64_t n = need_int(a[1], "「番目取得する」の「を」", pos);
    int64_t len = seq_len(xs);
    if (n < 1 || n > len) fail(pos, "%lld番目はありません(長さは%lldです。位置は1から数えます)", (long long)n, (long long)len);
    if (TAG(xs) == T_LIST) return AS(List, xs)->it[n - 1];
    return seq_slice(xs, n - 1, n);
}
BI(s_contains) { /* が, を */
    V xs = need_seq(a[0], "「含有である」の「が」", pos);
    if (TAG(xs) == T_STR) {
        Str *sub = need_str(a[1], "文字列の「含有である」の「を」", pos);
        return rt_bool(strstr(AS(Str, xs)->s, sub->s) != NULL);
    }
    List *l = AS(List, xs);
    for (int64_t i = 0; i < l->n; i++)
        if (rt_eq(l->it[i], a[1])) return V_TRUE;
    return V_FALSE;
}
BI(s_chars) {
    Str *s = need_str(a[0], "「文字分解する」の「を」", pos);
    if (s->ncp == 0) return V_EMPTY;
    List *l = new_list(s->ncp);
    int64_t k = 0;
    for (int64_t i = 0; i < s->n;) {
        int len = utf8_len(s->s[i]);
        l->it[k++] = mk_str(s->s + i, len);
        i += len;
    }
    return (V)(intptr_t)l;
}
BI(s_split) { /* を, で */
    Str *s = need_str(a[0], "「分割する」の「を」", pos);
    Str *sep = need_str(a[1], "「分割する」の「で」", pos);
    if (sep->n == 0) fail(pos, "「分割する」の「で」に空の文字列は使えません(1文字ずつにするには「文字分解する」)");
    V *tmp = rt_alloc((s->n + 2) * sizeof(V));
    int64_t k = 0;
    const char *p = s->s, *end = s->s + s->n;
    for (;;) {
        const char *q = strstr(p, sep->s);
        if (!q) { tmp[k++] = mk_str(p, end - p); break; }
        tmp[k++] = mk_str(p, q - p);
        p = q + sep->n;
    }
    return rt_list(k, tmp);
}
BI(s_join) { /* を, で */
    List *l = need_list(a[0], "「結合する」の「を」", pos);
    Str *sep = need_str(a[1], "「結合する」の「で」", pos);
    Buf b = {0};
    buf_add(&b, "", 0);
    for (int64_t i = 0; i < l->n; i++) {
        Str *x = need_str(l->it[i], "「結合する」のリストの要素", pos);
        if (i) buf_add(&b, sep->s, sep->n);
        buf_add(&b, x->s, x->n);
    }
    return mk_str(b.s, b.n);
}
BI(s_replace) { /* を, から, へ */
    Str *s = need_str(a[0], "「置換する」の「を」", pos);
    Str *old = need_str(a[1], "「置換する」の「から」", pos);
    if (old->n == 0) fail(pos, "「置換する」の「から」に空の文字列は使えません");
    Str *nw = need_str(a[2], "「置換する」の「へ」", pos);
    Buf b = {0};
    buf_add(&b, "", 0);
    const char *p = s->s;
    for (;;) {
        const char *q = strstr(p, old->s);
        if (!q) { buf_cat(&b, p); break; }
        buf_add(&b, p, q - p);
        buf_add(&b, nw->s, nw->n);
        p = q + old->n;
    }
    return mk_str(b.s, b.n);
}
static V map_case(V v, const char *what, int upper, int32_t pos) {
    Str *s = need_str(v, what, pos);
    Buf b = {0};
    buf_add(&b, "", 0);
    for (int64_t i = 0; i < s->n;) {
        int len = utf8_len(s->s[i]);
        uint32_t cp = utf8_cp(s->s + i, len);
        if (upper && ((cp >= 'a' && cp <= 'z') || (cp >= 0xff41 && cp <= 0xff5a))) cp -= cp < 0x80 ? 32 : 0x20;
        else if (!upper && ((cp >= 'A' && cp <= 'Z') || (cp >= 0xff21 && cp <= 0xff3a))) cp += cp < 0x80 ? 32 : 0x20;
        else { buf_add(&b, s->s + i, len); i += len; continue; }
        char enc[4];
        if (cp < 0x80) { enc[0] = (char)cp; buf_add(&b, enc, 1); }
        else { enc[0] = (char)(0xe0 | (cp >> 12)); enc[1] = (char)(0x80 | ((cp >> 6) & 0x3f)); enc[2] = (char)(0x80 | (cp & 0x3f)); buf_add(&b, enc, 3); }
        i += len;
    }
    return mk_str(b.s, b.n);
}
BI(s_upper) { return map_case(a[0], "「大文字にする」の「を」", 1, pos); }
BI(s_lower) { return map_case(a[0], "「小文字にする」の「を」", 0, pos); }
BI(s_strip) {
    Str *s = need_str(a[0], "「空白除去する」の「を」", pos);
    int64_t lo = 0, hi = s->n;
    while (lo < hi) {
        int len = utf8_len(s->s[lo]);
        if (!is_space_cp(utf8_cp(s->s + lo, len))) break;
        lo += len;
    }
    while (hi > lo) {
        int64_t k = hi - 1;
        while (k > lo && (s->s[k] & 0xc0) == 0x80) k--;
        if (!is_space_cp(utf8_cp(s->s + k, (int)(hi - k)))) break;
        hi = k;
    }
    return mk_str(s->s + lo, hi - lo);
}
BI(s_starts) { /* が, で */
    Str *s = need_str(a[0], "「先頭一致である」の「が」", pos), *p = need_str(a[1], "「先頭一致である」の「で」", pos);
    return rt_bool(p->n <= s->n && memcmp(s->s, p->s, p->n) == 0);
}
BI(s_ends) {
    Str *s = need_str(a[0], "「末尾一致である」の「が」", pos), *p = need_str(a[1], "「末尾一致である」の「で」", pos);
    return rt_bool(p->n <= s->n && memcmp(s->s + s->n - p->n, p->s, p->n) == 0);
}
BI(s_bytes) { return mk_int(need_str(a[0], "「バイト数にする」の「を」", pos)->n, pos); }
BI(s_chr) {
    V v = need_num(a[0], pos);
    int64_t c = IS_INT(v) ? INT_VAL(v) : -1;
    if (c < 0 || c > 0x10FFFF || (c >= 0xD800 && c <= 0xDFFF)) fail(pos, "「%s」は文字の番号ではありません", plain(v).s);
    char b[4];
    int n;
    if (c < 0x80) { b[0] = (char)c; n = 1; }
    else if (c < 0x800) { b[0] = (char)(0xc0 | (c >> 6)); b[1] = (char)(0x80 | (c & 0x3f)); n = 2; }
    else if (c < 0x10000) { b[0] = (char)(0xe0 | (c >> 12)); b[1] = (char)(0x80 | ((c >> 6) & 0x3f)); b[2] = (char)(0x80 | (c & 0x3f)); n = 3; }
    else { b[0] = (char)(0xf0 | (c >> 18)); b[1] = (char)(0x80 | ((c >> 12) & 0x3f)); b[2] = (char)(0x80 | ((c >> 6) & 0x3f)); b[3] = (char)(0x80 | (c & 0x3f)); n = 4; }
    return mk_str(b, n);
}
BI(s_ord) {
    Str *s = need_str(a[0], "「文字コードにする」の「を」", pos);
    if (s->ncp != 1) fail(pos, "「文字コードにする」の「を」は1文字の文字列です(「%s」)", s->s);
    return mk_int(utf8_cp(s->s, utf8_len(s->s[0])), pos);
}

/* --- 通信(「通信」の組み込み)。待受口と接続は1からの番号で表す(インタプリタと同じ) --- */

typedef struct { int fd; FILE *in; } Sock;
static Sock *socks;
static int64_t nsocks, capsocks;

static int64_t sock_add(int fd) {
    if (nsocks == capsocks) {
        capsocks = capsocks ? capsocks * 2 : 16;
        socks = realloc(socks, capsocks * sizeof(Sock));
        if (!socks) fail(0, "メモリが足りません");
    }
    socks[nsocks].fd = fd;
    socks[nsocks].in = NULL;
    return ++nsocks;
}
static Sock *sock_get(V v, const char *what, int32_t pos) {
    int64_t i = IS_INT(v) ? INT_VAL(v) : 0;
    if (TAG(v) == T_BOOL || i < 1 || i > nsocks || socks[i - 1].fd < 0) fail(pos, "「%s」は開いている%sではありません", plain(v).s, what);
    return &socks[i - 1];
}
__attribute__((noreturn)) static void net_fail(Act *a) { fail(a->pos, "「%s」で通信に失敗しました(%s)", a->name, strerror(errno)); }

static V net_run(Act *a) {
    int32_t pos = a->pos;
    switch (a->kind) {
    case A_LISTEN: {
        V v = need_num(a->a, pos);
        int64_t port = IS_INT(v) ? INT_VAL(v) : -1;
        if (port < 0 || port > 65535) fail(pos, "「%s」はポートの番号ではありません", plain(v).s);
        signal(SIGPIPE, SIG_IGN); /* 相手が切れても止まらず、送信のエラーにする */
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) net_fail(a);
        int one = 1;
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
        struct sockaddr_in ad = {0};
        ad.sin_family = AF_INET;
        ad.sin_addr.s_addr = htonl(INADDR_ANY);
        ad.sin_port = htons((uint16_t)port);
        if (bind(fd, (struct sockaddr *)&ad, sizeof ad) < 0 || listen(fd, 16) < 0) { int e = errno; close(fd); errno = e; net_fail(a); }
        return mk_int(sock_add(fd), pos);
    }
    case A_ACCEPT: {
        Sock *s = sock_get(a->a, "待受口", pos);
        fflush(stdout); /* 待つ前に、それまでの表示を出しておく */
        int fd;
        do fd = accept(s->fd, NULL, NULL); while (fd < 0 && errno == EINTR);
        if (fd < 0) net_fail(a);
        struct timeval tv = {5, 0}; /* 何も送ってこない相手で止まらないように(インタプリタの NET_TIMEOUT と同じ) */
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
        return mk_int(sock_add(fd), pos);
    }
    case A_RECVLINE: case A_RECV: {
        Sock *s = sock_get(a->a, "接続", pos);
        fflush(stdout);
        int64_t want = 0;
        if (a->kind == A_RECV) {
            V v = need_num(a->b, pos);
            want = IS_INT(v) ? INT_VAL(v) : -1;
            if (want < 0) fail(pos, "「%s」は受信するバイト数ではありません", plain(v).s);
        }
        if (!s->in) {
            int fd2 = dup(s->fd);
            if (fd2 < 0 || !(s->in = fdopen(fd2, "rb"))) net_fail(a);
        }
        Buf b = {0};
        if (a->kind == A_RECVLINE) {
            /* 終わりの改行を含めて1行(長すぎる行は 65536 バイトで切る) */
            int c;
            while (b.n < 65536 && (c = fgetc(s->in)) != EOF) {
                char ch = (char)c;
                buf_add(&b, &ch, 1);
                if (ch == '\n') break;
            }
        } else {
            char tmp[4096];
            while ((int64_t)b.n < want) {
                size_t k = fread(tmp, 1, (size_t)(want - (int64_t)b.n) < sizeof tmp ? (size_t)(want - (int64_t)b.n) : sizeof tmp, s->in);
                if (k == 0) break;
                buf_add(&b, tmp, k);
            }
        }
        if (ferror(s->in)) { free(b.s); net_fail(a); }
        V r = mk_str(b.s ? b.s : "", (int64_t)b.n);
        free(b.s);
        return r;
    }
    case A_SEND: {
        Str *str = need_str(a->a, "「送信する」の「を」", pos);
        Sock *s = sock_get(a->b, "接続", pos);
        int64_t off = 0;
        while (off < str->n) {
            ssize_t k = send(s->fd, str->s + off, (size_t)(str->n - off), 0);
            if (k < 0 && errno == EINTR) continue;
            if (k < 0) net_fail(a);
            off += k;
        }
        return mk_int(str->n, pos);
    }
    case A_CLOSE: {
        Sock *s = sock_get(a->a, "待受口か接続", pos);
        if (s->in) fclose(s->in);
        close(s->fd);
        s->fd = -1;
        s->in = NULL;
        return a->a;
    }
    }
    return 0;
}

static V mk_net(int kind, const char *name, V x, V y, int32_t pos) {
    V v = mk_act(kind, name, x, y);
    AS(Act, v)->pos = pos;
    return v;
}
BI(s_try) { /* を, で */
    const char *parts[2] = {"を", "で"};
    for (int i = 0; i < 2; i++) {
        int t = TAG(a[i]);
        if (t != T_ACT && t != T_PURE) fail(pos, "「試行する」の「%s」は動作でなければなりません(「%s」が渡されました)", parts[i], plain(a[i]).s);
    }
    return mk_act(A_TRY, "試行する", a[0], a[1]);
}
BI(n_listen) { return mk_net(A_LISTEN, "待受開始する", a[0], 0, pos); }
BI(n_accept) { return mk_net(A_ACCEPT, "接続受付する", a[0], 0, pos); }
BI(n_recvline) { return mk_net(A_RECVLINE, "行受信する", a[0], 0, pos); }
BI(n_recv) { return mk_net(A_RECV, "受信する", a[0], a[1], pos); }  /* から, を */
BI(n_send) { return mk_net(A_SEND, "送信する", a[0], a[1], pos); }  /* を, へ */
BI(n_close) { return mk_net(A_CLOSE, "切断する", a[0], 0, pos); }

static const int32_t P1_WO[] = {P_WO}, P2_WO_NI[] = {P_WO, P_NI}, P2_KARA_WO[] = {P_KARA, P_WO},
                     P2_WO_DE[] = {P_WO, P_DE}, P2_KARA_DE[] = {P_KARA, P_DE}, P3_WO_KARA_DE[] = {P_WO, P_KARA, P_DE},
                     P2_GA_WO[] = {P_GA, P_WO}, P1_KARA[] = {P_KARA}, P2_WO_HE[] = {P_WO, P_HE}, P3_WO_KARA_HE[] = {P_WO, P_KARA, P_HE}, P2_GA_DE[] = {P_GA, P_DE};
static const uint8_t R_OPT1[] = {0}, R_1_OPT[] = {1, 0};

typedef struct { const char *name; int32_t n; const int32_t *parts; const uint8_t *req; Code code; } BuiltinDef;

static const BuiltinDef BUILTINS[] = {
    {"表示する", 1, P1_WO, NULL, b_show},
    {"入力する", 1, P1_WO, R_OPT1, b_input},
    {"実行する", 1, P1_WO, NULL, b_runall},
    {"数値にする", 1, P1_WO, NULL, b_to_number},
    {"絶対値にする", 1, P1_WO, NULL, b_abs},
    {"加算する", 2, P2_WO_NI, R_1_OPT, b_add},
    {"乗算する", 2, P2_WO_NI, R_1_OPT, b_mul},
    {"減算する", 2, P2_KARA_WO, NULL, b_sub},
    {"除算する", 2, P2_WO_DE, NULL, b_div},
    {"追加する", 2, P2_WO_NI, NULL, b_append},
    {"挿入する", 2, P2_WO_NI, NULL, b_insert},
    {"適用する", 2, P2_WO_NI, R_1_OPT, b_apply},
    {"選別する", 2, P2_KARA_DE, NULL, b_filter},
    {"畳み込みする", 3, P3_WO_KARA_DE, NULL, b_fold},
};

/* ------------------------------------------------------------------ */
/* バイト列と、外部の関数とのやりとり(標準の組み込み)                 */
/* ------------------------------------------------------------------ */

V rt_ffi_from_ptr(void *p);
static int ffi_errno;

static V mk_bytes(const void *p, int64_t n) {
    Bytes *b = rt_alloc(sizeof(Bytes) + n + 1);
    b->tag = T_BYTES;
    b->n = n;
    if (n && p) memcpy(b->d, p, n);
    return (V)(intptr_t)b;
}
static Bytes *need_bytes(V v, const char *what, int32_t pos) {
    if (TAG(v) != T_BYTES) fail(pos, "%sはバイト列でなければなりません(「%s」が渡されました)", what, plain(v).s);
    return AS(Bytes, v);
}
static Addr *need_addr(V v, const char *what, int32_t pos) {
    if (TAG(v) != T_ADDR) fail(pos, "%sは番地でなければなりません(「%s」が渡されました)", what, plain(v).s);
    return AS(Addr, v);
}
/* Python の bytes.decode("utf-8") と同じ厳しさで調べる */
static int utf8_valid(const uint8_t *s, int64_t n) {
    int64_t i = 0;
    while (i < n) {
        uint8_t c = s[i];
        if (c < 0x80) { i++; continue; }
        int k;
        uint32_t cp, min;
        if ((c & 0xe0) == 0xc0) { k = 1; cp = c & 0x1f; min = 0x80; }
        else if ((c & 0xf0) == 0xe0) { k = 2; cp = c & 0x0f; min = 0x800; }
        else if ((c & 0xf8) == 0xf0) { k = 3; cp = c & 0x07; min = 0x10000; }
        else return 0;
        for (int j = 1; j <= k; j++) {
            if (i + j >= n || (s[i + j] & 0xc0) != 0x80) return 0;
            cp = (cp << 6) | (s[i + j] & 0x3f);
        }
        if (cp < min || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) return 0;
        i += k + 1;
    }
    return 1;
}
BI(m_tobytes) { Str *x = need_str(a[0], "「バイト列にする」の「を」", pos); return mk_bytes(x->s, x->n); }
BI(m_build) {
    if (TAG(a[0]) != T_LIST) fail(pos, "「バイト列組立する」の「を」はリストでなければなりません(「%s」が渡されました)", plain(a[0]).s);
    List *l = AS(List, a[0]);
    Bytes *b = AS(Bytes, mk_bytes(NULL, l->n));
    for (int64_t i = 0; i < l->n; i++) {
        V x = l->it[i];
        if (!IS_INT(x) || INT_VAL(x) < 0 || INT_VAL(x) > 255) fail(pos, "「%s」は 0 から 255 までの整数ではありません", plain(x).s);
        b->d[i] = (uint8_t)INT_VAL(x);
    }
    return (V)(intptr_t)b;
}
BI(m_list) {
    Bytes *b = need_bytes(a[0], "「数列にする」の「を」", pos);
    if (b->n == 0) return V_EMPTY;
    List *l = new_list(b->n);
    for (int64_t i = 0; i < b->n; i++) l->it[i] = mk_int(b->d[i], pos);
    return (V)(intptr_t)l;
}
BI(m_tostr) {
    Bytes *b = need_bytes(a[0], "「文字列にする」の「を」", pos);
    if (!utf8_valid(b->d, b->n)) fail(pos, "バイト列が UTF-8 の文字列ではありません");
    return mk_str((const char *)b->d, b->n);
}
BI(m_len) { return mk_int(need_bytes(a[0], "「バイト長にする」の「を」", pos)->n, pos); }
BI(m_addr) {
    V v = need_num(a[0], pos);
    if (!IS_INT(v) || INT_VAL(v) < 0) fail(pos, "「%s」は番地にできません(0 以上の整数が必要です)", plain(v).s);
    return rt_ffi_from_ptr((void *)(intptr_t)INT_VAL(v));
}
BI(m_addrnum) { return mk_int((int64_t)(intptr_t)need_addr(a[0], "「番地数値にする」の「を」", pos)->p, pos); }
static V mk_act_pos(int kind, const char *name, V x, V y, int32_t pos) {
    Act *act = AS(Act, mk_act(kind, name, x, y));
    act->pos = pos;
    return (V)(intptr_t)act;
}
BI(m_peek) { /* から, を */
    need_addr(a[0], "「バイト列取得する」の「から」", pos);
    V n = need_num(a[1], pos);
    if (!IS_INT(n) || INT_VAL(n) < 0) fail(pos, "「%s」は取得するバイト数ではありません", plain(n).s);
    return mk_act_pos(A_PEEK, "バイト列取得する", a[0], n, pos);
}
BI(m_poke) { /* を, へ */
    need_bytes(a[0], "「書込する」の「を」", pos);
    need_addr(a[1], "「書込する」の「へ」", pos);
    return mk_act_pos(A_POKE, "書込する", a[0], a[1], pos);
}
BI(m_errno) { return mk_act_pos(A_ERRNO, "エラー番号取得する", 0, 0, pos); }
BI(m_fail) {
    need_str(a[0], "「失敗する」の「を」", pos);
    return mk_act_pos(A_FAIL, "失敗する", a[0], 0, pos);
}
static V mem_run(Act *a) {
    switch (a->kind) {
    case A_PEEK: {
        void *p = AS(Addr, a->a)->p;
        int64_t n = INT_VAL(a->b);
        if (!p && n > 0) fail(a->pos, "番地(0x0)からは取得できません");
        return mk_bytes(p, n);
    }
    case A_POKE: {
        Bytes *b = AS(Bytes, a->a);
        void *p = AS(Addr, a->b)->p;
        if (!p && b->n > 0) fail(a->pos, "番地(0x0)へは書き込めません");
        if (b->n) memcpy(p, b->d, b->n);
        return mk_int(b->n, a->pos);
    }
    case A_ERRNO: return mk_int(ffi_errno, a->pos);
    case A_FAIL: fail(a->pos, "%s", AS(Str, a->a)->s);
    }
    return 0;
}

static const BuiltinDef STD_PRIMITIVES[] = {
    {"切捨する", 1, P1_WO, NULL, s_floor},
    {"平方根にする", 1, P1_WO, NULL, s_sqrt},
    {"範囲にする", 2, P2_KARA_WO, NULL, s_range},
    {"逆順にする", 1, P1_WO, NULL, s_reverse},
    {"先頭取得する", 2, P2_KARA_WO, NULL, s_take},
    {"先頭削除する", 2, P2_KARA_WO, NULL, s_drop},
    {"番目取得する", 2, P2_KARA_WO, NULL, s_nth},
    {"含有である", 2, P2_GA_WO, NULL, s_contains},
    {"文字分解する", 1, P1_WO, NULL, s_chars},
    {"分割する", 2, P2_WO_DE, NULL, s_split},
    {"結合する", 2, P2_WO_DE, NULL, s_join},
    {"置換する", 3, P3_WO_KARA_HE, NULL, s_replace},
    {"大文字にする", 1, P1_WO, NULL, s_upper},
    {"小文字にする", 1, P1_WO, NULL, s_lower},
    {"空白除去する", 1, P1_WO, NULL, s_strip},
    {"先頭一致である", 2, P2_GA_DE, NULL, s_starts},
    {"末尾一致である", 2, P2_GA_DE, NULL, s_ends},
    {"バイト数にする", 1, P1_WO, NULL, s_bytes},
    {"文字にする", 1, P1_WO, NULL, s_chr},
    {"文字コードにする", 1, P1_WO, NULL, s_ord},
    {"試行する", 2, P2_WO_DE, NULL, s_try},
    {"バイト列にする", 1, P1_WO, NULL, m_tobytes},
    {"バイト列組立する", 1, P1_WO, NULL, m_build},
    {"数列にする", 1, P1_WO, NULL, m_list},
    {"文字列にする", 1, P1_WO, NULL, m_tostr},
    {"バイト長にする", 1, P1_WO, NULL, m_len},
    {"番地にする", 1, P1_WO, NULL, m_addr},
    {"番地数値にする", 1, P1_WO, NULL, m_addrnum},
    {"バイト列取得する", 2, P2_KARA_WO, NULL, m_peek},
    {"書込する", 2, P2_WO_HE, NULL, m_poke},
    {"エラー番号取得する", 0, NULL, NULL, m_errno},
    {"失敗する", 1, P1_WO, NULL, m_fail},
    /* 「通信」の組み込み */
    {"待受開始する", 1, P1_WO, NULL, n_listen},
    {"接続受付する", 1, P1_KARA, NULL, n_accept},
    {"行受信する", 1, P1_KARA, NULL, n_recvline},
    {"受信する", 2, P2_KARA_WO, NULL, n_recv},
    {"送信する", 2, P2_WO_HE, NULL, n_send},
    {"切断する", 1, P1_WO, NULL, n_close},
};

static V def_builtin(const BuiltinDef *d) { return mk_builtin(d->name, d->n, d->parts, d->req, d->code, NULL); }

/* 標準ライブラリの組み込み(「標準」の中で使う) */
/* ------------------------------------------------------------------ */
/* 外部の関数(FFI): する の値と C の値の変換                           */
/* ------------------------------------------------------------------ */

__attribute__((noreturn)) static void ffi_bad(V v, const char *fname, int32_t part, const char *want, int32_t pos) {
    fail(pos, "外部の関数「%s」の「%s」には%sが必要です(「%s」が渡されました)", fname, PART_NAMES[part], want, plain(v).s);
}

static int64_t ffi_int(V v, const char *fname, int32_t part, int32_t pos, const char *want) {
    if (IS_INT(v)) return INT_VAL(v);
    if (TAG(v) == T_FLT) {
        double d = AS(Flt, v)->d;
        if (d == floor(d) && d >= -9223372036854775808.0 && d < 9223372036854775808.0) return (int64_t)d;
    }
    ffi_bad(v, fname, part, want, pos);
}

int64_t rt_ffi_i64(V v, const char *fname, int32_t part, int32_t pos) { return ffi_int(v, fname, part, pos, "整数"); }

int32_t rt_ffi_i32(V v, const char *fname, int32_t part, int32_t pos) {
    int64_t n = ffi_int(v, fname, part, pos, "整数");
    if (n < INT32_MIN || n > INT32_MAX) ffi_bad(v, fname, part, "-2147483648 から 2147483647 までの整数", pos);
    return (int32_t)n;
}

double rt_ffi_f64(V v, const char *fname, int32_t part, int32_t pos) {
    if (!is_num(v)) ffi_bad(v, fname, part, "数", pos);
    return num_d(v);
}

int32_t rt_ffi_bool(V v, const char *fname, int32_t part, int32_t pos) {
    if (TAG(v) != T_BOOL) ffi_bad(v, fname, part, "真偽", pos);
    return AS(Bool, v)->b ? 1 : 0;
}

const char *rt_ffi_str(V v, const char *fname, int32_t part, int32_t pos) {
    if (TAG(v) != T_STR) ffi_bad(v, fname, part, "文字列", pos);
    Str *s = AS(Str, v);
    if ((int64_t)strlen(s->s) != s->n) ffi_bad(v, fname, part, "途中に文字コード 0 を含まない文字列", pos);
    return s->s; /* 呼んでいる間だけ使える(C 側で持ち続けない) */
}

const uint8_t *rt_ffi_bytes(V v, const char *fname, int32_t part, int32_t pos) {
    if (TAG(v) != T_BYTES) ffi_bad(v, fname, part, "バイト列", pos);
    return AS(Bytes, v)->d; /* 呼んでいる間だけ使える(C 側で書き換えない) */
}

/* 外部の関数を呼ぶ前と後: 「エラー番号取得する」はその関数が残した errno */
static int ffi_errno;
void rt_ffi_pre(void) { errno = 0; }
void rt_ffi_post(void) { ffi_errno = errno; }

void *rt_ffi_ptr(V v, const char *fname, int32_t part, int32_t pos) {
    if (TAG(v) != T_ADDR) ffi_bad(v, fname, part, "番地", pos);
    return AS(Addr, v)->p;
}

V rt_ffi_from_i64(int64_t n, const char *fname, int32_t pos) {
    if (n > INT_MAX62 || n < INT_MIN62)
        fail(pos, "外部の関数「%s」の値 %lld が大きすぎます(整数は ±%lld までです)", fname, (long long)n, (long long)INT_MAX62);
    return mk_int(n, pos);
}

V rt_ffi_from_i32(int32_t n) { return mk_int(n, 0); }
V rt_ffi_from_bool(int32_t b) { return rt_bool(b != 0); }
V rt_ffi_from_str(const char *s) { return s ? cstr(s) : cstr(""); }

V rt_ffi_from_ptr(void *p) {
    Addr *a = rt_alloc(sizeof(Addr));
    a->tag = T_ADDR;
    a->p = p;
    return (V)(intptr_t)a;
}

/* 値が動作の外部の関数: 行ったときに k(引数を捕まえた関数)を呼ぶ */
V rt_ffi_action(V k, const char *fname, int32_t pos) {
    Act *x = AS(Act, mk_act(A_CALL, fname, k, 0));
    x->pos = pos;
    return (V)(intptr_t)x;
}

V rt_std(const char *name) {
    for (size_t i = 0; i < sizeof STD_PRIMITIVES / sizeof STD_PRIMITIVES[0]; i++)
        if (strcmp(STD_PRIMITIVES[i].name, name) == 0) return def_builtin(&STD_PRIMITIVES[i]);
    fail(0, "標準ライブラリに「%s」はありません", name);
}

/* 組み込み・形・性質の関数(どこからでも見える名前) */
V rt_global(const char *name, int32_t pos) {
    V v = shared_get(name);
    if (!v) fail(pos, "「%s」は定義されていません", name);
    return v;
}

V rt_global_cached(V *slot, const char *name, int32_t pos) {
    if (!*slot) *slot = rt_global(name, pos);
    return *slot;
}

/* 一番外の式の値: 動作なら行い、そうでなければ表示する */
void rt_top(V v) {
    int t = TAG(v);
    if (t == T_ACT || t == T_PURE) { perform(v); return; }
    fputs(show(v), stdout);
    fputc('\n', stdout);
}

static void init_builtins(void) {
    for (size_t i = 0; i < sizeof BUILTINS / sizeof BUILTINS[0]; i++) shared_set(BUILTINS[i].name, def_builtin(&BUILTINS[i]));
    static const int32_t P_X[] = {P_WO};
    rt_trait(SHOWABLE);
    rt_trait_method(SHOWABLE, TO_STRING, 1, P_X, 0, 0, 0);
    rt_trait(MAPPABLE);
    rt_trait_method(MAPPABLE, MAP, 2, PARTS_WO_DE, 0, 0, 0);
    rt_trait(MONAD);
    V unit = mk_builtin(UNIT, 1, P1_WO, NULL, b_unit, NULL);
    rt_trait_method(MONAD, BIND, 2, PARTS_WO_DE, 0, 0, 0);
    rt_trait_method(MONAD, UNIT, 1, P1_WO, 0, 0, unit);
    shared_set(UNIT, unit); /* 「を」の型で選ばず、いつも中立の値を作る */
    V fm = mk_builtin(MAP, 2, PARTS_WO_DE, NULL, b_fmap, NULL);
    V ch = mk_builtin(BIND, 2, PARTS_WO_DE, NULL, b_chain, NULL);
    const char *types[] = {"リスト", "動作"};
    for (int i = 0; i < 2; i++) {
        rt_impl(MAPPABLE, types[i], MAP, fm);
        rt_impl(MONAD, types[i], BIND, ch);
    }
}

/* ------------------------------------------------------------------ */
/* 始まり                                                              */
/* ------------------------------------------------------------------ */

extern void suru_main(void);
extern const char suru_source[];

static void *run_main(void *arg) {
    (void)arg;
    suru_main();
    fflush(stdout);
    return NULL;
}

int main(void) {
    source_text = suru_source;
    init_builtins();
    /* 深い再帰のために、大きなスタックのスレッドで動かす */
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, (size_t)1 << 30);
    pthread_t th;
    if (pthread_create(&th, &attr, run_main, NULL) != 0) run_main(NULL);
    else pthread_join(th, NULL);
    return 0;
}
