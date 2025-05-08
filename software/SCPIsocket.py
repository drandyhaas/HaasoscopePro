import socket

HOST = '127.0.0.1'  # Standard loopback interface address (localhost)
PORT = 32001        # Port to listen on (non-privileged ports are > 1023)

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind((HOST, PORT))
    s.listen()
    conn, addr = s.accept()
    with conn:
        print(f"Connected by {addr}")
        while True:
            data = conn.recv(1024)
            if not data: break
            print(data)
            if data==b'*IDN?\n':
                conn.sendall(b"DrAndyHaas Electronics,HaasoscopePro,v1.0,v26,\n")
            if data==b'RATES?\n':
                conn.sendall(b"1000000,2000000,\n")
            if data==b'DEPTHS?\n':
                conn.sendall(b"400,800,2000,8000,40000,\n")
            if data == b'START\n':
                print("Run")
            if data == b'STOP\n':
                print("Stop")
            if data == b'SINGLE\n':
                print("Single")
            if data == b'FORCE\n':
                print("Force")
            if data == b'K':
                print("Get event")
