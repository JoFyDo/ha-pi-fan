#!/usr/bin/env python3
"""Temperature-controlled PWM fan driver for a Raspberry Pi 4 on Home Assistant OS.

Reads the CPU temperature, maps it to a duty cycle with a linear fan curve and
writes it to the kernel's sysfs PWM interface (/sys/class/pwm).

Optionally a second PWM channel is used as a plain on/off output to switch the
fan's power, because a 4-pin PWM fan cannot be fully stopped via its PWM pin
(it idles at roughly 20 % instead).

Safety: whenever something goes wrong (temperature unreadable, PWM write
failing) or the add-on stops, the fan is set to 100 % and powered on.

Run with --curve to print the resulting fan curve and exit.
"""

import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

PWM_ROOT = Path(os.environ.get("PWM_SYSFS", "/sys/class/pwm"))
THERMAL_FILE = Path(
    os.environ.get("THERMAL_FILE", "/sys/class/thermal/thermal_zone0/temp")
)
OPTIONS_FILE = Path(os.environ.get("OPTIONS_FILE", "/data/options.json"))

DEFAULTS = {
    "pwm_chip": 0,
    "pwm_channel": 0,
    "pwm_frequency_hz": 25000,
    "power_switch_channel": -1,
    "min_temp": 45,
    "max_temp": 70,
    "min_duty": 20,
    "max_duty": 100,
    "off_below_temp": 40,
    "poll_interval": 5,
    "log_level": "info",
}

SMOOTHING = 0.3  # exponential moving average weight of the newest reading
MIN_DUTY_STEP = 2  # ignore duty changes smaller than this (percent)
STATUS_EVERY = 60  # seconds between info-level status lines

log = logging.getLogger("fan")


class FanError(Exception):
    """Anything that stops us from controlling the fan."""


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def load_config():
    cfg = dict(DEFAULTS)
    if OPTIONS_FILE.exists():
        try:
            cfg.update(json.loads(OPTIONS_FILE.read_text()))
        except (OSError, ValueError) as err:
            raise FanError(f"Cannot read {OPTIONS_FILE}: {err}")

    if cfg["min_temp"] >= cfg["max_temp"]:
        raise FanError("min_temp must be lower than max_temp")
    if not 0 <= cfg["min_duty"] <= cfg["max_duty"] <= 100:
        raise FanError("Need 0 <= min_duty <= max_duty <= 100")
    if cfg["power_switch_channel"] >= 0:
        if cfg["off_below_temp"] >= cfg["min_temp"]:
            raise FanError("off_below_temp must be lower than min_temp")
        if cfg["power_switch_channel"] == cfg["pwm_channel"]:
            raise FanError("power_switch_channel must differ from pwm_channel")
    return cfg


# --------------------------------------------------------------------------- #
# Sysfs PWM
# --------------------------------------------------------------------------- #
def _write(path, value):
    try:
        path.write_text(str(value))
    except OSError as err:
        raise FanError(f"Cannot write {value!r} to {path}: {err}")


class PwmChannel:
    def __init__(self, chip, channel, period_ns):
        self.chip_dir = PWM_ROOT / f"pwmchip{chip}"
        self.dir = self.chip_dir / f"pwm{channel}"
        self.channel = channel
        self.period_ns = period_ns

    def setup(self):
        if not self.chip_dir.exists():
            found = sorted(p.name for p in PWM_ROOT.glob("pwmchip*")) if PWM_ROOT.exists() else []
            raise FanError(
                f"{self.chip_dir} does not exist (found: {found or 'nothing'}). "
                "The PWM overlay is probably not enabled in config.txt - "
                "see the README, section 'Enable the PWM hardware'."
            )
        if not self.dir.exists():
            _write(self.chip_dir / "export", self.channel)
            for _ in range(50):
                if self.dir.exists():
                    break
                time.sleep(0.1)
            else:
                raise FanError(f"{self.dir} did not appear after export")
        # duty must never exceed period, so zero it before changing the period
        _write(self.dir / "duty_cycle", 0)
        _write(self.dir / "period", self.period_ns)
        _write(self.dir / "enable", 1)

    def set_percent(self, percent):
        percent = max(0.0, min(100.0, percent))
        _write(self.dir / "duty_cycle", int(round(self.period_ns * percent / 100.0)))


# --------------------------------------------------------------------------- #
# Fan logic
# --------------------------------------------------------------------------- #
def read_cpu_temp():
    try:
        return int(THERMAL_FILE.read_text().strip()) / 1000.0
    except (OSError, ValueError) as err:
        raise FanError(f"Cannot read CPU temperature from {THERMAL_FILE}: {err}")


def curve(temp, cfg):
    """Linear ramp from min_duty at min_temp to max_duty at max_temp."""
    if temp <= cfg["min_temp"]:
        return float(cfg["min_duty"])
    if temp >= cfg["max_temp"]:
        return float(cfg["max_duty"])
    frac = (temp - cfg["min_temp"]) / (cfg["max_temp"] - cfg["min_temp"])
    return cfg["min_duty"] + frac * (cfg["max_duty"] - cfg["min_duty"])


class Fan:
    def __init__(self, cfg):
        period_ns = int(round(1e9 / cfg["pwm_frequency_hz"]))
        self.cfg = cfg
        self.pwm = PwmChannel(cfg["pwm_chip"], cfg["pwm_channel"], period_ns)
        self.switch = None
        if cfg["power_switch_channel"] >= 0:
            self.switch = PwmChannel(cfg["pwm_chip"], cfg["power_switch_channel"], period_ns)
        self.duty = None
        self.powered = None

    def setup(self):
        self.pwm.setup()
        if self.switch:
            self.switch.setup()
        self.apply(100.0, True)  # start in the safe state

    def apply(self, duty, powered):
        """Set speed and power. Order matters so the fan never sees a floating/odd state."""
        if powered:
            self.pwm.set_percent(duty)  # speed first ...
            if self.switch:
                self.switch.set_percent(100)  # ... then power
        else:
            if self.switch:
                self.switch.set_percent(0)  # power off first ...
            self.pwm.set_percent(0)  # ... and park the PWM line low (no back-feeding)
        self.duty, self.powered = duty, powered

    def failsafe(self):
        try:
            self.apply(100.0, True)
        except FanError as err:
            log.error("Could not set failsafe: %s", err)


def run(cfg):
    fan = Fan(cfg)
    fan.setup()
    log.info(
        "PWM ready: chip %s channel %s @ %s Hz%s",
        cfg["pwm_chip"],
        cfg["pwm_channel"],
        cfg["pwm_frequency_hz"],
        f", power switch on channel {cfg['power_switch_channel']}" if fan.switch else ", no power switch (fan idles at min_duty)",
    )

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    smoothed = None
    last_error = None
    last_status = 0.0
    powered = True

    while not stop.is_set():
        try:
            raw = read_cpu_temp()
            smoothed = raw if smoothed is None else SMOOTHING * raw + (1 - SMOOTHING) * smoothed

            if fan.switch:
                if powered and smoothed <= cfg["off_below_temp"]:
                    powered = False
                elif not powered and smoothed >= cfg["min_temp"]:
                    powered = True

            # Emergency: raw (unsmoothed) reading at/above max_temp means full speed now.
            target = float(cfg["max_duty"]) if raw >= cfg["max_temp"] else curve(smoothed, cfg)
            if raw >= cfg["max_temp"]:
                powered = True

            changed_power = powered != fan.powered
            changed_duty = (
                fan.duty is None
                or abs(target - fan.duty) >= MIN_DUTY_STEP
                or (target in (cfg["min_duty"], cfg["max_duty"]) and target != fan.duty)
            )
            if changed_power or (powered and changed_duty):
                fan.apply(target if powered else 0.0, powered)
                log.info(
                    "temp=%.1fC -> fan %s",
                    smoothed,
                    f"{fan.duty:.0f}%" if powered else "OFF",
                )

            now = time.monotonic()
            if now - last_status >= STATUS_EVERY:
                log.info(
                    "status: cpu=%.1fC (avg %.1fC) fan=%s",
                    raw,
                    smoothed,
                    f"{fan.duty:.0f}%" if fan.powered else "OFF",
                )
                last_status = now
            else:
                log.debug("cpu=%.1fC avg=%.1fC fan=%s", raw, smoothed, fan.duty)
            last_error = None
        except FanError as err:
            if str(err) != last_error:  # don't spam the log every poll
                log.error("%s - running fan at 100%%", err)
                last_error = str(err)
            fan.failsafe()
            powered = True

        stop.wait(cfg["poll_interval"])

    log.info("Stopping - leaving fan at 100%")
    fan.failsafe()


def print_curve(cfg):
    print(f"{'CPU temp':>9}  {'fan':>5}")
    for t in range(30, 86, 5):
        if cfg["power_switch_channel"] >= 0 and t <= cfg["off_below_temp"]:
            speed = "OFF"
        else:
            speed = f"{curve(t, cfg):.0f}%"
        print(f"{t:>7}C  {speed:>5}")
    if cfg["power_switch_channel"] >= 0:
        print(
            f"(turns on at >= {cfg['min_temp']}C, off again at <= {cfg['off_below_temp']}C)"
        )


def main():
    try:
        cfg = load_config()
    except FanError as err:
        print(f"Configuration error: {err}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=getattr(logging, str(cfg["log_level"]).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if "--curve" in sys.argv:
        print_curve(cfg)
        return 0

    try:
        run(cfg)
    except FanError as err:
        log.error("%s", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
