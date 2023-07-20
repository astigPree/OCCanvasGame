import socket
import json
import pickle
import threading
import typing as tp
import sys
import time
import uuid

ADDR = "localhost"
PORT = 45678

SHUTDOWN_SERVER = False

HEADER_SIZE = 53  # The size of header when using pickle , format ; '7:567' = code:pickle_size
SOCKET_ID_SIZE = 53  # The size of the size of socket_id , format ; '9a1c6' = str(uuid.uuid4())[:5]


def create_socket() -> tp.Union[socket.socket, None] :
    try :
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((ADDR, PORT))
    except socket.error :
        return None
    return server


def received_data(client: socket.socket, packet: int) -> tp.Union[bytes, None] :
    try :
        data: bytes = client.recv(packet)
    except socket.error :
        return None
    return data


def send_data(client: socket.socket, data: bytes) -> bool :
    try :
        client.sendall(data)
    except socket.error :
        return False
    return True


class CustomSocket :
    __connection: socket.socket = None

    def setSocket(self, connection: socket.socket) :
        self.__connection = connection

    def received(self) -> tp.Union[None, tp.Dict] :
        header: bytes = received_data(self.__connection, HEADER_SIZE)  # Received ; 'code:body_size'
        if not header : return None
        header: str = pickle.loads(header)
        code, bode_size = header.split(":")
        body: bytes = received_data(self.__connection, int(bode_size))  # Received ; '(int, int, int)'
        if not body : return None
        return {int(code) : pickle.loads(body)}

    def send(self, code: int, data: tuple[int, int, int]) -> bool :
        data = pickle.dumps(data)
        body_size = sys.getsizeof(data)
        if not send_data(self.__connection, pickle.dumps(f"{code}:{body_size}")) :  # Sent ; 'code:body_size'
            return False
        if not send_data(self.__connection, data) :  # Sent ; '(int, int, int)'
            return False
        return True


class PlayerSockets :
    recv = CustomSocket()
    send = CustomSocket()

    send_items: list[tuple[int, tuple[int, int, int]], ...] = []
    recv_items: list[dict[int, tuple[int, int, int]], ...] = []

    has_connection_error = False

    def threadSend(self) :
        global SHUTDOWN_SERVER
        while not self.has_connection_error and SHUTDOWN_SERVER :
            if len(self.send_items) > 0 :
                data = self.send_items[0]
                if not self.send.send(data[0], data[1]) :
                    self.has_connection_error = True
                else :
                    del self.send_items[0]

    def threadRecv(self) :
        global SHUTDOWN_SERVER
        while not self.has_connection_error and SHUTDOWN_SERVER :
            data = self.recv.received()
            if not data :
                self.has_connection_error = True
            else :
                self.recv_items.append(data)

    def getFirstRecvItems(self) -> dict :
        return self.recv_items.pop(0)

    def putItemInSendItems(self, data: tuple[int, tuple[int, int, int]]) :
        self.send_items.append(data)

    def isCodeIsSent(self, code: int) -> bool :
        for item in self.send_items :
            if code == item[0] :
                return False
        return True

    def removeCodeIfExits(self,
                          code: int) -> bool :  # Return false if the code does not exit and if exist then delete it
        if not self.isCodeIsSent(code) :
            return False
        for n, item in self.send_items.copy() :
            if code == item[0] :
                del self.send_items[n]
                break
        return False

    def checkPlayerSocket(self) -> int :
        if self.has_connection_error :
            return 1
        return 0


class ServerTransaction :
    TOTAL_TILES_OF_BOARD = 800
    COOLDOWN = 20  # 20 seconds of cooldown
    filename = "player_board.json"
    __board: list[list[int, int, float], ...] = []  # course : int , color : int , time : float
    courses = (None, 'bshrm', 'bsc', 'bsbamfm', 'bsma', 'bscs', 'bseme', 'bsemm', 'bsemf', 'bsemss', 'bee')
    palettes = {
        'bshrm' : [], 'bsc' : [], 'bsbamfm' : [], 'bsma' : [], 'bscs' : [],
        'bseme' : [], 'bsemm' : [], 'bsemf' : [], 'bsemss' : [], 'bee' : []
    }

    pending_players: dict[str, socket.socket] = {}
    current_players: dict[str, PlayerSockets] = {}

    def loadBoardPastData(self) :
        with open(self.filename, 'r') as jf :
            self.__board = json.load(jf)
        print("[ / ] Done loading the board")

    def checkIfCurrentlyCooldown(self, index: int) -> bool :
        if 0 <= self.__board[index][2] :
            return False
        return True

    def getBoardTileData(self, index: int) :
        return self.__board[index].copy()

    def lessenTimeInTile(self, tile: int, cooldown: float) :
        if self.__board[tile][2] > -1 :
            self.__board[tile][2] -= cooldown

    def updateBoardTiles(self, tile: int, course: int, color: int) :
        self.__board[tile] = [course, color, self.COOLDOWN]

    def getBoardDataForSendingTileInformation(self, tile: int) -> tuple[
        int, pickle.dumps] :  # return of a size of bytes and bytes
        tile_info = self.getBoardTileData(tile)
        tile_info_to_bytes = pickle.dumps(
            (tile, tile_info[0], tile_info[1], tile_info[2]))  # tile number , tile course , tile color , tile cooldown
        tile_bytes_size = sys.getsizeof(tile_info_to_bytes)
        return tile_bytes_size, tile_info_to_bytes

    def createClassFor2SocketAndAddToCurrentPlayers(self, socket_id: str, send_socket: socket.socket,
                                                    recv_socket: socket.socket) :
        player_transact = PlayerSockets()
        player_transact.recv.setSocket(recv_socket)
        player_transact.send.setSocket(send_socket)
        self.current_players[socket_id] = player_transact

    def threadRemoveSocketIfNotTakenForASeconds(self, socket_id: str) :
        for counter in range(2) :
            time.sleep(1)
            if self.pending_players.get(socket_id) is not None and counter == 1 :
                break
        else :
            del self.pending_players[socket_id]

    def threadIdentifySocketBeforeAddingToCurrentPlayers(self, client: socket.socket) :
        # The First Socket is the RECEIVE SOCKET, next is SENDING SOCKET
        socket_id: bytes = received_data(client, SOCKET_ID_SIZE)
        if not socket_id : return
        socket_id: str = pickle.loads(socket_id)
        if socket_id not in self.pending_players :  # If First Time Entering Then Add To
            threading.Thread(target=self.threadRemoveSocketIfNotTakenForASeconds, args=(socket_id,)).start()
        else :
            recv_socket = self.pending_players[socket_id]
            del self.pending_players[socket_id]
            self.createClassFor2SocketAndAddToCurrentPlayers(socket_id=socket_id, send_socket=client,
                                                             recv_socket=recv_socket)
            self.threadRunTheThreadOfThePlayerClass(socket_id)  # Start the sending and receiving the player
            threading.Thread(target=self.threadHandleThePlayerTransaction , args=(socket_id, )).start()

    def threadRunTheThreadOfThePlayerClass(self, socket_id: str):
        threading.Thread(target=self.current_players[socket_id].threadRecv).start()
        threading.Thread(target=self.current_players[socket_id].threadSend).start()

    def threadHandleThePlayerTransaction(self, socket_id : str):
        """ This Where The Handling The Player Want To Happen In App """
        global SHUTDOWN_SERVER
        while True:

            if SHUTDOWN_SERVER: # Activity when the server want to close the server
                pass



if __name__ == "__main__" :
    d = str(uuid.uuid4())[:5]
    print(d)
    print(sys.getsizeof(pickle.dumps(d)))
