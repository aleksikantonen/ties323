import socket
import argparse

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4000
DEFAULT_PASSWORD = "secret"


def send_line(sock, line):
    print(f"c->s {line}")
    sock.sendall((line + "\r\n").encode())

def recv_line(sock):
    buf = b""
    while True:
        ch = sock.recv(1)
        if not ch:
            raise ConnectionError("server closed connection")
        buf += ch
        if buf.endswith(b"\n"):
            line = buf.rstrip(b"\r\n").decode(errors="replace")
            print(f"s->c {line}")
            return line

def recv_multiline(sock):
    # collect lines until the bare terminator "."
    lines = []
    while True:
        line = recv_line(sock)
        if line == ".":
            break
        lines.append(line)
    return lines

def kvsp_session(host, port, password):
    print(f"\nconnecting to {host}:{port}...")
    state = "CONNECTED"

    with socket.create_connection((host, port)) as sock:
        greeting = recv_line(sock)
        if not greeting.startswith("+OK"):
            raise RuntimeError(f"unexpected greeting: {greeting}")

        # transition CONNECTED -> AUTHENTICATED
        send_line(sock, f"AUTH {password}")
        resp = recv_line(sock)
        if not resp.startswith("+OK"):
            raise RuntimeError("authentication failed")
        state = "READY"

        print()
        print("authenticated. commands: SET <key> <value> | GET <key> | DEL <key> | KEYS | BYE")
        print()

        while state == "READY":
            try:
                cmd = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                cmd = "BYE"

            if not cmd:
                continue

            verb = cmd.split()[0].upper()
            send_line(sock, cmd)

            if verb == "KEYS":
                header = recv_line(sock)
                if header.startswith("+OK"):
                    keys = recv_multiline(sock)
                    if keys:
                        for k in keys:
                            print(f"  {k}")
                    else:
                        print("  (empty)")
            elif verb == "BYE":
                recv_line(sock)
                # transition READY -> DISCONNECTED
                state = "DISCONNECTED"
            else:
                recv_line(sock)

    print("\ndisconnected.")
    

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="kvsp client - key-value store protocol")
    p.add_argument("--host",     default=DEFAULT_HOST)
    p.add_argument("--port",     default=DEFAULT_PORT, type=int)
    p.add_argument("--password", default=DEFAULT_PASSWORD)
    args = p.parse_args()
    kvsp_session(args.host, args.port, args.password)
