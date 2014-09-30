#!/bin/sh
root=$(readlink -f $(dirname $0)/..)
image=${1}
sock=/tmp/.X11-unix/X0

if [ -z "$image" ]; then
    echo "Usage: $0 docker-image-name" 1>&2
    exit 1
fi

shift
##xhost +si:localuser:$USER <-- is this needed?
##docker run --rm -it -e DISPLAY=$DISPLAY -v $sock:$sock:ro -v $root:/app $image /app/memgraphinator.py "$@"

# XXX: this fails with a BadAccess error due to some weird shared memory magic;
# running the app four times in the same container is the workaround, but it is
# hard to script :(

docker run --rm -it -e DISPLAY=$DISPLAY -v $sock:$sock:ro -v $root:/app $image bash
