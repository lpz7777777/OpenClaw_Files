#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OpenClaw Gateway discovery helper for mixed HTTP + WebSocket setups.
"""

import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))


def probe_http(url: str):
    try:
        response = requests.get(url, timeout=5)
        return {
            "ok": response.status_code < 400,
            "status": response.status_code,
            "response": response.text[:200] + ("..." if len(response.text) > 200 else ""),
        }
    except Exception as exc:
        return {"ok": False, "status": "Error", "response": str(exc)}


def discover_gateway():
    gateway_url = os.getenv("GATEWAY_URL", "ws://127.0.0.1:18789").strip()

    from gateway_client import GatewayClient

    client = GatewayClient()
    info = client.get_info()

    print("=" * 60)
    print("OpenClaw Gateway discovery")
    print("=" * 60)
    print(f"\nConfigured URL: {gateway_url}")
    print(f"Resolved WebSocket URL: {info['ws_url']}")
    print(f"Resolved HTTP URL: {info['http_url']}")
    print(f"Agent ID: {info['agent_id']}")
    print(f"Session key: {info['session_key']}")
    print(f"Requested scopes: {', '.join(info['requested_scopes'])}")
    print(f"Token configured: {info['has_token']}")
    print(f"Password configured: {info['has_password']}\n")

    http_targets = [
        f"{info['http_url']}/",
        f"{info['http_url']}/health",
        f"{info['http_url']}/status",
    ]

    print("HTTP probes:\n")
    for url in http_targets:
        result = probe_http(url)
        status_symbol = "OK" if result["ok"] else "ERROR"
        print(f"{status_symbol:5} [GET ] {url}")
        print(f"      Status: {result['status']}")
        print(f"      Response: {result['response']}")
        print()

    connection_probe = info.get("connection_probe") or {}
    chat_probe = info.get("chat_probe") or {}

    print("WebSocket probes:\n")
    print(
        f"OK    [WS  ] {info['ws_url']}"
        if connection_probe.get("ok")
        else f"ERROR [WS  ] {info['ws_url']}"
    )
    print(f"      Connect detail: {connection_probe.get('detail')}")

    if connection_probe.get("server_version"):
        print(f"      Server version: {connection_probe.get('server_version')}")

    session_defaults = connection_probe.get("session_defaults")
    if session_defaults:
        print(f"      Session defaults: {json.dumps(session_defaults, ensure_ascii=False)}")

    print()
    print(
        f"OK    [RPC ] chat.history"
        if chat_probe.get("ok")
        else f"ERROR [RPC ] chat.history"
    )
    print(f"      Chat detail: {chat_probe.get('detail')}")

    print("\n" + "=" * 60)
    print("Discovery completed")
    print("=" * 60)

    if connection_probe.get("ok") and not chat_probe.get("ok"):
        print("\nWebSocket access works, but chat capability is still blocked.")
        print("This usually means the current token/password is connected successfully")
        print("but does not grant the requested operator scopes such as operator.read/operator.write.")


if __name__ == "__main__":
    discover_gateway()
