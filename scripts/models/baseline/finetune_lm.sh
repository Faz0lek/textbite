#!/bin/bash

# Author: Martin Kostelník
# Brief: Finetune LM on SGE
# Date: 21.04.2024

BASE=/mnt/matylda1/xkoste12

source $BASE/venv/bin/activate

SCRIPTS_DIR=$BASE/textbite/textbite/models/baseline
DATA_PATH=$BASE/textbite-data/nsp-data-fixed
MODEL_PATH=$BASE/lm-models-lm264
SAVE_PATH=$BASE/czerts
FILENAME=data-train.pkl

mkdir -p $SAVE_PATH

python -u $SCRIPTS_DIR/finetune_lm.py \
    --logging-level INFO \
    --data $DATA_PATH \
    --save $SAVE_PATH \
    --model $MODEL_PATH \
    --lr 1e-3 \
    --epochs 2 \
    --batch-size 32
