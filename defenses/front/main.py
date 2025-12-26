import numpy as np 
import argparse
import logging
import sys
import pandas as pd
import os
from os.path import join
from os import makedirs
import constants as ct
from time import strftime
# import matplotlib.pyplot as plt
import multiprocessing as mp
import configparser
import time
import datetime
from pprint import pprint
import json

# Add utils to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'utils'))
from fec_injector import FECInjector
from transport_simulator import TransportSimulator

logger = logging.getLogger('ranpad2')
def init_directories():
    # Create a results dir if it doesn't exist yet
    if not os.path.exists(ct.RESULTS_DIR):
        makedirs(ct.RESULTS_DIR)

    # Define output directory
    timestamp = strftime('%m%d_%H%M')
    output_dir = join(ct.RESULTS_DIR, 'ranpad2_'+timestamp)
    makedirs(output_dir, exist_ok=True)

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

    conf_parser = configparser.RawConfigParser()
    conf_parser.read(ct.CONFIG_FILE)


    parser = argparse.ArgumentParser(description='It simulates adaptive padding on a set of web traffic traces.')

    parser.add_argument('p',
                        metavar='<traces path>',
                        help='Path to the directory with the traffic traces to be simulated.')
    parser.add_argument('-format',
                        metavar='<suffix of a file>',
                        default = '',
                        help='suffix of a file.')
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
                        help='Max inflight packets (CWND) for congestion control simulation')

    parser.add_argument('--seed',
                        type=int,
                        dest="seed",
                        metavar='<seed>',
                        default=None,
                        help='Random seed for deterministic simulation')

    args = parser.parse_args()
    config = dict(conf_parser._sections[args.section])
    config_logger(args)
    return args,config

def load_trace(fdir):
    with open(fdir,'r') as f:
        tmp = f.readlines()
    t = pd.Series(tmp).str.slice(0,-1).str.split('\t',expand = True).astype('float')
    return np.array(t)

def dump(trace, fname, metadata_list=None):
    global output_dir
    with open(join(output_dir,fname), 'w') as fo:
        for i, packet in enumerate(trace):
            # Packet format in trace: [time, length, metadata] (if processed by TransportSimulator)
            # Or [time, length] + metadata_list[i] (if not)
            
            # If trace comes from TransportSimulator, it already has metadata in 3rd element
            ts = packet[0]
            length = int(packet[1])
            meta = None
            
            if len(packet) > 2:
                meta = packet[2]
            elif metadata_list and i < len(metadata_list):
                meta = metadata_list[i]
                
            line = "{:.4f}".format(ts) +'\t' + "{}".format(length)
            if meta:
                 line += '\t' + json.dumps(meta)
            fo.write(line + ct.NL)

# Add global variable
fec_strategy = 'A'
loss_rate = 0.0
rtt = 0.1
max_inflight = 20
seed = None

def init_worker(args_fec, c_min, s_min, c_dummy, s_dummy, start_time, max_w, min_w, out_dir, l_rate, r_time, m_inflight, s_seed):
    global fec_strategy
    global client_min_dummy_pkt_num
    global server_min_dummy_pkt_num
    global client_dummy_pkt_num
    global server_dummy_pkt_num
    global start_padding_time
    global max_wnd
    global min_wnd
    global output_dir
    global loss_rate
    global rtt
    global max_inflight
    global seed
    
    fec_strategy = args_fec
    client_min_dummy_pkt_num = c_min
    server_min_dummy_pkt_num = s_min
    client_dummy_pkt_num = c_dummy
    server_dummy_pkt_num = s_dummy
    start_padding_time = start_time
    max_wnd = max_w
    min_wnd = min_w
    output_dir = out_dir
    loss_rate = l_rate
    rtt = r_time
    max_inflight = m_inflight
    seed = s_seed

def simulate(fdir):
    global fec_strategy
    global loss_rate
    global rtt
    global max_inflight
    global seed
    global output_dir
    
    if not os.path.exists(fdir):
        return
    # logger.debug("Simulating trace {}".format(fdir))
    
    # Use provided seed or random
    if seed is not None:
        np.random.seed(seed)
    else:
        np.random.seed(datetime.datetime.now().microsecond)
        
    trace = load_trace(fdir)
    
    # Initialize FEC Injector
    injector_client = FECInjector(fec_strategy) # OUT
    injector_server = FECInjector(fec_strategy) # IN
    
    noisy_trace = RP(trace)
    
    # Post-process to apply FEC logic and generate metadata
    # We construct a list of [time, length, metadata] to pass to TransportSimulator
    processed_trace = []
    
    # Counters for packet IDs
    real_client_id = 0
    real_server_id = 0
    
    for packet in noisy_trace:
        ts = packet[0]
        length = int(packet[1])
        meta = {}
        
        is_dummy_client = (length == 888)
        is_dummy_server = (length == -888)
        
        if is_dummy_client:
            meta = injector_client.generate_dummy_content()
        elif is_dummy_server:
            meta = injector_server.generate_dummy_content()
        else:
            # Real packet
            if length > 0: # Client -> Server
                real_client_id += 1
                injector_client.process_real_packet(real_client_id)
            else: # Server -> Client
                real_server_id += 1
                injector_server.process_real_packet(real_server_id)
        
        processed_trace.append([ts, length, meta])

    # Generate Debug Log Path
    fname = fdir.split('/')[-1]
    debug_log_path = join(output_dir, fname + '.debug.log')

    # Simulate Transport (Loss & Retransmission)
    tsim = TransportSimulator(loss_rate, rtt, max_inflight=max_inflight, seed=seed, debug_log_path=debug_log_path)
    final_trace = tsim.simulate(processed_trace)

    dump(final_trace, fname)

def RP(trace):
    # format: [[time, pkt],[...]]
    # trace, cpkt_num, spkt_num, cwnd, swnd
    global client_dummy_pkt_num 
    global server_dummy_pkt_num 
    global min_wnd 
    global max_wnd 
    global start_padding_time
    global client_min_dummy_pkt_num
    global server_min_dummy_pkt_num
    
    client_wnd = np.random.uniform(min_wnd, max_wnd)
    server_wnd = np.random.uniform(min_wnd, max_wnd)
    if client_min_dummy_pkt_num != client_dummy_pkt_num:
        client_dummy_pkt = np.random.randint(client_min_dummy_pkt_num,client_dummy_pkt_num)
    else:
        client_dummy_pkt = client_dummy_pkt_num
    if server_min_dummy_pkt_num != server_dummy_pkt_num:
        server_dummy_pkt = np.random.randint(server_min_dummy_pkt_num,server_dummy_pkt_num)
    else:
        server_dummy_pkt = server_dummy_pkt_num
    logger.debug("client_wnd:",client_wnd)
    logger.debug("server_wnd:",server_wnd)
    logger.debug("client pkt:", client_dummy_pkt)
    logger.debug("server pkt:", server_dummy_pkt)


    first_incoming_pkt_time = trace[np.where(trace[:,1] <0)][0][0]
    last_pkt_time = trace[-1][0]    
    
    client_timetable = getTimestamps(client_wnd, client_dummy_pkt)
    client_timetable = client_timetable[np.where(start_padding_time+client_timetable[:,0] <= last_pkt_time)]

    server_timetable = getTimestamps(server_wnd, server_dummy_pkt)
    server_timetable[:,0] += first_incoming_pkt_time
    server_timetable = server_timetable[np.where(start_padding_time+server_timetable[:,0] <= last_pkt_time)]

    
    # print("client_timetable")
    # print(client_timetable[:10])
    client_pkts = np.concatenate((client_timetable, 888*np.ones((len(client_timetable),1))),axis = 1)
    server_pkts = np.concatenate((server_timetable, -888*np.ones((len(server_timetable),1))),axis = 1)


    noisy_trace = np.concatenate( (trace, client_pkts, server_pkts), axis = 0)
    noisy_trace = noisy_trace[ noisy_trace[:, 0].argsort(kind = 'mergesort')]
    return noisy_trace

def getTimestamps(wnd, num):
    # timestamps = sorted(np.random.exponential(wnd/2.0, num))   
    # print(wnd, num)
    # timestamps = sorted(abs(np.random.normal(0, wnd, num)))
    timestamps = sorted(np.random.rayleigh(wnd,num))
    # print(timestamps[:5])
    # timestamps = np.fromiter(map(lambda x: x if x <= wnd else wnd, timestamps),dtype = float)
    return np.reshape(timestamps, (len(timestamps),1))


def parallel(flist, init_args, n_jobs = 20):
    pool = mp.Pool(n_jobs, initializer=init_worker, initargs=init_args)
    pool.map(simulate, flist)


if __name__ == '__main__':
    # global client_dummy_pkt_num 
    # global server_dummy_pkt_num 
    # global client_min_dummy_pkt_num
    # global server_min_dummy_pkt_num
    # global max_wnd
    # global min_wnd 
    # global start_padding_time
    # global fec_strategy
    
    args, config = parse_arguments()
    logger.info(args)
    
    fec_strategy = args.fec_strategy
    loss_rate = args.loss_rate
    rtt = args.rtt
    max_inflight = args.max_inflight
    seed = args.seed

    client_min_dummy_pkt_num = int(config.get('client_min_dummy_pkt_num',100))
    server_min_dummy_pkt_num = int(config.get('server_min_dummy_pkt_num',100))
    client_dummy_pkt_num = int(config.get('client_dummy_pkt_num',300))
    server_dummy_pkt_num = int(config.get('server_dummy_pkt_num',300))
    start_padding_time = int(config.get('start_padding_time', 0))
    max_wnd = float(config.get('max_wnd',10))
    min_wnd = float(config.get('min_wnd',10))
    MON_SITE_NUM = int(config.get('mon_site_num', 10))
    MON_INST_NUM = int(config.get('mon_inst_num', 10))
    UNMON_SITE_NUM = int(config.get('unmon_site_num', 100))
    print("client_min_dummy_pkt_num:{}".format(client_min_dummy_pkt_num))
    print("server_min_dummy_pkt_num:{}".format(server_min_dummy_pkt_num))
    print("client_dummy_pkt_num: {}\nserver_dummy_pkt_num: {}".format(client_dummy_pkt_num,server_dummy_pkt_num))
    print("max_wnd: {}\nmin_wnd: {}".format(max_wnd,min_wnd))
    print("start_padding_time:", start_padding_time)
    flist  = []
    for i in range(MON_SITE_NUM):
        for j in range(MON_INST_NUM):
            flist.append(join(args.p, str(i)+'-'+str(j)+args.format))
    for i in range(UNMON_SITE_NUM):
        flist.append(join(args.p, str(i)+args.format))

    # Init run directories
    output_dir = init_directories()
    logger.info("Traces are dumped to {}".format(output_dir))
    start = time.time()
    # for i,f in enumerate(flist):
    #     logger.debug('Simulating {}'.format(f))
    #     if i %2000 == 0:
    #         print(r"Done for inst ",i,flush = True)
    #     simulate(f)

    init_args = (fec_strategy, client_min_dummy_pkt_num, server_min_dummy_pkt_num, 
                 client_dummy_pkt_num, server_dummy_pkt_num, start_padding_time, max_wnd, min_wnd, output_dir, loss_rate, rtt, max_inflight, seed)
    parallel(flist, init_args)
    logger.info("Time: {}".format(time.time()-start))
