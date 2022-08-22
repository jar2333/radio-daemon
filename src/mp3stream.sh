#!/bin/bash

ICECAST_MOUNT=test.ogg
ICECAST_PORT=4000
ICECAST_PASSWORD=VBK7KrDWD3ZQ

BITRATE=256k
CHANNELS=2

NEW_MOUNT=test

while true; 
do { 
    ffmpeg -i http://localhost:$ICECAST_PORT/$ICECAST_MOUNT \
    -codec:a libmp3lame \
    -ab $BITRATE \
    -ac $CHANNELS \
    -content_type audio/mpeg \
    -f mp3 \
    icecast://source:$ICECAST_PASSWORD@localhost:$ICECAST_PORT/$NEW_MOUNT
} || { 
    echo "sleeping..." && sleep 60 
}
done