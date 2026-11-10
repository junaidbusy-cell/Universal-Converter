#!/usr/bin/env bash
# ==============================================================================
# UNIVERSAL DOCUMENT PROCESSOR - OCR ENGINE INSTALLATION SCRIPT
# ==============================================================================
# Usage:
#   bash install_ocr.sh          # Auto-detects GPU or CPU
#   bash install_ocr.sh --cpu    # Forces CPU version
#   bash install_ocr.sh --gpu    # Forces GPU (CUDA) version
#   bash install_ocr.sh --tess   # Installs Tesseract fallback
# ==============================================================================

set -e

# Styling
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}====================================================================${NC}"
echo -e "${BLUE}        UNIVERSAL DOCUMENT PROCESSOR — OCR SETUP INSTALLER          ${NC}"
echo -e "${BLUE}====================================================================${NC}"

# 1. Determine Python command
# Check active virtualenv first (Linux/macOS bin/python or Windows Scripts/python.exe)
PY_CMD=""
if [ -n "$VIRTUAL_ENV" ]; then
    if [ -x "$VIRTUAL_ENV/bin/python" ]; then
        PY_CMD="$VIRTUAL_ENV/bin/python"
    elif [ -x "$VIRTUAL_ENV/Scripts/python.exe" ]; then
        PY_CMD="$VIRTUAL_ENV/Scripts/python.exe"
    elif [ -f "$VIRTUAL_ENV/Scripts/python.exe" ]; then
        PY_CMD="$VIRTUAL_ENV/Scripts/python.exe"
    elif command -v python &>/dev/null; then
        PY_CMD="python"
    fi
elif [ -d ".venv" ]; then
    if [ -x ".venv/bin/python" ]; then
        PY_CMD=".venv/bin/python"
    elif [ -x ".venv/Scripts/python.exe" ]; then
        PY_CMD=".venv/Scripts/python.exe"
    elif [ -f ".venv/Scripts/python.exe" ]; then
        PY_CMD=".venv/Scripts/python.exe"
    fi
fi

if [ -z "$PY_CMD" ]; then
    if command -v python3 &>/dev/null; then
        PY_CMD="python3"
    elif command -v python &>/dev/null; then
        PY_CMD="python"
    else
        echo -e "${RED}[ERROR] Python was not found on your system PATH.${NC}"
        exit 1
    fi
fi

PY_VER=$($PY_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PY_CMD -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PY_CMD -c "import sys; print(sys.version_info.minor)")
echo -e "${GREEN}[*] Using Python: $PY_CMD (version $PY_VER)${NC}"

# 2. Check execution mode (Auto-detect, Force CPU, or Force GPU)
MODE="auto"
INSTALL_TESS=false

for arg in "$@"; do
    case "$arg" in
        --cpu)
            MODE="cpu"
            ;;
        --gpu)
            MODE="gpu"
            ;;
        --tess|--tesseract)
            INSTALL_TESS=true
            ;;
        -h|--help)
            echo "Usage: bash install_ocr.sh [--cpu | --gpu | --tess]"
            exit 0
            ;;
    esac
done

# Architecture & Hardware Compatibility Analysis
CUDA_INDEX="cu118"
GPU_AVAILABLE=false
GPU_NAME=""
GPU_CAP=""
GPU_DRIVER=""

echo -e "\n${YELLOW}[*] Detecting system hardware and GPU accelerator...${NC}"
if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
    GPU_INFO=$(nvidia-smi --query-gpu=name,compute_cap,driver_version --format=csv,noheader 2>/dev/null | head -n 1)
    if [ -n "$GPU_INFO" ]; then
        GPU_AVAILABLE=true
        GPU_NAME=$(echo "$GPU_INFO" | cut -d',' -f1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        GPU_CAP=$(echo "$GPU_INFO" | cut -d',' -f2 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        GPU_DRIVER=$(echo "$GPU_INFO" | cut -d',' -f3 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    fi
fi

if [ "$GPU_AVAILABLE" = true ]; then
    echo -e "${GREEN}[+] Detected NVIDIA GPU: ${GPU_NAME}${NC}"
    echo -e "    Driver Version: ${GPU_DRIVER} | Compute Capability: ${GPU_CAP}"

    EVAL_RESULT=$($PY_CMD -c "
import sys
try:
    cap_val = float('$GPU_CAP')
    py_maj = int('$PY_MAJOR')
    py_min = int('$PY_MINOR')

    # Python Version Compatibility
    if py_maj != 3 or py_min < 8 or py_min > 12:
        print(f'INCOMPATIBLE_PY|PaddlePaddle GPU wheels require Python 3.8–3.12 (current Python is {py_maj}.{py_min}).')
        sys.exit(0)

    # Microarchitecture Compatibility
    if cap_val >= 10.0:
        # Blackwell (RTX 50xx, B100, B200) - sm_100/sm_120
        print(f'INCOMPATIBLE_ARCH|NVIDIA Blackwell architecture ({cap_val} - RTX 50xx series) requires native sm_120 wheels (currently in active development by PaddlePaddle).')
    elif cap_val >= 8.9:
        # Ada Lovelace (RTX 40xx) & Hopper (H100) - sm_89/sm_90
        print(f'COMPATIBLE|cu126|Ada Lovelace / Hopper ({cap_val} - RTX 40xx / H100) fully supported with CUDA 12.6.')
    elif cap_val >= 7.0:
        # Turing (RTX 20xx) & Ampere (RTX 30xx, A100) - sm_75/sm_80/sm_86
        print(f'COMPATIBLE|cu118|Turing / Ampere ({cap_val} - RTX 20xx / 30xx / A100) fully supported with CUDA 11.8/12.6.')
    elif cap_val >= 6.0:
        # Pascal (GTX 10xx, P100) - sm_60/sm_61
        print(f'COMPATIBLE|cu118|Pascal ({cap_val} - GTX 10xx / P100) supported with CUDA 11.8.')
    else:
        print(f'INCOMPATIBLE_ARCH|Legacy GPU compute capability {cap_val} is older than supported CUDA minimums.')
except Exception as e:
    print(f'ERROR|{e}')
")

    STATUS=$(echo "$EVAL_RESULT" | cut -d'|' -f1)

    if [ "$STATUS" = "COMPATIBLE" ]; then
        CUDA_INDEX=$(echo "$EVAL_RESULT" | cut -d'|' -f2)
        ARCH_MSG=$(echo "$EVAL_RESULT" | cut -d'|' -f3)
        echo -e "${GREEN}[+] Architecture match: ${ARCH_MSG}${NC}"
        if [ "$MODE" = "auto" ]; then
            MODE="gpu"
        fi
    elif [ "$STATUS" = "INCOMPATIBLE_PY" ]; then
        REASON=$(echo "$EVAL_RESULT" | cut -d'|' -f2)
        echo -e "${YELLOW}[!] Python compatibility notice: ${REASON}${NC}"
        echo -e "${YELLOW}[*] TIP: Create a Python 3.11 or 3.12 environment to use supported GPU acceleration.${NC}"
        if [ "$MODE" = "auto" ] || [ "$MODE" = "gpu" ]; then
            echo -e "${YELLOW}[*] Automatically switching to PaddlePaddle CPU runtime (fully functional).${NC}"
            MODE="cpu"
        fi
    elif [ "$STATUS" = "INCOMPATIBLE_ARCH" ]; then
        REASON=$(echo "$EVAL_RESULT" | cut -d'|' -f2)
        echo -e "${YELLOW}[!] GPU generation notice: ${REASON}${NC}"
        echo -e "${YELLOW}[*] Pre-compiled wheels do not yet contain sm_120 machine code.${NC}"
        if [ "$MODE" = "auto" ] || [ "$MODE" = "gpu" ]; then
            echo -e "${YELLOW}[*] Automatically configuring high-performance CPU runtime.${NC}"
            MODE="cpu"
        fi
    fi
else
    echo -e "${YELLOW}[!] No active NVIDIA GPU driver detected. Configuring CPU installation...${NC}"
    if [ "$MODE" = "auto" ]; then
        MODE="cpu"
    fi
fi

# 3. Upgrade pip and setuptools
echo -e "\n${BLUE}[*] Step 1: Upgrading pip, setuptools, and wheel...${NC}"
$PY_CMD -m pip install --upgrade pip setuptools wheel

# 4. Install PaddlePaddle Runtime
if [ "$MODE" = "gpu" ]; then
    echo -e "\n${BLUE}[*] Step 2: Installing PaddlePaddle GPU runtime (${CUDA_INDEX} CUDA support)...${NC}"
    set +e
    if [ "$CUDA_INDEX" = "cu126" ]; then
        $PY_CMD -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu126/ || \
        $PY_CMD -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu118/ || \
        $PY_CMD -m pip install paddlepaddle-gpu
    else
        $PY_CMD -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu118/ || \
        $PY_CMD -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu126/ || \
        $PY_CMD -m pip install paddlepaddle-gpu
    fi
    GPU_INSTALL_STATUS=$?
    set -e
    if [ $GPU_INSTALL_STATUS -ne 0 ]; then
        echo -e "${YELLOW}[!] PaddlePaddle GPU runtime could not be installed from mirror/PyPI.${NC}"
        echo -e "${YELLOW}[*] Falling back to PaddlePaddle CPU runtime (standard PyPI)...${NC}"
        $PY_CMD -m pip install "paddlepaddle>=3.0.0"
    fi
else
    echo -e "\n${BLUE}[*] Step 2: Installing PaddlePaddle CPU runtime (PyPI)...${NC}"
    $PY_CMD -m pip install "paddlepaddle>=3.0.0"
fi

# 5. Install PaddleOCR, PaddleX & aligned dependency bounds
echo -e "\n${BLUE}[*] Step 3: Installing PaddleOCR, PaddleX & aligned dependencies...${NC}"
$PY_CMD -m pip install --upgrade \
    "numpy>=1.24.0,<2.4.0" \
    "Pillow>=12.2.0" \
    "typing-extensions>=4.16.0" \
    "idna>=3.18" \
    "paddleocr>=3.0.0" \
    "paddlex>=3.0.0"

# Optional Tesseract installation
if [ "$INSTALL_TESS" = true ]; then
    echo -e "\n${BLUE}[*] Step 3b: Installing Tesseract OCR Python wrapper...${NC}"
    $PY_CMD -m pip install pytesseract
    echo -e "${YELLOW}[!] Note: Ensure system 'tesseract' binary is installed:${NC}"
    echo -e "    Ubuntu/Debian: sudo apt-get install -y tesseract-ocr"
    echo -e "    macOS: brew install tesseract"
    echo -e "    Windows: winget install UB-Mannheim.TesseractOCR"
fi

# 6. Verification Check
echo -e "\n${BLUE}[*] Step 4: Verifying OCR Engine installation...${NC}"
$PY_CMD -c "
import sys, os, warnings
warnings.filterwarnings('ignore', category=UserWarning)

devnull = os.open(os.devnull, os.O_WRONLY)
old_stdout = os.dup(1)
old_stderr = os.dup(2)
try:
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    import paddle
    import paddleocr
finally:
    os.dup2(old_stdout, 1)
    os.dup2(old_stderr, 2)
    os.close(old_stdout)
    os.close(old_stderr)
    os.close(devnull)

try:
    dev = 'GPU' if (paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0) else 'CPU'
    print(f'\033[0;32m[SUCCESS] PaddlePaddle {paddle.__version__} initialized successfully!\033[0m')
    print(f'\033[0;32m[SUCCESS] PaddleOCR {paddleocr.__version__} is ready to use (Active Device: {dev}).\033[0m')
except Exception as e:
    print(f'\033[0;31m[WARNING] Verification check notice: {e}\033[0m')
"

echo -e "\n${GREEN}====================================================================${NC}"
echo -e "${GREEN}  OCR Engine Setup Complete! You can now run OCR on PDFs and Images.  ${NC}"
echo -e "${GREEN}====================================================================${NC}\n"
