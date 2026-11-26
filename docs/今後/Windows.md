# Windows

計画: 1 実行時ライブラリ(済み) → 2 suruc・kumu・インタプリタ → 3 標準ライブラリ → 4 非標準ライブラリと GUI → 5 配布。道具は MSYS2 の clang(MinGW-w64、UCRT)。

- suruc・`suru --翻訳`・kumu が Windows で .exe を作る(`-lpthread -lws2_32`、`.exe` を付ける、UTF-8 を使う印(マニフェストの activeCodePage)を windres で埋め込む)
- インタプリタ(suru.py)の `fcntl.flock` を Windows では `msvcrt.locking` に、外部のライブラリは `名前.dll` を探す
- 標準ライブラリのファイル・時間・環境・乱数・動的リンク・プロセス・共有メモリを、実行時ライブラリの `rt_os_…` 経由にする
- System V のセマフォ(セマフォ・共有箱・読書ロック)とシグナルは、最初は「Windows では使えません」のエラーにする
- 名前つきの通路を Windows の名前つきパイプで作る
- 呼び戻しの番地を Windows の呼び出し規約(rcx・rdx・r8・r9 と xmm0〜3、残りはスタック)の入口で受け取る
- CI に windows-latest(MSYS2)を足す
- http・sqlite・regex・gui-sdl3 の CI と導入案内に Windows(MSYS2 の pacman)を足す。gui-sdl3 の書体に `C:\Windows\Fonts` の游ゴシック・メイリオ
- Releases に Windows 用の suruc.exe・kumu.exe を置き、README の「WSL を使ってください」を書き換える
