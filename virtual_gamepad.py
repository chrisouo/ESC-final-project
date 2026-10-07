class VirtualGamepad:
    """Small wrapper around the same vgamepad technique used by the chair demo."""

    def __init__(self):
        try:
            import vgamepad as vg
        except ImportError as exc:
            raise RuntimeError(
                "Missing Python package 'vgamepad'. Install it in the Python "
                "environment running this script. Note: vgamepad/ViGEm is "
                "mainly a Windows virtual-controller solution; on macOS you "
                "may need a different virtual HID driver or make the Pi/Pico "
                "act as a USB HID joystick."
            ) from exc

        self._gamepad = vg.VX360Gamepad()
        self._last = None

    def set_steer(self, steer):
        steer = max(-1.0, min(1.0, float(steer)))
        if self._last is not None and abs(steer - self._last) < 0.0001:
            return

        self._gamepad.left_joystick_float(
            x_value_float=steer,
            y_value_float=0.0,
        )
        self._gamepad.update()
        self._last = steer

    def center(self):
        self.set_steer(0.0)
