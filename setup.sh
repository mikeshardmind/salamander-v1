#!/usr/bin/env bash

sqlite3 salamander.db < schema.sql
python3.8 -m pip install -r requirements.txt
python3.8 -m pip install https://github.com/rogerbinns/apsw/releases/download/3.33.0-r1/apsw-3.33.0-r1.zip \
    --global-option=fetch --global-option=--version --global-option=3.33.0 --global-option=--all \
    --global-option=build --global-option=--enable-all-extensions