import logging
import socket
import socketserver
import tftp.storage as storage
import threading

SOCKET_TIMEOUT = 5.0

class UnknownOpcodeException(Exception):
    pass

class UnknownErrorCodeException(Exception):
    pass

class IllegalOperationException(Exception):
    pass

class UnknownModeException(Exception):
    pass

class MalformedPacketException(Exception):
    pass

Opcodes = {
    'RRQ': 0x01,
    'WRQ': 0x02,
    'DATA': 0x03,
    'ACK': 0x04,
    'ERROR': 0x05,
    0x01: 'RRQ',
    0x02: 'WRQ',
    0x03: 'DATA',
    0x04: 'ACK',
    0x05: 'ERROR'}

Errors = {
    'NOT_DEFINED': 0x00,
    'FILE_NOT_FOUND': 0x01,
    'ACCESS_VIOLATION': 0x02,
    'ALLOCATION_EXCEEDED': 0x03,
    'ILLEGAL_OPERATION': 0x04,
    'UNKNOWN_TRANSFER_ID': 0x05,
    'FILE_EXISTS': 0x06,
    'NO_SUCH_USER': 0x07,
    0x00: 'NOT_DEFINED',
    0x01: 'FILE_NOT_FOUND',
    0x02: 'ACCESS_VIOLATION',
    0x03: 'ALLOCATION_EXCEEDED',
    0x04: 'ILLEGAL_OPERATION',
    0x05: 'UNKNOWN_TRANSFER_ID',
    0x06: 'FILE_EXISTS',
    0x07: 'NO_SUCH_USER'}

Modes = {
    'OCTET': 'octet',
    'NETASCII': 'netascii',
    'MAIL': 'mail'}

def unpackOpcode(packet):
    """Returns an integer corresponding to Opcode encoded in packet.

    Raises UnknownOpcodeException if Opcode is out of bounds.
    """
    c = int.from_bytes(packet[:2], byteorder='big')
    if c not in Opcodes:
        raise UnknownOpcodeException("Unknown Opcode '{}'".format(c))
    return c

def packERROR(code, msg):
    """Returns a byte-ordered TFTP Error packet based on code and msg.

    Raises UnknownErrorCodeException when code is out of bounds.
    """
    if code not in Errors:
        raise UnknownErrorCodeException("Unknown error code '{}'".format(code))

    b = bytearray()
    b.extend(Opcodes['ERROR'].to_bytes(2, 'big'))
    b.extend(code.to_bytes(2, 'big'))
    b.extend(bytes(msg, 'ascii'))
    b.append(0)
    return b

def packDATA(data, blockNum):
    """Returns byte-formatted DATA packet"""
    b = bytearray()
    b.extebd(Opcodes['DATA'].to_bytes(2, 'big'))
    b.extend(blockNum.to_bytes(2, 'big'))
    b.extend(bytes(data))
    return b

def unpackDATA(packet):
    """Returns tuple of (Opcode, BlockNum, Data)"""
    opcode = unpackOpcode(packet)
    if opcode != Opcodes['DATA']:
        raise IllegalOperationException(
            "Expected DATA packet, but got '{0}'"\
            .format(Opcodes[opcode]))

    blockNum = int.from_bytes(packet[2:4], 'big')
    data = packet[4:]
    return (opcode, blockNum, data)

def unpackRWRQ(packet):
    """Returns a tuple of (Opcode, Filename, Mode)"""
    opcode = unpackOpcode(packet)
    if opcode not in (Opcodes['RRQ'], Opcodes['WRQ']):
        raise IllegalOperationException(
            "Expected RRQ or WRQ but got '{0}'"\
            .format(Opcodes[c]))

    s = 2
    e = packet.find(0, s)
    if e < s:
        raise MalformedPacketException("Couldn't find filename termination byte")
    filename = packet[s:e].decode('utf-8')

    s = e + 1
    e = packet.find(0, s)
    if e < s:
        raise MalformedPacketException("Couldn't find mode termination byte")
    mode = packet[s:e].decode('utf-8')

    if not filename:
        raise storage.EmptyPathException("Filename cannot be empty")
    elif mode.upper() not in Modes:
        raise UnknownModeException(
            "Mode '{}' not recognized"\
            .format(mode))
    return (opcode, filename, mode.upper())

def unpackACK(packet):
    """Returns a tuple of (Opcode, BlockNum)"""
    opcode = unpackOpcode(packet)
    if opcode != Opcodes['ACK']:
        raise IllegalOperationException(
            "Expected ACK packet, but got '{0}'"\
            .format(Opcodes[opcode]))

    blockNum = int.from_bytes(packet[2:4])
    return (opcode, blockNum)

def packACK(blockNum):
    """Returns a byte-formatted ACK packet"""
    b = bytearray()
    b.extend(Opcode['ACK'].to_bytes(2, 'big'))
    b.extend(blockNum.to_bytes(2, 'big'))
    return b

def sendError(address, socket, err):
    socket.sendto(err, address)

def logClientError(address, error):
    logging.info(
        "Sent error to Client [{0}]: {1}"\
        .format(address[0], error))

def sendData(address, socket, data, blockNum):
    data = packDATA(data, blockNum)
    socket.sendto(data, address)

def handleRRQ(address, socket, filename, mode):
    logging.info(
        "Client [{0}] requested to read file [{1}] using transfer mode [{2}]"\
        .format(address[0], filename, mode))
    store = storage.Storage()

    try:
        file = store.get(filename)
    except (storage.FileNotFoundException, storage.EmptyPathException) as ex:
        err = packERROR(
            Errors['FILE_NOT_FOUND'],
            str(ex))
        sendError(address, socket, err)
        logClientError(address, err)
        return

    data = None
    sendDATA = False
    readACK = False
    dataBlock = 0
    ackBlock = 0
    fileSize = len(file)
    # s and e are initially incremented by 512 to give data[0:512] slice
    s = -512
    e = 0

    # Control is returned to handler() by explicit return
    while True:
        # Ready for new DATA packet
        if ackBlock == dataBlock:
            dataBlock += 1
            s += 512
            e += 512
            if e > fileSize:
                e = -1
            data = file[s:e]
            sendDATA = True
            logging.debug(
                "Client [{0}]: Creating datablock [{1}] on file {2}[{3}:{4}]"\
                .format(address, dataBlock, filename, s, e))

        # We're sending a DATA packet
        if sendDATA:
            try:
                logging.debug(
                    "Client [{0}]: Sending datablock [{1}]"\
                    .format(address, dataBlock))
                sendData(address, socket, dataBlock, data)
                sendDATA = False
                readACK = True
            # Assume that a send timeout is a closed connection
            except socket.Timeout as ex:
                # Try at least to alert the client before closing connection
                err = packERROR(
                    Errors['NOT_DEFINED'],
                    str(ex))
                sendError(address, socket, err)
                logClientError(address, ex)
                return

        # We're waiting for an ACK packet
        if readACK:
            try:
                logging.debug(
                    "Client [{0}]: Receiving ACK for datablock [{1}]"\
                    .format(address, dataBlock))
                packet = socket.recv(1024)
                try:
                    opcode, block = unpackACK(packet)
                    # Ignore all ACKs other than for current block
                    if block == dataBlock:
                        ackBlock = block
                        readACK = False
                        logging.debug(
                            "Client [{0}]: Received ACK for datablock [{1}]"\
                            .format(address, block))
                    else:
                        logging.debug(
                            "Client [{0}]: Received ACK [{1}] for datablock [{2}]"\
                            + " Still waiting for ACK [{2}]"\
                            .format(address, block, dataBlock))
                except IllegalOperationException as ex:
                    err = packERROR(
                        Errors['ILLEGAL_OPERATION'],
                        str(ex))
                    sendError(address, socket, err)
                    logClientError(address, ex)
                    return
            # If we've timed out waiting for ACK, resend DATA
            except socket.Timeout:
                readACK = False
                sendDATA = True
                logging.debug(
                    "Client [{0}]: Timed out waiting for ACK [{1}]. Resending data."\
                    .format(address, dataBlock))

        # If we've acked the last block and no more data, we're done!
        if ackBlock == dataBlock and e == -1:
            logging.debug(
                "Client [{0}]: Finished sending file {1}"\
                .format(address, filename))
            return

def handleWRQ(address, socket, filename, mode):
    socket.sendto(
        filename,
        address)

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        packet, socket = self.request
        socket.settimeout(SOCKET_TIMEOUT)

        try:
            opcode, filename, mode = unpackRWRQ(packet)
        except UnknownModeException as ex:
            err = packERROR(
                Errors['ACCESS_VIOLATION'],
                str(ex))
            sendError(self.client_address, socket, err)
            logClientError(self.client_address, err)
            return
        except storage.EmptyPathException as ex:
            err = packERROR(
                Errors['FILE_NOT_FOUND'],
                str(ex))
            sendError(self.client_address, socket, err)
            logClientError(self.client_address, err)
            return
        except (IllegalOperationException, UnknownOpcodeException) as ex:
            err = packERROR(
                Errors['ILLEGAL_OPERATION'],
                str(ex))
            sendError(self.client_address, socket, err)
            logClientError(self.client_address, err)
            return

        if opcode == Opcodes['RRQ']:
            handleRRQ(self.client_address, socket, filename, mode)
        else:
            handleWRQ(self.client_address, socket, filename, mode)

class Server(socketserver.ThreadingMixIn, socketserver.UDPServer):
    pass
