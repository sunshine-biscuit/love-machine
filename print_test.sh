#!/usr/bin/env bash
# Simple launcher for Epson printer test

cd ~/love-machine || exit 1
source .venv/bin/activate
python3 print_test.py
