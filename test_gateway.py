#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OpenClaw Gateway WebSocket smoke test.

This script validates:
1. Whether Gateway mode is enabled
2. Whether the configured WebSocket handshake succeeds
3. Whether chat-related methods are reachable with the current auth/device pairing
4. Whether a test chat message can be sent
"""

import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from gateway_client import GatewayClient

load_dotenv()


def test_gateway_connection():
    """Check the Gateway connection."""
    print("=" * 50)
    print("OpenClaw Gateway WebSocket test")
    print("=" * 50)

    client = GatewayClient()
    info = client.get_info()

    print("\nConfiguration:")
    print(f"  Gateway mode enabled: {info['use_gateway']}")
    print(f"  Configured Gateway URL: {info['gateway_url']}")
    print(f"  WebSocket URL: {info['ws_url']}")
    print(f"  HTTP URL: {info['http_url']}")
    print(f"  Agent ID: {info['agent_id']}")
    print(f"  Session key: {info['session_key']}")
    print(f"  Default user: {info['default_user']}")
    print(f"  Client ID: {info['client_id']}")
    print(f"  Client mode: {info['client_mode']}")
    print(f"  Requested scopes: {', '.join(info['requested_scopes'])}")
    print(f"  Device ID: {info['device_id']}")
    print(f"  Local state dir: {info['state_dir']}")
    print(f"  Auto-approve pairing: {info['auto_approve_pairing']}")
    print(f"  Token configured: {info['has_token']}")
    print(f"  Password configured: {info['has_password']}")
    print(f"  OpenClaw CLI available: {info['has_cli']}")

    connection_probe = info.get("connection_probe") or {}
    print(
        f"  Connection probe: ok={connection_probe.get('ok')} detail={connection_probe.get('detail')}"
    )

    chat_probe = info.get("chat_probe") or {}
    print(f"  Chat probe: ok={chat_probe.get('ok')} detail={chat_probe.get('detail')}")

    if info["use_gateway"]:
        print("\nChecking Gateway availability...")
        if info["available"]:
            print("  OK: Gateway WebSocket handshake succeeded")
            return True

        print("  ERROR: Gateway is not reachable")
        print("\nPlease verify:")
        print("  1. OpenClaw Gateway is running")
        print("  2. GATEWAY_URL points to the WebSocket endpoint")
        print("  3. GATEWAY_TOKEN is correct")
        print("  4. The device can be paired and granted the requested scopes")
        return False

    print("\nGateway mode is disabled.")
    print("To enable it, set USE_GATEWAY=true in .env")
    return False


def test_gateway_message():
    """Send a test message through the WebSocket chat API."""
    print("\n" + "=" * 50)
    print("OpenClaw Gateway chat test")
    print("=" * 50)

    client = GatewayClient()

    if not client.use_gateway:
        print("Gateway mode is disabled, skipping message test.")
        return

    try:
        print("\nSending test message...")
        response = client.send_message("请用一句中文介绍你自己。")
        print("\nReceived response:")
        print(f"  {response}")
        print("\nOK: Chat request succeeded")
    except Exception as exc:
        print(f"\nERROR: Chat request failed: {exc}")


if __name__ == "__main__":
    print("\nStarting Gateway checks...\n")
    connected = test_gateway_connection()

    if connected:
        test_gateway_message()

    print("\n" + "=" * 50)
    print("Checks completed")
    print("=" * 50)
