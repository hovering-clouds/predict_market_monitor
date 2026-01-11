"""Simple Flask-based dashboard backend with SSE for pushing orderbook snapshots.

This module implements a lightweight MonitorManager that will instantiate
monitor classes available in `arbitrage` (e.g. LimitlessMonitor, PolymarketMonitor)
when possible. If a monitor type is unknown or fails to initialize, a simulator
monitor will be used so the dashboard remains functional.

The server provides:
- static UI at `/dashboard` (serves `static/index.html`)
- REST API under `/api/monitors` for create/list/delete
- REST API under `/api/arbitrage` for arbitrage monitoring
- SSE stream at `/stream/<monitor_id>` to push best bid/ask
"""
from __future__ import annotations

import threading
import time
import uuid
import json
from queue import Queue, Empty
from typing import Dict, Any, Optional
from importlib import import_module
from core.logger import logger

from flask import Flask, request, jsonify, send_from_directory, Response, abort

# Import arbitrage utilities
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.utils import OrderBook, PriceInfo

STATIC_DIR = 'static'


class MonitorTask:
    def __init__(self, id: str, cfg: dict, queue: Queue):
        self.id = id
        self.cfg = cfg
        self.queue = queue
        self._stop = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=1)

    def run(self):
        # Try to build a real monitor instance
        monitor = None
        mtype = self.cfg.get('type')
        market = self.cfg.get('market')
        freq = max(float(self.cfg.get('freq', 5)), 1.0)

        # mapping known monitor types to class path
        mapping = {
            'limitless': ('limitless.limitless_monitor', 'LimitlessMonitor'),
            'polymarket': ('polymarket.polymarket_monitor', 'PolymarketMonitor'),
            'kalshi': ('kalshi.kalshi_monitor', 'KalshiMonitor'),
        }

        if mtype in mapping:
            modname, clsname = mapping[mtype]
            try:
                mod = import_module(modname)
                cls = getattr(mod, clsname)
                monitor = cls(market_type="manual", slug=market)
            except Exception as e:
                logger.error(f"Error initializing monitor {mtype} for market {market}: {e}")
                monitor = None

        while not self._stop.is_set():
            result = None
            if monitor:
                try:
                    ob = None
                    # try common method names
                    if hasattr(monitor, 'get_yes_orderbook'):
                        ob = monitor.get_yes_orderbook()
                    elif hasattr(monitor, 'get_all_orderbooks'):
                        allb = monitor.get_all_orderbooks()
                        ob = allb[0] if allb else None

                    if ob and hasattr(ob, 'bids') and hasattr(ob, 'asks'):
                        bid = ob.bids[0] if ob.bids else None
                        ask = ob.asks[0] if ob.asks else None
                        result = {
                            'bid': {'value': getattr(bid, 'value', None), 'quantity': getattr(bid, 'quantity', None)} if bid else None,
                            'ask': {'value': getattr(ask, 'value', None), 'quantity': getattr(ask, 'quantity', None)} if ask else None,
                        }
                except Exception:
                    result = None

            if result is None:
                result = {
                    'bid': {'value': '-', 'quantity': '-'},
                    'ask': {'value': '-', 'quantity': '-'}
                }

            # push to queue for any active SSE listeners
            try:
                self.queue.put_nowait(json.dumps(result))
            except Exception:
                pass

            time.sleep(freq)


class ArbitrageTask:
    """Monitor two markets and compute arbitrage opportunities."""
    def __init__(self, id: str, cfg: dict, queue: Queue):
        self.id = id
        self.cfg = cfg
        self.queue = queue
        self._stop = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.max_arb_ratio = float(cfg.get('max_arb_ratio', 1.0))  # 默认为100%
        self.max_arb_quantity = float(cfg.get('max_arb_quantity', float('inf')))  # 默认为无限制

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=1)

    def _build_monitor(self, mtype: str, market: str):
        """Build a monitor instance."""
        mapping = {
            'limitless': ('limitless.limitless_monitor', 'LimitlessMonitor'),
            'polymarket': ('polymarket.polymarket_monitor', 'PolymarketMonitor'),
            'kalshi': ('kalshi.kalshi_monitor', 'KalshiMonitor'),
        }

        if mtype in mapping:
            modname, clsname = mapping[mtype]
            try:
                mod = import_module(modname)
                cls = getattr(mod, clsname)
                return cls(market_type="manual", slug=market)
            except Exception as e:
                logger.error(f"Error initializing monitor {mtype} for market {market}: {e}")
        return None

    def _get_orderbook(self, monitor):
        """Get orderbook from monitor."""
        if not monitor:
            return None
        try:
            ob = None
            if hasattr(monitor, 'get_yes_orderbook'):
                ob = monitor.get_yes_orderbook()
            elif hasattr(monitor, 'get_all_orderbooks'):
                allb = monitor.get_all_orderbooks()
                ob = allb[0] if allb else None
            return ob
        except Exception as e:
            logger.error(f"Error getting orderbook: {e}")
            return None

    def _fetch_placeholder_orderbook(self):
        """Return placeholder orderbook when data fetch fails."""
        bid = PriceInfo(value=None, quantity=None)
        ask = PriceInfo(value=None, quantity=None)
        return OrderBook(bids=[bid], asks=[ask])

    def run(self):
        monitor1 = self._build_monitor(self.cfg.get('type1'), self.cfg.get('market1'))
        monitor2 = self._build_monitor(self.cfg.get('type2'), self.cfg.get('market2'))
        freq = max(float(self.cfg.get('freq', 5)), 1.0)
        min_spread = float(self.cfg.get('min_spread', 0.01))

        while not self._stop.is_set():
            try:
                # Get orderbooks from both markets
                ob1 = self._get_orderbook(monitor1)
                ob2 = self._get_orderbook(monitor2)
                
                # Extract best bid/ask
                market1_bid = ob1.bids[0] if ob1 and ob1.bids else None
                market1_ask = ob1.asks[0] if ob1 and ob1.asks else None
                market2_bid = ob2.bids[0] if ob2 and ob2.bids else None
                market2_ask = ob2.asks[0] if ob2 and ob2.asks else None

                result = None
                # Calculate arbitrage opportunity
                if ob1 and ob2:
                    if hasattr(ob1, 'find_arbitrage_opportunity'):
                        arb_spread, quantity = ob1.find_arbitrage_opportunity(ob2, min_spread)
                        # 应用最大套利比例和数量限制
                        limited_quantity = min(quantity * self.max_arb_ratio, self.max_arb_quantity)
                        
                        result = {
                            'market1_bid': {'value': market1_bid.value, 'quantity': market1_bid.quantity} if market1_bid else '-',
                            'market1_ask': {'value': market1_ask.value, 'quantity': market1_ask.quantity} if market1_ask else '-',
                            'market2_bid': {'value': market2_bid.value, 'quantity': market2_bid.quantity} if market2_bid else '-',
                            'market2_ask': {'value': market2_ask.value, 'quantity': market2_ask.quantity} if market2_ask else '-',
                            'arbitrage_spread': round(arb_spread, 6),
                            'arbitrage_quantity': round(quantity, 6),
                        }
                if result is None:
                    result = {
                        'market1_bid': {'value': market1_bid.value, 'quantity': market1_bid.quantity} if market1_bid else '-',
                        'market1_ask': {'value': market1_ask.value, 'quantity': market1_ask.quantity} if market1_ask else '-',
                        'market2_bid': {'value': market2_bid.value, 'quantity': market2_bid.quantity} if market2_bid else '-',
                        'market2_ask': {'value': market2_ask.value, 'quantity': market2_ask.quantity} if market2_ask else '-',
                        'arbitrage_spread': '-',
                        'arbitrage_quantity': '-',
                    }

                # Push to queue
                try:
                    self.queue.put_nowait(json.dumps(result))
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"Error in arbitrage task: {e}")

            time.sleep(freq)


class MonitorManager:
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
            'market2': cfg.get('market2'),
            'min_spread': cfg.get('min_spread'),
            'freq': cfg.get('freq', 5),
            'status': 'running'
        }

    def list_monitors(self):
        with self._lock:
            result = []
            for mid, t in self._tasks.items():
                if isinstance(t, ArbitrageTask):
                    result.append({
                        'id': mid,
                        'arbitrage_pair': True,
                        'type1': t.cfg.get('type1'),
                        'max_arb_ratio': t.cfg.get('max_arb_ratio', 1.0),
                        'max_arb_quantity': t.cfg.get('max_arb_quantity', float('inf')),
                        'market1': t.cfg.get('market1'),
                        'type2': t.cfg.get('type2'),
                        'market2': t.cfg.get('market2'),
                        'min_spread': t.cfg.get('min_spread'),
                        'freq': t.cfg.get('freq', 5),
                        'status': 'running'
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


def create_app(manager: MonitorManager | None = None) -> Flask:
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='/static')
    manager = manager or MonitorManager()

    @app.route('/')
    def root():
        return send_from_directory(STATIC_DIR, 'index.html')

    @app.route('/dashboard')
    def dashboard_index():
        return send_from_directory(STATIC_DIR, 'index.html')

    @app.route('/api/monitors', methods=['GET', 'POST'])
    def api_monitors():
        if request.method == 'GET':
            return jsonify(manager.list_monitors())

        data = request.get_json() or {}
        if 'type' not in data or 'market' not in data:
            return jsonify({'error': 'missing fields'}), 400
        cfg = {'type': data.get('type'), 'market': data.get('market'), 'freq': data.get('freq', 5)}
        created = manager.create_monitor(cfg)
        return jsonify(created), 201

    @app.route('/api/arbitrage', methods=['POST'])
    def api_arbitrage():
        """Create an arbitrage monitoring task."""
        data = request.get_json() or {}
        required_fields = ['type1', 'market1', 'type2', 'market2', 'freq', 'min_spread']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'missing fields: ' + ', '.join(required_fields)}), 400
        
        cfg = {
            'type1': data.get('type1'),
            'market1': data.get('market1'),
            'type2': data.get('type2'),
            'market2': data.get('market2'),
            'max_arb_ratio': float(data.get('max_arb_ratio', 1.0)),
            'max_arb_quantity': float(data.get('max_arb_quantity', float('inf'))) if data.get('max_arb_quantity') else float('inf'),
            'freq': float(data.get('freq', 5)),
            'min_spread': float(data.get('min_spread', 0.01))
        }
        created = manager.create_arbitrage(cfg)
        return jsonify(created), 201

    @app.route('/api/monitors/<mid>', methods=['DELETE'])
    def api_cancel(mid):
        ok = manager.cancel_monitor(mid)
        if ok:
            return '', 204
        return jsonify({'error': 'not found'}), 404

    @app.route('/stream/<mid>')
    def stream(mid):
        q = manager.get_queue(mid)
        if q is None:
            abort(404)

        def gen():
            # SSE response generator
            while True:
                try:
                    item = q.get(timeout=30)
                    yield f'data: {item}\n\n'
                except Empty:
                    # send a comment to keep connection alive
                    yield ': keep-alive\n\n'

        return Response(gen(), mimetype='text/event-stream')

    # expose manager for external usage
    app.monitor_manager = manager
    return app


def run_server(host='0.0.0.0', port=5000):
    mgr = MonitorManager()
    app = create_app(mgr)
    logger.info(f"Starting dashboard on http://{host}:{port}/dashboard")
    app.run(host=host, port=port, threaded=True)

