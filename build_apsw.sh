#!/usr/bin/env bash

if [ ! -f wheels/apsw-3.35.4.post1-cp39-cp39*.whl ]; then
  git clone https://github.com/rogerbinns/apsw/
  pushd apsw
  git config --local user.email "nobody@example.org"
  git config --local user.name "nobody"
  git checkout d52777bec644c45bf416f7cc02c483fbe53e45fd
  git am ../patches/apsw/*.patch
  python3.9 setup.py fetch --all --version=3.35.4
  python3.9 setup.py bdist_wheel
  cp dist/* ../wheels/
  popd
  rm -rf apsw
fi