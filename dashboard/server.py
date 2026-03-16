"""Simple Flask-based dashboard backend with SSE for pushing orderbook snapshots.

This module implements a lightweight MonitorManager that will instantiate
monitor classes available in `arbitrage` (e.g. LimitlessMonitor, PolymarketMonitor)
when possible. If a monitor type is unknown or fails to initialize, a simulator
monitor will be used so the dashboard remains functional.

The server provides:
- static UI at `/dashboard` (serves `static/index.html`)
- static UI at `/dashboard/event-markets` for event-to-markets lookup
- static UI at `/dashboard/logs` for live log tail
- REST API under `/api/monitors` for create/list/delete
- REST API under `/api/arbitrage` for arbitrage monitoring
- REST API under `/api/event-markets` for querying event markets by platform identifier
- REST API under `/api/logs/latest` for reading latest log lines
- SSE stream at `/stream/<monitor_id>` to push best bid/ask
"""
from __future__ import annotations

from collections import deque
import threading
import time
import uuid
import json
from queue import Queue, Empty
from typing import Dict, Any, Optional
from importlib import import_module
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from core.logger import logger

from flask import Flask, request, jsonify, send_from_directory, Response, abort

# Import arbitrage utilities
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from task import TaskManager


STATIC_DIR = 'static'
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_FILE = (PROJECT_ROOT / 'logs' / 'arbitrage.log').resolve()


def _parse_lines_arg(lines_raw: str | None, default: int = 50) -> int:
    try:
        lines = int(lines_raw) if lines_raw is not None else default
    except (TypeError, ValueError):
        raise ValueError('lines must be an integer')

    return max(1, min(lines, 200))


def _read_latest_log_lines(log_file: Path, max_lines: int) -> list[str]:
    if not log_file.exists():
        return []

    with log_file.open('r', encoding='utf-8', errors='replace') as f:
        return [line.rstrip('\n') for line in deque(f, maxlen=max_lines)]


def _fetch_json(url: str) -> Any:
    req = Request(url, headers={'User-Agent': 'arbitrage-dashboard/1.0'})
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _build_event_market_response(platform: str, identifier: str) -> dict[str, Any]:
    normalized_platform = (platform or '').strip().lower()
    normalized_identifier = (identifier or '').strip()

    if not normalized_identifier:
        raise ValueError('missing event identifier')

    if normalized_platform == 'kalshi':
        payload = _fetch_json(
            f'https://api.elections.kalshi.com/trade-api/v2/events/{quote(normalized_identifier.upper(), safe="")}'
        )
        event = payload.get('event') or {}
        raw_markets = payload.get('markets') or []
        return {
            'platform': normalized_platform,
            'event_identifier': normalized_identifier,
            'event_title': event.get('title') or normalized_identifier,
            'markets': [
                {
                    'identifier': market.get('ticker') or '',
                    'title': market.get('title') or market.get('subtitle') or '',
                }
                for market in raw_markets
                if market.get('ticker')
            ],
        }

    if normalized_platform == 'polymarket':
        payload = _fetch_json(
            f'https://gamma-api.polymarket.com/events/slug/{quote(normalized_identifier, safe="")}'
        )
        raw_markets = payload.get('markets') or []
        return {
            'platform': normalized_platform,
            'event_identifier': normalized_identifier,
            'event_title': payload.get('title') or payload.get('slug') or normalized_identifier,
            'markets': [
                {
                    'identifier': market.get('slug') or str(market.get('id') or ''),
                    'title': market.get('title') or market.get('question') or market.get('groupItemTitle') or '',
                }
                for market in raw_markets
                if market.get('slug') or market.get('id')
            ],
        }

    raise ValueError(f'unsupported platform: {platform}')


def create_app(manager: TaskManager | None = None) -> Flask:
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='/static')
    manager = manager or TaskManager()

    @app.route('/')
    def root():
        return send_from_directory(STATIC_DIR, 'index.html')

    @app.route('/dashboard')
    def dashboard_index():
        return send_from_directory(STATIC_DIR, 'index.html')

    @app.route('/dashboard/event-markets')
    def dashboard_event_markets():
        return send_from_directory(STATIC_DIR, 'event-markets.html')

    @app.route('/dashboard/logs')
    def dashboard_logs():
        return send_from_directory(STATIC_DIR, 'logs.html')

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
        required_fields = ['type1', 'market1', 'type2', 'market2', 'freq', 'min_spread', 'market1_budget', 'market2_budget']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'missing fields: ' + ', '.join(required_fields)}), 400

        try:
            market1_budget = float(data.get('market1_budget'))
            market2_budget = float(data.get('market2_budget'))
            min_order_quantity = float(data.get('min_order_quantity', 5.0) or 5.0)
            min_order_amount = float(data.get('min_order_amount', 1.0) or 1.0)
        except (TypeError, ValueError):
            return jsonify({'error': 'budget and minimum order fields must be valid numbers'}), 400

        if market1_budget <= 0 or market2_budget <= 0:
            return jsonify({'error': 'market1_budget and market2_budget must be greater than 0'}), 400
        if min_order_quantity < 0 or min_order_amount < 0:
            return jsonify({'error': 'min_order_quantity and min_order_amount must be greater than or equal to 0'}), 400
        
        cfg = {
            'type1': data.get('type1'),
            'market1': data.get('market1'),
            'type2': data.get('type2'),
            'market2': data.get('market2'),
            'max_arb_ratio': float(data.get('max_arb_ratio', 1.0)),
            'max_arb_quantity': float(data.get('max_arb_quantity', float('inf'))) if data.get('max_arb_quantity') else float('inf'),
            'min_order_quantity': min_order_quantity,
            'min_order_amount': min_order_amount,
            'market1_budget': market1_budget,
            'market2_budget': market2_budget,
            'freq': float(data.get('freq', 5)),
            'min_spread': float(data.get('min_spread', 0.01))
        }
        created = manager.create_arbitrage(cfg)
        return jsonify(created), 201

    @app.route('/api/event-markets', methods=['GET'])
    def api_event_markets():
        platform = request.args.get('platform', '')
        identifier = request.args.get('identifier', '')

        if not platform or not identifier:
            return jsonify({'error': 'missing query params: platform, identifier'}), 400

        try:
            return jsonify(_build_event_market_response(platform, identifier))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except HTTPError as exc:
            detail = exc.reason or 'upstream request failed'
            return jsonify({'error': f'upstream request failed: {detail}'}), exc.code
        except URLError as exc:
            return jsonify({'error': f'upstream request failed: {exc.reason}'}), 502

    @app.route('/api/logs/latest', methods=['GET'])
    def api_logs_latest():
        try:
            lines = _parse_lines_arg(request.args.get('lines'), default=50)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

        try:
            content = _read_latest_log_lines(DEFAULT_LOG_FILE, lines)
        except OSError as exc:
            return jsonify({'error': f'failed to read log file: {exc}'}), 500

        return jsonify({
            'log_file': DEFAULT_LOG_FILE.name,
            'requested_lines': lines,
            'line_count': len(content),
            'lines': content,
        })

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

