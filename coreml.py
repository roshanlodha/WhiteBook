import torch
import coremltools as ct
import numpy as np
import shutil
from transformers import AutoModel, AutoTokenizer
from pathlib import Path
from typing import Any, cast

# Configuration - Ensure these match your .env setup
MODEL_ID = "Alibaba-NLP/gte-modernbert-base"
OUTPUT_NAME = "WhiteBookEmbedder.mlpackage"
IOS_APP_RESOURCES_DIR = Path("WhiteBook") / "WhiteBook"

class EmbeddingModelWrapper(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, input_ids, attention_mask):
        # Use explicit attention mask mapping to avoid tracing issues in ModernBERT masking utilities.
        attention_mask_mapping = {
            "full_attention": None,
            "sliding_attention": None,
        }
        outputs = self.model(input_ids=input_ids, attention_mask=attention_mask_mapping)
        # Mean-pool token embeddings using the provided attention mask.
        token_embeddings = outputs.last_hidden_state
        expanded_mask = attention_mask.unsqueeze(-1).to(token_embeddings.dtype)
        masked_sum = (token_embeddings * expanded_mask).sum(dim=1)
        token_count = expanded_mask.sum(dim=1).clamp(min=1e-6)
        return masked_sum / token_count


def _best_ios_deployment_target():
    # Prefer the requested iOS26 target when available; otherwise pick the newest iOS target exposed by this coremltools version.
    if hasattr(ct.target, "iOS26"):
        return ct.target.iOS26

    ios_targets = []
    for name in dir(ct.target):
        if name.startswith("iOS") and name[3:].isdigit():
            ios_targets.append((int(name[3:]), getattr(ct.target, name)))

    if not ios_targets:
        raise RuntimeError("No iOS deployment targets available in this coremltools version.")

    ios_targets.sort(key=lambda x: x[0])
    return ios_targets[-1][1]

def convert():
    print(f"Loading {MODEL_ID}...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
    base_model = AutoModel.from_pretrained(
        MODEL_ID,
        trust_remote_code=True,
        attn_implementation="eager",
    )
    base_model.eval()
    base_model.to(dtype=torch.float32)
    
    wrapper = EmbeddingModelWrapper(base_model)
    wrapper.eval()

    # Create dummy inputs for tracing (Max context for medical queries)
    vocab_size = tokenizer.vocab_size or 30000
    dummy_input_ids = torch.randint(0, vocab_size, (1, 512), dtype=torch.long)
    dummy_mask = torch.ones((1, 512), dtype=torch.long)

    print("Exporting model graph (this may take a minute)...")
    with torch.no_grad():
        try:
            exported_model = torch.export.export(wrapper, (dummy_input_ids, dummy_mask))
            exported_model = exported_model.run_decompositions({})
            model_for_coreml = exported_model
            print("Using torch.export graph for conversion.")
        except Exception as export_error:
            print(f"torch.export failed, falling back to torch.jit.trace: {export_error}")
            model_for_coreml = torch.jit.trace(wrapper, (dummy_input_ids, dummy_mask))

    deployment_target = _best_ios_deployment_target()
    print(f"Using CoreML minimum deployment target: {deployment_target}")

    print("Converting to CoreML...")
    mlmodel = cast(Any, ct.convert(
        model_for_coreml,
        inputs=[
            ct.TensorType(name="input_ids", shape=dummy_input_ids.shape, dtype=np.int32),
            ct.TensorType(name="attention_mask", shape=dummy_mask.shape, dtype=np.int32)
        ],
        outputs=[ct.TensorType(name="embeddings", dtype=np.float32)],
        minimum_deployment_target=deployment_target,
        compute_units=ct.ComputeUnit.ALL
    ))

    # Add metadata for Xcode
    mlmodel.author = "WhiteBook Pipeline"
    mlmodel.license = "Proprietary"
    mlmodel.short_description = "Alibaba ModernBERT optimized for medical RAG on-device."

    IOS_APP_RESOURCES_DIR.mkdir(parents=True, exist_ok=True)
    output_path = IOS_APP_RESOURCES_DIR / OUTPUT_NAME
    if output_path.exists():
        shutil.rmtree(output_path)

    print(f"Saving to {output_path}...")
    mlmodel.save(str(output_path))
    print("Done! Add WhiteBookEmbedder.mlpackage to the Xcode target membership if needed.")

if __name__ == "__main__":
    convert()