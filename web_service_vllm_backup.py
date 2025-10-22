#!/usr/bin/env python3
"""
DeepSeek-OCR Web Service
基于FastAPI和vLLM的OCR Web服务
"""
import asyncio
import os
import re
import base64
import io
import tempfile
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Header, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from PIL import Image, ImageOps
import uvicorn

# 设置环境变量
os.environ['VLLM_USE_V1'] = '0'
os.environ["CUDA_VISIBLE_DEVICES"] = '0'

# 延迟导入vLLM相关模块
vllm_loaded = False

app = FastAPI(
    title="DeepSeek-OCR API",
    description="光学字符识别Web服务（开放访问）",
    version="1.0.0"
)

# 添加CORS支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 移除了API Key验证 - 服务现在开放访问

# 全局变量
engine = None
MODEL_PATH = 'deepseek-ai/DeepSeek-OCR'
BASE_SIZE = 1024
IMAGE_SIZE = 640
CROP_MODE = True

# vLLM相关类的全局引用
AsyncLLMEngine = None
SamplingParams = None
AsyncEngineArgs = None
DeepseekOCRProcessor = None
NoRepeatNGramLogitsProcessor = None

def load_vllm_engine():
    """延迟加载vLLM引擎"""
    global engine, vllm_loaded, AsyncLLMEngine, SamplingParams, AsyncEngineArgs
    global DeepseekOCRProcessor, NoRepeatNGramLogitsProcessor
    
    if vllm_loaded:
        return
    
    try:
        from vllm import AsyncLLMEngine as _AsyncLLMEngine
        from vllm import SamplingParams as _SamplingParams
        from vllm.engine.arg_utils import AsyncEngineArgs as _AsyncEngineArgs
        from vllm.model_executor.models.registry import ModelRegistry
        import sys
        sys.path.insert(0, str(Path(__file__).parent / "DeepSeek-OCR-master/DeepSeek-OCR-vllm"))
        from deepseek_ocr import DeepseekOCRForCausalLM
        from process.image_process import DeepseekOCRProcessor as _DeepseekOCRProcessor
        from process.ngram_norepeat import NoRepeatNGramLogitsProcessor as _NoRepeatNGramLogitsProcessor
        
        # 赋值给全局变量
        AsyncLLMEngine = _AsyncLLMEngine
        SamplingParams = _SamplingParams
        AsyncEngineArgs = _AsyncEngineArgs
        DeepseekOCRProcessor = _DeepseekOCRProcessor
        NoRepeatNGramLogitsProcessor = _NoRepeatNGramLogitsProcessor
        
        # 注册模型
        ModelRegistry.register_model("DeepseekOCRForCausalLM", DeepseekOCRForCausalLM)
        
        vllm_loaded = True
        print("✓ vLLM引擎模块加载成功")
        
    except Exception as e:
        print(f"✗ vLLM引擎加载失败: {e}")
        raise


def load_image(image_data):
    """加载并处理图像"""
    try:
        image = Image.open(io.BytesIO(image_data))
        corrected_image = ImageOps.exif_transpose(image)
        return corrected_image.convert('RGB')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"图像加载失败: {str(e)}")


async def process_ocr(image: Image.Image, prompt: str) -> str:
    """执行OCR处理"""
    global engine
    
    # 如果引擎还未初始化，先初始化
    if engine is None:
        load_vllm_engine()
        engine_args = AsyncEngineArgs(
            model=MODEL_PATH,
            hf_overrides={"architectures": ["DeepseekOCRForCausalLM"]},
            block_size=256,
            max_model_len=8192,
            enforce_eager=False,
            trust_remote_code=True,
            tensor_parallel_size=1,
            gpu_memory_utilization=0.6,
        )
        engine = AsyncLLMEngine.from_engine_args(engine_args)
        print("✓ vLLM引擎初始化成功")
    
    # 处理图像
    if '<image>' in prompt:
        image_features = DeepseekOCRProcessor().tokenize_with_images(
            images=[image], 
            bos=True, 
            eos=True, 
            cropping=CROP_MODE
        )
    else:
        image_features = ''
    
    # 设置采样参数
    logits_processors = [NoRepeatNGramLogitsProcessor(
        ngram_size=30, 
        window_size=90, 
        whitelist_token_ids={128821, 128822}
    )]
    
    sampling_params = SamplingParams(
        temperature=0.0,
        max_tokens=8192,
        logits_processors=logits_processors,
        skip_special_tokens=False,
    )
    
    # 生成请求
    import time
    request_id = f"request-{int(time.time())}-{id(image)}"
    
    if image_features and '<image>' in prompt:
        request = {
            "prompt": prompt,
            "multi_modal_data": {"image": image_features}
        }
    else:
        request = {"prompt": prompt}
    
    # 执行推理
    result_text = ""
    async for request_output in engine.generate(request, sampling_params, request_id):
        if request_output.outputs:
            result_text = request_output.outputs[0].text
    
    return result_text


@app.get("/", response_class=HTMLResponse)
async def root():
    """返回现代化OCR Web界面"""
    # 读取优化后的UI界面文件
    ui_file_path = Path(__file__).parent / "ocr_ui_modern.html"
    
    if ui_file_path.exists():
        with open(ui_file_path, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read())
    
    # 如果文件不存在，返回备用HTML
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>DeepSeek-OCR Web服务</title>
        <meta charset="utf-8">
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                background-color: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
                text-align: center;
            }
            .upload-form {
                margin-top: 30px;
            }
            label {
                display: block;
                margin-bottom: 5px;
                font-weight: bold;
                color: #555;
            }
            input[type="file"], select {
                width: 100%;
                padding: 10px;
                margin-bottom: 20px;
                border: 1px solid #ddd;
                border-radius: 5px;
            }
            button {
                width: 100%;
                padding: 12px;
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-size: 16px;
            }
            button:hover {
                background-color: #45a049;
            }
            #result {
                margin-top: 30px;
                padding: 20px;
                background-color: #f9f9f9;
                border-radius: 5px;
                display: none;
            }
            #result pre {
                white-space: pre-wrap;
                word-wrap: break-word;
            }
            .loading {
                text-align: center;
                display: none;
            }
            .info {
                background-color: #e7f3fe;
                border-left: 4px solid #2196F3;
                padding: 10px;
                margin-bottom: 20px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔍 DeepSeek-OCR 文字识别服务</h1>
            
            <div class="info">
                <strong>🌐 服务状态：</strong> 开放访问<br>
                <strong>支持的功能：</strong><br>
                • 文档转Markdown格式<br>
                • 通用图像OCR<br>
                • 图表解析<br>
                • 详细图像描述
            </div>
            
            <form class="upload-form" id="uploadForm">
                <label>选择图片：</label>
                <input type="file" id="imageFile" accept="image/*" required>
                
                <label>识别模式：</label>
                <select id="promptType">
                    <option value="document">文档转Markdown</option>
                    <option value="ocr">通用OCR</option>
                    <option value="free">纯文本OCR（无布局）</option>
                    <option value="figure">图表解析</option>
                    <option value="describe">详细描述图像</option>
                </select>
                
                <button type="submit">开始识别</button>
            </form>
            
            <div class="loading" id="loading">
                <p>⏳ 正在识别中，请稍候...</p>
            </div>
            
            <div id="result">
                <h3>识别结果：</h3>
                <pre id="resultText"></pre>
            </div>
        </div>
        
        <script>
            document.getElementById('uploadForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                
                const fileInput = document.getElementById('imageFile');
                const promptType = document.getElementById('promptType').value;
                const loading = document.getElementById('loading');
                const result = document.getElementById('result');
                
                if (!fileInput.files[0]) {
                    alert('请选择图片文件');
                    return;
                }
                
                const formData = new FormData();
                formData.append('file', fileInput.files[0]);
                formData.append('prompt_type', promptType);
                
                loading.style.display = 'block';
                result.style.display = 'none';
                
                try {
                    const response = await fetch('/ocr', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        document.getElementById('resultText').textContent = data.text;
                        result.style.display = 'block';
                    } else {
                        alert('识别失败: ' + data.error);
                    }
                } catch (error) {
                    alert('请求失败: ' + error.message);
                } finally {
                    loading.style.display = 'none';
                }
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.post("/ocr")
async def ocr_endpoint(
    file: UploadFile = File(...),
    prompt_type: str = Form("document"),
    find_term: str = Form(""),
    custom_prompt: str = Form(""),
    grounding: bool = Form(False)
):
    """OCR识别接口 - 增强版支持Find和Freeform"""
    
    # 根据prompt类型选择提示词
    prompt_templates = {
        "document": "<image>\n<|grounding|>Convert the document to markdown.",
        "ocr": "<image>\n<|grounding|>OCR this image.",
        "free": "<image>\nFree OCR.",
        "figure": "<image>\nParse the figure.",
        "describe": "<image>\nDescribe this image in detail.",
        "find": "<image>\n<|grounding|>Locate <|ref|>{term}<|/ref|> in the image.",
        "freeform": "<image>\n{prompt}",
    }
    
    # 构建最终prompt
    if prompt_type == "find" and find_term:
        prompt = prompt_templates["find"].replace("{term}", find_term.strip() or "Total")
    elif prompt_type == "freeform" and custom_prompt:
        prompt = prompt_templates["freeform"].replace("{prompt}", custom_prompt.strip() or "OCR this image.")
    else:
        prompt = prompt_templates.get(prompt_type, prompt_templates["document"])
    
    # 如果手动开启grounding或模式需要grounding
    if grounding or prompt_type in ["find", "document", "ocr"]:
        if "<|grounding|>" not in prompt:
            prompt = prompt.replace("<image>", "<image>\n<|grounding|>")
    
    try:
        # 读取上传的图片
        image_data = await file.read()
        image = load_image(image_data)
        
        # 获取图片原始尺寸
        orig_w, orig_h = image.size
        
        # 执行OCR
        result_text = await process_ocr(image, prompt)
        
        # 解析grounding boxes
        boxes = []
        if "<|det|>" in result_text or "<|ref|>" in result_text:
            boxes = parse_detections(result_text, orig_w, orig_h)
        
        # 清理显示文本（移除grounding标记）
        display_text = clean_grounding_text(result_text)
        
        # 如果显示文本为空但有boxes，显示标签
        if not display_text and boxes:
            display_text = ", ".join([b["label"] for b in boxes])
        
        return JSONResponse({
            "success": True,
            "text": display_text,
            "raw_text": result_text,
            "boxes": boxes,
            "image_dims": {"w": orig_w, "h": orig_h},
            "prompt_type": prompt_type,
            "metadata": {
                "mode": prompt_type,
                "grounding": grounding or (prompt_type in ["find", "document", "ocr"]),
                "has_boxes": len(boxes) > 0
            }
        })
        
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


def clean_grounding_text(text: str) -> str:
    """移除grounding标记，保留标签"""
    cleaned = re.sub(
        r"<\|ref\|>(.*?)<\|/ref\|>\s*<\|det\|>\s*\[.*\]\s*<\|/det\|>",
        r"\1",
        text,
        flags=re.DOTALL,
    )
    cleaned = re.sub(r"<\|grounding\|>", "", cleaned)
    return cleaned.strip()


def parse_detections(text: str, image_width: int, image_height: int):
    """解析grounding boxes并缩放坐标"""
    boxes = []
    
    # 匹配detection块
    DET_BLOCK = re.compile(
        r"<\|ref\|>(?P<label>.*?)<\|/ref\|>\s*<\|det\|>\s*(?P<coords>\[.*?\])\s*<\|/det\|>",
        re.DOTALL,
    )
    
    for m in DET_BLOCK.finditer(text or ""):
        label = m.group("label").strip()
        coords_str = m.group("coords").strip()
        
        try:
            import ast
            parsed = ast.literal_eval(coords_str)
            
            # 标准化为列表的列表
            if isinstance(parsed, list) and len(parsed) == 4 and all(isinstance(n, (int, float)) for n in parsed):
                box_coords = [parsed]
            elif isinstance(parsed, list):
                box_coords = parsed
            else:
                continue
            
            # 处理每个box
            for box in box_coords:
                if isinstance(box, (list, tuple)) and len(box) >= 4:
                    # 从0-999归一化坐标转换为实际像素坐标
                    x1 = int(float(box[0]) / 999 * image_width)
                    y1 = int(float(box[1]) / 999 * image_height)
                    x2 = int(float(box[2]) / 999 * image_width)
                    y2 = int(float(box[3]) / 999 * image_height)
                    boxes.append({"label": label, "box": [x1, y1, x2, y2]})
        except Exception as e:
            print(f"解析坐标失败: {e}")
            continue
    
    return boxes


@app.get("/health")
async def health_check():
    """健康检查接口（无需认证）"""
    return {
        "status": "healthy",
        "model": MODEL_PATH,
        "engine_loaded": engine is not None,
        "authentication": "disabled"
    }


if __name__ == "__main__":
    import sys
    
    # 可以通过命令行参数指定端口
    port = 8001
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except:
            port = 8001
    
    print("="*50)
    print("DeepSeek-OCR Web服务启动中...")
    print("="*50)
    
    # 预加载vLLM模块（但不初始化引擎）
    try:
        load_vllm_engine()
        print("✓ 模块加载完成")
    except Exception as e:
        print(f"✗ 模块加载失败: {e}")
        print("提示: 引擎将在首次请求时初始化")
    
    print("\n服务信息:")
    print(f"- 访问地址: http://0.0.0.0:{port}")
    print(f"- API文档: http://0.0.0.0:{port}/docs")
    print(f"- 健康检查: http://0.0.0.0:{port}/health")
    print("="*50)
    
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
