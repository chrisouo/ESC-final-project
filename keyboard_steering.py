import time


class KeyboardSteering:
    """Mac-friendly fallback that maps steering to left/right key holds.

    This is not a true analog joystick. It uses thresholds so stronger wheel
    turns hold the direction key, while small turns release both keys.
    """

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
        self._threshold = max(0.0, min(0.95, float(threshold)))
        self._state = 0

    def set_steer(self, steer):
        steer = max(-1.0, min(1.0, float(steer)))
        if steer < -self._threshold:
            next_state = -1
        elif steer > self._threshold:
            next_state = 1
        else:
            next_state = 0

        if next_state == self._state:
            return

        self._release_all()
        time.sleep(0.002)

        if next_state < 0:
            self._keyboard.press(self._key.left)
        elif next_state > 0:
            self._keyboard.press(self._key.right)

        self._state = next_state

    def center(self):
        self._release_all()
        self._state = 0

    def _release_all(self):
        self._keyboard.release(self._key.left)
        self._keyboard.release(self._key.right)
