#!/usr/bin/env python3

from datetime import datetime
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
    ts = {}
    if args.verbose:
        print(f':: Processing kismet file {args.db}')
    # sqlite3
    conn = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    c = conn.cursor()
    sql = 'pragma query_only = on;'
    c.execute(sql)
    sql = 'pragma temp_store = 2;' # to store temp table and indices in memory
    c.execute(sql)
    sql = 'pragma journal_mode = off;' # disable journal for rollback (we don't use this)
    c.execute(sql)
    conn.commit()

    sql = 'select ts_sec,ts_usec,lower(sourcemac),lower(destmac),packet,signal from packets where phyname="IEEE802.11";'
    c.execute(sql)
    for row in c.fetchall():
        if row[5] < args.rssi:
            continue
        if row[2] in ts:
            ts[row[2]].append(row[0])
        else:
            ts[row[2]] = [row[0]]
        if row[3] in ts:
            ts[row[3]].append(row[0])
        else:
            ts[row[3]] = [row[0]]

    # filter to keep only wifi client and device
    sql = 'select lower(devmac),type from devices'
    c.execute(sql)
    dev_type = {}
    for row in c.fetchall():
        dev_type[row[0]] = row[1]
    conn.close()

    for k in list(ts.keys()):
        # remove Wi-Fi AP and Wi-Fi-Bridged
        if k not in dev_type or dev_type[k] not in ('Wi-Fi Device','Wi-Fi Client', 'Wi-Fi Ad-Hoc'):
            del ts[k]

    def match(m, s):
        # match on start of mac address and use % as wild-card like in SQL syntax
        if '%' in m:
            m = m.replace('%', '.*')
        else:
            m = m+'.*'
        m = '^'+m
        return re.search(m, s) is not None

    macs = list(ts.keys())
    if args.mac :
        # keep mac with args.mac as substring
        macs = [m for m in list(ts.keys()) if any(match(am.lower(), m) for am in args.mac)]

    # filter our data set based on min probe request or mac appearence
    for k,v in list(ts.items()):
        if (len(v) <= args.min and k not in args.knownmac) or k not in macs or k in config.IGNORED:
            del ts[k]

    # sort the data on frequency of appearence
    data = sorted(list(ts.items()), key=lambda x:len(x[1]))
    data.reverse()
    macs = [x for x,_ in data]
    times = [x for _,x in data]

    # merge all LAA mac into one plot for a virtual MAC called 'LAA'
    if args.privacy:
        indx = [i for i,m in enumerate(macs) if is_local_bit_set(m)]
        if len(indx) > 0:
            t = []
            # merge all times for LAA macs
            for i in indx:
                t.extend(times[i])
            macs = [m for i,m in enumerate(macs) if i not in indx]
            times = [x for i,x in enumerate(times) if i not in indx]
            macs.append('LAA')
            times.append(sorted(t))

    # merge all same vendor mac into one plot for a virtual MAC called 'OUI'
    for mv in args.merged:
        indx = [i for i,m in enumerate(macs) if m[:8] == mv]
        if len(indx) > 0:
            t = []
            # merge all times for vendor macs
            for i in indx:
                t.extend(times[i])
            macs = [m for i,m in enumerate(macs) if i not in indx]
            times = [x for i,x in enumerate(times) if i not in indx]
            macs.append(mv)
            times.append(sorted(t))

    return (macs, times)

def plot_data(macs, times, args):
    fig, ax = plt.subplots()
    # change margin around axis to the border
    fig.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.07)
    # set our custom color cycler (without red and gray)
    ax.set_prop_cycle(cycler('color', COLORS))

    # calculate size of marker given the number of macs to display and convert from inch to point
    markersize = (fig.get_figheight()/len(macs))*72
    # set default line style for the plot
    matplotlib.rc('lines', linestyle=':', linewidth=0.3, marker='|', markersize=markersize)
    # plot
    lines = []
    for i,p in enumerate(times):
        # reverse order to get most frequent at top
        n = len(times)-i-1
        # constant value
        q = [n]*len(p)
        label = macs[i]
        if macs[i] in args.knownmac:
            line, = ax.plot(p, q, color='tab:red', label=label)
        elif macs[i] == 'LAA' or is_local_bit_set(macs[i]):
            if macs[i] != 'LAA':
                label = '%s (LAA)' % macs[i]
            line, = ax.plot(p, q, color='tab:gray', label=label)
        else:
            line, = ax.plot(p, q, label=label)
        if args.label:
            ax.text(args.end_time, q[-1], label, fontsize=8, color='black', horizontalalignment='right', verticalalignment='center', family='monospace')
        lines.append(line)

    # add a grey background on period greater than 15 minutes without data
    alltimes = []
    for t in times:
       alltimes.extend(t)
    alltimes.sort()
    diff = [i for i,j in enumerate(zip(alltimes[:-1], alltimes[1:])) if (j[1]-j[0])>60*15]
    for i in diff:
        ax.axvspan(alltimes[i], alltimes[i+1], facecolor='#bbbbbb', alpha=0.5)

    # define helper function for labels and ticks
    def showdate(tick, pos):
        return time.strftime('%Y-%m-%d', time.localtime(tick))
    def showtime(tick, pos):
        return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(tick))
    def showhourminute(tick, pos):
        return time.strftime('%H:%M', time.localtime(tick))
    def showhour(tick, pos):
        return time.strftime('%Hh', time.localtime(tick))
    def showmac(tick, pos):
        try:
            m = macs[len(times)-int(round(tick))-1]
            if m != 'LAA' and is_local_bit_set(m):
                m = '%s (LAA)' % m
            return m
        except IndexError:
            pass

    ## customize the appearence of our figure/plot
    ax.xaxis.set_remove_overlapping_locs(False)
    # customize label of major/minor ticks
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(showdate))
    if args.span == 'd':
        # show minor tick every hour
        ax.xaxis.set_minor_formatter(ticker.FuncFormatter(showhour))
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(60*60))
    elif args.span == 'h':
        # show minor tick every x minutes
        ax.xaxis.set_minor_formatter(ticker.FuncFormatter(showhourminute))
        h = args.time_span//3600
        sm = 10*60
        if h > 2:
            sm = 15*60
        if h > 6:
            sm = 30*60
        if h > 12:
            sm = 60*60
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(sm))
    elif args.span == 'm':
        # show minor tick every 5 minutes
        ax.xaxis.set_minor_formatter(ticker.FuncFormatter(showhourminute))
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(5*60))

    # show only integer evenly spaced on y axis
    #ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True, steps=[1,2,4,5,10]))
    # don't draw y axis
    ax.yaxis.set_visible(False)
    # move down major tick labels not to overwrite minor tick labels and do not show major ticks
    ax.xaxis.set_tick_params(which='major', pad=15, length=0)
    # customize the label shown on mouse over
    ax.format_xdata = ticker.FuncFormatter(showtime)
    ax.format_ydata = ticker.FuncFormatter(showmac)
    # show vertical bars matching minor ticks
    ax.grid(True, axis='x', which='minor')
    # add a legend
    if args.legend:
        # add a custom label handler to draw rectangle instead of default line style
        ax.legend(lines, macs, loc='lower left', ncol=len(macs)//30+1,
            handler_map={matplotlib.lines.Line2D: MyLine2DHandler()}, prop={'family':'monospace', 'size':8})
    # avoid too much space around our data by defining set
    space = 5*60 # 5 minutes
    ax.set_xlim(args.start_time-space, args.end_time+space)
    ax.set_ylim(-1, len(macs))
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
    parser.add_argument('-i', '--image', default=None, const='plot.png', nargs='?', help='output an image')
    parser.add_argument('-l', '--legend', action='store_true', default=False, help='add a legend')
    parser.add_argument('--label', action='store_true', default=False, help='add a mac label for each plot')
    parser.add_argument('-g', '--merged', action='append', help='OUI mac to merge')
    parser.add_argument('-k', '--knownmac', action='append', help='known mac to highlight in red')
    parser.add_argument('-M', '--min', type=int, default=3, help='minimum number of packets for device to be plotted')
    parser.add_argument('-m', '--mac', action='append', help='only display that mac')
    parser.add_argument('-p', '--privacy', action='store_true', default=False, help='merge LAA MAC address')
    parser.add_argument('-r', '--rssi', type=int, default=-99, help='minimal value for RSSI')
    parser.add_argument('-s', '--start', help='start timestamp')
    parser.add_argument('--time-span', default='1d', help='time span (coud be #d or ##h or ###m)')
    parser.add_argument('-t', '--title', nargs='?', const='', default=None, help='add a title to the top of image (if none specified, use a timestamp)')
    parser.add_argument('-v', '--verbose', action='store_true', default=False, help='be verbose')
    # RESERVED: args.span, args.start_time, args.end_time
    args = parser.parse_args()

    # parse time_span
    args.span = args.time_span[-1:]
    try:
        sp = int(args.time_span[:-1])
    except ValueError:
        print('Error: --time-span argument should be of the form [digit]...[d|h|m]')
        sys.exit(-1)
    if args.span == 'd':
        args.time_span = sp*NUMOFSECSINADAY
    elif args.span == 'h':
        args.time_span = sp*60*60
    elif args.span == 'm':
        args.time_span = sp*60
    else:
        print('Error: --times-span postfix could only be d or h or m')
        sys.exit(-1)

    if args.knownmac is None:
        args.knownmac = config.KNOWNMAC

    if args.merged is None:
        args.merged = config.MERGED
    args.merged = (m[:8] for m in args.merged)

    if not args.db or not os.path.exists(args.db):
        print(f'Error: file not found {args.db}', file=sys.stderr)
        sys.exit(-1)

    if args.start:
        try:
            start_time = time.mktime(time.strptime(args.start, '%Y-%m-%dT%H:%M'))
        except  ValueError:
            try:
                date = time.strptime(args.start, '%Y-%m-%d')
                date = time.strptime('%sT12:00' % args.start, '%Y-%m-%dT%H:%M')
                start_time = time.mktime(date)
            except ValueError:
                print(f"Error: can't parse date timestamp, excepted format YYYY-mm-dd[THH:MM]", file=sys.stderr)
                sys.exit(-1)
        end_time = start_time + args.time_span
    else:
        end_time = time.time()
        start_time = end_time - args.time_span
    args.start_time = start_time
    args.end_time = end_time

    fig = None
    if args.verbose:
        print(':: Gathering data')
    macs, times = get_data(args)
    if len(times) == 0 or len(macs) == 0:
        print(f'Error: nothing to plot', file=sys.stderr)
        sys.exit(-1)

    if args.verbose:
        print(':: Plotting data')
    plot_data(macs, times, args)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt as k:
        pass
