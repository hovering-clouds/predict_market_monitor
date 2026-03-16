import threading
import uuid
from queue import Queue, Empty
from typing import Dict, Any, Optional
from .arbitrage_task import MonitorTask, ArbitrageTask

class TaskManager:
    def __init__(self):
        self._tasks: Dict[str, Any] = {}
        self._queues: Dict[str, Queue] = {}
        self._lock = threading.Lock()

    def create_monitor(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        mid = str(uuid.uuid4())
        q = Queue()
        task = MonitorTask(mid, cfg, q)
        with self._lock:
            self._tasks[mid] = task
            self._queues[mid] = q
        task.start()
        return {'id': mid, 'type': cfg.get('type'), 'market': cfg.get('market'), 'freq': cfg.get('freq', 5), 'status': 'running'}

    def create_arbitrage(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Create an arbitrage monitoring task."""
        mid = str(uuid.uuid4())
        q = Queue()
        task = ArbitrageTask(mid, cfg, q)
        with self._lock:
            self._tasks[mid] = task
            self._queues[mid] = q
        task.start()
        return {
            'id': mid,
            'arbitrage_pair': True,
            'type1': cfg.get('type1'),
            'market1': cfg.get('market1'),
            'type2': cfg.get('type2'),
            'max_arb_ratio': cfg.get('max_arb_ratio', 1.0),
            'max_arb_quantity': cfg.get('max_arb_quantity', float('inf')),
            'min_order_quantity': cfg.get('min_order_quantity', 5.0),
            'min_order_amount': cfg.get('min_order_amount', 1.0),
            'market1_budget': cfg.get('market1_budget'),
            'market2_budget': cfg.get('market2_budget'),
            'market1_remaining_budget': task.market1_remaining_budget,
            'market2_remaining_budget': task.market2_remaining_budget,
            'market1_consumed_budget': task.market1_consumed_budget,
            'market2_consumed_budget': task.market2_consumed_budget,
            'arb_cnt': task.arb_cnt,
            'market2': cfg.get('market2'),
            'min_spread': cfg.get('min_spread'),
            'freq': cfg.get('freq', 5),
            'status': task.status
        }

    def list_monitors(self):
        with self._lock:
            result = []
            for mid, t in self._tasks.items():
                if isinstance(t, ArbitrageTask):
                    status = t.status
                    result.append({
                        'id': mid,
                        'arbitrage_pair': True,
                        'type1': t.cfg.get('type1'),
                        'max_arb_ratio': t.cfg.get('max_arb_ratio', 1.0),
                        'max_arb_quantity': t.cfg.get('max_arb_quantity', float('inf')),
                        'min_order_quantity': t.min_order_quantity,
                        'min_order_amount': t.min_order_amount,
                        'market1_budget': t.market1_budget,
                        'market2_budget': t.market2_budget,
                        'market1_remaining_budget': t.market1_remaining_budget,
                        'market2_remaining_budget': t.market2_remaining_budget,
                        'market1_consumed_budget': t.market1_consumed_budget,
                        'market2_consumed_budget': t.market2_consumed_budget,
                        'arb_cnt': t.arb_cnt,
                        'market1': t.cfg.get('market1'),
                        'type2': t.cfg.get('type2'),
                        'market2': t.cfg.get('market2'),
                        'min_spread': t.cfg.get('min_spread'),
                        'freq': t.cfg.get('freq', 5),
                        'status': status
                    })
                else:
                    result.append({
                        'id': mid,
                        'type': t.cfg.get('type'),
                        'market': t.cfg.get('market'),
                        'freq': t.cfg.get('freq', 5),
                        'status': 'running'
                    })
            return result

    def cancel_monitor(self, mid: str) -> bool:
        with self._lock:
            t = self._tasks.pop(mid, None)
            q = self._queues.pop(mid, None)
        if t:
            t.stop()
        return t is not None

    def get_queue(self, mid: str) -> Optional[Queue]:
        return self._queues.get(mid)

