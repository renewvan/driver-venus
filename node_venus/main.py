#!/usr/bin/env python3
"""node-venus entrypoint."""

from __future__ import annotations

import argparse
import logging

from node_venus.config import load_config
from node_venus.publisher import Publisher
from node_venus.subscriber import Subscriber


def main() -> None:
    parser = argparse.ArgumentParser(
        description="node-venus: Victron Venus OS MQTT -> renewvan bus (battery, solar, charger)"
    )
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    config = load_config()
    publisher = Publisher(config.mqtt)
    publisher.connect()
    subscriber = Subscriber(config, publisher)
    try:
        subscriber.run_forever()
    finally:
        publisher.disconnect()


if __name__ == "__main__":
    main()
