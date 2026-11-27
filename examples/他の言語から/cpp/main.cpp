// する のライブラリ(examples/export.suru)を C++ から呼ぶ例 / Call a Suru library from C++
//
//   suruc --共有ライブラリ examples/export.suru -o libkeisan.so
//   c++ -std=c++17 main.cpp -I. -L. -lkeisan -Wl,-rpath,'$ORIGIN' -o main && ./main
#include <cstdio>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

#include "keisan.h"  // extern "C" が付いている / already wrapped in extern "C"

// 失敗を例外にする / turn a failed call into an exception
template <typename T>
T check(T value) {
    if (const char *e = keisan_last_error()) throw std::runtime_error(e);
    return value;
}

// 返った文字列は keisan_free で解放する / free returned strings with keisan_free
std::string greet(const std::string &name) {
    std::unique_ptr<char, void (*)(void *)> p(aisatsu(name.c_str()), keisan_free);
    check(p.get());
    return p.get();
}

int main() {
    std::cout << "nibai(21) = " << check(nibai(21)) << "\n";
    std::cout << "hikizan(3, 10) = " << check(hikizan(3, 10)) << "\n";
    std::cout << "aisatsu = " << greet("世界") << "\n";
    std::cout << "hanbun(5) = " << check(hanbun(5.0)) << "\n";
    std::cout << "sei(-1) = " << check(sei(-1)) << std::endl;
    kiroku("記録します");
    try {
        check(nibai(int64_t(1) << 62));
        std::cout << "nibai(2^62) = 0 error: no\n";
    } catch (const std::runtime_error &) {
        std::cout << "nibai(2^62) = 0 error: yes\n";
    }
    return 0;
}
