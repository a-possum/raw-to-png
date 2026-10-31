"""Explicit UI messages; file paths and library errors are never translated."""

ENGLISH = {
    'Оцениваем оставшееся время…': 'Estimating remaining time…',
    'Уточняем оставшееся время…': 'Updating the time estimate…',
    'Ожидание свободной памяти · оценка времени приостановлена': 'Waiting for free memory · time estimate paused',
    'Осталось примерно {time}': 'About {time} remaining',
    'менее 10 с': 'less than 10 s',
    '{seconds} с': '{seconds} s',
    '{minutes} мин {seconds} с': '{minutes} min {seconds} s',
    '{minutes} мин': '{minutes} min',
    '{hours} ч {minutes} мин': '{hours} h {minutes} min',
    'Дважды щёлкните по готовой строке, чтобы открыть PNG.': 'Double-click a completed row to open its PNG.',
    'Файл недоступен': 'File unavailable',
    'PNG был перемещён или удалён.': 'The PNG was moved or deleted.',
    'Не удалось открыть PNG': 'Could not open the PNG',
    'Откройте файл из папки результата.': 'Open the file from the output folder.',
    'ARW → PNG · Конвертер фотографий': 'ARW → PNG · Photo converter',
    ' · тестовая сборка': ' · test build',
    'Язык': 'Language',
    'Тёмная тема': 'Dark theme',
    'Светлая тема': 'Light theme',
    'Тема оформления': 'Theme',
    'Меняет яркость фотографии. Включается только по вашему выбору.': 'Changes photo brightness. Enabled only when you choose it.',
    'Ваши RAW. Готовые PNG.': 'Your RAW photos. Ready as PNG.',
    'Добавьте фотографии, выберите папку и запустите конвертацию.': 'Add photos, choose an output folder and start converting.',
    '1  Фотографии': '1  Photos',
    '+ Файлы': '+ Files',
    '+ Папка': '+ Folder',
    'Убрать выбранные': 'Remove selected',
    'Очистить': 'Clear',
    'Искать ARW во вложенных папках': 'Include ARW files in subfolders',
    'Фотография': 'Photo',
    'Статус': 'Status',
    'Результат / ошибка': 'Output / error',
    'Перетащите фотографии сюда\n\nФайлы .ARW или целую папку\n\nЛибо нажмите «+ Файлы» / «+ Папка» выше': 'Drop photos here\n\n.ARW files or an entire folder\n\nOr use “+ Files” / “+ Folder” above',
    'Очередь пуста · оригиналы остаются без изменений': 'Queue empty · originals stay unchanged',
    '2  Куда сохранить': '2  Output folder',
    'Папка для готовых PNG': 'Folder for converted PNG files',
    'Можно вставить полный путь или выбрать папку кнопкой ниже': 'Paste a full path or choose a folder using the button below',
    'Выбрать папку сохранения…': 'Choose output folder…',
    'Сохранять структуру подпапок': 'Keep the subfolder structure',
    'Если PNG с таким именем уже есть:': 'If a PNG with this name already exists:',
    'Создать копию с новым именем': 'Create a copy with a new name',
    'Пропустить этот файл': 'Skip this file',
    '3  Как конвертировать': '3  Conversion settings',
    'Для обработки · PNG 16 бит': 'For editing · 16-bit PNG',
    'Для публикации · PNG 8 бит': 'For sharing · 8-bit PNG',
    'Быстро · 8 бит, половина размера': 'Quick · 8-bit, half size',
    'Свои настройки': 'Custom settings',
    'Производительность': 'Performance',
    'Авто · баланс скорости и нагрузки': 'Auto · balanced speed and load',
    'Экономный · одна фотография': 'Eco · one photo at a time',
    'Максимальная скорость': 'Maximum speed',
    'Выберите баланс скорости и нагрузки на компьютер.': 'Choose a balance between speed and computer load.',
    'Пока идёт конвертация на максимальной скорости, не используйте другие тяжёлые приложения.': 'Avoid using other demanding apps while converting at maximum speed.',
    'Дополнительные настройки': 'Advanced settings',
    '16 бит на канал': '16 bits per channel',
    '8 бит на канал': '8 bits per channel',
    'Глубина цвета': 'Bit depth',
    'Как в камере': 'Camera setting',
    'Автоматический': 'Automatic',
    'Дневной свет': 'Daylight',
    'Баланс белого': 'White balance',
    'Множитель яркости 2^EV; 0 — без коррекции': 'Brightness multiplier: 2^EV; 0 keeps the original brightness',
    'Яркость': 'Brightness',
    'Автоматически осветлять': 'Auto brightness',
    '½ ширины и высоты': 'Half width and height',
    'Записывать отчёт проверки': 'Record a diagnostic report',
    'Отчёт хранится только на этом компьютере. Без фотографий, EXIF и полных путей. Никуда не отправляется.': 'The report stays on this computer. No photos, EXIF or full paths. Nothing is uploaded.',
    'Все варианты сохраняются в PNG / sRGB.\nОригиналы и существующие файлы не перезаписываются.': 'All presets save PNG / sRGB files.\nOriginals and existing files are never overwritten.',
    '%v из %m файлов · %p%': '%v of %m files · %p%',
    'Отчёт проверки будет сохранён только на этом компьютере.': 'The diagnostic report will be saved only on this computer.',
    'Добавьте фотографии для начала': 'Add photos to get started',
    'Остановить': 'Stop',
    'Открыть папку': 'Open folder',
    'Сохранить отчёт': 'Save report',
    'Конвертировать': 'Convert',
    'Авто': 'Auto',
    'Экономный': 'Eco',
    '{mode} · ожидание запуска': '{mode} · ready to start',
    'Конвертировать {count} файлов': 'Convert ({count})',
    'В очереди: {count} · оригиналы не изменяются': 'Queued: {count} · originals stay unchanged',
    'Ожидание файлов': 'Waiting for files',
    'Полный размер и 16 бит на канал — больше данных для дальнейшей обработки.': 'Full resolution and 16 bits per channel — more data for further editing.',
    'Полный размер и 8 бит на канал — для публикации и обычного просмотра.': 'Full resolution and 8 bits per channel — for sharing and everyday viewing.',
    'Половина ширины и высоты, 8 бит — быстрее и меньше места на диске.': 'Half width and height, 8 bits — faster conversion and smaller files.',
    'Выбраны ваши настройки. Результат сохраняется в PNG / sRGB.': 'Your custom settings. Output is saved as PNG / sRGB.',
    'В очереди: {count} файлов': 'Files queued: {count}',
    'Выберите файлы ARW': 'Select ARW files',
    'Файлы ARW (*.arw *.ARW)': 'ARW files (*.arw *.ARW)',
    'Добавить папку с ARW': 'Add a folder with ARW files',
    'Папка для PNG': 'PNG output folder',
    'Поиск ARW…': 'Searching for ARW files…',
    'Ошибка чтения папки: {error}': 'Could not read the folder: {error}',
    'В очереди': 'Queued',
    'Очередь очищена': 'Queue cleared',
    'Очередь пуста': 'Queue empty',
    'Добавьте файлы .ARW или папку.': 'Add .ARW files or a folder.',
    'Папка назначения недоступна': 'Output folder unavailable',
    'Будет пропущено: совпадение имени': 'Will be skipped: name already exists',
    'Конвертация…': 'Converting…',
    'Отчёт проверки записывается только на этом компьютере.': 'The diagnostic report is being recorded only on this computer.',
    'Подготовка…': 'Preparing…',
    'Обработка…': 'Processing…',
    'Не обработано': 'Not processed',
    'Готово': 'Done',
    'Ошибка': 'Error',
    'Пропущено': 'Skipped',
    'Отменено': 'Cancelled',
    'Остановка… Дождитесь завершения текущего этапа обработки RAW.': 'Stopping… Please wait for the current RAW processing step to finish.',
    'Не удалось автоматически сохранить отчёт. Попробуйте кнопку «Сохранить отчёт».': 'Could not save the report automatically. Try the “Save report” button.',
    'Не удалось создать отчёт проверки.': 'Could not create the diagnostic report.',
    'Отчёт проверки готов. Его можно сохранить и передать для проверки.': 'The diagnostic report is ready. You can save it and share it for review.',
    'Сохранить отчёт проверки': 'Save diagnostic report',
    'Отчёт JSON (*.json)': 'JSON report (*.json)',
    'Не удалось сохранить отчёт': 'Could not save the report',
    'Выберите другую папку для отчёта.': 'Choose another folder for the report.',
    'Дождитесь остановки': 'Please wait for processing to stop',
    'Идёт обработка. Дождитесь её остановки и закройте окно ещё раз.': 'Processing is in progress. Wait for it to stop, then close the window again.',
    'Не удалось продолжить очередь: {error}': 'Could not continue the queue: {error}',
    'Обработка остановлена': 'Processing stopped',
    'Остановлено': 'Stopped',
    'Завершено': 'Completed',
    '{state}. Готово: {ok}, ошибок: {failed}, пропущено: {skipped}, не обработано: {remaining}. Время: {elapsed:.0f} с.': '{state}. Done: {ok}, errors: {failed}, skipped: {skipped}, not processed: {remaining}. Time: {elapsed:.0f} s.',
    '{state} · одновременно обрабатывалось до {count} фотографий': '{state} · up to {count} photos processed at a time',
    '{mode} · остановка, активных задач: {count}': '{mode} · stopping, active tasks: {count}',
    '{mode} · обрабатывается фотографий: {count}': '{mode} · photos processing: {count}',
    '{mode} · ожидание свободной памяти, активных задач: {count}': '{mode} · waiting for free memory, active tasks: {count}',
    'Рабочий процесс завершился (код {code})': 'Worker process exited (code {code})',
    'Для этого RAW недостаточно оперативной памяти с учётом запаса системе': 'Not enough memory for this RAW file while keeping a reserve for the system',
    'Потеряна связь с рабочим процессом: {error}': 'Lost connection to the worker process: {error}',
    'PNG с таким именем уже существует или есть в очереди': 'A PNG with this name already exists or is queued',
    'Недостаточно памяти для безопасного запуска обработки': 'Not enough memory to start processing safely',
    'Неизвестный режим производительности': 'Unknown performance mode',
    'Неизвестный баланс белого': 'Unknown white balance setting',
    'Яркость должна быть от −2 до +2 EV': 'Brightness must be between −2 and +2 EV',
    'Неизвестный режим совпадения имён': 'Unknown name collision setting',
    'Недопустимый путь назначения': 'Invalid output path',
    'Ожидается RGB-массив uint8 или uint16': 'Expected a uint8 or uint16 RGB array',
    'Поддерживаются 8 и 16 бит': 'Only 8-bit and 16-bit output is supported',
}


def language_code(value):
    return value if value in ('ru', 'en') else 'ru'


class Message(str):
    """A Russian-compatible string that keeps its template across process IPC."""
    def __new__(cls, source, values=None):
        values = dict(values or {})
        obj = super().__new__(cls, source.format(**values))
        obj.source, obj.values = source, values
        return obj

    def __reduce__(self):
        return Message, (self.source, self.values)


def message(source, **values):
    return Message(source, values)


def render(value, language):
    if not isinstance(value, Message):
        return str(value)
    template = ENGLISH.get(value.source, value.source) if language == 'en' else value.source
    values = {key: render(item, language) if isinstance(item, Message) else item
              for key, item in value.values.items()}
    return template.format(**values)


def exception_text(error):
    if len(error.args) == 1 and isinstance(error.args[0], Message):
        return error.args[0]
    return str(error)
