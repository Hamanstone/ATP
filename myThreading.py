# coding=utf-8

import sys
import os
import threading
import time
import json
import serial  # 引用pySerial模組
from pynput import keyboard
from datetime import datetime
import queue  # 先进先出队列
from tools import *

# Public and global variable configure zone
COM_PORT = 'COM4'  # 指定通訊埠名稱
BAUD_RATES = 115200  # 設定傳輸速率
ser = serial.Serial(COM_PORT, BAUD_RATES)  # 初始化序列通訊埠
IPS_800_COM_PORT = 'COM3'
IPS_800_BAUD_RATES = 9600
IPS_800_ser = serial.Serial(IPS_800_COM_PORT, IPS_800_BAUD_RATES)
# 最多接收10个数据
uart_send_q = queue.Queue(1)
uart_read_q = queue.Queue(5)
ips_send_q = queue.Queue(1)
ips_check_pwr_q = queue.Queue(1)
uart_cmd_request_q = queue.Queue(1)
uart_cmd_response_q = queue.Queue(1)

# SHOW_DBG_MSG = True
SHOW_DBG_MSG = False
status_flag = ["IDLE", "BOOTING", "RUNNING", "HALTED", "UNKNOWN"]
power_flag = ""
new_start_flag = True
input_count = 1
fail_count = 0
uart_console = {"last_msg": "", "last_timestamp": datetime.now(), "status": status_flag[4]}
log_filename = ("log/%s.log" % datetime.now().strftime("%Y%m%d%H%M%S"))
script_content = {'idx': 0, 'cmd': '', 'wait_str': '', 'timeout': 0, 'exe_mode': 0, 'next': 0}
script_list = []
script_content['idx'] = 0
script_content['cmd'] = 'sh /sdk/insmod_rndis.sh\r\n'
script_content['wait_str'] = '<USB>[EP][2] Enable for BULK OUT with maxpacket/fifo(512/1024)\r\r\n'
script_content['timeout'] = 3
script_content['exe_mode'] = 1
script_content['comment'] = 'insert rndis module'
script_content['next'] = script_content['idx'] + 1
script_list.append(script_content.copy())

script_content['idx'] = 1
script_content['cmd'] = 'ifconfig usb0 192.168.100.99; cd /config/pega\r\n'
script_content['wait_str'] = '/config/pega # '
script_content['timeout'] = 1
script_content['exe_mode'] = 1
script_content['comment'] = 'ifconfig set IP and change DIR'
script_content['next'] = script_content['idx'] + 1
script_list.append(script_content.copy())

script_content['idx'] = 2
script_content['cmd'] = 'tftp -p -l test.raw 192.168.100.200 -b 20000\r\n'
script_content['wait_str'] = '100%'
script_content['timeout'] = 5
script_content['exe_mode'] = 1
script_content['comment'] = 'tftp send file'
script_content['next'] = script_content['idx'] + 1
script_list.append(script_content.copy())

script_content['idx'] = 3
script_content['cmd'] = 'diag factory poweroff\r\n'
script_content['wait_str'] = 'pegaDiag_FactoryPowerOff'
script_content['timeout'] = 3
script_content['exe_mode'] = 1
script_content['comment'] = 'diag factory poweroff'
script_content['next'] = script_content['idx'] + 1
script_list.append(script_content.copy())

# Read boot log into a dictionary before start program.
with open('data.json', 'r') as reader:
	boot_log = json.loads(reader.read())

if not os.path.exists('log'):
	os.makedirs('log')


def on_press(key):
	return 0
	if key == keyboard.Key.esc:
		return False  # stop listener
	try:
		k = key.char  # single-char keys
	except:
		k = key.name  # other keys

	if k in ['1', '2', 'left', 'right']:  # keys of interest
		print('Key pressed: ' + k)
	if k == '3':
		check_power(IPS_800_ser)
		# uart_send_q.put('reboot\r\n')
	if k == '4':
		print(uart_console['status'], uart_console['last_timestamp'], power_flag)
		# uart_send_q.put('diag ver isp\r\n')
	if k == '5':
		uart_send_q.put('sh /sdk/insmod_rndis.sh\r\n')
		uart_send_q.put('ifconfig usb0 192.168.100.99\r\n')
		# uart_send_q.put('diag hw pcba\r\n')
		# uart_send_q.put('diag factory poweroff\r\n')
	if k == '6':
		# is_idle()
		do_power_on()
	if k == '7':
		# is_idle()
		uart_send_q.put('diag factory poweroff\r\n')
		time.sleep(1)
		do_power_off()
	if k == 'q':
		ser.close()
		for idx in range(3):
			threads[idx].do_run = False
		sys.exit()


# 子執行緒的工作函數
def job_uart_read(arg, serialDev):
	t = threading.currentThread()
	# print ("working on %s" % arg)
	global log_filename

	# Force to convert system encoding
	reload(sys)
	sys.setdefaultencoding('utf-8')

	while getattr(t, "do_run", True):
		while serialDev.in_waiting:  # 若收到序列資料…
			data_raw = serialDev.readline()  # 讀取一行
			# data = data_raw.decode()   # 用預設的UTF-8解碼
			if SHOW_DBG_MSG:
				print('* %s %s' % (datetime.now(), repr(data_raw)))  # Escape newline characters
			with open(log_filename, "a+") as myfile:
				myfile.write('%s [DUT] => %s\n' % (datetime.now(), repr(data_raw)))
			check_booting(data_raw)
			uart_read_q.put(data_raw)
		time.sleep(0.1)
	# print("Stopping job %s." % arg)


def job_ips_read(arg, serialDev):
	t = threading.currentThread()
	global power_flag

	while getattr(t, "do_run", True):
		while serialDev.in_waiting:
			ips_raw = serialDev.readline()
			if repr(ips_raw)[2] == '5':
				# print('%s' % (repr(ips_raw)))  # Escape newline characters
				if 'OFF' in ips_raw:
					power_flag = "OFF"
					ips_check_pwr_q.put(power_flag)
				else:
					power_flag = "ON"
					ips_check_pwr_q.put(power_flag)
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
				with open(log_filename, "a+") as myfile:
					myfile.write("%s [DUT] <= %s\n" % (datetime.now(), repr(send_str)))
		if not ips_send_q.empty():
			send_str = ips_send_q.get()
			if len(send_str) is not 0:
				# print(send_str)
				IPS_800_ser.writelines(send_str)
				with open(log_filename, "a+") as myfile:
					myfile.write("%s [IPS] <= %s\n" % (datetime.now(), repr(send_str)))
		# To prevent while consuming too much cpu usage.
		time.sleep(0.1)
	# print("Stopping job %s." % arg)


def job_uart_parser(arg):
	t = threading.currentThread()
	# print ("working on %s" % arg)
	cmd = {'idx': -1, 'timestamp': datetime.now()}

	while getattr(t, "do_run", True):
		while not uart_read_q.empty() or not uart_cmd_request_q.empty():
			if not uart_cmd_request_q.empty():
				cmd['idx'] = uart_cmd_request_q.get()
				cmd['timestamp'] = datetime.now()
				uart_send_q.put(script_list[cmd['idx']]['cmd'])
			if not uart_read_q.empty():
				data = uart_read_q.get()
				# print(repr(data))
				cmd['idx'] = result_compare_engine(cmd['idx'], cmd['timestamp'], data)

				if check_string_match(data, "SigmaStar # \r\n"):
					uart_send_q.put('reset\r\n')
		# To prevent while consuming too much cpu usage.
		time.sleep(0.1)
	# print("Stopping job %s." % arg)


def restart_process():
	global new_start_flag
	global input_count

	set_uart_console_reg("status", "HALTED")  # HALTED
	input_count += 1
	new_start_flag = True
	threads[3].do_run = False
	threads[4].do_run = False
	threads[3].do_run = True
	threads[4].do_run = True
	print("Set new_start_flag = True")


def result_compare_engine(cmd_idx, cmd_receive_timestamp, tmp_data):
	if cmd_idx >= len(script_list) or cmd_idx == -1:
		return -1
	# with open(log_filename, "a+") as myfile:
	# 	myfile.write("%s %s [%s]" % (datetime.now(), repr(tmp_data), repr(script_list[cmd_idx]['wait_str'])))
	if check_string_match(tmp_data, script_list[cmd_idx]['wait_str']):
		uart_cmd_response_q.put({'idx': cmd_idx, 'result': 'pass'})
		with open(log_filename, "a+") as myfile:
			myfile.write("%s [DUT] == %s\n" % (datetime.now(), repr(tmp_data)))
		return cmd_idx + 1
	elif check_string_match(tmp_data, "g_ether.ko"):
		uart_cmd_response_q.put({'idx': cmd_idx, 'result': 'pass'})
		with open(log_filename, "a+") as myfile:
			myfile.write("%s [DUT] == %s\n" % (datetime.now(), repr(tmp_data)))
		return cmd_idx + 1
	elif ((datetime.now() - cmd_receive_timestamp).total_seconds()) >= script_list[cmd_idx]['timeout']:
		# print("Timeout: %s [%s]" % ((datetime.now() - cmd['timestamp']).total_seconds(), script_list[cmd_idx]['timeout']))
		uart_cmd_response_q.put({'idx': cmd_idx, 'result': 'timeout'})
		return cmd_idx + 1

	return cmd_idx


def print_pass_msg(pass_count):
	print("+----------------+")
	print("|      PASS      |")
	print("+----------------+")
	print("Pass Count: %d" % pass_count)
	with open(log_filename, "a+") as myfile:
		myfile.write('+----------------+\n')
		myfile.write('|      PASS      |\n')
		myfile.write('+----------------+\n')
		myfile.write('Pass Count: %d\n' % pass_count)
	set_uart_console_reg("status", "WAITING")  # WAITING

	return 0


def retry_func(var, delay, times, do_func):
	status = get_uart_console_reg("status")
	print("retry_func() will call %s() after %d(%f) retry. STATUS:%s" % (do_func.__name__, times, delay, status))
	if status == 'BOOTING':
		return 0
	time.sleep(delay)
	var += 1
	if var >= times:
		print("Enter retry state. over the boundary.")
		do_func()
		var = 0
	return var


def do_diag_poweroff():
	uart_send_q.put('diag factory poweroff\r\n')
	# time.sleep(3)
	do_power_reset()


def job_auto_test(arg):
	t = threading.currentThread()
	# print ("working on %s" % arg)
	halted_count = 0
	freeze_count = 0
	waiting_count = 0
	# cmd_idx = 0
	global power_flag
	global new_start_flag
	global log_filename
	global input_count

	while getattr(t, "do_run", True):
		# print("----- new loop start -----")
		if new_start_flag:
			print("new_start_flag = True, initial all variable of job_auto_test()")
			print("----------------------- Starting Test Now ----------------------")
			print("Current input count: %d" % input_count)
			log_filename = ("log/%s.log" % datetime.now().strftime("%Y%m%d%H%M%S"))
			print("filename: %s" % log_filename)
			halted_count = 0
			freeze_count = 0
			waiting_count = 0
			uart_send_q.queue.clear()
			uart_read_q.queue.clear()
			uart_cmd_request_q.queue.clear()
			uart_cmd_response_q.queue.clear()
			print("Clear queues.")
			# cmd_idx = 0
			new_start_flag = False

		if uart_console["status"] == "WAITING":
			waiting_count = retry_func(waiting_count, 0.1, 1, do_diag_poweroff)
			continue
		if uart_console["status"] == "HALTED" or uart_console["status"] == "UNKNOWN":
			# print("----- enter HALTED & UNKNOWN check loop -----")
			check_power(IPS_800_ser)
			try:
				if ips_check_pwr_q.get(True, 3) == 'ON':
					set_uart_console_reg("status", "RUNNING")
				else:
					do_power_on()
					time.sleep(1)
			except Exception:
				print("*** waiting for ips_check_pwr_q timeout(3s)")

		if uart_console["status"] == "BOOTING" or uart_console["status"] == "RUNNING":
			if uart_console["status"] == "RUNNING":  # and is_idle():
				# print("last message %s" % repr(uart_console["last_msg"]))
				if is_idle():
					set_uart_console_reg("status", "IDLE")
				else:
					freeze_count = retry_func(freeze_count, 0.1, 1, do_power_reset)
			else:  # BOOTING mode
				# Booting mode exception handler
				if (datetime.now() - uart_console['last_timestamp']).total_seconds() > 2:
					# TODO 或許可以往回看10Rows有沒有Auto-Negotiation...
					if not check_string_match(uart_console["last_msg"], "Auto-Negotiation..."):
						# print("last_msg %s" % uart_console["last_msg"])
						do_power_reset()
						print('%s %s %s' % (datetime.now(), "Booting hangup exception handler.", uart_console["status"]))
					check_power(IPS_800_ser)
					if ips_check_pwr_q.get() == 'OFF':
						do_power_on()
			time.sleep(1)
			# print('.'),
			continue
		else:
			print('%s %s %s' % (datetime.now(), "Starting Run Script", uart_console["status"]))

		if uart_console["status"] == "HALTED":
			halted_count = retry_func(halted_count, 0.5, 1, do_power_reset)
			continue

		if uart_console["status"] == "IDLE":
			command_dispatcher()
			# set_uart_console_reg("status", "WAITING")  # HALTED
		# To prevent while consuming too much cpu usage.
		time.sleep(0.5)
	# print("Stopping job %s." % arg)


# 注意：這個function帶有queue.get()方法，會有阻塞效果。
def command_dispatcher():
	inner_idx = 0
	fail_step_count = 0
	global fail_count
	global input_count

	print(">>> uart_cmd_request_q.len = %d, uart_cmd_response_q.len = %d <<<" % (uart_cmd_request_q.qsize(), uart_cmd_response_q.qsize()))
	# Just in case to prevent queue left when a new session start will cause something wrong.
	uart_cmd_response_q.queue.clear()
	uart_cmd_request_q.queue.clear()
	while inner_idx <= len(script_list) - 1:
		print('%s Send cmd: %s %s' % (datetime.now(), script_list[inner_idx]['comment'], uart_console["status"]))
		# uart_send_q.put(script_list[inner_idx]['cmd'])
		uart_cmd_request_q.put(script_list[inner_idx]['idx'])
		queue_dbg_str = "%s [QUEUE] => Sending uart_cmd_request_q = %d" % (datetime.now(), inner_idx)
		print(queue_dbg_str)
		with open(log_filename, "a+") as logfile:
			logfile.write(queue_dbg_str+'\n')
		response = uart_cmd_response_q.get()
		if response['idx'] != inner_idx and response['result'] != 'pass':
			fail_step_count += 1
			queue_dbg_str = "%s [DBG] => Fail on step %d, response = %s" % (datetime.now(), inner_idx, response)
			print(queue_dbg_str)
			with open(log_filename, "a+") as logfile:
				logfile.write(queue_dbg_str + '\n')
		# retry statement
		# if inner_idx == 2 and response == 'pass':
		# 	continue
		inner_idx += 1
	# TODO 處理不同的response，要有相對應的作法，目前什麼都沒做。
	if fail_step_count == 0:
		print_pass_msg(input_count - fail_count)
	else:
		fail_count += 1
	set_uart_console_reg("status", "HALTED")  # HALTED
	print('%s %s %s' % (datetime.now(), "Stop Testing", uart_console["status"]))
	do_power_off()
	print("--------------------------- Test End ---------------------------")
	with open(log_filename, "a+") as logfile:
		logfile.write("--------------------------- Test End ---------------------------\n")
	restart_process()

	# print("released from script_dispatcher() function loop.")


def check_power(serialDev):
	global power_flag
	# power_flag = 'UNKNOWN'
	print('%s %s %s' % (datetime.now(), "Do check_power()", uart_console["status"]))
	serialDev.writelines('/S\r')
	return 0


def check_booting(console_log):
	time_sec_diff = (datetime.now() - uart_console['last_timestamp']).total_seconds()
	# if time_sec_diff > 1:
	#     print("is_booting waiting 1 second.")

	match_result = search_log(boot_log, console_log)
	if isinstance(match_result, unicode):
		# print(repr(console_log))
		set_uart_console_reg("status", "BOOTING")
		# print("*"),
	# else:
	#     print("-"),

	BOOT_FINISHED_PATTERN = "#INFO#DIAG_START#END#\r\n"
	if console_log == BOOT_FINISHED_PATTERN:
		set_uart_console_reg("status", "IDLE")
		print('\n%s %s' % (datetime.now(), "Boot Finished!"))

	# if time_sec_diff > 0:
	#     print(time_sec_diff)
	set_uart_console_reg("last_msg", console_log)
	set_uart_console_reg("last_timestamp", datetime.now())

	return 0


def check_string_match(console_log, keyword):
	if keyword in console_log:
		return 1
	return 0


def do_power_reset():
	global power_flag
	power_flag = 'UNKNOWN'
	set_uart_console_reg('status', 'UNKNOWN')
	print('%s %s %s' % (datetime.now(), "Call do_power_reset()", repr(get_uart_console_reg('last_msg'))))
	ips_send_q.put('/OFF 5\r')
	time.sleep(1)
	ips_send_q.put('/ON 5\r')
	time.sleep(1)
	return 0


def do_power_on():
	print('%s %s' % (datetime.now(), "Call do_power_on()"))
	ips_send_q.put('/ON 5\r')
	set_uart_console_reg('status', 'BOOTING')
	return 0


def do_power_off():
	global power_flag
	ips_send_q.put('/OFF 5\r')
	power_flag = 'UNKNOWN'
	set_uart_console_reg('status', 'UNKNOWN')
	print('%s %s' % (datetime.now(), "Call do_power_off()"))
	return 0


def is_idle():
	if uart_console["last_msg"] != "Auto-Negotiation...":
		print('%s %s Mode: %s' % (datetime.now(), "Do is_idle() checking", get_uart_console_reg('status')))
		uart_send_q.put('\r\n')
		time.sleep(0.5)
		last_reply = (datetime.now() - uart_console["last_timestamp"]).total_seconds()
		if last_reply < 1 and uart_console["last_msg"] != "":
			return 1
	return 0


def set_uart_console_reg(target, data):
	if target == "last_msg":
		uart_console['last_msg'] = data
	if target == "last_timestamp":
		uart_console['last_timestamp'] = data
	if target == "status":
		uart_console['status'] = data  # status_flag = ["IDLE", "BOOTING", "RUNNING", "HANGUP"]
	return 0


def get_uart_console_reg(target):
	if target == "last_msg":
		return uart_console['last_msg']
	if target == "last_timestamp":
		return uart_console['last_timestamp']
	if target == "status":
		return uart_console['status']
	return 0


# 建立 4 個子執行緒
threads = [
	threading.Thread(target=job_uart_read, args=("Uart Read Thread", ser,)),
	threading.Thread(target=job_ips_read, args=("IPS-800 Read Thread", IPS_800_ser,)),
	threading.Thread(target=job_uart_send, args=("Uart Send Thread", ser,)),
	threading.Thread(target=job_auto_test, args=("Auto Testing Thread",)),
	threading.Thread(target=job_uart_parser, args=("Uart Parser",))
]
# for i in range(5):
#     threads.append(threading.Thread(target=job, args=(i,)))
#     threads[i].start()
threads[0].start()  # DUT Uart read Thread
threads[1].start()  # IPS-800 Uart read Thread
threads[2].start()  # DUT Uart send Thread
threads[3].start()  # Auto Testing Thread
threads[4].start()  # Uart Parser Thread

# 主執行緒繼續執行自己的工作
# ...
listener = keyboard.Listener(on_press=on_press)
listener.start()  # start to listen on a separate thread
listener.join()  # remove if main thread is polling self.keys
# 等待所有子執行緒結束
for i in range(4):
	threads[i].join()

# print("Done.")
