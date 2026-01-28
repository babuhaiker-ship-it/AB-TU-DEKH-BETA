import time

StartTime = time.time()
__version__ = "v1.0.00"

def get_size(size: int) -> str:
    """Converts bytes to human-readable format."""
    units = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB"]
    size = float(size)
    i = 0
    while size >= 1024.0 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.2f} {units[i]}"
