
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

SHUTDOWN_SERVER = False
DONE_RUNNING_SERVER = False

HEADER_SIZE = 40 # The size of header when using pickle , format ; '7:56767' = code:body_size
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
        data: bytes = client.recv(packet)
    except socket.error :
        return None
    if data is None:
        return None
    return data


def send_data(client: socket.socket, data: bytes , timing = 30) -> bool :
    try :
        time.sleep(1 / timing)
        client.sendall(data)
    except socket.error :
        return False
    return True


class CustomSocket:
    __connection: socket.socket = None
    done_activity = False

    def setSocket(self, connection: socket.socket) :
        self.__connection = connection

    def received(self) -> tp.Union[None, tp.Dict] :
        self.done_activity = False
        header: bytes = received_data(self.__connection, HEADER_SIZE)
        # Received ; 'code:body_size'
        if header is None or not header :
            self.done_activity = True
            return None
        # print(f"[!] Dumps Header : {header}")
        code, bode_size = header.decode().split(":")
        # print(f"[!] Loads Header : {header}")
        body: bytes = received_data(self.__connection, int(bode_size))  # Received ; '(int, int, int)'
        # print(f"[!] Dumps Body : {body}")
        if body is None and not body :
            self.done_activity = True
            return None

        try :
            body = json.loads(body.decode())
        except json.JSONDecodeError :
            self.done_activity = True
            return None

        self.done_activity = True
        return {int(code) : body}

    def send(self, code: int, data: tp.Any) -> bool :
        self.done_activity = False
        data = json.dumps(data).encode()
        body_size = sys.getsizeof(data)
        # print(f"[!] Packet Size {code}:{body_size} = ", end='')
        # print(f"{sys.getsizeof(pickle.dumps(f'{code}:{body_size}'))}")
        # print(f"[!] Body Size : {body_size}")
        if not send_data(self.__connection, f"{code}:{body_size}".encode()) :  # Sent ; 'code:body_size'
            self.done_activity = True
            return False
        if not send_data(self.__connection, data) :  # Sent ; '(int, int, int)'
            self.done_activity = True
            return False
        self.done_activity = True
        return True

    def close(self) :
        self.__connection.shutdown()
        self.__connection.close()

# App Transactions Class ' for sending and receiving data from server '

class PlayerSockets :
    recv = CustomSocket()
    send = CustomSocket()

    send_items: list[tuple[int, tp.Any], ...] = []
    recv_items: list[dict[int, tp.Any], ...] = []

    pending_board_activities: list[tuple[int, tp.Any], ...]

    done_downloading = False
    has_connection_error = False
    close_transaction = False


    def closeAllProcess(self) :
        self.close_transaction = True
        self.recv_items.clear()
        self.send_items.clear()
        while not self.recv.done_activity or not self.send.done_activity :
            pass
        if not self.has_connection_error :
            self.recv.close()
            self.send.close()

    def connectToServer(self) -> bool :
        send_socket = create_socket()
        if not send_socket :
            return False

        un_id = str(uuid4())[:5]
        print(f"Client ID {un_id}")

        if not send_data(send_socket , pickle.dumps(un_id) ) :
            return False

        self.send.setSocket(send_socket)

        recv_socket = create_socket()
        if not recv_socket :
            return False

        if not send_data(recv_socket , pickle.dumps(un_id) ) :
            return False

        self.recv.setSocket(recv_socket)
        return True

    def threadBoardActivitiesUpdate(self) :
        while not self.has_connection_error and not self.close_transaction :
            if len(self.pending_board_activities) > 0 and self.done_downloading:
                self.send_items.append(self.pending_board_activities.pop(0))

    def threadSend(self) :
        while not self.has_connection_error and not self.close_transaction :
            if len(self.send_items) > 0 and not self.send.done_activity:
                data = self.send_items[0]
                if not self.send.send(data[0], data[1]) :
                    self.has_connection_error = True
                else :
                    self.send_items.remove(data)

    def threadRecv(self) :
        while not self.has_connection_error and not self.close_transaction :
            data = self.recv.received()
            if not data :
                self.has_connection_error = True
            else :
                self.recv_items.append(data)

    def threadCheckingForASeconds(self , seconds = 5 ):
        """ This was to check if the client still working """
        while not self.has_connection_error and not self.close_transaction and not SHUTDOWN_SERVER:
            for _ in range(seconds):
                for _ in range(60):
                    time.sleep(1/60)
                    if self.has_connection_error or self.close_transaction or SHUTDOWN_SERVER :
                        break
                if self.has_connection_error or self.close_transaction or SHUTDOWN_SERVER :
                    break
            else:
                if not self.recv_items :
                    self.putItemInSendItems(data= (10 , None) )

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



def testServer():

    client = PlayerSockets()
    close = False

    # Connecting
    if not client.connectToServer() :
        print("[!] Not connected to server")
        return
    else :
        print("[!] Connected to server")

    # Ready Threading
    threading.Thread(target=client.threadRecv).start()
    threading.Thread(target=client.threadSend).start()
    threading.Thread(target=client.threadCheckingForASeconds).start()
    print("[!] Run Threading")

    # Download The Board
    # client.putItemInSendItems(data=(1, True))
    #
    # # Get Information In The Server
    # client.putItemInSendItems( data=( 9 , True))
    #
    # # Change The Tiles In Board
    # client.putItemInSendItems( data=( 3 ,(10, 2 , 3)) )

    # Display If Any Occurrence Happen
    def displayReceived():
        while not close:
            data = client.getFirstRecvItems()
            if data:
                with open("datas.txt", "a") as file:
                    txt = f"{ClientID} = "
                    for k in data:
                        txt += f"{k} : "
                        try:
                            txt += f"{len(data[k])}"
                        except TypeError:
                            txt += str(data[k])
                    file.write(txt+"\n")

    threading.Thread(target=displayReceived).start()

    while True:
        code = input("\nCode : ")
        activity = input("Value : ")
        client.putItemInSendItems(data=(int(code), eval(activity) ))
        if client.has_connection_error:
            client.closeAllProcess()
            print("[!] Has an error !")


testServer()