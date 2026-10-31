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
    parser.add_argument('--language', choices=('ru', 'en'), default='en')
    parser.add_argument('--bits', type=int, choices=(8, 16), default=16)
    parser.add_argument('--half-size', action='store_true')
    parser.add_argument('--theme', choices=('dark', 'light'), default='dark')
    args = parser.parse_args(arguments)
    if not args.raw_file.is_file() or args.output_directory.exists():
        return 2
    args.output_directory.mkdir(parents=True)
    import faulthandler
    trace = (args.output_directory/'shutdown-trace.txt').open('w')
    faulthandler.dump_traceback_later(25, file=trace, repeat=True)
    def phase(value):
        write_report(args.output_directory/'lifecycle.json', {'phase': value})
    phase('starting')
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    import png
    import numpy as np
    from .ui import Window
    from .converter import discover
    app = QApplication([])
    app.setStyle('Fusion')
    app.setQuitOnLastWindowClosed(False)
    window = Window()
    startup = {'startup_bits': window.bits.currentData(),
               'startup_auto_bright': window.auto_bright.isChecked(),
               'startup_theme': window.theme.currentData()}
    window.language.setCurrentIndex(window.language.findData(args.language))
    window.theme.setCurrentIndex(window.theme.findData(args.theme))
    window.show()
    window.imported(discover([args.raw_file]))
    if len(window.sources) != 1:
        return 2
    window.destination.setText(str(args.output_directory))
    window.preset.setCurrentIndex(window.preset.findData('editing'))
    window.bits.setCurrentIndex(window.bits.findData(args.bits))
    window.half_size.setChecked(args.half_size)
    window.performance.setCurrentIndex(window.performance.findData('auto'))
    window.collision.setCurrentIndex(window.collision.findData('rename'))
    window.diagnostics.setChecked(True)
    outcome = {'ok': False}

    def completed():
        # Run in the GUI thread after QThread has fully stopped. Closing from
        # the finished signal's emitting thread can enter the busy-close dialog.
        if window.worker.isRunning():
            QTimer.singleShot(10, window, completed)
            return
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
            if (info['bitdepth'] != args.bits or info['planes'] != 3 or count != height
                    or fraction < .01 or maximum < (256 if args.bits == 16 else 1)):
                raise RuntimeError('invalid PNG')
            entry = window.last_report['files'][0]
            if (entry['width'], entry['height']) != (width, height):
                raise RuntimeError('incorrect reported PNG dimensions')
            if result['thread_counts'] != [1]:
                raise RuntimeError('thread limit not applied')
            write_report(args.output_directory/'diagnostics.json', window.last_report)
            write_report(args.output_directory/'packaging-check.json', {
                'ok': True, 'channel': build_channel(), 'width': width, 'height': height,
                'bits': info['bitdepth'], 'diagnostics_exported': True,
                'nonzero_fraction': fraction, 'maximum_sample': maximum,
                'worker_priorities': result['priorities'], 'worker_threads': result['thread_counts'],
                'language': window.language.currentData(), 'half_size': args.half_size,
                'input_width': entry['input_width'], 'input_height': entry['input_height'],
                'theme': window.theme.currentData(), 'auto_bright': window.auto_bright.isChecked(),
                **startup,
            })
            window.grab().save(str(args.output_directory/'interface.png'))
            outcome['ok'] = True
        except Exception as error:
            write_report(args.output_directory/'packaging-check.json', {
                'ok': False, 'error_kind': type(error).__name__,
            })
        phase('closing_window')
        window.close()
        phase('window_closed')
        app.exit(0 if outcome['ok'] else 1)
        phase('exit_requested')

    window.begin()
    if window.worker is None:
        return 2
    window.worker.finished.connect(lambda: QTimer.singleShot(0, window, completed))
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(window.cancel)
    watchdog.start(180000)
    app.exec()
    phase('event_loop_stopped')
    faulthandler.cancel_dump_traceback_later()
    trace.close()
    return 0 if outcome['ok'] else 1
