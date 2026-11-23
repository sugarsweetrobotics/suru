// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

// VS Code 拡張「する」: 言語サーバー(suru-ls)の起動、実行・型の検査・バイナリ作り、kumu の命令。
// 色分けは syntaxes/ の文法が行う。言語サーバーが見つからなければ、保存したときに suru --検査 で調べる。

const vscode = require("vscode");
const cp = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const kumu = require("./kumu");

const LANG = "suru";
let diagnostics;
let output;
let terminal;
let client; // 言語サーバーにつないでいるとき

/** 設定とワークスペースから「する」を動かすコマンドを決める(先頭がプログラム、残りが引数) */
function suruCommand(doc) {
  const conf = vscode.workspace.getConfiguration("suru", doc && doc.uri);
  const configured = (conf.get("command") || "").trim();
  if (configured) {
    return splitCommand(configured);
  }
  const folders = [];
  const own = doc && vscode.workspace.getWorkspaceFolder(doc.uri);
  if (own) folders.push(own);
  for (const f of vscode.workspace.workspaceFolders || []) {
    if (f !== own) folders.push(f);
  }
  for (const f of folders) {
    const script = path.join(f.uri.fsPath, "suru.py");
    if (fs.existsSync(script)) {
      const python = (conf.get("python") || "").trim() || (process.platform === "win32" ? "python" : "python3");
      return [python, script];
    }
  }
  return ["suru"];
}

/** 「python3 "C:\a b\suru.py"」のような設定を空白で分ける(引用符で囲んだところは分けない) */
function splitCommand(text) {
  const parts = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    parts.push(m[1] !== undefined ? m[1] : m[2] !== undefined ? m[2] : m[3]);
  }
  return parts;
}

function quote(arg) {
  if (/^[\w./:\\-]+$/.test(arg)) return arg;
  if (process.platform === "win32") return `"${arg.replace(/"/g, '""')}"`;
  return `'${arg.replace(/'/g, `'\\''`)}'`;
}

function activeSuruDocument() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== LANG) {
    vscode.window.showWarningMessage("「する」のファイル(.suru)を開いてから使ってください");
    return undefined;
  }
  return editor.document;
}

async function saved(doc) {
  if (doc.isUntitled) {
    vscode.window.showWarningMessage("先にファイルを保存してください");
    return false;
  }
  if (doc.isDirty) {
    return doc.save();
  }
  return true;
}

/** ターミナルで動かす(入力する を使うプログラムのため、ターミナルで受け答えできるようにする) */
function runInTerminal(doc, extraArgs) {
  if (!terminal || terminal.exitStatus !== undefined) {
    terminal = vscode.window.createTerminal({ name: "する", env: { PYTHONUTF8: "1" } });
  }
  const cmd = suruCommand(doc);
  const args = [...cmd, ...extraArgs, doc.uri.fsPath].map(quote);
  terminal.show(true);
  terminal.sendText(`cd ${quote(path.dirname(doc.uri.fsPath))}`);
  // PowerShell では引用符で囲んだプログラム名の前に & が要る
  const prefix = process.platform === "win32" && /^["']/.test(args[0]) ? "& " : "";
  terminal.sendText(prefix + args.join(" "));
}

/** 開いているファイルのプロジェクト(組.suru のあるフォルダ)。なければ知らせて undefined */
function projectRoot(doc) {
  const root = kumu.findProjectRoot(doc.uri.fsPath);
  if (!root) {
    vscode.window.showWarningMessage("組.suru が見つかりません(kumu 新規 名前 でプロジェクトを作ります)");
  }
  return root;
}

/** プロジェクトのフォルダで kumu を動かす */
function runKumu(doc, args) {
  const root = projectRoot(doc);
  if (!root) return;
  if (!terminal || terminal.exitStatus !== undefined) {
    terminal = vscode.window.createTerminal({ name: "する", env: { PYTHONUTF8: "1" } });
  }
  const conf = vscode.workspace.getConfiguration("suru", doc.uri);
  const cmd = [...splitCommand(kumu.findKumu(conf.get("kumu"))), ...args].map(quote);
  terminal.show(true);
  terminal.sendText(`cd ${quote(root)}`);
  const prefix = process.platform === "win32" && /^["']/.test(cmd[0]) ? "& " : "";
  terminal.sendText(prefix + cmd.join(" "));
}

/** 開いているファイルを保存して、そのプロジェクトで kumu を動かす */
async function kumuOnActive(args) {
  const doc = activeSuruDocument();
  if (doc && (await saved(doc))) runKumu(doc, args);
}

/** 試験/ のファイルの「…試験する」の上に「▷ 試験する」を出す */
const testLenses = {
  provideCodeLenses(doc) {
    const root = kumu.findProjectRoot(doc.uri.fsPath);
    if (!root || !kumu.isTestFile(root, doc.uri.fsPath)) return [];
    return kumu.testDefinitions(doc.getText()).map(
      (t) =>
        new vscode.CodeLens(new vscode.Range(t.line, 0, t.line, 0), {
          title: "▷ 試験する",
          command: "suru.kumuTestOne",
          arguments: [doc.uri, t.name],
        }),
    );
  },
};

/**
 * suru --検査 の出力からエラーを取り出す。
 * 形は「エラー: 2行目 5文字目: メッセージ」(位置がないこともある)
 */
function parseErrors(text) {
  const errors = [];
  for (const line of text.split(/\r?\n/)) {
    const m = /^エラー: (?:(\d+)行目(?: (\d+)文字目)?: )?(.*)$/.exec(line);
    if (m) {
      errors.push({
        line: m[1] ? Number(m[1]) : 1,
        col: m[2] ? Number(m[2]) : undefined,
        message: m[3],
      });
    }
  }
  return errors;
}

/** エラーの位置から、その単語の終わりまでを範囲にする */
function errorRange(doc, err) {
  const lineNo = Math.min(Math.max(err.line - 1, 0), doc.lineCount - 1);
  const text = doc.lineAt(lineNo).text;
  if (err.col === undefined) {
    const start = text.length - text.trimStart().length;
    return new vscode.Range(lineNo, start, lineNo, Math.max(text.length, start + 1));
  }
  // 文字目は文字の数で数えているので、UTF-16 の位置に直す
  const chars = Array.from(text);
  const before = chars.slice(0, err.col - 1).join("").length;
  let end = err.col - 1;
  while (end < chars.length && !/[\s　、。（）()]/.test(chars[end])) end++;
  const after = chars.slice(0, Math.max(end, err.col)).join("").length;
  return new vscode.Range(lineNo, before, lineNo, Math.max(after, before + 1));
}

function check(doc, { quiet } = { quiet: false }) {
  if (doc.languageId !== LANG || doc.isUntitled || doc.uri.scheme !== "file") return Promise.resolve();
  const [program, ...args] = suruCommand(doc);
  return new Promise((resolve) => {
    cp.execFile(
      program,
      [...args, "--検査", doc.uri.fsPath],
      {
        cwd: path.dirname(doc.uri.fsPath),
        env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
        timeout: 30000,
        windowsHide: true,
      },
      (error, stdout, stderr) => {
        const text = `${stdout}\n${stderr}`;
        if (error && error.code === "ENOENT") {
          diagnostics.delete(doc.uri);
          if (!quiet) {
            vscode.window.showErrorMessage(
              `「する」のコマンド ${program} が見つかりません。pip で入れるか、設定「suru.command」で場所を指定してください。`,
            );
          }
          output.appendLine(`${program} が見つかりません`);
          resolve();
          return;
        }
        const errors = parseErrors(text);
        if (error && errors.length === 0) {
          output.appendLine(`型の検査を実行できませんでした(${doc.uri.fsPath}):\n${text}`);
          if (!quiet) output.show(true);
        }
        // 言語サーバーにつないでいるときは、間違いの表示はそちらに任せる
        if (!client)
          diagnostics.set(
            doc.uri,
            errors.map((e) => {
              const d = new vscode.Diagnostic(errorRange(doc, e), e.message, vscode.DiagnosticSeverity.Error);
              d.source = "する";
              return d;
            }),
          );
        if (!quiet) {
          if (errors.length) {
            vscode.window.showErrorMessage(`型の検査: ${errors[0].message}`);
          } else if (!error) {
            vscode.window.showInformationMessage("型の検査で問題は見つかりませんでした");
          }
        }
        resolve();
      },
    );
  });
}

/** 言語サーバー suru-ls の場所(設定、同梱、PATH、~/go/bin の順)。使わないなら undefined */
function findServer(context) {
  const configured = (vscode.workspace.getConfiguration("suru").get("languageServer") || "").trim();
  if (configured === "off") return undefined;
  if (configured) return configured;
  const exe = process.platform === "win32" ? ".exe" : "";
  const bundled = path.join(context.extensionPath, "server", `suru-ls-${process.platform}-${process.arch}${exe}`);
  if (fs.existsSync(bundled)) {
    try {
      if (process.platform !== "win32") fs.chmodSync(bundled, 0o755); // .vsix から出すと実行できる印が消えることがある
    } catch {
      // 書き込めなければそのまま試す
    }
    return bundled;
  }
  const candidates = [];
  for (const dir of (process.env.PATH || "").split(path.delimiter)) {
    if (dir) candidates.push(path.join(dir, `suru-ls${exe}`));
  }
  const gopath = process.env.GOPATH || path.join(os.homedir(), "go");
  candidates.push(path.join(gopath, "bin", `suru-ls${exe}`));
  return candidates.find((p) => {
    try {
      return fs.statSync(p).isFile();
    } catch {
      return false;
    }
  });
}

async function startServer(context) {
  const command = findServer(context);
  if (!command) {
    output.appendLine("言語サーバー suru-ls が見つからないので、保存したときに suru --検査 で調べます");
    return;
  }
  const { LanguageClient, TransportKind } = require("vscode-languageclient/node");
  const c = new LanguageClient(
    "suru",
    "する 言語サーバー",
    { command, transport: TransportKind.stdio },
    {
      documentSelector: [
        { scheme: "file", language: LANG },
        { scheme: "untitled", language: LANG },
      ],
      outputChannel: output,
    },
  );
  try {
    await c.start();
    client = c;
    diagnostics.clear(); // 間違いは言語サーバーが出す
    output.appendLine(`言語サーバーを起動しました: ${command}`);
  } catch (e) {
    output.appendLine(`言語サーバー ${command} を起動できませんでした: ${e}`);
    vscode.workspace.textDocuments.forEach((doc) => autoCheck(doc));
  }
}

async function stopServer() {
  if (client) {
    const c = client;
    client = undefined;
    try {
      await c.stop();
    } catch {
      // 止まっていればそれでよい
    }
  }
}

function autoCheck(doc) {
  if (client) return;
  if (vscode.workspace.getConfiguration("suru", doc.uri).get("checkOnSave")) check(doc, { quiet: true });
}

async function activate(context) {
  diagnostics = vscode.languages.createDiagnosticCollection("suru");
  output = vscode.window.createOutputChannel("する");
  context.subscriptions.push(diagnostics, output);

  context.subscriptions.push(
    vscode.commands.registerCommand("suru.run", async () => {
      const doc = activeSuruDocument();
      if (doc && (await saved(doc))) runInTerminal(doc, []);
    }),
    vscode.commands.registerCommand("suru.compile", async () => {
      const doc = activeSuruDocument();
      if (doc && (await saved(doc))) runInTerminal(doc, ["--翻訳"]);
    }),
    vscode.commands.registerCommand("suru.check", async () => {
      const doc = activeSuruDocument();
      if (doc && (await saved(doc))) await check(doc);
    }),
    vscode.commands.registerCommand("suru.kumuRun", () => kumuOnActive(["実行"])),
    vscode.commands.registerCommand("suru.kumuBuild", () => kumuOnActive(["作る"])),
    vscode.commands.registerCommand("suru.kumuTest", () => kumuOnActive(["試験"])),
    vscode.commands.registerCommand("suru.kumuCheck", () => kumuOnActive(["点検"])),
    vscode.commands.registerCommand("suru.kumuFetch", () => kumuOnActive(["取得"])),
    vscode.commands.registerCommand("suru.kumuTestOne", async (uri, name) => {
      const doc = uri ? await vscode.workspace.openTextDocument(uri) : activeSuruDocument();
      if (doc && (await saved(doc))) runKumu(doc, name ? ["試験", name] : ["試験"]);
    }),
    vscode.languages.registerCodeLensProvider({ language: LANG }, testLenses),
    vscode.commands.registerCommand("suru.restartServer", async () => {
      await stopServer();
      await startServer(context);
      vscode.window.showInformationMessage(client ? "言語サーバーを再起動しました" : "言語サーバーが見つかりません");
    }),
    vscode.window.onDidCloseTerminal((t) => {
      if (t === terminal) terminal = undefined;
    }),
  );

  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument(autoCheck),
    vscode.workspace.onDidSaveTextDocument(autoCheck),
    vscode.workspace.onDidCloseTextDocument((doc) => diagnostics.delete(doc.uri)),
  );
  await startServer(context);
  vscode.workspace.textDocuments.forEach(autoCheck);
}

function deactivate() {
  return stopServer();
}

module.exports = { activate, deactivate, parseErrors, splitCommand };
