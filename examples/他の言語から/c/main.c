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
    fflush(stdout);
    kiroku("記録します");

    /* 失敗すると 0 を返し、keisan_last_error に文が入る / a failed call returns 0 and sets keisan_last_error */
    int64_t r = nibai(INT64_C(1) << 62);
    printf("nibai(2^62) = %" PRId64 " error: %s\n", r, keisan_last_error() ? "yes" : "no");
    return 0;
}
