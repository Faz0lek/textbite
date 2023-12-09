import sys
import os
import argparse
import logging
from typing import Tuple
import time
from time import perf_counter
import pickle

import torch
from torch.utils.data import DataLoader

from safe_gpu import safe_gpu

from textbite.models.graph.dataset import GraphDataset
from textbite.models.graph.model import GraphModel
from textbite.models.graph.create_graphs import Graph  # needed for unpickling


def parse_arguments():
    print(' '.join(sys.argv), file=sys.stderr)

    parser = argparse.ArgumentParser()

    parser.add_argument("--data", required=True, type=str, help="Path to a pickle file with training data.")

    parser.add_argument("-b", "--batch-size", type=int, default=64, help="Batch size")
    parser.add_argument("-r", "--train-ratio", type=float, default=0.8, help="Train/Validation ratio.")

    parser.add_argument("-l", "--nb-hidden", type=int, default=2, help="Number of layers in the model.")
    parser.add_argument("-n", "--hidden-width", type=int, default=256, help="Hidden size of layers.")
    parser.add_argument("-d", "--dropout", type=float, default=0.1, help="Dropout probability in the model.")

    parser.add_argument("-e", "--max-epochs", type=int, default=50, help="Number of epochs")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")

    parser.add_argument("--save", type=str, help="Where to save the model best by validation F1")
    parser.add_argument("--checkpoint-dir", type=str, help="Where to put all training checkpoints")

    args = parser.parse_args()
    return args


def prepare_loaders(path: str, batch_size: int, ratio: float) -> Tuple[DataLoader, DataLoader]:
    start = perf_counter()
    dataset = GraphDataset(path)

    train_dataset, val_dataset = torch.utils.data.random_split(dataset, [ratio, 1 - ratio])

    train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=batch_size)
    val_loader = torch.utils.data.DataLoader(val_dataset, batch_size=batch_size)

    end = perf_counter()
    t = end - start
    logging.info(f"Train data loaded. n_samples = {len(dataset)}\ttrain = {len(train_dataset)}\tval = {len(val_dataset)}\ttook {t:.1f} s")

    return train_loader, val_loader


def per_edge_loss(node_features, graph, labels):
    criterion = torch.nn.BCEWithLogitsLoss()
    loss = torch.tensor(0.0, device=node_features.device)
    for i, (from_idx, to_idx) in enumerate(zip(graph.edge_index[0], graph.edge_index[1])):
        from_idx = from_idx.item()
        to_idx = to_idx.item()
        lhs = node_features[from_idx, :]
        rhs = node_features[to_idx, :]

        similarity = torch.dot(lhs, rhs)
        label = labels[i].to(dtype=torch.float32)

        loss += criterion(similarity, label)

    return loss


# TODO: DET or similar will be super useful, it's all terribly mis-calibrated so far
def per_edge_accuracy(node_features, graph, labels):
    nb_hits = 0
    for i, (from_idx, to_idx) in enumerate(zip(graph.edge_index[0], graph.edge_index[1])):
        from_idx = from_idx.item()
        to_idx = to_idx.item()
        lhs = node_features[from_idx, :]
        rhs = node_features[to_idx, :]

        similarity = torch.dot(lhs, rhs)
        nb_hits += (similarity > 0.5) == labels[i]

    return nb_hits / len(graph.edge_index[0])


def evaluate(model, data, device):
    model.eval()
    val_loss = 0.0
    accuracy = 0.0
    for graph in data:
        node_features = graph.node_features.to(device)
        edge_indices = graph.edge_index.to(device)
        labels = graph.labels.to(device)

        with torch.no_grad():
            outputs = model(node_features, edge_indices)
            loss = per_edge_loss(outputs, graph, labels)
            accuracy += per_edge_accuracy(outputs, graph, labels)
        val_loss += loss.cpu().item()

    print(f'Val loss: {val_loss/len(data):.1f}')
    print(f'Accuracy: {accuracy/len(data):.1f}')
    return val_loss


def train(
        model: GraphModel,
        device,
        train_data,
        val_data,
        epochs: int,
        lr: float,
        save_path: str,
        checkpoint_dir: str,
):
    evaluate(model, val_data, device)

    optim = torch.optim.Adam(model.parameters(), lr)
    for epoch in range(epochs):
        model.train()

        report_mod = 25
        running_loss = 0.0
        t0 = time.time()
        grad_acc = 1
        for graph_i, graph in enumerate(train_data):
            node_features = graph.node_features.to(device)
            edge_indices = graph.edge_index.to(device)
            labels = graph.labels.to(device)

            outputs = model(node_features, edge_indices)
            train_loss = per_edge_loss(outputs, graph, labels)

            train_loss.backward()
            running_loss += train_loss.cpu().item()

            if (graph_i + 1) % grad_acc == 0:
                optim.step()
                grad_norm = sum(p.grad.norm() for p in model.parameters())
                optim.zero_grad()

            if (graph_i + 1) % report_mod == 0:
                t_diff = time.time() - t0
                print(f"After {graph_i+1} graphs: avg time {1000.0*t_diff/report_mod:.1f}ms, avg loss {running_loss/report_mod:.1f}, latest grad norm: {grad_norm:.1f}")
                t0 = time.time()
                running_loss = 0.0

        evaluate(model, val_data, device)

        # dict_for_saving = {
        #     "state_dict": model.state_dict(),
        #     "n_layers": model.n_layers,
        #     "hidden_size": model.hidden_size
        # }

        # if f1_val > best_f1_val:
        #     best_f1_val = f1_val
        #     print(f"SAVING MODEL at f1_val = {f1_val}")
        #     torch.save(dict_for_saving, os.path.join(save_path, "BaselineModel.pth"))

        # print(f"Epoch {epoch + 1} finished | train f1 = {f1:.2f} loss = {train_loss/train_nb_examples:.3e} | val f1 = {f1_val:.2f} loss = {val_loss/val_nb_examples:.3e} {'| Only zeros in last val batch!' if not any(preds) else ''}")
        # if (epoch + 1) % 10 == 0:
        #     target_names = ["None", "Terminating", "Title"]  # should be provided by model or someone like that
        #     print("TRAIN REPORT:")
        #     print(classification_report(epoch_labels, epoch_preds, digits=4, zero_division=0, target_names=target_names))
        #     print(confusion_report(epoch_labels, epoch_preds, target_names))
        #     print("VALIDATION REPORT:")
        #     print(classification_report(epoch_labels_val, epoch_preds_val, digits=4, zero_division=0, target_names=target_names))
        #     print(confusion_report(epoch_labels_val, epoch_preds_val, target_names))
        #     print("VALIDATION REPORT:")
        #     if checkpoint_dir:
        #         torch.save(dict_for_saving, os.path.join(checkpoint_dir, f'checkpoint.{epoch}.pth'))


def main():
    logging.basicConfig(
        level=logging.INFO,
        force=True,
    )
    args = parse_arguments()
    safe_gpu.claim_gpus()

    if args.checkpoint_dir:
        os.makedirs(args.checkpoint_dir, exist_ok=True)

    # Device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logging.info(f"Training on: {device}")

    # # Data loaders
    # logging.info("Creating data loaders ...")
    # train_loader, val_loader = prepare_loaders(args.data, args.batch_size, args.train_ratio)
    # logging.info("Data loaders ready.")

    with open(args.data, "rb") as f:
        data = pickle.load(f)
    logging.info(f'There are {len(data)} graphs for training')

    last_train_idx = int(args.train_ratio * len(data))
    train_data = data[:last_train_idx]
    val_data = data[last_train_idx:]
    logging.info(f'Train data has {len(train_data)} graphs')
    logging.info(f'Valid data has {len(val_data)} graphs')

    # Model
    logging.info("Creating model ...")
    model = GraphModel(
        input_size=97,
        output_size=10,
        device=device,
    )
    model = model.to(device)
    logging.info("Model created.")

    logging.info("Starting training ...")
    start = perf_counter()
    train(
        model=model,
        device=device,
        train_data=train_data,
        val_data=val_data,
        epochs=args.max_epochs,
        lr=args.lr,
        save_path=args.save,
        checkpoint_dir=args.checkpoint_dir,
    )
    end = perf_counter()
    t = end - start
    logging.info(f"Training finished. Took {t:.1f} s")


if __name__ == "__main__":
    main()
