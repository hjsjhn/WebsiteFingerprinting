import argparse
import configparser
import logging
import sys
import os
import multiprocessing
import json

from adaptive import AdaptiveSimulator
from pparser import parse

# Add utils to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'utils'))
from transport_simulator import TransportSimulator

logger = logging.getLogger('wtfpad')

def parse_arguments():
    conf_parser = configparser.RawConfigParser()
    conf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'constants.conf')
    conf_parser.read(conf_path)

    parser = argparse.ArgumentParser(description='WTF-PAD Simulator')
    parser.add_argument('traces_path', metavar='<traces path>',
                        help='Path to the directory with the traffic traces to be simulated.')
    parser.add_argument('-c', '--config', dest="section", metavar='<config name>',
                        help="Adaptive padding configuration.",
                        choices=conf_parser.sections(), default="default")
    parser.add_argument('--log', type=str, dest="log", metavar='<log path>',
                        default='stdout', help='path to the log file.')
    
    parser.add_argument('--fec-strategy',
                        type=str,
                        dest="fec_strategy",
                        metavar='<strategy>',
                        default='A',
                        choices=['A', 'B', 'C', 'D'],
                        help='FEC Strategy: A (Baseline), B (Bucket), C (LT-like), D (Sliding Window)')

    parser.add_argument('--loss-rate',
                        type=float,
                        dest="loss_rate",
                        metavar='<loss_rate>',
                        default=0.0,
                        help='Packet loss rate (0.0 - 1.0)')

    parser.add_argument('--rtt',
                        type=float,
                        dest="rtt",
                        metavar='<rtt>',
                        default=0.1,
                        help='Round Trip Time in seconds')

    parser.add_argument('--max-inflight',
                        type=int,
                        dest="max_inflight",
                        metavar='<max_inflight>',
                        default=20,
                        help='Max inflight packets')

    parser.add_argument('--seed',
                        type=int,
                        dest="seed",
                        metavar='<seed>',
                        default=None,
                        help='Random seed')

    parser.add_argument('--external-fec-rate',
                        type=float,
                        dest="external_fec_rate",
                        metavar='<rate>',
                        default=0.0,
                        help='External FEC rate (0.0 - 1.0)')

    args = parser.parse_args()
    # config = dict(conf_parser._sections[args.section])
    config = dict(conf_parser[args.section])
    
    # Override config with args
    config['fec_strategy'] = args.fec_strategy
    config['loss_rate'] = args.loss_rate
    config['rtt'] = args.rtt
    config['max_inflight'] = args.max_inflight
    config['seed'] = args.seed
    config['external_fec_rate'] = args.external_fec_rate
    
    return args, config

def config_logger(args):
    log_file = sys.stdout
    if args.log != 'stdout':
        log_file = open(args.log, 'w')
    ch = logging.StreamHandler(log_file)
    ch.setFormatter(logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s'))
    logger.addHandler(ch)
    logger.setLevel(logging.INFO)

def process_trace(file_path, config, output_dir):
    try:
        fname = os.path.basename(file_path)
        # logger.info(f"Processing {fname}")
        
        # Parse trace
        trace = parse(file_path)
        
        # Simulate
        simulator = AdaptiveSimulator(config)
        noisy_trace = simulator.simulate(trace)
        
        # Apply Transport Simulation (Loss & Retransmission)
        loss_rate = float(config.get('loss_rate', 0.0))
        rtt = float(config.get('rtt', 0.1))
        max_inflight = int(config.get('max_inflight', 20))
        seed = config.get('seed')
        if seed is not None:
             seed = int(seed)
        
        # Convert Packet objects to list format for TransportSimulator
        # [time, length, metadata]
        processed_trace = []
        for p in noisy_trace:
            processed_trace.append([p.timestamp, p.length, p.metadata])
            
        # Debug log path
        debug_log_path = os.path.join(output_dir, fname + '.debug.log')
        external_fec_rate = float(config.get('external_fec_rate', 0.0))
        tsim = TransportSimulator(loss_rate, rtt, max_inflight=max_inflight, seed=seed, debug_log_path=debug_log_path, external_fec_rate=external_fec_rate)
        final_trace = tsim.simulate(processed_trace)
        
        # Dump
        output_path = os.path.join(output_dir, fname)
        with open(output_path, 'w') as f:
            for pkt in final_trace:
                ts = pkt[0]
                length = int(pkt[1])
                meta = pkt[2] if len(pkt) > 2 else {}
                
                line = f"{ts:.4f}\t{length}"
                if meta:
                    line += f"\t{json.dumps(meta)}"
                f.write(line + '\n')
                
    except Exception as e:
        logger.error(f"Error processing {file_path}: {e}")
        import traceback
        traceback.print_exc()

def main():
    args, config = parse_arguments()
    config_logger(args)
    
    logger.info(f"Arguments: {args}")
    logger.info(f"Configuration: {config}")

    # Output directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.join(base_dir, 'results')
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)
        
    timestamp = os.popen('date +%m%d_%H%M%S').read().strip()
    output_dir = os.path.join(results_dir, f"wtfpad_{timestamp}")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    logger.info(f"Output directory: {output_dir}")

    # Get list of files
    if os.path.isdir(args.traces_path):
        files = [os.path.join(args.traces_path, f) for f in os.listdir(args.traces_path) if f.endswith('.cell')]
    else:
        files = [args.traces_path]
        
    # Run simulation
    pool = multiprocessing.Pool(processes=multiprocessing.cpu_count())
    
    tasks = []
    for f in files:
        tasks.append((f, config, output_dir))
        
    pool.starmap(process_trace, tasks)
    pool.close()
    pool.join()

if __name__ == '__main__':
    main()
