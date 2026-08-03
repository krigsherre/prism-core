from transformers.utils import ModelOutput
import torch

class MyOutput(ModelOutput):
    logits: torch.Tensor
    pred_boxes: torch.Tensor

out = MyOutput(logits=torch.tensor([1.0]), pred_boxes=torch.tensor([2.0]))
out = out.to("cpu")
print("success")
