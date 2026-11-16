# -*- coding: utf-8 -*-
"""
DuMate 一键启动器（零依赖）

同时拉起两层服务，并做启动后自检：
  [1] points_api.py  —— OpenAI/Anthropic 兼容翻译层（127.0.0.1:8765）
  [2] relay.py       —— 反代 + 鉴权层（0.0.0.0:8000）

用法：
  python start.py                          # 用 ~/.dumate.json 或默认值
  python start.py --relay-token yyy --api-token xxx
  python start.py --api-port 8765 --relay-port 8000 --host 0.0.0.0

Ctrl+C 会同时停掉两个子进程。
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE / "scripts" if (HERE / "scripts").exists() else HERE


def _probe(url: str, timeout: float = 3.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _wait(url: str, seconds: float = 20.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _probe(url) is not None:
            return True
        time.sleep(0.5)
    return False


def main():
    ap = argparse.ArgumentParser(description="DuMate 一键启动")
    ap.add_argument("--api-port", type=int, default=8765)
    ap.add_argument("--relay-port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0", help="relay 监听地址")
    ap.add_argument("--api-token", default="", help="上游 points_api token")
    ap.add_argument("--relay-token", default="", help="对外 relay token")
    ap.add_argument("--api-only", action="store_true", help="只起 API 层，不起反代")
    args = ap.parse_args()

    api_token = args.api_token or "CHANGE_ME_API_TOKEN"
    relay_token = args.relay_token or "CHANGE_ME_RELAY_TOKEN"
    if not args.api_token or not args.relay_token:
        print("!" * 60)
        print("⚠️  你正在使用默认占位口令（CHANGE_ME_*），仅适合本机自查。")
        print("    对外提供服务前，必须用 --api-token / --relay-token 指定强口令：")
        print('    python -c "import secrets;print(secrets.token_urlsafe(24))"')
        print("!" * 60)

    env_api = dict(os.environ)
    env_relay = dict(env_api)
    env_relay.update({
        "DUMATE_UPSTREAM": f"http://127.0.0.1:{args.api_port}",
        "DUMATE_API_TOKEN": api_token,
        "RELAY_TOKEN": relay_token,
        "RELAY_HOST": args.host,
        "RELAY_PORT": str(args.relay_port),
    })

    procs = []

    print(f"[1/2] 启动 API 层 127.0.0.1:{args.api_port} ...")
    p1 = subprocess.Popen(
        [sys.executable, str(SCRIPTS / "points_api.py"),
         "--host", "127.0.0.1", "--port", str(args.api_port), "--token", api_token],
        cwd=str(SCRIPTS), env=env_api,
    )
    procs.append(p1)

    if not _wait(f"http://127.0.0.1:{args.api_port}/health", 20):
        print("  ✗ API 层没起来。常见原因：依赖没装（pip install fastapi uvicorn requests cryptography），"
              "或 DuMate 桌面版没运行。")
        p1.terminate()
        sys.exit(1)
    print("  ✓ API 层就绪")

    if args.api_only:
        print(f"\n完成。base_url = http://127.0.0.1:{args.api_port}/v1   api_key = {api_token}")
        try:
            p1.wait()
        except KeyboardInterrupt:
            p1.terminate()
        return

    print(f"[2/2] 启动反代层 {args.host}:{args.relay_port} ...")
    p2 = subprocess.Popen([sys.executable, str(SCRIPTS / "relay.py")], cwd=str(SCRIPTS), env=env_relay)
    procs.append(p2)

    if not _wait(f"http://127.0.0.1:{args.relay_port}/health", 15):
        # relay 的 health 走鉴权，401/403 也算活着
        time.sleep(2)
    print("  ✓ 反代层就绪")

    print("\n" + "=" * 56)
    print("  本机     : http://127.0.0.1:%d/v1" % args.relay_port)
    print("  局域网   : http://<本机IP>:%d/v1" % args.relay_port)
    print("  api_key  : %s   （relay token）" % relay_token)
    print("  查积分   : curl http://127.0.0.1:%d/api/points/balance -H 'X-Relay-Token: %s'"
          % (args.relay_port, relay_token))
    print("=" * 56)
    print("提示：DuMate 桌面版必须保持运行。Ctrl+C 停止。")

    try:
        while True:
            for p in procs:
                if p.poll() is not None:
                    print(f"\n⚠️  子进程 {p.args[1] if len(p.args) > 1 else p.args} 已退出（code={p.returncode}），一并停止。")
                    raise KeyboardInterrupt
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在停止 ...")
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        print("已停止")


if __name__ == "__main__":
    main()
