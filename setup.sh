#!/usr/bin/env bash

mkdir -p contrib_data
mkdir -p wheels
sqlite3 salamander.db < schema.sql
python3.8 -m pip install -U wheel setuptools pip
python3.8 -m pip install -Ur requirements.txt --upgrade-strategy eager --use-feature=2020-resolver

if [ ! -f wheels/apsw-3.33.0.post1-cp38-cp38*.whl ]; then
  git clone https://github.com/rogerbinns/apsw/
  pushd apsw
  git checkout 3ed983d92b52ce9732b04e82d74900a67cc92d10
  git am ../patches/apsw/*.patch
  python setup.py fetch --all
  python setup.py bdist_wheel
  cp dist/* ../wheels/
  popd
  rm -rf apsw
fi

python3.8 -m pip install wheels/*.whl
