"""Developer-only smoke check of the actual frozen test executable."""
import argparse
from pathlib import Path

from .diagnostics import build_channel, write_report


def run(arguments):
    if build_channel() != 'test':
        return 2
    parser = argparse.ArgumentParser()
    parser.add_argument('raw_file', type=Path)
    parser.add_argument('output_directory', type=Path)
    args = parser.parse_args(arguments)
    if not args.raw_file.is_file() or args.output_directory.exists():
        return 2
    args.output_directory.mkdir(parents=True)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    import png
    import numpy as np
    from .ui import Window
    from .converter import discover
    app = QApplication([])
    window = Window()
    window.show()
    window.imported(discover([args.raw_file]))
    if len(window.sources) != 1:
        return 2
    window.destination.setText(str(args.output_directory))
    window.preset.setCurrentIndex(window.preset.findData('editing'))
    window.performance.setCurrentIndex(window.performance.findData('auto'))
    window.collision.setCurrentIndex(window.collision.findData('rename'))
    window.diagnostics.setChecked(True)
    outcome = {'ok': False}

    def completed():
        try:
            result = window.worker.result
            if not result or result['ok'] != 1 or result['failed']:
                raise RuntimeError('conversion failed')
            outputs = list(args.output_directory.glob('*.png'))
            if len(outputs) != 1 or window.last_report is None:
                raise RuntimeError('missing output or report')
            width, height, rows, info = png.Reader(filename=str(outputs[0])).read()
            count = nonzero = 0
            maximum = 0
            for row in rows:
                values = np.asarray(row, dtype=np.uint16)
                count += 1
                nonzero += int(np.count_nonzero(values))
                maximum = max(maximum, int(values.max()))
            fraction = nonzero / max(1, width * height * 3)
            if (info['bitdepth'] != 16 or info['planes'] != 3 or count != height
                    or fraction < .01 or maximum < 256):
                raise RuntimeError('invalid PNG')
            if result['thread_counts'] != [1]:
                raise RuntimeError('thread limit not applied')
            write_report(args.output_directory/'diagnostics.json', window.last_report)
            write_report(args.output_directory/'packaging-check.json', {
                'ok': True, 'channel': build_channel(), 'width': width, 'height': height,
                'bits': info['bitdepth'], 'diagnostics_exported': True,
                'nonzero_fraction': fraction, 'maximum_sample': maximum,
                'worker_priorities': result['priorities'], 'worker_threads': result['thread_counts'],
            })
            outcome['ok'] = True
        except Exception as error:
            write_report(args.output_directory/'packaging-check.json', {
                'ok': False, 'error_kind': type(error).__name__,
            })
        window.close()
        app.quit()

    window.begin()
    if window.worker is None:
        return 2
    window.worker.finished.connect(completed)
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(window.cancel)
    watchdog.start(180000)
    app.exec()
    return 0 if outcome['ok'] else 1
