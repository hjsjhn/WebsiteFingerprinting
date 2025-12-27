#Anoa consists of two components:
#1. Send packets at some packet rate until data is done.
#2. Pad to cover total transmission size.
#The main logic decides how to send the next packet. 
#Resultant anonymity is measured in ambiguity sizes.
#Resultant overhead is in size and time.
#Maximizing anonymity while minimizing overhead is what we want. 
import math
import random
import constants as ct
from time import strftime
import argparse
import logging
import numpy as np
import overheads
import json

import sys
import os

# Add utils to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'utils'))
from fec_injector import FECInjector
from transport_simulator import TransportSimulator


logger = logging.getLogger('tamaraw')

'''params'''
DATASIZE = 1
DUMMYCODE = 1
# PadL = 50 # Moved to args

MON_SITE_NUM = 1
MON_INST_NUM = 1
UNMON_SITE_NUM = 1


#MON_SITE_NUM = 1
#MON_INST_NUM = 2
#UNMON_SITE_NUM = 0


tardist = [[], []]
defpackets = []
##    parameters = [100] #padL
##    AnoaPad(list2, lengths, times, parameters)

# for x in sys.argv[2:]:
#    parameters.append(float(x))
#    print(parameters)

def fsign(num):
    if num > 0:
        return 0
    else:
        return 1

def rsign(num):
    if num == 0:
        return 1
    else:
        return abs(num)/num

def AnoaTime(parameters):
    direction = parameters[0] #0 out, 1 in
    method = parameters[1]
    if (method == 0):
        if direction == 0:
            return 0.04
        if direction == 1:
            return 0.012  




        

def AnoaPad(list1, list2, padL, method, injector_snd, injector_rcv):
    lengths = [0, 0]
    times = [0, 0]
    for x in list1:
        if (x[1] > 0):
            lengths[0] += 1
            times[0] = x[0]
        else:
            lengths[1] += 1
            times[1] = x[0]
        list2.append(x)

    paddings = []

    for j in range(0, 2):
        curtime = times[j]
        topad = -int(math.log(random.uniform(0.00001, 1), 2) - 1) #1/2 1, 1/4 2, 1/8 3, ... #check this
        if (method == 0):
            if padL == 0:
                topad = 0
            else:
                topad = (lengths[j]//padL + topad) * padL
            
        logger.info("Need to pad to %d packets."%topad)
        while (lengths[j] < topad):
            curtime += AnoaTime([j, 0])
            
            # Generate FEC metadata for dummy packet
            metadata = {}
            if j == 0: # OUT (Client -> Server)
                metadata = injector_snd.generate_dummy_content()
                paddings.append([curtime, DUMMYCODE * DATASIZE, metadata])
            else: # IN (Server -> Client)
                metadata = injector_rcv.generate_dummy_content()
                paddings.append([curtime, -DUMMYCODE* DATASIZE, metadata])
            lengths[j] += 1
    paddings = sorted(paddings, key = lambda x: x[0])
    list2.extend(paddings)

def Anoa(list1, list2, parameters, injector_snd, injector_rcv): #inputpacket, outputpacket, parameters
    #Does NOT do padding, because ambiguity set analysis. 
    #list1 WILL be modified! if necessary rewrite to tempify list1.
    starttime = list1[0][0]
    times = [starttime, starttime] #lastpostime, lastnegtime
    curtime = starttime
    lengths = [0, 0]
    datasize = DATASIZE
    method = 0
    if (method == 0):
        parameters[0] = "Constant packet rate: " + str(AnoaTime([0, 0])) + ", " + str(AnoaTime([1, 0])) + ". "
        parameters[0] += "Data size: " + str(datasize) + ". "
    if (method == 1):
        parameters[0] = "Time-split varying bandwidth, split by 0.1 seconds. "
        parameters[0] += "Tolerance: 2x."
    listind = 1 #marks the next packet to send
    
    real_snd_id = 0
    real_rcv_id = 0
    
    while (listind < len(list1)):
        #decide which packet to send
        if times[0] + AnoaTime([0, method, times[0]-starttime]) < times[1] + AnoaTime([1, method, times[1]-starttime]):
            cursign = 0
        else:
            cursign = 1
        times[cursign] += AnoaTime([cursign, method, times[cursign]-starttime])
        curtime = times[cursign]
        
        tosend = datasize
        while (list1[listind][0] <= curtime and fsign(list1[listind][1]) == cursign and tosend > 0):
            if (tosend >= abs(list1[listind][1])):
                tosend -= abs(list1[listind][1])
                listind += 1
            else:
                list1[listind][1] = (abs(list1[listind][1]) - tosend) * rsign(list1[listind][1])
                tosend = 0
            if (listind >= len(list1)):
                break
        
        # Process Real Packet for FEC
        if cursign == 0: # OUT
            real_snd_id += 1
            injector_snd.process_real_packet(real_snd_id)
            list2.append([curtime, datasize])
        else: # IN
            real_rcv_id += 1
            injector_rcv.process_real_packet(real_rcv_id)
            list2.append([curtime, -datasize])
        lengths[cursign] += 1
        



def init_directories():
    # Create a results dir if it doesn't exist yet
    if not os.path.isdir(ct.RESULTS_DIR):
        os.mkdir(ct.RESULTS_DIR)

    # Define output directory
    timestamp = strftime('%m%d_%H%M%S')
    output_dir = os.path.join(ct.RESULTS_DIR, 'tamaraw_'+timestamp)
    #logger.info("Creating output directory: %s" % output_dir)

    # make the output directory
    os.makedirs(output_dir, exist_ok=True)

    return output_dir


def parse_arguments():
    # Read configuration file
    # conf_parser = configparser.RawConfigParser()
    # conf_parser.read(ct.CONFIG_FILE)

    parser = argparse.ArgumentParser(description='It simulates tamaraw on a set of web traffic traces.')

    parser.add_argument('traces_path',
                        metavar='<traces path>',
                        help='Path to the directory with the traffic traces to be simulated.')
    

    # parser.add_argument('-c', '--config',
    #                     dest="section",
    #                     metavar='<config name>',
    #                     help="Adaptive padding configuration.",
    #                     choices= conf_parser.sections(),
    #                     default="default")



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

    parser.add_argument('--padl',
                        type=int,
                        dest="padl",
                        metavar='<padl>',
                        default=50,
                        help='Padding Length (Controls overhead)')

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
    #config = dict(conf_parser._sections[args.section])
    config_logger(args)

    return args

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

if __name__ == '__main__':
    args = parse_arguments()
    logger.info("Arguments: %s" % (args))
    foldout = init_directories()
    
    packets = []
    desc = ""
    anoad = []
    anoadpad = []
    latencies = []
    sizes = []
    bandwidths = []

    tot_new_size = 0.0
    tot_new_latency = 0.0
    tot_old_size = 0.0
    tot_old_latency = 0.0


    # Iterate over all files in the directory
    import glob
    files = glob.glob(os.path.join(args.traces_path, '*.cell'))
    logger.info(f"Found {len(files)} files to process.")

    for file_path in files:
        fname = os.path.basename(file_path)
        logger.info('Simulating %s...'%fname)
        packets = []
        with open(file_path, "r") as f:
            lines = f.readlines()
            starttime = float(lines[0].split("\t")[0])
            for x in lines:
                x = x.split("\t")
                packets.append([float(x[0]) - starttime, int(x[1])])
        
        # Initialize injectors
        injector_snd = FECInjector(args.fec_strategy)
        injector_rcv = FECInjector(args.fec_strategy)
        
        list2 = [packets[0]]
        parameters = [""]
        
        Anoa(packets, list2, parameters, injector_snd, injector_rcv)
        list2 = sorted(list2, key = lambda list2: list2[0])
        anoad.append(list2)

        list3 = []
        
        # Run Tamaraw
        AnoaPad(list2, list3, args.padl, 0, injector_snd, injector_rcv)

        # Simulate Transport (Loss & Retransmission)
        debug_log_path = os.path.join(foldout, fname + '.debug.log')
        tsim = TransportSimulator(args.loss_rate, args.rtt, max_inflight=args.max_inflight, seed=args.seed, debug_log_path=debug_log_path, external_fec_rate=args.external_fec_rate)
        final_trace = tsim.simulate(list3)

        fout = open(os.path.join(foldout,fname), "w")
        for x in final_trace:
            line = "{:.4f}\t{:d}".format(x[0],x[1])
            if len(x) > 2 and x[2]: # If metadata exists
                    line += "\t" + json.dumps(x[2])
            fout.write(line + "\n")
        fout.close()

        #latency:
        old = packets[-1][0] - packets[0][0]
        #new definition of time latency:
        new = list2[-1][0] -list2[0][0]
        #new = list3[-1][0] -list3[0][0]

        #in case there is precision loss
        if new < old:
            new = old

        latency = 1.0*new/old
        latencies.append(latency)
        tot_new_latency += new
        tot_old_latency += old

        #sizes:
        old = sum([abs(p[1]) for p in packets])
        mid = sum([abs(p[1]) for p in list2])
        new = sum([abs(p[1]) for p in list3])
        # logger.info("old size:%d,mid size:%d, new size:%d"%(old,mid, new))
        size = 1.0*new/old 
        sizes.append(size)
        tot_new_size += new
        tot_old_size += old
        #bandwidth
        # bandwidth = size/latency * 1.0
        # bandwidths.append(bandwidth)
        # logger.info("Latency overhead: %.4f,size overhead:%.4f"%(latency,size))

    foldout = foldout.split('/')[-1]
    logger.info('Average latency overhead: %.4f'% (1.0*tot_new_latency/tot_old_latency-1))
    logger.info('Average size overhead:%.4f'%(1.0*tot_new_size/tot_old_size -1))
    logger.info('%s'%foldout)
    
