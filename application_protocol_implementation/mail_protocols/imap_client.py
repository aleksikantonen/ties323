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

def send_command(sock, cmd, tag):
    # imap commands are prefixed with a unique tag so responses can be matched
    send_line(sock, f"{tag} {cmd}")
    lines = []
    while True:
        line = recv_line(sock)
        lines.append(line)
        # server echoes the tag back on the final response line
        if line.startswith(tag):
            if f"{tag} OK" not in line:
                raise RuntimeError(f"command failed: {line}")
            return lines

def imap_session(host, port, username, password, use_ssl, fetch):
    print(f"\nconnecting to {host}:{port}...")

    raw_sock = socket.create_connection((host, port))
    if use_ssl:
        sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=host)
    else:
        sock = raw_sock

    with sock:
        recv_line(sock)

        seq = 0

        seq += 1
        send_command(sock, f"LOGIN {username} {password}", f"A{seq:03d}")

        # SELECT tells us how many messages are in the mailbox
        seq += 1
        lines = send_command(sock, "SELECT INBOX", f"A{seq:03d}")

        count = 0
        for line in lines:
            if line.startswith("*") and "EXISTS" in line:
                count = int(line.split()[1])
                break

        print(f"\n{count} message(s) in INBOX")

        if fetch and count > 0:
            os.makedirs(MAILBOX_DIR, exist_ok=True)
            for n in range(1, count + 1):
                print(f"\n  fetching message {n}...")
                seq += 1
                lines = send_command(sock, f"FETCH {n} RFC822", f"A{seq:03d}")
                # response lines: [fetch header, ...body lines..., closing paren, tagged ok]
                body_lines = lines[1:-2]
                path = os.path.join(MAILBOX_DIR, f"imap_msg_{n}.eml")
                with open(path, "w") as f:
                    f.write("\r\n".join(body_lines) + "\r\n")
                print(f"  saved to {path}")

        seq += 1
        send_command(sock, "LOGOUT", f"A{seq:03d}")

    print("\ndone.")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="simple imap client")
    p.add_argument("--host",   required=True)
    p.add_argument("--port",   required=True, type=int)
    p.add_argument("--user",   required=True)
    p.add_argument("--pass",   required=True, dest="password")
    p.add_argument("--no-ssl", action="store_true", help="connect without tls")
    p.add_argument("--fetch",  action="store_true", help="download messages to ./mailbox/")
    args = p.parse_args()
    imap_session(args.host, args.port, args.user, args.password, not args.no_ssl, args.fetch)
