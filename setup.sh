#!/usr/bin/env bash

mkdir -p wheels
python3.9 -m pip install -U wheel setuptools pip
python3.9 -m pip install --require-hashes -Ur requirements.txt --upgrade-strategy eager
./build_apsw.sh
printf ".open salamander.db\n.read schema.sql\n.quit" | python3.9 -c "import apsw; apsw.main()"
exit 0
