This project uses an Arduino to exchange data with a Nintendo 64
controller. Data passed to the Arduino over its serial interface
is transmitted to the controller, then the controller's response is
returned over the serial interface. A Python script is included for
interacting in certain ways with devices in the controller's expansion
port; it includes (and uses) a class with methods wrapping each known raw
command and providing some functionality on top of that for interacting
with expansion devices.

To use the Arduino part, once the code is uploaded connect the N64
controller's 3.3V and ground lines to the expected places, connect
the data line to pin 2 (changeable in `param.h`), and open the serial
interface at 115200 8N1. Transmit a two-byte header (length of raw command
and length of expected response) and the raw command to be sent to the
controller, and the controller's response will be sent back, with no
header. You will always get the number of response bytes you indicated
you were expecting; bytes beyond the number that the controller actually
sent are undefined.

(For example, to query the controller's buttons, send `01 04 01`, and
you will get back the four bytes the controller sends back.)

The main difference between this and other projects I found for
interacting with N64 controllers is that this implements only the bare
minimum that is necessary on the Arduino and leaves everything else to
the host machine. I feel that this has advantages over doing everything
on the Arduino, especially when it comes to flexibility, testing, and
interactive experimentation with the controller.

Building
--------

The Makefile includes Arduino.mk from the path where the Debian
`arduino-mk` package puts it. This path may need to be modified.

`BOARD_TAG` is not set in the Makefile because this should be able to work
with many Arduino boards. Specify it on the command line - something like:

    make BOARD_TAG=mega2560 upload

The Arduino used must be AVR-based with a clock rate of 16 MHz; this is
checked at compile time. Patches making it work at other clock rates
are welcome.

My use case
-----------

I did this project mainly to read and write savefiles from Game Boy
cartridges through a Transfer Pak. This was part of the setup for
shenanagans_' Pokémon glitch showcase at AGDQ 2016, whose finale involved
a specially preconstructed savefile made by luckytyphlosion. For more
information, see: <blog link TODO>

To do
-----

The Python script probably has many bugs, especially in fully handling
expansion devices. I don't have a Rumble Pak, so I can't test that it
can really distinguish those from Controller Paks and Transfer Paks
(which I do have); I went by what other code does.
