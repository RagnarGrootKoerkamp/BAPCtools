The checktestdata binary is statically linked and was built using docker image below.
If building on arm, make sure to build the docker image with `--platform linux/amd64`.

```Dockerfile
FROM ubuntu:latest

RUN apt update && apt install -y git make g++ libboost-dev libgmp-dev autotools-dev automake
RUN git clone https://github.com/DOMjudge/checktestdata.git /opt/checktestdata
WORKDIR /opt/checktestdata
RUN git switch release
RUN ./bootstrap
RUN echo "LDFLAGS += -static" >> config.mk
RUN make checktestdata
```
