#!/usr/bin/with-contenv bashio
bashio::log.info "Starting Pi Fan Control"
mount -o remount,rw /sys
exec python3 -u /fan_control.py
