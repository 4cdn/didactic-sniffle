#!/usr/bin/python
from datetime import datetime
import threading
import string
import Queue
import time
import sys

loglevel_all = (0, 1, 2, 3, 4, 5)
loglevel_names = (
  'VERBOSE',
  'DEBUG',
  'INFO',
  'WARNING',
  'ERROR',
  'CRITICAL'
)
loglevel_names_nice = (
  '%8s' % 'VERBOSE',
  '%8s' % 'DEBUG',
  '\x1b[32m%8s\x1b[m' % 'INFO',
  '\x1b[33m%8s\x1b[m' % 'WARNING',
  '\x1b[31m%8s\x1b[m' % 'ERROR',
  '\x1b[31m\x1b[01m%8s\x1b[m' % 'CRITICAL'
)
target_mapper = {
  'stdout': sys.stdout,
  'stderr': sys.stderr
}

class logger(threading.Thread):

  def log(self, source, message, loglevel):
    if not self.shut_down:
      self.queue.put((source, message, loglevel))
      return
    for line in ('%s' % message).split('\n'):
      if len(line) == 0: continue
      line = 'logger on its way to shut down but got another message: %s' % line
      for target in self.targets:
        if loglevel in target[1]:
          date = datetime.utcfromtimestamp(time.time()).strftime(target[3])
          target[0].write(target[2].substitute(date=date, loglevel=loglevel_names_nice[loglevel], source=source, message=line))
        target[0].flush()

  def __init__(self, log_targets=None):
    threading.Thread.__init__(self)
    self.queue = Queue.Queue()
    self.running = False
    self.VERBOSE =  0
    self.DEBUG =    1
    self.INFO =     2
    self.WARNING =  3
    self.ERROR =    4
    self.CRITICAL = 5
    self.level = {
      'VERBOSE':  self.VERBOSE,
      'DEBUG':    self.DEBUG,
      'INFO':     self.INFO,
      'WARNING':  self.WARNING,
      'ERROR':    self.ERROR,
      'CRITICAL': self.CRITICAL,
      'WARN':     self.WARNING,
      'ERR':      self.ERROR,
      'CRIT':     self.CRITICAL
    }
    self.generate_targets(log_targets)
    self.shut_down = False

  def generate_targets(self, targets):
    self.targets = list()
    for target in targets:
      # configure target
      if not 'target' in target:
        target_target = sys.stdout
      elif target['target'] in target_mapper:
        target_target = target_mapper[target['target']]
      else:
        target_target = open(target['target'], 'a')
      #configure loglevels
      if not 'loglevel' in target:
        target_loglevels = loglevel_all
      else:
        target_loglevels = list()
        for loglevel in target['loglevel']:
          if loglevel == 'all':
            target_loglevels = loglevel_all
            break
          if loglevel.upper() in self.level: 
            target_loglevels.append(self.level[loglevel.upper()])
          else:
            sys.stderr.write('unknown loglevel: \'%s\'\n' % loglevel)
      # TODO: implement source filters
      # configure format
      if not 'format' in target:
        target_format = string.Template('${date} ${loglevel} ${source} ${message}\n')
      else:
        target_format = string.Template(target['format'])
      # configure date format
      if not 'date_fmt' in target:
        target_date_fmt = '%m/%d %H:%M:%S'
      else:
        target_date_fmt = target['date_fmt']
      self.targets.append((target_target, target_loglevels, target_format, target_date_fmt))
    
  def run(self):
    for target in self.targets:
      date = datetime.utcfromtimestamp(time.time()).strftime(target[3])
      if target == 'stderr':
          lgn = loglevel_names_nice
      else:
          lgn = loglevel_names
      target[0].write(target[2].substitute(date=date, loglevel=lgn[self.INFO], source='logger', message='starting up'))
      target[0].flush()
    self.running = True
    while True:
      try:
        source, message, loglevel = self.queue.get(block=True, timeout=5)
        for line in ('%s' % message).split('\n'):
          if len(line) == 0: continue
          for target in self.targets:
            if loglevel in target[1]:
              date = datetime.utcfromtimestamp(time.time()).strftime(target[3])
              target[0].write(target[2].substitute(date=date, loglevel=lgn[loglevel], source=source, message=line))
            target[0].flush()
      except Queue.Empty:
        if not self.running:
          self.shut_down = True
          break
    for target in self.targets:
      date = datetime.utcfromtimestamp(time.time()).strftime(target[3])
      target[0].write(target[2].substitute(date=date, loglevel=lgn[self.INFO], source='logger', message='closing down'))
      target[0].flush()

if __name__ == '__main__':
  print "can't run as standalone"
  exit(1)
