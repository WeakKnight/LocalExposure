"""Pinned Windows packaging tools for the foreground NativeActivity benchmark."""
import zipfile
from .benchmark import TOOLS, download

ARCHIVES = [
    ('https://dl.google.com/android/repository/build-tools_r35.0.1_windows.zip',
     '79748cb4ab64b61fa678af21639985c7e394d874a4e31f082f4026d5c57e01a3',
     'android-15/aapt2.exe'),
    ('https://dl.google.com/android/repository/platform-35_r02.zip',
     '0988cacad01b38a18a47bac14a0695f246bc76c1b06c0eeb8eb0dc825ab0c8e0',
     'android-35/android.jar'),
    ('https://cdn.azul.com/zulu/bin/zulu17.68.17-ca-jre17.0.20-win_x64.zip',
     'a4d580f4c24c9795f185d5287917d028861ac5fbd670069631a0502cc79412bb',
     'zulu17.68.17-ca-jre17.0.20-win_x64/bin/java.exe'),
]


def bootstrap():
    for url, checksum, executable in ARCHIVES:
        archive = TOOLS / url.rsplit('/', 1)[1]
        destination = TOOLS / archive.stem
        download(url, archive, checksum)
        if not (destination / executable).exists():
            destination.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as package:
                package.extractall(destination)


def paths():
    paths = [TOOLS / url.rsplit('/', 1)[1][:-4] / executable
             for url, _, executable in ARCHIVES]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise RuntimeError('Missing activity packaging tools; rerun with --bootstrap: ' + ', '.join(missing))
    return paths[0].parent, paths[1], paths[2]
