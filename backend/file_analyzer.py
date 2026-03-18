import json
import os
from collections import Counter

import anthropic
from dotenv import load_dotenv

from gateway_client import GatewayClient

load_dotenv()

MAX_SCAN_DEPTH = 4
MAX_FILES_PER_FOLDER = 120
MAX_TOTAL_FILES = 800
MAX_SUBFOLDERS_PER_FOLDER = 80


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

            if self.use_gateway:
                response_text = self.gateway_client.send_message(prompt)
            else:
                message = self.client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                )
                response_text = message.content[0].text

            cleaned_response = self._strip_code_fence(response_text)
            plan = json.loads(cleaned_response)
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
        return f"""请分析下面这个文件夹，并生成更细致、可执行的整理建议。

目标文件夹：{folder_path}

要求：
1. 不只看根目录，要结合各级次级文件夹中的文件分布给出建议。
2. 优先指出哪些子文件夹已经合理、哪些子文件夹混杂严重、哪些文件应该移动到更合适的位置。
3. 对命名不统一、同类文件分散、临时文件堆积、资料重复归档等情况给出明确意见。
4. `operations` 里的 `source` 和 `target` 必须使用相对于目标文件夹的路径。
5. 只给出你有把握的操作，不要虚构不存在的目录或文件。
6. 如果某些子目录建议“保持不动”，请在 summary 里点明原因。

文件夹结构与统计：
{json.dumps(structure, ensure_ascii=False, indent=2)}

请只返回 JSON，格式如下：
{{
  "summary": "整体整理思路，需提到至少 2-4 个关键子目录的判断",
  "categories": ["建议分类1", "建议分类2", "建议分类3"],
  "operations": [
    {{
      "type": "move|rename",
      "source": "相对路径",
      "target": "相对路径",
      "reason": "说明为什么这样整理，尽量指出所属子目录或上下文"
    }}
  ]
}}
"""

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
                "path": os.path.relpath(current_path, folder_path) if current_path != folder_path else ".",
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
                node["summary"]["file_list_truncated"] = len(file_entries) - MAX_FILES_PER_FOLDER

            node["summary"].update(
                {
                    "file_count": len(file_entries),
                    "subfolder_count": len(child_directories),
                    "top_extensions": extension_counter.most_common(8),
                }
            )

            if stats["files"] >= MAX_TOTAL_FILES:
                return node

            for item, item_path in child_directories[:MAX_SUBFOLDERS_PER_FOLDER]:
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

        return {
            "path": folder_path,
            "scan_limits": {
                "max_depth": MAX_SCAN_DEPTH,
                "max_files_per_folder": MAX_FILES_PER_FOLDER,
                "max_total_files": MAX_TOTAL_FILES,
                "max_subfolders_per_folder": MAX_SUBFOLDERS_PER_FOLDER,
            },
            "stats": stats,
            "tree": build_tree(folder_path, 0),
        }

    def execute_plan(self, folder_path, operations):
        """Execute file move and rename operations."""
        results = []
        backup_info = []

        try:
            for operation in operations:
                op_type = operation.get("type")
                source = os.path.join(folder_path, operation.get("source", ""))
                target = os.path.join(folder_path, operation.get("target", ""))

                if not os.path.exists(source):
                    results.append(
                        {
                            "success": False,
                            "operation": operation,
                            "error": "Source path does not exist",
                        }
                    )
                    continue

                backup_info.append(
                    {
                        "type": op_type,
                        "source": source,
                        "target": target,
                    }
                )

                if op_type == "move":
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    os.rename(source, target)
                elif op_type == "rename":
                    os.rename(source, target)
                else:
                    raise ValueError(f"Unsupported operation type: {op_type}")

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
        try:
            for item in reversed(backup_info):
                source = item["source"]
                target = item["target"]

                if os.path.exists(target):
                    os.rename(target, source)

            return {"success": True}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
