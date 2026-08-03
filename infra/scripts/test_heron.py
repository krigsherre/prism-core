from transformers import AutoImageProcessor, AutoModelForObjectDetection
import torch
from PIL import Image
import io
import os

model_id = "docling-project/docling-layout-heron"
device = "mps"
processor = AutoImageProcessor.from_pretrained(model_id)
model = AutoModelForObjectDetection.from_pretrained(model_id).to(device)

img = Image.new("RGB", (800, 600), color="white")
inputs = processor(images=img, return_tensors="pt").to(device)

with torch.no_grad():
    outputs = model(**inputs)

target_sizes = [(img.height, img.width)]
try:
    processor.post_process_object_detection(outputs, target_sizes=target_sizes, threshold=0.3)
    print("Success without cast!")
except Exception as e:
    print(f"Failed without cast: {e}")

outputs.logits = outputs.logits.cpu()
outputs.pred_boxes = outputs.pred_boxes.cpu()

try:
    processor.post_process_object_detection(outputs, target_sizes=target_sizes, threshold=0.3)
    print("Success with explicit cast!")
except Exception as e:
    print(f"Failed with explicit cast: {e}")
