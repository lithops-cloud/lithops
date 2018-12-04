import os
import pylab
import logging
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib import patches as mpatches
from matplotlib.collections import LineCollection

sns.set_style('whitegrid')
logger = logging.getLogger(__name__)


def create_timeline(dst, name, run_statuses, invoke_statuses):
    results_df = pd.DataFrame(run_statuses)
    invoke_df = pd.DataFrame(invoke_statuses)

    results_df = pd.concat([results_df, invoke_df], axis=1)
    Cols = list(results_df.columns)
    for i, item in enumerate(results_df.columns):
        if item in results_df.columns[:i]:
            Cols[i] = "toDROP"
    results_df.columns = Cols
    results_df = results_df.drop("toDROP", 1)

    palette = sns.color_palette("deep", 6)
    time_offset = np.min(results_df.host_submit_time)
    fig = pylab.figure(figsize=(10, 6))
    ax = fig.add_subplot(1, 1, 1)
    total_jobs = len(results_df)

    y = np.arange(total_jobs)
    point_size = 10

    fields = [
              ('host submit', results_df.host_submit_time - time_offset),
              ('action start', results_df.start_time - time_offset),
              ('jobrunner start', results_df.jobrunner_start - time_offset),
              ('action done', results_df.end_time - time_offset),
              ('results fetched', results_df.download_output_timestamp - time_offset)
             ]

    patches = []
    for f_i, (field_name, val) in enumerate(fields):
        ax.scatter(val, y, c=[palette[f_i]], edgecolor='none', s=point_size, alpha=0.8)
        patches.append(mpatches.Patch(color=palette[f_i], label=field_name))

    ax.set_xlabel('wallclock time (sec)')
    ax.set_ylabel('job')
    #pylab.ylim(0, 10)

    legend = pylab.legend(handles=patches, loc='upper right', frameon=True)
    #pylab.title("Runtime for {} jobs of {:3.0f}M double ops (dgemm) each".format(total_jobs, JOB_GFLOPS))
    legend.get_frame().set_facecolor('#FFFFFF')

    plot_step = int(np.max([1, total_jobs/32]))

    y_ticks = np.arange(total_jobs//plot_step + 2) * plot_step

    ax.set_yticks(y_ticks)
    ax.set_ylim(-0.02*total_jobs, total_jobs*1.05)

    ax.set_xlim(-1, np.max(results_df.download_output_timestamp - time_offset)*1.35)
    #ax.set_xlim(-0.02, np.max(8))

    for y in y_ticks:
        ax.axhline(y, c='k', alpha=0.1, linewidth=1)

    ax.grid(False)
    fig.tight_layout()
    fig.savefig(os.path.join(dst, name+"_timeline.png"))


def create_histogram(dst, name, run_statuses, x_lim=300):
    runtime_bins = np.linspace(0, x_lim, x_lim)

    def compute_times_rates(d):
        x = np.array(d)

        tzero = np.min(x[:, 0])
        start_time = x[:, 0] - tzero
        end_time = x[:, 1] - tzero

        N = len(start_time)

        runtime_jobs_hist = np.zeros((N, len(runtime_bins)))

        for i in range(N):
            s = start_time[i]
            e = end_time[i]
            a, b = np.searchsorted(runtime_bins, [s, e])
            if b-a > 0:
                runtime_jobs_hist[i, a:b] = 1

        return {'start_time': start_time,
                'end_time': end_time,
                'runtime_jobs_hist': runtime_jobs_hist}

    fig = pylab.figure(figsize=(10, 6))
    ax = fig.add_subplot(1, 1, 1)

    time_rates = [(rs['start_time'], rs['end_time']) for rs in run_statuses]

    time_hist = compute_times_rates(time_rates)

    N = len(time_hist['start_time'])
    line_segments = LineCollection([[[time_hist['start_time'][i], i],
                                     [time_hist['end_time'][i], i]] for i in range(N)],
                                   linestyles='solid', color='k', alpha=0.4, linewidth=0.2)

    ax.add_collection(line_segments)

    ax.plot(runtime_bins, time_hist['runtime_jobs_hist'].sum(axis=0),
            label='active jobs total', zorder=-1)

    ax.set_xlim(0, x_lim)
    ax.set_ylim(0, len(time_hist['start_time'])*1.05)
    ax.set_xlabel("time (sec)")

    ax.set_ylabel("IBM Cloud function execution")
    ax.grid(False)
    ax.legend(loc='upper right')

    fig.tight_layout()
    fig.savefig(os.path.join(dst, name+"_histogram.png"))
