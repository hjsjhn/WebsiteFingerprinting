import os
import subprocess
import re
import csv
import sys
import time
import multiprocessing
import random

# Configuration
# Configuration
DATA_DIR = "data/walkiebatch_sample_100"
RESULTS_FILE = "comprehensive_results.csv"
LOG_DIR = "evaluation_logs"

# Dimensions
DEFENSES = [
    {'name': 'front_default', 'cmd': 'defenses/front/main.py', 'args': ['--config', 'default', '-format', '.cell']},
    {'name': 'front_t1', 'cmd': 'defenses/front/main.py', 'args': ['--config', 't1', '-format', '.cell']},
    {'name': 'wtfpad_default', 'cmd': 'defenses/wtfpad/main.py', 'args': ['-c', 'default']},
    {'name': 'tamaraw_default', 'cmd': 'defenses/tamaraw/tamaraw.py', 'args': ['--padl', '50']},
    {'name': 'tamaraw_high', 'cmd': 'defenses/tamaraw/tamaraw.py', 'args': ['--padl', '100']},
    {'name': 'glue_default', 'cmd': 'defenses/glue/main-base-rate.py', 'args': ['-mode', 'fix', '-n', '100', '-m', '1', '-b', '10', '-noise', 'False']}
]

STRATEGIES = ['A', 'B', 'C', 'D', 'O10', 'O30', 'O50']
MAX_INFLIGHT_VALUES = [5, 20]
LOSS_RATES = [0.02, 0.05, 0.10, 0.20]

# Regex for parsing stats
STATS_PATTERN = re.compile(
    r"\[TransportSimulator\] Stats: Total Real=(\d+), FEC=(\d+), Dummy=(\d+), Lost=(\d+), Recovered=(\d+), Retransmitted=(\d+), FCT=([\d\.]+), AvgLatency=([\d\.]+)"
)

def run_simulation(params):
    defense, strategy, inflight, loss_rate, trace_file, seed = params
    
    log_file = os.path.join(LOG_DIR, f"{defense['name']}_{strategy}_inf{inflight}_loss{loss_rate}_{os.path.basename(trace_file)}.log")
    
    fec_strategy = strategy
    external_fec_rate = 0.0
    
    if strategy.startswith('O'):
        fec_strategy = 'A'
        try:
            rate_percent = int(strategy[1:])
            external_fec_rate = rate_percent / 100.0
        except ValueError:
            print(f"Invalid strategy format: {strategy}")
            return None

    cmd = [
        "python3", defense['cmd'],
        trace_file, # Always pass the full path (DATA_DIR)
        "--fec-strategy", fec_strategy,
        "--external-fec-rate", str(external_fec_rate),
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
    # if 'glue' not in defense['name']:
    #      cmd[2] = DATA_DIR # Point to data dir instead of single file
    
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
        
        # Parse output from stdout (TransportSimulator prints to stdout)
        content = result.stdout
        matches = STATS_PATTERN.findall(content)
        
        # Also check stderr just in case
        if not matches:
             matches = STATS_PATTERN.findall(result.stderr)
             
        # If still no matches, check log file for "Traces are dumped to" and read debug logs
        if not matches and os.path.exists(log_file):
            with open(log_file, 'r') as f:
                log_content = f.read()
                
            # Try to find output directory
            out_dir_match = re.search(r"Traces are dumped to (.+)", log_content)
            if out_dir_match:
                out_dir = out_dir_match.group(1).strip()
                if os.path.exists(out_dir):
                    print(f"  -> Found output dir: {out_dir}")
                    # Read all .debug.log files
                    import glob
                    debug_logs = glob.glob(os.path.join(out_dir, "*.debug.log"))
                    for dlog in debug_logs:
                        with open(dlog, 'r') as df:
                            dcontent = df.read()
                            dmatches = STATS_PATTERN.findall(dcontent)
                            matches.extend(dmatches)
            
            # Also check the main log file itself for stats (some defenses might log there)
            matches.extend(STATS_PATTERN.findall(log_content))

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
            # Debug: print stdout/stderr snippet
            print(f"  -> No stats found. Stdout snippet: {result.stdout[:200]}...")
            print(f"  -> Stderr snippet: {result.stderr[:200]}...")
            if os.path.exists(log_file):
                 print(f"  -> Log file exists: {log_file}")
            return None
            
        # Cleanup debug logs to save space
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                log_content = f.read()
            out_dir_match = re.search(r"Traces are dumped to (.+)", log_content)
            if out_dir_match:
                out_dir = out_dir_match.group(1).strip()
                if os.path.exists(out_dir):
                    # print(f"  -> Cleaning up debug logs in {out_dir}")
                    import glob
                    debug_logs = glob.glob(os.path.join(out_dir, "*.debug.log"))
                    for dlog in debug_logs:
                        try:
                            os.remove(dlog)
                        except OSError:
                            pass
                    # Optional: remove the directory if empty or if we want to save even more space
                    # But we might want to keep the traces for manual inspection if needed.
                    # Given the user's request "accumulate too many logs", deleting debug logs is sufficient.

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

def prepare_sample_data(source_dir, target_dir, sample_size=100):
    """
    Ensures that the target_dir exists and contains sample_size files from source_dir.
    """
    if os.path.exists(target_dir):
        # Check if it has enough files
        files = [f for f in os.listdir(target_dir) if f.endswith('.cell')]
        if len(files) >= sample_size:
            print(f"Sample directory {target_dir} already exists with {len(files)} files.")
            return

        print(f"Sample directory {target_dir} exists but has fewer than {sample_size} files. Re-sampling...")
        import shutil
        shutil.rmtree(target_dir)
    
    if not os.path.exists(source_dir):
        print(f"Error: Source directory {source_dir} does not exist. Cannot create sample.")
        sys.exit(1)

    print(f"Creating sample directory {target_dir} with {sample_size} files from {source_dir}...")
    os.makedirs(target_dir)
    
    all_files = [f for f in os.listdir(source_dir) if f.endswith('.cell')]
    if len(all_files) < sample_size:
        print(f"Warning: Source has only {len(all_files)} files, using all of them.")
        sample_files = all_files
    else:
        sample_files = random.sample(all_files, sample_size)
    
    import shutil
    for f in sample_files:
        shutil.copy(os.path.join(source_dir, f), os.path.join(target_dir, f))
    print("Sampling complete.")

def load_existing_results(filepath):
    existing_data = {}
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Create a unique key for each task
                    # Key: (Defense, Strategy, MaxInflight, LossRate)
                    try:
                        key = (
                            row['Defense'],
                            row['Strategy'],
                            int(row['MaxInflight']),
                            float(row['LossRate'])
                        )
                        existing_data[key] = row
                    except (ValueError, KeyError):
                        continue # Skip malformed rows
            print(f"Loaded {len(existing_data)} existing results from {filepath}")
        except Exception as e:
            print(f"Warning: Could not read existing results: {e}")
    return existing_data

def main():
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
        
    # Ensure sample data exists
    SOURCE_DATA_DIR = "data/walkiebatch"
    prepare_sample_data(SOURCE_DATA_DIR, DATA_DIR, 100)

    # Generate all combinations
    tasks = []
    seed = 12345 # Fixed seed for reproducibility across runs
    
    # We run on the whole directory, so trace_file argument is just a placeholder or the dir itself
    # But wait, if we run on the whole directory, we only need ONE task per configuration.
    
    print("Generating tasks for 6 defenses, 4 strategies, 2 inflight values, 4 loss rates...")
    
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
    
    # Load existing results to skip completed tasks
    existing_results = load_existing_results(RESULTS_FILE)
    
    with open(RESULTS_FILE, 'w', newline='') as csvfile:
        fieldnames = ['Defense', 'Strategy', 'MaxInflight', 'LossRate', 'AvgRecovered', 'AvgRetransmitted', 'AvgFCT', 'AvgLatency', 'TotalFEC', 'TotalDummy', 'Count']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for i, task in enumerate(tasks):
            defense_name = task[0]['name']
            strategy = task[1]
            inflight = task[2]
            loss_rate = task[3]
            
            print(f"Processing {i+1}/{total}: {defense_name} | {strategy} | Inf={inflight} | Loss={loss_rate}")
            
            # Check if result already exists
            key = (defense_name, strategy, inflight, loss_rate)
            if key in existing_results:
                print("  -> Skipping... found existing results")
                writer.writerow(existing_results[key])
                csvfile.flush()
                results.append(existing_results[key])
                continue

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
