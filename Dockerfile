# Install the latest public BAPCtools release from PyPI.
FROM archlinux:latest
MAINTAINER ragnar.grootkoerkamp@gmail.com

RUN pacman -Syu --noconfirm \
	automake \
	git \
	sudo \
	tidy \
	vim \
	which \
	gcc \
	python \
	pypy \
	pypy3 \
	python-argcomplete \
	python-colorama \
	python-matplotlib \
	python-pip \
	python-pipx \
	python-pytest \
	python-requests \
	python-ruamel-yaml \
	python-typing_extensions \
	python-yaml \
	jdk21-openjdk \
	kotlin \
	rust \
	texlive-core \
	texlive-binextra \
	texlive-langeuropean \
	texlive-langgerman \
	texlive-langextra \
	texlive-latexextra \
	texlive-pictures \
	texlive-science \
	boost-libs \
	asymptote \
	ghostscript \
	nodejs \
	cue \
	&& pacman -Scc --noconfirm

ENV PIPX_HOME=/opt/pipx
ENV PIPX_BIN_DIR=/usr/local/bin
RUN pipx install bapctools

RUN mkdir /data
WORKDIR /data
RUN ln -s /usr/local/bin/bt bt
ENTRYPOINT ["bt"]
