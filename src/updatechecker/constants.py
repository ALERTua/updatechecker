import os
from pathlib import Path

ROOT_FOLDER = Path(__file__).parent.parent.parent
TEMP_FOLDER = Path(os.getenv('TEMP')) / 'updatechecker/'
TEMP_FOLDER.mkdir(exist_ok=True)

DEFAULT_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB in bytes

CONSOLE_WIDTH_LIMIT = 300
