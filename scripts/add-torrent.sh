#!/bin/sh

# Example script called to add a torrent. 
# The path to the torrent file is provided as the first argument

transmission-remote -n transmission:transmission -a $1

