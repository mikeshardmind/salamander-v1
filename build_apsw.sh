#!/usr/bin/env bash

if [ ! -f wheels/apsw-3.38.1.post1-cp310-cp310*.whl ]; then
  git clone https://github.com/rogerbinns/apsw/
  pushd apsw
  git config --local user.email "nobody@example.org"
  git config --local user.name "nobody"
  git checkout 61ec39bdc5b555d8fdc5d676e0bcff0e02d7f9df
  git am ../patches/apsw/*.patch
  python3.10 setup.py fetch --all --version=3.38.1
  python3.10 setup.py bdist_wheel
  python3.10 -m pip install dist/apsw-3.38.1.post1-cp310-cp310*.whl
  cp dist/* ../wheels/
  popd
  rm -rf apsw
fi