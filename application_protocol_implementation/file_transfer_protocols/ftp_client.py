import socket
import sys
import os

FILES_DIR = os.path.join(os.path.dirname(__file__), "files")


def recv_response(ctrl_sock):
    # ftp responses end when a line matches "NNN <text>\r\n"
    # multi-line responses use "NNN-<text>\r\n" for continuation lines
    response = b""
    while True:
        data = ctrl_sock.recv(4096)
        response += data
        # check if any complete line is the final response line
        for line in response.split(b"\r\n"):
            if len(line) >= 4 and line[:3].isdigit() and line[3:4] == b" ":
                return response.decode()

def send_command(ctrl_sock, command):
    # ftp commands are plain text terminated with \r\n
    ctrl_sock.sendall((command + "\r\n").encode())
    return recv_response(ctrl_sock)

def open_data_connection(ctrl_sock):
    # ask server to enter passive mode
    response = send_command(ctrl_sock, "EPSV")
    print(response.strip())
    if response.startswith("229"):
        # EPSV reply format
        start = response.index("|||")
        end = response.index("|", start + 3)
        port = int(response[start + 3:end])
        host = ctrl_sock.getpeername()[0]
    else:
        # fall back to PASV
        print("EPSV failed, trying PASV...")
        response = send_command(ctrl_sock, "PASV")
        print(response.strip())
        if not response.startswith("227"):
            print("could not enter passive mode")
            return None
        start = response.index("(")
        end = response.index(")")
        nums = response[start + 1:end].split(",")
        host = ".".join(nums[:4])
        # port is encoded as two bytes
        port = int(nums[4]) * 256 + int(nums[5])
    # open the data connection
    data_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    data_sock.connect((host, port))
    return data_sock

def recv_all_data(data_sock):
    # read until the server closes the data connection
    data = b""
    while True:
        chunk = data_sock.recv(4096)
        if not chunk:
            break
        data += chunk
    data_sock.close()
    return data

def main():
    if len(sys.argv) < 2:
        print("usage: python ftp_client.py <host> [port]")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 21

    # control connection, persistent TCP connection for sending commands
    ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ctrl_sock.connect((host, port))
    # server sends a greeting on connect
    response = recv_response(ctrl_sock)
    print(response.strip())

    print("\ncommands: USER <name>, PASS <password>, LIST, RETR <file>, QUIT\n")

    while True:
        try:
            user_input = input("ftp> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        cmd = user_input.upper().split()[0]

        if cmd == "QUIT":
            response = send_command(ctrl_sock, "QUIT")
            print(response.strip())
            break
        elif cmd == "LIST":
            # LIST uses a separate data connection for the directory listing
            data_sock = open_data_connection(ctrl_sock)
            if data_sock is None:
                continue
            response = send_command(ctrl_sock, "LIST")
            print(response.strip())
            listing = recv_all_data(data_sock)
            print(listing.decode())
            # server sends a 226 transfer complete on the control connection
            response = recv_response(ctrl_sock)
            print(response.strip())
        elif cmd == "RETR":
            if len(user_input.split()) < 2:
                print("usage: RETR <filename>")
                continue
            filename = user_input.split(None, 1)[1]
            # RETR also uses a separate data connection for file content
            data_sock = open_data_connection(ctrl_sock)
            if data_sock is None:
                continue
            response = send_command(ctrl_sock, f"RETR {filename}")
            print(response.strip())
            if response.startswith("150") or response.startswith("125"):
                data = recv_all_data(data_sock)
                local_name = filename.split("/")[-1]
                local_path = os.path.join(FILES_DIR, local_name)
                with open(local_path, "wb") as f:
                    f.write(data)
                print(f"saved to {local_path} ({len(data)} bytes)")
                response = recv_response(ctrl_sock)
                print(response.strip())
            else:
                data_sock.close()
        else:
            response = send_command(ctrl_sock, user_input)
            print(response.strip())

    ctrl_sock.close()

if __name__ == "__main__":
    main()
