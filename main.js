const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

let mainWindow;
let pythonProcess;

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1560,
        height: 960,
        minWidth: 1200,
        minHeight: 760,
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false
        },
        backgroundColor: '#f4efe7',
        icon: path.join(__dirname, 'assets/icon.png')
    });

    mainWindow.setMenuBarVisibility(false);
    mainWindow.loadFile('index.html');
    
    mainWindow.on('closed', function () {
        mainWindow = null;
    });
}

function startPythonServer() {
    const pythonPath = process.platform === 'win32' ? 'python' : 'python3';
    pythonProcess = spawn(pythonPath, [path.join(__dirname, 'backend', 'server.py')]);
    
    pythonProcess.stdout.on('data', (data) => {
        console.log(`Python: ${data}`);
    });
    
    pythonProcess.stderr.on('data', (data) => {
        console.error(`Python Error: ${data}`);
    });
}

app.on('ready', () => {
    startPythonServer();
    setTimeout(createWindow, 2000);
});

app.on('window-all-closed', function () {
    if (pythonProcess) {
        pythonProcess.kill();
    }
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('activate', function () {
    if (mainWindow === null) {
        createWindow();
    }
});

ipcMain.handle('select-folder', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
        properties: ['openDirectory']
    });
    
    if (!result.canceled && result.filePaths.length > 0) {
        return result.filePaths[0];
    }
    return null;
});
