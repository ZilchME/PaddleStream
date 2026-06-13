import logging

_LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    """Return a module logger with a shared stream handler."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
        )
        logger.addHandler(handler)

    return logger
