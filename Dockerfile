# DeepSeek-OCR-WebUI Dockerfile
# 基于 NVIDIA PyTorch 镜像，支持 GPU 加速
# 使用最新镜像，采用 transformers 引擎（更稳定）

FROM nvcr.io/nvidia/pytorch:25.09-py3

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    VLLM_USE_V1=0 \
    CUDA_VISIBLE_DEVICES=0 \
    LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH \
    CUDA_HOME=/usr/local/cuda

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .
COPY DeepSeek-OCR-master ./DeepSeek-OCR-master

# 安装 Python 依赖
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# 安装 FastAPI 和其他 Web 依赖（替代 vLLM）
RUN pip install \
    fastapi==0.119.1 \
    uvicorn[standard]==0.38.0 \
    python-multipart==0.0.20 \
    python-decouple==3.8

# 复制应用代码
COPY web_service.py .
COPY ocr_ui_modern.html .

# 暴露端口
EXPOSE 8001

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5m --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# 启动服务
CMD ["python", "web_service.py", "8001"]
