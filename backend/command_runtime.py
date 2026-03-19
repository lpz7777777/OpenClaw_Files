import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence


@dataclass
class CommandRuntime:
    mode: str
    executable: str
    display_path: str
    wsl_executable: str = ""
    wsl_distro: str = ""

    @property
    def available(self) -> bool:
        return bool(self.executable)

    def translate_path(self, raw_path: str) -> str:
        value = str(raw_path or "").strip()
        if not value or self.mode != "wsl":
            return value
        return windows_path_to_wsl(value)

    def build_command(
        self,
        args: Sequence[str],
        *,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        normalized_args = [str(arg) for arg in args]
        if self.mode != "wsl":
            return [self.executable, *normalized_args]

        command = [self.wsl_executable or "wsl.exe"]
        if self.wsl_distro:
            command.extend(["-d", self.wsl_distro])
        command.append("--")

        normalized_env = {
            str(key): str(value)
            for key, value in (extra_env or {}).items()
            if str(value or "").strip()
        }
        if normalized_env:
            command.append("env")
            for key, value in normalized_env.items():
                command.append(f"{key}={value}")

        command.append(self.executable)
        command.extend(normalized_args)
        return command

    def build_env(
        self,
        *,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        env = os.environ.copy()
        if self.mode != "wsl" and extra_env:
            env.update({str(key): str(value) for key, value in extra_env.items()})
        return env

    @classmethod
    def unavailable(cls) -> "CommandRuntime":
        return cls(mode="missing", executable="", display_path="")

    @classmethod
    def resolve(
        cls,
        *,
        command_name: str,
        env_path_var: str,
        mode_env_var: str,
        distro_env_var: str,
        windows_fallbacks: Optional[Sequence[Path]] = None,
    ) -> "CommandRuntime":
        requested_mode = str(os.getenv(mode_env_var, "auto") or "auto").strip().lower()
        if requested_mode not in {"auto", "native", "wsl"}:
            requested_mode = "auto"

        raw_env_path = str(os.getenv(env_path_var, "")).strip()
        wsl_distro = str(os.getenv(distro_env_var, "")).strip()

        if requested_mode in {"auto", "native"}:
            native_path = resolve_native_command(
                command_name=command_name,
                raw_env_path=raw_env_path,
                windows_fallbacks=windows_fallbacks,
            )
            if native_path:
                return cls(
                    mode="native",
                    executable=native_path,
                    display_path=native_path,
                )

        if requested_mode in {"auto", "wsl"}:
            wsl_executable = resolve_wsl_executable()
            if wsl_executable:
                wsl_command = resolve_wsl_command(
                    command_name=command_name,
                    raw_env_path=raw_env_path,
                    wsl_executable=wsl_executable,
                    wsl_distro=wsl_distro,
                )
                if wsl_command:
                    distro_label = wsl_distro or "default"
                    return cls(
                        mode="wsl",
                        executable=wsl_command,
                        display_path=f"wsl:{distro_label}:{wsl_command}",
                        wsl_executable=wsl_executable,
                        wsl_distro=wsl_distro,
                    )

        return cls.unavailable()


def resolve_native_command(
    *,
    command_name: str,
    raw_env_path: str,
    windows_fallbacks: Optional[Sequence[Path]] = None,
) -> str:
    if raw_env_path:
        candidate = Path(raw_env_path)
        if candidate.exists():
            return str(candidate)

    cli_from_path = shutil.which(command_name)
    if cli_from_path:
        return str(Path(cli_from_path))

    for candidate in windows_fallbacks or []:
        if candidate.exists():
            return str(candidate)

    return ""


def resolve_wsl_executable() -> str:
    for candidate_name in ("wsl.exe", "wsl"):
        candidate = shutil.which(candidate_name)
        if candidate:
            return candidate

    system32_candidate = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "wsl.exe"
    if system32_candidate.exists():
        return str(system32_candidate)

    return ""


def resolve_wsl_command(
    *,
    command_name: str,
    raw_env_path: str,
    wsl_executable: str,
    wsl_distro: str,
) -> str:
    explicit_command = raw_env_path if looks_like_wsl_command(raw_env_path) else command_name
    probe_target = shlex.quote(explicit_command)

    command = [wsl_executable]
    if wsl_distro:
        command.extend(["-d", wsl_distro])
    command.extend(["--", "sh", "-lc", f"command -v {probe_target}"])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except Exception:
        return ""

    if result.returncode != 0:
        return ""

    return (result.stdout or "").strip().splitlines()[0].strip()


def looks_like_wsl_command(raw_value: str) -> bool:
    value = str(raw_value or "").strip()
    if not value:
        return False

    if value.startswith("/"):
        return True

    if value.startswith("~"):
        return True

    return "/" in value and not re.match(r"^[A-Za-z]:[\\/]", value)


def windows_path_to_wsl(raw_path: str) -> str:
    value = str(raw_path or "").strip()
    if not value:
        return ""

    wsl_network_match = re.match(
        r"^\\\\wsl(?:\$|\.localhost)\\([^\\]+)(\\.*)?$",
        value,
        re.IGNORECASE,
    )
    if wsl_network_match:
        suffix = (wsl_network_match.group(2) or "").replace("\\", "/")
        return suffix or "/"

    normalized = value.replace("\\", "/")
    normalized = re.sub(r"/+", "/", normalized)
    if normalized.startswith("/"):
        return normalized

    drive_match = re.match(r"^([A-Za-z]):/(.*)$", normalized)
    if drive_match:
        drive = drive_match.group(1).lower()
        suffix = drive_match.group(2)
        return f"/mnt/{drive}/{suffix}".rstrip("/")

    return normalized
