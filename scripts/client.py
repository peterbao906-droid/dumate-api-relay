# -*- coding: utf-8 -*-
"""
DuMate API 客户端（零依赖，纯标准库）

给 harness / 自研 Agent / 脚本直接调用百度搭子（DuMate）额度用的轻客户端。
既可以打本机 relay 反代，也可以打局域网/Tailscale 上的 relay，或直连 points_api。

配置优先级：命令行参数 > 环境变量 > ~/.dumate.json

环境变量：
  DUMATE_BASE         服务地址，默认 http://127.0.0.1:8000
                      （relay 层默认 8000；若直连 points_api 则为 http://127.0.0.1:8765）
  DUMATE_API_KEY      relay token（或 points_api 的 --token）。经 relay 时作为 X-Relay-Token 发送，
                      同时也会放进 Authorization: Bearer，兼容 OpenAI SDK 习惯。
  DUMATE_MODEL        默认模型，默认 dumate-lite（可选 lite / turbo / ultra）
  DUMATE_TIMEOUT      超时秒数，默认 900（DuMate 会真干活，可能跑很久）

命令行：
  python client.py "问题"                          # 默认 lite 档
  python client.py --model dumate-ultra "复杂任务"
  python client.py --points                        # 查积分
  python client.py --models                        # 查模型清单
  python client.py --doctor                        # 全链路自检
  python client.py --stream "问题"                 # 流式输出

在代码里用：
  from client import dumate_chat, dumate_points
  r = dumate_chat([{"role": "user", "content": "你好"}], model="dumate-lite")
  print(r["content"])
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_TIMEOUT = int(os.environ.get("DUMATE_TIMEOUT", "900"))

MODELS = {
    "dumate-lite": {"level": "L0 / lite", "desc": "最省积分，日常问答、简单改写"},
    "dumate-turbo": {"level": "L1 / turbo", "desc": "中等档，复杂分析、代码"},
    "dumate-ultra": {"level": "L2 / ultra", "desc": "最强档，扣分最多，慎用"},
    "dumate-points": {"level": "—", "desc": "特殊：问积分会返回真实余额"},
}


# ---------------------------------------------------------------- 配置解析

def _load_config() -> dict:
    """读 ~/.dumate.json（不存在则返回空 dict）。"""
    for p in (Path.home() / ".dumate.json", Path.cwd() / ".dumate.json"):
        try:
            if p.is_file():
                return json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
    return {}


def _cfg(base=None, api_key=None, model=None) -> dict:
    c = _load_config()
    return {
        "base": (base or os.environ.get("DUMATE_BASE") or c.get("base")
                 or "http://127.0.0.1:8000").rstrip("/"),
        "api_key": (api_key or os.environ.get("DUMATE_API_KEY") or c.get("api_key")
                    or c.get("relay_token") or c.get("token") or ""),
        "model": (model or os.environ.get("DUMATE_MODEL") or c.get("model")
                  or "dumate-lite"),
    }


# ---------------------------------------------------------------- HTTP 底座

def _request(path: str, payload: dict | None = None, cfg: dict | None = None,
             timeout: int | None = None, stream: bool = False):
    cfg = cfg or _cfg()
    url = f"{cfg['base']}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    if cfg["api_key"]:
        # 同时给两种头：relay 认 X-Relay-Token，OpenAI 风格认 Bearer，points_api 两个都认
        req.add_header("X-Relay-Token", cfg["api_key"])
        req.add_header("Authorization", f"Bearer {cfg['api_key']}")
    return urllib.request.urlopen(req, timeout=timeout or DEFAULT_TIMEOUT), stream


def _raise_http(e: urllib.error.HTTPError):
    """把网关错误翻译成人能看懂的话。"""
    try:
        body = e.read().decode("utf-8", "ignore")
    except Exception:
        body = ""
    hints = {
        401: "token 不对：检查 DUMATE_API_KEY（relay token 或 points_api 的 --token）",
        403: "relay 拒绝了请求：X-Relay-Token 与服务端 RELAY_TOKEN 不一致",
        404: "路径不存在：确认 base 是否写到了 /v1 之外，且服务已启动",
        502: "上游不可用：dumate-api 没起，或 DuMate 桌面版没运行",
    }
    hint = hints.get(e.code)
    msg = f"HTTP {e.code}"
    if hint:
        msg += f" — {hint}"
    if body:
        msg += f"\n上游返回: {body[:500]}"
    raise RuntimeError(msg)


# ---------------------------------------------------------------- 对外接口

def dumate_chat(messages, model: str = None, base: str = None, api_key: str = None,
                temperature: float | None = None, max_tokens: int | None = None,
                timeout: int | None = None, extra: dict | None = None) -> dict:
    """调用 DuMate 对话补全，返回统一结构。

    Args:
        messages: OpenAI 格式消息列表，如 [{"role": "user", "content": "你好"}]
        model: dumate-lite / dumate-turbo / dumate-ultra（默认读配置，兜底 lite）
        base / api_key: 覆盖配置
        temperature / max_tokens: 透传给上游（DuMate 可能忽略，但兼容 SDK 习惯）
        timeout: 秒
        extra: 额外透传字段

    Returns:
        {"content": str, "model": str, "usage": dict, "raw": dict}
        content 为空时看 raw，多半是任务还没跑完或工具调用模式。
    """
    cfg = _cfg(base, api_key, model)
    payload = {"model": model or cfg["model"], "messages": messages, "stream": False}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if extra:
        payload.update(extra)

    try:
        resp, _ = _request("/v1/chat/completions", payload, cfg, timeout)
        with resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _raise_http(e)

    choice = (raw.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content") or ""
    return {
        "content": content,
        "model": raw.get("model"),
        "usage": raw.get("usage") or {},
        "tool_calls": (choice.get("message") or {}).get("tool_calls"),
        "finish_reason": choice.get("finish_reason"),
        "raw": raw,
    }


def dumate_chat_stream(messages, model: str = None, base: str = None,
                       api_key: str = None, timeout: int | None = None):
    """流式调用，逐段 yield 文本增量。"""
    cfg = _cfg(base, api_key, model)
    payload = {"model": model or cfg["model"], "messages": messages, "stream": True}
    try:
        resp, _ = _request("/v1/chat/completions", payload, cfg, timeout, stream=True)
    except urllib.error.HTTPError as e:
        _raise_http(e)

    with resp:
        for line in resp:
            line = line.decode("utf-8", "ignore").strip()
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except Exception:
                continue
            delta = (obj.get("choices") or [{}])[0].get("delta") or {}
            piece = delta.get("content")
            if piece:
                yield piece


def dumate_points(refresh: bool = False, base: str = None, api_key: str = None) -> dict:
    """查积分余额：返回 totalPoints / usedPoints / availablePoints。"""
    cfg = _cfg(base, api_key)
    path = "/api/points/balance" + ("/refresh" if refresh else "")
    try:
        resp, _ = _request(path, None, cfg, timeout=120)
        with resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _raise_http(e)


def dumate_models(base: str = None, api_key: str = None) -> dict:
    """列出可用模型（走上游 /v1/models，返回 OpenAI 格式）。"""
    cfg = _cfg(base, api_key)
    try:
        resp, _ = _request("/v1/models", None, cfg, timeout=60)
        with resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _raise_http(e)


def dumate_health(base: str = None, api_key: str = None) -> dict:
    cfg = _cfg(base, api_key)
    try:
        resp, _ = _request("/health", None, cfg, timeout=30)
        with resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _raise_http(e)


# ---------------------------------------------------------------- 自检

def doctor(base: str = None, api_key: str = None) -> int:
    cfg = _cfg(base, api_key)
    print(f"base     : {cfg['base']}")
    print(f"api_key  : {'已配置 (' + cfg['api_key'][:6] + '...)' if cfg['api_key'] else '⚠️  未配置'}")
    print(f"default  : {cfg['model']}")
    print("-" * 52)

    ok = True

    # 1. health
    try:
        h = dumate_health()
        print(f"[1/3] 健康检查   : OK {h}")
    except Exception as e:
        print(f"[1/3] 健康检查   : ✗ {e}")
        ok = False

    # 2. models
    try:
        m = dumate_models()
        ids = [x.get("id") for x in (m.get("data") or [])]
        print(f"[2/3] 模型清单   : {ids}")
    except Exception as e:
        print(f"[2/3] 模型清单   : ✗ {e}")
        ok = False

    # 3. 积分（顺带验证上游链路是否真的通到 DuMate）
    try:
        p = dumate_points()
        print(f"[3/3] 积分余额   : 可用 {p.get('availablePoints')} / 总 {p.get('totalPoints')}")
    except Exception as e:
        print(f"[3/3] 积分余额   : ✗ {e}")
        ok = False

    print("-" * 52)
    print("结论：" + ("✅ 全链路可用" if ok else "❌ 有环节不通，按上面提示排查"))
    return 0 if ok else 1


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description="DuMate API 客户端")
    ap.add_argument("prompt", nargs="*", help="要发送的问题")
    ap.add_argument("--model", "-m", default=None, help="dumate-lite / dumate-turbo / dumate-ultra")
    ap.add_argument("--base", default=None, help="服务地址，默认 http://127.0.0.1:8000")
    ap.add_argument("--api-key", default=None, help="relay token")
    ap.add_argument("--system", "-s", default=None, help="system prompt")
    ap.add_argument("--max-tokens", type=int, default=None)
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--timeout", type=int, default=None)
    ap.add_argument("--stream", action="store_true", help="流式输出")
    ap.add_argument("--points", action="store_true", help="查积分余额")
    ap.add_argument("--refresh-points", action="store_true", help="强制刷新积分（绕过 60s 缓存）")
    ap.add_argument("--models", action="store_true", help="列出模型")
    ap.add_argument("--doctor", action="store_true", help="全链路自检")
    ap.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = ap.parse_args()

    if args.doctor:
        sys.exit(doctor(args.base, args.api_key))

    if args.points or args.refresh_points:
        p = dumate_points(refresh=args.refresh_points, base=args.base, api_key=args.api_key)
        print(json.dumps(p, ensure_ascii=False, indent=2) if args.json
              else f"可用积分 {p.get('availablePoints')} / 总 {p.get('totalPoints')} / 已用 {p.get('usedPoints')}")
        return

    if args.models:
        m = dumate_models(args.base, args.api_key)
        if args.json:
            print(json.dumps(m, ensure_ascii=False, indent=2))
        else:
            for x in (m.get("data") or []):
                mid = x.get("id", "")
                meta = MODELS.get(mid, {})
                print(f"  {mid:<16} {meta.get('level', ''):<12} {meta.get('desc', '')}")
        return

    text = " ".join(args.prompt).strip()
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    if not text:
        ap.print_help()
        sys.exit(1)

    messages = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": text})

    t0 = time.time()
    if args.stream:
        try:
            for piece in dumate_chat_stream(messages, args.model, args.base, args.api_key, args.timeout):
                sys.stdout.write(piece)
                sys.stdout.flush()
        except Exception as e:
            print(f"\n[错误] {e}", file=sys.stderr)
            sys.exit(1)
        print(f"\n\n[{time.time() - t0:.1f}s]")
        return

    try:
        r = dumate_chat(messages, args.model, args.base, args.api_key,
                        args.temperature, args.max_tokens, args.timeout)
    except Exception as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(r["raw"], ensure_ascii=False, indent=2))
    else:
        print(r["content"] or "(空响应)")
        print(f"\n[{r['model']} | {time.time() - t0:.1f}s | usage={r['usage']}]")


if __name__ == "__main__":
    main()
