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
# 最多接收10个数据
uart_send_q = queue.Queue(10)
uart_read_q = queue.Queue(10)

status_flag = ["IDLE", "BOOTING", "RUNNING", "HANGUP"]
uart_console_reg = {"last_msg": "", "last_timestamp": datetime.now(), "status": status_flag[0]}

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
        print(uart_console_reg['status'])
        print(uart_console_reg['last_timestamp'])
        # uart_send_q.put('diag ver isp\r\n')
    if k == '5':
        # uart_send_q.put('sh /sdk/insmod_rndis.sh\r\n')
        # uart_send_q.put('diag hw pcba\r\n')
        uart_send_q.put('diag factory poweroff\r\n')
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
            data = data_raw.decode()   # 用預設的UTF-8解碼
            # print('%s %s' % (datetime.now(), repr(data_raw)))  # Escape newline characters
            uart_read_q.put(data)
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
        # To prevent while consuming too much cpu usage.
        time.sleep(0.1)
    # print("Stopping job %s." % arg)


def job_uart_parser(arg):
    t = threading.currentThread()
    # print ("working on %s" % arg)

    while getattr(t, "do_run", True):
        while not uart_read_q.empty():
            data = uart_read_q.get()
            is_booting(data)
        # To prevent while consuming too much cpu usage.
        time.sleep(0.1)
    # print("Stopping job %s." % arg)


def is_booting(console_log):
    time_sec_diff = 0

    match_result = search_log(boot_log, console_log)
    if isinstance(match_result, unicode):
        # print(len(boot_log))
        # time_sec_diff = (datetime.now() - uart_console_reg['last_timestamp']).total_seconds()
        update_uart_console_reg("status", status_flag[1])

    BOOT_FINISHED_PATTERN = "#INFO#DIAG_START#END#\r\n"
    if console_log == BOOT_FINISHED_PATTERN:
        update_uart_console_reg("status", status_flag[0])
        print "Boot Finished!"

    # if time_sec_diff > 0:
    #     print(time_sec_diff)
    update_uart_console_reg("last_msg", console_log)
    update_uart_console_reg("last_timestamp", datetime.now())

    return 0


def is_idle():



def update_uart_console_reg(target, data):
    if target == "last_msg":
        uart_console_reg['last_msg'] = data
    if target == "last_timestamp":
        uart_console_reg['last_timestamp'] = data
    if target == "status":
        uart_console_reg['status'] = data  # status_flag = ["IDLE", "BOOTING", "RUNNING", "HANGUP"]
    return 0


# 建立 4 個子執行緒
threads = [
    threading.Thread(target=job_uart_read, args=("Uart Read Thread", ser,)),
    threading.Thread(target=job_uart_send, args=("Uart Send Thread", ser,)),
    threading.Thread(target=job_uart_parser, args=("Uart Parser",))
]
# for i in range(5):
#     threads.append(threading.Thread(target=job, args=(i,)))
#     threads[i].start()
threads[0].start()  # Uart read Thread
threads[1].start()  # Uart send Thread
threads[2].start()  # Uart Parser Thread

# 主執行緒繼續執行自己的工作
# ...
listener = keyboard.Listener(on_press=on_press)
listener.start()  # start to listen on a separate thread
listener.join()  # remove if main thread is polling self.keys
# 等待所有子執行緒結束
for i in range(3):
    threads[i].join()

# print("Done.")
