#!/bin/sh
DATE=`date +"%Y-%m-%d"`;

rm -f pytsk-*.tgz

FILES="../pytsk/LICENSE ../pytsk/MANIFEST ../pytsk/*.* ../pytsk/dpkg ../pytsk/msvscpp ../pytsk/samples"

tar zcf pytsk-${DATE}.tgz ${FILES} 2>/dev/null
