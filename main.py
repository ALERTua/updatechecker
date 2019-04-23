import hashlib
import json
import locale
import os
import pprint
import re
import shutil
import sys
import urllib.request
import zipfile
from functools import partial
from pathlib import Path

# noinspection PyPackageRequirements
import psutil as psutil
import requests
from future.moves.urllib.request import urlretrieve, urlparse

import constants
from logger import Log

log = Log.getLogger(__name__)


def str_decode(_str):
    encs = (locale.getpreferredencoding(True), sys.stdin.encoding, 'utf-8', '866')
    output = _str
    for enc in encs:  # can't figure out why this shit doesn't work the way it should!
        try:
            output = _str.decode(enc)
            break
        except:
            continue
    return output


def process_running(executeable=None, exe_path=None, cmdline=None):
    """ Returns a list of running processes with executeable equals name and/or full path to executeable equals path

    :param executeable: process executeable name
    :type executeable: basestring
    :param exe_path: full path to process executeable including name
    :type exe_path: basestring
    :param cmdline: cmdline or a part of it that can be found in the process cmdline
    :type cmdline: basestring
    :rtype: list
    """
    process_iter = psutil.process_iter()
    output_processes = []
    for process in process_iter:
        append = False
        process_name = process.name()
        if executeable is not None:
            if process_name.lower() == executeable.lower():
                append = True
            else:
                continue

        if exe_path is not None:
            try:
                process_path = process.exe()
            except:
                continue

            if Path(process_path) == Path(exe_path):
                append = True
            else:
                continue

        if cmdline is not None:
            try:
                process_cmdline = process.cmdline()
            except:
                continue
            process_cmdline = [str_decode(_cmdln).lower().replace('\\', '/').strip('/') for _cmdln in process_cmdline]
            if cmdline.lower().replace('\\', '/').strip('/') in process_cmdline:
                append = True
            else:
                continue

        if append is True:
            output_processes.append(process)
    return output_processes


def kill_process(executeable=None, exe_path=None, cmdline=None):
    running_processes = process_running(executeable=executeable, exe_path=exe_path, cmdline=cmdline)
    for process in running_processes:
        log.printer("Killing process %s" % process.pid)
        process.kill()


def url_get_git_package(url: str) -> str:
    """

    :param url:
    :return:
    """
    if 'github' in url:
        url = re.search('(?<=github.com/)[^/]+/[^/]+', url).group(0)
    request = requests.get('https://github.com/%s/tags.atom' % url)
    if request.status_code != 200:
        raise NameError('%s is not a valid github url/package' % url)
    return url


def git_package_to_releases(package):
    releases_url = "https://api.github.com/repos/%s/releases" % package
    output = requests.get(url=releases_url)
    output = output.json()
    return output


def git_latest_release(releases):
    return releases[0]


def git_release_get_asset_url(release, asset_name):
    assets = release.get('assets')
    if assets is None:
        log.warning("Couldn't get asset url for '%s'" % asset_name)
        return

    matching_assets = list(filter(lambda f: re.match(asset_name, f.get('name')) is not None, assets))
    if not any(matching_assets):
        log.warning("There are no assets of name '%s'" % asset_name)
        return

    asset = matching_assets[0]
    output = asset.get('browser_download_url')
    log.debug("Returning url for asset '%s': '%s'" % (asset_name, output))
    return output


def url_accessible(_url):
    getcode = None
    try:
        urlopen = urllib.request.urlopen(_url)
        getcode = urlopen.getcode()
    except:
        pass
    output = getcode == 200
    log.debug("url '%s' accessible: %s" % (_url, output))
    return output


def md5sum(path):
    if not isinstance(path, Path):
        try:
            Path(path).exists()
            path = Path(path)
        except:
            pass

    if not isinstance(path, Path):
        log.debug("Getting md5 of an url '%s'" % path)
        if not url_accessible(path):
            log.warning("Cannot get an md5 of the url '%s': url is not accessible" % path)
            return None

        filename = url_to_filename(path)
        if filename is None:
            log.warning("Cannot get md5 from url '%s': couldn't get filename from url" % path)
            return None

        temp_file_path = constants.TEMP_FOLDER / filename
        if temp_file_path.exists():
            temp_file_path.unlink()

        downloaded_file = download_file_from_url(path, temp_file_path)
        if downloaded_file is None or not downloaded_file.exists():
            log.warning("Couldn't get url '%s' md5: couldn't download it to file '%s'" % (path, downloaded_file))
            return None

        path = downloaded_file

    log.debug("Getting md5 of '%s'" % path)
    with path.open('rb') as f:
        d = hashlib.md5()
        for buf in iter(partial(f.read, 128), b''):
            d.update(buf)
    output = d.hexdigest()
    return output


def download_file_from_url(source, destination):
    def basic_progress(blocknum, bs, size):
        if blocknum % 10 == 0:
            log.printer('.', end='')

    log.printer("Downloading '%s' to '%s'" % (source, destination), end='')
    try:
        urlretrieve(source, str(destination), basic_progress)
    except Exception as e:
        log.error("Error downloading '%s' to '%s': %s %s" % (source, destination, type(e), e))
        return None
    log.printer('Done')
    return Path(destination)


def url_to_filename(url):
    parse = urlparse(url)
    base = os.path.basename(parse.path)
    suffix = Path(base).suffix
    if suffix == '':
        log.warning("Cannot get filename from url '%s'. No dot in base '%s'" % (url, parse.path))
        return None
    return base


def load_config(path=None):
    path = path or constants.CONFIG_FILE
    if not Path(path).exists():
        raise Exception("Config doesn't exist @ '%s'. Create it using config.json.example" % path)

    with open(path, 'r') as config_file:
        config_data = json.load(config_file)

    return config_data


def read_url(url):
    fp = urllib.request.urlopen(url)
    mybytes = fp.read()
    output = mybytes.decode("utf8").strip()
    fp.close()
    return output


def unzip_file(source, destination, members=None, password=None):
    with zipfile.ZipFile(str(source), 'r') as _zip:
        log.debug("Unzipping '%s' to '%s'" % (source, destination))
        _zip.extractall(str(destination), members=members, pwd=password)


def is_filename_archive(filename):
    archive_exts = ('.zip', '.7z', '.rar')
    return any([ext for ext in archive_exts if ext in filename])


class UpdateChecker(object):
    def __init__(self, config_path=None):
        self._config = config_path

    @property
    def config(self) -> dict:
        if self._config is None:
            self._config = load_config(self._config)
        return self._config

    def main(self):
        for _, entry in self.config.items():
            self.process_entry(entry)

    @staticmethod
    def process_archive(entry):
        url = entry['url']
        kill_if_locked = entry.get('kill_if_locked')
        unzip_target = entry.get('unzip_target')
        archive_password = entry.get('archive_password')
        target = entry['target']
        target = Path(target)

        if is_filename_archive(target.name) and unzip_target is not None:
            if target.is_dir():
                url_file = url_to_filename(url)
                target = target / url_file

            try:
                unzip_file(target, unzip_target, password=archive_password)
            except Exception as e:
                log.warning("Couldn't unzip archive to '%s': %s %s" % (unzip_target, type(e), e))

                proc_running = process_running(exe_path=kill_if_locked)
                if proc_running is True:
                    kill_process(exe_path=kill_if_locked)

                try:
                    unzip_file(target, unzip_target, password=archive_password)
                except Exception as e:
                    log.warning("Couldn't unzip archive to '%s' after unlocking: %s %s. Breaking" %
                                (unzip_target, type(e), e))
                    return

    def process_entry(self, entry):
        log.debug("Processing entry:\n%s" % pprint.pformat(entry))
        url = entry['url']
        url_md5 = entry.get('md5')
        git_asset = entry.get('git_asset')
        launch = entry.get('launch')
        arguments = entry.get('arguments')
        kill_if_locked = entry.get('kill_if_locked')
        relaunch = entry.get('relaunch', False)

        def _launch():
            if launch is not None:
                __cmd = 'start "" %s %s' % (launch, arguments or '')
                log.debug("Launching '%s'" % __cmd)
                os.system(__cmd)

        if git_asset is not None:
            log.debug("Trying git package for git asset '%s'" % git_asset)
            git_package = url_get_git_package(url)
            if git_package is None:
                log.warning("Url is not for a file and not a git package. Cannot proceed")
                return

            releases = git_package_to_releases(git_package)
            release = git_latest_release(releases)
            url = git_release_get_asset_url(release, git_asset)

        url_file = url_to_filename(url)
        if url_file is None:
            log.warning("Url '%s' is not for a file." % url)
            return

        target = entry['target']
        target = Path(target)
        if target.is_dir():
            target = target / url_file

        if not target.exists():
            log.debug("Target '%s' doesn't exist. Just downloading url" % target)
            download_file_from_url(url, target)
            self.process_archive(entry)
            _launch()
            return

        target_md5 = md5sum(target)
        temp_file = constants.TEMP_FOLDER / url_file

        def del_temp():
            if temp_file.exists():
                temp_file.unlink()

        del_temp()

        if url_md5 is None:
            download_file_from_url(url, temp_file)
            url_md5 = md5sum(temp_file)
        else:
            url_md5 = read_url(url_md5)
            url_md5 = url_md5.split(' ')[0]

        if target_md5 == url_md5:
            log.info("No need to update '%s'" % target)
            del_temp()
            return
        else:
            log.debug("md5 url vs target: '%s' '%s'" % (url_md5, target_md5))

        bak_file = Path('%s.bak' % str(target))
        if bak_file.exists():
            log.debug("Deleting old backup for '%s'" % target)
            bak_file.unlink()

        killed = False
        try:
            target.rename(bak_file)
        except Exception as e:
            if kill_if_locked is None:
                log.warning("Couldn't back up '%s': %s %s" % (target, type(e), e))
                return

            proc_running = process_running(exe_path=kill_if_locked)
            if proc_running is True:
                kill_process(exe_path=kill_if_locked)
                killed = True

        if temp_file.exists():
            log.debug("Moving '%s' to '%s'" % (temp_file, target))
            shutil.move(str(temp_file), str(target))
            del_temp()
        else:
            download_file_from_url(url, target)

        self.process_archive(entry)

        if killed is True:
            if relaunch is True and kill_if_locked is not None:
                _cmd = "%s %s" % (kill_if_locked, arguments or '')
                os.system(kill_if_locked)
        else:
            _launch()


def main(args=None):
    _args = args or sys.argv[1:]
    config = None if not len(_args) else _args[0]

    update_checker = UpdateChecker(config)
    update_checker.main()


if __name__ == '__main__':
    log.verbose = True
    main()
    pass
