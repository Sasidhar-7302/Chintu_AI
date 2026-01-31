"""Train a LoRA adapter from weekly learning data (optional)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class TrainingOutcome:
    ok: bool
    message: str
    adapter_path: Optional[str] = None
    missing_deps: Optional[List[str]] = None


def train_adapter(dataset_path: Path, output_dir: Path) -> TrainingOutcome:
    config = get_config()
    base_model = getattr(config, "learning_base_model_id", "Qwen/Qwen2.5-1.5B-Instruct")
    max_steps = int(getattr(config, "learning_train_max_steps", 80))
    max_seq_len = int(getattr(config, "learning_train_max_seq_len", 1024))
    grad_accum = int(getattr(config, "learning_train_grad_accum", 8))

    missing = _check_deps()
    if missing:
        return TrainingOutcome(
            ok=False,
            message="Training dependencies missing: " + ", ".join(missing),
            missing_deps=missing,
        )

    try:
        import torch
        from datasets import Dataset
        from transformers import (
            AutoTokenizer,
            AutoModelForCausalLM,
            TrainingArguments,
            Trainer,
            DataCollatorForLanguageModeling,
        )
        from peft import LoraConfig, get_peft_model
    except Exception as exc:
        return TrainingOutcome(ok=False, message=f"Training imports failed: {exc}")

    if not dataset_path.exists():
        return TrainingOutcome(ok=False, message=f"Dataset not found: {dataset_path}")

    rows = _load_jsonl(dataset_path)
    if not rows:
        return TrainingOutcome(ok=False, message="Dataset is empty.")

    tokenizer = AutoTokenizer.from_pretrained(base_model, use_fast=True)
    if torch.cuda.is_available():
        dtype = torch.float16
        device_map = "auto"
    else:
        dtype = torch.float32
        device_map = None
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=dtype,
        device_map=device_map,
    )

    lora_modules = _select_lora_modules(model)
    lora_config = LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=lora_modules,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)

    dataset = Dataset.from_list(rows)
    dataset = dataset.map(
        lambda item: _tokenize_item(item, tokenizer, max_seq_len),
        remove_columns=list(dataset.features),
    )

    args = TrainingArguments(
        output_dir=str(output_dir),
        per_device_train_batch_size=1,
        gradient_accumulation_steps=grad_accum,
        num_train_epochs=1,
        max_steps=max_steps,
        logging_steps=10,
        save_steps=max_steps,
        learning_rate=2e-4,
        fp16=torch.cuda.is_available(),
        report_to=[],
    )
    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=dataset,
        data_collator=collator,
    )

    trainer.train()

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    adapter_path = output_dir / f"adapter_{stamp}"
    model.save_pretrained(adapter_path)
    _write_active_adapter(adapter_path, base_model, output_dir)
    return TrainingOutcome(ok=True, message="LoRA adapter trained.", adapter_path=str(adapter_path))


def _check_deps() -> List[str]:
    missing = []
    try:
        import torch  # noqa: F401
    except Exception:
        missing.append("torch")
    try:
        import transformers  # noqa: F401
    except Exception:
        missing.append("transformers")
    try:
        import peft  # noqa: F401
    except Exception:
        missing.append("peft")
    try:
        import datasets  # noqa: F401
    except Exception:
        missing.append("datasets")
    return missing


def _load_jsonl(path: Path) -> List[dict]:
    rows: List[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append(_normalize_sample(data))
    return rows


def _normalize_sample(sample: dict) -> dict:
    if "messages" in sample:
        return sample
    if "instruction" in sample and "output" in sample:
        return {
            "messages": [
                {"role": "user", "content": sample["instruction"]},
                {"role": "assistant", "content": sample["output"]},
            ]
        }
    return sample


def _tokenize_item(sample: dict, tokenizer, max_len: int) -> dict:
    text = _sample_to_text(sample, tokenizer)
    tokens = tokenizer(
        text,
        truncation=True,
        max_length=max_len,
        padding="max_length",
    )
    tokens["labels"] = tokens["input_ids"].copy()
    return tokens


def _sample_to_text(sample: dict, tokenizer) -> str:
    messages = sample.get("messages")
    if isinstance(messages, list) and hasattr(tokenizer, "apply_chat_template"):
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    parts = []
    if isinstance(messages, list):
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"{role.capitalize()}: {content}")
        parts.append("Assistant:")
        return "\n".join(parts)
    return json.dumps(sample, ensure_ascii=True)


def _select_lora_modules(model) -> List[str]:
    preferred = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    found = set()
    for name, _ in model.named_modules():
        for key in preferred:
            if name.endswith(key):
                found.add(key)
    return sorted(found) or preferred


def _write_active_adapter(adapter_path: Path, base_model: str, output_dir: Path) -> None:
    info = {"base_model": base_model, "adapter_path": str(adapter_path)}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "active_adapter.json").write_text(json.dumps(info, indent=2), encoding="utf-8")


if __name__ == "__main__":
    config = get_config()
    dataset = Path(config.training_exports_dir) / "latest.jsonl"
    output = Path(config.learning_adapter_dir)
    outcome = train_adapter(dataset, output)
    print(outcome.message)
