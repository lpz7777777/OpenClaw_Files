const { ipcRenderer } = require("electron");
const axios = require("axios");
const fs = require("fs");
const path = require("path");
const mammoth = require("mammoth");
const XLSX = require("xlsx");

const API_BASE = "http://localhost:8765";
const PREVIEW_BYTE_LIMIT = 200 * 1024;
const WORD_EXTENSIONS = new Set([".doc", ".docx"]);
const EXCEL_EXTENSIONS = new Set([".xls", ".xlsx", ".csv"]);
const THEME_STORAGE_KEY = "openclaw-workspace-theme";
const THEMES = new Set(["workspace", "mac"]);

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
    analysisTone: "idle",
    analysisMessage: "选择文件夹后，这里会显示 OpenClaw 输出的整理建议、操作计划和执行结果。",
    currentTheme: "workspace",
};

const selectFolderBtn = document.getElementById("selectFolderBtn");
const analyzeBtn = document.getElementById("analyzeBtn");
const themeSelect = document.getElementById("themeSelect");
const selectedPath = document.getElementById("selectedPath");
const explorerStats = document.getElementById("explorerStats");
const explorerTree = document.getElementById("explorerTree");
const tabStrip = document.getElementById("tabStrip");
const editorMeta = document.getElementById("editorMeta");
const editorContent = document.getElementById("editorContent");
const analysisStatus = document.getElementById("analysisStatus");
const analysisMeta = document.getElementById("analysisMeta");
const planSummary = document.getElementById("planSummary");
const categoriesList = document.getElementById("categoriesList");
const operationsMeta = document.getElementById("operationsMeta");
const operationsList = document.getElementById("operationsList");
const resultDisplay = document.getElementById("resultDisplay");
const confirmBtn = document.getElementById("confirmBtn");
const newAnalysisBtn = document.getElementById("newAnalysisBtn");
const rollbackBtn = document.getElementById("rollbackBtn");
const cancelBtn = document.getElementById("cancelBtn");

themeSelect.addEventListener("change", (event) => {
    applyTheme(event.target.value);
});

selectFolderBtn.addEventListener("click", async () => {
    const folderPath = await ipcRenderer.invoke("select-folder");
    if (!folderPath) {
        return;
    }

    await openFolder(folderPath);
});

analyzeBtn.addEventListener("click", async () => {
    if (!state.currentFolderPath || state.isAnalyzing || state.isExecutingOperation) {
        return;
    }

    await analyzeFolder(state.currentFolderPath);
});

newAnalysisBtn.addEventListener("click", async () => {
    if (!state.currentFolderPath || state.isAnalyzing || state.isExecutingOperation) {
        return;
    }

    await analyzeFolder(state.currentFolderPath);
});

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
        { writeReadme: true }
    );
});

rollbackBtn.addEventListener("click", async () => {
    if (!state.canRollback || state.isExecutingOperation) {
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
            state.completedOperationIndexes = new Set();
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

cancelBtn.addEventListener("click", () => {
    state.currentPlan = null;
    state.lastResult = null;
    state.completedOperationIndexes = new Set();
    setAnalysisStatus("idle", "输出已清空。你可以重新分析当前文件夹。");
    renderAnalysis();
    renderEditor();
    updateActionState();
});

async function openFolder(folderPath) {
    state.currentFolderPath = folderPath;
    state.currentPlan = null;
    state.lastResult = null;
    state.canRollback = false;
    state.completedOperationIndexes = new Set();
    state.selectedNodePath = folderPath;
    state.expandedPaths = new Set([folderPath]);

    selectedPath.textContent = folderPath;

    setAnalysisStatus("loading", "正在读取目录结构并准备分析...");
    renderAnalysis();
    updateActionState();

    await loadFolderTree(folderPath, false);
    openOverviewTab();
    await analyzeFolder(folderPath);
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

async function analyzeFolder(folderPath) {
    state.isAnalyzing = true;
    state.currentPlan = null;
    state.completedOperationIndexes = new Set();
    state.canRollback = false;
    setAnalysisStatus("loading", "OpenClaw 正在分析当前文件夹结构...");
    renderAnalysis();
    updateActionState();

    try {
        const response = await axios.post(`${API_BASE}/analyze`, {
            folder_path: folderPath,
        });

        if (response.data.success) {
            state.currentPlan = response.data.plan;
            setAnalysisStatus("success", "分析完成，右侧已生成更细的整理建议。");
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
        analysisMeta.textContent = `${getPendingOperations().length} pending · ${state.treeStats.files} files`;
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
    const isCompleted = state.completedOperationIndexes.has(index);
    const sourceMarkup = operation.source
        ? `<div><span>${operationMeta.sourceLabel}</span><code>${escapeHtml(operation.source || "")}</code></div>`
        : "";
    const targetMarkup = operation.target
        ? `<div><span>${operationMeta.targetLabel}</span><code>${escapeHtml(operation.target || "")}</code></div>`
        : "";

    return `
        <article class="operation-item ${isCompleted ? "is-completed" : ""}">
            <div class="operation-topline">
                <div class="operation-heading">
                    <span class="operation-type ${operationMeta.tone}">${operationMeta.label}</span>
                    ${
                        isCompleted
                            ? '<span class="operation-status-badge">已执行</span>'
                            : `<button type="button" class="operation-confirm-btn" data-operation-index="${index}" ${
                                  state.isExecutingOperation ? "disabled" : ""
                              }>确认这条</button>`
                    }
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
    const isBusy = state.isAnalyzing || state.isExecutingOperation;

    analyzeBtn.disabled = !hasFolder || isBusy;
    newAnalysisBtn.disabled = !hasFolder || isBusy;
    confirmBtn.disabled = isBusy || operationCount === 0;
    rollbackBtn.disabled = isBusy || !state.canRollback;
    cancelBtn.disabled = isBusy || (!state.currentPlan && !state.lastResult);
}

async function executeSingleOperation(index) {
    if (state.isExecutingOperation || state.isAnalyzing || state.completedOperationIndexes.has(index)) {
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

async function executeOperations(indexes, loadingMessage, options = {}) {
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
        });

        if (response.data.success) {
            const resultItems = Array.isArray(response.data.results) ? response.data.results : [];
            const succeededIndexes = new Set(
                resultItems
                    .filter((item) => item?.success)
                    .map((item) => item?.operation?.client_index)
                    .filter((value) => Number.isInteger(value))
            );
            const successfulOperations = operations
                .filter(({ index }) => succeededIndexes.has(index))
                .map(({ operation }) => operation);
            const failedResults = resultItems.filter((item) => !item?.success);

            updatePendingOperationsAfterExecution(successfulOperations);
            succeededIndexes.forEach((index) => state.completedOperationIndexes.add(index));

            const remainingCount = getPendingOperations().length;
            const readmeGenerated = Boolean(response.data.readme_generated);
            const readmeError = response.data.readme_error ? String(response.data.readme_error) : "";
            const successCount = successfulOperations.length;
            const failureCount = failedResults.length;

            if (successCount > 0) {
                state.canRollback = true;
                await loadFolderTree(state.currentFolderPath, true);
                openOverviewTab();
            }

            if (failureCount === 0) {
                const baseMessage = options.writeReadme
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
                    readmeGenerated
                        ? "全部操作已执行，README 已写入根目录。"
                        : readmeError
                        ? `操作已执行，但 README 写入失败：${readmeError}`
                        : "操作已执行，目录树已同步刷新。"
                );
            } else {
                const failureSummary = failedResults
                    .slice(0, 2)
                    .map((item) => item.error)
                    .filter(Boolean)
                    .join("；");

                state.lastResult = {
                    type: "error",
                    message:
                        `本轮共成功执行 ${successCount} 条，失败 ${failureCount} 条，剩余 ${remainingCount} 条待确认。` +
                        (failureSummary ? ` 失败原因：${failureSummary}` : ""),
                    at: Date.now(),
                };
                setAnalysisStatus(
                    "error",
                    `部分操作执行失败：成功 ${successCount} 条，失败 ${failureCount} 条。`
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

function getPendingOperations() {
    const operations = Array.isArray(state.currentPlan?.operations) ? state.currentPlan.operations : [];
    return operations
        .map((operation, index) => ({ operation, index }))
        .filter(({ index }) => !state.completedOperationIndexes.has(index));
}

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

function formatDate(timestamp) {
    if (!timestamp) {
        return "未知时间";
    }

    return new Date(timestamp).toLocaleString("zh-CN", {
        hour12: false,
    });
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function initializeTheme() {
    const storedTheme = localStorage.getItem(THEME_STORAGE_KEY);
    applyTheme(storedTheme && THEMES.has(storedTheme) ? storedTheme : "workspace");
}

function applyTheme(themeName) {
    const normalizedTheme = THEMES.has(themeName) ? themeName : "workspace";
    state.currentTheme = normalizedTheme;
    document.body.dataset.theme = normalizedTheme;
    themeSelect.value = normalizedTheme;
    localStorage.setItem(THEME_STORAGE_KEY, normalizedTheme);
}

initializeTheme();
renderExplorer();
renderEditor();
renderAnalysis();
updateActionState();
