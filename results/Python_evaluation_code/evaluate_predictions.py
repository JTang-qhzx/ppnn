"""Evaluate predictions. Compute CRPS for raw ensemble and PP predictions.

Need to have enstools.scores installed along with the scoringRules R package.

Some functions here are duplicates of functions in utils.py
This is done on purpose to make sure that the evaluation is correct.
"""
import argparse
from netCDF4 import Dataset, num2date
from datetime import datetime
import numpy as np
import pandas as pd
import os
from scipy.stats import norm
import sys
sys.path.append('/Users/stephanrasp/repositories/enstools')
from enstools.scores import crps_sample
import matplotlib.pyplot as plt
import seaborn as sns
from glob import glob
import os
import pdb

# Basic setup
date_format = '%Y-%m-%d'
obs_csv = './obs.csv'
raw_csv = './raw_crps.csv'


# Auxiliary functions
def load_obs_data(data_dir):
    """
    Loads obs [time, station], dates and station_ids
    """
    rg = Dataset(data_dir + 'data_interpolated_00UTC.nc')
    obs = rg.variables['t2m_obs'][:]
    station_id = rg.variables['station_id'][:]
    dates = num2date(rg.variables['time'][:],
                     units=rg.variables['time'].units)
    return obs, dates, station_id


def load_raw_ens_data(data_dir):
    """
    Loads raw ensemble [time, ens, station]
    """
    rg = Dataset(data_dir + 'data_interpolated_00UTC.nc')
    ens = rg.variables['t2m_fc'][:]
    return ens


def get_station_ids(obs, station_id):
    """
    Expand station ID to shape of obs
    """
    s = obs.shape
    station_ids = np.array([list(station_id)] * s[0])
    return station_ids


def get_date_strs(obs, dates):
    """
    Expand date_str to shape of obs
    """
    s = obs.shape
    date_strs = [datetime.strftime(dt, date_format) for dt in list(dates)]
    date_strs = np.array([list(date_strs)] * s[1])
    date_strs = np.rollaxis(date_strs, 1, 0)
    return date_strs


def return_date_idx(dates, date_str=None, y=None, m=None, d=None):
    """
    Return date index given a date string
    """
    if date_str is not None:
        dt = datetime.strptime(date_str, date_format)
    else:
        dt = datetime(y, m, d, 0, 0)
    return np.where(dates == dt)[0][0]


def crps_normal(mu, sigma, y):
    """
    Compute CRPS for a Gaussian distribution. 
    """
    # Make sure sigma is positive
    sigma = np.abs(sigma)
    loc = (y - mu) / sigma
    crps = sigma * (loc * (2 * norm.cdf(loc) - 1) + 
                    2 * norm.pdf(loc) - 1. / np.sqrt(np.pi))
    return crps


def plot_results(df):
    """
    Plots a summary figure of the scores.
    """
    # Create relative improvement column
    ref = df['crps'][0]
    df.loc[:, 'improvement in %'] = (ref - df['crps'])  / ref * 100
    plt.title('Raw ensemble CRPS: %.2f' % ref)
    sns.barplot(y='name', x='crps', data=df, palette='cubehelix_r')
    plt.xlim(0.6, 1.2)
    plt.savefig('./results', bbox_inches='tight')


# Central routines
def prepare_obs_df_and_compute_raw_crps(inargs):
    """
    Load and save observation dataframe and compute and return raw ens
    CRPS.
    """

    if not os.path.exists(obs_csv) or not os.path.exists(raw_csv) \
            or inargs.recompute:
        if inargs.verbose > 0: print('Get observations and compute raw crps')
        # Load the observation data
        obs, dates, station_id = load_obs_data(inargs.data_dir)
        ens = load_raw_ens_data(inargs.data_dir)

        # Create corresponding date and station_id arrays
        date_array = get_date_strs(obs, dates)
        station_id_array = get_station_ids(obs, station_id)

        # Cut out dates
        date_idx_start = return_date_idx(dates, inargs.date_start)
        date_idx_stop = return_date_idx(dates, inargs.date_stop)
        obs = obs[date_idx_start:date_idx_stop]
        date_array = date_array[date_idx_start:date_idx_stop]
        station_id_array = station_id_array[date_idx_start:date_idx_stop]
        ens = ens[date_idx_start:date_idx_stop]

        # Reorder axes of ens
        ens = np.rollaxis(ens, 1, 0)

        # Ravel arrays
        obs = np.ravel(obs)
        date_array = np.ravel(date_array)
        station_id_array = np.ravel(station_id_array)
        ens = np.reshape(ens, (ens.shape[0], -1))

        # Remove NaNs
        mask = np.isfinite(obs)

        # Save to dataframe
        obs_df = pd.DataFrame({
            'date': date_array[mask],
            'station_id': station_id_array[mask],
            'obs': obs[mask],
            })
        obs_df.to_csv(obs_csv)

        # Compute raw CRPS
        raw_crps = crps_sample(obs[mask].data, ens[:, mask].data, mean=True)
        pd.DataFrame({
            'raw_crps': [raw_crps]
        }).to_csv(raw_csv)

    else:
        if inargs.verbose > 0: print('Read raw CRPS')
        raw_crps = pd.read_csv(raw_csv)['raw_crps'][0]

    return raw_crps


def evaluate(inargs):
    """
    Compute CRPS for all experiments. Checks first if all data are present.
    """

    # Load obs data
    obs_df = pd.read_csv(obs_csv)

    # Load predictions
    if len(inargs.eval_files) == 0:
        inargs.eval_files = glob('./csv_files/*.csv')
    elif '*' in inargs.eval_files:
        inargs.eval_files = glob(inargs.eval_files)
    pred_dfs = [pd.read_csv(fn) for fn in inargs.eval_files]

    # Sort first by date, then by station id 
    obs_df = obs_df.sort_values(['date', 'station_id'])
    pred_dfs = [p.sort_values(['date', 'station_id']) for p in pred_dfs]

    # Check if all required data are there
    for ip, p in enumerate(pred_dfs):
        if inargs.verbose > 0: print('Checking file:', inargs.eval_files[ip])
        assert obs_df['date'].equals(p['date']), \
            'Wrong dates for %s' % inargs.eval_files[ip]
        assert np.array_equal(obs_df['station_id'], p['station_id']), \
            'Wrong station_ids for %s' % inargs.eval_files[ip]

    # Compute scores
    crps_list = [np.mean(crps_normal(p['mean'], p['std'], obs_df['obs'])) for 
                 p in pred_dfs]
    return crps_list


# Main program
def main(inargs):
    """
    Main routine for evaluation. Saves the CRPS for all experiments 
    and plots a histogram.
    """
    assert inargs.date_start == '2016-01-01' and inargs.date_stop == '2017-01-01', \
        'Flexible dates not implemented.'

    # Get observation data
    raw_crps = prepare_obs_df_and_compute_raw_crps(inargs)

    # Compute scores
    crps_list = evaluate(inargs)

    # Print and save results
    print('Raw CRPS', raw_crps)
    for i in range(len(inargs.eval_files)):
        print(inargs.eval_files[i], crps_list[i])
    crps_df = pd.DataFrame({
        'name': ['raw_ensemble'] + [e.split('/')[-1].split('.')[0]
                                    for e in inargs.eval_files],
        'crps': [raw_crps] + crps_list
        })
    if inargs.sort_by_score:
        crps_df = crps_df.sort_values('crps')
    crps_df.to_csv('./crps.csv')

    # Plot results
    plot_results(crps_df)


if __name__ == '__main__':

    description = __doc__

    parser = argparse.ArgumentParser(description=description)

    parser.add_argument('--data_dir',
                        type=str,
                        help='Directory containing observation data.')
    parser.add_argument('--eval_files',
                        type=str,
                        nargs='+',
                        default=[],
                        help='Predictions to be evaluated. '
                             'If empty, all from csv_file directory.')
    parser.add_argument('--date_start',
                        type=str,
                        default='2016-01-01',
                        help='Inclusive.')
    parser.add_argument('--date_stop',
                        type=str,
                        default='2017-01-01',
                        help='Exclusive.')
    parser.add_argument('--sort_by_score',
                        dest='sort_by_score',
                        action='store_true',
                        help='Sort results by score for plotting.')
    parser.set_defaults(sort_by_score=False)
    parser.add_argument('--verbose',
                        type=int,
                        default=0,
                        help='Verbosity level.')
    parser.add_argument('--recompute',
                        dest='recompute',
                        action='store_true',
                        help='Do not try to reuse obs and raw ens crps file.')
    parser.set_defaults(recompute=False)

    args = parser.parse_args()

    main(args)
