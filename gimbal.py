from collections import namedtuple
from typing import NamedTuple

import serial
import struct

# outgoing CMD_CONTROL - control gimbal movement
ControlData = namedtuple(
    'ControlData',
    'roll_mode pitch_mode yaw_mode roll_speed roll_angle pitch_speed pitch_angle yaw_speed yaw_angle')


class Message(NamedTuple):
    start_character: int
    command_id: int
    payload_size: int
    header_checksum: int
    payload: bytes

    @staticmethod
    def crc16(data: bytes) -> int:
        crc = 0
        poly = 0x8005
        for c in data:
            for b in range(8):
                crc_bit = bool(crc >> 15)
                crc = (crc << 1) & 0xFFFF
                if bool(c & (1 << b)) != crc_bit:
                    crc ^= poly
        return crc

    def pack(self):
        message_format = '<BBBB{}s'.format(self.payload_size)
        data = struct.pack(message_format, *self)
        data += struct.pack('<H', self.crc16(data[1:]))
        return data

    @staticmethod
    def create(command_id: int, payload: bytes) -> 'Message':
        payload_size = len(payload)
        return Message(start_character=0x24,
                       command_id=command_id,
                       payload_size=payload_size,
                       header_checksum=(command_id + payload_size) % 256,
                       payload=payload)


class BoardInfo(NamedTuple):
    board_ver: int
    firmware_ver: int
    state_flags1: int
    board_features: int
    connection_flag: int
    frw_extra_id: int
    board_features_ext: int
    reserved: int
    base_frw_ver: int

    @staticmethod
    def format():
        return '<BHBHBIH3sH'


def pack_control_data(control_data: ControlData) -> bytes:
    return struct.pack('<BBBhhhhhh', *control_data)


def pack_message(message: Message) -> bytes:
    message_format = '<BBBB{}sB'.format(message.payload_size)
    return struct.pack(message_format, *message)


def unpack_message(data: bytes, payload_size: int) -> Message:
    message_format = '<BBBB{}sB'.format(payload_size)
    return Message._make(struct.unpack(message_format, data))


def read_message(connection: serial.Serial, msg_type: NamedTuple) -> Message:
    # 5 is the length of the header + payload checksum byte
    # 1 is the payload size
    pl_fmt = msg_type.format()
    payload_size = struct.calcsize(pl_fmt)
    response_data = connection.read(6 + payload_size)
    print('received response', response_data)
    message_format = '<BBBB{}sH'.format(payload_size)
    unp = struct.unpack(message_format, response_data)
    p = unp[4]
    up = msg_type(*struct.unpack(pl_fmt, p))
    return unpack_message(response_data, payload_size)


def rotate_gimbal():
    CMD_CONTROL = 67
    control_data = ControlData(roll_mode=1, roll_speed=0, roll_angle=20,
                               pitch_mode=1, pitch_speed=0, pitch_angle=20,
                               yaw_mode=1, yaw_speed=100, yaw_angle=20)
    print('command to send:', control_data)
    packed_control_data = pack_control_data(control_data)
    print('packed command as payload:', packed_control_data)
    message = create_message(CMD_CONTROL, packed_control_data)
    print('created message:', message)
    packed_message = pack_message(message)
    print('packed message:', packed_message)

    connection = serial.Serial('/dev/ttyUSB0', baudrate=115200, timeout=10)
    print('send packed message:', packed_message)
    connection.write(packed_message)
    message = read_message(connection, 1)
    print('received confirmation:', message)
    print('confirmed command with ID:', ord(message.payload))


if __name__ == '__main__':
    msg = Message.create(77, b'').pack()
    #msg = Message.create(0x56, '\0\0'.encode()).pack()
    connection = serial.Serial('/dev/ttyUSB0', baudrate=115200, timeout=10)
    connection.write(msg)
    message = read_message(connection, BoardInfo)
    print('received confirmation:', message)

    rotate_gimbal()
