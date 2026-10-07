import argparse
import smbus2
import socket
import time

# Define I2C address and bus
AS5600_ADDR = 0x36
STATUS_REG = 0x0B
RAW_ANGLE_REG = 0x0C
ANGLE_REG = 0x0E
AGC_REG = 0x1A
MAGNITUDE_REG = 0x1B

bus = smbus2.SMBus(1)

def read_12bit(register):
    raw_data = bus.read_i2c_block_data(AS5600_ADDR, register, 2)
    return ((raw_data[0] << 8) | raw_data[1]) & 0x0FFF

def raw_to_degrees(raw_angle):
    return (raw_angle / 4096.0) * 360.0

def read_sensor():
    raw_angle = read_12bit(RAW_ANGLE_REG)
    angle = read_12bit(ANGLE_REG)
    status = bus.read_byte_data(AS5600_ADDR, STATUS_REG)
    agc = bus.read_byte_data(AS5600_ADDR, AGC_REG)
    magnitude = read_12bit(MAGNITUDE_REG)

    return {
        "raw_angle": raw_angle,
        "raw_degrees": raw_to_degrees(raw_angle),
        "angle": raw_to_degrees(angle),
        "magnet_detected": bool(status & 0x20),
        "magnet_too_weak": bool(status & 0x10),
        "magnet_too_strong": bool(status & 0x08),
        "agc": agc,
        "magnitude": magnitude,
    }

def centered_degrees(raw_degrees, center_degrees=211.5):
    # AS5600 wraps around at 360 degrees. Shift the physical center to 0,
    # then wrap to -180..180 so both sides of center behave continuously.
    return ((raw_degrees - center_degrees + 180.0) % 360.0) - 180.0

def angle_to_steering(raw_degrees, center_degrees=211.5, deadzone=5.0,
                      max_degrees=45.0):
    signed_degrees = centered_degrees(raw_degrees, center_degrees)

    if signed_degrees > max_degrees:
        signed_degrees = max_degrees
    elif signed_degrees < -max_degrees:
        signed_degrees = -max_degrees

    if abs(signed_degrees) <= deadzone:
        return 0.0

    direction = 1.0 if signed_degrees > 0.0 else -1.0
    value = (abs(signed_degrees) - deadzone) / (max_degrees - deadzone)
    return direction * min(value, 1.0)

def parse_args():
    parser = argparse.ArgumentParser(
        description="Read AS5600 as a steering wheel and send -1.0..1.0 over UDP."
    )
    parser.add_argument("--host", default="127.0.0.1", help="UDP target host")
    parser.add_argument("--port", type=int, default=5005, help="UDP target port")
    parser.add_argument("--hz", type=float, default=50.0, help="Send rate")
    parser.add_argument("--center-degrees", type=float, default=211.5, help="Raw AS5600 angle that means steering center")
    parser.add_argument("--deadzone", type=float, default=5.0, help="Center deadzone in degrees")
    parser.add_argument("--max-degrees", type=float, default=45.0, help="Full steering angle")
    parser.add_argument("--debug", action="store_true", help="Print sensor diagnostics")
    return parser.parse_args()

try:
    args = parse_args()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    delay = 1.0 / args.hz

    while True:
        sensor = read_sensor()
        steering = angle_to_steering(
            sensor["raw_degrees"],
            center_degrees=args.center_degrees,
            deadzone=args.deadzone,
            max_degrees=args.max_degrees,
        )
        message = f"{steering:.3f}"
        sock.sendto(message.encode("ascii"), (args.host, args.port))

        if args.debug:
            centered = centered_degrees(sensor["raw_degrees"], args.center_degrees)
            print(
                f"Send: {message:>7} | "
                f"Raw: {sensor['raw_degrees']:7.2f} deg | "
                f"Centered: {centered:7.2f} deg | "
                f"Magnet: {'OK' if sensor['magnet_detected'] else 'NO'} | "
                f"Weak: {'YES' if sensor['magnet_too_weak'] else 'NO'} | "
                f"Strong: {'YES' if sensor['magnet_too_strong'] else 'NO'} | "
                f"AGC: {sensor['agc']:3d} | "
                f"Magnitude: {sensor['magnitude']:4d}"
            )

        time.sleep(delay)
except KeyboardInterrupt:
    print("Exiting...")
