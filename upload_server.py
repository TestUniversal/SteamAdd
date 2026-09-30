#!/usr/bin/env python3
"""Simple LAN file upload server. Saves files to ./download."""

import cgi
import html
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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


INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>内网文件上传</title>
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
      width: min(640px, 100%);
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
    .files h2 { margin: 0 0 10px; font-size: 1rem; color: #cbd5e1; }
    .files ul { margin: 0; padding-left: 20px; color: #94a3b8; max-height: 220px; overflow: auto; }
  </style>
</head>
<body>
  <div class="card">
    <h1>内网文件上传</h1>
    <p class="hint">拖拽文件到下方区域，或点击选择文件。上传后保存到 <code>download</code> 目录。</p>

    <div class="dropzone" id="dropzone">
      <strong>拖拽文件到这里</strong>
      <span>或点击选择文件</span>
      <input id="fileInput" type="file" multiple>
    </div>

    <button class="btn" id="uploadBtn" disabled>开始上传</button>
    <div class="status" id="status"></div>

    <div class="files">
      <h2>download 目录已有文件</h2>
      <ul id="fileList"><li>加载中...</li></ul>
    </div>
  </div>

  <script>
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("fileInput");
    const uploadBtn = document.getElementById("uploadBtn");
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

    dropzone.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", (e) => updateSelected(e.target.files));

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
          fileListEl.innerHTML = "<li>暂无文件</li>";
          return;
        }
        fileListEl.innerHTML = data.files.map((f) => "<li>" + f + "</li>").join("");
      } catch (err) {
        fileListEl.innerHTML = "<li>加载失败</li>";
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
    server_version = "SteamAddUpload/1.0"

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

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self.send_html(INDEX_HTML)
            return
        if path == "/api/files":
            files = []
            if UPLOAD_DIR.exists():
                for item in sorted(UPLOAD_DIR.iterdir(), key=lambda p: p.name.lower()):
                    if item.is_file():
                        files.append(item.name)
            self.send_json(200, {"ok": True, "files": files})
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
    print(f"Upload server running at http://127.0.0.1:{PORT}")
    print(f"LAN access: http://<your-ip>:{PORT}")
    print(f"Upload directory: {UPLOAD_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
