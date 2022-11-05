#!/usr/bin/env python3

import datetime
import time
from cycler import cycler
import matplotlib
#matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.patches as mpatches
import argparse
import sqlite3
import sys
import os.path
import os
import re

VERSION = '0.1'
NUMOFSECSINADAY = 60*60*24
# standard "tableau" colors without red and gray
COLORS = ['tab:blue', 'tab:orange', 'tab:green', 'tab:purple', 'tab:brown', 'tab:pink', 'tab:olive', 'tab:cyan']

# read config variable from config.py file
import config

# draws a rectangle as custom legend handler
class MyLine2DHandler(object):
    def legend_artist(self, legend, orig_handle, fontsize, handlebox):
        x0, y0 = handlebox.xdescent, handlebox.ydescent
        width, height = handlebox.width, handlebox.height
        patch = mpatches.Rectangle([x0, y0], width, height, facecolor=orig_handle.get_color())
        handlebox.add_artist(patch)
        return patch

def is_local_bit_set(mac):
    byte = mac.split(':')
    return int(byte[0], 16) & 0b00000010 == 0b00000010

def get_data(args):
    if args.verbose:
        print(f':: Processing kismet file {args.db}')
    # sqlite3
    conn = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    c = conn.cursor()
    sql = 'pragma quick_check;'
    try:
        c.execute(sql)
        res = c.fetchone()[0]
        if res != 'ok':
            raise sqlite3.DatabaseError()
    except sqlite3.DatabaseError:
        print(f'Error: {args.db} db failed integrity check')
        sys.exit(1)

    sql = 'pragma query_only = on;'
    c.execute(sql)
    sql = 'pragma temp_store = 2;' # to store temp table and indices in memory
    c.execute(sql)
    sql = 'pragma journal_mode = off;' # disable journal for rollback (we don't use this)
    c.execute(sql)
    conn.commit()

    # use last packet ts_sec
    #sql = 'select ts_sec from packets where phyname="IEEE802.11" order by ts_sec asc limit 1;'
    #c.execute(sql)
    #ts_sec_first = datetime.datetime.fromtimestamp(c.fetchone()[0])
    sql = 'select ts_sec from packets where phyname="IEEE802.11" order by ts_sec desc limit 1;'
    c.execute(sql)
    res = c.fetchone()
    if not res:
        print('Error: no packet found', file=sys.stderr)
        sys.exit(1)
    ts_sec_last = datetime.datetime.fromtimestamp(res[0])
    if args.end_time > ts_sec_last:
        args.end_time = ts_sec_last
        if not args.start:
            args.start_time = args.end_time - args.time_span

    if args.datasource:
        sql = 'select ts_sec,ts_usec,signal from packets where phyname="IEEE802.11" and sourcemac=? and datasource in ('+','.join(['?']*len(args.datasource))+');'
        sql_args = (args.mac.upper(), *args.datasource)
    else:
        sql = 'select ts_sec,ts_usec,signal from packets where phyname="IEEE802.11" and sourcemac=?;'
        sql_args = (args.mac.upper(),)
    c.execute(sql, sql_args)
    times = []
    rssis = []
    for row in c.fetchall():
        ts_sec = datetime.datetime.fromtimestamp(row[0])
        ts_sec = ts_sec.replace(microsecond=row[1])
        if ts_sec > args.end_time or ts_sec < args.start_time:
            continue
        if row[2] < args.rssi or row[2] == 0:
            continue
        times.append(row[0])
        rssis.append(row[2])

    conn.close()

    return (times, rssis)

def plot_data(times, rssis, args):
    # set line style
    matplotlib.rc('lines', linestyle='', marker='.', markersize=2)
    fig, ax = plt.subplots()
    # change margin around axis to the border
    fig.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.07)
    # set our custom color cycler (without red and gray)
    ax.set_prop_cycle(cycler('color', COLORS))

    # plot
    lines = []
    label = args.mac
    line, = ax.plot(times, rssis, label=label)
    if args.label:
        ax.text(args.end_time, q[-1], label, fontsize=8, color='black', horizontalalignment='right', verticalalignment='center', family='monospace')

    # define helper function for labels and ticks
    def showdate(tick, pos):
        return time.strftime('%Y-%m-%d', time.localtime(tick))
    def showtime(tick, pos):
        return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(tick))
    def showhourminute(tick, pos):
        return time.strftime('%H:%M', time.localtime(tick))
    def showhour(tick, pos):
        return time.strftime('%Hh', time.localtime(tick))
    def showrssi(tick, pos):
        try:
            indx = times.index(tick)
            return rssis[indx]
        except ValueError:
            return None

    ## customize the appearence of our figure/plot
    ax.xaxis.set_remove_overlapping_locs(False)
    # customize label of major/minor ticks
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(showdate))
    if args.time_span > datetime.timedelta(days=4):
        # show minor tick every 6 hours
        ax.xaxis.set_minor_formatter(ticker.FuncFormatter(showhour))
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(6*60*60))
    elif args.time_span > datetime.timedelta(days=2):
        # show minor tick every 6 hours
        ax.xaxis.set_minor_formatter(ticker.FuncFormatter(showhour))
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(3*60*60))
    elif args.time_span > datetime.timedelta(days=1):
        # show minor tick every hour
        ax.xaxis.set_minor_formatter(ticker.FuncFormatter(showhour))
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(60*60))
    elif args.time_span <= datetime.timedelta(days=1):
        # show minor tick every x minutes
        ax.xaxis.set_minor_formatter(ticker.FuncFormatter(showhourminute))
        h = args.time_span / datetime.timedelta(hours=1)
        sm = 10*60
        if h > 2:
            sm = 15*60
        if h > 6:
            sm = 30*60
        if h > 12:
            sm = 60*60
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(sm))
    elif args.time_span < datetime.timedelta(hours=6):
        # show minor tick every 5 minutes
        ax.xaxis.set_minor_formatter(ticker.FuncFormatter(showhourminute))
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(5*60))

    # move down major tick labels not to overwrite minor tick labels and do not show major ticks
    ax.xaxis.set_tick_params(which='major', pad=15, length=0)
    # customize the label shown on mouse over
    ax.format_xdata = ticker.FuncFormatter(showtime)
    ax.format_ydata = ticker.FuncFormatter(showrssi)
    # show vertical bars matching minor ticks
    ax.grid(True, axis='x', which='minor')
    # add a legend
    if args.legend:
        # add a custom label handler to draw rectangle instead of default line style
        ax.legend(lines, [args.mac], loc='lower left', ncol=1//30+1,
            handler_map={matplotlib.lines.Line2D: MyLine2DHandler()}, prop={'family':'monospace', 'size':8})
    # avoid too much space around our data by defining set
    space = datetime.timedelta(minutes=5) # 5 minutes
    ax.set_xlim((args.start_time-space).timestamp(), (args.end_time+space).timestamp())
    ax.set_ylim(min(rssis), max(rssis))
    # add a title to the image
    if args.title is not None:
        if args.title == '':
            ts = time.localtime(os.stat(args.db).st_mtime)
            title = time.strftime('%Y-%m-%d %H:%M:%S', ts)
        else:
            title = args.title
        fig.text(0.49, 0.97, title, fontsize=8, alpha=0.2)

    # and tada !
    if args.image:
        fig.set_size_inches(config.HEIGHT/config.DPI, config.WIDTH/config.DPI)
        fig.savefig(args.image, dpi=config.DPI)
        #fig.savefig('test.svg', format='svg')
    else:
        plt.show()

def main():
    parser = argparse.ArgumentParser(description="Plot a timeline of devices' activity as captured by kismet")
    parser.add_argument('-b', '--db', help='file name of the kismet db')
    parser.add_argument('-d', '--datasource', action='append', help='filter datasource to use')
    parser.add_argument('-i', '--image', default=None, const='plot.png', nargs='?', help='output an image')
    parser.add_argument('-l', '--legend', action='store_true', default=False, help='add a legend')
    parser.add_argument('--label', action='store_true', default=False, help='add a mac label for each plot')
    parser.add_argument('-m', '--mac', required=True, help='only display that mac')
    parser.add_argument('-r', '--rssi', type=int, default=-99, help='minimal value for RSSI')
    parser.add_argument('-s', '--start', help='start timestamp')
    parser.add_argument('--time-span', default='1d', help='time span (expected format [###d][###h][###m]')
    parser.add_argument('-t', '--title', nargs='?', const='', default=None, help='add a title to the top of image (if none specified, use a timestamp)')
    parser.add_argument('-v', '--verbose', action='store_true', default=False, help='be verbose')
    # RESERVED: args.span, args.start_time, args.end_time
    args = parser.parse_args()

    # parse time_span
    tmsp = args.time_span
    args.time_span = datetime.timedelta(hours=0)
    number = ''
    for c in tmsp:
        if c in '0123456789':
            number += c
        else:
            try:
                if c == 'd':
                    args.time_span += datetime.timedelta(days=int(number))
                    args.span = 'd'
                    number = ''
                elif c == 'h':
                    args.time_span += datetime.timedelta(hours=int(number))
                    args.span = 'h'
                    number = ''
                elif c == 'm':
                    args.time_span += datetime.timedelta(minutes=int(number))
                    args.span = 'm'
                    number = ''
                else:
                    print('Error: --times-span postfix number could only be d or h or m')
                    sys.exit(-1)
            except ValueError:
                print('Error: --time-span argument should be of the form [:number:][d|h|m]')
                sys.exit(-1)

    if not args.db or not os.path.exists(args.db):
        print(f'Error: file not found {args.db}', file=sys.stderr)
        sys.exit(-1)

    if args.start:
        try:
            start_time = datetime.datetime.strptime(args.start, '%Y-%m-%dT%H:%M')
        except  ValueError:
            try:
                start_time = datetime.datetime.strptime(args.start, '%Y-%m-%d')
                start_time = datetime.datetime.strptime(f'{args.start}T12:00', '%Y-%m-%dT%H:%M')
            except ValueError:
                print("Error: can't parse date timestamp, excepted format YYYY-mm-dd[THH:MM]", file=sys.stderr)
                sys.exit(-1)
        end_time = start_time + args.time_span
    else:
        end_time = datetime.datetime.now()
        start_time = end_time - args.time_span
    args.start_time = start_time
    args.end_time = end_time

    if args.verbose:
        print(':: Gathering data')
    times, rssis = get_data(args)
    if len(times) == 0 or len(rssis) == 0:
        print('Error: nothing to plot', file=sys.stderr)
        sys.exit(-1)

    if args.verbose:
        print(':: Plotting data')
    plot_data(times, rssis, args)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt as k:
        pass
