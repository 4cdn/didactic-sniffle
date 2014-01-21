#!/usr/bin/python
import time
import signal
import os
import threading
import platform

import SRNd

if platform.system().lower() == 'linux':
  print "[SRNd] linux detected, using F_NOTIFY"
  import fcntl
  bsd = False
elif platform.system().lower().endswith('bsd'):
  print "[SRNd] *BSD detected: %s, using select.kqueue()" % platform.system()
  import select
  try:
    queue = select.kqueue()
    bsd = True
  except Exception as e:
    print "[SRNd] could not load BSD kqueue: %s" % e
    exit(1)
else:
  print "[SRNd] unsupported platform: '%s'" % platform.system()
  exit(1)

srnd = SRNd.SRNd()
fd = os.open(srnd.watching(), os.O_RDONLY | os.O_NONBLOCK)

if bsd:
  watching = (select.kevent(fd, filter=select.KQ_FILTER_VNODE, flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_CLEAR, fflags=select.KQ_NOTE_WRITE),)
else:
  signal.signal(signal.SIGIO, srnd.dropper.handler_progress_incoming)
  fcntl.fcntl(fd, fcntl.F_SETSIG, 0)
  fcntl.fcntl(fd, fcntl.F_NOTIFY, fcntl.DN_MODIFY | fcntl.DN_CREATE | fcntl.DN_MULTISHOT)

signal.signal(signal.SIGHUP, srnd.update_hooks_outfeeds_plugins)
srnd.start()
# TODO initialize with calling srnd.dropper.hanler_progress_incoming(None, None), best suited in SRNd run() itself.
while True:
  try:
    if bsd:
      print "[SRNd] reading events.."
      print "[SRNd] got events: '%s'" % str(queue.control(watching, 1, None))
      srnd.dropper.handler_progress_incoming(None, None)
    else:
      time.sleep(3600)
  except KeyboardInterrupt:
    print
    print "[SRNd] shutting down.."
    srnd.shutdown()
    for thread in threading.enumerate():
      #print "joining ", thread
      try:
        thread.join()
      except RuntimeError as e:
        pass
    print "[SRNd] bye"
    exit(0)
