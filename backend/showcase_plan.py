import copy
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


SHOWCASE_FOLDER_PATH = os.path.normcase(
    os.path.abspath(
        "D:\\Coding Demo\\202603_OpenClaw_Files\\Test\\Show_\u8f85\u5bfc\u5458"
    )
)
SHOWCASE_PLAN_FILE_NAME = "show_fu_daoyuan_plan.json"
SHOWCASE_REFERENCE_ROOT = "00_\u53c2\u8003\u8d44\u6599"
SHOWCASE_NUMBERED_ROOTS = [
    SHOWCASE_REFERENCE_ROOT,
    "01_\u5956\u5b66\u91d1\u8363\u8a89\u8d44\u52a9",
    "02_\u5b66\u751f\u7ec4\u4f8b\u4f1a",
    "03_\u5de5\u4f5c\u8ff0\u804c",
    "04_\u8f85\u5bfc\u5458\u7ba1\u7406",
    "05_\u5c31\u4e1a\u4fe1\u606f",
    "06_\u5fc3\u7406\u5de5\u4f5c",
    "07_\u5b66\u751f\u60c5\u51b5",
    "08_\u62a5\u9500\u89c4\u8303",
    "09_\u8f85\u5bfc\u5458\u6d25\u8d34",
    "10_\u8f85\u5bfc\u5458\u5de5\u4f5c",
    "11_\u6742\u4e8b\u5f52\u6863",
    "12_\u5e74\u5ea6\u4ea4\u6d41",
]
SHOWCASE_TOP_LEVEL_DIRECTORY_MAP = {
    "\u5956\u5b66\u91d1\u3001\u8363\u8a89\u548c\u8d44\u52a9": "01_\u5956\u5b66\u91d1\u8363\u8a89\u8d44\u52a9",
    "\u5b66\u751f\u7ec4\u4f8b\u4f1a": "02_\u5b66\u751f\u7ec4\u4f8b\u4f1a",
    "\u5de5\u4f5c\u8ff0\u804cppt": "03_\u5de5\u4f5c\u8ff0\u804c",
    "\u8f85\u5bfc\u5458\u7ba1\u7406": "04_\u8f85\u5bfc\u5458\u7ba1\u7406",
    "\u5c31\u4e1a\u4fe1\u606f\u6536\u96c6": "05_\u5c31\u4e1a\u4fe1\u606f",
    "\u5fc3\u7406\u5de5\u4f5c": "06_\u5fc3\u7406\u5de5\u4f5c",
    "\u5b66\u751f\u60c5\u51b5": "07_\u5b66\u751f\u60c5\u51b5",
    "\u5de5\u7269\u7cfb\u5b66\u751f\u62a5\u9500\u89c4\u8303": "08_\u62a5\u9500\u89c4\u8303",
    "\u8f85\u5bfc\u5458\u6d25\u8d34": "09_\u8f85\u5bfc\u5458\u6d25\u8d34",
    "\u8f85\u5bfc\u5458\u5de5\u4f5c": "10_\u8f85\u5bfc\u5458\u5de5\u4f5c",
    "\u4e00\u4e9b\u6742\u4e8b": "11_\u6742\u4e8b\u5f52\u6863",
    "2025\u5e74\u8f85\u5bfc\u5458\u5de5\u4f5c\u4ea4\u6d41": "12_\u5e74\u5ea6\u4ea4\u6d41",
}
SHOWCASE_TOP_LEVEL_FILE_TARGETS = {
    "2024-2025\u5b66\u5e74\u5ea6\u5de5\u7a0b\u7269\u7406\u7cfb\u672c\u79d1\u751f\u8363\u8a89\u4e0e\u5956\u5b66\u91d1\u8bc4\u5b9a\u5de5\u4f5c\u5b9e\u65bd\u7ec6\u5219.docx": "01_\u5956\u5b66\u91d1\u8363\u8a89\u8d44\u52a9/2024-2025\u5b66\u5e74\u5ea6\u5de5\u7a0b\u7269\u7406\u7cfb\u672c\u79d1\u751f\u8363\u8a89\u4e0e\u5956\u5b66\u91d1\u8bc4\u5b9a\u5de5\u4f5c\u5b9e\u65bd\u7ec6\u5219.docx",
    "2024\u5e74\u79cb\u5b63\u5b66\u671f\u8f85\u5bfc\u5458\u95e8\u7981\u5f00\u901a\u7533\u8bf7\u8868-\u5de5\u7269\u7cfb.xlsx": "04_\u8f85\u5bfc\u5458\u7ba1\u7406/2024\u5e74\u79cb\u5b63\u5b66\u671f\u8f85\u5bfc\u5458\u95e8\u7981\u5f00\u901a\u7533\u8bf7\u8868-\u5de5\u7269\u7cfb.xlsx",
    "2025\u5e74\u79cb\u8f85\u5bfc\u5458\u5b66\u53f7.xls": "04_\u8f85\u5bfc\u5458\u7ba1\u7406/2025\u5e74\u79cb\u8f85\u5bfc\u5458\u5b66\u53f7.xls",
    "\u5de5\u7a0b\u7269\u7406\u7cfb\u5b66\u751f\u5de5\u4f5c\u6982\u51b5.pptx": "03_\u5de5\u4f5c\u8ff0\u804c/\u5de5\u7a0b\u7269\u7406\u7cfb\u5b66\u751f\u5de5\u4f5c\u6982\u51b5.pptx",
    "\u540e\u5907\u8f85\u5bfc\u5458\u9009\u62d4\u5de5\u4f5c\u624b\u518c.docx": f"{SHOWCASE_REFERENCE_ROOT}/\u540e\u5907\u8f85\u5bfc\u5458\u9009\u62d4\u5de5\u4f5c\u624b\u518c.docx",
    "\u5b66\u751f\u7ec4\u5956\u5b66\u91d1\u5de5\u4f5c\u624b\u518c-\u901a\u7528\u7248.docx": f"{SHOWCASE_REFERENCE_ROOT}/\u5b66\u751f\u7ec4\u5956\u5b66\u91d1\u5de5\u4f5c\u624b\u518c-\u901a\u7528\u7248.docx",
    "\u5b66\u751f\u7ec4\u5956\u5b66\u91d1\u5de5\u4f5c\u624b\u518c.docx": f"{SHOWCASE_REFERENCE_ROOT}/\u5b66\u751f\u7ec4\u5956\u5b66\u91d1\u5de5\u4f5c\u624b\u518c.docx",
    "\u5b66\u751f\u7ec4\u65b0\u751f\u5de5\u4f5c\u624b\u518c.docx": f"{SHOWCASE_REFERENCE_ROOT}/\u5b66\u751f\u7ec4\u65b0\u751f\u5de5\u4f5c\u624b\u518c.docx",
}
SHOWCASE_ROOT_SEGMENT_REPLACEMENTS = {
    "00-\u53c2\u8003\u8d44\u6599": SHOWCASE_REFERENCE_ROOT,
    "00_\u6839\u76ee\u5f55\u6587\u6863": SHOWCASE_REFERENCE_ROOT,
    "00_\u89c4\u8303\u6587\u6863": SHOWCASE_REFERENCE_ROOT,
    "01_\u5956\u5b66\u91d1\u4e0e\u8363\u8a89\u8bc4\u9009": "01_\u5956\u5b66\u91d1\u8363\u8a89\u8d44\u52a9",
    "01_\u65e5\u5e38\u7ba1\u7406": "10_\u8f85\u5bfc\u5458\u5de5\u4f5c",
    "02_\u5956\u52a9\u8bc4\u4f18": "01_\u5956\u5b66\u91d1\u8363\u8a89\u8d44\u52a9",
    "03_\u5de5\u4f5c\u8ff0\u804c\u6c47\u62a5": "03_\u5de5\u4f5c\u8ff0\u804c",
    "03_\u5b66\u751f\u5de5\u4f5c": "10_\u8f85\u5bfc\u5458\u5de5\u4f5c",
    "05_\u5b66\u751f\u60c5\u51b5": "07_\u5b66\u751f\u60c5\u51b5",
    "05_\u4e13\u9879\u6d3b\u52a8": "11_\u6742\u4e8b\u5f52\u6863",
    "06_\u62a5\u9500\u89c4\u8303": "08_\u62a5\u9500\u89c4\u8303",
    "07_\u5c31\u4e1a\u4fe1\u606f": "05_\u5c31\u4e1a\u4fe1\u606f",
    "07_\u5f52\u6863\u8d44\u6599": SHOWCASE_REFERENCE_ROOT,
    "08_\u8f85\u5bfc\u5458\u6d25\u8d34": "09_\u8f85\u5bfc\u5458\u6d25\u8d34",
    "09_\u5e74\u5ea6\u5de5\u4f5c\u4ea4\u6d41": "12_\u5e74\u5ea6\u4ea4\u6d41",
    "99_\u4e34\u65f6\u5f52\u6863": "11_\u6742\u4e8b\u5f52\u6863",
}


def _normalize_path(path_value: str) -> str:
    return os.path.normcase(os.path.abspath(str(path_value or "").strip()))


def is_showcase_folder(folder_path: str) -> bool:
    return _normalize_path(folder_path) == SHOWCASE_FOLDER_PATH


def _showcase_cache_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "showcase_cache"
    return Path(__file__).resolve().parent / "showcase_cache"


def _showcase_cache_dir_candidates() -> List[Path]:
    if not getattr(sys, "frozen", False):
        return [_showcase_cache_dir()]

    executable_dir = Path(sys.executable).resolve().parent
    candidates: List[Path] = [
        executable_dir / "showcase_cache",
        executable_dir / "_internal" / "showcase_cache",
    ]

    runtime_extract_dir = getattr(sys, "_MEIPASS", None)
    if runtime_extract_dir:
        candidates.append(Path(runtime_extract_dir) / "showcase_cache")

    deduplicated: List[Path] = []
    seen = set()
    for candidate in candidates:
        key = str(candidate.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(candidate)
    return deduplicated


def _showcase_plan_path() -> Path:
    return _showcase_cache_dir() / SHOWCASE_PLAN_FILE_NAME


def _find_existing_showcase_plan_path() -> Optional[Path]:
    for cache_dir in _showcase_cache_dir_candidates():
        candidate = cache_dir / SHOWCASE_PLAN_FILE_NAME
        if candidate.exists():
            return candidate
    return None


def _normalize_relative_path(path_value: str) -> str:
    return str(path_value or "").replace("\\", "/").strip().strip("/")


def _split_relative_path(path_value: str) -> List[str]:
    normalized = _normalize_relative_path(path_value)
    if not normalized:
        return []
    return [segment for segment in normalized.split("/") if segment]


def _join_relative_path(*parts: str) -> str:
    normalized_parts: List[str] = []
    for part in parts:
        normalized_parts.extend(_split_relative_path(part))
    return "/".join(normalized_parts)


def _rewrite_showcase_root_segment(path_value: str) -> str:
    segments = _split_relative_path(path_value)
    if not segments:
        return ""
    segments[0] = SHOWCASE_ROOT_SEGMENT_REPLACEMENTS.get(segments[0], segments[0])
    return "/".join(segments)


def _canonicalize_showcase_root_segment(segment: str) -> str:
    normalized_segment = SHOWCASE_ROOT_SEGMENT_REPLACEMENTS.get(str(segment or ""), str(segment or ""))
    if not normalized_segment:
        return ""
    if normalized_segment in SHOWCASE_NUMBERED_ROOTS:
        return normalized_segment

    stripped = re.sub(r"^\d+\s*[_-]?\s*", "", normalized_segment).strip()
    compact = stripped.replace(" ", "")

    if (
        any(keyword in compact for keyword in ["参考", "文档", "资料"])
        and "报销" not in compact
        and "临时" not in compact
    ):
        return SHOWCASE_REFERENCE_ROOT
    if any(keyword in compact for keyword in ["奖学金", "奖助", "荣誉", "资助", "评优"]):
        return "01_\u5956\u5b66\u91d1\u8363\u8a89\u8d44\u52a9"
    if any(keyword in compact for keyword in ["学生组", "例会"]):
        return "02_\u5b66\u751f\u7ec4\u4f8b\u4f1a"
    if any(keyword in compact for keyword in ["述职", "汇报"]):
        return "03_\u5de5\u4f5c\u8ff0\u804c"
    if "辅导员管理" in compact or ("辅导员" in compact and "管理" in compact):
        return "04_\u8f85\u5bfc\u5458\u7ba1\u7406"
    if "就业" in compact:
        return "05_\u5c31\u4e1a\u4fe1\u606f"
    if "心理" in compact:
        return "06_\u5fc3\u7406\u5de5\u4f5c"
    if "学生情况" in compact:
        return "07_\u5b66\u751f\u60c5\u51b5"
    if "报销" in compact:
        return "08_\u62a5\u9500\u89c4\u8303"
    if "津贴" in compact:
        return "09_\u8f85\u5bfc\u5458\u6d25\u8d34"
    if any(keyword in compact for keyword in ["辅导员工作", "日常管理", "学生工作"]):
        return "10_\u8f85\u5bfc\u5458\u5de5\u4f5c"
    if "交流" in compact:
        return "12_\u5e74\u5ea6\u4ea4\u6d41"
    if any(keyword in compact for keyword in ["杂事", "临时", "事务", "专项"]):
        return "11_\u6742\u4e8b\u5f52\u6863"

    return normalized_segment


def _rewrite_showcase_target_root(path_value: str) -> str:
    segments = _split_relative_path(path_value)
    if not segments:
        return ""
    segments[0] = _canonicalize_showcase_root_segment(segments[0])
    return "/".join(segments)


def _rewrite_showcase_numbered_subpath(path_value: str) -> str:
    segments = _split_relative_path(path_value)
    if len(segments) < 2:
        return "/".join(segments)

    mapped_root = SHOWCASE_TOP_LEVEL_DIRECTORY_MAP.get(segments[0])
    if not mapped_root:
        return "/".join(segments)

    return "/".join([mapped_root, *segments[1:]])


def _deduplicate_operations(operations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduplicated: List[Dict[str, Any]] = []
    seen_keys = set()

    for operation in operations:
        if not isinstance(operation, dict):
            continue

        key = (
            str(operation.get("type", "")).strip().lower(),
            str(operation.get("source", "") or ""),
            str(operation.get("target", "") or ""),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduplicated.append(operation)

    return deduplicated


def _normalize_showcase_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(plan, dict):
        return {}

    normalized_plan = copy.deepcopy(plan)
    operations = normalized_plan.get("operations")
    if not isinstance(operations, list):
        operations = []

    normalized_operations: List[Dict[str, Any]] = []
    existing_create_targets = set()
    existing_root_directory_ops = set()
    existing_root_file_moves = set()

    for raw_operation in operations:
        if not isinstance(raw_operation, dict):
            continue

        operation = copy.deepcopy(raw_operation)
        op_type = str(operation.get("type", "")).strip().lower()
        source = _rewrite_showcase_root_segment(operation.get("source", ""))
        target = _rewrite_showcase_target_root(
            _rewrite_showcase_root_segment(operation.get("target", ""))
        )

        mapped_root = SHOWCASE_TOP_LEVEL_DIRECTORY_MAP.get(source)
        if mapped_root and op_type in {"move", "rename_folder"}:
            op_type = "rename_folder"
            target = mapped_root
            operation["reason"] = "\u5c06\u539f\u59cb\u4e00\u7ea7\u76ee\u5f55\u76f4\u63a5\u5e76\u5165\u5bf9\u5e94\u7684\u5e26\u7f16\u53f7\u6839\u76ee\u5f55"

        mapped_root_file_target = SHOWCASE_TOP_LEVEL_FILE_TARGETS.get(source)
        if mapped_root_file_target and op_type in {"move", "rename"}:
            target = mapped_root_file_target
            operation["reason"] = "\u5c06\u6839\u76ee\u5f55\u6563\u843d\u6587\u4ef6\u5f52\u6863\u5230\u5bf9\u5e94\u7684\u7f16\u53f7\u76ee\u5f55"

        if op_type in {"move", "rename", "delete"}:
            source = _rewrite_showcase_numbered_subpath(source)
        if op_type in {"move", "rename", "create_folder"}:
            target = _rewrite_showcase_target_root(
                _rewrite_showcase_numbered_subpath(target)
            )

        operation["type"] = op_type
        operation["source"] = "" if op_type == "create_folder" else source
        operation["target"] = "" if op_type == "delete" else target

        if op_type == "create_folder" and target:
            existing_create_targets.add(target)
        if op_type == "rename_folder" and source in SHOWCASE_TOP_LEVEL_DIRECTORY_MAP:
            existing_root_directory_ops.add((source, target))
        if op_type in {"move", "rename"} and source in SHOWCASE_TOP_LEVEL_FILE_TARGETS:
            existing_root_file_moves.add((source, target))

        normalized_operations.append(operation)

    prepended_operations: List[Dict[str, Any]] = []

    for root_name in SHOWCASE_NUMBERED_ROOTS:
        if root_name in existing_create_targets:
            continue
        prepended_operations.append(
            {
                "type": "create_folder",
                "source": "",
                "target": root_name,
                "reason": "\u4e3a\u5c55\u793a\u65b9\u6848\u51c6\u5907\u7edf\u4e00\u7684\u5e26\u7f16\u53f7\u4e00\u7ea7\u76ee\u5f55",
            }
        )

    for source_root, target_root in SHOWCASE_TOP_LEVEL_DIRECTORY_MAP.items():
        if (source_root, target_root) in existing_root_directory_ops:
            continue
        prepended_operations.append(
            {
                "type": "rename_folder",
                "source": source_root,
                "target": target_root,
                "reason": "\u5c06\u672a\u7f16\u53f7\u7684\u4e00\u7ea7\u76ee\u5f55\u76f4\u63a5\u5f52\u5e76\u5230\u5bf9\u5e94\u7684\u5e26\u7f16\u53f7\u6839\u76ee\u5f55",
            }
        )

    for source_file, target_file in SHOWCASE_TOP_LEVEL_FILE_TARGETS.items():
        if (source_file, target_file) in existing_root_file_moves:
            continue
        prepended_operations.append(
            {
                "type": "move",
                "source": source_file,
                "target": target_file,
                "reason": "\u5c06\u6839\u76ee\u5f55\u6563\u843d\u6587\u4ef6\u5f52\u6863\u5230\u5bf9\u5e94\u7684\u7f16\u53f7\u76ee\u5f55",
            }
        )

    normalized_plan["operations"] = _deduplicate_operations(
        prepended_operations + normalized_operations
    )

    summary = normalized_plan.get("summary")
    if isinstance(summary, str):
        normalized_plan["summary"] = summary.replace(
            "00-\u53c2\u8003\u8d44\u6599", SHOWCASE_REFERENCE_ROOT
        )

    summary_points = normalized_plan.get("summary_points")
    if isinstance(summary_points, list):
        normalized_summary_points = []
        numbering_summary_present = False
        for item in summary_points:
            if not isinstance(item, str):
                continue
            rewritten = item.replace("00-\u53c2\u8003\u8d44\u6599", SHOWCASE_REFERENCE_ROOT)
            if "01_" in rewritten and "12_" in rewritten:
                numbering_summary_present = True
            normalized_summary_points.append(rewritten)
        if not numbering_summary_present:
            normalized_summary_points.insert(
                0,
                "\u6240\u6709\u4e00\u7ea7\u76ee\u5f55\u7edf\u4e00\u6536\u53e3\u4e3a 00_ \u81f3 12_ \u8fd9\u7c7b\u5e26\u524d\u7f6e\u7f16\u53f7\u7684\u6839\u76ee\u5f55\uff0c\u907f\u514d\u6839\u76ee\u5f55\u540c\u65f6\u4fdd\u7559\u672a\u7f16\u53f7\u7684\u526f\u672c\u3002",
            )
        normalized_plan["summary_points"] = normalized_summary_points

    return normalized_plan


def _operation_identity(operation: Dict[str, Any]) -> tuple:
    return (
        str(operation.get("type", "")).strip().lower(),
        str(operation.get("source", "") or ""),
        str(operation.get("target", "") or ""),
    )


def _is_showcase_fragile_operation(operation: Dict[str, Any]) -> bool:
    if not isinstance(operation, dict):
        return False

    op_type = str(operation.get("type", "")).strip().lower()
    source = _normalize_relative_path(str(operation.get("source", "") or ""))
    reason = str(operation.get("reason", "") or "")
    target = str(operation.get("target", "") or "")
    normalized_target = _normalize_relative_path(target)
    target_parts = _split_relative_path(normalized_target)

    if "当前层级存在同名包装子目录" in reason:
        return True
    if "同名包装子目录在内容上移后可删除" in reason:
        return True
    if "文件名带有重复下载后缀" in reason:
        return True
    if len(target_parts) >= 2 and target_parts[-1] in {"00-参考资料", "00_参考资料"}:
        return True
    if len(target_parts) >= 2 and target_parts[-2] in {"00-参考资料", "00_参考资料"}:
        return True
    if op_type in {"rename_folder", "rename", "move"} and source and source == normalized_target:
        return True
    if (
        op_type == "rename_folder"
        and "同级目录已形成编号序列" in reason
        and (
            source.startswith("02_学生组例会/2021春/")
            or source.startswith("02_学生组例会/2021秋/")
        )
    ):
        return True

    return False


def _prune_non_executable_showcase_operations(
    analyzer: Any,
    folder_path: str,
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(plan, dict):
        return {}

    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        return plan

    if not hasattr(analyzer, "execute_plan"):
        return plan

    source_root = Path(folder_path).resolve()
    if not source_root.exists():
        return plan

    temp_root = Path(
        tempfile.mkdtemp(prefix="showcase-verify-", dir=str(source_root.parent))
    )
    verify_root = temp_root / source_root.name

    try:
        current_operations = [
            operation
            for operation in operations
            if not _is_showcase_fragile_operation(operation)
        ]

        for _ in range(4):
            if verify_root.exists():
                shutil.rmtree(verify_root, ignore_errors=True)
            shutil.copytree(source_root, verify_root)

            result = analyzer.execute_plan(
                str(verify_root),
                current_operations,
                write_readme=False,
            )
            if not result.get("success"):
                break

            successful_operation_ids = {
                _operation_identity(item.get("operation") or {})
                for item in (result.get("results") or [])
                if item.get("success") and isinstance(item.get("operation"), dict)
            }
            if not successful_operation_ids:
                break

            next_operations = [
                operation
                for operation in current_operations
                if _operation_identity(operation) in successful_operation_ids
            ]

            if len(next_operations) == len(current_operations):
                current_operations = next_operations
                break

            current_operations = next_operations

        pruned_plan = copy.deepcopy(plan)
        pruned_plan["operations"] = [
            operation
            for operation in current_operations
            if not _is_showcase_fragile_operation(operation)
        ]

        summary_points = pruned_plan.get("summary_points")
        if isinstance(summary_points, list):
            filtered_summary_points: List[str] = []
            for item in summary_points:
                if not isinstance(item, str):
                    continue
                if "00-参考资料" in item or "文件名带有重复下载后缀" in item:
                    continue
                if "当前层级存在同名包装子目录" in item:
                    continue
                filtered_summary_points.append(item)
            pruned_plan["summary_points"] = filtered_summary_points

        return pruned_plan
    except Exception:
        return plan
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def load_showcase_plan() -> Optional[Dict[str, Any]]:
    plan_path = _find_existing_showcase_plan_path()
    if not plan_path:
        return None

    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None

    plan = payload.get("plan")
    if not isinstance(plan, dict):
        return None

    payload["plan"] = _normalize_showcase_plan(plan)
    return payload


def save_showcase_plan(
    *,
    folder_path: str,
    plan: Dict[str, Any],
    mode: str = "standard",
    user_requests: Optional[List[str]] = None,
    source: str = "openclaw",
) -> Path:
    cache_dir = _showcase_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    normalized_requests = [
        str(item or "").strip() for item in (user_requests or []) if str(item or "").strip()
    ]
    normalized_plan = _normalize_showcase_plan(plan)
    payload = {
        "version": 1,
        "folder_path": os.path.abspath(folder_path),
        "mode": str(mode or "standard").strip().lower() or "standard",
        "source": source,
        "user_requests": normalized_requests,
        "plan": normalized_plan,
    }

    plan_path = _showcase_plan_path()
    plan_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return plan_path


def generate_showcase_analysis(
    analyzer: Any,
    folder_path: str,
    *,
    mode: str = "standard",
    target_root_path: str = "",
    user_requests: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if not is_showcase_folder(folder_path):
        return {
            "success": False,
            "error": "展示方案生成只支持预设目录：D:\\Coding Demo\\202603_OpenClaw_Files\\Test\\Show_辅导员",
            "demo_mode": False,
        }

    result = analyzer.analyze_folder(
        folder_path,
        mode=mode,
        target_root_path=target_root_path,
        user_requests=user_requests,
    )
    if not result.get("success"):
        return result

    normalized_plan = _normalize_showcase_plan(result.get("plan") or {})
    executable_plan = _prune_non_executable_showcase_operations(
        analyzer,
        folder_path,
        normalized_plan,
    )

    save_path = save_showcase_plan(
        folder_path=folder_path,
        plan=executable_plan,
        mode=mode,
        user_requests=user_requests,
        source="openclaw",
    )

    enriched = dict(result)
    enriched["plan"] = executable_plan
    enriched["showcase_plan_saved"] = True
    enriched["showcase_plan_path"] = str(save_path)
    return enriched


def get_showcase_analysis(
    folder_path: str,
    mode: str = "standard",
    target_root_path: str = "",
    user_requests: Optional[List[str]] = None,
) -> Dict[str, Any]:
    del target_root_path
    del user_requests

    normalized_mode = str(mode or "standard").strip().lower()
    if normalized_mode != "standard":
        return {
            "success": False,
            "error": "展示模式仅支持标准整理场景，不支持微信专项清理。",
            "demo_mode": True,
            "demo_label": "展示模式",
        }

    if not is_showcase_folder(folder_path):
        return {
            "success": False,
            "error": "展示模式只对预设的展示目录生效：D:\\Coding Demo\\202603_OpenClaw_Files\\Test\\Show_辅导员",
            "demo_mode": True,
            "demo_label": "展示模式",
        }

    cached = load_showcase_plan()
    if not cached:
        return {
            "success": False,
            "error": "展示方案缓存不存在。请先使用 OpenClaw 生成并保存展示方案。",
            "demo_mode": True,
            "demo_label": "展示模式",
        }

    cached_folder = cached.get("folder_path")
    if _normalize_path(cached_folder or "") != SHOWCASE_FOLDER_PATH:
        return {
            "success": False,
            "error": "当前展示方案缓存与预设目录不匹配，请重新生成展示方案。",
            "demo_mode": True,
            "demo_label": "展示模式",
        }

    existing_plan_path = _find_existing_showcase_plan_path() or _showcase_plan_path()

    return {
        "success": True,
        "plan": cached.get("plan") or {},
        "folder_structure": {},
        "mode": "standard",
        "target_root_path": "",
        "demo_mode": True,
        "demo_label": "展示模式",
        "showcase_plan_source": cached.get("source") or "openclaw",
        "showcase_plan_path": str(existing_plan_path),
    }
