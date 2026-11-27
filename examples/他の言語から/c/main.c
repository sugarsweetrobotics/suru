/* する のライブラリ(examples/export.suru)を C から呼ぶ例 / Call a Suru library from C
 *
 *   suruc --共有ライブラリ examples/export.suru -o libkeisan.so   (keisan.h もできる / also writes keisan.h)
 *   cc main.c -I. -L. -lkeisan -Wl,-rpath,'$ORIGIN' -o main && ./main
 */
#include <inttypes.h>
#include <stdio.h>

#include "keisan.h"

int main(void) {
    printf("nibai(21) = %" PRId64 "\n", nibai(21));
    printf("hikizan(3, 10) = %" PRId64 "\n", hikizan(3, 10));
    char *s = aisatsu("世界");
    printf("aisatsu = %s\n", s);
    keisan_free(s); /* 返った文字列は呼んだ側が解放する / the caller frees returned strings */
    printf("hanbun(5) = %g\n", hanbun(5.0));
    printf("sei(-1) = %d\n", sei(-1));
    int64_t xs[] = {1, 2, 3, 4}; /* 数 の リスト は番地と長さ / a pointer and a length */
    printf("goukei([1, 2, 3, 4]) = %" PRId64 "\n", goukei(xs, 4));
    keisan_value *p = ten(3, 4); /* 点 は手札 / a handle */
    char *shown = keisan_show(p);
    printf("ten(3, 4) = %s\n", shown);
    keisan_free(shown);
    keisan_value *y = keisan_field(p, "縦");
    printf("ten(3, 4).縦 = %" PRId64 "\n", keisan_to_int(y));
    keisan_release(y); /* 手札は keisan_release で手放す / release handles */
    keisan_release(p);
    fflush(stdout);
    kiroku("記録します");

    /* 失敗すると 0 を返し、keisan_last_error に文が入る / a failed call returns 0 and sets keisan_last_error */
    int64_t r = nibai(INT64_C(1) << 62);
    printf("nibai(2^62) = %" PRId64 " error: %s\n", r, keisan_last_error() ? "yes" : "no");
    return 0;
}
