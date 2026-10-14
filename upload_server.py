#!/usr/bin/env python3
"""Simple LAN file upload/download server. Saves files to ./download."""

import cgi
import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "download"
HOST = "0.0.0.0"
PORT = 8765


def safe_filename(name: str) -> str:
    name = os.path.basename(name.replace("\\", "/"))
    name = name.strip().strip(".")
    if not name:
        raise ValueError("invalid filename")
    return name


def resolve_download_file(name: str) -> Path | None:
    """Resolve a filename under UPLOAD_DIR; reject path traversal."""
    try:
        filename = safe_filename(unquote(name))
    except ValueError:
        return None
    target = (UPLOAD_DIR / filename).resolve()
    try:
        target.relative_to(UPLOAD_DIR.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    return target


def format_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>内网文件上传下载</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      color: #e2e8f0;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }
    .card {
      width: min(720px, 100%);
      background: rgba(15, 23, 42, 0.92);
      border: 1px solid rgba(148, 163, 184, 0.2);
      border-radius: 16px;
      padding: 28px;
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
    }
    h1 { margin: 0 0 8px; font-size: 1.6rem; }
    .hint { color: #94a3b8; margin-bottom: 20px; font-size: 0.95rem; }
    .dropzone {
      border: 2px dashed #475569;
      border-radius: 14px;
      padding: 48px 24px;
      text-align: center;
      cursor: pointer;
      transition: border-color 0.2s, background 0.2s;
      background: rgba(30, 41, 59, 0.6);
    }
    .dropzone.dragover {
      border-color: #38bdf8;
      background: rgba(56, 189, 248, 0.08);
    }
    .dropzone strong { display: block; font-size: 1.1rem; margin-bottom: 8px; }
    input[type="file"] { display: none; }
    .btn {
      margin-top: 16px;
      width: 100%;
      border: none;
      border-radius: 10px;
      padding: 12px 16px;
      font-size: 1rem;
      font-weight: 600;
      color: #0f172a;
      background: #38bdf8;
      cursor: pointer;
    }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .status {
      margin-top: 16px;
      min-height: 24px;
      font-size: 0.95rem;
      white-space: pre-wrap;
      word-break: break-all;
    }
    .status.ok { color: #4ade80; }
    .status.err { color: #f87171; }
    .files {
      margin-top: 24px;
      padding-top: 16px;
      border-top: 1px solid rgba(148, 163, 184, 0.15);
    }
    .files-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 10px;
    }
    .files h2 { margin: 0; font-size: 1rem; color: #cbd5e1; }
    .refresh {
      border: 1px solid rgba(148, 163, 184, 0.35);
      background: transparent;
      color: #94a3b8;
      border-radius: 8px;
      padding: 6px 10px;
      cursor: pointer;
      font-size: 0.85rem;
    }
    .refresh:hover { color: #e2e8f0; border-color: #94a3b8; }
    .files ul {
      margin: 0;
      padding: 0;
      list-style: none;
      color: #94a3b8;
      max-height: 320px;
      overflow: auto;
    }
    .files li {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid transparent;
    }
    .files li:hover {
      background: rgba(30, 41, 59, 0.8);
      border-color: rgba(148, 163, 184, 0.15);
    }
    .files a {
      flex: 1;
      color: #7dd3fc;
      text-decoration: none;
      word-break: break-all;
    }
    .files a:hover { text-decoration: underline; color: #38bdf8; }
    .files .size {
      flex-shrink: 0;
      font-size: 0.85rem;
      color: #64748b;
    }
    .empty { color: #64748b; padding: 8px 4px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>内网文件上传 / 下载</h1>
    <p class="hint">拖拽或选择文件上传到 <code>download</code> 目录；下方列表点击文件名即可下载。</p>

    <div class="dropzone" id="dropzone">
      <strong>拖拽文件到这里</strong>
      <span>或点击选择文件</span>
      <input id="fileInput" type="file" multiple>
    </div>

    <button class="btn" id="uploadBtn" disabled>开始上传</button>
    <div class="status" id="status"></div>

    <div class="files">
      <div class="files-header">
        <h2>download 目录已有文件</h2>
        <button class="refresh" id="refreshBtn" type="button">刷新</button>
      </div>
      <ul id="fileList"><li class="empty">加载中...</li></ul>
    </div>
  </div>

  <script>
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("fileInput");
    const uploadBtn = document.getElementById("uploadBtn");
    const refreshBtn = document.getElementById("refreshBtn");
    const statusEl = document.getElementById("status");
    const fileListEl = document.getElementById("fileList");
    let selectedFiles = [];

    function setStatus(text, ok) {
      statusEl.textContent = text;
      statusEl.className = "status " + (ok ? "ok" : "err");
    }

    function updateSelected(files) {
      selectedFiles = Array.from(files || []);
      uploadBtn.disabled = selectedFiles.length === 0;
      if (selectedFiles.length === 0) {
        setStatus("", true);
        return;
      }
      setStatus("已选择 " + selectedFiles.length + " 个文件，点击开始上传", true);
    }

    function escapeHtml(s) {
      return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    dropzone.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", (e) => updateSelected(e.target.files));
    refreshBtn.addEventListener("click", () => loadFileList());

    ["dragenter", "dragover"].forEach((evt) => {
      dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.add("dragover");
      });
    });

    ["dragleave", "drop"].forEach((evt) => {
      dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.remove("dragover");
      });
    });

    dropzone.addEventListener("drop", (e) => {
      updateSelected(e.dataTransfer.files);
    });

    async function loadFileList() {
      try {
        const res = await fetch("/api/files");
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "加载失败");
        if (data.files.length === 0) {
          fileListEl.innerHTML = '<li class="empty">暂无文件</li>';
          return;
        }
        fileListEl.innerHTML = data.files.map((f) => {
          const name = typeof f === "string" ? f : f.name;
          const size = typeof f === "string" ? "" : (f.size_label || "");
          const href = "/files/" + encodeURIComponent(name);
          return (
            "<li>" +
              '<a href="' + href + '" download="' + escapeHtml(name) + '" title="点击下载">' +
                escapeHtml(name) +
              "</a>" +
              (size ? '<span class="size">' + escapeHtml(size) + "</span>" : "") +
            "</li>"
          );
        }).join("");
      } catch (err) {
        fileListEl.innerHTML = '<li class="empty">加载失败</li>';
      }
    }

    uploadBtn.addEventListener("click", async () => {
      if (selectedFiles.length === 0) return;
      uploadBtn.disabled = true;
      setStatus("正在上传...", true);

      const form = new FormData();
      selectedFiles.forEach((file) => form.append("files", file, file.name));

      try {
        const res = await fetch("/upload", { method: "POST", body: form });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || "上传失败");
        setStatus("上传成功：\\n" + data.saved.join("\\n"), true);
        fileInput.value = "";
        selectedFiles = [];
        await loadFileList();
      } catch (err) {
        setStatus(err.message, false);
      } finally {
        uploadBtn.disabled = selectedFiles.length === 0;
      }
    });

    loadFileList();
  </script>
</body>
</html>
"""


class UploadHandler(BaseHTTPRequestHandler):
    server_version = "SteamAddUpload/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s - %s\n" % (self.log_date_time_string(), self.address_string(), fmt % args))

    def send_json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, content: str):
        body = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, filepath: Path):
        ctype = mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"
        size = filepath.stat().st_size
        filename = filepath.name
        ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "download"
        disposition = (
            'attachment; filename="%s"; filename*=UTF-8\'\'%s'
            % (ascii_name.replace('"', ""), quote(filename))
        )

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", disposition)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(1024 * 256)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self.send_html(INDEX_HTML)
            return

        if path == "/api/files":
            files = []
            if UPLOAD_DIR.exists():
                for item in sorted(UPLOAD_DIR.iterdir(), key=lambda p: p.name.lower()):
                    if item.is_file():
                        size = item.stat().st_size
                        files.append({
                            "name": item.name,
                            "size": size,
                            "size_label": format_size(size),
                        })
            self.send_json(200, {"ok": True, "files": files})
            return

        if path.startswith("/files/"):
            name = path[len("/files/"):]
            if not name or "/" in name or "\\" in name:
                self.send_json(400, {"ok": False, "error": "invalid filename"})
                return
            target = resolve_download_file(name)
            if target is None:
                self.send_json(404, {"ok": False, "error": "file not found"})
                return
            try:
                self.send_file(target)
            except Exception as exc:
                self.send_json(500, {"ok": False, "error": str(exc)})
            return

        self.send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/upload":
            self.send_json(404, {"ok": False, "error": "not found"})
            return

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_json(400, {"ok": False, "error": "需要 multipart/form-data"})
            return

        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": content_type,
                },
            )
        except Exception as exc:
            self.send_json(400, {"ok": False, "error": f"解析上传失败: {exc}"})
            return

        saved = []
        items = form["files"] if "files" in form else []
        if not isinstance(items, list):
            items = [items]

        if not items:
            self.send_json(400, {"ok": False, "error": "未选择文件"})
            return

        try:
            for item in items:
                if not item.filename:
                    continue
                filename = safe_filename(item.filename)
                target = UPLOAD_DIR / filename
                with open(target, "wb") as out:
                    if hasattr(item, "file"):
                        out.write(item.file.read())
                    else:
                        out.write(item.value if isinstance(item.value, bytes) else b"")
                saved.append(filename)
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})
            return

        if not saved:
            self.send_json(400, {"ok": False, "error": "没有有效文件被保存"})
            return

        self.send_json(200, {"ok": True, "saved": saved})


def main():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), UploadHandler)
    print(f"Upload/download server running at http://127.0.0.1:{PORT}")
    print(f"LAN access: http://<your-ip>:{PORT}")
    print(f"File directory: {UPLOAD_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
