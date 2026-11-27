// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import "strings"

// WebTarget は「kumu 新規 名前 --対象 web」の対象。マイコンではなく、屋台(suru-lang/web)のウェブアプリの雛形を作る
const WebTarget = "web"

// webVersion は雛形の依存に書く屋台の版
const webVersion = "0.1.0"

// webDepNames は屋台とその依存の読み込みの名前(ウェブアプリの名前には使えない)
var webDepNames = []string{"屋台", "HTTP", "雛形", "台帳", "蔵"}

// webFiles は屋台のウェブアプリの雛形(道と処理は「名前.suru」に置き、本体と試験から読み込む)
func webFiles(name string) []struct{ name, body string } {
	r := strings.NewReplacer("@名前@", name)
	return []struct{ name, body string }{
		{ConfigName, "名前 とは 「" + name + "」\n版 とは 「0.1.0」\n入口 とは 「本体」\n依存 とは 「github.com/suru-lang/web@" + webVersion + "」\n"},
		{".gitignore", gitignoreTemplate},
		{r.Replace("@名前@.suru"), r.Replace(`# 道と処理です。頁は 画面/ のテンプレートで、画面/配置.html の枠に入ります
「屋台」 を 読み込んで 使う
「JSON」 を 読み込んで 使う

画面 とは （「画面」 を 画面設定する） に 「配置.html」 を 配置設定する

挨拶頁 とは 題 は 文字列 で 名前 は 文字列 の 組
挨拶頁 は 【JSON】 を 導出する

挨拶 とは 名前 は 文字列 で 言葉 は 文字列 の 組
挨拶 は 【JSON】 を 導出する

文脈 を トップ表示する は HTTP内の応答 の 動作
c を トップ表示する とは 「トップ.html」 を 頁 で 画面 に 画面返答する
ただし 頁 とは （題 は 「ようこそ」 で 名前 は （c を 名前取得する） の 挨拶頁） を 挨拶頁JSON化する

文脈 を 挨拶返答する は HTTP内の応答 の 動作
c を 挨拶返答する とは （名前 は （c を 名前取得する） で 言葉 は 「こんにちは」 の 挨拶） を 挨拶JSON化して JSON返答する

# 問いの「名前」(なければ「世界」)
文脈 を 名前取得する は 文字列
c を 名前取得する とは もし 名 = 「」 ならば 「世界」 そうでなければ 名
ただし 名 とは c から 「名前」 を 問い取得する

文脈 を 静的配信する は HTTP内の応答 の 動作
c を 静的配信する とは 「公開」 から 「/静的」 を c で 静的返答する

道群 とは 以下の【道】です
  GET  /            トップ表示する
  GET  /api/挨拶     挨拶返答する
  GET  /静的/*       静的配信する
以上です
`)},
		{r.Replace("本体.suru"), r.Replace(`# ウェブアプリの入口です。kumu 実行 で動かし、http://localhost:8080/ を開きます
「屋台」 を 読み込んで 使う
「@名前@」 を 読み込んで 使う

8080 を （道群 を 記録中継すること で 中継付けする） で 屋台開店する
`)},
		{r.Replace("画面/配置.html"), r.Replace(`<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>{{ 題 }}</title>
<link rel="stylesheet" href="/静的/見た目.css">
</head>
<body>
{{ 中身 を 生にする }}
</body>
</html>
`)},
		{r.Replace("画面/トップ.html"), r.Replace(`<h1>こんにちは、{{ 名前 }}さん</h1>
<form method="get" action="/">
<label>お名前 <input name="名前"></label>
<button>あいさつする</button>
</form>
`)},
		{r.Replace("公開/見た目.css"), r.Replace(`body { font-family: sans-serif; max-width: 40em; margin: 2em auto; }
`)},
		{r.Replace("試験/道.suru"), r.Replace(`# 道の試験です。サーバーは立てずに、要求を作って振り分けます。kumu 試験 で動かします
「試験」 を 読み込んで 使う
「屋台」 を 読み込んで 使う
「HTTP」 を 読み込む
「@名前@」 を 読み込んで 使う

文字列 を 取得する は HTTP内の応答 の 動作
道 を 取得する とは 道群 で （「GET」 と 道 と 空 と 「」 の HTTP内の要求） を 振分する

トップ試験する は 真偽 の 動作
トップ試験する とは 以下の手順です
  r とは 「/?名前=%E8%8A%B1%E5%AD%90」 を 取得した 結果
  r の 状態 を 200 に 一致確認する
  （（r の 本文 を 文字列にする） が 「こんにちは、花子さん」 を 含有である） を 確認する
  以上です

挨拶試験する は 真偽 の 動作
挨拶試験する とは 以下の手順です
  r とは 「/api/挨拶」 を 取得した 結果
  （r の 本文 を 文字列にする） を 「{"名前":"世界","言葉":"こんにちは"}」 に 一致確認する
  以上です

見つからない試験する は 真偽 の 動作
見つからない試験する とは 以下の手順です
  r とは 「/ない」 を 取得した 結果
  r の 状態 を 404 に 一致確認する
  以上です
`)},
	}
}
