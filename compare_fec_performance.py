import os
import subprocess
import sys
import shutil
import tempfile
import re
import statistics
import random

NUM_RUNS = 20
CONFIGS = ['default', 't1'] # default=Low Overhead, t1=High Overhead

def run_strategy(strategy, input_dir, base_dir, log_file, seed, config):
    cmd = [
        "python3", "defenses/front/main.py",
        input_dir,
        "-format", ".cell",
        "--fec-strategy", strategy,
        "--loss-rate", "0.05",
        "--rtt", "0.1",
        "--max-inflight", "5", # Fix congestion to High for this test
        "--config", config,
        "--seed", str(seed),
        "--log", log_file
    ]
    try:
        output = subprocess.check_output(cmd, cwd=base_dir, stderr=subprocess.STDOUT).decode()
        return parse_stats(output)
    except subprocess.CalledProcessError as e:
        print(f"Strategy {strategy} failed: {e.output.decode()}")
        return None

def parse_stats(output):
    stats = {
        'total_real': 0,
        'total_fec': 0,
        'total_dummy': 0,
        'lost_real': 0,
        'recovered_real': 0,
        'retransmitted_real': 0,
        'fct': 0.0,
        'avg_latency': 0.0
    }
    
    pattern = r"\[TransportSimulator\] Stats: Total Real=(\d+), FEC=(\d+), Dummy=(\d+), Lost=(\d+), Recovered=(\d+), Retransmitted=(\d+), FCT=([\d\.]+), AvgLatency=([\d\.]+)"
    matches = re.findall(pattern, output)
    
    for match in matches:
        stats['total_real'] += int(match[0])
        stats['total_fec'] += int(match[1])
        stats['total_dummy'] += int(match[2])
        stats['lost_real'] += int(match[3])
        stats['recovered_real'] += int(match[4])
        stats['retransmitted_real'] += int(match[5])
        stats['fct'] = float(match[6])
        stats['avg_latency'] = float(match[7])
        
    return stats

def run_comparison():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, 'data/walkiebatch')
    
    test_trace_path = os.path.join(data_dir, '0-0.cell')
    if not os.path.exists(test_trace_path):
        print(f"Error: Test trace not found at {test_trace_path}")
        return

    print(f"Running comparison over {NUM_RUNS} runs with Configs={CONFIGS} and Fixed Seeds...")
    
    strategies = ['A', 'B', 'C', 'D']
    # Structure: results[config][strategy] = [run1_stats, run2_stats, ...]
    all_results = {cfg: {s: [] for s in strategies} for cfg in CONFIGS}

    with tempfile.TemporaryDirectory() as temp_input_dir:
        shutil.copy(test_trace_path, temp_input_dir)
        
        for i in range(NUM_RUNS):
            print(f"Run {i+1}/{NUM_RUNS}...", end='\r', flush=True)
            # Generate a random seed for this run
            run_seed = random.randint(0, 1000000)
            
            for cfg in CONFIGS:
                for s in strategies:
                    res = run_strategy(s, temp_input_dir, base_dir, f"front_{s.lower()}_{cfg}.log", run_seed, cfg)
                    if res:
                        all_results[cfg][s].append(res)
        print("\nRuns completed.")

    # Process and Print Results for each Config
    metrics = ['total_real', 'total_fec', 'total_dummy', 'lost_real', 'recovered_real', 'retransmitted_real', 'fct', 'avg_latency']
    
    for cfg in CONFIGS:
        print("\n" + "="*130)
        print(f"RESULTS FOR CONFIG = {cfg}")
        print("="*130)
        print(f"{'Metric (Avg over ' + str(NUM_RUNS) + ' runs)':<30} | {'Strategy A':<15} | {'Strategy B':<15} | {'Strategy C':<15} | {'Strategy D':<15}")
        print("-" * 130)
        
        final_stats = {}
        for s in strategies:
            results_list = all_results[cfg][s]
            if not results_list:
                final_stats[s] = {k: 'N/A' for k in metrics}
                continue
                
            avg_res = {}
            for k in metrics:
                values = [r[k] for r in results_list]
                avg_res[k] = statistics.mean(values)
            final_stats[s] = avg_res
            
        display_metrics = [
            ('Total Real', 'total_real'),
            ('FEC Packets', 'total_fec'),
            ('Dummy Packets', 'total_dummy'),
            ('Lost Real', 'lost_real'),
            ('Recovered', 'recovered_real'),
            ('Retransmitted', 'retransmitted_real'),
            ('Flow Completion Time (s)', 'fct'),
            ('Avg Packet Latency (s)', 'avg_latency')
        ]
        
        for label, key in display_metrics:
            row_str = f"{label:<30}"
            for s in strategies:
                val = final_stats[s].get(key, 0)
                if isinstance(val, float): val_str = f"{val:.4f}"
                else: val_str = str(val)
                row_str += f" | {val_str:<15}"
            print(row_str)
        print("="*130)

if __name__ == "__main__":
    run_comparison()
