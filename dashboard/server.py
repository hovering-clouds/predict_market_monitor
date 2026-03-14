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
from task import TaskManager


STATIC_DIR = 'static'


def create_app(manager: TaskManager | None = None) -> Flask:
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='/static')
    manager = manager or TaskManager()

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
            'max_arb_cnt': int(data.get('max_arb_cnt', 0) or 0),
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
    app.task_manager = manager
    return app


def run_server(host='0.0.0.0', port=5000):
    mgr = TaskManager()
    app = create_app(mgr)
    logger.info(f"Starting dashboard on http://{host}:{port}/dashboard")
    app.run(host=host, port=port, threaded=True)

