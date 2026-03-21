const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const fs = require("fs");
const http = require("http");
const path = require("path");
const { spawn } = require("child_process");

let mainWindow = null;
let backendProcess = null;

const BACKEND_PORT = 8765;
const BACKEND_STARTUP_RETRIES = 24;
const BACKEND_STARTUP_DELAY_MS = 500;

function resolveWindowIconPath() {
    const iconPath = path.join(__dirname, "assets", "app-icon.png");
    return fs.existsSync(iconPath) ? iconPath : undefined;
}

function createWindow() {
    const windowOptions = {
        width: 1560,
        height: 960,
        minWidth: 1200,
        minHeight: 760,
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false,
        },
        backgroundColor: "#f4efe7",
    };
    const iconPath = resolveWindowIconPath();
    if (iconPath) {
        windowOptions.icon = iconPath;
    }

    mainWindow = new BrowserWindow(windowOptions);

    mainWindow.setMenuBarVisibility(false);
    mainWindow.loadFile("index.html");

    mainWindow.on("closed", () => {
        mainWindow = null;
    });
}

function ensureRuntimeConfig() {
    const userDataPath = app.getPath("userData");
    fs.mkdirSync(userDataPath, { recursive: true });

    const runtimeEnvPath = path.join(userDataPath, ".env");
    const exampleEnvPath = path.join(__dirname, ".env.example");

    if (!fs.existsSync(runtimeEnvPath) && fs.existsSync(exampleEnvPath)) {
        fs.copyFileSync(exampleEnvPath, runtimeEnvPath);
    }

    return {
        runtimeEnvPath,
        gatewayStateDir: path.join(userDataPath, ".openclaw-state"),
    };
}

function resolveBackendLaunch(runtimeConfig) {
    if (app.isPackaged) {
        const backendExecutable = path.join(
            process.resourcesPath,
            "backend",
            "OpenClawBackend",
            "OpenClawBackend.exe"
        );

        return {
            command: backendExecutable,
            args: [],
            cwd: app.getPath("userData"),
            env: {
                ...process.env,
                OPENCLAW_FILES_ENV: runtimeConfig.runtimeEnvPath,
                GATEWAY_STATE_DIR: process.env.GATEWAY_STATE_DIR || runtimeConfig.gatewayStateDir,
            },
        };
    }

    const pythonPath = process.platform === "win32" ? "python" : "python3";
    return {
        command: pythonPath,
        args: [path.join(__dirname, "backend", "server.py")],
        cwd: __dirname,
        env: {
            ...process.env,
            OPENCLAW_FILES_ENV: path.join(__dirname, ".env"),
            GATEWAY_STATE_DIR: process.env.GATEWAY_STATE_DIR || runtimeConfig.gatewayStateDir,
            PYTHONIOENCODING: "utf-8",
        },
    };
}

function startBackendServer() {
    const runtimeConfig = ensureRuntimeConfig();
    const launchConfig = resolveBackendLaunch(runtimeConfig);

    backendProcess = spawn(launchConfig.command, launchConfig.args, {
        cwd: launchConfig.cwd,
        env: launchConfig.env,
        windowsHide: true,
    });

    backendProcess.stdout.on("data", (data) => {
        console.log(`[Backend] ${String(data).trim()}`);
    });

    backendProcess.stderr.on("data", (data) => {
        console.error(`[Backend Error] ${String(data).trim()}`);
    });

    backendProcess.on("error", (error) => {
        console.error(`[Backend Spawn Error] ${error.message}`);
        if (!app.isReady()) {
            return;
        }
        dialog.showErrorBox(
            "后端启动失败",
            `无法启动 OpenClaro 后端服务：${error.message}`
        );
    });

    backendProcess.on("exit", (code, signal) => {
        console.log(`[Backend Exit] code=${code} signal=${signal}`);
        backendProcess = null;
    });
}

function probeBackend() {
    return new Promise((resolve) => {
        const request = http.request(
            {
                hostname: "127.0.0.1",
                port: BACKEND_PORT,
                path: "/",
                method: "GET",
                timeout: 1000,
            },
            () => {
                resolve(true);
            }
        );

        request.on("error", () => {
            resolve(false);
        });

        request.on("timeout", () => {
            request.destroy();
            resolve(false);
        });

        request.end();
    });
}

async function waitForBackendReady() {
    for (let attempt = 0; attempt < BACKEND_STARTUP_RETRIES; attempt += 1) {
        if (await probeBackend()) {
            return true;
        }

        await new Promise((resolve) => {
            setTimeout(resolve, BACKEND_STARTUP_DELAY_MS);
        });
    }

    return false;
}

function stopBackendServer() {
    if (!backendProcess) {
        return;
    }

    backendProcess.kill();
    backendProcess = null;
}

app.whenReady().then(async () => {
    startBackendServer();
    await waitForBackendReady();
    createWindow();

    app.on("activate", () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});

app.on("window-all-closed", () => {
    stopBackendServer();
    if (process.platform !== "darwin") {
        app.quit();
    }
});

app.on("before-quit", () => {
    stopBackendServer();
});

ipcMain.handle("select-folder", async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
        properties: ["openDirectory"],
    });

    if (!result.canceled && result.filePaths.length > 0) {
        return result.filePaths[0];
    }

    return null;
});
