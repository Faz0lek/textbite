#!/bin/bash

# Author: Martin Kostelník
# Brief: Infer data using YOLO model
# Date: 28.12.2023

BASE=/home/martin/textbite

source $BASE/../semant/venv/bin/activate

SCRIPTS_DIR=$BASE/textbite/models/yolo
IMG_PATH=$BASE/data/images/val
XML_PATH=$BASE/data/xmls/val
ALTO_PATH=$BASE/data/altos
MODEL_PATH=$BASE/models/yolo-s-800.pt
SAVE_PATH=$BASE/yolo-inference-val

python -u $SCRIPTS_DIR/infer.py \
    --logging-level INFO \
    --data $XML_PATH \
    --images $IMG_PATH \
    --altos $ALTO_PATH \
    --model $MODEL_PATH \
    --save $SAVE_PATH
