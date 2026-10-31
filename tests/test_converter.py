from pathlib import Path
from threading import Event
import os

import numpy as np
import png
import pytest

from raw_to_png.converter import Cancelled, Source, convert, discover, plan, write_png


@pytest.mark.parametrize('bits', [8, 16])
def test_png_preserves_all_rgb_samples_and_depth(tmp_path, bits):
    dtype = np.uint16 if bits == 16 else np.uint8
    maximum = np.iinfo(dtype).max
    pixels = np.array([[[0, 1, maximum], [maximum // 2, 100, 42]],
                       [[10, 20, 30], [maximum - 1, 5, 7]]], dtype=dtype)
    output = tmp_path / 'sub' / 'image.png'
    write_png(pixels, output, Event())
    width, height, rows, info = png.Reader(filename=str(output)).read()
    assert (width, height, info['bitdepth'], info['planes']) == (2, 2, bits, 3)
    np.testing.assert_array_equal(np.array(list(rows)).reshape(2, 2, 3), pixels)
    assert (b'sRGB', b'\x00') in list(png.Reader(filename=str(output)).chunks())
    assert not list(output.parent.glob('*.part'))


def test_discovery_recursive_case_and_deduplication(tmp_path):
    (tmp_path / 'a.ARW').touch()
    (tmp_path / 'ignored.jpg').touch()
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'b.arw').touch()
    sources = discover([tmp_path, tmp_path / 'a.ARW'])
    assert [s.relative.as_posix() for s in sources] == ['a.ARW', 'sub/b.arw']
    assert len(discover([tmp_path], recursive=False)) == 1


def test_plan_preserves_folders_and_avoids_collisions(tmp_path):
    (tmp_path / 'a.png').write_bytes(b'original')
    sources = [Source(Path('/in/a.ARW'), Path('a.ARW')),
               Source(Path('/other/A.arw'), Path('A.arw')),
               Source(Path('/in/sub/b.arw'), Path('sub/b.arw'))]
    targets = [target.relative_to(tmp_path).as_posix() for _, target in plan(sources, tmp_path)]
    assert targets == ['a (2).png', 'A (3).png', 'sub/b.png']
    assert (tmp_path / 'a.png').read_bytes() == b'original'


def test_never_overwrites_file_created_after_planning(tmp_path):
    output = tmp_path / 'image.png'
    output.write_bytes(b'keep me')
    with pytest.raises(FileExistsError):
        write_png(np.zeros((2, 2, 3), dtype=np.uint16), output, Event())
    assert output.read_bytes() == b'keep me'
    assert not list(tmp_path.glob('*.part'))


def test_cancel_leaves_no_output(tmp_path):
    cancel = Event()
    cancel.set()
    with pytest.raises(Cancelled):
        convert(tmp_path / 'not-needed.arw', tmp_path / 'out.png', cancel=cancel)
    assert not list(tmp_path.iterdir())


def test_write_failure_cleans_partial_output(tmp_path, monkeypatch):
    def fail(source, output):
        output.write(b'partial')
        raise OSError('disk full')
    monkeypatch.setattr('raw_to_png.converter.shutil.copyfileobj', fail)
    with pytest.raises(OSError, match='disk full'):
        write_png(np.zeros((2, 2, 3), dtype=np.uint16), tmp_path / 'out.png', Event())
    assert not list(tmp_path.iterdir())


def test_cancel_during_encoding_cleans_temporary_file(tmp_path, monkeypatch):
    from raw_to_png.converter import SRGBWriter
    cancel = Event()
    original = SRGBWriter.write_preamble
    def interrupt(self, stream):
        original(self, stream)
        cancel.set()
    monkeypatch.setattr(SRGBWriter, 'write_preamble', interrupt)
    with pytest.raises(Cancelled):
        write_png(np.zeros((10, 10, 3), dtype=np.uint16), tmp_path / 'out.png', cancel)
    assert not list(tmp_path.iterdir())


def test_bad_raw_does_not_create_png(tmp_path):
    source = tmp_path / 'broken.ARW'
    source.write_bytes(b'not raw')
    with pytest.raises(Exception):
        convert(source, tmp_path / 'out.png')
    assert not (tmp_path / 'out.png').exists()


def test_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        plan([Source(Path('/in/a.arw'), Path('../a.arw'))], tmp_path)


@pytest.mark.skipif(not os.environ.get('RAW_TO_PNG_SAMPLE'), reason='External RAW sample not provided')
def test_real_raw(tmp_path):
    output = tmp_path / 'real.png'
    convert(Path(os.environ['RAW_TO_PNG_SAMPLE']), output)
    width, height, rows, info = png.Reader(filename=str(output)).read()
    assert width > 100 and height > 100
    assert info['bitdepth'] == 8 and info['planes'] == 3
    assert sum(1 for _ in rows) == height


def test_skip_and_flatten_plan(tmp_path):
    (tmp_path / 'a.png').write_bytes(b'existing')
    sources = [Source(Path('/in/a.ARW'), Path('nested/a.ARW')),
               Source(Path('/in/b.ARW'), Path('other/b.ARW')),
               Source(Path('/more/b.ARW'), Path('again/B.ARW'))]
    jobs = plan(sources, tmp_path, preserve_folders=False, collision='skip')
    assert [target for _, target in jobs] == [None, tmp_path / 'b.png', None]
    assert (tmp_path / 'a.png').read_bytes() == b'existing'


def test_conversion_options_reach_libraw(tmp_path, monkeypatch):
    from raw_to_png.converter import ConversionOptions
    from contextlib import nullcontext
    options = ConversionOptions(white_balance='auto', half_size=True, auto_bright=True, brightness_ev=1)
    calls = []
    class Raw:
        from types import SimpleNamespace
        sizes = SimpleNamespace(height=4, width=4)
        def postprocess(self, **kwargs):
            calls.append(kwargs)
            return np.zeros((2, 2, 3), dtype=np.uint8)
    monkeypatch.setattr('raw_to_png.converter.rawpy.imread', lambda path: nullcontext(Raw()))
    output = tmp_path / 'image.png'
    convert(tmp_path / 'image.ARW', output, bits=8, options=options)
    assert calls[0]['use_auto_wb'] is True and calls[0]['use_camera_wb'] is False
    assert calls[0]['half_size'] is True and calls[0]['no_auto_bright'] is False
    assert calls[0]['bright'] == 2 and calls[0]['output_bps'] == 8
    assert png.Reader(filename=str(output)).read()[3]['bitdepth'] == 8


def test_half_size_fallback_averages_samples(tmp_path, monkeypatch):
    from raw_to_png.converter import ConversionOptions
    from contextlib import nullcontext
    from types import SimpleNamespace
    pixels = np.arange(48, dtype=np.uint16).reshape(4, 4, 3)
    class Raw:
        sizes = SimpleNamespace(height=4, width=4)
        def postprocess(self, **kwargs):
            return pixels
    monkeypatch.setattr('raw_to_png.converter.rawpy.imread', lambda path: nullcontext(Raw()))
    output = tmp_path / 'small.png'
    convert(tmp_path / 'image.ARW', output, bits=16, options=ConversionOptions(half_size=True))
    width, height, rows, meta = png.Reader(filename=str(output)).read()
    assert (width, height, meta['bitdepth']) == (2, 2, 16)
    expected = ((pixels[::2, ::2].astype(np.uint32) + pixels[1::2, ::2]
                 + pixels[::2, 1::2] + pixels[1::2, 1::2] + 2) // 4)
    np.testing.assert_array_equal(np.array(list(rows)).reshape(2, 2, 3), expected)


@pytest.mark.parametrize('bits', [8, 16])
def test_conversion_returns_actual_rotated_half_size_png_dimensions(tmp_path, monkeypatch, bits):
    from raw_to_png.converter import ConversionOptions
    from contextlib import nullcontext
    from types import SimpleNamespace
    class Raw:
        sizes = SimpleNamespace(width=6, height=4)
        def postprocess(self, **kwargs):
            return np.ones((3, 2, 3), dtype=np.uint8 if bits == 8 else np.uint16)
    monkeypatch.setattr('raw_to_png.converter.rawpy.imread', lambda path: nullcontext(Raw()))
    output = tmp_path/'rotated-small.png'
    actual = convert(tmp_path/'photo.ARW', output, bits=bits, options=ConversionOptions(half_size=True))
    width, height, _, _ = png.Reader(filename=str(output)).read()
    assert actual == (width, height) == (2, 3)
