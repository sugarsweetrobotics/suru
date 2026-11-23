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
 * メモリは GC(保守的なマーク&スイープ)で片付ける(「メモリ」の節)。
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
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

typedef int64_t V;

enum { T_INT = 0, T_FLT = 1, T_BOOL, T_STR, T_LIST, T_REC, T_FN, T_ACT, T_PURE, T_LAZY, T_ADDR, T_BYTES };

typedef struct { int32_t tag; } Hdr;
typedef struct { int32_t tag; double d; } Flt;
typedef struct { int32_t tag; int32_t b; } Bool;
typedef struct { int32_t tag; int64_t n; int64_t ncp; char s[]; } Str;
/* リストは変更しない。it は自分の data か、別のリストの data の途中(「残り」などの切り出し)を指す */
typedef struct { int32_t tag; int64_t n; V *it; V data[]; } List;
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
enum { A_SHOW, A_INPUT, A_RUNALL, A_CHAIN, A_FMAP, A_LISTEN, A_ACCEPT, A_RECVLINE, A_RECV, A_SEND, A_CLOSE, A_TRY, A_CALL, A_PEEK, A_POKE, A_ERRNO, A_FAIL, A_ARGS, A_EXIT,
       A_SPAWN, A_JOIN, A_NCPU, A_CH_NEW, A_CH_PIPE, A_CH_FIFO_NEW, A_CH_FIFO_OPEN, A_CH_FIFO_DEL, A_CH_SEND, A_CH_RECV, A_CH_CLOSE, A_CH_EACH,
       A_LOCK_NEW, A_LOCKED, A_SLOT_NEW, A_SLOTTED, A_BOX_NEW, A_BOX_GET, A_BOX_UPDATE, A_BOX_SET };
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
/* メモリ(保守的なマーク&スイープの GC)                              */
/* ------------------------------------------------------------------ */
/*
 * 値の多くは C のスタックやレジスタにあって正確な場所が分からないので、
 * スタックの中の「オブジェクトを指していそうな語」はすべて生きているとみなす(保守的)。
 * オブジェクトは動かさないので、ポインタはそのまま使える。
 * オブジェクトの中身も、先頭の tag によらず語ごとに調べる(フレームや引数の配列には tag がない)。
 * 文字列と小数は中にポインタがないので調べない(atomic)。
 * オブジェクトの途中を指すポインタも、そのオブジェクトを指しているとみなす。
 * 根: スタックとレジスタ、IR の大域変数(suru_roots)、この実行時ライブラリの表。
 */

extern V *const suru_roots[];
extern const int64_t suru_nroots;

#define GC_BLOCK ((size_t)1 << 18)   /* 小さいオブジェクトのブロック(同じ大きさのものを並べる) */
#define GC_SMALL_MAX 2048            /* これより大きいものは1つずつ malloc する */
static const uint32_t GC_SIZES[] = {16,  32,  48,  64,  80,  96,  112, 128,  160,  192,  224,  256,
                                    320, 384, 448, 512, 640, 768, 896, 1024, 1280, 1536, 1792, 2048};
#define GC_NCLASS ((int)(sizeof GC_SIZES / sizeof GC_SIZES[0]))

typedef struct GcBlk {
    char *start, *end;   /* オブジェクトの領域 [start, end) */
    size_t osz;          /* 1つの大きさ(大きいオブジェクトなら全体) */
    size_t nobj;
    int large, atomic;
    uint8_t *mark;       /* オブジェクトごとの状態(GC_FREE / GC_USED / GC_MARKED) */
    size_t cursor;       /* ここから先で空いているもの(GC_FREE)を探す */
    struct GcBlk *next;  /* 空きのあるブロックのつながり */
} GcBlk;

/* 空いているものは調べない(空きのつながりをたどって空きを生きているとみなさないため) */
enum { GC_FREE = 0, GC_USED = 1, GC_MARKED = 2 };

static GcBlk **gc_regs;          /* すべての領域(片付けで順に見る) */
static size_t gc_nregs, gc_capregs;
/* ポインタらしい語からブロックを引く表。小さいオブジェクトのブロックは GC_BLOCK にそろえて置くので、
 * 語の下位を落とした番地で引ける(開番地法)。大きいオブジェクトは start の順の配列を二分探索する */
static GcBlk **gc_tab;
static size_t gc_tabcap, gc_ntab;
static GcBlk **gc_large;
static size_t gc_nlarge, gc_caplarge;
static uintptr_t gc_lo = UINTPTR_MAX, gc_hi; /* すべての領域を含む範囲 */
static GcBlk *gc_avail[2][GC_NCLASS]; /* [atomic][大きさ] 空きのあるブロック */
static uint8_t gc_class_of[GC_SMALL_MAX / 16 + 1];
static size_t gc_since;            /* 前の GC からの確保量 */
static size_t gc_min = (size_t)8 << 20; /* これだけ確保するまでは GC しない(SURU_GC_MIN で KB 単位に変えられる) */
static size_t gc_next = (size_t)8 << 20;
static size_t gc_batch = (size_t)64 << 10; /* スレッドごとの確保量をこれだけためてから gc_since に足す */
static int gc_log;
static size_t gc_live;
static int gc_on;                  /* プログラムが始まったら 1(それまでは GC しない) */
static int64_t gc_count;

/* --- スレッド ---
 * スレッドは同時に動く(本当の並列)。各スレッドは「動いている」か「外にいる」(外部の関数・入力・通信・通路の待ち)。
 * GC は止める合図(rt_gc_stop)を立て、動いているスレッドがみな安全点(関数の入口と確保)で止まるのを待ってから行う。
 * 止まるときや外に出るときは、そのときのレジスタとスタックの位置を残しておき、GC はそこも調べる。
 * 外にいるスレッドは、する の値を作ったり runtime の表を触ったりしない(戻るときに GC が終わるのを待つ)。
 * スレッドが1つだけのうちは何もしない。 */
typedef struct SThread {
    char *top;                    /* スタックの底(一番大きい番地)。ここまで調べる */
    char *lo;                     /* 止まった・外に出たときのスタックの位置(NULL ならまだスタックに値がない) */
    jmp_buf regs;                 /* 止まった・外に出たときのレジスタ */
    uintptr_t start;              /* 始める動作(終わるまで GC から守る) */
    uintptr_t cell;               /* 結果を書くところ(ThreadCell) */
    int (*wready)(void *);        /* 通路や合流で待っている間: 待つのを終えてよいか(NULL なら待っていない) */
    void *warg;
    pthread_cond_t wcv;           /* 待っている間、ここで起こされる */
    GcBlk *avail[2][GC_NCLASS];   /* このスレッドだけが確保に使うブロック([atomic][大きさ]) */
    size_t since;                 /* まだ gc_since に足していない確保量 */
    struct SThread *next;
} SThread;
static SThread main_thread;
static SThread *threads = &main_thread; /* 生きているスレッド(world_mu を持って変える) */
static _Thread_local SThread *self_thread = &main_thread;
static int world_multi;                 /* 2つ目のスレッドを作ったら 1 */
/* world_mu: スレッドの状態・表、通路・ロック・枠の中身を守る。GC をするスレッドは、終わるまでこれを持つ */
static pthread_mutex_t world_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t world_stop_cv = PTHREAD_COND_INITIALIZER;   /* 動いているスレッドが減った(GC が待つ) */
static pthread_cond_t world_resume_cv = PTHREAD_COND_INITIALIZER; /* GC が終わった */
static pthread_mutex_t alloc_mu = PTHREAD_MUTEX_INITIALIZER;      /* 領域の表と、共有の空きブロック */
int32_t rt_gc_stop;                     /* GC が止まってほしいとき 1(IR の安全点が読む) */
static int world_running = 1;           /* 動いているスレッドの数(world_mu) */

/* いまのレジスタとスタックの位置を残す(このあと GC がこのスレッドのスタックを調べてよい) */
__attribute__((noinline)) static void world_save(SThread *t) {
    setjmp(t->regs); /* レジスタにだけある値も GC から見えるように */
    volatile char here = 0;
    t->lo = (char *)&here;
}

/* world_mu を持って呼ぶ。動いているのをやめ、GC が終わるまで待ち、また動く */
static void world_park_locked(void) {
    world_running--;
    pthread_cond_signal(&world_stop_cv);
    while (__atomic_load_n(&rt_gc_stop, __ATOMIC_RELAXED)) pthread_cond_wait(&world_resume_cv, &world_mu);
    world_running++;
}

/* 安全点: GC が止まってほしいなら止まる(IR が関数の入口で rt_gc_stop を見て呼ぶ) */
void rt_safepoint(void) {
    if (!world_multi) return;
    world_save(self_thread);
    pthread_mutex_lock(&world_mu);
    world_park_locked();
    pthread_mutex_unlock(&world_mu);
}

/* 外に出る。このあと戻るまで、する の値を作ったり runtime の表を触ったりしない */
__attribute__((noinline)) static void world_release(void) {
    if (!world_multi) return;
    world_save(self_thread);
    pthread_mutex_lock(&world_mu);
    world_running--;
    pthread_cond_signal(&world_stop_cv);
    pthread_mutex_unlock(&world_mu);
}

/* 外から戻る(GC の途中なら終わるまで待つ) */
static void world_acquire(void) {
    if (!world_multi) return;
    pthread_mutex_lock(&world_mu);
    while (__atomic_load_n(&rt_gc_stop, __ATOMIC_RELAXED)) pthread_cond_wait(&world_resume_cv, &world_mu);
    world_running++;
    pthread_mutex_unlock(&world_mu);
}

static void world_lock(void) {
    if (world_multi) pthread_mutex_lock(&world_mu);
}
static void world_unlock(void) {
    if (world_multi) pthread_mutex_unlock(&world_mu);
}

/* fork: 子には呼んだスレッドだけが残る。GC や確保の途中で fork しないよう、ロックを取ってから fork し、
 * 子ではスレッドの表を自分だけにして、スレッドが1つの状態に戻す(fork は外部の関数なので、呼ぶスレッドは外にいる) */
static pthread_mutex_t sock_mu = PTHREAD_MUTEX_INITIALIZER; /* 通信の表(socks) */
static void world_atfork_prepare(void) {
    if (!world_multi) return;
    pthread_mutex_lock(&world_mu);
    pthread_mutex_lock(&alloc_mu);
    pthread_mutex_lock(&sock_mu);
}
static void world_atfork_parent(void) {
    if (!world_multi) return;
    pthread_mutex_unlock(&sock_mu);
    pthread_mutex_unlock(&alloc_mu);
    pthread_mutex_unlock(&world_mu);
}
static void world_atfork_child(void) {
    if (!world_multi) return;
    pthread_mutex_init(&world_mu, NULL);
    pthread_mutex_init(&alloc_mu, NULL);
    pthread_mutex_init(&sock_mu, NULL);
    pthread_cond_init(&world_stop_cv, NULL);
    pthread_cond_init(&world_resume_cv, NULL);
    pthread_cond_init(&self_thread->wcv, NULL);
    rt_gc_stop = 0;
    world_multi = 0; /* 戻ったところの world_acquire は何もしない */
    world_running = 1;
    threads = self_thread;
    self_thread->next = NULL;
    self_thread->lo = NULL;
}

static void gc_oom(void) {
    fputs("エラー: メモリが足りません\n", stderr);
    exit(1);
}

static size_t gc_hash(uintptr_t base) { return (size_t)((base >> 18) * 0x9E3779B97F4A7C15ULL); }

static void gc_tab_put(GcBlk *b) {
    if (2 * (gc_ntab + 1) > gc_tabcap) { /* 半分を超えたら広げる */
        size_t ncap = gc_tabcap ? gc_tabcap * 2 : 256;
        GcBlk **nt = calloc(ncap, sizeof(GcBlk *));
        if (!nt) gc_oom();
        for (size_t i = 0; i < gc_tabcap; i++) {
            if (!gc_tab[i]) continue;
            size_t h = gc_hash((uintptr_t)gc_tab[i]->start) & (ncap - 1);
            while (nt[h]) h = (h + 1) & (ncap - 1);
            nt[h] = gc_tab[i];
        }
        free(gc_tab);
        gc_tab = nt;
        gc_tabcap = ncap;
    }
    size_t h = gc_hash((uintptr_t)b->start) & (gc_tabcap - 1);
    while (gc_tab[h]) h = (h + 1) & (gc_tabcap - 1);
    gc_tab[h] = b;
    gc_ntab++;
}

static void gc_add_region(GcBlk *b) {
    if (gc_nregs == gc_capregs) {
        gc_capregs = gc_capregs ? gc_capregs * 2 : 64;
        gc_regs = realloc(gc_regs, gc_capregs * sizeof(GcBlk *));
        if (!gc_regs) gc_oom();
    }
    gc_regs[gc_nregs++] = b;
    if ((uintptr_t)b->start < gc_lo) gc_lo = (uintptr_t)b->start;
    if ((uintptr_t)b->end > gc_hi) gc_hi = (uintptr_t)b->end;
    if (!b->large) { gc_tab_put(b); return; }
    if (gc_nlarge == gc_caplarge) {
        gc_caplarge = gc_caplarge ? gc_caplarge * 2 : 64;
        gc_large = realloc(gc_large, gc_caplarge * sizeof(GcBlk *));
        if (!gc_large) gc_oom();
    }
    size_t lo = 0, hi = gc_nlarge;
    while (lo < hi) {
        size_t m = (lo + hi) / 2;
        if (gc_large[m]->start < b->start) lo = m + 1;
        else hi = m;
    }
    memmove(gc_large + lo + 1, gc_large + lo, (gc_nlarge - lo) * sizeof(GcBlk *));
    gc_large[lo] = b;
    gc_nlarge++;
}

static GcBlk *gc_find(uintptr_t p) {
    if (p < gc_lo || p >= gc_hi) return NULL;
    if (gc_tabcap) {
        uintptr_t base = p & ~(uintptr_t)(GC_BLOCK - 1);
        for (size_t h = gc_hash(base) & (gc_tabcap - 1); gc_tab[h]; h = (h + 1) & (gc_tabcap - 1))
            if ((uintptr_t)gc_tab[h]->start == base) return p < (uintptr_t)gc_tab[h]->end ? gc_tab[h] : NULL;
    }
    size_t lo = 0, hi = gc_nlarge;
    while (lo < hi) {
        size_t m = (lo + hi) / 2;
        if ((uintptr_t)gc_large[m]->start <= p) lo = m + 1;
        else hi = m;
    }
    if (lo == 0) return NULL;
    GcBlk *b = gc_large[lo - 1];
    return p < (uintptr_t)b->end ? b : NULL;
}

/* 新しいブロック(どのつながりにも入れない。alloc_mu を持たずに呼び、表に足すところだけ持つ) */
static GcBlk *gc_new_block(int atomic, int k) {
    GcBlk *b = malloc(sizeof(GcBlk));
    char *mem = aligned_alloc(GC_BLOCK, GC_BLOCK); /* 番地を GC_BLOCK にそろえる(gc_find が下位を落として引く) */
    if (!b || !mem) gc_oom();
    b->osz = GC_SIZES[k];
    b->nobj = GC_BLOCK / b->osz;
    b->start = mem;
    b->end = mem + b->nobj * b->osz;
    b->large = 0;
    b->atomic = atomic;
    b->mark = calloc(b->nobj, 1);
    if (!b->mark) gc_oom();
    b->cursor = 0;
    b->next = NULL;
    if (world_multi) pthread_mutex_lock(&alloc_mu);
    gc_add_region(b);
    if (world_multi) pthread_mutex_unlock(&alloc_mu);
    return b;
}

/* --- 印を付ける --- */

static uintptr_t *gc_stack;
static size_t gc_nstack, gc_capstack;

static void gc_mark(uintptr_t p) {
    GcBlk *b = gc_find(p);
    if (!b) return;
    size_t i = (p - (uintptr_t)b->start) / b->osz;
    if (b->mark[i] != GC_USED) return;
    b->mark[i] = GC_MARKED;
    if (b->atomic) return;
    if (gc_nstack + 2 > gc_capstack) {
        gc_capstack = gc_capstack ? gc_capstack * 2 : 4096;
        gc_stack = realloc(gc_stack, gc_capstack * sizeof(uintptr_t));
        if (!gc_stack) gc_oom();
    }
    gc_stack[gc_nstack++] = (uintptr_t)b->start + i * b->osz;
    gc_stack[gc_nstack++] = b->osz;
}

/* スタックやレジスタ: C の局所変数が文字列の途中(奇数の番地)を指すこともあるので、すべての語を調べる */
__attribute__((no_sanitize("thread"))) static void gc_mark_range(const void *lo, const void *hi) {
    const char *p = (const char *)(((uintptr_t)lo + 7) & ~(uintptr_t)7);
    for (; p + sizeof(uintptr_t) <= (const char *)hi; p += sizeof(uintptr_t)) {
        uintptr_t w = *(const uintptr_t *)p;
        if (w >= gc_lo && w < gc_hi) gc_mark(w);
    }
}

/* オブジェクトの中: 奇数の語は整数の値なので調べない(中にあるポインタは値かフレーム・配列で、どれも偶数) */
static void gc_mark_object(const uintptr_t *p, size_t size) {
    for (const uintptr_t *e = p + size / sizeof(uintptr_t); p < e; p++) {
        uintptr_t w = *p;
        if (!(w & 1) && w >= gc_lo && w < gc_hi) gc_mark(w);
    }
}

static void gc_drain(void) {
    while (gc_nstack) {
        size_t size = gc_stack[--gc_nstack];
        uintptr_t o = gc_stack[--gc_nstack];
        gc_mark_object((const uintptr_t *)o, size);
    }
}

static void gc_mark_tables(void); /* 実行時ライブラリの表(下で定義) */

__attribute__((noinline)) static void gc_mark_stack(void) {
    jmp_buf regs; /* レジスタにだけある値もスタックに書き出す */
    setjmp(regs);
    volatile char here = 0;
    gc_mark_range((const void *)&regs, (const void *)(&regs + 1));
    gc_mark_range((const void *)&here, self_thread->top);
    /* ほかのスレッド(みな止まっているか外にいる): 止まった・外に出たときのレジスタとスタック */
    for (SThread *t = threads; t; t = t->next) {
        if (t == self_thread) continue;
        if (t->start) gc_mark(t->start);
        if (t->cell) gc_mark(t->cell);
        if (!t->lo) continue;
        gc_mark_range((const void *)&t->regs, (const void *)(&t->regs + 1));
        gc_mark_range((const void *)t->lo, t->top);
    }
}

static void gc_collect(void) {
    gc_count++;
    /* 根 */
    for (int64_t i = 0; i < suru_nroots; i++) gc_mark((uintptr_t)*suru_roots[i]);
    gc_mark_tables();
    gc_drain();
    gc_mark_stack();
    gc_drain();
    /* 片付け: 印のないものを空きに戻す。スレッドが持っていたブロックも共有のつながりに戻す */
    memset(gc_avail, 0, sizeof gc_avail);
    for (SThread *t = threads; t; t = t->next) {
        memset(t->avail, 0, sizeof t->avail);
        t->since = 0;
    }
    gc_live = 0;
    size_t keep = 0;
    for (size_t r = 0; r < gc_nregs; r++) {
        GcBlk *b = gc_regs[r];
        if (b->large) {
            if (b->mark[0] != GC_MARKED) {
                free(b->start);
                b->start = NULL; /* GcBlk そのものは gc_large から除くときに解放する */
                free(b->mark);
                continue;
            }
            b->mark[0] = GC_USED;
            gc_live += b->osz;
        } else {
            /* 印のあるもの(2)は使用中(1)に、印のないもの(1・0)は空き(0)に。空きは確保するときに探す */
            int k = gc_class_of[b->osz / 16];
            uint8_t *m = b->mark;
            size_t used = 0;
            for (size_t i = 0; i < b->nobj; i++) {
                m[i] >>= 1;
                used += m[i];
            }
            gc_live += used * b->osz;
            b->cursor = 0;
            if (used < b->nobj) {
                b->next = gc_avail[b->atomic][k];
                gc_avail[b->atomic][k] = b;
            }
        }
        gc_regs[keep++] = b;
    }
    gc_nregs = keep;
    size_t lk = 0;
    for (size_t r = 0; r < gc_nlarge; r++)
        if (gc_large[r]->start) gc_large[lk++] = gc_large[r];
        else free(gc_large[r]);
    gc_nlarge = lk;
    gc_since = 0;
    /* 次は生きている量の2倍を確保したとき(マークの合計が確保量に比例するように) */
    gc_next = 2 * gc_live > gc_min ? 2 * gc_live : gc_min;
    if (gc_log)
        fprintf(stderr, "GC %lld: 生きている %zu KB、領域 %zu、スタック %zu KB\n", (long long)gc_count, gc_live >> 10, gc_nregs,
                (size_t)(self_thread->top - (char *)__builtin_frame_address(0)) >> 10);
}

static void gc_init(void) {
    for (int s = 0, k = 0; s <= GC_SMALL_MAX / 16; s++) {
        while (GC_SIZES[k] < (uint32_t)s * 16) k++;
        gc_class_of[s] = (uint8_t)k;
    }
}

/* GC をする。ほかのスレッドがいれば、みな止まるのを待ってから(ほかのスレッドが始めていたら、止まって終わるのを待つ) */
static void gc_request(void) {
    if (!world_multi) { gc_collect(); return; }
    world_save(self_thread);
    pthread_mutex_lock(&world_mu);
    if (__atomic_load_n(&rt_gc_stop, __ATOMIC_RELAXED)) world_park_locked();
    else if (__atomic_load_n(&gc_since, __ATOMIC_RELAXED) >= gc_next) {
        __atomic_store_n(&rt_gc_stop, 1, __ATOMIC_RELAXED);
        while (world_running > 1) pthread_cond_wait(&world_stop_cv, &world_mu);
        gc_collect();
        __atomic_store_n(&rt_gc_stop, 0, __ATOMIC_RELAXED);
        pthread_cond_broadcast(&world_resume_cv);
    }
    pthread_mutex_unlock(&world_mu);
}

/* 確保した量を数える(スレッドごとにためて、ときどき足す) */
static void gc_count_alloc(SThread *t, size_t n) {
    t->since += n;
    if (t->since >= gc_batch) {
        __atomic_fetch_add(&gc_since, t->since, __ATOMIC_RELAXED);
        t->since = 0;
    }
}

static void *gc_alloc(int64_t size, int atomic) {
    if (size < 16) size = 16;
    if (__atomic_load_n(&rt_gc_stop, __ATOMIC_RELAXED)) rt_safepoint();
    if (gc_on && __atomic_load_n(&gc_since, __ATOMIC_RELAXED) >= gc_next) gc_request();
    SThread *t = self_thread;
    if (size > GC_SMALL_MAX) {
        GcBlk *b = malloc(sizeof(GcBlk));
        char *mem = calloc(1, (size_t)size);
        if (!b || !mem) gc_oom();
        b->start = mem;
        b->end = mem + size;
        b->osz = (size_t)size;
        b->nobj = 1;
        b->large = 1;
        b->atomic = atomic;
        b->mark = calloc(1, 1);
        if (!b->mark) gc_oom();
        b->mark[0] = GC_USED;
        if (world_multi) pthread_mutex_lock(&alloc_mu);
        gc_add_region(b);
        if (world_multi) pthread_mutex_unlock(&alloc_mu);
        gc_count_alloc(t, (size_t)size);
        return mem;
    }
    int k = gc_class_of[(size + 15) / 16];
    GcBlk *b;
    uint8_t *f;
    for (;;) {
        b = t->avail[atomic][k];
        if (!b) { /* 共有のつながりから1つもらう(なければ新しく作る) */
            if (world_multi) pthread_mutex_lock(&alloc_mu);
            b = gc_avail[atomic][k];
            if (b) gc_avail[atomic][k] = b->next;
            if (world_multi) pthread_mutex_unlock(&alloc_mu);
            if (!b) b = gc_new_block(atomic, k);
            t->avail[atomic][k] = b;
        }
        f = memchr(b->mark + b->cursor, GC_FREE, b->nobj - b->cursor);
        if (f) break;
        t->avail[atomic][k] = NULL; /* このブロックはもう空きがない(次の GC で空きがあればつながりに戻る) */
    }
    size_t i = (size_t)(f - b->mark);
    b->cursor = i + 1;
    *f = GC_USED;
    void *o = b->start + i * b->osz;
    memset(o, 0, GC_SIZES[k]);
    gc_count_alloc(t, GC_SIZES[k]);
    return o;
}

void *rt_alloc(int64_t size) { return gc_alloc(size, 0); }
static void *rt_alloc_atomic(int64_t size) { return gc_alloc(size, 1); }

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
typedef struct TryFrame { jmp_buf jb; struct TryFrame *prev; int quiet; } TryFrame; /* quiet: 文を書かない(並列写像の中) */
static _Thread_local TryFrame *try_top;
static _Thread_local char *fail_last_msg;
static _Thread_local int32_t fail_last_pos;

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
        if (!try_top->quiet) {
            fprintf(stderr, "%s\n", b.s);
            fflush(stderr);
        }
        free(b.s);
        free(fail_last_msg); /* スレッドの一番外の受け口が、合流したときに同じエラーにするために覚えておく */
        fail_last_msg = strdup(msg);
        fail_last_pos = pos;
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
static List EMPTY_OBJ = {T_LIST, 0, NULL};
#define V_EMPTY ((V)(intptr_t)&EMPTY_OBJ)

V rt_bool(int32_t b) { return b ? V_TRUE : V_FALSE; }

static V mk_int(int64_t n, int32_t pos) {
    if (n > INT_MAX62 || n < INT_MIN62)
        fail(pos, "整数が大きすぎます(コンパイルしたプログラムの整数は ±%lld までです)", (long long)INT_MAX62);
    return (V)(((uint64_t)n << 1) | 1);
}

V rt_float(double d) {
    Flt *f = rt_alloc_atomic(sizeof(Flt));
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
    Str *o = rt_alloc_atomic(sizeof(Str) + n + 1);
    o->tag = T_STR;
    o->n = n;
    memcpy(o->s, s, n);
    o->s[n] = 0;
    o->ncp = count_cp(s, n);
    return (V)(intptr_t)o;
}
V rt_str(const char *s, int64_t n) { return mk_str(s, n); }
static V cstr(const char *s) { return mk_str(s, strlen(s)); }
/* Buf の中身を文字列の値にして、Buf は解放する */
static V buf_str(Buf *b) {
    V r = mk_str(b->s ? b->s : "", (int64_t)b->n);
    free(b->s);
    b->s = NULL;
    return r;
}

static List *new_list(int64_t n) {
    List *l = rt_alloc(sizeof(List) + n * sizeof(V));
    l->tag = T_LIST;
    l->n = n;
    l->it = l->data;
    return l;
}
/* l の lo から n 個。コピーせず元の配列を指す(GC は途中を指すポインタで元のリストを生かす) */
static V list_slice(List *l, int64_t lo, int64_t n) {
    if (n == 0) return V_EMPTY;
    List *s = rt_alloc(sizeof(List));
    s->tag = T_LIST;
    s->n = n;
    s->it = l->it + lo;
    return (V)(intptr_t)s;
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
    /* ほかのスレッドが同時に計算することもある(純粋なので同じ値になる) */
    if (__atomic_load_n(&z->state, __ATOMIC_ACQUIRE) == 0) {
        V x = z->code(z->up, NULL, 0);
        __atomic_store_n(&z->v, x, __ATOMIC_RELAXED);
        __atomic_store_n(&z->state, 1, __ATOMIC_RELEASE);
        return x;
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

static void gc_mark_tables(void) {
    for (int i = 0; i < nshared; i++) gc_mark((uintptr_t)shared[i].v);
    for (int i = 0; i < nctors; i++) gc_mark((uintptr_t)ctors[i]->nullary);
    for (int i = 0; i < ntraits; i++)
        for (int j = 0; j < traits[i]->nm; j++) gc_mark((uintptr_t)traits[i]->m[j].deflt);
    for (int i = 0; i < nimpls; i++)
        for (int j = 0; j < impls[i].n; j++) gc_mark((uintptr_t)impls[i].fns[j]);
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
    return buf_str(&b);
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
    if (!b.s) buf_add(&b, "", 0);
    return b.s; /* malloc したもの */
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
    if (op == OP_ADD && TAG(a) == T_STR && TAG(b) == T_STR) { /* 文字列どうしはそのままつなぐ */
        Str *x = AS(Str, a), *y = AS(Str, b);
        Str *o = rt_alloc_atomic(sizeof(Str) + x->n + y->n + 1);
        o->tag = T_STR;
        o->n = x->n + y->n;
        o->ncp = x->ncp + y->ncp;
        memcpy(o->s, x->s, x->n);
        memcpy(o->s + x->n, y->s, y->n);
        o->s[o->n] = 0;
        return (V)(intptr_t)o;
    }
    if (op == OP_ADD && (TAG(a) == T_STR || TAG(b) == T_STR)) {
        Buf x = plain(a), y = plain(b);
        buf_add(&x, y.s, y.n);
        free(y.s);
        return buf_str(&x);
    }
    if (op >= OP_LT && op <= OP_GE && TAG(a) == T_STR && TAG(b) == T_STR) {
        /* 文字列どうしは文字の番号の順(辞書順)。UTF-8 のバイトの順は文字の番号の順と同じ */
        Str *x = AS(Str, a), *y = AS(Str, b);
        int64_t m = x->n < y->n ? x->n : y->n;
        int c = memcmp(x->s, y->s, (size_t)m);
        if (c == 0) c = (x->n > y->n) - (x->n < y->n);
        switch (op) {
        case OP_LT: return rt_bool(c < 0);
        case OP_GT: return rt_bool(c > 0);
        case OP_LE: return rt_bool(c <= 0);
        default: return rt_bool(c >= 0);
        }
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
    if (TAG(v) != T_LIST) { /* エラー文は失敗したときだけ作る */
        char what[256];
        snprintf(what, sizeof what, "「の %s」の前", name);
        need_list(v, what, pos);
    }
    List *l = AS(List, v);
    if (strcmp(name, "残り") == 0) {
        if (l->n == 0) fail(pos, "空のリストに「残り」はありません");
        return list_slice(l, 1, l->n - 1);
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
        if (strcmp(fname, "残り") == 0) return list_slice(l, 1, l->n - 1);
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
static V thread_run(Act *a);

static V act_run(Act *a) {
    switch (a->kind) {
    case A_SHOW: {
        char *s = (char *)show(a->a);
        flockfile(stdout); /* ほかのスレッドの表示と混ざらないように */
        fputs(s, stdout);
        fputc('\n', stdout);
        funlockfile(stdout);
        free(s);
        return a->a;
    }
    case A_INPUT: {
        if (a->a) { fputs(AS(Str, a->a)->s, stdout); }
        fflush(stdout);
        char *line = NULL;
        size_t cap = 0;
        world_release();
        ssize_t n = getline(&line, &cap, stdin);
        world_acquire();
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
        f.quiet = a->b == 0; /* 「で」を省いたときは、エラーの文を書かずに失敗にする */
        try_top = &f;
        if (setjmp(f.jb) == 0) {
            V r = perform(a->a);
            try_top = f.prev;
            return a->b ? r : rt_construct("成功", 1, &r, 0);
        }
        if (!a->b) {
            V why = rt_str(fail_last_msg, (int64_t)strlen(fail_last_msg));
            return rt_construct("失敗", 1, &why, 0);
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
    case A_PEEK: case A_POKE: case A_ERRNO: case A_FAIL: case A_ARGS: case A_EXIT: return mem_run(a);
    case A_SPAWN: case A_JOIN: case A_NCPU: case A_CH_NEW: case A_CH_PIPE: case A_CH_FIFO_NEW: case A_CH_FIFO_OPEN: case A_CH_FIFO_DEL: case A_CH_SEND: case A_CH_RECV: case A_CH_CLOSE: case A_CH_EACH:
    case A_LOCK_NEW: case A_LOCKED: case A_SLOT_NEW: case A_SLOTTED: case A_BOX_NEW: case A_BOX_GET: case A_BOX_UPDATE: case A_BOX_SET:
        return thread_run(a);
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

/* 「…した 中身」: 成否の成功・有無の有なら中の値、失敗・無なら 0 */
V rt_unwrap(V v, const char *name, int32_t pos) {
    if (TAG(v) == T_REC) {
        Ctor *c = AS(Rec, v)->c;
        if (!strcmp(c->type, "成否") || !strcmp(c->type, "有無")) {
            if (!strcmp(c->name, "成功") || !strcmp(c->name, "有")) return AS(Rec, v)->v[0];
            if (!strcmp(c->name, "失敗") || !strcmp(c->name, "無")) return 0;
        }
    }
    fail(pos, "「%sした 中身」: 「%s」は成否でも有無でもありません", name, show(v));
}

/* 手順の中の「…した 中身」: 成功なら続き k に中の値を渡し、失敗なら手順をそこで終えて失敗を結果にする */
static V unwrap_then(V v, V k, const char *name, int32_t pos) {
    V x = rt_unwrap(v, name, pos);
    return x ? apply1(k, x, pos) : mk_pure(v);
}
static V k_unwrap(void *up, V *args, int32_t pos) {
    KData *d = up;
    return unwrap_then(args[0], d->f, (const char *)(intptr_t)d->m, d->pos);
}
V rt_do_unwrap(V m, V k, const char *name, int32_t pos) {
    int t = TAG(m);
    if (t == T_ACT || t == T_PURE) return chain(m, mk_k("中身", k_unwrap, k, (V)(intptr_t)name, pos), pos);
    return unwrap_then(m, k, name, pos);
}

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
            V r = 0;
            if (digits) {
                long long x = strtoll(t, &e, 10);
                if (*e == 0) r = mk_int(x, pos);
            }
            if (!r) {
                double d = strtod(t, &e);
                if (*e == 0) r = rt_float(d);
            }
            if (r) { free(b.s); return r; }
        }
        free(b.s);
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
    return list_slice(AS(List, v), lo, hi - lo);
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
    return buf_str(&b);
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
    return buf_str(&b);
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
    return buf_str(&b);
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

/* 開いているものだけを持つ(番号は増える一方で、閉じたものは表から除く) */
typedef struct { int64_t num; int fd; FILE *in; } Sock;
static Sock *socks;
static int64_t nsocks, capsocks, lastsock;

static int64_t sock_add(int fd) {
    pthread_mutex_lock(&sock_mu);
    if (nsocks == capsocks) {
        capsocks = capsocks ? capsocks * 2 : 16;
        socks = realloc(socks, capsocks * sizeof(Sock));
        if (!socks) fail(0, "メモリが足りません");
    }
    socks[nsocks].num = ++lastsock;
    socks[nsocks].fd = fd;
    socks[nsocks].in = NULL;
    nsocks++;
    int64_t num = lastsock;
    pthread_mutex_unlock(&sock_mu);
    return num;
}
/* 表の中の場所(sock_mu を持って呼ぶ。なければ -1) */
static int64_t sock_find(V v) {
    int64_t i = IS_INT(v) ? INT_VAL(v) : 0;
    if (TAG(v) != T_BOOL)
        for (int64_t k = nsocks; k-- > 0;)
            if (socks[k].num == i) return k;
    return -1;
}
/* 番号の待受口か接続(写しを返す。ほかのスレッドが表を広げても使える)。want_in なら読むための FILE も作る */
static Sock sock_get2(V v, const char *what, int want_in, int32_t pos) {
    pthread_mutex_lock(&sock_mu);
    int64_t k = sock_find(v);
    if (k < 0) {
        pthread_mutex_unlock(&sock_mu);
        fail(pos, "「%s」は開いている%sではありません", plain(v).s, what);
    }
    if (want_in && !socks[k].in) {
        int fd2 = dup(socks[k].fd);
        if (fd2 >= 0) socks[k].in = fdopen(fd2, "rb");
    }
    Sock s = socks[k];
    pthread_mutex_unlock(&sock_mu);
    return s;
}
static Sock sock_get(V v, const char *what, int32_t pos) { return sock_get2(v, what, 0, pos); }
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
        int lfd = sock_get(a->a, "待受口", pos).fd;
        fflush(stdout); /* 待つ前に、それまでの表示を出しておく */
        int fd;
        world_release(); /* 待つ間は、表(socks)に触らない */
        do fd = accept(lfd, NULL, NULL); while (fd < 0 && errno == EINTR);
        int e = errno;
        world_acquire();
        errno = e;
        if (fd < 0) net_fail(a);
        struct timeval tv = {5, 0}; /* 何も送ってこない相手で止まらないように(インタプリタの NET_TIMEOUT と同じ) */
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
        return mk_int(sock_add(fd), pos);
    }
    case A_RECVLINE: case A_RECV: {
        Sock s = sock_get2(a->a, "接続", 1, pos);
        fflush(stdout);
        int64_t want = 0;
        if (a->kind == A_RECV) {
            V v = need_num(a->b, pos);
            want = IS_INT(v) ? INT_VAL(v) : -1;
            if (want < 0) fail(pos, "「%s」は受信するバイト数ではありません", plain(v).s);
        }
        if (!s.in) net_fail(a);
        FILE *in = s.in; /* 待つ間は、表(socks)に触らない */
        Buf b = {0};
        world_release();
        if (a->kind == A_RECVLINE) {
            /* 終わりの改行を含めて1行(長すぎる行は 65536 バイトで切る) */
            int c;
            while (b.n < 65536 && (c = fgetc(in)) != EOF) {
                char ch = (char)c;
                buf_add(&b, &ch, 1);
                if (ch == '\n') break;
            }
        } else {
            char tmp[4096];
            while ((int64_t)b.n < want) {
                size_t k = fread(tmp, 1, (size_t)(want - (int64_t)b.n) < sizeof tmp ? (size_t)(want - (int64_t)b.n) : sizeof tmp, in);
                if (k == 0) break;
                buf_add(&b, tmp, k);
            }
        }
        int bad = ferror(in), e = errno;
        world_acquire();
        errno = e;
        if (bad) { free(b.s); net_fail(a); }
        return buf_str(&b);
    }
    case A_SEND: {
        Str *str = need_str(a->a, "「送信する」の「を」", pos);
        int fd = sock_get(a->b, "接続", pos).fd;
        int64_t off = 0;
        world_release(); /* str は手放しているスレッドのスタックから見えるので回収されない */
        while (off < str->n) {
            ssize_t k = send(fd, str->s + off, (size_t)(str->n - off), 0);
            if (k < 0 && errno == EINTR) continue;
            if (k < 0) break;
            off += k;
        }
        int e = errno;
        world_acquire();
        errno = e;
        if (off < str->n) net_fail(a);
        return mk_int(str->n, pos);
    }
    case A_CLOSE: {
        pthread_mutex_lock(&sock_mu);
        int64_t k = sock_find(a->a);
        if (k < 0) {
            pthread_mutex_unlock(&sock_mu);
            fail(pos, "「%s」は開いている待受口か接続ではありません", plain(a->a).s);
        }
        Sock s = socks[k];
        socks[k] = socks[--nsocks];
        pthread_mutex_unlock(&sock_mu);
        if (s.in) fclose(s.in);
        close(s.fd);
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
BI(s_try) { /* を, で(「で」を省くと成否を返す) */
    const char *parts[2] = {"を", "で"};
    for (int i = 0; i < (a[1] ? 2 : 1); i++) {
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

static const int32_t P1_DE[] = {P_DE}, P2_DE_WO[] = {P_DE, P_WO}, P1_WO[] = {P_WO}, P2_WO_NI[] = {P_WO, P_NI}, P2_KARA_WO[] = {P_KARA, P_WO},
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
static _Thread_local int ffi_errno;

static V mk_bytes(const void *p, int64_t n) {
    Bytes *b = rt_alloc_atomic(sizeof(Bytes) + n + 1); /* 中にポインタはない */
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
/* 直列化: 値をバイト列にする(プロセスどうしで値を渡すため)。
   形式は「SURU」+ 版(1)の後に値が1つ。数は小さい順の8バイト、長さは4バイト。
   i 整数 / f 小数 / b 真偽(1バイト) / s 文字列 / y バイト列 / l リスト(個数と中身) / r 組(形の名前、フィールドの数、名前と値) */
static void ser_u32(Buf *b, uint32_t n) {
    uint8_t d[4] = {n & 255, (n >> 8) & 255, (n >> 16) & 255, (n >> 24) & 255};
    buf_add(b, (const char *)d, 4);
}
static void ser_u64(Buf *b, uint64_t n) {
    uint8_t d[8];
    for (int i = 0; i < 8; i++) d[i] = (n >> (8 * i)) & 255;
    buf_add(b, (const char *)d, 8);
}
static void ser_text(Buf *b, const char *s, int64_t n) { ser_u32(b, (uint32_t)n); buf_add(b, s, (size_t)n); }
static void ser_value(Buf *b, V v, int depth, int32_t pos) {
    v = rt_force(v);
    if (depth > 10000) fail(pos, "入れ子が深すぎて直列化できません");
    switch (TAG(v)) {
    case T_INT: buf_add(b, "i", 1); ser_u64(b, (uint64_t)INT_VAL(v)); return;
    case T_FLT: {
        uint64_t u;
        memcpy(&u, &AS(Flt, v)->d, 8);
        buf_add(b, "f", 1);
        ser_u64(b, u);
        return;
    }
    case T_BOOL: buf_add(b, AS(Bool, v)->b ? "b\1" : "b\0", 2); return;
    case T_STR: buf_add(b, "s", 1); ser_text(b, AS(Str, v)->s, AS(Str, v)->n); return;
    case T_BYTES: buf_add(b, "y", 1); ser_text(b, (const char *)AS(Bytes, v)->d, AS(Bytes, v)->n); return;
    case T_LIST: {
        List *l = AS(List, v);
        buf_add(b, "l", 1);
        ser_u32(b, (uint32_t)l->n);
        for (int64_t i = 0; i < l->n; i++) ser_value(b, l->it[i], depth + 1, pos);
        return;
    }
    case T_REC: {
        Rec *r = AS(Rec, v);
        buf_add(b, "r", 1);
        ser_text(b, r->c->name, strlen(r->c->name));
        ser_u32(b, (uint32_t)r->c->n);
        for (int i = 0; i < r->c->n; i++) {
            ser_text(b, r->c->fields[i], strlen(r->c->fields[i]));
            ser_value(b, r->v[i], depth + 1, pos);
        }
        return;
    }
    default:
        fail(pos, "「%s」は直列化できません(関数・動作・番地はほかのプロセスへ渡せません)", plain(v).s);
    }
}
BI(m_serialize) {
    Buf b = {0};
    buf_add(&b, "SURU\1", 5);
    ser_value(&b, a[0], 0, pos);
    V r = mk_bytes(b.s, (int64_t)b.n);
    free(b.s);
    return r;
}
typedef struct { const uint8_t *d; int64_t n, i; int32_t pos; } Deser;
__attribute__((noreturn)) static void deser_bad(Deser *z) { fail(z->pos, "バイト列が直列化した値ではありません(%lld バイト目)", (long long)z->i); }
static const uint8_t *deser_take(Deser *z, int64_t k) {
    if (k < 0 || z->i + k > z->n) deser_bad(z);
    const uint8_t *p = z->d + z->i;
    z->i += k;
    return p;
}
static uint32_t deser_u32(Deser *z) {
    const uint8_t *p = deser_take(z, 4);
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint64_t deser_u64(Deser *z) {
    const uint8_t *p = deser_take(z, 8);
    uint64_t u = 0;
    for (int i = 7; i >= 0; i--) u = (u << 8) | p[i];
    return u;
}
static V deser_value(Deser *z, int depth) {
    if (depth > 10000) fail(z->pos, "入れ子が深すぎて復元できません");
    uint8_t t = *deser_take(z, 1);
    switch (t) {
    case 'i': return mk_int((int64_t)deser_u64(z), z->pos);
    case 'f': {
        uint64_t u = deser_u64(z);
        double d;
        memcpy(&d, &u, 8);
        return rt_float(d);
    }
    case 'b': {
        uint8_t x = *deser_take(z, 1);
        if (x > 1) deser_bad(z);
        return rt_bool(x);
    }
    case 's': {
        uint32_t k = deser_u32(z);
        const uint8_t *p = deser_take(z, k);
        if (!utf8_valid(p, k)) fail(z->pos, "復元した文字列が UTF-8 ではありません");
        return mk_str((const char *)p, k);
    }
    case 'y': {
        uint32_t k = deser_u32(z);
        return mk_bytes(deser_take(z, k), k);
    }
    case 'l': {
        uint32_t k = deser_u32(z);
        if (k == 0) return V_EMPTY;
        if (k > (uint64_t)(z->n - z->i)) deser_bad(z); /* 中身は1つ1バイト以上 */
        List *l = new_list(k);
        for (uint32_t j = 0; j < k; j++) l->it[j] = deser_value(z, depth + 1);
        return (V)(intptr_t)l;
    }
    case 'r': {
        uint32_t k = deser_u32(z);
        const uint8_t *p = deser_take(z, k);
        char name[256];
        if (k >= sizeof name) deser_bad(z);
        memcpy(name, p, k);
        name[k] = 0;
        Ctor *c = find_ctor(name);
        if (!c) fail(z->pos, "形「%s」はこのプログラムにないので復元できません", name);
        uint32_t nf = deser_u32(z);
        if ((int32_t)nf != c->n) fail(z->pos, "形「%s」のフィールドの数が違うので復元できません(このプログラムでは%d個、バイト列では%u個)", name, c->n, nf);
        if (nf == 0) return c->nullary;
        Rec *r = rt_alloc(sizeof(Rec) + nf * sizeof(V));
        r->tag = T_REC;
        r->c = c;
        for (uint32_t j = 0; j < nf; j++) {
            uint32_t fk = deser_u32(z);
            const uint8_t *fp = deser_take(z, fk);
            if (strlen(c->fields[j]) != fk || memcmp(c->fields[j], fp, fk) != 0)
                fail(z->pos, "形「%s」のフィールドが違うので復元できません(%d番目は、このプログラムでは「%s」)", name, (int)j + 1, c->fields[j]);
            r->v[j] = deser_value(z, depth + 1);
        }
        return (V)(intptr_t)r;
    }
    default: deser_bad(z);
    }
}
static V deser_all(const uint8_t *d, int64_t n, int32_t pos) {
    Deser z = {d, n, 0, pos};
    const uint8_t *h = deser_take(&z, 5);
    if (memcmp(h, "SURU", 4) != 0) deser_bad(&z);
    if (h[4] != 1) fail(pos, "直列化の版(%d)に対応していません", h[4]);
    V v = deser_value(&z, 0);
    if (z.i != z.n) deser_bad(&z);
    return v;
}
BI(m_deserialize) {
    Bytes *b = need_bytes(a[0], "「復元する」の「を」", pos);
    return deser_all(b->d, b->n, pos);
}
/* 固定の形: 見本の組の葉のフィールドを、どれも 8 バイト(整数は int64_t、小数は double、真偽は int64_t の 0 か 1)で
 * 並べる。入れ子の組は平らにする(C の構造体と同じ並び)。suru.py の _fixed_kinds と同じ */
static int64_t fixed_count(V s, int depth, int32_t pos) {
    s = rt_force(s);
    if (depth > 100) fail(pos, "入れ子が深すぎて固定の形にできません");
    switch (TAG(s)) {
    case T_INT: case T_FLT: case T_BOOL: return 1;
    case T_REC: {
        Rec *r = AS(Rec, s);
        int64_t n = 0;
        if (r->c->n > 0) {
            for (int i = 0; i < r->c->n; i++) n += fixed_count(r->v[i], depth + 1, pos);
            return n;
        }
    } /* fallthrough */
    default: fail(pos, "「%s」は固定の形にできません(できるのは、数と真偽だけでできた組です)", plain(s).s);
    }
}
static int64_t fixed_size(V s, int32_t pos) {
    s = rt_force(s);
    if (TAG(s) != T_REC || AS(Rec, s)->c->n == 0) fail(pos, "固定の形の見本は組でなければなりません(「%s」が渡されました)", plain(s).s);
    return fixed_count(s, 0, pos) * 8;
}
static void fixed_put(uint8_t **p, V x, V s, int32_t pos) {
    x = rt_force(x);
    s = rt_force(s);
    uint64_t u;
    switch (TAG(s)) {
    case T_REC: {
        Rec *rs = AS(Rec, s);
        if (TAG(x) != T_REC || AS(Rec, x)->c != rs->c) fail(pos, "「%s」は見本と形が違います(見本は「%s」)", plain(x).s, rs->c->name);
        for (int i = 0; i < rs->c->n; i++) fixed_put(p, AS(Rec, x)->v[i], rs->v[i], pos);
        return;
    }
    case T_BOOL:
        if (TAG(x) != T_BOOL) fail(pos, "「%s」は見本と違って真偽ではありません", plain(x).s);
        u = AS(Bool, x)->b ? 1 : 0;
        break;
    case T_INT:
        if (TAG(x) != T_INT) fail(pos, "「%s」は見本と違って整数ではありません", plain(x).s);
        u = (uint64_t)INT_VAL(x);
        break;
    default: { /* T_FLT */
        double d;
        if (TAG(x) == T_INT) d = (double)INT_VAL(x);
        else if (TAG(x) == T_FLT) d = AS(Flt, x)->d;
        else fail(pos, "「%s」は見本と違って数ではありません", plain(x).s);
        memcpy(&u, &d, 8);
    }
    }
    for (int i = 0; i < 8; i++) (*p)[i] = (uint8_t)(u >> (8 * i));
    *p += 8;
}
static V fixed_get(const uint8_t **p, V s, int32_t pos) {
    s = rt_force(s);
    if (TAG(s) == T_REC) {
        Rec *rs = AS(Rec, s);
        Rec *r = rt_alloc(sizeof(Rec) + rs->c->n * sizeof(V));
        r->tag = T_REC;
        r->c = rs->c;
        for (int i = 0; i < rs->c->n; i++) r->v[i] = fixed_get(p, rs->v[i], pos);
        return (V)(intptr_t)r;
    }
    uint64_t u = 0;
    for (int i = 7; i >= 0; i--) u = (u << 8) | (*p)[i];
    *p += 8;
    if (TAG(s) == T_BOOL) return u ? V_TRUE : V_FALSE;
    if (TAG(s) == T_INT) return mk_int((int64_t)u, pos);
    double d;
    memcpy(&d, &u, 8);
    return rt_float(d);
}
BI(m_fixed_ser) { /* を, で */
    int64_t n = fixed_size(a[1], pos);
    uint8_t *d = malloc((size_t)n), *p = d;
    if (!d) fail(pos, "メモリが足りません");
    fixed_put(&p, a[0], a[1], pos); /* 失敗したら d は残るが、すぐ終わるのでよしとする */
    V r = mk_bytes((const char *)d, n);
    free(d);
    return r;
}
BI(m_fixed_de) { /* を, で */
    Bytes *b = need_bytes(a[0], "「固定復元する」の「を」", pos);
    int64_t n = fixed_size(a[1], pos);
    if (b->n != n) fail(pos, "バイト列の長さが見本の形と違います(形は %lld バイト、バイト列は %lld バイト)", (long long)n, (long long)b->n);
    const uint8_t *p = b->d;
    return fixed_get(&p, a[1], pos);
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
static int prog_argc;
static char **prog_argv;
BI(m_args) { return mk_act_pos(A_ARGS, "引数取得する", 0, 0, pos); }
BI(m_exit) {
    V n = need_num(a[0], pos);
    if (!IS_INT(n) || INT_VAL(n) < 0 || INT_VAL(n) > 255) fail(pos, "「%s」は終了コードではありません(0 から 255 までの整数です)", plain(n).s);
    return mk_act_pos(A_EXIT, "終了する", n, 0, pos);
}
BI(m_abort) {
    fail_msg(pos, need_str(a[0], "「中断する」の「を」", pos)->s);
}
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
    case A_ARGS: {
        if (prog_argc <= 1) return V_EMPTY;
        List *l = new_list(prog_argc - 1);
        for (int i = 1; i < prog_argc; i++) l->it[i - 1] = cstr(prog_argv[i]);
        return (V)(intptr_t)l;
    }
    case A_EXIT:
        fflush(stdout);
        fflush(stderr);
        exit((int)INT_VAL(a->a));
    }
    return 0;
}


/* ------------------------------------------------------------------ */
/* スレッド(「スレッド」の組み込み)                                   */
/* ------------------------------------------------------------------ */

/* スレッドの結果を書くところ(GC の領域。合流する動作と、動いているスレッドの両方から見える) */
typedef struct { int64_t state; V result; char *msg; int32_t pos; } ThreadCell; /* state: 0 動いている、1 終わった、2 エラー */
/* 通路や合流の状態を変えたら、world_mu を持って呼ぶ。待っているスレッドのうち、先に進めるようになったものだけを起こす */
static void world_changed(void) {
    if (!world_multi) return;
    for (SThread *t = threads; t; t = t->next)
        if (t->wready && t != self_thread && t->wready(t->warg)) pthread_cond_signal(&t->wcv);
}

/* world_mu を持って呼び、ready(arg) が真になるまで(外に出て)待つ。持ったまま戻るので、続けて状態を変えられる。
 * ほかのスレッドがみな同じように待っていて、どれも進めないなら、ずっと終わらないのでエラーにする
 * (動いているスレッドや、外部の関数や入力で待っているスレッドは、そのうち進むかもしれないので数えない) */
static void world_wait(int (*ready)(void *), void *arg, int32_t pos) {
    while (!ready(arg)) {
        int stuck = 1;
        for (SThread *t = threads; t && stuck; t = t->next)
            if (t != self_thread && !(t->wready && !t->wready(t->warg))) stuck = 0;
        if (stuck) {
            world_unlock();
            fail(pos, "すべてのスレッドが待っていて、先に進めません(通路や合流の待ち)");
        }
        SThread *me = self_thread;
        me->warg = arg;
        me->wready = ready;
        world_save(me);
        world_running--;
        pthread_cond_signal(&world_stop_cv);
        while (!ready(arg)) pthread_cond_wait(&me->wcv, &world_mu);
        while (__atomic_load_n(&rt_gc_stop, __ATOMIC_RELAXED)) pthread_cond_wait(&world_resume_cv, &world_mu);
        world_running++;
        me->wready = NULL;
    }
}
#define THREAD_STACK ((size_t)256 << 20) /* 仮想のメモリなので、使った分だけ実際に使う */

typedef struct { V f; List *xs, *out; int64_t lo, hi; int32_t pos; } MapTask;

static V thread_perform(V v) { return perform(v); }
static V thread_map(V v) {
    MapTask *m = (MapTask *)(intptr_t)v;
    for (int64_t i = m->lo; i < m->hi; i++) m->out->it[i] = apply1(m->f, m->xs->it[i], m->pos);
    return V_EMPTY;
}

typedef struct { SThread *t; V (*run)(V); int quiet; } ThreadStart;

/* 終わったスレッド: 表から外して知らせ、使っていたブロックを共有のつながりに戻す */
static void thread_finish(SThread *t) {
    pthread_mutex_lock(&world_mu);
    SThread **pp = &threads;
    while (*pp != t) pp = &(*pp)->next;
    *pp = t->next;
    __atomic_fetch_add(&gc_since, t->since, __ATOMIC_RELAXED);
    pthread_mutex_lock(&alloc_mu);
    for (int a = 0; a < 2; a++)
        for (int k = 0; k < GC_NCLASS; k++) {
            GcBlk *b = t->avail[a][k];
            if (!b) continue;
            b->next = gc_avail[a][k];
            gc_avail[a][k] = b;
        }
    pthread_mutex_unlock(&alloc_mu);
    world_running--;
    pthread_cond_signal(&world_stop_cv);
    world_changed();
    pthread_mutex_unlock(&world_mu);
}

static void *thread_main(void *arg) {
    ThreadStart st = *(ThreadStart *)arg;
    free(arg);
    SThread *t = st.t;
    self_thread = t;
    t->top = __builtin_frame_address(0);
    world_acquire();
    ThreadCell *c = (ThreadCell *)(intptr_t)t->cell;
    /* 一番外の受け口: 実行時エラーはこのスレッドだけを終える。並行開始した動作ならその場で文を書き、
       合流したときは「エラーで終わりました」のエラー。並列写像なら文を書かず、待つ側で同じエラーにする */
    TryFrame f;
    f.prev = NULL;
    f.quiet = st.quiet;
    try_top = &f;
    int64_t state;
    if (setjmp(f.jb) == 0) {
        V r = st.run((V)t->start);
        try_top = NULL;
        c->result = r;
        state = 1;
    } else {
        if (st.quiet) {
            c->pos = fail_last_pos;
            c->msg = fail_last_msg;
            fail_last_msg = NULL;
        }
        state = 2;
    }
    pthread_mutex_lock(&world_mu);
    __atomic_store_n(&c->state, state, __ATOMIC_RELEASE);
    pthread_mutex_unlock(&world_mu);
    thread_finish(t);
    pthread_cond_destroy(&t->wcv);
    free(t);
    return NULL;
}

/* 新しいスレッドで run(arg) を始める。結果は返した ThreadCell に書く */
static ThreadCell *thread_start(V (*run)(V), V arg, int quiet, int32_t pos) {
    ThreadCell *c = rt_alloc(sizeof(ThreadCell));
    SThread *t = calloc(1, sizeof(SThread));
    ThreadStart *st = malloc(sizeof(ThreadStart));
    if (!t || !st) fail(pos, "メモリが足りません");
    c->pos = pos;
    t->start = (uintptr_t)arg;
    t->cell = (uintptr_t)c;
    st->t = t;
    st->run = run;
    st->quiet = quiet;
    pthread_cond_init(&t->wcv, NULL);
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, THREAD_STACK);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    if (!world_multi) {
        /* 初めてのスレッド: ここからロックを使う(このスレッドが動いている) */
        world_running = 1;
        world_multi = 1;
    }
    pthread_mutex_lock(&world_mu);
    t->next = threads;
    threads = t;
    pthread_mutex_unlock(&world_mu);
    pthread_t th;
    int e = pthread_create(&th, &attr, thread_main, st);
    pthread_attr_destroy(&attr);
    if (e != 0) {
        pthread_mutex_lock(&world_mu);
        SThread **pp = &threads;
        while (*pp != t) pp = &(*pp)->next;
        *pp = t->next;
        pthread_mutex_unlock(&world_mu);
        pthread_cond_destroy(&t->wcv);
        free(t);
        free(st);
        fail(pos, "スレッドを始められませんでした(%s)", strerror(e));
    }
    return c;
}

/* 終わるまで待って結果を返す(エラーで終わっていたら同じエラー) */
static int thread_done(void *arg) { return __atomic_load_n(&((ThreadCell *)arg)->state, __ATOMIC_ACQUIRE) != 0; }
static V thread_wait(ThreadCell *c) {
    world_lock();
    world_wait(thread_done, c, c->pos);
    world_unlock();
    if (c->state == 2) {
        if (c->msg) fail_msg(c->pos, c->msg);
        fail(c->pos, "並行開始した動作はエラーで終わりました");
    }
    return c->result;
}


/* --- 通路: スレッドどうしで値を渡す列 ---
 * 「通路」の組(lib/スレッド.suru)の中身は Chan を指す番地。kind で中身の種類を分ける(今はプロセスの中の列だけ。
 * パイプなど別の種類は、同じ送る・受け取る・閉じるの口で足す) */
enum { CH_LOCAL = 0, CH_PIPE = 1 };
typedef struct {
    int64_t kind;
    int64_t rfd, wfd;    /* CH_PIPE: パイプの読む口と書く口(閉じたら -1、名前つきでまだ開いていなければ -2) */
    const char *path;    /* 名前つきの通路(FIFO)の道。無名のパイプなら NULL */
    int64_t cap;         /* 0 なら、受け取られるまで送る側が待つ */
    int64_t closed;
    int64_t head, n, size; /* 輪の列(size = 容量。0 なら 1) */
    int64_t sent, taken; /* 送った数・受け取った数 */
    V *buf;
} Chan;

/* lib/スレッド.suru の組(通路・ロック・枠・箱)。中身の欄は runtime のもの(GC の領域)を指す番地 */
static V mk_handle(const char *ctor, void *p, int32_t pos) {
    Ctor *c = find_ctor(ctor);
    if (!c) fail(pos, "「スレッド」を読み込んでいません");
    Rec *r = rt_alloc(sizeof(Rec) + sizeof(V));
    r->tag = T_REC;
    r->c = c;
    r->v[0] = rt_ffi_from_ptr(p);
    return (V)(intptr_t)r;
}
static void *need_handle(V v, const char *ctor, const char *what, int32_t pos) {
    if (TAG(v) != T_REC || strcmp(AS(Rec, v)->c->name, ctor) != 0 || TAG(AS(Rec, v)->v[0]) != T_ADDR)
        fail(pos, "%sは%sでなければなりません(「%s」が渡されました)", what, ctor, plain(v).s);
    return AS(Addr, AS(Rec, v)->v[0])->p;
}

static V chan_new(int64_t cap, int32_t pos) {
    Chan *ch = rt_alloc(sizeof(Chan));
    ch->kind = CH_LOCAL;
    ch->cap = cap;
    ch->size = cap > 0 ? cap : 1;
    ch->buf = rt_alloc(ch->size * sizeof(V));
    return mk_handle("通路", ch, pos);
}
static Chan *need_chan(V v, const char *what, int32_t pos) { return need_handle(v, "通路", what, pos); }
static int64_t ld(int64_t *p) { return __atomic_load_n(p, __ATOMIC_ACQUIRE); }
static int ch_can_send(void *a) { Chan *c = a; return ld(&c->closed) || (ld(&c->n) < c->size && (c->cap > 0 || ld(&c->n) == 0)); }
static int ch_can_recv(void *a) { Chan *c = a; return ld(&c->n) > 0 || ld(&c->closed); }
typedef struct { Chan *c; int64_t my; } SendWait;
static int ch_taken(void *a) { SendWait *w = a; return ld(&w->c->taken) >= w->my; }

/* --- パイプの通路: fork したプロセスどうしで値を渡す。値は直列化して、長さ(4 バイト)を前に付けて書く。
 * 1つのプロセスでは向きは1つ: 初めて送ったら読む口を、初めて受け取ったら書く口を閉じる
 * (書く口がすべて閉じると、受け取る側は「閉じた」と分かる) */
static V pipe_new(int32_t pos) {
    int fd[2];
    if (pipe(fd) != 0) fail(pos, "パイプを作れませんでした(%s)", strerror(errno));
    signal(SIGPIPE, SIG_IGN); /* 受け取る相手がいなくても止まらず、送信のエラーにする */
    Chan *ch = rt_alloc(sizeof(Chan));
    ch->kind = CH_PIPE;
    ch->rfd = fd[0];
    ch->wfd = fd[1];
    return mk_handle("通路", ch, pos);
}
/* 名前つきの通路: 関係ないプログラムどうしで、ファイルの道(FIFO)を通して値を渡す。
 * 開くのは初めて送る・受け取るとき(相手が開くまで待つ) */
static V fifo_chan(const char *path, int32_t pos) {
    signal(SIGPIPE, SIG_IGN);
    Chan *ch = rt_alloc(sizeof(Chan));
    ch->kind = CH_PIPE;
    ch->rfd = ch->wfd = -2;
    ch->path = strdup(path);
    return mk_handle("通路", ch, pos);
}
static V fifo_new(V p, int32_t pos) {
    Str *s = need_str(p, "「名前つき通路作成する」の「を」", pos);
    struct stat st;
    if (stat(s->s, &st) == 0) {
        if (!S_ISFIFO(st.st_mode)) fail(pos, "『%s』はすでにあり、名前つきの通路ではありません", s->s);
    } else if (mkfifo(s->s, 0600) != 0) {
        fail(pos, "名前つきの通路『%s』を作れませんでした(%s)", s->s, strerror(errno));
    }
    return fifo_chan(s->s, pos);
}
static V fifo_open(V p, int32_t pos) {
    Str *s = need_str(p, "「名前つき通路接続する」の「を」", pos);
    struct stat st;
    if (stat(s->s, &st) != 0) fail(pos, "名前つきの通路『%s』に接続できませんでした(%s)", s->s, strerror(errno));
    if (!S_ISFIFO(st.st_mode)) fail(pos, "『%s』は名前つきの通路ではありません", s->s);
    return fifo_chan(s->s, pos);
}
static V fifo_del(V p, int32_t pos) {
    Str *s = need_str(p, "「名前つき通路削除する」の「を」", pos);
    if (unlink(s->s) != 0) fail(pos, "名前つきの通路『%s』を消せませんでした(%s)", s->s, strerror(errno));
    return mk_int(0, pos);
}
/* まだ開いていない口(-2)を開く。もう一方の口は使わない(-1) */
static void fifo_open_end(Chan *c, int64_t *fd, int64_t *other, int flags, int32_t pos) {
    if (*other == -2) *other = -1;
    if (*fd != -2) return;
    world_release();
    int k;
    do k = open(c->path, flags); while (k < 0 && errno == EINTR);
    int e = errno;
    world_acquire();
    if (k < 0) fail(pos, "名前つきの通路『%s』を開けませんでした(%s)", c->path, strerror(e));
    *fd = k;
}
static void pipe_close_fd(int64_t *fd) {
    if (*fd >= 0) close((int)*fd);
    *fd = -1;
}
static V pipe_send(Chan *c, V x, int32_t pos) {
    if (c->closed || c->wfd == -1) fail(pos, "閉じた通路には送れません");
    if (c->path) fifo_open_end(c, &c->wfd, &c->rfd, O_WRONLY, pos);
    else pipe_close_fd(&c->rfd);
    Buf b = {0};
    buf_add(&b, "\0\0\0\0SURU\1", 9);
    ser_value(&b, x, 0, pos);
    uint32_t n = (uint32_t)(b.n - 4);
    for (int i = 0; i < 4; i++) b.s[i] = (char)((n >> (8 * i)) & 255);
    size_t off = 0;
    /* 名前つきなら書く人が何人もいるので、1つの値を書き終えるまでほかの人を待たせる */
    if (c->path) {
        world_release();
        while (flock((int)c->wfd, LOCK_EX) != 0 && errno == EINTR) {}
        world_acquire();
    }
    while (off < b.n) {
        world_release();
        ssize_t k = write((int)c->wfd, b.s + off, b.n - off);
        int e = errno;
        world_acquire();
        if (k < 0 && e == EINTR) continue;
        if (k < 0) {
            free(b.s);
            if (c->path) flock((int)c->wfd, LOCK_UN);
            if (e == EPIPE) fail(pos, "受け取る相手がいないので、通路に送れません");
            fail(pos, "通路に送れませんでした(%s)", strerror(e));
        }
        off += (size_t)k;
    }
    if (c->path) flock((int)c->wfd, LOCK_UN);
    free(b.s);
    return x;
}
/* n バイト読む。初めから終わり(EOF)なら 0、途中で終わったら -1 */
static int pipe_read_full(Chan *c, uint8_t *p, size_t n, int32_t pos) {
    size_t off = 0;
    while (off < n) {
        world_release();
        ssize_t k = read((int)c->rfd, p + off, n - off);
        int e = errno;
        world_acquire();
        if (k < 0 && e == EINTR) continue;
        if (k < 0) fail(pos, "通路から受け取れませんでした(%s)", strerror(e));
        if (k == 0) return off == 0 ? 0 : -1;
        off += (size_t)k;
    }
    return 1;
}
static V pipe_take(Chan *c, int32_t pos) {
    if (c->rfd == -1) fail(pos, "この通路から受け取れません(このプロセスはこの通路に送っています)");
    if (c->path) fifo_open_end(c, &c->rfd, &c->wfd, O_RDONLY, pos);
    else pipe_close_fd(&c->wfd);
    uint8_t h[4];
    int r = pipe_read_full(c, h, 4, pos);
    if (r == 0) return 0;
    if (r < 0) fail(pos, "通路の値が途中で切れています");
    uint32_t n = (uint32_t)h[0] | ((uint32_t)h[1] << 8) | ((uint32_t)h[2] << 16) | ((uint32_t)h[3] << 24);
    uint8_t *d = malloc(n ? n : 1);
    if (!d) fail(pos, "メモリが足りません");
    if (pipe_read_full(c, d, n, pos) != 1) {
        free(d);
        fail(pos, "通路の値が途中で切れています");
    }
    V v = deser_all(d, n, pos); /* 失敗したら d は残るが、壊れた通路なのでよしとする */
    free(d);
    return v;
}

static V chan_send(Chan *c, V x, int32_t pos) {
    if (c->kind == CH_PIPE) return pipe_send(c, x, pos);
    world_lock();
    if (!c->closed) world_wait(ch_can_send, c, pos);
    if (c->closed) {
        world_unlock();
        fail(pos, "閉じた通路には送れません");
    }
    c->buf[(c->head + c->n) % c->size] = x;
    __atomic_store_n(&c->n, c->n + 1, __ATOMIC_RELEASE);
    int64_t my = ++c->sent;
    world_changed();
    if (c->cap == 0) { /* 受け取られるまで待つ */
        SendWait w = {c, my};
        world_wait(ch_taken, &w, pos);
    }
    world_unlock();
    return x;
}
/* 値を1つ取り出す。閉じていて空なら 0 */
static V chan_take(Chan *c, int32_t pos) {
    if (c->kind == CH_PIPE) return pipe_take(c, pos);
    world_lock();
    world_wait(ch_can_recv, c, pos);
    if (c->n == 0) {
        world_unlock();
        return 0;
    }
    V x = c->buf[c->head];
    c->buf[c->head] = 0;
    c->head = (c->head + 1) % c->size;
    __atomic_store_n(&c->n, c->n - 1, __ATOMIC_RELEASE);
    __atomic_store_n(&c->taken, c->taken + 1, __ATOMIC_RELEASE);
    world_changed();
    world_unlock();
    return x;
}


/* --- ロックと枠: 持っている間だけ動作を行う。エラーで抜けても必ず手放す ---
 * ロックは同じスレッドなら重ねて持てる(数える)。枠は同時に n 個まで(プロセスの中のセマフォ) */
typedef struct { SThread *owner; int64_t depth; int64_t free; } Gate; /* ロックは owner/depth、枠は free(空きの数) */
typedef struct { Gate *g; SThread *me; } GateWait;
static int lock_ready(void *a) {
    GateWait *w = a;
    SThread *o = __atomic_load_n(&w->g->owner, __ATOMIC_ACQUIRE);
    return o == NULL || o == w->me;
}
static int slot_ready(void *a) { return ld(&((GateWait *)a)->g->free) > 0; }

/* 動作 m を行う。エラーなら leave してから同じエラーにする */
static V run_guarded(V m, void (*leave)(Gate *), Gate *g) {
    TryFrame f;
    f.prev = try_top;
    f.quiet = 1; /* 文は外の受け口で1回だけ書く */
    try_top = &f;
    if (setjmp(f.jb) == 0) {
        V r = perform(m);
        try_top = f.prev;
        leave(g);
        return r;
    }
    leave(g); /* fail_msg が try_top を戻している */
    char *msg = fail_last_msg;
    fail_last_msg = NULL;
    fail_msg(fail_last_pos, msg ? msg : "エラー");
}
static void lock_leave(Gate *g) {
    world_lock();
    if (--g->depth == 0) __atomic_store_n(&g->owner, NULL, __ATOMIC_RELEASE);
    world_changed();
    world_unlock();
}
static void slot_leave(Gate *g) {
    world_lock();
    __atomic_store_n(&g->free, g->free + 1, __ATOMIC_RELEASE);
    world_changed();
    world_unlock();
}
static void need_action(V v, const char *what, int32_t pos) {
    int t = TAG(v);
    if (t != T_ACT && t != T_PURE) fail(pos, "%sは動作でなければなりません(「%s」が渡されました)", what, plain(v).s);
}

/* --- 箱: スレッドどうしで共有する、書き換えられる値。読むのは待たない --- */
typedef struct { V v; } Box;

static long cpu_count(void) {
    long n = sysconf(_SC_NPROCESSORS_ONLN);
    return n < 1 ? 1 : n;
}

static V thread_run(Act *a) {
    switch (a->kind) {
    case A_SPAWN: {
        fflush(stdout); /* それまでの表示を先に出しておく */
        /* 結果は「スレッド」の組(lib/スレッド.suru)。動作の結果を動作にすると続けて行われてしまうので、組で包む */
        Ctor *ctor = find_ctor("スレッド");
        if (!ctor) fail(a->pos, "「スレッド」を読み込んでいません");
        ThreadCell *c = thread_start(thread_perform, a->a, 0, a->pos);
        V j = mk_act(A_JOIN, "合流する", (V)(intptr_t)c, 0);
        AS(Act, j)->pos = a->pos;
        Rec *r = rt_alloc(sizeof(Rec) + sizeof(V));
        r->tag = T_REC;
        r->c = ctor;
        r->v[0] = j;
        return (V)(intptr_t)r;
    }
    case A_JOIN: return thread_wait((ThreadCell *)(intptr_t)a->a);
    case A_NCPU: return mk_int(cpu_count(), a->pos);
    case A_CH_NEW: {
        V v = need_num(a->a, a->pos);
        int64_t cap = IS_INT(v) ? INT_VAL(v) : -1;
        if (cap < 0) fail(a->pos, "「%s」は通路の容量ではありません(0 以上の整数)", plain(v).s);
        return chan_new(cap, a->pos);
    }
    case A_CH_PIPE: return pipe_new(a->pos);
    case A_CH_FIFO_NEW: return fifo_new(a->a, a->pos);
    case A_CH_FIFO_OPEN: return fifo_open(a->a, a->pos);
    case A_CH_FIFO_DEL: return fifo_del(a->a, a->pos);
    case A_CH_SEND: return chan_send(need_chan(a->b, "「通路送信する」の「へ」", a->pos), a->a, a->pos);
    case A_CH_RECV: {
        V x = chan_take(need_chan(a->a, "「通路受信する」の「から」", a->pos), a->pos);
        if (!x) fail(a->pos, "通路は閉じていて、もう値がありません");
        return x;
    }
    case A_CH_CLOSE: {
        Chan *c = need_chan(a->a, "「通路閉鎖する」の「を」", a->pos);
        world_lock();
        if (c->kind == CH_PIPE) pipe_close_fd(&c->wfd);
        __atomic_store_n(&c->closed, 1, __ATOMIC_RELEASE);
        world_changed();
        world_unlock();
        return a->a;
    }
    case A_LOCK_NEW: return mk_handle("ロック", rt_alloc(sizeof(Gate)), a->pos);
    case A_LOCKED: {
        Gate *g = need_handle(a->a, "ロック", "「排他実行する」の「で」", a->pos);
        need_action(a->b, "「排他実行する」の「を」", a->pos);
        GateWait w = {g, self_thread};
        world_lock();
        world_wait(lock_ready, &w, a->pos);
        __atomic_store_n(&g->owner, self_thread, __ATOMIC_RELEASE);
        g->depth++;
        world_unlock();
        return run_guarded(a->b, lock_leave, g);
    }
    case A_SLOT_NEW: {
        V v = need_num(a->a, a->pos);
        int64_t n = IS_INT(v) ? INT_VAL(v) : 0;
        if (n < 1) fail(a->pos, "「%s」は枠の数ではありません(1 以上の整数)", plain(v).s);
        Gate *g = rt_alloc(sizeof(Gate));
        g->free = n;
        return mk_handle("枠", g, a->pos);
    }
    case A_SLOTTED: {
        Gate *g = need_handle(a->a, "枠", "「枠内実行する」の「で」", a->pos);
        need_action(a->b, "「枠内実行する」の「を」", a->pos);
        GateWait w = {g, self_thread};
        world_lock();
        world_wait(slot_ready, &w, a->pos);
        __atomic_store_n(&g->free, g->free - 1, __ATOMIC_RELEASE);
        world_unlock();
        return run_guarded(a->b, slot_leave, g);
    }
    case A_BOX_NEW: {
        Box *b = rt_alloc(sizeof(Box));
        b->v = a->a;
        return mk_handle("箱", b, a->pos);
    }
    case A_BOX_GET: return __atomic_load_n(&((Box *)need_handle(a->a, "箱", "「箱読取する」の「を」", a->pos))->v, __ATOMIC_ACQUIRE);
    case A_BOX_UPDATE: { /* 純粋な関数で計算して置きかえる。その間にほかのスレッドが変えていたら、新しい値でやり直す */
        Box *b = need_handle(a->a, "箱", "「箱更新する」の「を」", a->pos);
        V old = __atomic_load_n(&b->v, __ATOMIC_ACQUIRE);
        for (;;) {
            V x = apply1(a->b, old, a->pos);
            if (__atomic_compare_exchange_n(&b->v, &old, x, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return x;
        }
    }
    case A_BOX_SET:
        __atomic_store_n(&((Box *)need_handle(a->b, "箱", "「箱書込する」の「へ」", a->pos))->v, a->a, __ATOMIC_RELEASE);
        return a->a;
    case A_CH_EACH: { /* 閉じるまで、届いた値ごとに動作を行う。結果は行った数 */
        Chan *c = need_chan(a->a, "「通路処理する」の「を」", a->pos);
        int64_t k = 0;
        for (V x; (x = chan_take(c, a->pos)); k++) perform(apply1(a->b, x, a->pos));
        return mk_int(k, a->pos);
    }
    }
    return 0;
}

BI(t_spawn) { /* を */
    int t = TAG(a[0]);
    if (t != T_ACT && t != T_PURE) fail(pos, "「並行開始する」の「を」は動作でなければなりません(「%s」が渡されました)", plain(a[0]).s);
    return mk_act_pos(A_SPAWN, "並行開始する", a[0], 0, pos);
}
BI(t_join) { /* を: スレッドの組 → 合流する動作 */
    if (TAG(a[0]) != T_REC || strcmp(AS(Rec, a[0])->c->name, "スレッド") != 0)
        fail(pos, "「合流する」の「を」はスレッドでなければなりません(「%s」が渡されました)", plain(a[0]).s);
    return AS(Rec, a[0])->v[0];
}
BI(c_new) { return mk_act_pos(A_CH_NEW, "通路作成する", a[0], 0, pos); }    /* で */
BI(c_pipe) { return mk_act_pos(A_CH_PIPE, "プロセス間通路作成する", 0, 0, pos); }
BI(c_fifo_new) { return mk_act_pos(A_CH_FIFO_NEW, "名前つき通路作成する", a[0], 0, pos); }  /* を */
BI(c_fifo_open) { return mk_act_pos(A_CH_FIFO_OPEN, "名前つき通路接続する", a[0], 0, pos); } /* を */
BI(c_fifo_del) { return mk_act_pos(A_CH_FIFO_DEL, "名前つき通路削除する", a[0], 0, pos); }  /* を */
BI(c_send) { return mk_act_pos(A_CH_SEND, "通路送信する", a[0], a[1], pos); } /* を, へ */
BI(c_recv) { return mk_act_pos(A_CH_RECV, "通路受信する", a[0], 0, pos); }   /* から */
BI(c_close) { return mk_act_pos(A_CH_CLOSE, "通路閉鎖する", a[0], 0, pos); } /* を */
BI(c_each) { return mk_act_pos(A_CH_EACH, "通路処理する", a[0], a[1], pos); } /* を, で */
BI(l_new) { return mk_act_pos(A_LOCK_NEW, "ロック作成する", 0, 0, pos); }
BI(l_run) { return mk_act_pos(A_LOCKED, "排他実行する", a[0], a[1], pos); }   /* で, を */
BI(s_new) { return mk_act_pos(A_SLOT_NEW, "枠作成する", a[0], 0, pos); }    /* で */
BI(s_run) { return mk_act_pos(A_SLOTTED, "枠内実行する", a[0], a[1], pos); } /* で, を */
BI(x_new) { return mk_act_pos(A_BOX_NEW, "箱作成する", a[0], 0, pos); }     /* で */
BI(x_get) { return mk_act_pos(A_BOX_GET, "箱読取する", a[0], 0, pos); }     /* を */
BI(x_update) { return mk_act_pos(A_BOX_UPDATE, "箱更新する", a[0], a[1], pos); } /* を, で */
BI(x_set) { return mk_act_pos(A_BOX_SET, "箱書込する", a[0], a[1], pos); }  /* を, へ */
BI(t_ncpu) { return mk_act_pos(A_NCPU, "コア数取得する", 0, 0, pos); }
BI(t_pmap) { /* を, で */
    List *xs = need_list(a[0], "「並列写像する」の「を」", pos);
    if (xs->n == 0) return V_EMPTY;
    int64_t k = cpu_count();
    if (k > xs->n) k = xs->n;
    List *out = new_list(xs->n);
    MapTask **tasks = rt_alloc(k * sizeof(MapTask *));
    ThreadCell **cells = rt_alloc(k * sizeof(ThreadCell *));
    for (int64_t j = 0; j < k; j++) {
        MapTask *m = rt_alloc(sizeof(MapTask));
        m->f = a[1];
        m->xs = xs;
        m->out = out;
        m->lo = xs->n * j / k;
        m->hi = xs->n * (j + 1) / k;
        m->pos = pos;
        tasks[j] = m;
    }
    /* 1つ目はこのスレッドで、残りは新しいスレッドで */
    for (int64_t j = 1; j < k; j++) cells[j] = thread_start(thread_map, (V)(intptr_t)tasks[j], 1, pos);
    thread_map((V)(intptr_t)tasks[0]);
    for (int64_t j = 1; j < k; j++) thread_wait(cells[j]);
    return (V)(intptr_t)out;
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
    {"試行する", 2, P2_WO_DE, R_1_OPT, s_try},
    {"バイト列にする", 1, P1_WO, NULL, m_tobytes},
    {"バイト列組立する", 1, P1_WO, NULL, m_build},
    {"数列にする", 1, P1_WO, NULL, m_list},
    {"文字列にする", 1, P1_WO, NULL, m_tostr},
    {"バイト長にする", 1, P1_WO, NULL, m_len},
    {"番地にする", 1, P1_WO, NULL, m_addr},
    {"番地数値にする", 1, P1_WO, NULL, m_addrnum},
    {"直列化する", 1, P1_WO, NULL, m_serialize},
    {"復元する", 1, P1_WO, NULL, m_deserialize},
    {"固定直列化する", 2, P2_WO_DE, NULL, m_fixed_ser},
    {"固定復元する", 2, P2_WO_DE, NULL, m_fixed_de},
    {"バイト列取得する", 2, P2_KARA_WO, NULL, m_peek},
    {"書込する", 2, P2_WO_HE, NULL, m_poke},
    {"エラー番号取得する", 0, NULL, NULL, m_errno},
    {"失敗する", 1, P1_WO, NULL, m_fail},
    {"引数取得する", 0, NULL, NULL, m_args},
    {"終了する", 1, P1_WO, NULL, m_exit},
    /* 「基本」の組み込み */
    {"中断する", 1, P1_WO, NULL, m_abort},
    /* 「スレッド」の組み込み */
    {"並行開始する", 1, P1_WO, NULL, t_spawn},
    {"合流する", 1, P1_WO, NULL, t_join},
    {"並列写像する", 2, P2_WO_DE, NULL, t_pmap},
    {"コア数取得する", 0, NULL, NULL, t_ncpu},
    {"通路作成する", 1, P1_DE, NULL, c_new},
    {"プロセス間通路作成する", 0, NULL, NULL, c_pipe},
    {"名前つき通路作成する", 1, P1_WO, NULL, c_fifo_new},
    {"名前つき通路接続する", 1, P1_WO, NULL, c_fifo_open},
    {"名前つき通路削除する", 1, P1_WO, NULL, c_fifo_del},
    {"通路送信する", 2, P2_WO_HE, NULL, c_send},
    {"通路受信する", 1, P1_KARA, NULL, c_recv},
    {"通路閉鎖する", 1, P1_WO, NULL, c_close},
    {"通路処理する", 2, P2_WO_DE, NULL, c_each},
    {"ロック作成する", 0, NULL, NULL, l_new},
    {"排他実行する", 2, P2_DE_WO, NULL, l_run},
    {"枠作成する", 1, P1_DE, NULL, s_new},
    {"枠内実行する", 2, P2_DE_WO, NULL, s_run},
    {"箱作成する", 1, P1_DE, NULL, x_new},
    {"箱読取する", 1, P1_WO, NULL, x_get},
    {"箱更新する", 2, P2_WO_DE, NULL, x_update},
    {"箱書込する", 2, P2_WO_HE, NULL, x_set},
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
/* 外部の関数を呼ぶ前後: 呼んでいる間は外に出る(待つ関数の間も GC がこのスレッドを待たないように) */
void rt_ffi_pre(void) {
    world_release();
    errno = 0;
}
void rt_ffi_post(void) {
    ffi_errno = errno;
    world_acquire();
}

void *rt_ffi_ptr(V v, const char *fname, int32_t part, int32_t pos) {
    if (TAG(v) != T_ADDR) ffi_bad(v, fname, part, "番地", pos);
    return AS(Addr, v)->p;
}

/* 「外部の（f）」: 引数 f の番地にある関数を呼ぶ(NULL なら実行時エラー) */
void *rt_ffi_fnptr(V v, const char *fname, int32_t part, int32_t pos) {
    if (TAG(v) != T_ADDR || AS(Addr, v)->p == NULL) ffi_bad(v, fname, part, "関数の番地", pos);
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
    V v = __atomic_load_n(slot, __ATOMIC_RELAXED);
    if (!v) __atomic_store_n(slot, v = rt_global(name, pos), __ATOMIC_RELAXED);
    return v;
}

/* 一番外の式の値: 動作なら行い、そうでなければ表示する */
void rt_top(V v) {
    int t = TAG(v);
    if (t == T_ACT || t == T_PURE) { perform(v); return; }
    char *s = (char *)show(v);
    flockfile(stdout);
    fputs(s, stdout);
    fputc('\n', stdout);
    funlockfile(stdout);
    free(s);
}

/* 一番外の手順で「した 中身」を使うもの: 結果が失敗なら、その理由のエラーで終わる(Rust の main が Err を返したとき) */
void rt_top_unwrap(V v) {
    int t = TAG(v);
    V r = (t == T_ACT || t == T_PURE) ? perform(v) : v;
    if (TAG(r) == T_REC && !strcmp(AS(Rec, r)->c->type, "成否") && !strcmp(AS(Rec, r)->c->name, "失敗")) {
        V why = AS(Rec, r)->v[0];
        fail_msg(0, TAG(why) == T_STR ? AS(Str, why)->s : show(why));
    }
    if (t != T_ACT && t != T_PURE) rt_top(v);
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
    self_thread = &main_thread;
    main_thread.top = __builtin_frame_address(0); /* ここより上(呼び出した側)には値がない */
    gc_on = 1;
    const char *e = getenv("SURU_GC_MIN");
    if (e) gc_min = gc_next = (size_t)strtoull(e, NULL, 10) << 10;
    if (gc_min / 16 < gc_batch) gc_batch = gc_min / 16;
    gc_log = getenv("SURU_GC_LOG") != NULL;
    suru_main();
    fflush(stdout);
    return NULL;
}

int main(int argc, char **argv) {
    gc_init();
    pthread_cond_init(&main_thread.wcv, NULL);
    prog_argc = argc;
    prog_argv = argv;
    source_text = suru_source;
    init_builtins();
    pthread_atfork(world_atfork_prepare, world_atfork_parent, world_atfork_child);
    /* 深い再帰のために、大きなスタックのスレッドで動かす */
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, (size_t)1 << 30);
    pthread_t th;
    if (pthread_create(&th, &attr, run_main, NULL) != 0) run_main(NULL);
    else {
        /* 待っているだけのこのスレッドではシグナルを受けない。プロセスに送られたシグナルは
           プログラムを動かすスレッドに届くので、そこでの受付(sigprocmask)がそのまま効く */
        sigset_t all;
        sigfillset(&all);
        pthread_sigmask(SIG_BLOCK, &all, NULL);
        pthread_join(th, NULL);
    }
    return 0;
}
