#!/usr/bin/env python3
"""driver-venus entrypoint."""

from __future__ import annotations

import argparse
import logging

from driver_venus.config import load_config
from driver_venus.driver_info import load_driver_info
from driver_venus.publisher import Publisher
from driver_venus.subscriber import Subscriber


def main() -> None:
    parser = argparse.ArgumentParser(
        description="driver-venus: Victron Venus OS MQTT -> renewvan bus (battery, solar, charger)"
    )
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    config = load_config()
    # Version is stamped by the release build (DRIVER_VERSION); unset reports "dev".
    # Board serial is read once, here, at process start.
    publisher = Publisher(config.mqtt, load_driver_info())
    publisher.connect()
    subscriber = Subscriber(config, publisher)
    try:
        subscriber.run_forever()
    finally:
        publisher.disconnect()


if __name__ == "__main__":
    main()
