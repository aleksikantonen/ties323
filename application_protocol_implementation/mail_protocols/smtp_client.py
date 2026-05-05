import socket
import argparse
import datetime

HOST = "127.0.0.1"
PORT = 2525

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

def expect(sock, code):
    # smtp responses can be multi-line: continuation lines use NNN- instead of NNN<space>
    line = recv_line(sock)
    while len(line) >= 4 and line[3] == "-":
        line = recv_line(sock)
    if int(line[:3]) != code:
        raise RuntimeError(f"expected {code}, got: {line}")

def send_mail(host, port, sender, recipient, subject, body):
    date_str = datetime.datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

    print(f"\nconnecting to {host}:{port}...")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((host, port))

        expect(sock, 220)                       # server greeting

        send_line(sock, f"HELO {socket.gethostname()}")
        expect(sock, 250)

        send_line(sock, f"MAIL FROM:<{sender}>")
        expect(sock, 250)

        send_line(sock, f"RCPT TO:<{recipient}>")
        expect(sock, 250)

        send_line(sock, "DATA")
        expect(sock, 354)

        # send message headers, blank line, then body (rfc 5322)
        for line in [f"From: {sender}", f"To: {recipient}",
                     f"Subject: {subject}", f"Date: {date_str}", "", body]:
            # dot-stuffing: lines starting with "." must be escaped with an extra "."
            if line.startswith("."):
                line = "." + line
            print(f"c->s {line}")
            sock.sendall((line + "\r\n").encode())

        # end-of-data marker
        print("c->s .")
        sock.sendall(b".\r\n")
        expect(sock, 250)

        send_line(sock, "QUIT")
        recv_line(sock)

    print("\nmessage sent.")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="simple smtp client")
    p.add_argument("--host",    default=HOST)
    p.add_argument("--port",    default=PORT, type=int)
    p.add_argument("--from",    default="alice@example.com", dest="sender")
    p.add_argument("--to",      default="bob@example.com",   dest="recipient")
    p.add_argument("--subject", default="test message")
    p.add_argument("--body",    default="hello from the smtp client.")
    args = p.parse_args()
    send_mail(args.host, args.port, args.sender, args.recipient, args.subject, args.body)
