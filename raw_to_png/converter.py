"""Conversion engine, independent of Qt. Originals are always read-only."""
from dataclasses import dataclass
from pathlib import Path
from threading import Event
import os
import shutil
import tempfile

import numpy as np
import png
import rawpy

from .i18n import message


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class Source:
    path: Path
    relative: Path


@dataclass(frozen=True)
class ConversionOptions:
    white_balance: str = 'camera'
    auto_bright: bool = False
    half_size: bool = False
    brightness_ev: float = 0.0

    def __post_init__(self):
        if self.white_balance not in ('camera', 'auto', 'daylight'):
            raise ValueError(message('Неизвестный баланс белого'))
        if not -2 <= self.brightness_ev <= 2:
            raise ValueError(message('Яркость должна быть от −2 до +2 EV'))


def discover(paths, recursive=True):
    """Keep folder-relative paths; avoid following directory symlinks."""
    result = []
    seen = set()
    for value in paths:
        path = Path(value).resolve()
        if path.is_dir():
            candidates = []
            for root, dirs, files in os.walk(path, followlinks=False, onerror=_raise):
                dirs.sort()
                candidates.extend(Path(root) / name for name in sorted(files)
                                  if Path(name).suffix.lower() == '.arw')
                if not recursive:
                    break
        else:
            candidates = [path] if path.suffix.lower() == '.arw' and path.is_file() else []
        for candidate in candidates:
            real = candidate.resolve()
            if real not in seen:
                seen.add(real)
                result.append(Source(real, candidate.relative_to(path) if path.is_dir()
                                     else Path(candidate.name)))
    return result


def _raise(error):
    raise error


def plan(sources, destination, *, preserve_folders=True, collision='rename'):
    """Reserve case-insensitive names so a queue behaves the same on Windows."""
    reserved = set()
    scanned = set()
    result = []
    if collision not in ('rename', 'skip'):
        raise ValueError(message('Неизвестный режим совпадения имён'))
    for source in sources:
        relative = source.relative.with_suffix('.png')
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError(message('Недопустимый путь назначения'))
        if not preserve_folders:
            relative = Path(relative.name)
        target = Path(destination) / relative
        if target.parent not in scanned:
            if target.parent.exists():
                reserved.update(str(entry).casefold() for entry in target.parent.iterdir())
            scanned.add(target.parent)
        base = target
        suffix = 2
        if collision == 'skip' and (str(target).casefold() in reserved or target.exists()):
            result.append((source, None))
            continue
        while str(target).casefold() in reserved or target.exists():
            target = base.with_name(f'{base.stem} ({suffix}).png')
            suffix += 1
        reserved.add(str(target).casefold())
        result.append((source, target))
    return result


class SRGBWriter(png.Writer):
    def write_preamble(self, outfile):
        super().write_preamble(outfile)
        png.write_chunk(outfile, b'sRGB', b'\x00')


def write_png(rgb, target, cancel):
    """Encode to a temporary file, then publish without overwriting any file."""
    if rgb.dtype not in (np.uint8, np.uint16) or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(message('Ожидается RGB-массив uint8 или uint16'))
    if cancel.is_set():
        raise Cancelled()
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.part', delete=False) as stream:
            temporary = Path(stream.name)
            def rows():
                for row in rgb:
                    if cancel.is_set():
                        raise Cancelled()
                    yield row.reshape(-1)
            SRGBWriter(width=rgb.shape[1], height=rgb.shape[0], greyscale=False,
                       bitdepth=rgb.dtype.itemsize * 8, compression=3).write(stream, rows())
        if cancel.is_set():
            raise Cancelled()
        # Exclusive creation is supported on Windows and removable filesystems.
        # A file created by another process after planning is never overwritten.
        created = False
        try:
            with temporary.open('rb') as source:
                with target.open('xb') as output:
                    created = True
                    shutil.copyfileobj(source, output)
        except BaseException:
            if created:
                target.unlink(missing_ok=True)
            raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def convert(source, target, bits=16, cancel=None, options=None):
    if bits not in (8, 16):
        raise ValueError(message('Поддерживаются 8 и 16 бит'))
    cancel = cancel if cancel is not None else Event()
    options = options if options is not None else ConversionOptions()
    if cancel.is_set():
        raise Cancelled()
    with rawpy.imread(str(source)) as raw:
        sizes = raw.sizes
        rgb = raw.postprocess(use_camera_wb=options.white_balance == 'camera',
                              use_auto_wb=options.white_balance == 'auto', output_bps=bits,
                              output_color=rawpy.ColorSpace.sRGB,
                              gamma=(2.4, 12.92), no_auto_bright=not options.auto_bright,
                              half_size=options.half_size, bright=2 ** options.brightness_ev,
                              user_flip=None)
        # LibRaw may ignore half_size for already demosaiced RAW (e.g. sRAW).
        # Keep the size option consistent for these files as well.
        if options.half_size and sorted(rgb.shape[:2]) == sorted((sizes.height, sizes.width)):
            height, width = (rgb.shape[0] // 2) * 2, (rgb.shape[1] // 2) * 2
            summed = rgb[:height:2, :width:2].astype(np.uint32)
            summed += rgb[1:height:2, :width:2]
            summed += rgb[:height:2, 1:width:2]
            summed += rgb[1:height:2, 1:width:2]
            rgb = ((summed + 2) // 4).astype(rgb.dtype)
    write_png(rgb, target, cancel)
    return rgb.shape[1], rgb.shape[0]
