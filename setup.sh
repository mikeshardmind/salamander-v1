#!/usr/bin/env bash

mkdir -p contrib_data
mkdir -p wheels
sqlite3 salamander.db < schema.sql
python3.8 -m pip install -U wheel setuptools pip
python3.8 -m pip install -Ur requirements.txt --upgrade-strategy eager

if [ ! -f wheels/apsw-3.35.0.post1-cp38-cp38*.whl ]; then
  git clone https://github.com/rogerbinns/apsw/
  pushd apsw
  git config --local user.email "nobody@example.org"
  git config --local user.name "nobody"
  git checkout 8a4858dad1dfd5d35bfd30c445641923f1a274e4
  git am ../patches/apsw/*.patch
  python setup.py fetch --all
  python setup.py bdist_wheel
  cp dist/* ../wheels/
  popd
  rm -rf apsw
fi

python3.8 -m pip install wheels/apsw-3.35.0.post1-cp38-cp38*.whl
