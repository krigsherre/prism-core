import os
import base64
import io
import torch
import uvicorn
import structlog
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForObjectDetection

logger = structlog.get_logger(__name__)

app = FastAPI(title="Docling Layout Heron Server")

processor = None
model = None
if torch.cuda.is_available():
    device = "cuda"
# Force CPU on Apple Silicon because Hugging Face RT-DETR v2 
# hardcodes torch.float64 tensors during forward pass, which crashes MPS.
# (CPU inference for this tiny model is still extremely fast on M1 Max).
else:
    device = "cpu"
id2label = {}

class ImageRequest(BaseModel):
    image_base64: str
    threshold: float = 0.3

class BBoxResult(BaseModel):
    label: str
    score: float
    bbox: List[float]

@app.on_event("startup")
def load_model():
    global processor, model, id2label
    model_id = "docling-project/docling-layout-heron"
    logger.info("Loading IBM Docling Layout Heron (RT-DETR v2) model...", device=device)
    try:
        processor = AutoImageProcessor.from_pretrained(model_id)
        model = AutoModelForObjectDetection.from_pretrained(model_id).to(device)
        id2label = getattr(model.config, "id2label", {})
        logger.info("Docling Layout Heron model loaded successfully.")
    except Exception as e:
        logger.error(f"Failed to load Docling Layout model: {e}")
        raise RuntimeError("Model failed to load.")

@app.post("/layout", response_model=List[BBoxResult])
def extract_layout(req: ImageRequest):
    if model is None or processor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        image_data = base64.b64decode(req.image_base64)
        img = Image.open(io.BytesIO(image_data))
        if img.mode != "RGB":
            img = img.convert("RGB")

        inputs = processor(images=img, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model(**inputs)

        # Move outputs to CPU to avoid Apple Silicon (MPS) float64 limitations
        # during object detection post-processing
        if hasattr(outputs, "to"):
            outputs = outputs.to("cpu")

        target_sizes = [(img.height, img.width)]
        results = processor.post_process_object_detection(
            outputs, target_sizes=target_sizes, threshold=req.threshold
        )[0]

        boxes_out = []
        for score, label_id, box in zip(results["scores"], results["labels"], results["boxes"]):
            label_name = id2label.get(int(label_id.item()), "text").lower()
            boxes_out.append(
                BBoxResult(
                    label=label_name,
                    score=float(score.item()),
                    bbox=box.tolist()
                )
            )

        return boxes_out

    except Exception as e:
        logger.error(f"Inference error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("layout_heron_server:app", host="0.0.0.0", port=8002)
