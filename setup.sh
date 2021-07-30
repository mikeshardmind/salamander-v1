#!/usr/bin/env bash

mkdir -p wheels
python3.9 -m pip install -U wheel setuptools pip
python3.9 -m pip install --require-hashes -Ur requirements.txt --upgrade-strategy eager
./build_apsw.sh
python3.9 -m pip install wheels/apsw-3.35.4.post1-cp39-cp39*.whl
printf ".open salamander.db\n.read schema.sql\n.quit" | python3.9 -c "import apsw; apsw.main()"
exit 0
