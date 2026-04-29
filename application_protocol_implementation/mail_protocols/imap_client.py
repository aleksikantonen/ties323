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
        if len(buf) > 8192:
            raise RuntimeError("server sent an oversized response line")


def _command(sock: socket.socket, cmd: str, counter: list) -> list[str]:
    counter[0] += 1
    tag = f"A{counter[0]:03d}"
    _send(sock, f"{tag} {cmd}")
    lines = []
    while True:
        line = _read(sock)
        lines.append(line)
        if line.startswith(tag):
            if f"{tag} OK" not in line:
                raise RuntimeError(f"command failed: {line}")
            return lines


def imap_session(
    host: str,
    port: int,
    username: str,
    password: str,
    use_ssl: bool,
    fetch: bool,
) -> None:
    print(f"\nconnecting to {host}:{port}...")

    raw_sock = socket.create_connection((host, port))

    if use_ssl:
        context = ssl.create_default_context()
        sock = context.wrap_socket(raw_sock, server_hostname=host)
    else:
        sock = raw_sock

    with sock:
        # greeting
        _read(sock)

        counter = [0]

        # LOGIN
        _command(sock, f"LOGIN {username} {password}", counter)

        # SELECT INBOX
        lines = _command(sock, "SELECT INBOX", counter)

        # find message count from "* N EXISTS"
        count = 0
        for line in lines:
            if line.startswith("*") and "EXISTS" in line:
                count = int(line.split()[1])
                break

        print(f"\n{count} message(s) in INBOX")

        if count == 0:
            _command(sock, "LOGOUT", counter)
            print("\ndone.")
            return

        if fetch:
            os.makedirs(MAILBOX_DIR, exist_ok=True)
            for n in range(1, count + 1):
                print(f"\n  fetching message {n} ...")
                lines = _command(sock, f"FETCH {n} RFC822", counter)
                body_lines = lines[1:-2]
                path = os.path.join(MAILBOX_DIR, f"imap_msg_{n}.eml")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("\r\n".join(body_lines) + "\r\n")
                print(f"  saved to {path}")

        # LOGOUT
        _command(sock, "LOGOUT", counter)

    print("\ndone.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="imap client")
    p.add_argument("--host",   required=True,           help="imap server hostname")
    p.add_argument("--port",   required=True, type=int, help="imap server port")
    p.add_argument("--user",   required=True,           help="username / email address")
    p.add_argument("--pass",   required=True,           help="password or app password", dest="password")
    p.add_argument("--no-ssl", action="store_true",     help="connect without tls")
    p.add_argument("--fetch",  action="store_true",     help="download all messages to ./mailbox/")
    args = p.parse_args()

    imap_session(
        host=args.host,
        port=args.port,
        username=args.user,
        password=args.password,
        use_ssl=not args.no_ssl,
        fetch=args.fetch,
    )
