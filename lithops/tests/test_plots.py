#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
from unittest.mock import MagicMock

import pytest

seaborn = pytest.importorskip('seaborn')  # noqa: F401

from lithops.plots import (  # noqa: E402
    _elapsed,
    _plot_destination,
    _set_call_axis,
    _set_time_axis,
    _timeline_span,
    create_histogram,
    create_timeline,
)


class TestPlotDestination:

    def test_none_writes_under_plots_with_suffix(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr('lithops.plots.time.time', lambda: 1234)
        path = _plot_destination(None, 'timeline.png')
        assert path == os.path.join(str(tmp_path), 'plots', '1234_timeline.png')
        assert os.path.isdir(tmp_path / 'plots')

    def test_explicit_path_appends_suffix(self, tmp_path):
        dst = tmp_path / 'run'
        dst.write_text('')
        path = _plot_destination(str(dst), 'histogram.png')
        assert path == '{}_{}'.format(os.path.realpath(dst), 'histogram.png')

    def test_expands_user_home_when_tilde_present(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        path = _plot_destination(os.path.join('~', 'out'), 'timeline.png')
        expected = '{}_{}'.format(
            os.path.realpath(os.path.join(str(tmp_path), 'out')),
            'timeline.png',
        )
        assert path == expected


class TestPlotAxes:

    def test_call_axis_sets_ticks_and_ylim(self):
        ax = MagicMock()
        y_ticks = _set_call_axis(ax, 40)
        ax.set_yticks.assert_called_once()
        ax.set_ylim.assert_called_once()
        assert len(y_ticks) > 0

    def test_time_axis_draws_vertical_guides(self):
        ax = MagicMock()
        x_ticks = _set_time_axis(ax, 16)
        ax.set_xlim.assert_called_once_with(0, 16)
        ax.set_xticks.assert_called_once()
        assert ax.axvline.call_count == len(x_ticks)


class TestElapsedAndSpan:

    def test_elapsed_subtracts_origin(self):
        import pandas as pd
        series = pd.Series([10.0, 12.0])
        assert list(_elapsed(series, 10.0)) == [0.0, 2.0]

    def test_timeline_span_prefers_result_then_status_then_end(self):
        import pandas as pd
        t0 = 100.0
        with_result = pd.DataFrame({
            'host_result_done_tstamp': [104.0],
            'host_status_done_tstamp': [103.0],
            'end_tstamp': [102.0],
        })
        assert _timeline_span(with_result, t0) == pytest.approx(4.0 * 1.25)
        with_status = pd.DataFrame({
            'host_status_done_tstamp': [108.0],
            'end_tstamp': [102.0],
        })
        assert _timeline_span(with_status, t0) == pytest.approx(8.0 * 1.25)
        with_end = pd.DataFrame({'end_tstamp': [110.0]})
        assert _timeline_span(with_end, t0) == pytest.approx(10.0 * 1.25)


def _stats(t0=1000.0, with_result=True):
    stats = {
        'host_job_create_tstamp': t0,
        'host_submit_tstamp': t0 + 0.1,
        'worker_func_start_tstamp': t0 + 0.2,
        'worker_func_end_tstamp': t0 + 0.8,
        'host_status_done_tstamp': t0 + 0.9,
        'worker_start_tstamp': t0 + 0.2,
        'worker_end_tstamp': t0 + 0.8,
    }
    if with_result:
        stats['host_result_done_tstamp'] = t0 + 1.0
    return stats


class FakePlotFuture:
    def __init__(self, stats):
        self.stats = stats


class TestCreatePlots:

    def test_create_timeline_and_histogram_write_files(self, tmp_path):
        fs = [FakePlotFuture(_stats()), FakePlotFuture(_stats(t0=1000.2))]
        dest = str(tmp_path / 'run')
        create_timeline(fs, dest, figsize=(4, 3))
        create_histogram(fs, dest, figsize=(4, 3))
        timeline = '{}_{}'.format(os.path.realpath(dest), 'timeline.png')
        histogram = '{}_{}'.format(os.path.realpath(dest), 'histogram.png')
        assert os.path.isfile(timeline)
        assert os.path.isfile(histogram)

    def test_create_timeline_without_result_timestamps(self, tmp_path):
        fs = [FakePlotFuture(_stats(with_result=False))]
        dest = str(tmp_path / 'status-only')
        create_timeline(fs, dest, figsize=(4, 3))
        assert os.path.isfile('{}_{}'.format(os.path.realpath(dest), 'timeline.png'))
