"""Script for the fine-tuning of the pretrained custom BERT-like LM.

Date -- 15.05.2024
Author -- Martin Kostelnik
"""


import argparse
import os
import logging
import pickle
from time import perf_counter

from sklearn.metrics import classification_report, f1_score

from transformers import BertModel
import torch
from safe_gpu import safe_gpu

from textbite.language_model import create_language_model


def parse_arguments():
    parser = argparse.ArgumentParser()

    parser.add_argument("--logging-level", default='WARNING', choices=['ERROR', 'WARNING', 'INFO', 'DEBUG'])
    parser.add_argument("--data", required=True, type=str, help="Path to a folder with pickle data.")
    parser.add_argument("--model", type=str, help="Path to the LM.")
    parser.add_argument("--tokenizer", type=str, help="Path to the tokenizer.")
    parser.add_argument("--save", required=True, type=str, help="Folder where to put the trained model.")

    parser.add_argument("-e", "--epochs", type=int, default=1, help="Number of epochs")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--batch-size", type=int, default=16, help="Batch size")

    return parser.parse_args()



class Dataset(torch.utils.data.Dataset):
    def __init__(self, data: list):
        self.data = data

    def __len__(self):
        return len(self.data)

    def __getitem__(self, index: int):
        return self.data[index]
    

class NSPModel(torch.nn.Module):
    def __init__(
        self,
        device,
        bert,
    ):
        super().__init__()

        self.device = device

        self.bert = bert
        self.cls = torch.nn.Linear(self.bert.n_features, 1)

    def forward(self, input_ids, attention_mask, token_type_ids):
        bert_output = self.bert(input_ids, attention_mask=attention_mask, token_type_ids=token_type_ids)
        logits = self.cls(bert_output.sep_output)
        return logits

    @property
    def dict_for_saving(self):
        dict_for_saving = {
            "bert_state_dict": self.bert.state_dict(),
            "cls_state_dict": self.cls.state_dict(),
        }

        return dict_for_saving


def load_data(path: str):
    filenames = os.listdir(path)
    train_data = []
    
    for filename in filenames:
        p = os.path.join(path, filename)
        with open(p, "rb") as f:
            if filename.startswith("val"):
                val_data = pickle.load(f)
                # train_data = val_data

            if filename.startswith("train"):
                train_data.extend(pickle.load(f))

    return Dataset(train_data), Dataset(val_data)


def forward(model, device, batch):
    input_ids = batch.data["input_ids"].squeeze().to(device)
    attention_mask = batch.data["attention_mask"].squeeze().to(device)
    token_type_ids = batch.data["token_type_ids"].squeeze().to(device)

    outputs = model(input_ids, attention_mask, token_type_ids)
    return outputs


def evaluate(
        model,
        loader,
        device,
        criterion,
    ):
    model.eval()

    val_loss = 0.0
    all_predictions = []
    all_labels = []

    for batch in loader:
        labels = batch.data["label"].to(device, dtype=torch.float32)

        with torch.no_grad():
            logits = forward(model, device, batch)
            probs = torch.sigmoid(logits)
            val_loss += criterion(probs, labels)

        all_predictions.extend((probs > 0.5).cpu().squeeze())
        all_labels.extend(labels.cpu().squeeze())

    print(f"Val loss: {val_loss/len(all_labels):.4f}")
    print(classification_report(all_labels, all_predictions, digits=4))

    return val_loss, all_predictions, all_labels


def train(
        model,
        device,
        train_dataloader,
        val_dataloader,
        lr,
        epochs,
        save_path,
):
    model.train()

    optim = torch.optim.AdamW(model.parameters(), lr)
    criterion = torch.nn.BCELoss(reduction="sum")

    best_val_f1 = 0.0
    best_model_path = os.path.join(save_path, "best-nsp-lm264.pth")

    for epoch in range(epochs):
        model.train()

        epoch_labels = []
        epoch_predictions = []

        for batch_index, batch in enumerate(train_dataloader):
            logits = forward(model, device, batch)
            labels = batch.data["label"].to(device, dtype=torch.float32)
            
            probs = torch.sigmoid(logits)
            train_loss = criterion(probs, labels)

            optim.zero_grad()
            train_loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()

            epoch_labels.extend(labels.cpu().squeeze().tolist())
            epoch_predictions.extend((probs > 0.5).cpu().squeeze().tolist())

            if (batch_index + 1) % 100 == 0:
                print("TRAIN REPORT:")
                print(classification_report(epoch_labels, epoch_predictions, digits=4))
                epoch_labels = []
                epoch_predictions = []

                print("EVALUATION REPORT:")
                _, val_predictions, val_labels = evaluate(model, val_dataloader, device, criterion)
                val_f1 = f1_score(val_labels, val_predictions)

                if val_f1 > best_val_f1:
                    best_val_f1 = val_f1
                    print(f"Found new best model at F1 = {best_val_f1:.4f}, SAVING")
                    torch.save(
                        model.dict_for_saving,
                        best_model_path,
                    )


def main():
    args = parse_arguments()
    logging.basicConfig(level=args.logging_level, force=True)
    safe_gpu.claim_gpus()

    # Device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logging.info(f"Training on: {device}")

    # Model
    logging.info("Creating model ...")
    _, bert = create_language_model(device, path=args.model, tokenizer_path=args.tokenizer)
    model = NSPModel(device, bert)
    model = model.to(device)
    logging.info("Model created.")

    # Data
    logging.info("Loading data ...")
    train_dataset, val_dataset = load_data(args.data)
    logging.info("Data loaded.")

    logging.info("Creating dataloaders ...")
    train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
    val_loader = torch.utils.data.DataLoader(val_dataset, batch_size=args.batch_size)
    logging.info("Loaders created.")

    # Output folders
    os.makedirs(args.save, exist_ok=True)

    logging.info("Starting training ...")
    start = perf_counter()
    train(
        model=model,
        device=device,
        train_dataloader=train_loader,
        val_dataloader=val_loader,
        lr=args.lr,
        epochs=args.epochs,
        save_path=args.save,
    )
    end = perf_counter()
    t = end - start
    logging.info(f"Training finished. Took {t:.1f} s")


if __name__ == "__main__":
    main()