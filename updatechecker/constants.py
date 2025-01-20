# noinspection PyCompatibility
from pathlib import Path

ROOT_FOLDER = Path(__file__).parent.parent.absolute()
TEMP_FOLDER = ROOT_FOLDER / 'temp/'
if not TEMP_FOLDER.exists():
    TEMP_FOLDER.mkdir()

LOGS_FOLDER = ROOT_FOLDER / 'logs/'
if not LOGS_FOLDER.exists():
    LOGS_FOLDER.mkdir()

CONFIG_FILE = ROOT_FOLDER / 'config.json'
HASHES_FILE = ROOT_FOLDER / 'hashes.json'

LOGGER_MESSAGE_FORMAT = '%(asctime)s.%(msecs)03d %(lineno)3s:%(name)-22s %(levelname)-6s %(message)s'
LOGGER_COLORED_MESSAGE_FORMAT = '%(log_color)s%(message)s'
LOGGER_DATE_FORMAT = '%H:%M:%S'
MAX_LOG_FILES = 10
