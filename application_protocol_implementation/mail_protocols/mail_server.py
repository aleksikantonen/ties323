import socket
import threading
import os
import datetime

HOST = "127.0.0.1"
SMTP_PORT = 2525
POP3_PORT = 1100
IMAP_PORT = 1430
MAILBOX_DIR = os.path.join(os.path.dirname(__file__), "mailbox")

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

def extract_address(arg):
    # pull address from MAIL FROM:<addr> or RCPT TO:<addr>
    if "<" in arg and ">" in arg:
        return arg[arg.index("<") + 1:arg.index(">")].strip()
    return arg.strip() or None

def save_message(sender, recipients, lines):
    os.makedirs(MAILBOX_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = os.path.join(MAILBOX_DIR, f"msg_{stamp}.eml")
    with open(path, "w") as f:
        f.write(f"X-Envelope-From: {sender}\r\n")
        for r in recipients:
            f.write(f"X-Envelope-To: {r}\r\n")
        f.write("\r\n".join(lines) + "\r\n")
    return path

def load_messages():
    os.makedirs(MAILBOX_DIR, exist_ok=True)
    return sorted(
        os.path.join(MAILBOX_DIR, f)
        for f in os.listdir(MAILBOX_DIR)
        if f.endswith(".eml")
    )

def handle_smtp_session(conn, addr):
    # smtp is a stateful protocol: commands must arrive in a specific order
    state = "WAIT_HELO"
    sender = ""
    recipients = []
    data = []

    send_line(conn, f"220 {socket.gethostname()} smtp server ready")

    try:
        while True:
            line = read_line(conn)
            if line is None:
                break

            # while in DATA state, collect lines until the end-of-data marker "."
            if state == "READING_DATA":
                if line == ".":
                    path = save_message(sender, recipients, data)
                    print(f"saved {path}")
                    sender, recipients, data = "", [], []
                    state = "WAIT_MAIL"
                    send_line(conn, "250 Ok: message queued")
                else:
                    data.append(line)
                continue

            print(f"c->s {line}")
            parts = line.split(" ", 1)
            verb = parts[0].upper()
            arg = parts[1] if len(parts) > 1 else ""

            if verb == "HELO":
                state = "WAIT_MAIL"
                send_line(conn, f"250 Hello {arg}")
            elif verb == "MAIL" and state == "WAIT_MAIL":
                addr_str = extract_address(arg)
                if addr_str is None:
                    send_line(conn, "501 Syntax: MAIL FROM:<address>")
                else:
                    sender = addr_str
                    state = "WAIT_RCPT"
                    send_line(conn, "250 Ok")
            elif verb == "RCPT" and state in ("WAIT_RCPT", "DATA_READY"):
                addr_str = extract_address(arg)
                if addr_str is None:
                    send_line(conn, "501 Syntax: RCPT TO:<address>")
                else:
                    recipients.append(addr_str)
                    state = "DATA_READY"
                    send_line(conn, "250 Ok")
            elif verb == "DATA" and state == "DATA_READY":
                state = "READING_DATA"
                send_line(conn, "354 End data with <CR><LF>.<CR><LF>")
            elif verb == "QUIT":
                send_line(conn, f"221 {socket.gethostname()} closing connection")
                break
            else:
                send_line(conn, "503 Bad sequence of commands")
    finally:
        conn.close()

def handle_pop3_session(conn, addr):
    messages = load_messages()
    print(f"pop3 connection from {addr} ({len(messages)} messages)")
    send_line(conn, "+OK simple pop3 server ready")

    try:
        while True:
            line = read_line(conn)
            if line is None:
                break

            print(f"c->s {line}")
            parts = line.split(" ", 1)
            verb = parts[0].upper()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if verb == "USER":
                send_line(conn, "+OK")
            elif verb == "PASS":
                send_line(conn, f"+OK {len(messages)} messages")
            elif verb == "LIST":
                send_line(conn, f"+OK {len(messages)} messages")
                for i, path in enumerate(messages, start=1):
                    conn.sendall(f"{i} {os.path.getsize(path)}\r\n".encode())
                conn.sendall(b".\r\n")
            elif verb == "RETR":
                try:
                    path = messages[int(arg) - 1]
                except (ValueError, IndexError):
                    send_line(conn, "-ERR no such message")
                    continue
                send_line(conn, "+OK message follows")
                with open(path, "r") as f:
                    for msg_line in f:
                        msg_line = msg_line.rstrip("\r\n")
                        # dot-stuffing for lines that start with "."
                        if msg_line.startswith("."):
                            msg_line = "." + msg_line
                        conn.sendall((msg_line + "\r\n").encode())
                conn.sendall(b".\r\n")
            elif verb == "QUIT":
                send_line(conn, "+OK bye")
                break
            else:
                send_line(conn, "-ERR unknown command")
    finally:
        conn.close()

def handle_imap_session(conn, addr):
    messages = load_messages()
    print(f"imap connection from {addr} ({len(messages)} messages)")
    send_line(conn, "* OK simple imap server ready")

    try:
        while True:
            line = read_line(conn)
            if line is None:
                break

            print(f"c->s {line}")
            parts = line.split(" ", 2)
            if len(parts) < 2:
                continue
            tag = parts[0]
            verb = parts[1].upper()
            arg = parts[2].strip() if len(parts) > 2 else ""

            if verb == "LOGIN":
                send_line(conn, f"{tag} OK LOGIN completed")
            elif verb == "SELECT":
                # EXISTS tells the client how many messages are in the mailbox
                send_line(conn, f"* {len(messages)} EXISTS")
                send_line(conn, f"{tag} OK SELECT completed")
            elif verb == "FETCH":
                try:
                    n = int(arg.split()[0])
                    path = messages[n - 1]
                except (ValueError, IndexError):
                    send_line(conn, f"{tag} NO no such message")
                    continue
                with open(path, "r") as f:
                    body = f.read()
                send_line(conn, f"* {n} FETCH (RFC822 {{{len(body.encode())}}}")
                conn.sendall(body.encode())
                conn.sendall(b")\r\n")
                send_line(conn, f"{tag} OK FETCH completed")
            elif verb == "LOGOUT":
                send_line(conn, "* BYE logging out")
                send_line(conn, f"{tag} OK LOGOUT completed")
                break
            else:
                send_line(conn, f"{tag} BAD unknown command")
    finally:
        conn.close()

def run_listener(host, port, handler):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(5)
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=handler, args=(conn, addr), daemon=True).start()

def run_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, SMTP_PORT))
        srv.listen(5)
        print(f"smtp on {HOST}:{SMTP_PORT}  pop3 on {HOST}:{POP3_PORT}  imap on {HOST}:{IMAP_PORT}")
        print(f"mailbox: {MAILBOX_DIR}")
        threading.Thread(target=run_listener, args=(HOST, POP3_PORT, handle_pop3_session), daemon=True).start()
        threading.Thread(target=run_listener, args=(HOST, IMAP_PORT, handle_imap_session), daemon=True).start()
        print("press ctrl+c to stop\n")
        while True:
            try:
                conn, addr = srv.accept()
            except KeyboardInterrupt:
                print("\nshutting down...")
                break
            threading.Thread(target=handle_smtp_session, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    run_server()
