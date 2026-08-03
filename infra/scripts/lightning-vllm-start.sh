#!/bin/bash
set -euo pipefail

echo "Checking Tailscale..."
if ! command -v tailscale &> /dev/null; then
    echo "Tailscale not found. Installing..."
    curl -fsSL https://tailscale.com/install.sh | sh
fi

echo "Starting Tailscale..."
sudo tailscaled --tun=userspace-networking > tailscaled.log 2>&1 &
sleep 3
sudo tailscale up
echo "Tailscale IP: $(tailscale ip -4)"

echo "Cleaning up old background processes..."
pkill -f vllm || true
pkill -f layout_heron_server || true
sleep 2

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing dependencies..."
pip install -q fastapi uvicorn transformers torch Pillow pydantic structlog vllm

echo "Starting Docling Layout Heron (port 8002)"
nohup python3 "${SCRIPT_DIR}/layout_heron_server.py" > heron_8002.log 2>&1 &

echo "Starting PaddleOCR-VL (port 8003) via Official vLLM Docker Container..."
nohup docker run --rm --gpus all --network host \
    ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-genai-vllm-server:latest-nvidia-gpu \
    paddleocr genai_server --model_name PaddleOCR-VL-1.6-0.9B --host 0.0.0.0 --port 8003 --backend vllm \
    > paddleocr_docker_8003.log 2>&1 &

echo "Starting SmolDocling (port 8004) via vLLM..."
nohup vllm serve docling-project/SmolDocling-256M-preview \
    --host 0.0.0.0 --port 8004 --max-model-len 4096 --max-num-seqs 16 --gpu-memory-utilization 0.40 --enforce-eager --trust-remote-code \
    > vllm_8004.log 2>&1 &

echo "APIs booting in background. Update your local .env with the Tailscale IP above."
