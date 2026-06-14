"""Simple CLI entrypoints for the PadelAnalysis workspace."""
import argparse
import os
import signal
import sys
from padel_analysis.mcp_client import MCPClient


def main():
    parser = argparse.ArgumentParser(prog="padel")
    sub = parser.add_subparsers(dest="cmd")

    sp_start = sub.add_parser("start-proxy", help="Start the mcp-remote proxy")
    sp_start.add_argument("--key", help="RapidAPI key (overrides env)")

    sp_stop = sub.add_parser("stop-proxy", help="Stop the proxy (if running)")

    args = parser.parse_args()

    if args.cmd == "start-proxy":
        api_key = args.key or os.environ.get("RAPIDAPI_KEY")
        client = MCPClient(api_key=api_key)
        try:
            proc = client.start_proxy(capture_output=False)
            print(f"Started proxy (pid={proc.pid}). Press Ctrl+C to stop.")
            signal.pause()
        except KeyboardInterrupt:
            client.stop_proxy()
            print("Stopped proxy")
        except Exception as e:
            print("Error:", e)
            sys.exit(1)

    elif args.cmd == "stop-proxy":
        print("If you launched a proxy via this script, use Ctrl+C to stop it.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
