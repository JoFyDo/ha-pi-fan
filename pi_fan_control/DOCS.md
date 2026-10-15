# Pi Fan Control

Drives a 4-pin PWM fan (for example a 5 V Noctua) from the Raspberry Pi's hardware PWM,
following the CPU temperature.

**Before starting the add-on** you must enable the PWM overlay in `config.txt` and wire the fan.
The full wiring diagrams and the overlay lines are in the README of the repository.

## Options

| Option | Meaning |
|---|---|
| `pwm_chip` / `pwm_channel` | Which `/sys/class/pwm/pwmchipN/pwmM` to use (default 0 / 0 = GPIO12) |
| `pwm_frequency_hz` | PWM frequency, 25000 for Noctua |
| `power_switch_channel` | `-1` = no power switch. `1` = GPIO13 switches the fan's power so it can turn fully off |
| `min_temp`, `max_temp` | Fan curve: starts at `min_temp`, reaches full speed at `max_temp` |
| `min_duty`, `max_duty` | Fan speed limits in percent |
| `off_below_temp` | With a power switch: fan turns off at or below this temperature |
| `poll_interval` | Seconds between readings |
| `log_level` | `debug`, `info`, `warning` or `error` |

The fan is forced to 100 % if the temperature can't be read, a PWM write fails, the CPU reaches
`max_temp`, or the add-on stops.
