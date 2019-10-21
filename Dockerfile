FROM archlinux/base
MAINTAINER ragnar.grootkoerkamp@gmail.com
RUN pacman -Syu --noconfirm \
	automake \
	git \
	sudo \
	tidy \
	vim \
	gcc \
	python \
	pypy \
	python-yaml \
	python-argcomplete \
	python2 \
	jdk8-openjdk \
	kotlin \
	texlive-core \
	texlive-latexextra \
	texlive-pictures \
	texlive-science \
	&& \
	pacman -Scc --noconfirm
