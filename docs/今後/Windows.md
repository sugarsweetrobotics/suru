# Windows

計画: 1 実行時ライブラリ → 2 suruc・kumu・インタプリタ → 3 標準ライブラリ → 4 非標準ライブラリと GUI → 5 配布(すべて済み)。道具は MSYS2 の clang(MinGW-w64、UCRT)。

- インタプリタ(suru.py)を Windows で動かすとき、標準ライブラリの POSIX の関数(uname・realpath など)を Python で用意する
- 「プロセス」の fork(分岐する・子実行する)を CreateProcess で作る
- System V のセマフォ(セマフォ・共有箱・読書ロック)を Windows の名前つきセマフォで、シグナルを SetConsoleCtrlHandler で作る
- 「プロセス」で、ほかのプログラムの出力の文字コード(cmd はコンソールのコードページ)を UTF-8 にそろえる
- 名前つきの通路を Windows の名前つきパイプで作る
- 呼び戻しの番地を Windows の呼び出し規約(rcx・rdx・r8・r9 と xmm0〜3、残りはスタック)の入口で受け取る
- CI に windows-latest(MSYS2)を足す
- Windows の配布物を MSYS2 なしでも使えるようにする(clang・lld を同梱するか、winget・Scoop で入れる)
