#!/usr/bin/python

import time
import random
import string
import urllib
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from urllib import unquote
from cgi import FieldStorage
import base64
from hashlib import sha1, sha512
from binascii import hexlify, unhexlify
from datetime import datetime
import os
import threading
import sqlite3
import socket
import nacl.signing
if __name__ == '__main__':
  import nntplib

class censor(BaseHTTPRequestHandler):

  def __init__(self, request, client_address, origin):
    self.origin = origin
    #if __name__ != '__main__':
    #  self.origin.log('postman initializing as plugin..', 2)
    #else:
    #  self.origin.log('postman initializing as standalone application..', 2)
    # ^ works
    BaseHTTPRequestHandler.__init__(self, request, client_address, origin)

  def do_POST(self):
    self.path = unquote(self.path)
    if self.path == '/moderate?evil':
      self.handle_moderation_request()
      return
    if self.path == '/moderate?auth':
      public = self.check_login() 
      if public:
        session = hexlify(self.origin.rnd.read(24))
        self.origin.sessions[session] = (int(time.time()) + 3600, public)
        self.send_redirect('/moderate/%s/' % session, 'access granted. this time.')
      else:
        self.send_login("totally not")
      return
    elif self.path.startswith("/moderate"):
      if self.path[10:58] not in self.origin.sessions:
        self.send_login()
        return
      if self.origin.sessions[self.path[10:58]][0] < int(time.time()):
        self.send_login()
        return
      path = self.path[58:]
      if path.startswith('/modify?'):
        key = path[8:]
        flags_available = int(self.origin.sqlite_censor.execute("SELECT flags FROM keys WHERE key=?", (self.origin.sessions[self.path[10:58]][1],)).fetchone()[0])
        flag_required = int(self.origin.sqlite_censor.execute('SELECT flag FROM commands WHERE command="srnd-acl-mod"').fetchone()[0])
        if (flags_available & flag_required) != flag_required:
          self.send_redirect(self.path[:58] + "/", "not authorized, flag srnd-acl-mod flag missing.<br />redirecting you in a moment.", 7)
          return
        try:
          self.handle_update_key(key)
          self.send_redirect(self.path[:58] + "/", "update ok,<br />redirecting you in a moment.", 2)
        except Exception as e:
          self.send_redirect(self.path[:58] + "/", "update failed: %s,<br />redirecting you in a moment." % e, 10)
      elif path == "/foo":
        self.die("POST bar")
      else:
        self.send_log()
      return
    self.origin.log("illegal access: {0}".format(self.path), 2)
    self.send_response(200)
    self.send_header('Content-type', 'text/plain')
    self.end_headers()
    self.wfile.write('nope')

  def do_GET(self):
    self.path = unquote(self.path)
    if self.path == '/moderate?getkey':
      secret = self.origin.rnd.read(32)
      public = nacl.signing.SigningKey(secret).verify_key.encode()
      self.send_error("secret: %s\npublic: %s" % (hexlify(secret), hexlify(public)))
      return
    elif self.path.startswith("/moderate"):
      if self.path[10:58] not in self.origin.sessions:
        self.send_login()
        return
      if self.origin.sessions[self.path[10:58]][0] < int(time.time()):
        self.send_login()
        return
      path = self.path[58:]
      if path.startswith('/modify?'):
        key = path[8:]
        self.send_modify_key(key)
      elif path.startswith('/piclog'):
        self.send_piclog()
      elif path == "/foo":
        self.die("GET bar")
      else:
        self.send_log()
      return
    self.origin.log("illegal access: {0}".format(self.path), 2)
    self.send_response(200)
    self.send_header('Content-type', 'text/plain')
    self.end_headers()
    self.wfile.write('nope')

  def handle_update_key(self, key):
    post_vars = FieldStorage(
      fp=self.rfile,
      headers=self.headers,
      environ={
        'REQUEST_METHOD':'POST',
        'CONTENT_TYPE':self.headers['Content-Type'],
      }
    )
    flags = post_vars.getlist("flags")
    result = 0
    if 'local_nick' in post_vars:
      local_nick = post_vars['local_nick'].value
    else:
      local_nick = ''
    for flag in flags:
      result += int(flag)
    self.origin.censor.add_article((self.origin.sessions[self.path[10:58]][1], "srnd-acl-mod %s %i %s" % (key, result, local_nick)), "httpd")

  def check_login(self):
    current_date = int(time.time())
    todelete = list()
    for key in self.origin.sessions:
      if self.origin.sessions[key][0] <= current_date:
        todelete.append(key)
    for key in todelete:
      del self.origin.sessions[key]
    del todelete
    post_vars = FieldStorage(
      fp=self.rfile,
      headers=self.headers,
      environ={
        'REQUEST_METHOD':'POST',
        'CONTENT_TYPE':self.headers['Content-Type'],
      }
    )
    if not 'secret' in post_vars:
      return False
    if len(post_vars['secret'].value) != 64:
      return False
    try:
      public = hexlify(nacl.signing.SigningKey(unhexlify(post_vars['secret'].value)).verify_key.encode())
      flags_available = int(self.origin.sqlite_censor.execute("SELECT flags FROM keys WHERE key=?", (public,)).fetchone()[0])
      flag_required = int(self.origin.sqlite_censor.execute('SELECT flag FROM commands WHERE command="srnd-acl-view"').fetchone()[0])
      if (flags_available & flag_required) == flag_required:
        return public
      else:
        return False
    except Exception as e:
      self.origin.log(e, 0)
      return False

  def send_redirect(self, target, message, wait=0):
    self.send_response(200)
    self.send_header('Content-type', 'text/html')
    self.end_headers()
    self.wfile.write('<html><head><META HTTP-EQUIV="Refresh" CONTENT="%i; URL=%s"></head><body style="font-family: arial,helvetica,sans-serif; font-size: 10pt;"><center><br />%s</center></body></html>' % (wait, target, message))
    return

  def send_login(self, message=""):
    self.send_response(200)
    self.send_header('Content-type', 'text/html')
    self.end_headers()
    self.wfile.write('<html><head></head><body><center>%s<br /><form action="/moderate?auth" enctype="multipart/form-data" method="POST"><label>your secret</label>&nbsp;<input type="text" name="secret" style="width: 400px;"/><input type="submit" /></form></html></html>' % message)

  def send_modify_key(self, key):
    out = self.origin.template_modify_key
    flags = self.origin.sqlite_censor.execute("SELECT command, flag FROM commands").fetchall()
    cur_template = self.origin.template_log_flagnames
    #table = list()
    #for flag in flags:
    #  current_flag = flag[0]
    #  if "-" in current_flag:
    #    current_flag = current_flag.split("-", 1)[1]
    #  table.append(cur_template.replace("%%flag%%", current_flag))
    #out = out.replace("%%flag_names%%", "\n".join(table))
    #del table[:]
    
    flaglist = list()
    row = self.origin.sqlite_censor.execute("SELECT key, local_name, flags, id FROM keys WHERE key = ?", (key,)).fetchone()
    if not row:
      self.die("key not found")
      return
    flagset_template = self.origin.template_modify_key_flagset
    out = out.replace("%%key%%", row[0])
    out = out.replace("%%nick%%", row[1])
    counter = 0
    for flag in flags:
      counter += 1
      if (int(row[2]) & int(flag[1])) == int(flag[1]):
        checked = 'checked="checked"'  
      else:
        checked = ''
      cur_template = flagset_template.replace("%%flag%%", flag[1])
      cur_template = cur_template.replace("%%flag_name%%", flag[0])
      cur_template = cur_template.replace("%%checked%%", checked)
      if counter == 5:
        cur_template += "<br />"
      else:
        cur_template += "&nbsp;"
      flaglist.append(cur_template)
    out = out.replace("%%modify_key_flagset%%", "".join(flaglist))
    del flaglist[:]
    self.send_response(200)
    self.send_header('Content-type', 'text/html')
    self.end_headers()
    self.wfile.write(out)    

  def send_log(self):
    out = self.origin.template_log
    table = list()    
    for row in self.origin.sqlite_censor.execute("SELECT key, local_name, command, data, reason, comment FROM log, commands, keys, reasons WHERE log.accepted = 1 AND keys.id = log.key_id AND commands.id = log.command_id AND reasons.id = log.reason_id ORDER BY log.id DESC").fetchall():
      cur_template = self.origin.template_log_accepted
      if row[1] != "":
        cur_template = cur_template.replace("%%key_or_nick%%", row[1])
      else:
        cur_template = cur_template.replace("%%key_or_nick%%", row[0])
      cur_template = cur_template.replace("%%key%%", row[0])
      cur_template = cur_template.replace("%%action%%", row[2])
      #parent = self.origin.sqlite_overchan.execute("SELECT parent FROM articles WHERE article_uid = ?", (row[3],)).fetchone()[0]
      # TODO save parent in censor.db?
      cur_template = cur_template.replace("%%postid%%", row[3].replace("<", "&lt;").replace(">", "&gt;"))
      cur_template = cur_template.replace("%%reason%%", row[4])
      table.append(cur_template)
    out = out.replace("%%mod_accepted%%", "\n".join(table))
    del table[:]    
    for row in self.origin.sqlite_censor.execute("SELECT key, local_name, command, data, reason, comment FROM log, commands, keys, reasons WHERE log.accepted = 0 AND keys.id = log.key_id AND commands.id = log.command_id AND reasons.id = log.reason_id ORDER BY log.id DESC").fetchall():
      cur_template = self.origin.template_log_ignored
      if row[1] != "":
        cur_template = cur_template.replace("%%key_or_nick%%", row[1])
      else:
        cur_template = cur_template.replace("%%key_or_nick%%", row[0])
      cur_template = cur_template.replace("%%key%%", row[0])
      cur_template = cur_template.replace("%%action%%", row[2])
      cur_template = cur_template.replace("%%postid%%", row[3].replace("<", "&lt;").replace(">", "&gt;"))
      cur_template = cur_template.replace("%%reason%%", row[4])
      table.append(cur_template)
    out = out.replace("%%mod_ignored%%", "\n".join(table))
    del table[:]
    flags = self.origin.sqlite_censor.execute("SELECT command, flag FROM commands").fetchall()
    cur_template = self.origin.template_log_flagnames
    for flag in flags:
      current_flag = flag[0]
      if "-" in current_flag:
        current_flag = current_flag.split("-", 1)[1]
      table.append(cur_template.replace("%%flag%%", current_flag))
    out = out.replace("%%flag_names%%", "\n".join(table))
    del table[:]
    flagset_template = self.origin.template_log_flagset
    flaglist = list()
    for row in self.origin.sqlite_censor.execute("SELECT key, local_name, flags, id FROM keys WHERE flags != 0").fetchall():
      cur_template = self.origin.template_log_whitelist
      cur_template = cur_template.replace("%%key%%", row[0])
      cur_template = cur_template.replace("%%nick%%", row[1])
      #table.append(self.origin.template_log_flagset)
      for flag in flags:
        if (int(row[2]) & int(flag[1])) == int(flag[1]):
          flaglist.append(flagset_template.replace("%%flag%%", "y"))
        else:
          flaglist.append(flagset_template.replace("%%flag%%", "n"))
      cur_template = cur_template.replace("%%flagset%%", "\n".join(flaglist))
      del flaglist[:]
      count = self.origin.sqlite_censor.execute("SELECT count(data) FROM log WHERE key_id = ?", (row[3],)).fetchone()
      cur_template = cur_template.replace("%%count%%", str(count[0]))
      table.append(cur_template)
    out = out.replace("%%mod_whitelist%%", "\n".join(table))
    del table[:]
    for row in self.origin.sqlite_censor.execute("SELECT key, local_name, flags, id FROM keys WHERE flags = 0").fetchall():
      cur_template = self.origin.template_log_unknown
      cur_template = cur_template.replace("%%key%%", row[0])
      cur_template = cur_template.replace("%%nick%%", row[1])
      count = self.origin.sqlite_censor.execute("SELECT count(data) FROM log WHERE key_id = ?", (row[3],)).fetchone()
      cur_template = cur_template.replace("%%count%%", str(count[0]))
      table.append(cur_template)
    out = out.replace("%%mod_unknown%%", "\n".join(table))
    self.send_response(200)
    self.send_header('Content-type', 'text/html')
    self.end_headers()
    self.wfile.write(out)
    
  def send_piclog(self, page=0):
    table = list()
    for row in self.origin.sqlite_overchan.execute('SELECT thumblink, parent, article_uid, last_update FROM articles WHERE thumblink != "" AND thumblink != "invalid" AND thumblink != "document" ORDER BY last_update DESC').fetchall():
      cur_template = '<a href="%%target%%" target="_blank"><img src="%%thumblink%%" class="image" /></a>'
      if row[1] == '' or row[1] == row[2]:
        target = '/thread-%s.html' % sha1(row[2]).hexdigest()[:10]
      else:
        target = '/thread-%s.html#%s' % (sha1(row[1]).hexdigest()[:10], sha1(row[2]).hexdigest()[:10])
      cur_template = cur_template.replace("%%target%%", target)
      cur_template = cur_template.replace("%%thumblink%%", '/thumbs/' + row[0])
      table.append(cur_template)
    out = '<html><head><link type="text/css" href="/styles.css" rel="stylesheet"></head><body>%%content%%</body></html>'
    out = out.replace("%%content%%", "\n".join(table))
    self.send_response(200)
    self.send_header('Content-type', 'text/html')
    self.end_headers()
    self.wfile.write(out)
    
  def send_error(self, errormessage):
    self.send_response(200)
    self.send_header('Content-type', 'text/plain')
    self.end_headers()
    self.wfile.write(errormessage)

  def die(self, message=''):
    self.origin.log("{0}:{1} wants to fuck around: {2}".format(self.client_address[0], self.client_address[1], message), 1)
    if self.origin.reject_debug:
      self.send_error('don\'t fuck around here mkay\n{0}'.format(message))
    else:
      self.send_error('don\'t fuck around here mkay')

  def __get_message_id_by_hash(self, hash):
    return self.origin.sqlite_hasher.execute("SELECT message_id FROM article_hashes WHERE message_id_hash = ?", (hash,)).fetchone()[0]

  def handle_moderation_request(self):
    author = 'Anonymous'
    email = 'an@onymo.us'
    sender = '%s <%s>' % (author, email)
    now = int(time.time())
    subject = 'no subject'
    newsgroups = 'ctl'
    uid_rnd = ''.join(random.choice(string.ascii_lowercase) for x in range(10))
    uid_message_id = '<%s%i@%s>' % (uid_rnd, now, self.origin.uid_host)
    now = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S +0000')
    lines = list()
    
    post_vars = FieldStorage(
      fp=self.rfile,
      headers=self.headers,
      environ={
        'REQUEST_METHOD':'POST',
        'CONTENT_TYPE':self.headers['Content-Type'],
      }
    )
    
    if 'secret' not in post_vars:
      self.die('%s not in post_vars' % item)
      return
    secret = post_vars['secret'].value
    if len(secret) != 64:
      self.die('secret has wrong length: %i instead of %i' % (len(secret), 64))
      return
    try:
      keypair = nacl.signing.SigningKey(unhexlify(secret))
    except Exception as e:
      self.die(e)
    for key in ('purge', 'purge_root'):
      if key in post_vars:
        purges = post_vars.getlist(key)
        for item in purges:
          try:
            lines.append("delete %s" % self.__get_message_id_by_hash(item))
          except Exception as e:
            self.origin.log("could not find message_id for hash %s: %s" % (item, e), 2)
    if 'delete_a' in post_vars:
      delete_attachments = post_vars.getlist('delete_a')
      for item in delete_attachments:
        try:
          lines.append("overchan-delete-attachment %s" % self.__get_message_id_by_hash(item))
        except Exception as e:
          self.origin.log("could not find message_d for hash %s: %s" % (item, e), 2)
    if len(lines) == 0:
      self.die('nothing to do')
      return
    #lines.append("")
    article = self.origin.template_message_control_inner.format(sender, now, newsgroups, subject, uid_message_id, self.origin.uid_host, "\n".join(lines))
    print "'%s'" % article
    hasher = sha512()
    old_line = None
    for line in article.split("\n")[:-1]:
      if old_line:
        hasher.update(old_line)
      old_line = '%s\r\n' % line
    hasher.update(old_line.replace("\r\n", ""))
    keypair = nacl.signing.SigningKey(unhexlify(secret))
    signature = hexlify(keypair.sign(hasher.digest()).signature)
    pubkey = hexlify(keypair.verify_key.encode())
    signed = self.origin.template_message_control_outer.format(sender, now, newsgroups, subject, uid_message_id, self.origin.uid_host, pubkey, signature, article)
    del keypair
    del signature
    del hasher
    f = open(os.path.join('incoming', 'tmp', uid_message_id), 'w')
    f.write(signed)
    f.close()
    del lines
    del article
    del signed
    os.rename(os.path.join('incoming', 'tmp', uid_message_id), os.path.join('incoming', uid_message_id))
    if 'target' in post_vars:
      target = post_vars['target'].value
    else:
      target = '/'
    self.send_redirect(target, 'moderation request received. will redirect you in a moment.', 2)

  def log_request(self, code):
    return

  def log_message(self, format):
    return

  def send_something(self, something):
    try:
      self.send_response(200)
      self.send_header('Content-type', 'text/html')
      self.end_headers()
      self.wfile.write('<html><head><title>foobar</title></head><body style="font-family: arial,helvetica,sans-serif; font-size: 10pt;"><center><br />your message has been received.<br />%s</center></body></html>' % something)
    except socket.error as e:
      if e.errno == 32:
        self.origin.log(e, 2)
        # Broken pipe
        pass
      else:
        raise e

class censor_httpd(threading.Thread):

  def __init__(self, thread_name, args):
    threading.Thread.__init__(self)
    self.name = thread_name
    if 'debug' not in args:
      self.debug = 2
      self.log('debuglevel not defined, using default of debug = 2', 2)
    else:
      try:
        self.debug = int(args['debug'])
        if self.debug < 0 or self.debug > 5:
          self.debug = 2
          self.log('debuglevel not between 0 and 5, using default of debug = 2', 2)
        else:
          self.log('using debuglevel {0}'.format(self.debug), 3)
      except ValueError as e:
        self.debug = 2
        self.log('debuglevel not between 0 and 5, using default of debug = 2', 2)
    self.log('initializing as plugin..', 2)
    self.should_terminate = False
    for key in ('bind_ip', 'bind_port', 'template_directory', 'censor', 'uid_host'):
      if not key in args:
        self.log('{0} not in args'.format(key), 0)
        self.should_terminate = True
    if self.should_terminate:
      self.log('terminating..'.format(key), 0)
      return
    self.uid_host = args['uid_host']
    self.ip = args['bind_ip']
    try:
      self.port = int(args['bind_port'])
    except ValueError as e:
      self.log("{0} is not a valid bind_port", 0)
      self.should_terminate = True
      self.log('terminating..'.format(key), 0)
      return
    if 'bind_use_ipv6' in args:
      tmp = args['bind_use_ipv6']
      if tmp.lower() == 'true':
        self.ipv6 = True
      elif tmp.lower() == 'false':
        self.ipv6 = False
      else:
        self.log("{0} is not a valid value for bind_use_ipv6. only true and false allowed.", 0)
        self.should_terminate = True
        self.log('terminating..'.format(key), 0)
        return
    #self.censor = args['censor']

    self.log('initializing httpserver..', 3)
    self.httpd = HTTPServer((self.ip, self.port), censor)
    if 'reject_debug' in args:
      tmp = args['reject_debug']
      if tmp.lower() == 'true':
        self.httpd.reject_debug = True
      elif tmp.lower() == 'false':
        self.httpd.reject_debug = False
      else:
        self.log("{0} is not a valid value for reject_debug. only true and false allowed. setting value to false.", 0)
    self.httpd.log = self.log
    self.httpd.rnd = open("/dev/urandom", "r")
    self.httpd.sessions = dict()
    self.httpd.uid_host = self.uid_host
    self.httpd.censor = args['censor']

    # read templates
    self.log('reading templates..', 3)
    template_directory = args['template_directory']
    f = open(os.path.join(template_directory, 'log.tmpl'), 'r')
    self.httpd.template_log = f.read()
    f.close()
    f = open(os.path.join(template_directory, 'log_accepted.tmpl'), 'r')
    self.httpd.template_log_accepted = f.read()
    f.close()
    f = open(os.path.join(template_directory, 'log_flagnames.tmpl'), 'r')
    self.httpd.template_log_flagnames = f.read()
    f.close()
    f = open(os.path.join(template_directory, 'log_flagset.tmpl'), 'r')
    self.httpd.template_log_flagset = f.read()
    f.close()
    f = open(os.path.join(template_directory, 'log_ignored.tmpl'), 'r')
    self.httpd.template_log_ignored = f.read()
    f.close()
    f = open(os.path.join(template_directory, 'log_unknown.tmpl'), 'r')
    self.httpd.template_log_unknown = f.read()
    f.close()
    f = open(os.path.join(template_directory, 'log_whitelist.tmpl'), 'r')
    self.httpd.template_log_whitelist = f.read()
    f.close()
    f = open(os.path.join(template_directory, 'message_control_inner.tmpl'), 'r')
    self.httpd.template_message_control_inner = f.read()
    f.close()
    f = open(os.path.join(template_directory, 'message_control_outer.tmpl'), 'r')
    self.httpd.template_message_control_outer = f.read()
    f.close()
    f = open(os.path.join(template_directory, 'modify_key.tmpl'), 'r')
    self.httpd.template_modify_key = f.read()
    f.close()
    f = open(os.path.join(template_directory, 'modify_key_flagset.tmpl'), 'r')
    self.httpd.template_modify_key_flagset = f.read()
    f.close()
    #f = open(os.path.join(template_directory, 'message_pic.template'), 'r')
    #self.httpd.template_message_pic = f.read()
    #f.close()
    #f = open(os.path.join(template_directory, 'message_signed.template'), 'r')
    #self.httpd.template_message_signed = f.read()
    #f.close()

  def shutdown(self):
    self.httpd.shutdown()

  def add_article(self, message_id, source="article"):
    self.log('this plugin does not handle any article. remove hook parts from {0}'.format(os.path.join('config', 'plugins', self.name.split('-', 1)[1])), 0)

  def run(self):
    if self.should_terminate:
      return
    # connect to hasher database
    # FIXME: add database_directory to postman?
    self.database_directory = ''
    self.httpd.sqlite_hasher_conn = sqlite3.connect('hashes.db3')
    self.httpd.sqlite_hasher = self.httpd.sqlite_hasher_conn.cursor()
    self.httpd.sqlite_censor_conn = sqlite3.connect('censor.db3')
    self.httpd.sqlite_censor = self.httpd.sqlite_censor_conn.cursor()
    # FIXME get overchan db path via arg
    self.httpd.sqlite_overchan_conn = sqlite3.connect('plugins/overchan/overchan.db3')
    self.httpd.sqlite_overchan = self.httpd.sqlite_overchan_conn.cursor()
    self.log('start listening at http://{0}:{1}'.format(self.ip, self.port), 1)
    self.httpd.serve_forever()
    self.httpd.sqlite_hasher_conn.close()
    self.httpd.sqlite_censor_conn.close()
    self.httpd.sqlite_overchan_conn.close()
    self.httpd.rnd.close()
    self.log('bye', 2)

  def log(self, message, debuglevel):
    if self.debug >= debuglevel:
      for line in str(message).split('\n'):
        print "[{0}] {1}".format(self.name, line)

if __name__ == '__main__':
  print "[%s] %s" % ("censor", "this plugin can't run as standalone version. yet.")
  exit(1)
