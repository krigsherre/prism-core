#!/bin/bash
set -euo pipefail

echo "Starting Tailscale..."
sudo tailscaled --tun=userspace-networking > tailscaled.log 2>&1 &
sleep 3
sudo tailscale up
echo "Tailscale IP: $(tailscale ip -4)"

echo "Cleaning up old background processes..."
pkill -f vllm || true
sleep 2

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Starting Docling Layout Heron (port 8002)"
pip install -q fastapi uvicorn transformers torch Pillow pydantic structlog
nohup python3 "${SCRIPT_DIR}/layout_heron_server.py" > heron_8002.log 2>&1 &

echo "Starting PaddleOCR-VL (port 8003)"
nohup vllm serve PaddlePaddle/PaddleOCR-VL-1.6 \
    --port 8003 --max-model-len 4096 --gpu-memory-utilization 0.55 --enforce-eager --trust-remote-code \
    > vllm_8003.log 2>&1 &

echo "Starting SmolDocling (port 8004)"
nohup vllm serve docling-project/SmolDocling-256M-preview \
    --port 8004 --max-model-len 4096 --gpu-memory-utilization 0.25 --enforce-eager --trust-remote-code \
    > vllm_8004.log 2>&1 &

echo "APIs booting in background. Update .env with the Tailscale IP above."
