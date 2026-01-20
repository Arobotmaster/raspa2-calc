import logging
import sys
from contextlib import contextmanager

CONSOLE_HANDLER = None


def setup_logging(log_file="raspa_calculation.log"):
    """Configure logging handlers."""
    root_logger = logging.getLogger()

    if root_logger.handlers:
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

    root_logger.setLevel(logging.INFO)

    log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    global CONSOLE_HANDLER
    CONSOLE_HANDLER = console_handler

    return root_logger


logger = setup_logging()


@contextmanager
def quiet_console(level=logging.WARNING):
    """Temporarily lower console log level to reduce noise."""
    if CONSOLE_HANDLER is None:
        yield
        return
    previous_level = CONSOLE_HANDLER.level
    CONSOLE_HANDLER.setLevel(level)
    try:
        yield
    finally:
        CONSOLE_HANDLER.setLevel(previous_level)
