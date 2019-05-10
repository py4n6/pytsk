#!/bin/bash
#
# Script to set up Travis-CI test VM.

if test -n "${CENTOS_VERSION}";
then
	CONTAINER_NAME="centos${CENTOS_VERSION}";

	docker pull centos:${CENTOS_VERSION};

	docker run --name=${CONTAINER_NAME} --detach -i centos:${CENTOS_VERSION};

	docker exec ${CONTAINER_NAME} yum group install -y "Development Tools";

	RPM_PACKAGES="git";

	if test ${TRAVIS_PYTHON_VERSION} = "2.7";
	then
		RPM_PACKAGES="${RPM_PACKAGES} python2 python2-devel python2-setuptools";
	else
		RPM_PACKAGES="${RPM_PACKAGES} python3 python3-devel python3-setuptools";
	fi
	docker exec ${CONTAINER_NAME} yum install -y ${RPM_PACKAGES};

	docker cp ../pytsk ${CONTAINER_NAME}:/

elif test -n "${FEDORA_VERSION}";
then
	CONTAINER_NAME="fedora${FEDORA_VERSION}";

	docker pull registry.fedoraproject.org/fedora:${FEDORA_VERSION};

	docker run --name=${CONTAINER_NAME} --detach -i registry.fedoraproject.org/fedora:${FEDORA_VERSION};

	docker exec ${CONTAINER_NAME} dnf groupinstall -y "Development Tools";

	RPM_PACKAGES="autoconf automake gcc-c++ git libtool libstdc++-devel";

	if test ${TRAVIS_PYTHON_VERSION} = "2.7";
	then
		RPM_PACKAGES="${RPM_PACKAGES} python2 python2-devel";
	else
		RPM_PACKAGES="${RPM_PACKAGES} python3 python3-devel";
	fi
	docker exec ${CONTAINER_NAME} dnf install -y ${RPM_PACKAGES};

	docker cp ../pytsk ${CONTAINER_NAME}:/

elif test -n "${UBUNTU_VERSION}";
then
	CONTAINER_NAME="ubuntu${UBUNTU_VERSION}";

	docker pull ubuntu:${UBUNTU_VERSION};

	docker run --name=${CONTAINER_NAME} --detach -i ubuntu:${UBUNTU_VERSION};

	# Install add-apt-repository and locale-gen.
	docker exec ${CONTAINER_NAME} apt-get update -q;
	docker exec -e "DEBIAN_FRONTEND=noninteractive" ${CONTAINER_NAME} sh -c "apt-get install -y locales software-properties-common";

	# Set locale to US English and UTF-8.
	docker exec ${CONTAINER_NAME} locale-gen en_US.UTF-8;

	# Install packages.
	DPKG_PACKAGES="automake autotools-dev build-essential git libtool";

	if test ${TRAVIS_PYTHON_VERSION} = "2.7";
	then
		DPKG_PACKAGES="${DPKG_PACKAGES} python python-dev python-setuptools";
	else
		DPKG_PACKAGES="${DPKG_PACKAGES} python3 python3-dev python3-distutils python3-setuptools";
	fi
	docker exec -e "DEBIAN_FRONTEND=noninteractive" ${CONTAINER_NAME} sh -c "apt-get install -y ${DPKG_PACKAGES}";

	docker cp ../pytsk ${CONTAINER_NAME}:/

elif test ${TARGET} = "linux";
then
	sudo apt-get update -q && sudo apt-get install -y autopoint;

elif test ${TARGET} = "macos";
then
	brew update && brew install gettext && brew link --force gettext;
fi
