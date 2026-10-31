"""python -m parenting_agent.demo [--brain-env FILE]

Runs the public demo locally on http://127.0.0.1:8765. --brain-env reads only the brain key (BASETEN_API_KEY,
Muse Spark Open) from an env file and ignores every other line. Before anything starts, every variable that
could reach the house is removed from the environment. Settings come from PA_DEMO_* variables (settings.py).
"""
import argparse
import os
import sys

from . import settings as settings_mod


def main(argv=None):
    parser = argparse.ArgumentParser(description="parenting agent public demo")
    parser.add_argument("--brain-env", help="env file to read the brain key from, nothing else is read")
    parser.add_argument("--port", type=int)
    args = parser.parse_args(argv)
    removed = settings_mod.scrub_environment()
    if removed:
        print(f"removed {len(removed)} variables that could reach the house or hold secrets: {', '.join(removed)}", flush=True)
    if args.brain_env:
        settings_mod.read_brain_key(args.brain_env)
    if args.port:
        os.environ["PA_DEMO_PORT"] = str(args.port)
    settings = settings_mod.load()

    from .app import DemoApp
    from .server import serve
    app = DemoApp(settings)
    server = serve(app, settings)
    print(f"demo on http://{settings['host']}:{settings['port']} brain {settings['brain_name']} "
          f"({app.brain.destination}), cap ${settings['daily_usd_cap']:.2f} a day", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
