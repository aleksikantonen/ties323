"""
smtp + pop3 server

smtp state machine:
  WAIT_HELO   -> HELO              -> WAIT_MAIL
  WAIT_MAIL   -> MAIL FROM         -> WAIT_RCPT
  WAIT_RCPT   -> RCPT TO           -> DATA_READY
  DATA_READY  -> DATA              -> READING_DATA
  READING_DATA -> lone "." line    -> WAIT_MAIL  (message saved)
  any state   -> QUIT              -> connection closed

pop3 (single-user, no password check):
  greeting -> USER -> PASS -> LIST / RETR -> QUIT
  all .eml files in mailbox/ are served as the inbox.
"""

import socket
import threading
import os
import datetime

HOST = "127.0.0.1"
SMTP_PORT = 2525
POP3_PORT = 1100
MAILBOX_DIR = os.path.join(os.path.dirname(__file__), "mailbox")


def _read(conn: socket.socket) -> str | None:
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
            return buf.rstrip(b"\r\n").decode("utf-8", errors="replace")
        if len(buf) > 1000:  # rfc 5321 line-length limit
            return None


def _send(conn: socket.socket, line: str) -> None:
    print(f"s->c {line}")
    conn.sendall((line + "\r\n").encode("utf-8"))


def _extract_address(argument: str) -> str | None:
    if "<" in argument and ">" in argument:
        return argument[argument.index("<") + 1 : argument.index(">")].strip()
    return argument.strip() or None


def _save_message(sender: str, recipients: list[str], lines: list[str]) -> str:
    os.makedirs(MAILBOX_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = os.path.join(MAILBOX_DIR, f"msg_{stamp}.eml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"X-Envelope-From: {sender}\r\n")
        for r in recipients:
            fh.write(f"X-Envelope-To: {r}\r\n")
        fh.write("\r\n".join(lines) + "\r\n")
    return path


def handle_session(conn: socket.socket) -> None:
    state = "WAIT_HELO"
    sender = ""
    recipients: list[str] = []
    data: list[str] = []

    _send(conn, f"220 {socket.gethostname()} smtp server ready")

    try:
        while True:
            line = _read(conn)
            if line is None:
                break

            if state == "READING_DATA":
                if line == ".":  # end-of-message marker
                    path = _save_message(sender, recipients, data)
                    print(f"saved {path}")
                    sender, recipients, data = "", [], []
                    state = "WAIT_MAIL"
                    _send(conn, "250 Ok: message queued")
                else:
                    data.append(line)
                continue

            print(line)
            parts = line.split(" ", 1)
            verb = parts[0].upper()
            arg = parts[1] if len(parts) > 1 else ""

            if verb == "HELO":
                if not arg:
                    _send(conn, "501 Syntax: HELO hostname")
                else:
                    state = "WAIT_MAIL"
                    _send(conn, f"250 Hello {arg}")

            elif verb == "MAIL" and state == "WAIT_MAIL":
                addr_str = _extract_address(arg)
                if addr_str is None:
                    _send(conn, "501 Syntax: MAIL FROM:<address>")
                else:
                    sender = addr_str
                    state = "WAIT_RCPT"
                    _send(conn, "250 Ok")

            elif verb == "RCPT" and state in ("WAIT_RCPT", "DATA_READY"):
                addr_str = _extract_address(arg)
                if addr_str is None:
                    _send(conn, "501 Syntax: RCPT TO:<address>")
                else:
                    recipients.append(addr_str)
                    state = "DATA_READY"
                    _send(conn, "250 Ok")

            elif verb == "DATA" and state == "DATA_READY":
                state = "READING_DATA"
                _send(conn, "354 End data with <CR><LF>.<CR><LF>")

            elif verb == "QUIT":
                _send(conn, f"221 {socket.gethostname()} closing connection")
                break

            else:
                _send(conn, "503 Bad sequence of commands")
    finally:
        conn.close()
        print("server closed connection")


def handle_pop3_session(conn: socket.socket, addr: tuple) -> None:
    # snapshot of the inbox at session start
    os.makedirs(MAILBOX_DIR, exist_ok=True)
    messages = sorted(
        os.path.join(MAILBOX_DIR, f)
        for f in os.listdir(MAILBOX_DIR)
        if f.endswith(".eml")
    )

    print(f"[+] pop3 {addr}  ({len(messages)} messages)")
    _send(conn, "+OK simple pop3 server ready")

    try:
        while True:
            line = _read(conn)
            if line is None:
                break

            print(f"pop3 c->s {line}")
            parts = line.split(" ", 1)
            verb = parts[0].upper()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if verb == "USER":
                _send(conn, "+OK")

            elif verb == "PASS":
                # no password checking per task description
                _send(conn, f"+OK {len(messages)} messages")

            elif verb == "LIST":
                _send(conn, f"+OK {len(messages)} messages")
                for i, path in enumerate(messages, start=1):
                    conn.sendall(f"{i} {os.path.getsize(path)}\r\n".encode("utf-8"))
                conn.sendall(b".\r\n")

            elif verb == "RETR":
                try:
                    path = messages[int(arg) - 1]
                except (ValueError, IndexError):
                    _send(conn, "-ERR no such message")
                    continue
                _send(conn, "+OK message follows")
                with open(path, "r", encoding="utf-8") as fh:
                    for msg_line in fh:
                        msg_line = msg_line.rstrip("\r\n")
                        conn.sendall((msg_line + "\r\n").encode("utf-8"))
                conn.sendall(b".\r\n")

            elif verb == "QUIT":
                _send(conn, "+OK bye")
                break

            else:
                _send(conn, "-ERR unknown command")
    finally:
        conn.close()
        print(f"[-] pop3 {addr}")


def _run_pop3(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(5)
        print(f"pop3 server on {host}:{port}")
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=handle_pop3_session, args=(conn, addr), daemon=True).start()


def run_server(host: str = HOST, smtp_port: int = SMTP_PORT, pop3_port: int = POP3_PORT) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, smtp_port))
        srv.listen(5)
        print(f"smtp server on {host}:{smtp_port}  (mailbox: {MAILBOX_DIR})")
        # start pop3 in a background thread
        threading.Thread(target=_run_pop3, args=(host, pop3_port), daemon=True).start()
        print("press ctrl+c to stop\n")
        while True:
            try:
                conn, addr = srv.accept()
            except KeyboardInterrupt:
                print("\nshutting down...")
                break
            threading.Thread(target=handle_session, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    run_server()
