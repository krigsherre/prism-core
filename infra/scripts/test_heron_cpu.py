from transformers import AutoImageProcessor, AutoModelForObjectDetection
import torch
from PIL import Image

model_id = "docling-project/docling-layout-heron"
device = "cpu"
processor = AutoImageProcessor.from_pretrained(model_id)
model = AutoModelForObjectDetection.from_pretrained(model_id).to(device)
print("loaded")
img = Image.new("RGB", (800, 600), color="white")
inputs = processor(images=img, return_tensors="pt").to(device)

with torch.no_grad():
    outputs = model(**inputs)

target_sizes = [(img.height, img.width)]
processor.post_process_object_detection(outputs, target_sizes=target_sizes, threshold=0.3)
print("Success on CPU!")
