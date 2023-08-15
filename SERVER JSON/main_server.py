import os
import socket
import json
import pickle
import threading
import typing as tp
import sys
import time
from collections import Counter

ADDR = "localhost"
PORT = 45678

NUMBER_OF_CONNECTED = 400
SHUTDOWN_SERVER = False
DONE_RUNNING_SERVER = False

HEADER_SIZE = 40  # The size of header when using pickle , format ; '7:56755' = code:body_size
SOCKET_ID_SIZE = 53  # The size of the size of socket_id , format ; '9a1c6' = str(uuid.uuid4())[:5]

"""
    Sending Data:
        Priority:
            Close -> ( 0 , True )
            Success -> ( 7 , True )
            Rejection -> (4 , tile_time )
            Information -> ( 8 , ( active_players, most_active_course, most_used_color ) )
        Minor :
            Tiles -> ( 2 , ( position , course , color  ) , ...  )
            Checking -> ( 10 , None )

    Receive Data:
        Priority :
            Close -> { 0 : True }
            Download -> { 1 : True }
            Information -> { 9 : True }
        Minor :
            Update Tiles -> { 3 : ( position , course , color ) }
            Checking -> { 10 : None }

"""


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


def send_data(client: socket.socket, data: bytes, timing=30) -> bool :
    try :
        time.sleep(1 / timing)
        client.sendall(data)
    except socket.error :
        return False
    return True


class CustomSocket :
    __connection: socket.socket = None
    done_activity = False

    def setSocket(self, connection: socket.socket) :
        self.__connection = connection

    def checkIfWorking(self) -> bool :
        if self.__connection.fileno() :
            return True
        else :
            return False

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
        body : bytes = received_data(self.__connection, int(bode_size))  # Received ; '(int, int, int)'
        # print(f"[!] Dumps Body : {body}")
        if body is None and not body :
            self.done_activity = True
            return None

        try :
            body = json.loads( body.decode() )
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
        self.__connection.shutdown(socket.SHUT_RDWR)
        self.__connection.close()


class PlayerSockets :
    recv = CustomSocket()
    send = CustomSocket()

    send_items: list[tuple[int, tp.Any], ...] = []
    recv_items: list[dict[int, tp.Any], ...] = []

    pending_board_activities: list[tuple[int, tp.Any], ...] = []

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

    def threadBoardActivitiesUpdate(self) :
        while not self.has_connection_error and not self.close_transaction :
            if len(self.pending_board_activities) > 0 and self.done_downloading :
                self.send_items.append(self.pending_board_activities.pop(0))

    def threadSend(self) :
        while not self.has_connection_error and not self.close_transaction :
            if len(self.send_items) > 0 :
                data = self.send_items[0]
                if not self.send.send(data[0], data[1]) :
                    self.has_connection_error = True
                else :
                    if data in self.send_items :
                        self.send_items.remove(data)

    def threadRecv(self) :
        while not self.has_connection_error and not self.close_transaction :
            data = self.recv.received()
            if not data :
                self.has_connection_error = True
            else :
                self.recv_items.append(data)

    def threadCheckingForASeconds(self, seconds=3) :
        """ This was to check if the client still working """
        while not self.has_connection_error and not self.close_transaction and not SHUTDOWN_SERVER :
            for _ in range(seconds) :
                for _ in range(60) :
                    time.sleep(1 / 60)
                    if self.has_connection_error or self.close_transaction or SHUTDOWN_SERVER :
                        break
                if self.has_connection_error or self.close_transaction or SHUTDOWN_SERVER :
                    break
            else :
                if not self.recv_items :
                    self.putItemInSendItems(data=(10, None))

    def checkIfPlayerWantToClose(self) :  # Return True if the player want to close the game
        for item in self.send_items :
            for key in item :
                if key == 0 :
                    return True
        return False

    def getFirstRecvItems(self) -> dict :
        return self.recv_items.pop(0)

    def putTilesInfoInBoardActivities(self, data: tuple[int, tp.Any]) :  # used only in tiles activty
        self.pending_board_activities.append(data)

    def putItemInSendItems(self, data: tuple[int, tp.Any]) :  # format; data = ( code , object )
        # priority = ( close : 0 ) -> ( rejection : 4 ) -> ( information : 8 ) -> ( success : 7 )
        if data[0] == 0 :
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
        for item in self.send_items :
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


class ServerTransaction :
    TOTAL_TILES_OF_BOARD = 250 * 250
    COOLDOWN = 20  # 20 seconds of cooldown
    COOLDOWN_INTERVAL = 1  # minus 1 for every second
    filename = "player_board.json"
    __board: list[list[int, int, float], ...] = []  # course : int , color : int , time : float
    courses = (None, 'bshrm', 'bsc', 'bsbamfm', 'bsma', 'bscs', 'bseme', 'bsemm', 'bsemf', 'bsemss', 'bee')
    palettes = {
        'bshrm' : [], 'bsc' : [], 'bsbamfm' : [], 'bsma' : [], 'bscs' : [],
        'bseme' : [], 'bsemm' : [], 'bsemf' : [], 'bsemss' : [], 'bee' : []
    }

    pending_players: dict[str, socket.socket] = {}
    current_players: dict[str, PlayerSockets] = {}
    pending_activity_in_boards: list[tuple[int, int, int], ...] = []

    server_socket: socket.socket = None

    # Information
    active_players: int = 0
    most_active_course: int = 0
    most_used_color: list[int, int] = [0, 0]  # [ course , color ]

    def saveBoardData(self) :
        with open(self.filename, 'w') as jf :
            json.dump(self.__board, jf)
        print("[ / ] Done saving the board")

    def loadBoardPastData(self) :
        with open(self.filename, 'r') as jf :
            self.__board = json.load(jf)
        print("[ / ] Done loading the board")

    def checkIfCurrentlyCooldown(self, index: int) -> bool :
        if not self.__board[index][2] :
            return True
        if 0 < self.__board[index][2] :
            return False
        return True

    def getBoardTileData(self, index: int) :
        return self.__board[index].copy()

    def lessenTimeInTile(self, tile: int, cooldown: float) :
        if not self.__board[tile][2] :
            return None
        if self.__board[tile][2] > 0 :
            self.__board[tile][2] -= cooldown

    def updateBoardTiles(self, tile: int, course: int, color: int) :
        self.__board[tile] = [course, color, self.COOLDOWN]
        for player in self.current_players :
            try :
                self.current_players[player].putTilesInfoInBoardActivities(data=(2, (tile, course, color)))
            except KeyError :
                pass

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

    def activityShutdownTheServer(self, socket_id: str) :
        self.current_players[socket_id].putItemInSendItems((0, None))
        while not self.current_players[socket_id].isCodeIsSent(0) and not self.current_players[
            socket_id].has_connection_error :
            pass
        self.current_players[socket_id].closeAllProcess()
        del self.current_players[socket_id]

    def activityPlayerHasErrorConnection(self, socket_id: str) :
        self.current_players[socket_id].closeAllProcess()
        del self.current_players[socket_id]

    def threadUpdateInformation(self) :
        while not SHUTDOWN_SERVER :

            # Get the active players
            self.active_players = len(self.current_players)

            # Filter out items with None in the first and last positions
            filtered_board = [item for item in self.__board.copy() if item[0] is not None and item[1] is not None]
            if not filtered_board :
                self.most_active_course = 0
                self.most_used_color[0] = 0
                self.most_used_color[1] = 0
            else :
                # Use collections.Counter to count occurrences
                counts = Counter(tuple(item[:2]) for item in filtered_board)

                # Find the combination with the highest count
                highest_count = max(counts.values())
                highest_combinations = [combo for combo, count in counts.items() if count == highest_count]

                self.most_active_course = highest_combinations[0][0]
                self.most_used_color[0] = self.most_active_course
                self.most_used_color[1] = highest_combinations[0][1]

    def threadLessenEveryInBoardBySecond(self) :
        def lessenTimeInTile(tile_start: int, tile_last: int) :
            time_sleep = self.COOLDOWN_INTERVAL / 60
            while not SHUTDOWN_SERVER :
                for _ in range(60) :
                    time.sleep(time_sleep)
                    if SHUTDOWN_SERVER : break  # if any shutdown happen then close it

                start_time = time.time()  # use for debugging

                for tile in range(tile_start, tile_last) :
                    self.lessenTimeInTile(tile, self.COOLDOWN_INTERVAL)
                    if SHUTDOWN_SERVER : break  # if any shutdown happen then close it

                end_time = time.time()  # use for debugging
                time_taken = end_time - start_time  # use for debugging

                # print(f"Time taken: {time_taken:.6f} seconds") # use for debugging

        interval = 10
        batch_tile = 0
        tiles_every_interval = int(len(self.__board) / interval)

        for _ in range(interval) :
            threading.Thread(target=lessenTimeInTile, args=(batch_tile, batch_tile + tiles_every_interval)).start()
            batch_tile += tiles_every_interval

        print("[/] Done Running The Cooldown Of Every Tiles")

    def threadRemoveSocketIfNotTakenForASeconds(self, socket_id: str) :
        for counter in range(2) :
            for i in range(60) :
                time.sleep(1 / 60)
                if SHUTDOWN_SERVER :
                    return

            if self.pending_players.get(socket_id) is None and counter == 1 :
                break
        else :
            del self.pending_players[socket_id]

    def threadIdentifySocketBeforeAddingToCurrentPlayers(self, client: socket.socket) :
        # The First Socket is the RECEIVE SOCKET, next is SENDING SOCKET
        socket_id: bytes = received_data(client, SOCKET_ID_SIZE)
        if not socket_id : return
        socket_id: str = pickle.loads(socket_id)
        print(f"\n[!] Socket ID : {socket_id}")  # use for debugging
        if socket_id not in self.pending_players :  # If First Time Entering Then Add To
            self.pending_players[socket_id] = client
            print(f"[!] Saved in pending players : {socket_id}")  # use for debugging
            threading.Thread(target=self.threadRemoveSocketIfNotTakenForASeconds, args=(socket_id,)).start()
        else :
            # print(f"[!] Found Partner : {socket_id}") # use for debugging
            recv_socket = self.pending_players[socket_id]
            recv_socket.shutdown(socket.SHUT_WR)
            del self.pending_players[socket_id]
            # print(f"[!] Got The Partner : {socket_id}") # use for debugging
            self.createClassFor2SocketAndAddToCurrentPlayers(socket_id=socket_id, send_socket=client,
                                                             recv_socket=recv_socket)
            # print(f"[!] Done Creating Class : {socket_id}") # use for debugging
            # Start the sending and receiving the player
            threading.Thread(target=self.current_players[socket_id].threadRecv).start()
            threading.Thread(target=self.current_players[socket_id].threadSend).start()
            threading.Thread(target=self.current_players[socket_id].threadCheckingForASeconds).start()
            threading.Thread(target=self.current_players[socket_id].threadBoardActivitiesUpdate).start()
            # print(f"[!] Thread Start Of Sending And Receiving : {socket_id}") # use for debugging
            threading.Thread(target=self.threadHandleTheNotificationOfServerAndPlayer, args=(socket_id,)).start()
            # print(f"[!] Thread Start Of Handling Notification To Server : {socket_id} ") # use for debugging
            threading.Thread(target=self.threadHandleTheActivityOfPlayer, args=(socket_id,)).start()
            # print(f"[!] Thread Start Of Handling Activity : {socket_id}") # use for debugging

    def threadHandleTheNotificationOfServerAndPlayer(self, socket_id: str) :
        """ This where the notifying the server or the player  """
        try :
            while True :

                if SHUTDOWN_SERVER :  # Activity when the admin want to close the server
                    self.activityShutdownTheServer(socket_id)
                    print(f"[!] Notify of shutting down server : {socket_id}")  # use for debugging
                    break

                if self.current_players[
                    socket_id].has_connection_error and not SHUTDOWN_SERVER :  # Activity when the player socket has an error
                    self.activityPlayerHasErrorConnection(socket_id)
                    print(f"[!] Notify of closing the player : {socket_id}")  # use for debugging
                    break

        except KeyError :
            pass

    def threadHandleTheActivityOfPlayer(self, socket_id: str) :
        """ This where the activity of player, Such; download board and any activities"""
        try :
            while not SHUTDOWN_SERVER and not self.current_players[socket_id].close_transaction and not \
                    self.current_players[socket_id].has_connection_error :
                if self.current_players[socket_id].recv_items :
                    activity = self.current_players[socket_id].getFirstRecvItems()
                    print(f"------------ [ {activity} ] ----------------")
                    print(f"Status Has Error : {self.current_players[socket_id].has_connection_error}")
                    print(f"Current Connected : {self.current_players}")

                    # if user want to close the program
                    if activity.get(0) :
                        print(f"[!] Activity user want to close the app : {socket_id}")  # use for debugging
                        self.activityPlayerHasErrorConnection(socket_id)

                    # if user want to join the game
                    if activity.get(1) :
                        # send the tiles in board
                        print(f"[!] Activity user want to download the board : {socket_id}")  # use for debugging
                        interval = 5
                        downloaded = 0
                        need_data_every_interval = int(len(self.__board) / interval)
                        print(f"Data Interval : {len(self.__board)} / {interval} = {need_data_every_interval}  ")
                        for i in range(interval) :
                            datas = tuple(
                                (pos, self.__board[pos][0], self.__board[pos][1]) for pos in
                                range(downloaded, int(downloaded + need_data_every_interval))
                            )
                            downloaded += need_data_every_interval
                            print("================== Loop")
                            if self.current_players[socket_id].has_connection_error :
                                break
                            else :
                                self.current_players[socket_id].putItemInSendItems(data=(2, tuple(datas)))
                        self.current_players[socket_id].putItemInSendItems(data=(7, None))
                        self.current_players[socket_id].done_downloading = True

                    # if user want to check the information of app
                    if activity.get(9) :
                        # Information -> ( 8 , ( active_players, most_active_course, most_used_color ) )
                        self.current_players[socket_id].putItemInSendItems(
                            data=(8, (self.active_players, self.most_active_course, tuple(self.most_used_color))))

                    # if user want to change the tiles in board
                    if activity.get(3) :
                        if self.checkIfCurrentlyCooldown(activity[3][0]) :
                            print("[!] The Board Is Okey")
                            self.updateBoardTiles(tile=activity[3][0], course=activity[3][1], color=activity[3][2])
                            print(f"[?] Updated Tiles : {self.__board[activity[3][0]]}")
                        else :
                            print("[!] The Board already used ")
                            print(f"[?] Cooldown Tiles : {self.__board[activity[3][0]]}")
                            self.current_players[socket_id].putItemInSendItems(
                                data=(4, self.getBoardTileData(activity[3][0])[-1]))
        except KeyError :
            pass

    def runTheServer(self) :
        """ This is where the configuring and assembling all the functions """
        self.loadBoardPastData()
        self.threadLessenEveryInBoardBySecond()
        threading.Thread(target=self.threadUpdateInformation).start()

        self.server_socket = create_socket()
        if not self.server_socket :
            print("[!] Error : Cant make a socket for server ")
            return

        global DONE_RUNNING_SERVER
        DONE_RUNNING_SERVER = True

        self.server_socket.listen(NUMBER_OF_CONNECTED)
        try :

            while True :
                if not SHUTDOWN_SERVER :
                    client, _ = self.server_socket.accept()
                    threading.Thread(target=self.threadIdentifySocketBeforeAddingToCurrentPlayers,
                                     args=(client,)).start()

        except Exception as e :
            print(f"[!] The Error : {e}")

        DONE_RUNNING_SERVER = False

    def closeTheServer(self) :
        global SHUTDOWN_SERVER
        SHUTDOWN_SERVER = True

        for i in self.pending_players :
            try :
                self.pending_players[i].close()
            except socket.error :
                print("[!] Pending player closing error")
        self.pending_players.clear()

        while self.current_players :
            pass

        self.saveBoardData()
        if self.server_socket :
            self.server_socket.close()
        print("[/] Successfully Closed")


def main() :
    transaction = ServerTransaction()

    while not SHUTDOWN_SERVER :
        print("\n ------------- SERVER ------------------ ")
        print("ACTIVITIES : ")
        print("  RUN SERVER = 'R' ")
        print("  CLOSE SERVER = 'C' \n")
        activity = input("[?] ACTIVITY : ")
        if activity.lower() == 'r' :

            if DONE_RUNNING_SERVER :
                print("[!] The Server Is Currently Running")
            else :
                threading.Thread(target=transaction.runTheServer).start()
                while not DONE_RUNNING_SERVER :
                    pass

        elif activity.lower() == 'c' :
            transaction.closeTheServer()
            break

        else :
            print("[    !] Follow The Instruction!")


if __name__ == "__main__" :
    transaction = ServerTransaction()
    transaction.runTheServer()
    # main()
    #
    # with open("player_board.json" , 'r') as jf:
    #     board = json.load(jf)
    #     print(sys.getsizeof(pickle.dumps(board[0:125])))

    # total_pickle = 0
    # total_json = 0
    # tiles_size = 250 * 250
    # with open("player_board.json" , 'w') as jf:
    #     board = []
    #     for _ in range(tiles_size):
    #         tiles = [None, None , None]
    #         board.append(tiles)
    #         total_pickle += sys.getsizeof(pickle.dumps({10 : tiles}))
    #         total_json += sys.getsizeof(json.dumps({10 : tiles}))
    #     json.dump(board , jf , indent=4)
    #
    # print(f"Number Of Tiles : {tiles_size:3,}")
    # print(f"Pickle : {total_pickle:3,}")
    # print(f"Json : {total_json:3,}")
