// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

// VS Code 拡張から kumu(プロジェクト管理)を使うための、vscode に頼らない部分(テストのため分けている)。

const fs = require("fs");
const os = require("os");
const path = require("path");

const CONFIG = "組.suru";
const TEST_DIR = "試験";

/** file のフォルダから上へ 組.suru を探し、あればそのフォルダ(なければ undefined) */
function findProjectRoot(file) {
  let dir = path.dirname(path.resolve(file));
  for (;;) {
    if (fs.existsSync(path.join(dir, CONFIG))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) return undefined;
    dir = parent;
  }
}

/** file がプロジェクトの 試験/ の下のファイルか */
function isTestFile(root, file) {
  const rel = path.relative(path.join(root, TEST_DIR), path.resolve(file));
  return rel !== "" && !rel.startsWith("..") && !path.isAbsolute(rel);
}

/**
 * 一番外の「…試験する とは」の定義(kumu 試験 が動かすもの)を、[{ name, line }] で返す(line は 0 から)。
 * 空白の書き方(`二倍試験する とは`)と句読点の書き方(`二倍試験するとは、`)の両方
 */
function testDefinitions(text) {
  const out = [];
  const seen = new Set();
  const lines = text.split(/\r?\n/);
  lines.forEach((line, i) => {
    const m = /^([^\s#「」『』（）()、。]+?試験する)[ 　]*とは(?:[ 　、]|$)/.exec(line);
    if (m && !seen.has(m[1])) {
      seen.add(m[1]);
      out.push({ name: m[1], line: i });
    }
  });
  return out;
}

/** kumu の場所(設定、PATH、~/go/bin の順)。見つからなければ "kumu"(ターミナルに任せる) */
function findKumu(configured) {
  configured = (configured || "").trim();
  if (configured) return configured;
  const exe = process.platform === "win32" ? ".exe" : "";
  const candidates = [];
  for (const dir of (process.env.PATH || "").split(path.delimiter)) {
    if (dir) candidates.push(path.join(dir, `kumu${exe}`));
  }
  const gopath = process.env.GOPATH || path.join(os.homedir(), "go");
  candidates.push(path.join(gopath, "bin", `kumu${exe}`));
  const found = candidates.find((p) => {
    try {
      return fs.statSync(p).isFile();
    } catch {
      return false;
    }
  });
  return found || "kumu";
}

module.exports = { findProjectRoot, isTestFile, testDefinitions, findKumu, CONFIG, TEST_DIR };
