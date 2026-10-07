#!/usr/bin/env python3
import argparse
import json
import socket
import time


def clamp(value, lower=0.0, upper=1.0):
    return max(lower, min(upper, value))


def map_adc_to_pedal(adc, adc_min=0, adc_max=400):
    if adc_max <= adc_min:
        raise ValueError("adc_max must be greater than adc_min")
    return clamp((float(adc) - adc_min) / (adc_max - adc_min))


def parse_pedal_packet(data, adc_min=0, adc_max=400):
    """Parse UDP packets containing throttle/brake or raw ADC data.

    Supported formats:
      - "0.42"
      - "throttle=0.42"
      - "brake=0.42"
      - "adc=358"
      - {"throttle": 0.42, "brake": 0.12}
      - {"adc": 358}
      - {"adc": {"throttle": 358, "brake": 120}}
    """
    text = data.decode("ascii", errors="replace").strip()
    if not text:
        raise ValueError("empty packet")

    if text.startswith("{"):
        payload = json.loads(text)
        throttle = 0.0
        brake = 0.0
        if "throttle" in payload:
            throttle = clamp(float(payload["throttle"]))
        if "brake" in payload:
            brake = clamp(float(payload["brake"]))
        if "adc" in payload:
            adc = payload["adc"]
            if isinstance(adc, dict):
                if "throttle" in adc and "throttle" not in payload:
                    throttle = map_adc_to_pedal(adc["throttle"], adc_min, adc_max)
                if "brake" in adc and "brake" not in payload:
                    brake = map_adc_to_pedal(adc["brake"], adc_min, adc_max)
            elif "throttle" not in payload:
                throttle = map_adc_to_pedal(adc, adc_min, adc_max)
        if "throttle" not in payload and "brake" not in payload and "adc" not in payload:
            raise ValueError("JSON packet needs throttle, brake, or adc")
        return throttle, brake

    if "=" in text:
        throttle = 0.0
        brake = 0.0
        for part in text.split(","):
            key, value = part.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key in ("throttle", "t"):
                throttle = clamp(float(value))
            elif key == "brake":
                brake = clamp(float(value))
            elif key == "adc":
                throttle = map_adc_to_pedal(float(value), adc_min, adc_max)
            elif key == "throttle_adc":
                throttle = map_adc_to_pedal(float(value), adc_min, adc_max)
            elif key == "brake_adc":
                brake = map_adc_to_pedal(float(value), adc_min, adc_max)
            else:
                raise ValueError(f"unknown packet key {key!r}")
        return throttle, brake

    return clamp(float(text)), 0.0


def apply_deadzone(value, deadzone):
    value = clamp(value)
    deadzone = clamp(deadzone, 0.0, 0.95)
    if value <= deadzone:
        return 0.0
    return (value - deadzone) / (1.0 - deadzone)


def apply_curve(value, power):
    value = clamp(value)
    power = max(0.1, float(power))
    return value ** power


class ThrottleFilter:
    def __init__(self, deadzone=0.02, curve_power=1.0, smoothing=0.15,
                 invert=False):
        self.deadzone = deadzone
        self.curve_power = curve_power
        self.smoothing = clamp(smoothing, 0.0, 0.99)
        self.invert = invert
        self._value = 0.0

    def update(self, raw_value):
        value = clamp(float(raw_value))
        if self.invert:
            value = 1.0 - value

        value = apply_deadzone(value, self.deadzone)
        value = apply_curve(value, self.curve_power)

        alpha = 1.0 - self.smoothing
        self._value = self._value * self.smoothing + value * alpha
        if self._value < 0.0005:
            self._value = 0.0
        return clamp(self._value)

    def release(self):
        self._value = 0.0
        return self._value


class VirtualGamepadThrottle:
    def __init__(self, control="y-button", button_threshold=0.08,
                 axis_floor=0.0):
        try:
            import vgamepad as vg
        except ImportError as exc:
            raise RuntimeError(
                "Missing Python package 'vgamepad'. Install it in the Python "
                "environment running this script. On Windows this also needs "
                "the ViGEmBus driver."
            ) from exc

        self._vg = vg
        self._gamepad = vg.VX360Gamepad()
        self._control = control
        self._button_threshold = clamp(button_threshold, 0.0, 0.95)
        self._axis_floor = clamp(axis_floor, 0.0, 0.95)
        self._button_pressed = False
        self._last = None

    def set_throttle(self, throttle):
        self.set_pedals(throttle, 0.0)

    def set_pedals(self, throttle, brake):
        throttle = clamp(float(throttle))
        brake = clamp(float(brake))
        next_state = (throttle, brake)
        if (
            self._last is not None
            and abs(throttle - self._last[0]) < 0.0001
            and abs(brake - self._last[1]) < 0.0001
        ):
            return

        if self._control == "y-button":
            self._set_y_button(throttle)
        elif self._control == "left-trigger":
            self._set_trigger("left", throttle)
        elif self._control == "right-trigger":
            self._set_trigger("right", throttle)
        elif self._control == "left-stick-y":
            throttle_axis = self._apply_axis_floor(throttle)
            brake_axis = self._apply_axis_floor(brake)
            axis_value = throttle_axis - brake_axis
            self._gamepad.left_joystick_float(
                x_value_float=0.0,
                y_value_float=axis_value,
            )
        else:
            raise ValueError(f"unknown vgamepad control {self._control!r}")

        self._gamepad.update()
        self._last = next_state

    def release(self):
        self.set_pedals(0.0, 0.0)
        if self._button_pressed:
            self._gamepad.release_button(
                button=self._vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
            )
            self._gamepad.update()
            self._button_pressed = False

    def _set_trigger(self, side, throttle):
        float_name = f"{side}_trigger_float"
        byte_name = f"{side}_trigger"

        if hasattr(self._gamepad, float_name):
            getattr(self._gamepad, float_name)(value_float=throttle)
        elif hasattr(self._gamepad, byte_name):
            getattr(self._gamepad, byte_name)(value=int(round(throttle * 255)))
        else:
            raise RuntimeError(f"vgamepad does not expose {side} trigger methods")

    def _apply_axis_floor(self, value):
        if value > 0.0 and self._axis_floor > 0.0:
            return self._axis_floor + value * (1.0 - self._axis_floor)
        return value

    def _set_y_button(self, throttle):
        should_press = throttle > self._button_threshold
        if should_press == self._button_pressed:
            return

        if should_press:
            self._gamepad.press_button(
                button=self._vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
            )
        else:
            self._gamepad.release_button(
                button=self._vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
            )
        self._button_pressed = should_press


class KeyboardThrottle:
    def __init__(self, threshold=0.08):
        try:
            from pynput.keyboard import Controller, Key
        except ImportError as exc:
            raise RuntimeError(
                "Missing Python package 'pynput'. Install it with "
                "'pip install pynput' to use --backend keyboard."
            ) from exc

        self._keyboard = Controller()
        self._key = Key
        self._threshold = clamp(threshold, 0.0, 0.95)
        self._pressed = False

    def set_throttle(self, throttle):
        self.set_pedals(throttle, 0.0)

    def set_pedals(self, throttle, brake):
        should_press = clamp(float(throttle)) > self._threshold
        if should_press == self._pressed:
            return

        if should_press:
            self._keyboard.press(self._key.up)
        else:
            self._keyboard.release(self._key.up)
        self._pressed = should_press

    def release(self):
        self._keyboard.release(self._key.up)
        self._pressed = False


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Receive B10K throttle/brake over UDP and expose it as a virtual "
            "gamepad control for SuperTuxKart."
        )
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5006)
    parser.add_argument("--adc-min", type=float, default=0.0)
    parser.add_argument("--adc-max", type=float, default=100.0)
    parser.add_argument("--deadzone", type=float, default=0.0)
    parser.add_argument("--curve-power", type=float, default=1.0)
    parser.add_argument(
        "--smoothing",
        type=float,
        default=0.15,
        help="0 disables smoothing, larger values smooth more; max 0.99.",
    )
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--brake-invert", action="store_true")
    parser.add_argument(
        "--backend",
        choices=("vgamepad", "keyboard"),
        default="vgamepad",
        help="keyboard is only digital; vgamepad preserves analog throttle.",
    )
    parser.add_argument(
        "--vgamepad-control",
        choices=("y-button", "right-trigger", "left-trigger", "left-stick-y"),
        default="left-stick-y",
        help=(
            "Virtual control to move. y-button matches STK's Xbox 360 default "
            "shown in the controls screen. Axis/trigger options are analog, "
            "but STK Accelerate must be rebound to that axis/trigger."
        ),
    )
    parser.add_argument(
        "--button-threshold",
        type=float,
        default=0.08,
        help="Minimum throttle before y-button is held.",
    )
    parser.add_argument(
        "--axis-floor",
        type=float,
        default=0.13,
        help=(
            "Minimum non-zero left-stick-y output. STK's default gamepad "
            "deadzone is about 0.125, so 0.13 lets small throttle values "
            "survive STK's deadzone."
        ),
    )
    parser.add_argument(
        "--keyboard-threshold",
        type=float,
        default=0.08,
        help="Minimum throttle before keyboard up is held.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.35,
        help="Release throttle if no UDP packet is received for this many seconds.",
    )
    parser.add_argument(
        "--print-every",
        type=float,
        default=0.10,
        help="Seconds between debug print lines. Use 0 to disable.",
    )
    return parser


def main():
    args = build_parser().parse_args()

    throttle_filter = ThrottleFilter(
        deadzone=args.deadzone,
        curve_power=args.curve_power,
        smoothing=args.smoothing,
        invert=args.invert,
    )
    brake_filter = ThrottleFilter(
        deadzone=args.deadzone,
        curve_power=args.curve_power,
        smoothing=args.smoothing,
        invert=args.brake_invert,
    )

    if args.backend == "keyboard":
        output = KeyboardThrottle(threshold=args.keyboard_threshold)
        output_name = "keyboard up arrow"
    else:
        output = VirtualGamepadThrottle(
            control=args.vgamepad_control,
            button_threshold=args.button_threshold,
            axis_floor=args.axis_floor,
        )
        output_name = f"virtual gamepad {args.vgamepad_control}"

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(0.05)

    print(f"Listening for B10K throttle/brake on UDP {args.host}:{args.port}")
    print(f"Output backend: {output_name}")
    print('Expected packets: {"throttle":0.5,"brake":0.0}, throttle=0.5, or 0..1.')
    print("Press Ctrl-C to stop.")

    last_packet_time = time.monotonic()
    last_print_time = 0.0
    released_after_timeout = False

    try:
        while True:
            now = time.monotonic()
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                if (
                    args.timeout > 0
                    and not released_after_timeout
                    and now - last_packet_time > args.timeout
                ):
                    throttle_filter.release()
                    brake_filter.release()
                    output.release()
                    released_after_timeout = True
                    print("No packets recently; released pedals.")
                continue

            last_packet_time = now
            released_after_timeout = False

            try:
                raw_throttle, raw_brake = parse_pedal_packet(
                    data,
                    adc_min=args.adc_min,
                    adc_max=args.adc_max,
                )
            except Exception as exc:
                print(f"Bad packet from {addr}: {data!r} ({exc})")
                continue

            throttle = throttle_filter.update(raw_throttle)
            brake = brake_filter.update(raw_brake)
            output.set_pedals(throttle, brake)

            if args.print_every > 0 and now - last_print_time >= args.print_every:
                print(
                    f"from {addr[0]} "
                    f"raw_throttle={raw_throttle:.3f} throttle={throttle:.3f} "
                    f"raw_brake={raw_brake:.3f} brake={brake:.3f}"
                )
                last_print_time = now

    except KeyboardInterrupt:
        print("\nStopping; releasing throttle output.")
    finally:
        output.release()
        sock.close()


if __name__ == "__main__":
    main()
