ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM $BUILD_FROM

RUN apk add --no-cache python3

COPY run.sh /run.sh
COPY fan_control.py /fan_control.py
RUN chmod a+x /run.sh

LABEL io.hass.type="app"

CMD [ "/run.sh" ]
