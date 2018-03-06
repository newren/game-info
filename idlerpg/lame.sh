#!/bin/bash

while true; do
  if ( ./levelling.py | grep -o Participants:.* | grep -v elijah | grep -q Atychiphobe ); then
    sleep $[ ( $RANDOM % 10800 ) + 3600 ]s
    ssh pt-scm-staging-01 pkill -TERM irssi
  fi
  sleep 3600
  #sleep 600
done
