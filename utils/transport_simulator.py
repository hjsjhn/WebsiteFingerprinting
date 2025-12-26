import heapq
import random
import json
import logging
import sys

logger = logging.getLogger('transport_sim')
logging.basicConfig(level=logging.INFO)

class TransportSimulator:
    def __init__(self, loss_rate=0.0, rtt=0.1, seed=None):
        self.loss_rate = loss_rate
        self.rtt = rtt
        self.seed = seed
        if seed:
            random.seed(seed)
            
        # State for Strategy D (Gaussian Elimination)
        # equations: list of sets, where each set contains sim_ids of unknown packets
        self.strategy_d_equations = {1: [], -1: []}
        
        # State for Strategy B (MDS Block)
        # block_state: {block_id: {'fec_count': 0}}
        self.strategy_b_state = {1: {}, -1: {}}

    def _is_real(self, packet):
        meta = packet[2] if len(packet) > 2 else {}
        if not meta:
            return True
        if meta.get('type') in ['FEC', 'DUMMY']:
            return False
        return True

    def simulate(self, trace):
        random.seed(self.seed)
        
        # Reset state
        self.strategy_d_equations = {1: [], -1: []}
        self.strategy_b_state = {1: {}, -1: {}}
        
        stats = {
            'total_real': 0,
            'total_fec': 0,
            'total_dummy': 0,
            'lost_real': 0,
            'recovered_real': 0,
            'retransmitted_real': 0,
            'total_latency': 0.0
        }
        
        events = []
        counter = 0
        
        for p in trace:
            pkt_info = {
                'original_ts': p[0],
                'length': p[1],
                'metadata': p[2] if len(p) > 2 else {},
                'is_real': self._is_real(p),
                'sim_id': None,
                'retrans_count': 0,
                'delivered': False
            }
            
            if pkt_info['is_real']:
                stats['total_real'] += 1
            else:
                # Check if it's FEC or DUMMY
                meta = pkt_info['metadata']
                if meta.get('type') == 'FEC':
                    stats['total_fec'] += 1
                else:
                    stats['total_dummy'] += 1
                
            heapq.heappush(events, (p[0], counter, 'SEND', pkt_info))
            counter += 1
            
        lost_real_packets = {1: {}, -1: {}} 
        final_trace = []
        sim_id_counters = {1: 0, -1: 0}
        current_time = 0
        
        while events:
            ts, _, event_type, p = heapq.heappop(events)
            current_time = ts
            
            if event_type == 'SEND':
                if p['is_real'] and p['sim_id'] is None:
                    direction = 1 if p['length'] > 0 else -1
                    sim_id_counters[direction] += 1
                    p['sim_id'] = sim_id_counters[direction]
                
                is_lost = random.random() < self.loss_rate
                
                if is_lost:
                    if p['is_real']:
                        rto = self.rtt * 1.5
                        timeout_ts = current_time + rto
                        
                        direction = 1 if p['length'] > 0 else -1
                        if p['retrans_count'] == 0:
                             stats['lost_real'] += 1
                             
                        lost_real_packets[direction][p['sim_id']] = p
                        
                        heapq.heappush(events, (timeout_ts, counter, 'TIMEOUT', p))
                        counter += 1
                    else:
                        pass
                else:
                    arrival_ts = current_time + (self.rtt / 2)
                    
                    if p['is_real']:
                        direction = 1 if p['length'] > 0 else -1
                        if p['sim_id'] in lost_real_packets[direction]:
                            del lost_real_packets[direction][p['sim_id']]
                            p['delivered'] = True
                            # Latency Calculation
                            latency = arrival_ts - p['original_ts']
                            stats['total_latency'] += latency
                            
                            # Also remove from Strategy D equations if it was considered lost but now delivered (retransmission arrived)
                            self._remove_recovered_id_from_equations(direction, p['sim_id'])
                        elif not p['delivered']:
                             # First time delivery (not lost)
                             p['delivered'] = True
                             latency = arrival_ts - p['original_ts']
                             stats['total_latency'] += latency
                    
                    final_trace.append([arrival_ts, p['length'], p['metadata']])
                    
                    if not p['is_real']:
                        recovered_pkts = self._process_fec(p, lost_real_packets)
                        for rec_p in recovered_pkts:
                             final_trace.append([arrival_ts, rec_p['length'], rec_p['metadata']])
                             stats['recovered_real'] += 1
                             # Latency for recovered packet
                             latency = arrival_ts - rec_p['original_ts']
                             stats['total_latency'] += latency
                        
            elif event_type == 'TIMEOUT':
                if p['delivered']:
                    continue
                
                direction = 1 if p['length'] > 0 else -1
                if p['is_real'] and p['sim_id'] in lost_real_packets[direction]:
                    p['retrans_count'] += 1
                    stats['retransmitted_real'] += 1
                    heapq.heappush(events, (current_time, counter, 'SEND', p))
                    counter += 1

        final_trace.sort(key=lambda x: x[0])
        
        # Calculate FCT based on the last delivered REAL packet
        fct = 0.0
        for i in range(len(final_trace) - 1, -1, -1):
            # final_trace item: [ts, len, meta]
            if self._is_real(final_trace[i]):
                fct = final_trace[i][0]
                break
        
        avg_latency = stats['total_latency'] / stats['total_real'] if stats['total_real'] > 0 else 0.0
        
        print(f"[TransportSimulator] Stats: Total Real={stats['total_real']}, FEC={stats['total_fec']}, Dummy={stats['total_dummy']}, "
                     f"Lost={stats['lost_real']}, Recovered={stats['recovered_real']}, "
                     f"Retransmitted={stats['retransmitted_real']}, FCT={fct:.4f}, AvgLatency={avg_latency:.4f}", flush=True)
                     
        return final_trace

    def _remove_recovered_id_from_equations(self, direction, sim_id):
        """
        Removes a recovered packet ID from all Strategy D equations.
        This simulates back-substitution.
        """
        new_eqs = []
        for eq in self.strategy_d_equations[direction]:
            if sim_id in eq:
                eq.remove(sim_id)
            if eq: # Keep non-empty equations
                new_eqs.append(eq)
        self.strategy_d_equations[direction] = new_eqs

    def _process_fec(self, fec_pkt, lost_real_packets):
        meta = fec_pkt['metadata']
        if not meta:
            return []
            
        direction = 1 if fec_pkt['length'] > 0 else -1
        recovered_ids = []
        
        # Strategy B: MDS Block Recovery
        if 'block_id' in meta:
            block_id = meta['block_id']
            protected_count = meta['protected_count']
            block_size = 10 # Default
            
            # Initialize block state if needed
            if block_id not in self.strategy_b_state[direction]:
                self.strategy_b_state[direction][block_id] = {'fec_count': 0}
            
            self.strategy_b_state[direction][block_id]['fec_count'] += 1
            
            start_id = block_id * block_size + 1
            end_id = start_id + protected_count - 1
            
            # Identify lost packets in this block
            lost_in_block = []
            for sim_id in lost_real_packets[direction]:
                if start_id <= sim_id <= end_id:
                    lost_in_block.append(sim_id)
            
            # MDS Logic: If FEC packets received >= Lost packets, recover ALL
            if self.strategy_b_state[direction][block_id]['fec_count'] >= len(lost_in_block):
                recovered_ids.extend(lost_in_block)

        # Strategy D: Gaussian Elimination
        elif 'start_id' in meta:
            win_start = meta['start_id']
            win_end = meta['end_id']
            
            # Identify unknowns (lost packets) in this window
            unknowns = set()
            for sim_id in lost_real_packets[direction]:
                if win_start <= sim_id <= win_end:
                    unknowns.add(sim_id)
            
            if unknowns:
                # Add new equation
                # We need to integrate this new equation into our system (Row Echelon Form)
                new_row = unknowns
                
                # Re-build the basis with the new row
                current_basis = self.strategy_d_equations[direction]
                current_basis.append(new_row)
                
                new_basis = []
                # Sort by min element to process in order
                current_basis.sort(key=lambda x: min(x) if x else float('inf'))
                
                for row in current_basis:
                    if not row:
                        continue
                        
                    # Try to insert row into new_basis
                    while row:
                        pivot = min(row)
                        collision = None
                        for b_row in new_basis:
                            if min(b_row) == pivot:
                                collision = b_row
                                break
                        
                        if collision:
                            row = row.symmetric_difference(collision)
                        else:
                            new_basis.append(row)
                            new_basis.sort(key=lambda x: min(x)) # Keep sorted
                            break
                
                self.strategy_d_equations[direction] = new_basis
                
                # Back-Substitution (Jordan)
                # Iterate backwards
                for i in range(len(new_basis) - 1, -1, -1):
                    row = new_basis[i]
                    pivot = min(row)
                    for j in range(i):
                        if pivot in new_basis[j]:
                            new_basis[j] = new_basis[j].symmetric_difference(row)
                
                self.strategy_d_equations[direction] = new_basis

                # Check for solved variables
                progress = True
                while progress:
                    progress = False
                    solved_vars = set()
                    
                    for eq in self.strategy_d_equations[direction]:
                        if len(eq) == 1:
                            solved_var = list(eq)[0]
                            if solved_var not in solved_vars:
                                solved_vars.add(solved_var)
                                recovered_ids.append(solved_var)
                                progress = True
                    
                    if solved_vars:
                        new_eqs = []
                        for eq in self.strategy_d_equations[direction]:
                            eq.difference_update(solved_vars)
                            if eq:
                                new_eqs.append(eq)
                        self.strategy_d_equations[direction] = new_eqs

        recovered_pkts = []
        # Deduplicate recovered_ids
        recovered_ids = list(set(recovered_ids))
        
        for rec_id in recovered_ids:
            if rec_id in lost_real_packets[direction]:
                p = lost_real_packets[direction][rec_id]
                del lost_real_packets[direction][rec_id]
                p['delivered'] = True
                recovered_pkts.append(p)
                
                # Also remove from Strategy D equations
                self._remove_recovered_id_from_equations(direction, rec_id)
                
        return recovered_pkts
