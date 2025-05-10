# NOTE: This installs the BAPCtools version from the GitHub master branch.
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
	python-pytest \
	python-ruamel-yaml \
	python-yaml \
	python-requests \
	jdk21-openjdk \
	kotlin \
	rust \
	texlive-core \
	texlive-binextra \
	texlive-langeuropean \
	texlive-langgerman \
	texlive-latexextra \
	texlive-pictures \
	texlive-science \
	boost-libs \
	asymptote \
	ghostscript \
	nodejs \
	cue \
	&& pacman -Scc --noconfirm

RUN git clone https://github.com/RagnarGrootKoerkamp/BAPCtools /opt/bapctools && \
	ln -sfn /opt/bapctools/bin/tools.py /usr/bin/bt && ln -sfn /opt/bapctools/third_party/checktestdata /usr/bin/checktestdata

RUN mkdir /data
WORKDIR /data
ENTRYPOINT ["/bin/bt"]
