"""Write a llama.cpp LoRA adapter (GGUF) for Muse Glimmer from our PEFT adapter.

llama.cpp b11909's convert_lora_to_gguf.py has no Muse Glimmer class, but the official GGUF uses the standard
tensor names (blk.N.attn_q / attn_k / attn_v / attn_output) with the same shapes as the HF projections, so the
adapter maps one-to-one. Conventions follow convert_lora_to_gguf.py: general.type=adapter, adapter.type=lora,
adapter.lora.alpha, tensors "<base tensor>.lora_a" (r x in) and ".lora_b" (out x r), untransposed.

    PYTHONPATH=<llama.cpp>/gguf-py python students/lora_to_gguf.py <peft_dir> <out.gguf>
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
from safetensors import safe_open

import gguf

MAP = {"q_proj": "attn_q", "k_proj": "attn_k", "v_proj": "attn_v", "o_proj": "attn_output"}
PAT = re.compile(r"language_model\.layers\.(\d+)\.self_attn\.(q_proj|k_proj|v_proj|o_proj)\.lora_([AB])\.weight$")


def main(src: str, dst: str) -> None:
    cfg = json.loads((Path(src) / "adapter_config.json").read_text())
    w = gguf.GGUFWriter(dst, arch="muse-glimmer")
    w.add_type(gguf.GGUFType.ADAPTER)
    w.add_string(gguf.Keys.Adapter.TYPE, "lora")
    w.add_float32(gguf.Keys.Adapter.LORA_ALPHA, float(cfg["lora_alpha"]))
    n = 0
    with safe_open(str(Path(src) / "adapter_model.safetensors"), "np") as f:
        for k in sorted(f.keys()):
            m = PAT.search(k)
            if not m:
                raise ValueError(f"unexpected tensor {k}")
            layer, proj, ab = m.groups()
            name = f"blk.{layer}.{MAP[proj]}.weight.lora_{ab.lower()}"
            w.add_tensor(name, f.get_tensor(k).astype(np.float16))
            n += 1
    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_tensors_to_file()
    w.close()
    print(f"wrote {n} tensors to {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
