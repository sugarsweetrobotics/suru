/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 sugarsweetrobotics(runtime/LICENSE)
 *
 * 「小さい する」の実行時ライブラリ(AVR、ATmega328P: Arduino Uno・Nano)。
 * main で時計・PWM・AD 変換・シリアル(9600)を用意して、する のプログラム(suru_main)を呼ぶ。
 * 文字列の定数はフラッシュにある(pgm_read_byte で読む)。数は 32 ビット(long)。
 * ピンの番号は Arduino と同じ: 0〜7 は PORTD、8〜13 は PORTB、14〜19(A0〜A5)は PORTC。
 */
#ifndef F_CPU
#define F_CPU 16000000UL
#endif

#include <avr/interrupt.h>
#include <avr/io.h>
#include <avr/pgmspace.h>
#include <util/delay.h>

void suru_main(void);

/* ---------------- 時計(タイマー0 の溢れ、約 1.024ms ごと) ---------------- */

static volatile unsigned long ms_count;
static volatile unsigned char ms_fract;
static volatile unsigned long ovf_count;

ISR(TIMER0_OVF_vect) {
    unsigned long m = ms_count;
    unsigned char f = ms_fract;
    m += 1;
    f += 3; /* 1024us のうち 1000 を超えた 24us を 8us 単位で数える */
    if (f >= 125) {
        f -= 125;
        m += 1;
    }
    ms_fract = f;
    ms_count = m;
    ovf_count++;
}

long mcu_millis(void) {
    unsigned long m;
    unsigned char s = SREG;
    cli();
    m = ms_count;
    SREG = s;
    return (long)m;
}

long mcu_micros(void) {
    unsigned long o;
    unsigned char t, s = SREG;
    cli();
    o = ovf_count;
    t = TCNT0;
    if ((TIFR0 & _BV(TOV0)) && t < 255) o++;
    SREG = s;
    return (long)(((o << 8) + t) * (64 / (F_CPU / 1000000UL)));
}

void mcu_delay_ms(long ms) {
    if (ms <= 0) return;
    unsigned long start = (unsigned long)mcu_millis();
    while ((unsigned long)mcu_millis() - start < (unsigned long)ms) {
    }
}

void mcu_delay_us(long us) {
    while (us-- > 0) _delay_us(1);
}

/* ---------------- シリアル(USART0) ---------------- */

void mcu_serial_begin(long baud) {
    unsigned int ubrr = (unsigned int)((F_CPU / 4 / (unsigned long)baud - 1) / 2);
    UCSR0A = _BV(U2X0);
    UBRR0H = ubrr >> 8;
    UBRR0L = ubrr & 0xff;
    UCSR0B = _BV(TXEN0) | _BV(RXEN0);
    UCSR0C = _BV(UCSZ01) | _BV(UCSZ00);
}

static void put(char c) {
    while (!(UCSR0A & _BV(UDRE0))) {
    }
    UDR0 = c;
}

long mcu_serial_read(void) {
    if (UCSR0A & _BV(RXC0)) return UDR0;
    return -1;
}

void suru_newline(void) {
    put('\r');
    put('\n');
}

void suru_put_str(const char *p) {
    char c;
    while ((c = pgm_read_byte(p++)) != 0) put(c);
}

void suru_put_int(long n) {
    char buf[12];
    int i = 0;
    unsigned long u = n < 0 ? 0UL - (unsigned long)n : (unsigned long)n;
    do {
        buf[i++] = (char)('0' + u % 10);
        u /= 10;
    } while (u);
    if (n < 0) put('-');
    while (i > 0) put(buf[--i]);
}

static const char S_TRUE[] PROGMEM = "真";
static const char S_FALSE[] PROGMEM = "偽";

void suru_put_bool(long b) { suru_put_str(b ? S_TRUE : S_FALSE); }

/* ---------------- エラー: シリアルに出して止まる ---------------- */

static void stop(void) {
    cli();
    for (;;) {
    }
}

static const char S_ERR[] PROGMEM = "エラー(";
static const char S_LINE[] PROGMEM = "行目): ";
static const char S_DIV0[] PROGMEM = "0 で割ることはできません";
static const char S_NOMATCH[] PROGMEM = "に当てはまる場合がありません";
static const char S_QUOTE_L[] PROGMEM = "「";
static const char S_QUOTE_R[] PROGMEM = "」";

static void error_head(long line) {
    suru_put_str(S_ERR);
    suru_put_int(line);
    suru_put_str(S_LINE);
}

void suru_no_match(const char *name, long line) {
    error_head(line);
    suru_put_str(S_QUOTE_L);
    suru_put_str(name);
    suru_put_str(S_QUOTE_R);
    suru_put_str(S_NOMATCH);
    suru_newline();
    stop();
}

/* ---------------- 算術 ---------------- */

long suru_floordiv(long a, long b, long line) {
    if (b == 0) {
        error_head(line);
        suru_put_str(S_DIV0);
        suru_newline();
        stop();
    }
    long q = a / b, r = a % b;
    if (r != 0 && ((r < 0) != (b < 0))) q -= 1;
    return q;
}

long suru_floormod(long a, long b, long line) {
    if (b == 0) {
        error_head(line);
        suru_put_str(S_DIV0);
        suru_newline();
        stop();
    }
    long r = a % b;
    if (r != 0 && ((r < 0) != (b < 0))) r += b;
    return r;
}

long suru_pow(long x, long y) {
    long acc = 1;
    if (y < 0) return 0;
    while (y > 0) {
        if (y & 1) acc *= x;
        x *= x;
        y >>= 1;
    }
    return acc;
}

long suru_abs(long x) { return x < 0 ? -x : x; }

/* ---------------- ピン ---------------- */

static volatile uint8_t *port_of(long pin, uint8_t *bit) {
    if (pin >= 0 && pin <= 7) {
        *bit = _BV(pin);
        return &PORTD;
    }
    if (pin >= 8 && pin <= 13) {
        *bit = _BV(pin - 8);
        return &PORTB;
    }
    if (pin >= 14 && pin <= 19) {
        *bit = _BV(pin - 14);
        return &PORTC;
    }
    return 0;
}

/* PORTx の1つ前が DDRx、2つ前が PINx(ATmega328P) */
#define DDR_OF(port) (*((port) - 1))
#define PIN_OF(port) (*((port) - 2))

static void pwm_off(long pin);

/* mode: 0 入力、1 出力、2 引き上げつきの入力 */
void mcu_pin_mode(long pin, long mode) {
    uint8_t bit;
    volatile uint8_t *port = port_of(pin, &bit);
    if (!port) return;
    uint8_t s = SREG;
    cli();
    if (mode == 1) {
        DDR_OF(port) |= bit;
    } else {
        DDR_OF(port) &= ~bit;
        if (mode == 2)
            *port |= bit;
        else
            *port &= ~bit;
    }
    SREG = s;
}

void mcu_pin_write(long pin, long v) {
    uint8_t bit;
    volatile uint8_t *port = port_of(pin, &bit);
    if (!port) return;
    pwm_off(pin);
    uint8_t s = SREG;
    cli();
    if (v)
        *port |= bit;
    else
        *port &= ~bit;
    SREG = s;
}

void mcu_pin_toggle(long pin) {
    uint8_t bit;
    volatile uint8_t *port = port_of(pin, &bit);
    if (!port) return;
    pwm_off(pin);
    PIN_OF(port) = bit; /* PINx に 1 を書くと反転する */
}

long mcu_pin_read(long pin) {
    uint8_t bit;
    volatile uint8_t *port = port_of(pin, &bit);
    if (!port) return 0;
    return (PIN_OF(port) & bit) ? 1 : 0;
}

/* ---------------- AD 変換(A0〜A5 → 0〜1023) ---------------- */

long mcu_analog_read(long ch) {
    if (ch >= 14) ch -= 14;
    ADMUX = _BV(REFS0) | (ch & 7);
    ADCSRA |= _BV(ADSC);
    while (ADCSRA & _BV(ADSC)) {
    }
    uint8_t lo = ADCL, hi = ADCH;
    return ((long)hi << 8) | lo;
}

/* ---------------- PWM(3・5・6・9・10・11、0〜255) ---------------- */

static void pwm_off(long pin) {
    switch (pin) {
    case 3: TCCR2A &= ~_BV(COM2B1); break;
    case 5: TCCR0A &= ~_BV(COM0B1); break;
    case 6: TCCR0A &= ~_BV(COM0A1); break;
    case 9: TCCR1A &= ~_BV(COM1A1); break;
    case 10: TCCR1A &= ~_BV(COM1B1); break;
    case 11: TCCR2A &= ~_BV(COM2A1); break;
    }
}

void mcu_pwm(long pin, long v) {
    mcu_pin_mode(pin, 1);
    if (v <= 0) {
        mcu_pin_write(pin, 0);
        return;
    }
    if (v >= 255) {
        mcu_pin_write(pin, 1);
        return;
    }
    switch (pin) {
    case 3: TCCR2A |= _BV(COM2B1); OCR2B = v; break;
    case 5: TCCR0A |= _BV(COM0B1); OCR0B = v; break;
    case 6: TCCR0A |= _BV(COM0A1); OCR0A = v; break;
    case 9: TCCR1A |= _BV(COM1A1); OCR1A = v; break;
    case 10: TCCR1A |= _BV(COM1B1); OCR1B = v; break;
    case 11: TCCR2A |= _BV(COM2A1); OCR2A = v; break;
    default: mcu_pin_write(pin, v >= 128);
    }
}

/* ---------------- 始め ---------------- */

int main(void) {
    /* タイマー0: 高速 PWM、64 分周(時計にも使う) */
    TCCR0A = _BV(WGM01) | _BV(WGM00);
    TCCR0B = _BV(CS01) | _BV(CS00);
    TIMSK0 = _BV(TOIE0);
    /* タイマー1: 8 ビットの位相基準 PWM、64 分周 */
    TCCR1A = _BV(WGM10);
    TCCR1B = _BV(CS11) | _BV(CS10);
    /* タイマー2: 位相基準 PWM、64 分周 */
    TCCR2A = _BV(WGM20);
    TCCR2B = _BV(CS22);
    /* AD 変換: 128 分周 */
    ADCSRA = _BV(ADEN) | _BV(ADPS2) | _BV(ADPS1) | _BV(ADPS0);
    mcu_serial_begin(9600);
    sei();
    suru_main();
    /* 最後まで行ったら、送り終わるまで待って止まる */
    while (!(UCSR0A & _BV(UDRE0))) {
    }
    for (;;) {
    }
}
