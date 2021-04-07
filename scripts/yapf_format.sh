#!/usr/bin/env sh

cd "${0%/*}"
yapf -i ../bin/*.py ../bin/*/*.py
