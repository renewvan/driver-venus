#!/usr/bin/env python3
"""node-venus entrypoint."""

from __future__ import annotations

import argparse
import logging

from node_venus.config import load_config
from node_venus.node_info import load_node_info
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
    # Version is stamped by the release build (NODE_VERSION); unset reports "dev".
    # Host serial is read once, here, at process start.
    publisher = Publisher(config.mqtt, load_node_info())
    publisher.connect()
    subscriber = Subscriber(config, publisher)
    try:
        subscriber.run_forever()
    finally:
        publisher.disconnect()


if __name__ == "__main__":
    main()
