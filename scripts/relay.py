# -*- coding: utf-8 -*-
"""
DuMate 反代服务器（零依赖，纯标准库）

跑在"装了 DuMate 桌面版并已登录"的机器上，把本机 points_api 的 OpenAI /
Anthropic 兼容接口反代出去，供其他 agent、harness 或外网机器调用。
外部客户端只需携带一个 relay token，DuMate 真实 token 由本服务注入，不下发。

架构：
  外部 agent --(X-Relay-Token / Bearer)--> 本服务 --(Bearer DUMATE_API_TOKEN)--> points_api(:8765) --> DuMate 桌面版

环境变量：
  DUMATE_UPSTREAM   上游地址，默认 http://127.0.0.1:8765
  DUMATE_API_TOKEN  上游 token（必填；转发时注入 Authorization）
  RELAY_TOKEN       本服务对外鉴权 token（强烈建议设置，为空=不鉴权=谁能访问谁白嫖你的积分）
  RELAY_HOST        监听地址，默认 0.0.0.0
  RELAY_PORT        监听端口，默认 8000
  DUMATE_TIMEOUT    上游超时秒数，默认 900

配置也可写在 ~/.dumate.json（优先级：环境变量 > 配置文件）：
  { "upstream": "http://127.0.0.1:8765", "api_token": "...", "relay_token": "...",
    "relay_host": "0.0.0.0", "relay_port": 8000 }

启动：
  DUMATE_API_TOKEN=xxx RELAY_TOKEN=yyy python relay.py
  python relay.py --port 8000 --relay-token yyy --api-token xxx

外部调用：
  base_url = http://<本机地址>:8000/v1
  api_key  = yyy
"""

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlreq
from urllib.error import HTTPError, URLError


def _load_file_config() -> dict:
    for p in (Path.home() / ".dumate.json", Path.cwd() / ".dumate.json"):
        try:
            if p.is_file():
                return json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
    return {}


_FILE_CFG = _load_file_config()


def _env(key: str, cfg_key: str, default: str = "") -> str:
    return os.environ.get(key) or str(_FILE_CFG.get(cfg_key) or default)


UPSTREAM = _env("DUMATE_UPSTREAM", "upstream", "http://127.0.0.1:8765").rstrip("/")
DUMATE_API_TOKEN = _env("DUMATE_API_TOKEN", "api_token", "")
RELAY_TOKEN = _env("RELAY_TOKEN", "relay_token", "")
RELAY_HOST = _env("RELAY_HOST", "relay_host", "0.0.0.0")
RELAY_PORT = int(_env("RELAY_PORT", "relay_port", "8000") or 8000)
TIMEOUT = int(_env("DUMATE_TIMEOUT", "timeout", "900") or 900)

# 透传给上游的业务头（Host / Authorization / Content-Length 自行处理）
FORWARD_HEADERS = ("content-type", "accept", "anthropic-version", "anthropic-beta",
                   "openai-beta", "x-api-key")
STREAM_TYPES = ("text/event-stream",)


class RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ---------------- 鉴权
    def _client_token(self) -> str:
        tok = self.headers.get("X-Relay-Token", "")
        if tok:
            return tok.strip()
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        # Anthropic 风格
        return (self.headers.get("x-api-key", "") or "").strip()

    def _check_auth(self) -> bool:
        if not RELAY_TOKEN:
            return True
        return self._client_token() == RELAY_TOKEN

    # ---------------- 转发
    def _proxy(self):
        if not self._check_auth():
            self._json(403, b'{"error":{"message":"invalid relay token","type":"auth_error"}}')
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""

        req = urlreq.Request(f"{UPSTREAM}{self.path}", data=body or None, method=self.command)
        req.add_header("Authorization", f"Bearer {DUMATE_API_TOKEN}")
        for h in FORWARD_HEADERS:
            v = self.headers.get(h)
            if v:
                # x-api-key 是客户端鉴权头，不能透传（否则会覆盖上游 token）
                if h == "x-api-key":
                    continue
                req.add_header(h, v)
        if body:
            req.add_header("Content-Length", str(len(body)))

        try:
            with urlreq.urlopen(req, timeout=TIMEOUT) as resp:
                ctype = resp.headers.get("Content-Type", "application/json")
                if any(t in ctype for t in STREAM_TYPES):
                    self._stream(resp, ctype)
                else:
                    self._json(resp.status, resp.read(), ctype)
        except HTTPError as e:
            self._json(e.code, e.read(), e.headers.get("Content-Type", "application/json"))
        except URLError as e:
            msg = json.dumps({"error": {"message": f"upstream unreachable: {e.reason}",
                                        "type": "upstream_error"}}, ensure_ascii=False)
            self._json(502, msg.encode())
        except Exception as e:  # noqa: BLE001
            msg = json.dumps({"error": {"message": f"relay failure: {str(e)[:200]}",
                                        "type": "relay_error"}}, ensure_ascii=False)
            self._json(502, msg.encode())

    # ---------------- 响应
    def _stream(self, resp, ctype: str):
        self.send_response(resp.status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            while True:
                chunk = resp.read(1024)
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except Exception:
                pass

    def _json(self, status: int, data: bytes, ctype: str = "application/json"):
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self._proxy()

    def do_POST(self):
        self._proxy()

    def log_message(self, fmt, *args):
        pass


def _preflight() -> bool:
    """启动前探一下上游是否活着，只是提示，不阻塞启动。"""
    try:
        with urlreq.urlopen(f"{UPSTREAM}/health", timeout=5) as r:
            return json.loads(r.read().decode("utf-8")).get("status") == "ok"
    except Exception:
        return False


def main():
    global RELAY_HOST, RELAY_PORT, RELAY_TOKEN, DUMATE_API_TOKEN

    ap = argparse.ArgumentParser(description="DuMate 反代服务器")
    ap.add_argument("--host", default=RELAY_HOST)
    ap.add_argument("--port", type=int, default=RELAY_PORT)
    ap.add_argument("--relay-token", default=RELAY_TOKEN)
    ap.add_argument("--api-token", default=DUMATE_API_TOKEN)
    ap.add_argument("--upstream", default=UPSTREAM)
    args = ap.parse_args()

    RELAY_HOST, RELAY_PORT = args.host, args.port
    RELAY_TOKEN, DUMATE_API_TOKEN = args.relay_token, args.api_token
    if args.upstream:
        globals()["UPSTREAM"] = args.upstream.rstrip("/")

    if not DUMATE_API_TOKEN:
        raise SystemExit("缺少 DUMATE_API_TOKEN：请设置环境变量，或用 --api-token 传入 points_api 的 token。")
    if not RELAY_TOKEN:
        print("⚠️  未设置 RELAY_TOKEN —— 任何能访问本端口的人都能消耗你的百度搭子积分！强烈建议设置。")

    alive = _preflight()
    print(f"[dumate-relay] upstream={UPSTREAM} ({'OK' if alive else '未就绪 ⚠️'})  "
          f"auth={'on' if RELAY_TOKEN else 'OFF(公开!)'}  listening={RELAY_HOST}:{RELAY_PORT}")
    if not alive:
        print("  ⚠️ 上游未响应：先启动 points_api.py，并确认 DuMate 桌面版已登录运行。")

    server = ThreadingHTTPServer((RELAY_HOST, RELAY_PORT), RelayHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dumate-relay] 已停止")


if __name__ == "__main__":
    main()
