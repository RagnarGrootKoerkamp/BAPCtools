# NOTE: This installs the BAPCtools version from the GitHub master branch.
FROM archlinux:latest
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
	pypy3 \
	python-yaml \
	python-colorama \
	python-argcomplete \
	python-pytest \
	python-ruamel-yaml \
	python2 \
	jdk17-openjdk \
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
RUN git clone https://github.com/RagnarGrootKoerkamp/BAPCtools /opt/bapctools && \
    ln -sfn /opt/bapctools/bin/tools.py /usr/bin/bt && ln -sfn /opt/bapctools/third_party/checktestdata /usr/bin/checktestdata
RUN mkdir /data
WORKDIR /data
ENTRYPOINT ["/bin/bt"]
