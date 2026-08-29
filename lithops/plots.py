#
# (C) Copyright IBM Corp. 2020
# (C) Copyright Cloudlab URV 2020
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
import pylab
import time
import logging
import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.patches as mpatches
from matplotlib.collections import LineCollection

sns.set_style('whitegrid')
pylab.switch_backend("Agg")
logger = logging.getLogger(__name__)


def _plot_destination(dst, suffix):
    """
    Resolves where a plot has to be written, defaulting to a timestamped
    file under a plots directory of the working directory
    """
    if dst is None:
        os.makedirs('plots', exist_ok=True)
        filename = f'{int(time.time())}_{suffix}'
        return os.path.join(os.getcwd(), 'plots', filename)
    return f'{os.path.realpath(os.path.expanduser(dst))}_{suffix}'


def _set_call_axis(ax, total_calls):
    yplot_step = max(1, total_calls // 20)
    y_ticks = np.arange(total_calls // yplot_step + 2) * yplot_step
    ax.set_yticks(y_ticks)
    ax.set_ylim(-0.02 * total_calls, total_calls * 1.02)
    return y_ticks


def _set_time_axis(ax, max_seconds):
    xplot_step = max(int(max_seconds / 8), 1)
    x_ticks = np.arange(max_seconds // xplot_step + 2) * xplot_step
    ax.set_xlim(0, max_seconds)
    ax.set_xticks(x_ticks)
    for x in x_ticks:
        ax.axvline(x, c='k', alpha=0.2, linewidth=0.8)
    return x_ticks


def _elapsed(series, t0):
    return series - t0


def _timeline_span(stats_df, t0):
    """
    Returns how far the time axis has to reach, based on the last milestone
    the run got to record
    """
    if 'host_result_done_tstamp' in stats_df:
        col = stats_df.host_result_done_tstamp
    elif 'host_status_done_tstamp' in stats_df:
        col = stats_df.host_status_done_tstamp
    else:
        col = stats_df.end_tstamp
    return np.max(col - t0) * 1.25


def _timeline_fields(stats_df, t0):
    """
    Returns a (label, elapsed times) pair per milestone that every call goes
    through. Results are only there when the client downloaded them
    """
    fields = [
        ('host submit', _elapsed(stats_df.host_submit_tstamp, t0)),
        ('function start', _elapsed(stats_df.worker_func_start_tstamp, t0)),
        ('function done', _elapsed(stats_df.worker_func_end_tstamp, t0)),
        ('status fetched', _elapsed(stats_df.host_status_done_tstamp, t0)),
    ]

    if 'host_result_done_tstamp' in stats_df:
        fields.append(
            ('results fetched', _elapsed(stats_df.host_result_done_tstamp, t0))
        )

    return fields


def create_timeline(fs, dst, figsize=(10, 6)):
    """
    Plots when every call reached each of its milestones, and writes the
    figure next to dst
    """
    stats = [f.stats for f in fs]
    t0 = min(cm['host_job_create_tstamp'] for cm in stats)

    stats_df = pd.DataFrame(stats)
    total_calls = len(stats_df)

    palette = sns.color_palette("deep", 10)

    fig = pylab.figure(figsize=figsize)
    ax = fig.add_subplot(1, 1, 1)

    y = np.arange(total_calls)
    point_size = 10
    fields = _timeline_fields(stats_df, t0)

    patches = []
    for f_i, (field_name, val) in enumerate(fields):
        ax.scatter(
            val, y, c=[palette[f_i]],
            edgecolor='none', s=point_size, alpha=0.8,
        )
        patches.append(
            mpatches.Patch(color=palette[f_i], label=field_name)
        )

    ax.set_xlabel('Execution Time (sec)')
    ax.set_ylabel('Function Call')

    legend = pylab.legend(
        handles=patches, loc='upper right', frameon=True
    )
    legend.get_frame().set_facecolor('#FFFFFF')

    y_ticks = _set_call_axis(ax, total_calls)
    for ytick in y_ticks:
        ax.axhline(ytick, c='k', alpha=0.1, linewidth=1)

    _set_time_axis(ax, _timeline_span(stats_df, t0))

    ax.grid(False)
    fig.tight_layout()
    fig.savefig(_plot_destination(dst, 'timeline.png'))


def _active_calls_hist(time_rates, t0, runtime_bins):
    """
    Turns (start, end) pairs into elapsed times, plus a per call mask of the
    time bins the call was active in, which summed gives the concurrency
    """
    x = np.array(time_rates)
    start_time = x[:, 0] - t0
    end_time = x[:, 1] - t0

    calls_hist = np.zeros((len(start_time), len(runtime_bins)))
    for i, (start, end) in enumerate(zip(start_time, end_time)):
        a, b = np.searchsorted(runtime_bins, [start, end])
        if b - a > 0:
            calls_hist[i, a:b] = 1

    return start_time, end_time, calls_hist


def create_histogram(fs, dst, figsize=(10, 6)):
    """
    Plots how long every call ran for, over the number of calls that were
    running at the same time, and writes the figure next to dst
    """
    stats = [f.stats for f in fs]
    t0 = min(cm['host_job_create_tstamp'] for cm in stats)

    total_calls = len(stats)
    max_seconds = int(max(
        cs['worker_end_tstamp'] - t0 for cs in stats
    ) * 2.5)

    runtime_bins = np.linspace(0, max_seconds, max_seconds)

    fig = pylab.figure(figsize=figsize)
    ax = fig.add_subplot(1, 1, 1)

    time_rates = [
        (cs['worker_start_tstamp'], cs['worker_end_tstamp'])
        for cs in stats
    ]
    start_time, end_time, calls_hist = _active_calls_hist(
        time_rates, t0, runtime_bins
    )

    segments = [
        [[start_time[i], i], [end_time[i], i]]
        for i in range(len(start_time))
    ]
    ax.add_collection(LineCollection(
        segments,
        linestyles='solid',
        color='k',
        alpha=0.6,
        linewidth=0.4,
    ))

    ax.plot(
        runtime_bins,
        calls_hist.sum(axis=0),
        label='Total Active Calls',
        zorder=-1,
    )

    _set_call_axis(ax, total_calls)
    _set_time_axis(ax, max_seconds)

    ax.set_xlabel('Execution Time (sec)')
    ax.set_ylabel('Function Call')
    ax.grid(False)
    ax.legend(loc='upper right')

    fig.tight_layout()
    fig.savefig(_plot_destination(dst, 'histogram.png'))
    pylab.close(fig)
