import json
import os
import re
import shutil
import tempfile
from collections import Counter
from datetime import datetime

import anthropic
from dotenv import load_dotenv
from json_repair import repair_json

try:
    from gateway_client import GatewayClient
except ImportError:  # pragma: no cover - fallback for root-level imports
    from backend.gateway_client import GatewayClient

load_dotenv(os.getenv("OPENCLAW_FILES_ENV", "").strip() or None)

MAX_SCAN_DEPTH = 5
MAX_FILES_PER_FOLDER = 160
MAX_TOTAL_FILES = 1200
MAX_SUBFOLDERS_PER_FOLDER = 100
MAX_SAMPLE_FILES_PER_FOLDER = 12
MAX_SAMPLE_SUBFOLDERS_PER_FOLDER = 12
ANALYSIS_PROMPT_PROFILES = [
    {
        "name": "full",
        "max_prompt_chars": 22000,
        "folder_limit": 120,
        "file_limit": 280,
        "sample_files": 4,
        "sample_subfolders": 4,
        "min_folder_limit": 48,
        "min_file_limit": 96,
    },
    {
        "name": "compact",
        "max_prompt_chars": 16000,
        "folder_limit": 80,
        "file_limit": 180,
        "sample_files": 2,
        "sample_subfolders": 2,
        "min_folder_limit": 32,
        "min_file_limit": 72,
    },
    {
        "name": "small",
        "max_prompt_chars": 12000,
        "folder_limit": 48,
        "file_limit": 110,
        "sample_files": 1,
        "sample_subfolders": 1,
        "min_folder_limit": 20,
        "min_file_limit": 48,
    },
    {
        "name": "tiny",
        "max_prompt_chars": 9000,
        "folder_limit": 28,
        "file_limit": 70,
        "sample_files": 0,
        "sample_subfolders": 0,
        "min_folder_limit": 14,
        "min_file_limit": 32,
    },
]


class FileAnalyzer:
    def __init__(self):
        self.use_gateway = os.getenv("USE_GATEWAY", "false").lower() == "true"
        self.gateway_failure_reason = None

        if self.use_gateway:
            self.gateway_client = GatewayClient()
            print(f"[FileAnalyzer] Using Gateway mode: {self.gateway_client.gateway_url}")
            if not self.gateway_client.check_gateway_available():
                self.gateway_failure_reason = (
                    f"Gateway is unreachable at {self.gateway_client.gateway_url}"
                )
                print(
                    "[FileAnalyzer] Warning: Gateway is unavailable, falling back to the direct Anthropic API."
                )
                self.use_gateway = False

        if not self.use_gateway:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key or api_key.startswith("sk-ant-placeholder"):
                gateway_hint = ""
                if self.gateway_failure_reason:
                    gateway_hint = f" Gateway issue: {self.gateway_failure_reason}."

                raise ValueError(
                    "Please set a valid ANTHROPIC_API_KEY in .env or fix the Gateway configuration."
                    + gateway_hint
                )

            self.client = anthropic.Anthropic(api_key=api_key)
            print("[FileAnalyzer] Using direct Anthropic API mode")

    def analyze_folder(self, folder_path):
        """Analyze a folder and generate a cleanup plan."""
        last_error = None
        try:
            structure = self._get_folder_structure(folder_path)

            for index, prompt_profile in enumerate(ANALYSIS_PROMPT_PROFILES):
                try:
                    prompt = self._build_analysis_prompt(
                        folder_path,
                        structure,
                        prompt_profile=prompt_profile,
                    )
                    response_text = self._generate_text(prompt)
                    plan = self._parse_plan_response(response_text)
                    plan = self._enrich_plan_with_heuristics(plan, structure)
                    return {
                        "success": True,
                        "plan": plan,
                        "folder_structure": structure,
                    }
                except Exception as exc:
                    last_error = exc
                    if (
                        index < len(ANALYSIS_PROMPT_PROFILES) - 1
                        and self._looks_like_context_overflow(exc)
                    ):
                        print(
                            "[FileAnalyzer] Prompt overflow on profile "
                            f"{prompt_profile['name']}, retrying with a smaller prompt."
                        )
                        continue
                    raise
        except Exception as exc:
            return {
                "success": False,
                "error": str(last_error or exc),
            }

    def _build_analysis_prompt(self, folder_path, structure, prompt_profile=None):
        prompt_profile = prompt_profile or ANALYSIS_PROMPT_PROFILES[0]
        prompt_payload = self._build_prompt_payload(structure, prompt_profile)
        folder_count = prompt_payload.get("prompt_view", {}).get("folder_index_included", 0)
        file_count = prompt_payload.get("prompt_view", {}).get("file_index_included", 0)
        required_summary_points = min(max(folder_count, 4), 10)
        payload_json = json.dumps(
            prompt_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        return f"""请基于下面的目录摘要生成一个稳妥的文件整理计划。

目标文件夹：{folder_path}

说明：
1. 重点先看 file_index，再决定目录应该如何重组；不要只根据文件夹名猜测。
2. file_index 中每项使用紧凑字段：path=相对路径，ext=扩展名，type=类型分组，group=语义分组。
3. folder_index 中每项包含 path、file_count、subfolder_count、top_extensions，以及少量 sample_files/sample_subfolders。
4. 如果 prompt_view 显示 sampled 或 omitted，说明这里只提供了代表性样本。你可以结合样本和统计做判断，但只能输出有把握的建议。

请严格遵守：
1. 目标不是局部微调，而是重新规划更清晰的目标结构。
2. 优先考虑同类文件归并、流程文档/模板/名单/图片/压缩包分区、编号命名统一、根目录减负。
3. 合理的子目录可以保持不动，但要在 summary_points 中说明理由。
4. 需要新目录时，用 create_folder + move 表达。
5. operations 的 source 和 target 必须是相对路径，统一使用 /。
6. 只输出有把握的建议，不要虚构不存在的路径。
7. 当前用于分析的代表性文件不少于 {file_count} 个，请优先基于 file_index 做文件级分析。
8. 尽量输出至少 {required_summary_points} 条 summary_points。
9. 输出必须是严格合法 JSON，只能使用双引号，不能附带解释文字或 Markdown。

数据：
{payload_json}

只返回 JSON，格式如下：
{{"summary":"整体整理思路","summary_points":["摘要1","摘要2"],"categories":["分类1","分类2"],"operations":[{{"type":"move|rename|rename_folder|create_folder|delete","source":"relative/path","target":"relative/path","reason":"说明原因"}}]}}
"""

    def _build_prompt_payload(self, structure, prompt_profile):
        folder_entries = structure.get("folder_index", [])
        file_entries = structure.get("file_index", [])

        folder_limit = min(
            max(int(prompt_profile.get("folder_limit", 0)), 0),
            len(folder_entries),
        )
        file_limit = min(
            max(int(prompt_profile.get("file_limit", 0)), 0),
            len(file_entries),
        )
        sample_files = max(int(prompt_profile.get("sample_files", 0)), 0)
        sample_subfolders = max(int(prompt_profile.get("sample_subfolders", 0)), 0)
        min_folder_limit = min(
            folder_limit,
            max(int(prompt_profile.get("min_folder_limit", 0)), 0),
        )
        min_file_limit = min(
            file_limit,
            max(int(prompt_profile.get("min_file_limit", 0)), 0),
        )

        while True:
            selected_folders = self._select_folder_index_for_prompt(
                folder_entries,
                folder_limit,
                sample_files,
                sample_subfolders,
            )
            selected_files = self._select_file_index_for_prompt(file_entries, file_limit)
            payload = {
                "path": structure.get("path"),
                "stats": structure.get("stats"),
                "prompt_view": {
                    "profile": prompt_profile.get("name"),
                    "folder_index_total": len(folder_entries),
                    "folder_index_included": len(selected_folders),
                    "folder_index_omitted": max(len(folder_entries) - len(selected_folders), 0),
                    "file_index_total": len(file_entries),
                    "file_index_included": len(selected_files),
                    "file_index_omitted": max(len(file_entries) - len(selected_files), 0),
                    "sampled": (
                        len(selected_folders) < len(folder_entries)
                        or len(selected_files) < len(file_entries)
                    ),
                },
                "folder_index": selected_folders,
                "file_type_overview": self._compact_file_type_overview(
                    structure.get("file_type_overview", {})
                ),
                "file_index": selected_files,
            }

            payload_text = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if len(payload_text) <= prompt_profile.get("max_prompt_chars", 0):
                return payload

            can_reduce_folders = folder_limit > min_folder_limit
            can_reduce_files = file_limit > min_file_limit
            can_reduce_samples = sample_files > 0 or sample_subfolders > 0
            if not any([can_reduce_folders, can_reduce_files, can_reduce_samples]):
                return payload

            if can_reduce_files:
                file_limit = max(min_file_limit, int(file_limit * 0.75))
            if can_reduce_folders:
                folder_limit = max(min_folder_limit, int(folder_limit * 0.75))
            if can_reduce_samples:
                sample_files = max(sample_files - 1, 0)
                sample_subfolders = max(sample_subfolders - 1, 0)

    def _select_folder_index_for_prompt(
        self,
        folder_entries,
        limit,
        sample_files,
        sample_subfolders,
    ):
        sorted_entries = sorted(
            folder_entries,
            key=lambda entry: (
                self._path_depth(entry.get("path", "")),
                str(entry.get("path", "")),
            ),
        )
        selected_entries = []
        for entry in sorted_entries[:limit]:
            compact = {
                "path": entry.get("path"),
                "file_count": entry.get("file_count", 0),
                "subfolder_count": entry.get("subfolder_count", 0),
                "top_extensions": self._compact_extension_pairs(entry.get("top_extensions", []), 4),
            }
            if sample_files > 0:
                compact["sample_files"] = list(entry.get("sample_files", [])[:sample_files])
            if sample_subfolders > 0:
                compact["sample_subfolders"] = list(
                    entry.get("sample_subfolders", [])[:sample_subfolders]
                )
            selected_entries.append(compact)

        return selected_entries

    def _select_file_index_for_prompt(self, file_entries, limit):
        if limit <= 0:
            return []

        sorted_entries = sorted(
            file_entries,
            key=lambda entry: (
                self._path_depth(entry.get("relative_path", "")),
                str(entry.get("parent_path", "")),
                str(entry.get("relative_path", "")),
            ),
        )
        buckets = {}
        bucket_order = []

        for entry in sorted_entries:
            bucket_key = str(entry.get("parent_path", "."))
            if bucket_key not in buckets:
                buckets[bucket_key] = []
                bucket_order.append(bucket_key)
            buckets[bucket_key].append(entry)

        selected = []
        while len(selected) < limit and bucket_order:
            next_bucket_order = []
            for bucket_key in bucket_order:
                bucket = buckets.get(bucket_key, [])
                if not bucket:
                    continue
                selected.append(bucket.pop(0))
                if len(selected) >= limit:
                    break
                if bucket:
                    next_bucket_order.append(bucket_key)
            bucket_order = next_bucket_order

        return [self._compact_file_index_entry(entry) for entry in selected]

    def _compact_file_index_entry(self, entry):
        return {
            "path": entry.get("relative_path"),
            "ext": entry.get("extension"),
            "type": entry.get("type_group"),
            "group": entry.get("semantic_group"),
        }

    def _compact_file_type_overview(self, overview):
        return {
            "top_extensions": self._compact_extension_pairs(
                overview.get("top_extensions", []),
                10,
            ),
            "type_groups": self._compact_extension_pairs(
                overview.get("type_groups", []),
                10,
            ),
            "semantic_groups": self._compact_extension_pairs(
                overview.get("semantic_groups", []),
                10,
            ),
        }

    def _compact_extension_pairs(self, pairs, limit):
        compact = []
        for name, count in list(pairs or [])[:limit]:
            compact.append(f"{name}:{count}")
        return compact

    def _looks_like_context_overflow(self, exc):
        message = str(exc).lower()
        return (
            "context overflow" in message
            or "prompt too large" in message
            or "context length" in message
            or "maximum context" in message
        )

    def _augment_analysis_prompt(self, prompt: str, structure: dict) -> str:
        folder_count = len(structure.get("folder_index", []))
        required_operation_count = min(max(folder_count * 2, 6), 24)

        return (
            prompt
            + f"""

Additional requirements:
1. The "type" field may be only one of "move", "rename", "rename_folder", "create_folder", or "delete".
2. Start from the files, not from the folders. Review file_index item by item, infer what each file is from its filename and type, then design the target folder structure around those file groups.
3. Output as many concrete operations as you can justify from the provided structure. Do not stop at a short high-level list if there are more clear file or folder changes.
4. Keep the overview and the operations aligned. If a summary point says a path should be adjusted, add matching operations for that path whenever the action is concrete and safe.
5. Every actionable summary point should map to one or more operations, and every operation should be reflected in the summary or summary_points.
6. Use "rename_folder" when renaming a directory, instead of renaming files inside that directory one by one.
7. Use "delete" for obsolete duplicates, empty staging artifacts, temporary exports, or clearly disposable files/folders. For delete operations, include "source" and "reason"; "target" can be an empty string.
8. If there are multiple similar files that need cleanup, enumerate them as separate operations instead of collapsing them into one vague suggestion.
9. When the folder structure is obviously messy, try to output at least {required_operation_count} confident operations before stopping. If there are fewer safe operations, output only the safe ones.
10. Do not overuse delete. If a file should be kept but just relocated or renamed, prefer "move" or "rename" over "delete".
11. If you suggest deleting extracted archives or temporary files, also include non-delete operations for naming, consolidation, or folder cleanup when the structure clearly supports them.
12. You may use "create_folder" when several loose files should be consolidated into a clearer subdirectory.

Correct JSON examples:
{{"type": "rename_folder", "source": "OldReports", "target": "Reports", "reason": "Use a clearer top-level folder name"}}
{{"type": "create_folder", "source": "", "target": "00-参考资料", "reason": "Create a single place for loose reference materials"}}
{{"type": "delete", "source": "exports/tmp-dump.zip", "target": "", "reason": "Temporary export that can be removed after consolidation"}}
"""
        )

    def _generate_text(self, prompt: str) -> str:
        if self.use_gateway:
            return self.gateway_client.send_message(prompt)

        message = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _parse_plan_response(self, response_text: str) -> dict:
        initial_candidate = self._extract_json_candidate(response_text)
        try:
            plan = json.loads(initial_candidate)
            return self._normalize_plan(plan)
        except json.JSONDecodeError as exc:
            repaired_candidate = self._attempt_local_json_cleanup(initial_candidate)
            if repaired_candidate != initial_candidate:
                try:
                    plan = json.loads(repaired_candidate)
                    return self._normalize_plan(plan)
                except json.JSONDecodeError:
                    pass

            repaired_object = self._attempt_library_json_repair(repaired_candidate)
            if repaired_object is not None:
                return self._normalize_plan(repaired_object)

            repaired_response = self._repair_plan_json(response_text, str(exc))
            repaired_candidate = self._extract_json_candidate(repaired_response)

            repaired_candidate = self._attempt_local_json_cleanup(repaired_candidate)
            try:
                plan = json.loads(repaired_candidate)
                return self._normalize_plan(plan)
            except json.JSONDecodeError as repair_exc:
                repaired_object = self._attempt_library_json_repair(repaired_candidate)
                if repaired_object is not None:
                    return self._normalize_plan(repaired_object)

                raise ValueError(
                    "模型返回的分析结果不是有效 JSON，自动修复后仍解析失败："
                    f"{repair_exc}"
                ) from repair_exc

    def _repair_plan_json(self, broken_response: str, error_message: str) -> str:
        repair_prompt = f"""下面是一段原本应该是 JSON 的分析结果，但它目前不是合法 JSON。

解析错误：
{error_message}

请你做的事情只有一件：
把下面内容修复为严格合法的 JSON，并且只输出 JSON 本体，不要加解释，不要加 Markdown 代码块。

原始内容：
{broken_response}
"""
        return self._generate_text(repair_prompt)

    def _strip_code_fence(self, response_text: str) -> str:
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            return response_text[json_start:json_end].strip()

        if "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            return response_text[json_start:json_end].strip()

        return response_text.strip()

    def _extract_json_candidate(self, response_text: str) -> str:
        stripped = self._strip_code_fence(response_text).strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped

        start = stripped.find("{")
        if start == -1:
            return stripped

        depth = 0
        in_string = False
        escaped = False

        for index in range(start, len(stripped)):
            char = stripped[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue

            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return stripped[start : index + 1]

        return stripped

    def _attempt_local_json_cleanup(self, candidate: str) -> str:
        cleaned = candidate.strip().replace("\ufeff", "")
        cleaned = cleaned.replace("“", '"').replace("”", '"')
        cleaned = cleaned.replace("‘", "'").replace("’", "'")
        cleaned = re.sub(
            r'("(?:source|target)"\s*:\s*")([^"]*)(")',
            lambda match: match.group(1) + match.group(2).replace("\\", "/") + match.group(3),
            cleaned,
        )
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
        return cleaned

    def _attempt_library_json_repair(self, candidate: str):
        try:
            repaired = repair_json(candidate, return_objects=True, skip_json_loads=True)
        except Exception:
            return None

        return repaired if isinstance(repaired, dict) else None

    def _normalize_plan(self, plan: dict) -> dict:
        if not isinstance(plan, dict):
            raise ValueError("分析结果不是 JSON object")

        summary = str(plan.get("summary", "")).strip()

        summary_points = plan.get("summary_points", [])
        if not isinstance(summary_points, list):
            summary_points = []
        summary_points = [str(item).strip() for item in summary_points if str(item).strip()]

        categories = plan.get("categories", [])
        if not isinstance(categories, list):
            categories = []
        categories = [str(item).strip() for item in categories if str(item).strip()]

        operations = plan.get("operations", [])
        if not isinstance(operations, list):
            operations = []

        normalized_operations = []
        seen_operations = set()
        for operation in operations:
            if not isinstance(operation, dict):
                continue

            op_type = str(operation.get("type", "")).strip().lower()
            if op_type not in {"move", "rename", "rename_folder", "create_folder", "delete"}:
                continue

            source = self._normalize_relative_path(operation.get("source", ""))
            target = self._normalize_relative_path(operation.get("target", ""))
            reason = str(operation.get("reason", "")).strip()

            if op_type == "create_folder":
                if not target or target == ".":
                    continue
                source = ""
            elif not source or source == ".":
                continue

            if op_type not in {"delete", "create_folder"} and (not target or target == "."):
                continue

            if op_type in {"move", "rename", "rename_folder"} and source == target:
                continue

            if op_type == "delete":
                target = ""

            operation_key = (op_type, source, target)
            if operation_key in seen_operations:
                continue
            seen_operations.add(operation_key)

            normalized_operations.append(
                {
                    "type": op_type,
                    "source": source,
                    "target": target,
                    "reason": reason or "未提供原因",
                }
            )

        summary_points = self._merge_summary_points_with_operations(
            summary_points, normalized_operations
        )

        if not summary and summary_points:
            summary = "；".join(summary_points[:3])

        return {
            "summary": summary or "未提供摘要。",
            "summary_points": summary_points,
            "categories": categories,
            "operations": normalized_operations,
        }

    def _normalize_relative_path(self, raw_path) -> str:
        normalized = str(raw_path or "").strip().replace("\\", "/")
        normalized = re.sub(r"/{2,}", "/", normalized)
        normalized = re.sub(r"^\./+", "", normalized)
        normalized = normalized.rstrip("/")
        return normalized

    def _normalize_name_for_path_lookup(self, name: str) -> str:
        normalized = str(name or "").strip().lower()
        normalized = normalized.replace("（", "(").replace("）", ")")
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    def _resolve_existing_path_with_fuzzy_segments(self, folder_path, relative_path):
        normalized_relative_path = self._normalize_relative_path(relative_path)
        if not normalized_relative_path or normalized_relative_path == ".":
            return None

        current_path = os.path.realpath(folder_path)
        folder_real = os.path.realpath(folder_path)
        segments = [segment for segment in normalized_relative_path.split("/") if segment]

        for segment in segments:
            exact_candidate = os.path.join(current_path, segment)
            if os.path.exists(exact_candidate):
                current_path = exact_candidate
                continue

            if not os.path.isdir(current_path):
                return None

            try:
                entries = os.listdir(current_path)
            except OSError:
                return None

            normalized_segment = self._normalize_name_for_path_lookup(segment)
            matches = [
                os.path.join(current_path, entry_name)
                for entry_name in entries
                if self._normalize_name_for_path_lookup(entry_name) == normalized_segment
            ]
            if not matches and "." in segment and segment == segments[-1]:
                requested_stem, _ = os.path.splitext(segment)
                normalized_requested_stem = self._normalize_name_for_path_lookup(
                    requested_stem
                )
                matches = [
                    os.path.join(current_path, entry_name)
                    for entry_name in entries
                    if self._normalize_name_for_path_lookup(
                        os.path.splitext(entry_name)[0]
                    )
                    == normalized_requested_stem
                ]
            if len(matches) != 1:
                return None

            current_path = matches[0]

        current_real = os.path.realpath(current_path)
        if os.path.commonpath([folder_real, current_real]) != folder_real:
            return None

        return current_path if os.path.exists(current_path) else None

    def _merge_summary_points_with_operations(self, summary_points, operations):
        merged = []
        seen_points = set()

        for point in summary_points:
            normalized_point = str(point).strip()
            if not normalized_point or normalized_point in seen_points:
                continue
            merged.append(normalized_point)
            seen_points.add(normalized_point)

        for operation in operations:
            if self._summary_points_cover_operation(merged, operation):
                continue

            operation_point = self._build_operation_summary_point(operation)
            if operation_point in seen_points:
                continue

            merged.append(operation_point)
            seen_points.add(operation_point)

        return merged[:18]

    def _summary_points_cover_operation(self, summary_points, operation):
        tokens = {
            self._display_relative_path(operation.get("source", "")),
            os.path.basename(operation.get("source", "")),
            self._display_relative_path(operation.get("target", "")),
            os.path.basename(operation.get("target", "")),
        }
        tokens = {token.lower() for token in tokens if token}

        for point in summary_points:
            normalized_point = str(point).lower()
            if any(token in normalized_point for token in tokens):
                return True

        return False

    def _build_operation_summary_point(self, operation):
        source = self._display_relative_path(operation.get("source", ""))
        target = self._display_relative_path(operation.get("target", ""))
        reason = str(operation.get("reason", "")).strip()
        op_type = operation.get("type")

        if op_type == "move":
            action = f"将 {source} 移动到 {target}"
        elif op_type == "rename":
            action = f"将文件 {source} 重命名为 {target}"
        elif op_type == "rename_folder":
            action = f"将文件夹 {source} 重命名为 {target}"
        elif op_type == "create_folder":
            action = f"创建文件夹 {target}"
        elif op_type == "delete":
            action = f"删除 {source}"
        else:
            action = f"整理 {source}"

        return f"{action}，{reason}" if reason else action

    def _display_relative_path(self, relative_path) -> str:
        return str(relative_path or "").replace("\\", "/")

    def _resolve_operation_path(self, folder_path, relative_path) -> str:
        normalized_relative_path = self._normalize_relative_path(relative_path)
        if not normalized_relative_path or normalized_relative_path == ".":
            raise ValueError("Operation path cannot point to the selected root folder")

        candidate = os.path.normpath(
            os.path.join(folder_path, normalized_relative_path.replace("/", os.sep))
        )
        folder_real = os.path.realpath(folder_path)
        candidate_real = os.path.realpath(candidate)

        if os.path.commonpath([folder_real, candidate_real]) != folder_real:
            raise ValueError("Operation path escapes the selected folder")

        return candidate

    def _ensure_parent_directory(self, target_path):
        parent = os.path.dirname(target_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _build_delete_backup_path(self, backup_root, relative_source_path):
        normalized_relative_path = self._normalize_relative_path(relative_source_path)
        return os.path.join(backup_root, normalized_relative_path.replace("/", os.sep))

    def _build_unique_backup_target(self, backup_target):
        if not os.path.exists(backup_target):
            return backup_target

        parent = os.path.dirname(backup_target)
        name = os.path.basename(backup_target)
        stem, extension = os.path.splitext(name)
        candidate_index = 1

        while True:
            if extension:
                candidate_name = f"{stem}.__openclaw_backup_{candidate_index}{extension}"
            else:
                candidate_name = f"{name}.__openclaw_backup_{candidate_index}"
            candidate = os.path.join(parent, candidate_name)
            if not os.path.exists(candidate):
                return candidate
            candidate_index += 1

    def _files_have_same_content(self, left_path, right_path):
        if not os.path.isfile(left_path) or not os.path.isfile(right_path):
            return False

        try:
            left_stat = os.stat(left_path)
            right_stat = os.stat(right_path)
        except OSError:
            return False

        if left_stat.st_size != right_stat.st_size:
            return False

        chunk_size = 1024 * 1024
        with open(left_path, "rb") as left_file, open(right_path, "rb") as right_file:
            while True:
                left_chunk = left_file.read(chunk_size)
                right_chunk = right_file.read(chunk_size)
                if left_chunk != right_chunk:
                    return False
                if not left_chunk:
                    return True

    def _ensure_delete_backup_root(self, folder_path, delete_backup_root):
        if delete_backup_root is not None:
            return delete_backup_root

        backup_parent_dir = os.path.dirname(os.path.abspath(folder_path))
        return tempfile.mkdtemp(
            prefix=".openclaw-delete-",
            dir=backup_parent_dir,
        )

    def _backup_duplicate_source(
        self,
        folder_path,
        delete_backup_root,
        source_relative_path,
        source_path,
    ):
        backup_root = self._ensure_delete_backup_root(folder_path, delete_backup_root)
        backup_target = self._build_delete_backup_path(
            backup_root,
            source_relative_path,
        )
        backup_target = self._build_unique_backup_target(backup_target)
        self._ensure_parent_directory(backup_target)
        os.rename(source_path, backup_target)
        return backup_root, backup_target

    def _merge_directory_into_existing_target(self, source_path, target_path, relative_prefix=""):
        if not os.path.isdir(source_path):
            raise ValueError("Source path is not a directory")
        if not os.path.isdir(target_path):
            raise ValueError("Target path is not a directory")

        child_names = sorted(os.listdir(source_path), key=lambda item: item.lower())
        moved_entries = []
        for child_name in child_names:
            source_child = os.path.join(source_path, child_name)
            target_child = os.path.join(target_path, child_name)
            relative_child_path = self._join_relative_path(relative_prefix, child_name)

            if not os.path.exists(target_child):
                os.rename(source_child, target_child)
                moved_entries.append(relative_child_path)
                continue

            if os.path.isdir(source_child) and os.path.isdir(target_child):
                moved_entries.extend(
                    self._merge_directory_into_existing_target(
                        source_child,
                        target_child,
                        relative_child_path,
                    )
                )
                continue

            if (
                os.path.isfile(source_child)
                and os.path.isfile(target_child)
                and self._files_have_same_content(source_child, target_child)
            ):
                raise ValueError(
                    "Target folder already exists and contains duplicate file content: "
                    + relative_child_path
                )

            raise ValueError(
                "Target folder already exists and contains conflicting items: "
                + relative_child_path
            )

        os.rmdir(source_path)
        return moved_entries

    def _join_relative_path(self, *parts) -> str:
        cleaned_parts = []
        for part in parts:
            normalized = self._normalize_relative_path(part)
            if normalized:
                cleaned_parts.append(normalized)
        return "/".join(cleaned_parts)

    def _path_depth(self, relative_path: str) -> int:
        normalized = self._normalize_relative_path(relative_path)
        if not normalized:
            return 0
        return normalized.count("/") + 1

    def _rewrite_relative_path_with_rename(self, relative_path: str, rename_operation: dict) -> str:
        normalized_path = self._normalize_relative_path(relative_path)
        source_prefix = self._normalize_relative_path(rename_operation.get("source", ""))
        target_prefix = self._normalize_relative_path(rename_operation.get("target", ""))

        if not normalized_path or not source_prefix or not target_prefix:
            return normalized_path
        if normalized_path == source_prefix:
            return target_prefix
        if normalized_path.startswith(f"{source_prefix}/"):
            return f"{target_prefix}{normalized_path[len(source_prefix):]}"
        return normalized_path

    def _rewrite_relative_path_with_inverse_rename(
        self,
        relative_path: str,
        rename_operation: dict,
    ) -> str:
        normalized_path = self._normalize_relative_path(relative_path)
        source_prefix = self._normalize_relative_path(rename_operation.get("source", ""))
        target_prefix = self._normalize_relative_path(rename_operation.get("target", ""))

        if not normalized_path or not source_prefix or not target_prefix:
            return normalized_path
        if normalized_path == target_prefix:
            return source_prefix
        if normalized_path.startswith(f"{target_prefix}/"):
            return f"{source_prefix}{normalized_path[len(target_prefix):]}"
        return normalized_path

    def _iter_directory_nodes(self, root_node):
        stack = [root_node]
        while stack:
            node = stack.pop()
            if node.get("type") != "directory":
                continue

            yield node

            children = node.get("children", [])
            for child in reversed(children):
                stack.append(child)

    def _normalize_name_for_matching(self, name: str) -> str:
        normalized = str(name or "").strip().lower()
        normalized = re.sub(r"^[0-9]+[\s\-_.、]*", "", normalized)
        normalized = normalized.replace("（", "(").replace("）", ")")
        normalized = re.sub(r"[\s\-_()]+", "", normalized)
        return normalized

    def _classify_file_entry(self, relative_path: str, extension: str, file_name: str) -> dict:
        normalized_name = str(file_name or "").lower()
        extension = str(extension or "").lower()

        type_group = "other"
        if extension in {".doc", ".docx", ".pdf", ".txt", ".md"}:
            type_group = "document"
        elif extension in {".xls", ".xlsx", ".csv"}:
            type_group = "spreadsheet"
        elif extension in {".ppt", ".pptx"}:
            type_group = "presentation"
        elif extension in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}:
            type_group = "image"
        elif extension in {".zip", ".rar", ".7z", ".tar", ".gz"}:
            type_group = "archive"
        elif extension in {".mp3", ".wav", ".mp4", ".mov", ".avi"}:
            type_group = "media"

        semantic_group = "general"
        if normalized_name.startswith("~$"):
            semantic_group = "temporary"
        elif any(keyword in normalized_name for keyword in ("模板", "范例", "样例", "填写说明")):
            semantic_group = "template"
        elif any(keyword in normalized_name for keyword in ("流程", "清单", "规范", "手册", "说明")):
            semantic_group = "reference"
        elif any(keyword in normalized_name for keyword in ("名单", "汇总表", "统计表")):
            semantic_group = "index"
        elif any(keyword in normalized_name for keyword in ("公示",)):
            semantic_group = "publicity"
        elif any(keyword in normalized_name for keyword in ("预汇报", "汇报")):
            semantic_group = "report"
        elif any(keyword in normalized_name for keyword in ("发展会", "票决", "决议", "介绍人意见")):
            semantic_group = "meeting"
        elif type_group == "archive":
            semantic_group = "archive"
        elif type_group == "image":
            semantic_group = "media"

        return {
            "type_group": type_group,
            "semantic_group": semantic_group,
            "parent_path": self._normalize_relative_path(os.path.dirname(relative_path)),
        }

    def _looks_like_redundant_wrapper(self, parent_name: str, child_name: str) -> bool:
        parent_normalized = self._normalize_name_for_matching(parent_name)
        child_normalized = self._normalize_name_for_matching(child_name)
        return bool(parent_normalized and parent_normalized == child_normalized)

    def _standardize_numbered_folder_name(self, name: str) -> str:
        match = re.match(r"^(\d{1,2})(.+)$", str(name or "").strip())
        if not match:
            return ""

        number = int(match.group(1))
        suffix = match.group(2).strip()
        if not suffix or suffix.startswith("-"):
            return ""

        return f"{number:02d}-{suffix}"

    def _paths_overlap(self, left: str, right: str) -> bool:
        left_normalized = self._normalize_relative_path(left)
        right_normalized = self._normalize_relative_path(right)
        if not left_normalized or not right_normalized:
            return False

        return (
            left_normalized == right_normalized
            or left_normalized.startswith(f"{right_normalized}/")
            or right_normalized.startswith(f"{left_normalized}/")
        )

    def _existing_relative_paths(self, structure: dict):
        existing_paths = set()
        for node in self._iter_directory_nodes(structure.get("tree", {})):
            node_path = self._normalize_relative_path(node.get("path", ""))
            if node_path and node_path != ".":
                existing_paths.add(node_path)

            for file_info in node.get("files", []):
                file_path = self._normalize_relative_path(file_info.get("relative_path", ""))
                if file_path:
                    existing_paths.add(file_path)

        return existing_paths

    def _enrich_plan_with_heuristics(self, plan: dict, structure: dict) -> dict:
        existing_operations = list(plan.get("operations", []))
        supplemental_operations = self._generate_heuristic_operations(
            structure, existing_operations
        )

        if not supplemental_operations:
            return plan

        merged_operations = existing_operations + supplemental_operations
        merged_categories = list(plan.get("categories", []))
        for category in self._infer_categories_from_operations(supplemental_operations):
            if category not in merged_categories:
                merged_categories.append(category)

        merged_summary_points = self._merge_summary_points_with_operations(
            plan.get("summary_points", []), merged_operations
        )
        merged_summary = str(plan.get("summary", "")).strip()
        if not merged_summary and merged_summary_points:
            merged_summary = "；".join(merged_summary_points[:3])

        return {
            "summary": merged_summary or "未提供摘要。",
            "summary_points": merged_summary_points,
            "categories": merged_categories,
            "operations": merged_operations,
        }

    def _infer_categories_from_operations(self, operations):
        categories = []
        operation_types = {operation.get("type") for operation in operations}

        if "delete" in operation_types:
            categories.append("临时文件与重复压缩包清理")
        if "rename" in operation_types or "rename_folder" in operation_types:
            categories.append("命名规范化")
        if "create_folder" in operation_types:
            categories.append("目录归档分区")
        if "move" in operation_types:
            categories.append("目录结构扁平化")

        return categories

    def _generate_heuristic_operations(self, structure: dict, existing_operations):
        existing_keys = {
            (
                str(operation.get("type", "")).strip().lower(),
                self._normalize_relative_path(operation.get("source", "")),
                self._normalize_relative_path(operation.get("target", "")),
            )
            for operation in existing_operations
            if isinstance(operation, dict)
        }
        reserved_paths = set()
        for _, source, target in existing_keys:
            if source:
                reserved_paths.add(source)
            if target:
                reserved_paths.add(target)

        existing_paths = self._existing_relative_paths(structure)
        heuristics = []

        def add_operation(op_type, source, target, reason):
            normalized_source = self._normalize_relative_path(source)
            normalized_target = self._normalize_relative_path(target)
            key = (op_type, normalized_source, normalized_target)
            if key in existing_keys:
                return
            if op_type == "create_folder":
                if not normalized_target:
                    return
            elif not normalized_source:
                return

            if normalized_source and normalized_source in reserved_paths:
                return
            if normalized_target and normalized_target in reserved_paths:
                return

            heuristics.append(
                {
                    "type": op_type,
                    "source": normalized_source if op_type != "create_folder" else "",
                    "target": normalized_target if op_type not in {"delete"} else "",
                    "reason": reason,
                }
            )
            existing_keys.add(key)
            if normalized_source:
                reserved_paths.add(normalized_source)
            if normalized_target and op_type != "create_folder":
                reserved_paths.add(normalized_target)

        archive_extensions = {".zip", ".rar", ".7z", ".tar", ".gz"}
        office_temp_extensions = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
        reference_extensions = {
            ".doc",
            ".docx",
            ".pdf",
            ".txt",
            ".xls",
            ".xlsx",
            ".csv",
            ".ppt",
            ".pptx",
        }
        reference_keywords = ("流程", "清单", "规范", "手册", "说明", "名单", "参考", "汇总")

        for node in self._iter_directory_nodes(structure.get("tree", {})):
            node_path = self._normalize_relative_path(node.get("path", ""))
            child_directories = {
                os.path.basename(self._normalize_relative_path(child.get("path", "")))
                for child in node.get("children", [])
            }
            folder_target = self._join_relative_path(node_path, "00-参考资料")
            candidate_reference_files = []

            if len(node.get("children", [])) >= 3:
                for file_info in node.get("files", []):
                    source = self._normalize_relative_path(file_info.get("relative_path", ""))
                    file_name = os.path.basename(source)
                    _, extension = os.path.splitext(file_name)
                    extension = extension.lower()

                    if extension not in reference_extensions:
                        continue
                    if not any(keyword in file_name for keyword in reference_keywords):
                        continue
                    candidate_reference_files.append(source)

            if (
                len(candidate_reference_files) >= 3
                and folder_target
                and folder_target not in existing_paths
            ):
                add_operation(
                    "create_folder",
                    "",
                    folder_target,
                    "为散落的说明、清单和手册建立统一的参考资料目录。",
                )
                for source in candidate_reference_files:
                    target = self._join_relative_path(
                        folder_target, os.path.basename(source)
                    )
                    if target in existing_paths or target in reserved_paths:
                        continue
                    add_operation(
                        "move",
                        source,
                        target,
                        "散落在当前目录的参考资料可集中到新建的 00-参考资料 目录。",
                    )
                    existing_paths.add(target)

            for file_info in node.get("files", []):
                source = self._normalize_relative_path(file_info.get("relative_path", ""))
                file_name = os.path.basename(source)
                stem, extension = os.path.splitext(file_name)
                extension = extension.lower()

                if extension in archive_extensions and stem in child_directories:
                    add_operation(
                        "delete",
                        source,
                        "",
                        "同目录下已有同名解压文件夹，压缩包更像是重复保留件。",
                    )

                if file_name.startswith("~$") and extension in office_temp_extensions:
                    add_operation(
                        "delete",
                        source,
                        "",
                        "Office 临时锁定文件不属于正式材料，建议清理。",
                    )

                duplicate_match = re.match(r"^(.*)\((\d+)\)(\.[^.]+)$", file_name)
                if duplicate_match:
                    clean_name = (
                        f"{duplicate_match.group(1).rstrip()}{duplicate_match.group(3)}"
                    )
                    target = self._join_relative_path(
                        os.path.dirname(source).replace("\\", "/"), clean_name
                    )
                    if target and target not in existing_paths:
                        add_operation(
                            "rename",
                            source,
                            target,
                            "文件名带有重复下载后缀，若保留这一版可改回规范名称。",
                        )

            children = node.get("children", [])
            if len(node.get("files", [])) == 0 and len(children) == 1:
                child = children[0]
                child_children = child.get("children", [])
                child_files = child.get("files", [])
                if child_children or not child_files:
                    continue

                if not self._looks_like_redundant_wrapper(node.get("name"), child.get("name")):
                    continue

                parent_path = self._normalize_relative_path(node.get("path", ""))
                child_path = self._normalize_relative_path(child.get("path", ""))
                movable_targets = []
                deletable_sources = []

                for file_info in child_files:
                    source = self._normalize_relative_path(file_info.get("relative_path", ""))
                    file_name = os.path.basename(source)
                    _, extension = os.path.splitext(file_name)
                    extension = extension.lower()

                    if file_name.startswith("~$") and extension in office_temp_extensions:
                        deletable_sources.append(source)
                        continue

                    target = self._join_relative_path(parent_path, os.path.basename(source))
                    if not target or target in existing_paths or target in reserved_paths:
                        movable_targets = []
                        deletable_sources = []
                        break
                    movable_targets.append((source, target))

                if not movable_targets and not deletable_sources:
                    continue

                for source in deletable_sources:
                    add_operation(
                        "delete",
                        source,
                        "",
                        "同名包装子目录中的 Office 临时文件可直接清理。",
                    )

                for source, target in movable_targets:
                    add_operation(
                        "move",
                        source,
                        target,
                        "当前层级存在同名包装子目录，文件上移后结构会更直接。",
                    )
                    existing_paths.add(target)

                add_operation(
                    "delete",
                    child_path,
                    "",
                    "同名包装子目录在内容上移后可删除，减少一层冗余目录。",
                )

        for node in self._iter_directory_nodes(structure.get("tree", {})):
            children = node.get("children", [])
            standardized_children = [
                child
                for child in children
                if self._standardize_numbered_folder_name(child.get("name")) not in {"", child.get("name")}
            ]
            if len(standardized_children) < 4:
                continue

            parent_path = self._normalize_relative_path(node.get("path", ""))
            for child in standardized_children:
                source = self._normalize_relative_path(child.get("path", ""))
                target_name = self._standardize_numbered_folder_name(child.get("name"))
                target = self._join_relative_path(parent_path, target_name)

                if not target or target in existing_paths:
                    continue
                if source in reserved_paths:
                    continue

                add_operation(
                    "rename_folder",
                    source,
                    target,
                    "同级目录已形成编号序列，可统一改成两位编号加连字符的命名格式。",
                )
                existing_paths.add(target)

        return heuristics

    def _get_folder_structure(self, folder_path):
        """Read recursive folder structure metadata with bounded depth and volume."""
        stats = {
            "folders": 0,
            "files": 0,
            "total_size": 0,
            "max_depth_scanned": 0,
            "truncated": False,
        }

        def build_tree(current_path, depth):
            stats["max_depth_scanned"] = max(stats["max_depth_scanned"], depth)
            node = {
                "path": os.path.relpath(current_path, folder_path)
                if current_path != folder_path
                else ".",
                "name": os.path.basename(current_path) or current_path,
                "type": "directory",
                "summary": {},
                "files": [],
                "children": [],
            }

            if depth >= MAX_SCAN_DEPTH:
                node["summary"]["depth_limited"] = True
                stats["truncated"] = True
                return node

            try:
                entries = sorted(os.listdir(current_path), key=lambda item: item.lower())
            except Exception as exc:
                node["error"] = str(exc)
                return node

            child_directories = []
            file_entries = []

            for item in entries:
                item_path = os.path.join(current_path, item)
                if os.path.isdir(item_path):
                    child_directories.append((item, item_path))
                elif os.path.isfile(item_path):
                    file_entries.append((item, item_path))

            extension_counter = Counter()

            for item, item_path in file_entries[:MAX_FILES_PER_FOLDER]:
                try:
                    size = os.path.getsize(item_path)
                    modified = os.path.getmtime(item_path)
                except OSError:
                    continue

                extension = os.path.splitext(item)[1].lower()
                extension_counter[extension or "[no_ext]"] += 1
                stats["files"] += 1
                stats["total_size"] += size

                node["files"].append(
                    {
                        "name": item,
                        "relative_path": os.path.relpath(item_path, folder_path),
                        "size": size,
                        "extension": extension,
                        "modified": modified,
                    }
                )

                if stats["files"] >= MAX_TOTAL_FILES:
                    stats["truncated"] = True
                    break

            if len(file_entries) > MAX_FILES_PER_FOLDER:
                stats["truncated"] = True
                node["summary"]["file_list_truncated"] = (
                    len(file_entries) - MAX_FILES_PER_FOLDER
                )

            node["summary"].update(
                {
                    "file_count": len(file_entries),
                    "subfolder_count": len(child_directories),
                    "top_extensions": extension_counter.most_common(8),
                }
            )

            if stats["files"] >= MAX_TOTAL_FILES:
                return node

            for _, item_path in child_directories[:MAX_SUBFOLDERS_PER_FOLDER]:
                stats["folders"] += 1
                child_node = build_tree(item_path, depth + 1)
                node["children"].append(child_node)
                if stats["files"] >= MAX_TOTAL_FILES:
                    break

            if len(child_directories) > MAX_SUBFOLDERS_PER_FOLDER:
                stats["truncated"] = True
                node["summary"]["subfolder_list_truncated"] = (
                    len(child_directories) - MAX_SUBFOLDERS_PER_FOLDER
                )

            return node

        tree = build_tree(folder_path, 0)

        file_index = self._build_file_index(tree)

        return {
            "path": folder_path,
            "scan_limits": {
                "max_depth": MAX_SCAN_DEPTH,
                "max_files_per_folder": MAX_FILES_PER_FOLDER,
                "max_total_files": MAX_TOTAL_FILES,
                "max_subfolders_per_folder": MAX_SUBFOLDERS_PER_FOLDER,
                "max_sample_files_per_folder": MAX_SAMPLE_FILES_PER_FOLDER,
                "max_sample_subfolders_per_folder": MAX_SAMPLE_SUBFOLDERS_PER_FOLDER,
            },
            "stats": stats,
            "folder_index": self._build_folder_index(tree),
            "file_index": file_index,
            "file_type_overview": self._build_file_type_overview(file_index),
            "tree": tree,
        }

    def _build_folder_index(self, root_node):
        folder_index = []

        def visit(node):
            if node.get("type") != "directory":
                return

            children = node.get("children", [])
            files = node.get("files", [])

            folder_index.append(
                {
                    "path": node.get("path"),
                    "file_count": node.get("summary", {}).get("file_count", len(files)),
                    "subfolder_count": node.get("summary", {}).get(
                        "subfolder_count", len(children)
                    ),
                    "top_extensions": node.get("summary", {}).get("top_extensions", []),
                    "sample_files": [
                        file_info.get("relative_path")
                        for file_info in files[:MAX_SAMPLE_FILES_PER_FOLDER]
                    ],
                    "sample_subfolders": [
                        child.get("path")
                        for child in children[:MAX_SAMPLE_SUBFOLDERS_PER_FOLDER]
                    ],
                }
            )

            for child in children:
                visit(child)

        visit(root_node)
        return folder_index

    def _build_file_index(self, root_node):
        file_index = []

        for node in self._iter_directory_nodes(root_node):
            for file_info in node.get("files", []):
                relative_path = self._normalize_relative_path(
                    file_info.get("relative_path", "")
                )
                if not relative_path:
                    continue

                file_name = file_info.get("name") or os.path.basename(relative_path)
                extension = str(file_info.get("extension", "")).lower()
                classification = self._classify_file_entry(
                    relative_path, extension, file_name
                )

                file_index.append(
                    {
                        "relative_path": relative_path,
                        "name": file_name,
                        "extension": extension or "[no_ext]",
                        "type_group": classification["type_group"],
                        "semantic_group": classification["semantic_group"],
                        "parent_path": classification["parent_path"] or ".",
                    }
                )

        return file_index

    def _build_file_type_overview(self, file_index):
        extension_counter = Counter()
        type_group_counter = Counter()
        semantic_group_counter = Counter()

        for file_info in file_index:
            extension_counter[file_info.get("extension") or "[no_ext]"] += 1
            type_group_counter[file_info.get("type_group") or "other"] += 1
            semantic_group_counter[file_info.get("semantic_group") or "general"] += 1

        return {
            "top_extensions": extension_counter.most_common(12),
            "type_groups": type_group_counter.most_common(),
            "semantic_groups": semantic_group_counter.most_common(),
        }

    def _sort_operations_for_execution(self, operations):
        def sort_key(operation):
            op_type = str(operation.get("type", "")).strip().lower()
            source_depth = self._path_depth(operation.get("source", ""))
            target_depth = self._path_depth(operation.get("target", ""))
            depth = max(source_depth, target_depth)

            if op_type == "rename_folder":
                return (0, -depth)
            if op_type == "create_folder":
                return (1, target_depth)
            if op_type in {"move", "rename"}:
                return (2, -depth)
            if op_type == "delete":
                return (3, -depth)
            return (4, -depth)

        return sorted(operations or [], key=sort_key)

    def _format_size_for_readme(self, value):
        size = float(value or 0)
        units = ["B", "KB", "MB", "GB", "TB"]
        unit_index = 0

        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1

        if unit_index == 0:
            return f"{int(size)} {units[unit_index]}"
        if size >= 10:
            return f"{size:.0f} {units[unit_index]}"
        return f"{size:.1f} {units[unit_index]}"

    def _format_extensions_for_readme(self, top_extensions):
        parts = []
        for extension, count in top_extensions[:4]:
            label = extension if extension != "[no_ext]" else "无扩展名"
            parts.append(f"`{label}` x {count}")
        return "、".join(parts) if parts else "无明显类型分布"

    def _build_top_level_section_for_readme(self, structure):
        root = structure.get("tree", {})
        lines = []

        directories = root.get("children", []) or []
        for node in directories:
            summary = node.get("summary", {})
            lines.append(
                "- "
                + f"`{node.get('name', '未命名目录')}/`："
                + f"{summary.get('file_count', len(node.get('files', [])))} 个文件，"
                + f"{summary.get('subfolder_count', len(node.get('children', [])))} 个子目录，"
                + f"主要类型为 {self._format_extensions_for_readme(summary.get('top_extensions', []))}。"
            )

        root_files = root.get("files", []) or []
        for file_info in root_files:
            lines.append(
                "- "
                + f"`{file_info.get('name', '未命名文件')}`："
                + f"根目录文件，大小约 {self._format_size_for_readme(file_info.get('size', 0))}。"
            )

        if not lines:
            lines.append("- 根目录当前没有可描述的子目录或文件。")

        return lines

    def _render_tree_lines_for_readme(self, root_node, max_depth=3, max_lines=220):
        root_name = root_node.get("name") or "root"
        lines = [f"{root_name}/"]
        truncated = False

        def walk_directory(node, prefix, depth):
            nonlocal truncated
            if truncated:
                return

            entries = []
            for child in node.get("children", []) or []:
                entries.append(("directory", child.get("name", "").lower(), child))
            for file_info in node.get("files", []) or []:
                entries.append(("file", file_info.get("name", "").lower(), file_info))

            entries.sort(key=lambda item: (0 if item[0] == "directory" else 1, item[1]))

            for index, (entry_type, _, entry) in enumerate(entries):
                if len(lines) >= max_lines:
                    truncated = True
                    return

                is_last = index == len(entries) - 1
                connector = "└── " if is_last else "├── "
                next_prefix = prefix + ("    " if is_last else "│   ")

                if entry_type == "directory":
                    lines.append(f"{prefix}{connector}{entry.get('name', '未命名目录')}/")
                    child_count = len(entry.get("children", []) or []) + len(
                        entry.get("files", []) or []
                    )
                    if depth >= max_depth:
                        if child_count > 0 and len(lines) < max_lines:
                            lines.append(f"{next_prefix}└── ... ({child_count} 个子项)")
                        continue
                    walk_directory(entry, next_prefix, depth + 1)
                    continue

                lines.append(f"{prefix}{connector}{entry.get('name', '未命名文件')}")

        walk_directory(root_node, "", 1)
        if truncated:
            lines.append("... (目录树过长，已截断显示)")

        return lines

    def _build_structure_readme(self, folder_path, structure, executed_results):
        folder_name = os.path.basename(os.path.abspath(folder_path)) or folder_path
        stats = structure.get("stats", {})
        succeeded_results = [
            item for item in (executed_results or []) if item.get("success")
        ]
        operation_counter = Counter(
            str(item.get("operation", {}).get("type", "")).strip().lower()
            for item in succeeded_results
            if item.get("operation")
        )
        operation_lines = []
        label_map = {
            "move": "移动",
            "rename": "重命名文件",
            "rename_folder": "重命名文件夹",
            "create_folder": "创建文件夹",
            "delete": "删除",
        }

        for op_type in ["move", "rename", "rename_folder", "create_folder", "delete"]:
            count = operation_counter.get(op_type, 0)
            if count > 0:
                operation_lines.append(f"- {label_map[op_type]}：{count} 项")

        if not operation_lines:
            operation_lines.append("- 本次没有记录到已执行的整理操作。")

        top_level_lines = self._build_top_level_section_for_readme(structure)
        tree_lines = self._render_tree_lines_for_readme(structure.get("tree", {}))
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        truncated_note = ""
        if stats.get("truncated"):
            truncated_note = (
                "\n> 说明：目录扫描已达到当前应用的体量限制，下面的结构说明可能是部分视图。"
            )

        return f"""# {folder_name} 文件夹结构说明

本文件由 OpenClaw Files 自动生成，用于说明“确认全部”执行完成后的当前目录结构。

## 当前概览

- 生成时间：{generated_at}
- 根目录：`{folder_path}`
- 子目录数量：{stats.get("folders", 0)}
- 文件数量：{stats.get("files", 0)}
- 总体积：{self._format_size_for_readme(stats.get("total_size", 0))}
- 扫描最大深度：{stats.get("max_depth_scanned", 0)}

## 本次整理结果

{os.linesep.join(operation_lines)}

## 一级结构说明

{os.linesep.join(top_level_lines)}

## 目录树概览

```text
{os.linesep.join(tree_lines)}
```
{truncated_note}
"""

    def _write_structure_readme(self, folder_path, executed_results):
        readme_path = os.path.join(folder_path, "README.md")
        backup_root = ""
        backup_path = ""
        existed_before = os.path.exists(readme_path)

        try:
            if existed_before:
                backup_parent_dir = os.path.dirname(os.path.abspath(folder_path))
                backup_root = tempfile.mkdtemp(
                    prefix=".openclaw-readme-",
                    dir=backup_parent_dir,
                )
                backup_path = os.path.join(backup_root, "README.md")
                shutil.copy2(readme_path, backup_path)

            structure = self._get_folder_structure(folder_path)
            readme_content = self._build_structure_readme(
                folder_path, structure, executed_results
            )
            with open(readme_path, "w", encoding="utf-8", newline="\n") as readme_file:
                readme_file.write(readme_content)
        except Exception:
            if backup_root:
                shutil.rmtree(backup_root, ignore_errors=True)
            raise

        return {
            "readme_path": readme_path,
            "backup_item": {
                "type": "write_readme",
                "source": backup_path,
                "target": readme_path,
                "temp_root": backup_root,
                "existed_before": existed_before,
            },
        }

    def execute_plan(self, folder_path, operations, write_readme=False):
        """Execute file and folder operations."""
        results = []
        backup_info = []
        delete_backup_root = None
        applied_path_rewrites = []
        failed_renames = []

        try:
            for operation in self._sort_operations_for_execution(operations):
                op_type = operation.get("type")
                source_relative_path = operation.get("source", "")
                target_relative_path = operation.get("target", "")

                for path_rewrite in applied_path_rewrites:
                    source_relative_path = self._rewrite_relative_path_with_rename(
                        source_relative_path, path_rewrite
                    )
                    target_relative_path = self._rewrite_relative_path_with_rename(
                        target_relative_path, path_rewrite
                    )

                normalized_source_relative_path = self._normalize_relative_path(
                    source_relative_path
                )
                normalized_target_relative_path = self._normalize_relative_path(
                    target_relative_path
                )
                if (
                    op_type in {"move", "rename", "rename_folder"}
                    and normalized_source_relative_path
                    and normalized_source_relative_path == normalized_target_relative_path
                ):
                    results.append(
                        {
                            "success": True,
                            "operation": operation,
                        }
                    )
                    continue

                try:
                    source = (
                        self._resolve_operation_path(folder_path, source_relative_path)
                        if op_type != "create_folder"
                        else ""
                    )
                    target = (
                        self._resolve_operation_path(folder_path, target_relative_path)
                        if target_relative_path
                        else ""
                    )
                    if op_type == "delete":
                        target = ""
                except ValueError as exc:
                    results.append(
                        {
                            "success": False,
                            "operation": operation,
                            "error": str(exc),
                        }
                    )
                    continue

                if op_type != "create_folder" and not os.path.exists(source):
                    alternate_source_relative_path = source_relative_path
                    for failed_rename in reversed(failed_renames):
                        alternate_candidate = self._rewrite_relative_path_with_inverse_rename(
                            alternate_source_relative_path,
                            failed_rename,
                        )
                        if alternate_candidate == alternate_source_relative_path:
                            continue

                        try:
                            alternate_source = self._resolve_operation_path(
                                folder_path,
                                alternate_candidate,
                            )
                        except ValueError:
                            continue

                        if os.path.exists(alternate_source):
                            source_relative_path = alternate_candidate
                            source = alternate_source
                            break
                        alternate_source_relative_path = alternate_candidate

                if op_type != "create_folder" and not os.path.exists(source):
                    fuzzy_source = self._resolve_existing_path_with_fuzzy_segments(
                        folder_path,
                        source_relative_path,
                    )
                    if fuzzy_source:
                        source = fuzzy_source

                if op_type != "create_folder" and not os.path.exists(source):
                    operation_already_applied = False
                    if op_type == "delete":
                        operation_already_applied = True
                    elif target and os.path.exists(target):
                        operation_already_applied = True

                    if operation_already_applied:
                        if op_type == "rename_folder":
                            applied_path_rewrites.append(
                                {
                                    "source": operation.get("source", ""),
                                    "target": operation.get("target", ""),
                                }
                            )
                        results.append(
                            {
                                "success": True,
                                "operation": operation,
                            }
                        )
                        continue

                    results.append(
                        {
                            "success": False,
                            "operation": operation,
                            "error": "Source path does not exist",
                        }
                    )
                    continue

                created_now = False
                merged_entries = []
                source_was_directory = False
                backup_entry = None

                try:
                    if op_type == "create_folder":
                        if os.path.exists(target):
                            if not os.path.isdir(target):
                                results.append(
                                    {
                                        "success": False,
                                        "operation": operation,
                                        "error": "Target path already exists and is not a directory",
                                    }
                                )
                                continue
                            created_now = False
                        else:
                            os.makedirs(target, exist_ok=False)
                            created_now = True
                    elif op_type == "move":
                        source_was_directory = os.path.isdir(source)
                        if source_was_directory:
                            if os.path.exists(target):
                                if not os.path.isdir(target):
                                    results.append(
                                        {
                                            "success": False,
                                            "operation": operation,
                                            "error": "Target path already exists and is not a directory",
                                        }
                                    )
                                    continue
                                merged_entries = self._merge_directory_into_existing_target(
                                    source,
                                    target,
                                )
                            else:
                                self._ensure_parent_directory(target)
                                os.rename(source, target)
                        else:
                            if os.path.exists(target):
                                if self._files_have_same_content(source, target):
                                    delete_backup_root, backup_target = self._backup_duplicate_source(
                                        folder_path,
                                        delete_backup_root,
                                        source_relative_path,
                                        source,
                                    )
                                    backup_entry = {
                                        "type": "delete",
                                        "source": source,
                                        "target": backup_target,
                                        "temp_root": delete_backup_root,
                                        "created_now": False,
                                        "merged_entries": [],
                                    }
                                else:
                                    results.append(
                                        {
                                            "success": False,
                                            "operation": operation,
                                            "error": "Target path already exists",
                                        }
                                    )
                                    continue
                            else:
                                self._ensure_parent_directory(target)
                                os.rename(source, target)
                    elif op_type == "rename":
                        if os.path.isdir(source):
                            results.append(
                                {
                                    "success": False,
                                    "operation": operation,
                                    "error": "Source path is a directory; use rename_folder instead",
                                }
                            )
                            continue
                        if os.path.exists(target):
                            if self._files_have_same_content(source, target):
                                delete_backup_root, backup_target = self._backup_duplicate_source(
                                    folder_path,
                                    delete_backup_root,
                                    source_relative_path,
                                    source,
                                )
                                backup_entry = {
                                    "type": "delete",
                                    "source": source,
                                    "target": backup_target,
                                    "temp_root": delete_backup_root,
                                    "created_now": False,
                                    "merged_entries": [],
                                }
                            else:
                                results.append(
                                    {
                                        "success": False,
                                        "operation": operation,
                                        "error": "Target path already exists",
                                    }
                                )
                                continue
                        else:
                            self._ensure_parent_directory(target)
                            os.rename(source, target)
                    elif op_type == "rename_folder":
                        if not os.path.isdir(source):
                            results.append(
                                {
                                    "success": False,
                                    "operation": operation,
                                    "error": "Source path is not a directory",
                                }
                            )
                            continue
                        if os.path.exists(target):
                            if not os.path.isdir(target):
                                results.append(
                                    {
                                        "success": False,
                                        "operation": operation,
                                        "error": "Target path already exists and is not a directory",
                                    }
                                )
                                continue

                            merged_entries = self._merge_directory_into_existing_target(
                                source, target
                            )
                        else:
                            self._ensure_parent_directory(target)
                            os.rename(source, target)
                    elif op_type == "delete":
                        delete_backup_root, backup_target = self._backup_duplicate_source(
                            folder_path,
                            delete_backup_root,
                            source_relative_path,
                            source,
                        )
                        target = backup_target
                    else:
                        raise ValueError(f"Unsupported operation type: {op_type}")
                except (OSError, ValueError) as exc:
                    if op_type == "rename_folder":
                        failed_renames.append(
                            {
                                "source": operation.get("source", ""),
                                "target": operation.get("target", ""),
                            }
                        )
                    results.append(
                        {
                            "success": False,
                            "operation": operation,
                            "error": str(exc),
                        }
                    )
                    continue

                if backup_entry is not None:
                    backup_info.append(backup_entry)
                else:
                    backup_info.append(
                        {
                            "type": op_type,
                            "source": source,
                            "target": target,
                            "temp_root": delete_backup_root if op_type == "delete" else "",
                            "created_now": created_now if op_type == "create_folder" else False,
                            "merged_entries": merged_entries
                            if op_type in {"move", "rename_folder"}
                            else [],
                        }
                    )

                if op_type == "rename_folder" or (op_type == "move" and source_was_directory):
                    applied_path_rewrites.append(
                        {
                            "source": operation.get("source", ""),
                            "target": operation.get("target", ""),
                        }
                    )

                results.append(
                    {
                        "success": True,
                        "operation": operation,
                    }
                )
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "backup_info": backup_info,
                "results": results,
                "all_succeeded": False,
                "readme_generated": False,
                "readme_path": "",
                "readme_error": "",
            }

        all_succeeded = bool(results) and all(
            item.get("success") for item in results
        )
        any_succeeded = any(item.get("success") for item in results)
        readme_generated = False
        readme_path = ""
        readme_error = ""

        if write_readme and any_succeeded:
            try:
                readme_result = self._write_structure_readme(folder_path, results)
                backup_info.append(readme_result["backup_item"])
                readme_generated = True
                readme_path = readme_result["readme_path"]
            except Exception as exc:
                readme_error = str(exc)

        return {
            "success": True,
            "results": results,
            "backup_info": backup_info,
            "all_succeeded": all_succeeded,
            "readme_generated": readme_generated,
            "readme_path": readme_path,
            "readme_error": readme_error,
        }

    def rollback(self, backup_info):
        """Rollback the most recent set of file operations."""
        temp_roots = set()

        try:
            for item in reversed(backup_info):
                op_type = item.get("type")
                source = item["source"]
                target = item.get("target", "")

                if item.get("temp_root"):
                    temp_roots.add(item["temp_root"])

                if op_type == "create_folder":
                    if item.get("created_now") and target and os.path.isdir(target):
                        try:
                            os.rmdir(target)
                        except OSError:
                            pass
                    continue

                if op_type == "write_readme":
                    existed_before = item.get("existed_before", False)
                    if existed_before:
                        if target and os.path.exists(target):
                            os.remove(target)
                        if source and os.path.exists(source):
                            self._ensure_parent_directory(target)
                            os.rename(source, target)
                    elif target and os.path.exists(target):
                        os.remove(target)
                    continue

                if op_type in {"move", "rename_folder"}:
                    if item.get("merged_entries"):
                        self._ensure_parent_directory(source)
                        os.makedirs(source, exist_ok=True)
                        for child_name in reversed(item.get("merged_entries", [])):
                            target_child = os.path.join(target, child_name)
                            source_child = os.path.join(source, child_name)
                            if os.path.exists(target_child):
                                self._ensure_parent_directory(source_child)
                                os.rename(target_child, source_child)
                        continue

                    if target and os.path.exists(target):
                        self._ensure_parent_directory(source)

                        if os.path.exists(source):
                            if not os.path.isdir(source):
                                raise ValueError(
                                    "Cannot rollback folder rename because the original path "
                                    "already exists and is not a directory"
                                )
                            if not os.path.isdir(target):
                                raise ValueError(
                                    "Cannot rollback folder rename because the renamed path "
                                    "is not a directory"
                                )
                            self._merge_directory_into_existing_target(target, source)
                        else:
                            os.rename(target, source)
                    continue

                if op_type == "delete":
                    if target and os.path.exists(target):
                        self._ensure_parent_directory(source)
                        os.rename(target, source)
                    continue

                if target and os.path.exists(target):
                    self._ensure_parent_directory(source)
                    os.rename(target, source)

            for temp_root in temp_roots:
                shutil.rmtree(temp_root, ignore_errors=True)

            return {"success": True}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
