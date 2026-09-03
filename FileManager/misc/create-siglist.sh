#!/bin/sh
#
#
>${1}.siglist
>${1}.dupes

find $1 -type f |\
while :
do
    read path
    if [ $? -ne 0 ]; then break; fi
    OUTPUT=`md5sum "$path"`
    egrep "${OUTPUT}" ${1}.siglist >/dev/null
    if [ $? -eq 0 ]; then
        echo "DUPLICATE: ${OUTPUT}"
        echo "${path}: ${OUTPUT}" >>${1}.dupes
    fi
    echo "${OUTPUT}" >>${1}.siglist
done
