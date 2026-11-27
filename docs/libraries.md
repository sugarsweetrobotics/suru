# Official libraries

[日本語](https://github.com/suru-lang/suru/blob/main/docs/公式ライブラリ.md)

Besides the standard library (`lib/`, loaded with `「名前」 を 読み込む`), the suru-lang organization keeps small libraries in their own repositories. They are not part of the standard library: add one to a [kumu](https://github.com/suru-lang/suru/blob/main/README.md#building-projects-kumu) project with `kumu 追加`, then load it by its name.

```sh
kumu 追加 github.com/suru-lang/db
kumu 追加 github.com/suru-lang/sqlite
```

```suru
「蔵」 を 読み込んで 使う
「SQLite」 を 読み込んで 使う

主処理する とは 以下の手順です
  db とは 「店.db」 を SQLite駆動 で DB開封した 結果
  db に 「CREATE TABLE IF NOT EXISTS 品 (名前 TEXT, 値段 REAL)」 を DB実行する
  db を DB閉鎖する
  「以上です」 を 表示する
  以上です

主処理する
```

kumu fetches the dependencies of a library too (for example, `github.com/suru-lang/orm` brings 「蔵」 along). Libraries that call a C library need it installed on the system; kumu checks the `外部依存` in each library's `組.suru` and tells you how to install it if it is missing. Each library's README has the details, and most have API pages on Read the Docs made from their comments.

## Libraries

"Suru" is the oldest version of Suru each library's README asks for. All of them are tested with the latest release.

| Repository | Load with | What it does | Suru | API |
| --- | --- | --- | --- | --- |
| [http](https://github.com/suru-lang/http) | `「HTTP」` `「HTTP/クライアント」` | HTTP server (static files, parallel answering, WebSocket) and HTTP/HTTPS client | 0.9.1 | [docs](https://http.readthedocs.io/en/latest/) |
| [template](https://github.com/suru-lang/template) | `「雛形」` | Jinja2-like template engine (loops, conditions, filters, inheritance, auto-escaping) | — | [docs](https://suru-lang-template.readthedocs.io/en/latest/) |
| [db](https://github.com/suru-lang/db) | `「蔵」` | thin database layer: connect, execute, fetch rows, transactions; the driver decides the database | — | [docs](https://suru-lang-db.readthedocs.io/en/latest/) |
| [sqlite](https://github.com/suru-lang/sqlite) | `「SQLite」` | SQLite (libsqlite3), on its own or as the 蔵 driver `SQLite駆動` | 0.9.1 | [docs](https://suru-lang-sqlite.readthedocs.io/en/latest/) |
| [postgresql](https://github.com/suru-lang/postgresql) | `「PostgreSQL」` | PostgreSQL driver for 蔵 (libpq), `PostgreSQL駆動` | 0.9.1 | [docs](https://suru-lang-postgresql.readthedocs.io/en/latest/) |
| [mysql](https://github.com/suru-lang/mysql) | `「MySQL」` | MySQL driver for 蔵 (libmysqlclient), `MySQL駆動` | 0.9.1 | [docs](https://suru-lang-mysql.readthedocs.io/en/latest/) |
| [orm](https://github.com/suru-lang/orm) | `「台帳」` | O/R mapper on 蔵: save and find records, conditions as values, one-to-many, tables derived with 【表】 | 0.10.0 | [docs](https://orm.readthedocs.io/en/latest/) |
| [regex](https://github.com/suru-lang/regex) | `「正規表現」` | PCRE2 regular expressions: search, search all, replace, split | 0.9.1 | [docs](https://suru-lang-regex.readthedocs.io/en/latest/) |
| [gui-sdl3](https://github.com/suru-lang/gui-sdl3) | `「画面」` | windows, shapes and Japanese text with SDL3, and Elm-like widgets | 0.9.1 | [docs](https://gui-sdl3.readthedocs.io/en/latest/) |
| [python](https://github.com/suru-lang/python) | `「Python」` | runs Python code and scripts in the same process (embedded libpython) and gets values back | 0.9.1 | [README](https://github.com/suru-lang/python/blob/main/README.md) |

"—" means the README asks for no particular version. 「蔵」, 「台帳」 and the drivers fit together: the same program runs on SQLite, PostgreSQL or MySQL by changing the driver. The same list is on the [website](https://suru-lang.github.io/libraries.html).

## Web framework 屋台

[suru-lang/web](https://github.com/suru-lang/web) (`「屋台」`, Suru 0.11.0 or later) is bigger than the libraries above: it puts http, 雛形 and 台帳 together into a web framework. List the routes one per line with 【道】, write a handler for each, and the server runs in the interpreter and as a compiled binary. Sessions, forms, cookies, middleware and route tests without a server are included. API: [docs](https://suru-lang-web.readthedocs.io/en/latest/).

`kumu 新規 店 --対象 web` creates a web app with routes, templates, static files and tests in place:

```suru
「屋台」 を 読み込んで 使う
「標準」 を 読み込んで 使う

文脈 を 品表示する は HTTP内の応答 を 返す 入出力動作
c を 品表示する とは 「品 」 + （c から 「番号」 を 道引数取得する） + 「 です」 を 文字返答する

道群 とは 以下の【道】です
  GET  /品/:番号    品表示する
以上です

8080 を 道群 で 屋台開店する
```

## ROS 2

[rclsuru](https://github.com/suru-lang/rclsuru) is a ROS 2 client library for Suru (`「rclsuru」`). Start with the [short tutorial](https://suru-lang.github.io/rclsuru.html) on the website; its README and [API docs](https://rclsuru.readthedocs.io/en/latest/) describe the rest.

## Tools written in Suru

| Repository | What it is | Suru |
| --- | --- | --- |
| [surl](https://github.com/suru-lang/surl) | a curl-like command for HTTP and HTTPS, built on http; install with `kumu 導入` | 0.12.0 |
| [ohanashi-ollama](https://github.com/suru-lang/ohanashi-ollama) | a web app for chatting with local LLMs through Ollama | see its README |

## Making your own

Any Git repository with a `組.suru` and a tag can be added with `kumu 追加`; there is no central registry. See [Publishing a library](publishing-a-library.md).
