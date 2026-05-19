#!/bin/bash
set -e
echo "============================================"
echo "  pyvideotrans-studio — Linux 7.0.8-cachyos-x64v3 / AMD Radeon RX 6600 XT"
echo "============================================"
echo ""
echo "  [1/3] 安装 PyTorch (ROCM)"
"/home/deepin/.hermes/hermes-agent/venv/bin/python" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/rocm7.2 || (
  echo "  回退 CPU 版..."
  "/home/deepin/.hermes/hermes-agent/venv/bin/python" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
)
echo ""
echo ""
echo "  ✅ 依赖安装完成！"
echo "  日常运行: python sv.py"
echo "  遇到问题: python main.py"
