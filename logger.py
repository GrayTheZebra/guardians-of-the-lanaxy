import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logger(log_file: str):
    logger = logging.getLogger("lanaxy")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    )

    logger.addHandler(file_handler)
    return logger
