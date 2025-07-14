import itertools
import sys
import threading
import time

def spinner_inline(msg="🔄", delay=0.1):
    stop_event = threading.Event()

    def spin():
        for c in itertools.cycle('|/-\\'):
            if stop_event.is_set():
                break
            sys.stdout.write(f'\r{msg} {c}')
            sys.stdout.flush()
            time.sleep(delay)
        sys.stdout.write('\r' + ' ' * (len(msg) + 2) + '\r')
        sys.stdout.flush()

    thread = threading.Thread(target=spin, daemon=True)
    thread.start()
    return stop_event.set