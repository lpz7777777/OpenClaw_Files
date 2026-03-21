import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.file_analyzer import FileAnalyzer
from backend.showcase_plan import SHOWCASE_FOLDER_PATH, generate_showcase_analysis

SHOWCASE_USER_REQUESTS = [
    "请确保整理后的各个主要文件夹都带有两位数字前缀编号，例如 01_、02_、03_ 这样的格式。",
]


def main() -> int:
    analyzer = FileAnalyzer()
    result = generate_showcase_analysis(
        analyzer,
        SHOWCASE_FOLDER_PATH,
        mode="standard",
        user_requests=SHOWCASE_USER_REQUESTS,
    )

    if not result.get("success"):
        print(f"[showcase] failed: {result.get('error', 'unknown error')}")
        return 1

    plan = result.get("plan") or {}
    operations = plan.get("operations") or []
    print("[showcase] saved showcase plan")
    print(f"[showcase] path: {result.get('showcase_plan_path', '')}")
    print(f"[showcase] operations: {len(operations)}")
    print(f"[showcase] summary: {plan.get('summary', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
