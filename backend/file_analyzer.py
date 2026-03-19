import json
import os
import re
import shutil
import tempfile
from collections import Counter

import anthropic
from dotenv import load_dotenv
from json_repair import repair_json

from gateway_client import GatewayClient

load_dotenv()

MAX_SCAN_DEPTH = 5
MAX_FILES_PER_FOLDER = 160
MAX_TOTAL_FILES = 1200
MAX_SUBFOLDERS_PER_FOLDER = 100
MAX_SAMPLE_FILES_PER_FOLDER = 12
MAX_SAMPLE_SUBFOLDERS_PER_FOLDER = 12


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
        try:
            structure = self._get_folder_structure(folder_path)
            prompt = self._build_analysis_prompt(folder_path, structure)
            prompt = self._augment_analysis_prompt(prompt, structure)
            response_text = self._generate_text(prompt)
            plan = self._parse_plan_response(response_text)
            plan = self._enrich_plan_with_heuristics(plan, structure)
            return {
                "success": True,
                "plan": plan,
                "folder_structure": structure,
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
            }

    def _build_analysis_prompt(self, folder_path, structure):
        folder_count = len(structure.get("folder_index", []))
        file_count = len(structure.get("file_index", []))
        required_summary_points = min(max(folder_count, 4), 12)
        prompt_payload = {
            "path": structure.get("path"),
            "stats": structure.get("stats"),
            "scan_limits": structure.get("scan_limits"),
            "folder_index": structure.get("folder_index"),
            "file_type_overview": structure.get("file_type_overview"),
            "file_index": structure.get("file_index"),
        }

        return f"""请分析下面这个文件夹，并基于“各个子文件的文件名、文件类型、所在路径”重新规划整个目录结构。

目标文件夹：{folder_path}

你会看到：
1. 各级目录统计信息
2. 扁平化的 file_index，里面列出了扫描到的各个子文件
3. 每个文件的相对路径、文件名、扩展名、文件类型和语义分组
4. 文件类型概览

请严格遵守以下要求：
1. 不要只看文件夹名字，必须逐个审阅 file_index 里的子文件条目，并依据文件名、扩展名、文件类型、语义分组来判断它们应该归入哪类目录。
2. 你的目标不是局部微调，而是重新规划整个目录的目标结构。先思考“什么样的目录结构更清晰”，再输出对应的 create_folder、rename_folder、move、rename、delete 操作。
3. 优先把“同类文件归并”“流程文档/模板/名单/图片/压缩包分区”“编号与命名统一”“根目录减负”作为重规划重点。
4. 如果某个子目录结构已经合理，也要在摘要中明确指出“保持不动”的判断原因。
5. 如果某类文件应该统一进入一个新目录，请直接使用 create_folder + move 的组合来表达。
6. operations 里的 source 和 target 必须是相对于目标文件夹的路径，并统一使用 / 作为路径分隔符，不要使用 Windows 反斜杠。
7. 只返回你有把握的建议，不要虚构不存在的路径。
8. 当前扫描到的文件数不少于 {file_count} 个，请优先基于 file_index 做文件级分析，而不是只根据目录层级猜测。
9. summary_points 必须是一条一条的结构化摘要，每一条都尽量点名具体目录路径，并说明该路径中的文件为什么应该这样重组。
10. 如果可分析目录不少于 {required_summary_points} 个，请尽量输出至少 {required_summary_points} 条 summary_points。
11. 输出必须是严格合法的 JSON：只能使用双引号，不能带注释，不能带多余说明文字，不能省略逗号。
12. reason、summary、summary_points 中如果要出现引号，请进行 JSON 转义。

用于分析的数据：
{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}

请只返回 JSON，格式如下：
{{
  "summary": "整体整理思路的总述",
  "summary_points": [
    "第 1 条结构化摘要",
    "第 2 条结构化摘要"
  ],
  "categories": ["建议分类1", "建议分类2", "建议分类3"],
  "operations": [
    {{
      "type": "move|rename|rename_folder|create_folder|delete",
      "source": "relative/path",
      "target": "relative/path",
      "reason": "说明为什么这样整理，并尽量点名对应子目录或文件集合"
    }}
  ]
}}
"""

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

    def _merge_directory_into_existing_target(self, source_path, target_path):
        if not os.path.isdir(source_path):
            raise ValueError("Source path is not a directory")
        if not os.path.isdir(target_path):
            raise ValueError("Target path is not a directory")

        child_names = sorted(os.listdir(source_path), key=lambda item: item.lower())
        conflicting_names = [
            child_name
            for child_name in child_names
            if os.path.exists(os.path.join(target_path, child_name))
        ]
        if conflicting_names:
            raise ValueError(
                "Target folder already exists and contains conflicting items: "
                + ", ".join(conflicting_names[:5])
            )

        moved_entries = []
        for child_name in child_names:
            source_child = os.path.join(source_path, child_name)
            target_child = os.path.join(target_path, child_name)
            os.rename(source_child, target_child)
            moved_entries.append(child_name)

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

            if op_type == "create_folder":
                return (0, target_depth)
            if op_type in {"move", "rename"}:
                return (1, -depth)
            if op_type == "rename_folder":
                return (2, -depth)
            if op_type == "delete":
                return (3, -depth)
            return (4, -depth)

        return sorted(operations or [], key=sort_key)

    def execute_plan(self, folder_path, operations):
        """Execute file and folder operations."""
        results = []
        backup_info = []
        delete_backup_root = None
        applied_renames = []

        try:
            for operation in self._sort_operations_for_execution(operations):
                op_type = operation.get("type")
                source_relative_path = operation.get("source", "")
                target_relative_path = operation.get("target", "")

                for rename_operation in applied_renames:
                    source_relative_path = self._rewrite_relative_path_with_rename(
                        source_relative_path, rename_operation
                    )
                    target_relative_path = self._rewrite_relative_path_with_rename(
                        target_relative_path, rename_operation
                    )

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

                        try:
                            merged_entries = self._merge_directory_into_existing_target(
                                source, target
                            )
                        except ValueError as exc:
                            results.append(
                                {
                                    "success": False,
                                    "operation": operation,
                                    "error": str(exc),
                                }
                            )
                            continue
                    else:
                        self._ensure_parent_directory(target)
                        os.rename(source, target)
                elif op_type == "delete":
                    if delete_backup_root is None:
                        backup_parent_dir = os.path.dirname(os.path.abspath(folder_path))
                        delete_backup_root = tempfile.mkdtemp(
                            prefix=".openclaw-delete-",
                            dir=backup_parent_dir,
                        )
                    backup_target = self._build_delete_backup_path(
                        delete_backup_root, source_relative_path
                    )
                    backup_target = self._build_unique_backup_target(backup_target)
                    self._ensure_parent_directory(backup_target)
                    os.rename(source, backup_target)
                    target = backup_target
                else:
                    raise ValueError(f"Unsupported operation type: {op_type}")

                backup_info.append(
                    {
                        "type": op_type,
                        "source": source,
                        "target": target,
                        "temp_root": delete_backup_root if op_type == "delete" else "",
                        "created_now": created_now if op_type == "create_folder" else False,
                        "merged_entries": merged_entries if op_type == "rename_folder" else [],
                    }
                )

                if op_type == "rename_folder":
                    applied_renames.append(
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
            }

        return {
            "success": True,
            "results": results,
            "backup_info": backup_info,
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

                if op_type == "rename_folder" and item.get("merged_entries"):
                    self._ensure_parent_directory(source)
                    os.makedirs(source, exist_ok=True)
                    for child_name in reversed(item.get("merged_entries", [])):
                        target_child = os.path.join(target, child_name)
                        source_child = os.path.join(source, child_name)
                        if os.path.exists(target_child):
                            os.rename(target_child, source_child)
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
