# coding=utf-8

import sys
import threading
import time
import json
import serial  # 引用pySerial模組
from pynput import keyboard
from datetime import datetime
import queue  # 先进先出队列

# Public and global variable configure zone
COM_PORT = 'COM4'    # 指定通訊埠名稱
BAUD_RATES = 115200    # 設定傳輸速率
ser = serial.Serial(COM_PORT, BAUD_RATES)  # 初始化序列通訊埠
IPS_800_COM_PORT = 'COM3'
IPS_800_BAUD_RATES = 9600
IPS_800_ser = serial.Serial(IPS_800_COM_PORT, IPS_800_BAUD_RATES)
# 最多接收10个数据
uart_send_q = queue.Queue(10)
uart_read_q = queue.Queue(10)
ips_send_q = queue.Queue(1)

status_flag = ["IDLE", "BOOTING", "RUNNING", "HALTED", "UNKNOWN"]
uart_console = {"last_msg": "", "last_timestamp": datetime.now(), "status": status_flag[4]}

# Read boot log into a dictionary before start program.
with open('data.json', 'r') as reader:
    boot_log = json.loads(reader.read())


def info_filter(src_string):
    start = "#INFO#"
    end = "#END#\r\n"
    subtract_prefix = (src_string.split(start))[1]
    subtract_postfix = subtract_prefix.split(end)[0]
    if ':' in subtract_postfix:
        execution_result = subtract_postfix.split(':')[0]
        info_string = subtract_postfix.split(':')[1]
        if execution_result == '0':
            return info_string
        else:
            return 0
    else:
        return subtract_postfix


def search_log(hugedata, searchfor):
    ignoreDict = ['\r\n', '/ # \r\n']
    for key in hugedata.keys():
        if searchfor == hugedata[key] and searchfor not in ignoreDict:
            # update_info_reg(key, "BOOTING")
            return key
    return repr(searchfor)


def on_press(key):
    if key == keyboard.Key.esc:
        return False  # stop listener
    try:
        k = key.char  # single-char keys
    except:
        k = key.name  # other keys

    if k in ['1', '2', 'left', 'right']:  # keys of interest
        print('Key pressed: ' + k)
    if k == '3':
        uart_send_q.put('reboot\r\n')
    if k == '4':
        print(uart_console['status'], uart_console['last_timestamp'])
        # uart_send_q.put('diag ver isp\r\n')
    if k == '5':
        uart_send_q.put('sh /sdk/insmod_rndis.sh\r\n')
        uart_send_q.put('ifconfig usb0 192.168.100.99\r\n')
        # uart_send_q.put('diag hw pcba\r\n')
        # uart_send_q.put('diag factory poweroff\r\n')
    if k == '6':
        # is_idle()
        ips_send_q.put('/ON 5\r')
    if k == '7':
        # is_idle()
        uart_send_q.put('diag factory poweroff\r\n')
        ips_send_q.put('/OFF 5\r')
    if k == 'q':
        ser.close()
        for idx in range(3):
            threads[idx].do_run = False
        sys.exit()


# 子執行緒的工作函數
def job_uart_read(arg, serialDev):
    t = threading.currentThread()
    # print ("working on %s" % arg)

    # Force to convert system encoding
    reload(sys)
    sys.setdefaultencoding('utf-8')

    while getattr(t, "do_run", True):
        while serialDev.in_waiting:          # 若收到序列資料…
            data_raw = serialDev.readline()  # 讀取一行
            # data = data_raw.decode()   # 用預設的UTF-8解碼
            # print('%s %s' % (datetime.now(), repr(data_raw)))  # Escape newline characters
            uart_read_q.put(data_raw)
        time.sleep(0.1)
    # print("Stopping job %s." % arg)


def job_uart_send(arg, serialDev):
    t = threading.currentThread()
    # print ("working on %s" % arg)

    while getattr(t, "do_run", True):
        if not uart_send_q.empty():
            send_str = uart_send_q.get()
            if len(send_str) is not 0:
                # print(send_str)
                serialDev.writelines(send_str)
        if not ips_send_q.empty():
            send_str = ips_send_q.get()
            if len(send_str) is not 0:
                # print(send_str)
                IPS_800_ser.writelines(send_str)

# To prevent while consuming too much cpu usage.
        time.sleep(0.1)
    # print("Stopping job %s." % arg)


def job_uart_parser(arg):
    t = threading.currentThread()
    # print ("working on %s" % arg)
    pass_count = 0

    while getattr(t, "do_run", True):
        while not uart_read_q.empty():
            data = uart_read_q.get()
            # print(repr(data))
            check_booting(data)
            if check_string_match(data, "100%"):
                pass_count += 1
                print("+----------------+")
                print("|      PASS      |")
                print("+----------------+")
                print("Pass Count: %d" % pass_count)
                print('%s %s %s' % (datetime.now(), "Stop Testing", uart_console["status"]))
                ips_send_q.put('/OFF 5\r')
                print('%s %s %s' % (datetime.now(), "AC Power OFF", uart_console["status"]))
                print("----------------------------------------------------------------")
                update_uart_console_reg("status", "HALTED")  # HALTED
            if check_string_match(data, "SigmaStar # \r\n"):
                uart_send_q.put('reset\r\n')
        # To prevent while consuming too much cpu usage.
        time.sleep(0.1)
    # print("Stopping job %s." % arg)


def job_auto_test(arg):
    t = threading.currentThread()
    # print ("working on %s" % arg)
    halted_count = 0
    freeze_count = 0

    while getattr(t, "do_run", True):
        # print("----- new loop start -----")
        if uart_console["status"] == "WAITING":
            print("I am waiting")
            time.sleep(1)
            continue
        if uart_console["status"] == "HALTED" or uart_console["status"] == "UNKNOWN":
            print('%s %s %s' % (datetime.now(), "AC Power ON", uart_console["status"]))
            ips_send_q.put('/ON 5\r')
            time.sleep(1)
            update_uart_console_reg("status", "RUNNING")

        if uart_console["status"] == "BOOTING" or uart_console["status"] == "RUNNING":
            if uart_console["status"] == "RUNNING":  # and is_idle():
                # print("last message %s" % repr(uart_console["last_msg"]))
                if is_idle():
                    uart_console["status"] = "IDLE"
                else:
                    freeze_count += 1
                if freeze_count >= 1:
                    freeze_count = 0
                    do_power_reset()
            time.sleep(1)
            print('.'),
            continue
        else:
            print('%s %s %s' % (datetime.now(), "Start Testing", uart_console["status"]))

        if uart_console["status"] == "HALTED":
            halted_count += 1
            time.sleep(0.5)
            if halted_count >= 3:
                do_power_reset()
                halted_count = 0
                print('%s %s %s' % (datetime.now(), "AC Power Reset", uart_console["status"]))
            continue

        if uart_console["status"] == "IDLE":
            print('%s %s %s' % (datetime.now(), "Send cmd: isnmod", uart_console["status"]))
            uart_send_q.put('sh /sdk/insmod_rndis.sh\r\n')
            print('%s %s %s' % (datetime.now(), "Send cmd: ifconfig", uart_console["status"]))
            uart_send_q.put('ifconfig usb0 192.168.100.99\r\n')
            print('%s %s %s' % (datetime.now(), "Send cmd: tftp send file", uart_console["status"]))
            uart_send_q.put('tftp -p -l /config/pega/test.raw 192.168.100.200 -b 20000\r\n')
            print('%s %s %s' % (datetime.now(), "Send cmd: diag factory poweroff", uart_console["status"]))
            uart_send_q.put('diag factory poweroff\r\n')
            # time.sleep(3)
            # update_uart_console_reg("status", "HALTED")  # HALTED
            update_uart_console_reg("status", "WAITING")  # HALTED
        # while not is_idle():
        #     print(uart_console_reg["status"])
        #     time.sleep(1)
        # if uart_console["status"] == "BOOTING":
        #     print("----- STOP ME -----")
        #     continue
        # To prevent while consuming too much cpu usage.
        time.sleep(0.5)
    # print("Stopping job %s." % arg)


def check_booting(console_log):
    time_sec_diff = 0
    time_sec_diff = (datetime.now() - uart_console['last_timestamp']).total_seconds()
    # if time_sec_diff > 1:
    #     print("is_booting waiting 1 second.")

    match_result = search_log(boot_log, console_log)
    if isinstance(match_result, unicode):
        # print(repr(console_log))
        update_uart_console_reg("status", "BOOTING")
        # print("*"),

    BOOT_FINISHED_PATTERN = "#INFO#DIAG_START#END#\r\n"
    if console_log == BOOT_FINISHED_PATTERN:
        update_uart_console_reg("status", "IDLE")
        print('\n%s %s' % (datetime.now(), "Boot Finished!"))

    # if time_sec_diff > 0:
    #     print(time_sec_diff)
    update_uart_console_reg("last_msg", console_log)
    update_uart_console_reg("last_timestamp", datetime.now())

    return 0


def check_string_match(console_log, keyword):
    if keyword in console_log:
        return 1
    return 0


def do_power_reset():
    print('%s %s %s' % (datetime.now(), "Call do_power_reset()", repr(uart_console["last_msg"])))

    ips_send_q.put('/OFF 5\r')
    time.sleep(0.6)
    ips_send_q.put('/ON 5\r')

    return 0


def is_idle():
    if uart_console["last_msg"] != "Auto-Negotiation...":
        uart_send_q.put('\r\n')
        time.sleep(0.5)
        # print(uart_console["last_msg"])
        last_reply = (datetime.now() - uart_console["last_timestamp"]).total_seconds()
        if last_reply < 1 and uart_console["last_msg"] == "/ # \r\n":
            # print('%s %s %s' % (datetime.now(), "running id_idle()", uart_console["status"]))
            return 1
    return 0


def update_uart_console_reg(target, data):
    if target == "last_msg":
        uart_console['last_msg'] = data
    if target == "last_timestamp":
        uart_console['last_timestamp'] = data
    if target == "status":
        # print("Change status to %s" % data)
        uart_console['status'] = data  # status_flag = ["IDLE", "BOOTING", "RUNNING", "HANGUP"]
    return 0


# 建立 4 個子執行緒
threads = [
    threading.Thread(target=job_uart_read, args=("Uart Read Thread", ser,)),
    threading.Thread(target=job_uart_send, args=("Uart Send Thread", ser,)),
    threading.Thread(target=job_auto_test, args=("Auto Testing Thread",)),
    threading.Thread(target=job_uart_parser, args=("Uart Parser",))
]
# for i in range(5):
#     threads.append(threading.Thread(target=job, args=(i,)))
#     threads[i].start()
threads[0].start()  # Uart read Thread
threads[1].start()  # Uart send Thread
threads[2].start()  # Auto Testing Thread
threads[3].start()  # Uart Parser Thread

# 主執行緒繼續執行自己的工作
# ...
listener = keyboard.Listener(on_press=on_press)
listener.start()  # start to listen on a separate thread
listener.join()  # remove if main thread is polling self.keys
# 等待所有子執行緒結束
for i in range(3):
    threads[i].join()

# print("Done.")
