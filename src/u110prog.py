"""Talk to the ESP32 SST39SF040 programmer over USB (https://github.com/yuyoi/esp32-maskrom-programmer).

burn_image() sends a 512 KB card image to the programmer (checked in 4 KB blocks with a CRC), then tells it to
erase the chip and write it. The programmer never reads the chip back, so verify in your normal programmer.
"""
import time
import zlib

BAUD = 921600
BLOCK = 4096
IMAGE_SIZE = 512 * 1024
USB_IDS = {0x1A86, 0x10C4}          # WCH CH343/CH340 and CP210x: the UART port of an ESP32-S3 DevKitC-1


class ProgrammerError(Exception):
    pass


def find_ports():
    from serial.tools import list_ports
    return [p.device for p in list_ports.comports() if p.vid in USB_IDS]


def _readline(ser, timeout=5):
    ser.timeout = timeout
    return ser.readline().decode('utf-8', 'replace').strip()


def _expect(ser, prefix, timeout=5):
    """skip debug lines until one starts with prefix"""
    end = time.time() + timeout
    while time.time() < end:
        line = _readline(ser, max(0.1, end - time.time()))
        if line.startswith(prefix):
            return line
        if line.startswith('ERR'):
            raise ProgrammerError('programmer said: ' + line)
    raise ProgrammerError('no answer from the programmer (waiting for %s)' % prefix)


def _cmd(ser, text, prefix, timeout=5):
    ser.reset_input_buffer()
    ser.write((text + '\n').encode())
    return _expect(ser, prefix, timeout)


def burn_image(data, name='card.bin', progress=None, port=None):
    """progress(fraction 0..1, text). returns a result message. raises ProgrammerError."""
    import serial
    say = progress or (lambda f, t: None)
    if len(data) != IMAGE_SIZE:
        raise ProgrammerError('card image must be exactly 512 KB (got %d bytes)' % len(data))
    if port is None:
        ports = find_ports()
        if not ports:
            raise ProgrammerError('no programmer found.\nPlug in the ESP32-S3\'s UART USB-C port (the one with the CH343 chip).')
        port = ports[0]
    name = ''.join(c if c.isalnum() or c in '._-' else '_' for c in name)[-40:] or 'card.bin'
    ser = serial.Serial()
    ser.port, ser.baudrate = port, BAUD
    ser.dtr = ser.rts = False                       # opening the port must not reset the board
    try:
        ser.open()
    except Exception as e:
        raise ProgrammerError('cannot open %s: %s' % (port, e))
    try:
        time.sleep(0.3)
        try:
            _cmd(ser, 'PING', 'PONG', 3)
        except ProgrammerError:
            raise ProgrammerError('%s did not answer as an SST programmer.\nWrong port, or the firmware is not running.' % port)
        crc = zlib.crc32(data) & 0xFFFFFFFF
        _cmd(ser, 'PUT %s %d %x' % (name, len(data), crc), 'OK')
        for i in range(0, len(data), BLOCK):
            ser.write(data[i:i + BLOCK])
            if ser.read(1) != b'K':
                raise ProgrammerError('transfer failed at %d KB' % (i // 1024))
            if (i // BLOCK) % 8 == 0:
                say(0.3 * i / len(data), 'Sending to programmer... %d%%' % (100 * i // len(data)))
        _expect(ser, 'DONE', 10)
        say(0.3, 'Sent, CRC ok. Erasing and writing the chip...')
        _cmd(ser, 'BURN ' + name, 'OK')
        names = ['idle', 'Erasing chip...', 'Writing chip...', 'done', 'error']
        while True:
            time.sleep(0.5)
            parts = _cmd(ser, 'STATUS', 'STATUS').split(' ', 4)
            state, done, total = int(parts[1]), int(parts[2]), int(parts[3])
            msg = parts[4] if len(parts) > 4 else ''
            if state in (3, 4):
                if state == 4:
                    raise ProgrammerError('burn failed: ' + msg)
                say(1.0, 'Burn finished')
                return msg or 'burn finished'
            say(0.3 + 0.7 * done / max(total, 1), names[state] + (' %d%%' % (100 * done // total) if state == 2 else ''))
    finally:
        ser.close()
