#!/bin/sh
DATE=`date +"%Y-%m-%d"`;
rm -f pytsk-*.tgz
tar zcf pytsk-${DATE}.tgz ../pytsk/LICENSE ../pytsk/MANIFEST ../pytsk/*.* ../pytsk/msvscpp ../pytsk/samples 2>/dev/null
