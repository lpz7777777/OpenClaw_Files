import hashlib
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from command_runtime import CommandRuntime
    from gateway_client import GatewayClient
except ImportError:  # pragma: no cover - fallback for root-level imports
    from backend.command_runtime import CommandRuntime
    from backend.gateway_client import GatewayClient


MANAGED_JOB_PREFIX = "OpenClaw Files Sync"
MANAGED_JOB_MARKER = "managed-by=openclaw-files"


class CloudSyncManager:
    def __init__(self):
        self.gateway_client = GatewayClient()
        self.timeout_seconds = max(self.gateway_client.timeout, 60)
        self.openclaw_cli_path = self.gateway_client.openclaw_cli_path
        self.bdpan_runtime = CommandRuntime.resolve(
            command_name="bdpan",
            env_path_var="BDPAN_BIN",
            mode_env_var="BDPAN_CLI_MODE",
            distro_env_var="BDPAN_WSL_DISTRO",
            windows_fallbacks=self._build_bdpan_native_fallbacks(),
        )
        self.bdpan_cli_path = self.bdpan_runtime.display_path
        self.default_timezone = (
            os.getenv("OPENCLAW_SYNC_TZ", "Asia/Shanghai").strip() or "Asia/Shanghai"
        )

    def get_status(self) -> Dict[str, Any]:
        gateway = self.gateway_client.probe_gateway_connection()
        bdpan = self._probe_bdpan_status()
        cron = self._probe_cron_status()
        jobs = self._list_managed_jobs()

        return {
            "success": True,
            "gateway": gateway,
            "bdpan": bdpan,
            "cron": cron,
            "jobs": jobs,
            "default_timezone": self.default_timezone,
        }

    def upload_folder(self, folder_path: str, remote_path: str) -> Dict[str, Any]:
        local_folder = self._validate_local_folder(folder_path)
        normalized_remote_path = self._normalize_remote_path(remote_path)
        folder_name = Path(local_folder).name or "folder"

        if not self.bdpan_cli_path:
            return {
                "success": False,
                "error": "bdpan CLI was not found on this machine.",
                "remote_path": normalized_remote_path,
            }

        bdpan_status = self._probe_bdpan_status()
        if not bdpan_status.get("installed"):
            return {
                "success": False,
                "error": bdpan_status.get("detail")
                or "bdpan CLI was not found on this machine.",
                "remote_path": normalized_remote_path,
            }
        if not bdpan_status.get("authenticated"):
            return {
                "success": False,
                "error": "百度网盘尚未登录或登录已失效，请先完成 bdpan 登录。",
                "remote_path": normalized_remote_path,
                "next_step": "请先在 OpenClaw 或 bdpan 中完成百度网盘登录。",
            }

        try:
            result = self._run_bdpan_upload(local_folder, normalized_remote_path)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "remote_path": normalized_remote_path,
            }

        upload_summary = self._summarize_bdpan_upload_result(
            result,
            local_folder=local_folder,
            remote_path=normalized_remote_path,
        )
        if not upload_summary["success"]:
            return {
                "success": False,
                "summary": upload_summary["summary"],
                "error": upload_summary["error"],
                "remote_path": upload_summary["remote_path"],
                "details": upload_summary["details"],
                "next_step": "请检查网盘路径、登录状态，或稍后重试。",
                "raw_response": result.get("raw"),
            }

        return {
            "success": True,
            "summary": upload_summary["summary"]
            or f"已将文件夹 {folder_name} 上传到百度网盘。",
            "remote_path": upload_summary["remote_path"],
            "details": upload_summary["details"],
            "next_step": "",
            "raw_response": result.get("raw"),
        }

    def create_schedule(
        self,
        folder_path: str,
        remote_path: str,
        cron_expression: str = "",
        *,
        daily_time: str = "",
        timezone: Optional[str] = None,
    ) -> Dict[str, Any]:
        local_folder = self._validate_local_folder(folder_path)
        normalized_remote_path = self._normalize_remote_path(remote_path)
        normalized_cron = (
            self._daily_time_to_cron(daily_time)
            if str(daily_time or "").strip()
            else self._normalize_cron_expression(cron_expression)
        )
        normalized_timezone = (
            (timezone or self.default_timezone).strip() or self.default_timezone
        )

        if not self.gateway_client.openclaw_runtime.available:
            return {
                "success": False,
                "error": "OpenClaw CLI was not found, so scheduled sync jobs cannot be created.",
            }

        if not self.gateway_client.check_gateway_available():
            return {
                "success": False,
                "error": (
                    "OpenClaw Gateway is unavailable at "
                    f"{self.gateway_client.gateway_url}"
                ),
            }

        folder_name = Path(local_folder).name or "folder"
        job_hash = hashlib.sha1(
            f"{local_folder}|{normalized_remote_path}|{normalized_cron}".encode(
                "utf-8"
            )
        ).hexdigest()[:8]
        job_name = f"{MANAGED_JOB_PREFIX} - {folder_name} - {job_hash}"
        description = (
            f"{MANAGED_JOB_MARKER};"
            f"folder={local_folder};"
            f"remote={normalized_remote_path}"
        )
        session_key = f"agent:{self.gateway_client.agent_id}:bdpan-sync-{job_hash}"
        prompt = self._build_upload_prompt(
            local_folder,
            normalized_remote_path,
            scheduled=True,
        )

        command_args = [
            "cron",
            "add",
            "--json",
            "--name",
            job_name,
            "--description",
            description,
            "--cron",
            normalized_cron,
            "--tz",
            normalized_timezone,
            "--agent",
            self.gateway_client.agent_id,
            "--session-key",
            session_key,
            "--light-context",
            "--no-deliver",
            "--expect-final",
            "--timeout-seconds",
            str(max(self.timeout_seconds, 7200)),
            "--message",
            prompt,
            "--url",
            self.gateway_client.ws_url,
        ]

        if self.gateway_client.gateway_token:
            command_args.extend(["--token", self.gateway_client.gateway_token])

        try:
            result = self.gateway_client.run_openclaw_cli(
                command_args,
                timeout=max(self.timeout_seconds, 90),
            )
        except Exception as exc:
            return {
                "success": False,
                "error": f"Failed to create the OpenClaw cron job: {exc}",
            }

        if result.returncode != 0:
            error_text = (
                (result.stderr or result.stdout or "").strip() or "unknown CLI error"
            )
            return {
                "success": False,
                "error": f"Failed to create the OpenClaw cron job: {error_text}",
            }

        payload = self._parse_json_text(result.stdout)
        jobs = self._list_managed_jobs()
        created_job = self._find_job_by_name(jobs, job_name)
        if created_job is None and isinstance(payload, dict):
            created_job = self._normalize_job(payload)

        return {
            "success": True,
            "summary": f"Scheduled sync created for {folder_name}.",
            "job_name": job_name,
            "cron_expression": normalized_cron,
            "daily_time": self._cron_to_daily_time(normalized_cron),
            "timezone": normalized_timezone,
            "remote_path": normalized_remote_path,
            "job": created_job,
            "raw_response": payload,
            "jobs": jobs,
        }

    def remove_schedule(self, job_id: str) -> Dict[str, Any]:
        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            raise ValueError("A scheduled job id is required.")

        jobs = self._list_managed_jobs()
        target_job = self._find_job_by_id(jobs, normalized_job_id)
        if target_job is None:
            return {
                "success": False,
                "error": f"Scheduled job was not found: {normalized_job_id}",
            }

        if not self.gateway_client.openclaw_runtime.available:
            return {
                "success": False,
                "error": "OpenClaw CLI was not found, so scheduled sync jobs cannot be removed.",
            }

        command_args = [
            "cron",
            "rm",
            "--json",
            normalized_job_id,
            "--url",
            self.gateway_client.ws_url,
        ]
        if self.gateway_client.gateway_token:
            command_args.extend(["--token", self.gateway_client.gateway_token])

        try:
            result = self.gateway_client.run_openclaw_cli(
                command_args,
                timeout=max(self.timeout_seconds, 30),
            )
        except Exception as exc:
            return {
                "success": False,
                "error": f"Failed to remove the OpenClaw cron job: {exc}",
            }

        if result.returncode != 0:
            error_text = (
                (result.stderr or result.stdout or "").strip() or "unknown CLI error"
            )
            return {
                "success": False,
                "error": f"Failed to remove the OpenClaw cron job: {error_text}",
            }

        jobs_after_removal = self._list_managed_jobs()
        return {
            "success": True,
            "summary": f"Scheduled sync removed for {target_job.get('name') or normalized_job_id}.",
            "removed_job_id": normalized_job_id,
            "job": target_job,
            "jobs": jobs_after_removal,
        }

    def _validate_local_folder(self, folder_path: str) -> str:
        normalized = os.path.abspath(str(folder_path or "").strip())
        if not normalized:
            raise ValueError("A local folder must be selected first.")
        if not os.path.isdir(normalized):
            raise ValueError(f"Selected path is not a folder: {normalized}")
        return normalized

    def _normalize_remote_path(self, remote_path: str) -> str:
        raw_value = str(remote_path or "").strip().replace("\\", "/")
        if not raw_value:
            raise ValueError("A Baidu Netdisk target path is required.")

        if raw_value.startswith("/apps/bdpan/"):
            raw_value = raw_value[len("/apps/bdpan/") :]
        elif raw_value.startswith("/apps/bdpan"):
            raw_value = raw_value[len("/apps/bdpan") :].lstrip("/")
        elif raw_value.startswith("/"):
            raw_value = raw_value.lstrip("/")

        normalized = re.sub(r"/+", "/", raw_value).strip("/")
        if not normalized:
            raise ValueError("The Baidu Netdisk target path cannot be empty.")
        if normalized.startswith("..") or "/../" in f"/{normalized}/":
            raise ValueError("The Baidu Netdisk target path cannot escape /apps/bdpan/.")

        return f"{normalized}/"

    def _normalize_cron_expression(self, cron_expression: str) -> str:
        normalized = re.sub(r"\s+", " ", str(cron_expression or "").strip())
        parts = [part for part in normalized.split(" ") if part]
        if len(parts) not in (5, 6):
            raise ValueError("Cron expression must contain 5 or 6 fields.")
        return " ".join(parts)

    def _daily_time_to_cron(self, daily_time: str) -> str:
        normalized = str(daily_time or "").strip()
        match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", normalized)
        if not match:
            raise ValueError("Daily sync time must use HH:MM 24-hour format.")

        hour = int(match.group(1))
        minute = int(match.group(2))
        return f"{minute} {hour} * * *"

    def _cron_to_daily_time(self, cron_expression: str) -> str:
        normalized = self._normalize_cron_expression(cron_expression)
        parts = normalized.split(" ")
        if len(parts) == 5:
            minute, hour, day_of_month, month, day_of_week = parts
        else:
            _, minute, hour, day_of_month, month, day_of_week = parts

        if day_of_month != "*" or month != "*" or day_of_week != "*":
            return ""
        if not minute.isdigit() or not hour.isdigit():
            return ""

        minute_value = int(minute)
        hour_value = int(hour)
        if not (0 <= minute_value <= 59 and 0 <= hour_value <= 23):
            return ""

        return f"{hour_value:02d}:{minute_value:02d}"

    def _parse_json_text(self, response_text: str) -> Dict[str, Any]:
        text = str(response_text or "").strip()
        if not text:
            raise ValueError("Command returned an empty response.")

        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Response does not contain a JSON object.")

        candidate = text[start : end + 1]
        payload = json.loads(candidate)
        if not isinstance(payload, dict):
            raise ValueError("Response JSON must be an object.")
        return payload

    def _normalize_string_list(self, values: Any) -> List[str]:
        if not isinstance(values, list):
            return []
        normalized = []
        for item in values:
            text = str(item or "").strip()
            if text:
                normalized.append(text)
        return normalized

    def _to_bdpan_cli_remote_path(self, remote_path: str) -> str:
        return self._normalize_remote_path(remote_path).rstrip("/")

    def _to_bdpan_cli_local_path(self, folder_path: str) -> str:
        normalized = os.path.abspath(folder_path)
        translated = self.bdpan_runtime.translate_path(normalized)
        separator = "/" if self.bdpan_runtime.mode == "wsl" else os.sep
        if translated.endswith(separator):
            return translated
        return translated + separator

    def _build_upload_prompt(self, folder_path: str, remote_path: str, *, scheduled: bool) -> str:
        mode_note = (
            "这是一个由 OpenClaw cron 触发的无人值守定时同步任务。"
            if scheduled
            else "这是桌面应用里用户刚刚手动触发的一次上传任务。"
        )
        confirmation_note = (
            "本任务已经获得用户预授权；如果远程路径已经存在，请直接继续上传并按覆盖或合并方式处理，不要再次追问。"
        )
        cli_remote_path = self._to_bdpan_cli_remote_path(remote_path)
        cli_local_path = self._to_bdpan_cli_local_path(folder_path)

        return f"""请使用已安装的 bdpan-storage skill，把本地文件夹上传到百度网盘。
{mode_note}

硬性要求：
1. 必须使用 bdpan-storage skill，不要改用其他上传方案。
2. 本地文件夹路径：{cli_local_path}
3. 目标网盘相对路径：{remote_path}
4. 这是文件夹上传，请严格按 bdpan-storage 的文件夹上传规则处理。
5. 优先直接执行等价命令：bdpan upload "{cli_local_path}" "{cli_remote_path}"
6. {confirmation_note}
7. 如果百度网盘未登录、登录失效、权限不足或命令执行失败，请直接返回失败结果和原因，不要输出敏感 token。
8. 除最终 JSON 外，不要输出解释、Markdown 或代码块。

只返回严格 JSON，格式如下：
{{"success":true,"summary":"一句话概述","remote_path":"{remote_path}","details":["细节1","细节2"],"next_step":""}}

如果失败，请返回：
{{"success":false,"summary":"失败原因","remote_path":"{remote_path}","details":["细节1"],"next_step":"建议下一步"}}
"""

    def _summarize_bdpan_upload_result(
        self,
        result: Dict[str, Any],
        *,
        local_folder: str,
        remote_path: str,
    ) -> Dict[str, Any]:
        payload = result.get("payload") or {}
        payload_data = payload.get("data")
        if not isinstance(payload_data, dict):
            payload_data = {}

        resolved_local_path = (
            str(payload_data.get("local") or payload.get("local_path") or local_folder).strip()
            or local_folder
        )
        resolved_remote_path = (
            str(payload_data.get("remote") or payload.get("remote_path") or remote_path).strip()
            or remote_path
        )
        payload_message = str(
            payload_data.get("message") or payload.get("message") or ""
        ).strip()
        payload_error = str(payload.get("error") or "").strip()
        payload_code = payload.get("code")
        view_url = str(
            payload_data.get("viewUrl") or payload.get("view_url") or ""
        ).strip()

        details = [
            f"本地目录：{resolved_local_path.rstrip(os.sep)}",
            f"网盘路径：{resolved_remote_path}",
        ]
        if view_url:
            details.append(f"查看链接：{view_url}")

        upload_succeeded = result["returncode"] == 0
        if isinstance(payload_code, int):
            upload_succeeded = upload_succeeded and payload_code == 0
        if payload_error:
            upload_succeeded = False

        normalized_remote = (
            resolved_remote_path
            if resolved_remote_path.endswith("/")
            else f"{resolved_remote_path}/"
        )

        if upload_succeeded:
            return {
                "success": True,
                "summary": payload_message or "百度网盘上传完成。",
                "error": "",
                "remote_path": normalized_remote,
                "details": details,
            }

        error_text = payload_error or result.get("error") or payload_message or "unknown bdpan error"
        return {
            "success": False,
            "summary": f"百度网盘上传失败：{error_text}",
            "error": error_text,
            "remote_path": normalized_remote,
            "details": details + self._normalize_string_list(result.get("details")),
        }

    def _run_bdpan_upload(self, folder_path: str, remote_path: str) -> Dict[str, Any]:
        result = self._run_bdpan_cli(
            [
                "upload",
                self._to_bdpan_cli_local_path(folder_path),
                self._to_bdpan_cli_remote_path(remote_path),
                "--json",
            ],
            timeout=max(self.timeout_seconds, 7200),
        )

        stdout_text = (result.stdout or "").strip()
        stderr_text = (result.stderr or "").strip()
        payload = None
        if stdout_text:
            try:
                payload = self._parse_json_text(stdout_text)
            except ValueError:
                payload = None

        details = []
        if stdout_text:
            details.append(stdout_text)
        if stderr_text:
            details.append(stderr_text)

        return {
            "returncode": result.returncode,
            "payload": payload or {},
            "details": details,
            "error": stderr_text or stdout_text,
            "raw": {"stdout": stdout_text, "stderr": stderr_text},
        }

    def _probe_bdpan_status(self) -> Dict[str, Any]:
        if not self.bdpan_runtime.available:
            return {
                "installed": False,
                "authenticated": False,
                "detail": "bdpan CLI was not found on this machine.",
            }

        try:
            result = self._run_bdpan_cli(["whoami", "--json"], timeout=20)
        except Exception as exc:
            return {
                "installed": True,
                "authenticated": False,
                "detail": f"Failed to query bdpan login status: {exc}",
                "path": self.bdpan_cli_path,
            }

        if result.returncode != 0:
            error_text = (
                (result.stderr or result.stdout or "").strip() or "unknown bdpan error"
            )
            return {
                "installed": True,
                "authenticated": False,
                "detail": error_text,
                "path": self.bdpan_cli_path,
            }

        payload = self._parse_json_text(result.stdout)
        return {
            "installed": True,
            "authenticated": bool(payload.get("authenticated")),
            "has_valid_token": bool(payload.get("has_valid_token")),
            "username": str(payload.get("username") or "").strip(),
            "expires_at": str(payload.get("expires_at") or "").strip(),
            "token_expires_in": str(payload.get("token_expires_in") or "").strip(),
            "detail": "bdpan login status loaded.",
            "path": self.bdpan_cli_path,
        }

    def _probe_cron_status(self) -> Dict[str, Any]:
        if not self.gateway_client.openclaw_runtime.available:
            return {
                "available": False,
                "enabled": False,
                "detail": "OpenClaw CLI was not found on this machine.",
            }

        try:
            command_args = [
                "cron",
                "status",
                "--json",
                "--url",
                self.gateway_client.ws_url,
            ]
            if self.gateway_client.gateway_token:
                command_args.extend(["--token", self.gateway_client.gateway_token])

            result = self.gateway_client.run_openclaw_cli(command_args, timeout=20)
        except Exception as exc:
            return {
                "available": True,
                "enabled": False,
                "detail": f"Failed to query cron status: {exc}",
            }

        if result.returncode != 0:
            error_text = (
                (result.stderr or result.stdout or "").strip() or "unknown cron error"
            )
            return {
                "available": True,
                "enabled": False,
                "detail": error_text,
            }

        payload = self._parse_json_text(result.stdout)
        return {
            "available": True,
            "enabled": bool(payload.get("enabled")),
            "jobs": int(payload.get("jobs") or 0),
            "store_path": str(payload.get("storePath") or "").strip(),
            "detail": "OpenClaw cron status loaded.",
        }

    def _list_managed_jobs(self) -> List[Dict[str, Any]]:
        if not self.gateway_client.openclaw_runtime.available:
            return []

        try:
            command_args = [
                "cron",
                "list",
                "--json",
                "--url",
                self.gateway_client.ws_url,
            ]
            if self.gateway_client.gateway_token:
                command_args.extend(["--token", self.gateway_client.gateway_token])

            result = self.gateway_client.run_openclaw_cli(command_args, timeout=20)
        except Exception:
            return []

        if result.returncode != 0:
            return []

        try:
            payload = self._parse_json_text(result.stdout)
        except ValueError:
            return []

        raw_jobs = payload.get("jobs")
        if not isinstance(raw_jobs, list):
            return []

        managed_jobs = []
        for raw_job in raw_jobs:
            if not isinstance(raw_job, dict):
                continue

            name = str(raw_job.get("name") or "").strip()
            description = str(raw_job.get("description") or "").strip()
            if (
                not name.startswith(MANAGED_JOB_PREFIX)
                and MANAGED_JOB_MARKER not in description
            ):
                continue

            managed_jobs.append(self._normalize_job(raw_job))

        return managed_jobs

    def _normalize_job(self, raw_job: Dict[str, Any]) -> Dict[str, Any]:
        description = str(raw_job.get("description") or "").strip()
        metadata = self._parse_job_metadata(description)
        schedule = raw_job.get("schedule")
        if not isinstance(schedule, dict):
            schedule = {}
        state = raw_job.get("state")
        if not isinstance(state, dict):
            state = {}

        enabled = raw_job.get("enabled")
        if isinstance(enabled, bool):
            enabled_value = enabled
        else:
            enabled_value = not bool(raw_job.get("disabled"))

        next_run_value = (
            raw_job.get("nextRunAt")
            or raw_job.get("nextRunAtIso")
            or raw_job.get("nextWakeAt")
            or state.get("nextRunAt")
            or state.get("nextRunAtIso")
            or self._format_timestamp(state.get("nextRunAtMs"))
            or ""
        )

        return {
            "id": str(raw_job.get("id") or raw_job.get("jobId") or "").strip(),
            "name": str(raw_job.get("name") or "").strip(),
            "description": description,
            "cron": str(
                raw_job.get("cron") or raw_job.get("expr") or schedule.get("expr") or ""
            ).strip(),
            "timezone": str(
                raw_job.get("tz") or raw_job.get("timezone") or schedule.get("tz") or ""
            ).strip(),
            "enabled": enabled_value,
            "next_run_at": str(next_run_value).strip(),
            "folder_path": metadata.get("folder_path", ""),
            "remote_path": metadata.get("remote_path", ""),
            "daily_time": self._cron_to_daily_time(
                str(
                    raw_job.get("cron")
                    or raw_job.get("expr")
                    or schedule.get("expr")
                    or ""
                ).strip()
            )
            if str(
                raw_job.get("cron") or raw_job.get("expr") or schedule.get("expr") or ""
            ).strip()
            else "",
        }

    def _parse_job_metadata(self, description: str) -> Dict[str, str]:
        metadata = {"folder_path": "", "remote_path": ""}
        if not description:
            return metadata

        for part in description.split(";"):
            piece = part.strip()
            if piece.startswith("folder="):
                metadata["folder_path"] = piece[len("folder=") :].strip()
            elif piece.startswith("remote="):
                metadata["remote_path"] = piece[len("remote=") :].strip()
        return metadata

    def _find_job_by_name(
        self,
        jobs: List[Dict[str, Any]],
        job_name: str,
    ) -> Optional[Dict[str, Any]]:
        for job in jobs:
            if job.get("name") == job_name:
                return job
        return None

    def _find_job_by_id(
        self,
        jobs: List[Dict[str, Any]],
        job_id: str,
    ) -> Optional[Dict[str, Any]]:
        normalized_job_id = str(job_id or "").strip()
        for job in jobs:
            if str(job.get("id") or "").strip() == normalized_job_id:
                return job
        return None

    def _format_timestamp(self, value: Any) -> str:
        if not isinstance(value, (int, float)) or value <= 0:
            return ""
        return datetime.fromtimestamp(value / 1000).isoformat(
            sep=" ",
            timespec="seconds",
        )

    def _build_bdpan_native_fallbacks(self) -> List[Path]:
        home_dir = Path.home()
        candidates = []

        current_version_file = home_dir / ".local" / "bdpan" / "current-version"
        if current_version_file.exists():
            try:
                version = current_version_file.read_text(encoding="utf-8").strip()
            except Exception:
                version = ""

            if version:
                version_dir = home_dir / ".local" / "bdpan" / "versions" / version
                candidates.extend(
                    [
                        version_dir / "bdpan.exe",
                        version_dir / "bdpan",
                    ]
                )

        candidates.extend(
            [
                home_dir / ".local" / "bin" / "bdpan",
                home_dir / ".local" / "bin" / "bdpan.exe",
            ]
        )
        return candidates

    def _run_bdpan_cli(
        self,
        args: List[str],
        *,
        timeout: int,
    ):
        if not self.bdpan_runtime.available:
            raise RuntimeError("bdpan CLI is unavailable")

        return subprocess.run(
            self.bdpan_runtime.build_command(args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=self.bdpan_runtime.build_env(),
            check=False,
        )
