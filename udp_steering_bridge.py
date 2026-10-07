#!/usr/bin/env python3
import argparse
import socket
import time

from as5600_filter import SteeringFilter, clamp, parse_steer_packet
from keyboard_steering import KeyboardSteering
from virtual_gamepad import VirtualGamepad


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Receive AS5600 steering over UDP and expose it as a virtual "
            "gamepad left-stick X axis for SuperTuxKart."
        )
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument("--deadzone", type=float, default=0.03)
    parser.add_argument("--curve-power", type=float, default=1.15)
    parser.add_argument(
        "--smoothing",
        type=float,
        default=0.20,
        help="0 disables smoothing, larger values smooth more; max 0.99.",
    )
    parser.add_argument("--invert", action="store_true")
    parser.add_argument(
        "--backend",
        choices=("vgamepad", "keyboard"),
        default="vgamepad",
        help=(
            "vgamepad creates a virtual joystick where supported. keyboard is "
            "a macOS-friendly fallback using left/right key presses."
        ),
    )
    parser.add_argument(
        "--keyboard-threshold",
        type=float,
        default=0.08,
        help="Minimum absolute steer value before keyboard left/right is held.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.35,
        help="Center steering if no UDP packet is received for this many seconds.",
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

    steering_filter = SteeringFilter(
        deadzone=args.deadzone,
        curve_power=args.curve_power,
        smoothing=args.smoothing,
        invert=args.invert,
    )
    if args.backend == "keyboard":
        output = KeyboardSteering(threshold=args.keyboard_threshold)
        output_name = "keyboard left/right"
    else:
        output = VirtualGamepad()
        output_name = "virtual gamepad"

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(0.05)

    print(f"Listening for AS5600 steering on UDP {args.host}:{args.port}")
    print(f"Output backend: {output_name}")
    print("Expected packets: -1..1, steer=-0.25, or JSON {\"steer\": -0.25}")
    print("Press Ctrl-C to stop.")

    last_packet_time = time.monotonic()
    last_print_time = 0.0
    centered_after_timeout = False

    try:
        while True:
            now = time.monotonic()
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                if (
                    args.timeout > 0
                    and not centered_after_timeout
                    and now - last_packet_time > args.timeout
                ):
                    steering_filter.center()
                    output.center()
                    centered_after_timeout = True
                    print("No packets recently; centered steering.")
                continue

            last_packet_time = now
            centered_after_timeout = False

            try:
                raw_steer = clamp(parse_steer_packet(data))
            except Exception as exc:
                print(f"Bad packet from {addr}: {data!r} ({exc})")
                continue

            steer = steering_filter.update(raw_steer)
            output.set_steer(steer)

            if args.print_every > 0 and now - last_print_time >= args.print_every:
                print(f"from {addr[0]} raw={raw_steer:+.3f} steer={steer:+.3f}")
                last_print_time = now

    except KeyboardInterrupt:
        print("\nStopping; centering steering output.")
    finally:
        output.center()
        sock.close()


if __name__ == "__main__":
    main()
