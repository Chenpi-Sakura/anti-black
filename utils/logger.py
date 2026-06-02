import io
import logging
import sys


def _make_utf8_stream():
    """
    Wrap the raw byte stream of stdout in a TextIOWrapper that forces
    UTF-8 with errors='replace'. More robust than sys.stdout.reconfigure()
    because:
      - .reconfigure() may not exist (PyInstaller, redirected IO, IDE consoles)
      - The returned wrapper uses the underlying .buffer directly, so even
        if sys.stdout is replaced, the byte stream stays valid
      - errors='replace' guarantees no UnicodeEncodeError on emoji or
        other non-BMP characters
    """
    buf = sys.stdout.buffer if hasattr(sys.stdout, 'buffer') else sys.stdout
    return io.TextIOWrapper(
        buf, encoding='utf-8', errors='replace', line_buffering=True,
    )


# ANSI Escape sequences for colors
class LogColors:
    RESET = "\033[0m"
    DEBUG = "\033[36m"    # Cyan
    INFO = "\033[32m"     # Green
    WARNING = "\033[33m"  # Yellow
    ERROR = "\033[31m"    # Red
    CRITICAL = "\033[41m\033[37m" # White on Red
    TIME = "\033[90m"     # Dark Gray
    NAME = "\033[35m"     # Magenta

class ColoredFormatter(logging.Formatter):
    def format(self, record):
        level_color = getattr(LogColors, record.levelname, LogColors.RESET)
        
        # Format the time
        record.asctime = self.formatTime(record, self.datefmt)
        
        # Construct the log message with colors
        formatted_message = (
            f"{LogColors.TIME}{record.asctime}{LogColors.RESET} - "
            f"{LogColors.NAME}{record.name}{LogColors.RESET} - "
            f"{level_color}{record.levelname}{LogColors.RESET} - "
            f"{record.getMessage()}"
        )
        
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            formatted_message += f"\n{level_color}{record.exc_text}{LogColors.RESET}"
            
        return formatted_message

def setup_colored_logger(name=None, level=logging.INFO):
    """Setup a root logger with colored output and timestamp."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Remove existing handlers if any
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    console_handler = logging.StreamHandler(_make_utf8_stream())
    formatter = ColoredFormatter(datefmt='%Y-%m-%d %H:%M:%S')
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    return logger

def configure_root_logger(level=logging.INFO, log_file=None):
    """Configure the root logger so all loggers inherit the colors."""
    root = logging.getLogger()
    root.setLevel(level)

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    console_handler = logging.StreamHandler(_make_utf8_stream())
    formatter = ColoredFormatter(datefmt='%Y-%m-%d %H:%M:%S')
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    if log_file:
        file_handler = logging.FileHandler(
            log_file, encoding='utf-8', errors='replace',
        )
        # Use standard formatter for files (no colors)
        file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(file_formatter)
        root.addHandler(file_handler)
