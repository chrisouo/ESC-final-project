import json
import math


def clamp(value, lower=-1.0, upper=1.0):
    return max(lower, min(upper, value))


def parse_steer_packet(data):
    """Parse ASCII UDP packets containing a steer value in [-1, 1].

    Supported formats:
      - "0.42"
      - "steer=0.42"
      - {"steer": 0.42}
    """
    text = data.decode("ascii", errors="replace").strip()
    if not text:
        raise ValueError("empty packet")

    if text.startswith("{"):
        payload = json.loads(text)
        return float(payload["steer"])

    if "=" in text:
        key, value = text.split("=", 1)
        if key.strip().lower() != "steer":
            raise ValueError(f"unknown packet key {key!r}")
        return float(value.strip())

    return float(text)


def apply_deadzone(value, deadzone):
    value = clamp(value)
    deadzone = clamp(deadzone, 0.0, 0.95)
    magnitude = abs(value)
    if magnitude <= deadzone:
        return 0.0
    scaled = (magnitude - deadzone) / (1.0 - deadzone)
    return math.copysign(scaled, value)


def apply_curve(value, power):
    value = clamp(value)
    power = max(0.1, power)
    return math.copysign(abs(value) ** power, value)


class SteeringFilter:
    def __init__(self, deadzone=0.03, curve_power=1.15, smoothing=0.25,
                 invert=False):
        self.deadzone = deadzone
        self.curve_power = curve_power
        self.smoothing = clamp(smoothing, 0.0, 0.99)
        self.invert = invert
        self._value = 0.0

    def update(self, raw_value):
        value = clamp(float(raw_value))
        if self.invert:
            value = -value

        value = apply_deadzone(value, self.deadzone)
        value = apply_curve(value, self.curve_power)

        alpha = 1.0 - self.smoothing
        self._value = self._value * self.smoothing + value * alpha
        if abs(self._value) < 0.0005:
            self._value = 0.0
        return clamp(self._value)

    def center(self):
        self._value = 0.0
        return self._value
