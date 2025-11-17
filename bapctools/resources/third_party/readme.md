The checktestdata binary is statically linked by running the following command
in the root of the [checktestdata repository](https://github.com/DOMjudge/checktestdata)
```
g++ *.h *.hpp *.cc -static -lgmpxx -lgmp -lboost_system -o checktestdata
```
