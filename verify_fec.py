import os
import subprocess
import sys
import shutil
import tempfile

def run_test():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, 'data/walkiebatch')
    defenses_dir = os.path.join(base_dir, 'defenses')
    results_dir = os.path.join(defenses_dir, 'results')
    
    # Create a dummy trace file for testing if not exists
    test_trace_path = os.path.join(data_dir, '0-0.cell')
    if not os.path.exists(test_trace_path):
        print(f"Error: Test trace not found at {test_trace_path}")
        return

    # Create a temp dir for input to speed up wtfpad
    with tempfile.TemporaryDirectory() as temp_input_dir:
        shutil.copy(test_trace_path, temp_input_dir)
        shutil.copy(test_trace_path, os.path.join(temp_input_dir, '0.cell'))
        print(f"Using temp input dir: {temp_input_dir}")

        print("Testing FRONT with Strategy B...")
        # FRONT takes a directory and processes files in it? 
        # FRONT args: p (traces path)
        cmd = [
            "python3", "defenses/front/main.py",
            temp_input_dir,
            "-format", ".cell",
            "--fec-strategy", "B",
            "--log", "front_test.log"
        ]
        try:
            subprocess.check_call(cmd, cwd=base_dir)
            print("FRONT run successful.")
        except subprocess.CalledProcessError as e:
            print(f"FRONT failed: {e}")
            return

        print("Testing WTF-PAD with Strategy D...")
        cmd = [
            "python3", "defenses/wtfpad/main.py",
            temp_input_dir,
            "--fec-strategy", "D",
            "--log", "wtfpad_test.log"
        ]
        try:
            subprocess.check_call(cmd, cwd=base_dir)
            print("WTF-PAD run successful.")
        except subprocess.CalledProcessError as e:
            print(f"WTF-PAD failed: {e}")
            return

        print("Testing Tamaraw with Strategy C...")
        cmd = [
            "python3", "defenses/tamaraw/tamaraw.py",
            temp_input_dir,
            "--fec-strategy", "C",
            "--log", "tamaraw_test.log"
        ]
        try:
            subprocess.check_call(cmd, cwd=base_dir)
            print("Tamaraw run successful.")
        except subprocess.CalledProcessError as e:
            print(f"Tamaraw failed: {e}")
            return

        print("Testing Glue with Strategy C...")
        # Glue needs arguments: traces_path -n 1 -m 1 -b 10 -mode fix
        cmd = [
            "python3", "defenses/glue/main-base-rate.py",
            temp_input_dir,
            "-n", "1",
            "-m", "1",
            "-b", "10",
            "-mode", "fix",
            "--fec-strategy", "C",
            "--log", "glue_test.log"
        ]
        try:
            subprocess.check_call(cmd, cwd=base_dir)
            print("Glue run successful.")
        except subprocess.CalledProcessError as e:
            print(f"Glue failed: {e}")
            return

        print("Testing FRONT with Strategy B and 5% Loss...")
        cmd = [
            "python3", "defenses/front/main.py",
            temp_input_dir,
            "-format", ".cell",
            "--fec-strategy", "B",
            "--loss-rate", "0.05",
            "--rtt", "0.1",
            "--log", "front_loss_test.log"
        ]
        try:
            subprocess.check_call(cmd, cwd=base_dir)
            print("FRONT with Loss run successful.")
        except subprocess.CalledProcessError as e:
            print(f"FRONT with Loss failed: {e}")
            return

        # Check output files
        # FRONT output
        
        if not os.path.exists(results_dir):
             print(f"FAIL: Results directory not found at {results_dir}")
             return

        front_dirs = sorted([d for d in os.listdir(results_dir) if d.startswith("ranpad2_")])
        if front_dirs:
            latest_front = os.path.join(results_dir, front_dirs[-1])
            output_file = os.path.join(latest_front, "0-0.cell")
            if os.path.exists(output_file):
                print(f"Checking FRONT output: {output_file}")
                with open(output_file, 'r') as f:
                    lines = f.readlines()
                    # Check for 3rd column in at least one line
                    has_metadata = False
                    for line in lines:
                        parts = line.strip().split('\t')
                        if len(parts) > 2:
                            has_metadata = True
                            break
                    if has_metadata:
                        print("PASS: FRONT output contains metadata.")
                    else:
                        print("FAIL: FRONT output missing metadata.")
            else:
                print("FAIL: FRONT output file not found.")
        else:
            print("FAIL: FRONT results directory not found.")

        # WTF-PAD output
        wtfpad_dirs = sorted([d for d in os.listdir(results_dir) if d.startswith("wtfpad_")])
        if wtfpad_dirs:
            latest_wtfpad = os.path.join(results_dir, wtfpad_dirs[-1])
            output_file = os.path.join(latest_wtfpad, "0-0.cell")
            if os.path.exists(output_file):
                print(f"Checking WTF-PAD output: {output_file}")
                with open(output_file, 'r') as f:
                    lines = f.readlines()
                    has_metadata = False
                    for line in lines:
                        parts = line.strip().split('\t')
                        if len(parts) > 2:
                            has_metadata = True
                            break
                    if has_metadata:
                        print("PASS: WTF-PAD output contains metadata.")
                    else:
                        print("FAIL: WTF-PAD output missing metadata (Expected if no padding added).")
            else:
                print("FAIL: WTF-PAD output file not found.")
        else:
            print("FAIL: WTF-PAD results directory not found.")

        # Tamaraw output
        tamaraw_dirs = sorted([d for d in os.listdir(results_dir) if d.startswith("tamaraw_")])
        if tamaraw_dirs:
            latest_tamaraw = os.path.join(results_dir, tamaraw_dirs[-1])
            output_file = os.path.join(latest_tamaraw, "0-0.cell")
            if os.path.exists(output_file):
                print(f"Checking Tamaraw output: {output_file}")
                with open(output_file, 'r') as f:
                    lines = f.readlines()
                    has_metadata = False
                    for line in lines:
                        parts = line.strip().split('\t')
                        if len(parts) > 2:
                            has_metadata = True
                            break
                    if has_metadata:
                        print("PASS: Tamaraw output contains metadata.")
                    else:
                        print("FAIL: Tamaraw output missing metadata.")
            else:
                print("FAIL: Tamaraw output file not found.")
        else:
            print("FAIL: Tamaraw results directory not found.")
            
        # Glue output
        glue_dirs = sorted([d for d in os.listdir(results_dir) if d.startswith("mergepad_")])
        if glue_dirs:
            latest_glue = os.path.join(results_dir, glue_dirs[-1])
            # Glue output name is 0.merge (cnt=0)
            output_file = os.path.join(latest_glue, "0.merge")
            if os.path.exists(output_file):
                print(f"Checking Glue output: {output_file}")
                with open(output_file, 'r') as f:
                    lines = f.readlines()
                    has_metadata = False
                    for line in lines:
                        parts = line.strip().split('\t')
                        if len(parts) > 2:
                            has_metadata = True
                            break
                    if has_metadata:
                        print("PASS: Glue output contains metadata.")
                    else:
                        print("FAIL: Glue output missing metadata.")
            else:
                print("FAIL: Glue output file not found.")
        else:
            print("FAIL: Glue results directory not found.")

if __name__ == "__main__":
    run_test()
