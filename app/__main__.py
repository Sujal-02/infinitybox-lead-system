"""python -m app [--port 8765]"""
import argparse

from .server import serve

p = argparse.ArgumentParser(prog="app")
p.add_argument("--port", type=int, default=8765)
serve(p.parse_args().port)
