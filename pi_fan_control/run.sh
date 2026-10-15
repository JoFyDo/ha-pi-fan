#!/usr/bin/with-contenv bashio
bashio::log.info "Starting Pi Fan Control"
exec python3 -u /fan_control.py
