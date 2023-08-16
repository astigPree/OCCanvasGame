
import os.path
import socket
import json
import pickle
import threading
import typing as tp
import sys
from uuid import uuid4
import time
import copy


ADDR = "localhost"
PORT = 45678

STOP_FUNCTIONS_RUNNING = False

HEADER_SIZE = 40 # The size of header when using string bytes , format ; '7:56767' = code:body_size
SOCKET_ID_SIZE = 53  # The size of the size of socket_id , format ; '9a1c6' = str(uuid.uuid4())[:5]

ClientID = 'Client 1'


def create_socket() -> tp.Union[socket.socket, None] :
    try :
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.connect((ADDR, PORT))
    except socket.error :
        return None
    return server


def received_data(client: socket.socket, packet: int , timing = 30) -> tp.Union[bytes, None] :
    try :
        time.sleep(1 / timing)
        while True:
            try:
                data: bytes = client.recv(packet)
            except BlockingIOError:
                if STOP_FUNCTIONS_RUNNING:
                    return None
            else:
                return data
    except socket.error :
        return None


def send_data(client: socket.socket, data: bytes , timing = 30) -> bool :
    try :
        time.sleep(1 / timing)
        client.sendall(data)
    except socket.error :
        return False
    return True


class CustomSocket:
    __connection: tp.Union[ socket.socket , None] = None

    def setSocket(self, connection: socket.socket) :
        self.__connection = connection

    def received(self) -> tp.Union[None, tp.Dict] :
        header: bytes = received_data(self.__connection, HEADER_SIZE)
        # Received ; 'code:body_size'
        if header is None or not header :
            return None
        code, bode_size = header.decode().split(":")
        body: bytes = received_data(self.__connection, int(bode_size))  # Received ; '(int, int, int)'
        if body is None and not body :
            return None

        try :
            body = json.loads(body.decode())
        except json.JSONDecodeError :
            return None

        return {int(code) : body}

    def send(self, code: int, data: tp.Any) -> bool :
        data = json.dumps(data).encode()
        body_size = sys.getsizeof(data)
        if not send_data(self.__connection, f"{code}:{body_size}".encode()) :  # Sent ; 'code:body_size'
            return False
        if not send_data(self.__connection, data) :  # Sent ; '(int, int, int)'
            return False
        return True

    def close(self) :
        self.__connection.shutdown(socket.SHUT_RDWR)
        self.__connection.close()
        self.__connection = None

# App Transactions Class ' for sending and receiving data from server '

class PlayerSockets :
    recv = CustomSocket()
    send = CustomSocket()

    send_items: list[tuple[int, tp.Any], ...] = []
    recv_items: list[dict[int, tp.Any], ...] = []

    done_downloading = False
    has_connection_error = False
    close_transaction = False

    def closeAllProcess(self) :
        global STOP_FUNCTIONS_RUNNING
        STOP_FUNCTIONS_RUNNING = True
        self.close_transaction = True
        self.recv_items.clear()
        self.send_items.clear()
        self.recv.close()
        self.send.close()

    def connectToServer(self) -> bool :
        global STOP_FUNCTIONS_RUNNING
        STOP_FUNCTIONS_RUNNING = False

        send_socket = create_socket()
        if not send_socket :
            return False

        un_id = str(uuid4())[:5]

        if not send_data(send_socket , pickle.dumps(un_id) ) :
            send_socket.close()
            return False

        recv_socket = create_socket()
        if not recv_socket :
            send_socket.close()
            return False

        if not send_data(recv_socket , pickle.dumps(un_id) ) :
            send_socket.close()
            recv_socket.close()
            return False

        recv_socket.setblocking(False)
        self.send.setSocket(send_socket)
        self.recv.setSocket(recv_socket)
        return True

    def threadSend(self) :
        global STOP_FUNCTIONS_RUNNING
        while not self.close_transaction :
            if len(self.send_items) > 0 and not self.has_connection_error:
                data = self.send_items[0]
                if not self.send.send(data[0], data[1]) :
                    STOP_FUNCTIONS_RUNNING = True
                    self.has_connection_error = True
                else :
                    self.send_items.remove(data)

    def threadRecv(self) :
        while not self.close_transaction :
            if not self.has_connection_error:
                data = self.recv.received()
                if not data :
                    self.has_connection_error = True
                else :
                    self.recv_items.append(data)

    def checkIfPlayerWantToClose(self) :  # Return True if the player want to close the game
        for item in self.send_items :
            for key in item :
                if key == 0 :
                    return True
        return False

    def getFirstRecvItems(self) -> tp.Union[ dict, None ] :
        if self.recv_items:
            return self.recv_items.pop(0)
        return None

    def putTilesInfoInBoardActivities(self, data: tuple[int, tp.Any]) :  # used only in tiles activty
        self.pending_board_activities.append(data)

    def putItemInSendItems(self, data: tuple[int, tp.Any]) :  # format; data = ( code , object )
        # priority = ( close : 0 ) -> ( rejection : 4 ) -> ( information : 8 ) -> ( success : 7 )
        if data[0] == 0:
            self.send_items.insert(0, data)
        elif not self.isCodeIsSent(0) and data[0] == 4 :
            self.send_items.insert(0, data)
        elif not self.isCodeIsSent(0) and not self.isCodeIsSent(4) and data[0] == 8 :
            self.send_items.insert(0, data)
        elif not self.isCodeIsSent(0) and not self.isCodeIsSent(4) and not self.isCodeIsSent(8) and data[0] == 7 :
            self.send_items.insert(0, data)
        else :
            self.send_items.append(data)

    def isCodeIsSent(self, code: int) -> bool :
        for item in self.send_items:
            if code == item[0] :
                return False
        return True

    def removeCodeIfExits(self, code: int) -> bool :
        # Return false if the code does not exit and if exist then delete it
        if not self.isCodeIsSent(code) :
            return False
        for n, item in self.send_items.copy() :
            if code == item[0] :
                del self.send_items[n]
                return True
        return False

    def checkPlayerSocket(self) -> int :
        if self.has_connection_error :
            return 1
        return 0



if __name__ == "__main__":
    client = PlayerSockets()
    client.connectToServer()
    threading.Thread(target=client.threadSend).start()
    threading.Thread(target=client.threadRecv).start()

    while True:
        act = input("\nActivity : ")
        if len(act) < 2:
            if act == "1":
                client.closeAllProcess()
            else:
                print(f"Connection Error : {client.has_connection_error}")
                print(f"Done Downloading : {client.done_downloading}")
                print(f"Close Transaction : {client.close_transaction}")
                print("Received Datas : ")
                for data in client.recv_items:
                    print(f"  Data : {data}")
                client.recv_items.clear()
        else :
            act = eval(act)
            client.putItemInSendItems(act)
            print(f"Sending Data : {act}")




