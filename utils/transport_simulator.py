import heapq
import random
import json
import logging
import sys

logger = logging.getLogger('transport_sim')
logging.basicConfig(level=logging.INFO)

class TransportSimulator:
    def __init__(self, loss_rate=0.0, rtt=0.1, max_inflight=20, seed=None, debug_log_path=None):
        self.loss_rate = loss_rate
        self.rtt = rtt
        self.max_inflight = max_inflight
        self.seed = seed
        self.debug_log_path = debug_log_path
        if seed:
            random.seed(seed)
            
        # State for Gaussian Elimination (Shared by Strategy D and C)
        self.gaussian_equations = {1: [], -1: []}
        # State for Strategy B (MDS Block)
        self.strategy_b_state = {1: {}, -1: {}}
        
        # Debug Log File Handle
        self.log_file = None

    def _log_event(self, event_type, details):
        if self.log_file:
            self.log_file.write(f"[{event_type}] {details}\n")

    def _is_real(self, packet):
        meta = packet[2] if len(packet) > 2 else {}
        if not meta:
            return True
        if meta.get('type') in ['FEC', 'DUMMY']:
            return False
        return True

    def simulate(self, trace):
        random.seed(self.seed)
        
        if self.debug_log_path:
            try:
                self.log_file = open(self.debug_log_path, 'w')
                self.log_file.write(f"Simulation Start: Loss={self.loss_rate}, RTT={self.rtt}, MaxInflight={self.max_inflight}, Seed={self.seed}\n")
            except Exception as e:
                print(f"Failed to open debug log: {e}")

        # Reset state
        self.gaussian_equations = {1: [], -1: []}
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
        
        # Pre-process trace to identify types
        trace_queue = []
        for p in trace:
            pkt_info = {
                'original_ts': p[0],
                'length': p[1],
                'metadata': p[2] if len(p) > 2 else {},
                'is_real': self._is_real(p),
                'sim_id': None,
                'retrans_count': 0,
                'delivered': False,
                'acked': False
            }
            if pkt_info['is_real']:
                stats['total_real'] += 1
            else:
                meta = pkt_info['metadata']
                if meta.get('type') == 'FEC':
                    stats['total_fec'] += 1
                else:
                    stats['total_dummy'] += 1
            trace_queue.append(pkt_info)

        # Simulation State
        current_time = 0.0
        trace_idx = 0
        inflight = {1: 0, -1: 0}
        sim_id_counters = {1: 0, -1: 0}
        lost_real_packets = {1: {}, -1: {}}
        
        events = []
        event_counter = 0
        
        final_trace = []
        
        while trace_idx < len(trace_queue) or events:
            next_trace_ts = trace_queue[trace_idx]['original_ts'] if trace_idx < len(trace_queue) else float('inf')
            next_event_ts = events[0][0] if events else float('inf')
            
            can_send = False
            if trace_idx < len(trace_queue):
                p = trace_queue[trace_idx]
                direction = 1 if p['length'] > 0 else -1
                if inflight[direction] < self.max_inflight:
                    effective_send_time = max(current_time, next_trace_ts)
                    if effective_send_time <= next_event_ts:
                        can_send = True
            
            if can_send:
                p = trace_queue[trace_idx]
                current_time = max(current_time, p['original_ts'])
                direction = 1 if p['length'] > 0 else -1
                
                if p['is_real'] and p['sim_id'] is None:
                    sim_id_counters[direction] += 1
                    p['sim_id'] = sim_id_counters[direction]
                
                inflight[direction] += 1
                trace_idx += 1
                
                # Log SEND event
                pkt_type = "REAL" if p['is_real'] else p['metadata'].get('type', 'DUMMY')
                meta_str = json.dumps(p['metadata']) if not p['is_real'] else ""
                sim_id_str = f"sim_id={p['sim_id']}" if p['is_real'] else ""
                self._log_event("PACKET_SEND", f"type={pkt_type}, dir={direction}, ts={current_time:.4f}, {sim_id_str} {meta_str}")
                
                is_lost = random.random() < self.loss_rate
                
                if is_lost:
                    if p['is_real']:
                        if p['retrans_count'] == 0:
                            stats['lost_real'] += 1
                            self._log_event("LOST_REAL", f"sim_id={p['sim_id']}, dir={direction}, ts={current_time:.4f}")
                        lost_real_packets[direction][p['sim_id']] = p
                        
                        rto = self.rtt * 1.5
                        heapq.heappush(events, (current_time + rto, event_counter, 'TIMEOUT', p))
                        event_counter += 1
                    else:
                        self._log_event("LOST_FEC_DUMMY", f"type={p['metadata'].get('type', 'DUMMY')}, dir={direction}, ts={current_time:.4f}")
                        heapq.heappush(events, (current_time + self.rtt, event_counter, 'ACK_CLEAR', p))
                        event_counter += 1
                else:
                    arrival_time = current_time + (self.rtt / 2)
                    heapq.heappush(events, (arrival_time, event_counter, 'ARRIVAL', p))
                    event_counter += 1
                    
            else:
                if not events: break
                
                ts, _, etype, p = heapq.heappop(events)
                current_time = ts
                direction = 1 if p['length'] > 0 else -1
                
                if etype == 'ARRIVAL':
                    final_trace.append([current_time, p['length'], p['metadata']])
                    
                    # Log ARRIVAL event
                    pkt_type = "REAL" if p['is_real'] else p['metadata'].get('type', 'DUMMY')
                    meta_str = json.dumps(p['metadata']) if not p['is_real'] else ""
                    sim_id_str = f"sim_id={p['sim_id']}" if p['is_real'] else ""
                    self._log_event("PACKET_ARRIVAL", f"type={pkt_type}, dir={direction}, ts={current_time:.4f}, {sim_id_str} {meta_str}")
                    
                    if p['is_real']:
                        if p['sim_id'] in lost_real_packets[direction]:
                             del lost_real_packets[direction][p['sim_id']]
                             self._remove_recovered_id_from_equations(direction, p['sim_id'])
                             self._log_event("RETRANS_ARRIVED", f"sim_id={p['sim_id']}, dir={direction}, ts={current_time:.4f}")
                        
                        if not p['delivered']:
                            p['delivered'] = True
                            latency = current_time - p['original_ts']
                            stats['total_latency'] += latency
                        
                        ack_time = current_time + (self.rtt / 2)
                        heapq.heappush(events, (ack_time, event_counter, 'ACK', p))
                        event_counter += 1
                        
                    else:
                        # FEC/Dummy arrived
                        recovered_pkts = self._process_fec(p, lost_real_packets)
                        for rec_p in recovered_pkts:
                            final_trace.append([current_time, rec_p['length'], rec_p['metadata']])
                            stats['recovered_real'] += 1
                            latency = current_time - rec_p['original_ts']
                            stats['total_latency'] += latency
                            
                            self._log_event("RECOVERED", f"sim_id={rec_p['sim_id']}, dir={direction}, ts={current_time:.4f}, via_fec_ts={current_time:.4f}")
                            
                            ack_time = current_time + (self.rtt / 2)
                            heapq.heappush(events, (ack_time, event_counter, 'ACK', rec_p))
                            event_counter += 1
                            
                        ack_time = current_time + (self.rtt / 2)
                        heapq.heappush(events, (ack_time, event_counter, 'ACK_CLEAR', p))
                        event_counter += 1

                elif etype == 'ACK':
                    if not p['acked']:
                        p['acked'] = True
                        inflight[direction] -= 1
                        
                elif etype == 'ACK_CLEAR':
                    inflight[direction] -= 1

                elif etype == 'TIMEOUT':
                    if p['delivered'] or p['acked']:
                        continue
                    
                    if p['is_real']:
                        p['retrans_count'] += 1
                        stats['retransmitted_real'] += 1
                        self._log_event("TIMEOUT_RETRANS", f"sim_id={p['sim_id']}, dir={direction}, count={p['retrans_count']}, ts={current_time:.4f}")
                        
                        is_lost = random.random() < self.loss_rate
                        if is_lost:
                            self._log_event("LOST_RETRANS", f"sim_id={p['sim_id']}, dir={direction}, ts={current_time:.4f}")
                            rto = self.rtt * 1.5
                            heapq.heappush(events, (current_time + rto, event_counter, 'TIMEOUT', p))
                            event_counter += 1
                        else:
                            arrival_time = current_time + (self.rtt / 2)
                            heapq.heappush(events, (arrival_time, event_counter, 'ARRIVAL', p))
                            event_counter += 1

        final_trace.sort(key=lambda x: x[0])
        
        fct = 0.0
        for i in range(len(final_trace) - 1, -1, -1):
            if self._is_real(final_trace[i]):
                fct = final_trace[i][0]
                break
        
        avg_latency = stats['total_latency'] / stats['total_real'] if stats['total_real'] > 0 else 0.0
        
        stats_line = f"[TransportSimulator] Stats: Total Real={stats['total_real']}, FEC={stats['total_fec']}, Dummy={stats['total_dummy']}, Lost={stats['lost_real']}, Recovered={stats['recovered_real']}, Retransmitted={stats['retransmitted_real']}, FCT={fct:.4f}, AvgLatency={avg_latency:.4f}"
        print(stats_line, flush=True)
        
        if self.debug_log_path:
            with open(self.debug_log_path, 'a') as f:
                f.write(stats_line + '\n')
        
        if self.log_file:
            self.log_file.close()
            
        return final_trace

    def _remove_recovered_id_from_equations(self, direction, sim_id):
        new_eqs = []
        for eq in self.gaussian_equations[direction]:
            if sim_id in eq:
                eq.remove(sim_id)
            if eq:
                new_eqs.append(eq)
        self.gaussian_equations[direction] = new_eqs

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
            block_size = 10 
            
            if block_id not in self.strategy_b_state[direction]:
                self.strategy_b_state[direction][block_id] = {'fec_count': 0}
            
            self.strategy_b_state[direction][block_id]['fec_count'] += 1
            
            start_id = block_id * block_size + 1
            end_id = start_id + protected_count - 1
            
            lost_in_block = []
            for sim_id in lost_real_packets[direction]:
                if start_id <= sim_id <= end_id:
                    lost_in_block.append(sim_id)
            
            if self.strategy_b_state[direction][block_id]['fec_count'] >= len(lost_in_block):
                recovered_ids.extend(lost_in_block)

        # Strategy C (LT-like) or Strategy D (Gaussian Elimination)
        elif 'seed' in meta or 'start_id' in meta:
            unknowns = set()
            
            if 'seed' in meta: # Strategy C
                seed = meta['seed']
                degree = meta['degree']
                min_id = meta['min_id']
                max_id = meta['max_id']
                buffer_size = meta['buffer_size']
                
                # Reconstruct the set of IDs covered by this FEC packet
                # We need to replicate the exact logic from FECInjector
                # Ideally, we should import FECInjector or share the logic, but for now we duplicate it carefully.
                # Assuming history buffer was [min_id, ..., max_id] (contiguous)
                # NOTE: This assumption holds if no gaps in ID generation, which is true for our sim_id.
                
                # Re-seed random generator
                # We need to be careful about the random state. 
                # Using a local Random instance is safer to avoid messing up the global state.
                rng = random.Random(seed)
                
                # Reconstruct history buffer IDs
                # If buffer_size matches max_id - min_id + 1, it's contiguous.
                # If not, we might have an issue if we don't know the exact gaps.
                # In our simulation, sim_id is strictly increasing 1, 2, 3... so it should be contiguous.
                history_ids = list(range(min_id, max_id + 1))
                
                # In case the buffer was smaller than the range (e.g. sliding window popped old ones),
                # FECInjector logic: history_buffer.append(packet_id); if len > window: pop(0)
                # So the buffer is always a contiguous range of IDs [min, max].
                # Wait, if we pop(0), min_id increases. Yes.
                # So history_ids = list(range(min_id, max_id + 1)) is correct.
                
                if len(history_ids) != buffer_size:
                     # This might happen if our assumption about contiguous IDs is wrong.
                     # But given process_real_packet logic, it should be fine.
                     pass

                if history_ids:
                    selected_indices = rng.sample(range(len(history_ids)), degree)
                    covered_ids = [history_ids[i] for i in selected_indices]
                    
                    for sim_id in covered_ids:
                        if sim_id in lost_real_packets[direction]:
                            unknowns.add(sim_id)

            elif 'start_id' in meta: # Strategy D
                win_start = meta['start_id']
                win_end = meta['end_id']
                for sim_id in lost_real_packets[direction]:
                    if win_start <= sim_id <= win_end:
                        unknowns.add(sim_id)
            
            if unknowns:
                new_row = unknowns
                current_basis = self.gaussian_equations[direction]
                current_basis.append(new_row)
                
                new_basis = []
                current_basis.sort(key=lambda x: min(x) if x else float('inf'))
                
                for row in current_basis:
                    if not row: continue
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
                            new_basis.sort(key=lambda x: min(x))
                            break
                
                self.gaussian_equations[direction] = new_basis
                
                for i in range(len(new_basis) - 1, -1, -1):
                    row = new_basis[i]
                    pivot = min(row)
                    for j in range(i):
                        if pivot in new_basis[j]:
                            new_basis[j] = new_basis[j].symmetric_difference(row)
                
                self.gaussian_equations[direction] = new_basis

                progress = True
                while progress:
                    progress = False
                    solved_vars = set()
                    for eq in self.gaussian_equations[direction]:
                        if len(eq) == 1:
                            solved_var = list(eq)[0]
                            if solved_var not in solved_vars:
                                solved_vars.add(solved_var)
                                recovered_ids.append(solved_var)
                                progress = True
                    if solved_vars:
                        new_eqs = []
                        for eq in self.gaussian_equations[direction]:
                            eq.difference_update(solved_vars)
                            if eq:
                                new_eqs.append(eq)
                        self.gaussian_equations[direction] = new_eqs

        recovered_pkts = []
        recovered_ids = list(set(recovered_ids))
        
        for rec_id in recovered_ids:
            if rec_id in lost_real_packets[direction]:
                p = lost_real_packets[direction][rec_id]
                del lost_real_packets[direction][rec_id]
                p['delivered'] = True 
                recovered_pkts.append(p)
                self._remove_recovered_id_from_equations(direction, rec_id)
                
        return recovered_pkts
