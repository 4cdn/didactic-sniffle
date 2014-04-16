#!/usr/bin/python
import socket
import sockssocket
import select
import threading
import time
import os
import sqlite3
import random
import string
import Queue
import traceback

# send article:
# f = open(os.path.join('invalid', item), 'r')
# for line in f:
#   if line[0] == '.': print '.' + line[:-1]
#   else: print line[:-1]
# f.close()

# FIXME implement self.log
# FIXME for all self.log use for line in "{0}".format(message).split('\n'):
# FIXME for outfeeds add full_sync (every restart? just once? what about stats directory?)


class feed(threading.Thread):
  def __init__(self, master, connection=None, outstream=False, host=None, port=None, sync_on_startup=False, proxy=None, debug=2):
    threading.Thread.__init__(self)
    # debug level
    #     0: quiet
    #     1: errors
    #     2: warnings/connection info/article received/sent
    #     3: in/out no multiline
    #     4: in/out conaints multiline
    #     5: info
    self.outstream = outstream
    self.debug = debug
    self.state = 'init'
    self.SRNd = master
    self.proxy = proxy
    if outstream:          
      self.host = host
      self.port = port
      self.queue = Queue.Queue()
      self.outstream_stream = False
      self.outstream_ihave = False
      self.outstream_post = False
      self.outstream_ready = False
      self.outstream_currently_testing = ''
      self.polltimeout = 500 # 1 * 1000
      self.name = 'outfeed-{0}-{1}'.format(self.host, self.port)
      self.init_socket()
    else:
      self.socket = connection[0]
      self.fileno = self.socket.fileno()
      self.host = connection[1][0]
      self.port = connection[1][1]
      self.polltimeout = -1
      self.name = 'infeed-{0}-{1}'.format(self.host, self.port)
    #self.socket.setblocking(0)
    self.buffersize = 2**16
    self.caps = [
        '101 i support to the following:',
        'VERSION 2',
        'IMPLEMENTATION artificial NNTP processing unit SRNd v0.1',
        'POST'
        'IHAVE'
        'STREAMING'
        ]
    self.welcome = '200 welcome much to artificial NNTP processing unit some random NNTPd v0.1, posting allowed'
    self.current_group_id = -1
    self.current_article_id = -1
    self.sync_on_startup = sync_on_startup

  def init_socket(self):
    if ':' in self.host:
      if self.proxy != None:
        raise Exception("can't use proxy server for ipv6 connections")
      self.socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
      return
    if self.proxy == None:
      self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    elif self.proxy[0] == 'socks5':
      self.socket = sockssocket.socksocket(socket.AF_INET, socket.SOCK_STREAM)
      self.socket.setproxy(sockssocket.PROXY_TYPE_SOCKS5, self.proxy[1], self.proxy[2], rdns=True)
    elif self.proxy[0] == 'socks4':
      self.socket = sockssocket.socksocket(socket.AF_INET, socket.SOCK_STREAM)
      self.socket.setproxy(sockssocket.PROXY_TYPE_SOCKS4, self.proxy[1], self.proxy[2], rdns=True)
    elif self.proxy[0] == 'http':
      self.socket = sockssocket.socksocket(socket.AF_INET, socket.SOCK_STREAM)
      self.socket.setproxy(sockssocket.PROXY_TYPE_HTTP, self.proxy[1], self.proxy[2], rdns=True)
    else:
      raise Exception("unknown proxy type %s, must be one of socks5, socks4, http." % self.proxy[0])

  def add_article(self, message_id):
    self.queue.put(message_id)

  def send(self, message):
    #FIXME: readd message_id if conn_broken
    #FIXME: ^ add message_id as additional argument
    #TODO: do the actual reading and sending here as well, including converting
    #TODO: ^ provide file FD as argument so reply to remote can be checked first 
    self.state = 'sending'
    sent = 0
    length = len(message)
    while sent != length:
      if self.debug > 4 and sent > 0:
        print "[{0}] resending part of line, starting at {1} to {2}".format(self.name, sent, length)
      try:
        sent += self.socket.send(message[sent:])
      except socket.error as e:
        if e.errno == 11:
          # 11 Resource temporarily unavailable
          time.sleep(0.1)
        elif e.errno == 32 or e.errno == 104 or e.errno == 110:
          # 32 Broken pipe
          # 104 Connection reset by peer
          # 110 Connection timed out
          self.con_broken = True
          break
        else:
          print "ERROR: [%s] got an unknown socket error at line 102 with error number %i: %s" % (self.name, e.errno, e)
          self.con_broken = True
          break
    if not self.multiline_out and self.debug > 2: print "[{0}] out: {1}".format(self.name, message[:-2])
    if self.multiline_out and self.debug > 3: print "[{0}] out: {1}".format(self.name, message[:-2])

  def shutdown(self):
    # FIXME socket.shutdown() needed if running == False?
    self.running = False
    try:
      self.socket.shutdown(socket.SHUT_RDWR)
    except socket.error as e:
      if e.errno != 9 and e.errno != 107:   # 9 == bad filedescriptor, 107 == not connected
        raise e
      
  def cooldown(self, additional_message=''):
    # FIXME write that fuckin self.log() def already!
    if self.cooldown_counter == 0:
      self.cooldown_counter += 1
      return
    if self.debug > 1 and self.cooldown_counter != 10:
      print "[%s] %ssleeping %s seconds" % (self.name, additional_message, self.cooldown_period * self.cooldown_counter)
    end_time = int(time.time()) + self.cooldown_period * self.cooldown_counter
    while self.running and int(time.time()) < end_time:
      time.sleep(2)
    if self.cooldown_counter != 10:
      self.cooldown_counter += 1

  def run(self):
    self.sqlite_conn = sqlite3.connect('dropper.db3')
    self.sqlite = self.sqlite_conn.cursor()
    self.running = True
    connected = False
    self.multiline = False
    self.multiline_out = False
    self.cooldown_period = 60
    self.cooldown_counter = 0
    if self.outstream:
      self.articles_to_send = list()
      while self.running and not connected:
        self.state = 'cooldown'
        self.cooldown()
        if not self.running:
          break
        self.state = 'connecting'
        try:
          self.socket.connect((self.host, self.port))
          connected = True
          if self.debug > 1 and self.cooldown_counter != 10:
            print "[%s] connection established via proxy %s" % (self.name, str(self.proxy))
        except socket.error as e:
          if e.errno == 106:
            # tunnelendpoint already connected. wtf? only happened via proxy
            # FIXME debug this
            print "[%s] %s, setting connected = True" % (self.name, e)
            connected = True
          elif e.errno == 9:
            # Bad file descriptor
            self.init_socket()
          elif self.debug > 1:
            print "[%s] connect socket.error: %s" % (self.name, e)
            print traceback.format_exc()
        except sockssocket.ProxyError as e:
          if self.debug > 1: print "[%s] connect ProxyError: %s" % (self.name, e)
    else:
      if self.debug > 1: print "[%s] connection established" % self.name
      self.send(self.welcome + '\r\n')
    self.state = 'idle'
    poll = select.poll()
    poll.register(self.socket.fileno(), select.POLLIN | select.POLLPRI)
    poll = poll.poll
    self.buffer_multiline = list()
    self.con_broken = False
    in_buffer = ''
    while self.running:
      if self.con_broken:
        if not self.outstream:
          print "[%s] not an outstream, terminating" % self.name
          break
        else:
          connected = False
          try:
            self.socket.shutdown(socket.SHUT_RDWR)
          except socket.error as e:
            if self.debug > 4: print "[{0}] {1}".format(self.name, e)
            pass
          self.socket.close()
          self.init_socket()
          while self.running and not connected:
            # FIXME creat def connect(), use self.vars for buffer, connected and poll
            if len(self.articles_to_send) == 0 and self.queue.qsize() == 0:
              if self.debug > 1: print "[%s] connection broken. no article to send, sleeping" % self.name
              self.state = 'nothing_to_send'
              while(self.running and self.queue.qsize() == 0):
                time.sleep(2)
            else:
              self.state = 'cooldown'
              self.cooldown('connection broken. ')
            if not self.running:
              break
            self.state = 'connecting'
            if self.debug > 2: print "[%s] reconnecting.." % self.name
            try:
              self.socket.connect((self.host, self.port))
              if self.debug > 1 and self.cooldown_counter != 10:
                print "[%s] connection established via proxy %s" % (self.name, str(self.proxy))
              connected = True
              self.con_broken = False
              poll = select.poll()
              poll.register(self.socket.fileno(), select.POLLIN | select.POLLPRI)
              poll = poll.poll
              in_buffer = ''
              self.multiline = False
              self.reconnect = False
              self.state = 'idle'
            except socket.error as e:
              if self.debug > 1: print "[%s] reconnecting socks.error: %s" % (self.name, e)
            except sockssocket.ProxyError as e:
              if self.debug > 1: print "[%s] reconnecting ProxyError: %s" % (self.name, e)
              if self.debug > 1: print "[%s] recreating proxy socket" % self.name
              break
          if not self.running: break
          if not connected: continue
      if poll(self.polltimeout):
        self.state = 'receiving'
        cur_len = len(in_buffer)
        try:
          in_buffer += self.socket.recv(self.buffersize)
        except socket.error as e:
          print "[%s] DEBUG socket.error.errno: %s, socket.error: %s" % (self.name, e.errno, e)
          if e.errno == 11:
            # 11 Resource temporarily unavailable
            time.sleep(0.1)
            continue
          elif e.errno == 32 or e.errno == 104 or e.errno == 110:
            # 32 Broken pipe
            # 104 Connection reset by peer
            # 110 Connection timed out
            self.con_broken = True
            continue
          else:
            # FIXME: different OS might produce different error numbers. make this portable.
            print "ERROR: [%s] got an unknown socket error at line 251 with error number %i: %s" % (self.name, e.errno, e)       
            self.con_broken = True
            continue
        except sockssocket.ProxyError as e:
          print "[%s] proxy error: %s" % (self.name, e)
          self.con_broken = True
          continue
            #if self.debug > 1: print "[{0}] connection problem: {1}".format(self.name, e)
            #self.con_broken = True
            #break
        received = len(in_buffer) - cur_len
        #print "[{0}] received: {1}".format(self.name, received)
        if received == 0:
          self.con_broken = True
          continue
        if not '\r\n' in in_buffer:
          continue
        parts = in_buffer.split('\r\n')
        if in_buffer[-2:] == '\r\n':
          in_buffer = ''
          #print "[{0}] received full message with {1} parts".format(self.name, len(parts) - 1)
        else:
          in_buffer = parts[-1]
          #print "[{0}] received incomplete message with {1} valid parts".format(self.name, len(parts) - 1)
        del parts[-1]
        for part in parts:
          if not self.multiline:
            self.handle_line(part)
          elif len(part) != 1:
            self.buffer_multiline.append(part)
            if self.debug > 3: print "[{0}] multiline in: {1}".format(self.name, part)
          else:
            if part[0] == '.':
              self.handle_multiline(self.buffer_multiline)
              self.multiline = False
              del self.buffer_multiline[:]
            else:
              self.buffer_multiline.append(part)
              if self.debug > 3: print "[{0}] multiline in: {1}".format(self.name, part)
          if not self.multiline:
            self.state = 'idle'
        continue
      else:
        #print "[{0}] timeout hit, state = {1}".format(self.name, self.state)
        if self.outstream_ready and self.state == 'idle':
          #print "[{0}] queue size: {1}".format(self.name, self.queue.qsize())
          if self.outstream_stream:
            self.state = 'outfeed_send_article_stream'
            for message_id in self.articles_to_send:
              if self.con_broken: break
              if os.path.exists(os.path.join('articles', message_id)):
                self.send('TAKETHIS {0}\r\n'.format(message_id))
                self.send_article(message_id)
            if not self.con_broken: del self.articles_to_send[:]
            self.state = 'outfeed_send_check_stream'
            count = 0
            while self.queue.qsize() > 0 and count <= 50 and not self.con_broken:
              # FIXME why self.message_id here? IHAVE and POST makes sense, but streaming?
              # FIXME: add CHECK statements to list and send the whole bunch after the loop
              self.message_id = self.queue.get()
              if os.path.exists(os.path.join('articles', self.message_id)):
                self.send('CHECK {0}\r\n'.format(self.message_id))
              count += 1
            self.state = 'idle'
          elif self.queue.qsize() > 0 and not self.con_broken:
            self.message_id = self.queue.get()
            #print "[{0}] got message-id {1}".format(self.name, self.message_id)
            # FIXME: check if article actually exists
            if self.outstream_ihave:
              self.send('IHAVE {0}\r\n'.format(self.message_id))
            elif self.outstream_post:
              self.send('POST\r\n')
    if self.debug > 1: print "[{0}] client disconnected".format(self.name)
    self.socket.close()
    self.SRNd.terminate_feed(self.name)

  def send_article(self, message_id):
    # FIXME: what the fuck? rewrite this whole def! waste RAM much.
    # FIXME: read line, convert, send, read next line. collect x lines before actually sending.
    if self.debug > 1: print '[{0}] sending article {1}'.format(self.name, message_id)
    self.multiline_out = True
    f = open(os.path.join('articles', message_id), 'r')
    article = ''
    read = -1
    while read != 0:
      cur_len = len(article)
      article += f.read()
      read = len(article) - cur_len
    f.close()
    # TODO measure
    #   article = '\r\n'.join(article.split('\n'))
    # against
    #   article = article.replace('\n', '\r\n')
    add_one = False
    if article[-1] != '\n':
      print "need to add a linebreak"
      add_one = True
    article = article.split('\n')
    for index in xrange(0, len(article)):
      if len(article[index]) > 0:
        if article[index][0] == '.':
          article[index] = '.' + article[index]
      if self.debug > 3: print "[{0}] out: {1}".format(self.name, message[:-2])
    if add_one:
      article.append('\r\n')
    article = '\r\n'.join(article) + '.\r\n'
    self.state = 'sending'
    sent = 0
    length = len(article)
    while sent != length:
      if self.debug > 4 and sent > 0:
        print "[{0}] resending part of line, starting at {1} to {2}".format(self.name, sent, length)
      try:
        sent += self.socket.send(article[sent:])
      except socket.error as e:
        if e.errno == 11:
          # 11 Resource temporarily unavailable
          time.sleep(0.1)
        elif e.errno == 32 or e.errno == 104 or e.errno == 110:
          # 32 Broken pipe
          # 104 Connection reset by peer
          # 110 Connection timed out
          self.con_broken = True
          break
        else:
          print "ERROR: [%s] got an unknown socket error at line 378 with error number %i: %s" % (self.name, e.errno, e)
          self.con_broken = True
          break

    #line = f.readline()
    #while line != '' and not self.con_broken:
    #  line = line[:-1] + '\r\n'
    #  if line[0] == '.':
    #    line = '.' + line
    #  self.send(line)
    #  line = f.readline()
    #f.close()
    if not self.con_broken:
      # FIXME: the fuck? .\r\n already added previously. how does this even work? 
      self.send('.\r\n')
    else:
      self.add_article(message_id)
    self.multiline_out = False

  def handle_line(self, line):
    if self.debug > 2: print "[{0}] in: {1}".format(self.name, line)
    commands = line.upper().split(' ')
    if len(commands) == 0:
      if self.debug > 1: print "[{0}] should handle empty line".format(self.name)
      return
    if self.outstream:
      if not self.outstream_ready:
        if commands[0] == '200':
          # TODO check CAPABILITES
          self.cooldown_counter = 0
          self.send('MODE STREAM\r\n')
          self.send('MODE STREAM\r\n')
        elif commands[0] == '203':
          # MODE STREAM test successfull
          self.outstream_stream = True
          self.outstream_ready = True
        elif commands[0] == '501' or commands[0] == '500':
          if self.outstream_currently_testing == '':
            # MODE STREAM test failed
            self.outstream_currently_testing = 'IHAVE'
            self.send('IHAVE <thisarticledoesnotexist>\r\n')
          elif self.outstream_currently_testing == 'IHAVE':
            # IHAVE test failed
            self.outstream_post = True
            self.outstream_ready = True
            if self.queue.qsize() > 0:
              self.message_id = self.queue.get()
              self.send('POST\r\n')
        elif commands[0] == '435':
          # IHAVE test successfull
          self.outstream_ihave = True
          self.outstream_ready = True
        elif commands[0] == '335':
          # IHAVE test successfull
          self.send('.\r\n')
          self.outstream_ihave = True
          self.outstream_ready = True
        # FIXME how to treat try later for IHAVE and CHECK?
        return
      if commands[0] == '200':
        # TODO check specs for reply 200 again, only valid as first welcome line?
        self.cooldown_counter = 0
        return
      if self.outstream_stream:
        if commands[0] == '238':
          # CHECK 238 == article wanted
          self.articles_to_send.append(line.split(' ')[1])
        elif commands[0] == '431':
          # CHECK 431 == try again later
          self.add_article(line.split(' ')[1])
        elif commands[0] == '438':
          # CHECK 438 == article not wanted
          return
      elif self.outstream_ihave:
        if commands[0] == '235' or commands[0] == '435' or commands[0] == '437':
          # IHAVE 235 == last article received
          # IHAVE 435 == article not wanted
          # IHAVE 437 == article rejected
          if self.queue.qsize() > 0:
            self.message_id = self.queue.get()
            self.send('IHAVE {0}\r\n'.format(self.message_id))
        elif commands[0] == '436':
          # IHAVE 436 == try again later
          self.add_article(self.message_id)
        elif commands[0] == '335':
          # IHAVE 335 == waiting for article
          self.send_article(self.message_id)
        else:
          print "[outfeed] unknown response to IHAVE:"
          print line
      elif self.outstream_post:
        if commands[0] == '340':
          # POST 340 == waiting for article
          self.send_article(self.message_id)
        elif commands[0] == '240' or commands[0] == '441':
          # POST 240 == last article received
          # POST 441 == posting failed
          if self.queue.qsize() > 0:
            self.message_id = self.queue.get()
            self.send('POST\r\n')
        elif commands[0] == '440':
          # POST 440 == posting not allowed
          if self.debug > 0: print "[{0}] remote host does not allow MODE STREAM, IHAVE or POST. shutting down.".format(self.name)
          self.running = False
          try:
            self.socket.shutdown(socket.SHUT_RDWR)
          except:
            pass
        else:
          print "[%s] unknown response to POST: %s" % (self.name, line)
      return
    elif commands[0] == 'CAPABILITIES':
      for cap in self.caps:
        self.send(cap + '\r\n')
      self.send('.\r\n')
    elif commands[0] == 'MODE' and len(commands) == 2 and commands[1] == 'STREAM':
      self.send('203 stream as you like\r\n')
    #elif commands[0] == 'MODE' and commands[1] == 'READER':
    #  self.send('502 i recommend in check to the CAPABILITIES\r\n')
    elif commands[0] == 'QUIT':
      self.send('205 bye bye\r\n')
      self.state = 'closing down'
      self.running = False
      self.socket.shutdown(socket.SHUT_RDWR)
    elif commands[0] == 'CHECK' and len(commands) == 2:
      #TODO 431 message-id   Transfer not possible; try again later
      message_id = line.split(' ', 1)[1]
      if '/' in message_id:
         self.send('438 {0} illegal message-id\r\n'.format(message_id))
         return
      if os.path.exists(os.path.join('articles', message_id)) or os.path.exists(os.path.join('incoming', message_id)):
        self.send('438 {0} i know this article already\r\n'.format(message_id))
        return
      if os.path.exists(os.path.join('articles', 'censored', message_id)):
        self.send('438 {0} article is blacklisted\r\n'.format(message_id))
        #print "[%s] CHECK article blacklisted: %s" % (self.name, message_id)
        return
      self.send('238 {0} go ahead, send to the article\r\n'.format(message_id))
    elif commands[0] == 'TAKETHIS' and len(commands) == 2:
      self.waitfor = 'article'
      self.variant = 'TAKETHIS'
      self.message_id_takethis = line.split(' ', 1)[1]
      self.multiline = True
    elif commands[0] == 'POST':
      self.send('340 go ahead, send to the article\r\n')
      self.waitfor = 'article'
      self.variant = 'POST'
      self.multiline = True
    elif commands[0] == 'IHAVE':
      arg = line.split(' ', 1)[1]
      if '/' in arg:
        self.send('435 illegal message-id\r\n')
        return
      #if self.sqlite.execute('SELECT message_id FROM articles WHERE message_id = ?', (arg,)).fetchone():
      if os.path.exists(os.path.join('articles', arg)) or os.path.exists(os.path.join('incoming', arg)):
        self.send('435 already have this article\r\n')
        return
      if os.path.exists(os.path.join('articles', 'censored', arg)):
        self.send('435 article is blacklisted\r\n')
        #print "[%s] IHAVE article blacklisted: %s" % (self.name, arg)
        return
      #TODO: add currently receiving same message_id from another feed == 436, try again later
      self.send('335 go ahead, send to the article\r\n'.format(arg))
      self.waitfor = 'article'
      self.variant = 'IHAVE'
      self.multiline = True
    elif commands[0] == 'STAT':
      if len(commands) == 1:
        # STAT without arguments
        if self.current_group_id == -1:
          self.send('412 i much recommend in select to the newsgroup first\r\n')
        elif self.current_article_id == -1:
          self.send('420 i claim in current group is empty\r\n')
        else:
          message_id = self.sqlite.execute('SELECT message_id FROM articles WHERE group_id = ? AND article_id = ?', (self.current_group_id, self.current_article_id)).fetchone()
          if message_id:
            message_id = message_id[0]
            self.send('223 {0} {1}\r\n'.format(self.current_article_id, message_id))
          else:
            if self.debug > -1: print "[{0}] error: internal state messed up. current_article_id does not have connected message_id.".format(feed.name)
            if self.debug > -1: print "DEBUG: current_group_id: {0}, current_article_id: {1}".format(self.current_group_id, self.current_article_id)
        return
      if len(commands) != 2:
        self.send('501 i much recommend in speak to the proper NNTP\r\n')
        return
      try:
        arg = int(commands[1])
        # STAT argument is article_id
        if self.current_group_id == -1:
          self.send('412 i much recommend in select to the newsgroup first\r\n')
        else:
          message_id = self.sqlite.execute('SELECT message_id FROM articles WHERE group_id = ? AND article_id = ?', (self.current_group_id, arg)).fetchone()
          if message_id:
            message_id = message_id[0]
            self.current_article_id = arg
            self.send('223 {0} {1}\r\n'.format(self.current_article_id, message_id))
          else:
            self.send('423 i claim such == invalid number\r\n')
      except ValueError:
        arg = line.split(' ')[1]
        # STAT argument is message_id
        #if self.sqlite.execute('SELECT message_id FROM articles WHERE message_id = ?', (arg,)).fetchone():
        if os.path.exists(os.path.join('articles', arg)):
          self.send('223 0 {0}\r\n'.format(arg))
        else:
          self.send('426 i do not know much in {0}\r\n'.format(arg))
    else:
      self.send('501 i much recommend in speak to the proper NNTP based on CAPABILITIES\r\n')

  def handle_multiline(self, lines):
    # TODO if variant != POST think about using message_id in handle_singleline for self.outfile = open(tmp/$message_id, 'w')
    # TODO also in handle_singleline: if os.path.exists(tmp/$message_id): retry later

    if self.waitfor == 'article':
      filename = '{0}-{1}'.format(self.name, int(time.time()))
      message_id = ''
      newsgroups = ''
      body_found = False
      error = ''
      new_message_id = False
      for index in xrange(0, len(lines)):
        if not body_found:
          if lines[index].lower().startswith('message-id:'):
            message_id = lines[index].split(' ', 1)[1]
          elif lines[index].lower().startswith('newsgroups:'):
            newsgroups = lines[index].split(' ', 1)[1]
        lines[index] = lines[index] + '\n'
        if lines[index] == '\n':
          body_found = True
        elif lines[index][0] == '.':
          lines[index] = lines[index][1:]

      # check for errors
      if not body_found: error += 'no body found, '
      if newsgroups == '': error += 'no newsgroups found, '
      if message_id == '':
        if self.variant != 'POST':
          error += 'no message-id in article, '
        else:
          rnd = ''.join(random.choice(string.ascii_lowercase) for x in range(10))
          message_id = '{0}{1}@POSTED.SRNd'.format(rnd, int(time.time()))
          new_message_id = True
      elif '/' in message_id:
        error += '/ in message-id, '
      if error != '':
        if self.variant == 'IHAVE':
          self.send('437 invalid article: {0}\r\n'.format(error[:-2]))
        elif self.variant == 'TAKETHIS':
          self.send('439 {0} invalid article: {1}\r\n'.format(self.message_id_takethis, error[:-2]))
          self.message_id_takethis = ''
        elif self.variant == 'POST':
          self.send('441 invalid article: {0}\r\n'.format(error[:-2]))
        # save in articles/invalid for manual debug
        f = open(os.path.join('articles', 'invalid', filename), 'w')
        f.write('X-SRNd-invalid: {0}\n'.format(error[:-2]))
        f.write('X-SRNd-source: {0}\n'.format(self.name))
        f.write('X-SRNd-variant: {0}\n'.format(self.variant))
        if new_message_id:
          f.write('Message-ID: {0}\n'.format(message_id))
        f.write(''.join(lines))
        f.close()
        self.waitfor = ''
        self.variant = ''
        if self.debug > 1: print '[{0}] article invalid {1}: {2}'.format(self.name, message_id, error[:-2])
        return

      if self.debug > 1: print '[{0}] article received {1}'.format(self.name, message_id)

      # save article in tmp and mv to incoming
      if self.variant == 'POST':
        self.send('240 article received\r\n')
      elif self.variant == 'IHAVE':
        self.send('235 article received\r\n')
        #TODO: failed but try again later ==> 436
      elif self.variant == 'TAKETHIS':
        self.send('239 {0} article received\r\n'.format(self.message_id_takethis))
        self.message_id_takethis = ''
      if not os.path.exists(os.path.join('articles', 'censored', message_id)):
        path = os.path.join('incoming', 'tmp', filename)
        f = open(path, 'w')
        if new_message_id:
          f.write('Message-ID: {0}\n'.format(message_id))
        f.write(''.join(lines))
        f.close()
        target = os.path.join('incoming', message_id)
        if not os.path.exists(target):
          os.rename(path, target)
        else:
          if self.debug > 0: print '[{0}] got duplicate article: {1} does already exist. removing temporary file.'.format(self.name, target)
          os.remove(path)
      self.waitfor = ''
      self.variant = ''
    else:
      print "[{0}] should handle multi line while waiting for {1}:".format(self.name, self.waitfor)
      print ''.join(lines)
      print "[{0}] should handle multi line end".format(self.name)
