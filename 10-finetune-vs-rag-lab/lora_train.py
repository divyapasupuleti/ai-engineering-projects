#!/usr/bin/env python3
"""Optional: real LoRA fine-tune of a small model on the Task A tickets (replaces the naive-Bayes stand-in).

    pip install "transformers>=4.44" "peft>=0.12" datasets accelerate torch
    python lora_train.py --model Qwen/Qwen2.5-0.5B-Instruct --epochs 3 --out runs/lora-router

Runs on a laptop GPU/MPS in minutes; on CPU it is slow but works. Not used by lab.py or the tests.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from make_data import QUEUES, tickets  # noqa: E402

PROMPT = "Route the support ticket to one queue ({labels}).\nTicket: {text}\nQueue:"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--rank", type=int, default=8)
    ap.add_argument("--out", default=str(ROOT / "runs" / "lora-router"))
    args = ap.parse_args()
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model
        from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments
    except ImportError as exc:
        sys.exit(f"missing dependency ({exc.name}); see the install line in this file's docstring")

    labels = ", ".join(QUEUES)
    tok = AutoTokenizer.from_pretrained(args.model)
    tok.pad_token = tok.pad_token or tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(args.model)
    model = get_peft_model(model, LoraConfig(r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05,
                                             target_modules=["q_proj", "v_proj"], task_type="CAUSAL_LM"))
    model.print_trainable_parameters()

    def encode(row):
        text = PROMPT.format(labels=labels, text=row["text"]) + " " + row["label"] + tok.eos_token
        enc = tok(text, truncation=True, max_length=128, padding="max_length")
        enc["labels"] = [t if t != tok.pad_token_id else -100 for t in enc["input_ids"]]
        return enc

    train = Dataset.from_list([{"text": t, "label": y} for t, y in tickets(400, seed=1)]).map(encode)
    Trainer(model=model, train_dataset=train, args=TrainingArguments(
        output_dir=args.out, num_train_epochs=args.epochs, per_device_train_batch_size=8,
        learning_rate=2e-4, logging_steps=10, save_strategy="no", report_to=[])).train()
    model.save_pretrained(args.out)

    model.eval()
    test = tickets(300, seed=2, noise=0.0, include_holdout=True)
    correct = 0
    for text, gold in test:
        ids = tok(PROMPT.format(labels=labels, text=text), return_tensors="pt")
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=6, do_sample=False)
        pred = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip().split()[0:1]
        correct += bool(pred) and pred[0] == gold
    print(f"LoRA accuracy on {len(test)} test tickets: {correct / len(test):.1%} (adapter saved to {args.out})")


if __name__ == "__main__":
    main()
