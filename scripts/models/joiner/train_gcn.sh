#!/bin/bash

# Author: Martin Kostelník
# Brief: Train graph model for bite joining
# Date: 30.12.2023

BASE=/home/martin/textbite

source $BASE/../semant/venv/bin/activate

SCRIPTS_DIR=$BASE/textbite/models/joiner
GRAPHS_PATH=$BASE/joiner-graphs
DATA_PATH=$GRAPHS_PATH/graphs-train.pkl
DATA_PATH_VAL_BOOK=$GRAPHS_PATH/graphs-val-book.pkl
DATA_PATH_VAL_DICT=$GRAPHS_PATH/graphs-val-dict.pkl
DATA_PATH_VAL_PERI=$GRAPHS_PATH/graphs-val-peri.pkl
SAVE_PATH=$BASE/joiner-models

mkdir -p $SAVE_PATH

python -u $SCRIPTS_DIR/train_gcn.py \
    --train $DATA_PATH \
    --val-book $DATA_PATH_VAL_BOOK \
    --val-dict $DATA_PATH_VAL_DICT \
    --val-peri $DATA_PATH_VAL_PERI \
    -l 3 \
    -n 128 \
    -o 128 \
    -d 0.0 \
    --threshold 0.71 \
    --lr 5e-3 \
    --batch-size 64 \
    --report-interval 50 \
    --save $SAVE_PATH
