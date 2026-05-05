import socket
import struct
import sys
import os

FILES_DIR = os.path.join(os.path.dirname(__file__), "files")

# tftp server listens on a well-known port (default 69)
OP_RRQ   = 1
OP_WRQ   = 2
OP_DATA  = 3
OP_ACK   = 4
OP_ERROR = 5

BLOCK_SIZE = 512
TIMEOUT = 5

def build_ack(block_num):
    return struct.pack("!HH", OP_ACK, block_num)

def build_data(block_num, data):
    return struct.pack("!HH", OP_DATA, block_num) + data

def build_error(error_code, error_msg):
    return struct.pack("!HH", OP_ERROR, error_code) + error_msg.encode() + b"\x00"

def parse_request(packet):
    # RRQ/WRQ: opcode(2) | filename | 0x00 | mode | 0x00
    opcode = struct.unpack("!H", packet[:2])[0]
    parts = packet[2:].split(b"\x00")
    filename = parts[0].decode()
    mode = parts[1].decode() if len(parts) > 1 else "octet"
    return opcode, filename, mode

def parse_packet(packet):
    opcode = struct.unpack("!H", packet[:2])[0]
    if opcode == OP_DATA:
        block_num = struct.unpack("!H", packet[2:4])[0]
        data = packet[4:]
        return opcode, block_num, data
    elif opcode == OP_ACK:
        block_num = struct.unpack("!H", packet[2:4])[0]
        return opcode, block_num
    return (opcode,)

def handle_rrq(sock, addr, filename):
    # only serve files from the files/ directory
    basename = os.path.basename(filename)
    filepath = os.path.join(FILES_DIR, basename)
    if not os.path.isfile(filepath):
        sock.sendto(build_error(1, "file not found"), addr)
        print(f"  file not found: {basename}")
        return

    print(f"  sending {basename} to {addr}")
    with open(filepath, "rb") as f:
        block_num = 1
        while True:
            block_data = f.read(BLOCK_SIZE)
            sock.sendto(build_data(block_num, block_data), addr)

            sock.settimeout(TIMEOUT)
            try:
                resp, _ = sock.recvfrom(BLOCK_SIZE + 4)
            except socket.timeout:
                print("  timeout waiting for ack")
                return

            # a block smaller than 512 bytes is the last one
            if len(block_data) < BLOCK_SIZE:
                break
            block_num += 1

    print("  transfer complete")

def handle_wrq(sock, addr, filename):
    # only write files to the files/ directory
    basename = os.path.basename(filename)
    filepath = os.path.join(FILES_DIR, basename)
    print(f"  receiving {basename} from {addr}")

    # ACK 0 tells the client we are ready to receive data
    sock.sendto(build_ack(0), addr)

    with open(filepath, "wb") as f:
        while True:
            sock.settimeout(TIMEOUT)
            try:
                packet, data_addr = sock.recvfrom(BLOCK_SIZE + 4)
            except socket.timeout:
                print("  timeout waiting for data")
                return

            opcode, block_num, block_data = parse_packet(packet)
            f.write(block_data)
            sock.sendto(build_ack(block_num), data_addr)

            if len(block_data) < BLOCK_SIZE:
                break

    print("  transfer complete")

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 6969

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", port))
    print(f"tftp server listening on port {port}")
    print(f"serving files from: {FILES_DIR}")

    while True:
        try:
            packet, addr = sock.recvfrom(BLOCK_SIZE + 4)
            opcode, filename, mode = parse_request(packet)

            if opcode == OP_RRQ:
                print(f"RRQ from {addr}: {filename}")
            elif opcode == OP_WRQ:
                print(f"WRQ from {addr}: {filename}")
            else:
                continue

            # each transfer uses its own socket bound to a random port
            transfer_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            transfer_sock.bind(("0.0.0.0", 0))

            if opcode == OP_RRQ:
                handle_rrq(transfer_sock, addr, filename)
            else:
                handle_wrq(transfer_sock, addr, filename)

            transfer_sock.close()

        except KeyboardInterrupt:
            print("\nshutting down")
            break

    sock.close()

if __name__ == "__main__":
    main()