FROM archlinux/base
MAINTAINER ragnar.grootkoerkamp@gmail.com
RUN pacman-key --refresh-keys --keyserver hkp://pool.sks-keyservers.net
RUN pacman -Syu --noconfirm \
	automake \
	git \
	sudo \
	tidy \
	vim \
	gcc \
	python \
	pypy \
	pypy3 \
	python-yaml \
	python-colorama \
	python-argcomplete \
	python-pytest \
	python2 \
	jdk11-openjdk \
	kotlin \
	texlive-core \
	texlive-latexextra \
	texlive-pictures \
	texlive-science \
	boost-libs \
	asymptote \
	ghostscript \
	&& \
	pacman -Scc --noconfirm
COPY third_party/checktestdata /usr/bin/checktestdata
