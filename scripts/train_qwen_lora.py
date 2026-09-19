from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPLITS_ROOT = PROJECT_ROOT / "data" / "finetuning" / "splits"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "models" / "qwen2_5_docia_lora"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            records.append(payload)
    return records


def format_example(example: dict[str, Any], tokenizer: Any | None = None) -> str:
    output = example.get("output", {})
    output_text = json.dumps(output, ensure_ascii=False)
    messages = [
        {"role": "system", "content": "Tu es un extracteur de documents. Reponds uniquement en JSON valide."},
        {
            "role": "user",
            "content": f"{example.get('instruction', '')}\n\nDocument:\n{example.get('input', '')}",
        },
        {"role": "assistant", "content": output_text},
    ]
    if tokenizer is not None and hasattr(tokenizer, "apply_chat_template"):
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    return (
        "<|system|>\nTu es un extracteur de documents. Reponds uniquement en JSON valide.\n"
        f"<|user|>\n{messages[1]['content']}\n"
        f"<|assistant|>\n{output_text}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tuning LoRA Qwen2.5 pour DocIA.")
    parser.add_argument("--splits-root", type=Path, default=DEFAULT_SPLITS_ROOT)
    parser.add_argument("--model-name", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--max-length", type=int, default=2048)
    args = parser.parse_args()

    try:
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            DataCollatorForLanguageModeling,
            Trainer,
            TrainingArguments,
        )
    except ImportError as exc:
        raise SystemExit(
            "Dependances fine-tuning manquantes. Installe: "
            "python -m pip install -r requirements-finetuning.txt"
        ) from exc

    train_records = load_jsonl(args.splits_root / "train.jsonl")
    validation_records = load_jsonl(args.splits_root / "validation.jsonl")
    if not train_records:
        raise SystemExit("Aucun exemple train trouve. Lance d'abord build_finetuning_dataset.py.")

    tokenizer = AutoTokenizer.from_pretrained(args.model_name, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    def tokenize(example: dict[str, Any]) -> dict[str, Any]:
        text = format_example(example, tokenizer)
        encoded = tokenizer(
            text,
            truncation=True,
            max_length=args.max_length,
            padding=False,
        )
        encoded["labels"] = list(encoded["input_ids"])
        return encoded

    train_dataset = Dataset.from_list(train_records).map(tokenize, remove_columns=list(train_records[0].keys()))
    eval_dataset = None
    if validation_records:
        eval_dataset = Dataset.from_list(validation_records).map(
            tokenize,
            remove_columns=list(validation_records[0].keys()),
        )

    model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        device_map="auto",
        torch_dtype="auto",
        trust_remote_code=True,
    )
    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora_config)

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        logging_steps=10,
        save_steps=100,
        evaluation_strategy="steps" if eval_dataset is not None else "no",
        eval_steps=100,
        save_total_limit=2,
        fp16=False,
        bf16=False,
        report_to=[],
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        tokenizer=tokenizer,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
    )
    trainer.train()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print(f"Adaptateur LoRA sauvegarde dans: {args.output_dir}")


if __name__ == "__main__":
    main()
