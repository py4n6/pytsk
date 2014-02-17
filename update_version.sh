#!/bin/bash
# A small helper script to update the version information.

DATE_VERSION=`date +"%Y%m%d"`;
DATE_DPKG=`date -R`;
EMAIL_DPKG="Joachim Metz <joachim.metz@gmail.com>";

sed -i -e "s/^\(VERSION = \)\"[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]\"$/\1\"${DATE_VERSION}\"/" class_parser.py
sed -i -e "s/^\(pytsk \)(\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-1)/\1(\2-${DATE_VERSION}-1)/" dpkg/changelog
sed -i -e "s/^\( -- ${EMAIL_DPKG}  \).*$/\1${DATE_DPKG}/" dpkg/changelog
