# -------------------------------------------------------------------------------
# authors: Florian Stechmann, Saurabh Band, Malavika Unnikrishnan
# date: 13.10.2022
# function: Code for esp32 board with lora module and sd card reader.
#           Needed SD Card format is W95 FAT32 (LBA).
#           Same as main_scratch.py, Raw LoRa plus retransmission plus
#           random back-off.
# -------------------------------------------------------------------------------

from machine import Pin, I2C, SoftSPI, Timer, UART
import machine
import micropython
import ustruct, ubinascii, uhashlib
import time
import random

from scd30 import SCD30
from lora import LoRa
from mcp3221 import MCP3221
from bmp180 import BMP180
from am2301 import AM2301

# ------------------------ function declaration -------------------------------


def measure_scd30(stat):
    """
    Takes CO2 reading.
    """
    try:
        if scd30.get_status_ready() == 1:
            SENSOR_DATA[0] = round(scd30.read_measurement()[0], 2)
            CONNECTION_VAR[stat] = 1
    except Exception as e:
        CONNECTION_VAR[stat] = 0
        write_to_log("CO2 error: {}".format(e),
                     str(time.mktime(time.localtime())))


def measure_co(stat):
    """
    Takes CO reading.
    """
    try:
        SENSOR_DATA[1] = MCP_CO.read_measurement_co()
        CONNECTION_VAR[stat] = 1
    except Exception as e:
        CONNECTION_VAR[stat] = 0
        write_to_log("CO error: {}".format(e),
                     str(time.mktime(time.localtime())))


def measure_o2(stat):
    """
    Takes O2 reading.
    """
    try:
        SENSOR_DATA[2] = MCP_O2.read_measurement_o2()
        CONNECTION_VAR[stat] = 1
    except Exception as e:
        CONNECTION_VAR[stat] = 0
        write_to_log("O2 error: {}".format(e),
                     str(time.mktime(time.localtime())))


def measure_bmp(stat):
    """
    Takes pressure reading.
    """
    try:
        SENSOR_DATA[3] = BMP.pressure
        CONNECTION_VAR[stat] = 1
    except Exception as e:
        CONNECTION_VAR[stat] = 0
        write_to_log("BMP error: {}".format(e),
                     str(time.mktime(time.localtime())))


def measure_am1(stat):
    """
    Temp & humidity sensor 1 reading.
    """
    global am_temp, am_hum
    try:
        am_temp, am_hum = AM2301_1.read_measurement()
        CONNECTION_VAR[stat] = 1
    except Exception as e:
        CONNECTION_VAR[stat] = 0
        write_to_log("AM1 error: {}".format(e),
                     str(time.mktime(time.localtime())))


def measure_am2(stat):
    """
    Temp & humidity sensor 2 reading.
    """
    global am_temp, am_hum
    try:
        am_temp, am_hum = AM2301_2.read_measurement()
        CONNECTION_VAR[stat] = 1
    except Exception as e:
        CONNECTION_VAR[stat] = 0
        write_to_log("AM2 error: {}".format(e),
                     str(time.mktime(time.localtime())))


def measure_am3(stat):
    """
    Temp & humidity sensor 3 reading.
    """
    global am_temp, am_hum
    try:
        am_temp, am_hum = AM2301_3.read_measurement()
        CONNECTION_VAR[stat] = 1
    except Exception as e:
        CONNECTION_VAR[stat] = 0
        write_to_log("AM3 error: {}".format(e),
                     str(time.mktime(time.localtime())))


def measure_am4(stat):
    """
    Temp & humidity sensor 4 reading.
    """
    global am_temp, am_hum
    try:
        am_temp, am_hum = AM2301_4.read_measurement()
        CONNECTION_VAR[stat] = 1
    except Exception as e:
        CONNECTION_VAR[stat] = 0
        write_to_log("AM4 error: {}".format(e),
                     str(time.mktime(time.localtime())))


def cb_hb(p):
    """
    Callback for the sending of msgs every btw 20s-40s.
    """
    global cb_hb_done
    cb_hb_done = True


def cb_retrans(p):
    """
    Callback for resending msgs.
    """
    global cb_retrans_done
    cb_retrans_done = True


def lora_scheduled(r_msg):
    """
    Scheduled lora callback.
    """
    global cb_lora_recv, rcv_msg
    cb_lora_recv = True
    rcv_msg.append(r_msg)


def cb_lora(p):
    """
    Schedules lora callback.
    """
    micropython.schedule(lora_scheduled, p)


def crc32(crc, p, len):
    """
    crc = 0
    p = message
    len = length of msg
    """
    crc = 0xffffffff & ~crc
    for i in range(len):
        crc = crc ^ p[i]
        for j in range(8):
            crc = (crc >> 1) ^ (0xedb88320 & -(crc & 1))
    return 0xffffffff & ~crc


def write_to_log(msg, timestamp):
    """
    Write a given Message to the file log.txt. If UART is establshed.
    Otherwise doesn't do a thing.
    """
    if UART_ESTABLISHED:
        uart_msg = msg + "\t" + timestamp + "\n"
        uart.write(uart_msg.encode())


def add_to_que(msg, current_time):
    """
    Adds given msg to the que with a given timestamp
    """
    global que
    if len(que) >= MAX_QUEUE:
        # pop the packet from the end of que (the oldest packet)
        que.pop()
        # add the newest msg at the front of que
        que = [(msg, current_time)] + que
    else:
        que = [(msg, current_time)] + que


def get_nodename():
    """
    Retuns the unique_id of the esp32.
    """
    uuid = ubinascii.hexlify(machine.unique_id()).decode()
    node_name = "ESP_" + uuid
    return node_name


def get_node_id(hex=False):
    """
    Get node id, which consists of four bytes unsigned int.
    Return as hex, according to parameter.
    """
    node_id = ubinascii.hexlify(uhashlib.sha1(
        machine.unique_id()).digest()).decode("utf-8")[-8:]
    if hex:
        return node_id
    else:
        return int(node_id, 16)


def cb_redundancy(p):
    global cb_redundancy_done
    cb_redundancy_done = True


def lora_rcv_exec(p):
    """
    Processed all received msgs.
    """
    global cb_lora_recv, rcv_msg, cb_redundancy_done, redun_timer_reset, packet_no #start_process
    if cb_lora_recv:
        cb_lora_recv = False
        for i in range(len(rcv_msg)):
            msg = rcv_msg[i]
            print('received:', len(msg))
            try:
                if len(msg) == MESSAGE_LENGTH:
                    received_crc = ustruct.unpack(">L", msg[-4:])[0]
                    if received_crc != crc32(0, msg[:-4], MESSAGE_LENGTH-4):
                        print("Invalid CRC32 in msg")
                    else:
                        # exclude timstamp and crc (8 bytes) to get msg
                        values = ustruct.unpack(_pkng_frmt, msg[:-12])
                        id_received = values[16]
                        packet_no_received = values[15]
                        timestamp_sent = list(ustruct.unpack(">L", msg[-8:-4]))[0]
                        timestamp_retr = list(ustruct.unpack(">L", msg[-12:-8]))[0]
                        if id_received == 94420780:
                            print(id_received)
                            print('timestamps', timestamp_sent, timestamp_retr)
                            # if start_process:     ### check if first packet received from the PB to start timer
                            if timestamp_sent - timestamp_retr == 0:
                                redun_timer_reset = True
                                timer_redun.deinit()
                                packet_no = packet_no_received
                            else:
                                print('retransmitted')
                            # else:
                            #     start_process = True
                            #     redun_timer_reset = True
            except Exception as e:
                write_to_log("Lora msg process failure: {}".format(e),
                             str(time.mktime(time.localtime())))
        rcv_msg = []


# ------------------------ constants and variables ----------------------------
# addresses of sensors
O2_ADRR = const(0x48)
CO_ADRR = const(0x49)
SCD30_ADRR = const(0x61)
AM2301_1_ADRR = const(0)
AM2301_2_ADRR = const(4)
AM2301_3_ADRR = const(13)  # 17 -> 13
AM2301_4_ADRR = const(15)  # 16 -> 15
UART_TX = const(17)
UART_RX = const(16)

# maximum number of values in queue
MAX_QUEUE = const(10)

# connection_variables init for sensors
CONNECTION_CO2 = 1
CONNECTION_CO = 1
CONNECTION_O2 = 1
CONNECTION_BMP = 1
CONNECTION_A1 = 1
CONNECTION_A2 = 1
CONNECTION_A3 = 1
CONNECTION_A4 = 1
UART_ESTABLISHED = 1
LORA_ESTABLISHED = 1
I2C_ESTABLISHED = 1

# initial values for scd and AMs
am_temp = 0
am_hum = 0

# list for measurements values
que = []

# init cb booleans
cb_hb_done = False
cb_retrans_done = False
cb_lora_recv = False
cb_redundancy_done = False   ### True: will tx pkts, False: will tx hb  
redun_timer_reset = False     ### to indicate if timer complete or packet received
# start_process = False
# process_start_count = 1

# initial msg sending intervals
# select time randomly with steps of 1000ms, because the
# max on air time is 123ms and 390ms for SF7 and SF9 resp.
msg_interval = random.randrange(8000, 12000, 130)
# select random time interval with step size of 1 sec
retx_interval = 3000

MESSAGE_LENGTH = 76

# init process variables
retransmit_count = 0
packet_no = 0

# msg init
msg = ""

# rcv_msg init
rcv_msg = []

# msg for log file
start_msg = "Boot process was successfull! Starting initialization..."
status_msg = "Current connection variables (CO2, CO, O2, BMP, AMs): "

# packing format
_pkng_frmt = ">13f2H2I"

# package format for ack
_pkng_frmt_ack = ">2H3I"  # 16 bytes for ack

# unique node id for sender identification
SENSORBOARD_ID = get_node_id()

# allcoate emergeny buffer for interrupt signals
micropython.alloc_emergency_exception_buf(100)

# thresshold limits
THRESHOLDS = ((0.0, 3000.0),
              (0.0, 20.0),
              (18, 23.0),
              (950.0, 1040.0),
              (18.0, 30.0, 0.0, 100.0))

# connectionvaribles for each sensor
CONNECTION_VAR = [CONNECTION_CO2, CONNECTION_CO,
                  CONNECTION_O2, CONNECTION_BMP,
                  CONNECTION_A1, CONNECTION_A2,
                  CONNECTION_A3, CONNECTION_A4]

# list with all sensor names for log purposes
SENSORS_LIST = ("CO2", "CO", "O2", "BMP", "AM1", "AM2", "AM3", "AM4")

# functions for taking sensor readings
FUNC_VAR = (measure_scd30, measure_co, measure_o2, measure_bmp,
            measure_am1, measure_am2, measure_am3, measure_am4)

# # create Timers
timer0 = Timer(0)
# timer1 = Timer(1)
timer_redun = Timer(2)

# sensor readings list init
SENSOR_DATA = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

# ------------------------ establish connections ------------------------------
# establish UART connection
try:
    uart = UART(1, baudrate=9600, tx=UART_TX, rx=UART_RX)
    uart_msg = start_msg + " UART establshed"
    write_to_log(uart_msg, str(time.mktime(time.localtime())))
except Exception:
    UART_ESTABLISHED = 0

# establish I2C Bus
try:
    I2CBUS = I2C(1, sda=Pin(21), scl=Pin(22), freq=100000)
    write_to_log("I2C establshed", str(time.mktime(time.localtime())))
except Exception:
    I2C_ESTABLISHED = 0
    write_to_log("I2C init failed", str(time.mktime(time.localtime())))

# establish SPI Bus and LoRa (SX1276)
try:
    SPI_BUS = SoftSPI(baudrate=10000000, sck=Pin(18, Pin.OUT),
                      mosi=Pin(23, Pin.OUT), miso=Pin(19, Pin.IN))
    write_to_log("SPI established", str(time.mktime(time.localtime())))
    lora = LoRa(SPI_BUS, True, cs=Pin(5, Pin.OUT), rx=Pin(2, Pin.IN))
    write_to_log("LoRa established", str(time.mktime(time.localtime())))
except Exception:
    LORA_ESTABLISHED = 0
    write_to_log("SPI and LoRa init failed",
                 str(time.mktime(time.localtime())))

# create sensorobjects
try:
    scd30 = SCD30(I2CBUS, SCD30_ADRR)
    scd30.start_continous_measurement()
    write_to_log("CO2 initialized", str(time.mktime(time.localtime())))
except Exception:
    CONNECTION_CO2 = 0
    write_to_log("CO2 init failed", str(time.mktime(time.localtime())))

try:
    MCP_CO = MCP3221(I2CBUS, CO_ADRR)
    write_to_log("CO initialized", str(time.mktime(time.localtime())))
except Exception:
    CONNECTION_CO = 0
    write_to_log("CO init failed", str(time.mktime(time.localtime())))

try:
    MCP_O2 = MCP3221(I2CBUS, O2_ADRR)
    write_to_log("O2 initialized", str(time.mktime(time.localtime())))
except Exception:
    CONNECTION_O2 = 0
    write_to_log("O2 failed", str(time.mktime(time.localtime())))

try:
    BMP = BMP180(I2CBUS)
    write_to_log("pressure initialized", str(time.mktime(time.localtime())))
except Exception:
    CONNECTION_BMP = 0
    write_to_log("pressure failed", str(time.mktime(time.localtime())))

try:
    AM2301_1 = AM2301(AM2301_1_ADRR)
    write_to_log("AM1 initialized", str(time.mktime(time.localtime())))
except Exception:
    CONNECTION_A1 = 0
    write_to_log("AM1 failed", str(time.mktime(time.localtime())))

try:
    AM2301_2 = AM2301(AM2301_2_ADRR)
    write_to_log("AM2 initialized", str(time.mktime(time.localtime())))
except Exception:
    CONNECTION_A2 = 0
    write_to_log("AM2 failed", str(time.mktime(time.localtime())))

try:
    AM2301_3 = AM2301(AM2301_3_ADRR)
    write_to_log("AM3 initialized", str(time.mktime(time.localtime())))
except Exception:
    CONNECTION_A3 = 0
    write_to_log("AM3 failed", str(time.mktime(time.localtime())))

try:
    AM2301_4 = AM2301(AM2301_4_ADRR)
    write_to_log("AM4 initialized", str(time.mktime(time.localtime())))
except Exception:
    CONNECTION_A4 = 0
    write_to_log("AM4 failed", str(time.mktime(time.localtime())))

# ------------------------ infinite loop execution ----------------------------
# initialize timer
# Timer for heartbeat
timer0.init(period=60000, mode=Timer.PERIODIC, callback=cb_hb)
# write_to_log("msg sending timer activated", str(time.mktime(time.localtime())))

timer_redun.init(period=15000, mode=Timer.ONE_SHOT, callback=cb_redundancy)    ### period = tx interval of primary board + 1 (for edge cases)

# set callback for LoRa (recv as scheduled IR)
lora.on_recv(cb_lora)

# get the start time of the script in seconds wrt the localtime
start_time = time.mktime(time.localtime())

write_to_log("start measuring", str(time.mktime(time.localtime())))

while True:
    # get the current time of the script in seconds wrt the localtime
    time.sleep(2)
    current_time = time.mktime(time.localtime())

    if redun_timer_reset:
        timer_redun.init(period=15000, mode=Timer.ONE_SHOT, callback=cb_redundancy)
        redun_timer_reset =  False
        # if process_start_count == 1:
        #     print('Process started')
        #     process_start_count -= 1
        # else:
        #     print('timer reinit flag')

    if not cb_redundancy_done and cb_hb_done:
        rssi = lora.get_rssi()
        hb_msg = ustruct.pack(_pkng_frmt, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0,
                            -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, rssi, 0, 0,
                            0, SENSORBOARD_ID)
        hb_msg += ustruct.pack(">L", current_time)  # add timestamp to the msg
        hb_msg += ustruct.pack(">L", current_time)  # add timestamp to the msg for re-tx check
        hb_msg += ustruct.pack(">L", crc32(0, hb_msg, 72))  # add 32-bit crc
        add_to_que(hb_msg, current_time)
        print('heartbeat')
        lora.send(hb_msg)
        lora.recv()
        micropython.schedule(lora_rcv_exec, 0)  # process received msgs
        cb_hb_done = False
    elif cb_redundancy_done:
        SENSOR_STATUS = 0
        LIMITS_BROKEN = 0
        j = 4  # offset for am values in SENSOR_DATA

        for i in range(len(CONNECTION_VAR)):
            # take readings for all sensors, also note if one is not working
            func_call = FUNC_VAR[i]
            try:
                if i < 4:
                    # readings for CO2, CO, O2 and pressure are taken.
                    micropython.schedule(func_call, i)
                    if not THRESHOLDS[i][0] <= SENSOR_DATA[i] <= THRESHOLDS[i][1]:
                        LIMITS_BROKEN = 0
                else:
                    # AM2301 readings (involves 2 values)
                    micropython.schedule(func_call, i)
                    if not THRESHOLDS[4][0] <= am_temp <= THRESHOLDS[4][1]:
                        LIMITS_BROKEN = 0
                    if not THRESHOLDS[4][2] <= am_hum <= THRESHOLDS[4][3]:
                        LIMITS_BROKEN = 0
                    SENSOR_DATA[j] = am_temp
                    SENSOR_DATA[j+1] = am_hum
                    j += 2
            except Exception as e:
                CONNECTION_VAR[i] = 0
                write_to_log("failed {}: {}".format(SENSORS_LIST[i], e),
                            str(current_time))

            if not CONNECTION_VAR[i]:
                # sensor failed
                if i < 4:
                    SENSOR_STATUS += 2**(i)
                else:
                    SENSOR_STATUS += 2**(i)
        try:
            write_to_log(status_msg+str(CONNECTION_VAR), str(current_time))
            # get rssi for performance information
            rssi = lora.get_rssi()
            packet_no += 1   ### give the next number after the last packet no of primary board
            # prepare data to be sent
            msg = ustruct.pack(_pkng_frmt, SENSOR_DATA[0], SENSOR_DATA[1],
                            SENSOR_DATA[2], SENSOR_DATA[3], SENSOR_DATA[4],
                            SENSOR_DATA[5], SENSOR_DATA[6], SENSOR_DATA[7],
                            SENSOR_DATA[8], SENSOR_DATA[9], SENSOR_DATA[10],
                            SENSOR_DATA[11], rssi, SENSOR_STATUS, LIMITS_BROKEN,
                            packet_no, SENSORBOARD_ID)
            #msg += ustruct.pack(">L", current_time)  # add timestamp to the msg
            # msg += ustruct.pack(">L", crc32(0, msg, 68))  # add 32-bit crc

            micropython.schedule(lora_rcv_exec, 0)  # process received msgs
        except Exception as e:
            write_to_log("error msg packing: {}".format(e), str(current_time))

        if LORA_ESTABLISHED:
            try:
                msg += ustruct.pack(">L", current_time)
                msg += ustruct.pack(">L", current_time)
                msg += ustruct.pack(">L", crc32(0, msg, 72))
                add_to_que(msg, current_time)
                print('packet')
                lora.send(msg)
                lora.recv()
                write_to_log("PKT {} sent, Limits broken".format(packet_no),
                            str(time.mktime(time.localtime())))
            except Exception as e:
                write_to_log("error limits broken: {}".format(e),
                            str(current_time))
            cb_redundancy_done = False
            timer_redun.init(period=15000, mode=Timer.ONE_SHOT, callback=cb_redundancy)
            timer0.deinit() 
            timer0.init(period=60000, mode=Timer.PERIODIC, callback=cb_hb)   
            ### stop the heartbeat timer
            print('TImer reinitialized')
            micropython.schedule(lora_rcv_exec, 0)  # process received msgs

    lora.recv()
    micropython.schedule(lora_rcv_exec, 0)  # process received msgs
        
