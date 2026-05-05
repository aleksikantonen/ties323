import socket
import sys
import struct
import os

FILES_DIR = os.path.join(os.path.dirname(__file__), "files")

# packets: RRQ (read request), WRQ (write request), DATA, ACK, ERROR
OP_RRQ   = 1
OP_WRQ   = 2
OP_DATA  = 3
OP_ACK   = 4
OP_ERROR = 5

BLOCK_SIZE = 512
TIMEOUT = 5

def build_rrq(filename, mode="octet"):
    # RRQ packet: opcode(2) | filename | 0x00 | mode | 0x00
    return struct.pack("!H", OP_RRQ) + filename.encode() + b"\x00" + mode.encode() + b"\x00"

def build_wrq(filename, mode="octet"):
    # WRQ packet: same structure as RRQ but with opcode 2
    return struct.pack("!H", OP_WRQ) + filename.encode() + b"\x00" + mode.encode() + b"\x00"

def build_ack(block_num):
    # ACK packet: opcode(2) | block_number(2)
    return struct.pack("!HH", OP_ACK, block_num)

def build_data(block_num, data):
    # DATA packet: opcode(2) | block_number(2) | data (up to 512 bytes)
    return struct.pack("!HH", OP_DATA, block_num) + data

def parse_packet(packet):
    # read the opcode from the first 2 bytes and unpack the rest accordingly
    opcode = struct.unpack("!H", packet[:2])[0]
    if opcode == OP_DATA:
        block_num = struct.unpack("!H", packet[2:4])[0]
        data = packet[4:]
        return opcode, block_num, data
    elif opcode == OP_ACK:
        block_num = struct.unpack("!H", packet[2:4])[0]
        return opcode, block_num
    elif opcode == OP_ERROR:
        error_code = struct.unpack("!H", packet[2:4])[0]
        error_msg = packet[4:packet.index(b"\x00", 4)].decode()
        return opcode, error_code, error_msg
    return (opcode,)

def read_file(host, port, remote_filename, local_filename):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIMEOUT)

    # send RRQ
    rrq = build_rrq(remote_filename)
    sock.sendto(rrq, (host, port))

    with open(local_filename, "wb") as f:
        while True:
            # server replies from a new port, and becomes our transfer address
            packet, addr = sock.recvfrom(BLOCK_SIZE + 4)
            opcode, *rest = parse_packet(packet)

            if opcode == OP_ERROR:
                print(f"error: {rest[1]}")
                sock.close()
                return

            block_num, block_data = rest
            f.write(block_data)

            # ack the data block
            sock.sendto(build_ack(block_num), addr)

            # a block smaller than 512 bytes means this was the last one
            if len(block_data) < BLOCK_SIZE:
                break

    sock.close()
    print(f"downloaded {remote_filename} -> {local_filename}")

def write_file(host, port, local_filename, remote_filename):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIMEOUT)

    # read the file before sending WRQ so the server cannot truncate it first
    with open(local_filename, "rb") as f:
        file_data = f.read()

    # send WRQ
    wrq = build_wrq(remote_filename)
    sock.sendto(wrq, (host, port))

    # server replies with ACK 0 to confirm it is ready to receive
    packet, addr = sock.recvfrom(BLOCK_SIZE + 4)
    opcode, *rest = parse_packet(packet)

    if opcode == OP_ERROR:
        print(f"error: {rest[1]}")
        sock.close()
        return

    if opcode != OP_ACK or rest[0] != 0:
        print("unexpected response to WRQ")
        sock.close()
        return

    offset = 0
    block_num = 1
    while True:
        block_data = file_data[offset:offset + BLOCK_SIZE]
        offset += BLOCK_SIZE

        # send data block and wait for ack
        sock.sendto(build_data(block_num, block_data), addr)
        packet, addr = sock.recvfrom(BLOCK_SIZE + 4)
        opcode, *rest = parse_packet(packet)

        if opcode == OP_ERROR:
            print(f"error: {rest[1]}")
            sock.close()
            return

        # last block signals end of file
        if len(block_data) < BLOCK_SIZE:
            break

        block_num += 1

    sock.close()
    print(f"uploaded {local_filename} -> {remote_filename}")

def main():
    if len(sys.argv) < 5:
        print("usage:")
        print("python tftp_client.py <host> <port> get <remote_file> [local_file]")
        print("python tftp_client.py <host> <port> put <local_file> [remote_file]")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2])
    command = sys.argv[3].lower()

    if command == "get":
        remote_file = sys.argv[4]
        local_file = sys.argv[5] if len(sys.argv) > 5 else os.path.join(FILES_DIR, os.path.basename(remote_file))
        read_file(host, port, remote_file, local_file)
    elif command == "put":
        local_file = sys.argv[4]
        remote_file = sys.argv[5] if len(sys.argv) > 5 else os.path.basename(local_file)
        write_file(host, port, local_file, remote_file)
    else:
        print("unknown command. use 'get' or 'put'.")
        sys.exit(1)

if __name__ == "__main__":
    main()
