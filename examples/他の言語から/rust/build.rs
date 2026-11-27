// libkeisan.so のある所(KEISAN_LIB_DIR、なければ 1つ上)をリンクに使う
// Link against libkeisan in KEISAN_LIB_DIR (default: the parent directory)
fn main() {
    let dir = std::env::var("KEISAN_LIB_DIR").unwrap_or_else(|_| {
        let here = std::env::var("CARGO_MANIFEST_DIR").unwrap();
        format!("{here}/..")
    });
    println!("cargo:rerun-if-env-changed=KEISAN_LIB_DIR");
    println!("cargo:rustc-link-search=native={dir}");
    println!("cargo:rustc-link-lib=dylib=keisan");
    println!("cargo:rustc-link-arg=-Wl,-rpath,{dir}");
}
