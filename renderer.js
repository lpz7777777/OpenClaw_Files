13/**
 * OpenClaw Files 前端渲染逻辑
 * 负责界面交互、文件预览分析结果展示百度网盘同步等功能
 */

// 引入依赖
const { ipcRenderer } = require("electron"); // Electron 进程间信
const axios = require("axios"); // HTTP 请求
const fs = require("fs"); // 文件系统操作
const path = require("path"); // 路径处理
const mammoth = require("mammoth"); // Word 文档解析
const XLSX = require("xlsx"); // Excel 表格解析

/**
 * 常量定义
 */
const API_BASE = "http://localhost:8765"; // 后端 API 基础地址
const PREVIEW_BYTE_LIMIT = 200 * 1024;
const WORD_EXTENSIONS = new Set([".doc", ".docx"]);
const EXCEL_EXTENSIONS = new Set([".xls", ".xlsx", ".csv"]);
const THEME_STORAGE_KEY = "openclaw-workspace-theme";
const AUTO_ANALYZE_STORAGE_KEY = "openclaw-auto-analyze-on-open";
const FOLDER_INSTRUCTION_STORAGE_KEY = "openclaw-folder-instructions";
const WECHAT_CLEANUP_STORAGE_KEY = "openclaw-wechat-cleanup-config";
const WECHAT_CLEANUP_MODE = "wechat_cleanup";

/** 操作类型筛配置：id -> { label, types[], tone }（tone ?operation-type ?CSS 类名丢致） */
const OPERATION_TYPE_FILTER_DEFS = [
    { id: "move", label: "移动", types: ["move"], tone: "move" },
    { id: "rename", label: "重命名文件", types: ["rename"], tone: "rename" },
    { id: "rename_folder", label: "重命名文件夹", types: ["rename_folder"], tone: "rename-folder" },
    { id: "create_folder", label: "新建文件夹", types: ["create_folder"], tone: "create-folder" },
    { id: "delete", label: "删除", types: ["delete"], tone: "delete" },
];

/**
 * 主题定义
 */
const THEME_DEFINITIONS = [
    {
        id: "workspace",
        label: "雾杉",
        description: "Warm paper texture and grounded colors for long sorting sessions.",
    },
    {
        id: "mac",
        label: "晴空",
        description: "Bright glassy highlights with a light macOS-inspired feel.",
    },
    {
        id: "fjord",
        label: "北岸",
        description: "Cool blue-gray tones with a technical workspace vibe.",
    },
    {
        id: "amber",
        label: "琥珀",
        description: "Creamy pages and amber accents like a desk full of folders.",
    },
    {
        id: "sage",
        label: "雨后",
        description: "Low-saturation greens with a soft misty background.",
    },
    {
        id: "petal",
        label: "珊瑚",
        description: "Soft coral color and morning-cloud atmosphere with more breathing room.",
    },
];
const THEMES = new Set(THEME_DEFINITIONS.map((theme) => theme.id)); // 主题 ID 集合
const DEFAULT_THEME = "mac"; // 默认主题
const DEFAULT_BDPAN_DAILY_TIME = "12:00"; // 默认百度网盘同步时间
const FILE_TYPE_ICON_ASSETS = {
    word: "assets/icons/word_icon.png",
    pdf: "assets/icons/PDF_icon.png",
    excel: "assets/icons/excel_icon.png",
    ppt: "assets/icons/ppt_icon.png",
    zip: "assets/icons/zip_icon.png",
    wechat: "assets/icons/wechat_icon.png",
};

/**
 * 应用状管? */
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
    analysisMessage: "Choose a folder to see OpenClaw suggestions, operation plans, and execution results here.",
    currentTheme: "mac",
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
    autoAnalyzeOnOpen: true,
    folderInstructionMap: {},
    currentFolderInstructions: [],
    instructionDraft: "",
    wechatCleanupConfig: {
        sourcePath: "",
        targetPath: "",
    },
    /** 操作类型是否可执行，默认全部点亮 */
    enabledOperationTypes: Object.fromEntries(
        OPERATION_TYPE_FILTER_DEFS.flatMap((def) => def.types.map((t) => [t, true]))
    ),
};

/**
 * DOM 元素引用
 */
const selectFolderBtn = document.getElementById("selectFolderBtn");
const wechatCleanupBtn = document.getElementById("wechatCleanupBtn");
const analyzeBtn = document.getElementById("analyzeBtn"); // 分析按钮
const themeSelect = document.getElementById("themeSelect");
const themeDescription = document.getElementById("themeDescription");
const selectedPath = document.getElementById("selectedPath"); // 选中路径显示
const explorerStats = document.getElementById("explorerStats");
const explorerTree = document.getElementById("explorerTree");
const instructionMeta = document.getElementById("instructionMeta");
const instructionMessages = document.getElementById("instructionMessages");
const instructionInput = document.getElementById("instructionInput");
const sendInstructionBtn = document.getElementById("sendInstructionBtn");
const tabStrip = document.getElementById("tabStrip");
const editorMeta = document.getElementById("editorMeta");
const editorContent = document.getElementById("editorContent");
const analysisStatus = document.getElementById("analysisStatus");
const analysisMeta = document.getElementById("analysisMeta");
const planSummary = document.getElementById("planSummary");
const categoriesList = document.getElementById("categoriesList"); // 分类列表
const operationsMeta = document.getElementById("operationsMeta");
const operationTypeFilters = document.getElementById("operationTypeFilters");
const operationsList = document.getElementById("operationsList");
const resultDisplay = document.getElementById("resultDisplay"); // 结果显示
const gatewayStatusPill = document.getElementById("gatewayStatusPill");
const gatewayStatusText = document.getElementById("gatewayStatusText");
const topbarJobsChips = document.getElementById("topbarJobsChips");
const bdpanMeta = document.getElementById("bdpanMeta");
const bdpanStatusCard = document.getElementById("bdpanStatusCard");
const bdpanRemotePathInput = document.getElementById("bdpanRemotePathInput");
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
const autoAnalyzeToggle = document.getElementById("autoAnalyzeToggle");
const wechatCleanupDialog = document.getElementById("wechatCleanupDialog"); // 微信清理弹窗
const wechatSourcePathInput = document.getElementById("wechatSourcePathInput");
const wechatTargetPathInput = document.getElementById("wechatTargetPathInput");
const wechatSourceBrowseBtn = document.getElementById("wechatSourceBrowseBtn");
const wechatTargetBrowseBtn = document.getElementById("wechatTargetBrowseBtn");
const wechatCleanupSaveBtn = document.getElementById("wechatCleanupSaveBtn"); // 微信清理保存
const wechatCleanupRunBtn = document.getElementById("wechatCleanupRunBtn"); // 微信清理执行

/**
 * 初始化主题项
 */
renderThemeOptions();

/**
 * 主题选择事件监听
 */
themeSelect.addEventListener("change", (event) => {
    applyTheme(event.target.value);
});

autoAnalyzeToggle.addEventListener("change", (event) => {
    state.autoAnalyzeOnOpen = Boolean(event.target.checked);
    localStorage.setItem(AUTO_ANALYZE_STORAGE_KEY, String(state.autoAnalyzeOnOpen));
    updateActionState();
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

instructionInput.addEventListener("input", (event) => {
    state.instructionDraft = event.target.value;
    updateActionState();
});

instructionInput.addEventListener("keydown", async (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        await sendInstructionMessage();
    }
});

sendInstructionBtn.addEventListener("click", async () => {
    await sendInstructionMessage();
});

/**
 * 选择文件夹按钮点击事? */
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
    const pendingAll = getPendingOperationsUnfiltered();
    if (pending.length === 0 && pendingAll.length === 0) {
        setAnalysisStatus("error", "No executable suggestions are available right now.");
        renderAnalysis();
        return;
    }

    const disabledCount = pendingAll.length - pending.length;
    const confirmMsg =
        disabledCount > 0
            ? `Execute ${pending.length} suggestions now? ${disabledCount} suggestions from disabled operation types will be discarded.`
            : `Execute the remaining ${pending.length} suggestions now?`;
    const confirmed = window.confirm(confirmMsg);
    if (!confirmed) {
        return;
    }

    const disabledIndexes = pendingAll
        .filter(({ operation }) => !isOperationTypeEnabled(operation?.type))
        .map(({ index }) => index);
    disabledIndexes.forEach((idx) => state.discardedOperationIndexes.add(idx));

    if (pending.length > 0) {
        await executeOperations(
            pending.map(({ index }) => index),
            `Executing the remaining ${pending.length} operations...`,
            { writeReadme: state.analysisMode !== WECHAT_CLEANUP_MODE }
        );
    } else {
        setAnalysisStatus("warning", `Discarded ${disabledCount} suggestions from disabled operation types. No other operations can be executed.`);
        renderAnalysis();
        updateActionState();
    }
});

/**
 * 回滚按钮点击事件
 */
rollbackBtn.addEventListener("click", async () => {
    if (!state.canRollback || state.isExecutingOperation || state.isCloudSyncBusy) {
        setAnalysisStatus("error", "There are no operations available to roll back right now.");
        renderAnalysis();
        return;
    }

    const confirmed = window.confirm("Are you sure you want to roll back the most recently executed file operations?");
    if (!confirmed) {
        return;
    }

    setAnalysisStatus("loading", "Rolling back the latest file operations...");
    renderAnalysis();
    updateActionState();

    try {
        const response = await axios.post(`${API_BASE}/rollback`, {});

        if (response.data.success) {
            state.lastResult = {
                type: "success",
                message: "Rollback succeeded. The most recently executed changes have been restored.",
                at: Date.now(),
            };
            state.canRollback = false;
            resetOperationProgress();
            setAnalysisStatus("success", "Rollback complete. The directory tree has been refreshed.");
            await loadFolderTree(state.currentFolderPath, true);
            openOverviewTab();
        } else {
            state.lastResult = {
                type: "error",
                message: `Rollback failed: ${response.data.error}`,
                at: Date.now(),
            };
            setAnalysisStatus("error", `Rollback failed: ${response.data.error}`);
        }
    } catch (error) {
        state.lastResult = {
            type: "error",
            message: `Rollback error: ${error.message}`,
            at: Date.now(),
        };
        setAnalysisStatus("error", `Rollback error: ${error.message}`);
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
    setAnalysisStatus("idle", "Output cleared. You can analyze the current folder again.");
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
    state.currentFolderInstructions = getFolderInstructionMessages(folderPath);
    state.instructionDraft = "";
    initializeBdpanDefaults(folderPath);

    selectedPath.textContent = buildSelectedPathText();
    renderFolderInstructions();

    setAnalysisStatus(
        "loading",
        analysisMode === WECHAT_CLEANUP_MODE
            ? "正在读取微信文件目录并准备专项清理分析..."
            : "正在读取目录结构并准备开始分析..."
    );
    renderAnalysis();
    updateActionState();

    await loadFolderTree(folderPath, false);
    openOverviewTab();
    if (!state.autoAnalyzeOnOpen) {
        setAnalysisStatus(
            "idle",
            analysisMode === WECHAT_CLEANUP_MODE
                ? "微信文件目录已载入，当前已关闭自动分析。点击“重新生成”即可创建专项清理方案。"
                : "文件夹已载入，当前已关闭自动分析。点击“重新生成”即可开始分析。"
        );
        renderAnalysis();
        updateActionState();
        return;
    }

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
        return "No folder selected yet.";
    }

    if (state.analysisMode === WECHAT_CLEANUP_MODE && state.analysisTargetRootPath) {
        return `${state.currentFolderPath} -> ${state.analysisTargetRootPath}`;
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
        return { ok: false, message: "Please choose the WeChat source folder first." };
    }
    if (!config.targetPath) {
        return { ok: false, message: "Please choose the target folder first." };
    }
    if (path.resolve(config.sourcePath) === path.resolve(config.targetPath)) {
        return { ok: false, message: "The WeChat source folder and target folder cannot be the same." };
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
        window.alert("The WeChat source folder and target folder cannot be the same.");
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
        const response = await axios.post(`${API_BASE}/cloud/status`, {}, { timeout: 6000 });
        if (response.data.success) {
            state.cloudSyncStatus = response.data;
            state.cloudSyncFeedback = null;
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
                message: `同步状检查失败：${response.data.error}`,
                at: Date.now(),
            };
        }
    } catch (error) {
        state.cloudSyncStatus = null;
        state.cloudSyncFeedback = {
            type: "error",
            message: `同步状检查失败：${error.message}`,
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
    const userRequests = normalizeInstructionMessages(state.currentFolderInstructions);

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
            : "OpenClaw 正在分析当前文件夹结构，并生成整理建议..."
    );
    renderAnalysis();
    updateActionState();

    try {
        const response = await axios.post(`${API_BASE}/analyze`, {
            folder_path: folderPath,
            mode,
            target_root_path: targetRootPath,
            user_requests: userRequests,
        });

        if (response.data.success) {
            state.currentPlan = response.data.plan;
            setAnalysisStatus(
                "success",
                mode === WECHAT_CLEANUP_MODE
                    ? "微信专项清理方案已生成，可在右侧查看并执行。"
                    : "分析完成，详细整理建议已出现在右侧面板。"
            );
            openOverviewTab();
        } else {
            setAnalysisStatus("error", `Analysis failed: ${response.data.error}`);
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
        explorerTree.textContent = "Choose a folder and the full directory structure will appear here.";
        renderFolderInstructions();
        return;
    }

    explorerStats.textContent = `${state.treeStats.folders} folders · ${state.treeStats.files} files`;
    explorerTree.className = "explorer-tree";
    explorerTree.innerHTML = "";
    explorerTree.appendChild(createTreeBranch(state.currentTree.root, 0));
    renderFolderInstructions();
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

    let icon;
    if (iconMeta.kind === "image") {
        icon = document.createElement("img");
        icon.className = "tree-icon-image";
        icon.src = iconMeta.src;
        icon.alt = iconMeta.alt || "";
        icon.draggable = false;
    } else {
        icon = document.createElement("span");
        icon.className = `tree-icon tree-icon-${iconMeta.tone}`;
        icon.textContent = iconMeta.label;
    }

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
            pinned.textContent = "概";
            tabButton.appendChild(pinned);
        }

        tabStrip.appendChild(tabButton);
    });
}

function renderOverviewDocument() {
    const summaryMarkup = renderSummaryMarkup(state.currentPlan);
    const categories = Array.isArray(state.currentPlan?.categories) ? state.currentPlan.categories : [];
    const operations = Array.isArray(state.currentPlan?.operations) ? state.currentPlan.operations : [];
    const folderInstructions = normalizeInstructionMessages(state.currentFolderInstructions);
    const instructionMarkup =
        folderInstructions.length > 0
            ? `<ul class="summary-list">${folderInstructions
                  .map((item) => `<li class="summary-item">${escapeHtml(item)}</li>`)
                  .join("")}</ul>`
            : '<p class="subtle">未额外提供整理要求。</p>';

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

                <article class="overview-card full-span">
                    <h4>用户整理要求</h4>
                    ${instructionMarkup}
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
                "This version can preview .docx files directly.",
                "Legacy .doc files do not yet have a stable dependency-free parser, so only file information is shown for now.",
            ],
            notice: "Convert .doc to .docx for a fuller preview.",
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
            ? "The document was parsed. Some complex formatting may be simplified in preview."
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
        notice: totalRows > rows.length ? `当前仅预览前 ${rows.length} 行数据` : "",
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
        analysisMeta.textContent = `${modeLabel} · ${getPendingOperations().length} 项待执行 · ${state.treeStats.files} 个文件`;
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

    renderOperationTypeFilters();

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
        operationsList.textContent = "No executable operations yet.";
    }

    if (state.lastResult) {
        resultDisplay.className = `result-display result-${state.lastResult.type}`;
        resultDisplay.innerHTML = `
            <p>${escapeHtml(state.lastResult.message)}</p>
            <p class="result-timestamp">${formatDate(state.lastResult.at)}</p>
        `;
    } else {
        resultDisplay.className = "result-display empty-inline";
        resultDisplay.textContent = "No file operations have been executed yet.";
    }

    renderCloudSyncPanel();
}

function getJobScheduleLabel(job) {
    const dailyTime = String(job?.daily_time || "").trim();
    if (dailyTime) {
        return `每日 ${dailyTime}`;
    }

    const cronExpression = String(job?.cron || "").trim();
    return cronExpression ? `Cron ${cronExpression}` : "No schedule configured";
}

function getJobDisplayName(job) {
    const folderName = path.basename(String(job?.folder_path || "").trim()) || "Untitled Job";
    return `${folderName} · ${getJobScheduleLabel(job)}`;
}

function renderTopbarCloudSummary(status, jobs) {
    const gateway = status?.gateway || {};
    const gatewayOk = Boolean(gateway.ok);

    if (state.isCloudSyncLoading && !status) {
        gatewayStatusPill.className = "sync-status-pill neutral";
        gatewayStatusPill.textContent = "Gateway 检查中...";
        gatewayStatusText.textContent = "正在连接到OpenClaw Gateway，获取同步状态...";
    } else if (!status && state.cloudSyncFeedback?.type === "error") {
        gatewayStatusPill.className = "sync-status-pill error";
        gatewayStatusPill.textContent = "Gateway error";
        gatewayStatusText.textContent = state.cloudSyncFeedback.message;
    } else if (status) {
        gatewayStatusPill.className = `sync-status-pill ${gatewayOk ? "ok" : "error"}`;
        gatewayStatusPill.textContent = gatewayOk ? "Gateway 可用" : "Gateway 不可用";
        gatewayStatusText.textContent =
            String(gateway.detail || "").trim() ||
            (gatewayOk ? "OpenClaw Gateway 已连接." : "OpenClaw Gateway is not connected yet.");
    } else {
        gatewayStatusPill.className = "sync-status-pill neutral";
        gatewayStatusPill.textContent = "Gateway unchecked";
        gatewayStatusText.textContent = "OpenClaw Gateway has not been checked yet.";
    }

    if (jobs.length > 0) {
        topbarJobsChips.innerHTML = jobs
            .slice(0, 4)
            .map(
                (job) => `
                    <span class="topbar-job-chip ${job.enabled ? "ok" : "warning"}" title="${escapeHtml(
                        `${job.name || "Untitled Job"} ? ${job.folder_path || "-"} ? ${job.remote_path || "-"}`
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
        bdpanMeta.textContent = "Checking";
    } else if (state.isCloudSyncBusy) {
        bdpanMeta.textContent = "Running";
    } else if (!hasConfirmedStatus) {
        bdpanMeta.textContent = "Unchecked";
    } else {
        bdpanMeta.textContent = `${jobs.length} jobs`;
    }

    const statusLines = [];

    if (!hasConfirmedStatus) {
        statusLines.push(
            `<div class="sync-status-line sync-status-note"><span>${
                state.isCloudSyncLoading
                    ? "正在刷新百度网盘登录状和定时任务信息..."
                    : "Finish one refresh to see Baidu login status and scheduled jobs here."
            }</span></div>`
        );
    } else {
        if (bdpanStatus.installed) {
            const authText = bdpanStatus.authenticated
                ? `百度网盘已登录：${bdpanStatus.username || "当前账户"}`
                : "Baidu Netdisk is not logged in or the session has expired.";
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
                `<div class="sync-status-line"><span class="sync-status-pill error">bdpan not installed</span><span>${escapeHtml(
                    bdpanStatus.detail || "bdpan CLI was not found."
                )}</span></div>`
            );
        }

        statusLines.push(
            `<div class="sync-status-line"><span class="sync-status-pill ${
                cronStatus.enabled ? "ok" : "warning"
            }>${cronStatus.enabled ? "Scheduler enabled" : "Scheduler disabled"}</span><span>${escapeHtml(
                cronStatus.detail || "OpenClaw cron has not been checked yet."
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
                            <strong>${escapeHtml(job.name || "Untitled Job")}</strong>
                            <div class="sync-job-actions">
                                <span class="sync-job-pill ${job.enabled ? "ok" : "warning"}">${
                                    job.enabled ? "Enabled" : "Disabled"
                                }</span>
                                <button
                                    type="button"
                                    class="ghost-btn sync-job-remove-btn"
                                    data-job-id="${escapeHtml(job.id || "")}"
                                    data-job-name="${escapeHtml(job.name || "Untitled Job")}"
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
                                ? `<div class="sync-job-next">Next run: ${escapeHtml(job.next_run_at)}</div>`
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
        bdpanJobsList.textContent = "No Baidu Netdisk sync tasks created by this app yet.";
    }
}

function isOperationTypeEnabled(opType) {
    return Boolean(state.enabledOperationTypes?.[opType] !== false);
}

function renderOperationTypeFilters() {
    const operations = Array.isArray(state.currentPlan?.operations) ? state.currentPlan.operations : [];
    const hasOps = operations.length > 0;

    if (!hasOps) {
        operationTypeFilters.className = "operation-type-filters is-empty";
        operationTypeFilters.innerHTML = "";
        return;
    }

    operationTypeFilters.className = "operation-type-filters";
    operationTypeFilters.innerHTML = OPERATION_TYPE_FILTER_DEFS.map((def) => {
        const anyEnabled = def.types.some((t) => state.enabledOperationTypes?.[t] !== false);
        const hasAnyOfType = operations.some((op) => def.types.includes(op?.type));
        const toneClass = def.tone ? `tone-${def.tone}` : "";
        const className = hasAnyOfType
            ? `operation-type-filter-chip tone-${def.tone} ${anyEnabled ? "is-enabled" : "is-disabled"}`
            : `operation-type-filter-chip tone-${def.tone} is-empty`;
        return `<button type="button" class="${className}" data-filter-id="${escapeHtml(def.id)}" title="${
            anyEnabled ? "点击后将关闭该类型，执行时会自动跳过。" : "点击后将启用该类型，执行时会纳入处理。"
        }">${escapeHtml(def.label)}</button>`;
    }).join("");

    operationTypeFilters.querySelectorAll("[data-filter-id]").forEach((btn) => {
        btn.addEventListener("click", () => {
            const def = OPERATION_TYPE_FILTER_DEFS.find((d) => d.id === btn.dataset.filterId);
            if (!def) return;
            const next = def.types.some((t) => state.enabledOperationTypes?.[t] !== false) ? false : true;
            def.types.forEach((t) => {
                state.enabledOperationTypes[t] = next;
            });
            renderAnalysis();
            updateActionState();
        });
    });
}

function getOperationMeta(operation) {
    switch (operation?.type) {
        case "move":
            return { label: "移动", tone: "move", sourceLabel: "来源", targetLabel: "目标" };
        case "rename":
            return { label: "重命名文件", tone: "rename", sourceLabel: "原路径", targetLabel: "新路径" };
        case "rename_folder":
            return { label: "重命名文件夹", tone: "rename-folder", sourceLabel: "原目录", targetLabel: "新目录" };
        case "create_folder":
            return { label: "新建文件夹", tone: "create-folder", sourceLabel: "", targetLabel: "创建到" };
        case "delete":
            return { label: "删除", tone: "delete", sourceLabel: "路径", targetLabel: "" };
        default:
            return { label: "操作", tone: "rename", sourceLabel: "来源", targetLabel: "目标" };
    }
}

function renderOperationItem(operation, index) {
    const operationMeta = getOperationMeta(operation);
    const isCompleted = isOperationCompleted(index);
    const isDiscarded = isOperationDiscarded(index);
    const typeEnabled = isOperationTypeEnabled(operation?.type);
    const sourceMarkup = operation.source
        ? `<div><span>${operationMeta.sourceLabel}</span><code>${escapeHtml(operation.source || "")}</code></div>`
        : "";
    const targetMarkup = operation.target
        ? `<div><span>${operationMeta.targetLabel}</span><code>${escapeHtml(operation.target || "")}</code></div>`
        : "";
    const itemStateClass = isCompleted ? "is-completed" : isDiscarded ? "is-discarded" : !typeEnabled ? "is-type-disabled" : "";
    const actionMarkup = isCompleted
        ? '<span class="operation-status-badge">已完成</span>'
        : isDiscarded
        ? '<span class="operation-status-badge is-discarded">已丢弃</span>'
        : !typeEnabled
        ? '<span class="operation-status-badge is-type-disabled">已关闭</span>'
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
                <span class="operation-reason">${escapeHtml(operation.reason || "未提供原因")}</span>
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
        return '<p class="empty-inline">No analysis summary yet.</p>';
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
        .split(/[。！？.!?]/)
        .map((part) => part.trim())
        .filter(Boolean);
}

function setAnalysisStatus(tone, message) {
    state.analysisTone = tone;
    state.analysisMessage = message;
}

function normalizeInstructionMessages(messages) {
    if (!Array.isArray(messages)) {
        return [];
    }

    return messages
        .map((message) => String(message || "").replace(/\s+/g, " ").trim())
        .filter(Boolean)
        .slice(-8);
}

function normalizeInstructionFolderPath(folderPath) {
    const normalizedPath = String(folderPath || "").trim();
    if (!normalizedPath) {
        return "";
    }

    try {
        return path.resolve(normalizedPath);
    } catch (error) {
        return normalizedPath;
    }
}

function persistFolderInstructionMap() {
    localStorage.setItem(
        FOLDER_INSTRUCTION_STORAGE_KEY,
        JSON.stringify(state.folderInstructionMap || {})
    );
}

function getFolderInstructionMessages(folderPath) {
    const key = normalizeInstructionFolderPath(folderPath);
    if (!key) {
        return [];
    }

    return normalizeInstructionMessages(state.folderInstructionMap?.[key]);
}

function syncCurrentFolderInstructions() {
    const key = normalizeInstructionFolderPath(state.currentFolderPath);
    if (!key) {
        return;
    }

    const messages = normalizeInstructionMessages(state.currentFolderInstructions);
    state.currentFolderInstructions = messages;

    if (messages.length > 0) {
        state.folderInstructionMap[key] = messages;
    } else {
        delete state.folderInstructionMap[key];
    }

    persistFolderInstructionMap();
}

function renderFolderInstructions() {
    const hasFolder = Boolean(state.currentFolderPath);
    const messages = normalizeInstructionMessages(state.currentFolderInstructions);
    const isBusy = state.isAnalyzing || state.isExecutingOperation || state.isCloudSyncBusy;

    if (!hasFolder) {
        instructionMeta.textContent = "Not sent";
        instructionMessages.className = "instruction-messages empty-inline";
        instructionMessages.textContent = "After opening a folder, you can add extra instructions for how OpenClaw should organize it here.";
        instructionInput.value = "";
        instructionInput.disabled = true;
        return;
    }

    instructionMeta.textContent = `${messages.length} requests`;
    instructionInput.disabled = false;
    instructionInput.value = state.instructionDraft;

    if (messages.length === 0) {
        instructionMessages.className = "instruction-messages empty-inline";
        instructionMessages.textContent = "No extra instructions yet. Add naming rules, archive preferences, or exclusions here.";
        return;
    }

    instructionMessages.className = "instruction-messages";
    instructionMessages.innerHTML = messages
        .map(
            (message, index) => `
                <div class="instruction-message">
                    <p>${escapeHtml(message)}</p>
                    <button
                        class="instruction-remove-btn"
                        type="button"
                        data-instruction-index="${index}"
                        title="删除这条要求"
                        ${isBusy ? "disabled" : ""}
                    >
                        ×
                    </button>
                </div>
            `
        )
        .join("");

    instructionMessages.querySelectorAll("[data-instruction-index]").forEach((button) => {
        button.addEventListener("click", () => {
            const index = Number(button.dataset.instructionIndex);
            if (!Number.isInteger(index)) {
                return;
            }

            state.currentFolderInstructions = state.currentFolderInstructions.filter(
                (_, itemIndex) => itemIndex !== index
            );
            syncCurrentFolderInstructions();
            renderFolderInstructions();
            renderEditor();
            updateActionState();
        });
    });
}

async function sendInstructionMessage() {
    if (!state.currentFolderPath || state.isAnalyzing || state.isExecutingOperation || state.isCloudSyncBusy) {
        return;
    }

    const message = String(state.instructionDraft || "").replace(/\s+/g, " ").trim();
    if (!message) {
        return;
    }

    state.currentFolderInstructions = normalizeInstructionMessages([
        ...state.currentFolderInstructions,
        message,
    ]);
    state.instructionDraft = "";
    syncCurrentFolderInstructions();
    renderFolderInstructions();
    renderEditor();
    updateActionState();
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
    const pendingTotalCount = getPendingOperationsUnfiltered().length;
    const isBusy = state.isAnalyzing || state.isExecutingOperation || state.isCloudSyncBusy;
    const hasRemotePath = Boolean(String(state.bdpanRemotePath || "").trim());
    const hasDailyTime = Boolean(String(state.bdpanDailyTime || "").trim());
    const hasTimezone = Boolean(String(state.bdpanTimezone || "").trim());
    const hasInstructionDraft = Boolean(String(state.instructionDraft || "").trim());

    wechatCleanupBtn.disabled = isBusy;
    analyzeBtn.disabled = !hasFolder || isBusy;
    newAnalysisBtn.disabled = !hasFolder || isBusy;
    confirmBtn.disabled = isBusy || pendingTotalCount === 0;
    rollbackBtn.disabled = isBusy || !state.canRollback;
    cancelBtn.disabled = isBusy || (!state.currentPlan && !state.lastResult);
    bdpanUploadBtn.disabled = !hasFolder || isBusy || !hasRemotePath;
    bdpanRefreshBtn.disabled = state.isCloudSyncBusy || state.isCloudSyncLoading;
    bdpanScheduleBtn.disabled = !hasFolder || isBusy || !hasRemotePath || !hasDailyTime || !hasTimezone;
    wechatCleanupRunBtn.disabled = isBusy;
    sendInstructionBtn.disabled = !hasFolder || isBusy || !hasInstructionDraft;
    autoAnalyzeToggle.disabled = isBusy;
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
            message: "Please enter the Baidu Netdisk target path first.",
            at: Date.now(),
        };
        renderCloudSyncPanel();
        updateActionState();
        return;
    }

    const confirmed = window.confirm(
        `Upload the current folder to Baidu Netdisk now?\n\nLocal folder: ${state.currentFolderPath}\nRemote path: ${remotePath}\n\nThis uses the local bdpan CLI directly to avoid large uploads stalling through the chat path.`
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
            message: `Baidu Netdisk upload failed: ${errorMessage}`,
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
            message: "Please complete the remote path, daily sync time, and timezone first.",
            at: Date.now(),
        };
        renderCloudSyncPanel();
        updateActionState();
        return;
    }

    const confirmed = window.confirm(
        `Create a daily automatic sync task to Baidu Netdisk?\n\nLocal folder: ${state.currentFolderPath}\nRemote path: ${remotePath}\nDaily time: ${dailyTime}\nTimezone: ${timezone}`
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
            message: `Failed to create scheduled sync: ${errorMessage}`,
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

    const confirmed = window.confirm(`Cancel this scheduled task?\n\nTask: ${jobName || jobId}`);
    if (!confirmed) {
        return;
    }

    state.isCloudSyncBusy = true;
    state.cloudSyncFeedback = {
        type: "loading",
        message: `Cancelling scheduled task: ${jobName || jobId}`,
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
            message: `Failed to cancel scheduled task: ${errorMessage}`,
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
 * 构建云同步消? * @param {Object} payload - 消息内容
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
        parts.push(`Target path: ${remotePath}`);
    }
    if (dailyTime) {
        parts.push(`Daily time: ${dailyTime}`);
    }
    if (details.length > 0) {
        parts.push(`Details: ${details.join("；")}`);
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

    const confirmed = window.confirm("现在执行这条建议吗？");
    if (!confirmed) {
        return;
    }

    await executeOperations([index], "正在执行所选建议...");
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
                    ? `已完成 ${successCount} 条微信清理操作，文件正在整理到目标目录。`
                    : options.writeReadme
                    ? `已完成 ${successCount} 条操作，并将最新整理结果写入磁盘。`
                    : `已完成 ${successCount} 条操作，仍有 ${remainingCount} 条建议等待确认。`;
                const readmeMessage = readmeGenerated
                    ? " 已在当前打开目录的根目录写入 README.md。"
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
                        ? "微信清理操作已执行完成，源目录和目标目录都已刷新。"
                        : readmeGenerated
                        ? "全部操作已执行完成，并已在根目录写入 README.md。"
                        : readmeError
                        ? `操作已执行完成，但 README.md 写入失败：${readmeError}`
                        : "操作已执行完成，目录树已刷新。"
                );
            } else {
                const discardedSummary = discardedResults
                    .slice(0, 2)
                    .map((item) => item.error)
                    .filter(Boolean)
                    .join("；");
                const readmeMessage = readmeGenerated
                    ? " 已在当前打开目录的根目录写入 README.md。"
                    : readmeError
                    ? ` README.md 写入失败：${readmeError}`
                    : "";

                state.lastResult = {
                    type: readmeError ? "error" : "warning",
                    message:
                        `${
                            isWechatCleanup
                                ? `本轮已执行 ${successCount} 条微信清理操作，并丢弃了 ${discardedCount} 条无法执行的建议。`
                                : `本轮已执行 ${successCount} 条操作，并丢弃了 ${discardedCount} 条无法执行的建议。`
                        }` +
                        (remainingCount > 0 ? ` 仍有 ${remainingCount} 条建议等待确认。` : "") +
                        (discardedSummary ? ` 丢弃原因：${discardedSummary}` : "") +
                        readmeMessage,
                    at: Date.now(),
                };
                setAnalysisStatus(
                    readmeError ? "error" : "warning",
                    isWechatCleanup
                        ? remainingCount > 0
                            ? `已自动丢弃 ${discardedCount} 条无法执行的微信清理建议，仍有 ${remainingCount} 条建议等待确认。`
                            : `已自动丢弃 ${discardedCount} 条无法执行的微信清理建议。`
                        : remainingCount > 0
                        ? readmeGenerated
                            ? `已自动丢弃 ${discardedCount} 条无法执行的建议，仍有 ${remainingCount} 条建议等待确认，并已在根目录写入 README.md。`
                            : `已自动丢弃 ${discardedCount} 条无法执行的建议，仍有 ${remainingCount} 条建议等待确认。`
                        : readmeGenerated
                        ? `已自动丢弃 ${discardedCount} 条无法执行的建议，并已在根目录写入 README.md。`
                        : `已自动丢弃 ${discardedCount} 条无法执行的建议。`
                );
            }
        } else {
            state.lastResult = {
                type: "error",
                message: `Execution failed: ${response.data.error}`,
                at: Date.now(),
            };
            setAnalysisStatus("error", `Execution failed: ${response.data.error}`);
        }
    } catch (error) {
        state.lastResult = {
            type: "error",
            message: `Execution error: ${error.message}`,
            at: Date.now(),
        };
        setAnalysisStatus("error", `Execution error: ${error.message}`);
    } finally {
        state.isExecutingOperation = false;
        renderAnalysis();
        updateActionState();
    }
}

/**
 * 获取待执行的操作（不含类型筛选，仅排除已处理? * @returns {Array} 待执行操作数? */
function getPendingOperationsUnfiltered() {
    const operations = Array.isArray(state.currentPlan?.operations) ? state.currentPlan.operations : [];
    return operations
        .map((operation, index) => ({ operation, index }))
        .filter(({ index }) => !isOperationHandled(index));
}

/**
 * 获取待执行的操作（仅含已点亮类型的未完成的）
 * @returns {Array} 待执行操作数? */
function getPendingOperations() {
    return getPendingOperationsUnfiltered().filter(({ operation }) => isOperationTypeEnabled(operation?.type));
}

/**
 * 清理不存在的标签? */
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
 * @param {Buffer} buffer - 文件缓冲? * @returns {boolean} 是否为二进制文件
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
 * 获取文件图标元数? * @param {string} fileName - 文件? * @param {string} extension - 文件扩展? * @returns {Object} 图标元数? */
function fileIconMeta(fileName, extension) {
    const normalizedName = String(fileName || "").toLowerCase();
    const extensionToAsset = {
        ".doc": FILE_TYPE_ICON_ASSETS.word,
        ".docx": FILE_TYPE_ICON_ASSETS.word,
        ".txt": FILE_TYPE_ICON_ASSETS.word,
        ".md": FILE_TYPE_ICON_ASSETS.word,
        ".pdf": FILE_TYPE_ICON_ASSETS.pdf,
        ".xls": FILE_TYPE_ICON_ASSETS.excel,
        ".xlsx": FILE_TYPE_ICON_ASSETS.excel,
        ".csv": FILE_TYPE_ICON_ASSETS.excel,
        ".ppt": FILE_TYPE_ICON_ASSETS.ppt,
        ".pptx": FILE_TYPE_ICON_ASSETS.ppt,
        ".zip": FILE_TYPE_ICON_ASSETS.zip,
        ".rar": FILE_TYPE_ICON_ASSETS.zip,
        ".7z": FILE_TYPE_ICON_ASSETS.zip,
        ".tar": FILE_TYPE_ICON_ASSETS.zip,
        ".gz": FILE_TYPE_ICON_ASSETS.zip,
    };
    const textFallbackMap = {
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
        ".env": { label: "ENV", tone: "config" },
        ".yml": { label: "CFG", tone: "config" },
        ".yaml": { label: "CFG", tone: "config" },
        ".ini": { label: "CFG", tone: "config" },
        ".toml": { label: "CFG", tone: "config" },
    };

    if (normalizedName === "readme.md") {
        return {
            kind: "image",
            src: FILE_TYPE_ICON_ASSETS.word,
            alt: "文档",
        };
    }

    if (normalizedName.includes("wechat") || normalizedName.includes("微信")) {
        return {
            kind: "image",
            src: FILE_TYPE_ICON_ASSETS.wechat,
            alt: "微信",
        };
    }

    if (extensionToAsset[extension]) {
        return {
            kind: "image",
            src: extensionToAsset[extension],
            alt: extension.replace(".", "").toUpperCase() || "FILE",
        };
    }

    return textFallbackMap[extension] || { label: "FILE", tone: "generic" };
}

/**
 * 格式化字节大? * @param {number} value - 字节大小
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
 * 格式化日期时? * @param {number} timestamp - 时间? * @returns {string} 格式化后的日期时间字符串
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
 * @param {string} value - 要转义的字符? * @returns {string} 转义后的字符? */
function escapeHtml(value) {
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

/**
 * 初始化主? */
function initializeTheme() {
    applyTheme(DEFAULT_THEME);
}

function initializeAutoAnalyzePreference() {
    const storedValue = localStorage.getItem(AUTO_ANALYZE_STORAGE_KEY);
    state.autoAnalyzeOnOpen = storedValue !== "false";
    autoAnalyzeToggle.checked = state.autoAnalyzeOnOpen;
}

function initializeFolderInstructionMap() {
    try {
        const storedValue = JSON.parse(localStorage.getItem(FOLDER_INSTRUCTION_STORAGE_KEY) || "{}");
        if (storedValue && typeof storedValue === "object" && !Array.isArray(storedValue)) {
            state.folderInstructionMap = Object.fromEntries(
                Object.entries(storedValue).map(([folderPath, messages]) => [
                    normalizeInstructionFolderPath(folderPath),
                    normalizeInstructionMessages(messages),
                ])
            );
            return;
        }
    } catch (error) {
        // Ignore invalid persisted instruction state and fall back to defaults.
    }

    state.folderInstructionMap = {};
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

function setupAnalysisActionLayout() {
    const actionBar = document.querySelector(".action-buttons");
    if (
        !actionBar ||
        actionBar.dataset.layoutReady === "true" ||
        !operationTypeFilters ||
        !confirmBtn ||
        !newAnalysisBtn ||
        !rollbackBtn ||
        !autoAnalyzeToggle ||
        !cancelBtn
    ) {
        return;
    }

    const autoAnalyzeSwitch = autoAnalyzeToggle.closest(".toggle-switch");
    if (!autoAnalyzeSwitch) {
        return;
    }

    const filterGroup = document.createElement("div");
    filterGroup.id = "operationFilterGroup";
    filterGroup.className = "analysis-action-group analysis-filter-group";

    const filterHeading = document.createElement("div");
    filterHeading.className = "analysis-action-heading";
    filterHeading.textContent = "Filters";

    filterGroup.append(filterHeading, operationTypeFilters);

    const actionStack = document.createElement("div");
    actionStack.className = "analysis-action-stack";

    const primaryGroup = document.createElement("div");
    primaryGroup.className = "analysis-action-group analysis-primary-actions";

    const primaryHeading = document.createElement("div");
    primaryHeading.className = "analysis-action-heading";
    primaryHeading.textContent = "Actions";

    const primaryRow = document.createElement("div");
    primaryRow.className = "analysis-button-row";
    primaryRow.append(confirmBtn, newAnalysisBtn, rollbackBtn);
    primaryGroup.append(primaryHeading, primaryRow);

    const secondaryGroup = document.createElement("div");
    secondaryGroup.className = "analysis-action-group analysis-secondary-actions";

    const secondaryHeading = document.createElement("div");
    secondaryHeading.className = "analysis-action-heading";
    secondaryHeading.textContent = "Tools";

    const secondaryRow = document.createElement("div");
    secondaryRow.className = "analysis-button-row analysis-button-row-secondary";
    secondaryRow.append(autoAnalyzeSwitch, cancelBtn);
    secondaryGroup.append(secondaryHeading, secondaryRow);

    actionStack.append(primaryGroup, secondaryGroup);
    actionBar.replaceChildren(filterGroup, actionStack);
    actionBar.dataset.layoutReady = "true";
}
setupAnalysisActionLayout();

/**
 * 初始化应用
 */
initializeWechatCleanupConfig();
initializeAutoAnalyzePreference();
initializeFolderInstructionMap();
initializeTheme();
renderExplorer();
renderEditor();
renderAnalysis();
updateActionState();
loadCloudSyncStatus();
