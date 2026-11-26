# Windows

計画: 1 実行時ライブラリ(済み) → 2 suruc・kumu・インタプリタ(済み) → 3 標準ライブラリ(済み) → 4 非標準ライブラリと GUI → 5 配布。道具は MSYS2 の clang(MinGW-w64、UCRT)。

- インタプリタ(suru.py)を Windows で動かすとき、標準ライブラリの POSIX の関数(uname・realpath など)を Python で用意する
- 「プロセス」の fork(分岐する・子実行する)を CreateProcess で作る
- System V のセマフォ(セマフォ・共有箱・読書ロック)を Windows の名前つきセマフォで、シグナルを SetConsoleCtrlHandler で作る
- 「プロセス」で、ほかのプログラムの出力の文字コード(cmd はコンソールのコードページ)を UTF-8 にそろえる
- 名前つきの通路を Windows の名前つきパイプで作る
- 呼び戻しの番地を Windows の呼び出し規約(rcx・rdx・r8・r9 と xmm0〜3、残りはスタック)の入口で受け取る
- CI に windows-latest(MSYS2)を足す
- http・sqlite・regex・gui-sdl3 の CI と導入案内に Windows(MSYS2 の pacman)を足す。gui-sdl3 の書体に `C:\Windows\Fonts` の游ゴシック・メイリオ
- Releases に Windows 用の suruc.exe・kumu.exe を置き、README の「WSL を使ってください」を書き換える
