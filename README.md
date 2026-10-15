# Pi Fan Control (Home Assistant add-on)

Temperature-controlled PWM fan for a **Raspberry Pi 4 running Home Assistant OS**,
using a **Noctua 4-pin 5 V PWM fan**. The add-on reads the CPU temperature and drives
the Pi's hardware PWM at 25 kHz along a configurable fan curve.

> Status: written and logic-tested against a simulated sysfs, but **not yet tested on real
> HAOS hardware**. Whether the add-on can write to `/sys/class/pwm` depends on your HAOS
> version and kernel. See [Troubleshooting](#troubleshooting).

## What you need

- Raspberry Pi 4 with Home Assistant OS (64-bit, `aarch64`)
- A **5 V** Noctua PWM fan, e.g. NF-A4x10 5V PWM or NF-A4x20 5V PWM.
  A 12 V fan will not run properly from the Pi's 5 V pin.
- Jumper wires (Dupont female for the GPIO header)
- *Optional, for a true "off":* a few cheap parts, see [Build B](#build-b-fan-can-switch-fully-off)

## Which build do you want?

| | Build A: simple | Build B: true off |
|---|---|---|
| Fan below `min_temp` | idles at `min_duty` (about 20 %, nearly silent) | **completely off** |
| Parts | fan only | fan + 1 NPN transistor + 1 P-MOSFET + 2 resistors |
| PWM pins used | GPIO12 | GPIO12 + GPIO13 |

A 4-pin Noctua cannot be stopped through its PWM pin (it idles at roughly 20 % at 0 % duty),
which is why Build B switches the fan's power instead. Start with Build A. You can add the
switch later.

## Wiring

### Noctua connector pinout

```
Pin 1  black   GND
Pin 2  yellow  +5 V (power)
Pin 3  green   tach / RPM   (not used by this add-on, leave unconnected)
Pin 4  blue    PWM control
```

### Raspberry Pi 4 header pins used (physical pin numbers)

```
 (pin 1 = 3V3)  1 o o  2  = 5V
                3 o o  4  = 5V          <- fan +5 V
                5 o o  6  = GND         <- fan GND
                7 o o  8
                9 o o  10
               11 o o  12
               13 o o  14
               15 o o  16
               17 o o  18
               19 o o  20
               21 o o  22
               23 o o  24
               25 o o  26
               27 o o  28
               29 o o  30
               31 o o  32 = GPIO12      <- PWM0 (fan speed)
               33 o o  34
                       (33 = GPIO13 = PWM1, only for Build B)
```

### Build A: simple

| Fan pin | Connect to |
|---|---|
| 1 black (GND) | Pi pin 6 (GND) |
| 2 yellow (+5 V) | Pi pin 4 (5 V) |
| 3 green (tach) | not connected |
| 4 blue (PWM) | Pi pin 32 (GPIO12) |

The Noctua PWM input accepts 3.3 V logic, so no level shifter is needed.
Check your fan's datasheet for its current draw. A 5 V Noctua is far below what the 5 V pin can
supply with a proper power supply.

### Build B: fan can switch fully off

The fan's **power** is switched on the *high side* (the +5 V line) so the fan's ground
stays permanently at Pi ground. Do not switch the ground side: the fan's PWM input would then
be referenced to a floating ground and could push current back into the Pi's GPIO.

Parts: NPN transistor (2N3904, BC547 or 2N2222), P-channel logic-level MOSFET
(IRLML6402 or AO3401, both SOT-23, so you'll want a breakout board or some careful
soldering), 1 kΩ resistor, 10 kΩ resistor.

Connections (every line is one wire or component):

| From | Through | To |
|---|---|---|
| Pi 5 V (pin 4) | | MOSFET **source** |
| Pi 5 V (pin 4) | 10 kΩ resistor | MOSFET **gate** |
| MOSFET **gate** | | NPN **collector** |
| NPN **emitter** | | Pi GND (pin 6) |
| Pi GPIO13 (pin 33) | 1 kΩ resistor | NPN **base** |
| MOSFET **drain** | | Fan pin 2 (yellow, +5 V) |
| Fan pin 1 (black, GND) | | Pi GND (pin 6) |
| Fan pin 4 (blue, PWM) | | Pi GPIO12 (pin 32) |
| Fan pin 3 (green, tach) | | not connected |

```
   Pi 5V ──┬──────────┬──[10k]──┐
           │          │         │
          (S)        (G)────────┴─── NPN collector
         P-MOSFET     │                │
          (D)         │             NPN base ──[1k]── Pi GPIO13
           │          │                │
           ▼          │            NPN emitter ── Pi GND
      Fan yellow      │
                      (gate node is shared by the 10k, the MOSFET gate and the NPN collector)
```

How it works: GPIO13 high turns the NPN on, which pulls the MOSFET gate to ground, which turns
the P-MOSFET on and powers the fan. GPIO13 low means the 10 kΩ resistor holds the gate at
5 V, so the MOSFET is off and the fan is unpowered. When the add-on switches the fan off it also
parks GPIO12 low, so the unpowered fan isn't fed through its PWM pin.

**Double-check the MOSFET pinout in its datasheet before powering up.** SOT-23 pin order varies
between parts.

(Alternative: a ready-made 5 V relay or MOSFET "load switch" module driven from GPIO13 works too,
as long as it's wired high-side and works with 3.3 V logic.)

## Enable the PWM hardware

HAOS doesn't expose PWM by default. You need a device-tree overlay in `config.txt` on the boot
partition.

**Build A** (one channel on GPIO12):

```
dtoverlay=pwm,pin=12,func=4
```

**Build B** (two channels, GPIO12 and GPIO13):

```
dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
```

How to edit `config.txt` on HAOS depends on your version. The documented routes are a USB stick
labelled `CONFIG` or SSH on port 22222 to the host. Check the current Home Assistant OS docs for
the exact procedure. Then reboot.

Verify: from the host shell (SSH port 22222), `ls /sys/class/pwm/` should show `pwmchip0`.
If it doesn't, the overlay isn't applied or the kernel lacks the driver.

## Install the add-on

### Option 1: local add-on (best for the first test)

1. Install the **Samba share** or **Advanced SSH & Web Terminal** add-on.
2. Copy the `pi_fan_control` folder to `/addons/pi_fan_control/`.
3. Settings → Add-ons → Add-on Store → ⋮ → **Check for updates**.
4. Open **Pi Fan Control** under *Local add-ons* → Install → Start.
5. Check the **Log** tab. You should see `PWM ready` and then lines like `temp=47.1C -> fan 27%`.

After editing code, rebuild from the add-on page.

### Option 2: from a git repository

1. Edit `repository.yaml` (name, URL) and push this repo to GitHub.
2. Settings → Add-ons → Add-on Store → ⋮ → Repositories → paste the repo URL.
3. Install **Pi Fan Control** from the store.

`config.yaml` deliberately has no `image:` key, so the Pi builds the add-on itself.

## Configuration

| Option | Default | Meaning |
|---|---|---|
| `pwm_chip` | 0 | `pwmchipN` in `/sys/class/pwm/` |
| `pwm_channel` | 0 | Channel of the fan's PWM line (GPIO12 = channel 0) |
| `pwm_frequency_hz` | 25000 | Noctua spec is 25 kHz |
| `power_switch_channel` | -1 | `-1` = Build A. Set to `1` for Build B (GPIO13) |
| `min_temp` | 45 | Temperature where the fan starts, at `min_duty` |
| `max_temp` | 70 | Temperature at which the fan reaches `max_duty` |
| `min_duty` | 20 | Lowest fan speed in %. Noctua fans don't go below about 20 % |
| `max_duty` | 100 | Highest fan speed in % |
| `off_below_temp` | 40 | Build B only: fan switches off at or below this (must be below `min_temp`) |
| `poll_interval` | 5 | Seconds between temperature readings |
| `log_level` | info | `debug` prints every reading |

Between `min_temp` and `max_temp` the speed rises linearly. Example with the defaults:
45 °C → 20 %, 57 °C → 60 %, 70 °C → 100 %. (The Pi 4 starts throttling at 80 °C.)

To preview your curve, run `python3 fan_control.py --curve` (it reads the options file, or the
defaults when run outside HA).

Temperature readings are smoothed, and tiny speed changes are ignored, so the fan doesn't
hunt. Build B turns on at `min_temp` and off at `off_below_temp`, which gives a hysteresis gap.

## Safety behaviour

The add-on sets the fan to **100 % and powered on** when:

- the add-on starts (until the first reading),
- the CPU temperature can't be read,
- a PWM write fails,
- the CPU reaches `max_temp` (unsmoothed reading),
- the add-on is stopped or restarted.

If the whole Pi hangs, nothing can help, but the fan keeps its last setting.

## Troubleshooting

**`pwmchip0 does not exist`**: the overlay isn't active. Check the `config.txt` line, reboot,
and run `ls /sys/class/pwm/` on the host. If the directory is missing even with the overlay,
the HAOS kernel may not include the PWM driver. In that case use the ESP32/ESPHome route or the
GPIO on/off approach instead.

**`Cannot write ... Permission denied` / `Read-only file system`**: the container can't write to
sysfs. Make sure `full_access: true` and `apparmor: false` are still in `config.yaml`, then
rebuild. Also check the add-on's protection settings in HA.

**Fan runs full speed all the time**: either the PWM wire isn't reaching GPIO12 (a floating Noctua
PWM input means full speed), or the add-on is in failsafe. Read the log.

**Fan never stops in Build A**: expected, see "Which build do you want?".

**Different chip number**: if `ls /sys/class/pwm/` shows something other than `pwmchip0`, set
`pwm_chip` accordingly.

**Fan makes a faint whine at low speed**: try raising `min_duty` a little.

## Files

```
repository.yaml            repository manifest for the add-on store
pi_fan_control/
  config.yaml              add-on manifest and options
  Dockerfile               Alpine + Python 3 (no pip packages needed)
  run.sh                   entrypoint
  fan_control.py           the controller
  DOCS.md                  text shown on the add-on's Documentation tab
```
