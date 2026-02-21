from colorama import Fore
from colorlog import ColoredFormatter, default_log_colors

import datetime
import logging
import os
import pprint
import re
import sys
import time

# noinspection PyCompatibility
from pathlib import Path

from . import constants


class InfoFilter(logging.Filter):
    def filter(self, rec):
        return rec.levelno <= logging.INFO


class PrettyLog:
    def __init__(self, obj):
        self.obj = obj

    def __repr__(self):
        if isinstance(self.obj, str):
            return self.obj

        return pprint.pformat(self.obj)


class Struct:
    def __init__(self, **entries):
        self.__dict__.update(entries)


LOGGER_DEFAULT_LEVEL = logging.INFO
LOGGER_LEVELS_DICT = {
    'CRITICAL': logging.CRITICAL,
    'ERROR': logging.ERROR,
    'WARNING': logging.WARNING,
    'INFO': logging.INFO,
    'DEBUG': logging.DEBUG,
}
LOGGER_LEVELS = Struct(**LOGGER_LEVELS_DICT)


class Log:
    loggers = {}
    levels = LOGGER_LEVELS
    default_level = LOGGER_DEFAULT_LEVEL
    log_session_filename = None

    @staticmethod
    def set_global_log_level(level):
        print(f"Changing global logger level to {level}")
        Log.default_level = level
        for logger in Log.loggers.values():
            logger.level = level

    def __init__(self, name, _level=None):
        level = _level or Log.default_level
        verbose = os.getenv('verbose', None)
        if verbose is not None:
            level = logging.DEBUG

        self.name = name
        self.log = logging.getLogger(self.name)

        self.debug = self.log.debug
        self.info = self.log.info
        self.warning = self.log.warning
        self.error = self.log.error
        self.critical = self.log.critical
        self.exception = self.log.exception

        if not (
            Path(constants.LOGS_FOLDER).exists()
            and Path(constants.LOGS_FOLDER).is_dir()
        ):
            os.mkdir(str(constants.LOGS_FOLDER))

        if Log.log_session_filename is None:
            Log.log_session_filename = (
                f"{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
            )
            self.clean_logs_folder()

        formatter = logging.Formatter(
            constants.LOGGER_MESSAGE_FORMAT, datefmt=constants.LOGGER_DATE_FORMAT
        )
        color_formatter = ColoredFormatter(
            fmt=constants.LOGGER_COLORED_MESSAGE_FORMAT,
            datefmt=constants.LOGGER_DATE_FORMAT,
            reset=True,
            log_colors=default_log_colors,
        )

        self.stdout_handler = logging.StreamHandler(sys.stdout)
        self.stdout_handler.addFilter(InfoFilter())
        self.log.addHandler(self.stdout_handler)
        self.stdout_handler.setFormatter(color_formatter)

        self.stderr_handler = logging.StreamHandler(sys.stderr)
        self.log.addHandler(self.stderr_handler)
        self.stderr_handler.setFormatter(color_formatter)

        log_file_full_path = Path(constants.LOGS_FOLDER) / Log.log_session_filename
        self.filehandler = logging.FileHandler(str(log_file_full_path))
        self.filehandler.setFormatter(formatter)
        self.log.addHandler(self.filehandler)

        self.level = level
        Log.loggers[self.name] = self

    def __str__(self):
        return self.name

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return self.name == other.name

    @property
    def verbose(self):
        return self.level == logging.DEBUG

    @verbose.setter
    def verbose(self, value):
        if value is True:
            self.set_global_log_level(logging.DEBUG)
        else:
            self.set_global_log_level(logging.INFO)

    @classmethod
    def getLogger(cls, name, _level=None):
        output = Log.loggers.get(name, None)
        if output is None:
            output = cls(name, _level=None)
        return output

    @property
    def level(self):
        return self.stdout_handler.level

    @level.setter
    def level(self, value):
        Log.default_level = value
        self.log.setLevel(logging.DEBUG)
        self.filehandler.setLevel(logging.DEBUG)
        self.stdout_handler.setLevel(value)
        self.stderr_handler.setLevel(logging.WARNING)

    @staticmethod
    def clean_logs_folder():
        log_files = sorted(
            list(Path(constants.LOGS_FOLDER).glob('*.log')),
            key=lambda f: f.stat().st_ctime,
            reverse=True,
        )
        if len(log_files) > constants.MAX_LOG_FILES:
            for _file in log_files[constants.MAX_LOG_FILES :]:
                # noinspection PyBroadException
                try:
                    os.remove(str(_file))
                except:  # noqa: E722
                    pass

    def printer(self, *message, **kwargs):
        # for exception in EXCEPTIONS:
        #     if exception in message:
        #         return

        default_end = '\n'
        end = kwargs.get('end', None)
        color = kwargs.get('color', True)
        clear = kwargs.get('clear', True)
        print_end = end if end is not None else default_end
        for msg in message:
            timestamp = '' if end == '' else f'{time.strftime("%H:%M:%S")} '

            _timestamped_message = f'{timestamp}{msg}'
            _cleared_timestamped_message = re.sub(
                r'\x1b(\[.*?[@-~]|\].*?(\x07|\x1b\\))', '', _timestamped_message
            )

            self.filehandler.stream.write(_cleared_timestamped_message)
            self.filehandler.flush()

            _cleared_message = msg
            if clear is True:
                _cleared_message = re.sub(
                    r'\x1b(\[.*?[@-~]|\].*?(\x07|\x1b\\))', '', msg
                )

            _colored_msg = _cleared_message
            if color is True:
                _colored_msg = f'{Fore.GREEN}{_cleared_message}{Fore.RESET}'

            print(_colored_msg, end=print_end)


if __name__ == '__main__':
    log = Log.getLogger(__name__)
    # log.clean_logs_folder()
    log.debug('test debug')
    log.info('test info')
    log.error('test error')
    log.printer('test filehandler message')
    log.warning('test warning')
    print("")
