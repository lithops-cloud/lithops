#
# (C) Copyright IBM Corp. 2020
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


def create_timeline(fs, dst):
    call_status = [f._call_status for f in fs]
    call_metadata = [f._call_metadata for f in fs]
    fs_start_time = min([cm['job_created_timestamp'] for cm in call_metadata])

    status_df = pd.DataFrame(call_status)
    metadata_df = pd.DataFrame(call_metadata)
    results_df = pd.concat([status_df, metadata_df], axis=1)
    total_calls = len(results_df)

    Cols = list(results_df.columns)
    for i, item in enumerate(results_df.columns):
        if item in results_df.columns[:i]:
            Cols[i] = "toDROP"
    results_df.columns = Cols
    results_df = results_df.drop("toDROP", 1)

    palette = sns.color_palette("deep", 6)

    fig = pylab.figure(figsize=(10, 6))
    ax = fig.add_subplot(1, 1, 1)

    y = np.arange(total_calls)
    point_size = 10

    fields = [('host submit', results_df.host_submit_time - fs_start_time),
              ('action start', results_df.start_time - fs_start_time),
              # ('jobrunner start', results_df.jobrunner_start - pw_start_time),
              ('action done', results_df.end_time - fs_start_time)]

    fields.append(('status fetched', results_df.status_done_timestamp - fs_start_time))

    if 'download_output_timestamp' in results_df:
        fields.append(('results fetched', results_df.download_output_timestamp - fs_start_time))

    patches = []
    for f_i, (field_name, val) in enumerate(fields):
        ax.scatter(val, y, c=[palette[f_i]], edgecolor='none', s=point_size, alpha=0.8)
        patches.append(mpatches.Patch(color=palette[f_i], label=field_name))

    ax.set_xlabel('Execution Time (sec)')
    ax.set_ylabel('Function Call')

    legend = pylab.legend(handles=patches, loc='upper right', frameon=True)
    legend.get_frame().set_facecolor('#FFFFFF')

    yplot_step = int(np.max([1, total_calls/20]))
    y_ticks = np.arange(total_calls//yplot_step + 2) * yplot_step
    ax.set_yticks(y_ticks)
    ax.set_ylim(-0.02*total_calls, total_calls*1.02)
    for y in y_ticks:
        ax.axhline(y, c='k', alpha=0.1, linewidth=1)

    if 'download_output_timestamp' in results_df:
        max_seconds = np.max(results_df.download_output_timestamp - fs_start_time)*1.25
    elif 'status_done_timestamp' in results_df:
        max_seconds = np.max(results_df.status_done_timestamp - fs_start_time)*1.25
    else:
        max_seconds = np.max(results_df.end_time - fs_start_time)*1.25
    xplot_step = max(int(max_seconds/8), 1)
    x_ticks = np.arange(max_seconds//xplot_step + 2) * xplot_step
    ax.set_xlim(0, max_seconds)

    ax.set_xticks(x_ticks)
    for x in x_ticks:
        ax.axvline(x, c='k', alpha=0.2, linewidth=0.8)

    ax.grid(False)
    fig.tight_layout()

    if dst is None:
        os.makedirs('plots', exist_ok=True)
        dst = os.path.join(os.getcwd(), 'plots', '{}_{}'.format(int(time.time()), 'timeline.png'))
    else:
        dst = os.path.expanduser(dst) if '~' in dst else dst
        dst = '{}_{}'.format(dst, 'timeline.png')

    fig.savefig(dst)


def create_histogram(fs, dst):
    call_status = [f._call_status for f in fs]
    call_metadata = [f._call_metadata for f in fs]
    fs_start_time = min([cm['job_created_timestamp'] for cm in call_metadata])

    total_calls = len(call_status)
    max_seconds = max([cs['end_time']-fs_start_time for cs in call_status])*2.5

    runtime_bins = np.linspace(0, max_seconds, max_seconds)

    def compute_times_rates(time_rates):
        x = np.array(time_rates)
        tzero = fs_start_time
        start_time = x[:, 0] - tzero
        end_time = x[:, 1] - tzero

        N = len(start_time)

        runtime_calls_hist = np.zeros((N, len(runtime_bins)))

        for i in range(N):
            s = start_time[i]
            e = end_time[i]
            a, b = np.searchsorted(runtime_bins, [s, e])
            if b-a > 0:
                runtime_calls_hist[i, a:b] = 1

        return {'start_time': start_time,
                'end_time': end_time,
                'runtime_calls_hist': runtime_calls_hist}

    fig = pylab.figure(figsize=(10, 6))
    ax = fig.add_subplot(1, 1, 1)

    time_rates = [(cs['start_time'], cs['end_time']) for cs in call_status]

    time_hist = compute_times_rates(time_rates)

    N = len(time_hist['start_time'])
    line_segments = LineCollection([[[time_hist['start_time'][i], i],
                                     [time_hist['end_time'][i], i]] for i in range(N)],
                                   linestyles='solid', color='k', alpha=0.6, linewidth=0.4)

    ax.add_collection(line_segments)

    ax.plot(runtime_bins, time_hist['runtime_calls_hist'].sum(axis=0), label='Total Active Calls', zorder=-1)

    yplot_step = int(np.max([1, total_calls/20]))
    y_ticks = np.arange(total_calls//yplot_step + 2) * yplot_step
    ax.set_yticks(y_ticks)
    ax.set_ylim(-0.02*total_calls, total_calls*1.02)

    xplot_step = max(int(max_seconds/8), 1)
    x_ticks = np.arange(max_seconds//xplot_step + 2) * xplot_step
    ax.set_xlim(0, max_seconds)
    ax.set_xticks(x_ticks)
    for x in x_ticks:
        ax.axvline(x, c='k', alpha=0.2, linewidth=0.8)

    ax.set_xlabel("Execution Time (sec)")
    ax.set_ylabel("Function Call")
    ax.grid(False)
    ax.legend(loc='upper right')

    fig.tight_layout()

    if dst is None:
        os.makedirs('plots', exist_ok=True)
        dst = os.path.join(os.getcwd(), 'plots', '{}_{}'.format(int(time.time()), 'histogram.png'))
    else:
        dst = os.path.expanduser(dst) if '~' in dst else dst
        dst = '{}_{}'.format(dst, 'histogram.png')

    fig.savefig(dst)
    pylab.close(fig)
