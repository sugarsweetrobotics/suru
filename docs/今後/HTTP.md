# 今後の候補: HTTP

HTTP のサーバーは [suru-lang/http](https://github.com/suru-lang/http) に移しました。サーバーの候補(キャッシュの見出し、大きいファイルを分けて送るなど)は、そのリポジトリの README の「今後の候補」に書きます。ここには本体の側で要るものを書きます。

- HTTP.suru を変えたら `tests/http/HTTP.suru` の写しも同じにする(写しを取ってくる仕組みにするか)
- ファイルの更新時刻と大きさを取る(`stat`。Last-Modified・ETag に要る。構造体の並びが OS で違うので組み込みか C の小さな関数で)
