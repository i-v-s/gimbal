from abc import ABCMeta, abstractstaticmethod
from typing import NamedTuple, Any, Optional, Tuple
from serial import Serial
from struct import calcsize, pack, unpack


class MessageFormat(NamedTuple):
    command_id: Optional[int]
    struct_format: str
    response: Any = None


class Payload(metaclass=ABCMeta):
    @abstractstaticmethod
    def format() -> MessageFormat:
        ...


class Message(NamedTuple):
    start_character: int
    command_id: int
    payload_size: int
    header_checksum: int
    payload: bytes = b''

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
        data = pack(message_format, *self)
        data += pack('<H', self.crc16(data[1:]))
        return data

    @staticmethod
    def create(command_id: int, payload: bytes = b'') -> 'Message':
        payload_size = len(payload)
        return Message(start_character=0x24,
                       command_id=command_id,
                       payload_size=payload_size,
                       header_checksum=(command_id + payload_size) % 256,
                       payload=payload)

    @staticmethod
    def unpack_header(data: bytes):
        return Message(*unpack('<BBBB', data))

    def unpack_payload(self, data: bytes):
        assert self.payload_size == len(data) - 2
        fmt = f'<{self.payload_size}sH'
        payload, crc = unpack(fmt, data)
        return Message(*self[:-1], payload=payload)

    @staticmethod
    def unpack(data: bytes, payload_size: int):
        message_format = '<BBBB{}sH'.format(payload_size)
        message = unpack(message_format, data)
        crc = message[-1]
        return Message(*message[:-1])


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
    def format() -> MessageFormat:
        return MessageFormat(86, '<BHBHBIH3sH')


class BoardInfoReq(NamedTuple):
    cfg: int = 0

    @staticmethod
    def format() -> MessageFormat:
        return MessageFormat(86, '<H', BoardInfo)


class MotorsOffReq(NamedTuple):
    mode: int

    @staticmethod
    def format() -> MessageFormat:
        return MessageFormat(109, '<B')


# outgoing CMD_CONTROL - control gimbal movement
class ControlReq(NamedTuple):
    roll_mode: int
    pitch_mode: int
    yaw_mode: int
    roll_speed: int
    roll_angle: int
    pitch_speed: int
    pitch_angle: int
    yaw_speed: int
    yaw_angle: int

    @staticmethod
    def format() -> MessageFormat:
        return MessageFormat(67, '<BBBhhhhhh')


class ImuData(NamedTuple):
    acc_data: float
    gyro_data: float

    # @staticmethod
    # def from_items(items):
    #     ...


class Angles(NamedTuple):
    roll: float
    pitch: float
    yaw: float

    @staticmethod
    def from_items(r, p, y):
        return Angles(r * 0.02197265625, p * 0.02197265625, y * 0.02197265625)


class RealtimeData3(NamedTuple):
    imu_data: Tuple[ImuData, ImuData, ImuData]
    serial_err_cnt: int
    system_error: int
    system_sub_error: int
    reserved: bytes
    rc_raw: Tuple[int, int, int]
    rc_cmd: int
    ext_fc_roll: int
    ext_fc_pitch: int

    imu_angle: Angles
    frame_imu_angle: Angles
    target_angle: Angles
    cycle_time: int
    i2c_error_count: int
    error_code: int
    bat_level: float
    rt_data_flags: int
    cur_imu: int
    cur_profiile: int
    motor_power: Tuple[int, int, int]

    @staticmethod
    def format():
        return MessageFormat(23, '<6hHHB3s3hh2h9hHHBH6B')


class Confirm(NamedTuple):
    cmd_id: int
    data: bytes


payloads_map = {
    86: BoardInfo,
    23: RealtimeData3,
}


def deserialize(target_type, items, types=None):
    if types is None:
        types = map(getattr(target_type, '_field_types').get, getattr(target_type, '_fields'))
    result = []
    for ft in types:
        if ft in [int, float, bytes]:
            result.append(items.pop(0))
        elif hasattr(ft, 'from_items'):
            size = len(getattr(ft, '_fields'))
            result.append(ft.from_items(*items[:size]))
            for t in range(size):
                items.pop(0)
        elif hasattr(ft, '_fields') and hasattr(ft, '_field_types'):
            result.append(deserialize(ft, items))
        elif ft.__origin__ is tuple:
            result.append(deserialize(tuple, items, ft.__args__))
        else:
            print()
    return tuple(result) if target_type is tuple else target_type(*result)


class Gimbal(Serial):
    def __init__(self, *args, **kwargs):
        super(Gimbal, self).__init__(*args, **kwargs)

    def read_message(self) -> Any:
        header_data = self.read(4)
        header = Message.unpack_header(header_data)
        payload_data = self.read(header.payload_size + 2)
        message = header.unpack_payload(payload_data)
        msg_type = payloads_map.get(message.command_id, None)
        if msg_type is not None:
            command_id, payload_format, _ = msg_type.format()
            payload = unpack(payload_format, message.payload)
            payload = deserialize(msg_type, list(payload))
            return payload
        if message.command_id == 67:    # CMD_CONFIRM
            fmt = f'<B{message.payload_size - 1}s'
            return Confirm(*unpack(fmt, message.payload))
        raise RuntimeError(f'Unknown response command_id {message.command_id}')

    def write_message(self, payload):
        command_id, fmt, _ = payload.format()
        self.write(Message.create(command_id, pack(fmt, *payload)).pack())

    def request(self, req):
        self.write_message(req)
        return self.read_message()

    def board_info(self, cfg: int = 0) -> BoardInfo:
        return self.request(BoardInfoReq(cfg))

    def motors_on(self) -> bool:
        self.write(Message.create(77).pack())
        result = self.read_message()
        assert isinstance(result, Confirm)
        assert result.cmd_id == 77
        return True

    def motors_off(self, mode=0) -> bool:
        result = self.request(MotorsOffReq(mode))
        assert isinstance(result, Confirm)
        assert result.cmd_id == 109
        return True

    def control_angle(self, roll: float, pitch: float, yaw: float):
        result = self.request(ControlReq(
            2, 2, 2,
            0, round(roll / 0.02197265625),
            0, round(pitch / 0.02197265625),
            0, round(yaw / 0.02197265625),
        ))
        assert isinstance(result, Confirm)
        assert result.cmd_id == 67
        return True

    def realtime_data(self, ver=3):
        self.write(Message.create(23 if ver == 3 else 25).pack())
        return self.read_message()


if __name__ == '__main__':
    gimbal = Gimbal('/dev/ttyUSB0', baudrate=115200, timeout=10)
    bi = gimbal.board_info()
    c1 = gimbal.motors_on()
    c3 = gimbal.control_angle(0, 30, 0)
    rd = gimbal.realtime_data()
    c4 = gimbal.control_angle(0, -30, 0)
    c2 = gimbal.motors_off()
    #connection = serial.Serial('/dev/ttyUSB0', baudrate=115200, timeout=10)
    connection.write(msg)
    message = read_message(connection, BoardInfo)
    print('received confirmation:', message)

    rotate_gimbal()
