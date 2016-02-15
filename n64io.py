#!/usr/bin/env python3
# n64io: Communication with Nintendo 64 controllers
# Copyright (C) 2015-2016 stump
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import serial
import sys
import time
from contextlib import contextmanager


def addr_crc(addr):
    '''
    Compute the CRC of an N64 controller expansion bus address
    as required by the controller. Takes a 16-bit int whose bottom
    5 bits are zero and returns the (5-bit) CRC.
    '''
    # Yes, the naive way. crcmod isn't capable of handling non-byte-sized CRCs,
    # and given that we therefore need a custom implementation (and that I
    # therefore needed to learn how CRCs actually work, which was highly
    # enlightening) but we're applying it to small amounts of data, I felt it
    # would be best to write it this way.
    #
    # 5-bit CRC with polynomial 0x15.
    crc = addr >> 11
    for i in reversed(range(11)):
        crc <<= 1
        crc |= 1 if (addr & 1<<i) else 0
        if crc & 0x0020:
            crc ^= 0x0035
    return crc

# TODO: Also implement the CRC the controller returns for the transferred data
# so we can verify correct transmission. Only the controller actually transmits
# data CRCs over the wire though (whether we're reading or writing), so we can
# get by without an implementation of it.


class N64Controller(object):
    '''
    A Nintendo 64 controller, as communicated with by
    the Arduino part of this project.
    '''
    def __init__(self, serialdev='/dev/ttyACM0'):
        self._serial = serial.Serial(port=serialdev, baudrate=115200)
        time.sleep(1)  # let the Arduino reset

    def _do_cmd(self, cmdbuf, resplen):
        '''
        Transmit cmdbuf to the controller; expect (and return) resplen
        bytes of response.
        '''
        cmdbuf = bytes((len(cmdbuf), resplen)) + cmdbuf
        self._serial.write(cmdbuf)
        return self._serial.read(resplen)

    def _do_status(self):
        '''
        Get a raw status response (3 bytes) from the controller.
        '''
        return self._do_cmd(b'\x00', 3)

    def _do_button_status(self):
        '''
        Get a raw button status response (4 bytes) from the controller.
        '''
        return self._do_cmd(b'\x01', 4)

    def _do_pak_read(self, addr):
        '''
        Read a 32-byte-aligned group of 32 bytes from the controller's expansion bus.
        '''
        addr |= addr_crc(addr)
        # The controller actually returns a 33rd byte that is a CRC over the first 32.
        # TODO: check it.
        return self._do_cmd(bytes((2, addr >> 8, addr & 0xff)), 33)[:32]

    def _do_pak_write(self, addr, data):
        '''
        Write a 32-byte-aligned group of 32 bytes to the controller's expansion bus.
        '''
        addr |= addr_crc(addr)
        # TODO: check the response byte, which is a CRC over the received data.
        return self._do_cmd(bytes((3, addr >> 8, addr & 0xff)) + data, 1)

    def _do_reset(self):
        '''
        Reset the controller and return the resulting raw status response (3 bytes).
        '''
        return self._do_cmd(b'\xff', 3)

    def has_pak(self):
        '''
        Check whether the controller has something plugged into its expansion port.
        '''
        status = self._do_status()
        return bool(status[2] & 0x01)

    # Determining what is plugged into the expansion port sadly requires probing.
    # Different Pak types have different values that 0x8000 can be set to.

    def pak_is_transfer_pak(self):
        '''
        Determine whether the controller has a Transfer Pak plugged in.
        '''
        old_block = self._do_pak_read(0x8000)
        self._do_pak_write(0x8000, b'\x84' * 32)
        if self._do_pak_read(0x8000) == b'\x84' * 32:
            self._do_pak_write(0x8000, b'\xfe' * 32)
            self._do_pak_write(0x8000, old_block)
            return True
        self._do_pak_write(0x8000, old_block)
        return False

    def pak_is_rumble_pak(self):
        '''
        Determine whether the controller has a Rumble Pak plugged in.
        '''
        old_block = self._do_pak_read(0x8000)
        self._do_pak_write(0x8000, b'\xfe' * 32)
        self._do_pak_write(0x8000, b'\x80' * 32)
        if self._do_pak_read(0x8000) == b'\x80' * 32:
            self._do_pak_write(0x8000, old_block)
            return True
        self._do_pak_write(0x8000, old_block)
        return False

    def tpak_set_power(self, power):
        if power:
            self._do_pak_write(0x8000, b'\x84' * 32)
        else:
            self._do_pak_write(0x8000, b'\xfe' * 32)

    def tpak_get_power(self):
        return self._do_pak_read(0x8000) == b'\x84' * 32

    def tpak_detect_pak(self):
        self._tpak_high_bits = -1
        self._do_pak_write(0xb000, b'\x01' * 32)
        return self._do_pak_read(0xb000) == b'\x89' * 32

    def tpak_read(self, addr):
        '''
        Read a 32-byte-aligned group of 32 bytes from the address space of the
        Game Boy cartridge in the Transfer Pak plugged into the controller.
        '''
        if addr >> 14 != self._tpak_high_bits:
            self._tpak_high_bits = addr >> 14
            self._do_pak_write(0xa000, bytes((self._tpak_high_bits,)) * 32)
        return self._do_pak_read(addr | 0xc000)

    def tpak_write(self, addr, data):
        '''
        Write a 32-byte-aligned group of 32 bytes to the address space of the
        Game Boy cartridge in the Transfer Pak plugged into the controller.
        '''
        if addr >> 14 != self._tpak_high_bits:
            self._tpak_high_bits = addr >> 14
            self._do_pak_write(0xa000, bytes((self._tpak_high_bits,)) * 32)
        return self._do_pak_write(addr | 0xc000, data)


def cmd_identify_pak(controller):
    if not controller.has_pak():
        print('No Pak inserted.')
    elif controller.pak_is_transfer_pak():
        print('Transfer Pak inserted.')
    elif controller.pak_is_rumble_pak():
        print('Rumble Pak inserted.')
    else:
        print('Controller Pak inserted.')


def cmd_dump_controller_pak(controller):
    if not controller.has_pak():
        sys.stderr.write('No Pak inserted.\n')
        sys.exit(1)

    if controller.pak_is_transfer_pak() or controller.pak_is_rumble_pak():
        sys.stderr.write('Incorrect Pak inserted.\n')
        sys.exit(1)

    for addr in range(0, 0x8000, 32):
        sys.stdout.buffer.write(controller._do_pak_read(addr))


def cmd_restore_controller_pak(controller):
    if not controller.has_pak():
        sys.stderr.write('No Pak inserted.\n')
        sys.exit(1)

    if controller.pak_is_transfer_pak() or controller.pak_is_rumble_pak():
        sys.stderr.write('Incorrect Pak inserted.\n')
        sys.exit(1)

    for addr in range(0, 0x8000, 32):
        controller._do_pak_write(addr, sys.stdin.buffer.read(32))


@contextmanager
def tpak_setup(controller):
    if not controller.has_pak():
        sys.stderr.write('No Pak inserted.\n')
        sys.exit(1)

    if not controller.pak_is_transfer_pak():
        sys.stderr.write('Incorrect Pak inserted.\n')
        sys.exit(1)

    controller.tpak_set_power(True)
    try:
        if not controller.tpak_detect_pak():
            sys.stderr.write('No cartridge inserted.\n')
            sys.exit(1)

        yield

    finally:
        controller.tpak_set_power(False)


@contextmanager
def tpak_ram_enabled(controller):
    controller.tpak_write(0x0000, bytes((0x0a,)) * 32)
    try:
        yield
    finally:
        controller.tpak_write(0x0000, bytes((0x00,)) * 32)


# Amount of RAM, in bytes, for values of the ROM header's RAM size byte.
RAM_SIZE_CODES = {0: 0, 1: 512, 2: 8192, 3: 32768, 4: 131072}
def ram_size_code_to_bytes(code):
    '''
    Convert a value of the Game Boy ROM header's RAM size byte into
    a number of bytes of RAM. 0 means no RAM. -1 means unrecognized byte.
    '''
    return RAM_SIZE_CODES.get(code, -1)


def cmd_dump_cartridge_sram(controller):
    with tpak_setup(controller):
        ram_code = controller.tpak_read(0x0140)[9]
        ram_bytes = ram_size_code_to_bytes(ram_code)
        if ram_bytes == -1:
            sys.stderr.write('Unrecognized RAM code.\n')
            sys.exit(1)
        elif ram_bytes == 0:
            sys.stderr.write('Cartridge has no RAM.\n')
            sys.exit(1)

        with tpak_ram_enabled(controller):
            if ram_bytes < 0x2000:
                for addr in range(0xa000, 0xa000 + ram_bytes, 32):
                    sys.stdout.buffer.write(controller.tpak_read(addr))
            else:
                banks = ram_bytes // 0x2000
                for i in range(banks):
                    controller.tpak_write(0x4000, bytes((i,)) * 32)
                    for addr in range(0xa000, 0xc000, 32):
                        sys.stdout.buffer.write(controller.tpak_read(addr))


def cmd_restore_cartridge_sram(controller):
    with tpak_setup(controller):
        ram_code = controller.tpak_read(0x0140)[9]
        ram_bytes = ram_size_code_to_bytes(ram_code)
        if ram_bytes == -1:
            sys.stderr.write('Unrecognized RAM code.\n')
            sys.exit(1)
        elif ram_bytes == 0:
            sys.stderr.write('Cartridge has no RAM.\n')
            sys.exit(1)

        with tpak_ram_enabled(controller):
            if ram_bytes < 0x2000:
                for addr in range(0xa000, 0xa000 + ram_bytes, 32):
                    controller.tpak_write(addr, sys.stdin.buffer.read(32))
            else:
                banks = ram_bytes // 0x2000
                for i in range(banks):
                    controller.tpak_write(0x4000, bytes((i,)) * 32)
                    for addr in range(0xa000, 0xc000, 32):
                        controller.tpak_write(addr, sys.stdin.buffer.read(32))


if __name__ == '__main__':
    controller = N64Controller()
    if sys.argv[1] == 'identify-pak':
        cmd_identify_pak(controller)
    elif sys.argv[1] == 'dump-controller-pak':
        cmd_dump_controller_pak(controller)
    elif sys.argv[1] == 'restore-controller-pak':
        cmd_restore_controller_pak(controller)
    elif sys.argv[1] == 'dump-cartridge-sram':
        cmd_dump_cartridge_sram(controller)
    elif sys.argv[1] == 'restore-cartridge-sram':
        cmd_restore_cartridge_sram(controller)
    else:
        sys.stderr.write('Unrecognized command.\n')
        sys.exit(1)
    sys.exit(0)
