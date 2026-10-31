"""Encode the original PNG artwork as a Windows multi-size icon."""
from pathlib import Path
import struct

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage


def main():
    folder = Path(__file__).resolve().parents[1]/'raw_to_png/assets'
    image = QImage(str(folder/'app-icon.png'))
    if image.isNull():
        raise ValueError('Cannot read icon artwork')
    image = image.convertToFormat(QImage.Format_ARGB32)
    frames = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        scaled = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if not scaled.save(buffer, 'PNG'):
            raise ValueError('Cannot encode icon frame')
        frames.append((size, bytes(data)))
    offset = 6 + 16 * len(frames)
    entries = []
    for size, data in frames:
        entries.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    (folder/'app.ico').write_bytes(struct.pack('<HHH', 0, 1, len(frames)) + b''.join(entries)
                                  + b''.join(data for _, data in frames))


if __name__ == '__main__':
    main()
