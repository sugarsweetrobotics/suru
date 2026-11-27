// する のライブラリ(examples/export.suru)を Rust から呼ぶ例 / Call a Suru library from Rust
//
//   suruc --共有ライブラリ examples/export.suru -o libkeisan.so
//   KEISAN_LIB_DIR=$PWD cargo run
use std::ffi::{c_char, c_double, c_int, c_void, CStr, CString};
use std::io::Write;

// keisan.h と同じ宣言 / the same declarations as keisan.h
extern "C" {
    fn keisan_last_error() -> *const c_char;
    fn keisan_free(p: *mut c_void);
    fn nibai(a1: i64) -> i64;
    fn hikizan(a1: i64, a2: i64) -> i64;
    fn aisatsu(a1: *const c_char) -> *mut c_char;
    fn hanbun(a1: c_double) -> c_double;
    fn sei(a1: i64) -> c_int;
    fn kiroku(a1: *const c_char);
}

/// 失敗を Err にする / turn a failed call into Err
fn check<T>(value: T) -> Result<T, String> {
    let e = unsafe { keisan_last_error() };
    if e.is_null() {
        Ok(value)
    } else {
        Err(unsafe { CStr::from_ptr(e) }.to_string_lossy().into_owned())
    }
}

fn greet(name: &str) -> Result<String, String> {
    let name = CString::new(name).unwrap();
    let p = check(unsafe { aisatsu(name.as_ptr()) })?;
    let s = unsafe { CStr::from_ptr(p) }.to_string_lossy().into_owned();
    unsafe { keisan_free(p as *mut c_void) }; // 返った文字列は呼んだ側が解放する / the caller frees it
    Ok(s)
}

fn main() -> Result<(), String> {
    println!("nibai(21) = {}", check(unsafe { nibai(21) })?);
    println!("hikizan(3, 10) = {}", check(unsafe { hikizan(3, 10) })?);
    println!("aisatsu = {}", greet("世界")?);
    println!("hanbun(5) = {}", check(unsafe { hanbun(5.0) })?);
    println!("sei(-1) = {}", check(unsafe { sei(-1) })?);
    std::io::stdout().flush().unwrap();
    let msg = CString::new("記録します").unwrap();
    unsafe { kiroku(msg.as_ptr()) };
    let failed = check(unsafe { nibai(1 << 62) }).is_err();
    println!("nibai(2^62) = 0 error: {}", if failed { "yes" } else { "no" });
    Ok(())
}
