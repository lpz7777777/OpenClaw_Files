/**
 * OpenClaw Files 前端渲染逻辑
 * 负责界面交互、文件预览、分析结果展示、百度网盘同步等功能
 */

// 引入依赖
const { ipcRenderer } = require("electron"); // Electron 进程间通信
const axios = require("axios"); // HTTP 请求
const fs = require("fs"); // 文件系统操作
const path = require("path"); // 路径处理
const mammoth = require("mammoth"); // Word 文档解析
const XLSX = require("xlsx"); // Excel 表格解析

/**
 * 常量定义
 */
const API_BASE = "http://localhost:8765"; // 后端 API 基础地址
const PREVIEW_BYTE_LIMIT = 200 * 1024; // 文件预览大小限制（200KB）
const WORD_EXTENSIONS = new Set([".doc", ".docx"]); // Word 文档扩展名
const EXCEL_EXTENSIONS = new Set([".xls", ".xlsx", ".csv"]); // Excel 表格扩展名
const THEME_STORAGE_KEY = "openclaw-workspace-theme"; // 主题存储键名
const WECHAT_CLEANUP_STORAGE_KEY = "openclaw-wechat-cleanup-config";
const WECHAT_CLEANUP_MODE = "wechat_cleanup";

/**
 * 主题定义
 */
const THEME_DEFINITIONS = [
    {
        id: "workspace",
        label: "雾杉",
        description: "暖纸质感、沉稳配色，适合长时间整理文件。",
    },
    {
        id: "mac",
        label: "晴空",
        description: "明亮玻璃感和轻盈高光，保留 macOS 风格气质。",
    },
    {
        id: "fjord",
        label: "北岸",
        description: "冷静蓝灰与工程线稿感，适合偏技术型工作流。",
    },
    {
        id: "amber",
        label: "琥珀",
        description: "奶油纸页和琥珀点缀，像在桌面上整理实体档案。",
    },
    {
        id: "sage",
        label: "雨后",
        description: "低饱和绿调与柔雾背景，视觉更松弛。",
    },
    {
        id: "petal",
        label: "珊瑚",
        description: "柔和珊瑚色和清晨云雾感，页面更有呼吸感。",
    },
];
const THEMES = new Set(THEME_DEFINITIONS.map((theme) => theme.id)); // 主题 ID 集合
const DEFAULT_THEME = "workspace"; // 默认主题
const DEFAULT_BDPAN_DAILY_TIME = "02:00"; // 默认百度网盘同步时间

/**
 * 应用状态管理
 */
const state = {
    currentFolderPath: null,
    currentPlan: null,
    currentTree: null,
    treeStats: {
        files: 0,
        folders: 0,
        totalSize: 0,
    },
    openTabs: [],
    activeTabId: null,
    selectedNodePath: null,
    expandedPaths: new Set(),
    isAnalyzing: false,
    isExecutingOperation: false,
    lastResult: null,
    canRollback: false,
    completedOperationIndexes: new Set(),
    discardedOperationIndexes: new Set(),
    analysisTone: "idle",
    analysisMessage: "选择文件夹后，这里会显示 OpenClaw 输出的整理建议、操作计划和执行结果。",
    currentTheme: "workspace",
    cloudSyncStatus: null,
    cloudSyncFeedback: null,
    bdpanRemotePath: "",
    bdpanRemotePathEdited: false,
    bdpanDailyTime: DEFAULT_BDPAN_DAILY_TIME,
    bdpanTimezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai",
    bdpanTimezoneEdited: false,
    isCloudSyncBusy: false,
    isCloudSyncLoading: false,
    analysisMode: "standard",
    analysisTargetRootPath: "",
    wechatCleanupConfig: {
        sourcePath: "",
        targetPath: "",
    },
};

/**
 * DOM 元素引用
 */
const selectFolderBtn = document.getElementById("selectFolderBtn"); // 选择文件夹按钮
const wechatCleanupBtn = document.getElementById("wechatCleanupBtn"); // 微信清理按钮
const analyzeBtn = document.getElementById("analyzeBtn"); // 分析按钮
const themeSelect = document.getElementById("themeSelect"); // 主题选择器
const themeDescription = document.getElementById("themeDescription"); // 主题描述
const selectedPath = document.getElementById("selectedPath"); // 选中路径显示
const explorerStats = document.getElementById("explorerStats"); // 资源管理器统计
const explorerTree = document.getElementById("explorerTree"); // 资源管理器树
const tabStrip = document.getElementById("tabStrip"); // 标签栏
const editorMeta = document.getElementById("editorMeta"); // 编辑器元信息
const editorContent = document.getElementById("editorContent"); // 编辑器内容
const analysisStatus = document.getElementById("analysisStatus"); // 分析状态
const analysisMeta = document.getElementById("analysisMeta"); // 分析元信息
const planSummary = document.getElementById("planSummary"); // 计划摘要
const categoriesList = document.getElementById("categoriesList"); // 分类列表
const operationsMeta = document.getElementById("operationsMeta"); // 操作元信息
const operationsList = document.getElementById("operationsList"); // 操作列表
const resultDisplay = document.getElementById("resultDisplay"); // 结果显示
const gatewayStatusPill = document.getElementById("gatewayStatusPill"); // Gateway 状态胶囊
const gatewayStatusText = document.getElementById("gatewayStatusText"); // Gateway 状态文本
const topbarJobsChips = document.getElementById("topbarJobsChips"); // 顶部任务芯片
const bdpanMeta = document.getElementById("bdpanMeta"); // 百度网盘元信息
const bdpanStatusCard = document.getElementById("bdpanStatusCard"); // 百度网盘状态卡片
const bdpanRemotePathInput = document.getElementById("bdpanRemotePathInput"); // 百度网盘远程路径输入
const bdpanUploadBtn = document.getElementById("bdpanUploadBtn"); // 百度网盘上传按钮
const bdpanRefreshBtn = document.getElementById("bdpanRefreshBtn"); // 百度网盘刷新按钮
const bdpanDailyTimeInput = document.getElementById("bdpanDailyTimeInput"); // 百度网盘每日时间输入
const bdpanTimezoneInput = document.getElementById("bdpanTimezoneInput"); // 百度网盘时区输入
const bdpanScheduleBtn = document.getElementById("bdpanScheduleBtn"); // 百度网盘调度按钮
const bdpanJobsList = document.getElementById("bdpanJobsList"); // 百度网盘任务列表
const confirmBtn = document.getElementById("confirmBtn"); // 确认按钮
const newAnalysisBtn = document.getElementById("newAnalysisBtn"); // 重新分析按钮
const rollbackBtn = document.getElementById("rollbackBtn"); // 回滚按钮
const cancelBtn = document.getElementById("cancelBtn"); // 取消按钮
const wechatCleanupDialog = document.getElementById("wechatCleanupDialog"); // 微信清理弹窗
const wechatSourcePathInput = document.getElementById("wechatSourcePathInput"); // 微信源目录输入
const wechatTargetPathInput = document.getElementById("wechatTargetPathInput"); // 微信目标目录输入
const wechatSourceBrowseBtn = document.getElementById("wechatSourceBrowseBtn"); // 微信源目录浏览
const wechatTargetBrowseBtn = document.getElementById("wechatTargetBrowseBtn"); // 微信目标目录浏览
const wechatCleanupSaveBtn = document.getElementById("wechatCleanupSaveBtn"); // 微信清理保存
const wechatCleanupRunBtn = document.getElementById("wechatCleanupRunBtn"); // 微信清理执行

/**
 * 初始化主题选项
 */
renderThemeOptions();

/**
 * 主题选择事件监听
 */
themeSelect.addEventListener("change", (event) => {
    applyTheme(event.target.value);
});

/**
 * 百度网盘远程路径输入事件监听
 */
bdpanRemotePathInput.addEventListener("input", (event) => {
    state.bdpanRemotePath = event.target.value;
    state.bdpanRemotePathEdited = true;
    renderCloudSyncPanel();
    updateActionState();
});

/**
 * 百度网盘每日时间输入事件监听
 */
bdpanDailyTimeInput.addEventListener("input", (event) => {
    state.bdpanDailyTime = event.target.value;
    updateActionState();
});

/**
 * 百度网盘时区输入事件监听
 */
bdpanTimezoneInput.addEventListener("input", (event) => {
    state.bdpanTimezone = event.target.value;
    state.bdpanTimezoneEdited = true;
    updateActionState();
});

/**
 * 选择文件夹按钮点击事件
 */
selectFolderBtn.addEventListener("click", async () => {
    const folderPath = await ipcRenderer.invoke("select-folder");
    if (!folderPath) {
        return;
    }

    await openFolder(folderPath);
});

wechatCleanupBtn.addEventListener("click", async () => {
    await runWechatCleanup();
});

wechatCleanupBtn.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    openWechatCleanupDialog();
});

/**
 * 分析按钮点击事件
 */
analyzeBtn.addEventListener("click", async () => {
    if (!state.currentFolderPath || state.isAnalyzing || state.isExecutingOperation || state.isCloudSyncBusy) {
        return;
    }

    await analyzeFolder(state.currentFolderPath);
});

/**
 * 重新分析按钮点击事件
 */
newAnalysisBtn.addEventListener("click", async () => {
    if (!state.currentFolderPath || state.isAnalyzing || state.isExecutingOperation || state.isCloudSyncBusy) {
        return;
    }

    await analyzeFolder(state.currentFolderPath);
});

/**
 * 确认执行按钮点击事件
 */
confirmBtn.addEventListener("click", async () => {
    const pending = getPendingOperations();
    if (pending.length === 0) {
        setAnalysisStatus("error", "当前没有可执行的整理建议。");
        renderAnalysis();
        return;
    }

    const confirmed = window.confirm(`确定要一次性执行剩余的 ${pending.length} 条建议吗？`);
    if (!confirmed) {
        return;
    }

    await executeOperations(
        pending.map(({ index }) => index),
        `正在执行剩余的 ${pending.length} 条操作，请稍候...`,
        { writeReadme: state.analysisMode !== WECHAT_CLEANUP_MODE }
    );
});

/**
 * 回滚按钮点击事件
 */
rollbackBtn.addEventListener("click", async () => {
    if (!state.canRollback || state.isExecutingOperation || state.isCloudSyncBusy) {
        setAnalysisStatus("error", "当前没有可回滚的操作。");
        renderAnalysis();
        return;
    }

    const confirmed = window.confirm("确定要回滚最近这一轮已经确认执行的文件操作吗？");
    if (!confirmed) {
        return;
    }

    setAnalysisStatus("loading", "正在回滚最近的文件操作...");
    renderAnalysis();
    updateActionState();

    try {
        const response = await axios.post(`${API_BASE}/rollback`, {});

        if (response.data.success) {
            state.lastResult = {
                type: "success",
                message: "回滚成功，最近已执行的变更已恢复。",
                at: Date.now(),
            };
            state.canRollback = false;
            resetOperationProgress();
            setAnalysisStatus("success", "回滚完成，目录树已刷新。");
            await loadFolderTree(state.currentFolderPath, true);
            openOverviewTab();
        } else {
            state.lastResult = {
                type: "error",
                message: `回滚失败：${response.data.error}`,
                at: Date.now(),
            };
            setAnalysisStatus("error", `回滚失败：${response.data.error}`);
        }
    } catch (error) {
        state.lastResult = {
            type: "error",
            message: `回滚出错：${error.message}`,
            at: Date.now(),
        };
        setAnalysisStatus("error", `回滚出错：${error.message}`);
    }

    renderAnalysis();
    updateActionState();
});

bdpanUploadBtn.addEventListener("click", async () => {
    await uploadCurrentFolderToBdpan();
});

bdpanRefreshBtn.addEventListener("click", async () => {
    await loadCloudSyncStatus();
});

bdpanScheduleBtn.addEventListener("click", async () => {
    await createBdpanSchedule();
});

cancelBtn.addEventListener("click", () => {
    state.currentPlan = null;
    state.lastResult = null;
    resetOperationProgress();
    setAnalysisStatus("idle", "输出已清空。你可以重新分析当前文件夹。");
    renderAnalysis();
    renderEditor();
    updateActionState();
});

wechatSourceBrowseBtn.addEventListener("click", async () => {
    const folderPath = await ipcRenderer.invoke("select-folder");
    if (folderPath) {
        wechatSourcePathInput.value = folderPath;
    }
});

wechatTargetBrowseBtn.addEventListener("click", async () => {
    const folderPath = await ipcRenderer.invoke("select-folder");
    if (folderPath) {
        wechatTargetPathInput.value = folderPath;
    }
});

wechatCleanupSaveBtn.addEventListener("click", () => {
    const result = persistWechatCleanupConfigFromDialog();
    if (!result.ok) {
        window.alert(result.message);
        return;
    }
    wechatCleanupDialog.close("save");
});

wechatCleanupRunBtn.addEventListener("click", async () => {
    const result = persistWechatCleanupConfigFromDialog();
    if (!result.ok) {
        window.alert(result.message);
        return;
    }
    wechatCleanupDialog.close("run");
    await runWechatCleanup();
});

async function openFolder(folderPath, options = {}) {
    const analysisMode = options.analysisMode === WECHAT_CLEANUP_MODE ? WECHAT_CLEANUP_MODE : "standard";
    const targetRootPath = String(options.targetRootPath || "").trim();

    state.currentFolderPath = folderPath;
    state.currentPlan = null;
    state.lastResult = null;
    state.canRollback = false;
    resetOperationProgress();
    state.selectedNodePath = folderPath;
    state.expandedPaths = new Set([folderPath]);
    state.cloudSyncFeedback = null;
    state.analysisMode = analysisMode;
    state.analysisTargetRootPath = analysisMode === WECHAT_CLEANUP_MODE ? targetRootPath : "";
    initializeBdpanDefaults(folderPath);

    selectedPath.textContent = buildSelectedPathText();

    setAnalysisStatus(
        "loading",
        analysisMode === WECHAT_CLEANUP_MODE
            ? "正在读取微信文件目录并准备专项清理分析..."
            : "正在读取目录结构并准备分析..."
    );
    renderAnalysis();
    updateActionState();

    await loadFolderTree(folderPath, false);
    openOverviewTab();
    await analyzeFolder(folderPath, {
        mode: analysisMode,
        targetRootPath: state.analysisTargetRootPath,
    });
}

function initializeBdpanDefaults(folderPath) {
    const folderName = path.basename(folderPath || "").trim();
    state.bdpanRemotePath = folderName ? `${folderName}/` : "";
    state.bdpanRemotePathEdited = false;
    state.bdpanDailyTime = DEFAULT_BDPAN_DAILY_TIME;
    state.bdpanTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
    state.bdpanTimezoneEdited = false;

    bdpanRemotePathInput.value = state.bdpanRemotePath;
    bdpanDailyTimeInput.value = state.bdpanDailyTime;
    bdpanTimezoneInput.value = state.bdpanTimezone;
}

function buildSelectedPathText() {
    if (!state.currentFolderPath) {
        return "尚未打开任何文件夹";
    }

    if (state.analysisMode === WECHAT_CLEANUP_MODE && state.analysisTargetRootPath) {
        return `${state.currentFolderPath}  →  ${state.analysisTargetRootPath}`;
    }

    return state.currentFolderPath;
}

function openWechatCleanupDialog() {
    wechatSourcePathInput.value = state.wechatCleanupConfig.sourcePath || "";
    wechatTargetPathInput.value = state.wechatCleanupConfig.targetPath || "";
    if (!wechatCleanupDialog.open) {
        wechatCleanupDialog.showModal();
    }
}

function normalizeWechatCleanupConfig(config) {
    return {
        sourcePath: String(config?.sourcePath || "").trim(),
        targetPath: String(config?.targetPath || "").trim(),
    };
}

function persistWechatCleanupConfigFromDialog() {
    const config = normalizeWechatCleanupConfig({
        sourcePath: wechatSourcePathInput.value,
        targetPath: wechatTargetPathInput.value,
    });

    if (!config.sourcePath) {
        return { ok: false, message: "请先填写微信文件夹。" };
    }
    if (!config.targetPath) {
        return { ok: false, message: "请先填写整理目标文件夹。" };
    }
    if (path.resolve(config.sourcePath) === path.resolve(config.targetPath)) {
        return { ok: false, message: "微信文件夹和整理目标文件夹不能相同。" };
    }

    state.wechatCleanupConfig = config;
    localStorage.setItem(WECHAT_CLEANUP_STORAGE_KEY, JSON.stringify(config));
    return { ok: true, config };
}

function initializeWechatCleanupConfig() {
    try {
        const storedConfig = JSON.parse(localStorage.getItem(WECHAT_CLEANUP_STORAGE_KEY) || "{}");
        state.wechatCleanupConfig = normalizeWechatCleanupConfig(storedConfig);
    } catch (error) {
        state.wechatCleanupConfig = { sourcePath: "", targetPath: "" };
    }
}

async function runWechatCleanup() {
    if (state.isAnalyzing || state.isExecutingOperation || state.isCloudSyncBusy) {
        return;
    }

    const config = normalizeWechatCleanupConfig(state.wechatCleanupConfig);
    if (!config.sourcePath || !config.targetPath) {
        openWechatCleanupDialog();
        return;
    }

    if (path.resolve(config.sourcePath) === path.resolve(config.targetPath)) {
        window.alert("微信文件夹和整理目标文件夹不能相同。");
        openWechatCleanupDialog();
        return;
    }

    await openFolder(config.sourcePath, {
        analysisMode: WECHAT_CLEANUP_MODE,
        targetRootPath: config.targetPath,
    });
}

async function loadCloudSyncStatus() {
    if (state.isCloudSyncBusy) {
        return;
    }

    state.isCloudSyncLoading = true;
    renderCloudSyncPanel();
    updateActionState();

    try {
        const response = await axios.post(`${API_BASE}/cloud/status`, {});
        if (response.data.success) {
            state.cloudSyncStatus = response.data;
            if (state.currentFolderPath && !state.bdpanRemotePathEdited && !state.bdpanRemotePath) {
                initializeBdpanDefaults(state.currentFolderPath);
            }
            if (!state.bdpanTimezoneEdited && response.data.default_timezone) {
                state.bdpanTimezone = response.data.default_timezone;
                bdpanTimezoneInput.value = state.bdpanTimezone;
            }
        } else {
            state.cloudSyncFeedback = {
                type: "error",
                message: `同步状态检查失败：${response.data.error}`,
                at: Date.now(),
            };
        }
    } catch (error) {
        state.cloudSyncFeedback = {
            type: "error",
            message: `同步状态检查失败：${error.message}`,
            at: Date.now(),
        };
    } finally {
        state.isCloudSyncLoading = false;
        renderCloudSyncPanel();
        updateActionState();
    }
}

async function loadFolderTree(folderPath, preserveTabs = true) {
    try {
        const tree = await buildDirectoryTree(folderPath);
        state.currentTree = tree;
        state.treeStats = tree.stats;

        if (!preserveTabs) {
            state.openTabs = [];
            state.activeTabId = null;
        } else {
            await pruneMissingTabs();
        }

        renderExplorer();
        renderEditor();
        updateActionState();
    } catch (error) {
        state.currentTree = null;
        state.treeStats = { files: 0, folders: 0, totalSize: 0 };
        renderExplorer();
        setAnalysisStatus("error", `读取文件夹结构失败：${error.message}`);
        renderAnalysis();
    }
}

async function analyzeFolder(folderPath, options = {}) {
    const mode = options.mode || state.analysisMode || "standard";
    const targetRootPath =
        mode === WECHAT_CLEANUP_MODE
            ? String(options.targetRootPath || state.analysisTargetRootPath || "").trim()
            : "";

    state.isAnalyzing = true;
    state.currentPlan = null;
    resetOperationProgress();
    state.canRollback = false;
    state.analysisMode = mode;
    state.analysisTargetRootPath = targetRootPath;
    selectedPath.textContent = buildSelectedPathText();
    setAnalysisStatus(
        "loading",
        mode === WECHAT_CLEANUP_MODE
            ? "OpenClaw 正在分析微信文件，并生成分类整理方案..."
            : "OpenClaw 正在分析当前文件夹结构..."
    );
    renderAnalysis();
    updateActionState();

    try {
        const response = await axios.post(`${API_BASE}/analyze`, {
            folder_path: folderPath,
            mode,
            target_root_path: targetRootPath,
        });

        if (response.data.success) {
            state.currentPlan = response.data.plan;
            setAnalysisStatus(
                "success",
                mode === WECHAT_CLEANUP_MODE
                    ? "微信文件清理方案已生成，右侧可确认执行到目标目录。"
                    : "分析完成，右侧已生成更细的整理建议。"
            );
            openOverviewTab();
        } else {
            setAnalysisStatus("error", `分析失败：${response.data.error}`);
        }
    } catch (error) {
        setAnalysisStatus("error", `无法连接到后端服务：${error.message}`);
    }

    state.isAnalyzing = false;
    renderAnalysis();
    renderEditor();
    updateActionState();
}

async function buildDirectoryTree(rootPath) {
    const stats = {
        files: 0,
        folders: 0,
        totalSize: 0,
    };

    async function walk(targetPath, isRoot = false) {
        const targetStat = await fs.promises.stat(targetPath);
        const node = {
            name: path.basename(targetPath) || targetPath,
            path: targetPath,
            type: "directory",
            expanded: isRoot || state.expandedPaths.has(targetPath),
            modifiedAt: targetStat.mtimeMs,
            children: [],
        };

        const entries = await fs.promises.readdir(targetPath, { withFileTypes: true });
        entries.sort((left, right) => {
            const leftIsDir = left.isDirectory();
            const rightIsDir = right.isDirectory();

            if (leftIsDir !== rightIsDir) {
                return leftIsDir ? -1 : 1;
            }

            return left.name.localeCompare(right.name, "zh-CN");
        });

        for (const entry of entries) {
            const entryPath = path.join(targetPath, entry.name);

            if (entry.isDirectory()) {
                stats.folders += 1;
                const child = await walk(entryPath, false);
                node.children.push(child);
                continue;
            }

            const entryStat = await fs.promises.stat(entryPath);
            stats.files += 1;
            stats.totalSize += entryStat.size;
            node.children.push({
                name: entry.name,
                path: entryPath,
                type: "file",
                size: entryStat.size,
                modifiedAt: entryStat.mtimeMs,
                extension: path.extname(entry.name).toLowerCase(),
            });
        }

        return node;
    }

    const root = await walk(rootPath, true);
    return {
        root,
        stats,
    };
}

function renderExplorer() {
    if (!state.currentTree || !state.currentFolderPath) {
        explorerStats.textContent = "等待打开";
        explorerTree.className = "explorer-tree empty-state";
        explorerTree.textContent = "选择一个文件夹后，这里会显示完整的目录结构。";
        return;
    }

    explorerStats.textContent = `${state.treeStats.folders} folders · ${state.treeStats.files} files`;
    explorerTree.className = "explorer-tree";
    explorerTree.innerHTML = "";
    explorerTree.appendChild(createTreeBranch(state.currentTree.root, 0));
}

function createTreeBranch(node, depth) {
    const branch = document.createElement("div");
    branch.className = "tree-branch";

    const item = document.createElement("button");
    item.type = "button";
    item.className = `tree-item tree-item-${node.type}`;
    if (state.selectedNodePath === node.path) {
        item.classList.add("active");
    }
    item.style.setProperty("--depth", depth);

    const iconMeta =
        node.type === "directory"
            ? { label: node.expanded ? "[-]" : "[+]", tone: "folder" }
            : fileIconMeta(node.name, node.extension);

    const icon = document.createElement("span");
    icon.className = `tree-icon tree-icon-${iconMeta.tone}`;
    icon.textContent = iconMeta.label;

    const label = document.createElement("span");
    label.className = "tree-label";
    label.textContent = node.name;

    item.append(icon, label);

    if (node.type === "directory") {
        item.addEventListener("click", () => {
            state.selectedNodePath = node.path;
            if (state.expandedPaths.has(node.path)) {
                state.expandedPaths.delete(node.path);
                node.expanded = false;
            } else {
                state.expandedPaths.add(node.path);
                node.expanded = true;
            }
            renderExplorer();
        });
    } else {
        item.addEventListener("click", async () => {
            state.selectedNodePath = node.path;
            renderExplorer();
            await openFileTab(node.path);
        });
    }

    branch.appendChild(item);

    if (node.type === "directory" && node.expanded && Array.isArray(node.children)) {
        const children = document.createElement("div");
        children.className = "tree-children";

        node.children.forEach((child) => {
            children.appendChild(createTreeBranch(child, depth + 1));
        });

        if (node.children.length === 0) {
            const empty = document.createElement("div");
            empty.className = "tree-empty";
            empty.textContent = "空文件夹";
            children.appendChild(empty);
        }

        branch.appendChild(children);
    }

    return branch;
}

async function openFileTab(filePath) {
    const existingTab = state.openTabs.find((tab) => tab.path === filePath);
    if (existingTab) {
        existingTab.payload = await readFilePreview(filePath);
        state.activeTabId = existingTab.id;
        renderEditor();
        return;
    }

    const filePreview = await readFilePreview(filePath);
    const tab = {
        id: `file:${filePath}`,
        title: path.basename(filePath),
        path: filePath,
        type: "file",
        payload: filePreview,
    };

    state.openTabs.push(tab);
    state.activeTabId = tab.id;
    renderEditor();
}

function openOverviewTab() {
    if (!state.currentFolderPath) {
        return;
    }

    const overviewId = `overview:${state.currentFolderPath}`;
    const existing = state.openTabs.find((tab) => tab.id === overviewId);
    if (!existing) {
        state.openTabs.unshift({
            id: overviewId,
            title: path.basename(state.currentFolderPath) || state.currentFolderPath,
            path: state.currentFolderPath,
            type: "overview",
        });
    }

    state.activeTabId = overviewId;
    renderEditor();
}

function closeTab(tabId) {
    state.openTabs = state.openTabs.filter((tab) => tab.id !== tabId);

    if (state.activeTabId === tabId) {
        state.activeTabId = state.openTabs[0]?.id || null;
    }

    renderEditor();
}

function renderEditor() {
    editorMeta.textContent = `${state.openTabs.length} tab${state.openTabs.length === 1 ? "" : "s"}`;
    renderTabStrip();

    const activeTab = state.openTabs.find((tab) => tab.id === state.activeTabId) || null;
    if (!activeTab) {
        editorContent.innerHTML = `
            <div class="empty-state large-empty">
                在左侧资源管理器中点击文件，即可在这里打开多个文档标签页。
            </div>
        `;
        return;
    }

    if (activeTab.type === "overview") {
        editorContent.innerHTML = renderOverviewDocument();
        return;
    }

    editorContent.innerHTML = renderFileDocument(activeTab);
}

function renderTabStrip() {
    if (state.openTabs.length === 0) {
        tabStrip.className = "tab-strip hidden";
        tabStrip.innerHTML = "";
        return;
    }

    tabStrip.className = "tab-strip";
    tabStrip.innerHTML = "";

    state.openTabs.forEach((tab) => {
        const tabButton = document.createElement("button");
        tabButton.type = "button";
        tabButton.className = "tab-button";
        if (tab.id === state.activeTabId) {
            tabButton.classList.add("active");
        }

        tabButton.addEventListener("click", () => {
            state.activeTabId = tab.id;
            renderEditor();
        });

        const title = document.createElement("span");
        title.className = "tab-title";
        title.textContent = tab.title;
        tabButton.appendChild(title);

        if (tab.type !== "overview") {
            const close = document.createElement("span");
            close.className = "tab-close";
            close.textContent = "×";
            close.addEventListener("click", (event) => {
                event.stopPropagation();
                closeTab(tab.id);
            });
            tabButton.appendChild(close);
        } else {
            const pinned = document.createElement("span");
            pinned.className = "tab-pin";
            pinned.textContent = "•";
            tabButton.appendChild(pinned);
        }

        tabStrip.appendChild(tabButton);
    });
}

function renderOverviewDocument() {
    const summaryMarkup = renderSummaryMarkup(state.currentPlan);
    const categories = Array.isArray(state.currentPlan?.categories) ? state.currentPlan.categories : [];
    const operations = Array.isArray(state.currentPlan?.operations) ? state.currentPlan.operations : [];

    return `
        <div class="document-shell">
            <div class="document-header">
                <div>
                    <p class="document-kicker">Folder Overview</p>
                    <h3>${escapeHtml(path.basename(state.currentFolderPath) || state.currentFolderPath)}</h3>
                </div>
                <div class="document-meta">
                    <span>${state.treeStats.folders} folders</span>
                    <span>${state.treeStats.files} files</span>
                    <span>${formatBytes(state.treeStats.totalSize)}</span>
                </div>
            </div>

            <div class="overview-grid">
                <article class="overview-card">
                    <h4>当前目录</h4>
                    <p class="mono subtle">${escapeHtml(state.currentFolderPath || "")}</p>
                </article>

                <article class="overview-card">
                    <h4>分析状态</h4>
                    <p>${escapeHtml(state.analysisMessage)}</p>
                </article>

                <article class="overview-card full-span">
                    <h4>最近摘要</h4>
                    ${summaryMarkup}
                </article>

                <article class="overview-card">
                    <h4>建议分类</h4>
                    ${
                        categories.length > 0
                            ? `<div class="overview-tags">${categories
                                  .map((item) => `<span class="tag">${escapeHtml(item)}</span>`)
                                  .join("")}</div>`
                            : '<p class="subtle">暂无分类建议。</p>'
                    }
                </article>

                <article class="overview-card">
                    <h4>待执行操作</h4>
                    <p>${getPendingOperations().length} / ${operations.length}</p>
                </article>
            </div>
        </div>
    `;
}

function renderFileDocument(tab) {
    const payload = tab.payload;
    const filePath = escapeHtml(tab.path);

    if (payload.kind === "binary") {
        return `
            <div class="document-shell">
                <div class="document-header">
                    <div>
                        <p class="document-kicker">Binary Preview</p>
                        <h3>${escapeHtml(tab.title)}</h3>
                    </div>
                    <div class="document-meta">
                        <span>${formatBytes(payload.size)}</span>
                        <span>${formatDate(payload.modifiedAt)}</span>
                    </div>
                </div>

                <div class="binary-card">
                    <p>该文件看起来是二进制文件，当前工作区仅提供只读文本预览。</p>
                    <p class="mono subtle">${filePath}</p>
                </div>
            </div>
        `;
    }

    if (payload.kind === "word") {
        return renderWordDocument(tab, payload, filePath);
    }

    if (payload.kind === "spreadsheet") {
        return renderSpreadsheetDocument(tab, payload, filePath);
    }

    const lines = payload.content.split(/\r?\n/);
    const linesMarkup = lines
        .map(
            (line, index) => `
                <div class="code-row">
                    <span class="code-line-no">${index + 1}</span>
                    <span class="code-line-text">${escapeHtml(line) || "&nbsp;"}</span>
                </div>
            `
        )
        .join("");

    return `
        <div class="document-shell">
            <div class="document-header">
                <div>
                    <p class="document-kicker">Document Preview</p>
                    <h3>${escapeHtml(tab.title)}</h3>
                    <p class="document-path mono subtle">${filePath}</p>
                </div>
                <div class="document-meta">
                    <span>${formatBytes(payload.size)}</span>
                    <span>${payload.lineCount} lines</span>
                    <span>${formatDate(payload.modifiedAt)}</span>
                </div>
            </div>

            ${
                payload.truncated
                    ? '<div class="preview-warning">文件较大，当前仅显示前 200 KB 作为只读预览。</div>'
                    : ""
            }

            <div class="code-view">${linesMarkup}</div>
        </div>
    `;
}

function renderWordDocument(tab, payload, filePath) {
    const paragraphs = payload.paragraphs
        .map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`)
        .join("");

    return `
        <div class="document-shell">
            <div class="document-header">
                <div>
                    <p class="document-kicker">Word Preview</p>
                    <h3>${escapeHtml(tab.title)}</h3>
                    <p class="document-path mono subtle">${filePath}</p>
                </div>
                <div class="document-meta">
                    <span>${formatBytes(payload.size)}</span>
                    <span>${payload.paragraphs.length} paragraphs</span>
                    <span>${formatDate(payload.modifiedAt)}</span>
                </div>
            </div>

            ${
                payload.notice
                    ? `<div class="preview-warning">${escapeHtml(payload.notice)}</div>`
                    : ""
            }

            <article class="rich-preview">
                ${paragraphs || "<p>文档内容为空。</p>"}
            </article>
        </div>
    `;
}

function renderSpreadsheetDocument(tab, payload, filePath) {
    const rowsMarkup = payload.rows
        .map((row) => {
            const cells = row
                .map((cell) => `<td>${escapeHtml(cell == null ? "" : String(cell))}</td>`)
                .join("");
            return `<tr>${cells}</tr>`;
        })
        .join("");

    const headerMarkup = payload.headers.length
        ? `<thead><tr>${payload.headers
              .map((header) => `<th>${escapeHtml(header == null ? "" : String(header))}</th>`)
              .join("")}</tr></thead>`
        : "";

    return `
        <div class="document-shell">
            <div class="document-header">
                <div>
                    <p class="document-kicker">Excel Preview</p>
                    <h3>${escapeHtml(tab.title)}</h3>
                    <p class="document-path mono subtle">${filePath}</p>
                </div>
                <div class="document-meta">
                    <span>${formatBytes(payload.size)}</span>
                    <span>${escapeHtml(payload.sheetName || "Sheet1")}</span>
                    <span>${payload.rows.length} rows</span>
                    <span>${formatDate(payload.modifiedAt)}</span>
                </div>
            </div>

            ${
                payload.notice
                    ? `<div class="preview-warning">${escapeHtml(payload.notice)}</div>`
                    : ""
            }

            <div class="sheet-preview-shell">
                <table class="sheet-preview">
                    ${headerMarkup}
                    <tbody>${rowsMarkup || '<tr><td>工作表内容为空。</td></tr>'}</tbody>
                </table>
            </div>
        </div>
    `;
}

async function readFilePreview(filePath) {
    const fileStat = await fs.promises.stat(filePath);
    const extension = path.extname(filePath).toLowerCase();

    if (WORD_EXTENSIONS.has(extension)) {
        return readWordPreview(filePath, fileStat, extension);
    }

    if (EXCEL_EXTENSIONS.has(extension)) {
        return readSpreadsheetPreview(filePath, fileStat);
    }

    const fileHandle = await fs.promises.open(filePath, "r");
    const bytesToRead = Math.min(fileStat.size, PREVIEW_BYTE_LIMIT);
    const buffer = Buffer.alloc(bytesToRead);

    try {
        await fileHandle.read(buffer, 0, bytesToRead, 0);
    } finally {
        await fileHandle.close();
    }

    if (looksBinary(buffer)) {
        return {
            kind: "binary",
            size: fileStat.size,
            modifiedAt: fileStat.mtimeMs,
        };
    }

    const content = buffer.toString("utf8");
    return {
        kind: "text",
        content,
        size: fileStat.size,
        modifiedAt: fileStat.mtimeMs,
        truncated: fileStat.size > PREVIEW_BYTE_LIMIT,
        lineCount: content.split(/\r?\n/).length,
    };
}

async function readWordPreview(filePath, fileStat, extension) {
    if (extension === ".doc") {
        return {
            kind: "word",
            paragraphs: [
                "当前版本支持直接预览 .docx 文件。",
                "旧版 .doc 文件缺少稳定的无依赖解析能力，因此这里先提供文件信息与兼容性提示。",
            ],
            notice: "建议将 .doc 转为 .docx 后获得更完整的正文预览。",
            size: fileStat.size,
            modifiedAt: fileStat.mtimeMs,
        };
    }

    const result = await mammoth.extractRawText({ path: filePath });
    const paragraphs = result.value
        .split(/\r?\n+/)
        .map((line) => line.trim())
        .filter(Boolean)
        .slice(0, 80);

    return {
        kind: "word",
        paragraphs,
        notice: result.messages.length
            ? "文档已解析，部分复杂格式可能在预览中被简化。"
            : "",
        size: fileStat.size,
        modifiedAt: fileStat.mtimeMs,
    };
}

async function readSpreadsheetPreview(filePath, fileStat) {
    const workbook = XLSX.readFile(filePath, {
        cellDates: true,
        cellNF: false,
        cellStyles: false,
    });

    const firstSheetName = workbook.SheetNames[0];
    const sheet = workbook.Sheets[firstSheetName];
    const matrix = XLSX.utils.sheet_to_json(sheet, {
        header: 1,
        defval: "",
        blankrows: false,
        raw: false,
    });

    const limitedRows = matrix.slice(0, 41);
    const headers = limitedRows[0] || [];
    const rows = limitedRows.slice(1);
    const totalRows = Math.max(matrix.length - 1, 0);

    return {
        kind: "spreadsheet",
        headers,
        rows,
        sheetName: firstSheetName,
        notice: totalRows > rows.length ? `当前仅预览前 ${rows.length} 行数据。` : "",
        size: fileStat.size,
        modifiedAt: fileStat.mtimeMs,
    };
}

function renderAnalysis() {
    analysisStatus.className = `status-card status-${state.analysisTone}`;
    analysisStatus.textContent = state.analysisMessage;

    if (!state.currentFolderPath) {
        analysisMeta.textContent = "等待分析";
    } else if (state.isAnalyzing) {
        analysisMeta.textContent = "分析中";
    } else if (state.isExecutingOperation) {
        analysisMeta.textContent = "执行中";
    } else {
        const modeLabel = state.analysisMode === WECHAT_CLEANUP_MODE ? "微信清理" : "标准整理";
        analysisMeta.textContent = `${modeLabel} · ${getPendingOperations().length} pending · ${state.treeStats.files} files`;
    }

    if (state.currentPlan) {
        planSummary.className = "plan-summary";
        planSummary.innerHTML = renderSummaryMarkup(state.currentPlan);
    } else {
        planSummary.className = "plan-summary empty-inline";
        planSummary.textContent = "暂无分析输出。";
    }

    const categories = Array.isArray(state.currentPlan?.categories) ? state.currentPlan.categories : [];
    if (categories.length > 0) {
        categoriesList.className = "categories-list";
        categoriesList.innerHTML = categories
            .map((category) => `<span class="category-chip">${escapeHtml(category)}</span>`)
            .join("");
    } else {
        categoriesList.className = "categories-list empty-inline";
        categoriesList.textContent = "暂无分类建议。";
    }

    const operations = Array.isArray(state.currentPlan?.operations) ? state.currentPlan.operations : [];
    operationsMeta.textContent = `${getPendingOperations().length}/${operations.length} 待执行`;

    if (operations.length > 0) {
        operationsList.className = "operations-list";
        operationsList.innerHTML = operations
            .map((operation, index) => renderOperationItem(operation, index))
            .join("");

        operationsList.querySelectorAll(".operation-confirm-btn").forEach((button) => {
            button.addEventListener("click", async () => {
                const index = Number(button.dataset.operationIndex);
                if (!Number.isInteger(index)) {
                    return;
                }
                await executeSingleOperation(index);
            });
        });
    } else {
        operationsList.className = "operations-list empty-inline";
        operationsList.textContent = "还没有可执行的整理操作。";
    }

    if (state.lastResult) {
        resultDisplay.className = `result-display result-${state.lastResult.type}`;
        resultDisplay.innerHTML = `
            <p>${escapeHtml(state.lastResult.message)}</p>
            <p class="result-timestamp">${formatDate(state.lastResult.at)}</p>
        `;
    } else {
        resultDisplay.className = "result-display empty-inline";
        resultDisplay.textContent = "尚未执行任何文件操作。";
    }

    renderCloudSyncPanel();
}

function getJobScheduleLabel(job) {
    const dailyTime = String(job?.daily_time || "").trim();
    if (dailyTime) {
        return `每日 ${dailyTime}`;
    }

    const cronExpression = String(job?.cron || "").trim();
    return cronExpression ? `Cron ${cronExpression}` : "未配置时间";
}

function getJobDisplayName(job) {
    const folderName = path.basename(String(job?.folder_path || "").trim()) || "未命名任务";
    return `${folderName} · ${getJobScheduleLabel(job)}`;
}

function renderTopbarCloudSummary(status, jobs) {
    const gateway = status?.gateway || {};
    const gatewayOk = Boolean(gateway.ok);

    if (state.isCloudSyncLoading && !status) {
        gatewayStatusPill.className = "sync-status-pill neutral";
        gatewayStatusPill.textContent = "Gateway 检查中";
        gatewayStatusText.textContent = "正在连接 OpenClaw Gateway 并加载定时任务...";
    } else if (!status && state.cloudSyncFeedback?.type === "error") {
        gatewayStatusPill.className = "sync-status-pill error";
        gatewayStatusPill.textContent = "Gateway 状态异常";
        gatewayStatusText.textContent = state.cloudSyncFeedback.message;
    } else if (status) {
        gatewayStatusPill.className = `sync-status-pill ${gatewayOk ? "ok" : "error"}`;
        gatewayStatusPill.textContent = gatewayOk ? "Gateway 已连接" : "Gateway 不可用";
        gatewayStatusText.textContent =
            String(gateway.detail || "").trim() ||
            (gatewayOk ? "OpenClaw Gateway 连接正常。" : "尚未连接到 OpenClaw Gateway。");
    } else {
        gatewayStatusPill.className = "sync-status-pill neutral";
        gatewayStatusPill.textContent = "Gateway 未检查";
        gatewayStatusText.textContent = "尚未检查 OpenClaw Gateway。";
    }

    if (jobs.length > 0) {
        topbarJobsChips.innerHTML = jobs
            .slice(0, 4)
            .map(
                (job) => `
                    <span class="topbar-job-chip ${job.enabled ? "ok" : "warning"}" title="${escapeHtml(
                        `${job.name || "未命名任务"} ｜ ${job.folder_path || "-"} ｜ ${job.remote_path || "-"}`
                    )}">
                        ${escapeHtml(getJobDisplayName(job))}
                    </span>
                `
            )
            .join("");

        if (jobs.length > 4) {
            topbarJobsChips.innerHTML += `<span class="topbar-job-chip subtle-chip">+${jobs.length - 4}</span>`;
        }
    } else {
        topbarJobsChips.innerHTML = '<span class="topbar-job-chip subtle-chip">暂无任务</span>';
    }
}

function renderCloudSyncPanel() {
    const hasFolder = Boolean(state.currentFolderPath);
    const status = state.cloudSyncStatus;
    const jobs = Array.isArray(status?.jobs) ? status.jobs : [];
    const bdpanStatus = status?.bdpan || {};
    const cronStatus = status?.cron || {};
    const hasConfirmedStatus = Boolean(status);

    bdpanRemotePathInput.value = state.bdpanRemotePath;
    bdpanDailyTimeInput.value = state.bdpanDailyTime || DEFAULT_BDPAN_DAILY_TIME;
    bdpanTimezoneInput.value = state.bdpanTimezone;

    renderTopbarCloudSummary(status, jobs);

    if (state.isCloudSyncLoading) {
        bdpanMeta.textContent = "检查中";
    } else if (state.isCloudSyncBusy) {
        bdpanMeta.textContent = "执行中";
    } else if (!hasConfirmedStatus) {
        bdpanMeta.textContent = "未检查";
    } else {
        bdpanMeta.textContent = `${jobs.length} 个任务`;
    }

    const statusLines = [];

    if (!hasConfirmedStatus) {
        statusLines.push(
            `<div class="sync-status-line sync-status-note"><span>${
                state.isCloudSyncLoading
                    ? "正在刷新百度网盘登录状态和定时任务信息..."
                    : "等待完成一次状态刷新后，这里会显示百度网盘登录状态和定时任务摘要。"
            }</span></div>`
        );
    } else {
        if (bdpanStatus.installed) {
            const authText = bdpanStatus.authenticated
                ? `百度网盘已登录：${bdpanStatus.username || "当前账户"}`
                : "百度网盘未登录或登录已失效";
            const authDetail = bdpanStatus.authenticated
                ? bdpanStatus.token_expires_in || bdpanStatus.expires_at || ""
                : bdpanStatus.detail || "";

            statusLines.push(
                `<div class="sync-status-line"><span class="sync-status-pill ${
                    bdpanStatus.authenticated ? "ok" : "warning"
                }">${escapeHtml(authText)}</span><span>${escapeHtml(authDetail)}</span></div>`
            );
        } else {
            statusLines.push(
                `<div class="sync-status-line"><span class="sync-status-pill error">bdpan 未安装</span><span>${escapeHtml(
                    bdpanStatus.detail || "未找到 bdpan CLI。"
                )}</span></div>`
            );
        }

        statusLines.push(
            `<div class="sync-status-line"><span class="sync-status-pill ${
                cronStatus.enabled ? "ok" : "warning"
            }">${cronStatus.enabled ? "定时调度已启用" : "定时调度未启用"}</span><span>${escapeHtml(
                cronStatus.detail || "尚未检查 OpenClaw cron。"
            )}</span></div>`
        );
    }

    if (!hasFolder) {
        statusLines.push(
            '<div class="sync-status-line sync-status-note"><span>选择文件夹后即可设置上传目标、每日同步时间，并创建新的同步任务。</span></div>'
        );
    }

    if (state.cloudSyncFeedback) {
        statusLines.push(
            `<div class="sync-feedback sync-feedback-${escapeHtml(state.cloudSyncFeedback.type)}"><p>${escapeHtml(
                state.cloudSyncFeedback.message
            )}</p><p class="result-timestamp">${formatDate(state.cloudSyncFeedback.at)}</p></div>`
        );
    }

    bdpanStatusCard.className = "cloud-sync-status";
    bdpanStatusCard.innerHTML = statusLines.join("");

    if (jobs.length > 0) {
        bdpanJobsList.className = "bdpan-jobs";
        bdpanJobsList.innerHTML = jobs
            .map(
                (job) => `
                    <article class="sync-job-item">
                        <div class="sync-job-topline">
                            <strong>${escapeHtml(job.name || "未命名任务")}</strong>
                            <div class="sync-job-actions">
                                <span class="sync-job-pill ${job.enabled ? "ok" : "warning"}">${
                                    job.enabled ? "已启用" : "已停用"
                                }</span>
                                <button
                                    type="button"
                                    class="ghost-btn sync-job-remove-btn"
                                    data-job-id="${escapeHtml(job.id || "")}"
                                    data-job-name="${escapeHtml(job.name || "未命名任务")}"
                                    ${state.isCloudSyncBusy ? "disabled" : ""}
                                >
                                    取消任务
                                </button>
                            </div>
                        </div>
                        <div class="sync-job-meta">
                            <span><strong>同步时间:</strong> ${escapeHtml(getJobScheduleLabel(job))}</span>
                            <span><strong>时区:</strong> ${escapeHtml(job.timezone || "-")}</span>
                        </div>
                        <div class="sync-job-meta">
                            <span><strong>本地目录:</strong> ${escapeHtml(job.folder_path || "-")}</span>
                        </div>
                        <div class="sync-job-meta">
                            <span><strong>网盘路径:</strong> <code>${escapeHtml(job.remote_path || "-")}</code></span>
                        </div>
                        ${
                            job.next_run_at
                                ? `<div class="sync-job-next">下次执行：${escapeHtml(job.next_run_at)}</div>`
                                : ""
                        }
                    </article>
                `
            )
            .join("");

        bdpanJobsList.querySelectorAll(".sync-job-remove-btn").forEach((button) => {
            button.addEventListener("click", async () => {
                const jobId = String(button.dataset.jobId || "").trim();
                const jobName = String(button.dataset.jobName || "").trim();
                await removeBdpanSchedule(jobId, jobName);
            });
        });
    } else {
        bdpanJobsList.className = "bdpan-jobs empty-inline";
        bdpanJobsList.textContent = "暂无由当前应用创建的百度网盘同步任务。";
    }
}

function getOperationMeta(operation) {
    switch (operation?.type) {
        case "move":
            return { label: "移动", tone: "move", sourceLabel: "源", targetLabel: "目标" };
        case "rename":
            return { label: "重命名文件", tone: "rename", sourceLabel: "源", targetLabel: "目标" };
        case "rename_folder":
            return { label: "重命名文件夹", tone: "rename-folder", sourceLabel: "目录", targetLabel: "新目录" };
        case "create_folder":
            return { label: "创建文件夹", tone: "create-folder", sourceLabel: "", targetLabel: "目录" };
        case "delete":
            return { label: "删除", tone: "delete", sourceLabel: "路径", targetLabel: "" };
        default:
            return { label: "整理", tone: "rename", sourceLabel: "源", targetLabel: "目标" };
    }
}

function renderOperationItem(operation, index) {
    const operationMeta = getOperationMeta(operation);
    const isCompleted = isOperationCompleted(index);
    const isDiscarded = isOperationDiscarded(index);
    const sourceMarkup = operation.source
        ? `<div><span>${operationMeta.sourceLabel}</span><code>${escapeHtml(operation.source || "")}</code></div>`
        : "";
    const targetMarkup = operation.target
        ? `<div><span>${operationMeta.targetLabel}</span><code>${escapeHtml(operation.target || "")}</code></div>`
        : "";
    const itemStateClass = isCompleted ? "is-completed" : isDiscarded ? "is-discarded" : "";
    const actionMarkup = isCompleted
        ? '<span class="operation-status-badge">已执行</span>'
        : isDiscarded
        ? '<span class="operation-status-badge is-discarded">已丢弃</span>'
        : `<button type="button" class="operation-confirm-btn" data-operation-index="${index}" ${
              state.isExecutingOperation ? "disabled" : ""
          }>确认这条</button>`;

    return `
        <article class="operation-item ${itemStateClass}">
            <div class="operation-topline">
                <div class="operation-heading">
                    <span class="operation-type ${operationMeta.tone}">${operationMeta.label}</span>
                    ${actionMarkup}
                </div>
                <span class="operation-reason">${escapeHtml(operation.reason || "无说明")}</span>
            </div>
            <div class="operation-paths">
                ${sourceMarkup}
                ${targetMarkup}
            </div>
        </article>
    `;
}

function renderSummaryMarkup(plan) {
    const summaryPoints = getSummaryPoints(plan);
    if (summaryPoints.length === 0) {
        return '<p class="empty-inline">暂无分析摘要。</p>';
    }

    return `
        <ul class="summary-list">
            ${summaryPoints
                .map((point) => `<li class="summary-item">${escapeHtml(point)}</li>`)
                .join("")}
        </ul>
    `;
}

function getSummaryPoints(plan) {
    if (!plan) {
        return [];
    }

    if (Array.isArray(plan.summary_points)) {
        const normalized = plan.summary_points
            .map((item) => String(item || "").trim())
            .filter(Boolean);
        if (normalized.length > 0) {
            return normalized;
        }
    }

    const summaryText = String(plan.summary || "").trim();
    if (!summaryText) {
        return [];
    }

    const byLines = summaryText
        .split(/\r?\n+/)
        .map((line) => line.replace(/^[-*•\d.\s]+/, "").trim())
        .filter(Boolean);
    if (byLines.length > 1) {
        return byLines;
    }

    return summaryText
        .split(/[；;。]/)
        .map((part) => part.trim())
        .filter(Boolean);
}

function setAnalysisStatus(tone, message) {
    state.analysisTone = tone;
    state.analysisMessage = message;
}

function isOperationCompleted(index) {
    return state.completedOperationIndexes.has(index);
}

function isOperationDiscarded(index) {
    return state.discardedOperationIndexes.has(index);
}

function isOperationHandled(index) {
    return isOperationCompleted(index) || isOperationDiscarded(index);
}

function resetOperationProgress() {
    state.completedOperationIndexes = new Set();
    state.discardedOperationIndexes = new Set();
}

function rewriteOperationPathWithRenameFolder(rawPath, renameOperation) {
    const pathValue = String(rawPath || "");
    if (!pathValue) {
        return pathValue;
    }

    const sourcePrefix = String(renameOperation?.source || "");
    const targetPrefix = String(renameOperation?.target || "");
    if (!sourcePrefix || !targetPrefix) {
        return pathValue;
    }

    if (pathValue === sourcePrefix) {
        return targetPrefix;
    }

    if (pathValue.startsWith(`${sourcePrefix}/`)) {
        return `${targetPrefix}${pathValue.slice(sourcePrefix.length)}`;
    }

    return pathValue;
}

function updatePendingOperationsAfterExecution(executedOperations) {
    if (!Array.isArray(state.currentPlan?.operations) || executedOperations.length === 0) {
        return;
    }

    const renameFolderOperations = executedOperations.filter(
        (operation) => operation?.type === "rename_folder"
    );
    if (renameFolderOperations.length === 0) {
        return;
    }

    state.currentPlan.operations = state.currentPlan.operations.map((operation) => {
        const updatedOperation = { ...operation };

        renameFolderOperations.forEach((renameOperation) => {
            updatedOperation.source = rewriteOperationPathWithRenameFolder(
                updatedOperation.source,
                renameOperation
            );
            updatedOperation.target = rewriteOperationPathWithRenameFolder(
                updatedOperation.target,
                renameOperation
            );
        });

        return updatedOperation;
    });
}

function updateActionState() {
    const hasFolder = Boolean(state.currentFolderPath);
    const operationCount = getPendingOperations().length;
    const isBusy = state.isAnalyzing || state.isExecutingOperation || state.isCloudSyncBusy;
    const hasRemotePath = Boolean(String(state.bdpanRemotePath || "").trim());
    const hasDailyTime = Boolean(String(state.bdpanDailyTime || "").trim());
    const hasTimezone = Boolean(String(state.bdpanTimezone || "").trim());

    wechatCleanupBtn.disabled = isBusy;
    analyzeBtn.disabled = !hasFolder || isBusy;
    newAnalysisBtn.disabled = !hasFolder || isBusy;
    confirmBtn.disabled = isBusy || operationCount === 0;
    rollbackBtn.disabled = isBusy || !state.canRollback;
    cancelBtn.disabled = isBusy || (!state.currentPlan && !state.lastResult);
    bdpanUploadBtn.disabled = !hasFolder || isBusy || !hasRemotePath;
    bdpanRefreshBtn.disabled = state.isCloudSyncBusy || state.isCloudSyncLoading;
    bdpanScheduleBtn.disabled = !hasFolder || isBusy || !hasRemotePath || !hasDailyTime || !hasTimezone;
    wechatCleanupRunBtn.disabled = isBusy;
}

/**
 * 上传当前文件夹到百度网盘
 */
async function uploadCurrentFolderToBdpan() {
    if (!state.currentFolderPath || state.isAnalyzing || state.isExecutingOperation || state.isCloudSyncBusy) {
        return;
    }

    const remotePath = String(state.bdpanRemotePath || "").trim();
    if (!remotePath) {
        state.cloudSyncFeedback = {
            type: "error",
            message: "请先填写百度网盘目标路径。",
            at: Date.now(),
        };
        renderCloudSyncPanel();
        updateActionState();
        return;
    }

    const confirmed = window.confirm(
        `确定要把当前文件夹上传到百度网盘吗？\n\n本地目录：${state.currentFolderPath}\n网盘路径：${remotePath}\n\n说明：立即上传会直接调用本机 bdpan CLI，以避免大文件夹通过聊天链路中途停住。`
    );
    if (!confirmed) {
        return;
    }

    state.isCloudSyncBusy = true;
    state.cloudSyncFeedback = {
        type: "loading",
        message: "正在通过本机 bdpan CLI 上传当前文件夹到百度网盘...",
        at: Date.now(),
    };
    renderCloudSyncPanel();
    updateActionState();

    try {
        const response = await axios.post(`${API_BASE}/cloud/upload`, {
            folder_path: state.currentFolderPath,
            remote_path: remotePath,
        });

        state.cloudSyncFeedback = {
            type: response.data.success ? "success" : "error",
            message: buildCloudSyncMessage(response.data),
            at: Date.now(),
        };
    } catch (error) {
        const errorMessage = error.response?.data?.error || error.message;
        state.cloudSyncFeedback = {
            type: "error",
            message: `百度网盘上传失败：${errorMessage}`,
            at: Date.now(),
        };
    } finally {
        state.isCloudSyncBusy = false;
        await loadCloudSyncStatus();
        renderCloudSyncPanel();
        updateActionState();
    }
}

/**
 * 创建百度网盘定时同步任务
 */
async function createBdpanSchedule() {
    if (!state.currentFolderPath || state.isAnalyzing || state.isExecutingOperation || state.isCloudSyncBusy) {
        return;
    }

    const remotePath = String(state.bdpanRemotePath || "").trim();
    const dailyTime = String(state.bdpanDailyTime || "").trim();
    const timezone = String(state.bdpanTimezone || "").trim();

    if (!remotePath || !dailyTime || !timezone) {
        state.cloudSyncFeedback = {
            type: "error",
            message: "请先填写完整的网盘路径、每日同步时间和时区。",
            at: Date.now(),
        };
        renderCloudSyncPanel();
        updateActionState();
        return;
    }

    const confirmed = window.confirm(
        `确定要创建一个每日自动同步到百度网盘的任务吗？\n\n本地目录：${state.currentFolderPath}\n网盘路径：${remotePath}\n每日时间：${dailyTime}\n时区：${timezone}`
    );
    if (!confirmed) {
        return;
    }

    state.isCloudSyncBusy = true;
    state.cloudSyncFeedback = {
        type: "loading",
        message: "正在创建 OpenClaw 每日同步任务...",
        at: Date.now(),
    };
    renderCloudSyncPanel();
    updateActionState();

    try {
        const response = await axios.post(`${API_BASE}/cloud/schedule`, {
            folder_path: state.currentFolderPath,
            remote_path: remotePath,
            daily_time: dailyTime,
            timezone,
        });

        state.cloudSyncFeedback = {
            type: response.data.success ? "success" : "error",
            message: buildCloudSyncMessage(response.data),
            at: Date.now(),
        };

        if (response.data.timezone) {
            state.bdpanTimezone = response.data.timezone;
            bdpanTimezoneInput.value = state.bdpanTimezone;
        }
    } catch (error) {
        const errorMessage = error.response?.data?.error || error.message;
        state.cloudSyncFeedback = {
            type: "error",
            message: `创建定时同步失败：${errorMessage}`,
            at: Date.now(),
        };
    } finally {
        state.isCloudSyncBusy = false;
        await loadCloudSyncStatus();
        renderCloudSyncPanel();
        updateActionState();
    }
}

/**
 * 取消百度网盘定时同步任务
 * @param {string} jobId - 任务ID
 * @param {string} jobName - 任务名称
 */
async function removeBdpanSchedule(jobId, jobName) {
    if (!jobId || state.isCloudSyncBusy) {
        return;
    }

    const confirmed = window.confirm(`确定要取消这个定时任务吗？\n\n任务：${jobName || jobId}`);
    if (!confirmed) {
        return;
    }

    state.isCloudSyncBusy = true;
    state.cloudSyncFeedback = {
        type: "loading",
        message: `正在取消定时任务：${jobName || jobId}`,
        at: Date.now(),
    };
    renderCloudSyncPanel();
    updateActionState();

    try {
        const response = await axios.post(`${API_BASE}/cloud/schedule/remove`, {
            job_id: jobId,
        });

        state.cloudSyncFeedback = {
            type: response.data.success ? "success" : "error",
            message: buildCloudSyncMessage(response.data),
            at: Date.now(),
        };
    } catch (error) {
        const errorMessage = error.response?.data?.error || error.message;
        state.cloudSyncFeedback = {
            type: "error",
            message: `取消定时任务失败：${errorMessage}`,
            at: Date.now(),
        };
    } finally {
        state.isCloudSyncBusy = false;
        await loadCloudSyncStatus();
        renderCloudSyncPanel();
        updateActionState();
    }
}

/**
 * 构建云同步消息
 * @param {Object} payload - 消息内容
 * @returns {string} 构建后的消息
 */
function buildCloudSyncMessage(payload) {
    const summary = String(payload?.summary || payload?.error || "").trim();
    const remotePath = String(payload?.remote_path || "").trim();
    const dailyTime = String(payload?.daily_time || payload?.job?.daily_time || "").trim();
    const details = Array.isArray(payload?.details) ? payload.details.filter(Boolean) : [];
    const nextStep = String(payload?.next_step || "").trim();

    const parts = [];
    if (summary) {
        parts.push(summary);
    }
    if (remotePath) {
        parts.push(`目标路径：${remotePath}`);
    }
    if (dailyTime) {
        parts.push(`每日时间：${dailyTime}`);
    }
    if (details.length > 0) {
        parts.push(`细节：${details.join("；")}`);
    }
    if (nextStep) {
        parts.push(`下一步：${nextStep}`);
    }

    return parts.join(" ");
}

/**
 * 执行单个操作
 * @param {number} index - 操作索引
 */
async function executeSingleOperation(index) {
    if (state.isExecutingOperation || state.isAnalyzing || isOperationHandled(index)) {
        return;
    }

    const operation = state.currentPlan?.operations?.[index];
    if (!operation) {
        return;
    }

    const confirmed = window.confirm("确定要执行这条整理建议吗？");
    if (!confirmed) {
        return;
    }

    await executeOperations([index], "正在执行当前确认的操作...");
}

/**
 * 执行多个操作
 * @param {Array<number>} indexes - 操作索引数组
 * @param {string} loadingMessage - 加载消息
 * @param {Object} options - 选项
 */
async function executeOperations(indexes, loadingMessage, options = {}) {
    const isWechatCleanup = state.analysisMode === WECHAT_CLEANUP_MODE;
    const operations = indexes
        .map((index) => {
            const operation = state.currentPlan?.operations?.[index];
            if (!operation) {
                return null;
            }

            return {
                index,
                operation: {
                    ...operation,
                    client_index: index,
                },
            };
        })
        .filter(Boolean);

    if (operations.length === 0) {
        return;
    }

    state.isExecutingOperation = true;
    setAnalysisStatus("loading", loadingMessage);
    renderAnalysis();
    updateActionState();

    try {
        const response = await axios.post(`${API_BASE}/execute`, {
            folder_path: state.currentFolderPath,
            operations: operations.map(({ operation }) => operation),
            write_readme: Boolean(options.writeReadme),
            mode: state.analysisMode,
            target_root_path: state.analysisTargetRootPath,
        });

        if (response.data.success) {
            const resultItems = Array.isArray(response.data.results) ? response.data.results : [];
            const succeededIndexes = new Set(
                resultItems
                    .filter((item) => item?.success)
                    .map((item) => item?.operation?.client_index)
                    .filter((value) => Number.isInteger(value))
            );
            const discardedResults = resultItems.filter((item) => !item?.success);
            const discardedIndexes = new Set(
                discardedResults
                    .map((item) => item?.operation?.client_index)
                    .filter((value) => Number.isInteger(value))
            );
            const successfulOperations = operations
                .filter(({ index }) => succeededIndexes.has(index))
                .map(({ operation }) => operation);

            updatePendingOperationsAfterExecution(successfulOperations);
            succeededIndexes.forEach((index) => state.completedOperationIndexes.add(index));
            discardedIndexes.forEach((index) => state.discardedOperationIndexes.add(index));

            const remainingCount = getPendingOperations().length;
            const readmeGenerated = Boolean(response.data.readme_generated);
            const readmeError = response.data.readme_error ? String(response.data.readme_error) : "";
            const successCount = successfulOperations.length;
            const discardedCount = discardedResults.length;

            if (successCount > 0) {
                state.canRollback = true;
                await loadFolderTree(state.currentFolderPath, true);
                openOverviewTab();
            }

            if (discardedCount === 0) {
                const baseMessage = isWechatCleanup
                    ? `已完成 ${successCount} 条微信文件整理操作，文件已开始归档到目标目录。`
                    : options.writeReadme
                    ? `已完成 ${successCount} 条操作，当前整理结果已落盘。`
                    : `已执行 ${successCount} 条操作，剩余 ${remainingCount} 条待确认。`;
                const readmeMessage = readmeGenerated
                    ? " 已在打开文件夹的根目录写入 README.md。"
                    : readmeError
                    ? ` README.md 写入失败：${readmeError}`
                    : "";

                state.lastResult = {
                    type: readmeError ? "error" : "success",
                    message: `${baseMessage}${readmeMessage}`.trim(),
                    at: Date.now(),
                };
                setAnalysisStatus(
                    readmeError ? "error" : "success",
                    isWechatCleanup
                        ? "微信文件清理操作已执行，源目录与目标目录已同步更新。"
                        : readmeGenerated
                        ? "全部操作已执行，README 已写入根目录。"
                        : readmeError
                        ? `操作已执行，但 README 写入失败：${readmeError}`
                        : "操作已执行，目录树已同步刷新。"
                );
            } else {
                const discardedSummary = discardedResults
                    .slice(0, 2)
                    .map((item) => item.error)
                    .filter(Boolean)
                    .join("；");
                const readmeMessage = readmeGenerated
                    ? " 已在打开文件夹的根目录写入 README.md。"
                    : readmeError
                    ? ` README.md 写入失败：${readmeError}`
                    : "";

                state.lastResult = {
                    type: readmeError ? "error" : "warning",
                    message:
                        `${
                            isWechatCleanup
                                ? `本轮成功执行 ${successCount} 条微信文件整理操作，已丢弃 ${discardedCount} 条无法执行的建议。`
                                : `本轮成功执行 ${successCount} 条，已丢弃 ${discardedCount} 条无法执行的建议。`
                        }` +
                        (remainingCount > 0 ? ` 剩余 ${remainingCount} 条待确认。` : "") +
                        (discardedSummary ? ` 丢弃原因：${discardedSummary}` : "") +
                        readmeMessage,
                    at: Date.now(),
                };
                setAnalysisStatus(
                    readmeError ? "error" : "warning",
                    isWechatCleanup
                        ? remainingCount > 0
                            ? `已自动丢弃 ${discardedCount} 条无法执行的微信清理建议，剩余 ${remainingCount} 条待确认。`
                            : `已自动丢弃 ${discardedCount} 条无法执行的微信清理建议。`
                        : remainingCount > 0
                        ? readmeGenerated
                            ? `已自动丢弃 ${discardedCount} 条无法执行的建议，剩余 ${remainingCount} 条待确认，README 已写入根目录。`
                            : `已自动丢弃 ${discardedCount} 条无法执行的建议，剩余 ${remainingCount} 条待确认。`
                        : readmeGenerated
                        ? `已自动丢弃 ${discardedCount} 条无法执行的建议，README 已写入根目录。`
                        : `已自动丢弃 ${discardedCount} 条无法执行的建议。`
                );
            }
        } else {
            state.lastResult = {
                type: "error",
                message: `执行失败：${response.data.error}`,
                at: Date.now(),
            };
            setAnalysisStatus("error", `执行失败：${response.data.error}`);
        }
    } catch (error) {
        state.lastResult = {
            type: "error",
            message: `执行出错：${error.message}`,
            at: Date.now(),
        };
        setAnalysisStatus("error", `执行出错：${error.message}`);
    } finally {
        state.isExecutingOperation = false;
        renderAnalysis();
        updateActionState();
    }
}

/**
 * 获取待执行的操作
 * @returns {Array} 待执行操作数组
 */
function getPendingOperations() {
    const operations = Array.isArray(state.currentPlan?.operations) ? state.currentPlan.operations : [];
    return operations
        .map((operation, index) => ({ operation, index }))
        .filter(({ index }) => !isOperationHandled(index));
}

/**
 * 清理不存在的标签页
 */
async function pruneMissingTabs() {
    const remainingTabs = [];

    for (const tab of state.openTabs) {
        if (tab.type === "overview") {
            remainingTabs.push(tab);
            continue;
        }

        if (fs.existsSync(tab.path)) {
            if (tab.type === "file") {
                tab.payload = await readFilePreview(tab.path);
            }
            remainingTabs.push(tab);
        }
    }

    state.openTabs = remainingTabs;
    if (!state.openTabs.some((tab) => tab.id === state.activeTabId)) {
        state.activeTabId = state.openTabs[0]?.id || null;
    }
}

/**
 * 判断是否为二进制文件
 * @param {Buffer} buffer - 文件缓冲区
 * @returns {boolean} 是否为二进制文件
 */
function looksBinary(buffer) {
    if (buffer.length === 0) {
        return false;
    }

    let suspicious = 0;
    for (const value of buffer) {
        if (value === 0) {
            return true;
        }
        if (value < 7 || (value > 14 && value < 32)) {
            suspicious += 1;
        }
    }

    return suspicious / buffer.length > 0.1;
}

/**
 * 获取文件图标元数据
 * @param {string} fileName - 文件名
 * @param {string} extension - 文件扩展名
 * @returns {Object} 图标元数据
 */
function fileIconMeta(fileName, extension) {
    const normalizedName = String(fileName || "").toLowerCase();
    const iconMap = {
        ".js": { label: "JS", tone: "script" },
        ".jsx": { label: "JS", tone: "script" },
        ".ts": { label: "TS", tone: "script" },
        ".tsx": { label: "TS", tone: "script" },
        ".py": { label: "PY", tone: "script" },
        ".html": { label: "</>", tone: "code" },
        ".css": { label: "CSS", tone: "code" },
        ".scss": { label: "CSS", tone: "code" },
        ".less": { label: "CSS", tone: "code" },
        ".json": { label: "{}", tone: "data" },
        ".xml": { label: "XML", tone: "data" },
        ".sql": { label: "SQL", tone: "data" },
        ".db": { label: "DB", tone: "data" },
        ".sqlite": { label: "DB", tone: "data" },
        ".md": { label: "MD", tone: "doc" },
        ".txt": { label: "TXT", tone: "doc" },
        ".doc": { label: "DOC", tone: "doc" },
        ".docx": { label: "DOC", tone: "doc" },
        ".pdf": { label: "PDF", tone: "doc" },
        ".xls": { label: "XLS", tone: "sheet" },
        ".xlsx": { label: "XLS", tone: "sheet" },
        ".csv": { label: "CSV", tone: "sheet" },
        ".ppt": { label: "PPT", tone: "slides" },
        ".pptx": { label: "PPT", tone: "slides" },
        ".png": { label: "IMG", tone: "media" },
        ".jpg": { label: "IMG", tone: "media" },
        ".jpeg": { label: "IMG", tone: "media" },
        ".gif": { label: "IMG", tone: "media" },
        ".svg": { label: "SVG", tone: "media" },
        ".webp": { label: "IMG", tone: "media" },
        ".mp3": { label: "AUD", tone: "media" },
        ".wav": { label: "AUD", tone: "media" },
        ".flac": { label: "AUD", tone: "media" },
        ".mp4": { label: "VID", tone: "media" },
        ".mov": { label: "VID", tone: "media" },
        ".avi": { label: "VID", tone: "media" },
        ".zip": { label: "ZIP", tone: "archive" },
        ".rar": { label: "ZIP", tone: "archive" },
        ".7z": { label: "ZIP", tone: "archive" },
        ".tar": { label: "ZIP", tone: "archive" },
        ".gz": { label: "ZIP", tone: "archive" },
        ".env": { label: "ENV", tone: "config" },
        ".yml": { label: "CFG", tone: "config" },
        ".yaml": { label: "CFG", tone: "config" },
        ".ini": { label: "CFG", tone: "config" },
        ".toml": { label: "CFG", tone: "config" },
    };

    if (normalizedName === "readme.md") {
        return { label: "DOC", tone: "doc" };
    }

    return iconMap[extension] || { label: "FILE", tone: "generic" };
}

/**
 * 格式化字节大小
 * @param {number} value - 字节大小
 * @returns {string} 格式化后的字符串
 */
function formatBytes(value) {
    if (!Number.isFinite(value) || value <= 0) {
        return "0 B";
    }

    const units = ["B", "KB", "MB", "GB"];
    let size = value;
    let unitIndex = 0;

    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex += 1;
    }

    return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

/**
 * 格式化日期时间
 * @param {number} timestamp - 时间戳
 * @returns {string} 格式化后的日期时间字符串
 */
function formatDate(timestamp) {
    if (!timestamp) {
        return "未知时间";
    }

    return new Date(timestamp).toLocaleString("zh-CN", {
        hour12: false,
    });
}

/**
 * 转义HTML特殊字符
 * @param {string} value - 要转义的字符串
 * @returns {string} 转义后的字符串
 */
function escapeHtml(value) {
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

/**
 * 初始化主题
 */
function initializeTheme() {
    const storedTheme = localStorage.getItem(THEME_STORAGE_KEY);
    applyTheme(storedTheme && THEMES.has(storedTheme) ? storedTheme : DEFAULT_THEME);
}

/**
 * 应用主题
 * @param {string} themeName - 主题名称
 */
function applyTheme(themeName) {
    const normalizedTheme = THEMES.has(themeName) ? themeName : DEFAULT_THEME;
    const theme = getThemeDefinition(normalizedTheme);
    state.currentTheme = normalizedTheme;
    document.body.dataset.theme = normalizedTheme;
    themeSelect.value = normalizedTheme;
    localStorage.setItem(THEME_STORAGE_KEY, normalizedTheme);
}

/**
 * 渲染主题选项
 */
function renderThemeOptions() {
    themeSelect.innerHTML = THEME_DEFINITIONS.map(
        (theme) => `<option value="${theme.id}">${theme.label}</option>`
    ).join("");
}

/**
 * 获取主题定义
 * @param {string} themeName - 主题名称
 * @returns {Object} 主题定义
 */
function getThemeDefinition(themeName) {
    return THEME_DEFINITIONS.find((theme) => theme.id === themeName) || THEME_DEFINITIONS[0];
}

/**
 * 初始化应用
 */
initializeWechatCleanupConfig(); // 初始化微信清理配置
initializeTheme(); // 初始化主题
renderExplorer(); // 渲染资源管理器
renderEditor(); // 渲染编辑器
renderAnalysis(); // 渲染分析结果
updateActionState(); // 更新操作状态
loadCloudSyncStatus(); // 加载云同步状态
