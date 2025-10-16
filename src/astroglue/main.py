import logging
import sys


def setup_logging():
    """
    Configures basic logging.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main():
    """Main entry point for the astroglue application."""
    setup_logging()
    logging.info("hello world")


if __name__ == "__main__":
    main()
