import os
import subprocess
import sys
import shutil
import tempfile
import re
import statistics

NUM_RUNS = 20

def run_strategy(strategy, input_dir, base_dir, log_file):
    cmd = [
        "python3", "defenses/front/main.py",
        input_dir,
        "-format", ".cell",
        "--fec-strategy", strategy,
        "--loss-rate", "0.05",
        "--rtt", "0.1",
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
    
    # In case of multiple matches (multiprocessing), sum counts and average timings?
    # Actually, FRONT runs multiple processes for multiple files.
    # But here we input a directory with 1 file.
    # So we expect 1 match.
    
    for match in matches:
        stats['total_real'] += int(match[0])
        stats['total_fec'] += int(match[1])
        stats['total_dummy'] += int(match[2])
        stats['lost_real'] += int(match[3])
        stats['recovered_real'] += int(match[4])
        stats['retransmitted_real'] += int(match[5])
        # For timing, if there are multiple, we should probably take the max FCT? 
        # But for 1 file, it's fine.
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

    print(f"Running comparison over {NUM_RUNS} runs...")
    
    strategies = ['A', 'B', 'D']
    aggregated_results = {s: [] for s in strategies}

    with tempfile.TemporaryDirectory() as temp_input_dir:
        shutil.copy(test_trace_path, temp_input_dir)
        
        for i in range(NUM_RUNS):
            print(f"Run {i+1}/{NUM_RUNS}...", end='\r', flush=True)
            for s in strategies:
                res = run_strategy(s, temp_input_dir, base_dir, f"front_{s.lower()}.log")
                if res:
                    aggregated_results[s].append(res)
        print("\nRuns completed.")

    # Calculate Averages
    final_stats = {}
    metrics = ['total_real', 'total_fec', 'total_dummy', 'lost_real', 'recovered_real', 'retransmitted_real', 'fct', 'avg_latency']
    
    for s in strategies:
        results_list = aggregated_results[s]
        if not results_list:
            final_stats[s] = {k: 'N/A' for k in metrics}
            continue
            
        avg_res = {}
        for k in metrics:
            values = [r[k] for r in results_list]
            avg_res[k] = statistics.mean(values)
        final_stats[s] = avg_res

    # Print Table
    print("\n" + "="*110)
    print(f"{'Metric (Avg over ' + str(NUM_RUNS) + ' runs)':<30} | {'Strategy A (No FEC)':<20} | {'Strategy B (Bucket)':<20} | {'Strategy D (Window)':<20}")
    print("-" * 110)
    
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
        val_a = final_stats['A'].get(key, 0)
        val_b = final_stats['B'].get(key, 0)
        val_d = final_stats['D'].get(key, 0)
        
        # Format floats
        if isinstance(val_a, float): str_a = f"{val_a:.4f}"
        else: str_a = str(val_a)
        
        if isinstance(val_b, float): str_b = f"{val_b:.4f}"
        else: str_b = str(val_b)
        
        if isinstance(val_d, float): str_d = f"{val_d:.4f}"
        else: str_d = str(val_d)
        
        print(f"{label:<30} | {str_a:<20} | {str_b:<20} | {str_d:<20}")
    print("="*110)

if __name__ == "__main__":
    run_comparison()
