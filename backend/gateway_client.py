import base64
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import websocket
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption
from dotenv import load_dotenv
from websocket import WebSocketTimeoutException

load_dotenv()


class GatewayClient:
    """OpenClaw Gateway client built on the WebSocket Gateway API."""

    def __init__(self):
        project_root = Path(__file__).resolve().parent.parent

        self.use_gateway = os.getenv("USE_GATEWAY", "false").lower() == "true"
        self.gateway_url = os.getenv("GATEWAY_URL", "ws://127.0.0.1:18789").strip()
        self.ws_url = self._normalize_ws_url(self.gateway_url)
        self.http_url = self._normalize_http_url(self.gateway_url)
        self.gateway_token = os.getenv("GATEWAY_TOKEN", "").strip()
        self.gateway_password = os.getenv("GATEWAY_PASSWORD", "").strip()
        self.agent_id = os.getenv("GATEWAY_AGENT_ID", "main").strip() or "main"
        self.default_user = os.getenv("GATEWAY_USER", "main").strip() or "main"
        self.default_model = os.getenv("GATEWAY_MODEL", "openclaw").strip() or "openclaw"
        self.timeout = int(os.getenv("GATEWAY_TIMEOUT", "60"))
        self.client_id = os.getenv("GATEWAY_CLIENT_ID", "gateway-client").strip() or "gateway-client"
        self.client_mode = os.getenv("GATEWAY_CLIENT_MODE", "backend").strip() or "backend"
        self.session_key = os.getenv("GATEWAY_SESSION_KEY", "").strip() or None
        self.requested_scopes = self._parse_scopes(
            os.getenv("GATEWAY_SCOPES", "operator.read,operator.write")
        )
        self.auto_approve_pairing = (
            os.getenv("GATEWAY_AUTO_APPROVE_LOCAL_PAIRING", "true").lower() == "true"
        )
        self.openclaw_cli_path = self._resolve_openclaw_cli_path()
        self.openclaw_config_path = os.getenv("OPENCLAW_CONFIG_PATH", "").strip()
        if not self.openclaw_config_path:
            self.openclaw_config_path = str(Path.home() / ".openclaw" / "openclaw.json")

        raw_state_dir = os.getenv("GATEWAY_STATE_DIR", "").strip()
        self.state_dir = Path(raw_state_dir) if raw_state_dir else project_root / ".openclaw-state"
        self.identity_path = self.state_dir / "identity" / "device.json"
        self.device_auth_path = self.state_dir / "identity" / "device-auth.json"

        self.device_identity = self._load_or_create_device_identity()

    def check_gateway_available(self) -> bool:
        """Check whether the Gateway can be reached over WebSocket."""
        probe = self.probe_gateway_connection()
        return bool(probe["ok"])

    def probe_gateway_connection(self) -> Dict[str, Any]:
        """Verify whether the WebSocket handshake succeeds."""
        try:
            hello = self._run_with_pairing_retry(self._probe_gateway_connection_once)
            return {
                "ok": True,
                "detail": "WebSocket connect succeeded",
                "server_version": hello.get("server", {}).get("version"),
                "session_defaults": hello.get("snapshot", {}).get("sessionDefaults"),
                "available_methods": hello.get("features", {}).get("methods", []),
            }
        except Exception as exc:
            return {
                "ok": False,
                "detail": str(exc),
            }

    def _probe_gateway_connection_once(self) -> Dict[str, Any]:
        ws = None
        try:
            ws = self._open_websocket()
            return self._connect(ws)
        finally:
            if ws is not None:
                self._safe_close(ws)

    def probe_chat_capability(self) -> Dict[str, Any]:
        """Verify whether chat-related methods are available and authorized."""
        try:
            response = self._run_with_pairing_retry(self._probe_chat_capability_once)
            return {
                "ok": True,
                "detail": "chat.history request succeeded",
                "response": response,
            }
        except Exception as exc:
            return {
                "ok": False,
                "detail": str(exc),
            }

    def _probe_chat_capability_once(self) -> Dict[str, Any]:
        ws = None
        try:
            ws = self._open_websocket()
            hello = self._connect(ws)

            if "chat.send" not in hello.get("features", {}).get("methods", []):
                raise Exception("Gateway does not expose chat.send")

            session_key = self._build_session_key()
            return self._send_request(
                ws,
                "chat.history",
                {"sessionKey": session_key, "limit": 1},
            )
        finally:
            if ws is not None:
                self._safe_close(ws)

    def send_message(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        stream: bool = False,
        user: Optional[str] = None,
    ) -> str:
        """Send a message through the WebSocket chat API."""
        del model
        del max_tokens
        del stream

        def _send_once() -> str:
            ws = None
            try:
                ws = self._open_websocket()
                self._connect(ws)

                session_key = self._build_session_key(user=user)
                run_id = str(uuid.uuid4())
                request_id = self._send_request_without_waiting(
                    ws,
                    "chat.send",
                    {
                        "sessionKey": session_key,
                        "message": prompt,
                        "deliver": False,
                        "idempotencyKey": run_id,
                    },
                )

                final_text = ""
                partial_text = ""

                while True:
                    message = self._recv_json(ws)
                    message_type = message.get("type")

                    if message_type == "res" and message.get("id") == request_id:
                        if not message.get("ok"):
                            raise self._build_request_error(message)
                        continue

                    if message_type != "event" or message.get("event") != "chat":
                        continue

                    payload = message.get("payload", {})
                    if payload.get("sessionKey") != session_key:
                        continue
                    if payload.get("runId") != run_id:
                        continue

                    state = payload.get("state")
                    if state == "delta":
                        delta_text = self._extract_chat_text(payload.get("message"))
                        if delta_text:
                            partial_text = delta_text
                        continue

                    if state == "final":
                        final_text = self._extract_chat_text(payload.get("message")) or partial_text
                        break

                    if state == "aborted":
                        final_text = self._extract_chat_text(payload.get("message")) or partial_text
                        break

                    if state == "error":
                        error_message = payload.get("errorMessage") or "Gateway chat error"
                        raise Exception(error_message)

                return final_text.strip()
            finally:
                if ws is not None:
                    self._safe_close(ws)

        try:
            return self._run_with_pairing_retry(_send_once)
        except WebSocketTimeoutException as exc:
            raise Exception("Gateway WebSocket request timed out") from exc
        except Exception as exc:
            raise Exception(f"Gateway WebSocket request failed: {exc}") from exc

    def get_info(self) -> Dict[str, Any]:
        """Return the current Gateway configuration."""
        return {
            "use_gateway": self.use_gateway,
            "gateway_url": self.gateway_url,
            "ws_url": self.ws_url,
            "http_url": self.http_url,
            "agent_id": self.agent_id,
            "session_key": self._build_session_key(),
            "default_model": self.default_model,
            "default_user": self.default_user,
            "client_id": self.client_id,
            "client_mode": self.client_mode,
            "requested_scopes": self.requested_scopes,
            "device_id": self.device_identity["deviceId"],
            "state_dir": str(self.state_dir),
            "auto_approve_pairing": self.auto_approve_pairing,
            "has_token": bool(self.gateway_token),
            "has_password": bool(self.gateway_password),
            "has_cli": bool(self.openclaw_cli_path),
            "available": self.check_gateway_available() if self.use_gateway else None,
            "connection_probe": self.probe_gateway_connection() if self.use_gateway else None,
            "chat_probe": self.probe_chat_capability() if self.use_gateway else None,
        }

    def approve_local_pairing(self) -> Dict[str, Any]:
        """Approve the pending pairing request for the current workspace device."""
        if not self.openclaw_cli_path:
            return {
                "ok": False,
                "detail": "OpenClaw CLI was not found, so local pairing approval is unavailable.",
            }

        pending_info = self._list_pending_pairing_requests()
        if not pending_info["ok"]:
            return pending_info

        pending_requests = pending_info.get("pending", [])
        device_id = self.device_identity["deviceId"]
        match = next(
            (item for item in pending_requests if item.get("deviceId") == device_id),
            None,
        )
        if not match:
            return {
                "ok": False,
                "detail": (
                    f"No pending pairing request was found for device {device_id}. "
                    "Try connecting once more to create the request."
                ),
            }

        command = [
            str(self.openclaw_cli_path),
            "devices",
            "approve",
            match["requestId"],
            "--json",
            "--url",
            self.ws_url,
        ]
        if self.gateway_token:
            command.extend(["--token", self.gateway_token])
        if self.gateway_password:
            command.extend(["--password", self.gateway_password])

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=self._build_openclaw_cli_env(),
                check=False,
            )
        except Exception as exc:
            return {"ok": False, "detail": f"OpenClaw CLI approval failed: {exc}"}

        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "").strip() or "unknown CLI error"
            return {
                "ok": False,
                "detail": f"OpenClaw CLI approval failed: {error_text}",
            }

        payload = self._parse_json_output(result.stdout)
        detail = f"Approved pairing request {match['requestId']} for device {device_id}."
        if isinstance(payload, dict) and payload.get("requestId"):
            detail = f"Approved pairing request {payload['requestId']} for device {device_id}."

        return {
            "ok": True,
            "detail": detail,
            "request_id": match["requestId"],
            "device_id": device_id,
            "response": payload,
        }

    def _open_websocket(self):
        return websocket.create_connection(self.ws_url, timeout=self.timeout)

    def _connect(self, ws) -> Dict[str, Any]:
        nonce = self._await_connect_challenge(ws)
        connect_id = self._send_request_without_waiting(ws, "connect", self._build_connect_params(nonce))

        while True:
            message = self._recv_json(ws)
            message_type = message.get("type")

            if message_type == "event" and message.get("event") == "connect.challenge":
                continue

            if message_type == "res" and message.get("id") == connect_id:
                if not message.get("ok"):
                    raise self._build_request_error(message)

                payload = message.get("payload", {})
                self._store_device_token(payload.get("auth"))
                return payload

    def _await_connect_challenge(self, ws) -> str:
        started_at = time.time()
        while time.time() - started_at < self.timeout:
            message = self._recv_json(ws)
            if message.get("type") != "event" or message.get("event") != "connect.challenge":
                continue

            payload = message.get("payload") or {}
            nonce = str(payload.get("nonce", "")).strip()
            if nonce:
                return nonce

            raise Exception("Gateway connect challenge is missing a nonce")

        raise Exception("Timed out waiting for Gateway connect challenge")

    def _build_connect_params(self, nonce: str) -> Dict[str, Any]:
        signed_at_ms = int(time.time() * 1000)
        signature_token = self.gateway_token or None
        device_token = self._load_stored_device_token()

        params: Dict[str, Any] = {
            "minProtocol": 3,
            "maxProtocol": 3,
            "client": {
                "id": self.client_id,
                "version": "openclaw-file-manager",
                "platform": "python",
                "mode": self.client_mode,
                "instanceId": str(uuid.uuid4()),
            },
            "role": "operator",
            "scopes": self.requested_scopes,
            "caps": ["tool-events"],
            "userAgent": "openclaw-file-manager/python",
            "locale": "zh-CN",
            "device": self._build_device_signature(nonce, signed_at_ms, signature_token),
        }

        auth: Dict[str, Any] = {}
        if self.gateway_token:
            auth["token"] = self.gateway_token
        elif device_token:
            auth["token"] = device_token

        if self.gateway_password:
            auth["password"] = self.gateway_password

        if auth:
            params["auth"] = auth

        return params

    def _build_device_signature(
        self,
        nonce: str,
        signed_at_ms: int,
        signature_token: Optional[str],
    ) -> Dict[str, Any]:
        payload = self._build_device_auth_payload_v3(
            device_id=self.device_identity["deviceId"],
            client_id=self.client_id,
            client_mode=self.client_mode,
            role="operator",
            scopes=self.requested_scopes,
            signed_at_ms=signed_at_ms,
            token=signature_token,
            nonce=nonce,
            platform="python",
            device_family="",
        )

        private_key = serialization.load_pem_private_key(
            self.device_identity["privateKeyPem"].encode("utf-8"),
            password=None,
        )
        signature = private_key.sign(payload.encode("utf-8"))

        return {
            "id": self.device_identity["deviceId"],
            "publicKey": self._public_key_raw_base64url(self.device_identity["publicKeyPem"]),
            "signature": self._base64url_encode(signature),
            "signedAt": signed_at_ms,
            "nonce": nonce,
        }

    def _send_request(self, ws, method: str, params: Dict[str, Any]) -> Any:
        request_id = self._send_request_without_waiting(ws, method, params)

        while True:
            message = self._recv_json(ws)
            if message.get("type") == "res" and message.get("id") == request_id:
                if not message.get("ok"):
                    raise self._build_request_error(message)
                return message.get("payload")

    def _send_request_without_waiting(self, ws, method: str, params: Dict[str, Any]) -> str:
        request_id = str(uuid.uuid4())
        ws.send(
            json.dumps(
                {
                    "type": "req",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
                ensure_ascii=False,
            )
        )
        return request_id

    def _recv_json(self, ws) -> Dict[str, Any]:
        raw_message = ws.recv()
        return json.loads(raw_message)

    def _build_request_error(self, message: Dict[str, Any]) -> Exception:
        error = message.get("error", {})
        code = error.get("code")
        detail = error.get("details")
        summary = error.get("message") or "unknown gateway error"

        detail_code = None
        if detail and isinstance(detail, dict):
            detail_code = detail.get("code")

        if code == "INVALID_REQUEST" and "missing scope" in summary:
            return Exception(
                f"{summary}. Confirm the device is paired and that the current auth grants the requested scopes."
            )

        if code == "NOT_PAIRED" or detail_code == "PAIRING_REQUIRED":
            return Exception(
                "pairing required. Approve the pending device request and retry. "
                "This project can auto-approve locally when GATEWAY_AUTO_APPROVE_LOCAL_PAIRING=true."
            )

        if detail_code:
            return Exception(f"{summary} ({detail_code})")

        return Exception(summary)

    def _build_session_key(self, user: Optional[str] = None) -> str:
        if self.session_key:
            return self.session_key

        stable_user = (user or self.default_user or "main").strip() or "main"
        return f"agent:{self.agent_id}:{stable_user}"

    def _extract_chat_text(self, message: Any) -> str:
        if message is None:
            return ""

        if isinstance(message, str):
            return message

        if not isinstance(message, dict):
            return str(message)

        content = message.get("content")
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            chunks: List[str] = []
            for item in content:
                if isinstance(item, str):
                    chunks.append(item)
                    continue

                if not isinstance(item, dict):
                    chunks.append(str(item))
                    continue

                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    chunks.append(item["text"])
                elif isinstance(item.get("text"), str):
                    chunks.append(item["text"])
            return "".join(chunks)

        if isinstance(message.get("text"), str):
            return message["text"]

        return json.dumps(message, ensure_ascii=False)

    def _parse_scopes(self, raw_scopes: str) -> List[str]:
        scopes = [scope.strip() for scope in raw_scopes.split(",") if scope.strip()]
        return scopes or ["operator.read", "operator.write"]

    def _normalize_ws_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        if parsed.scheme in ("ws", "wss"):
            return raw_url
        if parsed.scheme in ("http", "https"):
            ws_scheme = "wss" if parsed.scheme == "https" else "ws"
            return urlunparse(parsed._replace(scheme=ws_scheme))
        return f"ws://{raw_url.lstrip('/')}"

    def _normalize_http_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        if parsed.scheme in ("http", "https"):
            return raw_url.rstrip("/")
        if parsed.scheme in ("ws", "wss"):
            http_scheme = "https" if parsed.scheme == "wss" else "http"
            return urlunparse(parsed._replace(scheme=http_scheme)).rstrip("/")
        return f"http://{raw_url.lstrip('/')}".rstrip("/")

    def _safe_close(self, ws) -> None:
        try:
            ws.close()
        except Exception:
            pass

    def _resolve_openclaw_cli_path(self) -> Optional[Path]:
        raw_cli_path = os.getenv("OPENCLAW_CLI_PATH", "").strip()
        if raw_cli_path:
            cli_path = Path(raw_cli_path)
            if cli_path.exists():
                return cli_path

        cli_from_path = shutil.which("openclaw")
        if cli_from_path:
            return Path(cli_from_path)

        windows_cli = Path.home() / "AppData" / "Roaming" / "npm" / "openclaw.cmd"
        if windows_cli.exists():
            return windows_cli

        return None

    def _run_with_pairing_retry(self, operation: Callable[[], Any]) -> Any:
        last_error: Optional[Exception] = None

        for attempt in range(2):
            try:
                return operation()
            except Exception as exc:
                last_error = exc
                if (
                    attempt == 0
                    and self.auto_approve_pairing
                    and self._looks_like_pairing_required(exc)
                ):
                    approval = self.approve_local_pairing()
                    if approval.get("ok"):
                        continue

                    detail = approval.get("detail") or "unknown pairing approval error"
                    raise Exception(f"{exc}. Automatic local pairing approval failed: {detail}") from exc

                raise

        if last_error is not None:
            raise last_error

        raise Exception("Gateway operation failed")

    def _looks_like_pairing_required(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "pairing required" in message
            or "not_paired" in message
            or "not paired" in message
            or "pairing_required" in message
        )

    def _load_or_create_device_identity(self) -> Dict[str, str]:
        identity = self._load_device_identity()
        if identity:
            return identity

        self.identity_path.parent.mkdir(parents=True, exist_ok=True)

        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        public_key_pem = public_key.public_bytes(
            Encoding.PEM,
            PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        private_key_pem = private_key.private_bytes(
            Encoding.PEM,
            PrivateFormat.PKCS8,
            NoEncryption(),
        ).decode("utf-8")

        public_key_raw = public_key.public_bytes(
            Encoding.Raw,
            PublicFormat.Raw,
        )
        device_id = hashlib.sha256(public_key_raw).hexdigest()

        stored = {
            "version": 1,
            "deviceId": device_id,
            "publicKeyPem": public_key_pem,
            "privateKeyPem": private_key_pem,
            "createdAtMs": int(time.time() * 1000),
        }
        self.identity_path.write_text(
            json.dumps(stored, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        return {
            "deviceId": device_id,
            "publicKeyPem": public_key_pem,
            "privateKeyPem": private_key_pem,
        }

    def _load_device_identity(self) -> Optional[Dict[str, str]]:
        if not self.identity_path.exists():
            return None

        try:
            stored = json.loads(self.identity_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        public_key_pem = stored.get("publicKeyPem")
        private_key_pem = stored.get("privateKeyPem")
        if not isinstance(public_key_pem, str) or not isinstance(private_key_pem, str):
            return None

        try:
            public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
            public_key_raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        except Exception:
            return None

        device_id = hashlib.sha256(public_key_raw).hexdigest()
        if stored.get("deviceId") != device_id:
            stored["deviceId"] = device_id
            self.identity_path.write_text(
                json.dumps(stored, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        return {
            "deviceId": device_id,
            "publicKeyPem": public_key_pem,
            "privateKeyPem": private_key_pem,
        }

    def _load_stored_device_token(self, role: str = "operator") -> Optional[str]:
        if not self.device_auth_path.exists():
            return None

        try:
            stored = json.loads(self.device_auth_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        if stored.get("deviceId") != self.device_identity["deviceId"]:
            return None

        tokens = stored.get("tokens")
        if not isinstance(tokens, dict):
            return None

        entry = tokens.get(role)
        if not isinstance(entry, dict):
            return None

        token = entry.get("token")
        return token.strip() if isinstance(token, str) and token.strip() else None

    def _store_device_token(self, auth_info: Any) -> None:
        if not isinstance(auth_info, dict):
            return

        token = auth_info.get("deviceToken")
        if not isinstance(token, str) or not token.strip():
            return

        role = auth_info.get("role")
        normalized_role = role.strip() if isinstance(role, str) and role.strip() else "operator"

        scopes = auth_info.get("scopes")
        if not isinstance(scopes, list):
            scopes = []

        existing = {
            "version": 1,
            "deviceId": self.device_identity["deviceId"],
            "tokens": {},
        }
        if self.device_auth_path.exists():
            try:
                existing = json.loads(self.device_auth_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {
                    "version": 1,
                    "deviceId": self.device_identity["deviceId"],
                    "tokens": {},
                }

        existing["version"] = 1
        existing["deviceId"] = self.device_identity["deviceId"]
        if not isinstance(existing.get("tokens"), dict):
            existing["tokens"] = {}

        existing["tokens"][normalized_role] = {
            "token": token.strip(),
            "role": normalized_role,
            "scopes": sorted({scope for scope in scopes if isinstance(scope, str) and scope.strip()}),
            "updatedAtMs": int(time.time() * 1000),
        }

        self.device_auth_path.parent.mkdir(parents=True, exist_ok=True)
        self.device_auth_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _build_device_auth_payload_v3(
        self,
        *,
        device_id: str,
        client_id: str,
        client_mode: str,
        role: str,
        scopes: List[str],
        signed_at_ms: int,
        token: Optional[str],
        nonce: str,
        platform: str,
        device_family: str,
    ) -> str:
        joined_scopes = ",".join(scopes)
        return "|".join(
            [
                "v3",
                device_id,
                client_id,
                client_mode,
                role,
                joined_scopes,
                str(signed_at_ms),
                token or "",
                nonce,
                platform.strip().lower(),
                device_family.strip().lower(),
            ]
        )

    def _public_key_raw_base64url(self, public_key_pem: str) -> str:
        public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        public_key_raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        return self._base64url_encode(public_key_raw)

    def _base64url_encode(self, payload: bytes) -> str:
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    def _build_openclaw_cli_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        env["OPENCLAW_STATE_DIR"] = str(self.state_dir)
        if self.openclaw_config_path:
            env["OPENCLAW_CONFIG_PATH"] = self.openclaw_config_path
        return env

    def _list_pending_pairing_requests(self) -> Dict[str, Any]:
        if not self.openclaw_cli_path:
            return {
                "ok": False,
                "detail": "OpenClaw CLI was not found, so pairing requests cannot be inspected.",
            }

        command = [str(self.openclaw_cli_path), "devices", "list", "--json"]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=self._build_openclaw_cli_env(),
                check=False,
            )
        except Exception as exc:
            return {"ok": False, "detail": f"OpenClaw CLI pairing list failed: {exc}"}

        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "").strip() or "unknown CLI error"
            return {"ok": False, "detail": f"OpenClaw CLI pairing list failed: {error_text}"}

        payload = self._parse_json_output(result.stdout)
        pending = payload.get("pending") if isinstance(payload, dict) else None
        if not isinstance(pending, list):
            pending = []

        return {
            "ok": True,
            "detail": f"Found {len(pending)} pending pairing request(s).",
            "pending": pending,
            "response": payload,
        }

    def _parse_json_output(self, raw_output: str) -> Any:
        trimmed = (raw_output or "").strip()
        if not trimmed:
            return {}

        return json.loads(trimmed)
