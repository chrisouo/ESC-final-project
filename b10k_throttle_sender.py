#!/usr/bin/env python3
import argparse
import json
import socket
import time

import spidev


def clamp(value, lower=0.0, upper=1.0):
    return max(lower, min(upper, value))


def read_channel(spi, channel):
    if channel < 0 or channel > 7:
        raise ValueError("channel must be 0-7")

    adc = spi.xfer2([1, (8 + channel) << 4, 0])
    return ((adc[1] & 3) << 8) + adc[2]


def adc_to_normalized(value, adc_min=0, adc_max=1023, invert=False):
    if adc_max <= adc_min:
        raise ValueError("adc_max must be greater than adc_min")

    normalized = (float(value) - adc_min) / (adc_max - adc_min)
    normalized = clamp(normalized)
    if invert:
        normalized = 1.0 - normalized
    return normalized


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Read B10K throttle/brake potentiometers through an MCP3008-style "
            "SPI ADC and send normalized pedal values 0.0..1.0 over UDP."
        )
    )
    parser.add_argument("--host", default="127.0.0.1", help="UDP target host")
    parser.add_argument("--port", type=int, default=5006, help="UDP target port")
    parser.add_argument("--hz", type=float, default=50.0, help="Send rate")
    parser.add_argument("--bus", type=int, default=0, help="SPI bus")
    parser.add_argument("--device", type=int, default=0, help="SPI CE device")
    parser.add_argument("--channel", type=int, default=0, help="Throttle ADC channel 0-7")
    parser.add_argument("--brake-channel", type=int, default=1, help="Brake ADC channel 0-7")
    parser.add_argument("--spi-speed", type=int, default=1350000)
    parser.add_argument("--vref", type=float, default=3.3)
    parser.add_argument("--adc-min", type=float, default=0.0)
    parser.add_argument(
        "--adc-max",
        type=float,
        default=100.0,
        help="ADC value that should become full throttle.",
    )
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--brake-adc-min", type=float, default=None)
    parser.add_argument(
        "--brake-adc-max",
        type=float,
        default=None,
        help="ADC value that should become full brake. Defaults to --adc-max.",
    )
    parser.add_argument("--brake-invert", action="store_true")
    parser.add_argument(
        "--packet",
        choices=("plain", "key", "json", "adc"),
        default="json",
        help=(
            "json sends throttle and brake. plain/key keep old throttle-only "
            "formats. adc sends raw throttle/brake ADC values."
        ),
    )
    parser.add_argument("--debug", action="store_true")
    return parser


def format_packet(packet_type, throttle_adc, brake_adc, throttle, brake):
    if packet_type == "plain":
        return f"{throttle:.3f}"
    if packet_type == "key":
        return f"throttle={throttle:.3f}"
    if packet_type == "json":
        return json.dumps(
            {
                "throttle": round(throttle, 3),
                "brake": round(brake, 3),
                "adc": {
                    "throttle": throttle_adc,
                    "brake": brake_adc,
                },
            },
            separators=(",", ":"),
        )
    if packet_type == "adc":
        return f"throttle_adc={throttle_adc},brake_adc={brake_adc}"
    raise ValueError(f"unknown packet type {packet_type!r}")


def main():
    args = build_parser().parse_args()
    delay = 1.0 / max(args.hz, 0.1)
    brake_adc_min = args.adc_min if args.brake_adc_min is None else args.brake_adc_min
    brake_adc_max = args.adc_max if args.brake_adc_max is None else args.brake_adc_max

    spi = spidev.SpiDev()
    spi.open(args.bus, args.device)
    spi.max_speed_hz = args.spi_speed

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (args.host, args.port)

    print(f"Sending B10K throttle/brake to UDP {args.host}:{args.port}")
    print(
        f"Throttle ADC channel {args.channel}, map "
        f"{args.adc_min:g}..{args.adc_max:g} to throttle 0.0..1.0"
    )
    print(
        f"Brake ADC channel {args.brake_channel}, map "
        f"{brake_adc_min:g}..{brake_adc_max:g} to brake 0.0..1.0"
    )
    print("Press Ctrl-C to stop.")

    try:
        while True:
            throttle_adc = read_channel(spi, args.channel)
            brake_adc = read_channel(spi, args.brake_channel)
            throttle = adc_to_normalized(
                throttle_adc,
                adc_min=args.adc_min,
                adc_max=args.adc_max,
                invert=args.invert,
            )
            brake = adc_to_normalized(
                brake_adc,
                adc_min=brake_adc_min,
                adc_max=brake_adc_max,
                invert=args.brake_invert,
            )
            message = format_packet(
                args.packet,
                throttle_adc,
                brake_adc,
                throttle,
                brake,
            )
            sock.sendto(message.encode("ascii"), target)

            if args.debug:
                throttle_voltage = throttle_adc * args.vref / 1023.0
                brake_voltage = brake_adc * args.vref / 1023.0
                print(
                    f"Throttle ADC: {throttle_adc:4d}, "
                    f"V: {throttle_voltage:4.2f}, "
                    f"Throttle: {throttle:5.3f} | "
                    f"Brake ADC: {brake_adc:4d}, "
                    f"V: {brake_voltage:4.2f}, "
                    f"Brake: {brake:5.3f} | Send: {message}"
                )

            time.sleep(delay)

    except KeyboardInterrupt:
        print("Exiting...")
    finally:
        try:
            sock.sendto(b'{"throttle":0.0,"brake":0.0}', target)
        finally:
            sock.close()
            spi.close()


if __name__ == "__main__":
    main()
