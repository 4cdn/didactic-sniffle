#!/usr/bin/python
import sqlite3
import time
from datetime import datetime, timedelta
from email.utils import parsedate_tz
from calendar import timegm
import random
import string
import os
import threading
import urllib
from hashlib import sha1, sha512
from email.feedparser import FeedParser
import Image
import codecs
import nacl.signing
from binascii import unhexlify
import re
import traceback
if __name__ == '__main__':
  import signal
  import fcntl
else:
  import Queue

class main(threading.Thread):

  def log(self, loglevel, message):
    if loglevel >= self.loglevel:
      self.logger.log(self.name, message, loglevel)

  def die(self, message):
    self.log(self.logger.CRITICAL, message)
    self.log(self.logger.CRITICAL, 'terminating..')
    self.should_terminate = True
    if __name__ == '__main__':
      exit(1)
    else:
      raise Exception(message)
      return

  def __init__(self, thread_name, logger, args):
    threading.Thread.__init__(self)
    self.name = thread_name
    self.should_terminate = False
    self.logger = logger
    
    # TODO: move sleep stuff to config table
    self.sleep_threshold = 10
    self.sleep_time = 0.02

    error = ''
    for arg in ('template_directory', 'output_directory', 'database_directory', 'temp_directory', 'no_file', 'invalid_file', 'css_file', 'title'):
      if not arg in args:
        error += "%s not in arguments\n" % arg
    if error != '':
      error = error.rstrip("\n")
      self.die(error)
    self.output_directory = args['output_directory']
    self.database_directory = args['database_directory']
    self.template_directory = args['template_directory']
    self.temp_directory = args['temp_directory']
    self.html_title = args['title']
    if not os.path.exists(self.template_directory):
      self.die('error: template directory \'%s\' does not exist' % self.template_directory)
    self.no_file = args['no_file']
    self.invalid_file = args['invalid_file']
    self.document_file = args['document_file']
    self.css_file = args['css_file']
    self.loglevel = self.logger.INFO
    if 'debug' in args:
      try:
        self.loglevel = int(args['debug'])
        if self.loglevel < 0 or self.loglevel > 5:
          self.loglevel = 2
          self.log(self.logger.WARNING, 'invalid value for debug, using default debug level of 2')
      except:
        self.loglevel = 2
        self.log(self.logger.WARNING, 'invalid value for debug, using default debug level of 2')
        
    self.regenerate_html_on_startup = True
    if 'generate_all' in args:
      if args['generate_all'].lower() in ('false', 'no'):
        self.regenerate_html_on_startup = False

    self.threads_per_page = 10
    if 'threads_per_page' in args:
      try:    self.threads_per_page = int(args['threads_per_page'])
      except: pass
    self.pages_per_board = 10
    if 'pages_per_board' in args:
      try:    self.pages_per_board = int(args['pages_per_board'])
      except: pass

    # FIXME messy code is messy
    if not os.path.exists(os.path.join(self.template_directory, self.no_file)):
      self.die('replacement for root posts without picture not found: %s' % os.path.join(self.template_directory, self.no_file))

    if not os.path.exists(os.path.join(self.template_directory, self.invalid_file)):
      self.die('replacement for posts with invalid pictures not found: %s' % os.path.join(self.template_directory, self.invalid_file))
    if not os.path.exists(os.path.join(self.template_directory, self.document_file)):
      self.die('replacement for posts with documents attached (.pdf, .ps) not found: %s' % os.path.join(self.template_directory, self.document_file))
    if not os.path.exists(os.path.join(self.template_directory, self.css_file)):
      self.die('specified CSS file not found in template directory: %s' % os.path.join(self.template_directory, self.css_file))
    error = ''
    for template in ('board.tmpl', 'board_threads.tmpl', 'thread_single.tmpl', 'message_root.tmpl', 'message_child_pic.tmpl', 'message_child_nopic.tmpl', 'signed.tmpl', 'help.tmpl'):
      template_file = os.path.join(self.template_directory, template)
      if not os.path.exists(template_file):
        error += '%s missing\n' % template_file
    if error != '':
      error = error.rstrip("\n")
      self.die(error)
    self.sync_on_startup = False
    if 'sync_on_startup' in args:
      if args['sync_on_startup'].lower() == 'true':
        self.sync_on_startup = True

    # TODO use tuple instead and load in above loop. seriously.
    # statics
    f = codecs.open(os.path.join(self.template_directory, 'help.tmpl'), "r", "utf-8")
    self.template_help = f.read()
    f.close()
    
    # still to convert
    f = codecs.open(os.path.join(self.template_directory, 'stats_usage.tmpl'), "r", "utf-8")
    self.template_stats_usage = f.read()
    f.close()
    f = codecs.open(os.path.join(self.template_directory, 'stats_usage_row.tmpl'), "r", "utf-8")
    self.template_stats_usage_row = f.read()
    f.close()
    f = codecs.open(os.path.join(self.template_directory, 'latest_posts.tmpl'), "r", "utf-8")
    self.template_latest_posts = f.read()
    f.close()
    f = codecs.open(os.path.join(self.template_directory, 'latest_posts_row.tmpl'), "r", "utf-8")
    self.template_latest_posts_row = f.read()
    f.close()
    f = codecs.open(os.path.join(self.template_directory, 'stats_boards.tmpl'), "r", "utf-8")
    self.template_stats_boards = f.read()
    f.close()
    f = codecs.open(os.path.join(self.template_directory, 'stats_boards_row.tmpl'), "r", "utf-8")
    self.template_stats_boards_row = f.read()
    f.close()
    
    # template_engines
    f = codecs.open(os.path.join(self.template_directory, 'board.tmpl'), "r", "utf-8")
    self.t_engine_board = string.Template(
      string.Template(f.read()).safe_substitute(
        help=self.template_help,
        title=self.html_title
      )
    )
    f.close()
    f = codecs.open(os.path.join(self.template_directory, 'thread_single.tmpl'), "r", "utf-8")
    self.t_engine_thread_single = string.Template(
      string.Template(f.read()).safe_substitute(
        help=self.template_help,
        title=self.html_title
      )
    )
    f.close
    f = codecs.open(os.path.join(self.template_directory, 'overview.tmpl'), "r", "utf-8")
    self.t_engine_overview = string.Template(
      string.Template(f.read()).safe_substitute(
        help=self.template_help,
        title=self.html_title
      )
    )
    f.close()
    f = codecs.open(os.path.join(self.template_directory, 'board_threads.tmpl'), "r", "utf-8")
    self.t_engine_board_threads = string.Template(f.read())
    f.close
    f = codecs.open(os.path.join(self.template_directory, 'message_root.tmpl'), "r", "utf-8")
    self.t_engine_message_root = string.Template(f.read())
    f.close()
    f = codecs.open(os.path.join(self.template_directory, 'message_child_pic.tmpl'), "r", "utf-8")
    self.t_engine_message_pic = string.Template(f.read())
    f.close()
    f = codecs.open(os.path.join(self.template_directory, 'message_child_nopic.tmpl'), "r", "utf-8")
    self.t_engine_message_nopic = string.Template(f.read())
    f.close()
    f = codecs.open(os.path.join(self.template_directory, 'signed.tmpl'), "r", "utf-8")
    self.t_engine_signed = string.Template(f.read())
    f.close()
    
    self.linker = re.compile("(&gt;&gt;)([0-9a-f]{10})")
    self.quoter = re.compile("^&gt;(?!&gt;).*", re.MULTILINE)
    self.coder = re.compile('\[code](?!\[/code])(.+?)\[/code]', re.DOTALL)
    
    self.upper_table = {'0': '1',
                        '1': '2',
                        '2': '3',
                        '3': '4',
                        '4': '5',
                        '5': '6',
                        '6': '7',
                        '7': '8',
                        '8': '9',
                        '9': 'a',
                        'a': 'b',
                        'b': 'c',
                        'c': 'd',
                        'd': 'e',
                        'e': 'f',
                        'f': 'g'}

    if __name__ == '__main__':
      i = open(os.path.join(self.template_directory, self.css_file), 'r')
      o = open(os.path.join(self.output_directory, 'styles.css'), 'w')
      o.write(i.read())
      o.close()
      i.close()
      if not 'watch_dir' in args:
        self.log(self.logger.CRITICAL, 'watch_dir not in args')
        self.log(self.logger.CRITICAL, 'terminating..')
        exit(1)
      else:
        self.watch_dir = args['watch_dir']
      if not self.init_standalone():
        exit(1)
    else:
      if not self.init_plugin():
        self.should_terminate = True
        return

  def init_plugin(self):
    self.log(self.logger.INFO, 'initializing as plugin..')
    try:
      # load required imports for PIL
      something = Image.open(os.path.join(self.template_directory, self.no_file))
      modifier = float(180) / something.size[0]
      x = int(something.size[0] * modifier)
      y = int(something.size[1] * modifier)
      if something.mode == 'RGBA' or something.mode == 'LA':
        thumb_name = 'nope_loading_PIL.png'
      else:
        something = something.convert('RGB')
        thumb_name = 'nope_loading_PIL.jpg'
      something = something.resize((x,y), Image.ANTIALIAS)
      out = os.path.join(self.template_directory, thumb_name)
      something.save(out, optimize=True)
      del something
      os.remove(out)
    except IOError as e:
      self.die('error: can\'t load PIL library')
      return False
    self.queue = Queue.Queue()
    return True

  def init_standalone(self):
    self.log(self.logger.INFO, 'initializing as standalone..')
    signal.signal(signal.SIGIO, self.signal_handler)
    try:
      fd = os.open(self.watching, os.O_RDONLY)
    except OSError as e:
      if e.errno == 2:
        self.die(e)
        exit(1)
      else:
        raise e
    fcntl.fcntl(fd, fcntl.F_SETSIG, 0)
    fcntl.fcntl(fd, fcntl.F_NOTIFY,
                fcntl.DN_MODIFY | fcntl.DN_CREATE | fcntl.DN_MULTISHOT)
    self.past_init()
    return True

  def past_init(self):
    required_dirs = list()
    required_dirs.append(self.output_directory)
    required_dirs.append(os.path.join(self.output_directory, '..', 'spamprotector'))
    required_dirs.append(os.path.join(self.output_directory, 'img'))
    required_dirs.append(os.path.join(self.output_directory, 'thumbs'))
    required_dirs.append(self.database_directory)
    required_dirs.append(self.temp_directory)
    for directory in required_dirs:
      if not os.path.exists(directory):
        os.mkdir(directory)
    del required_dirs
    # TODO use softlinks or at least cp instead
    # ^ hardlinks not gonna work because of remote filesystems
    # ^ softlinks not gonna work because of nginx chroot
    # ^ => cp
    # FIXME messy code is messy
    for file_source, file_target in (
        (self.css_file, 'styles.css'),
        ('user.css', 'user.css'),
        (self.no_file, os.path.join('img', self.no_file)),
        (self.no_file, os.path.join('thumbs', self.no_file)),
      ):
        i = open(os.path.join(self.template_directory, file_source), 'r')
        o = open(os.path.join(self.output_directory, file_target), 'w')
        o.write(i.read())
        o.close()
        i.close()

    # TODO: generate gen_thumbnail(source, dest) returning true/false
    link = os.path.join(self.output_directory, 'thumbs', self.invalid_file)
    if not os.path.exists(link):
      try:
        something = Image.open(os.path.join(self.template_directory, self.invalid_file))
        modifier = float(180) / something.size[0]
        x = int(something.size[0] * modifier)
        y = int(something.size[1] * modifier)
        if not (something.mode == 'RGBA' or something.mode == 'LA'):
          something = something.convert('RGB')
        something = something.resize((x,y), Image.ANTIALIAS)
        something.save(link, optimize=True)
        del something
      except IOError as e:
        self.log(self.logger.ERROR, 'can\'t save %s. wtf? %s' % (link, e))
    link = os.path.join(self.output_directory, 'thumbs', self.document_file)
    if not os.path.exists(link):
      try:
        something = Image.open(os.path.join(self.template_directory, self.document_file))
        modifier = float(180) / something.size[0]
        x = int(something.size[0] * modifier)
        y = int(something.size[1] * modifier)
        if not (something.mode == 'RGBA' or something.mode == 'LA'):
          something = something.convert('RGB')
        something = something.resize((x,y), Image.ANTIALIAS)
        something.save(link, optimize=True)
        del something
      except IOError as e:
        self.log(self.logger.ERROR, 'can\'t save %s. wtf? %s' % (link, e))
    self.regenerate_boards = list()
    self.regenerate_threads = list()
    self.missing_parents = dict()
    self.sqlite_hasher_conn = sqlite3.connect('hashes.db3')
    self.db_hasher = self.sqlite_hasher_conn.cursor() 
    self.sqlite_conn = sqlite3.connect(os.path.join(self.database_directory, 'overchan.db3'))
    self.sqlite = self.sqlite_conn.cursor()
    # FIXME use config table with current db version + def update_db(db_version) like in censor plugin
    self.sqlite.execute('''CREATE TABLE IF NOT EXISTS groups
               (group_id INTEGER PRIMARY KEY AUTOINCREMENT, group_name text UNIQUE, article_count INTEGER, last_update INTEGER)''')
    self.sqlite.execute('''CREATE TABLE IF NOT EXISTS articles
               (article_uid text, group_id INTEGER, sender text, email text, subject text, sent INTEGER, parent text, message text, imagename text, imagelink text, thumblink text, last_update INTEGER, public_key text, PRIMARY KEY (article_uid, group_id))''')
    
    # TODO add some flag like ability to carry different data for groups like (removed + added manually + public + hidden + whatever)
    #self.sqlite.execute('''CREATE TABLE IF NOT EXISTS flags
    #           (flag_id INTEGER PRIMARY KEY AUTOINCREMENT, flag_name text UNIQUE, flag text)''')
    #try:
    #  self.sqlite.execute('INSERT INTO flags (flag_name, flag) VALUES (?,?)', ('removed', str(0b1)))
    #except:
    #  pass
    try:
      self.sqlite.execute('ALTER TABLE articles ADD COLUMN public_key text')
    except:
      pass
    try:
      self.sqlite.execute('ALTER TABLE articles ADD COLUMN received INTEGER DEFAULT 0')
    except:
      pass
    try:
      self.sqlite.execute('ALTER TABLE groups ADD COLUMN blocked INTEGER DEFAULT 0')
    except:
      pass
    self.sqlite.execute('CREATE INDEX IF NOT EXISTS articles_group_idx ON articles(group_id);')
    self.sqlite.execute('CREATE INDEX IF NOT EXISTS articles_parent_idx ON articles(parent);')
    self.sqlite.execute('CREATE INDEX IF NOT EXISTS articles_article_idx ON articles(article_uid);')
    self.sqlite_conn.commit()
    
    if self.regenerate_html_on_startup:
      self.regenerate_all_html()

  def regenerate_all_html(self):
    for group_row in self.sqlite.execute('SELECT group_id FROM groups WHERE blocked != 1').fetchall():
      if group_row[0] not in self.regenerate_boards:
        self.regenerate_boards.append(group_row[0])
    for thread_row in self.sqlite.execute('SELECT article_uid FROM articles WHERE parent = "" OR parent = article_uid ORDER BY last_update DESC').fetchall():
      if thread_row[0] not in self.regenerate_threads:
        self.regenerate_threads.append(thread_row[0])

  def shutdown(self):
    self.running = False

  def add_article(self, message_id, source="article", timestamp=None):
    self.queue.put((source, message_id, timestamp))
    
  def handle_control(self, lines, timestamp):
    # FIXME how should board-add and board-del react on timestamps in the past / future
    self.log(self.logger.DEBUG, 'got control message: %s' % lines)
    root_posts = list()
    for line in lines.split("\n"):
      if line.lower().startswith('overchan-board-add'):
        group_name = line.lower().split(" ")[1]
        if '/' in group_name:
          self.log(self.logger.WARNING, 'got overchan-board-add with invalid group name: \'%s\', ignoring' % group_name)
          continue
        try:
          self.sqlite.execute('UPDATE groups SET blocked = 0 WHERE group_name = ?', (group_name,))
          self.log(self.logger.INFO, 'unblocked existing board: \'%s\'' % group_name)
        except:
          self.sqlite.execute('INSERT INTO groups(group_name, article_count, last_update) VALUES (?,?,?)', (group_name, 0, int(time.time())))
          self.log(self.logger.INFO, 'added new board: \'%s\'' % group_name)
        self.sqlite_conn.commit()
        self.regenerate_all_html()
      elif line.lower().startswith("overchan-board-del"):
        group_name = line.lower().split(" ")[1]
        try:
          self.sqlite.execute('UPDATE groups SET blocked = 1 WHERE group_name = ?', (group_name,))
          self.log(self.logger.INFO, 'blocked board: \'%s\'' % group_name)
          self.sqlite_conn.commit()
          self.regenerate_all_html()
        except:
          self.log(self.logger.WARNING, 'should delete board %s but there is no board with that name' % group_name)
      elif line.lower().startswith("overchan-delete-attachment "):
        message_id = line.lower().split(" ")[1]
        if os.path.exists(os.path.join("articles", "restored", message_id)):
          self.log(self.logger.DEBUG, 'message has been restored: %s. ignoring overchan-delete-attachment' % message_id)
          continue
        row = self.sqlite.execute("SELECT imagelink, thumblink, parent, group_id, received FROM articles WHERE article_uid = ?", (message_id,)).fetchone()
        if not row:
          self.log(self.logger.DEBUG, 'should delete attachments for message_id %s but there is no article matching this message_id' % message_id)
          continue
        #if row[4] > timestamp:
        #  self.log("post more recent than control message. ignoring delete-attachment for %s" % message_id, 2)
        #  continue
        if row[0] == 'invalid':
          self.log(self.logger.DEBUG, 'attachment already deleted. ignoring delete-attachment for %s' % message_id)
          continue
        self.log(self.logger.INFO, 'deleting attachments for message_id %s' % message_id)
        if row[3] not in self.regenerate_boards:
          self.regenerate_boards.append(row[3])
        if row[2] == '':
          if not message_id in self.regenerate_threads:
            self.regenerate_threads.append(message_id)
        elif not row[2] in self.regenerate_threads:
          self.regenerate_threads.append(row[2])
        if len(row[0]) > 0:
          self.log(self.logger.INFO, 'deleting attachment for message_id %s: img/%s' % (message_id, row[0]))
          try:
            os.unlink(os.path.join(self.output_directory, "img", row[0]))
          except Exception as e:
            self.log(self.logger.WARNING, 'could not delete attachment %s: %s' % (row[0], e))
        if len(row[1]) > 0 and row[1] != "invalid":
          self.log(self.logger.INFO, 'deleting attachment for message_id %s: thumbs/%s' % (message_id, row[1]))
          try:
            os.unlink(os.path.join(self.output_directory, "thumbs", row[1]))
          except Exception as e:
            self.log(self.logger.WARNING, 'could not delete attachment %s: %s' % (row[1], e))
        self.sqlite.execute('UPDATE articles SET imagelink = "invalid", thumblink = "invalid", imagename = "invalid", public_key = "" WHERE article_uid = ?', (message_id,))
        self.sqlite_conn.commit()
      elif line.lower().startswith("delete "):
        message_id = line.lower().split(" ")[1]
        if os.path.exists(os.path.join("articles", "restored", message_id)):
          self.log(self.logger.DEBUG, 'message has been restored: %s. ignoring delete' % message_id)
          continue
        row = self.sqlite.execute("SELECT imagelink, thumblink, parent, group_id, received FROM articles WHERE article_uid = ?", (message_id,)).fetchone()
        if not row:
          self.log(self.logger.DEBUG, 'should delete message_id %s but there is no article matching this message_id' % message_id)
          continue
        #if row[4] > timestamp:
        #  self.log("post more recent than control message. ignoring delete for %s" % message_id, 2)
        #  continue
        # FIXME: allow deletion of earlier delete-attachment'ed messages
        #if row[0] == 'invalid':
        #  self.log("message already deleted/censored. ignoring delete for %s" % message_id, 4)
        #  continue
        self.log(self.logger.INFO, 'deleting message_id %s' % message_id)
        if row[3] not in self.regenerate_boards:
          self.regenerate_boards.append(row[3])
        if row[2] == '':
          # root post
          if int(self.sqlite.execute("SELECT count(article_uid) FROM articles WHERE parent = ?", (message_id,)).fetchone()[0]) > 0:
            # root posts with child posts
            self.log(self.logger.DEBUG, 'deleting message_id %s, got a root post with attached child posts' % message_id)
            root_posts.append(message_id)
            self.sqlite.execute('UPDATE articles SET imagelink = "invalid", thumblink = "invalid", imagename = "invalid", message = "this post has been deleted by some evil mod", sender = "deleted", email = "deleted", subject = "deleted", public_key = "" WHERE article_uid = ?', (message_id,))
            if message_id not in self.regenerate_threads:
              self.regenerate_threads.append(message_id)
          else:
            # root posts without child posts
            self.log(self.logger.DEBUG, 'deleting message_id %s, got a root post without any child posts' % message_id)
            self.sqlite.execute('DELETE FROM articles WHERE article_uid = ?', (message_id,))
            try:
              os.unlink(os.path.join(self.output_directory, "thread-%s.html" % sha1(message_id).hexdigest()[:10]))
            except Exception as e:
              self.log(self.logger.WARNING, 'could not delete thread for message_id %s: %s' % (message_id, e))
        else:
          # child post
          self.log(self.logger.DEBUG, 'deleting message_id %s, got a child post' % message_id)
          self.sqlite.execute('DELETE FROM articles WHERE article_uid = ?', (message_id,))
          if row[2] not in self.regenerate_threads:
            self.regenerate_threads.append(row[2])
          # FIXME: add detection for parent == deleted message (not just censored) and if true, add to root_posts 
        if len(row[0]) > 0 and row[0] != "invalid":
          self.log(self.logger.INFO, 'deleting message_id %s, attachment %s' % (message_id, row[0]))
          try:
            os.unlink(os.path.join(self.output_directory, "img", row[0]))
          except Exception as e:
            self.log(self.logger.WARNING, 'could not delete img/%s: %s' % (row[0], e))
        if len(row[1]) > 0 and row[1] != "invalid":
          self.log(self.logger.INFO, 'deleting message_id %s, thumb %s' % (message_id, row[1]))
          try:
            os.unlink(os.path.join(self.output_directory, "thumbs", row[1]))
          except Exception as e:
            self.log(self.logger.WARNING, 'could not delete thumbs/%s: %s' % (row[1], e))
        self.sqlite_conn.commit()
    for post in root_posts:
      if int(self.sqlite.execute("SELECT count(article_uid) FROM articles WHERE parent = ? and parent != article_uid", (message_id,)).fetchone()[0]) == 0:
        self.log(self.logger.DEBUG, 'deleting message_id %s, root_post has no more childs' % message_id)
        self.sqlite.execute('DELETE FROM articles WHERE article_uid = ?', (message_id,))
        self.sqlite_conn.commit()
        try:
          os.unlink(os.path.join(self.output_directory, "thread-%s" % sha1(message_id).hexdigest()[:10]))
        except Exception as e:
          self.log(self.logger.WARNING, 'could not delete thread for message_id %s: %s' % (message_id, e))
      else:
        self.log(self.logger.DEBUG, 'deleting message_id %s, root_post still has childs' % message_id)

  def signal_handler(self, signum, frame):
    # FIXME use try: except: around open(), also check for duplicate here
    for item in os.listdir(self.watching):
      link = os.path.join(self.watching, item)
      f = open(link, 'r')
      if not self.parse_message(message_id, f):
        f.close()
      os.remove(link)
    if len(self.regenerate_boards) > 0:
      for board in self.regenerate_boards:
        self.generate_board(board)
      del self.regenerate_boards[:]
    if len(self.regenerate_threads) > 0:
      for thread in self.regenerate_threads:
        self.generate_thread(thread)
      del self.regenerate_threads[:]

  def run(self):
    if self.should_terminate:
      return
    if  __name__ == '__main__':
      return
    self.log(self.logger.INFO, 'starting up as plugin..')
    self.past_init()
    self.running = True
    regen_overview = False
    got_control = False
    while self.running:
      try:
        ret = self.queue.get(block=True, timeout=1)
        if ret[0] == "article":
          message_id = ret[1]
          if self.sqlite.execute('SELECT subject FROM articles WHERE article_uid = ? AND imagelink != "invalid"', (message_id,)).fetchone():
            self.log(self.logger.DEBUG, '%s already in database..' % message_id)
            continue
          #message_id = self.queue.get(block=True, timeout=1)
          self.log(self.logger.DEBUG, 'got article %s' % message_id)
          try:
            f = open(os.path.join('articles', message_id), 'r')
            if not self.parse_message(message_id, f):
              f.close()
              #self.log(self.logger.WARNING, 'got article %s, parse_message failed. somehow.' % message_id)
          except Exception as e:
            self.log(self.logger.WARNING, 'something went wrong while trying to parse article %s:' % message_id)
            self.log(self.logger.WARNING, traceback.format_exc())
            try:
              f.close()
            except:
              pass
        elif ret[0] == "control":
          got_control = True
          self.handle_control(ret[1], ret[2])
        else:
          self.log(self.logger.ERROR, 'found article with unknown source: %s' % ret[0])

        if self.queue.qsize() > self.sleep_threshold:
          time.sleep(self.sleep_time)
      except Queue.Empty as e:
        if len(self.regenerate_boards) > 0:
          do_sleep = len(self.regenerate_boards) > self.sleep_threshold
          if do_sleep:
            self.log(self.logger.DEBUG, 'boards: should sleep')
          for board in self.regenerate_boards:
            self.generate_board(board)
            if do_sleep: time.sleep(self.sleep_time)
          self.regenerate_boards = list()
          regen_overview = True
        if len(self.regenerate_threads) > 0:
          do_sleep = len(self.regenerate_threads) > self.sleep_threshold
          if do_sleep:
            self.log(self.logger.DEBUG, 'threads: should sleep')
          for thread in self.regenerate_threads:
            self.generate_thread(thread)
            if do_sleep: time.sleep(self.sleep_time)
          self.regenerate_threads = list()
          regen_overview = True
        if regen_overview:
          self.generate_overview()
          regen_overview = False
        if got_control:
          self.sqlite_conn.commit()
          self.sqlite.execute('VACUUM;')
          self.sqlite_conn.commit()
          got_control = False
    self.sqlite_conn.close()
    self.sqlite_hasher_conn.close()
    self.log(self.logger.INFO, 'bye')

  def basicHTMLencode(self, inputString):
    return inputString.replace('<', '&lt;').replace('>', '&gt;')
  
  def generate_pubkey_short_utf_8(self, full_pubkey_hex, length=6):
    pub_short = ''
    for x in range(0, length / 2):
      pub_short +=  '&#%i;' % (9600 + int(full_pubkey_hex[x*2:x*2+2], 16))
    length = length - (length / 2)
    for x in range(0, length):
      pub_short += '&#%i;' % (9600 + int(full_pubkey_hex[-(length*2):][x*2:x*2+2], 16))
    return pub_short

  def upp_it(self, data):
    if data[-1] not in self.upper_table:
      return data
    return data[:-1] + self.upper_table[data[-1]]
    
  def linkit(self, rematch):
    row = self.db_hasher.execute("SELECT message_id FROM article_hashes WHERE message_id_hash >= ? and message_id_hash < ?", (rematch.group(2), self.upp_it(rematch.group(2)))).fetchall()
    if not row:
      # hash not found
      return rematch.group(0)
    if len(row) > 1:
      # multiple matches for that 10 char hash
      return rematch.group(0)
    message_id = row[0][0]
    parent_row = self.sqlite.execute("SELECT parent FROM articles WHERE article_uid = ?", (message_id,)).fetchone()
    if not parent_row:
      # not an overchan article (anymore)
      return rematch.group(0)
    parent_id = parent_row[0]
    if parent_id == "":
      # article is root post
      return '%s<a href="thread-%s.html">%s</a>' % (rematch.group(1), rematch.group(2), rematch.group(2))
    # article has a parent
    # FIXME: cache results somehow?
    parent = sha1(parent_id).hexdigest()[:10]
    return '%s<a href="thread-%s.html#%s">%s</a>' % (rematch.group(1), parent, rematch.group(2), rematch.group(2))
  
  def quoteit(self, rematch):
    return '<span class="quote">%s</span>' % rematch.group(0).rstrip("\r")

  def codeit(self, rematch):
    return '<div class="code">%s</div>' % rematch.group(1)

  def parse_message(self, message_id, fd):
    self.log(self.logger.INFO, 'new message: %s' % message_id)
    hash_message_uid = sha1(message_id).hexdigest()
    identifier = hash_message_uid[:10]
    subject = 'None'
    sent = 0
    sender = 'Anonymous'
    email = 'nobody@no.where'
    parent = ''
    groups = list()
    sage = False
    signature = None
    public_key = ''
    header_found = False
    parser = FeedParser()
    line = fd.readline()
    while line != '':
      parser.feed(line)
      lower_line = line.lower()
      if lower_line.startswith('subject:'):
        subject = self.basicHTMLencode(line.split(' ', 1)[1][:-1])
      elif lower_line.startswith('date:'):
        sent = line.split(' ', 1)[1][:-1]
        sent_tz = parsedate_tz(sent)
        if sent_tz:
          offset = 0
          if sent_tz[-1]: offset = sent_tz[-1]
          sent = timegm((datetime(*sent_tz[:6]) - timedelta(seconds=offset)).timetuple())
        else:
          sent = int(time.time())
      elif lower_line.startswith('from:'):
        sender = self.basicHTMLencode(line.split(' ', 1)[1][:-1].split(' <', 1)[0])
        try:
          email = self.basicHTMLencode(line.split(' ', 1)[1][:-1].split(' <', 1)[1].replace('>', ''))
        except:
          pass
      elif lower_line.startswith('references:'):
        parent = line[:-1].split(' ')[1]
      elif lower_line.startswith('newsgroups:'):
        group_in = lower_line[:-1].split(' ', 1)[1]
        if ';' in group_in:
          groups_in = group_in.split(';')
          for group_in in groups_in:
            if group_in.startswith('overchan.'):
              groups.append(group_in)
        elif ',' in group_in:
          groups_in = group_in.split(',')
          for group_in in groups_in:
            if group_in.startswith('overchan.'):
              groups.append(group_in)
        else:
          groups.append(group_in)
      elif lower_line.startswith('x-sage:'):
        sage = True
      elif lower_line.startswith("x-pubkey-ed25519:"):
        public_key = lower_line[:-1].split(' ', 1)[1]
      elif lower_line.startswith("x-signature-ed25519-sha512:"):
        signature = lower_line[:-1].split(' ', 1)[1]
      elif line == '\n':
        header_found = True
        break
      line = fd.readline()

    if not header_found:
      #self.log(self.logger.WARNING, '%s malformed article' % message_id)
      #return False
      raise Exception('%s malformed article' % message_id)
    if signature:
      if public_key != '':
        self.log(self.logger.DEBUG, 'got signature with length %i and content \'%s\'' % (len(signature), signature))
        self.log(self.logger.DEBUG, 'got public_key with length %i and content \'%s\'' % (len(public_key), public_key))
        if not (len(signature) == 128 and len(public_key) == 64):
          public_key = ''
    group_ids = list()
    for group in groups:
      result = self.sqlite.execute('SELECT group_id FROM groups WHERE group_name=? AND blocked = 0', (group,)).fetchone()
      if not result:
        try:
          self.sqlite.execute('INSERT INTO groups(group_name, article_count, last_update) VALUES (?,?,?)', (group, 1, int(time.time())))
          self.sqlite_conn.commit()
        except:
          self.log(self.logger.INFO, 'ignoring message for blocked group %s' % group)
          continue
        self.regenerate_all_html()
        group_ids.append(int(self.sqlite.execute('SELECT group_id FROM groups WHERE group_name=?', (group,)).fetchone()[0]))
      else:
        group_ids.append(int(result[0]))
    if len(group_ids) == 0:
      self.log(self.logger.DEBUG, 'no groups left which are not blocked. ignoring %s' % message_id)
      return False
    for group_id in group_ids:
      if group_id not in self.regenerate_boards:
        self.regenerate_boards.append(group_id)

    if parent != '' and parent != message_id:
      last_update = sent
      if parent not in self.regenerate_threads:
        self.regenerate_threads.append(parent)
      if not sage:
        result = self.sqlite.execute('SELECT last_update FROM articles WHERE article_uid = ?', (parent,)).fetchone()
        if result:
          parent_last_update = result[0]
          if sent > parent_last_update:
            self.sqlite.execute('UPDATE articles SET last_update=? WHERE article_uid=?', (sent, parent))
            self.sqlite_conn.commit()
        else:
          self.log(self.logger.INFO, 'missing parent %s for post %s' %  (parent, message_id))
          if parent in self.missing_parents:
            if sent > self.missing_parents[parent]:
              self.missing_parents[parent] = sent
          else:
            self.missing_parents[parent] = sent
    else:
      # root post
      if not message_id in self.missing_parents:
        last_update = sent
      else:
        if self.missing_parents[message_id] > sent:
          # obviously the case. still we check for invalid dates here
          last_update = self.missing_parents[message_id]
        else:
          last_update = sent
        del self.missing_parents[message_id]
        self.log(self.logger.INFO, 'found a missing parent: %s' % message_id)
        if len(self.missing_parents) > 0:
          self.log(self.logger.INFO, 'still missing %i parents' % len(self.missing_parents))
      if message_id not in self.regenerate_threads:
        self.regenerate_threads.append(message_id)

    #parser = FeedParser()
    if public_key != '':
      bodyoffset = fd.tell()
      hasher = sha512()
      oldline = None
      for line in fd:
        if oldline:
          hasher.update(oldline)
        oldline = line.replace("\n", "\r\n")
      hasher.update(oldline.replace("\r\n", ""))
      fd.seek(bodyoffset)
      try:
        self.log(self.logger.INFO, 'trying to validate signature.. ')
        nacl.signing.VerifyKey(unhexlify(public_key)).verify(hasher.digest(), unhexlify(signature))
        self.log(self.logger.INFO, 'validated')
      except Exception as e:
        public_key = ''
        self.log(self.logger.INFO, 'failed: %s' % e)
      del hasher
      del signature
    parser.feed(fd.read())
    fd.close()
    result = parser.close()
    del parser
    image_name_original = ''
    image_name = ''
    thumb_name = ''
    message = ''
    # TODO: check if out dir is remote fs, use os.rename if not
    if result.is_multipart():
      self.log(self.logger.DEBUG, 'message is multipart, length: %i' % len(result.get_payload()))
      if len(result.get_payload()) == 1 and result.get_payload()[0].get_content_type() == "multipart/mixed":
        result = result.get_payload()[0]
      for part in result.get_payload():
        self.log(self.logger.DEBUG, 'got part == %s' % part.get_content_type())
        if part.get_content_type().startswith('image/'):
          tmp_link = os.path.join(self.temp_directory, 'tmpImage')
          f = open(tmp_link, 'w')
          f.write(part.get_payload(decode=True))
          f.close()
          # get hash for filename
          f = open(tmp_link, 'r')
          image_name_original = self.basicHTMLencode(part.get_filename().replace('/', '_').replace('"', '_'))
          # FIXME read line by line and use hasher.update(line)
          imagehash = sha1(f.read()).hexdigest()
          image_name = image_name_original.split('.')[-1].lower()
          if image_name in ('html', 'php'):
            image_name = 'txt'
          image_name = imagehash + '.' + image_name
          out_link = os.path.join(self.output_directory, 'img', image_name)
          f.close()
          # copy to out directory with new filename
          # FIXME use os.rename() for the sake of good
          c = open(out_link, 'w')
          f = open(tmp_link, 'r')
          c.write(f.read())
          c.close()
          f.close()
          if image_name_original.split('.')[-1].lower() == 'gif':
            # copy to thumb directory with new filename
            # FIXME: use relative link instead
            thumb_link = os.path.join(self.output_directory, 'thumbs', image_name)
            thumb_name = image_name
            c = open(thumb_link, 'w')
            f = open(tmp_link, 'r')
            c.write(f.read())
            c.close()
            f.close()
          else:
            # create thumb, convert to RGB and use jpeg if no transparency involved, png if it is
            try:
              thumb = Image.open(out_link)
              # always use width for modifier
              modifier = float(180) / thumb.size[0]
              #if thumb.size[0] > thumb.size[1]:
              #  modifier = float(200) / thumb.size[0]
              #else:
              #  modifier = float(200) / thumb.size[1]
              x = int(thumb.size[0] * modifier)
              y = int(thumb.size[1] * modifier)
              self.log(self.logger.DEBUG, 'old image size: %ix%i, new image size: %ix%i' %  (thumb.size[0], thumb.size[1], x, y))
              if thumb.mode == 'RGBA' or thumb.mode == 'LA':
                thumb_name = imagehash + '.png'
              else:
                thumb = thumb.convert('RGB')
                thumb_name = imagehash + '.jpg'
              thumb_link = os.path.join(self.output_directory, 'thumbs', thumb_name)
              thumb = thumb.resize((x,y), Image.ANTIALIAS)
              #thumb.thumbnail((200, 200), Image.ANTIALIAS)
              thumb.save(thumb_link, optimize=True)
              del thumb
            except Exception as e:
              self.log(e, 3)
              thumb_name = 'invalid'
          os.remove(tmp_link)
          #os.rename('tmp/tmpImage', 'html/img/' + imagelink) # damn remote file systems and stuff
        elif part.get_content_type().lower() in ('application/pdf', 'application/postscript', 'application/ps'):
          tmp_link = os.path.join(self.temp_directory, 'tmpImage')
          f = open(tmp_link, 'w')
          f.write(part.get_payload(decode=True))
          f.close()
          # get hash for filename
          f = open(tmp_link, 'r')
          image_name_original = self.basicHTMLencode(part.get_filename().replace('/', '_').replace('"', '_'))
          imagehash = sha1(f.read()).hexdigest()
          image_name = image_name_original.split('.')[-1].lower()
          if image_name in ('html', 'php'):
            image_name = 'txt'
          image_name = imagehash + '.' + image_name
          out_link = os.path.join(self.output_directory, 'img', image_name)
          f.close()
          # copy to out directory with new filename
          c = open(out_link, 'w')
          f = open(tmp_link, 'r')
          c.write(f.read())
          c.close()
          f.close()
          thumb_name = 'document'
          os.remove(tmp_link)
        elif part.get_content_type().lower() == 'text/plain':
          message += part.get_payload(decode=True)
        else:
          message += '\n----' + part.get_content_type() + '----\n'
          message += 'invalid content type\n'
          message += '----' + part.get_content_type() + '----\n\n'
    else:
      if result.get_content_type().lower() == 'text/plain':
        message += result.get_payload(decode=True)
      else:
        message += '\n----' + result.get_content_type() + '----\n'
        message += 'invalid content type\n'
        message += '----' + result.get_content_type() + '----\n\n'
    del result
    message = self.basicHTMLencode(message)
    if self.sqlite.execute('SELECT article_uid FROM articles WHERE article_uid=?', (message_id,)).fetchone():
      # post has been censored and is now being restored. just delete post for all groups so it can be reinserted
      self.log(self.logger.INFO, 'post has been censored and is now being restored: %s' % message_id) 
      self.sqlite.execute('DELETE FROM articles WHERE article_uid=?', (message_id,))
      self.sqlite_conn.commit()
    for group_id in group_ids:
      self.sqlite.execute('INSERT INTO articles(article_uid, group_id, sender, email, subject, sent, parent, message, imagename, imagelink, thumblink, last_update, public_key, received) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (message_id, group_id, sender.decode('UTF-8'), email.decode('UTF-8'), subject.decode('UTF-8'), sent, parent, message.decode('UTF-8'), image_name_original.decode('UTF-8'), image_name, thumb_name, last_update, public_key, int(time.time())))
      self.sqlite.execute('UPDATE groups SET last_update=?, article_count = (SELECT count(article_uid) FROM articles WHERE group_id = ?) WHERE group_id = ?', (int(time.time()), group_id, group_id))
    self.sqlite_conn.commit()
    return True

  def generate_board(self, group_id):
    threads_per_page = self.threads_per_page
    pages_per_board = self.pages_per_board
    # FIXME: cache board_name, _unquoted, _full
    full_board_name_unquoted = self.sqlite.execute('SELECT group_name FROM groups WHERE group_id = ?', (group_id,)).fetchone()[0].replace('"', '').replace('/', '')
    full_board_name = self.basicHTMLencode(full_board_name_unquoted)
    board_name_unquoted = full_board_name_unquoted.split('.', 1)[1]
    board_name = full_board_name.split('.', 1)[1]
    boardlist = list()
    # FIXME cache group list html globally like censor_httpd_navigation
    for group_row in self.sqlite.execute('SELECT group_name, group_id FROM groups WHERE blocked = 0 ORDER by group_name ASC').fetchall():
      current_group_name = group_row[0].split('.', 1)[1].replace('"', '').replace('/', '')
      current_group_name_encoded = self.basicHTMLencode(current_group_name)
      if group_row[1] != group_id:
        boardlist.append('&nbsp;<a href="%s-1.html">%s</a>&nbsp;|' % (current_group_name, current_group_name_encoded))
      else:
        boardlist.append('&nbsp;' + current_group_name_encoded + '&nbsp;|')
    boardlist[-1] = boardlist[-1][:-1]
    boardlist = ''.join(boardlist)
    
    threads = int(self.sqlite.execute('SELECT count(group_id) FROM (SELECT group_id FROM articles WHERE group_id = ? AND (parent = "" OR parent = article_uid) LIMIT ?)', (group_id, threads_per_page * pages_per_board)).fetchone()[0])
    pages = int(threads / threads_per_page)
    if threads % threads_per_page != 0:
      pages += 1;
    thread_counter = 0
    page_counter = 1
    threads = list()
      
    for root_row in self.sqlite.execute('SELECT article_uid, sender, subject, sent, message, imagename, imagelink, thumblink, public_key FROM articles WHERE group_id = ? AND (parent = "" OR parent = article_uid) ORDER BY last_update DESC LIMIT ?', (group_id, threads_per_page * pages_per_board)).fetchall():
      t_engine_mapper_root = dict() 
      root_message_id_hash = sha1(root_row[0]).hexdigest()
      if thread_counter == threads_per_page:
        self.log(self.logger.INFO, 'generating %s/%s-%s.html' % (self.output_directory, board_name_unquoted, page_counter))
        t_engine_mapper_board = dict()
        t_engine_mapper_board['threads'] = ''.join(threads)
        pagelist = list()
        for page in xrange(1, pages + 1):
          if page != page_counter:
            pagelist.append('<a href="{0}-{1}.html">[{1}]</a>&nbsp;'.format(board_name_unquoted, page))
          else:
            pagelist.append('[{0}]&nbsp;'.format(page))
        t_engine_mapper_board['pagelist'] = ''.join(pagelist)
        t_engine_mapper_board['boardlist'] = boardlist
        t_engine_mapper_board['full_board'] = full_board_name_unquoted
        t_engine_mapper_board['board'] = board_name
        t_engine_mapper_board['target'] =  "{0}-1.html".format(board_name_unquoted)
        f = codecs.open(os.path.join(self.output_directory, '{0}-{1}.html'.format(board_name_unquoted, page_counter)), 'w', 'UTF-8')
        f.write(self.t_engine_board.substitute(t_engine_mapper_board))
        f.close()
        threads = list()
        page_counter += 1
        thread_counter = 0
      thread_counter += 1
      if root_row[6] != '':
        root_imagelink = root_row[6]
        if root_row[7] == 'document':
          root_thumblink = self.document_file
        elif root_row[7] == 'invalid':
          root_thumblink = self.invalid_file
        else:
          root_thumblink = root_row[7]
      else:
        root_imagelink = self.no_file
        root_thumblink = self.no_file
      if root_row[8]:
        if root_row[8] != '':
          t_engine_mapper_root['signed'] = self.t_engine_signed.substitute(
            articlehash=root_message_id_hash[:10],
            pubkey=root_row[8],
            pubkey_short=self.generate_pubkey_short_utf_8(root_row[8])
          ) 
        else:
          t_engine_mapper_root['signed'] = ''
      else:
        t_engine_mapper_root['signed'] = ''
      if len(root_row[4].split('\n')) > 20:
        message = '\n'.join(root_row[4].split('\n')[:20]) + '\n[..] <a href="thread-%s.html"><i>message too large</i></a>\n' % root_message_id_hash[:10]
      elif len(root_row[4]) > 1000:
        message = root_row[4][:1000] + '\n[..] <a href="thread-%s.html"><i>message too large</i></a>\n' % root_message_id_hash[:10]
      else:
        message = root_row[4]
      message = self.linker.sub(self.linkit, message)
      message = self.quoter.sub(self.quoteit, message)
      message = self.coder.sub(self.codeit, message)
      
      child_count = int(self.sqlite.execute('SELECT count(article_uid) FROM articles WHERE parent = ? AND parent != article_uid AND group_id = ?', (root_row[0], group_id)).fetchone()[0])
      if child_count > 4: missing = child_count - 4
      else: missing = 0
      if missing > 0:
        if missing == 1: post = "post"
        else: post = "posts"
        message += '\n<a href="thread-{0}.html">{1} {2} omitted</a>'.format(root_message_id_hash[:10], missing, post)

      t_engine_mapper_root['message'] = message
      t_engine_mapper_root['articlehash'] = root_message_id_hash[:10]
      t_engine_mapper_root['articlehash_full'] = root_message_id_hash
      t_engine_mapper_root['author'] = root_row[1]
      t_engine_mapper_root['subject'] = root_row[2]
      t_engine_mapper_root['sent'] = datetime.utcfromtimestamp(root_row[3]).strftime('%d.%m.%Y (%a) %H:%M')
      t_engine_mapper_root['imagelink'] = root_imagelink
      t_engine_mapper_root['thumblink'] = root_thumblink
      t_engine_mapper_root['imagename'] =  root_row[5]

      childs = list()
      childs.append('') # FIXME: the fuck is this for?

      for child_row in self.sqlite.execute('SELECT * FROM (SELECT article_uid, sender, subject, sent, message, imagename, imagelink, thumblink, public_key FROM articles WHERE parent = ? AND parent != article_uid AND group_id = ? ORDER BY sent DESC LIMIT 4) ORDER BY sent ASC', (root_row[0], group_id)).fetchall():
        t_engine_mapper_child = dict()
        article_hash = sha1(child_row[0]).hexdigest()
        if child_row[6] != '':
          if child_row[7] == 'invalid':
            child_thumblink = self.invalid_file
          elif child_row[7] == 'document':
            child_thumblink = self.document_file
          else:
            child_thumblink = child_row[7]
          t_engine_mapper_child['imagelink'] = child_row[6]
          t_engine_mapper_child['thumblink'] = child_thumblink
          t_engine_mapper_child['imagename'] = child_row[5]
        if child_row[8]:
          if child_row[8] != '':
            t_engine_mapper_child['signed'] = self.t_engine_signed.substitute(
              articlehash=article_hash[:10],
              pubkey=child_row[8],
              pubkey_short=self.generate_pubkey_short_utf_8(child_row[8])
            )
          else:
            t_engine_mapper_child['signed'] = ''
        else:
          t_engine_mapper_child['signed'] = ''
        
        if len(child_row[4].split('\n')) > 20:
          message = '\n'.join(child_row[4].split('\n')[:20]) + '\n[..] <a href="thread-%s.html#%s"><i>message too large</i></a>\n' % (root_message_id_hash[:10], article_hash[:10])
        elif len(child_row[4]) > 1000:
          message = child_row[4][:1000] + '\n[..] <a href="thread-%s.html#%s"><i>message too large</i></a>\n' % (root_message_id_hash[:10], article_hash[:10])
        else:
          message = child_row[4]
        message = self.linker.sub(self.linkit, message) 
        message = self.quoter.sub(self.quoteit, message)
        message = self.coder.sub(self.codeit, message)
        t_engine_mapper_child['articlehash'] = article_hash[:10]
        t_engine_mapper_child['articlehash_full'] = article_hash
        t_engine_mapper_child['author'] = child_row[1]
        t_engine_mapper_child['subject'] = child_row[2]
        t_engine_mapper_child['sent'] = datetime.utcfromtimestamp(child_row[3]).strftime('%d.%m.%Y (%a) %H:%M')
        t_engine_mapper_child['message'] = message
        if child_row[6] != '':
          childs.append(self.t_engine_message_pic.substitute(t_engine_mapper_child))
        else:
          childs.append(self.t_engine_message_nopic.substitute(t_engine_mapper_child))
      
      threads.append(
        self.t_engine_board_threads.substitute(
          message_root=self.t_engine_message_root.substitute(t_engine_mapper_root),
          message_childs=''.join(childs)
        )
      )
      del childs
    if thread_counter > 0 or (page_counter == 1 and thread_counter == 0):
      self.log(self.logger.INFO, 'generating %s/%s-%s.html' % (self.output_directory, board_name_unquoted, page_counter))
      t_engine_mapper_board = dict()
      t_engine_mapper_board['threads'] = ''.join(threads)
      pagelist = list()
      for page in xrange(1, pages + 1):
        if page != page_counter:
          pagelist.append('<a href="{0}-{1}.html">[{1}]</a>&nbsp;'.format(board_name_unquoted, page))
        else:
          pagelist.append('[{0}]&nbsp;'.format(page))
      t_engine_mapper_board['pagelist'] = ''.join(pagelist)
      t_engine_mapper_board['boardlist'] = boardlist
      t_engine_mapper_board['full_board'] = full_board_name_unquoted
      t_engine_mapper_board['board'] = board_name
      t_engine_mapper_board['target'] =  "{0}-1.html".format(board_name_unquoted)
      f = codecs.open(os.path.join(self.output_directory, '{0}-{1}.html'.format(board_name_unquoted, page_counter)), 'w', 'UTF-8')
      f.write(self.t_engine_board.substitute(t_engine_mapper_board))
      f.close()
      del pagelist
      del boardlist
      del threads

  def generate_thread(self, root_uid):
    t_engine_mappings_root = dict()
    root_message_id_hash = sha1(root_uid).hexdigest() #self.sqlite_hashes.execute('SELECT message_id_hash from article_hashes WHERE message_id = ?', (root_row[0],)).fetchone()
    # FIXME: benchmark sha1() vs hasher_db_query
            
    root_row = self.sqlite.execute('SELECT article_uid, sender, subject, sent, message, imagename, imagelink, thumblink, group_id, public_key FROM articles WHERE article_uid = ?', (root_uid,)).fetchone()    
    if not root_row:
      # FIXME: create temporary root post here? this will never get called on startup because it checks for root posts only
      # FIXME: ^ alternatives: wasted threads in admin panel? red border around images in pic log? actually adding temporary root post while processing?
      #root_row = (root_uid, 'none', 'root post not yet available', 0, 'root post not yet available', '', '', 0, '')
      self.log(self.logger.INFO, 'root post not yet available: %s, should create temporary root post here' % root_uid)
      return

    if self.sqlite.execute('SELECT group_id FROM groups WHERE group_id = ? AND blocked = 1', (root_row[8],)).fetchone():
      path = os.path.join(self.output_directory, 'thread-%s.html' % root_message_id_hash[:10])
      if os.path.isfile(path):
        self.log(self.logger.INFO, 'this thread belongs to some blocked board. deleting %s.' % path)
        try:
          os.unlink(path)
        except Exception as e:
          self.log(self.logger.ERROR, 'could not delete %s: %s' % (path, e))
      return

    self.log(self.logger.INFO, 'generating %s/thread-%s.html' % (self.output_directory, root_message_id_hash[:10]))
    if root_row[6] != '':
      root_imagelink = root_row[6]
      if root_row[7] == 'invalid':
        root_thumblink = self.invalid_file
      elif root_row[7] == 'document':
        root_thumblink = self.document_file
      else:
        root_thumblink = root_row[7]
    else:
      root_imagelink = self.no_file
      root_thumblink = self.no_file

    if root_row[9]:
      if root_row[9] != '':
        t_engine_mappings_root['signed'] = self.t_engine_signed.substitute(
          articlehash=root_message_id_hash[:10],
          pubkey=root_row[9],
          pubkey_short=self.generate_pubkey_short_utf_8(root_row[9])
        )
      else:
        t_engine_mappings_root['signed'] = ''
    else:
      t_engine_mappings_root['signed'] = ''
    message = self.linker.sub(self.linkit, root_row[4])
    message = self.quoter.sub(self.quoteit, message)
    message = self.coder.sub(self.codeit, message)
    t_engine_mappings_root['articlehash'] = root_message_id_hash[:10]
    t_engine_mappings_root['articlehash_full'] = root_message_id_hash
    t_engine_mappings_root['author'] = root_row[1]
    t_engine_mappings_root['subject'] = root_row[2]
    t_engine_mappings_root['sent'] = datetime.utcfromtimestamp(root_row[3]).strftime('%d.%m.%Y (%a) %H:%M')
    t_engine_mappings_root['imagelink'] = root_imagelink
    t_engine_mappings_root['thumblink'] = root_thumblink
    t_engine_mappings_root['imagename'] = root_row[5]
    t_engine_mappings_root['message'] = message
    childs = list()
    childs.append('') # FIXME: the fuck is this for?
    
    for child_row in self.sqlite.execute('SELECT article_uid, sender, subject, sent, message, imagename, imagelink, thumblink, public_key FROM articles WHERE parent = ? AND parent != article_uid ORDER BY sent ASC', (root_uid,)).fetchall():
      t_engine_mappings_child = dict()
      article_hash = sha1(child_row[0]).hexdigest()
      if child_row[6] != '':
        if child_row[7] == 'invalid':
          child_thumblink = self.invalid_file
        elif child_row[7] == 'document':
          child_thumblink = self.document_file
        else:
          child_thumblink = child_row[7]
        t_engine_mappings_child['imagelink'] = child_row[6]
        t_engine_mappings_child['thumblink'] = child_thumblink
        t_engine_mappings_child['imagename'] = child_row[5]
      if child_row[8]:
        if child_row[8] != '':
          t_engine_mappings_child['signed'] = self.t_engine_signed.substitute(
            articlehash=article_hash[:10],
            pubkey=child_row[8],
            pubkey_short=self.generate_pubkey_short_utf_8(child_row[8])
          )
        else:
          t_engine_mappings_child['signed'] = ''
      else:
        t_engine_mappings_child['signed'] = ''
      t_engine_mappings_child['articlehash'] = article_hash[:10]
      t_engine_mappings_child['articlehash_full'] = article_hash
      t_engine_mappings_child['author'] = child_row[1]
      t_engine_mappings_child['subject'] = child_row[2]
      t_engine_mappings_child['sent'] = datetime.utcfromtimestamp(child_row[3]).strftime('%d.%m.%Y (%a) %H:%M')
      message = self.linker.sub(self.linkit, child_row[4])
      message = self.quoter.sub(self.quoteit, message)
      message = self.coder.sub(self.codeit, message)      
      t_engine_mappings_child['message'] = message
      if child_row[6] != '':
        childs.append(self.t_engine_message_pic.substitute(t_engine_mappings_child))
      else:
        childs.append(self.t_engine_message_nopic.substitute(t_engine_mappings_child))
    t_engine_mappings_threads = dict()
    t_engine_mappings_threads['message_root'] = self.t_engine_message_root.substitute(t_engine_mappings_root)
    t_engine_mappings_threads['message_childs'] = ''.join(childs)
    boardlist = list()
    # FIXME hold this list somewhere global and update on board add/remove/block/unblock
    for group_row in self.sqlite.execute('SELECT group_name, group_id FROM groups WHERE blocked = 0 ORDER by group_name ASC').fetchall():
      current_group_name = group_row[0].split('.', 1)[1].replace('"', '').replace('/', '')
      current_group_name_encoded = self.basicHTMLencode(current_group_name)
      boardlist.append('&nbsp;<a href="%s-1.html">%s</a>&nbsp;|' % (current_group_name, current_group_name_encoded))
      if group_row[1] == root_row[8]:
        full_group_name_unquoted = group_row[0].replace('"', '').replace('/', '')
        full_group_name = self.basicHTMLencode(full_group_name_unquoted)
    boardlist[-1] = boardlist[-1][:-1]
    t_engine_mappings_thread_single = dict()
    t_engine_mappings_thread_single['boardlist'] = ''.join(boardlist)
    t_engine_mappings_thread_single['thread_id'] = root_message_id_hash
    t_engine_mappings_thread_single['board'] = full_group_name.split('.', 1)[1]
    t_engine_mappings_thread_single['full_board'] = full_group_name_unquoted
    t_engine_mappings_thread_single['target'] = "{0}-1.html".format(full_group_name.split('.', 1)[1])
    t_engine_mappings_thread_single['subject'] = root_row[2][:60]
    t_engine_mappings_thread_single['thread_single'] = self.t_engine_board_threads.substitute(t_engine_mappings_threads)

    f = codecs.open(os.path.join(self.output_directory, 'thread-{0}.html'.format(root_message_id_hash[:10])), 'w', 'UTF-8')
    f.write(self.t_engine_thread_single.substitute(t_engine_mappings_thread_single))
    f.close()
    #del childs
    #del boardlist
    
  def generate_overview(self):
    self.log(self.logger.INFO, 'generating %s/overview.html' % self.output_directory)
    t_engine_mappings_overview = dict()
    boardlist = list()
    news_uid = '<lwmueokaxt1389929084@web.overchan.sfor.ano>'
    # FIXME: cache this shit somewhere
    for group_row in self.sqlite.execute('SELECT group_name, group_id FROM groups WHERE blocked = 0 ORDER by group_name ASC').fetchall():
      current_group_name = group_row[0].split('.', 1)[1].replace('"', '').replace('/', '')
      current_group_name_encoded = self.basicHTMLencode(current_group_name)
      boardlist.append('&nbsp;<a href="%s-1.html">%s</a>&nbsp;|' % (current_group_name, current_group_name_encoded))
    boardlist[-1] = boardlist[-1][:-1]
    t_engine_mappings_overview['boardlist'] = ''.join(boardlist)
    row = self.sqlite.execute('SELECT subject, message, sent, public_key, parent, sender FROM articles WHERE article_uid = ?', (news_uid, )).fetchone()
    if not row:
      t_engine_mappings_overview['subject'] = ''
      t_engine_mappings_overview['sent'] = ''
      t_engine_mappings_overview['author'] = ''
      t_engine_mappings_overview['pubkey_short'] = ''
      t_engine_mappings_overview['pubkey'] = ''
      t_engine_mappings_overview['postid'] = ''
      t_engine_mappings_overview['parent'] = 'does_not_exist_yet'
      t_engine_mappings_overview['message'] = 'once upon a time there was a news post'
    else:
      postid = sha1(news_uid).hexdigest()[:10]
      if row[4] == '' or row[4] == news_uid:
        parent = postid
      else:
        parent = sha1(row[4]).hexdigest()[:10]
      if len(row[1].split('\n')) > 5:
        message = '\n'.join(row[1].split('\n')[:5]) + '\n[..] <a href="thread-%s.html#%s"><i>message too large</i></a>\n' % (parent, postid)
      elif len(row[1]) > 1000:
        message = row[1][:1000] + '\n[..] <a href="thread-%s.html#%s"><i>message too large</i></a>\n' % (parent, postid)
      else:
        message = row[1]
      t_engine_mappings_overview['subject'] = row[0]
      t_engine_mappings_overview['sent'] = datetime.utcfromtimestamp(row[2]).strftime('%d.%m.%Y (%a) %H:%M')
      t_engine_mappings_overview['author'] = row[5]
      if not row[3] == '':
          t_engine_mappings_overview['pubkey_short'] = self.generate_pubkey_short_utf_8(row[3])
      else:
          t_engine_mappings_overview['pubkey_short'] = ''
      t_engine_mappings_overview['pubkey'] = row[3]
      t_engine_mappings_overview['postid'] = postid
      t_engine_mappings_overview['parent'] = parent
      t_engine_mappings_overview['message'] = message
    
    weekdays = ('Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday')
    max = 0
    stats = list()
    bar_length = 20
    days = 21
    totals = int(self.sqlite.execute('SELECT count(1) FROM articles WHERE sent > strftime("%s", "now", "-' + str(days) + ' days")').fetchone()[0])
    stats.append(self.template_stats_usage_row.replace('%%postcount%%', str(totals)).replace('%%date%%', 'all posts').replace('%%weekday%%', '').replace('%%bar%%', 'since %s days' % days))
    for row in self.sqlite.execute('SELECT count(1) as counter, strftime("%Y-%m-%d",  sent, "unixepoch") as day, strftime("%w", sent, "unixepoch") as weekday FROM articles WHERE sent > strftime("%s", "now", "-' + str(days) + ' days") GROUP BY day ORDER BY day DESC').fetchall():
      if row[0] > max:
        max = row[0]
      stats.append((row[0], row[1], weekdays[int(row[2])]))
    for index in range(1, len(stats)):
      graph = ''
      for x in range(0, int(float(stats[index][0])/max*bar_length)):
        graph += '='
      if len(graph) == 0:
        graph = '&nbsp;'
      stats[index] = self.template_stats_usage_row.replace('%%postcount%%', str(stats[index][0])).replace('%%date%%', stats[index][1]).replace('%%weekday%%', stats[index][2]).replace('%%bar%%', graph)
    overview_stats_usage = self.template_stats_usage
    overview_stats_usage = overview_stats_usage.replace('%%stats_usage_rows%%', ''.join(stats))
    t_engine_mappings_overview['stats_usage'] = overview_stats_usage
    del stats[:]

    postcount = 23
    for row in self.sqlite.execute('SELECT sent, group_name, sender, subject, article_uid, parent FROM articles, groups WHERE groups.blocked = 0 AND articles.group_id = groups.group_id ORDER BY sent DESC LIMIT ' + str(postcount)).fetchall():
      sent = datetime.utcfromtimestamp(row[0]).strftime('%d.%m.%Y (%a) %H:%M UTC')
      board = self.basicHTMLencode(row[1].replace('"', '')).split('.', 1)[1]
      author = row[2]
      articlehash = sha1(row[4]).hexdigest()[:10]
      if row[5] == '' or row[5] == row[4]:
        # root post
        subject = row[3]
        parent = articlehash
      else:
        parent = sha1(row[5]).hexdigest()[:10]
        try:
          subject = self.sqlite.execute('SELECT subject FROM articles WHERE article_uid = ?', (row[5],)).fetchone()[0] 
        except:
          subject = 'root post not yet available'
      if len(subject) > 60:
        subject = subject[:60] + ' [..]'
      if len(author) > 20:
        author = author[:20] + ' [..]'
      stats.append(self.template_latest_posts_row.replace('%%sent%%', sent).replace('%%board%%', board).replace('%%parent%%', parent).replace('%%articlehash%%', articlehash).replace('%%author%%', author).replace('%%subject%%', subject))
    #for row in self.sqlite.execute('SELECT articles.last_update, group_name, sender, subject, article_uid FROM articles, groups WHERE (parent = "" or parent = article_uid) AND articles.group_id = groups.group_id ORDER BY articles.last_update DESC LIMIT ' + str(postcount)).fetchall():
    #  last_update = datetime.utcfromtimestamp(row[0]).strftime('%d.%m.%Y (%a) %H:%M UTC')
    #  board = self.basicHTMLencode(row[1].replace('"', '')).split('.', 1)[1]
    #  subject = row[3]
    #  parent = sha1(row[4]).hexdigest()[:10]
    #  try:
    #    childrow = self.sqlite.execute('SELECT sender, article_uid FROM articles WHERE parent = ? ORDER BY sent DESC LIMIT 1', (row[4],)).fetchone()
    #    articlehash = sha1(childrow[1]).hexdigest()[:10]
    #    author = childrow[0]
    #  except:
    #    articlehash = parent
    #    author = row[2]
    #  stats.append(self.template_latest_posts_row.replace('%%sent%%', last_update).replace('%%board%%', board).replace('%%parent%%', parent).replace('%%articlehash%%', articlehash).replace('%%author%%', author).replace('%%subject%%', subject))
    overview_latest_posts = self.template_latest_posts
    overview_latest_posts = overview_latest_posts.replace('%%latest_posts_rows%%', ''.join(stats))
    t_engine_mappings_overview['latest_posts'] = overview_latest_posts
    del stats[:]

    for row in self.sqlite.execute('SELECT count(1) as counter, group_name FROM articles, groups WHERE groups.blocked = 0 AND articles.group_id = groups.group_id GROUP BY articles.group_id ORDER BY counter DESC').fetchall():
      stats.append(self.template_stats_boards_row.replace('%%postcount%%', str(row[0])).replace('%%board%%', self.basicHTMLencode(row[1])))
    overview_stats_boards = self.template_stats_boards
    overview_stats_boards = overview_stats_boards.replace('%%stats_boards_rows%%', ''.join(stats))
    t_engine_mappings_overview['stats_boards'] = overview_stats_boards
    
    f = codecs.open(os.path.join(self.output_directory, 'overview.html'), 'w', 'UTF-8')
    f.write(self.t_engine_overview.substitute(t_engine_mappings_overview))
    f.close()

if __name__ == '__main__':
  # FIXME fix this shit
  overchan = main('overchan', args)
  while True:
    try:
      print "signal.pause()"
      signal.pause()
    except KeyboardInterrupt as e:
      print
      self.sqlite_conn.close()
      self.log('bye', 2)
      exit(0)
    except Exception as e:
      print "Exception:", e  
      self.sqlite_conn.close()
      self.log('bye', 2)
      exit(0)
