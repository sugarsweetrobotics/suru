// する のライブラリ(examples/export.suru)を Go(cgo)から呼ぶ例 / Call a Suru library from Go (cgo)
//
//	suruc --共有ライブラリ examples/export.suru -o libkeisan.so
//	CGO_CFLAGS=-I$PWD CGO_LDFLAGS="-L$PWD -lkeisan -Wl,-rpath,$PWD" go run .
package main

/*
#include <stdlib.h>
#include "keisan.h"
*/
import "C"

import (
	"errors"
	"fmt"
	"os"
	"runtime"
	"unsafe"
)

// lastError はこのスレッドで最後に呼んだ関数のエラー / the error of the last call on this thread
func lastError() error {
	if e := C.keisan_last_error(); e != nil {
		return errors.New(C.GoString(e))
	}
	return nil
}

func aisatsu(name string) string {
	cs := C.CString(name)
	defer C.free(unsafe.Pointer(cs))
	p := C.aisatsu(cs)
	defer C.keisan_free(unsafe.Pointer(p)) // 返った文字列は呼んだ側が解放する / the caller frees it
	return C.GoString(p)
}

func main() {
	// エラーはスレッドごとなので、呼び出しと keisan_last_error を同じ OS のスレッドで行う
	// (the error is per thread, so keep this goroutine on one OS thread)
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()

	fmt.Println("nibai(21) =", int64(C.nibai(21)))
	fmt.Println("hikizan(3, 10) =", int64(C.hikizan(3, 10)))
	fmt.Println("aisatsu =", aisatsu("世界"))
	fmt.Println("hanbun(5) =", float64(C.hanbun(5)))
	fmt.Println("sei(-1) =", int(C.sei(-1)))
	xs := []C.int64_t{1, 2, 3, 4} // 数 の リスト は番地と長さ / a pointer and a length
	fmt.Println("goukei([1, 2, 3, 4]) =", int64(C.goukei(&xs[0], C.int64_t(len(xs)))))
	p := C.ten(3, 4) // 点 は手札 / a handle
	shown := C.keisan_show(p)
	fmt.Println("ten(3, 4) =", C.GoString(shown))
	C.keisan_free(unsafe.Pointer(shown))
	field := C.CString("縦")
	y := C.keisan_field(p, field)
	C.free(unsafe.Pointer(field))
	fmt.Println("ten(3, 4).縦 =", int64(C.keisan_to_int(y)))
	C.keisan_release(y) // 手札は keisan_release で手放す / release handles
	C.keisan_release(p)
	os.Stdout.Sync()
	msg := C.CString("記録します")
	C.kiroku(msg)
	C.free(unsafe.Pointer(msg))

	// 失敗すると 0 を返し、keisan_last_error に文が入る / a failed call returns 0 and sets keisan_last_error
	r := C.nibai(1 << 62)
	yes := "no"
	if lastError() != nil {
		yes = "yes"
	}
	fmt.Println("nibai(2^62) =", int64(r), "error:", yes)
}
