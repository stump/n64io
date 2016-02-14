/* n64io: Communication with Nintendo 64 controllers
 * Copyright (C) 2015-2016 stump
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#include "param.h"

/* Communication with the N64 controller occurs over a single,
   bidirectional data line with a self-clocking serial protocol. (The
   other two pins in the connector are +3.3V and ground.) The controller
   has a pullup resistor; data transmission involves either end driving
   the line low. A zero is pulling the line low for 3us and letting
   it go high for 1us, and a one is the same thing with the durations
   switched. Thus, a falling edge is the beginning of a bit, and we can
   look at the line 2us later to get the bit's value, and we have 250
   kbps data transmission. The console end (that's us!) sends commands to
   elicit responses from the controller; each string of bytes in either
   direction is sent, one after the other, high bit first, followed by
   a stop bit (of 1). The controller never transmits except in response
   to commands sent by the console. */

void setup(void)
{
  Serial.begin(115200);
}

/* Transmit cmdlen bytes at cmd to the controller, then receive resplen bytes into resp. */
void n64_txn(unsigned char* cmd, unsigned char cmdlen, unsigned char* resp, unsigned char resplen)
{
  uint8_t port = digitalPinToPort(N64_DATA_PIN);
  uint8_t mask = digitalPinToBitMask(N64_DATA_PIN);
  volatile uint8_t* modereg = portModeRegister(port);
  volatile uint8_t* inreg = portInputRegister(port);
  volatile uint8_t* outreg = portOutputRegister(port);
  uint8_t saved_SREG = SREG;

#if F_CPU != 16000000
#error This implementation requires a CPU clock rate of exactly 16 MHz
#endif

#define NOPS(n) ".rept " #n "\n\tnop\n\t.endr\n\t"
/* The ldi and dec are 1 cycle; the brne is 1 cycle if not taken and
   2 cycles if taken. The code therefore takes exactly n*3 cycles. */
#define THREE_CYCLE_LOOP_IMPL(n, l) \
    "ldi r23, " #n "\n" \
".three_cycle_loop_" l "_%=:\n\t" \
    "dec r23\n\t" \
    "brne .three_cycle_loop_" l "_%=\n\t"
#define TOSTR2(x) #x
#define TOSTR(x) TOSTR2(x)
#define THREE_CYCLE_LOOP(n) THREE_CYCLE_LOOP_IMPL(n, TOSTR(__LINE__))

  __asm__ __volatile__ (
    "cli\n\t"

    /* Ensure PORTn is low, so that in output mode the line is
       driven low, and in input mode the line is tristated. */
    "movw Z, %7\n\t"
    "mov r26, %4\n\t"
    "com r26\n\t"
    "ld r27, Z\n\t"
    "and r27, r26\n\t"
    "st Z, r27\n\t"

    "movw X, %0\n"

    /* Start transmitting a bit. Timing is critical beyond this point. */
".tx_byte_%=:\n\t"
    /* The bit begins 6 cycles after we get here. */
    "movw Z, %5\n\t"          /* 1 cycle */
    "ld __tmp_reg__, Z\n\t"   /* 2 cycles */
    "or __tmp_reg__, %4\n\t"  /* 1 cycle */
    "st Z, __tmp_reg__\n\t"   /* 2 cycles, and we just pulled the line low. */

    /* If cmdlen is zero, we're done transmitting, and this will be the stop bit. */
    "tst %1\n\t"            /* 1 cycle */
    "breq .tx_done_%=\n\t"  /* 1 cycle if not taken, 2 if taken */

    /* Read the byte being sent. */
    "ld r24, X+\n\t"  /* 2 cycles */
    "ldi r25, 7\n"    /* 1 cycle */

".tx_next_bit_%=:\n\t"
    /* Line has been low for 5 cycles. */
    "lsl r24\n\t"               /* 1 cycle */
    "brcs .tx_bit_is_1_%=\n\t"  /* 1 cycle if not taken, 2 if taken */

    /* It's a zero. Line has been low for 7 cycles. */
    THREE_CYCLE_LOOP(12)       /* 36 cycles */
    NOPS(2)
    "eor __tmp_reg__, %4\n\t"  /* 1 cycle */
    "st Z, __tmp_reg__\n\t"    /* 2 cycles, and the line is now high again. */
    "rjmp .tx_bit_done_%=\n"   /* 2 cycles */

".tx_bit_is_1_%=:\n\t"
    /* It's a one. Line has been low for 8 cycles. */
    NOPS(5)
    "eor __tmp_reg__, %4\n\t"  /* 1 cycle */
    "st Z, __tmp_reg__\n\t"    /* 2 cycles, and the line is now high again. */
    NOPS(1)
    THREE_CYCLE_LOOP(11)       /* 33 cycles */
    /* fallthrough */

".tx_bit_done_%=:\n\t"
    /* When we get here, the next falling edge is due in 14 cycles. */
    "tst r25\n\t"                /* 1 cycle */
    "breq .tx_byte_done_%=\n\t"  /* 1 cycle if not taken, 2 if taken */
    NOPS(9)
    "or __tmp_reg__, %4\n\t"     /* 1 cycle */
    "st Z, __tmp_reg__\n\t"      /* 2 cycles, and we just pulled the line low. */
    NOPS(2)
    "dec r25\n\t"                /* 1 cycle */
    "rjmp .tx_next_bit_%=\n\t"   /* 2 cycles */

".tx_byte_done_%=:\n\t"
    /* When we get here, the next falling edge is due in 11 cycles. */
    NOPS(2)
    "dec %1\n\t"          /* 1 cycle */
    "rjmp .tx_byte_%=\n"  /* 2 cycles */

".tx_done_%=:\n\t"
    /* Line has been low for 3 cycles when we get here. */
    NOPS(10)
    "eor __tmp_reg__, %4\n\t"  /* 1 cycle */
    "st Z, __tmp_reg__\n\t"    /* 2 cycles, and the line is now high again. */

    /* Yay, we're done with the timing-critical part!
       Now to receive the response. */
    "movw X, %2\n\t"
    "movw Z, %6\n"

".rx_byte_%=:\n\t"
    "tst %3\n\t"
    "breq .rx_done_%=\n\t"
    "clr r25\n\t"
    "ldi r24, 1\n"  /* when the 1 shifts off the top, we're done the byte */

    /* Wait for input to be high. */
".rx_wait_high_%=:\n\t"
    "inc r25\n\t"
    "breq .rx_abort_wh_%=\n\t"
    "ld __tmp_reg__, Z\n\t"
    "and __tmp_reg__, %4\n\t"
    "breq .rx_wait_high_%=\n"

    /* Wait for input to be low. */
    "clr r25\n"
".rx_wait_low_%=:\n\t"
    "inc r25\n\t"
    "breq .rx_abort_wl_%=\n\t"
    "ld __tmp_reg__, Z\n\t"
    "and __tmp_reg__, %4\n\t"
    "brne .rx_wait_low_%=\n\t"

    /* Wait until the middle of the bit, then sample there. */
    THREE_CYCLE_LOOP(9)
    "ld __tmp_reg__, Z\n\t"
    "and __tmp_reg__, %4\n\t"
    "sec\n\t"
    "cpse __tmp_reg__, %4\n\t"
    "clc\n\t"
    "rol r24\n\t"

    /* Done a byte? */
    "brcc .rx_wait_high_%=\n\t"
".rx_abort_%=:\n\t"
    /* Done a byte. */
    "st X+, r24\n\t"
    "dec %3\n\t"
    "rjmp .rx_byte_%=\n"

".rx_abort_wh_%=:\n\t"
    "ldi r24, 255\n\t"
    "rjmp .rx_abort_%=\n"
".rx_abort_wl_%=:\n\t"
    "ldi r24, 254\n\t"
    "rjmp .rx_abort_%=\n"

".rx_done_%=:\n\t"
    /* All done. */

  : : "r" (cmd), "r" (cmdlen), "r" (resp), "r" (resplen),
      "r" (mask), "r" (modereg), "r" (inreg), "r" (outreg)
    : "r23", "r24", "r25", "r26", "r27", "r30", "r31");

  SREG = saved_SREG;
}

void loop(void)
{
  unsigned char inlen;
  unsigned char outlen;
  unsigned char buf[256];

  while (Serial.available() < 2)
    ;

  inlen = Serial.read();
  outlen = Serial.read();

  if (Serial.readBytes((char*)buf, inlen) == inlen) {
    n64_txn(buf, inlen, buf, outlen);
    Serial.write(buf, outlen);
  }
}
