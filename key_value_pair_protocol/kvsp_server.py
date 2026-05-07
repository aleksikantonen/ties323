import socket
import threading
import argparse

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4000
DEFAULT_PASSWORD = "secret"

# shared in-memory key-value store and a lock for concurrent access
store = {}
store_lock = threading.Lock()


def read_line(conn):
    buf = b""
    while True:
        try:
            ch = conn.recv(1)
        except OSError:
            return None
        if not ch:
            return None
        buf += ch
        if buf.endswith(b"\n"):
            return buf.rstrip(b"\r\n").decode(errors="replace")

def send_line(conn, line):
    print(f"s->c {line}")
    conn.sendall((line + "\r\n").encode())

def handle_session(conn, addr, password):
    print(f"connection from {addr}")
    # state machine starts in WAIT_AUTH,
    # transitions to READY after correct AUTH
    state = "WAIT_AUTH"
    send_line(conn, "+OK KVSP/1.0 server ready")

    try:
        while True:
            line = read_line(conn)
            if line is None:
                break

            print(f"c->s {line}")
            # split into verb + up to two args; SET <key> <value> keeps spaces in value
            parts = line.split(" ", 2)
            verb = parts[0].upper()
            args = parts[1:] if len(parts) > 1 else []

            if verb == "AUTH":
                if state == "READY":
                    send_line(conn, "-ERR already authenticated")
                elif not args:
                    send_line(conn, "-ERR syntax: AUTH <password>")
                elif args[0] == password:
                    state = "READY"
                    send_line(conn, "+OK authenticated")
                else:
                    send_line(conn, "-ERR wrong password")

            elif verb == "SET":
                if state != "READY":
                    send_line(conn, "-ERR not authenticated")
                elif len(args) < 2:
                    send_line(conn, "-ERR syntax: SET <key> <value>")
                else:
                    with store_lock:
                        store[args[0]] = args[1]
                    send_line(conn, "+OK stored")

            elif verb == "GET":
                if state != "READY":
                    send_line(conn, "-ERR not authenticated")
                elif not args:
                    send_line(conn, "-ERR syntax: GET <key>")
                else:
                    with store_lock:
                        val = store.get(args[0])
                    if val is None:
                        send_line(conn, "-ERR key not found")
                    else:
                        send_line(conn, f"+VALUE {val}")

            elif verb == "DEL":
                if state != "READY":
                    send_line(conn, "-ERR not authenticated")
                elif not args:
                    send_line(conn, "-ERR syntax: DEL <key>")
                else:
                    with store_lock:
                        removed = store.pop(args[0], None)
                    if removed is None:
                        send_line(conn, "-ERR key not found")
                    else:
                        send_line(conn, "+OK deleted")

            elif verb == "KEYS":
                if state != "READY":
                    send_line(conn, "-ERR not authenticated")
                else:
                    with store_lock:
                        keys = list(store.keys())
                    send_line(conn, f"+OK {len(keys)} keys")
                    for k in keys:
                        send_line(conn, k)
                    send_line(conn, ".")

            elif verb == "BYE":
                send_line(conn, "+OK goodbye")
                break

            else:
                send_line(conn, "-ERR unknown command")

    finally:
        conn.close()
        print(f"connection closed {addr}")

def main():
    p = argparse.ArgumentParser(description="kvsp server - key-value store protocol")
    p.add_argument("--host",     default=DEFAULT_HOST)
    p.add_argument("--port",     default=DEFAULT_PORT, type=int)
    p.add_argument("--password", default=DEFAULT_PASSWORD)
    args = p.parse_args()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((args.host, args.port))
        srv.listen(5)
        print(f"kvsp server listening on {args.host}:{args.port}")
        while True:
            conn, addr = srv.accept()
            threading.Thread(
                target=handle_session,
                args=(conn, addr, args.password),
                daemon=True
            ).start()


if __name__ == "__main__":
    main()
