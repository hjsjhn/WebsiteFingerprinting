import argparse
import configparser
import logging
import sys
import os
from os import mkdir
from os.path import join, isdir
from time import strftime
import multiprocessing as mp

import constants as ct
from adaptive import AdaptiveSimulator
from pparser import parse, dump
# from overheads import compute_overheads

logger = logging.getLogger('wtfpad')


def init_directories():
    # Create a results dir if it doesn't exist yet
    if not isdir(ct.RESULTS_DIR):
        mkdir(ct.RESULTS_DIR)

    # Define output directory
    timestamp = strftime('%m%d_%H%M')
    output_dir = join(ct.RESULTS_DIR, 'wtfpad_'+timestamp)
    #logger.info("Creating output directory: %s" % output_dir)

    # make the output directory
    mkdir(output_dir)
    return output_dir


def config_logger(args):
    # Set file
    log_file = sys.stdout
    if args.log != 'stdout':
        log_file = open(args.log, 'w')
    ch = logging.StreamHandler(log_file)

    # Set logging format
    ch.setFormatter(logging.Formatter(ct.LOG_FORMAT))
    logger.addHandler(ch)

    # Set level format
    logger.setLevel(logging.INFO)


def parse_arguments():
    # Read configuration file
    conf_parser = configparser.RawConfigParser()
    conf_parser.read(ct.CONFIG_FILE)

    parser = argparse.ArgumentParser(description='It simulates adaptive padding on a set of web traffic traces.')

    parser.add_argument('traces_path',
                        metavar='<traces path>',
                        help='Path to the directory with the traffic traces to be simulated.')

    parser.add_argument('-c', '--config',
                        dest="section",
                        metavar='<config name>',
                        help="Adaptive padding configuration.",
                        choices= conf_parser.sections(),
                        default="default")

    parser.add_argument('--log',
                        type=str,
                        dest="log",
                        metavar='<log path>',
                        default='stdout',
                        help='path to the log file. It will print to stdout by default.')
                        
    parser.add_argument('--fec-strategy',
                        type=str,
                        dest="fec_strategy",
                        metavar='<strategy>',
                        default='A',
                        choices=['A', 'B', 'C', 'D'],
                        help='FEC Strategy: A (Baseline), B (Bucket), C (LT-like), D (Sliding Window)')

    args = parser.parse_args()
    config = dict(conf_parser._sections[args.section])
    
    # Add FEC strategy to config
    config['fec_strategy'] = args.fec_strategy
    
    config_logger(args)

    return args, config


def process_trace(trace_path, output_dir, config):
    # logger.info("Processing trace: %s", trace_path)
    try:
        # Parse trace
        trace = parse(trace_path)

        # Simulate adaptive padding
        simulator = AdaptiveSimulator(config)
        trace = simulator.simulate(trace)

        # Dump trace
        output_name = os.path.basename(trace_path)
        output_path = join(output_dir, output_name)
        dump(trace, output_path)

        # Compute overheads
        # bw_ov, lat_ov = compute_overheads(trace_path, output_path)
        # logger.info("Bandwidth overhead: %s", bw_ov)
        # logger.info("Latency overhead: %s", lat_ov)

    except Exception as e:
        logger.exception(e)


def main():
    args, config = parse_arguments()
    logger.info("Arguments: %s" % args)
    logger.info("Configuration: %s" % config)

    output_dir = init_directories()

    # Get list of traces
    traces = [join(args.traces_path, f) for f in os.listdir(args.traces_path) if f.endswith('.cell')]
    
    # Run simulation
    pool = mp.Pool()
    for trace_path in traces:
        pool.apply_async(process_trace, args=(trace_path, output_dir, config))
    pool.close()
    pool.join()


if __name__ == '__main__':
    main()
