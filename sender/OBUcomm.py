from queue 				import Queue , Empty, Full
from settings 			import *
from windowbuffer		import WindowBuffer_Element
from sender 			import send_bundle
from threading 			import Lock
from time 				import sleep
from windowManagement	import *
from log 				import *
from util 				import ping

import threading
import socket
import sys
import json
import settings
import atexit
import time

seq_nr = 0
n_lostMsg = 0
n_buffered = 0 ## from 0 to WINDOW_SIZE-1
window_elements = []
q = Queue(QUEUE_MAX_SIZE)


class TestConnectionThread(threading.Thread):

	def __init__(self):
		threading.Thread.__init__(self)

	def run(self):

		while(True):
			sleep(1)

			newContact = False

			connected = ping()

			if connected == False:
				print("NOT_CONNECTED")
				settings.connected_lock.acquire()
				if settings.ConnectionInfo.connected == True:
					settings.ConnectionInfo.connected = False
					settings.ConnectionInfo.start = -1
					settings.ConnectionInfo.lastFinish = int(time.time())
					settings.ConnectionInfo.prevsStateconn = True
				settings.connected_lock.release()


			if connected == True:
				settings.connected_lock.acquire()

				if settings.ConnectionInfo.connected == True:
					pass # do nothing - same contact

				# pode ser um novo contacto ou não (pode ter sido apenas uma perda instantanea)
				else: #settings.ConnectionInfo.connected == False:

					if time.time() - settings.ConnectionInfo.lastFinish > 10: #novo contacto!!!
						settings.ConnectionInfo.connected = True
						settings.ConnectionInfo.start = int(time.time())
						# settings.ConnectionInfo.lastFinish mantem se
						settings.ConnectionInfo.prevsStateconn = False
						newContact = True

					else: #mesmo contacto
						settings.ConnectionInfo.connected = True

				settings.connected_lock.release()

			if newContact == True:
				for i in range(n_buffered):
					window_elements[i].set_nContact(window_elements[i].get_nContact() + 1)
					window_elements[i].set_sent(False)


class WindowManagThread(threading.Thread):

	def __init__(self):
		threading.Thread.__init__(self)

	def run(self):

		global n_buffered
		global seq_nr
		global window_elements
		global rcv_seqNr

		while True:

			sleep(3)

			#acks update
			while window_elements[0].get_ack() == True:
				#remove window's first position
				window_LeftShift(window_elements)
				n_buffered -= 1

				#add empty element in window's last position
				window_addEmptyElem(window_elements , seq_nr)
				seq_nr += 1

			if not q.empty():

				while n_buffered < WINDOW_SIZE:

					if q.empty():
						break
					try:
						bundle = q.get(False)
					except Empty:
						pass
					else: #add bundle to window
						settings.connected_lock.acquire()
						connected = settings.connected
						settings.connected_lock.release()
						bundle = window_addNewElem(window_elements, n_buffered, bundle)
						if connected == True:
							send_bundle(bundle)
							window_elements[n_buffered].set_nContact(1)
						n_buffered += 1


			#update acks in window
			while True:
				if settings.rcv_seqNr.empty():
					break;
				try:
					elem = settings.rcv_seqNr.get(False)
				except Empty:
					pass
				else: #add bundle to window
					for i in range(n_buffered):
						if int(elem) == window_elements[i].get_seqNr():
							window_elements[i].set_ack(True)
							#store_TransmInfo(window_elements[i])
							break
			## IMP: clean rcv_seqNr -> it's needed to avoid that old acks acknowledge just sent bundles
			settings.rcv_seqNr = Queue()

			#check for expired timers
			for i in range(n_buffered):
				window_elements[i].check_timer()

			for i in range(WINDOW_SIZE): #DEBUG
				print("[WINDOW----->] seqNr: %d; ack: %s" % (window_elements[i].get_seqNr(), window_elements[i].get_ack()))

			print("")



class HandleConnThread(threading.Thread):

	def __init__(self, clientSocket, clientAddress):

		threading.Thread.__init__(self)
		self.clientSocket = clientSocket
		self.clientAddress = clientAddress

	def run(self):

		global n_lostMsg

		try:
			while True:

				inData = self.clientSocket.recv(1024)
				inData = inData.decode('utf-8')

				if inData:
					global q
					try:
						q.put(inData, False)
					except Full:
						print("queue is full")
						n_lostMsg += 1
				else:
					print("no more data from OBU")
					break
		finally:
			clientSocket.close()

#save number of LostMsg before leaving
def saveLostMsg_count():
    with open("LostMsg.csv", "a") as outfile:
        outfile.write("\n\n%d" % n_lostMsg)


if __name__ == '__main__':

	settings.init()
	atexit.register(saveLostMsg_count)

	print("window size %d" % WINDOW_SIZE)

	fp = open("TransmInfo_Log.csv", 'a')
	fp.write("\n\n")
	fp.close()

	fp = open("RTO_evolution.csv", 'a')
	fp.write("\n\n")
	fp.close()

	## init window ##
	for i in range(WINDOW_SIZE):
		window_elements.append(WindowBuffer_Element( (seq_nr % (MAX_SEQ_NUMBER+1))))
		seq_nr += 1

	connectivityThread = TestConnectionThread()
	connectivityThread.start()

	windowMngThread = WindowManagThread()
	windowMngThread.start()

	sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	server_address = ('localhost', PORT)
	sock.bind(server_address)

	sock.listen(1)

	while True:

		(clientSocket, clientAddress) = sock.accept()
		connThread = HandleConnThread(clientSocket, clientAddress)
		connThread.start()