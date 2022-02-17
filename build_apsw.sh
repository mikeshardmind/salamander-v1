#!/usr/bin/env bash

if [ ! -f wheels/apsw-3.37.0.post1-cp310-cp310*.whl ]; then
  git clone https://github.com/rogerbinns/apsw/
  pushd apsw
  git config --local user.email "nobody@example.org"
  git config --local user.name "nobody"
  git checkout 3e872a11fba8ebf0392c3c01b414d8f92379aee8
  git am ../patches/apsw/*.patch
  python3.10 setup.py fetch --all --version=3.37.0
  python3.10 setup.py bdist_wheel
  python3.10 -m pip install dist/apsw-3.37.0.post1-cp310-cp310*.whl
  cp dist/* ../wheels/
  popd
  rm -rf apsw
fi
