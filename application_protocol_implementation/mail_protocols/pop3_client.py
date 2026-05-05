import socket
import ssl
import os
import argparse

MAILBOX_DIR = os.path.join(os.path.dirname(__file__), "mailbox")

def send_line(sock, line):
    print(f"c->s {line}")
    sock.sendall((line + "\r\n").encode())

def recv_line(sock):
    buf = b""
    while True:
        ch = sock.recv(1)
        if not ch:
            raise ConnectionError("server closed")
        buf += ch
        if buf.endswith(b"\n"):
            line = buf.rstrip(b"\r\n").decode(errors="replace")
            print(f"s->c {line}")
            return line

def recv_ok(sock):
    # pop3 positive responses start with +OK
    line = recv_line(sock)
    if not line.startswith("+OK"):
        raise RuntimeError(f"server error: {line}")
    return line

def recv_multiline(sock):
    # pop3 multi-line responses end with a line containing only "."
    # lines starting with ".." are dot-unstuffed to "."
    lines = []
    while True:
        line = recv_line(sock)
        if line == ".":
            break
        lines.append(line[1:] if line.startswith("..") else line)
    return lines

def pop3_session(host, port, username, password, use_ssl, fetch):
    print(f"\nconnecting to {host}:{port}...")

    raw_sock = socket.create_connection((host, port))
    if use_ssl:
        sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=host)
    else:
        sock = raw_sock

    with sock:
        recv_ok(sock)                           # server greeting

        send_line(sock, f"USER {username}")
        recv_ok(sock)

        send_line(sock, f"PASS {password}")
        recv_ok(sock)

        # LIST returns one line per message: "<num> <size>"
        send_line(sock, "LIST")
        recv_ok(sock)
        entries = recv_multiline(sock)

        if not entries:
            print("mailbox is empty")
        else:
            for entry in entries:
                print(f"  msg {entry}")

        if fetch and entries:
            os.makedirs(MAILBOX_DIR, exist_ok=True)
            for entry in entries:
                msg_num = entry.split()[0]
                print(f"\n  fetching message {msg_num}...")
                send_line(sock, f"RETR {msg_num}")
                recv_ok(sock)
                msg_lines = recv_multiline(sock)
                path = os.path.join(MAILBOX_DIR, f"pop3_msg_{msg_num}.eml")
                with open(path, "w") as f:
                    f.write("\r\n".join(msg_lines) + "\r\n")
                print(f"  saved to {path}")

        send_line(sock, "QUIT")
        recv_line(sock)

    print("\ndone.")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="simple pop3 client")
    p.add_argument("--host",   required=True)
    p.add_argument("--port",   required=True, type=int)
    p.add_argument("--user",   required=True)
    p.add_argument("--pass",   required=True, dest="password")
    p.add_argument("--no-ssl", action="store_true", help="connect without tls")
    p.add_argument("--fetch",  action="store_true", help="download messages to ./mailbox/")
    args = p.parse_args()
    pop3_session(args.host, args.port, args.user, args.password, not args.no_ssl, args.fetch)
