import socket
import ssl
import os
import argparse

MAILBOX_DIR = os.path.join(os.path.dirname(__file__), "mailbox")


def _send(sock: socket.socket, line: str) -> None:
    print(f"c->s {line}")
    sock.sendall((line + "\r\n").encode("utf-8"))

def _read(sock: socket.socket) -> str:
    buf = b""
    while True:
        ch = sock.recv(1)
        if not ch:
            raise ConnectionError("server closed the connection")
        buf += ch
        if buf.endswith(b"\n"):
            line = buf.rstrip(b"\r\n").decode("utf-8", errors="replace")
            print(f"s->c {line}")
            return line
        if len(buf) > 1000:
            raise RuntimeError("server sent an oversized response line")

def _read_ok(sock: socket.socket) -> str:
    line = _read(sock)
    if not line.startswith("+OK"):
        raise RuntimeError(f"server error: {line}")
    return line

def _read_multiline(sock: socket.socket) -> list[str]:
    lines = []
    while True:
        line = _read(sock)
        if line == ".":
            break
        lines.append(line[1:] if line.startswith("..") else line)
    return lines

def pop3_session(
    host: str,
    port: int,
    username: str,
    password: str,
    use_ssl: bool,
    fetch: bool,
) -> None:
    print(f"\nconnecting to {host}:{port} ({'ssl' if use_ssl else 'plain'}) ...")

    raw_sock = socket.create_connection((host, port))

    if use_ssl:
        context = ssl.create_default_context()
        sock = context.wrap_socket(raw_sock, server_hostname=host)
    else:
        sock = raw_sock

    with sock:
        # greeting
        _read_ok(sock)

        # USER
        _send(sock, f"USER {username}")
        _read_ok(sock)

        # PASS
        _send(sock, f"PASS {password}")
        _read_ok(sock)

        # LIST
        _send(sock, "LIST")
        _read_ok(sock)
        entries = _read_multiline(sock)

        if not entries:
            print("mailbox is empty")
        else:
            for entry in entries:
                print(f"  msg {entry}")

        if fetch and entries:
            os.makedirs(MAILBOX_DIR, exist_ok=True)
            for entry in entries:
                msg_num = entry.split()[0]
                print(f"\n  fetching message {msg_num} ...")
                _send(sock, f"RETR {msg_num}")
                _read_ok(sock)
                msg_lines = _read_multiline(sock)
                path = os.path.join(MAILBOX_DIR, f"pop3_msg_{msg_num}.eml")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("\r\n".join(msg_lines) + "\r\n")
                print(f"  saved to {path}")

        # QUIT
        _send(sock, "QUIT")
        _read(sock)    # consume the 221/+OK bye line

    print("\ndone.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="pop3 client")
    p.add_argument("--host",    default="pop.gmail.com",  help="pop3 server hostname")
    p.add_argument("--port",    default=995, type=int,    help="pop3 server port (995=ssl, 110=plain)")
    p.add_argument("--user",    required=True,            help="mailbox username / email address")
    p.add_argument("--pass",    required=True,            help="password or app password", dest="password")
    p.add_argument("--no-ssl",  action="store_true",      help="connect without tls (e.g. via stunnel)")
    p.add_argument("--fetch",   action="store_true",      help="download all messages to ./mailbox/")
    args = p.parse_args()

    pop3_session(
        host=args.host,
        port=args.port,
        username=args.user,
        password=args.password,
        use_ssl=not args.no_ssl,
        fetch=args.fetch,
    )
