#!/usr/bin/env python3
import argparse
import json
import socket
import time
import urllib.request


PROTO_TABLES = [
    ("/proc/net/tcp", "TCP", False),
    ("/proc/net/tcp6", "TCP", True),
    ("/proc/net/udp", "UDP", False),
    ("/proc/net/udp6", "UDP", True),
]


def proc_ipv4(hex_ip):
    raw = int(hex_ip, 16).to_bytes(4, "little")
    return socket.inet_ntop(socket.AF_INET, raw)


def proc_ipv6(hex_ip):
    raw = bytes.fromhex(hex_ip)
    fixed = b"".join(raw[i:i + 4][::-1] for i in range(0, 16, 4))
    return socket.inet_ntop(socket.AF_INET6, fixed)


def split_endpoint(value, ipv6):
    ip_hex, port_hex = value.split(":", 1)
    ip = proc_ipv6(ip_hex) if ipv6 else proc_ipv4(ip_hex)
    return ip, int(port_hex, 16)


def state_name(state_hex, proto):
    if proto == "UDP":
        return "EST"
    if state_hex == "01":
        return "EST"
    if state_hex == "02":
        return "SYN-SENT"
    if state_hex in {"06", "07", "08", "09"}:
        return "FIN-WAIT"
    if state_hex in {"07", "0A"}:
        return "CLOSED"
    return "NEW"


def read_table(path, proto, ipv6, host):
    flows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            next(f, None)
            for line in f:
                parts = line.split()
                if len(parts) < 10:
                    continue
                src_ip, src_port = split_endpoint(parts[1], ipv6)
                dst_ip, dst_port = split_endpoint(parts[2], ipv6)
                if dst_ip in {"0.0.0.0", "::"} and dst_port == 0:
                    continue
                flows.append({
                    "host": host,
                    "src_ip": src_ip,
                    "src_port": src_port,
                    "dst_ip": dst_ip,
                    "dst_port": dst_port,
                    "protocol": proto,
                    "packets": 1,
                    "bytes": 0,
                    "process": "",
                    "state": state_name(parts[3], proto),
                })
    except FileNotFoundError:
        pass
    return flows


def collect(host):
    flows = []
    for path, proto, ipv6 in PROTO_TABLES:
        flows.extend(read_table(path, proto, ipv6, host))
    return flows


def post(server, host, flows):
    body = json.dumps({"host": host, "flows": flows}).encode("utf-8")
    req = urllib.request.Request(
        server.rstrip("/") + "/ingest",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read().decode("utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(description="PacketLens remote flow agent")
    parser.add_argument("--server", required=True, help="PacketLens API base URL, e.g. http://10.0.0.5:8765")
    parser.add_argument("--host", default=socket.gethostname(), help="Host label shown in PacketLens")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between reports")
    args = parser.parse_args()

    while True:
        flows = collect(args.host)
        try:
            post(args.server, args.host, flows)
            print(f"sent {len(flows)} flows to {args.server}", flush=True)
        except Exception as exc:
            print(f"send failed: {exc}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
