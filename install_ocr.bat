@echo off
REM ==============================================================================
REM UNIVERSAL DOCUMENT PROCESSOR - OCR ENGINE INSTALLATION SCRIPT (WINDOWS BATCH)
REM ==============================================================================

setlocal enabledelayedexpansion

echo ====================================================================
echo        UNIVERSAL DOCUMENT PROCESSOR - OCR SETUP (WINDOWS)
echo ====================================================================

REM 1. Locate Python
set "PY_CMD="
if defined VIRTUAL_ENV (
    if exist "%VIRTUAL_ENV%\Scripts\python.exe" (
        set "PY_CMD=%VIRTUAL_ENV%\Scripts\python.exe"
    )
)

if not defined PY_CMD (
    if exist ".venv\Scripts\python.exe" (
        set "PY_CMD=.venv\Scripts\python.exe"
    )
)

if not defined PY_CMD (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set "PY_CMD=python"
    )
)

if not defined PY_CMD (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        set "PY_CMD=py"
    )
)

if not defined PY_CMD (
    echo [ERROR] Python was not found on your system PATH.
    echo Please install Python 3.10+ from https://www.python.org/ or ensure it is added to your PATH.
    exit /b 1
)

echo [*] Using Python: %PY_CMD%

REM Extract Python version
for /f "tokens=1,2 delims=." %%a in ('"%PY_CMD%" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)

REM 2. Determine GPU or CPU
set "MODE=auto"
if "%~1"=="--gpu" (
    set "MODE=gpu"
) else if "%~1"=="--cpu" (
    set "MODE=cpu"
)

REM Query GPU and Architecture
set "CUDA_INDEX=cu118"
set "GPU_STATUS=NONE"

echo.
echo [*] Detecting system hardware and GPU accelerator...

where nvidia-smi >nul 2>nul
if %errorlevel% equ 0 (
    for /f "tokens=1,2,3 delims=," %%x in ('nvidia-smi --query-gpu^=name^,compute_cap^,driver_version --format^=csv^,noheader 2^>nul') do (
        set "GPU_NAME=%%x"
        set "GPU_CAP=%%y"
        set "GPU_DRIVER=%%z"
    )
    if defined GPU_NAME (
        echo [+] Detected NVIDIA GPU: !GPU_NAME!
        echo     Driver Version: !GPU_DRIVER! ^| Compute Capability: !GPU_CAP!

        REM Comprehensive hardware and Python evaluation
        for /f "tokens=1,2,3 delims=|" %%i in ('"%PY_CMD%" -c "import sys; cap=float('!GPU_CAP!'.strip()) if '!GPU_CAP!'.strip() else 0.0; maj=int('!PY_MAJOR!'); min=int('!PY_MINOR!'); sys.stdout.write('INCOMPATIBLE_PY|PaddlePaddle GPU wheels require Python 3.8-3.12 (current is ' + str(maj) + '.' + str(min) + ')\n' if (maj!=3 or min<8 or min>12) else ('INCOMPATIBLE_ARCH|NVIDIA Blackwell architecture (' + str(cap) + ' - RTX 50xx series) requires native sm_120 wheels (currently in active development by PaddlePaddle)\n' if cap>=10.0 else ('COMPATIBLE|cu126|Ada Lovelace / Hopper (' + str(cap) + ' - RTX 40xx / H100) fully supported with CUDA 12.6\n' if cap>=8.9 else ('COMPATIBLE|cu118|Turing / Ampere (' + str(cap) + ' - RTX 20xx / 30xx / A100) fully supported with CUDA 11.8/12.6\n' if cap>=7.0 else ('COMPATIBLE|cu118|Pascal (' + str(cap) + ' - GTX 10xx / P100) supported with CUDA 11.8\n' if cap>=6.0 else 'INCOMPATIBLE_ARCH|Legacy GPU is older than supported CUDA minimums\n')))))"') do (
            set "EVAL_STATUS=%%i"
            set "EVAL_OPT=%%j"
            set "EVAL_MSG=%%k"
        )

        if "!EVAL_STATUS!"=="COMPATIBLE" (
            set "CUDA_INDEX=!EVAL_OPT!"
            echo [+] Architecture match: !EVAL_MSG!
            if "!MODE!"=="auto" set "MODE=gpu"
        ) else if "!EVAL_STATUS!"=="INCOMPATIBLE_PY" (
            echo [!] Python compatibility notice: !EVAL_OPT!
            echo [*] TIP: Create a Python 3.11 or 3.12 environment to use supported GPU acceleration.
            echo [*] Automatically switching to PaddlePaddle CPU runtime (fully functional).
            set "MODE=cpu"
        ) else if "!EVAL_STATUS!"=="INCOMPATIBLE_ARCH" (
            echo [!] GPU generation notice: !EVAL_OPT!
            echo [*] Pre-compiled wheels do not yet contain sm_120 machine code.
            echo [*] Automatically configuring high-performance CPU runtime.
            set "MODE=cpu"
        )
    )
) else (
    echo [!] No active NVIDIA GPU driver detected. Configuring CPU installation...
    if "!MODE!"=="auto" set "MODE=cpu"
)

REM 3. Upgrade pip
echo.
echo [*] Step 1: Upgrading pip, setuptools, wheel...
"%PY_CMD%" -m pip install --upgrade pip setuptools wheel

REM 4. Install PaddlePaddle
if "%MODE%"=="gpu" (
    echo.
    echo [*] Step 2: Installing PaddlePaddle GPU runtime (!CUDA_INDEX! CUDA support)...
    if "!CUDA_INDEX!"=="cu126" (
        "%PY_CMD%" -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu126/ || "%PY_CMD%" -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu118/ || "%PY_CMD%" -m pip install paddlepaddle-gpu || (
            echo [!] PaddlePaddle GPU runtime could not be installed from mirror/PyPI.
            echo [*] Falling back to PaddlePaddle CPU runtime (PyPI)...
            "%PY_CMD%" -m pip install "paddlepaddle>=3.0.0"
        )
    ) else (
        "%PY_CMD%" -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu118/ || "%PY_CMD%" -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu126/ || "%PY_CMD%" -m pip install paddlepaddle-gpu || (
            echo [!] PaddlePaddle GPU runtime could not be installed from mirror/PyPI.
            echo [*] Falling back to PaddlePaddle CPU runtime (PyPI)...
            "%PY_CMD%" -m pip install "paddlepaddle>=3.0.0"
        )
    )
) else (
    echo.
    echo [*] Step 2: Installing PaddlePaddle CPU runtime (PyPI)...
    "%PY_CMD%" -m pip install "paddlepaddle>=3.0.0"
)

REM 5. Install PaddleOCR and PaddleX with aligned dependencies
echo.
echo [*] Step 3: Installing PaddleOCR, PaddleX and aligned dependencies...
"%PY_CMD%" -m pip install --upgrade "numpy>=1.24.0,<2.4.0" "Pillow>=12.2.0" "typing-extensions>=4.16.0" "idna>=3.18" "paddleocr>=3.0.0" "paddlex>=3.0.0"

REM 6. Verification
echo.
echo [*] Step 4: Verifying OCR Engine installation...
"%PY_CMD%" -c "import sys, os, warnings; warnings.filterwarnings('ignore'); devnull = os.open(os.devnull, os.O_WRONLY); old_stdout = os.dup(1); old_stderr = os.dup(2); os.dup2(devnull, 1); os.dup2(devnull, 2); import paddle, paddleocr; os.dup2(old_stdout, 1); os.dup2(old_stderr, 2); os.close(old_stdout); os.close(old_stderr); os.close(devnull); dev = 'GPU' if (paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0) else 'CPU'; print(f'[SUCCESS] PaddlePaddle {paddle.__version__} initialized successfully!'); print(f'[SUCCESS] PaddleOCR {paddleocr.__version__} is ready to use (Active Device: {dev}).')"

echo.
echo ====================================================================
echo   OCR Engine Setup Complete! You can now run OCR on PDFs and Images.
echo ====================================================================
