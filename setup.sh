#!/usr/bin/env bash

mkdir -p wheels
sqlite3 salamander.db < schema.sql
python3.8 -m pip install -U wheel setuptools pip
python3.8 -m pip install -Ur requirements.txt --upgrade-strategy eager
./build_apsw.sh
python3.8 -m pip install wheels/apsw-3.35.2.post1-cp38-cp38*.whl
