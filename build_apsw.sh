#!/usr/bin/env bash

if [ ! -f wheels/apsw-3.35.2.post1-cp38-cp38*.whl ]; then
  git clone https://github.com/rogerbinns/apsw/
  pushd apsw
  git config --local user.email "nobody@example.org"
  git config --local user.name "nobody"
  git checkout 3d9c51f09258ab5140fca05c651c66899c608759
  git am ../patches/apsw/*.patch
  python setup.py fetch --all --version=3.35.3
  python setup.py bdist_wheel
  cp dist/* ../wheels/
  popd
  rm -rf apsw
fi