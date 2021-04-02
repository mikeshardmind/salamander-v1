#!/usr/bin/env bash

wget https://sqlite.org/2021/sqlite-autoconf-3350300.tar.gz
tar xvf sqlite-autoconf-3350300.tar.gz
cd sqlite-autoconf-3350300
./configure
make
make install