import matplotlib
matplotlib.use('Agg')
import io
import os
import pylab
import logging
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib import patches as mpatches
from matplotlib.collections import LineCollection
from pywren_ibm_cloud.storage.backends import cos
sns.set_style('whitegrid')
logger = logging.getLogger(__name__)


def create_timeline(dst, name, pw_start_time, run_statuses, invoke_statuses, cos_config):
    results_df = pd.DataFrame(run_statuses)

    if invoke_statuses:
        invoke_df = pd.DataFrame(invoke_statuses)
        results_df = pd.concat([results_df, invoke_df], axis=1)
        Cols = list(results_df.columns)
        for i, item in enumerate(results_df.columns):
            if item in results_df.columns[:i]:
                Cols[i] = "toDROP"
        results_df.columns = Cols
        results_df = results_df.drop("toDROP", 1)

    palette = sns.color_palette("deep", 6)
    #time_offset = np.min(results_df.host_submit_time)
    fig = pylab.figure(figsize=(10, 6))
    ax = fig.add_subplot(1, 1, 1)
    total_jobs = len(results_df)

    y = np.arange(total_jobs)
    point_size = 10

    fields = [('host submit', results_df.host_submit_time - pw_start_time),
              ('action start', results_df.start_time - pw_start_time),
              #('jobrunner start', results_df.jobrunner_start - pw_start_time),
              ('action done', results_df.end_time - pw_start_time)]

    if 'download_output_timestamp' in results_df:
        fields.append(('results fetched', results_df.download_output_timestamp - pw_start_time))
    elif 'status_done_timestamp' in results_df:
        fields.append(('status fetched', results_df.status_done_timestamp - pw_start_time))

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
    for y in y_ticks:
        ax.axhline(y, c='k', alpha=0.1, linewidth=1)

    if 'download_output_timestamp' in results_df:
        max_seconds = np.max(results_df.download_output_timestamp - pw_start_time)*1.25
    elif 'status_done_timestamp' in results_df:
        max_seconds = np.max(results_df.status_done_timestamp - pw_start_time)*1.25
    else:
        max_seconds = np.max(results_df.end_time - pw_start_time)*1.25

    xplot_step = max(int(max_seconds/8), 1)
    x_ticks = np.arange(max_seconds//xplot_step + 2) * xplot_step
    ax.set_xlim(0, max_seconds)

    ax.set_xticks(x_ticks)
    for x in x_ticks:
        ax.axvline(x, c='k', alpha=0.2, linewidth=0.8)

    ax.grid(False)
    fig.tight_layout()

    if dst.split('://')[0] == 'cos':
        save_plot_in_cos(cos_config, fig, dst, name+"_timeline.png")
    else:
        fig.savefig(os.path.join(dst, name+"_timeline.png"))


def create_histogram(dst, name, pw_start_time, run_statuses, cos_config):
    runtime_bins = np.linspace(0, 600, 600)

    def compute_times_rates(time_rates):
        x = np.array(time_rates)

        #tzero = np.min(x[:, 0])
        tzero = pw_start_time
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
                                   linestyles='solid', color='k', alpha=0.6, linewidth=0.4)

    ax.add_collection(line_segments)

    ax.plot(runtime_bins, time_hist['runtime_jobs_hist'].sum(axis=0),
            label='active jobs total', zorder=-1)

    #ax.set_xlim(0, x_lim)
    ax.set_xlim(0, np.max(time_hist['end_time'])*3)
    ax.set_ylim(0, len(time_hist['start_time'])*1.05)
    ax.set_xlabel("time (sec)")

    ax.set_ylabel("IBM Cloud function execution")
    ax.grid(False)
    ax.legend(loc='upper right')

    fig.tight_layout()
    if dst.split('://')[0] == 'cos':
        save_plot_in_cos(cos_config, fig, dst, name+"_histogram.png")
    else:
        fig.savefig(os.path.join(dst, name+"_histogram.png"))


def save_plot_in_cos(cos_config, fig, dst, filename):
    bucketname = dst.split('cos://')[1].split('/')[0]
    key = os.path.join(*dst.split('cos://')[1].split('/')[1:], filename)

    buff = io.BytesIO()
    fig.savefig(buff)
    buff.seek(0)

    cos_handler = cos.COSBackend(cos_config)
    cos_handler.put_object(bucketname, key, buff.read())
