// する のライブラリ(examples/export.suru)を Rust から呼ぶ例 / Call a Suru library from Rust
//
//   suruc --共有ライブラリ examples/export.suru -o libkeisan.so
//   KEISAN_LIB_DIR=$PWD cargo run
use std::ffi::{c_char, c_double, c_int, c_void, CStr, CString};
use std::io::Write;

// keisan.h と同じ宣言 / the same declarations as keisan.h
// 手札(keisan_value *)/ a handle
#[repr(C)]
struct KeisanValue {
    _private: [u8; 0],
}

extern "C" {
    fn keisan_last_error() -> *const c_char;
    fn keisan_free(p: *mut c_void);
    fn keisan_release(h: *mut KeisanValue);
    fn keisan_show(h: *const KeisanValue) -> *mut c_char;
    fn keisan_field(h: *const KeisanValue, name: *const c_char) -> *mut KeisanValue;
    fn keisan_to_int(h: *const KeisanValue) -> i64;
    fn nibai(a1: i64) -> i64;
    fn hikizan(a1: i64, a2: i64) -> i64;
    fn aisatsu(a1: *const c_char) -> *mut c_char;
    fn hanbun(a1: c_double) -> c_double;
    fn sei(a1: i64) -> c_int;
    fn goukei(a1: *const i64, a1_len: i64) -> i64;
    fn ten(a1: i64, a2: i64) -> *mut KeisanValue;
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

/// 手札を持ち、落とすときに手放す / owns a handle and releases it on drop
struct Value(*mut KeisanValue);

impl Value {
    fn new(p: *mut KeisanValue) -> Result<Value, String> {
        check(p).map(Value)
    }
    fn show(&self) -> Result<String, String> {
        let p = check(unsafe { keisan_show(self.0) })?;
        let s = unsafe { CStr::from_ptr(p) }.to_string_lossy().into_owned();
        unsafe { keisan_free(p as *mut c_void) };
        Ok(s)
    }
    fn field(&self, name: &str) -> Result<Value, String> {
        let name = CString::new(name).unwrap();
        Value::new(unsafe { keisan_field(self.0, name.as_ptr()) })
    }
    fn to_int(&self) -> Result<i64, String> {
        check(unsafe { keisan_to_int(self.0) })
    }
}

impl Drop for Value {
    fn drop(&mut self) {
        unsafe { keisan_release(self.0) }
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
    let xs: [i64; 4] = [1, 2, 3, 4];
    println!("goukei([1, 2, 3, 4]) = {}", check(unsafe { goukei(xs.as_ptr(), xs.len() as i64) })?);
    let p = Value::new(unsafe { ten(3, 4) })?;
    println!("ten(3, 4) = {}", p.show()?);
    println!("ten(3, 4).縦 = {}", p.field("縦")?.to_int()?);
    std::io::stdout().flush().unwrap();
    let msg = CString::new("記録します").unwrap();
    unsafe { kiroku(msg.as_ptr()) };
    let failed = check(unsafe { nibai(1 << 62) }).is_err();
    println!("nibai(2^62) = 0 error: {}", if failed { "yes" } else { "no" });
    Ok(())
}
