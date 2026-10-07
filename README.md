# ESC Final Project — Steering Wheel & Pedals for SuperTuxKart

Embedded System Capstone project.

A **Raspberry Pi** reads two physical controls and streams their values over
the network as UDP packets:

- An **AS5600** magnetic rotary encoder used as a **steering wheel**.
- A **B10K** potentiometer pair used as **throttle / brake pedals**, read
  through an **MCP3008-style SPI ADC**.

A **PC running the game** receives those UDP packets and turns them into a
**virtual Xbox 360 gamepad** (via `vgamepad`) so they drive
[SuperTuxKart](https://supertuxkart.net/). A keyboard fallback is also
included.

```
  Raspberry Pi (sensors)                     PC (game)
  ----------------------                     ---------
  AS5600  --> steer_sender.py        --UDP 5005-->  udp_steering_bridge.py --> virtual gamepad (left stick X)
  B10K    --> b10k_throttle_sender.py --UDP 5006-->  thorttle.py            --> virtual gamepad (throttle/brake)
```

## Files

### Senders — run on the Raspberry Pi (read hardware, send UDP)

| File | Purpose |
|------|---------|
| `steer_sender.py` | Reads the **AS5600** steering angle over I²C, centers it, applies a deadzone and clamps it to ±`max-degrees`, then sends a steering value in `-1.0..1.0` over UDP (default port **5005**). |
| `b10k_throttle_sender.py` | Reads the **B10K** throttle (and optional brake) potentiometers through an **MCP3008** SPI ADC, normalizes them to `0.0..1.0`, and sends them over UDP (default port **5006**). Defaults to a JSON packet with `throttle`, `brake`, and raw `adc` values. |

### Receivers — run on the PC with the game (receive UDP, emit gamepad/keyboard)

| File | Purpose |
|------|---------|
| `udp_steering_bridge.py` | Listens for steering packets on UDP **5005**, runs them through `SteeringFilter`, and drives the **left-stick X axis** of a virtual gamepad. Centers steering automatically if packets stop. |
| `thorttle.py` | Listens for throttle/brake packets on UDP **5006**, filters them, and drives a virtual gamepad control (default **left-stick Y**) for acceleration/braking. Releases the pedals automatically if packets stop. |

### Helper modules — imported by `udp_steering_bridge.py` (not run directly)

| File | Purpose |
|------|---------|
| `as5600_filter.py` | `parse_steer_packet()` (decodes the UDP steering formats) and `SteeringFilter` (deadzone + response curve + smoothing). |
| `virtual_gamepad.py` | `VirtualGamepad` — thin wrapper over `vgamepad` that maps a steer value to the left-stick X axis. |
| `keyboard_steering.py` | `KeyboardSteering` — macOS-friendly fallback that holds the left/right arrow keys instead of using a virtual joystick. |

> Note: `thorttle.py` contains its own throttle filter and gamepad/keyboard
> backend classes inline, so it does not import the helper modules above.

## Requirements

**Raspberry Pi (senders):**
```bash
pip install smbus2 spidev
```
Enable I²C and SPI with `sudo raspi-config` (Interface Options).

**PC (receivers):**
```bash
pip install vgamepad          # virtual gamepad backend
pip install pynput            # only needed for --backend keyboard
```
`vgamepad` requires the **ViGEmBus** driver and is primarily a **Windows**
solution. On macOS, use `--backend keyboard` (the code warns about this).

## Usage

Make sure the Pi and PC are on the same network and note the **PC's IP
address** (used as `--host` on the Pi). Start the **receivers first**, then the
**senders**.

### 1. On the PC — start the receivers

```bash
# Steering receiver (listens on 5005)
python udp_steering_bridge.py

# Throttle/brake receiver (listens on 5006)
python thorttle.py
```

macOS / no virtual-gamepad driver:
```bash
python udp_steering_bridge.py --backend keyboard
python thorttle.py --backend keyboard
```

### 2. On the Raspberry Pi — start the senders

Replace `192.168.1.50` with your PC's IP address.

```bash
# Steering
python steer_sender.py --host 192.168.1.50 --port 5005 --debug

# Throttle / brake
python b10k_throttle_sender.py --host 192.168.1.50 --port 5006 --debug
```

### 3. Calibrate

- **Steering center:** hold the wheel straight, read the `Raw` value printed by
  `steer_sender.py --debug`, and pass it as `--center-degrees`
  (default `211.5`). Tune `--deadzone` and `--max-degrees` to taste.
- **Pedals:** read the ADC values from `b10k_throttle_sender.py --debug` at
  fully released vs. fully pressed, then set `--adc-min` / `--adc-max`
  (and `--brake-adc-min` / `--brake-adc-max`). Add `--invert` if a pedal
  reads backwards.

### 4. In SuperTuxKart

Configure the game to use the virtual gamepad. The throttle receiver defaults
to `left-stick-y`; with the default `y-button` control the **Accelerate**
binding matches STK's Xbox 360 default. If you use an axis/trigger control,
rebind **Accelerate** to that axis in STK's controller settings.

## UDP packet formats

**Steering (port 5005)** — accepted by `udp_steering_bridge.py`:
- `0.42` (plain float, `-1..1`)
- `steer=0.42`
- `{"steer": 0.42}`

**Throttle / brake (port 5006)** — accepted by `thorttle.py`:
- `0.42` (plain float throttle, `0..1`)
- `throttle=0.42`, `brake=0.12`, or `adc=358`
- `{"throttle":0.42,"brake":0.12}` (default sender format)
- `{"adc":{"throttle":358,"brake":120}}`

## Common options (both receivers)

| Option | Meaning |
|--------|---------|
| `--host` / `--port` | Address/port to listen on (default `0.0.0.0` / 5005 or 5006). |
| `--deadzone` | Ignore small inputs near rest. |
| `--curve-power` | Response curve (`>1` softer near center). |
| `--smoothing` | `0` = none, up to `0.99` = heavily smoothed. |
| `--invert` | Flip the input direction. |
| `--backend` | `vgamepad` (default) or `keyboard`. |
| `--timeout` | Center/release output if no packet arrives for this long. |
