"""
微信文件整理模块
负责扫描微信存储目录，检测重复文件，并生成整理建议
"""

import os
import hashlib
import json
from pathlib import Path
from datetime import datetime


# 微信文件类型分类映射
WECHAT_FILE_CATEGORIES = {
    "images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic"],
    "videos": [".mp4", ".mov", ".avi", ".wmv", ".mkv", ".flv"],
    "documents": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md"],
    "audio": [".mp3", ".wav", ".aac", ".wma", ".flac", ".m4a"],
    "archives": [".zip", ".rar", ".7z", ".tar", ".gz"],
    "other": []
}


def get_wechat_path():
    """
    获取微信存储目录路径
    Windows 默认路径：文档/WeChat Files/
    """
    home = Path.home()
    wechat_path = home / "Documents" / "WeChat Files"
    
    if wechat_path.exists():
        return wechat_path
    
    # 尝试其他可能的位置
    possible_paths = [
        home / "My Documents" / "WeChat Files",
        Path("C:/Users") / os.getenv("USERNAME") / "Documents" / "WeChat Files",
    ]
    
    for path in possible_paths:
        if path.exists():
            return path
    
    return None


def calculate_file_hash(file_path, chunk_size=8192):
    """
    计算文件的 MD5 哈希值
    """
    md5_hash = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()
    except (IOError, OSError):
        return None


def scan_wechat_files(wechat_path):
    """
    扫描微信目录下的所有文件
    返回文件列表和统计信息
    """
    files = []
    stats = {
        "total_files": 0,
        "total_size": 0,
        "by_category": {},
        "by_account": {}
    }
    
    # 遍历微信账号目录
    try:
        accounts = [d for d in wechat_path.iterdir() if d.is_dir() and not d.name.startswith(".")]
    except PermissionError:
        return None, {"error": "无法访问微信目录，请检查权限"}
    
    for account_dir in accounts:
        account_name = account_dir.name
        stats["by_account"][account_name] = {"files": 0, "size": 0}
        
        # 扫描 FileStorage 目录（微信文件存储位置）
        file_storage = account_dir / "FileStorage"
        if not file_storage.exists():
            continue
        
        # 扫描不同类型的子目录
        subdirs = {
            "File": "documents",
            "Image": "images",
            "Video": "videos",
            "Music": "audio"
        }
        
        for subdir, category in subdirs.items():
            dir_path = file_storage / subdir
            if not dir_path.exists():
                continue
            
            # 遍历年份/月份目录
            for year_month in dir_path.iterdir():
                if not year_month.is_dir():
                    continue
                
                try:
                    for file_path in year_month.glob("*"):
                        if file_path.is_file() and not file_path.name.startswith("~"):
                            try:
                                stat = file_path.stat()
                                file_ext = file_path.suffix.lower()
                                
                                file_info = {
                                    "path": str(file_path),
                                    "name": file_path.name,
                                    "size": stat.st_size,
                                    "modified": stat.st_mtime,
                                    "category": get_file_category(file_ext),
                                    "extension": file_ext,
                                    "account": account_name,
                                    "relative_path": str(file_path.relative_to(wechat_path))
                                }
                                
                                files.append(file_info)
                                stats["total_files"] += 1
                                stats["total_size"] += stat.st_size
                                
                                # 按分类统计
                                if file_info["category"] not in stats["by_category"]:
                                    stats["by_category"][file_info["category"]] = {"files": 0, "size": 0}
                                stats["by_category"][file_info["category"]]["files"] += 1
                                stats["by_category"][file_info["category"]]["size"] += stat.st_size
                                
                                # 按账号统计
                                stats["by_account"][account_name]["files"] += 1
                                stats["by_account"][account_name]["size"] += stat.st_size
                                
                            except (OSError, PermissionError):
                                continue
                except (OSError, PermissionError):
                    continue
    
    return files, stats


def get_file_category(extension):
    """
    根据文件扩展名获取分类
    """
    for category, extensions in WECHAT_FILE_CATEGORIES.items():
        if extension in extensions:
            return category
    return "other"


def find_duplicates(files):
    """
    查找重复文件（基于文件内容和大小）
    返回重复文件组
    """
    # 首先按大小分组
    size_groups = {}
    for file_info in files:
        size = file_info["size"]
        if size not in size_groups:
            size_groups[size] = []
        size_groups[size].append(file_info)
    
    # 对大小相同的文件计算哈希值
    duplicates = []
    for size, group in size_groups.items():
        if len(group) < 2:
            continue
        
        # 计算哈希值
        hash_groups = {}
        for file_info in group:
            file_hash = calculate_file_hash(file_info["path"])
            if file_hash:
                if file_hash not in hash_groups:
                    hash_groups[file_hash] = []
                hash_groups[file_hash].append(file_info)
        
        # 找出重复的文件组
        for file_hash, dup_group in hash_groups.items():
            if len(dup_group) >= 2:
                # 按修改时间排序，保留最新的
                dup_group.sort(key=lambda x: x["modified"], reverse=True)
                duplicates.append({
                    "hash": file_hash,
                    "size": size,
                    "files": dup_group,
                    "keep": dup_group[0],  # 保留最新的
                    "remove": dup_group[1:]  # 删除旧的
                })
    
    return duplicates


def generate_cleanup_plan(files, duplicates, target_folder):
    """
    生成整理计划
    """
    operations = []
    categories_used = set()
    
    # 1. 为重复文件生成删除操作
    for dup_group in duplicates:
        for file_info in dup_group["remove"]:
            operations.append({
                "type": "delete",
                "source": file_info["path"],
                "target": "",
                "reason": f"重复文件（保留：{Path(dup_group['keep']['path']).name}）",
                "category": "duplicate"
            })
    
    # 2. 按文件类型分类移动
    for file_info in files:
        # 跳过已标记删除的文件
        is_duplicate = any(
            file_info in dup["remove"] 
            for dup in duplicates
        )
        if is_duplicate:
            continue
        
        # 生成目标路径
        category = file_info["category"]
        categories_used.add(category)
        target_path = Path(target_folder) / category / file_info["name"]
        
        # 如果目标文件已存在，添加序号
        counter = 1
        original_stem = Path(file_info["name"]).stem
        original_suffix = Path(file_info["name"]).suffix
        while target_path.exists():
            target_path = Path(target_folder) / category / f"{original_stem}_{counter}{original_suffix}"
            counter += 1
        
        operations.append({
            "type": "move",
            "source": file_info["path"],
            "target": str(target_path),
            "reason": f"按类型整理到 {category} 文件夹",
            "category": category
        })
    
    # 生成摘要
    summary_points = [
        f"扫描到 {len(files)} 个微信文件",
        f"发现 {len(duplicates)} 组重复文件，共 {sum(len(d['remove']) for d in duplicates)} 个重复文件",
        f"将按 {len(categories_used)} 个类别整理文件：{', '.join(categories_used)}",
        f"目标目录：{target_folder}"
    ]
    
    return {
        "operations": operations,
        "summary": "；".join(summary_points),
        "summary_points": summary_points,
        "categories": list(categories_used),
        "stats": {
            "total_files": len(files),
            "duplicates": sum(len(d["remove"]) for d in duplicates),
            "to_move": len(operations) - sum(len(d["remove"]) for d in duplicates)
        }
    }


def cleanup_wechat_files(target_folder=None):
    """
    主函数：清理微信文件
    """
    # 1. 获取微信路径
    wechat_path = get_wechat_path()
    if not wechat_path:
        return {
            "success": False,
            "error": "未找到微信存储目录，请确认已安装微信并登录过"
        }
    
    # 2. 扫描文件
    files, scan_result = scan_wechat_files(wechat_path)
    if files is None:
        return {
            "success": False,
            "error": scan_result.get("error", "扫描失败")
        }
    
    if not files:
        return {
            "success": False,
            "error": "微信目录下没有找到文件"
        }
    
    # 3. 查找重复文件
    duplicates = find_duplicates(files)
    
    # 4. 生成整理计划
    if not target_folder:
        # 如果没有指定目标文件夹，返回计划供用户确认
        plan = generate_cleanup_plan(files, duplicates, str(Path.home() / "WeChat_Files_Cleaned"))
    else:
        plan = generate_cleanup_plan(files, duplicates, target_folder)
    
    # 5. 返回结果
    return {
        "success": True,
        "wechat_path": str(wechat_path),
        "files": files,
        "duplicates": duplicates,
        "plan": plan,
        "scan_stats": scan_result
    }


def open_wechat_folder():
    """
    打开微信存储目录
    """
    wechat_path = get_wechat_path()
    if not wechat_path:
        return {
            "success": False,
            "error": "未找到微信存储目录"
        }
    
    return {
        "success": True,
        "path": str(wechat_path)
    }


if __name__ == "__main__":
    # 测试
    result = cleanup_wechat_files()
    print(json.dumps(result, ensure_ascii=False, indent=2))
