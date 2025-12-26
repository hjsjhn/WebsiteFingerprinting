import os
import subprocess
import re
import csv
import sys
import time
import multiprocessing
import random

# Configuration
DATA_DIR = "data/walkiebatch"
RESULTS_FILE = "comprehensive_results.csv"
LOG_DIR = "evaluation_logs"

# Dimensions
DEFENSES = [
    {'name': 'front_default', 'cmd': 'defenses/front/main.py', 'args': ['--config', 'default']},
    {'name': 'front_t1', 'cmd': 'defenses/front/main.py', 'args': ['--config', 't1']},
    {'name': 'wtfpad_default', 'cmd': 'defenses/wtfpad/main.py', 'args': ['-c', 'default']},
    {'name': 'tamaraw_default', 'cmd': 'defenses/tamaraw/tamaraw.py', 'args': ['--padl', '50']},
    {'name': 'tamaraw_high', 'cmd': 'defenses/tamaraw/tamaraw.py', 'args': ['--padl', '100']},
    {'name': 'glue_default', 'cmd': 'defenses/glue/main-base-rate.py', 'args': ['-mode', 'fix', '-n', '1', '-m', '1', '-b', '10', '-noise', 'False']}
]

STRATEGIES = ['A', 'B', 'C', 'D']
MAX_INFLIGHT_VALUES = [5, 20]
LOSS_RATES = [0.02, 0.05, 0.10, 0.20]

# Regex for parsing stats
STATS_PATTERN = re.compile(
    r"\[TransportSimulator\] Stats: Total Real=(\d+), FEC=(\d+), Dummy=(\d+), Lost=(\d+), Recovered=(\d+), Retransmitted=(\d+), FCT=([\d\.]+), AvgLatency=([\d\.]+)"
)

def run_simulation(params):
    defense, strategy, inflight, loss_rate, trace_file, seed = params
    
    log_file = os.path.join(LOG_DIR, f"{defense['name']}_{strategy}_inf{inflight}_loss{loss_rate}_{os.path.basename(trace_file)}.log")
    
    cmd = [
        "python3", defense['cmd'],
        trace_file if 'glue' not in defense['name'] else os.path.dirname(trace_file), # Glue takes dir, others take file/dir
        "--fec-strategy", strategy,
        "--max-inflight", str(inflight),
        "--loss-rate", str(loss_rate),
        "--seed", str(seed),
        "--log", log_file
    ] + defense['args']
    
    # Special handling for Glue which iterates directory internally or takes specific args
    # For simplicity, we assume Glue runs on the dir passed.
    # But wait, Glue script takes 'traces_path' and runs on all files in it or random selection.
    # To make it comparable, we might need to restrict Glue to specific files or just let it run its batch.
    # Given the user said "All Cell Traffic", running on the directory is fine.
    # However, other scripts like FRONT/WTF-PAD/Tamaraw also take a directory and iterate.
    # So we should pass the directory to all of them, and they will process all files.
    
    # Adjust command for directory processing
    if 'glue' not in defense['name']:
         cmd[2] = DATA_DIR # Point to data dir instead of single file
    
    try:
        # Run command
        # We use a timeout to prevent hangs
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        # Parse output
        # Since they process multiple files, we'll get multiple stats lines.
        # We need to aggregate them.
        
        total_real = 0
        total_fec = 0
        total_dummy = 0
        total_lost = 0
        total_recovered = 0
        total_retransmitted = 0
        total_fct = 0.0
        total_latency = 0.0
        count = 0
        
        # Output might be in stdout or stderr depending on logging
        # But we redirected log to file. We should read the log file.
        
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                content = f.read()
                matches = STATS_PATTERN.findall(content)
                for match in matches:
                    total_real += int(match[0])
                    total_fec += int(match[1])
                    total_dummy += int(match[2])
                    total_lost += int(match[3])
                    total_recovered += int(match[4])
                    total_retransmitted += int(match[5])
                    total_fct += float(match[6])
                    total_latency += float(match[7])
                    count += 1
        
        if count == 0:
            return None
            
        return {
            'Defense': defense['name'],
            'Strategy': strategy,
            'MaxInflight': inflight,
            'LossRate': loss_rate,
            'AvgRecovered': total_recovered / count,
            'AvgRetransmitted': total_retransmitted / count,
            'AvgFCT': total_fct / count,
            'AvgLatency': total_latency / count,
            'TotalFEC': total_fec,
            'TotalDummy': total_dummy,
            'Count': count
        }

    except subprocess.TimeoutExpired:
        print(f"Timeout: {defense['name']} {strategy} {inflight} {loss_rate}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

def main():
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
        
    # Generate tasks
    tasks = []
    seed = 12345 # Fixed seed for reproducibility across runs
    
    # We run on the whole directory, so trace_file argument is just a placeholder or the dir itself
    # But wait, if we run on the whole directory, we only need ONE task per configuration.
    
    print(f"Generating tasks for {len(DEFENSES)} defenses, {len(STRATEGIES)} strategies, {len(MAX_INFLIGHT_VALUES)} inflight values, {len(LOSS_RATES)} loss rates...")
    
    for defense in DEFENSES:
        for strategy in STRATEGIES:
            for inflight in MAX_INFLIGHT_VALUES:
                for loss_rate in LOSS_RATES:
                    tasks.append((defense, strategy, inflight, loss_rate, DATA_DIR, seed))
    
    print(f"Total tasks: {len(tasks)}")
    
    # Run in parallel?
    # Be careful with parallelism as the scripts themselves might use multiprocessing (e.g. Glue, FRONT)
    # It's safer to run sequentially or with low parallelism if the scripts are single-threaded.
    # FRONT and Glue use multiprocessing. WTF-PAD and Tamaraw seem single-threaded or per-file.
    # To be safe and avoid OOM/CPU contention, let's run sequentially for now, or with very low pool size.
    # Given the user wants to run it, let's just run sequentially to be safe.
    
    results = []
    total = len(tasks)
    
    with open(RESULTS_FILE, 'w', newline='') as csvfile:
        fieldnames = ['Defense', 'Strategy', 'MaxInflight', 'LossRate', 'AvgRecovered', 'AvgRetransmitted', 'AvgFCT', 'AvgLatency', 'TotalFEC', 'TotalDummy', 'Count']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for i, task in enumerate(tasks):
            print(f"Processing {i+1}/{total}: {task[0]['name']} | {task[1]} | Inf={task[2]} | Loss={task[3]}")
            res = run_simulation(task)
            if res:
                writer.writerow(res)
                csvfile.flush() # Ensure data is written
                results.append(res)
            else:
                print("  -> Failed or No Data")

    print(f"Done. Results saved to {RESULTS_FILE}")

if __name__ == "__main__":
    main()
