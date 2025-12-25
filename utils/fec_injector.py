import random
import json
import logging

class FECInjector:
    def __init__(self, strategy, window_size=32, block_size=10):
        self.strategy = strategy
        self.window_size = window_size
        self.block_size = block_size
        
        # Strategy A: Baseline (Control Group) - No state needed
        
        # Strategy B: Fixed Bucket
        self.current_block_id = 0
        self.packets_in_current_block = 0
        
        # Strategy C: LT-like Random Subset
        self.history_buffer = [] # Stores packet IDs
        
        # Strategy D: Smart Sliding Window RLNC
        self.head_id = -1
        self.first_missing_id = 0 # In simulation, we assume receiver confirms nothing, so this tracks oldest in window
        
        self.logger = logging.getLogger('fec_injector')

    def process_real_packet(self, packet_id):
        """
        Updates internal state when a real packet is sent.
        packet_id: Unique identifier for the packet (e.g., sequence number)
        """
        if self.strategy == 'A':
            pass
            
        elif self.strategy == 'B':
            self.packets_in_current_block += 1
            if self.packets_in_current_block >= self.block_size:
                self.current_block_id += 1
                self.packets_in_current_block = 0
                
        elif self.strategy == 'C':
            self.history_buffer.append(packet_id)
            if len(self.history_buffer) > self.window_size:
                self.history_buffer.pop(0)
                
        elif self.strategy == 'D':
            self.head_id = packet_id
            # Update first_missing_id logic
            # In a real scenario, this would be updated by ACKs.
            # In this simulation, we assume a sliding window of interest.
            # The "first missing" is effectively the start of our window.
            # We assume packet_id starts at 1.
            self.first_missing_id = max(1, self.head_id - self.window_size + 1)

    def generate_dummy_content(self):
        """
        Returns a dictionary containing FEC metadata for a dummy packet.
        If no FEC packet can be generated (e.g., buffer empty), returns None or a "Wasted" marker.
        """
        metadata = {
            "type": "FEC",
            "strategy": self.strategy
        }

        if self.strategy == 'A':
            metadata["type"] = "DUMMY" # Pure dummy, no FEC
            return metadata

        elif self.strategy == 'B':
            if self.packets_in_current_block > 0:
                metadata["block_id"] = self.current_block_id
                metadata["protected_count"] = self.packets_in_current_block
                return metadata
            elif self.current_block_id > 0:
                # If current block is empty, but we have a previous block, 
                # we can send more repair symbols for the previous block (optional, but good for utilization)
                # Or we just say it's empty.
                # For "Fixed Bucket", usually we only protect the *current* bucket until it's full?
                # Actually, if the bucket is full (packets_in_current_block == 0), it means we just finished one.
                # So we should probably protect the *previous* one (current_block_id - 1).
                metadata["block_id"] = self.current_block_id - 1
                metadata["protected_count"] = self.block_size
                metadata["info"] = "Previous Block Repair"
                return metadata
            else:
                metadata["type"] = "DUMMY" # Wasted slot
                metadata["info"] = "Empty Block"
                return metadata

        elif self.strategy == 'C':
            if not self.history_buffer:
                metadata["type"] = "DUMMY"
                metadata["info"] = "Empty Buffer"
                return metadata
            
            degree = random.randint(1, len(self.history_buffer))
            selected_indices = random.sample(range(len(self.history_buffer)), degree)
            selected_ids = [self.history_buffer[i] for i in selected_indices]
            
            metadata["degree"] = degree
            metadata["covered_ids"] = selected_ids
            return metadata

        elif self.strategy == 'D':
            if self.head_id == -1:
                metadata["type"] = "DUMMY"
                metadata["info"] = "No Data Yet"
                return metadata

            start = max(1, self.head_id - self.window_size + 1)
            # Ensure start is not less than first_missing_id (though in this sim they are tied)
            start = max(start, self.first_missing_id)
            
            end = self.head_id
            
            if start > end:
                 metadata["type"] = "DUMMY"
                 metadata["info"] = "Window Error"
                 return metadata

            metadata["start_id"] = start
            metadata["end_id"] = end
            return metadata
            
        else:
            self.logger.warning(f"Unknown strategy: {self.strategy}")
            metadata["type"] = "DUMMY"
            metadata["info"] = "Unknown Strategy"
            return metadata
