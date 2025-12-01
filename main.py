"""Project entrypoint to run the arbitrage dashboard server.

This script starts the lightweight Flask dashboard which allows users to
create/cancel monitor tasks and receive best bid/ask snapshots via SSE.

Run:
    python main.py

You can pass `--host` and `--port` environment variables or edit below.
"""
import os
import argparse

from dashboard.server import run_server


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--host', default=os.environ.get('DASH_HOST', '0.0.0.0'))
    p.add_argument('--port', type=int, default=int(os.environ.get('DASH_PORT', 5000)))
    return p.parse_args()


def main():
    args = parse_args()
    run_server(host=args.host, port=args.port)


if __name__ == '__main__':
    main()
