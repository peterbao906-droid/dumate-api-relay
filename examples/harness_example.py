# -*- coding: utf-8 -*-
"""
harness 接入示例 —— 四种方式，任选一种复制到你的 harness 里。

前提：DuMate 服务已启动（python start.py --api-token X --relay-token Y），
      DuMate 桌面版保持运行。

【重要】把下面的 RELAY_TOKEN 改成你自己的 relay token。
        本文件里出现的 CHANGE_ME_RELAY_TOKEN 只是占位符，直接用会被拒绝。
"""

import os
import sys

# relay token —— 改成你自己的，或用环境变量 DUMATE_API_KEY 覆盖
RELAY_TOKEN = os.environ.get("DUMATE_API_KEY", "CHANGE_ME_RELAY_TOKEN")

# relay 监听地址；跨机时换成 http://<Tailscale-IP>:8000
RELAY_BASE = os.environ.get("DUMATE_BASE", "http://127.0.0.1:8000")

# 本仓库 scripts 目录的路径（自动推导，无需手改）
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.join(os.path.dirname(_HERE), "scripts")


# ============================================================
# 方式一：标准 OpenAI SDK（如果你 harness 已经在用 openai 库，改两行即可）
# ============================================================

def example_openai_sdk():
    from openai import OpenAI

    client = OpenAI(
        base_url=RELAY_BASE.rstrip("/") + "/v1",
        api_key=RELAY_TOKEN,
    )

    # 非流式
    r = client.chat.completions.create(
        model="dumate-lite",                   # lite / turbo / ultra
        messages=[{"role": "user", "content": "用一句话介绍你自己的能力"}],
    )
    print(r.choices[0].message.content)

    # 流式
    stream = client.chat.completions.create(
        model="dumate-lite",
        messages=[{"role": "user", "content": "数到十"}],
        stream=True,
    )
    for chunk in stream:
        piece = chunk.choices[0].delta.content
        if piece:
            print(piece, end="", flush=True)


# ============================================================
# 方式二：直接 import 本仓库的客户端（零依赖，最轻）
# ============================================================

def example_direct_client():
    sys.path.insert(0, _SCRIPTS_DIR)
    from client import dumate_chat, dumate_chat_stream, dumate_points

    # 配置可通过参数传，也可设环境变量 DUMATE_BASE / DUMATE_API_KEY
    r = dumate_chat(
        [{"role": "user", "content": "用一句话介绍你自己的能力"}],
        model="dumate-lite",
        base=RELAY_BASE,
        api_key=RELAY_TOKEN,
    )
    print("回答:", r["content"])
    print("模型:", r["model"])

    # 流式
    for piece in dumate_chat_stream(
        [{"role": "user", "content": "数到十"}],
        model="dumate-lite",
        base=RELAY_BASE,
        api_key=RELAY_TOKEN,
    ):
        print(piece, end="", flush=True)

    # 查积分（建议在 harness 调用前后查一次，监控消耗）
    p = dumate_points(base=RELAY_BASE, api_key=RELAY_TOKEN)
    print(f"\n剩余积分: {p['availablePoints']}")


# ============================================================
# 方式三：裸 HTTP（不依赖任何库，适合 Node / Go / curl 等非 Python harness）
# ============================================================

def example_raw_http():
    import json
    import urllib.request

    req = urllib.request.Request(
        RELAY_BASE.rstrip("/") + "/v1/chat/completions",
        data=json.dumps({
            "model": "dumate-lite",
            "messages": [{"role": "user", "content": "你好"}],
        }).encode(),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + RELAY_TOKEN)   # 或 X-Relay-Token

    with urllib.request.urlopen(req, timeout=900) as resp:
        d = json.loads(resp.read())
    print(d["choices"][0]["message"]["content"])


# ============================================================
# 方式四：集成到已有 harness 的推荐做法 —— 包一层统一接口
# ============================================================

class DumateBackend:
    """把 DuMate 包装成 harness 内部统一的后端接口。

    好处：你的 harness 上层代码不关心底下是 DeepSeek、OpenAI 还是 DuMate，
    换后端只改这一层。
    """

    def __init__(self, base=None, api_key=None, default_model="dumate-lite"):
        self.base = (base or RELAY_BASE).rstrip("/")
        self.api_key = api_key or RELAY_TOKEN
        self.default_model = default_model

    def _client_mod(self):
        if _SCRIPTS_DIR not in sys.path:
            sys.path.insert(0, _SCRIPTS_DIR)
        import client
        return client

    def chat(self, messages, model=None, timeout=900):
        """返回纯文本，harness 里最常见的用法。"""
        c = self._client_mod()
        r = c.dumate_chat(messages, model or self.default_model,
                          base=self.base, api_key=self.api_key, timeout=timeout)
        return r["content"]

    def points(self):
        return self._client_mod().dumate_points(base=self.base, api_key=self.api_key)

    def guard_quota(self, min_points=500):
        """积分低于阈值就抛错，防止 harness 跑到一半积分耗尽。"""
        p = self.points()
        avail = p.get("availablePoints") or 0
        if avail < min_points:
            raise RuntimeError(f"DuMate 积分不足：剩 {avail}，阈值 {min_points}")
        return avail


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "raw"
    if which == "sdk":
        example_openai_sdk()
    elif which == "direct":
        example_direct_client()
    elif which == "raw":
        example_raw_http()
    elif which == "backend":
        b = DumateBackend()
        print("剩余:", b.guard_quota(100))
        print(b.chat([{"role": "user", "content": "用一句话介绍你自己的能力"}]))
    else:
        print("用法: python harness_example.py [sdk|direct|raw|backend]")
